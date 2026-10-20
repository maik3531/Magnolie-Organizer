using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class TimeControlContract
{
    internal const int Version = 13;
    internal const int MaximumWire = 192 * 1024;
    internal const string RequestKind = "time_tracking.control_request", ReportKind = "time_tracking.control_report";
    private static readonly string[] RequestFields = ["format", "request_id", "action", "operation_id", "expected_revision", "restore_epoch", "entry_id", "activity", "note"];
    private static readonly string[] ReportFields = ["format", "request_id", "operation_id", "status", "error", "restore_epoch", "revision", "enabled", "entries", "paused",
        "server_minute", "operation_applied", "persisted", "applied_entry_id", "applied_clock", "runtime_request"];
    internal static JsonObject Request(string requestId, string action = "read", string operationId = "", string expectedRevision = "",
        string restoreEpoch = "", string entryId = "", string activity = "", string note = "")
    {
        var body = new JsonObject { ["format"] = Version, ["request_id"] = requestId, ["action"] = action, ["operation_id"] = operationId,
            ["expected_revision"] = expectedRevision, ["restore_epoch"] = restoreEpoch, ["entry_id"] = entryId, ["activity"] = activity, ["note"] = note };
        ValidateRequest(body); return body;
    }
    internal static void ValidateRequest(JsonObject body)
    {
        Exact(body, RequestFields); Number(body, "format", Version, Version); Uuid(Text(body, "request_id")); Text(body, "restore_epoch", 256);
        var action = Text(body, "action");
        if (action == "read")
        {
            if (new[] { "operation_id", "expected_revision", "restore_epoch", "entry_id", "activity", "note" }.Any(key => Text(body, key).Length != 0)) Fail();
        }
        else
        {
            if (action is not ("start" or "pause" or "resume" or "finish")) Fail();
            Uuid(Text(body, "operation_id")); Hash(Text(body, "expected_revision")); Text(body, "activity", 120); Text(body, "note", 20000);
            if (action == "start") { if (Text(body, "entry_id").Length != 0) Fail(); }
            else { Uuid(Text(body, "entry_id")); if (Text(body, "activity").Length != 0 || Text(body, "note").Length != 0) Fail(); }
        }
    }
    internal static void ValidateReport(JsonObject body)
    {
        Exact(body, ReportFields); Number(body, "format", Version, Version); Uuid(Text(body, "request_id"));
        var operation = Text(body, "operation_id"); if (operation.Length != 0) Uuid(operation);
        var status = Text(body, "status"); var error = Text(body, "error");
        if (status is not ("ok" or "duplicate" or "rejected") || error is not ("none" or "not_granted" or "unsupported_feature" or "conflict" or "no_running_entry" or "already_running" or "save_failed" or "protocol" or "unknown")) Fail();
        Text(body, "restore_epoch", 256); var enabled = Bool(body, "enabled"); var paused = Bool(body, "paused");
        var applied = Bool(body, "operation_applied"); var persisted = Bool(body, "persisted"); var minute = Number(body, "server_minute", 0, TimeSyncContract.MaximumMinute);
        var runtime = Text(body, "runtime_request"); if (runtime is not ("none" or "requested" or "failed")) Fail();
        if (body["entries"] is not JsonArray entries || entries.Count > 1 || body["applied_clock"] is not JsonObject clock) throw new InvalidDataException("invalid_timer_state");
        if (status == "rejected")
        {
            if (error == "none" || Text(body, "restore_epoch").Length != 0 || Text(body, "revision").Length != 0 || enabled || paused || applied || persisted ||
                entries.Count != 0 || clock.Count != 0 || minute != 0 || Text(body, "applied_entry_id").Length != 0 || runtime != "none") Fail();
            return;
        }
        Hash(Text(body, "revision")); if (error != "none" || entries.Count == 0 && paused) Fail();
        foreach (var raw in entries)
        {
            if (raw is not JsonObject record) throw new InvalidDataException("invalid_timer_record");
            TimeSyncContract.ValidateRecord(record);
            if (Bool(record, "deleted") || record["endMinute"] is not null) Fail();
        }
        if (operation.Length == 0)
        {
            if (status != "ok" || applied || persisted || Text(body, "applied_entry_id").Length != 0 || clock.Count != 0 || runtime != "none") Fail();
        }
        else
        {
            if (!applied || !persisted || clock.Count is < 1 or > 32) Fail(); Uuid(Text(body, "applied_entry_id"));
            foreach (var (actor, _) in clock) { Uuid(actor); Number(clock, actor, 1, TimeSyncContract.MaximumCounter); }
        }
    }
    private static void Exact(JsonObject value, string[] fields) { if (!value.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(fields)) Fail(); }
    private static string Text(JsonObject value, string key, int maximum = 20000)
    {
        if (value[key] is not JsonValue node || !node.TryGetValue<string>(out var text) || text.Length > maximum) throw new InvalidDataException("invalid_timer_text");
        return text;
    }
    private static bool Bool(JsonObject value, string key)
    { if (value[key] is JsonValue node && node.TryGetValue<bool>(out var result)) return result; throw new InvalidDataException("invalid_timer_boolean"); }
    private static long Number(JsonObject value, string key, long minimum, long maximum)
    { var result = TelefonProtocolContract.Integer(value[key]); if (result < minimum || result > maximum) Fail(); return result; }
    private static void Hash(string value) { if (!Regex.IsMatch(value, "^[a-f0-9]{64}$")) Fail(); }
    private static void Uuid(string value) { if (!Regex.IsMatch(value, "^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")) Fail(); }
    private static void Fail() => throw new InvalidDataException("invalid_timer_control_schema");
}
