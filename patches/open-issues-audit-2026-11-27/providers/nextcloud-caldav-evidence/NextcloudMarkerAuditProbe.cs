using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security.Cryptography;
using MagnolieOrganizer.Windows;
namespace MagnolieOrganizer.Windows.Tests;
internal static class NextcloudMarkerAuditProbe
{
    internal static int Run(string fixtures, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures, "cases.json")))!.AsArray();
        var results = new JsonArray();
        foreach (var node in cases)
        {
            var c = node!.AsObject(); var filename = c["filename"]!.GetValue<string>();
            var bytes = File.ReadAllBytes(Path.Combine(fixtures, filename));
            var text = System.Text.Encoding.UTF8.GetString(bytes);
            var parsed = ExchangeCodec.ParseIcs(text);
            TestAssert.That(parsed.Termine.Count + parsed.Jahrestage.Count == 1, "Reader did not return exactly one record");
            var bucket = parsed.Jahrestage.Count > 0 ? "jahrestage" : "termine";
            var item = (bucket == "jahrestage" ? parsed.Jahrestage : parsed.Termine)[0]!.AsObject();
            var expectedDate = c["expected_date"]?.GetValue<string>(); var expectedType = c["expected_type"]?.GetValue<string>();
            var raw = item["icsRoundtrip"]!.AsArray().Select(x => x!.GetValue<string>()).ToHashSet();
            var markers = text.Split('\n').Select(x => x.TrimEnd('\r')).Where(x => x.StartsWith("X-NEXTCLOUD-BC-", StringComparison.Ordinal));
            var result = (JsonObject)c.DeepClone();
            result["actual_bucket"] = bucket; result["actual_date"] = item["datum"]?.DeepClone(); result["actual_type"] = item["typ"]?.DeepClone();
            result["ics_complex"] = item["icsKomplex"]?.DeepClone(); result["markers_preserved"] = markers.All(raw.Contains);
            result["fixture_sha256"] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            result["matches_expected"] = bucket == c["expected_bucket"]!.GetValue<string>() && (expectedDate is null || item["datum"]?.GetValue<string>() == expectedDate) && (expectedType is null || item["typ"]?.GetValue<string>() == expectedType);
            results.Add(result);
        }
        var report = new JsonObject { ["product_method"] = "ExchangeCodec.ParseIcs", ["results"] = results,
            ["boundary"] = "Actual unchanged C# production codec in existing CoreTests harness; no native GUI, live server or contact-derived birthday path." };
        File.WriteAllText(output, report.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
        Console.WriteLine(report.ToJsonString()); return 0;
    }
}
