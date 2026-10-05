using System.Globalization;
using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static partial class DocumentExportService
{
    private static readonly XNamespace Number = "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0";
    private static readonly XNamespace Formula = "urn:oasis:names:tc:opendocument:xmlns:of:1.2";
    private sealed record TimeRow(DateTimeOffset Start, DateTimeOffset? End, long Pause, string Activity, string Note, string Zone, long? Gross, long StartMinute);

    internal static byte[] CreateTimeSpreadsheet(JsonElement report)
    {
        string Required(JsonElement parent, string name, int maximum = 160)
        {
            var value = Value(parent, name);
            if (!parent.TryGetProperty(name, out var raw) || raw.ValueKind != JsonValueKind.String || value.Length > maximum)
                throw new ArgumentException(NativeLocalization.Gettext("The ODS columns are invalid."));
            return value;
        }
        var month = Required(report, "month", 7);
        if (!DateOnly.TryParseExact(month + "-01", "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var first))
            throw new ArgumentException(NativeLocalization.Gettext("The ODS title is invalid."));
        var labels = report.GetProperty("labels");
        var headings = StringArray(labels, "columns");
        if (headings.Length != 10 || headings.Any(value => string.IsNullOrWhiteSpace(value) || value.Length > 160))
            throw new ArgumentException(NativeLocalization.Gettext("The ODS columns are invalid."));
        foreach (var name in new[] { "title", "name", "date", "signature", "total", "clock" }) Required(labels, name);
        var locale = Required(report, "locale", 32);
        var language = locale.Split('-')[0];
        var country = locale.Split('-').Skip(1).FirstOrDefault(value => value.Length == 2)?.ToUpperInvariant();
        _ = CultureInfo.GetCultureInfo(locale);
        var digits = Required(report, "digits", 10);
        if (digits.Length != 10 || digits.Where((value, index) => char.GetNumericValue(value) != index).Any())
            throw new ArgumentException(NativeLocalization.Gettext("The ODS columns are invalid."));
        var weekdays = StringArray(report, "weekdays"); var periods = StringArray(report, "periods");
        if (weekdays.Length != 7 || periods.Length != 2 || weekdays.Concat(periods).Any(value => value.Length > 64))
            throw new ArgumentException(NativeLocalization.Gettext("The ODS columns are invalid."));
        var dateParts = Parts(report.GetProperty("dateParts"), false);
        var timeParts = Parts(report.GetProperty("timeParts"), true);
        var twelve = timeParts.Any(part => part.Type == "dayPeriod");
        var days = report.TryGetProperty("days", out var selection)
            ? selection.EnumerateArray().Select(value => value.GetInt32()).ToArray()
            : Enumerable.Range(1, DateTime.DaysInMonth(first.Year, first.Month)).ToArray();
        if (days.Length == 0 || days.Distinct().Count() != days.Length || days.Any(day => day < 1 || day > DateTime.DaysInMonth(first.Year, first.Month)))
            throw new ArgumentException(NativeLocalization.Gettext("The ODS row count is invalid."));
        Array.Sort(days);
        var holidays = new Dictionary<string, List<string>>(StringComparer.Ordinal);
        if (report.TryGetProperty("calendar", out var calendarElement))
        {
            var calendar = JsonNode.Parse(calendarElement.GetRawText())!.AsObject();
            TimeSyncContract.ValidateCalendar(calendar);
            if (calendar["enabled"]!.GetValue<bool>())
            {
                var selectedCountry = calendar["country"]!.GetValue<string>();
                string Region(string value) => value.Contains('-') ? value.ToUpperInvariant() : selectedCountry + "-" + value.ToUpperInvariant();
                var regions = calendar["regions"]!.AsArray().Select(value => Region(value!.GetValue<string>())).ToHashSet(StringComparer.Ordinal);
                foreach (var holiday in calendar["holidays"]!.AsArray().OfType<JsonObject>())
                {
                    if (holiday["country"]!.GetValue<string>() != selectedCountry || regions.Count > 0 &&
                        !holiday["nationwide"]!.GetValue<bool>() && !holiday["regions"]!.AsArray().Any(value => regions.Contains(Region(value!.GetValue<string>())))) continue;
                    var date = holiday["date"]!.GetValue<string>();
                    if (!holidays.TryGetValue(date, out var names)) holidays[date] = names = [];
                    var title = holiday["name"]!.GetValue<string>(); if (!names.Contains(title)) names.Add(title);
                }
            }
        }
        var rows = new Dictionary<int, List<TimeRow>>(); var ids = new HashSet<string>(StringComparer.Ordinal);
        var totalCharacters = 0;
        var incoming = report.GetProperty("entries");
        if (incoming.ValueKind != JsonValueKind.Array || incoming.GetArrayLength() > 9969)
            throw new ArgumentException(NativeLocalization.Gettext("The ODS row count is invalid."));
        foreach (var entry in incoming.EnumerateArray())
        {
            var id = Required(entry, "id", 36);
            if (!Guid.TryParseExact(id, "D", out var parsedId) || parsedId.ToString("D") != id || !ids.Add(id)) throw new ArgumentException("Invalid time identity.");
            if (entry.TryGetProperty("deleted", out var deleted) && deleted.ValueKind == JsonValueKind.True) continue;
            var start = entry.GetProperty("startMinute").GetInt64();
            var end = entry.TryGetProperty("endMinute", out var rawEnd) && rawEnd.ValueKind != JsonValueKind.Null ? rawEnd.GetInt64() : (long?)null;
            var pause = entry.TryGetProperty("pauseMinutes", out var rawPause) ? rawPause.GetInt64() : 0;
            if (start is < 0 or > 4223371679 || pause < 0 || pause > 4223371679 - start || end is not null &&
                (end < start || end > 4223371679 || pause > end - start)) throw new ArgumentException("Invalid time interval.");
            var zoneName = Required(entry, "zone", 160);
            var localStart = TimeSheetProjectedLocal(entry, "localStartMinute", start, zoneName);
            var localEnd = end is null ? null : (DateTimeOffset?)TimeSheetProjectedLocal(entry, "localEndMinute", end.Value, zoneName);
            var activity = Required(entry, "type", 120); var note = Required(entry, "note", 20000);
            totalCharacters += activity.Length + note.Length;
            if (totalCharacters > 4 * 1024 * 1024) throw new ArgumentException(NativeLocalization.Gettext("The ODS export is too large."));
            if (localStart.Year != first.Year || localStart.Month != first.Month) continue;
            if (!rows.TryGetValue(localStart.Day, out var values)) rows[localStart.Day] = values = [];
            values.Add(new TimeRow(localStart, localEnd, pause, activity, note, zoneName, end - start, start));
        }
        string LocalDigits(string value) => string.Concat(value.Select(character => character is >= '0' and <= '9' ? digits[character - '0'] : character));
        string Duration(long minutes) => LocalDigits((minutes / 60).ToString("00", CultureInfo.InvariantCulture) + ":" + (minutes % 60).ToString("00", CultureInfo.InvariantCulture));
        string Display(DateTime value, IReadOnlyList<(string Type, string Value)> parts) => string.Concat(parts.Select(part => part.Type switch {
            "literal" => part.Value, "weekday" => weekdays[(int)value.DayOfWeek], "dayPeriod" => periods[value.Hour >= 12 ? 1 : 0],
            "year" => LocalDigits(value.Year.ToString("0000", CultureInfo.InvariantCulture)), "month" => LocalDigits(value.Month.ToString("00", CultureInfo.InvariantCulture)),
            "day" => LocalDigits(value.Day.ToString("00", CultureInfo.InvariantCulture)), "minute" => LocalDigits(value.Minute.ToString("00", CultureInfo.InvariantCulture)),
            "hour" => LocalDigits((twelve ? (value.Hour + 11) % 12 + 1 : value.Hour).ToString("00", CultureInfo.InvariantCulture)), _ => throw new ArgumentException() }));
        var suffix = "";
        XElement Cell(string value = "", string style = "cell", params XAttribute[] attributes) => new(Table + "table-cell",
            new XAttribute(Table + "style-name", style + (new[] { "cell", "date", "clock", "duration", "integer" }.Contains(style) ? suffix : "")),
            attributes.Any(attribute => attribute.Name == Office + "value-type") ? null : new XAttribute(Office + "value-type", "string"), attributes,
            new XElement(Text + "p", value.Split('\n').SelectMany((line, index) => index == 0 ? new object[] { line } : new object[] { new XElement(Text + "line-break"), line })));
        XElement DateCell(DateTime value) => Cell(Display(value, dateParts), "date", new XAttribute(Office + "value-type", "date"),
            new XAttribute(Office + "date-value", value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)));
        XElement ClockCell(DateTimeOffset? value) => value is null ? Cell() : Cell(Display(value.Value.DateTime, timeParts), "clock",
            new XAttribute(Office + "value-type", "time"), new XAttribute(Office + "time-value", $"PT{value.Value.Hour}H{value.Value.Minute}M"));
        XElement Integer(long value) => Cell(LocalDigits(value.ToString(CultureInfo.InvariantCulture)), "integer", new XAttribute(Office + "value-type", "float"), new XAttribute(Office + "value", value));
        XElement FormulaCell(string formula, long? minutes, bool integer = false) => minutes is null
            ? Cell("", "duration", new XAttribute(Table + "formula", "of:=" + formula))
            : Cell(integer ? LocalDigits(minutes.Value.ToString(CultureInfo.InvariantCulture)) : Duration(minutes.Value), integer ? "integer" : "duration",
                new XAttribute(Table + "formula", "of:=" + formula), new XAttribute(Office + "value-type", "float"), new XAttribute(Office + "value", integer ? minutes.Value : minutes.Value / 1440d));
        XElement Row(IEnumerable<XElement> cells) => new(Table + "table-row", cells);
        XElement Banner(string value, string style = "cell") => Row(new[] { Cell(value, style, new XAttribute(Table + "number-columns-spanned", 10)) }
            .Concat(Enumerable.Range(0, 9).Select(_ => new XElement(Table + "covered-table-cell"))).Append(Cell()));
        var bodyRows = new List<XElement>(); long grossTotal = 0, pauseTotal = 0, netTotal = 0;
        foreach (var day in days)
        {
            var date = new DateTime(first.Year, first.Month, day);
            var holidayNames = holidays.GetValueOrDefault(date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)) ?? [];
            suffix = holidayNames.Count > 0 ? "Holiday" : date.DayOfWeek == DayOfWeek.Sunday ? "Sunday" : "";
            foreach (var value in (rows.GetValueOrDefault(day) ?? [new TimeRow(new DateTimeOffset(date, TimeSpan.Zero), null, 0, "", "", "", null, 0)]).OrderBy(value => value.StartMinute))
            {
                var n = 7 + bodyRows.Count;
                var delta = $"ROUND(([.D{n}]+[.E{n}]-[.A{n}]-[.C{n}])*1440-[.J{n}];0)";
                var grossFormula = $"IF(COUNT([.A{n}];[.C{n}];[.D{n}];[.E{n}])=4;IF({delta}<0;NA();{delta}/1440);\"\")";
                var pauseFormula = $"IF([.F{n}]=\"\";\"\";IF(AND(ISNUMBER([.G{n}]);[.G{n}]>=0;MOD([.G{n}];1)=0);[.G{n}]/1440;NA()))";
                var netFormula = $"IF([.F{n}]=\"\";\"\";IF([.K{n}]>[.F{n}];NA();[.F{n}]-[.K{n}]))";
                var adjustment = value.End is null ? 0 : (long)((value.End.Value.DateTime.AddSeconds(-value.End.Value.Second) -
                    value.Start.DateTime.AddSeconds(-value.Start.Second)).TotalMinutes - value.Gross!.Value);
                bodyRows.Add(Row(new[] { DateCell(value.Start.DateTime), Cell(value.Activity), ClockCell(value.Zone.Length > 0 ? value.Start : null),
                    DateCell((value.End ?? value.Start).DateTime), ClockCell(value.End), FormulaCell(grossFormula, value.Gross), Integer(value.Pause),
                    FormulaCell(netFormula, value.Gross - value.Pause), Cell(string.Join("\n", new[] { value.Note }.Concat(holidayNames).Append(value.Zone).Where(text => text.Length > 0))),
                    Integer(adjustment), FormulaCell(pauseFormula, value.Gross is null ? null : value.Pause) }));
                if (value.Gross is not null) { grossTotal += value.Gross.Value; pauseTotal += value.Pause; netTotal += value.Gross.Value - value.Pause; }
            }
        }
        suffix = ""; var last = 6 + bodyRows.Count;
        var automatic = TimeStyles(language, country, dateParts, timeParts);
        var widths = new[] { 3d, 3, 1.8, 3, 1.8, 1.6, 1.8, 1.8, 4.7, 2.2, 1 };
        for (var i = 0; i < widths.Length; i++) automatic.Add(new XElement(Style + "style", new XAttribute(Style + "name", "col" + i),
            new XAttribute(Style + "family", "table-column"), new XElement(Style + "table-column-properties", new XAttribute(Style + "column-width", widths[i].ToString("0.0", CultureInfo.InvariantCulture) + "cm"))));
        var table = new XElement(Table + "table", new XAttribute(Table + "name", month), new XAttribute(Table + "style-name", "sheet"),
            new XAttribute(Table + "print-ranges", $"'{month}'.A1:J{last + 4}"),
            Enumerable.Range(0, 11).Select(i => new XElement(Table + "table-column", new XAttribute(Table + "style-name", "col" + i), i == 10 ? new XAttribute(Table + "visibility", "collapse") : null)),
            Banner(Required(labels, "title"), "title"), Banner(Required(labels, "name") + ": " + Required(report, "name", 240)), Banner(Required(report, "monthTitle")),
            Row(Enumerable.Range(0, 11).Select(_ => Cell())),
            new XElement(Table + "table-header-rows", Row(new[] { Cell(), Cell(), Cell(Required(labels, "clock"), "header", new XAttribute(Table + "number-columns-spanned", 3)),
                new XElement(Table + "covered-table-cell"), new XElement(Table + "covered-table-cell") }.Concat(Enumerable.Range(0, 6).Select(_ => Cell()))),
                Row(headings.Select(value => Cell(value, "header")).Append(Cell()))), bodyRows,
            Row(new[] { Cell(Required(labels, "total"), "header") }.Concat(Enumerable.Range(0, 4).Select(_ => Cell())).Concat(new[] {
                FormulaCell($"SUM([.F7:.F{last}])", grossTotal), FormulaCell($"SUM([.K7:.K{last}])*1440", pauseTotal, true),
                FormulaCell($"SUM([.H7:.H{last}])", netTotal), Cell(), Cell(), Cell() })), Row(Enumerable.Range(0, 11).Select(_ => Cell())),
            Banner(Required(labels, "date") + ": ____________________     " + Required(labels, "signature") + ": ____________________"));
        var content = new XDocument(new XElement(Office + "document-content", NamespaceAttributes(), new XAttribute(XNamespace.Xmlns + "number", Number),
            new XAttribute(XNamespace.Xmlns + "of", Formula), new XAttribute(Office + "version", "1.2"), automatic, new XElement(Office + "body", new XElement(Office + "spreadsheet", table))));
        var styles = new XDocument(new XElement(Office + "document-styles", NamespaceAttributes(), new XAttribute(Office + "version", "1.2"),
            new XElement(Office + "automatic-styles", new XElement(Style + "page-layout", new XAttribute(Style + "name", "Page"),
                new XElement(Style + "page-layout-properties", new XAttribute(Fo + "page-width", "29.7cm"), new XAttribute(Fo + "page-height", "21cm"),
                    new XAttribute(Style + "print-orientation", "landscape"), new XAttribute(Fo + "margin", "1cm"), new XAttribute(Style + "scale-to-X", 1), new XAttribute(Style + "scale-to-Y", 0)))),
            new XElement(Office + "master-styles", new XElement(Style + "master-page", new XAttribute(Style + "name", "Magnolie"), new XAttribute(Style + "page-layout-name", "Page")))));
        using var output = new MemoryStream();
        using (var archive = new ZipArchive(output, ZipArchiveMode.Create, true))
        {
            WriteEntry(archive, "mimetype", "application/vnd.oasis.opendocument.spreadsheet", CompressionLevel.NoCompression);
            WriteEntry(archive, "content.xml", content.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
            WriteEntry(archive, "styles.xml", styles.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
            var manifest = new XElement(Manifest + "manifest", new XAttribute(XNamespace.Xmlns + "manifest", Manifest), new XAttribute(Manifest + "version", "1.2"),
                new[] { ("/", "application/vnd.oasis.opendocument.spreadsheet"), ("content.xml", "text/xml"), ("styles.xml", "text/xml") }.Select(item =>
                    new XElement(Manifest + "file-entry", new XAttribute(Manifest + "full-path", item.Item1), new XAttribute(Manifest + "media-type", item.Item2))));
            WriteEntry(archive, "META-INF/manifest.xml", manifest.ToString(SaveOptions.DisableFormatting), CompressionLevel.Optimal);
        }
        return output.ToArray();
    }

    private static DateTimeOffset TimeSheetProjectedLocal(JsonElement entry, string property, long minute, string zone)
    {
        var local = TimeSheetLocal(minute, zone);
        if (!entry.TryGetProperty(property, out var raw)) return local;
        var projected = raw.GetInt64();
        var nativeMinute = new DateTimeOffset(DateTime.SpecifyKind(local.DateTime.AddSeconds(-local.Second), DateTimeKind.Utc)).ToUnixTimeSeconds() / 60;
        // TimeZoneInfo rounds historical sub-minute offsets. The browser's ICU projection
        // keeps these minute cells identical to Notes, with at most that one-minute correction.
        if (projected < -1080 || projected > 4223371679L + 1080 || Math.Abs(projected - nativeMinute) > 1)
            throw new ArgumentException(NativeLocalization.Gettext("The ODS columns are invalid."));
        return DateTimeOffset.FromUnixTimeSeconds(projected * 60);
    }

    private static DateTimeOffset TimeSheetLocal(long minute, string zone)
    {
        var instant = DateTimeOffset.FromUnixTimeSeconds(minute * 60);
        if (zone is "UTC" or "GMT" or "UT" or "Z") return instant;
        var match = Regex.Match(zone, @"^(?:UTC|GMT|UT)?([+-])([0-9]{2})(?::([0-9]{2}))?$");
        if (!match.Success) return TimeZoneInfo.ConvertTime(instant, TimeZoneInfo.FindSystemTimeZoneById(zone));
        var hours = int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture);
        var minutes = match.Groups[3].Success ? int.Parse(match.Groups[3].Value, CultureInfo.InvariantCulture) : 0;
        if (hours > 18 || minutes > 59 || hours == 18 && minutes != 0) throw new ArgumentException("Invalid time zone.");
        var offset = (hours * 60 + minutes) * (match.Groups[1].Value == "-" ? -1 : 1);
        // These values render civil cells only; elapsed time and ordering use the original UTC minutes.
        return new DateTimeOffset(instant.UtcDateTime.AddMinutes(offset), TimeSpan.Zero);
    }

    private static (string Type, string Value)[] Parts(JsonElement source, bool time)
    {
        var parts = source.EnumerateArray().Select(value => (Type: Value(value, "type"), Value: Value(value, "value"))).ToArray();
        var allowed = time ? new[] { "hour", "minute", "dayPeriod", "literal" } : new[] { "year", "month", "day", "weekday", "literal" };
        var required = time ? new[] { "hour", "minute" } : new[] { "year", "month", "day" };
        if (parts.Length is < 3 or > 16 || parts.Any(part => !allowed.Contains(part.Type) || part.Value.Length > 64) ||
            required.Any(type => parts.Count(part => part.Type == type) != 1) || parts.Where(part => part.Type != "literal").GroupBy(part => part.Type).Any(group => group.Count() > 1))
            throw new ArgumentException("Invalid date/time format parts.");
        return parts;
    }

    private static XElement TimeStyles(string language, string? country, (string Type, string Value)[] dates, (string Type, string Value)[] times)
    {
        object[] Locale() => country is null ? [new XAttribute(Number + "language", language)] : [new XAttribute(Number + "language", language), new XAttribute(Number + "country", country)];
        XElement Format(string name, (string Type, string Value)[] parts, bool time) => new(Number + (time ? "time-style" : "date-style"),
            new XAttribute(Style + "name", name), Locale(), parts.Select(part => part.Type switch {
                "literal" => new XElement(Number + "text", part.Value), "dayPeriod" => new XElement(Number + "am-pm"),
                _ => new XElement(Number + (part.Type switch { "hour" => "hours", "minute" => "minutes", "weekday" => "day-of-week", _ => part.Type }),
                    new XAttribute(Number + "style", part.Type == "weekday" ? "short" : "long")) }));
        var styles = new XElement(Office + "automatic-styles", Format("dateFormat", dates, false), Format("clockFormat", times, true),
            new XElement(Number + "time-style", new XAttribute(Style + "name", "durationFormat"), new XAttribute(Number + "truncate-on-overflow", "false"), Locale(),
                new XElement(Number + "hours", new XAttribute(Number + "style", "long")), new XElement(Number + "text", ":"), new XElement(Number + "minutes", new XAttribute(Number + "style", "long"))),
            new XElement(Number + "number-style", new XAttribute(Style + "name", "integerFormat"), Locale(),
                new XElement(Number + "number", new XAttribute(Number + "decimal-places", 0), new XAttribute(Number + "min-integer-digits", 1))),
            new XElement(Style + "style", new XAttribute(Style + "name", "sheet"), new XAttribute(Style + "family", "table"), new XAttribute(Style + "master-page-name", "Magnolie"),
                new XElement(Style + "table-properties", new XAttribute(Style + "writing-mode", language == "ar" ? "rl-tb" : "lr-tb"))));
        foreach (var suffix in new[] { "", "Sunday", "Holiday" }) foreach (var kind in new[] { "cell", "date", "clock", "duration", "integer" })
        {
            var style = CellStyleElement(kind + suffix, suffix == "Sunday" ? "#f4efe5" : suffix == "Holiday" ? "#e8f0eb" : "#ffffff", "#3d2a1d", "none", "8pt", false, kind == "cell" ? "left" : "right", "middle");
            style.Element(Style + "table-cell-properties")!.SetAttributeValue(Fo + "padding", "0.05cm");
            style.Element(Style + "table-cell-properties")!.SetAttributeValue(Fo + "border-bottom", "0.01cm solid #c9baa0");
            if (kind != "cell") style.Add(new XAttribute(Style + "data-style-name", kind + "Format"));
            styles.Add(style);
        }
        foreach (var heading in new[] { ("title", "20pt", "#f8f1e1", "#4b3022"), ("header", "9pt", "#5b3927", "#f6e5b7") })
        {
            var style = CellStyleElement(heading.Item1, heading.Item3, heading.Item4, "none", heading.Item2, true, "left", "middle");
            style.Element(Style + "table-cell-properties")!.SetAttributeValue(Fo + "padding", "0.05cm");
            styles.Add(style);
        }
        return styles;
    }
}
