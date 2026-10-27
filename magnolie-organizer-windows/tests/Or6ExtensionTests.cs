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
        return Task.CompletedTask;
    }
}
