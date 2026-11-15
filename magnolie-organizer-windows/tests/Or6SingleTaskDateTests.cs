using System.Text.Json;
using System.Text.Json.Nodes;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6SingleTaskDateTests
{
    internal static void Run()
    {
        var raw = Or6CodecTests.Fixture(); var task = Or6Codec.Read(raw).Aufgaben.Single()!.AsObject();
        var expected = new Dictionary<string, string> { ["startDatum"] = "2026-10-24", ["startZeit"] = "08:00", ["faellig"] = "2026-10-24", ["faelligZeit"] = "18:00" };
        foreach (var pair in expected) TestAssert.That(ContactFields.Text(task, pair.Key) == pair.Value, "Ordinary native task dropped a structured date/clock");
        using var input = JsonDocument.Parse(new JsonArray(task.DeepClone()).ToJsonString());
        var exported = ExchangeCodec.WriteIcs("ics-aufgaben", input.RootElement); var reread = ExchangeCodec.ParseIcs(exported.Text).Aufgaben.Single()!.AsObject();
        TestAssert.That(exported.Count == 1 && exported.Skipped == 0, "Ordinary native task failed VTODO export");
        foreach (var pair in expected) TestAssert.That(ContactFields.Text(reread, pair.Key) == pair.Value, "VTODO roundtrip changed native task date/clock");
        TestAssert.That(JsonNode.DeepEquals(task["prio"], reread["prio"]) && JsonNode.DeepEquals(task["erledigt"], reread["erledigt"]), "Task date mapping changed priority/status");
        foreach (var missing in new[] { 7, 8 })
        {
            var data = Rotate(raw, true);
            var owner = Blocks(data).Single(at => U32(data, at) == 0x300 && FieldTextIfPresent(data, at, 9) == "TASK-OR6-212");
            var field = Field(data, owner, missing); TestAssert.That(field.Length == 8, "Independent task timestamp missing");
            new byte[] { 2, 0, 2, 2, 2, 2, 2, 2 }.CopyTo(data, field.Value);
            var absent = Or6Codec.Read(Rotate(data, false)).Aufgaben.Single()!.AsObject();
            foreach (var key in missing == 7 ? new[] { "startDatum", "startZeit" } : new[] { "faellig", "faelligZeit" })
                TestAssert.That(absent[key] is not null && ContactFields.Text(absent, key) == "", "Missing native timestamp acquired an invented default");
            TestAssert.That(JsonNode.DeepEquals(absent["prio"], task["prio"]) && JsonNode.DeepEquals(absent["erledigt"], task["erledigt"]), "Missing stamp changed unrelated task fields");
        }
    }
}
