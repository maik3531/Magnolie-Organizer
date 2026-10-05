using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

/// <summary>Optional v7 time data. Transport availability remains separate.</summary>
internal static class TimeSyncContract
{
    internal const int Version = 7;
    internal const int MaximumBody = 192 * 1024;
    internal const string Settings = "personal_sync.time_settings";
    internal const string Request = "personal_sync.time_request";
    internal const string Batch = "personal_sync.time_batch";
    private const long MaximumCounter = 9007199254740991;
    private const long MaximumMinute = 4223371679;
    private static readonly UTF8Encoding Utf8 = new(false, true);

    internal static bool IsKind(string? kind) => kind is Settings or Request or Batch;

    internal static JsonObject NewSettings(bool enabled = false, long revision = 1)
    {
        var value = new JsonObject { ["format"] = Version, ["scope"] = "time_tracking", ["enabled"] = enabled,
            ["revision"] = revision, ["epoch"] = Guid.NewGuid().ToString("D") };
        ValidateSettings(value); return value;
    }

    internal static JsonObject RequestBody(JsonObject local, JsonObject remote, string trigger = "manual")
    {
        ValidateSettings(local); ValidateSettings(remote);
        var body = new JsonObject { ["format"] = Version, ["trigger"] = trigger,
            ["sender_epoch"] = local["epoch"]!.DeepClone(), ["receiver_epoch"] = remote["epoch"]!.DeepClone(),
            ["sender_revision"] = local["revision"]!.DeepClone(), ["receiver_revision"] = remote["revision"]!.DeepClone() };
        Validate(Request, body, true); return body;
    }

    internal static IReadOnlyList<JsonObject> Batches(JsonObject local, JsonObject remote, JsonArray entries,
        JsonObject? calendar = null, string trigger = "manual", bool fromOrganizer = true)
    {
        if (entries.Count > 10000) Fail();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var raw in entries)
        {
            var entry = raw as JsonObject ?? throw new InvalidDataException("Invalid time entry.");
            ValidateRecord(entry, fromOrganizer); if (!ids.Add(Text(entry, "id"))) Fail();
        }
        var header = RequestBody(local, remote, trigger);
        JsonObject Empty() { var result = header.DeepClone().AsObject(); result["entries"] = new JsonArray(); return result; }
        var packet = Empty();
        if (calendar is not null) packet["calendar"] = calendar.DeepClone();
        Validate(Batch, packet, fromOrganizer);
        var packets = new List<JsonObject>();
        foreach (var entry in entries)
        {
            var candidate = packet.DeepClone().AsObject(); candidate["entries"]!.AsArray().Add(entry!.DeepClone());
            if (candidate["entries"]!.AsArray().Count > 32 || TelefonCrypto.Canonical(candidate).Length > MaximumBody)
            {
                if (packet["entries"]!.AsArray().Count > 0 || packet.ContainsKey("calendar")) packets.Add(packet);
                packet = Empty(); packet["entries"]!.AsArray().Add(entry!.DeepClone()); Validate(Batch, packet, fromOrganizer);
            }
            else packet = candidate;
        }
        if (packet["entries"]!.AsArray().Count > 0 || packet.ContainsKey("calendar") || packets.Count == 0) packets.Add(packet);
        return packets;
    }

    internal static void ValidateSettings(JsonObject body)
    {
        Exact(body, "format", "scope", "enabled", "revision", "epoch");
        Number(body, "format", Version, Version);
        if (Text(body, "scope") != "time_tracking") Fail();
        Bool(body, "enabled"); Number(body, "revision", 1, MaximumCounter); Uuid(Text(body, "epoch"));
    }

    internal static JsonObject AcceptSettings(JsonObject? current, JsonObject incoming)
    {
        ValidateSettings(incoming);
        if (current is not null)
        {
            ValidateSettings(current);
            if (JsonNode.DeepEquals(current, incoming)) return current;
            if (Number(incoming, "revision", 1, MaximumCounter) <= Number(current, "revision", 1, MaximumCounter) ||
                Text(incoming, "epoch") == Text(current, "epoch")) Fail();
        }
        return incoming.DeepClone().AsObject();
    }

    internal static void Validate(string kind, JsonObject body, bool fromOrganizer)
    {
        if (TelefonCrypto.Canonical(body).Length > MaximumBody) Fail();
        if (kind == Settings) { ValidateSettings(body); return; }
        var fields = new[] { "format", "sender_epoch", "receiver_epoch", "sender_revision", "receiver_revision", "trigger" };
        if (kind == Request) Exact(body, fields);
        else if (kind == Batch) Exact(body, fields.Concat(new[] { "entries" })
            .Concat(body.ContainsKey("calendar") ? new[] { "calendar" } : Array.Empty<string>()).ToArray());
        else Fail();
        Number(body, "format", Version, Version);
        if (Text(body, "trigger") is not ("manual" or "auto_wifi")) Fail();
        Uuid(Text(body, "sender_epoch")); Uuid(Text(body, "receiver_epoch"));
        Number(body, "sender_revision", 1, MaximumCounter); Number(body, "receiver_revision", 1, MaximumCounter);
        if (kind != Batch) return;
        var entries = body["entries"] as JsonArray ?? throw new InvalidDataException("Time entries missing.");
        if (entries.Count > 32) Fail();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var raw in entries)
        {
            var record = raw as JsonObject ?? throw new InvalidDataException("Invalid time record.");
            ValidateRecord(record, allowDeletion: fromOrganizer);
            if (!ids.Add(Text(record, "id"))) Fail();
        }
        if (body.ContainsKey("calendar"))
        {
            if (!fromOrganizer) Fail();
            ValidateCalendar(body["calendar"] as JsonObject ?? throw new InvalidDataException("Invalid time calendar."));
        }
    }

    internal static void ValidateRecord(JsonObject record, bool allowDeletion = false)
    {
        var fields = new[] { "id", "startMinute", "endMinute", "pauseMinute", "pauseMinutes", "zone", "type", "note", "modifiedMs", "deleted", "clock" };
        Exact(record, fields.Concat(record.ContainsKey("pausePlan") ? new[] { "pausePlan" } : Array.Empty<string>()).ToArray());
        Uuid(Text(record, "id"));
        var start = Number(record, "startMinute", 0, MaximumMinute);
        var pauses = Number(record, "pauseMinutes", 0, MaximumMinute - start);
        Number(record, "modifiedMs", 0, 253402300799999);
        if (record["endMinute"] is not null && pauses > Number(record, "endMinute", start, MaximumMinute) - start) Fail();
        if (record["pauseMinute"] is not null && (record["endMinute"] is not null ||
            pauses > Number(record, "pauseMinute", start, MaximumMinute) - start)) Fail();
        var deleted = Bool(record, "deleted");
        if (deleted && !allowDeletion) Fail();
        if (deleted && (start != 0 || record["endMinute"] is null || Number(record, "endMinute", 0, MaximumMinute) != 0 ||
            record["pauseMinute"] is not null || pauses != 0 || Text(record, "zone") != "UTC" ||
            Text(record, "type").Length > 0 || Text(record, "note").Length > 0 || record["pausePlan"] is not null)) Fail();
        Zone(Text(record, "zone", 160)); Text(record, "type", 120); Text(record, "note", 20000);
        var clock = record["clock"] as JsonObject ?? throw new InvalidDataException("Time clock missing.");
        if (clock.Count is < 1 or > 32) Fail();
        foreach (var pair in clock) { Uuid(pair.Key); Number(clock, pair.Key, 1, MaximumCounter); }
        ValidatePausePlan(record);
    }

    private static void ValidatePausePlan(JsonObject record)
    {
        if (record["pausePlan"] is null) return;
        if (record["endMinute"] is not null || Bool(record, "deleted")) Fail();
        var plan = record["pausePlan"] as JsonObject ?? throw new InvalidDataException("Pause plan required.");
        Exact(plan, "fixed", "manual", "replaced", "fixedEnds", "baseMinutes");
        var begin = Number(record, "startMinute", 0, MaximumMinute);
        Number(plan, "baseMinutes", 0, MaximumMinute - begin);
        var windows = plan["fixed"] as JsonArray ?? throw new InvalidDataException("Fixed pause windows required.");
        var manual = plan["manual"] as JsonArray ?? throw new InvalidDataException("Manual pause intervals required.");
        if (windows.Count > 16 || manual.Count > 10000) Fail();
        foreach (var raw in windows)
        {
            var item = raw as JsonObject ?? throw new InvalidDataException("Pause window required.");
            Exact(item, "start", "end");
            if (Number(item, "start", 0, 1439) == Number(item, "end", 0, 1439)) Fail();
        }
        var previous = begin;
        foreach (var raw in manual)
        {
            var item = raw as JsonObject ?? throw new InvalidDataException("Pause interval required.");
            Exact(item, "start", "end");
            var start = Number(item, "start", previous, MaximumMinute);
            previous = Number(item, "end", start, MaximumMinute);
            if (record["pauseMinute"] is not null && previous > Number(record, "pauseMinute", begin, MaximumMinute)) Fail();
        }
        var replaced = plan["replaced"] as JsonArray ?? throw new InvalidDataException("Replaced pause occurrences required.");
        if (replaced.Count > 60000) Fail();
        previous = -1;
        foreach (var raw in replaced)
        {
            var value = TelefonProtocolContract.Integer(raw);
            if (value <= previous || value > MaximumMinute) Fail();
            previous = value;
        }
        var ends = plan["fixedEnds"] as JsonObject ?? throw new InvalidDataException("Fixed pause endings required.");
        if (ends.Count > 60000) Fail();
        foreach (var pair in ends)
        {
            if (!long.TryParse(pair.Key, NumberStyles.None, CultureInfo.InvariantCulture, out var start) ||
                start < 0 || start > MaximumMinute || start.ToString(CultureInfo.InvariantCulture) != pair.Key) Fail();
            Number(ends, pair.Key, start, MaximumMinute);
        }
    }

    internal static void ValidateCalendar(JsonObject value)
    {
        Exact(value, "enabled", "country", "regions", "holidays");
        var enabled = Bool(value, "enabled");
        var country = Text(value, "country", 2);
        if ((enabled || country.Length > 0) && !Regex.IsMatch(country, "^[A-Z]{2}$")) Fail();
        Regions(value["regions"]);
        var days = value["holidays"] as JsonArray ?? throw new InvalidDataException("Holidays missing.");
        if (days.Count > 2048) Fail();
        foreach (var raw in days)
        {
            var day = raw as JsonObject ?? throw new InvalidDataException("Invalid holiday.");
            Exact(day, "date", "name", "country", "nationwide", "regions");
            if (!DateOnly.TryParseExact(Text(day, "date", 10), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _) ||
                Text(day, "name", 160).Length == 0 || !Regex.IsMatch(Text(day, "country", 2), "^[A-Z]{2}$")) Fail();
            Bool(day, "nationwide"); Regions(day["regions"]);
        }
    }

    internal static bool Allowed(JsonObject body, JsonObject? local, JsonObject? remote, bool localOwn, bool remoteOwn,
        bool freshControls, IReadOnlyCollection<int> localVersions, IReadOnlyCollection<int> remoteVersions)
    {
        if (!freshControls || !localOwn || !remoteOwn || local is null || remote is null ||
            !localVersions.Contains(Version) || !remoteVersions.Contains(Version)) return false;
        try
        {
            ValidateSettings(local); ValidateSettings(remote);
            return Bool(local, "enabled") && Bool(remote, "enabled") &&
                Text(body, "sender_epoch") == Text(remote, "epoch") && Text(body, "receiver_epoch") == Text(local, "epoch") &&
                Number(body, "sender_revision", 1, MaximumCounter) == Number(remote, "revision", 1, MaximumCounter) &&
                Number(body, "receiver_revision", 1, MaximumCounter) == Number(local, "revision", 1, MaximumCounter);
        }
        catch (Exception error) when (error is InvalidDataException or ArgumentException or InvalidOperationException) { return false; }
    }

    private static void Regions(JsonNode? node)
    {
        var values = node as JsonArray ?? throw new InvalidDataException("Regions missing.");
        if (values.Count > 64) Fail();
        foreach (var raw in values)
        {
            if (raw is not JsonValue value || !value.TryGetValue<string>(out var text) || text.Length is < 1 or > 64) Fail();
            else Utf8.GetByteCount(text);
        }
    }
    private static void Zone(string zone)
    {
        if (zone is "UTC" or "UT" or "GMT" or "Z") return;
        var offset = Regex.Match(zone, @"^(?:UTC|GMT|UT)?([+-])([0-9]{2})(?::([0-9]{2}))?$");
        if (offset.Success)
        {
            var hour = int.Parse(offset.Groups[2].Value, CultureInfo.InvariantCulture);
            var minute = offset.Groups[3].Success ? int.Parse(offset.Groups[3].Value, CultureInfo.InvariantCulture) : 0;
            if (hour > 18 || minute > 59 || hour == 18 && minute != 0) Fail();
        }
        else _ = TimeZoneInfo.FindSystemTimeZoneById(zone);
    }
    private static void Exact(JsonObject body, params string[] fields) => TelefonProtocolContract.ExactObject(body, fields);
    private static void Uuid(string value) { if (!TelefonProtocolContract.IsUuidV4(value)) Fail(); }
    private static string Text(JsonObject body, string key, int maximum = 20000)
    {
        if (body[key] is not JsonValue value || !value.TryGetValue<string>(out var text) || text.Length > maximum)
            throw new InvalidDataException("Time string required.");
        Utf8.GetByteCount(text); return text;
    }
    private static long Number(JsonObject body, string key, long minimum, long maximum)
    {
        var number = TelefonProtocolContract.Integer(body[key]);
        if (number < minimum || number > maximum) Fail();
        return number;
    }
    private static bool Bool(JsonObject body, string key) => body[key] is JsonValue value && value.TryGetValue<bool>(out var result)
        ? result : throw new InvalidDataException("Time boolean required.");
    private static void Fail() => throw new InvalidDataException("Invalid time synchronization data.");
}
