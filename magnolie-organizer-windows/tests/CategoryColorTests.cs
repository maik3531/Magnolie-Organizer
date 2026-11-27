using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.IO.Compression;
using System.Xml.Linq;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CategoryColorTests
{
    internal static Task ExternalIcsColoursAsync()
    {
        var cases = new[] {
            ("", "COLOR:turquoise", "#40e0d0"),
            ("", "COLOR:RED", "#ff0000"),
            ("COLOR:turquoise", "", "#40e0d0"),
            ("X-APPLE-CALENDAR-COLOR:#40E0D0", "", "#40e0d0"),
            ("X-APPLE-CALENDAR-COLOR:#40E0D0FF", "", "#40e0d0"),
            ("COLOR:turquoise", "COLOR:RED", "#ff0000"),
            ("COLOR:turquoise", "COLOR:RED\r\nX-MAGNOLIE-ACCENT-COLOR:#112233", "#112233"),
            ("", "COLOR:not-a-css-colour", ""),
        };
        foreach (var (kind, date, format) in new[] { ("VEVENT", "DTSTART", "ics-termine"), ("VTODO", "DUE", "ics-aufgaben") })
        foreach (var (calendarColour, componentColour, expected) in cases)
        {
            var raw = string.Join("\r\n", new[] { "BEGIN:VCALENDAR", "VERSION:2.0", calendarColour, "BEGIN:" + kind,
                "UID:external-colour", "SUMMARY:External colour", date + ";VALUE=DATE:20261018", componentColour,
                "CATEGORIES:Provider", "X-OWNED:preserved", "END:" + kind, "END:VCALENDAR", "" });
            JsonObject Read(string data)
            {
                var parsed = ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(data), "ics", "external.ics");
                return (kind == "VEVENT" ? parsed.Termine : parsed.Aufgaben).OfType<JsonObject>().Single();
            }
            string Write(JsonObject value)
            {
                using var document = JsonDocument.Parse(new JsonArray(value.DeepClone()).ToJsonString());
                return ExchangeCodec.WriteIcs(format, document.RootElement).Text;
            }
            var item = Read(raw);
            TestAssert.That(item["akzentFarbe"]!.GetValue<string>() == expected &&
                item["kategorien"]!.GetValue<string>() == "Provider", $"Unexpected native colour for {kind}: {calendarColour}; {componentColour}");
            var saved = Write(item);
            TestAssert.That(Read(saved)["akzentFarbe"]!.GetValue<string>() == expected, "The external accent was lost on roundtrip.");
            if (calendarColour.Length > 0)
                TestAssert.That(saved[..saved.IndexOf("BEGIN:" + kind, StringComparison.Ordinal)].Contains(calendarColour, StringComparison.Ordinal),
                    "A uniform export lost its original calendar colour header.");
            if (componentColour == "COLOR:not-a-css-colour")
                TestAssert.That(saved.Contains(componentColour, StringComparison.Ordinal), "Unknown COLOR was silently omitted.");
            item["akzentFarbe"] = "#123456";
            TestAssert.That(Read(Write(item))["akzentFarbe"]!.GetValue<string>() == "#123456", "Original accent replaced the deliberate edit.");
            item["akzentFarbe"] = "";
            var cleared = Write(item);
            TestAssert.That(cleared.Contains("X-OWNED:preserved", StringComparison.Ordinal) &&
                Read(cleared)["akzentFarbe"]!.GetValue<string>() == "", "Clear restored an external accent or removed foreign metadata.");
        }
        static string Calendar(string uid, string colour) =>
            $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{uid}\r\nDTSTART;VALUE=DATE:20261018\r\n" +
            $"END:VEVENT\r\n{colour}\r\nEND:VCALENDAR\r\n";
        var mixed = ExchangeCodec.ParseIcs(Calendar("first", "COLOR:DarkGrey") + Calendar("second", ""));
        TestAssert.That(mixed.Termine[0]!["akzentFarbe"]!.GetValue<string>() == "#a9a9a9" &&
            mixed.Termine[1]!["akzentFarbe"]!.GetValue<string>() == "", "Calendar colours leaked across two VCALENDAR roots.");
        using var mixedDocument = JsonDocument.Parse(mixed.Termine.ToJsonString());
        var mixedText = ExchangeCodec.WriteIcs("ics-termine", mixedDocument.RootElement).Text;
        TestAssert.That(!mixedText.Contains("COLOR:DarkGrey", StringComparison.Ordinal) &&
            ExchangeCodec.ParseIcs(mixedText).Termine[1]!["akzentFarbe"]!.GetValue<string>() == "",
            "A mixed export promoted a source calendar default onto another calendar.");
        var legacy = mixed.Termine[1]!.DeepClone().AsObject();
        legacy.Remove("icsCalendarColor");
        legacy["icsRoundtrip"] = new JsonArray("COLOR:turquoise");
        using var legacyDocument = JsonDocument.Parse(new JsonArray(legacy).ToJsonString());
        TestAssert.That(ExchangeCodec.WriteIcs("ics-termine", legacyDocument.RootElement).Text.Contains("COLOR:turquoise", StringComparison.Ordinal),
            "An existing raw colour without an import decision was discarded.");
        return Task.CompletedTask;
    }

    internal static Task RunAsync()
    {
        const string raw = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:owned-task\r\nSUMMARY:Owned task\r\nDUE;VALUE=DATE:20261018\r\nCATEGORIES:Arzt,Provider\r\nX-MAGNOLIE-ACCENT-COLOR:#3366AA\r\nX-OWNED:preserved\r\nEND:VTODO\r\nEND:VCALENDAR\r\n";
        var imported = ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(raw), "ics", "owned.ics");
        var task = imported.Aufgaben.OfType<JsonObject>().Single();
        TestAssert.That(task["kategorien"]!.GetValue<string>() == "Arzt,Provider" && task["akzentFarbe"]!.GetValue<string>() == "#3366aa", "Native task categories/accent were lost on import.");
        task["kategorien"] = "Urlaub"; task["akzentFarbe"] = "#ff9900";
        using var document = JsonDocument.Parse(new JsonArray(task.DeepClone()).ToJsonString());
        var exported = ExchangeCodec.WriteIcs("ics-aufgaben", document.RootElement).Text;
        var restored = ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(exported), "ics", "owned.ics").Aufgaben.OfType<JsonObject>().Single();
        TestAssert.That(restored["kategorien"]!.GetValue<string>() == "Urlaub" && restored["akzentFarbe"]!.GetValue<string>() == "#ff9900" && exported.Contains("X-OWNED:preserved", StringComparison.Ordinal), "Changed categories/accent or foreign properties were lost on native task export.");
        TestAssert.That(exported.Split("X-MAGNOLIE-ACCENT-COLOR:", StringSplitOptions.None).Length == 2, "Native accent export duplicated the raw property.");
        task["kategorien"] = ""; task["akzentFarbe"] = "";
        using var clearedDocument = JsonDocument.Parse(new JsonArray(task.DeepClone()).ToJsonString());
        var cleared = ExchangeCodec.WriteIcs("ics-aufgaben", clearedDocument.RootElement).Text;
        TestAssert.That(!cleared.Contains("CATEGORIES:", StringComparison.Ordinal) && !cleared.Contains("X-MAGNOLIE-ACCENT-COLOR:", StringComparison.Ordinal) && cleared.Contains("X-OWNED:preserved", StringComparison.Ordinal), "Clearing native task categories/accent restored stale raw values.");
        var eventRaw = raw.Replace("VTODO", "VEVENT", StringComparison.Ordinal).Replace("DUE;", "DTSTART;", StringComparison.Ordinal);
        var appointment = ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(eventRaw), "ics", "owned.ics").Termine.OfType<JsonObject>().Single();
        TestAssert.That(appointment["akzentFarbe"]!.GetValue<string>() == "#3366aa", "Native appointment accent was lost.");
        appointment["akzentFarbe"] = "#ff0000";
        using var eventDocument = JsonDocument.Parse(new JsonArray(appointment.DeepClone()).ToJsonString());
        var eventExport = ExchangeCodec.WriteIcs("ics-termine", eventDocument.RootElement).Text;
        TestAssert.That(eventExport.Contains("X-MAGNOLIE-ACCENT-COLOR:#ff0000", StringComparison.Ordinal) && eventExport.Contains("X-OWNED:preserved", StringComparison.Ordinal), "Native event accent or foreign properties were lost.");
        foreach (var layout in new[] { "month", "year" })
        {
            using var payload = JsonDocument.Parse("""
                {"cmd":"planer_ods","layout":"month","titel":"Owned planner","spalten":["Owned"],"zeilen":[["18"]],"inhalte":[[{"datum":"18","eintraege":[{"text":"Owned task","art":"aufgabe","farbe":"#112233","akzent":true}]}]]}
                """.Replace("\"month\"", JsonSerializer.Serialize(layout), StringComparison.Ordinal));
            var sheet = DocumentExportService.ReadSheet(payload.RootElement, "Owned planner");
            using var archive = new ZipArchive(new MemoryStream(DocumentExportService.CreateSpreadsheet(new[] { sheet })), ZipArchiveMode.Read);
            using var reader = new StreamReader(archive.GetEntry("content.xml")!.Open());
            var content = reader.ReadToEnd();
            var xml = XDocument.Parse(content);
            XNamespace text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0";
            XNamespace style = "urn:oasis:names:tc:opendocument:xmlns:style:1.0";
            XNamespace fo = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0";
            var styles = xml.Descendants(style + "style").ToDictionary(node => (string)node.Attribute(style + "name")!, StringComparer.Ordinal);
            TestAssert.That(xml.Descendants(text + "span").Where(node => node.Value.Contains("Owned task", StringComparison.Ordinal)).Any(node =>
                styles.TryGetValue((string?)node.Attribute(text + "style-name") ?? "", out var referenced) &&
                referenced.Element(style + "text-properties") is { } properties &&
                (string?)properties.Attribute(fo + "background-color") == "#112233" &&
                (string?)properties.Attribute(fo + "color") == "#ffffff" &&
                (layout != "year" || (string?)properties.Attribute(fo + "font-size") == "3.6pt")),
                "Actual planner text lost its referenced accent/contrast or annual size in ODS " + layout);
        }
        return Task.CompletedTask;
    }
}
