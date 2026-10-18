using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.IO.Compression;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CategoryColorTests
{
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
            TestAssert.That(content.Contains("fo:background-color=\"#112233\"", StringComparison.Ordinal) && content.Contains("fo:color=\"#ffffff\"", StringComparison.Ordinal) && content.Contains("text:style-name=\"ax112233\"", StringComparison.Ordinal), "Native planner accent/contrast was lost in ODS " + layout);
        }
        return Task.CompletedTask;
    }
}
