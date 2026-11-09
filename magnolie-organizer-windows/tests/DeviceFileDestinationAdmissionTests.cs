using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileDestinationAdmissionTests
{
    private sealed class Fixture : IDisposable
    {
        internal readonly DeviceFileReceiveJobTests.Fixture F;
        internal readonly TelefonCoordinator C;
        internal readonly PersonalActorNativeSaveHost Host;
        internal readonly Dictionary<string, TelefonConnection> Online;
        internal string Peer => F.Native.Peer.Id;
        internal TelefonStore Store => F.Native.Store;
        internal Fixture(DeviceFileReceiveJobTests.Fixture f)
        {
            F = f; Host = new(Path.Combine(f.Native.Paths.Root, "admission-book"), "{\"syncEpoch\":\"admission-book\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}");
            C = new(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: Store, localOnly: true);
            C.NativeProducerBook = Host.Snapshot; C.NativeSavedBook = Host.Saved;
            Online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(C)!;
            Online.Add(Peer, f.Native.Connection);
            var receive = Store.ReadNativeMediaReceiveConsent(Peer); Store.ChangeNativeMediaReceiveConsent(Peer, receive.Version, true);
            DeviceFileConnectionRunsTests.Clear(F);
        }
        internal static async Task<Fixture> Create(bool shared = false, bool sourceSend = false)
        {
            var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: sourceSend, sharedMedia: shared);
            try
            {
                if (shared)
                {
                    f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("import_only")!,
                        f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode"));
                    await DeviceFileSharedTransportTests.MatchAsync(f.Native);
                }
                return new(f);
            }
            catch { f.Dispose(); throw; }
        }
        internal string Root(string leaf) { var path = Path.Combine(F.Native.Paths.Root, leaf); Directory.CreateDirectory(path); return path; }
        internal (NativeMediaSelectionWitness Selection, NativeMediaDestinationAdmission Admission) Admit(string path)
        {
            DeviceFileNativeDirectory? held = null;
            var result = C.AdmitNativeMediaDestination(Peer, "images", C.NativeDestinationAdmissionVersion(Peer, "images"), current =>
            { current(); return held = DeviceFileNativeDirectory.OpenExistingForReceive(path); }) ?? throw new Exception("Native admission canceled unexpectedly.");
            TestAssert.Throws<ObjectDisposedException>(() => held!.CurrentIdentity(), "Admitted picked owner survived the native result.");
            return result;
        }
        public void Dispose() { C.Dispose(); F.Dispose(); }
    }
    private static byte[] Row(Fixture f, string version)
    {
        using var db = f.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_destination_admissions WHERE peer_id=$peer AND version=$version";
        read.Parameters.AddWithValue("$peer", f.Peer); read.Parameters.AddWithValue("$version", version); return (byte[])read.ExecuteScalar()!;
    }
    private static void DeleteHead(Fixture f)
    {
        using var db = f.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
        write.CommandText = "DELETE FROM native_media_selection_witnesses WHERE peer_id=$peer"; write.Parameters.AddWithValue("$peer", f.Peer); write.ExecuteNonQuery();
    }

    internal static async Task WindowsNativeAdmissionAsync()
    {
        using var f = await Fixture.Create(shared: true);
        var path = f.Root("actually-picked-root-one");
        var preferences = f.Store.ReadNativeMediaPreferences(f.Peer); var send = f.Store.ReadNativeMediaSendConsent(f.Peer); var receive = f.Store.ReadNativeMediaReceiveConsent(f.Peer);
        var first = f.Admit(path); var row = Row(f, first.Admission.Destination.Version);
        var middle = f.Admit(f.F.Root); var again = f.Admit(path);
        TestAssert.That(first.Selection.NativeAdmission && middle.Selection.NativeAdmission && again.Selection.NativeAdmission &&
            first.Admission == again.Admission && Row(f, first.Admission.Destination.Version).SequenceEqual(row) &&
            first.Selection.Stamp != again.Selection.Stamp && middle.Admission.Destination == f.F.Destination &&
            f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", first.Admission.Destination.Version) == first.Admission &&
            f.Store.ReadNativeMediaDestination(f.Peer, "images") == f.F.Destination && !first.Admission.GrantsReadAuthority && !first.Admission.GrantsReceiveAuthority && !first.Admission.GrantsSendAuthority &&
            f.Store.ReadNativeMediaPreferences(f.Peer) == preferences && f.Store.ReadNativeMediaSendConsent(f.Peer) == send && f.Store.ReadNativeMediaReceiveConsent(f.Peer) == receive &&
            !Directory.EnumerateFileSystemEntries(path).Any() && f.Store.NativeMediaReceiveHistory(f.Peer).Count == 0 && f.Store.NativeMediaSourceHistory(f.Peer).Count == 0 && f.F.Native.Stream.Length == 0,
            "Native admission rotated an original generation, activated a target, granted IO or changed data/policy/history.");
    }

    internal static async Task WindowsHistoricalAdmissionIndependentAsync()
    {
        using var f = await Fixture.Create(); var admitted = f.Admit(f.Root("historical-root-one"));
        var latest = f.Admit(f.F.Root); var row = Row(f, admitted.Admission.Destination.Version);
        DeleteHead(f);
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaSelectionWitness(f.Peer, "images"), "Lost current head was repaired from admission history.");
        TestAssert.That(f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", admitted.Admission.Destination.Version) == admitted.Admission,
            "Original historical admission consulted a missing current head.");
        var dir = Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Single();
        File.WriteAllText(Path.Combine(dir, "unknown-future-intent"), "not current will");
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var fault = db.CreateCommand(); fault.CommandText = "DELETE FROM native_media_destinations WHERE peer_id=$peer AND media_type='images'";
            fault.Parameters.AddWithValue("$peer", f.Peer); fault.ExecuteNonQuery();
        }
        TestAssert.That(f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", admitted.Admission.Destination.Version) == admitted.Admission &&
            Row(f, admitted.Admission.Destination.Version).SequenceEqual(row), "Historical admission depended on legacy0/current inventory or rewrote its original proof.");
        // Removing the original admission file, unlike unrelated current files,
        // must always close the original metadata proof.
        File.Move(Path.Combine(dir, admitted.Admission.AdmissionStamp + ".seal"), Path.Combine(f.F.Native.Paths.Root, "retired-admission.seal"));
        TestAssert.Throws<IOException>(() => f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", admitted.Admission.Destination.Version), "Missing original admission file was replaced by current flags.");
    }

    internal static async Task WindowsAdmissionPickerGuardsAsync()
    {
        foreach (var scenario in new[] { "cancel", "book", "connection", "consent", "stale", "worker", "control" })
        {
            using var f = await Fixture.Create(); var path = f.Root("guarded-native-root"); var version = f.C.NativeDestinationAdmissionVersion(f.Peer, "images");
            var calls = 0; DeviceFileNativeDirectory? held = null; Action? originalContext = null;
            DeviceFileNativeDirectory? Picker(Action current)
            {
                calls++; originalContext = current; current();
                TestAssert.Throws<InvalidDataException>(() => f.C.ChooseNativeMediaCollectionFolder(f.Peer, "images", version, _ => throw new Exception("Competing source dialog opened.")), "Native admission overlapped source choice.");
                var send = f.Store.ReadNativeMediaSendConsent(f.Peer);
                TestAssert.Throws<InvalidDataException>(() => f.C.ConfirmNativeMediaUiSendConsent(f.Peer, send.Version, true, false, () => throw new Exception("Competing SEND dialog opened.")), "Native admission overlapped SEND consent.");
                if (scenario == "cancel") return null;
                if (scenario == "book") typeof(PersonalActorNativeSaveHost).GetProperty("currentPlainTextAvailable", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(f.Host, false);
                if (scenario == "connection") f.Online.Remove(f.Peer);
                if (scenario == "consent") { var receive = f.Store.ReadNativeMediaReceiveConsent(f.Peer); f.Store.ChangeNativeMediaReceiveConsent(f.Peer, receive.Version, false); }
                if (scenario == "worker") typeof(TelefonCoordinator).GetField("nativeMediaWorker", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(f.C, 1);
                if (scenario == "control")
                {
                    var packet = f.F.Phone.Packet(); f.F.Phone.MarkSent(packet);
                    f.F.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(packet, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())).GetAwaiter().GetResult();
                }
                return held = DeviceFileNativeDirectory.OpenExistingForReceive(path);
            }
            if (scenario == "cancel") TestAssert.That(f.C.AdmitNativeMediaDestination(f.Peer, "images", version, Picker) is null, "Canceled native admission produced a generation.");
            else TestAssert.Throws<InvalidDataException>(() => f.C.AdmitNativeMediaDestination(f.Peer, "images", scenario == "stale" ? new string('a', 64) : version, Picker), "Late admission adopted changed original context: " + scenario);
            if (originalContext is not null) TestAssert.Throws<InvalidDataException>(originalContext, "Completed/failed native callback retained a reusable admission context.");
            if (held is not null) TestAssert.Throws<ObjectDisposedException>(() => held.CurrentIdentity(), "Rejected native admission leaked the selected owner.");
            TestAssert.That(calls == (scenario == "stale" ? 0 : 1) && !Directory.EnumerateFileSystemEntries(path).Any() &&
                !Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Any() && f.Store.ReadNativeMediaDestination(f.Peer, "images") == f.F.Destination,
                "Rejected dialog wrote a generation, witness or target metadata.");
        }
    }

    internal static async Task WindowsLostAdmissionNeverRebuiltAsync()
    {
        using var f = await Fixture.Create(); var path = f.Root("lost-admission-root"); var admitted = f.Admit(path);
        var dir = Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Single(); var files = Directory.GetFiles(dir).ToDictionary(p => p, File.ReadAllBytes);
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var fault = db.CreateCommand(); fault.CommandText = "DELETE FROM native_media_destination_admissions WHERE peer_id=$peer";
            fault.Parameters.AddWithValue("$peer", f.Peer); fault.ExecuteNonQuery();
        }
        TestAssert.That(f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", admitted.Admission.Destination.Version) is null, "Admission reader bootstrapped from selection flags.");
        try { f.Admit(path); throw new Exception("Lost immutable admission was silently recreated from historical flags."); }
        catch (InvalidDataException error) { TestAssert.That(error.Message == "file_destination_admission_original_required", "Lost-admission HOLD was unrelated."); }
        TestAssert.That(files.Count == Directory.GetFiles(dir).Length && files.All(item => File.ReadAllBytes(item.Key).SequenceEqual(item.Value)), "Lost admission retry appended/evicted witness files.");
    }

    internal static async Task WindowsIntentIsNotAdmissionAsync()
    {
        using var f = await Fixture.Create(); var path = f.Root("proposal-not-admission");
        NativeMediaSelectionWitness proposed;
        using (var picked = DeviceFileNativeDirectory.OpenExistingForReceive(path))
            proposed = f.Store.RecordNativeMediaSelectionWitness(f.Peer, "images", null, picked, () => { });
        TestAssert.That(!proposed.NativeAdmission && f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", proposed.Destination.Version) is null,
            "Generic metadata intent was resolved as an admitted generation.");
        // Even authenticated CLR/SQL metadata pointing at an actual generic
        // intent must not manufacture the separately native-admitted event role.
        byte[] cipher;
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_selection_witnesses WHERE peer_id=$peer";
            read.Parameters.AddWithValue("$peer", f.Peer); cipher = (byte[])read.ExecuteScalar()!;
        }
        var plain = f.Store.Open("native_media_selection_witness_head", f.Peer + "/images", cipher); JsonObject header;
        try { header = JsonNode.Parse(plain)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(plain); }
        var dir = Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Single();
        plain = f.Store.Open("native_media_selection_witness_event", f.Peer + "/images/" + proposed.Stamp, File.ReadAllBytes(Path.Combine(dir, proposed.Stamp + ".seal")));
        JsonObject value;
        try { value = JsonNode.Parse(plain)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(plain); }
        var fake = new JsonObject { ["format"] = 1, ["scope"] = header["scope"]!.DeepClone(), ["media_type"] = "images", ["version"] = proposed.Destination.Version,
            ["destination"] = value["destination"]!.DeepClone(), ["creation"] = value["creation"]!.DeepClone(), ["directory"] = header["directory"]!.DeepClone(),
            ["event"] = header["events"]![0]!.DeepClone(), ["previous"] = null };
        plain = TelefonCrypto.Canonical(fake);
        try { cipher = f.Store.Seal("native_media_destination_admission", f.Peer + "/images/" + proposed.Destination.Version, plain); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var write = db.CreateCommand(); write.CommandText = "CREATE TABLE native_media_destination_admissions(peer_id TEXT,media_type TEXT,version TEXT,value BLOB,PRIMARY KEY(peer_id,media_type,version)); INSERT INTO native_media_destination_admissions VALUES($peer,'images',$version,$value)";
            write.Parameters.AddWithValue("$peer", f.Peer); write.Parameters.AddWithValue("$version", proposed.Destination.Version); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
        }
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", proposed.Destination.Version), "Forged admission row turned a generic event into actual native admission.");
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var restore = db.CreateCommand(); restore.CommandText = "DELETE FROM native_media_destination_admissions"; restore.ExecuteNonQuery();
        }
        var real = f.Admit(path);
        TestAssert.That(real.Selection.NativeAdmission && real.Admission.Destination == proposed.Destination && real.Admission.AdmissionStamp != proposed.Stamp &&
            f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", proposed.Destination.Version) == real.Admission,
            "Genuine native callback did not create its own independent admitted event.");
    }

    internal static async Task WindowsAdmissionLossAndOtherKindAsync()
    {
        using var f = await Fixture.Create(); var path = f.Root("protected-root-one"); var admitted = f.Admit(path);
        DeleteHead(f);
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var fault = db.CreateCommand(); fault.CommandText = "DELETE FROM native_media_destinations WHERE peer_id=$peer AND media_type='images'";
            fault.Parameters.AddWithValue("$peer", f.Peer); fault.ExecuteNonQuery();
        }
        var dir = Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Single(); Directory.Move(dir, dir + ".retired");
        using var picked = DeviceFileNativeDirectory.OpenExistingForReceive(path);
        try { f.Store.SetNativeMediaDestination(f.Peer, "images", null, picked); throw new Exception("Missing originals were recreated despite an independent admission row."); }
        catch (InvalidDataException error) { TestAssert.That(error.Message == "file_destination_original_record_required", "Admission-only evidence loss held for unrelated reason."); }
        try { f.Store.SetNativeMediaDestination(f.Peer, "video", null, picked); throw new Exception("Lost current witnesses freed a protected historical image root for video."); }
        catch (InvalidDataException error) { TestAssert.That(error.Message == "file_destination_media_roots_overlap", "Admission-only cross-kind overlap held for unrelated reason."); }
        using var distinct = DeviceFileNativeDirectory.OpenExistingForReceive(f.Root("distinct-first-video"));
        var video = f.Store.SetNativeMediaDestination(f.Peer, "video", null, distinct);
        TestAssert.That(!video.GrantsReceiveAuthority && f.Store.ReadNativeMediaDestination(f.Peer, "images") is null &&
            !Directory.EnumerateFileSystemEntries(path).Any() && f.Store.NativeMediaReceiveHistory(f.Peer).Count == 0 &&
            Row(f, admitted.Admission.Destination.Version).Length > 29, "Loss/overlap guards repaired metadata, blocked a distinct first kind or granted receiving.");
    }

    internal static async Task WindowsAdmissionOriginalGuardsAsync()
    {
        foreach (var scenario in new[] { "future", "descriptor", "bytes", "file-id", "missing-key" })
        {
            using var f = await Fixture.Create(); var admitted = f.Admit(f.Root("admitted-guard-root")); var version = admitted.Admission.Destination.Version;
            var row = Row(f, version); var dir = Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Single();
            var file = Path.Combine(dir, admitted.Admission.AdmissionStamp + ".seal"); var bytes = File.ReadAllBytes(file);
            if (scenario is "future" or "descriptor")
            {
                var plain = f.Store.Open("native_media_destination_admission", f.Peer + "/images/" + version, row); JsonObject body;
                try { body = JsonNode.Parse(plain)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(plain); }
                if (scenario == "future") body["future_field"] = true;
                else body["destination"]!["destination_token"] = new string('a', 64);
                plain = TelefonCrypto.Canonical(body);
                try { row = f.Store.Seal("native_media_destination_admission", f.Peer + "/images/" + version, plain); }
                finally { CryptographicOperations.ZeroMemory(plain); }
                using var db = f.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
                write.CommandText = "UPDATE native_media_destination_admissions SET value=$value WHERE peer_id=$peer AND version=$version";
                write.Parameters.AddWithValue("$value", row); write.Parameters.AddWithValue("$peer", f.Peer); write.Parameters.AddWithValue("$version", version); write.ExecuteNonQuery();
            }
            if (scenario == "bytes") { bytes[^1] ^= 1; File.WriteAllBytes(file, bytes); }
            if (scenario == "file-id") { File.Move(file, file + ".original"); File.WriteAllBytes(file, bytes); }
            if (scenario == "missing-key") File.Delete(f.F.Native.Paths.TelefonStorageKey);
            TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", version), "Original admission accepted changed proof: " + scenario);
            TestAssert.That(Row(f, version).SequenceEqual(row) && (scenario != "missing-key" || !File.Exists(f.F.Native.Paths.TelefonStorageKey)) &&
                f.Store.ReadNativeMediaDestination(f.Peer, "images") == f.F.Destination, "Admission failure repaired a record/key or activated a target.");
        }
    }

    internal static async Task WindowsAdmissionOriginalDeadlineAsync()
    {
        using var f = await Fixture.Create(); var path = f.Root("late-admission-root"); DeviceFileNativeDirectory? held = null;
        TestAssert.Throws<InvalidDataException>(() => f.C.AdmitNativeMediaDestination(f.Peer, "images", f.C.NativeDestinationAdmissionVersion(f.Peer, "images"), current => {
            current(); Thread.Sleep(TimeSpan.FromSeconds(61)); return held = DeviceFileNativeDirectory.OpenExistingForReceive(path);
        }), "Native generation admission reset the original 60 second deadline after the picker.");
        TestAssert.Throws<ObjectDisposedException>(() => held!.CurrentIdentity(), "Late picked native owner was not disposed.");
        TestAssert.That(!Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Any() && !Directory.EnumerateFileSystemEntries(path).Any() &&
            f.Store.ReadNativeMediaDestination(f.Peer, "images") == f.F.Destination, "Late native admission wrote metadata or data.");
    }

    internal static async Task WindowsAdmissionSqlAtomicityAsync()
    {
        using var f = await Fixture.Create(); var path = f.Root("admission-sql-failure");
        using (var original = f.F.Destination.OpenNative())
            _ = f.Store.RecordNativeMediaSelectionWitness(f.Peer, "images", null, original, () => { });
        byte[] old;
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_selection_witnesses WHERE peer_id=$peer";
            read.Parameters.AddWithValue("$peer", f.Peer); old = (byte[])read.ExecuteScalar()!;
            // Isolated persistence-failure fixture, not a valid schema/migration:
            // the real admission INSERT must fail AFTER the pending head write.
            using var fault = db.CreateCommand(); fault.CommandText = "CREATE TABLE native_media_destination_admissions(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,version TEXT NOT NULL,value BLOB NOT NULL CHECK(value IS NULL),PRIMARY KEY(peer_id,media_type,version))";
            fault.ExecuteNonQuery();
        }
        try { f.Admit(path); throw new Exception("Admission persistence failure was ignored."); }
        catch (Microsoft.Data.Sqlite.SqliteException error) when (error.SqliteErrorCode == 19) { }
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_selection_witnesses WHERE peer_id=$peer";
            read.Parameters.AddWithValue("$peer", f.Peer);
            TestAssert.That(((byte[])read.ExecuteScalar()!).SequenceEqual(old), "Failed actual admission committed its pending new head.");
            using var count = db.CreateCommand(); count.CommandText = "SELECT COUNT(*) FROM native_media_destination_admissions";
            TestAssert.That(Convert.ToInt64(count.ExecuteScalar()) == 0, "Failed actual admission left a partial generation row.");
        }
        var dir = Directory.GetDirectories(f.F.Native.Paths.Telefon, ".magnolie-selection-*").Single();
        TestAssert.That(Directory.GetFiles(dir).Length == 2 && Directory.GetFiles(dir).All(p => new FileInfo(p).Length > 29) &&
            f.Store.ReadNativeMediaDestination(f.Peer, "images") == f.F.Destination && !Directory.EnumerateFileSystemEntries(path).Any(),
            "Failed admission erased its independently flushed native intent or changed media/legacy data.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaSelectionWitness(f.Peer, "images"), "SQL rollback adopted its uncommitted admission file as current.");
    }

    internal static async Task WindowsOriginalJobUsesIndependentAdmissionAsync()
    {
        using var f = await Fixture.Create(sourceSend: true);
        var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aX0AAAAASUVORK5CYII=");
        await DeviceFileBackupCatalogTests.Seed(f.F, png);
        var job = f.Store.NativeMediaReceiveHistory(f.Peer).Single(); var admission = f.Admit(f.F.Root).Admission;
        DeleteHead(f);
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var fault = db.CreateCommand(); fault.CommandText = "DELETE FROM native_media_destinations WHERE peer_id=$peer AND media_type='images'";
            fault.Parameters.AddWithValue("$peer", f.Peer); fault.ExecuteNonQuery();
        }
        var book = NativeMediaBookPermit.Capture(f.Host.Snapshot()!, f.Host.Saved);
        bool Current() { book.Require(); return true; }
        var backup = DeviceFileBackupCatalogTests.Save(f.F, permit: Current);
        var entry = f.Store.TrashNativeMediaSavedFile(f.Peer, job.JobId, job.Version, 1.ToString("x32"), Current);
        var rendered = 0;
        _ = f.Store.PreviewNativeMediaTrash(f.Peer, entry, Current, 192, (bytes, kind, side, current) => {
            current(); rendered++; TestAssert.That(bytes.SequenceEqual(png) && kind == "images", "Independent original job preview read other bytes.");
            return new("image/png", 1, 1, Convert.ToBase64String(png));
        });
        var restored = f.Store.RestoreNativeMediaTrash(f.Peer, entry, Current);
        var dir = Path.Combine(f.F.Root, new NativeMediaAlbumContext(new string('e', 64), "Kamera").Folder);
        TestAssert.That(rendered == 1 && restored.State == "restored" && File.ReadAllBytes(Path.Combine(dir, "first.jpg")).SequenceEqual(png) &&
            f.Store.NativeMediaReceiveHistory(f.Peer).Single() == job && f.Store.ReadNativeMediaDestination(f.Peer, "images") is null &&
            f.Store.ReadNativeMediaDestinationAdmission(f.Peer, "images", f.F.Destination.Version) == admission &&
            f.Store.NativeMediaBackupVersions(f.F.Destination, Current).Contains(backup),
            "Actual original-job IO required a current/legacy record, repaired metadata or lost history/raw bytes.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaSelectionWitness(f.Peer, "images"), "Independent job IO repaired a missing current head.");
    }
}
