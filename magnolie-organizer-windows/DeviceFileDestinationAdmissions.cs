using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

// Historical native destination metadata, never a data permission or current
// selection. The original admission event is independent of the current head.
internal sealed record NativeMediaDestinationAdmission(NativeMediaDestination Destination, ulong CreationFileTime, string AdmissionStamp, string RecordSha256,
    bool? OriginalLegacy = null)
{
    internal bool GrantsReadAuthority => false;
    internal bool GrantsReceiveAuthority => false;
    internal bool GrantsSendAuthority => false;
}

internal sealed partial class TelefonStore
{
    private static JsonObject ParseDestinationAdmissionBody(JsonNode node)
    {
        var format = TelefonProtocolContract.Integer(node["format"]);
        if (format == 1) return TelefonProtocolContract.ExactObject(node, "format", "scope", "media_type", "version", "destination", "creation", "directory", "event", "previous");
        if (format != 2) throw DeviceFileControl.Error("file_destination_admission_invalid");
        var body = TelefonProtocolContract.ExactObject(node, "format", "scope", "media_type", "version", "destination", "creation", "directory", "event", "previous", "original_legacy");
        if (body["original_legacy"] is not JsonValue value || !value.TryGetValue<bool>(out _)) throw DeviceFileControl.Error("file_destination_admission_invalid");
        return body;
    }
    private static bool HasDestinationAdmissionEvidence(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope, string kind)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_destination_admissions'";
        if (exists.ExecuteScalar() is null) return false;
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT 1 FROM native_media_destination_admissions WHERE peer_id=$peer AND media_type=$kind LIMIT 1";
        read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$kind", kind);
        return read.ExecuteScalar() is not null;
    }

    // Authenticated metadata is used ONLY to DENY known cross-kind overlap.
    // Missing current heads/files must not turn historical roots into free space.
    private void RequireNoNativeAdmissionOverlap(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope,
        string kind, DeviceFileNativeDirectory picked)
    {
        if (!HasDestinationAdmissionEvidence(db, transaction, scope, kind)) return;
        using var query = db.CreateCommand(); query.Transaction = transaction;
        query.CommandText = "SELECT version,value FROM native_media_destination_admissions WHERE peer_id=$peer AND media_type=$kind LIMIT 33";
        query.Parameters.AddWithValue("$peer", scope.PeerId); query.Parameters.AddWithValue("$kind", kind);
        using var rows = query.ExecuteReader(); var count = 0;
        while (rows.Read())
        {
            if (++count > SelectionWitnessLimit) throw DeviceFileControl.Error("file_destination_admission_capacity");
            var version = rows.GetString(0); var cipher = (byte[])rows[1];
            if (!DeviceFileControl.Hash(version) || cipher.Length > MediaDestinationRecordLimit + 28) throw DeviceFileControl.Error("file_destination_admission_invalid");
            var plain = Open("native_media_destination_admission", scope.PeerId + "/" + kind + "/" + version, cipher);
            try
            {
                var body = ParseDestinationAdmissionBody(JsonNode.Parse(plain)!);
                var destination = ParseNativeMediaDestination(body["destination"]!.AsObject(), scope, kind);
                if (body["scope"]?.GetValue<string>() != SelectionScope(scope) ||
                    body["media_type"]?.GetValue<string>() != kind || body["version"]?.GetValue<string>() != version || destination.Version != version)
                    throw DeviceFileControl.Error("file_destination_admission_invalid");
                if (picked.CurrentReceiveIdentity() == destination.RootIdentity || picked.VolumePath.Equals(destination.VolumePath, StringComparison.OrdinalIgnoreCase) ||
                    picked.VolumePath.StartsWith(destination.VolumePath.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) ||
                    destination.VolumePath.StartsWith(picked.VolumePath.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase))
                    throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
    }

    internal (NativeMediaSelectionWitness Selection, NativeMediaDestinationAdmission Admission) AdmitNativeMediaDestination(
        TelefonCoordinator.NativeDestinationAdmissionContext context, DeviceFileNativeDirectory picked)
    {
        context.BeginWrite(this);
        try
        {
            var selected = RecordSelectionWitness(context.PeerId, context.Kind, context.ExpectedStamp, picked, context.RequireForWrite, context);
            var admitted = ReadNativeMediaDestinationAdmission(context.PeerId, context.Kind, selected.Destination.Version)
                ?? throw DeviceFileControl.Error("file_destination_admission_required");
            if (!selected.NativeAdmission || admitted.Destination != selected.Destination || admitted.CreationFileTime != selected.CreationFileTime)
                throw DeviceFileControl.Error("file_destination_admission_changed");
            return (selected, admitted);
        }
        finally { context.EndWrite(); }
    }

    private void SaveNativeDestinationAdmission(SqliteConnection db, SqliteTransaction transaction, NativeMediaPreferenceScope scope,
        string kind, JsonObject selection, NativeMediaSelectionWitness selected, string? previous, Action current)
    {
        current();
        if (!selected.NativeAdmission) throw DeviceFileControl.Error("file_destination_admission_required");
        var existing = ReadNativeDestinationAdmission(db, transaction, scope, kind, selected.Destination.Version, current);
        if (existing is not null)
        {
            if (existing.Destination != selected.Destination || existing.CreationFileTime != selected.CreationFileTime)
                throw DeviceFileControl.Error("file_destination_admission_changed");
            return; // Immutable original admission, no rotation on re-selection.
        }
        var value = new JsonObject { ["format"] = 2, ["scope"] = SelectionScope(scope), ["media_type"] = kind,
            ["version"] = selected.Destination.Version, ["destination"] = NativeMediaDestinationValue(scope, selected.Destination),
            ["original_legacy"] = JsonNode.DeepEquals(selection["original"], NativeMediaDestinationValue(scope, selected.Destination)),
            ["creation"] = SelectionHex(selected.CreationFileTime), ["directory"] = selection["directory"]!.DeepClone(),
            ["event"] = selection["events"]!.AsArray().Last()!.DeepClone(), ["previous"] = previous };
        var plain = TelefonCrypto.Canonical(value); byte[] cipher;
        try
        {
            if (plain.Length > MediaDestinationRecordLimit) throw DeviceFileControl.Error("file_destination_admission_capacity");
            cipher = Seal("native_media_destination_admission", scope.PeerId + "/" + kind + "/" + selected.Destination.Version, plain);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
        using var write = db.CreateCommand(); write.Transaction = transaction;
        write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_destination_admissions(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,version TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,media_type,version)); " +
            "INSERT INTO native_media_destination_admissions(peer_id,media_type,version,value) VALUES($peer,$kind,$version,$value)";
        write.Parameters.AddWithValue("$peer", scope.PeerId); write.Parameters.AddWithValue("$kind", kind);
        write.Parameters.AddWithValue("$version", selected.Destination.Version); write.Parameters.AddWithValue("$value", cipher);
        write.ExecuteNonQuery(); current();
        var readback = ReadNativeDestinationAdmission(db, transaction, scope, kind, selected.Destination.Version, current);
        if (readback?.Destination != selected.Destination || readback.CreationFileTime != selected.CreationFileTime || readback.AdmissionStamp != selected.Stamp)
            throw DeviceFileControl.Error("file_destination_admission_changed");
    }

    internal NativeMediaDestinationAdmission? ReadNativeMediaDestinationAdmission(string peerId, string kind, string version)
    {
        MediaDestinationKind(kind);
        if (!DeviceFileControl.Hash(version)) throw DeviceFileControl.Error("file_destination_admission_invalid");
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            void Current()
            {
                RequireNativeMediaStorageKey();
                if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_destination_admission_changed");
            }
            using var db = OpenNativeMediaDatabase(); db.Open();
            return ReadNativeDestinationAdmission(db, null, scope, kind, version, Current);
        }
    }

    private NativeMediaDestinationAdmission? ReadNativeDestinationAdmission(SqliteConnection db, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope, string kind, string version, Action current)
    {
        current();
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_destination_admissions'";
        if (exists.ExecuteScalar() is null) return null;
        using var query = db.CreateCommand(); query.Transaction = transaction;
        query.CommandText = "SELECT value FROM native_media_destination_admissions WHERE peer_id=$peer AND media_type=$kind AND version=$version";
        query.Parameters.AddWithValue("$peer", scope.PeerId); query.Parameters.AddWithValue("$kind", kind); query.Parameters.AddWithValue("$version", version);
        var stored = query.ExecuteScalar();
        if (stored is null) return null;
        if (stored is not byte[] cipher || cipher.Length > MediaDestinationRecordLimit + 28) throw DeviceFileControl.Error("file_destination_admission_invalid");
        var plain = Open("native_media_destination_admission", scope.PeerId + "/" + kind + "/" + version, cipher);
        JsonObject value;
        try { value = ParseDestinationAdmissionBody(JsonNode.Parse(plain)!); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        if (value["scope"]?.GetValue<string>() != SelectionScope(scope) ||
            value["media_type"]?.GetValue<string>() != kind || value["version"]?.GetValue<string>() != version)
            throw DeviceFileControl.Error("file_destination_admission_invalid");
        var destination = ParseNativeMediaDestination(value["destination"]!.AsObject(), scope, kind);
        var creation = SelectionHex(value["creation"]); var descriptor = value["directory"]!.AsObject(); var entry = value["event"]!.AsObject();
        if (destination.Version != version) throw DeviceFileControl.Error("file_destination_admission_invalid");
        TelefonProtocolContract.ExactObject(descriptor, "native_path", "volume_path", "identity", "creation");
        TelefonProtocolContract.ExactObject(entry, "stamp", "identity", "size", "sha256", "creation");
        var stamp = entry["stamp"]!.GetValue<string>(); var sha = entry["sha256"]!.GetValue<string>();
        var size = TelefonProtocolContract.Integer(entry["size"]); var previous = value["previous"]?.GetValue<string>();
        if (!DeviceFileControl.Hash(stamp) || !DeviceFileControl.Hash(sha) || previous is not null && !DeviceFileControl.Hash(previous) ||
            size is < 29 or > SelectionWitnessFileLimit)
            throw DeviceFileControl.Error("file_destination_admission_invalid");
        using var directory = OpenSelectionDirectory(SelectionDirectory(scope, kind))
            ?? throw DeviceFileControl.Error("file_destination_admission_witness_required");
        void Bound()
        {
            current();
            if (directory.NativePath != descriptor["native_path"]?.GetValue<string>() || directory.VolumePath != descriptor["volume_path"]?.GetValue<string>() ||
                directory.CurrentReceiveIdentity() != NativeMediaReceiveJob.NativeAlbumIdentity(descriptor["identity"]!.AsObject()) ||
                directory.CurrentReceiveCreationFileTime() != SelectionHex(descriptor["creation"]))
                throw DeviceFileControl.Error("file_destination_admission_witness_changed");
        }
        Bound();
        // Deliberately verify ONLY the independently admitted original event.
        // No current head, legacy record, full inventory or stage lookup here.
        using var file = directory.OpenOriginalStagedFile(stamp + ".seal", NativeMediaReceiveJob.NativeAlbumIdentity(entry["identity"]!.AsObject()), size, sha);
        if (file.CurrentCreationFileTime() != SelectionHex(entry["creation"])) throw DeviceFileControl.Error("file_destination_admission_witness_changed");
        _ = NativeMediaBackupBytes.Verify(file, size, sha, Bound);
        var bytes = new byte[checked((int)size)];
        try
        {
            for (var at = 0; at < bytes.Length;)
            {
                Bound(); var chunk = file.ReadExact(at, Math.Min(DeviceFileManifest.ChunkBytes, bytes.Length - at));
                try { chunk.CopyTo(bytes, at); at += chunk.Length; }
                finally { CryptographicOperations.ZeroMemory(chunk); }
            }
            plain = Open("native_media_selection_witness_event", scope.PeerId + "/" + kind + "/" + stamp, bytes);
            try
            {
                var original = ParseSelectionEvent(JsonNode.Parse(plain)!.AsObject(), scope, kind, stamp, previous);
                if (!original.NativeAdmission || original.Destination != destination || original.Creation != creation)
                    throw DeviceFileControl.Error("file_destination_admission_required");
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
        Bound(); return new(destination, creation, stamp, DeviceFileControl.Digest("magnolie-native-destination-admission-v1\0", value), value["original_legacy"]?.GetValue<bool>());
    }
}
