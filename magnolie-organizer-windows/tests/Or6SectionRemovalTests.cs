using System.Buffers.Binary;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6SectionRemovalTests
{
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-section-removal.json"), "contracts/or6-native-section-removal.json")))!;
        var beforeRaw = Or6TaskScopeTests.Fixture(contract["files"]!["section-before-remove-570.or6"]!);
        var before = Or6Codec.Read(beforeRaw);
        TestAssert.That(before.Notizen?.Count == 2 && CountLiveNotes(beforeRaw) == 2, "Independent synthetic before-removal pages changed");
        foreach (var name in new[] { "section-removed-verified-v2-570.or6", "section-removed-reopened-v2-570.or6" })
        {
            var raw = Or6TaskScopeTests.Fixture(contract["files"]![name]!); var retained = raw.ToArray(); var after = Or6Codec.Read(raw);
            TestAssert.That(CountLiveNotes(raw) == 0 && after.Notizen?.Count == 0, "Confirmed removed source section was reconstructed");
            TestAssert.That(JsonNode.DeepEquals(before.Termine, after.Termine) && JsonNode.DeepEquals(before.Aufgaben, after.Aufgaben) &&
                JsonNode.DeepEquals(before.Kontakte, after.Kontakte) && JsonNode.DeepEquals(before.Jahrestage, after.Jahrestage) &&
                JsonNode.DeepEquals(before.Geburtstage, after.Geburtstage) && before.Uebersprungen == after.Uebersprungen && before.Wiederholend == after.Wiederholend,
                "Native source notebook removal changed an unrelated imported collection");
            TestAssert.That(raw.AsSpan().SequenceEqual(retained), "Read-only importer changed source bytes");
        }
    }
    private static int CountLiveNotes(byte[] raw)
    {
        var decoded = Or6PlannerTests.Rotate(raw, true);
        return Or6PlannerTests.Blocks(decoded).Count(at => BinaryPrimitives.ReadUInt32LittleEndian(decoded.AsSpan(at)) == 0x510);
    }
}
