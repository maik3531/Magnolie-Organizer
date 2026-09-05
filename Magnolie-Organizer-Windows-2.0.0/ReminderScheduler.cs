using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record ReminderNotice(string Title, string Body, string Kind, string Style);

internal sealed class ReminderScheduler : IDisposable
{
    private readonly Action<ReminderNotice> show;
    private readonly AtomicStore store;
    private readonly string statePath;
    private readonly object gate = new();
    private readonly HashSet<string> reported = new(StringComparer.Ordinal);
    private System.Threading.Timer? timer;
    private string data = "{}";
    private bool enabled;
    private int running;
    private bool dirty;

    internal ReminderScheduler(string statePath, Action<ReminderNotice> show, AtomicStore? store = null)
    {
        this.statePath = statePath;
        this.show = show;
        this.store = store ?? new AtomicStore();
        try
        {
            var text = this.store.Read(statePath, 64 * 1024 * 1024);
            if (text is null) return;
            JsonDocument document;
            try { document = JsonDocument.Parse(text); }
            catch (JsonException)
            {
                text = this.store.ReadRecoverableJson(statePath, 64 * 1024 * 1024);
                if (text is null) return;
                document = JsonDocument.Parse(text);
            }
            using (document)
            {
            var values = document.RootElement.ValueKind == JsonValueKind.Array
                ? document.RootElement
                : document.RootElement.ValueKind == JsonValueKind.Object &&
                  document.RootElement.TryGetProperty("reported", out var saved) && saved.ValueKind == JsonValueKind.Array
                    ? saved : default;
            if (values.ValueKind == JsonValueKind.Array)
                foreach (var item in values.EnumerateArray())
                    if (item.ValueKind == JsonValueKind.String && item.GetString() is { Length: > 0 } key) reported.Add(key);
            }
        }
        catch (Exception) { }
    }

    internal void UpdateData(string plainText)
    {
        lock (gate) data = plainText;
    }

    internal void Configure(bool active)
    {
        lock (gate)
        {
            if (enabled == active && (active ? timer is not null : timer is null)) return;
            enabled = active;
            timer?.Dispose();
            timer = active ? new System.Threading.Timer(_ => Check(DateTime.Now), null, TimeSpan.Zero, TimeSpan.FromSeconds(30)) : null;
        }
    }

    internal void RunOnce(DateTime now)
    {
        lock (gate) enabled = true;
        Check(now);
    }

    internal static string? SelectBackgroundData(string plainText)
    {
        using var document = JsonDocument.Parse(plainText);
        if (document.RootElement.ValueKind != JsonValueKind.Object) return null;
        var root = document.RootElement;
        var settings = Child(root, "einstellungen");
        var security = Child(settings, "sicherheit");
        if (!True(security, "erinnernTrotzKennwort")) return null;
        var confidential = True(security, "vertraulicheErinnerungen");
        return SelectData(root, confidential);
    }

    internal static string SelectRuntimeData(string plainText)
    {
        using var document = JsonDocument.Parse(plainText);
        return document.RootElement.ValueKind == JsonValueKind.Object
            ? SelectData(document.RootElement, true) : "{}";
    }

    private static string SelectData(JsonElement root, bool confidential)
    {
        var appointments = SelectAppointments(root, item => confidential || !True(item, "vertraulich")).ToList();
        appointments.AddRange(SelectCustomEntries(root, "appointments"));
        var tasks = SelectArray(root, "aufgaben", item => confidential || !True(item, "vertraulich"),
            "id", "uid", "titel", "faellig", "startZeit", "faelligZeit", "erledigt", "erinnern",
            "individuelleErinnerungTage").ToList();
        tasks.AddRange(SelectCustomEntries(root, "tasks"));
        var settings = Child(root, "einstellungen");
        var selected = new Dictionary<string, object?>
        {
            ["version"] = 1,
            ["nurErinnerungen"] = true,
            ["termine"] = appointments,
            ["aufgaben"] = tasks,
            ["jahrestage"] = SelectArray(root, "jahrestage", item => confidential || !True(item, "vertraulich"),
                "id", "uid", "name", "datum", "typ"),
            ["einstellungen"] = new JsonObject
            {
                ["erinnerung"] = SelectFields(Child(settings, "erinnerung"),
                    "an", "vorlauf", "verpasste", "aufgaben", "art", "stil", "jahrestage")
            }
        };
        return JsonSerializer.Serialize(selected);
    }

    private static JsonObject[] SelectCustomEntries(JsonElement root, string type)
    {
        var custom = Child(root, "customOrganizer");
        if (custom.ValueKind != JsonValueKind.Object ||
            !custom.TryGetProperty("modules", out var modules) || modules.ValueKind != JsonValueKind.Array)
            return Array.Empty<JsonObject>();
        var result = new List<JsonObject>();
        foreach (var module in modules.EnumerateArray().Take(24))
        {
            if (module.ValueKind != JsonValueKind.Object || Text(module, "type") != type || !True(module, "reminders") ||
                !module.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array) continue;
            var moduleTitle = Text(module, "title");
            var moduleId = Text(module, "id");
            foreach (var item in items.EnumerateArray().Take(500))
            {
                if (item.ValueKind != JsonValueKind.Object ||
                    item.TryGetProperty("remind", out var remind) && remind.ValueKind == JsonValueKind.False) continue;
                var title = string.Join(" · ", new[] { moduleTitle, Text(item, "title") }.Where(value => value.Length > 0));
                var reminderId = $"custom:{moduleId}:{Text(item, "id")}";
                var date = Text(item, type == "appointments" ? "date" : "due");
                if (!DateTime.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out _)) continue;
                var time = Text(item, "time");
                time = time.Length >= 5 && TimeOnly.TryParseExact(time[..5], "HH:mm",
                    CultureInfo.InvariantCulture, DateTimeStyles.None, out _) ? time[..5] : "";
                if (type == "appointments")
                {
                    var selected = new JsonObject { ["id"] = reminderId, ["datum"] = date,
                        ["zeit"] = time, ["titel"] = title, ["standardErinnerung"] = true };
                    if (item.TryGetProperty("wiederholung", out var recurrence))
                        selected["wiederholung"] = SelectFields(recurrence,
                            "art", "bis", "ordinal", "wochentag", "intervall", "daten");
                    result.Add(selected);
                }
                else
                    result.Add(new JsonObject { ["id"] = reminderId, ["titel"] = title,
                        ["faellig"] = date, ["faelligZeit"] = time,
                        ["erledigt"] = True(item, "done"), ["erinnern"] = true });
            }
        }
        return result.ToArray();
    }

    internal static IReadOnlyList<(string Key, DateTime Start, DateTime Due)> DueAppointments(
        string json, DateTime now)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        var reminder = Child(Child(root, "einstellungen"), "erinnerung");
        var lead = Math.Clamp(Number(reminder, "vorlauf", 15), 0, 120);
        var includeMissed = reminder.ValueKind != JsonValueKind.Object ||
                            !reminder.TryGetProperty("verpasste", out var missed) || missed.ValueKind != JsonValueKind.False;
        if (!root.TryGetProperty("termine", out var appointments) || appointments.ValueKind != JsonValueKind.Array)
            return Array.Empty<(string, DateTime, DateTime)>();
        var result = new List<(string, DateTime, DateTime)>();
        foreach (var item in appointments.EnumerateArray())
        {
            if (!TryStart(item, out var first)) continue;
            var duration = TryEnd(item, first, out var firstEnd) && firstEnd >= first ? firstEnd - first : TimeSpan.Zero;
            var alarms = AppointmentAlarms(item);
            var maximumLead = alarms.Count == 0 ? 0 : alarms.Max(alarm => alarm.OffsetMinutes);
            var id = Text(item, "id");
            if (id.Length == 0) id = Text(item, "uid");
            if (id.Length == 0) id = $"{Text(item, "datum")}|{Text(item, "zeit")}|{Text(item, "titel")}";
            var lower = duration <= now.AddHours(-72) - DateTime.MinValue
                ? now.AddHours(-72).Subtract(duration) : DateTime.MinValue;
            foreach (var start in Occurrences(item, first, lower,
                         now.AddMinutes(Math.Max(8 * 1440, maximumLead))))
            {
                var individualDays = Math.Clamp(Number(item, "individuelleErinnerungTage", 0), 0, 7);
                var standard = !item.TryGetProperty("standardErinnerung", out var standardNode) || standardNode.ValueKind != JsonValueKind.False || individualDays == 0;
                var existing = new HashSet<string>(StringComparer.Ordinal);
                if (individualDays > 0) AddDue(result, id, "individuell", start, start.AddDays(-individualDays), now, includeMissed);
                if (standard) AddDue(result, id, "standard", start, start.AddMinutes(-lead), now, includeMissed);
                if (individualDays > 0) existing.Add($"START:{individualDays * 1440}");
                if (standard) existing.Add($"START:{lead}");
                foreach (var alarm in alarms)
                {
                    if (!existing.Add($"{alarm.Related}:{alarm.OffsetMinutes}")) continue;
                    var basis = alarm.Related == "END" ? start.Add(duration) : start;
                    AddDue(result, id, $"alarm-{alarm.Related.ToLowerInvariant()}-{alarm.OffsetMinutes}",
                        start, basis.AddMinutes(-alarm.OffsetMinutes), now, includeMissed, basis);
                }
            }
        }
        return result;
    }

    private void Check(DateTime now)
    {
        if (Interlocked.Exchange(ref running, 1) != 0) return;
        try
        {
            string snapshot;
            lock (gate) { if (!enabled) return; snapshot = data; }
            using var document = JsonDocument.Parse(snapshot);
            var reminder = Child(Child(document.RootElement, "einstellungen"), "erinnerung");
            var kind = Text(reminder, "art") is "notification" or "sound" or "both" ? Text(reminder, "art") : "both";
            var style = Text(reminder, "stil") == "magnolie" ? "magnolie" : "system";
            IEnumerable<(string Key, DateTime Start, DateTime Due)> dueItems = DueAppointments(snapshot, now);
            if (!reminder.TryGetProperty("aufgaben", out var tasksEnabled) || tasksEnabled.ValueKind != JsonValueKind.False)
                dueItems = dueItems.Concat(DueTasks(document.RootElement, reminder, now));
            dueItems = dueItems.Concat(DueAnniversaries(document.RootElement, reminder, now));
            var pending = new List<(string Key, ReminderNotice Notice)>();
            foreach (var due in dueItems)
            {
                lock (gate) { if (!reported.Add(due.Key)) continue; dirty = true; }
                var title = FindTitle(document.RootElement, due.Key);
                var when = due.Start.ToString(due.Start.TimeOfDay == TimeSpan.FromHours(8) ? "d" : "g", CultureInfo.CurrentCulture);
                var heading = due.Key.StartsWith("aufgabe:", StringComparison.Ordinal) ? "Aufgabe" :
                    due.Key.StartsWith("jahrestag:", StringComparison.Ordinal) ? "Jahrestag" : "Termin";
                pending.Add((due.Key, new ReminderNotice(heading, $"{title}\n{when}", kind, style)));
            }
            if (dirty && !Persist(now))
            {
                lock (gate) foreach (var item in pending) reported.Remove(item.Key);
                return;
            }
            foreach (var item in pending) show(item.Notice);
        }
        catch (Exception) { }
        finally { Volatile.Write(ref running, 0); }
    }

    internal static IReadOnlyList<(string Key, DateTime Start, DateTime Due)> DueTasks(
        JsonElement root, JsonElement reminder, DateTime now)
    {
        if (!root.TryGetProperty("aufgaben", out var tasks) || tasks.ValueKind != JsonValueKind.Array)
            return Array.Empty<(string, DateTime, DateTime)>();
        var includeMissed = reminder.ValueKind != JsonValueKind.Object ||
                            !reminder.TryGetProperty("verpasste", out var missed) || missed.ValueKind != JsonValueKind.False;
        var result = new List<(string, DateTime, DateTime)>();
        foreach (var task in tasks.EnumerateArray())
        {
            if (task.TryGetProperty("erledigt", out var done) && done.ValueKind == JsonValueKind.True ||
                !task.TryGetProperty("erinnern", out var remind) || remind.ValueKind != JsonValueKind.True ||
                !DateOnly.TryParseExact(Text(task, "faellig"), "yyyy-MM-dd", out var date)) continue;
            var dueTime = TimeOnly.TryParseExact(Text(task, "faelligZeit"), "HH:mm", out var parsedDue)
                ? parsedDue : new TimeOnly(8, 0);
            var start = date.ToDateTime(dueTime);
            var days = Math.Clamp(Number(task, "individuelleErinnerungTage", 0), 0, 7);
            var id = Text(task, "id"); if (id.Length == 0) id = Text(task, "uid"); if (id.Length == 0) id = Text(task, "titel") + "|" + date;
            AddDue(result, "aufgabe:" + id, days > 0 ? "individuell" : "faellig", start, start.AddDays(-days), now, includeMissed);
        }
        return result;
    }

    internal static IReadOnlyList<(string Key, DateTime Start, DateTime Due)> DueAnniversaries(
        JsonElement root, JsonElement reminder, DateTime now)
    {
        var settings = Child(reminder, "jahrestage");
        if (settings.ValueKind != JsonValueKind.Object || !settings.TryGetProperty("an", out var active) || active.ValueKind != JsonValueKind.True ||
            !root.TryGetProperty("jahrestage", out var anniversaries) || anniversaries.ValueKind != JsonValueKind.Array)
            return Array.Empty<(string, DateTime, DateTime)>();
        var leadDays = Math.Clamp(Number(settings, "tage", 1), 0, 30);
        var onDay = !settings.TryGetProperty("amTag", out var onDayNode) || onDayNode.ValueKind != JsonValueKind.False;
        var hour = Math.Clamp(Number(settings, "stunde", 8), 0, 23);
        var result = new List<(string, DateTime, DateTime)>();
        foreach (var item in anniversaries.EnumerateArray())
        {
            if (!ExchangeCodec.TryParseCanonicalDate(Text(item, "datum"), out _, out var month, out var day)) continue;
            foreach (var year in new[] { now.Year - 1, now.Year, now.Year + 1 })
            {
                var occurrenceDay = month == 2 && day == 29 && !DateTime.IsLeapYear(year) ? 28 : day;
                var occurrence = new DateOnly(year, month, occurrenceDay);
                var start = occurrence.ToDateTime(new TimeOnly(hour, 0));
                var id = Text(item, "id"); if (id.Length == 0) id = Text(item, "uid"); if (id.Length == 0) id = Text(item, "name") + $"|{month:00}-{day:00}";
                if (leadDays > 0) AddDue(result, "jahrestag:" + id, "vorlauf", start, start.AddDays(-leadDays), now, true);
                if (onDay || leadDays == 0) AddDue(result, "jahrestag:" + id, "am-tag", start, start, now, true);
            }
        }
        return result;
    }

    private static void AddDue(List<(string Key, DateTime Start, DateTime Due)> result, string id,
        string mode, DateTime start, DateTime due, DateTime now, bool includeMissed, DateTime? reminderEnd = null)
    {
        var end = reminderEnd ?? start;
        if (now < due || now > end.AddHours(72)) return;
        if (!includeMissed && now > end.AddMinutes(5)) return;
        result.Add(($"{id}@{start:yyyyMMddHHmm}:{mode}", start, due));
    }

    private static IEnumerable<DateTime> Occurrences(JsonElement item, DateTime first, DateTime lower, DateTime upper)
    {
        var recurrence = Child(item, "wiederholung");
        var kind = Text(recurrence, "art");
        var until = DateOnly.TryParse(Text(recurrence, "bis"), out var untilDate) ? untilDate.ToDateTime(TimeOnly.MaxValue) : DateTime.MaxValue;
        if (kind == "custom")
        {
            if (first >= lower && first <= upper) yield return first;
            if (recurrence.ValueKind == JsonValueKind.Object && recurrence.TryGetProperty("daten", out var dates) &&
                dates.ValueKind == JsonValueKind.Array)
                foreach (var value in dates.EnumerateArray())
                    if (value.ValueKind == JsonValueKind.String &&
                        DateOnly.TryParseExact(value.GetString(), "yyyy-MM-dd", out var date))
                    {
                        var occurrence = date.ToDateTime(TimeOnly.FromDateTime(first));
                        if (occurrence > first && occurrence >= lower && occurrence <= upper) yield return occurrence;
                    }
            yield break;
        }
        if (kind is not ("daily" or "weekly" or "monthly" or "monthly_weekday" or "yearly"))
        {
            if (first >= lower && first <= upper) yield return first;
            yield break;
        }
        var current = first;
        var interval = Math.Clamp(Number(recurrence, "intervall", 1), 1, 3660);
        if (kind is "daily" or "weekly")
        {
            var step = (kind == "daily" ? 1 : 7) * interval;
            if (current < lower) current = current.AddDays(Math.Max(0, Math.Floor((lower - current).TotalDays / step)) * step);
            while (current < lower) current = current.AddDays(step);
        }
        else
        {
            while (current < lower && current <= until) current = kind switch
            {
                "monthly" => NextMonthly(current, recurrence),
                "monthly_weekday" => NextMonthly(current, recurrence),
                _ => current.AddYears(1)
            };
        }
        while (current <= upper && current <= until)
        {
            yield return current;
            current = kind switch { "daily" => current.AddDays(interval), "weekly" => current.AddDays(7 * interval), "monthly" => NextMonthly(current, recurrence),
                "monthly_weekday" => NextMonthly(current, recurrence), _ => current.AddYears(1) };
        }
    }

    private static DateTime NextMonthly(DateTime current, JsonElement recurrence)
    {
        var first = new DateTime(current.Year, current.Month, 1, current.Hour, current.Minute, current.Second, current.Kind).AddMonths(1);
        var ordinal = Number(recurrence, "ordinal", 0);
        var weekdays = new Dictionary<string, DayOfWeek> { ["MO"] = DayOfWeek.Monday, ["TU"] = DayOfWeek.Tuesday,
            ["WE"] = DayOfWeek.Wednesday, ["TH"] = DayOfWeek.Thursday, ["FR"] = DayOfWeek.Friday,
            ["SA"] = DayOfWeek.Saturday, ["SU"] = DayOfWeek.Sunday };
        if (ordinal is not (-1 or 1 or 2 or 3 or 4) || !weekdays.TryGetValue(Text(recurrence, "wochentag").ToUpperInvariant(), out var weekday))
            return current.AddMonths(1);
        if (ordinal == -1)
        {
            var last = first.AddMonths(1).AddDays(-1);
            return last.AddDays(-((int)last.DayOfWeek - (int)weekday + 7) % 7);
        }
        var offset = ((int)weekday - (int)first.DayOfWeek + 7) % 7;
        return first.AddDays(offset + (ordinal - 1) * 7);
    }

    private static bool TryStart(JsonElement item, out DateTime start)
    {
        start = default;
        if (!DateOnly.TryParseExact(Text(item, "datum"), "yyyy-MM-dd", out var date)) return false;
        var timeText = Text(item, "zeit");
        var time = timeText.Length == 0 ? new TimeOnly(8, 0) : TimeOnly.TryParseExact(timeText, "HH:mm", out var parsed) ? parsed : default;
        if (time == default && timeText.Length > 0) return false;
        start = date.ToDateTime(time);
        return true;
    }

    private static bool TryEnd(JsonElement item, DateTime start, out DateTime end)
    {
        end = start;
        var dateText = Text(item, "endDatum");
        var date = dateText.Length == 0
            ? DateOnly.FromDateTime(start)
            : DateOnly.TryParseExact(dateText, "yyyy-MM-dd", out var parsedDate) ? parsedDate : default;
        if (date == default) return false;
        var timeText = Text(item, "endZeit");
        var time = TimeOnly.FromDateTime(start);
        if (timeText.Length > 0 && !TimeOnly.TryParseExact(timeText, "HH:mm", out time)) return false;
        end = date.ToDateTime(time);
        return true;
    }

    private static IReadOnlyList<(int OffsetMinutes, string Related)> AppointmentAlarms(JsonElement item)
    {
        if (!item.TryGetProperty("alarme", out var values) || values.ValueKind != JsonValueKind.Array)
            return Array.Empty<(int, string)>();
        var result = new List<(int, string)>();
        foreach (var alarm in values.EnumerateArray().Take(32))
        {
            if (alarm.ValueKind != JsonValueKind.Object ||
                alarm.TryGetProperty("aktiviert", out var enabled) && enabled.ValueKind == JsonValueKind.False ||
                alarm.TryGetProperty("bearbeitbar", out var editable) && editable.ValueKind == JsonValueKind.False ||
                Text(alarm, "aktion") is { Length: > 0 } action && action != "display" ||
                !alarm.TryGetProperty("offsetMinuten", out var offsetNode) ||
                !offsetNode.TryGetInt32(out var offset) || offset is < 0 or > 525600) continue;
            result.Add((offset, string.Equals(Text(alarm, "related"), "END", StringComparison.OrdinalIgnoreCase)
                ? "END" : "START"));
        }
        return result;
    }

    private static string FindTitle(JsonElement root, string key)
    {
        var separator = key.LastIndexOf('@');
        var id = separator > 0 ? key[..separator] : key;
        if (id.StartsWith("aufgabe:", StringComparison.Ordinal))
            return FindItemTitle(root, "aufgaben", id[8..], "titel", "Aufgabe");
        if (id.StartsWith("jahrestag:", StringComparison.Ordinal))
            return FindItemTitle(root, "jahrestage", id[10..], "name", "Jahrestag");
        if (root.TryGetProperty("termine", out var appointments) && appointments.ValueKind == JsonValueKind.Array)
            foreach (var item in appointments.EnumerateArray())
                if (Text(item, "id") == id || Text(item, "uid") == id || key.StartsWith($"{Text(item, "datum")}|{Text(item, "zeit")}|{Text(item, "titel")}@", StringComparison.Ordinal))
                    return Text(item, "titel") is { Length: > 0 } title ? title : "Termin";
        return "Termin";
    }

    private static string FindItemTitle(JsonElement root, string collection, string id, string titleField, string fallback)
    {
        if (root.TryGetProperty(collection, out var items) && items.ValueKind == JsonValueKind.Array)
            foreach (var item in items.EnumerateArray())
                if (Text(item, "id") == id || Text(item, "uid") == id || id.StartsWith(Text(item, titleField) + "|", StringComparison.Ordinal))
                    return Text(item, titleField) is { Length: > 0 } title ? title : fallback;
        return fallback;
    }

    private bool Persist(DateTime now)
    {
        try
        {
            string[] values;
            lock (gate)
            {
                var cutoff = now.AddDays(-10).ToString("yyyyMMddHHmm", CultureInfo.InvariantCulture);
                foreach (var key in reported.Where(key => OccurrenceStamp(key) is { } stamp &&
                                                          string.CompareOrdinal(stamp, cutoff) < 0).ToArray())
                    reported.Remove(key);
                values = reported.Order().ToArray();
            }
            store.WriteRecoverableJson(statePath, JsonSerializer.Serialize(new { version = 1, reported = values }));
            dirty = false;
            return true;
        }
        catch (Exception) { return false; }
    }

    private static string? OccurrenceStamp(string key)
    {
        var marker = key.LastIndexOf('@');
        return marker >= 0 && key.Length >= marker + 13 ? key.Substring(marker + 1, 12) : null;
    }

    private static JsonObject[] SelectArray(JsonElement root, string name, Func<JsonElement, bool> include,
        params string[] fields) =>
        root.TryGetProperty(name, out var values) && values.ValueKind == JsonValueKind.Array
            ? values.EnumerateArray().Where(item => item.ValueKind == JsonValueKind.Object && include(item))
                .Select(item => SelectFields(item, fields)).ToArray()
            : Array.Empty<JsonObject>();

    private static JsonObject[] SelectAppointments(JsonElement root, Func<JsonElement, bool> include) =>
        root.TryGetProperty("termine", out var values) && values.ValueKind == JsonValueKind.Array
            ? values.EnumerateArray().Where(item => item.ValueKind == JsonValueKind.Object && include(item))
                .Select(SelectAppointment).ToArray()
            : Array.Empty<JsonObject>();

    private static JsonObject SelectAppointment(JsonElement item)
    {
        var result = SelectFields(item, "id", "uid", "datum", "zeit", "endDatum", "endZeit", "titel",
            "individuelleErinnerungTage", "standardErinnerung", "wiederholung");
        if (!item.TryGetProperty("alarme", out var alarms) || alarms.ValueKind != JsonValueKind.Array) return result;
        var selected = new JsonArray();
        foreach (var alarm in alarms.EnumerateArray().Take(32))
            if (alarm.ValueKind == JsonValueKind.Object &&
                (!alarm.TryGetProperty("bearbeitbar", out var editable) || editable.ValueKind != JsonValueKind.False))
                selected.Add(SelectFields(alarm, "offsetMinuten", "aktiviert", "related", "aktion"));
        result["alarme"] = selected;
        return result;
    }

    private static JsonObject SelectFields(JsonElement source, params string[] fields)
    {
        var result = new JsonObject();
        if (source.ValueKind != JsonValueKind.Object) return result;
        foreach (var field in fields)
            if (source.TryGetProperty(field, out var value)) result[field] = JsonNode.Parse(value.GetRawText());
        return result;
    }

    private static JsonElement Child(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var child) && child.ValueKind == JsonValueKind.Object ? child : default;
    private static string Text(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    private static int Number(JsonElement element, string name, int fallback) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : fallback;
    private static bool True(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    public void Dispose()
    {
        lock (gate) { enabled = false; timer?.Dispose(); timer = null; }
    }
}
