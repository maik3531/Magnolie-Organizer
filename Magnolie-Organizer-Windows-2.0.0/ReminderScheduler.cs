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
    private readonly Dictionary<string, DateTime> reportedAt = new(StringComparer.Ordinal);
    private System.Threading.Timer? timer;
    private string data = "{}";
    private bool enabled;
    private int running;
    private bool dirty;
    internal string? LastError { get; private set; }
    internal IReadOnlyDictionary<string, string> ExpansionErrors { get; private set; } = new Dictionary<string, string>();

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
            if (document.RootElement.ValueKind == JsonValueKind.Object &&
                document.RootElement.TryGetProperty("reportedAt", out var times) && times.ValueKind == JsonValueKind.Object)
                foreach (var item in times.EnumerateObject())
                    if (reported.Contains(item.Name) && item.Value.ValueKind == JsonValueKind.String &&
                        DateTimeOffset.TryParse(item.Value.GetString(), CultureInfo.InvariantCulture,
                            DateTimeStyles.None, out var timestamp)) reportedAt[item.Name] = timestamp.UtcDateTime;
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
        var tasks = new List<JsonObject>();
        if (root.TryGetProperty("aufgaben", out var rawTasks) && rawTasks.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in rawTasks.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object || (!confidential && True(item, "vertraulich"))) continue;
                var selectedTask = SelectFields(item, "id", "uid", "icsQuelleId", "syncKalenderUid", "titel", "faellig", "startDatum", "startZeit", "faelligZeit", "erledigt", "erinnern",
                    "icsStatus", "icsAusnahmen", "icsAusnahmeTermine", "icsTimezones", "individuelleErinnerungTage");
                selectedTask["icsRoundtrip"] = ReminderRaw(item);
                selectedTask["icsRangeOverrides"] = ReminderRanges(item);
                selectedTask["alarme"] = SelectAppointment(item)["alarme"]?.DeepClone();
                tasks.Add(selectedTask);
            }
        }
        tasks.AddRange(SelectCustomEntries(root, "tasks"));
        var settings = Child(root, "einstellungen");
        var selected = new Dictionary<string, object?>
        {
            ["version"] = 1,
            ["nurErinnerungen"] = true,
            ["termine"] = appointments,
            ["aufgaben"] = tasks,
            ["jahrestage"] = SelectArray(root, "jahrestage", item => confidential || !True(item, "vertraulich"),
                 "id", "uid", "icsQuelleId", "syncKalenderUid", "name", "datum", "typ"),
            ["einstellungen"] = new JsonObject
            {
                ["regional"] = SelectFields(Child(settings, "regional"), "timeZone"),
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
        string json, DateTime now, Dictionary<string, string>? titles = null, Dictionary<string, string>? errors = null)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        var zone = CalendarRecurrence.OrganizerZone(root);
        var nowUtc = CalendarRecurrence.NowUtc(now);
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
            var maximumLag = alarms.Count == 0 ? 0 : Math.Max(0, -alarms.Min(alarm => alarm.OffsetMinutes));
            var id = Identity(item);
            if (id.Length == 0) id = $"{Text(item, "datum")}|{Text(item, "zeit")}|{Text(item, "titel")}";
            var lookback = duration + TimeSpan.FromDays(5) + TimeSpan.FromMinutes(maximumLag);
            var lower = lookback.Ticks <= nowUtc.Ticks ? nowUtc.Subtract(lookback) : DateTime.SpecifyKind(DateTime.MinValue, DateTimeKind.Utc);
            var occurrences = ExpandForReminders(item, lower, nowUtc.AddMinutes(Math.Max(8 * 1440, maximumLead)), zone, false, alarms.Any(alarm => alarm.Related == "END"), errors);
            foreach (var occurrence in occurrences)
            {
                var resultStart = result.Count;
                var start = occurrence.AllDay ? occurrence.Start.Date.AddHours(8) : occurrence.Start;
                var startUtc = occurrence.AllDay ? CalendarRecurrence.ToUtc(start, zone) : occurrence.StartUtc;
                var individualDays = Math.Clamp(Number(item, "individuelleErinnerungTage", 0), 0, 7);
                var standard = !item.TryGetProperty("standardErinnerung", out var standardNode) || standardNode.ValueKind != JsonValueKind.False || individualDays == 0;
                var existing = new HashSet<string>(StringComparer.Ordinal);
                if (individualDays > 0) AddDue(result, id, "individuell", start, start.AddDays(-individualDays), now, includeMissed, zone: zone, endUtc: startUtc, occurrenceUtc: startUtc);
                if (standard) AddDue(result, id, "standard", start, TimeZoneInfo.ConvertTimeFromUtc(startUtc.AddMinutes(-lead), zone), now, includeMissed,
                    zone: zone, dueUtc: startUtc.AddMinutes(-lead), endUtc: startUtc, occurrenceUtc: startUtc);
                if (individualDays > 0) existing.Add($"START:{individualDays * 1440}");
                if (standard) existing.Add($"START:{lead}");
                foreach (var alarm in alarms)
                {
                    if (!existing.Add($"{alarm.Related}:{alarm.OffsetMinutes}")) continue;
                    var basisUtc = alarm.Related == "END" ? occurrence.EndUtc : startUtc;
                    var basis = TimeZoneInfo.ConvertTimeFromUtc(basisUtc, zone);
                    AddDue(result, id, $"alarm-{alarm.Related.ToLowerInvariant()}-{alarm.OffsetMinutes}",
                        start, TimeZoneInfo.ConvertTimeFromUtc(basisUtc.AddMinutes(-alarm.OffsetMinutes), zone), now, includeMissed, basis,
                        zone, basisUtc.AddMinutes(-alarm.OffsetMinutes), basisUtc, startUtc);
                }
                if (titles is not null && occurrence.Summary is not null)
                    foreach (var due in result.Skip(resultStart)) titles[due.Item1] = CalendarRecurrence.TextValue(occurrence.Summary);
            }
        }
        return result;
    }

    private static IReadOnlyList<CalendarOccurrence> ExpandForReminders(JsonElement item, DateTime lower, DateTime upper,
        TimeZoneInfo zone, bool task, bool overlap, Dictionary<string, string>? errors)
    {
        try { return CalendarRecurrence.Expand(item, lower, upper, zone, task, overlap); }
        catch (Exception error) when (errors is not null && error is InvalidDataException or ArgumentException or FormatException or OverflowException or InvalidOperationException or TimeZoneNotFoundException or InvalidTimeZoneException)
        {
            var identity = Identity(item);
            if (identity.Length == 0) identity = Text(item, "titel") + "|" + Text(item, task ? "faellig" : "datum") + "|" + Text(item, task ? "faelligZeit" : "zeit");
            var id = (task ? "aufgabe:" : "termin:") + identity;
            errors[id] = (error.Data["retryable"] is true ? "pending: " : "error: ") + error.Message;
            return [];
        }
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
            var titles = new Dictionary<string, string>(StringComparer.Ordinal);
            var errors = new Dictionary<string, string>(StringComparer.Ordinal);
            IEnumerable<(string Key, DateTime Start, DateTime Due)> dueItems = DueAppointments(snapshot, now, titles, errors);
            if (!reminder.TryGetProperty("aufgaben", out var tasksEnabled) || tasksEnabled.ValueKind != JsonValueKind.False)
                dueItems = dueItems.Concat(DueTasks(document.RootElement, reminder, now, titles, errors));
            dueItems = dueItems.Concat(DueAnniversaries(document.RootElement, reminder, now));
            ExpansionErrors = errors;
            var previousError = LastError;
            var expansionError = errors.Count == 0 ? null : string.Join("\n", errors.OrderBy(value => value.Key).Select(value => value.Key + ": " + value.Value));
            LastError = expansionError;
            var pending = new List<(string Key, ReminderNotice Notice)>();
            lock (gate)
                foreach (var key in reported)
                    if (!reportedAt.ContainsKey(key)) { reportedAt[key] = CalendarRecurrence.NowUtc(now); dirty = true; }
            foreach (var due in dueItems)
            {
                lock (gate) { if (!reported.Add(due.Key)) continue; reportedAt[due.Key] = CalendarRecurrence.NowUtc(now); dirty = true; }
                var title = titles.GetValueOrDefault(due.Key) ?? FindTitle(document.RootElement, due.Key);
                var when = due.Start.ToString(due.Start.TimeOfDay == TimeSpan.FromHours(8) ? "d" : "g", CultureInfo.CurrentCulture);
            var heading = due.Key.StartsWith("aufgabe:", StringComparison.Ordinal) ? NativeLocalization.Gettext("Task") :
                    due.Key.StartsWith("jahrestag:", StringComparison.Ordinal) ? NativeLocalization.Gettext("Anniversary") : NativeLocalization.Gettext("Appointment");
                pending.Add((due.Key, new ReminderNotice(heading, $"{title}\n{when}", kind, style)));
            }
            if (dirty && !Persist(now))
            {
                lock (gate) foreach (var item in pending) { reported.Remove(item.Key); reportedAt.Remove(item.Key); }
                return;
            }
            foreach (var item in pending)
            {
                lock (gate) if (!enabled) break;
                show(item.Notice);
            }
            if (expansionError is not null && expansionError != previousError)
            {
                RotatingLog.Append(statePath + ".log", expansionError);
                show(new ReminderNotice(NativeLocalization.Gettext("Appointment"),
                    NativeLocalization.Gettext("Some recurrence rules cannot be expanded. Their original calendar data was preserved."), "notification", "system"));
            }
        }
        catch (Exception error)
        {
            if (LastError != error.Message)
            {
                LastError = error.Message;
                RotatingLog.Append(statePath + ".log", error.ToString());
                show(new ReminderNotice(NativeLocalization.Gettext("Appointment"),
                    NativeLocalization.Gettext("Some recurrence rules cannot be expanded. Their original calendar data was preserved."), "notification", "system"));
            }
        }
        finally { Volatile.Write(ref running, 0); }
    }

    internal static IReadOnlyList<(string Key, DateTime Start, DateTime Due)> DueTasks(
        JsonElement root, JsonElement reminder, DateTime now, Dictionary<string, string>? titles = null, Dictionary<string, string>? errors = null)
    {
        if (!root.TryGetProperty("aufgaben", out var tasks) || tasks.ValueKind != JsonValueKind.Array)
            return Array.Empty<(string, DateTime, DateTime)>();
        var includeMissed = reminder.ValueKind != JsonValueKind.Object ||
                            !reminder.TryGetProperty("verpasste", out var missed) || missed.ValueKind != JsonValueKind.False;
        var result = new List<(string, DateTime, DateTime)>();
        var zone = CalendarRecurrence.OrganizerZone(root);
        var nowUtc = CalendarRecurrence.NowUtc(now);
        foreach (var task in tasks.EnumerateArray())
        {
            if (True(task, "erledigt")) continue;
            var alarms = AppointmentAlarms(task);
            var days = Math.Clamp(Number(task, "individuelleErinnerungTage", 0), 0, 7);
            if (!True(task, "erinnern") && days == 0 && alarms.Count == 0) continue;
            var id = Identity(task); if (id.Length == 0) id = Text(task, "titel") + "|" + Text(task, "faellig");
            var span = DateTime.TryParseExact(Text(task, "startDatum"), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var startDay) &&
                DateTime.TryParseExact(Text(task, "faellig"), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var dueDay) ? Math.Max(0, (dueDay - startDay).TotalDays) : 0;
            var lead = Math.Max(8 * 1440, alarms.Count == 0 ? 0 : alarms.Max(alarm => alarm.OffsetMinutes));
            var lag = alarms.Count == 0 ? 0 : Math.Max(0, -alarms.Min(alarm => alarm.OffsetMinutes));
            var lookback = TimeSpan.FromDays(5 + span) + TimeSpan.FromMinutes(lag);
            var lower = lookback.Ticks <= nowUtc.Ticks ? nowUtc.Subtract(lookback) : DateTime.SpecifyKind(DateTime.MinValue, DateTimeKind.Utc);
            var occurrences = ExpandForReminders(task, lower, nowUtc.AddMinutes(lead), zone, true, true, errors);
            foreach (var occurrence in occurrences)
            {
                var resultStart = result.Count;
                var due = Text(task, "faelligZeit").Length == 0 && occurrence.AllDay ? occurrence.End.Date.AddHours(8) : occurrence.End;
                var scheduledDue = occurrence.AllDay ? CalendarRecurrence.ToUtc(due, zone) : occurrence.EndUtc;
                if (True(task, "erinnern") || days > 0)
                    AddDue(result, "aufgabe:" + id, days > 0 ? "individuell" : "faellig", due, due.AddDays(-days), now, includeMissed, zone: zone,
                        dueUtc: days == 0 ? scheduledDue : CalendarRecurrence.ToUtc(due.AddDays(-days), zone), endUtc: scheduledDue, occurrenceUtc: scheduledDue);
                foreach (var alarm in alarms)
                {
                    var basis = alarm.Related == "END" ? occurrence.EndUtc : occurrence.StartUtc;
                    var trigger = basis.AddMinutes(-alarm.OffsetMinutes);
                    AddDue(result, "aufgabe:" + id, $"alarm-{alarm.Related.ToLowerInvariant()}-{alarm.OffsetMinutes}", due,
                        TimeZoneInfo.ConvertTimeFromUtc(trigger, zone), now, includeMissed, zone: zone, dueUtc: trigger,
                        endUtc: basis > trigger ? basis : trigger, occurrenceUtc: occurrence.EndUtc);
                }
                if (titles is not null && occurrence.Summary is not null)
                    foreach (var entry in result.Skip(resultStart)) titles[entry.Item1] = CalendarRecurrence.TextValue(occurrence.Summary);
            }
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
        var zone = CalendarRecurrence.OrganizerZone(root);
        var localNow = TimeZoneInfo.ConvertTimeFromUtc(CalendarRecurrence.NowUtc(now), zone);
        foreach (var item in anniversaries.EnumerateArray())
        {
            if (!ExchangeCodec.TryParseCanonicalDate(Text(item, "datum"), out _, out var month, out var day)) continue;
            foreach (var year in new[] { localNow.Year - 1, localNow.Year, localNow.Year + 1 }.Where(year => year is >= 1 and <= 9999))
            {
                var occurrenceDay = month == 2 && day == 29 && !DateTime.IsLeapYear(year) ? 28 : day;
                var occurrence = new DateOnly(year, month, occurrenceDay);
                var start = occurrence.ToDateTime(new TimeOnly(hour, 0));
                var id = Identity(item); if (id.Length == 0) id = Text(item, "name") + $"|{month:00}-{day:00}";
                if (leadDays > 0) AddDue(result, "jahrestag:" + id, "vorlauf", start, start.AddDays(-leadDays), now, true, zone: zone);
                if (onDay || leadDays == 0) AddDue(result, "jahrestag:" + id, "am-tag", start, start, now, true, zone: zone);
            }
        }
        return result;
    }

    private static void AddDue(List<(string Key, DateTime Start, DateTime Due)> result, string id,
        string mode, DateTime start, DateTime due, DateTime now, bool includeMissed, DateTime? reminderEnd = null,
        TimeZoneInfo? zone = null, DateTime? dueUtc = null, DateTime? endUtc = null, DateTime? occurrenceUtc = null)
    {
        var end = reminderEnd ?? start;
        zone ??= TimeZoneInfo.Local;
        var instant = CalendarRecurrence.NowUtc(now);
        var trigger = dueUtc ?? CalendarRecurrence.ToUtc(due, zone);
        var endInstant = endUtc ?? CalendarRecurrence.ToUtc(end, zone);
        if (trigger > endInstant) endInstant = trigger;
        if (instant < trigger || instant > endInstant.AddHours(72)) return;
        if (!includeMissed && instant > endInstant.AddMinutes(5)) return;
        var stamp = start.ToString(start.Second == 0 ? "yyyyMMddHHmm" : "yyyyMMddHHmmss", CultureInfo.InvariantCulture);
        if (occurrenceUtc is not null && zone.IsAmbiguousTime(DateTime.SpecifyKind(start, DateTimeKind.Unspecified)))
            stamp += ":utc-" + occurrenceUtc.Value.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);
        result.Add(($"{id}@{stamp}:{mode}", start, due));
    }

    private static bool TryStart(JsonElement item, out DateTime start)
    {
        start = default;
        if (!DateOnly.TryParseExact(Text(item, "datum"), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date)) return false;
        var timeText = Text(item, "zeit");
        var time = new TimeOnly(8, 0);
        if (timeText.Length > 0 && !TimeOnly.TryParseExact(timeText, ["HH:mm", "HH:mm:ss"], CultureInfo.InvariantCulture, DateTimeStyles.None, out time)) return false;
        start = date.ToDateTime(time);
        return true;
    }

    private static bool TryEnd(JsonElement item, DateTime start, out DateTime end)
    {
        end = start;
        var dateText = Text(item, "endDatum");
        var date = dateText.Length == 0
            ? DateOnly.FromDateTime(start)
            : DateOnly.TryParseExact(dateText, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsedDate) ? parsedDate : default;
        if (date == default) return false;
        var timeText = Text(item, "endZeit");
        var time = TimeOnly.FromDateTime(start);
        if (timeText.Length > 0 && !TimeOnly.TryParseExact(timeText, ["HH:mm", "HH:mm:ss"], CultureInfo.InvariantCulture, DateTimeStyles.None, out time)) return false;
        end = date.ToDateTime(time);
        return true;
    }

    private static IReadOnlyList<(int OffsetMinutes, string Related)> AppointmentAlarms(JsonElement item)
    {
        var result = new List<(int, string)>();
        if (item.TryGetProperty("alarme", out var values) && values.ValueKind == JsonValueKind.Array)
        foreach (var alarm in values.EnumerateArray().Take(32))
        {
            if (alarm.ValueKind != JsonValueKind.Object ||
                alarm.TryGetProperty("aktiviert", out var enabled) && enabled.ValueKind == JsonValueKind.False ||
                alarm.TryGetProperty("bearbeitbar", out var editable) && editable.ValueKind == JsonValueKind.False ||
                Text(alarm, "aktion") is { Length: > 0 } action && action != "display" ||
                 !alarm.TryGetProperty("offsetMinuten", out var offsetNode) || offsetNode.ValueKind != JsonValueKind.Number ||
                !offsetNode.TryGetInt32(out var offset) || offset is < 0 or > 525600) continue;
            result.Add((offset, string.Equals(Text(alarm, "related"), "END", StringComparison.OrdinalIgnoreCase)
                ? "END" : "START"));
        }
        if (item.TryGetProperty("icsRoundtrip", out var raw) && raw.ValueKind == JsonValueKind.Array)
        {
            var inAlarm = false; var display = false; CalendarRecurrence.Property? trigger = null;
            foreach (var line in raw.EnumerateArray())
            {
                if (line.ValueKind != JsonValueKind.String || CalendarRecurrence.ParseProperty(line.GetString()!) is not { } property) continue;
                if (property.Name == "BEGIN" && property.Value == "VALARM") { inAlarm = true; display = false; trigger = null; }
                else if (inAlarm && property.Name == "ACTION") display = property.Value.Equals("DISPLAY", StringComparison.OrdinalIgnoreCase);
                else if (inAlarm && property.Name == "TRIGGER") trigger = property;
                else if (inAlarm && property.Name == "END" && property.Value == "VALARM")
                {
                    if (display && trigger is { } alarmTrigger && TryAlarmOffset(alarmTrigger.Value, out var offset))
                        result.Add((offset, alarmTrigger.Parameter("RELATED") == "END" ? "END" : "START"));
                    inAlarm = false;
                }
            }
        }
        return result.Distinct().ToArray();
    }

    private static bool TryAlarmOffset(string value, out int minutes)
    {
        minutes = 0;
        try
        {
            var duration = CalendarRecurrence.Duration(value.TrimStart('-'));
            if (duration.TotalMinutes > 525600) return false;
            minutes = checked((int)Math.Ceiling(duration.TotalMinutes)) * (value.StartsWith('-') ? 1 : -1);
            return true;
        }
        catch (InvalidDataException) { return false; }
    }

    private static string FindTitle(JsonElement root, string key)
    {
        var separator = key.LastIndexOf('@');
        var id = separator > 0 ? key[..separator] : key;
        if (id.StartsWith("aufgabe:", StringComparison.Ordinal))
            return FindItemTitle(root, "aufgaben", id[8..], "titel", NativeLocalization.Gettext("Task"));
        if (id.StartsWith("jahrestag:", StringComparison.Ordinal))
            return FindItemTitle(root, "jahrestage", id[10..], "name", NativeLocalization.Gettext("Anniversary"));
        if (root.TryGetProperty("termine", out var appointments) && appointments.ValueKind == JsonValueKind.Array)
            foreach (var item in appointments.EnumerateArray())
                if (Identity(item) == id || key.StartsWith($"{Text(item, "datum")}|{Text(item, "zeit")}|{Text(item, "titel")}@", StringComparison.Ordinal))
                    return Text(item, "titel") is { Length: > 0 } title ? title : NativeLocalization.Gettext("Appointment");
        return NativeLocalization.Gettext("Appointment");
    }

    private static string FindItemTitle(JsonElement root, string collection, string id, string titleField, string fallback)
    {
        if (root.TryGetProperty(collection, out var items) && items.ValueKind == JsonValueKind.Array)
            foreach (var item in items.EnumerateArray())
                if (Identity(item) == id || id.StartsWith(Text(item, titleField) + "|", StringComparison.Ordinal))
                    return Text(item, titleField) is { Length: > 0 } title ? title : fallback;
        return fallback;
    }

    private bool Persist(DateTime now)
    {
        try
        {
            string[] values;
            Dictionary<string, DateTime> timestamps;
            lock (gate)
            {
                // Follow-up alarms can be delivered long after their occurrence started.
                var cutoff = CalendarRecurrence.NowUtc(now).AddDays(-10);
                foreach (var key in reported.Where(key => reportedAt.TryGetValue(key, out var timestamp) && timestamp < cutoff).ToArray())
                { reported.Remove(key); reportedAt.Remove(key); }
                values = reported.Order().ToArray();
                timestamps = values.ToDictionary(key => key, key => reportedAt[key], StringComparer.Ordinal);
            }
            store.WriteRecoverableJson(statePath, JsonSerializer.Serialize(new { version = 2, reported = values, reportedAt = timestamps }));
            dirty = false;
            return true;
        }
        catch (Exception) { return false; }
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
        var result = SelectFields(item, "id", "uid", "icsQuelleId", "syncKalenderUid", "datum", "zeit", "endDatum", "endZeit", "titel",
            "individuelleErinnerungTage", "standardErinnerung", "wiederholung", "icsAusnahmen",
            "icsZusatzDaten", "icsZusatzTermine", "icsAusnahmeTermine", "icsStatus", "icsTimezones");
        result["icsRoundtrip"] = ReminderRaw(item);
        result["icsRangeOverrides"] = ReminderRanges(item);
        if (!item.TryGetProperty("alarme", out var alarms) || alarms.ValueKind != JsonValueKind.Array) return result;
        var selected = new JsonArray();
        foreach (var alarm in alarms.EnumerateArray().Take(32))
            if (alarm.ValueKind == JsonValueKind.Object &&
                (!alarm.TryGetProperty("bearbeitbar", out var editable) || editable.ValueKind != JsonValueKind.False))
                selected.Add(SelectFields(alarm, "offsetMinuten", "aktiviert", "related", "aktion"));
        result["alarme"] = selected;
        return result;
    }

    private static JsonArray ReminderRaw(JsonElement item)
    {
        var result = new JsonArray();
        if (!item.TryGetProperty("icsRoundtrip", out var lines) || lines.ValueKind != JsonValueKind.Array) return result;
        foreach (var line in lines.EnumerateArray())
            if (line.ValueKind == JsonValueKind.String && CalendarRecurrence.ParseProperty(line.GetString()!) is { } property &&
                 (property.Name is "DTSTART" or "DTEND" or "DUE" or "DURATION" or "RRULE" or "RDATE" or "EXDATE" or "EXRULE" or "RECURRENCE-ID" or "STATUS" or "SUMMARY" or "LOCATION" or "ACTION" or "TRIGGER" ||
                 property.Name is "BEGIN" or "END" && property.Value == "VALARM"))
            {
                var parameters = property.Parameters.Where(value => new[] { "TZID", "VALUE", "RELATED", "RANGE" }.Contains(value.Split('=', 2)[0].ToUpperInvariant()));
                result.Add(property.Name + string.Concat(parameters.Select(value => ";" + value)) + ":" + property.Value);
            }
        return result;
    }

    private static JsonArray ReminderRanges(JsonElement item)
    {
        var result = new JsonArray();
        if (!item.TryGetProperty("icsRangeOverrides", out var ranges) || ranges.ValueKind != JsonValueKind.Array) return result;
        foreach (var range in ranges.EnumerateArray().Where(value => value.ValueKind == JsonValueKind.Array))
        {
            using var wrapper = JsonDocument.Parse(new JsonObject { ["icsRoundtrip"] = JsonNode.Parse(range.GetRawText()) }.ToJsonString());
            result.Add(ReminderRaw(wrapper.RootElement));
        }
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
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) ? number : fallback;
    private static bool True(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    private static string Identity(JsonElement item)
    {
        var id = Text(item, "id"); if (id.Length > 0) return id;
        var uid = Text(item, "uid"); if (uid.Length == 0) return "";
        var source = Text(item, "icsQuelleId"); if (source.Length == 0) source = Text(item, "syncKalenderUid");
        return source.Length == 0 ? uid : $"scope:{source.Length}:{source}:{uid}";
    }

    public void Dispose()
    {
        lock (gate) { enabled = false; timer?.Dispose(); timer = null; }
    }

    internal async Task ShutdownAsync()
    {
        System.Threading.Timer? current;
        lock (gate) { enabled = false; current = timer; timer = null; }
        if (current is not null) await current.DisposeAsync().ConfigureAwait(false);
        while (Volatile.Read(ref running) != 0) await Task.Delay(10).ConfigureAwait(false);
    }
}
