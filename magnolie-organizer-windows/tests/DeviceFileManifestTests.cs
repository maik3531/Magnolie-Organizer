using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileManifestTests
{
    internal static Task RunAsync()
    {
        const string relative = "contracts/file-transfer-manifest-v1-vectors.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!["vectors"]!.AsArray();
        foreach (var vector in vectors)
        {
            var original = vector!["manifest"]!.AsObject();
            DeviceFileManifest Parse(JsonNode value)
            {
                using var document = JsonDocument.Parse(value.ToJsonString());
                return DeviceFileManifest.Parse(document.RootElement);
            }
            var manifest = Parse(original);
            TestAssert.That(manifest.Fingerprint == vector["manifest_sha256"]!.GetValue<string>() &&
                manifest.Files.Single().Path == "Photos/Blüte.jpg" && manifest.TotalBytes == 5,
                "Windows/Python manifest framing or Unicode path bytes differ from the shared vector.");
            var mutatedInput = original.DeepClone().AsObject();
            mutatedInput["files"]![0]!["path"] = "changed.jpg";
            TestAssert.That(Parse(mutatedInput).Fingerprint != manifest.Fingerprint && manifest.Files[0].Path == "Photos/Blüte.jpg",
                "Manifest identity omitted the accepted path or adopted mutable JSON input.");
            var copiedFiles = manifest.Files.ToArray();
            var native = new DeviceFileManifest(manifest.TransferId, manifest.SourceId, manifest.SenderId, manifest.ReceiverId,
                copiedFiles, manifest.TotalBytes);
            copiedFiles[0] = copiedFiles[0] with { Path = "later.jpg" };
            TestAssert.That(native.Fingerprint == manifest.Fingerprint && native.Files[0].Path == "Photos/Blüte.jpg",
                "Native manifest adopted a mutable caller member list.");
            TestAssert.Throws<NotSupportedException>(() => ((IList<DeviceManifestFile>)native.Files)[0] = copiedFiles[0],
                "A reviewed native member list could be widened/replaced in place.");
            void Reject(Action<JsonObject> change)
            { var value = original.DeepClone().AsObject(); change(value); TestAssert.Throws<InvalidDataException>(() => Parse(value), "Malformed general file manifest was accepted."); }
            foreach (var invalid in new[] { "../a", "/absolute", "a//b", "a/./b", "a/../b", "C:relative", "a\\b", "a/NUL.txt",
                "a/COM¹.jpg", "CON .jpg", "a/b.", "a/b ", "a/\u202e.jpg", "e\u0301.jpg", new string('x', 256),
                string.Join('/', Enumerable.Repeat("a", 17)) })
                Reject(value => value["files"]![0]!["path"] = invalid);
            foreach (var field in new[] { "format", "chunk_bytes", "total_bytes" })
            {
                Reject(value => value[field] = true);
                Reject(value => value[field] = "1");
                Reject(value => value[field] = JsonNode.Parse("1.0"));
            }
            Reject(value => value["format"] = 2);
            Reject(value => value["files"]![0]!["size"] = true);
            Reject(value => value["files"]![0]!["sha256"] = new string('A', 64));
            Reject(value => value["files"]![0]!["grant"] = true);
            Reject(value => value["total_bytes"] = 6);
            Reject(value => value["receiver_id"] = value["sender_id"]!.DeepClone());
            Reject(value => value["files"] = new JsonArray());
            Reject(value => value["extra"] = true);
            foreach (var path in new[] { "photos/BLÜTE.jpg", "Photos/Blüte.jpg/child" })
                Reject(value =>
                {
                    var second = value["files"]![0]!.DeepClone(); second["id"] = new string('d', 32); second["path"] = path;
                    value["files"]!.AsArray().Add(second); value["total_bytes"] = 10;
                });
            Reject(value =>
            {
                var first = value["files"]![0]!; first["path"] = "photo/straße.jpg";
                var second = first.DeepClone(); second["id"] = new string('d', 32); second["path"] = "PHOTO/STRASSE.jpg";
                value["files"]!.AsArray().Add(second); value["total_bytes"] = 10;
            });
            Reject(value =>
            {
                var first = value["files"]![0]!; first["path"] = "photo/straße.jpg";
                var second = first.DeepClone(); second["id"] = new string('d', 32); second["path"] = "PHOTO/STRAẞE.jpg";
                value["files"]!.AsArray().Add(second); value["total_bytes"] = 10;
            });
            var json = original.ToJsonString().Replace("\"format\":1", "\"format\":1,\"format\":1", StringComparison.Ordinal);
            using var duplicate = JsonDocument.Parse(json);
            TestAssert.Throws<InvalidDataException>(() => DeviceFileManifest.Parse(duplicate.RootElement),
                "Duplicate manifest keys bypassed exact field validation.");
        }
        return Task.CompletedTask;
    }
}
