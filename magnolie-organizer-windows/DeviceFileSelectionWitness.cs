using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

// Metadata protocol only. No current destination getter, UI or data operation
// consumes this witness until admission and live-owner invalidation are joined.
internal sealed record NativeMediaSelectionWitness(string Stamp, NativeMediaDestination Destination, ulong CreationFileTime, int Count)
{
    internal bool GrantsReceiveAuthority => false;
    internal bool GrantsSendAuthority => false;
}

internal sealed partial class TelefonStore
{
    private const int SelectionWitnessLimit = 32, SelectionWitnessRowLimit = 128 * 1024, SelectionWitnessFileLimit = 256 * 1024;
    private sealed record SelectionWitnessState(JsonObject Body, IReadOnlyList<NativeMediaSelectionWitness> Events)
    { internal NativeMediaSelectionWitness Head => Events[^1]; }

    private static string SelectionScope(NativeMediaPreferenceScope scope) => DeviceFileControl.Digest("magnolie-selection-witness-scope-v1\0", new JsonObject {
        ["peer"] = scope.PeerId, ["key"] = scope.PeerKey, ["epoch"] = scope.PairingEpoch, ["local"] = scope.LocalId, ["local_key"] = scope.LocalKey });
    private static ulong SelectionHex(JsonNode? value)
    {
        var text = value?.GetValue<string>() ?? "";
        if (text.Length != 16 || text.Any(c => !char.IsAsciiHexDigitLower(c)) ||
            !ulong.TryParse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var number) || number == 0)
            throw DeviceFileControl.Error("file_selection_witness_invalid");
        return number;
    }
    private static string SelectionHex(ulong value) => value.ToString("x16", CultureInfo.InvariantCulture);
    private string SelectionDirectory(NativeMediaPreferenceScope scope, string kind)
        => Path.Combine(paths.Telefon, ".magnolie-selection-" + SelectionScope(scope) + "-" + kind);
    private static DeviceFileNativeDirectory? OpenSelectionDirectory(string path)
    {
        try { return DeviceFileNativeDirectory.OpenExistingForReceive(path); }
        catch (IOException error) when (error.InnerException is System.ComponentModel.Win32Exception { NativeErrorCode: 2 or 3 }) { return null; }
    }
    private JsonObject? ReadSelectionWitnessBody(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope, string kind)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_selection_witnesses'";
        if (exists.ExecuteScalar() is null) return null;
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT value FROM native_media_selection_witnesses WHERE peer_id=$peer AND media_type=$kind";
        read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$kind", kind);
        var stored = read.ExecuteScalar();
        if (stored is null) return null;
        if (stored is not byte[] cipher) throw DeviceFileControl.Error("file_selection_witness_invalid");
        if (cipher.Length > SelectionWitnessRowLimit + 28) throw DeviceFileControl.Error("file_selection_witness_invalid");
        var plain = Open("native_media_selection_witness_head", scope.PeerId + "/" + kind, cipher);
        try { return JsonNode.Parse(plain) as JsonObject ?? throw DeviceFileControl.Error("file_selection_witness_invalid"); }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private SelectionWitnessState? ReadSelectionWitness(SqliteConnection db, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope, string kind, Action current)
    {
        current(); var body = ReadSelectionWitnessBody(db, transaction, scope, kind);
        using var directory = OpenSelectionDirectory(SelectionDirectory(scope, kind));
        if (body is null)
        {
            if (directory is not null) throw DeviceFileControl.Error("file_selection_witness_head_required");
            return null;
        }
        if (directory is null) throw DeviceFileControl.Error("file_selection_witness_directory_required");
        var legacy = ReadLegacyNativeMediaDestination(db, transaction, scope, kind)
            ?? throw DeviceFileControl.Error("file_destination_original_record_required");
        TelefonProtocolContract.ExactObject(body, "format", "scope", "media_type", "original", "directory", "head", "events");
        if (TelefonProtocolContract.Integer(body["format"]) != 1 || body["scope"]?.GetValue<string>() != SelectionScope(scope) ||
            body["media_type"]?.GetValue<string>() != kind || !JsonNode.DeepEquals(body["original"], NativeMediaDestinationValue(scope, legacy)) ||
            body["directory"] is not JsonObject descriptor || body["events"] is not JsonArray entries || entries.Count is < 1 or > SelectionWitnessLimit)
            throw DeviceFileControl.Error("file_selection_witness_invalid");
        TelefonProtocolContract.ExactObject(descriptor, "native_path", "volume_path", "identity", "creation");
        void DirectoryCurrent()
        {
            current();
            if (directory.NativePath != descriptor["native_path"]?.GetValue<string>() || directory.VolumePath != descriptor["volume_path"]?.GetValue<string>() ||
                directory.CurrentReceiveIdentity() != NativeMediaReceiveJob.NativeAlbumIdentity(descriptor["identity"]!.AsObject()) ||
                directory.CurrentReceiveCreationFileTime() != SelectionHex(descriptor["creation"]))
                throw DeviceFileControl.Error("file_selection_witness_directory_changed");
        }
        DirectoryCurrent();
        var inventory = directory.NativeMetadataFiles(DirectoryCurrent, SelectionWitnessLimit);
        if (inventory.Count != entries.Count) throw DeviceFileControl.Error("file_selection_witness_inventory_changed");
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var held = new List<DeviceFileNativeDirectory.DeviceFileNativeStagedFile>();
        var events = new List<NativeMediaSelectionWitness>(); string? previous = null;
        try
        {
            foreach (var node in entries)
            {
                DirectoryCurrent(); var entry = node!.AsObject();
                TelefonProtocolContract.ExactObject(entry, "stamp", "identity", "size", "sha256", "creation");
                var stamp = entry["stamp"]!.GetValue<string>(); var sha = entry["sha256"]!.GetValue<string>();
                var size = TelefonProtocolContract.Integer(entry["size"]); var name = stamp + ".seal";
                if (!DeviceFileControl.Hash(stamp) || !DeviceFileControl.Hash(sha) || !names.Add(name) || size is < 29 or > SelectionWitnessFileLimit)
                    throw DeviceFileControl.Error("file_selection_witness_invalid");
                var identity = NativeMediaReceiveJob.NativeAlbumIdentity(entry["identity"]!.AsObject());
                var observed = inventory.SingleOrDefault(item => item.Name == name);
                if (observed is null || observed.Identity != identity || observed.Size != size || observed.CreationFileTime != SelectionHex(entry["creation"]))
                    throw DeviceFileControl.Error("file_selection_witness_inventory_changed");
                var file = directory.OpenOriginalStagedFile(name, identity, size, sha); held.Add(file);
                if (file.CurrentCreationFileTime() != observed.CreationFileTime) throw DeviceFileControl.Error("file_selection_witness_changed");
                var verified = NativeMediaBackupBytes.Verify(file, size, sha, DirectoryCurrent);
                if (verified.Identity != identity) throw DeviceFileControl.Error("file_selection_witness_changed");
                var bytes = new byte[checked((int)size)];
                try
                {
                    for (var at = 0; at < bytes.Length;)
                    {
                        DirectoryCurrent(); var chunk = file.ReadExact(at, Math.Min(DeviceFileManifest.ChunkBytes, bytes.Length - at));
                        try { chunk.CopyTo(bytes, at); at += chunk.Length; }
                        finally { CryptographicOperations.ZeroMemory(chunk); }
                    }
                    var plain = Open("native_media_selection_witness_event", scope.PeerId + "/" + kind + "/" + stamp, bytes);
                    try
                    {
                        var value = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "media_type", "stamp", "previous", "destination", "creation");
                        if (TelefonProtocolContract.Integer(value["format"]) != 1 || value["scope"]?.GetValue<string>() != SelectionScope(scope) ||
                            value["media_type"]?.GetValue<string>() != kind || value["stamp"]?.GetValue<string>() != stamp ||
                            value["previous"]?.GetValue<string>() != previous)
                            throw DeviceFileControl.Error("file_selection_witness_invalid");
                        var destination = ParseNativeMediaDestination(value["destination"]!.AsObject(), scope, kind);
                        var creation = SelectionHex(value["creation"]);
                        events.Add(new(stamp, destination, creation, events.Count + 1)); previous = stamp;
                    }
                    finally { CryptographicOperations.ZeroMemory(plain); }
                }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            // Validate the explicit authenticated head; NEVER select a directory's
            // highest entry or repair an old/missing head from the inventory.
            if (body["head"]?.GetValue<string>() != previous) throw DeviceFileControl.Error("file_selection_witness_head_changed");
            var after = directory.NativeMetadataFiles(DirectoryCurrent, SelectionWitnessLimit);
            if (!inventory.OrderBy(item => item.Name, StringComparer.Ordinal).SequenceEqual(after.OrderBy(item => item.Name, StringComparer.Ordinal)))
                throw DeviceFileControl.Error("file_selection_witness_inventory_changed");
            DirectoryCurrent(); return new(body, events.AsReadOnly());
        }
        finally { foreach (var file in held) file.Dispose(); }
    }

    internal NativeMediaSelectionWitness? ReadNativeMediaSelectionWitness(string peerId, string kind)
    {
        MediaDestinationKind(kind);
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            void Current()
            {
                RequireNativeMediaStorageKey();
                if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_selection_witness_scope_changed");
            }
            using var db = OpenNativeMediaDatabase(); db.Open();
            return ReadSelectionWitness(db, null, scope, kind, Current)?.Head;
        }
    }

    // A deny-only metadata epoch fence, not a live file/IO/control authority.
    // Require performs protected store/native IO: NEVER call it from a control
    // Scope callback. A writer must separately CAS its original head/readset;
    // recursively observing its own pending journal would correctly HOLD.
    internal sealed class NativeMediaSelectionContextOwner
    {
        private readonly TelefonStore store;
        private readonly string peerId, kind;
        private readonly NativeMediaPreferenceScope scope;
        private readonly NativeMediaDestination? original;
        private bool revoked;
        internal NativeMediaSelectionWitness? Snapshot { get; }
        internal bool GrantsReadAuthority => false;
        internal bool GrantsReceiveAuthority => false;
        internal bool GrantsSendAuthority => false;

        internal NativeMediaSelectionContextOwner(TelefonStore store, string peerId, string kind)
        {
            this.store = store; this.peerId = peerId; this.kind = kind; MediaDestinationKind(kind);
            lock (store.gate)
            {
                store.RequireNativeMediaStorageKey(); scope = store.MediaPreferenceScope(peerId);
                original = store.ReadOriginalLegacyDestination(peerId, kind);
                Snapshot = store.ReadNativeMediaSelectionWitness(peerId, kind);
                Require();
            }
        }

        internal void Require()
        {
            lock (store.gate)
            {
                try
                {
                    if (revoked) throw DeviceFileControl.Error("file_selection_original_context_retired");
                    store.RequireNativeMediaStorageKey();
                    if (store.MediaPreferenceScope(peerId) != scope || store.ReadOriginalLegacyDestination(peerId, kind) != original ||
                        store.ReadNativeMediaSelectionWitness(peerId, kind) != Snapshot)
                        throw DeviceFileControl.Error("file_selection_original_context_retired");
                }
                catch { revoked = true; throw; }
            }
        }
    }

    // Only a native caller can supply this exact picked directory and original
    // deny-only callback. This records a witnessed intent, NOT an active target
    // or an admitted historical generation. Current runtime readers are unchanged.
    internal NativeMediaSelectionWitness RecordNativeMediaSelectionWitness(string peerId, string kind, string? expectedStamp,
        DeviceFileNativeDirectory picked, Action nativeContext)
    {
        ArgumentNullException.ThrowIfNull(nativeContext); MediaDestinationKind(kind);
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId); var revoked = false;
            var root = picked.CurrentReceiveIdentity(); var creation = picked.CurrentReceiveCreationFileTime();
            void Current()
            {
                try
                {
                    if (revoked) throw DeviceFileControl.Error("file_selection_witness_context_changed");
                    nativeContext(); RequireNativeMediaStorageKey();
                    if (MediaPreferenceScope(peerId) != scope || picked.CurrentReceiveIdentity() != root || picked.CurrentReceiveCreationFileTime() != creation)
                        throw DeviceFileControl.Error("file_selection_witness_context_changed");
                }
                catch { revoked = true; throw; }
            }
            Current(); NativeMediaBackupExclusions.RequireMediaDirectory(picked);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var legacy = ReadLegacyNativeMediaDestination(db, null, scope, kind)
                ?? throw DeviceFileControl.Error("file_destination_original_record_required");
            var before = ReadSelectionWitness(db, null, scope, kind, Current);
            if (before?.Head.Stamp != expectedStamp) throw DeviceFileControl.Error("file_selection_witness_stale_choice");
            if (before?.Events.Count >= SelectionWitnessLimit) throw DeviceFileControl.Error("file_selection_witness_capacity");
            var otherKind = kind == "images" ? "video" : "images";
            var other = ReadLegacyNativeMediaDestination(db, null, scope, otherKind);
            var otherWitness = ReadSelectionWitness(db, null, scope, otherKind, Current);
            static bool Overlap(DeviceFileNativeDirectory selected, NativeMediaDestination candidate) => selected.OriginalIdentity == candidate.RootIdentity ||
                selected.VolumePath.Equals(candidate.VolumePath, StringComparison.OrdinalIgnoreCase) ||
                selected.VolumePath.StartsWith(candidate.VolumePath.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) ||
                candidate.VolumePath.StartsWith(selected.VolumePath.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
            if (other is not null && Overlap(picked, other) || otherWitness?.Events.Any(item => Overlap(picked, item.Destination)) == true)
                throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            if (ReadNativeMediaDestinationChoices(db, null, scope, otherKind).Any(item => Overlap(picked, item.Destination)))
                throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            foreach (var history in ReceiveHeads(db, null, scope).Where(head => TelefonMessagingContract.String(head.Body, "media_type") == otherKind))
            {
                var destination = history.Body["destination"]!.AsObject(); var volumePath = TelefonMessagingContract.String(destination, "volume_path");
                if (NativeMediaReceiveJob.NativeAlbumIdentity(destination["identity"]!.AsObject()) == root ||
                    picked.VolumePath.Equals(volumePath, StringComparison.OrdinalIgnoreCase) ||
                    picked.VolumePath.StartsWith(volumePath.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) ||
                    volumePath.StartsWith(picked.VolumePath.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase))
                    throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            }
            var known = before?.Events.FirstOrDefault(item => item.Destination.RootIdentity == root && item.Destination.NativePath == picked.NativePath && item.Destination.VolumePath == picked.VolumePath);
            if (known is not null && known.CreationFileTime != creation) throw DeviceFileControl.Error("file_selection_witness_context_changed");
            var isLegacy = legacy.RootIdentity == root && legacy.NativePath == picked.NativePath && legacy.VolumePath == picked.VolumePath;
            if (legacy.RootIdentity == root && !isLegacy || before?.Events.Any(item => item.Destination.RootIdentity == root &&
                (item.Destination.NativePath != picked.NativePath || item.Destination.VolumePath != picked.VolumePath || item.CreationFileTime != creation)) == true)
                throw DeviceFileControl.Error("file_selection_witness_context_changed");
            var target = isLegacy ? legacy : known?.Destination ?? new NativeMediaDestination(1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(),
                kind, picked.NativePath, picked.VolumePath, root, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant());
            var stamp = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
            var value = new JsonObject { ["format"] = 1, ["scope"] = SelectionScope(scope), ["media_type"] = kind, ["stamp"] = stamp,
                ["previous"] = expectedStamp, ["destination"] = NativeMediaDestinationValue(scope, target), ["creation"] = SelectionHex(creation) };
            var plain = TelefonCrypto.Canonical(value); byte[] cipher;
            try { cipher = Seal("native_media_selection_witness_event", scope.PeerId + "/" + kind + "/" + stamp, plain); }
            finally { CryptographicOperations.ZeroMemory(plain); }
            if (cipher.Length > SelectionWitnessFileLimit) throw DeviceFileControl.Error("file_selection_witness_capacity");
            Current();
            using var parent = DeviceFileNativeDirectory.OpenExistingForReceive(paths.Telefon);
            using var directory = before is null ? parent.CreateChild(Path.GetFileName(SelectionDirectory(scope, kind)))
                : parent.OpenOriginalChild(Path.GetFileName(SelectionDirectory(scope, kind)), NativeMediaReceiveJob.NativeAlbumIdentity(before.Body["directory"]!["identity"]!.AsObject()));
            DeviceFileNativeDirectory.Identity fileIdentity; long fileSize; string fileSha; ulong fileCreation;
            using (var file = directory.CreateStagedFile(stamp + ".seal"))
            {
                try
                {
                    for (var at = 0; at < cipher.Length;)
                    {
                        Current(); var count = Math.Min(DeviceFileManifest.ChunkBytes, cipher.Length - at);
                        file.WriteChunk(at, cipher.AsSpan(at, count)); at += count;
                    }
                    var checkpoint = file.DurableCheckpoint();
                    var verified = NativeMediaBackupBytes.Verify(file, checkpoint.Size, checkpoint.Sha256, Current);
                    fileIdentity = verified.Identity; fileSize = checkpoint.Size; fileSha = checkpoint.Sha256; fileCreation = file.CurrentCreationFileTime();
                }
                finally { CryptographicOperations.ZeroMemory(cipher); }
            }
            Current();
            var inventory = directory.NativeMetadataFiles(Current, SelectionWitnessLimit);
            var member = inventory.Single(item => item.Name == stamp + ".seal");
            if (member.Identity != fileIdentity || member.Size != fileSize || member.CreationFileTime != fileCreation)
                throw DeviceFileControl.Error("file_selection_witness_changed");
            var entries = before?.Body["events"]!.DeepClone().AsArray() ?? new JsonArray();
            entries.Add(new JsonObject { ["stamp"] = stamp, ["identity"] = NativeMediaReceiveJob.NativeIdentity(member.Identity),
                ["size"] = fileSize, ["sha256"] = fileSha, ["creation"] = SelectionHex(fileCreation) });
            var next = new JsonObject { ["format"] = 1, ["scope"] = SelectionScope(scope), ["media_type"] = kind,
                ["original"] = NativeMediaDestinationValue(scope, legacy), ["head"] = stamp, ["events"] = entries,
                ["directory"] = before?.Body["directory"]!.DeepClone() ?? new JsonObject { ["native_path"] = directory.NativePath, ["volume_path"] = directory.VolumePath,
                    ["identity"] = NativeMediaReceiveJob.NativeIdentity(directory.OriginalIdentity), ["creation"] = SelectionHex(directory.CurrentReceiveCreationFileTime()) } };
            using var transaction = db.BeginTransaction();
            if (!JsonNode.DeepEquals(ReadSelectionWitnessBody(db, transaction, scope, kind), before?.Body))
                throw DeviceFileControl.Error("file_selection_witness_stale_choice");
            plain = TelefonCrypto.Canonical(next);
            try
            {
                if (plain.Length > SelectionWitnessRowLimit) throw DeviceFileControl.Error("file_selection_witness_capacity");
                cipher = Seal("native_media_selection_witness_head", scope.PeerId + "/" + kind, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_selection_witnesses(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,media_type)); " +
                "INSERT INTO native_media_selection_witnesses(peer_id,media_type,value) VALUES($peer,$kind,$value) ON CONFLICT(peer_id,media_type) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", peerId); write.Parameters.AddWithValue("$kind", kind); write.Parameters.AddWithValue("$value", cipher);
            write.ExecuteNonQuery();
            var readback = ReadSelectionWitness(db, transaction, scope, kind, Current)?.Head;
            if (readback?.Stamp != stamp) throw DeviceFileControl.Error("file_selection_witness_head_changed");
            Current(); transaction.Commit();
            if (ReadSelectionWitness(db, null, scope, kind, Current)?.Head != readback)
                throw DeviceFileControl.Error("file_selection_witness_head_changed");
            return readback;
        }
    }

}
