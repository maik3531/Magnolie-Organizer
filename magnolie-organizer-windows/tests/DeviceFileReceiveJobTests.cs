using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileReceiveJobTests
{
    internal sealed class Fixture : IDisposable
    {
        internal readonly DeviceFileConnectionMetadataTests.Fixture Native = new();
        internal NativeLocalFileGrant Local = new(new(7, new string('b', 64), false, true), new object(), true);
        internal NativeLocalFileGrant RemoteLocal = new(new(3, new string('a', 64), true, false), new object(), true);
        internal NativeFileControlPeer RemotePeer = null!;
        internal NativeFileControlSession Owner = null!, Phone = null!;
        internal NativeMediaDestination Destination = null!;
        internal string Root => Destination.NativePath;
        internal static async Task<Fixture> CreateAsync(bool sourceSend = true)
        {
            var f = new Fixture();
            try
            {
                await f.Native.SeedAsync();
                var identity = f.Native.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
                if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
                // This fixture explicitly materializes its injected test key as
                // the real current-user DPAPI record. Product code only reads it.
                File.WriteAllText(f.Native.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
                    Enumerable.Repeat((byte)29, 32).ToArray(), System.Text.Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
                var path = Path.Combine(f.Native.Paths.Root, "native-photo-target"); Directory.CreateDirectory(path);
                using (var directory = DeviceFileNativeDirectory.OpenExistingForReceive(path))
                    f.Destination = f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "images", null, directory);
                f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, null, true, false, false);
                var local = f.Native.Store.ReadFileIdentity(); f.Owner = f.Native.Connection.OpenNativeFileControls(() => f.Local);
                var remoteIdentity = new NativeFileControlIdentity(f.Native.Peer.Id, Convert.ToHexString(SHA256.HashData(f.Native.Peer.PublicKey)).ToLowerInvariant());
                var peer = new NativeFileControlPeer(local.DeviceId, local.IdentitySha256, new object(), true, true, true, true, true, f.Native.Peer.FilePairingEpoch);
                f.RemotePeer = peer;
                f.RemoteLocal = new(new(3, new string('a', 64), sourceSend, false), f.RemoteLocal.Owner, true);
                f.Phone = new NativeFileControlSession(remoteIdentity, () => peer, () => f.RemoteLocal);
                f.Native.Stream.SetLength(0); f.Native.Stream.Position = 0;
                TestAssert.That(await f.Native.Connection.SendNativeFileControlsAsync(), "No actual secure control output.");
                var first = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Single();
                f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(first, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), peer);
                var response = f.Phone.Packet(); f.Phone.MarkSent(response);
                f.Native.Stream.SetLength(0); f.Native.Stream.Position = 0;
                await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(response, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
                var echo = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Single();
                f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(echo, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), peer);
                TestAssert.That((f.Current() is not null) == sourceSend && f.Current() == f.Phone.Binding(f.Destination.DestinationToken, senderIsLocal: true), "Actual bilateral secure file agreement did not join native destination token.");
                return f;
            }
            catch { f.Dispose(); throw; }
        }
        internal DeviceTransferBinding? Current() => Owner.Binding(Destination.DestinationToken);
        internal DeviceFileManifest Manifest(params (string Name, byte[] Bytes)[] files) => new(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"),
            Native.Peer.Id, Native.Store.ReadFileIdentity().DeviceId,
            files.Select((file, index) => new DeviceManifestFile((index + 1).ToString("x32"), file.Name, file.Bytes.Length, Sha(file.Bytes))).ToArray(), files.Sum(file => (long)file.Bytes.Length));
        internal TelefonStore.NativeMediaReceiveJob Begin(DeviceFileManifest manifest) => Native.Store.BeginNativeMediaReceiveJob(Native.Peer.Id, "images", manifest, Current);
        public void Dispose() { Phone?.Dispose(); Native.Dispose(); }
    }
    private static string Sha(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static byte[] SharedRead(string path)
    {
        using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var bytes = new MemoryStream(); source.CopyTo(bytes); return bytes.ToArray();
    }

    internal static async Task WindowsActualReceiveAsync()
    {
        using var f = await Fixture.CreateAsync();
        var bytes = Enumerable.Range(0, 70000).Select(index => (byte)(index % 251)).ToArray();
        var manifest = f.Manifest(("native-photo.jpg", bytes));
        using var job = f.Begin(manifest);
        var initial = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        TestAssert.That(initial.JobId == job.JobId && initial.Phase == "receiving" && !File.Exists(Path.Combine(f.Root, "native-photo.jpg")), "History/staging was not committed before receiving.");
        job.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]);
        job.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]); // Idempotent exact duplicate.
        TestAssert.Throws<InvalidDataException>(() => job.ReceiveChunk(manifest.Files[0].Id, 0, new byte[DeviceFileManifest.ChunkBytes]), "Changed duplicate chunk was accepted.");
        TestAssert.Throws<InvalidDataException>(() => job.PublishAll(), "Incomplete file was published.");
        job.ReceiveChunk(manifest.Files[0].Id, 1, bytes[DeviceFileManifest.ChunkBytes..]); job.PublishAll();
        TestAssert.That(SharedRead(Path.Combine(f.Root, "native-photo.jpg")).SequenceEqual(bytes), "Actual native received bytes differ.");
        var complete = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        TestAssert.That(complete.Phase == "published" && complete.Version != initial.Version, "Actual publication did not advance protected original history.");
        TestAssert.Throws<InvalidDataException>(() => job.PublishAll(), "Completed receive job replayed publication.");
        TestAssert.Throws<InvalidDataException>(() => job.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]), "Published job still received data.");
        var rowsBefore = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count;
        TestAssert.Throws<InvalidDataException>(() => f.Begin(manifest), "An ordinary new job substituted for the original published job.");
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == rowsBefore, "Duplicate publication fabricated another history row.");
    }

    internal static async Task WindowsInterruptedAndWithdrawnAsync()
    {
        using var f = await Fixture.CreateAsync(); var bytes = "hello"u8.ToArray(); var manifest = f.Manifest(("pending.jpg", bytes));
        var job = f.Begin(manifest); var jobId = job.JobId; job.ReceiveChunk(manifest.Files[0].Id, 0, bytes); job.Dispose();
        var payload = Path.Combine(f.Root, ".magnolie-receive-" + jobId, manifest.Files[0].Id + ".part");
        TestAssert.That(File.ReadAllBytes(payload).SequenceEqual(bytes), "Closing an incomplete original job discarded its bytes.");
        TestAssert.Throws<InvalidDataException>(() => f.Begin(manifest), "A new ordinary job bypassed original-job recovery.");
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 1 && File.ReadAllBytes(payload).SequenceEqual(bytes), "Original recovery HOLD changed history/payload.");
        var secondManifest = f.Manifest(("withdrawn.jpg", bytes)); using var second = f.Begin(secondManifest);
        f.Local = new(new(8, new string('c', 64), false, false), f.Local.Owner, true);
        TestAssert.Throws<InvalidDataException>(() => second.ReceiveChunk(secondManifest.Files[0].Id, 0, bytes), "Withdrawn actual receive agreement admitted bytes.");
        TestAssert.That(!File.Exists(Path.Combine(f.Root, "withdrawn.jpg")), "Revocation published a file.");
    }

    internal static async Task WindowsPartialPublicationAsync()
    {
        using var f = await Fixture.CreateAsync(); var bytes = "hello"u8.ToArray(); var manifest = f.Manifest(("first.jpg", bytes), ("second.jpg", bytes));
        using var job = f.Begin(manifest);
        foreach (var file in manifest.Files) job.ReceiveChunk(file.Id, 0, bytes);
        File.WriteAllText(Path.Combine(f.Root, "second.jpg"), "keep new user content");
        TestAssert.Throws<IOException>(() => job.PublishAll(), "Raced destination file was overwritten.");
        TestAssert.That(SharedRead(Path.Combine(f.Root, "first.jpg")).SequenceEqual(bytes) && File.ReadAllText(Path.Combine(f.Root, "second.jpg")) == "keep new user content", "Partial publication lost/overwrote bytes.");
        var staged = Path.Combine(f.Root, ".magnolie-receive-" + job.JobId, manifest.Files[1].Id + ".part");
        TestAssert.That(SharedRead(staged).SequenceEqual(bytes) && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().Phase == "publishing", "Uncertain publication erased its original prepared intent/payload.");
        TestAssert.Throws<InvalidDataException>(() => job.PublishAll(), "Uncertain native publication replayed itself.");
    }

    internal static async Task WindowsMissingHistoryAndOccupiedAsync()
    {
        using var f = await Fixture.CreateAsync(); var bytes = "hello"u8.ToArray();
        File.WriteAllText(Path.Combine(f.Root, "user.jpg"), "untouched");
        TestAssert.Throws<InvalidDataException>(() => f.Begin(f.Manifest(("user.jpg", bytes))), "Occupied native target was accepted as a new stage job.");
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 && File.ReadAllText(Path.Combine(f.Root, "user.jpg")) == "untouched", "Occupied preflight created history/changed user data.");
        var orphan = Path.Combine(f.Root, ".magnolie-receive-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(orphan);
        File.WriteAllText(Path.Combine(orphan, "keep"), "held unknown original bytes");
        TestAssert.Throws<InvalidDataException>(() => f.Begin(f.Manifest(("new.jpg", bytes))), "Missing original native history was silently bootstrapped around an unknown stage.");
        TestAssert.That(File.ReadAllText(Path.Combine(orphan, "keep")) == "held unknown original bytes" && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0,
            "Unknown original stage was discarded or fabricated into a new history.");
    }

    internal static async Task WindowsKeyWithdrawalAndCorruptionAsync()
    {
        using var f = await Fixture.CreateAsync(); var bytes = "hello"u8.ToArray(); var manifest = f.Manifest(("held-key.jpg", bytes));
        using var job = f.Begin(manifest); job.ReceiveChunk(manifest.Files[0].Id, 0, bytes);
        var key = f.Native.Paths.TelefonStorageKey; var held = key + ".fixture-held"; File.Move(key, held);
        try { TestAssert.Throws<InvalidDataException>(() => job.PublishAll(), "Removed actual DPAPI storage key left a live publishing owner."); }
        finally { File.Move(held, key); }
        TestAssert.Throws<InvalidDataException>(() => job.PublishAll(), "Restoring a withdrawn key revived the old receive owner.");
        var payload = Path.Combine(f.Root, ".magnolie-receive-" + job.JobId, manifest.Files[0].Id + ".part");
        TestAssert.That(!File.Exists(Path.Combine(f.Root, "held-key.jpg")) && SharedRead(payload).SequenceEqual(bytes), "Key withdrawal lost/published held bytes.");

        var secondManifest = f.Manifest(("held-cipher.jpg", bytes)); using var second = f.Begin(secondManifest);
        second.ReceiveChunk(secondManifest.Files[0].Id, 0, bytes);
        using var db = f.Native.Store.OpenDatabase(); db.Open();
        using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_receive_jobs WHERE peer_id=$peer AND job_id=$job";
        read.Parameters.AddWithValue("$peer", f.Native.Peer.Id); read.Parameters.AddWithValue("$job", second.JobId);
        var original = (byte[])read.ExecuteScalar()!; var damaged = original.ToArray(); damaged[^1] ^= 1;
        using var write = db.CreateCommand(); write.CommandText = "UPDATE native_media_receive_jobs SET value=$value WHERE peer_id=$peer AND job_id=$job";
        write.Parameters.AddWithValue("$peer", f.Native.Peer.Id); write.Parameters.AddWithValue("$job", second.JobId); write.Parameters.AddWithValue("$value", damaged); write.ExecuteNonQuery();
        TestAssert.Throws<CryptographicException>(() => second.PublishAll(), "Damaged protected publication history was overwritten/reset.");
        TestAssert.That(((byte[])read.ExecuteScalar()!).SequenceEqual(damaged) && !File.Exists(Path.Combine(f.Root, "held-cipher.jpg")), "Corrupt history HOLD changed the record or published the file.");
        TestAssert.That(SharedRead(Path.Combine(f.Root, ".magnolie-receive-" + second.JobId, secondManifest.Files[0].Id + ".part")).SequenceEqual(bytes), "Corrupt history HOLD discarded original bytes.");
    }

    internal static async Task WindowsReservationBoundsAsync()
    {
        foreach (var size in new[] { 0L, DeviceFileManifest.MaxFileBytes })
        {
            using var f = await Fixture.CreateAsync(); var maximum = size == 0 ? 32 : 20;
            DeviceFileManifest Reserved(int index) => new(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), f.Native.Peer.Id,
                f.Native.Store.ReadFileIdentity().DeviceId, new[] { new DeviceManifestFile("1".PadLeft(32, '0'), "reserved-" + index + ".jpg", size, new string('a', 64)) }, size);
            for (var index = 0; index < maximum; index++) { using var job = f.Begin(Reserved(index)); }
            TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == maximum, "Reserved quota lost historical jobs.");
            TestAssert.Throws<InvalidDataException>(() => f.Begin(Reserved(maximum)), "Existing active-job / 1 GiB cache budget was widened.");
            TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == maximum &&
                Directory.EnumerateDirectories(f.Root, ".magnolie-receive-*").Count() == maximum, "Quota failure created another root or evicted original history.");
        }
    }
}
