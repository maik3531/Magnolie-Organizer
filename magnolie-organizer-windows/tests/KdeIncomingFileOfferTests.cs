using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeIncomingFileOfferTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-offer-" + Guid.NewGuid().ToString("N"));
        var staging = Path.Combine(root, "staging"); Directory.CreateDirectory(staging);
        var source = new KdeReceiveSource("paired-offer", new string('a', 64), new object(), 7);
        KdeReceiveSource? live = source;
        var now = new DateTimeOffset(2026, 11, 2, 12, 0, 0, TimeSpan.Zero);
        var nativeGate = new object();
        void PublishGate(KdeReceiveSource expected, Action action)
        {
            lock (nativeGate)
            {
                TestAssert.That(live is not null && live.DeviceId == expected.DeviceId &&
                    live.CertificateFingerprint == expected.CertificateFingerprint && live.Generation == expected.Generation &&
                    ReferenceEquals(live.Connection, expected.Connection), "Native publication lease changed.");
                action();
            }
        }
        string Destination()
        {
            var path = Path.Combine(root, "target-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(path); return path;
        }
        (KdeIncomingFileOffer Offer, string[] Paths) Offer((string Name, byte[] Data)[] values,
            Action<KdeReceiveSource, Action>? publication = null)
        {
            live = source;
            var total = values.Sum(value => (long)value.Data.Length);
            using var batch = new KdeIncomingFileBatch(source, staging, values.Length, total,
                now.AddMinutes(5), () => live, () => now);
            var paths = new List<string>();
            foreach (var value in values)
            {
                var id = Guid.NewGuid();
                batch.Announce(id, new(value.Name, value.Data.Length, 1716, values.Length, total));
                var path = Path.Combine(staging, Guid.NewGuid().ToString("N"));
                File.WriteAllBytes(path, value.Data); paths.Add(path); batch.Stage(id, path);
            }
            return (batch.CreateOffer(publication ?? PublishGate), paths.ToArray());
        }
        try
        {
            var destination = Destination(); var existing = Path.Combine(destination, "same.txt");
            File.WriteAllText(existing, "keep");
            var first = Offer([("same.txt", [1]), ("same.txt", [2]), ("empty.txt", [])]);
            await using (var offer = first.Offer)
            {
                TestAssert.That(offer.Proposal().Count == 3 && offer.Saved.Count == 0,
                    "An offer published a file before a destination acceptance.");
                var saved = await offer.PublishAsync(destination);
                TestAssert.That(saved.Select(value => value.Name).SequenceEqual(["same (1).txt", "same (2).txt", "empty.txt"]) &&
                    saved.Count == 3 && offer.RemainingCount == 0 && saved.All(value => File.Exists(value.Path)),
                    "One accepted list was not published completely with collision-safe names.");
                TestAssert.That(File.ReadAllBytes(saved[0].Path).SequenceEqual(new byte[] { 1 }) &&
                    File.ReadAllBytes(saved[1].Path).SequenceEqual(new byte[] { 2 }) && new FileInfo(saved[2].Path).Length == 0 &&
                    File.ReadAllText(existing) == "keep", "Publication changed existing data or received bytes.");
                TestAssert.That((await offer.PublishAsync(destination)).Count == 3 &&
                    !File.Exists(Path.Combine(destination, "same (3).txt")), "An accepted-list retry duplicated completed files.");
            }
            TestAssert.That(File.Exists(existing) && Directory.GetFiles(destination).Length == 4 && first.Paths.All(path => !File.Exists(path)),
                "Offer disposal removed saved files or retained normal staging files.");

            foreach (var failAfterCommit in new[] { false, true })
            {
                var target = Destination(); var other = Destination(); var calls = 0;
                var partial = Offer([("first.txt", [1]), ("second.txt", [2])], (expected, action) =>
                {
                    calls++;
                    if (!failAfterCommit && calls == 2) throw new IOException("synthetic target failure");
                    PublishGate(expected, action);
                    if (failAfterCommit && calls == 1) throw new IOException("synthetic acknowledgement failure after committed move");
                });
                await using (var offer = partial.Offer)
                {
                    await TestAssert.ThrowsAsync<IOException>(() => offer.PublishAsync(target), "Synthetic partial failure was not surfaced.");
                    TestAssert.That(offer.Saved.Count == 1 && offer.RemainingCount == 1 &&
                        File.ReadAllBytes(Path.Combine(target, "first.txt")).SequenceEqual(new byte[] { 1 }),
                        "A partial or post-commit failure forgot an actual saved member.");
                    await TestAssert.ThrowsAsync<InvalidOperationException>(() => offer.PublishAsync(other),
                        "A partially saved list silently changed its selected destination.");
                    TestAssert.That((await offer.PublishAsync(target)).Count == 2 && offer.RemainingCount == 0 &&
                        Directory.GetFiles(target).Length == 2 && Directory.GetFiles(other).Length == 0,
                        "Retry overwrote/duplicated already-saved members or used another target.");
                }
                TestAssert.That(Directory.GetFiles(target).Length == 2 && partial.Paths.All(path => !File.Exists(path)),
                    "Partial retry cleanup removed destination files or leaked adopted staging.");
            }

            var revokeTarget = Destination();
            var revoked = Offer([("one.txt", [1])], (_, action) => { live = source with { Generation = 8 }; action(); });
            await using (var offer = revoked.Offer)
            {
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => offer.PublishAsync(revokeTarget),
                    "Source revocation at the actual publication boundary was ignored.");
                TestAssert.That(offer.Saved.Count == 0 && Directory.GetFiles(revokeTarget).Length == 0 &&
                    File.Exists(revoked.Paths[0]), "Rejected publication changed a destination or silently discarded its staged source.");
            }
            TestAssert.That(!File.Exists(revoked.Paths[0]), "Rejected offer could not clean its own private staging after revocation.");

            var tamperedTarget = Destination(); var tampered = Offer([("one.txt", [1])]);
            await using (var offer = tampered.Offer)
            {
                File.WriteAllBytes(tampered.Paths[0], [9]);
                await TestAssert.ThrowsAsync<InvalidDataException>(() => offer.PublishAsync(tamperedTarget),
                    "Same-size changed staging passed the original byte witness.");
                TestAssert.That(Directory.GetFiles(tamperedTarget).Length == 0 && offer.Saved.Count == 0,
                    "Changed received bytes were exposed as a completed destination file.");
            }

            var cancelTarget = Destination(); using var cancellation = new CancellationTokenSource();
            var canceled = Offer([("one.txt", [1])], (_, action) => { cancellation.Cancel(); action(); });
            await using (var offer = canceled.Offer)
            {
                await TestAssert.ThrowsAsync<OperationCanceledException>(() => offer.PublishAsync(cancelTarget, cancellation.Token),
                    "Cancellation at the actual native move boundary was ignored.");
                TestAssert.That(Directory.GetFiles(cancelTarget).Length == 0, "Canceled publication left an accepted destination file.");
            }

            var longTarget = Destination(); var longName = new string('x', 250) + ".txt";
            File.WriteAllText(Path.Combine(longTarget, longName), "keep");
            var longFile = Offer([(longName, [7])]);
            await using (var offer = longFile.Offer)
            {
                var saved = (await offer.PublishAsync(longTarget)).Single();
                TestAssert.That(saved.Name.Length <= 255 && KdeShareProtocol.SafeName(saved.Name) &&
                    saved.Name != longName && File.ReadAllBytes(saved.Path).SequenceEqual(new byte[] { 7 }) &&
                    File.ReadAllText(Path.Combine(longTarget, longName)) == "keep", "Collision alternative exceeded the Windows name bound or overwrote the original.");
            }

            var noCommitTarget = Destination(); var noCommit = Offer([("one.txt", [1])], (_, _) => { });
            await using (var offer = noCommit.Offer)
            {
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => offer.PublishAsync(noCommitTarget),
                    "A native gate which never executed the move manufactured a saved receipt.");
                TestAssert.That(Directory.GetFiles(noCommitTarget).Length == 0 && offer.Saved.Count == 0,
                    "Unexecuted publication acquired a completed destination file.");
            }
            TestAssert.That(Directory.GetFiles(staging).Length == 0, "Owned offer fixtures leaked staged or temporary files.");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
