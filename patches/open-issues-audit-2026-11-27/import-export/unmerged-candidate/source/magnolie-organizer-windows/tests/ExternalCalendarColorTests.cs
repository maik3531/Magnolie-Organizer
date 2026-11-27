using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ExternalCalendarColorTests
{
    private static string Wire(string kind, string[] properties, string calendar = "", string uid = "owned-color")
    {
        var component = kind == "aufgaben" ? "VTODO" : "VEVENT";
        var parts = new List<string> { "BEGIN:VCALENDAR", "VERSION:2.0" };
        if (calendar.Length > 0) parts.Add(calendar);
        parts.AddRange(["BEGIN:" + component, "UID:" + uid, "SUMMARY:Owned color", (kind == "aufgaben" ? "DUE" : "DTSTART") + ";VALUE=DATE:20261205"]);
        if (kind == "jahrestage") parts.AddRange(["RRULE:FREQ=YEARLY", "X-MAGNOLIE-TYPE-ID:birthday"]);
        parts.AddRange(properties); parts.AddRange(["END:" + component, "END:VCALENDAR", ""]);
        return string.Join("\r\n", parts);
    }
    private static ExchangeImportResult Read(string text) => ExchangeCodec.ParseImport(Encoding.UTF8.GetBytes(text), "ics", "owned.ics");
    private static JsonArray Items(ExchangeImportResult result, string kind) => kind switch
    { "aufgaben" => result.Aufgaben, "jahrestage" => result.Jahrestage, _ => result.Termine };
    private static string Export(string kind, JsonArray values) => ExchangeCodec.WriteIcs("ics-" + kind, JsonSerializer.SerializeToElement(values)).Text;
    private static string Text(JsonNode? item, string name) => item?[name]?.GetValue<string>() ?? "";

    internal static Task RunAsync()
    {
        const string marker = "contracts/calendar-external-colors.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(marker), marker)))!;
        var cases = 0;
        foreach (var node in vectors["cases"]!.AsArray())
        {
            var vector = node!; var expected = vector["expected"]!; var kind = Text(expected, "kind");
            var parsed = Read(Text(vector, "input")); var exported = Export(kind, Items(parsed, kind));
            foreach (var result in new[] { parsed, Read(exported) })
            {
                var values = Items(result, kind);
                TestAssert.That(values.Count == 1 && result.Termine.Count + result.Aufgaben.Count + result.Jahrestage.Count == 1, Text(vector, "id") + ": type changed");
                var item = values[0]!;
                foreach (var key in new[] { "typ", "datum" })
                    if (expected[key] is not null) TestAssert.That(Text(item, key) == Text(expected, key), key + ": semantic value changed");
                if (expected["accent"] is not null) TestAssert.That(Text(item, "akzentFarbe") == Text(expected, "accent"), Text(vector, "id") + ": color lost");
                if (expected["recurrence"] is not null) TestAssert.That(Text(item["wiederholung"], "art") == Text(expected, "recurrence"), "Recurrence changed");
                foreach (var raw in expected["opaque"]?.AsArray() ?? [])
                    TestAssert.That(item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == raw!.GetValue<string>()), "Opaque property lost");
            }
            cases++;
        }
        foreach (var named in vectors["css3_names"]!.AsObject())
        {
            var items = Read(Wire("termine", ["COLOR:" + named.Key.ToUpperInvariant()])).Termine;
            TestAssert.That(Text(items[0], "akzentFarbe") == named.Value!.GetValue<string>() &&
                Text(Read(Export("termine", items)).Termine[0], "akzentFarbe") == named.Value.GetValue<string>(), "CSS3 name differs: " + named.Key);
            cases++;
        }
        foreach (var kind in new[] { "termine", "aufgaben", "jahrestage" })
        {
            foreach (var color in new[] { "#123456", "" })
            {
                var items = Items(Read(Wire(kind, ["COLOR:turquoise"])), kind); items[0]!["akzentFarbe"] = color;
                var text = Export(kind, items);
                TestAssert.That(!text.Contains("COLOR:turquoise") && !text.Split('\n').Any(line => line.StartsWith("COLOR:#", StringComparison.Ordinal)) && Text(Items(Read(text), kind)[0], "akzentFarbe") == color, "Edit/clear revived stale color"); cases++;
            }
            var legacy = Items(Read(Wire(kind, ["COLOR:turquoise"])), kind);
            legacy[0]!.AsObject().Remove("icsAkzentFarbeBasis"); legacy[0]!["akzentFarbe"] = "";
            legacy = JsonNode.Parse(legacy.ToJsonString())!.AsArray();
            TestAssert.That(Export(kind, legacy).Contains("COLOR:turquoise"), "Legacy opaque color was deleted"); cases++;
            const string parameterized = "COLOR;X-SOURCE=owned:red";
            var overridden = Items(Read(Wire(kind, [parameterized, "X-MAGNOLIE-ACCENT-COLOR:#112233"])), kind);
            var unchanged = Export(kind, overridden);
            TestAssert.That(unchanged.Contains(parameterized) && Text(Items(Read(unchanged), kind)[0], "akzentFarbe") == "#112233", "Own override altered an unchanged parameterized color");
            overridden[0]!["akzentFarbe"] = "";
            var refused = false;
            try { Export(kind, overridden); } catch (InvalidOperationException error) when (error.GetType().Name == "ProtectedCalendarPropertyException") { refused = true; }
            TestAssert.That(refused, "Protected color parameters were silently discarded"); cases++;
            var folder = Path.Combine(Path.GetTempPath(), "magnolie-color-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                var store = new AtomicStore(); var file = Path.Combine(folder, "book.json");
                var payload = Read(Wire(kind, ["COLOR:turquoise"])).ToPayload("ics", "owned.ics");
                store.WriteRecoverableJson(file, payload.ToJsonString());
                var reopened = JsonNode.Parse(store.ReadRecoverableJson(file) ?? throw new IOException("Book readback missing"))!;
                TestAssert.That(Text(reopened[kind]![0], "icsAkzentFarbeBasis") == "#40e0d0", "Durable color baseline lost");
                reopened[kind]![0]!["akzentFarbe"] = "";
                TestAssert.That(!Export(kind, reopened[kind]!.AsArray()).Contains("COLOR:turquoise"), "Stored clear revived source color"); cases++;
            }
            finally { Directory.Delete(folder, true); }
        }
        var combined = Read(Wire("termine", [], "COLOR:red", "red") + Wire("termine", [], "X-APPLE-CALENDAR-COLOR:#0000FF", "blue") + Wire("termine", [], uid: "plain")).Termine;
        foreach (var values in new[] { combined, Read(Export("termine", combined)).Termine })
            TestAssert.That(values.Count == 3 && Text(values[0], "akzentFarbe") == "#ff0000" && Text(values[1], "akzentFarbe") == "#0000ff" && Text(values[2], "akzentFarbe") == "", "Calendar source colors leaked");
        cases++;
        Console.WriteLine($"External calendar colors: {cases} actual-codec cases passed (147 exact CSS3 names included)");
        return Task.CompletedTask;
    }
}
