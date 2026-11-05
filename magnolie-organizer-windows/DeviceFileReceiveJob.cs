using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Retain historical jobs; a full catalog blocks new work, never evicts it.
    private const int NativeReceiveHistoryLimit = 128, NativeReceiveActiveLimit = 32;
    private const long NativeReceiveCacheLimit = 1024L * 1024 * 1024;
    private sealed record ReceiveHead(string JobId, long Revision, string Version, JsonObject Body);

    internal void RequireNativeMediaStorageKey()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("file_receive_windows_required");
        var encrypted = files.Read(paths.TelefonStorageKey, 4096) ?? throw DeviceFileControl.Error("file_receive_existing_storage_key_required");
        var current = ProtectedData.Unprotect(Convert.FromBase64String(encrypted), System.Text.Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser);
        try
        {
            if (current.Length != 32 || !CryptographicOperations.FixedTimeEquals(current, storageKey))
                throw DeviceFileControl.Error("file_receive_existing_storage_key_changed");
        }
        finally { CryptographicOperations.ZeroMemory(current); }
    }

    private ReceiveHead ReadReceiveHead(byte[] cipher, string jobId, NativeMediaPreferenceScope scope)
    {
        if (cipher.Length > 262144) throw DeviceFileControl.Error("file_receive_history_invalid");
        var plain = Open("native_media_receive_job", scope.PeerId + "/" + jobId, cipher);
        try
        {
            var value = JsonNode.Parse(plain) as JsonObject ?? throw DeviceFileControl.Error("file_receive_history_invalid");
            TelefonProtocolContract.ExactObject(value, "format", "peer_id", "peer_key", "pairing_epoch", "local_id", "local_key", "job_id", "revision", "version", "record");
            string Text(string key) => TelefonMessagingContract.String(value, key);
            if (TelefonProtocolContract.Integer(value["format"]) != 1 || Text("peer_id") != scope.PeerId || Text("peer_key") != scope.PeerKey ||
                Text("pairing_epoch") != scope.PairingEpoch || Text("local_id") != scope.LocalId || Text("local_key") != scope.LocalKey || Text("job_id") != jobId)
                throw DeviceFileControl.Error("file_receive_history_binding_changed");
            var revision = TelefonProtocolContract.Integer(value["revision"]); var version = Text("version");
            if (revision is < 1 or > DeviceFileControl.MaximumRevision || !DeviceFileControl.Hash(version) ||
                value["record"] is not JsonObject body) throw DeviceFileControl.Error("file_receive_history_invalid");
            NativeMediaReceiveJob.ValidateBody(body, jobId);
            var binding = body["binding"]!.AsObject();
            if (TelefonMessagingContract.String(binding, "sender_id") != scope.PeerId || TelefonMessagingContract.String(binding, "receiver_id") != scope.LocalId ||
                TelefonMessagingContract.String(binding, "sender_identity_sha256") != scope.PeerKey || TelefonMessagingContract.String(binding, "receiver_identity_sha256") != scope.LocalKey)
                throw DeviceFileControl.Error("file_receive_history_binding_changed");
            return new(jobId, revision, version, body);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private List<ReceiveHead> ReceiveHeads(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_receive_jobs'";
        if (exists.ExecuteScalar() is null) return [];
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT job_id,value FROM native_media_receive_jobs WHERE peer_id=$peer ORDER BY job_id";
        read.Parameters.AddWithValue("$peer", scope.PeerId);
        using var rows = read.ExecuteReader(); var result = new List<ReceiveHead>();
        while (rows.Read())
        {
            var id = rows.GetString(0);
            if (result.Count >= NativeReceiveHistoryLimit || id.Length != 32 || id.Any(c => !char.IsAsciiHexDigitLower(c)))
                throw DeviceFileControl.Error("file_receive_history_bound");
            result.Add(ReadReceiveHead((byte[])rows[1], id, scope));
        }
        return result;
    }

    // Native inspection is metadata only; it opens no destination/stage or grant.
    internal IReadOnlyList<(string JobId, string Version, string Phase)> NativeMediaReceiveHistory(string peerId)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var heads = ReceiveHeads(db, null, scope);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_history_binding_changed");
            return heads.Select(head => (head.JobId, head.Version, TelefonMessagingContract.String(head.Body, "phase"))).ToArray();
        }
    }

    internal (int HistoryJobs, int ActiveJobs, long ReservedBytes) NativeMediaReceiveBudget(string peerId)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var heads = ReceiveHeads(db, null, scope); var active = heads.Where(head => !head.Body.ContainsKey("source_end")).ToArray();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_history_binding_changed");
            return (heads.Count, active.Length, active.Sum(head => TelefonProtocolContract.Integer(head.Body["manifest"]!["total_bytes"])));
        }
    }

    private void CheckReceiveStageInventory(string peerId, NativeMediaDestination destination, DeviceFileNativeDirectory root, Action current)
    {
        lock (gate)
        {
            current(); var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var known = ReceiveHeads(db, null, scope).Where(head =>
                TelefonMessagingContract.String(head.Body["binding"]!.AsObject(), "destination_token") == destination.DestinationToken)
                .Select(head => TelefonMessagingContract.String(head.Body, "stage_name")).ToHashSet(StringComparer.Ordinal);
            var count = 0;
            foreach (var candidate in Directory.EnumerateFileSystemEntries(root.NativePath, ".magnolie-receive-*", SearchOption.TopDirectoryOnly))
            {
                current();
                if (++count > NativeReceiveHistoryLimit || !known.Contains(Path.GetFileName(candidate)))
                    throw DeviceFileControl.Error("file_receive_original_history_required");
            }
            current();
        }
    }

    private ReceiveHead SaveReceiveHead(string peerId, string jobId, string? expectedVersion, JsonObject body, Action current)
    {
        lock (gate)
        {
            current(); NativeMediaReceiveJob.ValidateBody(body, jobId);
            var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            using var transaction = db.BeginTransaction();
            var heads = ReceiveHeads(db, transaction, scope); var before = heads.SingleOrDefault(head => head.JobId == jobId);
            if (before?.Version != expectedVersion) throw DeviceFileControl.Error("file_receive_history_cas_conflict");
            if (before is null)
            {
                long Budget(JsonObject record) => TelefonProtocolContract.Integer(record["manifest"]!["total_bytes"]);
                var active = heads.Where(head => !head.Body.ContainsKey("source_end")).ToArray();
                if (heads.Count >= NativeReceiveHistoryLimit || active.Length >= NativeReceiveActiveLimit ||
                    active.Sum(head => Budget(head.Body)) + Budget(body) > NativeReceiveCacheLimit)
                    throw DeviceFileControl.Error("file_receive_history_quota_reached");
                if (TelefonMessagingContract.String(body, "phase") != "reserved") throw DeviceFileControl.Error("file_receive_original_reservation_required");
                var transfer = TelefonMessagingContract.String(body["manifest"]!.AsObject(), "transfer_id");
                var token = TelefonMessagingContract.String(body["binding"]!.AsObject(), "destination_token");
                var paths = body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Select(file => TelefonMessagingContract.String(file, "path")).ToHashSet(StringComparer.OrdinalIgnoreCase);
                foreach (var head in heads)
                {
                    if (TelefonMessagingContract.String(head.Body["manifest"]!.AsObject(), "transfer_id") == transfer ||
                        TelefonMessagingContract.String(head.Body["binding"]!.AsObject(), "destination_token") == token &&
                        string.Equals(head.Body["album_root"]?["folder"]?.GetValue<string>() ?? "", body["album_root"]?["folder"]?.GetValue<string>() ?? "", StringComparison.OrdinalIgnoreCase) &&
                        head.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Any(file => paths.Contains(TelefonMessagingContract.String(file, "path")) &&
                            !body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Any(next =>
                                string.Equals(TelefonMessagingContract.String(next, "path"), TelefonMessagingContract.String(file, "path"), StringComparison.OrdinalIgnoreCase) &&
                                ReplacementAncestors(heads, body, TelefonMessagingContract.String(next, "id")).Contains((head.JobId, TelefonMessagingContract.String(file, "id"))))))
                        throw DeviceFileControl.Error("file_receive_original_job_resume_required");
                }
                foreach (var file in body["manifest"]!["files"]!.AsArray().OfType<JsonObject>())
                    _ = ReplacementAncestors(heads, body, TelefonMessagingContract.String(file, "id"));
            }
            else
            {
                foreach (var key in new[] { "manifest", "binding", "media_type", "destination_version", "destination", "stage_name", "replacements" })
                    if (!JsonNode.DeepEquals(before.Body[key], body[key])) throw DeviceFileControl.Error("file_receive_original_job_changed");
                if (before.Body.ContainsKey("source_job") && !JsonNode.DeepEquals(before.Body["source_job"], body["source_job"]))
                    throw DeviceFileControl.Error("file_receive_original_source_history_changed");
                foreach (var key in new[] { "media", "acceptance", "saved", "source_end" })
                    if (before.Body.ContainsKey(key) && !JsonNode.DeepEquals(before.Body[key], body[key]))
                        throw DeviceFileControl.Error("file_receive_original_receipt_changed");
                if (!JsonNode.DeepEquals(before.Body["album_root"], body["album_root"]) && !InitialAlbumIdentity(before.Body, body))
                    throw DeviceFileControl.Error("file_receive_original_album_changed");
                if (before.Revision >= DeviceFileControl.MaximumRevision) throw DeviceFileControl.Error("file_receive_history_revision_exhausted");
            }
            var result = new ReceiveHead(jobId, (before?.Revision ?? 0) + 1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), body);
            var value = new JsonObject { ["format"] = 1, ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
                ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey, ["job_id"] = jobId, ["revision"] = result.Revision,
                ["version"] = result.Version, ["record"] = body.DeepClone() };
            byte[] cipher; var plain = TelefonCrypto.Canonical(value);
            try { cipher = Seal("native_media_receive_job", peerId + "/" + jobId, plain); }
            finally { CryptographicOperations.ZeroMemory(plain); }
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_receive_jobs(peer_id TEXT NOT NULL,job_id TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,job_id)); " +
                "INSERT INTO native_media_receive_jobs(peer_id,job_id,value) VALUES($peer,$job,$value) ON CONFLICT(peer_id,job_id) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", peerId); write.Parameters.AddWithValue("$job", jobId); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
            current(); if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_history_binding_changed");
            transaction.Commit();
            using var readback = db.CreateCommand();
            readback.CommandText = "SELECT value FROM native_media_receive_jobs WHERE peer_id=$peer AND job_id=$job";
            readback.Parameters.AddWithValue("$peer", peerId); readback.Parameters.AddWithValue("$job", jobId);
            if (readback.ExecuteScalar() is not byte[] saved) throw DeviceFileControl.Error("file_receive_history_readback_failed");
            var actual = ReadReceiveHead(saved, jobId, scope);
            if (actual.Revision != result.Revision || actual.Version != result.Version || !JsonNode.DeepEquals(actual.Body, body))
                throw DeviceFileControl.Error("file_receive_history_readback_failed");
            current(); if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_history_binding_changed");
            return actual;
        }
    }

    internal NativeMediaReceiveJob BeginNativeMediaReceiveJob(string peerId, string mediaType, DeviceFileManifest manifest,
        Func<DeviceTransferBinding?> currentBinding, NativeMediaAlbumContext? album = null, NativeMediaReplacementContext? replacements = null)
        => NativeMediaReceiveJob.Begin(this, peerId, mediaType, manifest, currentBinding, album, replacements);

    // Explicit native owner only. No route registration, file grant fabrication,
    // automatic worker or original-job resume is performed by construction.
    internal sealed partial class NativeMediaReceiveJob : IDisposable
    {
        private readonly TelefonStore store; private readonly string peerId, mediaType;
        private readonly NativeMediaDestination destination; private readonly DeviceTransferBinding binding;
        private readonly Func<DeviceTransferBinding?> currentBinding; private readonly DeviceFileResumeLedger ledger;
        private readonly object jobGate = new(); private bool disposed, uncertain;
        private ReceiveHead? head; private DeviceFileNativeDirectory? root, stage;
        private readonly Dictionary<string, DeviceFileNativeDirectory.DeviceFileNativeStagedFile> files = [];
        internal string JobId { get; }
        internal string Version => head?.Version ?? throw DeviceFileControl.Error("file_receive_original_reservation_required");
        internal DeviceFileManifest Manifest { get; }

        private NativeMediaReceiveJob(TelefonStore store, string peerId, string mediaType, DeviceFileManifest manifest,
            NativeMediaDestination destination, Func<DeviceTransferBinding?> currentBinding, string? originalJobId = null)
        {
            this.store = store; this.peerId = peerId; this.mediaType = mediaType; Manifest = manifest;
            JobId = originalJobId ?? Guid.NewGuid().ToString("N");
            this.destination = destination; this.currentBinding = currentBinding;
            binding = currentBinding() ?? throw DeviceFileControl.Error("file_receive_current_binding_required");
            binding.Validate(); ledger = new(manifest, binding, currentBinding); Current();
        }

        private void Current()
        {
            try { CurrentImpl(); }
            catch { uncertain = true; throw; }
        }

        private void CurrentImpl()
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            nativeWorkerGuard?.Invoke();
            if (uncertain || currentBinding() != binding || binding.DestinationToken != destination.DestinationToken ||
                binding.SenderId != Manifest.SenderId || binding.ReceiverId != Manifest.ReceiverId)
                throw DeviceFileControl.Error("file_receive_current_binding_changed");
            store.RequireNativeMediaStorageKey();
            var scope = store.MediaPreferenceScope(peerId);
            if (scope.PeerId != binding.SenderId || scope.PeerKey != binding.SenderIdentitySha256 ||
                scope.LocalId != binding.ReceiverId || scope.LocalKey != binding.ReceiverIdentitySha256 ||
                store.ReadNativeMediaDestination(peerId, mediaType) != destination)
                throw DeviceFileControl.Error("file_receive_destination_binding_changed");
            var preferences = store.ReadNativeMediaPreferences(peerId);
            if (!(mediaType == "images" ? preferences.PhotosEnabled : preferences.VideosEnabled))
                throw DeviceFileControl.Error("file_receive_native_choice_withdrawn");
            _ = root?.CurrentIdentity(); _ = stage?.CurrentIdentity();
            _ = albumDirectory?.CurrentIdentity();
        }

        private void Save(JsonObject body) => head = store.SaveReceiveHead(peerId, JobId, head?.Version, body, Current);
        private JsonObject Change() => head?.Body.DeepClone().AsObject() ?? throw DeviceFileControl.Error("file_receive_original_reservation_required");
        private static JsonObject Key(DeviceFileNativeDirectory.Identity id) => new()
        { ["volume"] = id.VolumeSerial.ToString("x16", CultureInfo.InvariantCulture), ["low"] = id.FileIdLow.ToString("x16", CultureInfo.InvariantCulture), ["high"] = id.FileIdHigh.ToString("x16", CultureInfo.InvariantCulture) };
        internal static JsonObject NativeIdentity(DeviceFileNativeDirectory.Identity id) => Key(id);

        internal static NativeMediaReceiveJob Begin(TelefonStore store, string peerId, string mediaType, DeviceFileManifest manifest,
            Func<DeviceTransferBinding?> currentBinding, NativeMediaAlbumContext? album = null, NativeMediaReplacementContext? replacements = null)
        {
            ArgumentNullException.ThrowIfNull(currentBinding);
            MediaDestinationKind(mediaType);
            if (manifest.Files.Count > 16) throw DeviceFileControl.Error("file_receive_media_batch_bound");
            foreach (var file in manifest.Files) _ = DeviceFileNativeDirectory.ReceiveLeaf(file.Path);
            var destination = store.ReadNativeMediaDestination(peerId, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
            var owner = new NativeMediaReceiveJob(store, peerId, mediaType, manifest, destination, currentBinding);
            try
            {
                owner.root = destination.OpenNative(); owner.Current();
                if (album is not null)
                {
                    owner.albumRoot = store.FindNativeAlbumRoot(peerId, mediaType, destination, album.SourceEpoch);
                    if (owner.albumRoot is null && album.DisplayName is not null)
                        owner.albumRoot = new JsonObject { ["source_epoch"] = album.SourceEpoch, ["folder"] = album.Folder, ["identity"] = null };
                    if (owner.albumRoot?["identity"] is JsonObject identity)
                        owner.albumDirectory = owner.root.OpenOriginalChild(TelefonMessagingContract.String(owner.albumRoot, "folder"), AlbumIdentity(identity));
                }
                store.CheckReceiveStageInventory(peerId, destination, owner.root, owner.Current);
                replacements?.Consent.Require(); owner.replacementConsent = replacements?.Consent;
                foreach (var file in manifest.Files)
                {
                    if (owner.albumRoot?["identity"] is not null || owner.albumRoot is null)
                        if (owner.PublicationRoot.ExistingFileIdentity(file.Path) is not null &&
                            !(replacements?.Records.OfType<JsonObject>().Any(link => TelefonMessagingContract.String(link, "file_id") == file.Id) ?? false))
                            throw DeviceFileControl.Error("file_receive_destination_occupied");
                    owner.Current();
                }
                var manifestBody = new JsonObject { ["format"] = 1, ["transfer_id"] = manifest.TransferId, ["source_id"] = manifest.SourceId,
                    ["sender_id"] = manifest.SenderId, ["receiver_id"] = manifest.ReceiverId, ["chunk_bytes"] = DeviceFileManifest.ChunkBytes,
                    ["total_bytes"] = manifest.TotalBytes, ["files"] = new JsonArray(manifest.Files.Select(file => (JsonNode)new JsonObject
                    { ["id"] = file.Id, ["path"] = file.Path, ["size"] = file.Size, ["sha256"] = file.Sha256 }).ToArray()) };
                var reserved = new JsonObject { ["manifest"] = manifestBody, ["binding"] = owner.binding.Snapshot(), ["media_type"] = mediaType,
                    ["destination_version"] = destination.Version, ["destination"] = new JsonObject { ["native_path"] = destination.NativePath,
                        ["volume_path"] = destination.VolumePath, ["identity"] = Key(destination.RootIdentity), ["token"] = destination.DestinationToken },
                    ["phase"] = "reserved", ["stage_name"] = ".magnolie-receive-" + owner.JobId,
                    ["stage_identity"] = null, ["files"] = new JsonArray(manifest.Files.Select(file => (JsonNode)new JsonObject
                    { ["id"] = file.Id, ["phase"] = "pending", ["identity"] = null }).ToArray()) };
                if (owner.albumRoot is not null) reserved["album_root"] = owner.albumRoot.DeepClone();
                if (replacements is not null) reserved["replacements"] = replacements.Records.DeepClone();
                owner.Save(reserved);
                if (owner.albumRoot is not null && owner.albumRoot["identity"] is null)
                {
                    owner.albumDirectory = owner.root.CreateChild(TelefonMessagingContract.String(owner.albumRoot, "folder"));
                    owner.albumRoot["identity"] = Key(owner.albumDirectory.OriginalIdentity);
                    var directory = owner.Change(); directory["album_root"] = owner.albumRoot.DeepClone(); owner.Save(directory);
                }
                owner.Current();
                owner.stage = owner.root.CreateChild(".magnolie-receive-" + owner.JobId);
                var staged = owner.Change(); staged["phase"] = "staging"; staged["stage_identity"] = Key(owner.stage.OriginalIdentity); owner.Save(staged);
                foreach (var file in manifest.Files) { owner.Current(); owner.files.Add(file.Id, owner.stage.CreateStagedFile(file.Id + ".part")); }
                var receiving = owner.Change(); receiving["phase"] = "receiving";
                foreach (var file in receiving["files"]!.AsArray().OfType<JsonObject>())
                {
                    file["phase"] = "receiving"; file["identity"] = Key(owner.files[TelefonMessagingContract.String(file, "id")].Observe().Identity);
                    file["checkpoint"] = new JsonObject { ["size"] = 0, ["sha256"] = Convert.ToHexString(SHA256.HashData(Array.Empty<byte>())).ToLowerInvariant() };
                }
                owner.Save(receiving); return owner;
            }
            catch { owner.Dispose(); throw; } // Keep the reserved history and actual staged bytes.
        }

        internal void ReceiveChunk(string fileId, int index, byte[] bytes)
        {
            lock (jobGate)
            {
                Current();
                if (TelefonMessagingContract.String(head!.Body, "phase") != "receiving") throw DeviceFileControl.Error("file_receive_not_receiving");
                ledger.Record(fileId, index, bytes, (id, offset, data) =>
                {
                    try { Current(); files[id].WriteChunk(offset, data); Current(); }
                    catch { uncertain = true; throw; }
                },
                    (id, offset, count) => { Current(); var data = files[id].ReadExact(offset, count); Current(); return data; });
                try
                {
                    var checkpoint = files[fileId].DurableCheckpoint(); Current();
                    var body = Change();
                    var member = body["files"]!.AsArray().OfType<JsonObject>().Single(value => TelefonMessagingContract.String(value, "id") == fileId);
                    var progress = new JsonObject { ["size"] = checkpoint.Size, ["sha256"] = checkpoint.Sha256 };
                    if (!JsonNode.DeepEquals(member["checkpoint"], progress)) { member["checkpoint"] = progress; Save(body); }
                }
                catch { uncertain = true; throw; }
            }
        }

        internal void PublishAll()
        {
            lock (jobGate)
            {
                Current();
                if (TelefonMessagingContract.String(head!.Body, "phase") != "receiving" || Manifest.Files.Any(file => ledger.Missing(file.Id).Length != 0))
                    throw DeviceFileControl.Error("file_receive_not_complete");
                try
                {
                    foreach (var file in Manifest.Files)
                    {
                        PreserveReplacementOriginal(file.Id); // Only after ALL incoming chunks are durable; before publishing any replacement.
                        var prepared = Change(); prepared["phase"] = "publishing";
                        prepared["files"]!.AsArray().OfType<JsonObject>().Single(value => TelefonMessagingContract.String(value, "id") == file.Id)["phase"] = "publishing";
                        Save(prepared); // Durable exact original intent BEFORE the native rename.
                        var observed = files[file.Id].Publish(PublicationRoot, file.Path, file.Size, file.Sha256, Current);
                        var committed = Change(); committed["phase"] = "receiving";
                        var member = committed["files"]!.AsArray().OfType<JsonObject>().Single(value => TelefonMessagingContract.String(value, "id") == file.Id);
                        if (!JsonNode.DeepEquals(member["identity"], Key(observed.Identity))) throw DeviceFileControl.Error("file_receive_original_file_changed");
                        member["phase"] = "published"; Save(committed);
                    }
                    var completed = Change(); completed["phase"] = "published"; Save(completed);
                }
                catch { uncertain = true; throw; }
            }
        }

        internal static void ValidateBody(JsonObject body, string jobId)
        {
            var fields = new List<string> { "manifest", "binding", "media_type", "destination_version", "destination", "phase", "stage_name", "stage_identity", "files" };
            if (body.ContainsKey("source_job"))
            {
                fields.Add("source_job");
                var sourceJob = TelefonProtocolContract.ExactObject(body["source_job"]!, "job_id", "job_version");
                var sourceId = TelefonMessagingContract.String(sourceJob, "job_id");
                if (sourceId.Length != 32 || sourceId.Any(c => !char.IsAsciiHexDigitLower(c)) ||
                    !DeviceFileControl.Hash(TelefonMessagingContract.String(sourceJob, "job_version"))) throw DeviceFileControl.Error("file_receive_history_invalid");
            }
            foreach (var key in new[] { "replacements", "album_root", "media", "acceptance", "saved", "source_end" }) if (body.ContainsKey(key)) fields.Add(key);
            TelefonProtocolContract.ExactObject(body, fields.ToArray());
            using var document = JsonDocument.Parse(body["manifest"]!.ToJsonString()); var manifest = DeviceFileManifest.Parse(document.RootElement);
            var kind = TelefonMessagingContract.String(body, "media_type"); MediaDestinationKind(kind);
            var phase = TelefonMessagingContract.String(body, "phase");
            if (phase is not ("reserved" or "staging" or "receiving" or "publishing" or "published") || manifest.Files.Count > 16 ||
                !DeviceFileControl.Hash(TelefonMessagingContract.String(body, "destination_version")) ||
                TelefonMessagingContract.String(body, "stage_name") != ".magnolie-receive-" + jobId || body["files"] is not JsonArray members || members.Count != manifest.Files.Count)
                throw DeviceFileControl.Error("file_receive_history_invalid");
            void Identity(JsonNode? node)
            {
                var identity = TelefonProtocolContract.ExactObject(node!, "volume", "low", "high");
                foreach (var value in identity)
                {
                    var text = TelefonMessagingContract.String(identity, value.Key);
                    if (text.Length != 16 || text.Any(c => !char.IsAsciiHexDigitLower(c))) throw DeviceFileControl.Error("file_receive_history_invalid");
                }
                if (TelefonMessagingContract.String(identity, "low") == new string('0', 16) && TelefonMessagingContract.String(identity, "high") == new string('0', 16))
                    throw DeviceFileControl.Error("file_receive_history_invalid");
            }
            if (phase == "reserved" ? body["stage_identity"] is not null : body["stage_identity"] is null) throw DeviceFileControl.Error("file_receive_history_invalid");
            if (body["stage_identity"] is not null) Identity(body["stage_identity"]);
            var destination = TelefonProtocolContract.ExactObject(body["destination"]!, "native_path", "volume_path", "identity", "token");
            _ = DeviceFileNativeDirectory.NtDirectoryName(TelefonMessagingContract.String(destination, "native_path"));
            var volumePath = TelefonMessagingContract.String(destination, "volume_path");
            if (!volumePath.StartsWith(@"\\?\Volume{", StringComparison.Ordinal) || volumePath.Length > 16048 || volumePath.Any(c => c < 32 || c == 127))
                throw DeviceFileControl.Error("file_receive_history_invalid");
            Identity(destination["identity"]);
            var bound = TelefonProtocolContract.ExactObject(body["binding"]!, "sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token");
            var binding = new DeviceTransferBinding(TelefonMessagingContract.String(bound, "sender_id"), TelefonMessagingContract.String(bound, "receiver_id"),
                TelefonMessagingContract.String(bound, "sender_identity_sha256"), TelefonMessagingContract.String(bound, "receiver_identity_sha256"),
                TelefonMessagingContract.String(bound, "permission_epoch"), TelefonMessagingContract.String(bound, "destination_token"));
            binding.Validate(); if (binding.SenderId != manifest.SenderId || binding.ReceiverId != manifest.ReceiverId ||
                binding.DestinationToken != TelefonMessagingContract.String(destination, "token")) throw DeviceFileControl.Error("file_receive_history_invalid");
            for (var index = 0; index < members.Count; index++)
            {
                var hasCheckpoint = members[index] is JsonObject item && item.ContainsKey("checkpoint");
                var member = TelefonProtocolContract.ExactObject(members[index]!, hasCheckpoint ? ["id", "phase", "identity", "checkpoint"] : ["id", "phase", "identity"]);
                var state = TelefonMessagingContract.String(member, "phase");
                if (TelefonMessagingContract.String(member, "id") != manifest.Files[index].Id || state is not ("pending" or "receiving" or "publishing" or "published") ||
                    (state == "pending") != (member["identity"] is null) || phase == "published" && state != "published" ||
                    phase is "reserved" or "staging" && state != "pending" || phase is "receiving" or "publishing" && state == "pending")
                    throw DeviceFileControl.Error("file_receive_history_invalid");
                if (member["identity"] is not null) Identity(member["identity"]);
                if (hasCheckpoint)
                {
                    var checkpoint = TelefonProtocolContract.ExactObject(member["checkpoint"]!, "size", "sha256");
                    var size = TelefonProtocolContract.Integer(checkpoint["size"]);
                    var hash = TelefonMessagingContract.String(checkpoint, "sha256");
                    if (state == "pending" || size < 0 || size > manifest.Files[index].Size ||
                        size != manifest.Files[index].Size && size % DeviceFileManifest.ChunkBytes != 0 || !DeviceFileControl.Hash(hash) ||
                        size == 0 && hash != Convert.ToHexString(SHA256.HashData(Array.Empty<byte>())).ToLowerInvariant() ||
                        state is "publishing" or "published" && size != manifest.Files[index].Size)
                        throw DeviceFileControl.Error("file_receive_checkpoint_invalid");
                }
                if (member["identity"] is not null && !JsonNode.DeepEquals(member["identity"]!["volume"], destination["identity"]!["volume"]) ||
                    body["stage_identity"] is not null && !JsonNode.DeepEquals(body["stage_identity"]!["volume"], destination["identity"]!["volume"]))
                    throw DeviceFileControl.Error("file_receive_history_invalid");
                _ = DeviceFileNativeDirectory.ReceiveLeaf(manifest.Files[index].Path);
            }
            var publishing = members.OfType<JsonObject>().Count(member => TelefonMessagingContract.String(member, "phase") == "publishing");
            if (publishing != (phase == "publishing" ? 1 : 0)) throw DeviceFileControl.Error("file_receive_history_invalid");
            ValidateNativeMediaContext(body, manifest);
            ValidateAlbumRoot(body);
            ValidateReplacements(body, manifest);
            ValidateReceipts(body, jobId);
        }

        public void Dispose()
        {
            lock (jobGate)
            {
                if (disposed) return; disposed = true;
                foreach (var file in files.Values) file.Dispose();
                foreach (var archive in replacementArchives.Values) archive.Dispose();
                stage?.Dispose(); albumDirectory?.Dispose(); root?.Dispose();
            }
        }
    }
}
