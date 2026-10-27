using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalBatchBoundaryTests
{
    internal static Task RunAsync()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "resources", "personal-sync-batch-boundaries.json");
        var cases = JsonNode.Parse(File.ReadAllText(path))!["cases"]!.AsArray();
        TestAssert.That(cases.Count == 16, "Shared byte-boundary vectors missing.");
        foreach (var item in cases.OfType<JsonObject>())
        {
            var name = item["name"]!.GetValue<string>();
            using var input = new MemoryStream(Convert.FromBase64String(item["gzip_base64"]!.GetValue<string>()));
            using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
            var raw = output.ToArray(); var body = JsonNode.Parse(raw)!.AsObject();
            TestAssert.That(raw.Length == item["body_bytes"]!.GetValue<int>() &&
                Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() == item["sha256"]!.GetValue<string>() &&
                raw.SequenceEqual(TelefonCrypto.Canonical(body)), "Independent canonical fixture changed: " + name);
            foreach (var record in body["records"]!.AsArray())
            {
                var single = body.DeepClone().AsObject(); single["records"] = new JsonArray(record!.DeepClone());
                if (single["records_hash"] is not null) single["records_hash"] = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(single["records"]!))).ToLowerInvariant();
                PersonalSyncContract.ValidateBody("personal_sync.batch", single);
            }
            if (item["valid"]!.GetValue<bool>())
            {
                PersonalSyncContract.ValidateBody("personal_sync.batch", body);
                var envelope = PersonalSyncActorContract.Wrap(body["run_id"]!.GetValue<string>(), "personal_sync.batch", body);
                var inner = PersonalSyncActorContract.Unwrap(envelope);
                TestAssert.That(inner.Kind == "personal_sync.batch" && JsonNode.DeepEquals(inner.Body, body) &&
                    TelefonCrypto.Canonical(envelope).Length < 256 * 1024, "Valid boundary failed actor roundtrip: " + name);
            }
            else
            {
                TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.batch", body), "Oversized batch accepted: " + name);
                TestAssert.Throws<InvalidDataException>(() => PersonalSyncActorContract.Wrap(body["run_id"]!.GetValue<string>(), "personal_sync.batch", body), "Actor accepted oversized inner batch: " + name);
            }
        }
        return Task.CompletedTask;
    }
}
