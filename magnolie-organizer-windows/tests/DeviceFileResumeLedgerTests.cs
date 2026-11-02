using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileResumeLedgerTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-resume-ledger-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        const string sender = "sender_fixture_01", receiver = "receiver_fixture_01";
        var source = new DeviceTransferBinding(sender, receiver, new string('d', 64), new string('e', 64), new string('f', 64), new string('0', 64));
        DeviceTransferBinding? live = source;
        var path = Path.Combine(root, "owned.part");
        var writes = 0;
        var fileId = new string('c', 32);
        DeviceFileManifest Manifest(byte[] data) => new(new string('a', 32), new string('b', 32), sender, receiver,
            [new(fileId, "Photos/Blüte.jpg", data.Length, Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant())], data.Length);
        void Write(string id, long offset, byte[] data)
        {
            TestAssert.That(id == fileId, "Unknown wire path was accepted as an owned staging file.");
            using var output = new FileStream(path, File.Exists(path) ? FileMode.Open : FileMode.CreateNew, FileAccess.Write, FileShare.None);
            output.Position = offset; output.Write(data); output.Flush(flushToDisk: true); writes++;
        }
        byte[] Read(string id, long offset, int size)
        {
            TestAssert.That(id == fileId, "Unknown staging member was read.");
            using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            input.Position = offset;
            var bytes = new byte[Math.Min(size, Math.Max(0L, input.Length - offset))];
            input.ReadExactly(bytes); return bytes;
        }
        DeviceFileResumeLedger Restore(DeviceFileManifest manifest, DeviceTransferBinding binding, JsonObject checkpoint)
        {
            using var parsed = JsonDocument.Parse(checkpoint.ToJsonString());
            return DeviceFileResumeLedger.Restore(manifest, binding, () => live, parsed.RootElement, Read);
        }
        try
        {
            var data = Enumerable.Repeat((byte)'a', DeviceFileManifest.ChunkBytes).Concat(new byte[] { 1, 2, 3, 4 }).ToArray();
            var manifest = Manifest(data);
            var ledger = new DeviceFileResumeLedger(manifest, source, () => live);
            ledger.Record(fileId, 1, [1, 2, 3, 4], Write, Read);
            TestAssert.That(ledger.VerifiedBytes == 4 && ledger.Missing(fileId).SequenceEqual([0]), "Tail-only readback invented whole-file progress.");
            var checkpoint = ledger.Checkpoint();
            var resumed = Restore(manifest, source, checkpoint);
            resumed.Record(fileId, 1, [1, 2, 3, 4], Write, Read);
            TestAssert.That(writes == 1, "An identical verified resumed chunk was written again.");
            resumed.Record(fileId, 0, data[..DeviceFileManifest.ChunkBytes], Write, Read);
            TestAssert.That(resumed.VerifiedBytes == data.Length && resumed.Missing(fileId).Length == 0 &&
                resumed.VerifiedFile(fileId, Read) == manifest.Files[0] && writes == 2, "Actual resumed readbacks/digest were not bound to the manifest.");
            checkpoint["chunks"]!.AsArray().Clear();
            TestAssert.That(resumed.VerifiedBytes == data.Length, "A mutable checkpoint modified the native proof ledger.");
            foreach (var changed in new[] { source with { SenderIdentitySha256 = new string('1', 64) },
                source with { ReceiverIdentitySha256 = new string('1', 64) }, source with { PermissionEpoch = new string('1', 64) },
                source with { DestinationToken = new string('1', 64) } })
            {
                var saved = resumed.Checkpoint(); live = changed;
                TestAssert.Throws<InvalidDataException>(() => Restore(manifest, changed, saved), "Persisted acceptance migrated to another native source/destination.");
                TestAssert.Throws<InvalidOperationException>(() => Restore(manifest, source, saved), "Revoked native source retained a resumed grant.");
                live = source;
            }
            var valid = resumed.Checkpoint();
            var damaged = File.ReadAllBytes(path); damaged[0] ^= 1; File.WriteAllBytes(path, damaged);
            TestAssert.Throws<InvalidDataException>(() => Restore(manifest, source, valid), "Changed persisted chunk claims manufactured a resume proof.");
            TestAssert.Throws<InvalidDataException>(() => resumed.VerifiedFile(fileId, Read), "A once-verified chunk bypassed final actual-byte hashing.");

            File.Delete(path); writes = 0;
            var hello = "hello"u8.ToArray(); var small = Manifest(hello);
            var readback = new DeviceFileResumeLedger(small, source, () => live);
            TestAssert.Throws<InvalidDataException>(() => readback.Record(fileId, 0, hello, Write, (_, _, _) => "other"u8.ToArray()),
                "Failed destination readback acquired a chunk proof.");
            TestAssert.That(readback.VerifiedBytes == 0, "Readback failure invented actual progress.");
            TestAssert.Throws<InvalidOperationException>(() => readback.Record(fileId, 0, hello,
                (id, offset, bytes) => { Write(id, offset, bytes); live = source with { PermissionEpoch = new string('1', 64) }; }, Read),
                "Revocation during staging IO acquired a successful chunk proof.");
            live = source; TestAssert.That(readback.VerifiedBytes == 0, "Rejected write retained a proof after native permission returned.");
            readback.Record(fileId, 0, hello, Write, Read);
            var exact = readback.Checkpoint();
            const string relative = "contracts/file-transfer-manifest-v1-vectors.json";
            var shared = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!["vectors"]![0]!["resume_checkpoint"]!.AsObject();
            TestAssert.That(JsonNode.DeepEquals(exact, shared) && Restore(small, source, shared).VerifiedFile(fileId, Read) == small.Files[0],
                "Windows resume metadata or actual readback differs from the shared Python/Kotlin checkpoint vector.");
            foreach (var alter in new Action<JsonObject>[] {
                value => value["format"] = true, value => value["extra"] = true,
                value => value["chunks"]![0]!["index"] = true,
                value => value["chunks"]![0]!["index"] = JsonNode.Parse("0.0"),
                value => value["chunks"]![0]!["sha256"] = new string('0', 64),
                value => value["chunks"]!.AsArray().Add(value["chunks"]![0]!.DeepClone()) })
            {
                var changed = exact.DeepClone().AsObject(); alter(changed);
                TestAssert.Throws<InvalidDataException>(() => Restore(small, source, changed), "Malformed persisted chunk metadata bypassed bounds/type/integrity checks.");
            }
            File.WriteAllBytes(path, hello.Concat(new byte[] { 1 }).ToArray());
            TestAssert.Throws<InvalidDataException>(() => readback.VerifiedFile(fileId, Read), "Extra EOF bytes were exposed as the accepted complete file.");
            File.Delete(path);
            var wrong = new DeviceFileResumeLedger(small, source, () => source);
            wrong.Record(fileId, 0, "other"u8.ToArray(), Write, Read);
            TestAssert.Throws<InvalidDataException>(() => wrong.VerifiedFile(fileId, Read), "Chunk readback witness replaced the manifest's actual full-file SHA.");
            File.Delete(path);
            var empty = new DeviceFileResumeLedger(Manifest([]), source, () => source);
            TestAssert.Throws<FileNotFoundException>(() => empty.VerifiedFile(fileId, Read), "Missing file was silently treated as a valid empty staging file.");
            File.WriteAllBytes(path, []);
            TestAssert.That(empty.VerifiedFile(fileId, Read).Size == 0, "A real zero-byte owned staging file could not be verified.");
        }
        finally { Directory.Delete(root, recursive: true); }
        return Task.CompletedTask;
    }
}
