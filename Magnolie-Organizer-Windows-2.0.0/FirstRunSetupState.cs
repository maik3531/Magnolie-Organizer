using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record SetupConnectionRequest(string AccountType, string Server, string User, string Password);
internal sealed record SetupSource(string Uid, string Name);
internal sealed record SetupConnection(string Token, IReadOnlyList<SetupSource> Calendars,
    IReadOnlyList<SetupSource> AddressBooks);

internal interface IFirstRunSetupServices
{
    Task<JsonObject?> PrepareImportAsync(string source, string? path, CancellationToken cancellationToken);
    Task<SetupConnection> DiscoverAsync(SetupConnectionRequest request, CancellationToken cancellationToken);
    Task CommitConnectionAsync(string token, CancellationToken cancellationToken);
}

internal sealed record SetupPhoneCapability(string Transport, bool Available, bool CanAutoStart, string Reason = "");
internal sealed record SetupPhonePrompt(string Kind, IReadOnlyList<SetupSource> Devices, string Code = "", bool CanMarkOwn = false);
internal sealed record SetupPhoneResult(string Transport, string DeviceId, string Name, bool Authenticated);
internal interface IFirstRunSetupPhoneServices
{
    IReadOnlyList<SetupPhoneCapability> Capabilities { get; }
    Task<SetupPhoneResult> ConnectAsync(string transport, Func<SetupPhonePrompt, Task<string?>> prompt, CancellationToken cancellationToken);
    Task<IReadOnlyList<string>> ConnectedAsync(CancellationToken cancellationToken);
    Task CommitStartupAsync(IReadOnlyList<string> transports, CancellationToken cancellationToken);
}

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
    internal IReadOnlyList<string> ForegroundPhoneTransports { get; init; } = [];
    [JsonPropertyName("language")]
    public string Language { get; init; } = "system";
    [JsonPropertyName("address")]
    public FirstRunSetupAddress Address { get; init; } = new();
    [JsonPropertyName("addressSource")]
    public string AddressSource { get; init; } = "own";
    [JsonPropertyName("addressChanged")]
    public bool AddressChanged { get; init; }
    [JsonPropertyName("schoolHolidays")]
    public bool SchoolHolidays { get; init; }
    [JsonPropertyName("schoolHolidayRegion")]
    public string SchoolHolidayRegion { get; init; } = "";
    [JsonPropertyName("setupSkipped")]
    public bool SetupSkipped { get; init; }
    [JsonPropertyName("addressSort")]
    public string AddressSort { get; init; } = "last-name";
    [JsonPropertyName("calendarUids")]
    public List<string> CalendarUids { get; init; } = [];
    [JsonPropertyName("addressBookUid")]
    public string AddressBookUid { get; init; } = "";
    [JsonPropertyName("oneTimeImports")]
    public List<string> OneTimeImports { get; init; } = [];
    [JsonPropertyName("stagedImports")]
    public List<FirstRunSetupImport> StagedImports { get; init; } = [];
    [JsonPropertyName("phoneActions")]
    public List<string> PhoneActions { get; init; } = [];
    [JsonPropertyName("phoneBackgroundServices")]
    public List<string> PhoneBackgroundServices { get; init; } = [];
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

internal sealed record FirstRunSetupImport(
    [property: JsonPropertyName("source")] string Source,
    [property: JsonPropertyName("payload")] JsonObject Payload);

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
    [JsonPropertyName("country")] public string Country { get; init; } = SystemCountry(System.Globalization.CultureInfo.CurrentCulture.Name);

    internal static string SystemCountry(string locale)
    {
        // A neutral language must not acquire an invented default territory.
        try
        {
            var culture = System.Globalization.CultureInfo.GetCultureInfo(locale.Replace('_', '-'));
            return culture.IsNeutralCulture || culture.Equals(System.Globalization.CultureInfo.InvariantCulture)
                ? "" : new System.Globalization.RegionInfo(culture.Name).TwoLetterISORegionName;
        }
        catch (ArgumentException) { return ""; }
    }
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
    private static readonly string[] ImportOrder = ["thunderbird", "claws", "vcard", "ldif", "csv-lotus", "windows-contacts"];
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
                SetupSkipped = true,
                OpenHandbook = false,
                BackupPath = defaultBackupPath,
                BackupInterval = "manual"
            };

        var holidayRegion = SchoolHolidayRegion(selections.Address.Country, selections.Address.State);
        var holidayConsent = selections.SchoolHolidays && holidayRegion.Length > 0 &&
            holidayRegion == selections.SchoolHolidayRegion;
        return selections with
        {
            SchoolHolidays = holidayConsent,
            SchoolHolidayRegion = holidayConsent ? holidayRegion : "",
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
                { Modules = NormalizeCustomModules(selections.CustomOrganizer?.Modules ?? []) },
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

    private static List<FirstRunSetupCustomModule> NormalizeCustomModules(
        IEnumerable<FirstRunSetupCustomModule> source)
    {
        var result = new List<FirstRunSetupCustomModule>();
        foreach (var module in source.Take(24))
        {
            if (module is null || module.Type is not ("appointments" or "notes" or "tasks")) continue;
            if (module.Type != "notes" && result.Any(item => item.Type == module.Type)) continue;
            var page = module.Page == "right" ? "right" : "left";
            if (result.Count(item => item.Page == page) >= 2 ||
                module.Type == "notes" && result.Any(item => item.Type == "notes" && item.Page == page))
            {
                page = page == "left" ? "right" : "left";
            }
            if (result.Count(item => item.Page == page) >= 2 ||
                module.Type == "notes" && result.Any(item => item.Type == "notes" && item.Page == page)) continue;
            result.Add(new FirstRunSetupCustomModule
            {
                Id = $"setup-{result.Count}", Type = module.Type, Page = page,
                Order = result.Count(item => item.Page == page)
            });
            if (result.Count == 4) break;
        }
        return result;
    }

    private static string Limited(string value)
    {
        var trimmed = (value ?? "").Trim();
        return trimmed[..Math.Min(trimmed.Length, 120)];
    }

    internal static string SchoolHolidayRegion(string country, string region)
    {
        var value = NormalizeRegion(country, region).ToUpperInvariant();
        var territory = Limited(country).ToUpperInvariant();
        return territory switch
        {
            "DE" when GermanRegions.ContainsKey(value) => value,
            "AT" when value.Length == 4 && value.StartsWith("AT-", StringComparison.Ordinal) && value[3] is >= '1' and <= '9' => value,
            "CH" when new[] { "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
                "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH" }.Any(code => value == "CH-" + code) => value,
            _ => ""
        };
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
        // Parsed personal data is a transient handoff, never part of the setup marker.
        var marker = new FirstRunSetupMarker(Format, Version, status, DateTimeOffset.UtcNow,
            selections with { StagedImports = [] });
        store.WriteRecoverableJson(paths.FirstRunSetup,
            JsonSerializer.Serialize(marker, new JsonSerializerOptions { WriteIndented = true }), MaximumBytes);
    }

    private bool HasExistingInstallation()
    {
        if (!Directory.Exists(paths.Root)) return false;
        try
        {
            return Directory.EnumerateFileSystemEntries(paths.Root).Any(path =>
                Path.GetFileName(path) != ".profile-owner.lock" &&
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
