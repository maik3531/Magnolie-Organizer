using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Reflection;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileStoreDestinationsTests
{
    private static DeviceFileConnectionMetadataTests.Fixture Fixture()
    {
        var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        var identity = fixture.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        return fixture;
    }
    private static DeviceFileConnectionMetadataTests.Fixture StagingFixture()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var fixture = Fixture();
        // Explicit fixture materialization only, matching the established real
        // current-user DPAPI receive/source test lane. Product staging never creates keys.
        File.WriteAllText(fixture.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
        return fixture;
    }
    private static long Tables(TelefonStore store)
    {
        using var db = store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT count(*) FROM sqlite_master WHERE name='native_media_destinations'";
        return (long)command.ExecuteScalar()!;
    }
    private static byte[] Blob(TelefonStore store, string peer, string kind)
    {
        using var db = store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT value FROM native_media_destinations WHERE peer_id=$peer AND media_type=$kind";
        command.Parameters.AddWithValue("$peer", peer); command.Parameters.AddWithValue("$kind", kind);
        return (byte[])command.ExecuteScalar()!;
    }
    internal static Task DefaultsAsync()
    {
        using var f = Fixture(); var before = File.ReadAllBytes(f.Paths.TelefonIdentity);
        TestAssert.That(f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") is null &&
            f.Store.ReadNativeMediaDestination(f.Peer.Id, "video") is null && Tables(f.Store) == 0, "Read created a destination/default root.");
        TestAssert.That(File.ReadAllBytes(f.Paths.TelefonIdentity).SequenceEqual(before), "Destination read refreshed local identity.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaDestination(f.Peer.Id, "all"), "Unknown media destination kind accepted.");
        return Task.CompletedTask;
    }
    private static DeviceFileNativeDirectory Directory(DeviceFileConnectionMetadataTests.Fixture f, string name)
    {
        var path = Path.Combine(f.Paths.Root, name); System.IO.Directory.CreateDirectory(path);
        return DeviceFileNativeDirectory.OpenExistingForReceive(path);
    }
    internal static Task WindowsPersistenceAsync()
    {
        using var f = Fixture(); using var images = Directory(f, "native-pictures"); using var videos = Directory(f, "native-videos");
        var picture = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images);
        var video = f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, videos);
        TestAssert.That(picture.DestinationToken != video.DestinationToken && !picture.GrantsReceiveAuthority && !video.GrantsReceiveAuthority,
            "Independent destinations shared a token or created receive consent.");
        var cipher = Blob(f.Store, f.Peer.Id, "images");
        var second = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(second.ReadNativeMediaDestination(f.Peer.Id, "images") == picture && second.ReadNativeMediaDestination(f.Peer.Id, "video") == video,
            "New owner lost a protected native destination.");
        TestAssert.That(second.SetNativeMediaDestination(f.Peer.Id, "images", picture.Version, images) == picture && Blob(f.Store, f.Peer.Id, "images").SequenceEqual(cipher),
            "Idempotent destination save rotated token/ciphertext.");
        TestAssert.Throws<InvalidDataException>(() => second.SetNativeMediaDestination(f.Peer.Id, "images", null, images), "Stale destination choice overwrote saved binding.");
        TestAssert.That(!Encoding.UTF8.GetString(cipher).Contains(picture.NativePath, StringComparison.Ordinal) &&
            !Encoding.UTF8.GetString(cipher).Contains(picture.DestinationToken, StringComparison.Ordinal), "Destination was stored as plaintext.");
        var preferences = second.ReadNativeMediaPreferences(f.Peer.Id);
        TestAssert.That(!preferences.PhotosEnabled && !preferences.VideosEnabled, "Selecting a destination enabled photos/videos.");
        using var db = f.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand(); command.CommandText = "DELETE FROM meta"; command.ExecuteNonQuery();
        TestAssert.That(second.ReadNativeMediaDestination(f.Peer.Id, "images") == picture, "Generic Notes metadata cleanup erased media destination.");
        return Task.CompletedTask;
    }
    internal static Task WindowsOverlapAndReopenAsync()
    {
        using var f = Fixture(); var images = Directory(f, "pictures");
        try
        {
            var saved = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images);
            TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, images), "Photos/videos accepted the same root.");
            using (var nested = images.CreateChild("nested-videos"))
                TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, nested), "Videos accepted a child of the photo destination.");
            using var parent = DeviceFileNativeDirectory.OpenExistingForReceive(f.Paths.Root);
            TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, parent), "Videos accepted a parent of the photo destination.");
            using var other = Directory(f, "other-pictures");
            TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "images", saved.Version, other), "Existing historical destination was silently reassigned.");
            images.Dispose();
            using (var reopened = saved.OpenNative()) TestAssert.That(reopened.CurrentIdentity() == saved.RootIdentity, "Protected native destination could not be reopened exactly.");
            System.IO.Directory.Move(saved.NativePath, saved.NativePath + "-original"); System.IO.Directory.CreateDirectory(saved.NativePath);
            TestAssert.Throws<InvalidDataException>(() => saved.OpenNative(), "A different directory at the old path inherited saved identity/token.");
        }
        finally { images.Dispose(); }
        return Task.CompletedTask;
    }

    internal static Task WindowsInertChoiceStagingAsync()
    {
        using var f = StagingFixture(); using var originalOwner = Directory(f, "original-receive"); using var candidateOwner = Directory(f, "candidate-receive");
        var original = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, originalOwner);
        var originalBlob = Blob(f.Store, f.Peer.Id, "images");
        var preferences = f.Store.ReadNativeMediaPreferences(f.Peer.Id); var consent = f.Store.ReadNativeMediaSendConsent(f.Peer.Id);
        long ChoiceTables()
        {
            using var db = f.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
            command.CommandText = "SELECT count(*) FROM sqlite_master WHERE name='native_media_destination_choices'"; return (long)command.ExecuteScalar()!;
        }
        var before = f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images");
        TestAssert.That(before.Count == 0 && ChoiceTables() == 0, "Choice inspection created a new destination registry.");
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Paths.Root, "destination-choice-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}");
        var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var staged = f.Store.StageNativeMediaDestinationChoice(f.Peer.Id, "images", original.Version, before, candidateOwner, permit.Require);
        TestAssert.That(staged.OriginalVersion == original.Version && staged.CreationFileTime == candidateOwner.CurrentReceiveCreationFileTime() &&
            !staged.GrantsReceiveAuthority && !staged.GrantsSendAuthority && !staged.Destination.GrantsReceiveAuthority &&
            staged.Destination.RootIdentity == candidateOwner.CurrentReceiveIdentity() && staged.Destination.Version != original.Version,
            "Staged native metadata lost original context/generation or granted transfer rights.");
        var catalog = f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images");
        TestAssert.That(catalog.Count == 1 && catalog[0] == staged && ChoiceTables() == 1, "Staged choice lost its protected readback.");
        var second = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(second.ReadNativeMediaDestinationChoices(f.Peer.Id, "images").SequenceEqual(catalog) &&
            second.StageNativeMediaDestinationChoice(f.Peer.Id, "images", original.Version, catalog, candidateOwner, permit.Require) == staged,
            "New store lost or rotated an idempotent inert choice.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "images", original.Version, candidateOwner),
            "Staging opened the unimplemented active destination switch.");
        TestAssert.That(f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") == original && Blob(f.Store, f.Peer.Id, "images").SequenceEqual(originalBlob) &&
            f.Store.ReadNativeMediaPreferences(f.Peer.Id) == preferences && f.Store.ReadNativeMediaSendConsent(f.Peer.Id) == consent &&
            !System.IO.Directory.EnumerateFileSystemEntries(candidateOwner.NativePath).Any(), "Staging modified active root/ciphertext/consent/files.");
        return Task.CompletedTask;
    }

    internal static Task WindowsInertChoiceStagingGuardsAsync()
    {
        foreach (var scenario in new[] { "stale_original", "stale_catalog", "late_context", "generation", "overlap", "cipher", "future_field" })
        {
            using var f = StagingFixture(); using var originalOwner = Directory(f, "original"); using var candidateOwner = Directory(f, "candidate");
            var original = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, originalOwner); var originalBlob = Blob(f.Store, f.Peer.Id, "images");
            var expected = f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images");
            TelefonStore.NativeMediaDestinationChoice? first = null; byte[]? changedBlob = null;
            if (scenario is "stale_catalog" or "cipher" or "future_field")
                first = f.Store.StageNativeMediaDestinationChoice(f.Peer.Id, "images", original.Version, expected, candidateOwner, () => { });
            if (scenario is "cipher" or "future_field")
            {
                using var db = f.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
                read.CommandText = "SELECT value FROM native_media_destination_choices WHERE version=$version"; read.Parameters.AddWithValue("$version", first!.Destination.Version);
                var cipher = (byte[])read.ExecuteScalar()!;
                if (scenario == "cipher") { changedBlob = cipher.ToArray(); changedBlob[^1] ^= 1; }
                else
                {
                    var plain = f.Store.Open("native_media_destination_choices", f.Peer.Id + "/images/" + first.Destination.Version, cipher);
                    try
                    {
                        var value = System.Text.Json.Nodes.JsonNode.Parse(plain)!.AsObject(); value["future_field"] = "must remain retained, not rewritten";
                        var bytes = TelefonCrypto.Canonical(value);
                        try { changedBlob = f.Store.Seal("native_media_destination_choices", f.Peer.Id + "/images/" + first.Destination.Version, bytes); }
                        finally { CryptographicOperations.ZeroMemory(bytes); }
                    }
                    finally { CryptographicOperations.ZeroMemory(plain); }
                }
                using var write = db.CreateCommand(); write.CommandText = "UPDATE native_media_destination_choices SET value=$value WHERE version=$version";
                write.Parameters.AddWithValue("$value", changedBlob); write.Parameters.AddWithValue("$version", first.Destination.Version); write.ExecuteNonQuery();
            }
            var calls = 0;
            void Current()
            {
                calls++;
                if (scenario == "late_context" && calls == 4) throw DeviceFileControl.Error("destination-test-original-context-ended");
                if (scenario == "generation" && calls == 3) System.IO.Directory.SetCreationTimeUtc(candidateOwner.NativePath,
                    DateTime.FromFileTimeUtc((long)candidateOwner.CurrentReceiveCreationFileTime()).AddSeconds(-5));
            }
            string? rejection = null;
            try
            {
                f.Store.StageNativeMediaDestinationChoice(f.Peer.Id, "images", scenario == "stale_original" ? new string('e', 64) : original.Version,
                    expected, scenario == "overlap" ? originalOwner : candidateOwner, Current);
                throw new Exception("Invalid inert destination choice was accepted: " + scenario);
            }
            catch (InvalidDataException error) { rejection = error.Message; }
            catch (CryptographicException) when (scenario == "cipher") { rejection = "crypto"; }
            var required = scenario switch {
                "stale_original" => "file_destination_stale_choice", "stale_catalog" => "file_destination_choice_catalog_changed",
                "late_context" => "destination-test-original-context-ended", "generation" => "file_destination_choice_context_changed",
                "overlap" => "file_destination_choice_roots_overlap", "cipher" => "crypto", _ => "Unbekannte oder fehlende Felder." };
            TestAssert.That(rejection == required && (scenario != "late_context" || calls == 4) && (scenario != "generation" || calls == 3),
                "Choice guard did not exercise its original failure boundary: " + scenario + ": " + rejection);
            TestAssert.That(f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") == original && Blob(f.Store, f.Peer.Id, "images").SequenceEqual(originalBlob),
                "Staging guard rewrote active original metadata: " + scenario);
            if (changedBlob is null) TestAssert.That(f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images").Count == (first is null ? 0 : 1),
                "Failed choice lost existing metadata or committed a late result: " + scenario);
            else
            {
                using var db = f.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
                read.CommandText = "SELECT value FROM native_media_destination_choices WHERE version=$version"; read.Parameters.AddWithValue("$version", first!.Destination.Version);
                TestAssert.That(((byte[])read.ExecuteScalar()!).SequenceEqual(changedBlob), "Corrupt/unknown choice metadata was normalized or repaired.");
            }
        }
        return Task.CompletedTask;
    }

    internal static Task WindowsInertChoiceCapacityAndKeyAsync()
    {
        using var f = StagingFixture(); using var originalOwner = Directory(f, "original");
        var original = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, originalOwner); var blob = Blob(f.Store, f.Peer.Id, "images");
        var before = f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images"); var key = File.ReadAllBytes(f.Paths.TelefonStorageKey);
        using (var candidate = Directory(f, "no-key-candidate"))
        {
            File.Delete(f.Paths.TelefonStorageKey);
            try
            {
                TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images"), "Missing native key was hidden by cached metadata.");
                TestAssert.Throws<InvalidDataException>(() => f.Store.StageNativeMediaDestinationChoice(f.Peer.Id, "images", original.Version, before, candidate, () => { }),
                    "Missing original key allowed a new choice.");
                TestAssert.That(!File.Exists(f.Paths.TelefonStorageKey), "Inert staging recreated a missing native key.");
            }
            finally { File.WriteAllBytes(f.Paths.TelefonStorageKey, key); }
        }
        for (var index = 0; index < 32; index++)
        {
            using var candidate = Directory(f, "candidate-" + index);
            f.Store.StageNativeMediaDestinationChoice(f.Peer.Id, "images", original.Version,
                f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images"), candidate, () => { });
        }
        var full = f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images");
        using (var overflow = Directory(f, "candidate-overflow"))
        {
            try
            {
                f.Store.StageNativeMediaDestinationChoice(f.Peer.Id, "images", original.Version, full, overflow, () => { });
                throw new Exception("Full inert destination-choice catalog evicted history or enlarged its bound.");
            }
            catch (InvalidDataException error) { TestAssert.That(error.Message == "file_destination_choice_capacity", "Choice capacity held for unrelated reason."); }
        }
        TestAssert.That(full.Count == 32 && f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images").SequenceEqual(full) &&
            f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") == original && Blob(f.Store, f.Peer.Id, "images").SequenceEqual(blob),
            "Inert capacity HOLD discarded metadata or selected a new active destination.");
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var write = db.CreateCommand(); write.CommandText = "DELETE FROM native_media_destinations WHERE peer_id=$peer";
            write.Parameters.AddWithValue("$peer", f.Peer.Id); write.ExecuteNonQuery();
        }
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaDestinationChoices(f.Peer.Id, "images"), "Orphan inert choices reconstructed a lost original destination.");
        return Task.CompletedTask;
    }

    private static (object Scope, object Head, byte[] Cipher) OriginalJobInputs(DeviceFileReceiveJobTests.Fixture f)
    {
        var flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var scope = typeof(TelefonStore).GetMethod("MediaPreferenceScope", flags)!.Invoke(f.Native.Store, [f.Native.Peer.Id])!;
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_receive_jobs WHERE job_id=$job"; read.Parameters.AddWithValue("$job", job.JobId);
        var cipher = (byte[])read.ExecuteScalar()!;
        var head = typeof(TelefonStore).GetMethod("ReadReceiveHead", flags)!.Invoke(f.Native.Store, [cipher, job.JobId, scope])!;
        return (scope, head, cipher);
    }
    private static object OriginalJobOwner(TelefonStore store, object scope, object head) => Activator.CreateInstance(
        typeof(TelefonStore).GetNestedType("NativeCompletedDestinationOwner", BindingFlags.NonPublic)!,
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public, null, [store, scope, head], null)!;
    private static void RequireOriginalJobOwner(object owner) => owner.GetType().GetMethod("Require", BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(owner, null);

    internal static async Task WindowsOriginalJobRecoveryAfterStagingAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aX0AAAAASUVORK5CYII=");
        await DeviceFileBackupCatalogTests.Seed(f, png);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var legacy = Blob(f.Native.Store, f.Native.Peer.Id, "images");
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "original-job-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}");
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        bool Current() { book.Require(); return true; }
        var backup = DeviceFileBackupCatalogTests.Save(f, permit: Current);
        var path = Path.Combine(f.Native.Paths.Root, "inert-candidate"); System.IO.Directory.CreateDirectory(path);
        DeviceFileConnectionRunsTests.Clear(f);
        using (var candidate = DeviceFileNativeDirectory.OpenExistingForReceive(path))
            f.Native.Store.StageNativeMediaDestinationChoice(f.Native.Peer.Id, "images", f.Destination.Version,
                f.Native.Store.ReadNativeMediaDestinationChoices(f.Native.Peer.Id, "images"), candidate, book.Require);
        TestAssert.That(DeviceFileBackupCatalogTests.Save(f, permit: Current) == backup, "Inert metadata renewed or replaced the original raw backup.");
        using (var root = f.Destination.OpenNative())
        using (var target = root.CreateStagedFile("independent-restored.png"))
            f.Native.Store.RestoreNativeMediaBackup(f.Destination, backup, target, Current);
        var entry = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, 1.ToString("x32"), Current);
        var rendered = 0;
        var preview = f.Native.Store.PreviewNativeMediaTrash(f.Native.Peer.Id, entry, Current, 192, (bytes, kind, side, current) =>
        {
            current(); rendered++; TestAssert.That(bytes.SequenceEqual(png) && kind == "images", "Original preview read another root or unauthenticated bytes.");
            return new("image/png", 1, 1, Convert.ToBase64String(png));
        });
        var restored = f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, Current);
        var album = Path.Combine(f.Root, new NativeMediaAlbumContext(new string('e', 64), "Kamera").Folder);
        TestAssert.That(rendered == 1 && preview.Width == 1 && restored.State == "restored" &&
            File.ReadAllBytes(Path.Combine(album, "first.jpg")).SequenceEqual(png) && File.ReadAllBytes(Path.Combine(f.Root, "independent-restored.png")).SequenceEqual(png) &&
            Blob(f.Native.Store, f.Native.Peer.Id, "images").SequenceEqual(legacy) && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job &&
            f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination && !System.IO.Directory.EnumerateFileSystemEntries(path).Any() && f.Native.Stream.Length == 0,
            "Staging displaced original backup/trash/preview/restore ownership, bytes or receive history.");
    }

    internal static async Task WindowsOriginalJobOwnerGuardsAsync()
    {
        foreach (var scenario in new[] { "substituted_root", "lost_job", "missing_key", "staged_version", "forged_body", "saved_without_end" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
            var inputs = OriginalJobInputs(f); var owner = OriginalJobOwner(f.Native.Store, inputs.Scope, inputs.Head);
            var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var legacy = Blob(f.Native.Store, f.Native.Peer.Id, "images");
            var key = File.ReadAllBytes(f.Native.Paths.TelefonStorageKey); var first = File.ReadAllBytes(Path.Combine(f.Root, "first.jpg"));
            var path = Path.Combine(f.Native.Paths.Root, "inert-root"); System.IO.Directory.CreateDirectory(path);
            using var candidate = DeviceFileNativeDirectory.OpenExistingForReceive(path);
            var staged = f.Native.Store.StageNativeMediaDestinationChoice(f.Native.Peer.Id, "images", f.Destination.Version,
                f.Native.Store.ReadNativeMediaDestinationChoices(f.Native.Peer.Id, "images"), candidate, () => { });
            void Held(Action action)
            {
                try { action(); }
                catch (TargetInvocationException error) when (error.InnerException is InvalidDataException or CryptographicException) { return; }
                throw new Exception("Invalid completed-job owner survived: " + scenario);
            }
            if (scenario is "staged_version" or "forged_body" or "saved_without_end")
            {
                var body = ((JsonObject)inputs.Head.GetType().GetProperty("Body")!.GetValue(inputs.Head)!).DeepClone().AsObject();
                if (scenario == "saved_without_end") body.Remove("source_end");
                else
                {
                    body["destination_version"] = staged.Destination.Version;
                    body["destination"] = new JsonObject { ["native_path"] = staged.Destination.NativePath, ["volume_path"] = staged.Destination.VolumePath,
                        ["identity"] = TelefonStore.NativeMediaReceiveJob.NativeIdentity(staged.Destination.RootIdentity), ["token"] = staged.Destination.DestinationToken };
                    body["binding"]!["destination_token"] = staged.Destination.DestinationToken;
                }
                var fake = Activator.CreateInstance(inputs.Head.GetType(), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
                    [job.JobId, (long)inputs.Head.GetType().GetProperty("Revision")!.GetValue(inputs.Head)!, scenario == "staged_version" ? staged.Destination.Version : job.Version, body], null)!;
                Held(() => OriginalJobOwner(f.Native.Store, inputs.Scope, fake));
                RequireOriginalJobOwner(owner); // A failed foreign proposal does not retire the actual original metadata owner.
            }
            else
            {
                if (scenario == "missing_key") File.Delete(f.Native.Paths.TelefonStorageKey);
                else
                {
                    using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
                    if (scenario == "lost_job")
                    { write.CommandText = "DELETE FROM native_media_receive_jobs WHERE job_id=$job"; write.Parameters.AddWithValue("$job", job.JobId); }
                    else
                    {
                        var plain = f.Native.Store.Open("native_media_destinations", f.Native.Peer.Id + "/images", legacy); byte[] cipher;
                        try
                        {
                            var body = JsonNode.Parse(plain)!.AsObject(); body["native_path"] = staged.Destination.NativePath; body["volume_path"] = staged.Destination.VolumePath;
                            body["volume_serial"] = staged.Destination.RootIdentity.VolumeSerial.ToString("x16");
                            body["file_id_low"] = staged.Destination.RootIdentity.FileIdLow.ToString("x16"); body["file_id_high"] = staged.Destination.RootIdentity.FileIdHigh.ToString("x16");
                            var bytes = TelefonCrypto.Canonical(body);
                            try { cipher = f.Native.Store.Seal("native_media_destinations", f.Native.Peer.Id + "/images", bytes); }
                            finally { CryptographicOperations.ZeroMemory(bytes); }
                        }
                        finally { CryptographicOperations.ZeroMemory(plain); }
                        write.CommandText = "UPDATE native_media_destinations SET value=$value WHERE peer_id=$peer AND media_type='images'";
                        write.Parameters.AddWithValue("$value", cipher); write.Parameters.AddWithValue("$peer", f.Native.Peer.Id);
                    }
                    write.ExecuteNonQuery();
                }
                Held(() => RequireOriginalJobOwner(owner));
                if (scenario == "missing_key")
                { TestAssert.That(!File.Exists(f.Native.Paths.TelefonStorageKey), "Original-job owner recreated a missing native key."); File.WriteAllBytes(f.Native.Paths.TelefonStorageKey, key); }
                else
                {
                    using var db = f.Native.Store.OpenDatabase(); db.Open(); using var restore = db.CreateCommand();
                    restore.CommandText = scenario == "lost_job" ? "INSERT INTO native_media_receive_jobs(peer_id,job_id,value) VALUES($peer,$job,$value)" :
                        "UPDATE native_media_destinations SET value=$value WHERE peer_id=$peer AND media_type='images'";
                    restore.Parameters.AddWithValue("$peer", f.Native.Peer.Id); restore.Parameters.AddWithValue("$value", scenario == "lost_job" ? inputs.Cipher : legacy);
                    if (scenario == "lost_job") restore.Parameters.AddWithValue("$job", job.JobId);
                    restore.ExecuteNonQuery();
                }
                Held(() => RequireOriginalJobOwner(owner)); // Restoration never revives the old metadata owner.
                RequireOriginalJobOwner(OriginalJobOwner(f.Native.Store, inputs.Scope, inputs.Head));
            }
            TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(first) &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job && !System.IO.Directory.EnumerateFileSystemEntries(path).Any(),
                "Invalid metadata owner read/mutated a staged root or lost original job facts.");
        }
    }
    internal static Task WindowsBindingAndTamperAsync()
    {
        foreach (var change in new[] { "key", "pairing", "local", "unpaired", "cipher" })
        {
            using var f = Fixture(); using var images = Directory(f, "pictures");
            var saved = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images); var original = Blob(f.Store, f.Peer.Id, "images");
            if (change == "key") f.Store.SavePeers([f.Peer with { PublicKey = Enumerable.Repeat((byte)91, 32).ToArray() }]);
            if (change == "pairing") f.Store.SavePeers([f.Peer with { FilePairingEpoch = new string('f', 64) }]);
            if (change == "unpaired") f.Store.SavePeers([]);
            if (change == "local")
            {
                File.Delete(f.Paths.TelefonIdentity); File.Delete(f.Paths.TelefonIdentityKey);
                var local = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(local.PrivateKey);
            }
            var expected = original;
            if (change == "cipher")
            {
                expected = original.ToArray(); expected[^1] ^= 1;
                using var db = f.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
                command.CommandText = "UPDATE native_media_destinations SET value=$value WHERE peer_id=$peer";
                command.Parameters.AddWithValue("$value", expected); command.Parameters.AddWithValue("$peer", f.Peer.Id); command.ExecuteNonQuery();
            }
            void Held(Action action)
            {
                try { action(); } catch (InvalidDataException) { return; } catch (CryptographicException) { return; }
                throw new InvalidOperationException("Changed/tampered destination was not held: " + change);
            }
            Held(() => f.Store.ReadNativeMediaDestination(f.Peer.Id, "images"));
            Held(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "images", saved.Version, images));
            TestAssert.That(Blob(f.Store, f.Peer.Id, "images").SequenceEqual(expected), "Binding/tamper HOLD overwrote destination evidence: " + change);
        }
        return Task.CompletedTask;
    }

    internal static Task WindowsMissingDatabaseAsync()
    {
        using var f = Fixture(); using var images = Directory(f, "pictures");
        var original = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images);
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        var path = f.Paths.TelefonDatabase; var held = path + ".fixture-held"; File.Move(path, held);
        try
        {
            TestAssert.Throws<Microsoft.Data.Sqlite.SqliteException>(() => f.Store.ReadNativeMediaDestination(f.Peer.Id, "images"), "Missing original DB was defaulted/created by destination read.");
            TestAssert.Throws<Microsoft.Data.Sqlite.SqliteException>(() => f.Store.ReadNativeMediaPreferences(f.Peer.Id), "Missing original DB was defaulted/created by preference read.");
            TestAssert.Throws<Microsoft.Data.Sqlite.SqliteException>(() => f.Store.NativeMediaReceiveHistory(f.Peer.Id), "Missing original DB was defaulted/created by receive-history read.");
            TestAssert.That(!File.Exists(path), "A media inspection bootstrapped a replacement personal phone DB.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); File.Move(held, path); }
        TestAssert.That(f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") == original, "Original DB return lost native destination.");
        return Task.CompletedTask;
    }
}
