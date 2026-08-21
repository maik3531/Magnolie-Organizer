using System.Text.Json;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal sealed record TraySettings(
    bool Aktiv = false,
    bool MinimierenInTray = true,
    bool SchliessenInTray = true,
    bool StartMinimiert = false,
    bool Autostart = false,
    bool Zaehler = false,
    string Oeffnen = "previous")
{
    internal static TraySettings FromJson(JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Object) return new TraySettings();
        var opening = Text(element, "oeffnen").ToLowerInvariant() switch
        {
            "zentriert" or "centered" => "centered",
            "maximiert" or "maximized" => "maximized",
            _ => "previous"
        };
        return new TraySettings(
            True(element, "aktiv"),
            NotFalse(element, "minimierenInTray"),
            NotFalse(element, "schliessenInTray"),
            True(element, "startMinimiert"),
            True(element, "autostart"),
            True(element, "zaehler"),
            opening);
    }

    private static bool True(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    private static bool NotFalse(JsonElement element, string name) =>
        !element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.False;

    private static string Text(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? "" : "";
}

internal sealed class TraySettingsService
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string RunValue = "Magnolie Organizer";
    private readonly string path;
    private readonly AtomicStore store = new();
    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web);
    internal bool LoadFailed { get; private set; }

    internal TraySettingsService(string path) => this.path = path;

    internal TraySettings Load(string? legacyDataPath = null)
    {
        LoadFailed = false;
        try
        {
            var text = store.Read(path, 64 * 1024);
            if (text is not null)
            {
                using var document = JsonDocument.Parse(text);
                return TraySettings.FromJson(document.RootElement);
            }

            var migrated = LoadLegacy(legacyDataPath);
            if (migrated is not null) Save(migrated);
            return migrated ?? new TraySettings();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            LoadFailed = true;
            return new TraySettings();
        }
    }

    internal void Save(TraySettings settings) =>
        store.Write(path, JsonSerializer.Serialize(settings, SerializerOptions));

    private TraySettings? LoadLegacy(string? dataPath)
    {
        if (string.IsNullOrWhiteSpace(dataPath)) return null;
        var text = store.ReadRecoverableJson(dataPath, 64 * 1024 * 1024);
        if (text is null || EncryptionService.IsEncrypted(text)) return null;
        using var document = JsonDocument.Parse(text);
        if (!document.RootElement.TryGetProperty("einstellungen", out var settings) ||
            !settings.TryGetProperty("allgemein", out var general) ||
            !general.TryGetProperty("tray", out var tray)) return null;
        return TraySettings.FromJson(tray);
    }

    internal static string AutostartCommand(string executablePath) =>
        $"\"{executablePath}\" --tray-start";

    internal static string BackgroundAutostartCommand(string executablePath) =>
        $"\"{executablePath}\" --tray-start --reminder-start";

    internal static string ConfigureAutostart(bool enabled, string executablePath, bool reminderStart = false)
    {
        if (!OperatingSystem.IsWindows()) return "";
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(RunKey, writable: true)
                ?? throw new UnauthorizedAccessException("Der Autostartschlüssel konnte nicht geöffnet werden.");
            if (enabled)
            {
                if (string.IsNullOrWhiteSpace(executablePath) || !File.Exists(executablePath))
                    throw new FileNotFoundException("Die Programmdatei für den Autostart wurde nicht gefunden.");
                key.SetValue(RunValue, reminderStart ? BackgroundAutostartCommand(executablePath) : AutostartCommand(executablePath), RegistryValueKind.String);
            }
            else key.DeleteValue(RunValue, throwOnMissingValue: false);
            return "";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                             System.Security.SecurityException or ArgumentException)
        {
            return $"Der Windows-Autostart konnte nicht eingerichtet werden: {error.Message}";
        }
    }
}
