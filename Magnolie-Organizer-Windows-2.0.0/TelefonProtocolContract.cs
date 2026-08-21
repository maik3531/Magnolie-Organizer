using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Zustand des Bluetooth-RFCOMM-Transports. Der Wert wird zur Laufzeit von der
/// Windows-Anbindung gesetzt, sobald ein Bluetooth-Funkgerät gefunden und der
/// RFCOMM-Dienst tatsächlich veröffentlicht wurde. Ohne diese Meldung – etwa im
/// portablen Testlauf oder auf einem Rechner ohne Bluetooth – bleibt der
/// Transport ausdrücklich nicht verfügbar.
/// </summary>
internal static class TelefonBluetoothSupport
{
    private static volatile string state = "os_restricted";
    private static volatile string detail = DefaultBlocker;

    internal const string DefaultBlocker =
        "Bluetooth ist auf diesem Rechner nicht nutzbar. Der Organizer veröffentlicht den " +
        "RFCOMM-Dienst nur, wenn Windows ein eingeschaltetes Bluetooth-Funkgerät meldet und " +
        "das Telefon bereits in den Windows-Bluetooth-Einstellungen gekoppelt ist.";

    internal static bool Available => state == "available";
    internal static string Reason => state;
    internal static string Blocker => detail;

    /// <summary>Meldet den geprüften Zustand des RFCOMM-Transports.</summary>
    internal static void Report(bool available, string reason, string blocker)
    {
        state = available ? "available" : reason;
        detail = available ? "" : blocker.Length > 0 ? blocker : DefaultBlocker;
    }
}

internal static class TelefonProtocolContract
{
    internal static readonly string[] CapabilityNames = ["answer_call", "device_status", "dial_request", "end_call", "incoming_call_number", "incoming_call_state",
        "personal_deletions_sync", "personal_notes_sync", "personal_tasks_sync", "selected_notifications_readonly", "transport.bluetooth_rfcomm"];
    internal static readonly string[] GrantNames = ["answer_call", "device_status", "dial_request", "end_call", "incoming_call_number", "incoming_call_state",
        "personal_deletions_sync", "personal_notes_sync", "personal_tasks_sync", "selected_notifications_readonly"];
    internal static readonly HashSet<string> PersonalKinds = new(StringComparer.Ordinal) { "personal_sync.settings", "personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result", "personal_sync.deletion_proposals", "personal_sync.deletion_decision" };
    private static readonly HashSet<string> Reasons = new(StringComparer.Ordinal) { "available", "not_implemented", "no_hardware", "disabled", "permission_missing", "os_restricted" };

    internal static JsonObject DesktopCapabilities() => new() { ["revision"] = 1, ["items"] = new JsonObject
    {
        ["answer_call"] = Capability(true, "available", 1), ["device_status"] = Capability(true, "available", 1, 2),
        ["dial_request"] = Capability(true, "available", 1), ["end_call"] = Capability(true, "available", 1),
        ["incoming_call_number"] = Capability(true, "available", 1), ["incoming_call_state"] = Capability(true, "available", 2),
        ["personal_deletions_sync"] = Capability(true, "available", 1), ["personal_notes_sync"] = Capability(true, "available", 1, 2),
        ["personal_tasks_sync"] = Capability(true, "available", 1), ["selected_notifications_readonly"] = Capability(false, "not_implemented", 1),
        ["transport.bluetooth_rfcomm"] = Capability(TelefonBluetoothSupport.Available, TelefonBluetoothSupport.Reason, 1)
    }};

    internal static JsonObject DesktopGrants() => new()
    {
        ["answer_call"] = false, ["device_status"] = true, ["dial_request"] = true, ["end_call"] = false,
        ["incoming_call_number"] = false, ["incoming_call_state"] = false, ["personal_deletions_sync"] = false,
        ["personal_notes_sync"] = false, ["personal_tasks_sync"] = false, ["selected_notifications_readonly"] = false
    };

    internal static long ValidateCapabilities(JsonNode node)
    {
        var body = ExactObject(node, "revision", "items"); var revision = PositiveRevision(body, "revision");
        var items = body["items"] as JsonObject ?? throw new InvalidDataException("Capability-Objekt erwartet.");
        if (items.Count != CapabilityNames.Length || CapabilityNames.Any(name => !items.ContainsKey(name))) throw new InvalidDataException("Capability-Menge ungültig.");
        foreach (var item in items)
        {
            var value = ExactObject(item.Value!, "available", "reason", "versions");
            if (value["available"] is not JsonValue availableNode || !availableNode.TryGetValue<bool>(out var available) ||
                value["reason"] is not JsonValue reasonNode || !reasonNode.TryGetValue<string>(out var reason) || !Reasons.Contains(reason) || available != (reason == "available") ||
                value["versions"] is not JsonArray versions || versions.Count is < 1 or > 16 || versions.Select(CapabilityVersion).Distinct().Count() != versions.Count)
                throw new InvalidDataException("Ungültige Capability.");
        }
        return revision;
    }
    internal static long ValidateGrants(JsonNode node)
    {
        var body = ExactObject(node, "revision", "grants"); var revision = PositiveRevision(body, "revision"); var grants = ExactObject(body["grants"]!, GrantNames);
        foreach (var name in GrantNames) if (grants[name] is not JsonValue value || !value.TryGetValue<bool>(out _)) throw new InvalidDataException("Ungültiger Grant.");
        return revision;
    }
    internal static bool IsDesktopGranted(string name) => name is "device_status" or "dial_request";
    internal static bool TryInteger(JsonNode? node, out long number)
    {
        if (node is JsonValue value)
        {
            if (value.TryGetValue<long>(out number)) return true;
            if (value.TryGetValue<int>(out var integer)) { number = integer; return true; }
        }
        number = 0; return false;
    }
    internal static long Integer(JsonNode? node) { if (!TryInteger(node, out var number)) throw new InvalidDataException("Ganzzahl erwartet."); return number; }
    internal static JsonObject ExactObject(JsonNode node, params string[] fields)
    { var value = node as JsonObject ?? throw new InvalidDataException("Objekt erwartet."); var expected = fields.ToHashSet(StringComparer.Ordinal); if (value.Count != expected.Count || value.Any(item => !expected.Contains(item.Key))) throw new InvalidDataException("Unbekannte oder fehlende Felder."); return value; }
    internal static bool IsUuidV4(string? text) => Guid.TryParseExact(text, "D", out var id) && id != Guid.Empty && id.ToString("D") == text && text![14] == '4' && "89ab".Contains(text[19]);
    private static long PositiveRevision(JsonObject value, string name) { if (!TryInteger(value[name], out var revision) || revision < 1) throw new InvalidDataException("Ungültige Revision."); return revision; }
    private static int CapabilityVersion(JsonNode? value) { if (!TryInteger(value, out var version) || version is < 1 or > 65_535) throw new InvalidDataException("Ungültige Capability-Fassung."); return (int)version; }
    private static JsonObject Capability(bool available, string reason, params int[] versions) => new() { ["available"] = available, ["reason"] = reason, ["versions"] = new JsonArray(versions.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray()) };
}

internal static class TelefonMessageContract
{
    private static readonly HashSet<string> Kinds = new(StringComparer.Ordinal) { "capabilities.update", "grants.update", "device_status.request", "device_status.report",
        "dial_request.command", "dial_request.result", "selected_notifications_readonly.event", "incoming_call_state.event", "answer_call.command", "answer_call.result", "end_call.command", "end_call.result" };
    internal static void ValidateMessage(JsonObject message, long now, bool receiving)
    {
        var id = "00000000-0000-0000-0000-000000000000";
        try
        {
            TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
            id = TelefonMessagingContract.String(message, "message_id"); var kind = TelefonMessagingContract.String(message, "kind");
            if (TelefonMessagingContract.String(message, "type") != "message" || !TelefonProtocolContract.TryInteger(message["v"], out var version) || version != 1 ||
                !TelefonProtocolContract.IsUuidV4(id) || (!Kinds.Contains(kind) && !TelefonProtocolContract.PersonalKinds.Contains(kind)) ||
                !TelefonProtocolContract.TryInteger(message["created_ms"], out var created) || created < 0 || !TelefonProtocolContract.TryInteger(message["expires_ms"], out var expires) ||
                expires <= created || expires - created > TelefonStore.MaximumMessageTtlMs || message["body"] is not JsonObject body) throw new InvalidDataException();
            if (receiving && (expires < now - 300_000 || created > now + 300_000)) throw new TelefonMessageException(id, "expired");
            var ttl = expires - created;
            if (kind == "capabilities.update") { Maximum(ttl, 86_400_000); TelefonProtocolContract.ValidateCapabilities(body); }
            else if (kind == "grants.update") { Maximum(ttl, 86_400_000); TelefonProtocolContract.ValidateGrants(body); }
            else if (kind == "device_status.request") { Maximum(ttl, 60_000); TelefonDeviceStatusContract.ValidateRequest(body); }
            else if (kind == "device_status.report") { Maximum(ttl, 300_000); TelefonDeviceStatusContract.ValidateReport(body); }
            else if (kind == "selected_notifications_readonly.event") { Maximum(ttl, 86_400_000); TelefonMessagingContract.Validate(kind, body); }
            else if (TelefonProtocolContract.PersonalKinds.Contains(kind)) { Maximum(ttl, kind == "personal_sync.request" ? 3_600_000 : 86_400_000); PersonalSyncContract.ValidateBody(kind, body); }
            else { Maximum(ttl, kind is "answer_call.command" or "end_call.command" ? 10_000 : 60_000); TelefonCallContract.Validate(kind, body); }
            if (TelefonCrypto.Canonical(message).Length > 262_144) throw new TelefonMessageException(id, "too_large");
        }
        catch (TelefonMessageException) { throw; }
        catch (Exception error) when (error is InvalidDataException or InvalidOperationException or FormatException) { throw new TelefonMessageException(id, "invalid_schema"); }
    }
    private static void Maximum(long value, long maximum) { if (value > maximum) throw new InvalidDataException(); }
}

internal sealed class TelefonMessageException(string messageId, string error) : IOException(error)
{
    internal string MessageId { get; } = messageId;
    internal string Error { get; } = error;
}
