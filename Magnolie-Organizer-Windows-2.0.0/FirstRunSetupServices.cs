using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Only selection-triggered reads occur here. Draft imports never touch the organizer store.
internal sealed class FirstRunSetupServices(WindowsPaths paths, string? thunderbirdRoot = null,
    string? contactsFolder = null) : IFirstRunSetupServices, IDisposable
{
    private readonly string temporary = Path.Combine(Path.GetTempPath(), "magnolie-setup-" + Guid.NewGuid().ToString("N"));
    private readonly Dictionary<string, SetupConnectionRequest> connections = new(StringComparer.Ordinal);

    public Task<JsonObject?> PrepareImportAsync(string source, string? path, CancellationToken cancellationToken) =>
        Task.Run(async () =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (path is not null)
            {
                var art = source switch
                {
                    "ics" => "ics", "vcard" => "vcf", "csv-lotus" => "lotus",
                    "claws" or "ldif" => "claws",
                    "thunderbird" => Path.GetExtension(path).ToLowerInvariant() switch
                    {
                        ".ics" or ".vcs" or ".lcs" => "ics", ".vcf" => "vcf",
                        ".csv" => "lotus", ".xml" or ".ldif" or ".ldi" => "claws",
                        _ => throw new InvalidDataException(NativeLocalization.Gettext("The file has an unsupported format."))
                    },
                    _ => throw new ArgumentException("Unknown setup import source")
                };
                if (new FileInfo(path).Length > ExchangeCodec.MaxImportBytes)
                    throw new IOException(NativeLocalization.Gettext("The import file is larger than 32 megabytes."));
                var bytes = await File.ReadAllBytesAsync(path, cancellationToken);
                var parsed = ExchangeCodec.ParseImport(bytes, art, path);
                return JsonSerializer.SerializeToNode(parsed.ToPayload(art, Path.GetFileName(path)))!.AsObject();
            }
            if (source == "thunderbird")
            {
                var root = thunderbirdRoot ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Thunderbird");
                if (!Directory.Exists(root)) return null;
                var profiles = ThunderbirdCalendarImporter.DiscoverProfiles(root);
                var calendars = ThunderbirdCalendarImporter.ParseProfiles(
                    profiles.Select(profile => Path.Combine(profile, "calendar-data", "local.sqlite")), out var files);
                var books = ThunderbirdCalendarImporter.ParseAddressBooks(profiles, out var bookFiles);
                if (files + bookFiles == 0) return null;
                var result = JsonSerializer.SerializeToNode(calendars.ToPayload("lokal", "Thunderbird"))!.AsObject();
                result["kontakte"] = books.Kontakte.DeepClone();
                foreach (var profile in profiles)
                {
                    try
                    {
                        var compatibility = Path.Combine(profile, "compatibility.ini");
                        if (!File.Exists(compatibility) || new FileInfo(compatibility).Length > 64 * 1024) continue;
                        var version = File.ReadLines(compatibility).FirstOrDefault(line => line.StartsWith("LastVersion=", StringComparison.Ordinal));
                        if (version is null) continue;
                        result["sourceVersion"] = new string(version[12..].Where(c => char.IsAsciiLetterOrDigit(c) || "._-".Contains(c)).Take(80).ToArray());
                        break;
                    }
                    catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
                }
                return new[] { "kontakte", "termine", "aufgaben", "jahrestage", "geburtstage", "notizen" }
                    .Any(key => result[key] is JsonArray { Count: > 0 }) ? result : null;
            }
            if (source == "windows-contacts")
            {
                var store = new WindowsContactStore(contactsFolder ?? Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Contacts"));
                var contacts = await store.ReadAsync(cancellationToken);
                return new JsonObject { ["art"] = "lokal", ["kontakte"] = new JsonArray(contacts.Select(contact =>
                {
                    var item = contact.Data.DeepClone().AsObject();
                    item["uid"] = store.ImportUid(contact); item["geaendert"] = contact.Modified;
                    return (JsonNode)item;
                }).ToArray()) };
            }
            return null;
        }, cancellationToken);

    public async Task<SetupConnection> DiscoverAsync(SetupConnectionRequest request, CancellationToken cancellationToken)
    {
        var token = Guid.NewGuid().ToString("N");
        var folder = Path.Combine(temporary, token);
        var store = new NextcloudMailboxSettingsStore(Path.Combine(folder, "settings.json"), Path.Combine(folder, "password.dpapi"));
        try
        {
            await Task.Run(() => store.SaveConfiguration(new NextcloudMailboxSettings(true, false, request.Server, request.User)
                { AccountType = request.AccountType }, request.Password, false), cancellationToken);
            using var client = new NextcloudDavClient(store);
            var sources = await client.ListSourcesAsync(cancellationToken);
            connections[token] = request;
            return new SetupConnection(token, sources.Calendars.Select(s => new SetupSource(s.Uid, s.Name)).ToArray(),
                sources.AddressBooks.Select(s => new SetupSource(s.Uid, s.Name)).ToArray());
        }
        finally { if (Directory.Exists(folder)) Directory.Delete(folder, true); }
    }

    public Task CommitConnectionAsync(string token, CancellationToken cancellationToken)
    {
        var request = connections[token];
        return Task.Run(() => new NextcloudMailboxSettingsStore(paths.BaumMailboxSettings, paths.BaumMailboxPassword)
            .SaveConfiguration(new NextcloudMailboxSettings(true, false, request.Server, request.User)
                { AccountType = request.AccountType }, request.Password, false), cancellationToken);
    }

    public void Dispose()
    {
        connections.Clear();
        if (Directory.Exists(temporary)) Directory.Delete(temporary, true);
    }
}
