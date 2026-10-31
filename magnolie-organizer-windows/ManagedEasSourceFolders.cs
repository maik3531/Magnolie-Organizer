using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record ManagedEasSourceFolder(string ProfileId, string AccountId, string FolderId, string Kind,
    string Name, string Identity, string Revision, bool Selected, string? TargetId)
{
    // Target IDs and labels may change; they must never redefine the remote source.
    internal string Uid => $"managed-eas:{ProfileId}:{Identity}";
}

internal sealed record ManagedEasFolderPreparation(ManagedEasSourceFolder Source, string Token);

// Folder setup only. EAS caches are not DAV resources, and these receipts must
// never be interpreted as provider data-sync, write or native commit receipts.
internal static class ManagedEasSourceFolderContract
{
    private static readonly string[] Fields = ["protocol", "version", "account_id", "folder_id", "kind", "source_identity",
        "revision", "selected", "target_id", "provider_sync_confirmed"];

    internal static IReadOnlyList<ManagedEasSourceFolder> ReadList(JsonObject body)
    {
        Exact(body, "id", "ok", "protocol", "version", "profile_id", "complete", "folders");
        Header(body);
        if (!Boolean(body, "complete") || body["folders"] is not JsonArray rows || rows.Count > 256) throw new InvalidDataException();
        var profile = Profile(body);
        var result = new List<ManagedEasSourceFolder>();
        foreach (var raw in rows)
        {
            var row = raw as JsonObject ?? throw new InvalidDataException();
            Exact(row, Fields.Concat(["name"]).ToArray());
            result.Add(ReadFolder(row, profile, Text(row, "name", 256)));
        }
        if (result.Select(source => source.Uid).Distinct(StringComparer.Ordinal).Count() != result.Count ||
            result.Select(source => (source.AccountId, source.FolderId)).Distinct().Count() != result.Count) throw new InvalidDataException();
        return result;
    }

    internal static ManagedEasSourceFolder ReadCurrent(JsonObject body, ManagedEasSourceFolder expected) => ReadReport(body, expected, "current");

    internal static ManagedEasFolderPreparation ReadPrepared(JsonObject body, ManagedEasSourceFolder expected)
    {
        var source = ReadReport(body, expected, "prepared");
        if (source.Revision != expected.Revision || !TelefonProtocolContract.IsUuidV4(Text(body, "token", 36))) throw new InvalidDataException();
        return new(source, body["token"]!.GetValue<string>());
    }

    internal static ManagedEasSourceFolder ReadSelected(JsonObject body, ManagedEasSourceFolder expected)
    {
        var source = ReadReport(body, expected, "selected");
        if (!source.Selected || source.TargetId is null || expected.Selected && source.TargetId != expected.TargetId) throw new InvalidDataException();
        return source;
    }

    private static ManagedEasSourceFolder ReadReport(JsonObject body, ManagedEasSourceFolder expected, string state)
    {
        Exact(body, Fields.Concat(["id", "ok", "profile_id", "state"]).Concat(state == "prepared" ? ["token"] : Array.Empty<string>()).ToArray());
        Header(body);
        if (Profile(body) != expected.ProfileId || Text(body, "state", 16) != state) throw new InvalidDataException();
        var source = ReadFolder(body, expected.ProfileId, expected.Name);
        if (source.AccountId != expected.AccountId || source.FolderId != expected.FolderId || source.Kind != expected.Kind || source.Identity != expected.Identity)
            throw new InvalidDataException();
        return source;
    }

    private static ManagedEasSourceFolder ReadFolder(JsonObject row, string profile, string name)
    {
        if (TelefonProtocolContract.Integer(row["protocol"]) != 1 || TelefonProtocolContract.Integer(row["version"]) != 1 ||
            Boolean(row, "provider_sync_confirmed")) throw new InvalidDataException();
        var account = Text(row, "account_id", 256);
        var folder = Text(row, "folder_id", 256);
        var kind = Text(row, "kind", 16);
        if (kind is not ("contacts" or "calendars")) throw new InvalidDataException();
        var target = row["target_id"] is null ? null : Text(row, "target_id", 1024);
        var selected = Boolean(row, "selected");
        if (!selected && target is not null) throw new InvalidDataException();
        return new(profile, account, folder, kind, name, Hash(row, "source_identity"), Hash(row, "revision"), selected, target);
    }

    private static void Header(JsonObject body)
    {
        var id = Text(body, "id", 32);
        if (!Boolean(body, "ok") || id.Length != 32 || id.Any(c => !IsHex(c)) ||
            TelefonProtocolContract.Integer(body["protocol"]) != 1 || TelefonProtocolContract.Integer(body["version"]) != 1) throw new InvalidDataException();
    }

    private static string Profile(JsonObject body)
    {
        var profile = Text(body, "profile_id", 36);
        if (!TelefonProtocolContract.IsUuidV4(profile)) throw new InvalidDataException();
        return profile;
    }

    private static bool IsHex(char value) => value is >= '0' and <= '9' or >= 'a' and <= 'f';
    private static string Hash(JsonObject body, string field)
    {
        var value = Text(body, field, 64);
        if (value.Length != 64 || value.Any(c => !IsHex(c))) throw new InvalidDataException();
        return value;
    }

    private static string Text(JsonObject body, string field, int maximum)
    {
        if (body[field] is not JsonValue raw || !raw.TryGetValue<string>(out var value) || value.Length is < 1 || value.Length > maximum ||
            value != value.Trim() || value.Any(char.IsControl)) throw new InvalidDataException();
        try { if (value != value.Normalize(NormalizationForm.FormC)) throw new InvalidDataException(); }
        catch (ArgumentException error) { throw new InvalidDataException("Invalid source text.", error); }
        return value;
    }

    private static bool Boolean(JsonObject body, string field) => body[field] is JsonValue raw && raw.TryGetValue<bool>(out var value)
        ? value : throw new InvalidDataException();
    private static void Exact(JsonObject body, params string[] fields)
    {
        if (body.Count != fields.Length || body.Any(item => !fields.Contains(item.Key, StringComparer.Ordinal))) throw new InvalidDataException();
    }
}

internal sealed class ManagedEasSourceFolderClient
{
    private readonly Func<JsonObject, CancellationToken, Task<JsonObject>> call;
    internal ManagedEasSourceFolderClient(Func<JsonObject, CancellationToken, Task<JsonObject>>? call = null) =>
        this.call = call ?? ((request, token) => ThunderbirdBridge.CallAsync(request, token, managed: true));

    internal async Task<IReadOnlyList<ManagedEasSourceFolder>> ReadAsync(CancellationToken token) =>
        ManagedEasSourceFolderContract.ReadList(await call(new() { ["op"] = "eas-source-list" }, token).ConfigureAwait(false));

    internal async Task<ManagedEasSourceFolder> InspectAsync(ManagedEasSourceFolder source, CancellationToken token) =>
        ManagedEasSourceFolderContract.ReadCurrent(await call(Request("eas-source-inspect", source), token).ConfigureAwait(false), source);

    internal async Task<ManagedEasFolderPreparation> PrepareAsync(ManagedEasSourceFolder source, CancellationToken token) =>
        ManagedEasSourceFolderContract.ReadPrepared(await call(Request("eas-source-prepare", source), token).ConfigureAwait(false), source);

    internal async Task<ManagedEasSourceFolder> EnableAsync(ManagedEasFolderPreparation prepared, CancellationToken token)
    {
        var request = Request("eas-source-enable", prepared.Source);
        request["token"] = prepared.Token; request["revision"] = prepared.Source.Revision;
        return ManagedEasSourceFolderContract.ReadSelected(await call(request, token).ConfigureAwait(false), prepared.Source);
    }

    private static JsonObject Request(string op, ManagedEasSourceFolder source) => new()
    { ["op"] = op, ["account_id"] = source.AccountId, ["folder_id"] = source.FolderId };
}
