using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarColourRemainderTests
{
    internal static Task RunAsync()
    {
        const string marker = "contracts/calendar-color-remainders.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(marker), marker)))!.AsArray();
        var directory = Path.Combine(Path.GetTempPath(), "magnolie-colour-remainder-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var store = new AtomicStore();
            foreach (var vector in vectors.OfType<JsonObject>())
            {
                var id = vector["id"]!.GetValue<string>();
                var section = vector["section"]!.GetValue<string>();
                var expected = vector["expected_accent"]!.GetValue<string>();
                var preserve = vector["preserve_line"]!.GetValue<string>();
                var imported = Read(vector["input"]!.GetValue<string>());
                var path = Path.Combine(directory, id + ".json");
                store.WriteRecoverableJson(path, imported.ToJsonString());
                var reopened = JsonNode.Parse(store.ReadRecoverableJson(path)!)!.AsObject();
                var item = reopened[section]![0]!.AsObject();
                TestAssert.That(Colour(item) == expected, id + ": native book reopen lost its imported accent.");
                if (section == "jahrestage")
                    TestAssert.That(item["datum"]!.GetValue<string>() == vector["expected_date"]!.GetValue<string>() &&
                        item["typ"]!.GetValue<string>() == vector["expected_type"]!.GetValue<string>() &&
                        reopened["termine"]!.AsArray().Count == 0, id + ": annual type or date changed.");
                var text = Write(section, new JsonArray(item.DeepClone()));
                TestAssert.That(text.Contains("X-OWNED:keep", StringComparison.Ordinal) &&
                    (preserve.Length == 0 || text.Split("\r\n").Contains(preserve)), id + ": unchanged foreign property was lost.");
                var again = Read(text);
                TestAssert.That(Colour(again[section]![0]!) == expected, id + ": export/reimport lost its accent.");
                if (section == "jahrestage")
                    TestAssert.That(again[section]![0]!["datum"]!.GetValue<string>() == vector["expected_date"]!.GetValue<string>() &&
                        again[section]![0]!["typ"]!.GetValue<string>() == vector["expected_type"]!.GetValue<string>() &&
                        again["termine"]!.AsArray().Count == 0, id + ": export/reimport changed its annual identity.");
                foreach (var accent in new[] { "#123456", "" })
                {
                    item["akzentFarbe"] = accent;
                    var changed = Write(section, new JsonArray(item.DeepClone()));
                    TestAssert.That(Colour(Read(changed)[section]![0]!) == accent && changed.Contains("X-OWNED:keep", StringComparison.Ordinal),
                        id + ": explicit edit/clear restored an old colour or removed unrelated data.");
                    if (preserve.StartsWith("COLOR;X-SOURCE", StringComparison.Ordinal))
                        TestAssert.That(!changed.Split("\r\n").Contains(preserve), id + ": an edited colour retained the old effective property.");
                    if (preserve == "COLOR:future-colour")
                        TestAssert.That(changed.Split("\r\n").Contains(preserve), id + ": unknown colour was reinterpreted.");
                }
            }
            var coloured = vectors.OfType<JsonObject>().Single(value => value["id"]!.GetValue<string>() == "birthday-calendar")["input"]!.GetValue<string>();
            var other = coloured.Replace("COLOR:turquoise\r\n", "", StringComparison.Ordinal).Replace("birthday-calendar", "uncoloured", StringComparison.Ordinal);
            var mixed = Write("jahrestage", Read(coloured + other)["jahrestage"]!.AsArray());
            var result = Read(mixed)["jahrestage"]!.AsArray();
            TestAssert.That(!mixed[..mixed.IndexOf("BEGIN:VEVENT", StringComparison.Ordinal)].Contains("COLOR:turquoise", StringComparison.Ordinal) &&
                Colour(result[0]!) == "#40e0d0" && Colour(result[1]!) == "", "Mixed anniversary calendars leaked a colour into another source.");
            Console.WriteLine($"Calendar colour remainders: {vectors.Count} native store/reopen/export vectors, {vectors.Count} edit/clear vectors, one mixed-calendar case.");
            return Task.CompletedTask;
        }
        finally { Directory.Delete(directory, true); }
    }

    private static string Colour(JsonNode value) => value["akzentFarbe"]?.GetValue<string>() ?? "";
    private static JsonObject Read(string text) => ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(text), "ics", "colour-remainders.ics").ToPayload("ics", "colour-remainders.ics");
    private static string Write(string section, JsonArray data)
    {
        using var document = JsonDocument.Parse(data.ToJsonString());
        return ExchangeCodec.WriteIcs("ics-" + section, document.RootElement).Text;
    }
}
