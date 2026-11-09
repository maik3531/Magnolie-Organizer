using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

// Storage metadata only: no transfer token, file grant or synchronization root.
internal sealed record NativeMediaBackupParent(string NativePath, string VolumePath, DeviceFileNativeDirectory.Identity Identity)
{
    internal JsonObject Wire() => new() { ["native_path"] = NativePath, ["volume_path"] = VolumePath,
        ["identity"] = TelefonStore.NativeMediaReceiveJob.NativeIdentity(Identity) };
    internal string Id => DeviceFileControl.Digest("magnolie-native-backup-parent-v1\0", Wire());
    internal static NativeMediaBackupParent FromDestination(NativeMediaDestination value) => new(value.NativePath, value.VolumePath, value.RootIdentity);
    internal static NativeMediaBackupParent Capture(DeviceFileNativeDirectory owner) => new(owner.NativePath, owner.VolumePath, owner.CurrentReceiveIdentity());
    internal static NativeMediaBackupParent Parse(JsonNode value)
    {
        var record = TelefonProtocolContract.ExactObject(value, "native_path", "volume_path", "identity");
        var path = TelefonMessagingContract.String(record, "native_path"); var volume = TelefonMessagingContract.String(record, "volume_path");
        if (!volume.StartsWith(@"\\?\Volume{", StringComparison.Ordinal) || volume.Length > 16048 || volume.Any(c => c < 32 || c == 127))
            throw DeviceFileControl.Error("media_backup_parent_invalid");
        NativeMediaBackupExclusions.RequireMediaDirectory(path, volume); // Never nest a catalog inside another Backup subtree.
        return new(path, volume, TelefonStore.NativeMediaReceiveJob.NativeAlbumIdentity(record["identity"]!.AsObject()));
    }
    internal DeviceFileNativeDirectory OpenNative()
    {
        var owner = DeviceFileNativeDirectory.OpenExistingForReceive(NativePath);
        try
        {
            if (owner.CurrentReceiveIdentity() != Identity || !owner.VolumePath.Equals(VolumePath, StringComparison.OrdinalIgnoreCase))
                throw DeviceFileControl.Error("media_backup_original_parent_required");
            NativeMediaBackupExclusions.RequireMediaDirectory(owner); return owner;
        }
        catch { owner.Dispose(); throw; }
    }
}

internal sealed record NativeMediaBackupLocations(string? Version, NativeMediaBackupParent Default,
    string? SelectedId, IReadOnlyList<NativeMediaBackupParent> Parents)
{
    internal NativeMediaBackupParent Current => SelectedId is null ? Default : Parents.Single(value => value.Id == SelectedId);
}

internal sealed partial class TelefonStore
{
    private static string BackupLocationsScope(NativeMediaPreferenceScope scope, string kind) => DeviceFileControl.Digest(
        "magnolie-native-backup-locations-scope-v1\0", new JsonArray(scope.PeerId, scope.PeerKey, scope.PairingEpoch, scope.LocalId, scope.LocalKey, kind));

    private sealed record BackupLocationAddress(string Table, string Purpose, string Key, string Scope, string? DestinationVersion);
    private static BackupLocationAddress LegacyBackupLocationAddress(NativeMediaPreferenceScope scope, string kind)
        => new("native_media_backup_locations", "native_media_backup_locations", scope.PeerId + "/" + kind, BackupLocationsScope(scope, kind), null);

    private BackupLocationAddress BackupAddressForDestination(NativeMediaPreferenceScope scope, string kind, NativeMediaDestination destination)
    {
        using var db = OpenNativeMediaDatabase(); db.Open();
        var legacy = ReadLegacyNativeMediaDestination(db, null, scope, kind);
        if (legacy == destination) return LegacyBackupLocationAddress(scope, kind);
        var admission = ReadNativeMediaDestinationAdmission(scope.PeerId, kind, destination.Version)
            ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
        if (admission.Destination != destination) throw DeviceFileControl.Error("media_backup_original_destination_required");
        if (admission.OriginalLegacy == true || legacy is null && admission.OriginalLegacy is null)
            return LegacyBackupLocationAddress(scope, kind); // V1 compatibility remains strict about the signed default.
        var digest = DeviceFileControl.Digest("magnolie-native-backup-generation-scope-v1\0", NativeMediaDestinationValue(scope, destination));
        return new("native_media_backup_locations_by_destination", "native_media_backup_locations_by_destination",
            scope.PeerId + "/" + kind + "/" + destination.Version, digest, destination.Version);
    }

    private NativeMediaBackupLocations ReadBackupLocations(SqliteConnection db, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope, string kind, NativeMediaBackupParent defaultParent, BackupLocationAddress? address = null)
    {
        address ??= LegacyBackupLocationAddress(scope, kind);
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=$table";
        read.Parameters.AddWithValue("$table", address.Table);
        if (read.ExecuteScalar() is null) return new(null, defaultParent, null, new[] { defaultParent });
        read.Parameters.Clear();
        read.CommandText = "SELECT value FROM " + address.Table + " WHERE peer_id=$peer AND media_type=$kind" +
            (address.DestinationVersion is null ? "" : " AND destination_version=$destination");
        read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$kind", kind);
        if (address.DestinationVersion is not null) read.Parameters.AddWithValue("$destination", address.DestinationVersion);
        if (read.ExecuteScalar() is not byte[] encrypted) return new(null, defaultParent, null, new[] { defaultParent });
        RequireNativeMediaStorageKey();
        if (encrypted.Length > 2 * 1024 * 1024) throw DeviceFileControl.Error("media_backup_locations_invalid");
        var plain = Open(address.Purpose, address.Key, encrypted);
        try
        {
            var body = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "version", "default", "selected", "parents");
            var version = TelefonMessagingContract.String(body, "version");
            if (TelefonProtocolContract.Integer(body["format"]) != 1 || body["scope"]?.GetValue<string>() != address.Scope ||
                !DeviceFileControl.Hash(version) || body["default"]?.GetValue<string>() != defaultParent.Id ||
                body["parents"] is not JsonArray parents || parents.Count is < 1 or > 64)
                throw DeviceFileControl.Error("media_backup_locations_scope_changed");
            var roots = parents.Select(value => NativeMediaBackupParent.Parse(value!)).ToArray();
            var selected = body["selected"] is null ? null : TelefonMessagingContract.String(body, "selected");
            if (roots.Select(value => value.Id).Distinct().Count() != roots.Length || !roots.Contains(defaultParent) ||
                selected is not null && !roots.Any(value => value.Id == selected)) throw DeviceFileControl.Error("media_backup_locations_invalid");
            return new(version, defaultParent, selected, roots);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    internal NativeMediaBackupLocations ReadNativeMediaBackupLocations(string peerId, string kind)
    {
        MediaDestinationKind(kind);
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            var destination = ReadNativeMediaDestination(peerId, kind) ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
            var result = ReadOriginalNativeMediaBackupLocations(peerId, kind, destination);
            if (scope != MediaPreferenceScope(peerId)) throw DeviceFileControl.Error("media_backup_locations_scope_changed");
            return result;
        }
    }

    // Completed-job backup selection is relative to its authenticated original
    // destination, never the current receive getter. Existing nonmatching parent
    // registries HOLD; they are not migrated or copied to another generation.
    private NativeMediaBackupLocations ReadOriginalNativeMediaBackupLocations(string peerId, string kind, NativeMediaDestination destination)
    {
        var scope = MediaPreferenceScope(peerId);
        using var db = OpenNativeMediaDatabase(); db.Open();
        var result = ReadBackupLocations(db, null, scope, kind, NativeMediaBackupParent.FromDestination(destination), BackupAddressForDestination(scope, kind, destination));
        if (scope != MediaPreferenceScope(peerId)) throw DeviceFileControl.Error("media_backup_locations_scope_changed");
        return result;
    }

    // Explicit local native picker only. Recording a parent creates NO Backup
    // directory, copies/moves no bytes and never removes retained parent entries.
    internal NativeMediaBackupLocations ChangeNativeMediaBackupParent(string peerId, string kind, string? expectedVersion,
        DeviceFileNativeDirectory? selectedOwner, Action native)
        => ChangeOriginalNativeMediaBackupParent(peerId, kind, null, expectedVersion, selectedOwner, native);

    internal NativeMediaBackupLocations ReadNativeMediaBackupLocationsForAdmission(string peerId, string kind, string destinationVersion)
    {
        var admission = ReadNativeMediaDestinationAdmission(peerId, kind, destinationVersion)
            ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
        lock (gate) return ReadOriginalNativeMediaBackupLocations(peerId, kind, admission.Destination);
    }

    internal NativeMediaBackupLocations ChangeNativeMediaBackupParentForAdmission(string peerId, string kind, string destinationVersion,
        string? expectedVersion, DeviceFileNativeDirectory? selectedOwner, Action native)
    {
        var admission = ReadNativeMediaDestinationAdmission(peerId, kind, destinationVersion)
            ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
        void Bound()
        {
            native();
            if (ReadNativeMediaDestinationAdmission(peerId, kind, destinationVersion) != admission)
                throw DeviceFileControl.Error("media_backup_original_destination_required");
        }
        return ChangeOriginalNativeMediaBackupParent(peerId, kind, admission.Destination, expectedVersion, selectedOwner, Bound);
    }

    private NativeMediaBackupLocations ChangeOriginalNativeMediaBackupParent(string peerId, string kind, NativeMediaDestination? admitted,
        string? expectedVersion, DeviceFileNativeDirectory? selectedOwner, Action native)
    {
        MediaDestinationKind(kind);
        lock (gate)
        {
            native(); RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            var destination = admitted ?? ReadNativeMediaDestination(peerId, kind) ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
            var address = BackupAddressForDestination(scope, kind, destination);
            using var original = destination.OpenNative();
            var selected = selectedOwner is null ? null : NativeMediaBackupParent.Capture(selectedOwner);
            if (selected is not null) NativeMediaBackupExclusions.RequireMediaDirectory(selectedOwner!);
            var defaultParent = NativeMediaBackupParent.FromDestination(destination);
            var selectedId = selected is null || selected == defaultParent ? null : selected.Id;
            var chosen = selected ?? defaultParent;
            DeviceFileNativeDirectory? existingBackup = null;
            try { existingBackup = DeviceFileNativeDirectory.OpenExistingForReceive(Path.Combine(chosen.NativePath, "Backup")); }
            catch (IOException error) when (error.InnerException is System.ComponentModel.Win32Exception nativeError && nativeError.NativeErrorCode is 2 or 3) { }
            if (existingBackup is not null)
            {
                using (existingBackup)
                using (var catalog = new MediaBackupCatalog(this, destination, native, false, chosen)) _ = catalog.Versions();
            }
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            var before = ReadBackupLocations(db, transaction, scope, kind, defaultParent, address);
            if (before.Version != expectedVersion) throw DeviceFileControl.Error("media_backup_locations_stale_choice");
            void Current()
            {
                native(); RequireNativeMediaStorageKey(); _ = original.CurrentReceiveIdentity();
                if (scope != MediaPreferenceScope(peerId) || selected is not null && selectedOwner!.CurrentReceiveIdentity() != selected.Identity)
                    throw DeviceFileControl.Error("media_backup_locations_scope_changed");
            }
            Current();
            if (selectedId == before.SelectedId) { transaction.Commit(); return before; }
            var parents = before.Parents.ToList();
            if (selected is not null && !parents.Contains(selected)) parents.Add(selected);
            if (parents.Count > 64) throw DeviceFileControl.Error("media_backup_locations_capacity");
            var version = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
            var body = new JsonObject { ["format"] = 1, ["scope"] = address.Scope, ["version"] = version,
                ["default"] = defaultParent.Id, ["selected"] = selectedId, ["parents"] = new JsonArray(parents.Select(value => (JsonNode)value.Wire()).ToArray()) };
            var plain = TelefonCrypto.Canonical(body); byte[] encrypted;
            try
            {
                if (plain.Length > 2 * 1024 * 1024 - 28) throw DeviceFileControl.Error("media_backup_locations_capacity");
                encrypted = Seal(address.Purpose, address.Key, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = address.DestinationVersion is null
                ? "CREATE TABLE IF NOT EXISTS native_media_backup_locations(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,media_type)); INSERT OR REPLACE INTO native_media_backup_locations(peer_id,media_type,value) VALUES($peer,$kind,$value)"
                : "CREATE TABLE IF NOT EXISTS native_media_backup_locations_by_destination(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,destination_version TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,media_type,destination_version)); INSERT INTO native_media_backup_locations_by_destination(peer_id,media_type,destination_version,value) VALUES($peer,$kind,$destination,$value) ON CONFLICT(peer_id,media_type,destination_version) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", peerId); write.Parameters.AddWithValue("$kind", kind); write.Parameters.AddWithValue("$value", encrypted);
            if (address.DestinationVersion is not null) write.Parameters.AddWithValue("$destination", address.DestinationVersion);
            write.ExecuteNonQuery(); Current(); transaction.Commit();
            var saved = ReadBackupLocations(db, null, scope, kind, defaultParent, address);
            if (saved.Version != version || saved.SelectedId != selectedId || !saved.Parents.SequenceEqual(parents))
                throw DeviceFileControl.Error("media_backup_locations_not_proven");
            return saved;
        }
    }
}
