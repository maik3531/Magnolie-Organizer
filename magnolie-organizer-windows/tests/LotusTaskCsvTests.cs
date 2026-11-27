using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class LotusTaskCsvTests
{
    internal static Task RunAsync()
    {
        const string marker = "contracts/lotus-task-csv-vectors.json";
        using var vectors = JsonDocument.Parse(File.ReadAllText(Path.Combine(TestSource.Root(marker), marker)));
        foreach (var vector in vectors.RootElement.EnumerateArray())
        {
            var header = vector.GetProperty("header").GetString()!;
            var rows = vector.GetProperty("rows").EnumerateArray().ToArray();
            var csvRows = rows.Select(row => row.GetProperty("csv").GetString()!).ToArray();
            var imported = ExchangeCodec.ParseLotusCsv(string.Join("\r\n", [header, .. csvRows, ""]));
            TestAssert.That(imported.Uebersprungen == 0 && imported.Aufgaben.Count == rows.Length,
                $"{header}: task rows were lost.");
            CheckFields(imported.Aufgaben, "CSV");
            var exported = ExchangeCodec.WriteIcs("ics-aufgaben", JsonSerializer.SerializeToElement(imported.Aufgaben));
            TestAssert.That(exported.Count == rows.Length && exported.Skipped == 0, $"{header}: lost VTODOs.");
            CheckFields(ExchangeCodec.ParseIcs(exported.Text).Aufgaben, "VTODO");

            void CheckFields(JsonArray tasks, string phase)
            {
                TestAssert.That(tasks.Count == rows.Length, $"{header}: {phase} task count differs.");
                for (var index = 0; index < rows.Length; index++)
                {
                    var row = rows[index];
                    var title = csvRows[index].Split(';')[0];
                    var task = tasks[index]!;
                    TestAssert.That(task["titel"]!.GetValue<string>() == title &&
                        task["faellig"]!.GetValue<string>() == "2026-05-31" &&
                        task["erledigt"]!.GetValue<bool>() == row.GetProperty("done").GetBoolean() &&
                        task["prio"]!.GetValue<int>() == row.GetProperty("priority").GetInt32(),
                        $"{phase}: status, priority, or date changed for {title}: {task}.");
                }
            }
        }
        return Task.CompletedTask;
    }
}
