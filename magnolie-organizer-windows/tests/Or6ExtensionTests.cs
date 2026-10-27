using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6ExtensionTests
{
    private static JsonNode Contract() => JsonNode.Parse(File.ReadAllText(Path.Combine(
        TestSource.Root("contracts/or6-native-extensions.json"), "contracts/or6-native-extensions.json")))!;
    private static byte[] Fixture(string name)
    {
        var item = Contract()["files"]![name]!;
        using var input = new MemoryStream(Convert.FromBase64String(item["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var bytes = output.ToArray();
        TestAssert.That(bytes.Length == item["bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == item["sha256"]!.GetValue<string>(), "Independent OR6 extension fixture changed.");
        return bytes;
    }
    internal static Task RunAsync()
    {
        var expected = Contract()["expected"]!;
        var raw = Fixture("weekly-monday-222.or6"); var result = Or6Codec.Read(raw);
        var series = result.Termine.OfType<JsonObject>().Where(item => item["titel"]!.GetValue<string>() == expected["weekly"]!["title"]!.GetValue<string>()).ToArray();
        TestAssert.That(series.Length == 1 && result.Termine.Count == 2 && result.Wiederholend == 0 && result.Uebersprungen == 0,
            "Native linked series was skipped or flattened.");
        var item = series.Single();
        TestAssert.That(item["wiederholung"]!["art"]!.GetValue<string>() == "weekly" &&
            item["wiederholung"]!["intervall"]!.GetValue<int>() == 2 && item["wiederholung"]!["bis"]!.GetValue<string>() == "2026-12-14" &&
            item["zeit"]!.GetValue<string>() == "09:15" && item["endZeit"]!.GetValue<string>() == "10:00", "Native weekly rule/times differ.");
        var contacts = Or6Codec.Read(Fixture("contact-context-222.or6")).Kontakte;
        var contact = contacts.OfType<JsonObject>().Single(entry => entry["vorname"]!.GetValue<string>() == "Grace");
        foreach (var field in new[] { "vorname", "nachname", "firma", "email" })
            TestAssert.That(JsonNode.DeepEquals(contact[field], expected["contact"]![field]), "Original contact field changed: " + field);
        foreach (var phone in contact["telefone"]!.AsArray().OfType<JsonObject>())
            TestAssert.That(JsonNode.DeepEquals(phone["typen"], expected["contact"]!["phoneTypes"]![phone["wert"]!.GetValue<string>()]), "Sparse native phone slot lost context.");
        TestAssert.That(contact["telefone"]!.AsArray().Count == 3 && contact["vcardRoundtrip"]![0]!.GetValue<string>() == "CATEGORIES:OR6-222 Alpha",
            "Original contact category/phones missing.");
        var grouped = Or6Codec.Read(Fixture("group-beta-222.or6"));
        TestAssert.That(grouped.Kontakte.Count == 2 && grouped.Uebersprungen == 0, "Distribution groups became ordinary contacts or were lost.");
        foreach (var member in grouped.Kontakte.OfType<JsonObject>())
        {
            var names = expected["groups"]![member["vorname"]!.GetValue<string>()]!.AsArray().Select(value => value!.GetValue<string>());
            TestAssert.That(member["vcardRoundtrip"]![0]!.GetValue<string>() == "CATEGORIES:" + string.Join(',', names), "Original group membership differs.");
        }
        var deleted = Or6Codec.Read(Fixture("weekly-deleted-222.or6"));
        var retained = deleted.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == expected["weekly"]!["title"]!.GetValue<string>());
        TestAssert.That(deleted.Wiederholend == 0 && deleted.Uebersprungen == 0 && retained["icsKomplex"]!.GetValue<bool>() &&
            retained["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == "EXDATE:20261116T091500"), "Deleted original occurrence was resurrected or series lost.");
        var sections = Or6Codec.Read(Fixture("sections-corrected-222.or6")); var selected = expected["sections"]!;
        var annual = sections.Jahrestage.OfType<JsonObject>().Single();
        TestAssert.That(annual["name"]!.GetValue<string>() == selected["anniversary"]!["title"]!.GetValue<string>() &&
            annual["datum"]!.GetValue<string>() == selected["anniversary"]!["date"]!.GetValue<string>() &&
            annual["typ"]!.GetValue<string>() == "anniversary", "Original annual checkbox/date not retained.");
        var planner = sections.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == selected["planner"]!["title"]!.GetValue<string>());
        TestAssert.That(planner["datum"]!.GetValue<string>() == "2026-11-06" && planner["endDatum"]!.GetValue<string>() == "2026-11-08" &&
            planner["zeit"]!.GetValue<string>() == "" && planner["endZeit"]!.GetValue<string>() == "", "Planner inclusive all-day span changed.");
        var call = sections.Notizen!.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == selected["call"]!["title"]!.GetValue<string>());
        foreach (var value in new[] { "Lotus Organizer: Calls", "Start: 2026-11-09 10:30", "End: 2026-11-09 10:45", "Grace Fixture", "+49305550222", "Synthetic historical record; do not dial", "Completed: true", "Status: Planned" })
            TestAssert.That(call["text"]!.GetValue<string>().Contains(value, StringComparison.Ordinal), "Original call field missing: " + value);
        var web = sections.Notizen!.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == selected["web"]!["title"]!.GetValue<string>());
        TestAssert.That(web["text"]!.GetValue<string>() == "Lotus Organizer: Web\nURL: https://example.test/or6-222\nPreserve source bookmark" &&
            sections.Kontakte.Count == 2 && sections.Termine.Count == 3 && sections.Notizen!.Count == 3 && sections.Uebersprungen == 0,
            "Source sections were lost or became callable contacts/appointments.");
        var once = Or6Codec.Read(Fixture("anniversary-once-222.or6"));
        var oneOff = once.Termine.OfType<JsonObject>().Single(value => value["titel"]!.GetValue<string>() == annual["name"]!.GetValue<string>());
        TestAssert.That(once.Jahrestage.Count == 0 && once.Uebersprungen == 0 && JsonNode.DeepEquals(oneOff["uid"], annual["uid"]) &&
            oneOff["datum"]!.GetValue<string>() == "2026-11-04" && oneOff["zeit"]!.GetValue<string>() == "" && oneOff["wiederholung"] is null,
            "Unchecked original annual checkbox became a yearly recurrence.");
        return Task.CompletedTask;
    }
}
