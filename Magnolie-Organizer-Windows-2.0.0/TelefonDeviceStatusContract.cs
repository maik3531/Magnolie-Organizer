using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class TelefonDeviceStatusContract
{
    private static readonly HashSet<string> RequestFields = new(StringComparer.Ordinal) { "request_id" };
    private static readonly HashSet<string> RequestV2Fields = new(StringComparer.Ordinal) { "request_id", "version" };
    private static readonly HashSet<string> ReportFields = new(StringComparer.Ordinal)
        { "request_id", "model", "manufacturer", "os_name", "os_version", "battery_percent", "charging", "captured_ms" };
    private static readonly HashSet<string> ReportV2Fields = new(ReportFields, StringComparer.Ordinal)
        { "sdk_int", "battery_temperature_deci_c", "power_source", "storage_total_bytes", "storage_available_bytes",
          "memory_total_bytes", "memory_available_bytes", "uptime_ms", "network_transport", "network_validated", "network_metered" };
    private static readonly HashSet<string> Charging = new(StringComparer.Ordinal)
        { "charging", "full", "discharging", "not_charging", "unknown" };

    internal static void ValidateRequest(JsonNode node)
    {
        var value = node as JsonObject ?? throw new InvalidDataException("Der Gerätestatus ist kein Objekt.");
        if (!FieldsAre(value, RequestFields) && !FieldsAre(value, RequestV2Fields)) throw new InvalidDataException("Ungültige Statusanfrage.");
        Uuid(value, "request_id");
        if (value.ContainsKey("version") && (!TelefonProtocolContract.TryInteger(value["version"], out var version) || version is < 1 or > 2))
            throw new InvalidDataException("Die Statusversion ist ungültig.");
    }

    internal static void ValidateReport(JsonNode node)
    {
        var value = node as JsonObject ?? throw new InvalidDataException("Der Gerätestatus ist kein Objekt.");
        var extended = FieldsAre(value, ReportV2Fields);
        if (!extended && !FieldsAre(value, ReportFields)) throw new InvalidDataException("Der Gerätestatus enthält unbekannte oder fehlende Felder.");
        Uuid(value, "request_id"); Text(value, "model", 0, 80); Text(value, "manufacturer", 0, 80);
        Text(value, "os_name", 1, 20); Text(value, "os_version", 0, 40);
        if (!TelefonProtocolContract.TryInteger(value["battery_percent"], out var battery) || battery is < -1 or > 100)
            throw new InvalidDataException("Der Akkustand ist ungültig.");
        if (value["charging"] is not JsonValue chargingNode || !chargingNode.TryGetValue<string>(out var charging) || !Charging.Contains(charging))
            throw new InvalidDataException("Der Ladezustand ist ungültig.");
        if (!TelefonProtocolContract.TryInteger(value["captured_ms"], out var captured) || captured is < 0 or > 253402300799999)
            throw new InvalidDataException("Der Erfassungszeitpunkt ist ungültig.");
        if (!extended) return;
        Integer(value, "sdk_int", 1, 1000); Integer(value, "battery_temperature_deci_c", -1, 2000);
        var storageTotal = Integer(value, "storage_total_bytes", -1, 1L << 60);
        var storageAvailable = Integer(value, "storage_available_bytes", -1, 1L << 60);
        var memoryTotal = Integer(value, "memory_total_bytes", -1, 1L << 60);
        var memoryAvailable = Integer(value, "memory_available_bytes", -1, 1L << 60);
        Integer(value, "uptime_ms", -1, 253402300799999);
        if ((storageAvailable >= 0 && storageTotal >= 0 && storageAvailable > storageTotal) ||
            (memoryAvailable >= 0 && memoryTotal >= 0 && memoryAvailable > memoryTotal)) throw new InvalidDataException("Ungültige Ressourcenwerte.");
        Enum(value, "power_source", "ac", "usb", "wireless", "dock", "none", "unknown");
        Enum(value, "network_transport", "wifi", "cellular", "ethernet", "vpn", "bluetooth", "none");
        Boolean(value, "network_validated"); Boolean(value, "network_metered");
    }

    private static JsonObject Object(JsonNode node, HashSet<string> fields)
    {
        var value = node as JsonObject ?? throw new InvalidDataException("Der Gerätestatus ist kein Objekt.");
        if (value.Count != fields.Count || value.Any(item => !fields.Contains(item.Key)))
            throw new InvalidDataException("Der Gerätestatus enthält unbekannte oder fehlende Felder.");
        return value;
    }

    private static bool FieldsAre(JsonObject value, HashSet<string> fields) =>
        value.Count == fields.Count && value.All(item => fields.Contains(item.Key));

    private static long Integer(JsonObject value, string name, long minimum, long maximum)
    {
        if (!TelefonProtocolContract.TryInteger(value[name], out var number) || number < minimum || number > maximum)
            throw new InvalidDataException($"Das Feld {name} ist ungültig.");
        return number;
    }

    private static void Enum(JsonObject value, string name, params string[] allowed)
    {
        if (value[name] is not JsonValue node || !node.TryGetValue<string>(out var text) || !allowed.Contains(text, StringComparer.Ordinal))
            throw new InvalidDataException($"Das Feld {name} ist ungültig.");
    }

    private static void Boolean(JsonObject value, string name)
    {
        if (value[name] is not JsonValue node || !node.TryGetValue<bool>(out _))
            throw new InvalidDataException($"Das Feld {name} ist ungültig.");
    }

    private static void Uuid(JsonObject value, string name)
    {
        if (value[name] is not JsonValue node || !node.TryGetValue<string>(out var text) ||
            !Guid.TryParseExact(text, "D", out var id) || id.ToString("D") != text || id == Guid.Empty)
            throw new InvalidDataException($"Das Feld {name} ist ungültig.");
    }

    private static void Text(JsonObject value, string name, int minimum, int maximum)
    {
        if (value[name] is not JsonValue node || !node.TryGetValue<string>(out var text))
            throw new InvalidDataException($"Das Feld {name} ist ungültig.");
        var count = text.EnumerateRunes().Count();
        if (count < minimum || count > maximum || text.Any(char.IsControl))
            throw new InvalidDataException($"Das Feld {name} ist ungültig.");
    }
}
