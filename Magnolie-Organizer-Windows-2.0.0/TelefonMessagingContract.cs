using System.Text.RegularExpressions;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static partial class TelefonMessagingContract
{
    internal static void Validate(string kind, JsonNode node)
    {
        var body = node as JsonObject ?? throw new InvalidDataException("Nachrichteninhalt erwartet.");
        if (kind != "selected_notifications_readonly.event")
            throw new InvalidDataException("Unbekannte Telefon-Nachrichtenart.");
        TelefonProtocolContract.ExactObject(body, "notification_id", "event", "package", "app_label", "title", "text", "posted_ms", "is_default_sms_app");
        Uuid(body, "notification_id");
        var eventName = Text(body, "event", 1, 16);
        if (eventName is not ("posted" or "removed")) throw new InvalidDataException("Benachrichtigungsereignis ungültig.");
        var package = Text(body, "package", 1, 255);
        if (!PackageName().IsMatch(package)) throw new InvalidDataException("Paketname ungültig.");
        Text(body, "app_label", 0, 80); var title = Text(body, "title", 0, 500, true); var text = Text(body, "text", 0, 5000, true);
        Time(body, "posted_ms"); Boolean(body, "is_default_sms_app");
        if (eventName == "removed" && (title.Length != 0 || text.Length != 0)) throw new InvalidDataException("Entfernte Benachrichtigung enthält Inhalt.");
    }

    internal static void Time(JsonObject body, string name)
    { if (!TelefonProtocolContract.TryInteger(body[name], out var value) || value is < 0 or > 253402300799999) throw new InvalidDataException("Zeitpunkt ungültig."); }
    internal static string Text(JsonObject body, string name, int minimum, int maximum, bool allowLines = false)
    {
        if (body[name] is not JsonValue value || !value.TryGetValue<string>(out var text) || text.EnumerateRunes().Count() is var count &&
            (count < minimum || count > maximum || text.Any(character => char.IsControl(character) && (!allowLines || character is not ('\n' or '\t')))))
            throw new InvalidDataException("Textfeld ungültig.");
        return text;
    }
    internal static string String(JsonObject body, string name)
    { if (body[name] is not JsonValue value || !value.TryGetValue<string>(out var text)) throw new InvalidDataException("Text erwartet."); return text; }
    internal static bool Boolean(JsonObject body, string name)
    { if (body[name] is not JsonValue value || !value.TryGetValue<bool>(out var result)) throw new InvalidDataException("Boolescher Wert erwartet."); return result; }
    internal static void Uuid(JsonObject body, string name, bool version4 = false)
    {
        var text = String(body, name);
        if (!Guid.TryParseExact(text, "D", out var id) || id == Guid.Empty || id.ToString("D") != text || version4 && !TelefonProtocolContract.IsUuidV4(text))
            throw new InvalidDataException("UUID ungültig.");
    }

    [GeneratedRegex("^[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+$", RegexOptions.CultureInvariant)]
    private static partial Regex PackageName();
}
