using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Live cache ownership across store instances in this process.
    private static readonly object batchNativeIoGate = new();
    private static readonly Dictionary<string, NativePreparedMediaBatch> batchNativeIoOwners = new(StringComparer.Ordinal);

    private static string AcquireBatchNativeIo(string peerId, string jobId, string bookVersion, NativePreparedMediaBatch owner)
    {
        var key = DeviceFileControl.Digest("magnolie-native-source-batch-io-v1\0", new JsonArray(peerId, jobId, bookVersion));
        lock (batchNativeIoGate)
        {
            if (!batchNativeIoOwners.TryAdd(key, owner)) throw DeviceFileControl.Error("media_source_batch_original_io_pending");
        }
        return key;
    }

    private static void ReleaseBatchNativeIo(string key, NativePreparedMediaBatch owner)
    {
        lock (batchNativeIoGate)
        {
            if (!batchNativeIoOwners.TryGetValue(key, out var current) || !ReferenceEquals(current, owner))
                throw DeviceFileControl.Error("media_source_batch_actual_io_owner_required");
            batchNativeIoOwners.Remove(key);
        }
    }

    private const int NativeBatchSourceRecordLimit = 1048576;
    // Refs #330: a distinct whole-source codec/owner on the existing protected
    // job/chunk tables. Old formats remain single-file; no old sender can adopt
    // this class, and historical rows cannot reconstruct the actual originals.
    private static DeviceFileManifest BatchManifest(JsonObject body)
    {
        using var document = JsonDocument.Parse(body["manifest"]!.ToJsonString());
        return DeviceFileManifest.Parse(document.RootElement);
    }

    private static IEnumerable<(DeviceManifestFile File, int Index)> BatchRoutes(DeviceFileManifest manifest)
    {
        foreach (var file in manifest.Files)
            for (var index = 0; (long)index * DeviceFileManifest.ChunkBytes < file.Size; index++) yield return (file, index);
    }

    private static int BatchChunkSize(DeviceManifestFile file, int index) =>
        (int)Math.Min(DeviceFileManifest.ChunkBytes, file.Size - (long)index * DeviceFileManifest.ChunkBytes);

    private static long BatchCopiedBytes(JsonObject body) => BatchRoutes(BatchManifest(body))
        .Take(body["chunks"]!.AsArray().Count).Sum(route => (long)BatchChunkSize(route.File, route.Index));

    internal static void ValidateBatchPredecessor(JsonNode? raw, string jobId)
    {
        if (raw is null) return;
        var value = TelefonProtocolContract.ExactObject(raw, "job_id", "job_version", "exchange_version", "file_id", "publication_sha256", "size", "sha256");
        if (!SourceId(TelefonMessagingContract.String(value, "job_id")) || TelefonMessagingContract.String(value, "job_id") == jobId ||
            !SourceId(TelefonMessagingContract.String(value, "file_id")) ||
            new[] { "job_version", "exchange_version", "publication_sha256", "sha256" }.Any(key => !DeviceFileControl.Hash(TelefonMessagingContract.String(value, key))) ||
            TelefonProtocolContract.Integer(value["size"]) is < 1 or > DeviceFileManifest.MaxFileBytes)
            throw DeviceFileControl.Error("media_source_batch_cache_previous_invalid");
    }

    private static JsonObject ReadBatchSourceRecord(JsonObject raw, string jobId, NativeMediaPreferenceScope scope)
    {
        var body = TelefonProtocolContract.ExactObject(raw, "format", "scope", "nonce", "provenance", "manifest", "manifest_sha256",
            "origins", "mime_types", "predecessors", "phase", "chunks");
        var manifest = BatchManifest(body);
        var provenance = TelefonProtocolContract.ExactObject(body["provenance"]!,
            "collection_root", "collection_version", "book_version", "media_type", "settings", "sending_binding");
        var binding = TelefonProtocolContract.ExactObject(provenance["sending_binding"]!,
            "sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token");
        var expectedScope = new JsonObject { ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
            ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey };
        var kind = TelefonMessagingContract.String(provenance, "media_type");
        MediaSyncSettings.ValidateStart(new JsonObject { ["format"] = 1, ["settings"] = provenance["settings"]!.DeepClone() });
        if (TelefonProtocolContract.Integer(body["format"]) != 5 || !JsonNode.DeepEquals(body["scope"], expectedScope) ||
            manifest.SourceId != jobId || manifest.SenderId != scope.LocalId || manifest.ReceiverId != scope.PeerId ||
            TelefonMessagingContract.String(body, "manifest_sha256") != manifest.Fingerprint ||
            !DeviceFileControl.Hash(TelefonMessagingContract.String(body, "nonce")) ||
            !DeviceFileControl.Hash(TelefonMessagingContract.String(provenance, "book_version")) ||
            TelefonMessagingContract.String(binding, "sender_id") != scope.LocalId || TelefonMessagingContract.String(binding, "receiver_id") != scope.PeerId ||
            TelefonMessagingContract.String(binding, "sender_identity_sha256") != scope.LocalKey ||
            TelefonMessagingContract.String(binding, "receiver_identity_sha256") != scope.PeerKey ||
            !DeviceFileControl.Hash(TelefonMessagingContract.String(binding, "permission_epoch")) ||
            !DeviceFileControl.Hash(TelefonMessagingContract.String(binding, "destination_token")) ||
            !MediaSyncSettings.TransferRequestedFor(provenance["settings"]!.AsObject(), kind, toPhone: true) ||
            MediaSyncSettings.Effective(provenance["settings"]!.AsObject())["collection_mode"]!.GetValue<string>() != "entire_collection" ||
            body["origins"] is not JsonObject origins || body["mime_types"] is not JsonObject mime ||
            body["predecessors"] is not JsonObject previous || body["chunks"] is not JsonArray chunks ||
            !manifest.Files.Select(file => file.Id).ToHashSet(StringComparer.Ordinal).SetEquals(origins.Select(pair => pair.Key)) ||
            !origins.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(mime.Select(pair => pair.Key)) ||
            !origins.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(previous.Select(pair => pair.Key)) ||
            TelefonMessagingContract.String(body, "phase") is not ("planned" or "ready"))
            throw DeviceFileControl.Error("media_source_batch_cache_record_invalid");
        var identities = new HashSet<DeviceFileNativeDirectory.Identity>();
        foreach (var file in manifest.Files)
        {
            ValidateLocalCollectionOrigin(origins[file.Id]!, provenance);
            var origin = origins[file.Id]!.AsObject();
            ValidateBatchPredecessor(previous[file.Id], jobId);
            if (TelefonProtocolContract.Integer(origin["format"]) != 2 || origin["relative_path"]!.GetValue<string>() != file.Path ||
                !identities.Add(NativeMediaReceiveJob.NativeAlbumIdentity(origin["file_identity"]!.AsObject())) ||
                mime[file.Id] is not JsonValue type || !type.TryGetValue<string>(out var mediaMime) ||
                !(kind == "images" ? mediaMime is "image/jpeg" or "image/png" :
                    kind == "video" && mediaMime is "video/mp4" or "video/quicktime"))
                throw DeviceFileControl.Error("media_source_batch_cache_original_members_required");
        }
        var routes = BatchRoutes(manifest).ToArray();
        if (chunks.Count > routes.Length || body["phase"]!.GetValue<string>() == "ready" && chunks.Count != routes.Length)
            throw DeviceFileControl.Error("media_source_batch_cache_record_invalid");
        for (var number = 0; number < chunks.Count; number++)
        {
            var chunk = TelefonProtocolContract.ExactObject(chunks[number]!, "file_id", "index", "sha256");
            if (TelefonMessagingContract.String(chunk, "file_id") != routes[number].File.Id ||
                TelefonProtocolContract.Integer(chunk["index"]) != routes[number].Index ||
                !DeviceFileControl.Hash(TelefonMessagingContract.String(chunk, "sha256")))
                throw DeviceFileControl.Error("media_source_batch_cache_original_chunks_required");
        }
        return body;
    }

    internal sealed partial class NativePreparedMediaBatch : IDisposable
    {
        private readonly object cacheGate = new(), endGate = new();
        private readonly NativeCollectionMediaBatch source;
        private readonly TelefonStore store;
        private readonly NativeMediaPreferenceScope scope;
        private readonly (DeviceManifestFile File, int Index)[] routes;
        private readonly Dictionary<(string, int), int> numbers;
        private JsonObject record;
        private string version = "";
        private volatile bool retired, sourceIoEnded;
        private bool sendAttempted;
        private string? nativeIoKey;
        private bool retirementIo;
        internal DeviceFileManifest Manifest { get; }
        internal string JobId => Manifest.SourceId;
        internal object ConnectionOwner => source.ConnectionOwner;
        internal string PeerId => scope.PeerId;
        internal TelefonStore OwnerStore => store;
        internal PendingSavedPhotoBatch? Recovery { get; private init; }
        internal string Nonce { get { lock (cacheGate) { Require(); return record["nonce"]!.GetValue<string>(); } } }
        internal string Version { get { lock (cacheGate) { Require(); return version; } } }
        internal JsonObject Observation { get { lock (cacheGate) { Require(); return record.DeepClone().AsObject(); } } }

        internal void RequireBackupIdentity(string expectedVersion, string expectedNonce)
        {
            lock (cacheGate)
            {
                Require();
                CheckBackupIdentity(expectedVersion, expectedNonce);
            }
        }

        private void CheckBackupIdentity(string expectedVersion, string expectedNonce)
        {
            if (version != expectedVersion || record["nonce"]!.GetValue<string>() != expectedNonce || record["phase"]!.GetValue<string>() != "ready")
                throw DeviceFileControl.Error("media_backup_original_batch_owner_required");
        }

        internal (string Version, string Nonce) CaptureBackupIdentity()
        {
            lock (cacheGate)
            {
                Require();
                var nonce = record["nonce"]!.GetValue<string>();
                CheckBackupIdentity(version, nonce);
                return (version, nonce);
            }
        }

        internal byte[] ReadBackupChunk(string fileId, int index, string expectedVersion, string expectedNonce)
        {
            lock (cacheGate)
            {
                CheckBackupIdentity(expectedVersion, expectedNonce);
                return ReadChunk(fileId, index); // Checks both protected head and live source before and after IO.
            }
        }

        internal Dictionary<string, JsonObject> RetirementBackupProvenances()
        {
            lock (cacheGate) { Require(); return Manifest.Files.ToDictionary(file => file.Id, BackupProvenance, StringComparer.Ordinal); }
        }

        internal bool HasOriginalSource(NativeCollectionMediaBatch candidate) => ReferenceEquals(source, candidate);

        internal void RunRetirementScope(NativeBatchSourceRetirement owner)
        {
            // The same order as actual Dispose, then original IO, then store.
            // No store lock is held while awaiting an earlier native reader.
            lock (endGate)
            {
                retirementIo = true;
                try { lock (cacheGate) source.RunRetirementScope(owner); }
                finally { retirementIo = false; ReleaseNativeIoIfDrained(); }
            }
        }

        internal void DrainForRetirement(NativeBatchSourceRetirement owner)
        {
            owner.Current(); source.BindRetirementDrain(owner);
            Dispose(); // Actual reader/backup IO return and ALL original handles, never a flag-only drain.
        }

        internal void RequireEndedRetirement(NativeBatchSourceRetirement owner)
        {
            RequireIoEnded(); source.RequireRetirementAuthority(owner);
        }

        internal void VerifyRetirementCiphers(NativeBatchSourceRetirement owner, bool ended)
        {
            lock (cacheGate)
            {
                owner.Current();
                if (!ended) { VerifyCipherSet(); return; }
                using var db = store.OpenNativeMediaDatabase(); db.Open(); _ = ReadHead(db, null);
                using var read = db.CreateCommand();
                read.CommandText = "SELECT number,value FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job ORDER BY number";
                read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", JobId);
                using var rows = read.ExecuteReader(); var number = 0;
                while (rows.Read())
                {
                    owner.Current();
                    if (number >= routes.Length || rows.GetInt32(0) != number || rows[1] is not byte[] cipher ||
                        cipher.Length != BatchChunkSize(routes[number].File, routes[number].Index) + 28 ||
                        SourceDigest(cipher) != record["chunks"]![number]!["sha256"]!.GetValue<string>())
                        throw DeviceFileControl.Error("media_source_batch_cache_original_chunks_required");
                    number++;
                }
                if (number != routes.Length) throw DeviceFileControl.Error("media_source_batch_cache_original_chunks_required");
                owner.Current(); // Opaque cipher verification only; no ended raw reader reconstructed.
            }
        }

        internal void BeginSendAttempt(TelefonConnection connection)
        {
            lock (cacheGate)
            {
                Require();
                if (!ReferenceEquals(ConnectionOwner, connection) || sendAttempted)
                    throw DeviceFileControl.Error("media_source_exchange_original_attempt_required");
                sendAttempted = true;
            }
        }

        internal JsonObject CreateMediaOffer(long now)
        {
            lock (cacheGate)
            {
                if (Recovery is not null) throw DeviceFileControl.Error("media_source_batch_recovery_read_only");
                Require(); VerifyCipherSet();
                var origins = new JsonObject();
                foreach (var pair in record["origins"]!.AsObject())
                    origins[pair.Key] = new JsonObject { ["format"] = 1, ["origin_sha256"] = PcOriginDigest(pair.Value!.AsObject()),
                        ["previous_publication_sha256"] = record["predecessors"]![pair.Key]?["publication_sha256"]?.DeepClone() };
                return MediaOfferEnvelope.Create(Manifest, record["provenance"]!["settings"]!.AsObject(), record["provenance"]!["media_type"]!.GetValue<string>(),
                    record["mime_types"]!.DeepClone().AsObject(), new JsonObject(), now, pcOrigins: origins, pcBatch: true);
            }
        }

        private NativePreparedMediaBatch(NativeCollectionMediaBatch source, NativeMediaPreferenceScope scope, JsonObject record)
        {
            this.source = source; store = source.Store; this.scope = scope; this.record = record;
            Manifest = BatchManifest(record); routes = BatchRoutes(Manifest).ToArray();
            numbers = routes.Select((route, number) => (route, number)).ToDictionary(item => (item.route.File.Id, item.route.Index), item => item.number);
        }

        private void Current()
        {
            if (retired || sourceIoEnded) throw DeviceFileControl.Error("media_source_batch_cache_retired");
            source.Require(); store.RequireNativeMediaStorageKey();
            if (store.MediaPreferenceScope(scope.PeerId) != scope) throw DeviceFileControl.Error("media_source_cache_scope_changed");
        }

        private JsonObject ReadHead(SqliteConnection db, SqliteTransaction? transaction)
        {
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT value FROM native_media_source_jobs WHERE peer_id=$peer AND job_id=$job";
            read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", JobId);
            if (read.ExecuteScalar() is not byte[] cipher || SourceDigest(cipher) != version)
                throw DeviceFileControl.Error("media_source_cache_original_record_required");
            var actual = store.ReadSourceRecord(cipher, scope.PeerId, JobId, scope);
            if (!JsonNode.DeepEquals(actual, record)) throw DeviceFileControl.Error("media_source_cache_original_record_required");
            return actual;
        }

        internal void Require() => RequireHeads(null);

        // One synchronous protected read scope for BOTH pinned heads. Native
        // originals/book/control/key checks still bracket the actual DB read;
        // nesting three complete root traversals grants no extra authority.
        internal void RequireHeads(Action<SqliteConnection, SqliteTransaction>? additionalHead)
        {
            lock (cacheGate)
                try
                {
                    Current();
                    lock (store.gate)
                    {
                        using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
                        _ = ReadHead(db, transaction); additionalHead?.Invoke(db, transaction); transaction.Commit();
                    }
                    Current();
                }
                catch { retired = true; throw; }
        }

        private string ChunkContext(int number) => scope.PeerId + "/" + JobId + "/" + record["nonce"]!.GetValue<string>() +
            "/batch/" + routes[number].File.Id + "/" + routes[number].Index.ToString(System.Globalization.CultureInfo.InvariantCulture);

        private byte[] ReadCore(int number)
        {
            Require();
            if (number < 0 || number >= record["chunks"]!.AsArray().Count) throw DeviceFileControl.Error("media_source_cache_chunk_bounds");
            byte[] cipher; var wanted = BatchChunkSize(routes[number].File, routes[number].Index);
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open(); _ = ReadHead(db, null);
                using var read = db.CreateCommand();
                read.CommandText = "SELECT value FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job AND number=$number AND length(value)=$length";
                read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", JobId);
                read.Parameters.AddWithValue("$number", number); read.Parameters.AddWithValue("$length", wanted + 28);
                cipher = read.ExecuteScalar() as byte[] ?? throw DeviceFileControl.Error("media_source_cache_original_chunk_required");
            }
            if (SourceDigest(cipher) != record["chunks"]![number]!["sha256"]!.GetValue<string>())
                throw DeviceFileControl.Error("media_source_cache_chunk_changed");
            var bytes = store.Open("native_media_source_chunk", ChunkContext(number), cipher);
            try { if (bytes.Length != wanted) throw DeviceFileControl.Error("media_source_cache_chunk_changed"); Require(); return bytes; }
            catch { CryptographicOperations.ZeroMemory(bytes); throw; }
        }

        internal byte[] ReadChunk(string fileId, int index)
        {
            lock (cacheGate)
                try
                {
                    if (Recovery is not null || record["phase"]!.GetValue<string>() != "ready" || !numbers.TryGetValue((fileId, index), out var number))
                        throw DeviceFileControl.Error("media_source_batch_cache_exact_route_required");
                    return ReadCore(number);
                }
                catch { retired = true; throw; }
        }

        private void Write(JsonObject next, int? number = null, byte[]? payload = null)
        {
            Current();
            byte[]? chunk = number is int n ? store.Seal("native_media_source_chunk", ChunkContext(n), payload!) : null;
            if (chunk is not null)
                next["chunks"]!.AsArray().Add(new JsonObject { ["file_id"] = routes[number!.Value].File.Id,
                    ["index"] = routes[number.Value].Index, ["sha256"] = SourceDigest(chunk) });
            var clear = TelefonCrypto.Canonical(next); byte[] cipher;
            try
            {
                if (clear.Length > NativeBatchSourceRecordLimit) throw DeviceFileControl.Error("media_source_cache_record_bound");
                cipher = store.Seal("native_media_source_job", scope.PeerId + "/" + JobId, clear);
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
            _ = store.ReadSourceRecord(cipher, scope.PeerId, JobId, scope);
            lock (store.gate)
            {
                Current(); using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
                if (version.Length != 0)
                {
                    _ = ReadHead(db, transaction);
                    if (next["phase"]!.GetValue<string>() == "ready")
                    {
                        var retained = store.SourceRecords(db, transaction, scope).Where(item => item.JobId != JobId).ToList();
                        if (!JsonNode.DeepEquals(record["predecessors"], store.CompletedBatchPredecessors(db, transaction, scope, retained, record, Manifest)))
                            throw DeviceFileControl.Error("media_source_cache_previous_changed");
                        VerifyCipherSet(db, transaction);
                    }
                }
                else
                {
                    var previous = store.SourceRecords(db, transaction, scope);
                    RequireLocalSourceGenerationHistory(previous, record);
                    if (previous.Count >= NativeSourceHistoryLimit || previous.Any(item => item.JobId == JobId) ||
                        previous.Sum(item => TelefonProtocolContract.Integer(item.Body["manifest"]!["total_bytes"])) + Manifest.TotalBytes > NativeSourceCacheLimit)
                        throw DeviceFileControl.Error("media_source_cache_original_preparation_required");
                    if (!JsonNode.DeepEquals(record["predecessors"], store.CompletedBatchPredecessors(db, transaction, scope, previous, record, Manifest)))
                        throw DeviceFileControl.Error("media_source_cache_previous_changed");
                }
                using var write = db.CreateCommand(); write.Transaction = transaction;
                write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_source_jobs(peer_id TEXT NOT NULL,job_id TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,job_id)); " +
                    "CREATE TABLE IF NOT EXISTS native_media_source_chunks(peer_id TEXT NOT NULL,job_id TEXT NOT NULL,number INTEGER NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,job_id,number)); " +
                    "INSERT INTO native_media_source_jobs(peer_id,job_id,value) VALUES($peer,$job,$value) ON CONFLICT(peer_id,job_id) DO UPDATE SET value=excluded.value";
                write.Parameters.AddWithValue("$peer", scope.PeerId); write.Parameters.AddWithValue("$job", JobId); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
                if (chunk is not null)
                {
                    write.Parameters.Clear(); write.CommandText = "INSERT INTO native_media_source_chunks(peer_id,job_id,number,value) VALUES($peer,$job,$number,$value)";
                    write.Parameters.AddWithValue("$peer", scope.PeerId); write.Parameters.AddWithValue("$job", JobId);
                    write.Parameters.AddWithValue("$number", number!.Value); write.Parameters.AddWithValue("$value", chunk); write.ExecuteNonQuery();
                }
                Current(); transaction.Commit(); record = next; version = SourceDigest(cipher); _ = ReadHead(db, null); Current();
            }
        }

        private void VerifyCipherSet()
        {
            Current();
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open();
                VerifyCipherSet(db, null);
            }
            Current();
        }

        private void VerifyCipherSet(SqliteConnection db, SqliteTransaction? transaction)
        {
                _ = ReadHead(db, transaction);
                using var read = db.CreateCommand(); read.Transaction = transaction;
                read.CommandText = "SELECT number,value FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job ORDER BY number";
                read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", JobId);
                using var rows = read.ExecuteReader(); var number = 0;
                while (rows.Read())
                {
                    Current();
                    if (number >= routes.Length || rows.GetInt32(0) != number || rows[1] is not byte[] cipher ||
                        cipher.Length != BatchChunkSize(routes[number].File, routes[number].Index) + 28 ||
                        SourceDigest(cipher) != record["chunks"]![number]!["sha256"]!.GetValue<string>())
                        throw DeviceFileControl.Error("media_source_batch_cache_original_chunks_required");
                    number++;
                }
                if (number != routes.Length) throw DeviceFileControl.Error("media_source_batch_cache_original_chunks_required");
        }

        private void Freeze()
        {
            Write(record.DeepClone().AsObject()); // One durable whole reservation before any payload copy.
            for (var number = 0; number < routes.Length; number++)
            {
                var bytes = source.ReadChunk(routes[number].File.Id, routes[number].Index);
                try { Write(record.DeepClone().AsObject(), number, bytes); }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            var numberRead = 0;
            foreach (var file in Manifest.Files)
            {
                using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                for (var index = 0; (long)index * DeviceFileManifest.ChunkBytes < file.Size; index++)
                {
                    var bytes = ReadCore(numberRead++);
                    try { digest.AppendData(bytes); } finally { CryptographicOperations.ZeroMemory(bytes); }
                }
                if (Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != file.Sha256)
                    throw DeviceFileControl.Error("media_source_cache_content_changed");
            }
            VerifyCipherSet();
            var ready = record.DeepClone().AsObject(); ready["phase"] = "ready"; Write(ready); Require();
        }

        internal static NativePreparedMediaBatch Create(NativeCollectionMediaBatch source)
        {
            source.Require(); var scope = source.Store.MediaPreferenceScope(source.PeerId); var manifest = source.PrepareManifest();
            var wire = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())["body"]!["manifest"]!.DeepClone();
            var mime = new JsonObject(); var previous = new JsonObject();
            foreach (var pair in source.MimeTypes) { mime[pair.Key] = pair.Value; previous[pair.Key] = null; }
            var body = new JsonObject { ["format"] = 5, ["scope"] = new JsonObject { ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey,
                ["pairing_epoch"] = scope.PairingEpoch, ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey },
                ["nonce"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), ["provenance"] = source.Provenance,
                ["manifest"] = wire, ["manifest_sha256"] = manifest.Fingerprint, ["origins"] = source.OriginalOrigins,
                ["mime_types"] = mime, ["predecessors"] = previous, ["phase"] = "planned", ["chunks"] = new JsonArray() };
            lock (source.Store.gate)
            {
                source.Require(); using var db = source.Store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
                body["predecessors"] = source.Store.CompletedBatchPredecessors(db, transaction, scope, source.Store.SourceRecords(db, transaction, scope), body, manifest);
                source.Require(); transaction.Commit();
            }
            if (manifest.Files.All(file => body["predecessors"]![file.Id] is JsonObject old &&
                TelefonProtocolContract.Integer(old["size"]) == file.Size && old["sha256"]!.GetValue<string>() == file.Sha256))
                throw DeviceFileControl.Error("media_source_batch_latest_payload_already_sent");
            var result = new NativePreparedMediaBatch(source, scope, body);
            try
            {
                result.nativeIoKey = AcquireBatchNativeIo(scope.PeerId, manifest.SourceId, body["provenance"]!["book_version"]!.GetValue<string>(), result);
                result.Freeze(); return result;
            }
            catch { result.Dispose(); throw; } // Keep every planned/partial row; no restart adoption.
        }

        internal static NativePreparedMediaBatch? AttachSaved(NativeCollectionMediaBatch source)
        {
            source.Require(); var store = source.Store; var scope = store.MediaPreferenceScope(source.PeerId);
            var origins = source.OriginalOrigins;
            PendingSavedPhotoBatch? pending;
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
                var records = store.SourceRecords(db, transaction, scope);
                pending = new BatchHistory(store, db, transaction, scope, records).FindSavedPhotos(origins);
                transaction.Commit();
            }
            if (pending is null) return null;
            var historical = pending.Job["provenance"]!.DeepClone().AsObject();
            var live = source.Provenance;
            // A reconnect can negotiate a different bilateral file epoch. No
            // other part of the journal's native provenance may change.
            historical["sending_binding"]!["permission_epoch"] = live["sending_binding"]!["permission_epoch"]!.DeepClone();
            if (!JsonNode.DeepEquals(historical, live)) throw DeviceFileControl.Error("media_source_batch_recovery_provenance_changed");
            var actual = source.PrepareManifest().Files.ToDictionary(file => file.Path, StringComparer.Ordinal);
            var mime = source.MimeTypes;
            var result = new NativePreparedMediaBatch(source, scope, pending.Job) { version = pending.JobVersion, Recovery = pending };
            try
            {
                if (result.Manifest.Files.Count != actual.Count || result.Manifest.Files.Any(file =>
                    !actual.TryGetValue(file.Path, out var current) || current.Size != file.Size || current.Sha256 != file.Sha256 ||
                    !JsonNode.DeepEquals(origins[current.Id], pending.Job["origins"]![file.Id]) ||
                    mime[current.Id] != pending.Job["mime_types"]![file.Id]!.GetValue<string>()))
                    throw DeviceFileControl.Error("media_source_batch_recovery_original_changed");
                result.nativeIoKey = AcquireBatchNativeIo(scope.PeerId, result.JobId, live["book_version"]!.GetValue<string>(), result);
                result.VerifyCipherSet();
                return result;
            }
            catch { result.Dispose(); throw; }
        }

        internal void RequireIoEnded()
        {
            if (!retired || !sourceIoEnded) throw DeviceFileControl.Error("media_source_cache_io_pending");
            store.RequireNativeMediaStorageKey();
            lock (store.gate) { using var db = store.OpenNativeMediaDatabase(); db.Open(); _ = ReadHead(db, null); }
        }

        public void Dispose()
        {
            retired = true;
            lock (endGate)
            {
                if (sourceIoEnded) { ReleaseNativeIoIfDrained(); return; }
                lock (cacheGate) { } // Actual reader return, not a cancellation flag.
                source.CloseOriginalsForCache(this); sourceIoEnded = true;
                ReleaseNativeIoIfDrained();
            }
        }

        private void ReleaseNativeIoIfDrained()
        {
            if (!sourceIoEnded || retirementIo || nativeIoKey is null) return;
            ReleaseBatchNativeIo(nativeIoKey, this); nativeIoKey = null;
        }
    }
}
