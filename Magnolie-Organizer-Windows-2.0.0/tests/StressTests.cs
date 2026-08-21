using System.Diagnostics;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class StressTests
{
    internal static Task RunAsync()
    {
        var configured = Environment.GetEnvironmentVariable("MAGNOLIE_STRESS_COUNT");
        var count = configured is null ? 500 : int.Parse(configured, System.Globalization.CultureInfo.InvariantCulture);
        if (count is < 1 or > 30_000) throw new InvalidOperationException("MAGNOLIE_STRESS_COUNT muss zwischen 1 und 30000 liegen.");

        var csv = new StringBuilder("ANFANGSDATUMZEIT,ENDDATUMZEIT,BESCHREIBUNG,NOTIZ\r\n", count * 100);
        for (var index = 0; index < count; index++)
            csv.Append($"08/{1 + index % 28:00}/2026 9:30 AM,08/{1 + index % 28:00}/2026 10:00 AM,Termin {index} Grüße,Zeile {index}\r\n");
        var watch = Stopwatch.StartNew();
        var imported = ExchangeCodec.ParseLotusCsv(csv.ToString());
        var importSeconds = watch.Elapsed.TotalSeconds;
        TestAssert.That(imported.Termine.Count == count && imported.Uebersprungen == 0,
            $"Lotus-Lastimport verlor Datensätze: {imported.Termine.Count}/{count}.");
        TestAssert.That(importSeconds <= (count == 30_000 ? 20 : 5),
            $"Lotus-Lastimport überschritt die Grenze: {importSeconds:F2} s.");

        var data = new JsonObject { ["version"] = 6, ["termine"] = imported.Termine, ["kontakte"] = new JsonArray(),
            ["notizen"] = new JsonArray(), ["papierkorb"] = new JsonArray(), ["einstellungen"] = new JsonObject() };
        var storeRoot = Path.Combine(Path.GetTempPath(), $"magnolie-stress-store-{Guid.NewGuid():N}");
        Directory.CreateDirectory(storeRoot);
        try
        {
            var path = Path.Combine(storeRoot, "daten.json");
            var text = data.ToJsonString();
            var store = new AtomicStore();
            store.WriteRecoverableJson(path, text);
            File.WriteAllText(path, "{abgebrochen");
            var recovered = JsonNode.Parse(store.ReadRecoverableJson(path)!)!;
            TestAssert.That(recovered["termine"]!.AsArray().Count == count,
                $"AtomicStore-Recovery verlor Datensätze: {recovered["termine"]!.AsArray().Count}/{count}.");
        }
        finally { try { Directory.Delete(storeRoot, true); } catch (Exception) { } }
        watch.Restart();
        var archive = GesamtarchivService.Create(data, "windows", "2.0.0");
        var restored = GesamtarchivService.Read(archive).Daten;
        var archiveSeconds = watch.Elapsed.TotalSeconds;
        TestAssert.That(restored["termine"]!.AsArray().Count == count, "Gesamtarchiv-Lastlauf verlor Kerndaten.");
        TestAssert.That(archiveSeconds <= (count == 30_000 ? 20 : 5),
            $"Gesamtarchiv-Lastlauf überschritt die Grenze: {archiveSeconds:F2} s.");
        Console.WriteLine($"         Lastmenge {count}: Import {importSeconds:F2} s, Archiv {archiveSeconds:F2} s");
        return Task.CompletedTask;
    }
}
