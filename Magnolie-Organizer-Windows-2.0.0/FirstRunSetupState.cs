using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal enum FirstRunSetupClassification
{
    Fresh,
    Pending,
    Complete,
    ExistingWithoutMarker,
    DamagedMarker
}

internal sealed record FirstRunSetupSelections
{
    [JsonPropertyName("language")]
    public string Language { get; init; } = "system";
    [JsonPropertyName("address")]
    public FirstRunSetupAddress Address { get; init; } = new();
    [JsonPropertyName("addressSource")]
    public string AddressSource { get; init; } = "own";
    [JsonPropertyName("addressSort")]
    public string AddressSort { get; init; } = "last-name";
    [JsonPropertyName("calendarUids")]
    public List<string> CalendarUids { get; init; } = [];
    [JsonPropertyName("addressBookUid")]
    public string AddressBookUid { get; init; } = "";
    [JsonPropertyName("oneTimeImports")]
    public List<string> OneTimeImports { get; init; } = [];
    [JsonPropertyName("phoneActions")]
    public List<string> PhoneActions { get; init; } = [];
    [JsonPropertyName("registers")]
    public List<string> Registers { get; init; } = ["tasks", "addresses", "notes", "anniversaries", "planner", "health"];
    [JsonPropertyName("customTabEnabled")]
    public bool CustomTabEnabled { get; init; }
    [JsonPropertyName("customTabName")]
    public string CustomTabName { get; init; } = "";
    [JsonPropertyName("customTabDesignRequested")]
    public bool CustomTabDesignRequested { get; init; }
    [JsonPropertyName("customTabChanged")]
    public bool CustomTabChanged { get; init; }
    [JsonPropertyName("customOrganizerChanged")]
    public bool CustomOrganizerChanged { get; init; }
    [JsonPropertyName("customOrganizer")]
    public FirstRunSetupCustomOrganizer CustomOrganizer { get; init; } = new();
    [JsonPropertyName("openHandbook")]
    public bool OpenHandbook { get; init; }
    [JsonPropertyName("backupPath")]
    public string BackupPath { get; init; } = "";
    [JsonPropertyName("backupInterval")]
    public string BackupInterval { get; init; } = "manual";
    [JsonPropertyName("autostart")]
    public bool Autostart { get; init; }
    [JsonPropertyName("tray")]
    public bool Tray { get; init; }
    [JsonPropertyName("weather")]
    public bool Weather { get; init; }
    [JsonPropertyName("restoreRequest")]
    public bool RestoreRequest { get; init; }
}

internal sealed record FirstRunSetupCustomOrganizer
{
    [JsonPropertyName("version")] public int Version { get; init; } = 3;
    [JsonPropertyName("modules")] public List<FirstRunSetupCustomModule> Modules { get; init; } = [];
}

internal sealed record FirstRunSetupCustomModule
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("type")] public string Type { get; init; } = "notes";
    [JsonPropertyName("page")] public string Page { get; init; } = "left";
    [JsonPropertyName("order")] public int Order { get; init; }
}

internal sealed record FirstRunSetupAddress
{
    [JsonPropertyName("firstName")] public string FirstName { get; init; } = "";
    [JsonPropertyName("lastName")] public string LastName { get; init; } = "";
    [JsonPropertyName("street")] public string Street { get; init; } = "";
    [JsonPropertyName("postalCode")] public string PostalCode { get; init; } = "";
    [JsonPropertyName("city")] public string City { get; init; } = "";
    [JsonPropertyName("country")] public string Country { get; init; } = "DE";
    [JsonPropertyName("state")] public string State { get; init; } = "";
}

internal sealed record FirstRunSetupMarker(
    string Format,
    int Version,
    string Status,
    DateTimeOffset CompletedUtc,
    FirstRunSetupSelections Selections);

internal static class FirstRunSetupSelectionNormalizer
{
    private static readonly string[] ImportOrder = ["claws", "vcard", "ldif", "csv-lotus", "windows-contacts"];
    private static readonly string[] RegisterOrder = ["tasks", "addresses", "notes", "anniversaries", "planner", "health"];
    private static readonly Dictionary<string, string> GermanRegions = new(StringComparer.OrdinalIgnoreCase)
    {
        ["DE-BW"] = "DE-BW", ["Baden-Württemberg"] = "DE-BW",
        ["DE-BY"] = "DE-BY", ["Bavaria"] = "DE-BY", ["Bayern"] = "DE-BY",
        ["DE-BE"] = "DE-BE", ["Berlin"] = "DE-BE",
        ["DE-BB"] = "DE-BB", ["Brandenburg"] = "DE-BB",
        ["DE-HB"] = "DE-HB", ["Bremen"] = "DE-HB",
        ["DE-HH"] = "DE-HH", ["Hamburg"] = "DE-HH",
        ["DE-HE"] = "DE-HE", ["Hesse"] = "DE-HE", ["Hessen"] = "DE-HE",
        ["DE-NI"] = "DE-NI", ["Lower Saxony"] = "DE-NI", ["Niedersachsen"] = "DE-NI",
        ["DE-MV"] = "DE-MV", ["Mecklenburg-Western Pomerania"] = "DE-MV", ["Mecklenburg-Vorpommern"] = "DE-MV",
        ["DE-NW"] = "DE-NW", ["North Rhine-Westphalia"] = "DE-NW", ["Nordrhein-Westfalen"] = "DE-NW",
        ["DE-RP"] = "DE-RP", ["Rhineland-Palatinate"] = "DE-RP", ["Rheinland-Pfalz"] = "DE-RP",
        ["DE-SL"] = "DE-SL", ["Saarland"] = "DE-SL",
        ["DE-SN"] = "DE-SN", ["Saxony"] = "DE-SN", ["Sachsen"] = "DE-SN",
        ["DE-ST"] = "DE-ST", ["Saxony-Anhalt"] = "DE-ST", ["Sachsen-Anhalt"] = "DE-ST",
        ["DE-SH"] = "DE-SH", ["Schleswig-Holstein"] = "DE-SH",
        ["DE-TH"] = "DE-TH", ["Thuringia"] = "DE-TH", ["Thüringen"] = "DE-TH"
    };

    internal static FirstRunSetupSelections Normalize(FirstRunSetupSelections selections,
        string defaultBackupPath, bool skipped = false)
    {
        if (skipped)
            return new FirstRunSetupSelections
            {
                Language = selections.Language,
                OpenHandbook = false,
                BackupPath = defaultBackupPath,
                BackupInterval = "manual"
            };

        return selections with
        {
            AddressSort = selections.AddressSort == "first-name" ? "first-name" : "last-name",
            OneTimeImports = Canonical(selections.OneTimeImports, ImportOrder),
            PhoneActions = [],
            Registers = Canonical(selections.Registers, RegisterOrder),
            Address = new FirstRunSetupAddress
            {
                FirstName = Limited(selections.Address.FirstName),
                LastName = Limited(selections.Address.LastName),
                Street = Limited(selections.Address.Street),
                PostalCode = Limited(selections.Address.PostalCode),
                City = Limited(selections.Address.City),
                Country = Limited(selections.Address.Country),
                State = NormalizeRegion(selections.Address.Country, selections.Address.State)
            },
            CustomTabName = Limited(selections.CustomTabName),
            CustomOrganizer = new FirstRunSetupCustomOrganizer
            {
                Modules = (selections.CustomOrganizer?.Modules ?? [])
                    .Where(module => module is not null && module.Type is "appointments" or "notes" or "tasks")
                    .Take(24)
                    .Select((module, index) => new FirstRunSetupCustomModule
                    {
                        Id = $"setup-{index}",
                        Type = module.Type,
                        Page = index % 2 == 0 ? "left" : "right",
                        Order = index / 2
                    })
                    .ToList()
            },
            BackupPath = string.IsNullOrWhiteSpace(selections.BackupPath)
                ? defaultBackupPath
                : selections.BackupPath.Trim(),
            Tray = selections.Tray || selections.Autostart
        };
    }

    private static List<string> Canonical(IEnumerable<string> selected, IEnumerable<string> order)
    {
        var values = selected.ToHashSet(StringComparer.Ordinal);
        return order.Where(values.Contains).ToList();
    }

    private static string Limited(string value)
    {
        var trimmed = (value ?? "").Trim();
        return trimmed[..Math.Min(trimmed.Length, 120)];
    }

    private static string NormalizeRegion(string country, string region)
    {
        var value = Limited(region);
        return string.Equals(Limited(country), "DE", StringComparison.OrdinalIgnoreCase) &&
               GermanRegions.TryGetValue(value, out var code) ? code : value;
    }
}

internal sealed class FirstRunSetupState
{
    internal const string Format = "magnolie-windows-first-run";
    internal const int Version = 1;
    private const long MaximumBytes = 256 * 1024;
    private readonly WindowsPaths paths;
    private readonly AtomicStore store;

    internal FirstRunSetupState(WindowsPaths paths, AtomicStore? store = null)
    {
        this.paths = paths;
        this.store = store ?? new AtomicStore();
    }

    internal FirstRunSetupClassification Classify()
    {
        try
        {
            var text = store.ReadRecoverableJson(paths.FirstRunSetup, MaximumBytes);
            if (text is not null)
            {
                var marker = JsonSerializer.Deserialize<FirstRunSetupMarker>(text);
                if (marker is not null && marker.Format == Format && marker.Version == Version && marker.Selections is not null)
                    return marker.Status switch
                    {
                        "pending" => FirstRunSetupClassification.Pending,
                        "completed" or "skipped" or "adopted" => FirstRunSetupClassification.Complete,
                        _ => FirstRunSetupClassification.DamagedMarker
                    };
                return FirstRunSetupClassification.DamagedMarker;
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or InvalidDataException)
        {
            return FirstRunSetupClassification.DamagedMarker;
        }

        return HasExistingInstallation()
            ? FirstRunSetupClassification.ExistingWithoutMarker
            : FirstRunSetupClassification.Fresh;
    }

    internal void Complete(FirstRunSetupSelections selections, bool skipped = false) =>
        Write(skipped ? "skipped" : "completed", selections);

    internal void Begin() => Write("pending", new FirstRunSetupSelections
    {
        Language = RegionalSettings.Read(paths.RegionalSettings)["language"]?.GetValue<string>() ?? "system",
        BackupPath = paths.Backups
    });

    internal void AdoptExisting() => Write("adopted", new FirstRunSetupSelections
    {
        Language = RegionalSettings.Read(paths.RegionalSettings)["language"]?.GetValue<string>() ?? "system",
        BackupPath = paths.Backups,
        OpenHandbook = false
    });

    private void Write(string status, FirstRunSetupSelections selections)
    {
        var marker = new FirstRunSetupMarker(Format, Version, status, DateTimeOffset.UtcNow, selections);
        store.WriteRecoverableJson(paths.FirstRunSetup,
            JsonSerializer.Serialize(marker, new JsonSerializerOptions { WriteIndented = true }), MaximumBytes);
    }

    private bool HasExistingInstallation()
    {
        if (!Directory.Exists(paths.Root)) return false;
        try
        {
            return Directory.EnumerateFileSystemEntries(paths.Root).Any(path =>
                !string.Equals(path, paths.FirstRunSetup, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(path, AtomicStore.BackupPath(paths.FirstRunSetup), StringComparison.OrdinalIgnoreCase));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            return true;
        }
    }
}

internal static class FirstRunSetupStartup
{
    internal static bool MustShowAssistant(FirstRunSetupClassification classification,
        bool trayStart, bool reminderStart) =>
        (classification is FirstRunSetupClassification.Fresh or FirstRunSetupClassification.Pending or FirstRunSetupClassification.DamagedMarker) &&
        !trayStart && !reminderStart;

    internal static bool MustExitBackground(FirstRunSetupClassification classification,
        bool trayStart, bool reminderStart) =>
        (classification is FirstRunSetupClassification.Fresh or FirstRunSetupClassification.Pending or FirstRunSetupClassification.DamagedMarker) &&
        (trayStart || reminderStart);
}
