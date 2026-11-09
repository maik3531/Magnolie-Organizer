using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileDestinationSelectionTests
{
    private static byte[] WitnessRow(DeviceFileReceiveJobTests.Fixture f)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_selection_witnesses WHERE peer_id=$peer AND media_type='images'";
        read.Parameters.AddWithValue("$peer", f.Native.Peer.Id); return (byte[])read.ExecuteScalar()!;
    }
    private static void PutWitnessRow(DeviceFileReceiveJobTests.Fixture f, byte[]? value)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
        write.CommandText = value is null ? "DELETE FROM native_media_selection_witnesses WHERE peer_id=$peer AND media_type='images'" :
            "INSERT INTO native_media_selection_witnesses(peer_id,media_type,value) VALUES($peer,'images',$value) ON CONFLICT(peer_id,media_type) DO UPDATE SET value=excluded.value";
        write.Parameters.AddWithValue("$peer", f.Native.Peer.Id);
        if (value is not null) write.Parameters.AddWithValue("$value", value);
        write.ExecuteNonQuery();
    }
    private static string WitnessDirectory(DeviceFileReceiveJobTests.Fixture f) => Directory.GetDirectories(f.Native.Paths.Telefon, ".magnolie-selection-*").Single();

    internal static async Task WindowsWitnessChoiceCycleAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false);
        TestAssert.That(f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images") is null &&
            !Directory.GetDirectories(f.Native.Paths.Telefon, ".magnolie-selection-*").Any(), "Reading an absent witness created metadata.");
        var preferences = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        var receive = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id); var send = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
        var candidate = Path.Combine(f.Native.Paths.Root, "witness-choice-root"); Directory.CreateDirectory(candidate);
        using var original = f.Destination.OpenNative(); using var picked = DeviceFileNativeDirectory.OpenExistingForReceive(candidate);
        var first = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => { });
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, picked, () => { }),
            "Stale selection stamp reached a new journal intent.");
        var second = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", first.Stamp, picked, () => { });
        var third = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", second.Stamp, original, () => { });
        TestAssert.That(new[] { first.Stamp, second.Stamp, third.Stamp }.Distinct().Count() == 3 && first.Destination == f.Destination && third.Destination == f.Destination &&
            second.Destination.RootIdentity == picked.CurrentIdentity() && second.Destination.Version != f.Destination.Version &&
            f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images") == third && third.Count == 3 && !third.GrantsReceiveAuthority && !third.GrantsSendAuthority &&
            f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination &&
            f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id) == preferences && f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id) == receive &&
            f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id) == send && !Directory.EnumerateFileSystemEntries(candidate).Any() &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0,
            "Witness cycle rotated the original root token, activated intent or changed consent/data/history.");
        var reopened = new TelefonStore(f.Native.Paths);
        TestAssert.That(reopened.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images") == third, "New store lost the exact independent native witness.");
    }

    internal static async Task WindowsWitnessHeadRollbackAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false);
        using var original = f.Destination.OpenNative();
        var first = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => { }); var old = WitnessRow(f);
        var second = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", first.Stamp, original, () => { }); var latest = WitnessRow(f);
        var files = Directory.GetFiles(WitnessDirectory(f)).ToDictionary(path => path, File.ReadAllBytes);
        foreach (var rollback in new byte[]?[] { old, null })
        {
            PutWitnessRow(f, rollback);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images"), "Old or missing SQL head adopted a highest native event.");
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => { }), "Uncertain head was reconstructed as first selection.");
            if (rollback is not null) TestAssert.That(WitnessRow(f).SequenceEqual(old), "A witness read repaired an old SQL head.");
            PutWitnessRow(f, latest);
            TestAssert.That(f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images") == second, "Restoring exact fixture metadata changed its witness.");
        }
        TestAssert.That(files.All(item => File.ReadAllBytes(item.Key).SequenceEqual(item.Value)) && Directory.GetFiles(WitnessDirectory(f)).Length == files.Count,
            "Rollback rejection deleted/rewrote independently retained commit files.");
    }

    internal static async Task WindowsWitnessPartialCommitAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false); using var original = f.Destination.OpenNative();
        var observed = false;
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => {
            if (Directory.GetDirectories(f.Native.Paths.Telefon, ".magnolie-selection-*").Any() && Directory.GetFiles(WitnessDirectory(f)).Length != 0)
            { observed = true; throw new InvalidDataException("test_original_context_retired"); }
        }), "Native context withdrawal committed a partial intent.");
        var file = Directory.GetFiles(WitnessDirectory(f)).Single(); var bytes = File.ReadAllBytes(file);
        TestAssert.That(observed, "Failure did not reach the native independent file phase.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images"), "Orphan native intent became an active head.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => { }), "Retry repaired/replayed an uncommitted native intent.");
        TestAssert.That(File.ReadAllBytes(file).SequenceEqual(bytes) && f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination,
            "Partial intent HOLD cleaned metadata or replaced the legacy target.");
    }

    internal static async Task WindowsWitnessSqlRollbackAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false); using var original = f.Destination.OpenNative();
        // Observe a real uncommitted SQLite write, not a guessed callback count.
        // This isolated fixture uses DELETE journalling so the actual rollback
        // journal exists only after the new table/head have been written.
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var mode = db.CreateCommand(); mode.CommandTimeout = 3; mode.CommandText = "PRAGMA journal_mode=DELETE";
            TestAssert.That(mode.ExecuteScalar()?.ToString() == "delete", "SQL rollback fixture did not establish its observable transaction mode.");
        }
        var journal = f.Native.Paths.TelefonDatabase + "-journal"; var observed = false;
        TestAssert.That(!File.Exists(journal), "SQL rollback fixture already had an unrelated transaction.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => {
            if (File.Exists(journal)) { observed = true; throw new InvalidDataException("test_original_context_retired_after_sql_write"); }
        }), "Post-SQL context withdrawal committed a selection head.");
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='native_media_selection_witnesses'";
            TestAssert.That(observed && Convert.ToInt64(read.ExecuteScalar()) == 0 && !File.Exists(journal),
                "Actual SQL table/head write was not rolled back after original-context rejection.");
        }
        var file = Directory.GetFiles(WitnessDirectory(f)).Single(); var bytes = File.ReadAllBytes(file);
        TestAssert.That(bytes.Length > 29, "Post-SQL rejection did not retain its already flushed independent ciphertext.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images"), "SQL rollback adopted its independently retained intent as current.");
        TestAssert.That(File.ReadAllBytes(file).SequenceEqual(bytes) && f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination,
            "SQL rollback HOLD cleaned witness bytes or replaced original metadata.");
    }

    internal static async Task WindowsWitnessNativeGuardsAsync()
    {
        foreach (var scenario in new[] { "bytes", "file-id", "directory-id", "unknown-file", "missing-key" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false); using var original = f.Destination.OpenNative();
            _ = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => { });
            var directory = WitnessDirectory(f); var file = Directory.GetFiles(directory).Single(); var bytes = File.ReadAllBytes(file); var row = WitnessRow(f);
            if (scenario == "bytes") { bytes[bytes.Length / 2] ^= 1; File.WriteAllBytes(file, bytes); }
            if (scenario == "file-id") { File.Move(file, file + ".original"); File.WriteAllBytes(file, bytes); File.Move(file + ".original", Path.Combine(f.Native.Paths.Root, "retired-witness.seal")); }
            if (scenario == "directory-id")
            {
                Directory.Move(directory, directory + ".original"); Directory.CreateDirectory(directory); File.WriteAllBytes(file, bytes);
            }
            if (scenario == "unknown-file") File.WriteAllText(Path.Combine(directory, "unknown.seal"), "must remain unknown");
            if (scenario == "missing-key") File.Delete(f.Native.Paths.TelefonStorageKey);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images"), "Native witness changed without HOLD: " + scenario);
            TestAssert.That(WitnessRow(f).SequenceEqual(row) && (scenario != "missing-key" || !File.Exists(f.Native.Paths.TelefonStorageKey)) &&
                f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination, "Witness guard repaired metadata/key or activated intent.");
        }
    }

    internal static async Task WindowsWitnessCapacityAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false); using var original = f.Destination.OpenNative();
        NativeMediaSelectionWitness? head = null;
        for (var index = 0; index < 32; index++) head = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", head?.Stamp, original, () => { });
        var row = WitnessRow(f); var files = Directory.GetFiles(WitnessDirectory(f)).ToDictionary(path => path, File.ReadAllBytes);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", head!.Stamp, original, () => { }),
            "Full witness window evicted history or grew beyond its bound.");
        TestAssert.That(head!.Count == 32 && f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images") == head && WitnessRow(f).SequenceEqual(row) &&
            files.Count == 32 && Directory.GetFiles(WitnessDirectory(f)).Length == 32 && files.All(item => File.ReadAllBytes(item.Key).SequenceEqual(item.Value)),
            "Capacity HOLD deleted old independent witnesses or changed the SQL head.");
    }

    internal static async Task WindowsWitnessOtherKindAsync()
    {
        foreach (var scenario in new[] { "legacy", "witness", "staged", "received" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: scenario == "received");
            if (scenario == "received") await DeviceFileReconcileTests.Establish(f);
            var path = Path.Combine(f.Native.Paths.Root, "video-metadata-root"); Directory.CreateDirectory(path);
            using var video = DeviceFileNativeDirectory.OpenExistingForReceive(path);
            var destination = f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, video);
            var candidatePath = Path.Combine(f.Native.Paths.Root, "opposite-intent-root"); Directory.CreateDirectory(candidatePath);
            using var candidate = DeviceFileNativeDirectory.OpenExistingForReceive(candidatePath);
            if (scenario == "witness") _ = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "video", null, candidate, () => { });
            if (scenario == "staged") _ = f.Native.Store.StageNativeMediaDestinationChoice(f.Native.Peer.Id, "video", destination.Version,
                f.Native.Store.ReadNativeMediaDestinationChoices(f.Native.Peer.Id, "video"), candidate, () => { });
            if (scenario == "received")
            {
                using var db = f.Native.Store.OpenDatabase(); db.Open(); using var fault = db.CreateCommand();
                fault.CommandText = "DELETE FROM native_media_destinations WHERE peer_id=$peer AND media_type='images'";
                fault.Parameters.AddWithValue("$peer", f.Native.Peer.Id); fault.ExecuteNonQuery();
            }
            var kind = scenario == "received" ? "video" : "images";
            using var original = f.Destination.OpenNative();
            var chosen = scenario == "received" ? original : scenario == "legacy" ? video : candidate;
            try
            {
                f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, kind, null, chosen, () => { });
                throw new Exception("Opposite media root became a selected intent: " + scenario);
            }
            catch (InvalidDataException error)
            { TestAssert.That(error.Message == "file_destination_media_roots_overlap", "Other-kind guard held for unrelated reason: " + error.Message); }
            TestAssert.That(f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, kind) is null &&
                f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "video") == destination &&
                !Directory.EnumerateFileSystemEntries(candidatePath).Any() && !Directory.EnumerateFileSystemEntries(path).Any(),
                "Other-kind rejection created/adopted a witness or modified user roots.");
        }
    }

    internal static async Task WindowsWitnessMetadataGuardsAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false); using var original = f.Destination.OpenNative();
        var first = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", null, original, () => { });
        var second = f.Native.Store.RecordNativeMediaSelectionWitness(f.Native.Peer.Id, "images", first.Stamp, original, () => { }); var row = WitnessRow(f);
        var plain = f.Native.Store.Open("native_media_selection_witness_head", f.Native.Peer.Id + "/images", row);
        JsonObject body;
        try { body = JsonNode.Parse(plain)!.AsObject(); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        foreach (var scenario in new[] { "future", "old-head", "duplicate", "scope", "original", "count" })
        {
            var next = body.DeepClone().AsObject();
            if (scenario == "future") next["future_field"] = true;
            if (scenario == "old-head") next["head"] = first.Stamp;
            if (scenario == "duplicate") next["events"]!.AsArray().Add(next["events"]![0]!.DeepClone());
            if (scenario == "scope") next["scope"] = new string('a', 64);
            if (scenario == "original") next["original"]!["destination_token"] = new string('b', 64);
            if (scenario == "count") while (next["events"]!.AsArray().Count < 33) next["events"]!.AsArray().Add(next["events"]![0]!.DeepClone());
            var bytes = TelefonCrypto.Canonical(next); byte[] encrypted;
            try { encrypted = f.Native.Store.Seal("native_media_selection_witness_head", f.Native.Peer.Id + "/images", bytes); }
            finally { CryptographicOperations.ZeroMemory(bytes); }
            PutWitnessRow(f, encrypted);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images"), "Ambiguous authenticated metadata did not HOLD: " + scenario);
            TestAssert.That(WitnessRow(f).SequenceEqual(encrypted), "A metadata read normalized unknown/invalid witness bytes.");
            PutWitnessRow(f, row);
        }
        TestAssert.That(f.Native.Store.ReadNativeMediaSelectionWitness(f.Native.Peer.Id, "images") == second, "Negative proposals changed the original witness.");
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var fault = db.CreateCommand(); fault.CommandText = "DELETE FROM native_media_destinations WHERE peer_id=$peer AND media_type='images'";
            fault.Parameters.AddWithValue("$peer", f.Native.Peer.Id); fault.ExecuteNonQuery();
        }
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "images", null, original), "Known selection witness reconstructed a lost legacy original.");
        TestAssert.That(f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") is null && WitnessRow(f).SequenceEqual(row), "Loss HOLD repaired the original or rewrote independent metadata.");
        PutWitnessRow(f, null);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "images", null, original), "Orphan independent directory was treated as a first legacy choice.");
    }

    // Architectural counterproof, not a claim that backup history is a current
    // selection owner, and not a simulated legitimate target migration.
    internal static async Task WindowsBackupAnchorIsNotCurrentSelectionAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        await DeviceFileReconcileTests.Establish(f);
        var first = DeviceFileBackupCatalogTests.Save(f);
        byte[] Anchor()
        {
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT value FROM native_media_backup_anchors";
            return (byte[])read.ExecuteScalar()!;
        }
        void PutAnchor(byte[] value)
        {
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
            write.CommandText = "UPDATE native_media_backup_anchors SET value=$value";
            write.Parameters.AddWithValue("$value", value);
            TestAssert.That(write.ExecuteNonQuery() == 1, "Counterproof did not isolate one original backup anchor.");
        }
        var oldAnchor = Anchor();
        var second = DeviceFileBackupCatalogTests.Save(f, "00000000000000000000000000000002");
        var latestAnchor = Anchor();
        TestAssert.That(!oldAnchor.SequenceEqual(latestAnchor) && first != second &&
            f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 2,
            "Counterproof did not establish two actual backup catalog revisions.");
        var folder = Path.Combine(f.Root, "Backup");
        var files = Directory.GetFiles(folder).ToDictionary(path => path, path => SHA256.HashData(File.ReadAllBytes(path)));
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        try
        {
            PutAnchor(oldAnchor); // Fault injection only; NOT a user selection.
            var oldView = f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true);
            TestAssert.That(oldView.Count == 1 && oldView.Single() == first && Anchor().SequenceEqual(oldAnchor),
                "Retained snapshot behavior changed; reassess current-head counterproof before using it.");
        }
        finally { PutAnchor(latestAnchor); }
        TestAssert.That(f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 2 &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            Directory.GetFiles(folder).Length == files.Count && files.All(item => File.Exists(item.Key) &&
                SHA256.HashData(File.ReadAllBytes(item.Key)).SequenceEqual(item.Value)),
            "Read-only counterproof changed raw bytes, native snapshots or completed receive history.");
    }
}
