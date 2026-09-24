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
    bool SupportsYearlessBirthdays => true;
    Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken);
    Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken);
    Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken);
    Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken);
}

internal static class ContactFields
{
    internal static bool NormalizeBirthday(JsonObject contact)
    {
        // Some contact providers use the leap year 1604 when only month/day
        // are known. This is a birthday rule, not a general date conversion.
        var value = Text(contact, "geburtstag");
        if (!ExchangeCodec.TryParseCanonicalDate(value, out var date, out _, out _) || date is null ||
            (date.Value.Year != 1604 && contact["geburtstagJahrUnbekannt"]?.GetValue<bool>() != true)) return false;
        contact["geburtstag"] = "--" + value[5..];
        contact["geburtstagJahrUnbekannt"] = true;
        return true;
    }

    internal static readonly string[] Names =
    {
        "nachname", "vorname", "anzeigename", "firma", "strasse", "plz", "ort", "land", "telefon", "mobil",
        "telefone", "email", "emails", "emailEintraege", "anschriften", "geburtstag",
        "geburtstagJahrUnbekannt", "jubilaeum", "jubilaeumJahrUnbekannt", "notiz", "foto", "kontaktpersonName", "kontaktpersonTelefon",
        "kontaktpersonStatus", "kontaktpersonen", "sozialeMedien", "vcardRoundtrip"
    };

    internal static JsonObject CopyRemoteFields(JsonObject target, JsonObject source, string provider = "")
    {
        foreach (var name in Names)
        {
            if (provider is "windows-contacts" or "microsoft-graph")
            {
                if (name is "foto" or "emailEintraege" or "kontaktpersonName" or "kontaktpersonTelefon" or
                    "kontaktpersonStatus" or "kontaktpersonen" or "sozialeMedien" or "vcardRoundtrip") continue;
                if (provider == "microsoft-graph" && name is "anzeigename" or "jubilaeum" or "jubilaeumJahrUnbekannt") continue;
            }
            var dateField = name switch { "geburtstagJahrUnbekannt" => "geburtstag", "jubilaeumJahrUnbekannt" => "jubilaeum", _ => name };
            if (dateField is "geburtstag" or "jubilaeum" && Text(source, dateField).Length == 0 && Text(target, dateField).Length > 0) continue;
            if (name == "anzeigename" && !source.ContainsKey(name)) continue;
            target[name] = source[name]?.DeepClone();
        }
        NormalizeBirthday(target);
        return target;
    }

    internal static string Text(JsonObject value, string name) => value[name]?.GetValue<string>()?.Trim() ?? "";

    internal static JsonObject? Source(JsonObject value, string source)
    {
        return value["syncQuellen"] is JsonObject all && all[source] is JsonObject item ? item : null;
    }

    internal static void SetSource(JsonObject value, string source, RemoteContact remote, bool remoteBaseline = false)
    {
        var baseline = remoteBaseline ? remote.Data : value;
        if (remoteBaseline && source is "windows-contacts" or "microsoft-graph")
            baseline = CopyRemoteFields(value.DeepClone().AsObject(), remote.Data, source);
        var all = value["syncQuellen"] as JsonObject ?? new JsonObject();
        value["syncQuellen"] = all;
        all[source] = new JsonObject
        {
            ["id"] = remote.Id, ["etag"] = remote.ETag, ["geaendert"] = remote.Modified,
            ["eigen"] = remote.Owned,
            ["inhaltFormat"] = "windows-1",
            ["inhaltSha256"] = SyncBaseline.Hash(baseline, Names)
        };
        value["sync"] = true;
    }
}

internal static class SyncBaseline
{
    internal static string Hash(JsonObject value, IEnumerable<string> fields)
    {
        var projection = new JsonObject();
        foreach (var field in fields)
        {
            var node = value[field];
            // The frontend materializes empty/default fields when saving imported records.
            if (node is null || node.ToJsonString() is "\"\"" or "[]" or "{}" or "false" or "0") continue;
            projection[field] = node.DeepClone();
        }
        return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
            MagnolienbaumCrypto.Canonical(projection))).ToLowerInvariant();
    }

    internal static bool Dirty(JsonObject value, JsonObject? mapping, IEnumerable<string> fields,
        JsonObject? unchangedRemote = null)
    {
        var hash = Hash(value, fields);
        if (mapping?["inhaltFormat"]?.GetValue<string>() == "windows-1" &&
            mapping["inhaltSha256"] is JsonValue baseline && baseline.TryGetValue<string>(out var saved))
            return saved != hash;
        // Shipped mappings have no content baseline. Only an unchanged remote
        // revision can establish one without hiding an unsynchronized local edit.
        return unchangedRemote is null || hash != Hash(unchangedRemote, fields);
    }

    internal static void RequireDeletionRevision(JsonObject? mapping, string etag)
    {
        if (string.IsNullOrWhiteSpace(etag) || mapping?["etag"]?.GetValue<string>() != etag)
            throw new InvalidOperationException("Das DAV-Objekt wurde gleichzeitig geändert.");
    }

    internal static bool ContainsSavedResult(JsonObject result, JsonObject saved)
    {
        if (result["syncEpoch"] is not null && !JsonNode.DeepEquals(result["syncEpoch"], saved["syncEpoch"])) return false;
        if (result["syncAbgleichBasis"] is JsonObject basis && saved["syncAbgleichNachweis"] is JsonObject current)
        {
            if (!JsonNode.DeepEquals(result["transactionId"], current["transactionId"])) return false;
            result = result.DeepClone().AsObject();
            foreach (var field in new[] { "termine", "aufgaben", "kontakte", "jahrestage" })
            {
                if (basis[field] is not JsonArray before || current[field] is not JsonArray local || result[field] is not JsonArray remote) return false;
                result[field] = Reconcile(before, local, remote);
            }
            foreach (var field in new[] { "termine", "aufgaben", "kontakte" })
            {
                if (basis["geloescht"]?[field] is not JsonArray before || current["geloescht"]?[field] is not JsonArray local || result["geloescht"]?[field] is not JsonArray remote) return false;
                result["geloescht"]![field] = Reconcile(before, local, remote);
            }
        }
        static bool Contains(JsonNode? expected, JsonNode? actual)
        {
            // Accept frontend defaults and redundant DAV/ICS fields, not missing domain content or mappings.
            if (expected is JsonObject obj) return actual is JsonObject other && obj.All(pair =>
                other.ContainsKey(pair.Key) ? Contains(pair.Value, other[pair.Key]) :
                pair.Value is null || pair.Value.ToJsonString() is "\"\"" or "[]" or "{}" or "false" or "0" ||
                (pair.Key is "davHref" or "davEtag") && obj["syncQuellen"] is JsonObject ||
                pair.Key == "icsStatus" && obj["icsRoundtrip"] is JsonArray ||
                obj.ContainsKey("art") && (pair.Key == "rruleForm" || pair.Key == "intervall" && pair.Value.ToJsonString() == "1"));
            if (expected is JsonArray array) return actual is JsonArray otherArray && array.Count == otherArray.Count &&
                array.Zip(otherArray).All(pair => Contains(pair.First, pair.Second));
            return JsonNode.DeepEquals(expected, actual);
        }
        return new[] { "termine", "aufgaben", "kontakte", "jahrestage", "geloescht", "letzterSync", "letzteSyncs", "syncMetadaten" }
            .All(field => result.ContainsKey(field) && saved.ContainsKey(field) && Contains(result[field], saved[field]));
    }

    private static JsonArray Reconcile(JsonArray baseline, JsonArray current, JsonArray remote)
    {
        static string Key(JsonObject item) => ContactFields.Text(item, "uid") is { Length: > 0 } uid ? uid : ContactFields.Text(item, "id");
        var before = baseline.OfType<JsonObject>().ToDictionary(Key, StringComparer.Ordinal);
        var local = current.OfType<JsonObject>().ToDictionary(Key, StringComparer.Ordinal);
        var result = new JsonArray();
        foreach (var item in remote.OfType<JsonObject>())
        {
            var key = Key(item); before.TryGetValue(key, out var original); local.Remove(key, out var now);
            if (original is not null && now is null) continue;
            var merged = item.DeepClone().AsObject();
            if (now is not null && !JsonNode.DeepEquals(original, now))
                foreach (var field in (original?.Select(pair => pair.Key) ?? []).Concat(now.Select(pair => pair.Key)).Distinct())
                {
                    if (JsonNode.DeepEquals(original?[field], now[field])) continue;
                    if (now.ContainsKey(field)) merged[field] = now[field]?.DeepClone();
                    else merged.Remove(field);
                }
            result.Add(merged);
        }
        foreach (var (key, item) in local)
            if (!JsonNode.DeepEquals(before.GetValueOrDefault(key), item)) result.Add(item.DeepClone());
        return result;
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
        var received = await remoteStore.ReadAsync(cancellationToken).ConfigureAwait(false);
        var birthdayRepairs = new HashSet<string>(StringComparer.Ordinal);
        // Remember the uncorrected wire state separately: a normalized content
        // baseline must not hide a repair still owed to the remote source.
        var remote = received.Select(item =>
        {
            var data = item.Data.DeepClone().AsObject();
            if (ContactFields.NormalizeBirthday(data) && remoteStore.SupportsYearlessBirthdays) birthdayRepairs.Add(item.Id);
            return item with { Data = data };
        }).ToArray();
        foreach (var item in local.OfType<JsonObject>()) ContactFields.NormalizeBirthday(item);
        if (remote.Any(item => string.IsNullOrWhiteSpace(item.Id)) || remote.Select(item => item.Id).Distinct(StringComparer.Ordinal).Count() != remote.Length)
            throw new InvalidDataException(NativeLocalization.Gettext("The Nextcloud response was incomplete."));
        var remoteById = remote.ToDictionary(item => item.Id, StringComparer.Ordinal);
        if (!additiveOnly && NextcloudDavSelection.IsAddressBook(source))
            foreach (var tombstone in dead.OfType<JsonObject>())
            {
                var mapping = ContactFields.Source(tombstone, source);
                if (mapping?["id"]?.GetValue<string>() is string id && remoteById.TryGetValue(id, out var other))
                    SyncBaseline.RequireDeletionRevision(mapping, other.ETag);
            }
        var mappedIds = local.OfType<JsonObject>().Select(item => ContactFields.Source(item, source)?["id"]?.GetValue<string>())
            .Where(id => !string.IsNullOrWhiteSpace(id)).GroupBy(id => id!, StringComparer.Ordinal)
            .Where(group => group.Count() == 1).ToDictionary(group => group.Key, _ => true, StringComparer.Ordinal);
        var reservedIds = local.Concat(dead).OfType<JsonObject>()
            .Select(item => ContactFields.Source(item, source)?["id"]?.GetValue<string>())
            .Where(id => !string.IsNullOrWhiteSpace(id)).ToHashSet(StringComparer.Ordinal);
        var sameContent = remote.GroupBy(item => SyncBaseline.Hash(item.Data, ContactFields.Names), StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.Ordinal);
        var imported = 0; var exported = 0; var updated = 0; var deleted = 0; var errors = 0;

        foreach (var item in local.OfType<JsonObject>().ToArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var uid = ContactFields.Text(item, "uid");
            if (uid.Length == 0) { uid = $"mag-{Guid.NewGuid():N}@magnolie-organizer"; item["uid"] = uid; }
            var mapping = ContactFields.Source(item, source);
            var remoteId = mapping?["id"]?.GetValue<string>() ?? "";
            if (remoteId.Length == 0 && sameContent.TryGetValue(SyncBaseline.Hash(item, ContactFields.Names), out var equal))
            {
                // A different provider UID does not make otherwise identical
                // contact data a new person. Names alone remain ambiguous.
                var hasContactDetails = new[] { "email", "telefon", "mobil" }.Any(field => ContactFields.Text(item, field).Length > 0) ||
                    new[] { "emails", "emailEintraege", "telefone" }.Any(field => item[field] is JsonArray entries && entries.Any(entry =>
                        entry is JsonValue text && text.TryGetValue<string>(out var value) && !string.IsNullOrWhiteSpace(value) ||
                        entry is JsonObject detail && ContactFields.Text(detail, "wert").Length > 0));
                var available = equal.Where(other => remoteById.ContainsKey(other.Id) && !reservedIds.Contains(other.Id)).ToArray();
                var sameUid = available.Where(other => ContactFields.Text(other.Data, "uid") == uid).Take(2).ToArray();
                // Windows .contact deletion ownership is tied to its embedded
                // Magnolie UID; do not infer a different identity there.
                var candidates = sameUid.Length > 0 ? sameUid : source != "windows-contacts" && hasContactDetails ? available.Take(2).ToArray() : [];
                if (candidates.Length == 1)
                {
                    var same = candidates[0];
                    ContactFields.SetSource(item, source, same);
                    mapping = ContactFields.Source(item, source); remoteId = same.Id;
                    mappedIds[remoteId] = true; reservedIds.Add(remoteId);
                }
            }
            if (additiveOnly && remoteId.Length == 0)
            {
                var matches = remoteById.Values.Where(value => ContactFields.Text(value.Data, "uid") == uid).ToArray();
                if (matches.Length == 1)
                {
                    var other = matches[0]; remoteById.Remove(other.Id);
                    if (other.Modified > (item["geaendert"]?.GetValue<long>() ?? 0))
                    {
                        ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    }
                    ContactFields.SetSource(item, source, other, remoteBaseline: true);
                }
                continue;
            }
            if (remoteId.Length > 0 && mappedIds.ContainsKey(remoteId))
            {
                if (!remoteById.Remove(remoteId, out var other))
                {
                    if (additiveOnly) { if (mapping is not null) mapping["inhaltSha256"] = ""; continue; }
                    if (!SyncBaseline.Dirty(item, mapping, ContactFields.Names)) { local.Remove(item); deleted++; continue; }
                    try { var made = await remoteStore.CreateAsync(uid, item, cancellationToken); ContactFields.SetSource(item, source, made); exported++; }
                    catch { errors++; }
                    continue;
                }
                var localTime = item["geaendert"]?.GetValue<long>() ?? 0;
                var priorEtag = mapping?["etag"]?.GetValue<string>() ?? "";
                var remoteChanged = priorEtag.Length > 0 || other.ETag.Length > 0
                    ? priorEtag != other.ETag : (mapping?["geaendert"]?.GetValue<long>() ?? lastSync) != other.Modified;
                var localChanged = SyncBaseline.Dirty(item, mapping, ContactFields.Names, remoteChanged ? null : other.Data);
                var conflictingChanges = remoteChanged && localChanged &&
                    SyncBaseline.Hash(item, ContactFields.Names) != SyncBaseline.Hash(other.Data, ContactFields.Names);
                var repairBirthday = birthdayRepairs.Contains(other.Id) ||
                    ContactFields.Text(item, "geburtstag").Length > 0 && ContactFields.Text(other.Data, "geburtstag").Length == 0 &&
                    (remoteStore.SupportsYearlessBirthdays || !ContactFields.Text(item, "geburtstag").StartsWith("--", StringComparison.Ordinal));
                var wroteRemote = false;
                if (additiveOnly)
                {
                    if (other.Modified > localTime)
                    {
                        ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    }
                    ContactFields.SetSource(item, source, other, remoteBaseline: true);
                }
                else if (conflictingChanges)
                {
                    var conflict = item.DeepClone().AsObject();
                    conflict["id"] = Guid.NewGuid().ToString("N");
                    conflict["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
                    conflict.Remove("syncQuellen"); conflict["sync"] = false;
                    local.Add(conflict);
                    ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    ContactFields.SetSource(item, source, other); updated++;
                }
                else if (remoteChanged)
                {
                    ContactFields.CopyRemoteFields(item, other.Data, source); item["geaendert"] = other.Modified;
                    ContactFields.SetSource(item, source, other); updated++;
                }
                else if (localChanged)
                {
                    try { var changed = await remoteStore.UpdateAsync(other, uid, item, cancellationToken); ContactFields.SetSource(item, source, changed); updated++; wroteRemote = true; }
                    catch { errors++; }
                }
                else ContactFields.SetSource(item, source, other);
                if (!additiveOnly && repairBirthday && !wroteRemote && !conflictingChanges)
                {
                    try { var changed = await remoteStore.UpdateAsync(other, uid, item, cancellationToken); ContactFields.SetSource(item, source, changed); updated++; }
                    catch { errors++; }
                }
                continue;
            }
            if (!additiveOnly)
            {
                try { var made = await remoteStore.CreateAsync(uid, item, cancellationToken); ContactFields.SetSource(item, source, made); remoteById.Remove(made.Id); exported++; }
                catch { errors++; }
            }
        }

        if (!additiveOnly && errors == 0)
            foreach (var tombstone in dead.OfType<JsonObject>().ToArray())
            {
                var mapping = ContactFields.Source(tombstone, source);
                var id = mapping?["id"]?.GetValue<string>() ?? "";
                var other = id.Length > 0 ? remote.FirstOrDefault(item => item.Id == id) : null;
                if (other is null) continue;
                remoteById.Remove(id);
                try
                {
                    await remoteStore.DeleteAsync(other, ContactFields.Text(tombstone, "uid"), cancellationToken);
                    var sources = tombstone["syncQuellen"] as JsonObject;
                    sources?.Remove(source);
                    if (sources is null || sources.Count == 0) dead.Remove(tombstone);
                    deleted++;
                }
                catch { errors++; break; }
            }

        foreach (var other in remoteById.Values)
        {
            var item = other.Data.DeepClone().AsObject();
            item["id"] = Guid.NewGuid().ToString("N");
            if (ContactFields.Text(item, "uid").Length == 0)
                item["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
            item["geaendert"] = other.Modified;
            var importedRemote = other;
            if (!additiveOnly && birthdayRepairs.Contains(other.Id))
            {
                try { importedRemote = await remoteStore.UpdateAsync(other, ContactFields.Text(item, "uid"), item, cancellationToken); updated++; }
                catch { errors++; }
            }
            ContactFields.SetSource(item, source, importedRemote);
            local.Add(item); imported++;
        }

        return new ContactSyncResult(local, dead, new ContactSyncCounts(imported, exported, updated, deleted, errors));
    }
}
