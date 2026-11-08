using System.Text.Json;

namespace MagnolieOrganizer.Windows;

// A time-bounded visual lease. It has no transport, data or permission setters.
internal sealed class TrayVisualTest
{
    internal static bool SavedDeveloperMode(string savedDocument, bool unlocked)
    {
        if (!unlocked) return false;
        try
        {
            using var document = JsonDocument.Parse(savedDocument);
            return document.RootElement.TryGetProperty("einstellungen", out var settings) &&
                settings.TryGetProperty("allgemein", out var general) &&
                general.TryGetProperty("entwicklermodus", out var developer) && developer.ValueKind == JsonValueKind.True;
        }
        catch (JsonException) { return false; }
        catch (InvalidOperationException) { return false; }
    }
    private TrayAppearanceState? state;
    private object? owner;
    private long deadline;
    internal bool HasLease => state.HasValue;
    internal void Clear() { state = null; owner = null; deadline = 0; }
    internal void Start(JsonElement request, bool savedDeveloperMode, object bookOwner, long now)
    {
        Clear();
        if (!savedDeveloperMode) throw new InvalidOperationException("native_developer_mode_required");
        if (request.ValueKind != JsonValueKind.Object || request.EnumerateObject().Any(p => p.Name is not ("cmd" or "connection" or "mode" or "sync")) ||
            request.EnumerateObject().Select(p => p.Name).Distinct(StringComparer.Ordinal).Count() != request.EnumerateObject().Count())
            throw new InvalidDataException("invalid_tray_visual_test");
        var connection = request.GetProperty("connection").GetString() switch
        {
            "none" => TrayFlowerConnection.None, "notes" => TrayFlowerConnection.Notes,
            "kde" => TrayFlowerConnection.Kde, "both" => TrayFlowerConnection.Both,
            _ => throw new InvalidDataException("invalid_tray_visual_test")
        };
        var mode = request.GetProperty("mode").GetString() switch
        {
            "flower" => TrayAppearanceMode.Flower, "camera" => TrayAppearanceMode.Camera,
            "phone" => TrayAppearanceMode.Phone, _ => throw new InvalidDataException("invalid_tray_visual_test")
        };
        var sync = request.GetProperty("sync").GetBoolean();
        state = new(connection, sync, mode); owner = bookOwner; deadline = checked(now + 60000);
    }
    internal TrayAppearanceState? Current(bool savedDeveloperMode, object bookOwner, long now)
    {
        if (!savedDeveloperMode || !ReferenceEquals(owner, bookOwner) || now >= deadline) Clear();
        return state;
    }
}
