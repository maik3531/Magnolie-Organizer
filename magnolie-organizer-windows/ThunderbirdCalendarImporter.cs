using System.Text;
using System.Text.Json.Nodes;
using System.Security.Cryptography;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal static class ThunderbirdCalendarImporter
{
    private readonly record struct ItemKey(string Calendar, string Item, long? Recurrence, string RecurrenceZone);
    private readonly record struct Property(string Name, string Value);
    private readonly record struct Parameter(string Property, string Name, string Value);

    internal static ExchangeImportResult Parse(string path) => Parse(path, ProfileId(path));

    internal static IReadOnlyList<string> DiscoverProfiles(string thunderbirdRoot)
    {
        var profiles = new List<string>();
        void Add(string path)
        {
            try
            {
                var full = Path.GetFullPath(path);
                if (Directory.Exists(full) && !profiles.Contains(full, StringComparer.OrdinalIgnoreCase) && profiles.Count < 32)
                    profiles.Add(full);
            }
            catch (Exception error) when (error is ArgumentException or IOException or UnauthorizedAccessException) { }
        }
        var ini = Path.Combine(thunderbirdRoot, "profiles.ini");
        try
        {
            if (File.Exists(ini) && new FileInfo(ini).Length <= 1024 * 1024)
            {
                string? path = null; var relative = true;
                void Flush() { if (!string.IsNullOrWhiteSpace(path)) Add(relative ? Path.Combine(thunderbirdRoot, path) : path); path = null; relative = true; }
                foreach (var raw in File.ReadLines(ini))
                {
                    var line = raw.Trim();
                    if (line.StartsWith('[') && line.EndsWith(']')) { Flush(); continue; }
                    var split = line.IndexOf('='); if (split < 1) continue;
                    var name = line[..split].Trim(); var value = line[(split + 1)..].Trim();
                    if (name.Equals("Path", StringComparison.OrdinalIgnoreCase)) path = value;
                    else if (name.Equals("IsRelative", StringComparison.OrdinalIgnoreCase)) relative = value == "1";
                }
                Flush();
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        var standard = Path.Combine(thunderbirdRoot, "Profiles");
        try { if (profiles.Count == 0 && Directory.Exists(standard)) foreach (var directory in Directory.EnumerateDirectories(standard).Take(32)) Add(directory); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        return profiles;
    }

    internal static IReadOnlyList<string> DiscoverCalendarStores(IEnumerable<string> profiles) =>
        profiles.Take(32).SelectMany(profile => new[]
        {
            Path.Combine(profile, "calendar-data", "local.sqlite"),
            Path.Combine(profile, "calendar-data", "cache.sqlite")
        }).Where(File.Exists).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();

    internal static ExchangeImportResult ParseAddressBooks(IEnumerable<string> profiles, out int read)
    {
        var result = Empty(); read = 0;
        foreach (var profile in profiles.Take(32))
        {
            IEnumerable<string> books;
            try { books = Directory.EnumerateFiles(profile, "*.sqlite").Where(path =>
                Path.GetFileName(path).Equals("abook.sqlite", StringComparison.OrdinalIgnoreCase) ||
                Path.GetFileName(path).Equals("history.sqlite", StringComparison.OrdinalIgnoreCase) ||
                Path.GetFileName(path).StartsWith("abook-", StringComparison.OrdinalIgnoreCase)).Take(64).ToArray(); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { continue; }
            foreach (var book in books)
            {
                try
                {
                    if (new FileInfo(book).Length > 512L * 1024 * 1024) continue;
                    var parsed = ParseAddressBook(book);
                    if (parsed.Kontakte.Count > 0) read++;
                    Append(result.Kontakte, parsed.Kontakte); Append(result.Geburtstage, parsed.Geburtstage);
                    result = result with { Uebersprungen = result.Uebersprungen + parsed.Uebersprungen };
                }
                catch (Exception) { result = result with { Uebersprungen = result.Uebersprungen + 1 }; }
            }
        }
        return result;
    }

    internal static ExchangeImportResult ParseAddressBook(string path)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly }.ToString());
        connection.Open();
        var cards = new Dictionary<string, Dictionary<string, List<string>>>(StringComparer.Ordinal);
        foreach (var row in Rows(connection, "properties").Take(200000))
        {
            var card = Text(row, "card"); var name = Text(row, "name"); var value = Text(row, "value");
            if (card.Length == 0 || name.Length == 0 || value.Length == 0) continue;
            if (!cards.TryGetValue(card, out var properties)) cards[card] = properties = new(StringComparer.OrdinalIgnoreCase);
            if (!properties.TryGetValue(name, out var values)) properties[name] = values = new(); values.Add(value);
        }
        var source = ProfileId(path); var text = new StringBuilder();
        foreach (var (card, properties) in cards.Take(100000))
        {
            string First(string name) => properties.TryGetValue(name, out var values) ? values.FirstOrDefault()?.Trim() ?? "" : "";
            IEnumerable<string> Values(string name) => properties.TryGetValue(name, out var values) ? values : [];
            var last = First("LastName"); var first = First("FirstName"); var display = First("DisplayName"); var company = First("Company");
            var lines = new List<string> { "BEGIN:VCARD", "VERSION:3.0", $"N:{Escape(last)};{Escape(first)};;;",
                "FN:" + Escape(display.Length > 0 ? display : string.Join(' ', new[] { first, last }.Where(value => value.Length > 0))) };
            if (company.Length > 0) lines.Add("ORG:" + Escape(company));
            foreach (var (property, vcard) in new[] { ("JobTitle", "TITLE"), ("Department", "X-THUNDERBIRD-DEPARTMENT"),
                ("NickName", "NICKNAME"), ("WebPage1", "URL;TYPE=WORK"), ("WebPage2", "URL;TYPE=HOME"),
                ("Custom1", "X-THUNDERBIRD-CUSTOM1"), ("Custom2", "X-THUNDERBIRD-CUSTOM2"),
                ("Custom3", "X-THUNDERBIRD-CUSTOM3"), ("Custom4", "X-THUNDERBIRD-CUSTOM4") })
                if (First(property) is { Length: > 0 } value) lines.Add(vcard + ":" + Escape(value));
            foreach (var email in Values("PrimaryEmail").Concat(Values("SecondEmail"))) lines.Add("EMAIL:" + Escape(email));
            foreach (var (name, types) in new[] { ("HomePhone", "HOME,VOICE"), ("WorkPhone", "WORK,VOICE"), ("CellularNumber", "CELL"),
                ("FaxNumber", "FAX"), ("HomeFax", "HOME,FAX"), ("WorkFax", "WORK,FAX"), ("PagerNumber", "PAGER"), ("OtherNumber", "VOICE") })
                foreach (var number in Values(name)) lines.Add($"TEL;TYPE={types}:{Escape(number)}");
            foreach (var (prefix, type) in new[] { ("Home", "HOME"), ("Work", "WORK") })
            {
                var street = string.Join('\n', new[] { First(prefix + "Address"), First(prefix + "Address2") }.Where(value => value.Length > 0));
                var city = First(prefix + "City"); var state = First(prefix + "State"); var zip = First(prefix + "ZipCode"); var country = First(prefix + "Country");
                if (street.Length + city.Length + state.Length + zip.Length + country.Length > 0) lines.Add($"ADR;TYPE={type}:;;{Escape(street)};{Escape(city)};{Escape(state)};{Escape(zip)};{Escape(country)}");
            }
            if (First("Notes") is { Length: > 0 } note) lines.Add("NOTE:" + Escape(note));
            var photo = ContactPhoto(path, First("PhotoURI"), First("PhotoName"), First("Photo")); if (photo.Length > 0) lines.Add("PHOTO:" + photo);
            AddDate(lines, "BDAY", First("BirthYear"), First("BirthMonth"), First("BirthDay"));
            AddDate(lines, "ANNIVERSARY", First("AnniversaryYear"), First("AnniversaryMonth"), First("AnniversaryDay"));
            if (long.TryParse(First("LastModifiedDate"), out var modified) && modified is > 0 and <= 253402300799)
                lines.Add($"REV:{DateTimeOffset.FromUnixTimeSeconds(modified).UtcDateTime:yyyyMMdd'T'HHmmss'Z'}");
            lines.Add($"UID:thunderbird:{source}:{Escape(card)}");
            text.Append(ExchangeCodec.SupplementVCard(string.Join("\r\n", Values("_vCard")), lines, reference => ContactPhoto(path, reference)));
        }
        return text.Length == 0 ? Empty() : ExchangeCodec.ParseVCard(text.ToString());
    }

    private static ExchangeImportResult Parse(string path, string profile)
    {
        using var culture = new CalendarRecurrence.WireCulture();
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path, Mode = SqliteOpenMode.ReadOnly
        }.ToString());
        connection.Open();
        var tables = Rows(connection, "sqlite_master", "type='table'").Select(row => Text(row, "name")).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var skipped = 0;
        var properties = new Dictionary<ItemKey, List<Property>>();
        if (tables.Contains("cal_properties"))
            foreach (var row in Rows(connection, "cal_properties"))
            {
                try
                {
                    var value = Text(row, "value"); if (value.Length == 0) continue;
                    var key = Key(row); if (!properties.TryGetValue(key, out var values)) properties[key] = values = new();
                    values.Add(new Property(Text(row, "key").ToUpperInvariant(), value));
                }
                catch (Exception) { skipped++; }
            }
        var parameters = new Dictionary<ItemKey, List<Parameter>>();
        if (tables.Contains("cal_parameters"))
            foreach (var row in Rows(connection, "cal_parameters"))
            {
                try
                {
                    var key = Key(row); if (!parameters.TryGetValue(key, out var values)) parameters[key] = values = new();
                    values.Add(new Parameter(Text(row, "key1").ToUpperInvariant(), Text(row, "key2").ToUpperInvariant(), Text(row, "value")));
                }
                catch (Exception) { skipped++; }
            }
        var extra = new Dictionary<ItemKey, List<string>>();
        foreach (var table in new[] { "cal_recurrence", "cal_alarms", "cal_attendees", "cal_attachments", "cal_relations" })
            if (tables.Contains(table)) foreach (var row in Rows(connection, table))
            {
                try
                {
                    var value = Text(row, "icalString"); if (value.Length == 0) continue;
                    var key = Key(row); if (!extra.TryGetValue(key, out var values)) extra[key] = values = new(); values.Add(value);
                }
                catch (Exception) { skipped++; }
            }

        var result = Empty();
        foreach (var table in new[] { "cal_events", "cal_todos" })
        {
            if (!tables.Contains(table)) continue;
            foreach (var row in Rows(connection, table))
            {
                try
                {
                var key = Key(row); var component = table == "cal_events" ? "VEVENT" : "VTODO"; var flags = Long(row, "flags");
                var lines = new List<string> { "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:" + component, "UID:" + Escape(Text(row, "id")) };
                if (Long(row, "last_modified") > 0) lines.Add(DateLine("LAST-MODIFIED", Long(row, "last_modified"), "UTC", false));
                if (component == "VEVENT")
                {
                    var allDay = (flags & 8) != 0;
                    lines.Add(DateLine("DTSTART", Long(row, "event_start"), Text(row, "event_start_tz"), allDay));
                    lines.Add(DateLine("DTEND", Long(row, "event_end"), Text(row, "event_end_tz"), allDay));
                    lines.Add("SUMMARY:" + Escape(Text(row, "title")));
                    var privacy = Text(row, "privacy").ToUpperInvariant();
                    if (privacy is "PRIVATE" or "CONFIDENTIAL") lines.Add("CLASS:" + privacy);
                    if (Text(row, "ical_status") is { Length: > 0 } status) lines.Add("STATUS:" + status);
                }
                else
                {
                    lines.Add("SUMMARY:" + Escape(Text(row, "title")));
                    if (row.TryGetValue("todo_entry", out var entry) && entry is not null)
                        lines.Add(DateLine("DTSTART", Long(row, "todo_entry"), Text(row, "todo_entry_tz"), (flags & 8) != 0));
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
                {
                    var source = $"thunderbird:{profile}:{key.Calendar}";
                    value["icsQuelleId"] = source;
                    value["icsQuelleName"] = "Thunderbird: " + key.Calendar;
                    value["syncKalenderUid"] = source;
                    value["syncQuellen"] = new JsonObject { [source] = new JsonObject { ["id"] = key.Item } };
                    if (key.Recurrence is not null)
                        value["icsOriginalDatum"] = NativeDate(key.Recurrence.Value,
                            (flags & 512) != 0 ? "" : key.RecurrenceZone).ToString("yyyy-MM-dd");
                }
                foreach (var node in parsed.Termine.OfType<JsonObject>())
                {
                    result.Termine.Add(node.DeepClone());
                }
                Append(result.Jahrestage, parsed.Jahrestage); Append(result.Aufgaben, parsed.Aufgaben);
                result = result with { Uebersprungen = result.Uebersprungen + parsed.Uebersprungen,
                    Wiederholend = result.Wiederholend + parsed.Wiederholend };
                }
                catch (Exception) { skipped++; }
            }
        }
        ExchangeCodec.ReconcileRecurrences(result.Termine);
        ExchangeCodec.ReconcileRecurrences(result.Aufgaben);
        PromoteOccasions(result);
        return result with { Uebersprungen = result.Uebersprungen + skipped };
    }

    internal static ExchangeImportResult ParseProfiles(IEnumerable<string> paths, out int read)
    {
        var result = Empty(); read = 0;
        foreach (var path in paths)
        {
            try
            {
                if (!File.Exists(path) || new FileInfo(path).Length > 512L * 1024 * 1024) continue;
                var parsed = Parse(path, ProfileId(path)); read++;
                Append(result.Termine, parsed.Termine); Append(result.Jahrestage, parsed.Jahrestage);
                Append(result.Aufgaben, parsed.Aufgaben);
                result = result with { Uebersprungen = result.Uebersprungen + parsed.Uebersprungen,
                    Wiederholend = result.Wiederholend + parsed.Wiederholend };
            }
            catch (Exception) { result = result with { Uebersprungen = result.Uebersprungen + 1 }; }
        }
        return result;
    }

    private static void AddDate(List<string> lines, string name, string yearText, string monthText, string dayText)
    {
        if (!int.TryParse(monthText, out var month) || !int.TryParse(dayText, out var day) || month is < 1 or > 12 || day is < 1 or > 31) return;
        lines.Add(int.TryParse(yearText, out var year) && year >= 1000 ? $"{name}:{year:0000}-{month:00}-{day:00}" : $"{name}:--{month:00}-{day:00}");
    }

    private static void PromoteOccasions(ExchangeImportResult result)
    {
        foreach (var node in result.Termine.OfType<JsonObject>().ToArray())
        {
            var title = node["titel"]?.ToString() ?? "";
            var categories = (node["kategorien"]?.ToString() ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            var type = categories.Contains("Birthday", StringComparer.OrdinalIgnoreCase) &&
                System.Text.RegularExpressions.Regex.IsMatch(title, "(?:Birthday|Geburtstag)$", System.Text.RegularExpressions.RegexOptions.IgnoreCase) ? "birthday" :
                categories.Contains("Anniversary", StringComparer.OrdinalIgnoreCase) &&
                System.Text.RegularExpressions.Regex.IsMatch(title, "(?:Anniversary|Jahrestag)$", System.Text.RegularExpressions.RegexOptions.IgnoreCase) ? "anniversary" : "";
            var raw = (node["icsRoundtrip"] as JsonArray ?? []).Select(line => CalendarRecurrence.ParseProperty(line?.ToString() ?? "")).OfType<CalendarRecurrence.Property>().ToArray();
            var rule = raw.FirstOrDefault(property => property.Name == "RRULE");
            if (type.Length == 0 || !ExchangeCodec.IsUnboundedAnnualRule(rule.Value ?? "") ||
                raw.Any(property => property.Name is "EXDATE" or "EXRULE" or "RDATE" or "RECURRENCE-ID") ||
                !string.IsNullOrEmpty(node["zeit"]?.ToString()) || !string.IsNullOrEmpty(node["endDatum"]?.ToString())) continue;
            var occasion = node.DeepClone().AsObject(); occasion.Remove("titel"); occasion.Remove("wiederholung");
            occasion["name"] = title; occasion["typ"] = type;
            // An unmarked calendar anchor is not evidence of a birth/wedding year.
            occasion["datum"] = "--" + (node["datum"]?.ToString() ?? "")[5..];
            occasion["jahrUnbekannt"] = true;
            result.Termine.Remove(node); result.Jahrestage.Add(occasion);
        }
    }

    private static string ContactPhoto(string book, params string[] candidates)
    {
        foreach (var candidate in candidates.Where(value => !string.IsNullOrWhiteSpace(value)))
        {
            if (candidate.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase)) return candidate;
            string path;
            try
            {
                path = Uri.TryCreate(candidate, UriKind.Absolute, out var uri) && uri.IsFile ? uri.LocalPath : candidate;
                if (!Path.IsPathRooted(path))
                {
                    var profile = Path.GetDirectoryName(book)!;
                    var photoPath = Path.Combine(profile, "Photos", path);
                    path = File.Exists(photoPath) ? photoPath : Path.Combine(profile, path);
                }
                if (!File.Exists(path) || new FileInfo(path).Length > 2_700_000) continue;
                var bytes = File.ReadAllBytes(path); string? type = bytes.AsSpan().StartsWith(new byte[] { 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a }) ? "png" :
                    bytes.AsSpan().StartsWith(new byte[] { 0xff, 0xd8, 0xff }) ? "jpeg" : bytes.AsSpan().StartsWith("GIF8"u8) ? "gif" : null;
                if (type is not null) return $"data:image/{type};base64,{Convert.ToBase64String(bytes)}";
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException) { }
        }
        return "";
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
        var value = NativeDate(microseconds, allDay ? "" : zone);
        if (allDay) return $"{name};VALUE=DATE:{value:yyyyMMdd}";
        if (zone.Equals("UTC", StringComparison.OrdinalIgnoreCase)) return $"{name}:{value:yyyyMMdd'T'HHmmss'Z'}";
        return name + (zone.Length > 0 && !zone.Equals("floating", StringComparison.OrdinalIgnoreCase) ? ";TZID=" + zone : "") + $":{value:yyyyMMdd'T'HHmmss}";
    }
    private static DateTime NativeDate(long microseconds, string zone)
    {
        var value = DateTimeOffset.FromUnixTimeMilliseconds(microseconds / 1000).UtcDateTime;
        if (zone.Length == 0 || zone.Equals("UTC", StringComparison.OrdinalIgnoreCase) || zone.Equals("floating", StringComparison.OrdinalIgnoreCase)) return value;
        try { return TimeZoneInfo.ConvertTimeFromUtc(value, TimeZoneInfo.FindSystemTimeZoneById(zone)); }
        catch (TimeZoneNotFoundException) when (TimeZoneInfo.TryConvertIanaIdToWindowsId(zone, out var windowsId))
        { return TimeZoneInfo.ConvertTimeFromUtc(value, TimeZoneInfo.FindSystemTimeZoneById(windowsId)); }
    }
    private static string ProfileId(string path) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
        Path.GetFullPath(path).Replace('\\', '/').ToUpperInvariant())))[..16].ToLowerInvariant();
    private static string Escape(string value) => value.Replace("\\", "\\\\").Replace("\r\n", "\\n").Replace("\n", "\\n").Replace(",", "\\,").Replace(";", "\\;");
    private static ExchangeImportResult Empty() => new(new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray(), new JsonArray());
    private static void Append(JsonArray target, JsonArray source) { foreach (var node in source) target.Add(node?.DeepClone()); }
}
