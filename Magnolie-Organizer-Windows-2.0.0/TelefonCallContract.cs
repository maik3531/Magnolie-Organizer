using System.Text.RegularExpressions;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static partial class TelefonCallContract
{
    private static readonly HashSet<string> DialErrors = new(StringComparer.Ordinal)
        { "none", "invalid_destination", "dial_unavailable", "not_granted", "permission_missing", "no_telephony", "os_restricted", "unknown" };
    private static readonly HashSet<string> AnswerErrors = new(StringComparer.Ordinal)
        { "none", "expired", "not_granted", "permission_missing", "not_ringing", "stale_call", "os_restricted", "unknown" };
    private static readonly HashSet<string> EndErrors = new(StringComparer.Ordinal)
        { "none", "expired", "not_granted", "permission_missing", "unsupported_api", "stale_call", "not_active", "os_restricted", "unknown" };

    internal static void Validate(string kind, JsonNode node)
    {
        var body = node as JsonObject ?? throw new InvalidDataException("Anrufinhalt erwartet.");
        switch (kind)
        {
            case "dial_request.command":
                Exact(body, "to", "client_ref"); Phone(body, "to"); Uuid4(body, "client_ref"); break;
            case "dial_request.result":
                Result(body, "client_ref", new HashSet<string>(StringComparer.Ordinal) { "submitted", "failed" }, DialErrors); break;
            case "incoming_call_state.event": ValidateIncoming(body); break;
            case "answer_call.command":
                Exact(body, "command_ref", "call_ref", "expected_state"); Uuid4(body, "command_ref"); Uuid4(body, "call_ref");
                if (String(body, "expected_state") != "ringing") throw new InvalidDataException("Erwarteter Anrufzustand ungültig."); break;
            case "answer_call.result":
                CallResult(body, new HashSet<string>(StringComparer.Ordinal) { "submitted", "already_answered", "failed" }, AnswerErrors); break;
            case "end_call.command":
                Exact(body, "command_ref", "call_ref", "expected_revision", "expected_state"); Uuid4(body, "command_ref"); Uuid4(body, "call_ref");
                Revision(body, "expected_revision"); if (String(body, "expected_state") != "offhook") throw new InvalidDataException("Erwarteter Anrufzustand ungültig."); break;
            case "end_call.result":
                CallResult(body, new HashSet<string>(StringComparer.Ordinal) { "submitted", "already_ended", "failed" }, EndErrors); break;
            default: throw new InvalidDataException("Unbekannte Anruf-Nachrichtenart.");
        }
    }

    private static void ValidateIncoming(JsonObject body)
    {
        Exact(body, "call_ref", "revision", "state", "direction", "number", "number_status", "started_ms", "offhook_ms", "ended_ms", "occurred_ms", "spam_status", "control_origin", "battery_percent", "battery_captured_ms");
        Uuid4(body, "call_ref"); Revision(body, "revision");
        var state = Enum(body, "state", "ringing", "offhook", "idle"); Enum(body, "direction", "incoming", "outgoing", "unknown");
        var numberStatus = Enum(body, "number_status", "available", "withheld", "unavailable", "permission_missing", "not_shared");
        var number = String(body, "number"); if ((numberStatus == "available") != PhoneNumber().IsMatch(number) || numberStatus != "available" && number.Length != 0) throw new InvalidDataException("Anrufnummer ungültig.");
        Enum(body, "spam_status", "suspected", "unknown"); Enum(body, "control_origin", "desktop", "phone", "unknown");
        var started = Timestamp(body, "started_ms"); var offhook = Timestamp(body, "offhook_ms"); var ended = Timestamp(body, "ended_ms"); var occurred = Timestamp(body, "occurred_ms");
        var battery = Integer(body, "battery_percent", -1, 100); var captured = Timestamp(body, "battery_captured_ms");
        if (started == 0 || started > occurred || offhook > occurred || ended > occurred || (state == "idle") != (ended > 0) ||
            state == "offhook" && offhook == 0 || offhook > 0 && offhook < started || ended > 0 && ended < Math.Max(started, offhook) ||
            captured > occurred || (battery < 0) != (captured == 0)) throw new InvalidDataException("Anrufzeitachse ungültig.");
    }

    private static void Result(JsonObject body, string reference, HashSet<string> states, HashSet<string> errors)
    {
        Exact(body, reference, "state", "error", "occurred_ms"); Uuid4(body, reference);
        ValidateResult(body, states, errors);
    }
    private static void CallResult(JsonObject body, HashSet<string> states, HashSet<string> errors)
    {
        Exact(body, "command_ref", "call_ref", "state", "error", "occurred_ms"); Uuid4(body, "command_ref"); Uuid4(body, "call_ref");
        ValidateResult(body, states, errors);
    }
    private static void ValidateResult(JsonObject body, HashSet<string> states, HashSet<string> errors)
    {
        var state = String(body, "state"); var error = String(body, "error"); Timestamp(body, "occurred_ms");
        if (!states.Contains(state) || !errors.Contains(error) || (state == "failed") != (error != "none")) throw new InvalidDataException("Anrufergebnis ungültig.");
    }
    private static string Enum(JsonObject body, string name, params string[] values)
    { var value = String(body, name); if (!values.Contains(value, StringComparer.Ordinal)) throw new InvalidDataException("Auswahlwert ungültig."); return value; }
    private static long Timestamp(JsonObject body, string name) => Integer(body, name, 0, 253402300799999);
    private static long Integer(JsonObject body, string name, long minimum, long maximum)
    { if (!TelefonProtocolContract.TryInteger(body[name], out var value) || value < minimum || value > maximum) throw new InvalidDataException("Ganzzahl ungültig."); return value; }
    private static void Revision(JsonObject body, string name) => Integer(body, name, 1, long.MaxValue);
    private static string String(JsonObject body, string name) => TelefonMessagingContract.String(body, name);
    private static void Uuid4(JsonObject body, string name) => TelefonMessagingContract.Uuid(body, name, true);
    private static void Phone(JsonObject body, string name) { if (!PhoneNumber().IsMatch(String(body, name))) throw new InvalidDataException("Rufnummer ungültig."); }
    private static void Exact(JsonObject body, params string[] names) => TelefonProtocolContract.ExactObject(body, names);

    [GeneratedRegex("^\\+[0-9]{3,15}$", RegexOptions.CultureInvariant)]
    private static partial Regex PhoneNumber();
}
