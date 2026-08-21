using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal static class ThunderbirdCalendarImporter
{
    private readonly record struct ItemKey(string Calendar, string Item, long? Recurrence, string RecurrenceZone);
    private readonly record struct Property(string Name, string Value);
    private readonly record struct Parameter(string Property, string Name, string Value);

    internal static ExchangeImportResult Parse(string path)
    {
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path, Mode = SqliteOpenMode.ReadOnly
        }.ToString());
        connection.Open();
        var tables = Rows(connection, "sqlite_master", "type='table'").Select(row => Text(row, "name")).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var properties = new Dictionary<ItemKey, List<Property>>();
        if (tables.Contains("cal_properties"))
            foreach (var row in Rows(connection, "cal_properties"))
            {
                var value = Text(row, "value"); if (value.Length == 0) continue;
                var key = Key(row); if (!properties.TryGetValue(key, out var values)) properties[key] = values = new();
                values.Add(new Property(Text(row, "key").ToUpperInvariant(), value));
            }
        var parameters = new Dictionary<ItemKey, List<Parameter>>();
        if (tables.Contains("cal_parameters"))
            foreach (var row in Rows(connection, "cal_parameters"))
            {
                var key = Key(row); if (!parameters.TryGetValue(key, out var values)) parameters[key] = values = new();
                values.Add(new Parameter(Text(row, "key1").ToUpperInvariant(),
                    Text(row, "key2").ToUpperInvariant(), Text(row, "value")));
            }
        var extra = new Dictionary<ItemKey, List<string>>();
        foreach (var table in new[] { "cal_recurrence", "cal_alarms", "cal_attendees", "cal_attachments", "cal_relations" })
            if (tables.Contains(table)) foreach (var row in Rows(connection, table))
            {
                var value = Text(row, "icalString"); if (value.Length == 0) continue;
                var key = Key(row); if (!extra.TryGetValue(key, out var values)) extra[key] = values = new(); values.Add(value);
            }

        var result = Empty();
        foreach (var table in new[] { "cal_events", "cal_todos" })
        {
            if (!tables.Contains(table)) continue;
            foreach (var row in Rows(connection, table))
            {
                var key = Key(row); var component = table == "cal_events" ? "VEVENT" : "VTODO"; var flags = Long(row, "flags");
                var lines = new List<string> { "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:" + component, "UID:" + Escape(Text(row, "id")) };
                if (component == "VEVENT")
                {
                    var allDay = (flags & 8) != 0;
                    lines.Add(DateLine("DTSTART", Long(row, "event_start"), Text(row, "event_start_tz"), allDay));
                    lines.Add(DateLine("DTEND", Long(row, "event_end"), Text(row, "event_end_tz"), allDay));
                    lines.Add("SUMMARY:" + Escape(Text(row, "title")));
                    if (Text(row, "privacy").Equals("PRIVATE", StringComparison.OrdinalIgnoreCase)) lines.Add("CLASS:PRIVATE");
                    if (Text(row, "ical_status") is { Length: > 0 } status) lines.Add("STATUS:" + status);
                }
                else
                {
                    lines.Add("SUMMARY:" + Escape(Text(row, "title")));
                    if (row.ContainsKey("todo_due") && row["todo_due"] is not null) lines.Add(DateLine("DUE", Long(row, "todo_due"), Text(row, "todo_due_tz"), (flags & 8) != 0));
                    if (Text(row, "ical_status") is { Length: > 0 } status) lines.Add("STATUS:" + status);
                    var complete = row.ContainsKey("percent_complete") ? Long(row, "percent_complete") : Long(row, "todo_complete");
                    if (complete > 0) lines.Add("PERCENT-COMPLETE:" + complete);
                    if (Long(row, "priority") > 0) lines.Add("PRIORITY:" + Long(row, "priority"));
                }
                if (properties.TryGetValue(key, out var props))
                    foreach (var property in props)
                    {
                        var suffix = parameters.TryGetValue(key, out var args)
                            ? string.Concat(args.Where(value => value.Property.Equals(property.Name, StringComparison.OrdinalIgnoreCase) &&
                                value.Name.Length > 0 && value.Value.IndexOfAny(['\r', '\n']) < 0)
                                .Select(value => $";{value.Name}={value.Value}")) : "";
                        lines.Add(property.Name + suffix + ":" + property.Value);
                    }
                if (extra.TryGetValue(key, out var extras)) lines.AddRange(extras);
                if (key.Recurrence is not null) lines.Add(DateLine("RECURRENCE-ID", key.Recurrence.Value, key.RecurrenceZone, (flags & 512) != 0));
                lines.Add("END:" + component); lines.Add("END:VCALENDAR");
                var parsed = ExchangeCodec.ParseIcs(string.Join("\r\n", lines) + "\r\n");
                foreach (var value in parsed.Termine.Concat(parsed.Jahrestage).Concat(parsed.Aufgaben).OfType<JsonObject>())
                    value["syncKalenderUid"] = key.Calendar;
                Append(result.Termine, parsed.Termine); Append(result.Jahrestage, parsed.Jahrestage); Append(result.Aufgaben, parsed.Aufgaben);
                result = result with { Uebersprungen = result.Uebersprungen + parsed.Uebersprungen,
                    Wiederholend = result.Wiederholend + parsed.Wiederholend };
            }
        }
        return result;
    }

    internal static ExchangeImportResult ParseProfiles(IEnumerable<string> paths, out int read)
    {
        var result = Empty(); read = 0;
        foreach (var path in paths)
        {
            try
            {
                if (!File.Exists(path) || new FileInfo(path).Length > 512L * 1024 * 1024) continue;
                var parsed = Parse(path); read++;
                Append(result.Termine, parsed.Termine); Append(result.Jahrestage, parsed.Jahrestage);
                Append(result.Aufgaben, parsed.Aufgaben);
                result = result with { Uebersprungen = result.Uebersprungen + parsed.Uebersprungen,
                    Wiederholend = result.Wiederholend + parsed.Wiederholend };
            }
            catch (Exception) { result = result with { Uebersprungen = result.Uebersprungen + 1 }; }
        }
        return result;
    }

    private static List<Dictionary<string, object?>> Rows(SqliteConnection connection, string table, string where = "")
    {
        if (!System.Text.RegularExpressions.Regex.IsMatch(table, "^[A-Za-z_][A-Za-z0-9_]*$")) throw new InvalidDataException();
        using var command = connection.CreateCommand(); command.CommandText = $"SELECT * FROM \"{table}\"" + (where.Length > 0 ? " WHERE " + where : "");
        using var reader = command.ExecuteReader(); var rows = new List<Dictionary<string, object?>>();
        while (reader.Read())
        {
            var row = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
            for (var index = 0; index < reader.FieldCount; index++) row[reader.GetName(index)] = reader.IsDBNull(index) ? null : reader.GetValue(index);
            rows.Add(row);
        }
        return rows;
    }

    private static ItemKey Key(Dictionary<string, object?> row) => new(Text(row, "cal_id"), Text(row, row.ContainsKey("item_id") ? "item_id" : "id"),
        row.TryGetValue("recurrence_id", out var recurrence) && recurrence is not null ? Convert.ToInt64(recurrence) : null, Text(row, "recurrence_id_tz"));
    private static string Text(Dictionary<string, object?> row, string name) => row.TryGetValue(name, out var value) && value is not null
        ? value is byte[] bytes ? Encoding.UTF8.GetString(bytes) : Convert.ToString(value) ?? "" : "";
    private static long Long(Dictionary<string, object?> row, string name) => row.TryGetValue(name, out var value) && value is not null ? Convert.ToInt64(value) : 0;
    private static string DateLine(string name, long microseconds, string zone, bool allDay)
    {
        var value = DateTimeOffset.FromUnixTimeMilliseconds(microseconds / 1000).UtcDateTime;
        if (allDay) return $"{name};VALUE=DATE:{value:yyyyMMdd}";
        if (zone.Equals("UTC", StringComparison.OrdinalIgnoreCase)) return $"{name}:{value:yyyyMMdd'T'HHmmss'Z'}";
        if (zone.Length > 0 && !zone.Equals("floating", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                var source = TimeZoneInfo.FindSystemTimeZoneById(zone);
                value = TimeZoneInfo.ConvertTimeFromUtc(value, source);
            }
            catch (TimeZoneNotFoundException) when (TimeZoneInfo.TryConvertIanaIdToWindowsId(zone, out var windowsId))
            {
                value = TimeZoneInfo.ConvertTimeFromUtc(value, TimeZoneInfo.FindSystemTimeZoneById(windowsId));
            }
        }
        return name + (zone.Length > 0 && !zone.Equals("floating", StringComparison.OrdinalIgnoreCase) ? ";TZID=" + zone : "") + $":{value:yyyyMMdd'T'HHmmss}";
    }
    private static string Escape(string value) => value.Replace("\\", "\\\\").Replace("\r\n", "\\n").Replace("\n", "\\n").Replace(",", "\\,").Replace(";", "\\;");
    private static ExchangeImportResult Empty() => new(new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray());
    private static void Append(JsonArray target, JsonArray source) { foreach (var node in source) target.Add(node?.DeepClone()); }
}
