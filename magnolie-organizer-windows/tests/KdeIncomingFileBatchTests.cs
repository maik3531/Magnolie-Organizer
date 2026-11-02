using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeIncomingFileBatchTests
{
    private sealed class EqualConnection
    {
        public override bool Equals(object? value) => true;
        public override int GetHashCode() => 0;
    }

    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-incoming-" + Guid.NewGuid().ToString("N"));
        var staging = Path.Combine(root, "staging");
        Directory.CreateDirectory(staging);
        var initialTime = new DateTimeOffset(2026, 11, 2, 12, 0, 0, TimeSpan.Zero);
        var now = initialTime;
        var source = new KdeReceiveSource("paired-device", new string('a', 64), new EqualConnection(), 3);
        KdeReceiveSource? live = source;
        KdeIncomingFileBatch Create(long count, long total) => new(source, staging, count, total,
            now.AddMinutes(5), () => live, () => now);
        string FileBytes(byte[] bytes)
        {
            var path = Path.Combine(staging, Guid.NewGuid().ToString("N"));
            File.WriteAllBytes(path, bytes);
            return path;
        }
        KdeShareAnnouncement Value(string name, long size, long count, long total) => new(name, size, 1716, count, total);
        try
        {
            using (var batch = Create(2, 5))
            {
                var first = Guid.NewGuid(); var second = Guid.NewGuid();
                batch.Announce(first, Value("one.txt", 2, 2, 5));
                TestAssert.Throws<InvalidOperationException>(() => batch.Proposal(), "Incomplete list could be reviewed.");
                TestAssert.That(!batch.Stage(first, FileBytes([1, 2])), "First of two members sealed the list.");
                batch.Announce(second, Value("two.txt", 3, 2, 5));
                TestAssert.That(batch.Stage(second, FileBytes([3, 4, 5])), "Complete list was not sealed.");
                var preview = batch.Proposal();
                TestAssert.That(preview.SequenceEqual(new[] { new KdeIncomingMember("one.txt", 2), new KdeIncomingMember("two.txt", 3) }),
                    "Reviewed manifest lost a member or exposed transport/staging fields.");
                ((KdeIncomingMember[])preview)[0] = new("unreviewed.txt", 10);
                TestAssert.That(batch.Proposal()[0].Name == "one.txt", "Preview mutation changed the internal manifest.");
                TestAssert.Throws<InvalidOperationException>(() => batch.Update(3, 6), "A sealed offer accepted a late extension.");
                TestAssert.Throws<InvalidOperationException>(() => batch.Announce(Guid.NewGuid(), Value("later", 1, 3, 6)),
                    "An unknown later member inherited sealed-list consent.");
                var taken = batch.Take();
                TestAssert.That(taken[0].Sha256 == Convert.ToHexString(SHA256.HashData(new byte[] { 1, 2 })).ToLowerInvariant(),
                    "Staged witness did not bind the actual received bytes.");
                TestAssert.Throws<InvalidOperationException>(() => batch.Take(), "A manifest could be handed off twice.");
                batch.Dispose();
                TestAssert.That(taken.All(member => File.Exists(member.StagedPath)), "Disposal removed files already handed to the accepted offer.");
                foreach (var member in taken) File.Delete(member.StagedPath);
            }

            var unrelated = Path.Combine(root, "unrelated"); File.WriteAllText(unrelated, "keep");
            string owned;
            using (var batch = Create(2, 2))
            {
                var id = Guid.NewGuid(); batch.Announce(id, Value("one", 1, 2, 2));
                owned = FileBytes([1]); batch.Stage(id, owned);
                TestAssert.Throws<InvalidDataException>(() => batch.Announce(id, Value("duplicate", 1, 2, 2)),
                    "A local member token could be repeated.");
                TestAssert.Throws<InvalidDataException>(() => batch.Stage(Guid.NewGuid(), unrelated),
                    "An unannounced file was adopted as a staging member.");
            }
            TestAssert.That(!File.Exists(owned) && File.ReadAllText(unrelated) == "keep", "Batch cleanup touched unrelated data or kept owned staged files.");

            foreach (var changed in new KdeReceiveSource?[] { null, source with { Generation = 4 },
                source with { DeviceId = "other-device" }, source with { CertificateFingerprint = new string('b', 64) },
                source with { Connection = new EqualConnection() } })
            {
                live = source;
                using var batch = Create(1, 0);
                var id = Guid.NewGuid(); batch.Announce(id, Value("empty", 0, 1, 0));
                var empty = FileBytes([]); batch.Stage(id, empty);
                live = changed;
                TestAssert.Throws<InvalidOperationException>(() => batch.Take(), "Changed source/identity/connection/generation retained consent.");
                batch.Dispose();
                TestAssert.That(!File.Exists(empty), "Revoked source blocked safe staging cleanup.");
            }
            live = source;

            using (var batch = Create(1, 0))
            {
                var id = Guid.NewGuid(); batch.Announce(id, Value("empty", 0, 1, 0));
                var empty = FileBytes([]); batch.Stage(id, empty);
                now = now.AddMinutes(6);
                TestAssert.Throws<InvalidOperationException>(() => batch.Take(), "Expired reviewed list could be accepted.");
                batch.Dispose(); TestAssert.That(!File.Exists(empty), "Expired list kept owned staging files.");
            }
            now = initialTime;

            using (var batch = Create(2, 2))
            {
                var first = Guid.NewGuid(); var second = Guid.NewGuid(); var third = Guid.NewGuid();
                batch.Announce(first, Value("same.txt", 1, 2, 2));
                batch.Announce(second, Value("same.txt", 1, 2, 2));
                TestAssert.That(!batch.AcceptingAnnouncements, "Full announcement count admitted unrelated members.");
                batch.Update(3, 3);
                batch.Announce(third, Value("third.txt", 1, 3, 3));
                TestAssert.That(!batch.Stage(first, FileBytes([1])) && !batch.Stage(second, FileBytes([2])) &&
                    batch.Stage(third, FileBytes([3])), "Growing unsealed count was ignored or completed prematurely.");
                TestAssert.That(batch.Proposal().Count == 3, "Growth omitted a file from the actual reviewed manifest.");
            }

            using (var batch = Create(1, 1))
            {
                var id = Guid.NewGuid(); batch.Announce(id, Value("one", 1, 1, 1));
                TestAssert.Throws<InvalidDataException>(() => batch.Stage(id, unrelated), "A file outside the exact private staging directory was read/adopted.");
                TestAssert.Throws<InvalidDataException>(() => batch.Stage(id, Path.Combine(staging, "file:stream")),
                    "An alternate-stream staging path bypassed the private regular-file boundary.");
                var shortFile = FileBytes([]);
                TestAssert.Throws<InvalidDataException>(() => batch.Stage(id, shortFile), "Wrong-sized file was verified.");
                TestAssert.Throws<InvalidOperationException>(() => batch.Proposal(), "Wrong-sized staging produced a proposal.");
                File.Delete(shortFile);
                if (!OperatingSystem.IsWindows())
                {
                    var link = Path.Combine(staging, "owned-test-link"); File.CreateSymbolicLink(link, unrelated);
                    TestAssert.Throws<InvalidDataException>(() => batch.Stage(id, link), "Staging followed a link outside its root.");
                    File.Delete(link);
                }
            }
            TestAssert.That(File.ReadAllText(unrelated) == "keep", "Rejected staging changed the unrelated file.");

            var checks = 0; var revokeDuringRead = false;
            using (var batch = new KdeIncomingFileBatch(source, staging, 1, 1, now.AddMinutes(5),
                () => revokeDuringRead && ++checks >= 2 ? source with { Generation = 4 } : source, () => now))
            {
                var id = Guid.NewGuid(); batch.Announce(id, Value("one", 1, 1, 1));
                var path = FileBytes([1]); revokeDuringRead = true;
                TestAssert.Throws<InvalidOperationException>(() => batch.Stage(id, path), "Identity change during the actual hash read was ignored.");
                TestAssert.That(File.Exists(path), "Failed staging silently adopted/deleted a caller-owned download.");
                File.Delete(path);
            }

            foreach (var bounds in new[] { (0L, 1L), (129L, 1L), (1L, -1L), (1L, KdeIncomingFileBatch.MaxBytes + 1) })
                TestAssert.Throws<InvalidDataException>(() => Create(bounds.Item1, bounds.Item2), "Unbounded batch allocation was admitted.");
        }
        finally { Directory.Delete(root, recursive: true); }
        return Task.CompletedTask;
    }
}
