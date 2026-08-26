using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record RemoteContact(string Id, string ETag, long Modified, JsonObject Data, bool Owned);

internal sealed record ContactSyncCounts(int Imported, int Exported, int Updated, int Deleted, int Errors)
{
    internal string Report(string name) =>
        $"{name}: {Imported} importiert, {Exported} exportiert, {Updated} aktualisiert, {Deleted} gelöscht" +
        (Errors > 0 ? $", {Errors} Fehler." : ".");
}

internal sealed record ContactSyncResult(JsonArray Contacts, JsonArray Tombstones, ContactSyncCounts Counts);

internal interface IContactRemote
{
    Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken);
    Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken);
    Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken);
    Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken);
}

internal static class ContactFields
{
    internal static readonly string[] Names =
    {
        "nachname", "vorname", "firma", "strasse", "plz", "ort", "land", "telefon", "mobil",
        "telefone", "email", "emails", "emailEintraege", "anschriften", "geburtstag",
        "geburtstagJahrUnbekannt", "notiz", "foto", "kontaktpersonName", "kontaktpersonTelefon",
        "kontaktpersonStatus", "kontaktpersonen", "sozialeMedien", "vcardRoundtrip"
    };

    internal static JsonObject CopyRemoteFields(JsonObject target, JsonObject source)
    {
        foreach (var name in Names)
            if (name != "geburtstag" || source.ContainsKey(name)) target[name] = source[name]?.DeepClone();
        return target;
    }

    internal static string Text(JsonObject value, string name) => value[name]?.GetValue<string>()?.Trim() ?? "";

    internal static JsonObject? Source(JsonObject value, string source)
    {
        return value["syncQuellen"] is JsonObject all && all[source] is JsonObject item ? item : null;
    }

    internal static void SetSource(JsonObject value, string source, RemoteContact remote)
    {
        var all = value["syncQuellen"] as JsonObject ?? new JsonObject();
        value["syncQuellen"] = all;
        all[source] = new JsonObject
        {
            ["id"] = remote.Id, ["etag"] = remote.ETag, ["geaendert"] = remote.Modified,
            ["eigen"] = remote.Owned
        };
        value["sync"] = true;
    }
}

internal sealed class ContactSyncEngine
{
    internal async Task<ContactSyncResult> SyncAsync(string source, JsonArray contacts, JsonArray tombstones,
        long lastSync, IContactRemote remoteStore, CancellationToken cancellationToken = default,
        bool additiveOnly = false)
    {
        var local = new JsonArray(contacts.Select(item => item?.DeepClone()).ToArray());
        var dead = new JsonArray(tombstones.Select(item => item?.DeepClone()).ToArray());
        var remote = await remoteStore.ReadAsync(cancellationToken).ConfigureAwait(false);
        var remoteById = remote.GroupBy(item => item.Id, StringComparer.Ordinal)
            .Where(group => group.Count() == 1).ToDictionary(group => group.Key, group => group.Single(), StringComparer.Ordinal);
        var mappedIds = local.OfType<JsonObject>().Select(item => ContactFields.Source(item, source)?["id"]?.GetValue<string>())
            .Where(id => !string.IsNullOrWhiteSpace(id)).GroupBy(id => id!, StringComparer.Ordinal)
            .Where(group => group.Count() == 1).ToDictionary(group => group.Key, _ => true, StringComparer.Ordinal);
        var imported = 0; var exported = 0; var updated = 0; var deleted = 0; var errors = 0;

        foreach (var item in local.OfType<JsonObject>().ToArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var uid = ContactFields.Text(item, "uid");
            if (uid.Length == 0) { uid = $"mag-{Guid.NewGuid():N}@magnolie-organizer"; item["uid"] = uid; }
            var mapping = ContactFields.Source(item, source);
            var remoteId = mapping?["id"]?.GetValue<string>() ?? "";
            if (remoteId.Length > 0 && mappedIds.ContainsKey(remoteId))
            {
                if (!remoteById.Remove(remoteId, out var other))
                {
                    if (!additiveOnly && (item["geaendert"]?.GetValue<long>() ?? 0) <= lastSync) { local.Remove(item); deleted++; continue; }
                    try { var made = await remoteStore.CreateAsync(uid, item, cancellationToken); ContactFields.SetSource(item, source, made); exported++; }
                    catch { errors++; }
                    continue;
                }
                var localTime = item["geaendert"]?.GetValue<long>() ?? 0;
                var remoteChanged = mapping?["etag"]?.GetValue<string>() is string priorEtag && priorEtag != other.ETag;
                var localChanged = localTime > lastSync;
                if (other.Modified > localTime)
                {
                    ContactFields.CopyRemoteFields(item, other.Data); item["geaendert"] = other.Modified;
                    ContactFields.SetSource(item, source, other); updated++;
                }
                else if (localTime > other.Modified)
                {
                    try { var changed = await remoteStore.UpdateAsync(other, uid, item, cancellationToken); ContactFields.SetSource(item, source, changed); updated++; }
                    catch { errors++; }
                }
                else if (remoteChanged && localChanged)
                {
                    var conflict = other.Data.DeepClone().AsObject();
                    conflict["id"] = Guid.NewGuid().ToString("N");
                    conflict["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
                    conflict["geaendert"] = Math.Max(other.Modified, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    ContactFields.SetSource(conflict, source, other);
                    local.Add(conflict); updated++; errors++;
                }
                else if (remoteChanged)
                {
                    ContactFields.CopyRemoteFields(item, other.Data); item["geaendert"] = other.Modified;
                    ContactFields.SetSource(item, source, other); updated++;
                }
                else ContactFields.SetSource(item, source, other);
                continue;
            }
            try { var made = await remoteStore.CreateAsync(uid, item, cancellationToken); ContactFields.SetSource(item, source, made); exported++; }
            catch { errors++; }
        }

        if (!additiveOnly && errors == 0)
            foreach (var tombstone in dead.OfType<JsonObject>().ToArray())
            {
                var mapping = ContactFields.Source(tombstone, source);
                var id = mapping?["id"]?.GetValue<string>() ?? "";
                var other = id.Length > 0 ? remote.FirstOrDefault(item => item.Id == id) : null;
                if (other is null) continue;
                remoteById.Remove(id);
                try { await remoteStore.DeleteAsync(other, ContactFields.Text(tombstone, "uid"), cancellationToken); dead.Remove(tombstone); deleted++; }
                catch { errors++; break; }
            }

        foreach (var other in remoteById.Values)
        {
            var item = other.Data.DeepClone().AsObject();
            item["id"] = Guid.NewGuid().ToString("N");
            if (ContactFields.Text(item, "uid").Length == 0)
                item["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
            item["geaendert"] = other.Modified;
            ContactFields.SetSource(item, source, other);
            local.Add(item); imported++;
        }

        return new ContactSyncResult(local, dead, new ContactSyncCounts(imported, exported, updated, deleted, errors));
    }
}
