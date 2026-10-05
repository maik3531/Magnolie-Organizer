using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeSheetExportTests
{
    internal static Task RunAsync()
    {
        JsonArray Parts(params (string Type, string Value)[] parts) => new(parts.Select(part => (JsonNode)new JsonObject { ["type"] = part.Type, ["value"] = part.Value }).ToArray());
        long Minute(string date) => DateTimeOffset.Parse(date, System.Globalization.CultureInfo.InvariantCulture).ToUnixTimeSeconds() / 60;
        var report = new JsonObject
        {
            ["month"] = "2026-10", ["monthTitle"] = "October 2026", ["name"] = "Synthetic name", ["locale"] = "en-US",
            ["digits"] = "0123456789", ["weekdays"] = new JsonArray("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"),
            ["periods"] = new JsonArray("AM", "PM"),
            ["dateParts"] = Parts(("month", "10"), ("literal", "/"), ("day", "04"), ("literal", "/"), ("year", "2026")),
            ["timeParts"] = Parts(("hour", "02"), ("literal", ":"), ("minute", "35"), ("literal", " "), ("dayPeriod", "PM")),
            ["labels"] = new JsonObject { ["title"] = "Time tracking", ["name"] = "Name", ["date"] = "Date", ["signature"] = "Signature",
                ["total"] = "Total", ["clock"] = "Time", ["columns"] = new JsonArray("Date", "Activity", "Start", "End date", "End", "Hours", "Pause (minutes)", "Total time", "Note", "Clock change (min)") },
            ["entries"] = new JsonArray(new JsonObject { ["id"] = Guid.NewGuid().ToString("D"), ["startMinute"] = Minute("2026-10-01T00:00:00Z"),
                ["endMinute"] = Minute("2026-10-08T01:00:00Z"), ["pauseMinutes"] = 30, ["zone"] = "UTC", ["type"] = "Synthetic activity", ["note"] = "=HYPERLINK(\"not a formula\")" }),
            ["calendar"] = new JsonObject { ["enabled"] = true, ["country"] = "DE", ["regions"] = new JsonArray("DE-TH"),
                ["holidays"] = new JsonArray(new JsonObject { ["date"] = "2026-10-31", ["name"] = "Regional fixture", ["country"] = "DE", ["nationwide"] = false, ["regions"] = new JsonArray("DE-TH") }) }
        };
        byte[] Render(JsonObject value)
        {
            using var document = JsonDocument.Parse(value.ToJsonString());
            return DocumentExportService.CreateTimeSpreadsheet(document.RootElement);
        }
        var bytes = Render(report);
        using var archive = new ZipArchive(new MemoryStream(bytes));
        using var content = archive.GetEntry("content.xml")!.Open();
        var xml = XDocument.Load(content);
        XNamespace table = "urn:oasis:names:tc:opendocument:xmlns:table:1.0";
        XNamespace office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0";
        XNamespace number = "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0";
        var rows = xml.Descendants(table + "table").Single().Elements(table + "table-row").ToArray();
        var visible = xml.Descendants(table + "table-column").Select((column, index) => (column, index))
            .Where(value => (string?)value.column.Attribute(table + "visibility") != "collapse").Select(value => value.index);
        TestAssert.That(visible.SequenceEqual(new[] { 0, 2, 4, 5, 6, 7 }), "Portrait template must expose exactly six columns.");
        var blankRows = xml.Descendants(table + "table-row-group").Single().Elements(table + "table-row").ToArray();
        TestAssert.That(blankRows.Length == 9 && blankRows.All(row => new[] { 3, 5, 7, 10 }.All(index =>
            row.Elements(table + "table-cell").ElementAt(index).Attribute(table + "formula") is not null)), "Blank writing rows need editable time formulas.");
        using var stylesStream = archive.GetEntry("styles.xml")!.Open();
        XNamespace style = "urn:oasis:names:tc:opendocument:xmlns:style:1.0";
        TestAssert.That((string?)XDocument.Load(stylesStream).Descendants(style + "page-layout-properties").Single().Attribute(style + "print-orientation") == "portrait",
            "Timesheet must print in portrait orientation.");
        TestAssert.That(rows.Length == 38 && xml.Descendants().Any(node => node.Value == "168:30"), "Monthly time report lost free days or wrapped its duration.");
        TestAssert.That(xml.Descendants(number + "am-pm").Any() && !xml.Descendants(number + "seconds").Any(), "Time clock format omitted AM/PM or added seconds.");
        var first = rows[4].Elements(table + "table-cell").ToArray();
        TestAssert.That(first[5].Attribute(table + "formula") is not null && first[7].Attribute(table + "formula") is not null && first[10].Attribute(table + "formula") is not null,
            "Gross, pause conversion or net formula is missing.");
        TestAssert.That(first[8].Attribute(table + "formula") is null && (string?)first[8].Attribute(office + "value-type") == "string", "User note became a spreadsheet formula.");
        TestAssert.That(rows[34].Elements(table + "table-cell").First().Attribute(table + "style-name")!.Value == "dateHoliday", "Scoped regional holiday not highlighted.");
        report["days"] = new JsonArray(1, 31);
        using var selectedZip = new ZipArchive(new MemoryStream(Render(report)));
        using var selectedContent = selectedZip.GetEntry("content.xml")!.Open();
        TestAssert.That(XDocument.Load(selectedContent).Descendants(table + "table").Single().Elements(table + "table-row").Count() == 9,
            "Selected-day report exported additional days.");
        XElement[] DailyCells(JsonObject value)
        {
            using var zipped = new ZipArchive(new MemoryStream(Render(value)));
            using var stream = zipped.GetEntry("content.xml")!.Open();
            return XDocument.Load(stream).Descendants(table + "table").Single().Elements(table + "table-row").ElementAt(4)
                .Elements(table + "table-cell").ToArray();
        }
        var fixedOffset = report.DeepClone().AsObject(); fixedOffset["days"] = new JsonArray(1);
        fixedOffset["entries"]![0]!["zone"] = "UTC+05:30";
        TestAssert.That(DailyCells(fixedOffset)[2].Value == "05:30 AM", "Fixed UTC offsets must render like Notes.");
        fixedOffset["entries"]![0]!["zone"] = "UTC+18:00";
        TestAssert.That(DailyCells(fixedOffset)[2].Value == "06:00 PM", "The full supported fixed-offset range must remain printable.");
        var historic = report.DeepClone().AsObject(); historic["month"] = "1972-01"; historic["monthTitle"] = "January 1972";
        historic["days"] = new JsonArray(6);
        historic["entries"]![0]!["startMinute"] = Minute("1972-01-07T00:00:00Z");
        historic["entries"]![0]!["endMinute"] = Minute("1972-01-07T02:00:00Z");
        historic["entries"]![0]!["zone"] = "Africa/Monrovia"; historic["entries"]![0]!["pauseMinutes"] = 0;
        historic["entries"]![0]!["localStartMinute"] = Minute("1972-01-06T23:15:00Z");
        historic["entries"]![0]!["localEndMinute"] = Minute("1972-01-07T02:00:00Z");
        var historicCells = DailyCells(historic);
        TestAssert.That((string?)historicCells[9].Attribute(office + "value") == "45",
            $"Minute cells need historical clock adjustment 45; got {historicCells[2].Value}–{historicCells[4].Value}, adjustment {historicCells[9].Value}.");
        historic["entries"]![0]!["localStartMinute"] = Minute("1972-01-07T00:15:00Z");
        TestAssert.Throws<ArgumentException>(() => Render(historic), "An unrelated civil-clock projection was accepted.");
        var output = Environment.GetEnvironmentVariable("MAGNOLIE_ODS_FIXTURE_OUTPUT");
        if (!string.IsNullOrEmpty(output))
        {
            if (!Directory.Exists(output)) throw new DirectoryNotFoundException(output);
            File.WriteAllBytes(Path.Combine(output, "time-windows.ods"), bytes);
        }
        return Task.CompletedTask;
    }
}
