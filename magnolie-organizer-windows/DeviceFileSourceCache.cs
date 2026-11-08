using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    private const int NativeSourceHistoryLimit = 128, NativeSourceRecordLimit = 131072;
    private const long NativeSourceCacheLimit = DeviceFileManifest.MaxTotalBytes;
    private static string SourceDigest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static bool SourceId(string text) => text.Length == 32 && text.All(char.IsAsciiHexDigitLower);

    private JsonObject ReadSourceRecord(byte[] cipher, string peerId, string jobId, NativeMediaPreferenceScope scope)
    {
        if (cipher.Length is < 29 or > NativeSourceRecordLimit + 28 || !SourceId(jobId))
            throw DeviceFileControl.Error("media_source_cache_record_invalid");
        var plain = Open("native_media_source_job", peerId + "/" + jobId, cipher);
        try
        {
            var raw = JsonNode.Parse(plain)!.AsObject();
            var successor = TelefonProtocolContract.Integer(raw["format"]) == 2;
            var fields = new[] { "format", "scope", "nonce", "provenance", "manifest", "manifest_sha256", "originals", "phase", "chunks" };
            var body = TelefonProtocolContract.ExactObject(raw, successor ? fields.Concat(new[] { "previous" }).ToArray() : fields);
            if (successor)
            {
                var previous = TelefonProtocolContract.ExactObject(body["previous"]!, "job_id", "job_version", "exchange_version");
                if (!SourceId(TelefonMessagingContract.String(previous, "job_id")) || previous["job_id"]!.GetValue<string>() == jobId ||
                    !DeviceFileControl.Hash(TelefonMessagingContract.String(previous, "job_version")) ||
                    !DeviceFileControl.Hash(TelefonMessagingContract.String(previous, "exchange_version")))
                    throw DeviceFileControl.Error("media_source_cache_previous_invalid");
            }
            var expectedScope = new JsonObject { ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
                ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey };
            using var document = JsonDocument.Parse(body["manifest"]!.ToJsonString());
            var manifest = DeviceFileManifest.Parse(document.RootElement);
            var provenance = TelefonProtocolContract.ExactObject(body["provenance"]!, "mapping_job", "mapping_version", "mapping_file", "book_version", "media_type", "settings", "sending_binding");
            var binding = TelefonProtocolContract.ExactObject(provenance["sending_binding"]!, "sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token");
            var kind = TelefonMessagingContract.String(provenance, "media_type");
            MediaSyncSettings.ValidateStart(new JsonObject { ["format"] = 1, ["settings"] = provenance["settings"]!.DeepClone() });
            if (TelefonProtocolContract.Integer(body["format"]) != (successor ? 2 : 1) || !JsonNode.DeepEquals(body["scope"], expectedScope) ||
                !DeviceFileControl.Hash(TelefonMessagingContract.String(body, "nonce")) || manifest.SourceId != jobId || manifest.Files.Count != 1 ||
                manifest.SenderId != scope.LocalId || manifest.ReceiverId != peerId || TelefonMessagingContract.String(body, "manifest_sha256") != manifest.Fingerprint ||
                TelefonMessagingContract.String(binding, "sender_id") != scope.LocalId || TelefonMessagingContract.String(binding, "receiver_id") != scope.PeerId ||
                TelefonMessagingContract.String(binding, "sender_identity_sha256") != scope.LocalKey || TelefonMessagingContract.String(binding, "receiver_identity_sha256") != scope.PeerKey ||
                !DeviceFileControl.Hash(TelefonMessagingContract.String(binding, "permission_epoch")) || !DeviceFileControl.Hash(TelefonMessagingContract.String(binding, "destination_token")) ||
                !SourceId(TelefonMessagingContract.String(provenance, "mapping_job")) || !SourceId(TelefonMessagingContract.String(provenance, "mapping_file")) ||
                !DeviceFileControl.Hash(TelefonMessagingContract.String(provenance, "mapping_version")) || !DeviceFileControl.Hash(TelefonMessagingContract.String(provenance, "book_version")) ||
                !MediaSyncSettings.TransferRequestedFor(provenance["settings"]!.AsObject(), kind, toPhone: true) ||
                body["originals"] is not JsonObject originals || originals.Count != 1 || originals[manifest.Files[0].Id] is not JsonObject original ||
                !ValidSourceOriginal(original, kind) ||
                body["chunks"] is not JsonArray chunks || chunks.Count > (manifest.TotalBytes + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes ||
                chunks.Any(value => value is not JsonValue hash || !hash.TryGetValue<string>(out var text) || !DeviceFileControl.Hash(text)) ||
                TelefonMessagingContract.String(body, "phase") is not ("planned" or "ready") ||
                body["phase"]!.GetValue<string>() == "ready" && chunks.Count != (manifest.TotalBytes + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes)
                throw DeviceFileControl.Error("media_source_cache_record_invalid");
            return body;
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private static bool ValidSourceOriginal(JsonObject original, string kind)
    {
        TelefonProtocolContract.ExactObject(original, "source_epoch", "photo_id", "media_type", "manifest_sha256", "file_id", "original_size", "original_sha256", "receipt_sha256");
        return original["media_type"]?.GetValue<string>() == kind && SourceId(TelefonMessagingContract.String(original, "file_id")) &&
            TelefonProtocolContract.Integer(original["original_size"]) is >= 1 and <= DeviceFileManifest.MaxFileBytes &&
            new[] { "source_epoch", "photo_id", "manifest_sha256", "original_sha256", "receipt_sha256" }.All(key => DeviceFileControl.Hash(TelefonMessagingContract.String(original, key)));
    }

    internal IReadOnlyList<(string JobId, string Version, string Phase)> NativeMediaSourceHistory(string peerId)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            using var transaction = db.BeginTransaction(deferred: true);
            var result = SourceRecords(db, transaction, scope).Select(item => (item.JobId, SourceDigest(item.Cipher), item.Body["phase"]!.GetValue<string>())).ToArray();
            transaction.Commit(); return result;
        }
    }

    private List<(string JobId, byte[] Cipher, JsonObject Body)> SourceRecords(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope)
    {
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('native_media_source_jobs','native_media_source_chunks')";
        var tables = Convert.ToInt32(read.ExecuteScalar());
        if (tables == 0) return [];
        if (tables != 2) throw DeviceFileControl.Error("media_source_cache_original_storage_required");
        read.CommandText = "SELECT job_id,length(value),value FROM native_media_source_jobs WHERE peer_id=$peer ORDER BY job_id";
        read.Parameters.AddWithValue("$peer", scope.PeerId);
        using var rows = read.ExecuteReader(); var result = new List<(string, byte[], JsonObject)>();
        while (rows.Read())
        {
            if (result.Count >= NativeSourceHistoryLimit) throw DeviceFileControl.Error("media_source_cache_history_bound");
            if (rows.GetInt64(1) is < 29 or > NativeSourceRecordLimit + 28) throw DeviceFileControl.Error("media_source_cache_record_invalid");
            var id = rows.GetString(0); var cipher = (byte[])rows[2];
            result.Add((id, cipher, ReadSourceRecord(cipher, scope.PeerId, id, scope)));
        }
        rows.Close();
        read.CommandText = "SELECT count(*) FROM native_media_source_chunks AS chunks WHERE peer_id=$peer AND NOT EXISTS " +
            "(SELECT 1 FROM native_media_source_jobs AS jobs WHERE jobs.peer_id=chunks.peer_id AND jobs.job_id=chunks.job_id)";
        if (Convert.ToInt64(read.ExecuteScalar()) != 0) throw DeviceFileControl.Error("media_source_cache_original_record_required");
        read.Parameters.AddWithValue("$job", "");
        foreach (var (id, _, body) in result)
        {
            read.Parameters["$job"].Value = id;
            read.CommandText = "SELECT count(*),COALESCE(min(number),0),COALESCE(max(number),-1),COALESCE(sum(length(value)),0) " +
                "FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job";
            using var chunks = read.ExecuteReader();
            var count = body["chunks"]!.AsArray().Count;
            var size = TelefonProtocolContract.Integer(body["manifest"]!["total_bytes"]);
            if (!chunks.Read() || chunks.GetInt64(0) != count || chunks.GetInt64(1) != 0 || chunks.GetInt64(2) != count - 1 ||
                chunks.GetInt64(3) != Math.Min((long)count * DeviceFileManifest.ChunkBytes, size) + 28L * count)
                throw DeviceFileControl.Error("media_source_cache_chunk_membership_changed");
        }
        return result;
    }

    // Scheduling/preparation lineage only. Historical END never substitutes for
    // the new source's own original-book/current-control/held-file authority.
    private JsonObject? CompletedSourcePredecessor(SqliteConnection db, SqliteTransaction transaction, NativeMediaPreferenceScope scope,
        List<(string JobId, byte[] Cipher, JsonObject Body)> records, JsonObject originals, DeviceFileManifest nextManifest)
    {
        static string Text(JsonObject value, string name) => TelefonMessagingContract.String(value, name);
        static InvalidDataException Error() => DeviceFileControl.Error("media_source_cache_completed_previous_required");
        var matching = records.Where(item => JsonNode.DeepEquals(item.Body["originals"]!.AsObject().Single().Value, originals.Single().Value)).ToArray();
        if (matching.Length == 0) return null;
        using (var schema = db.CreateCommand())
        {
            schema.Transaction = transaction;
            schema.CommandText = "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='native_media_source_exchanges'";
            if (Convert.ToInt32(schema.ExecuteScalar()) != 1) throw Error();
        }
        var endVersions = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var previous in matching)
        {
            if (Text(previous.Body, "phase") != "ready") throw Error();
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job AND length(value) BETWEEN 29 AND 32796";
            read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", previous.JobId);
            if (read.ExecuteScalar() is not byte[] cipher) throw Error();
            var clear = Open("native_media_source_exchange", scope.PeerId + "/" + previous.JobId, cipher);
            try
            {
                var exchange = TelefonProtocolContract.ExactObject(JsonNode.Parse(clear)!, "format", "cache_version", "nonce", "offer", "permission_epoch",
                    "phase", "acceptance", "sent_chunks", "pending_chunk", "peer_saved", "peer_readback", "source_end");
                var end = TelefonProtocolContract.ExactObject(exchange["source_end"]!, "format", "job_id", "cache_version", "nonce", "readback_sha256");
                var readback = exchange["peer_readback"] as JsonObject ?? throw Error();
                var epoch = Text(exchange, "permission_epoch");
                var originalBinding = previous.Body["provenance"]!["sending_binding"]!.AsObject();
                var binding = new DeviceTransferBinding(scope.LocalId, scope.PeerId, scope.LocalKey, scope.PeerKey, epoch, Text(readback, "destination_token"));
                var context = new JsonObject(readback.Where(pair => pair.Key is not ("destination_token" or "binding_sha256" or "readback_sha256"))
                    .Select(pair => KeyValuePair.Create(pair.Key, pair.Value?.DeepClone())));
                var offer = exchange["offer"]!.AsObject();
                var media = MediaOfferEnvelope.Validate(offer, scope.LocalId, scope.PeerId, TelefonProtocolContract.Integer(offer["created_ms"]));
                var receipt = exchange["peer_saved"]!["receipts"]!.AsArray().Single()!.AsObject();
                if (TelefonProtocolContract.Integer(exchange["format"]) != 1 || Text(exchange, "phase") != "source_ended" ||
                    Text(exchange, "cache_version") != SourceDigest(previous.Cipher) || exchange["nonce"]?.ToJsonString() != previous.Body["nonce"]?.ToJsonString() ||
                    TelefonProtocolContract.Integer(end["format"]) != 1 || Text(end, "job_id") != previous.JobId ||
                    !JsonNode.DeepEquals(end["cache_version"], exchange["cache_version"]) || !JsonNode.DeepEquals(end["nonce"], exchange["nonce"]) ||
                    Text(end, "readback_sha256") != Text(readback, "readback_sha256") || exchange["pending_chunk"] is not null ||
                    media.Manifest.Fingerprint != Text(previous.Body, "manifest_sha256") || Text(readback, "manifest_sha256") != media.Manifest.Fingerprint ||
                    Text(readback, "offer_id") != Text(offer, "message_id") || Text(readback, "media_type") != media.MediaType ||
                    Text(readback, "publication_sha256") != Text(receipt, "receipt_sha256") ||
                    Text(originalBinding, "permission_epoch") != epoch || !JsonNode.DeepEquals(DevicePublishedReadbackEnvelope.EncodeBody(context, binding), readback))
                    throw Error();
                var file = media.Manifest.Files.Single();
                if (Text(readback, "file_id") != file.Id || Text(readback, "sha256") != file.Sha256 || TelefonProtocolContract.Integer(readback["size"]) != file.Size ||
                    Text(readback, "transfer_id") != media.Manifest.TransferId || Text(readback, "source_id") != media.Manifest.SourceId ||
                    Text(readback, "mime_type") != media.MimeTypes[file.Id]!.GetValue<string>()) throw Error();
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
            endVersions.Add(previous.JobId, SourceDigest(cipher));
            // Preserve and authenticate every prior cache chunk; a newer version
            // must not conceal a missing/corrupt recovery copy.
            read.CommandText = "SELECT number,value FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job ORDER BY number";
            using var chunks = read.ExecuteReader(); var index = 0; var hashes = previous.Body["chunks"]!.AsArray();
            while (chunks.Read())
            {
                if (index >= hashes.Count || chunks.GetInt32(0) != index || chunks[1] is not byte[] chunk || SourceDigest(chunk) != hashes[index]!.GetValue<string>()) throw Error();
                index++;
            }
            if (index != hashes.Count) throw Error();
        }
        var byId = matching.ToDictionary(item => item.JobId, StringComparer.Ordinal);
        var referenced = new HashSet<string>(StringComparer.Ordinal);
        foreach (var previous in matching)
            if (previous.Body["previous"] is JsonObject link)
            {
                var id = Text(link, "job_id");
                if (!byId.TryGetValue(id, out var parent) || Text(link, "job_version") != SourceDigest(parent.Cipher) ||
                    Text(link, "exchange_version") != endVersions[id] || !referenced.Add(id)) throw Error();
            }
        var leaves = matching.Where(item => !referenced.Contains(item.JobId)).ToArray();
        if (leaves.Length != 1) throw Error();
        var leaf = leaves[0]; var visited = new HashSet<string>(StringComparer.Ordinal); var cursor = leaf;
        while (true)
        {
            if (!visited.Add(cursor.JobId)) throw Error();
            if (cursor.Body["previous"] is not JsonObject link) break;
            cursor = byId[Text(link, "job_id")];
        }
        if (visited.Count != matching.Length) throw Error();
        var latest = leaf.Body["manifest"]!["files"]!.AsArray().Single()!.AsObject(); var next = nextManifest.Files.Single();
        if (Text(latest, "sha256") == next.Sha256 && TelefonProtocolContract.Integer(latest["size"]) == next.Size)
            throw DeviceFileControl.Error("media_source_cache_latest_payload_already_sent");
        return new JsonObject { ["job_id"] = leaf.JobId, ["job_version"] = SourceDigest(leaf.Cipher), ["exchange_version"] = endVersions[leaf.JobId] };
    }

    internal sealed class NativePreparedMediaSource : IDisposable
    {
        private readonly object cacheGate = new();
        private readonly object endGate = new();
        private volatile bool sourceIoEnded;
        private readonly TelefonStore store;
        private readonly NativeMappedMediaSource source;
        private readonly NativeMediaPreferenceScope scope;
        private JsonObject record;
        private string version = "";
        private volatile bool retired;
        private bool sendAttempted;
        internal DeviceFileManifest Manifest { get; }
        internal string JobId => Manifest.SourceId;
        internal TelefonStore OwnerStore => store;
        internal object ConnectionOwner => source.ConnectionOwner;
        internal string PeerId => scope.PeerId;
        internal string Nonce { get { lock (cacheGate) { Require(); return record["nonce"]!.GetValue<string>(); } } }
        internal void BeginSendAttempt(TelefonConnection connection)
        {
            lock (cacheGate)
            {
                Require();
                if (!ReferenceEquals(ConnectionOwner, connection) || sendAttempted) throw DeviceFileControl.Error("media_source_exchange_original_attempt_required");
                sendAttempted = true; // A missing exchange row must never permit replay by the surviving live owner either.
            }
        }
        internal string Version { get { lock (cacheGate) { Require(); return version; } } }
        internal JsonObject Originals { get { lock (cacheGate) { Require(); return record["originals"]!.DeepClone().AsObject(); } } }

        internal JsonObject CreateMediaOffer(long now)
        {
            lock (cacheGate)
            {
                Require();
                var prefix = new byte[(int)Math.Min(Manifest.TotalBytes, NativeMediaContentMime.PrefixBytes)];
                try
                {
                    for (var offset = 0; offset < prefix.Length;)
                    {
                        var chunk = ReadChunk(offset / DeviceFileManifest.ChunkBytes);
                        try { var count = Math.Min(chunk.Length, prefix.Length - offset); chunk.AsSpan(0, count).CopyTo(prefix.AsSpan(offset)); offset += count; }
                        finally { CryptographicOperations.ZeroMemory(chunk); }
                    }
                    Require(); var provenance = record["provenance"]!.AsObject();
                    var kind = provenance["media_type"]!.GetValue<string>();
                    var mime = NativeMediaContentMime.Identify(prefix, Manifest.TotalBytes, kind);
                    var offer = MediaOfferEnvelope.Create(Manifest, provenance["settings"]!.AsObject(), kind,
                        new JsonObject { [Manifest.Files[0].Id] = mime }, record["originals"]!.AsObject(), now);
                    Require(); return offer;
                }
                finally { CryptographicOperations.ZeroMemory(prefix); }
            }
        }

        private NativePreparedMediaSource(TelefonStore store, NativeMappedMediaSource source, NativeMediaPreferenceScope scope, JsonObject record)
        { this.store = store; this.source = source; this.scope = scope; this.record = record; Manifest = source.PrepareManifest(); }

        private void Current()
        {
            if (retired) throw DeviceFileControl.Error("media_source_cache_owner_retired");
            source.Require(); store.RequireNativeMediaStorageKey();
            if (store.MediaPreferenceScope(source.PeerId) != scope) throw DeviceFileControl.Error("media_source_cache_scope_changed");
        }
        private byte[] ReadHead(SqliteConnection db, SqliteTransaction? transaction)
        {
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT value FROM native_media_source_jobs WHERE peer_id=$peer AND job_id=$job AND length(value) BETWEEN 29 AND " + (NativeSourceRecordLimit + 28);
            read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", JobId);
            var cipher = read.ExecuteScalar() as byte[] ?? throw DeviceFileControl.Error("media_source_cache_original_record_required");
            if (SourceDigest(cipher) != version || !JsonNode.DeepEquals(store.ReadSourceRecord(cipher, scope.PeerId, JobId, scope), record))
                throw DeviceFileControl.Error("media_source_cache_record_changed");
            return cipher;
        }
        internal void Require()
        {
            lock (cacheGate)
            {
                try
                {
                    Current();
                    lock (store.gate) { using var db = store.OpenNativeMediaDatabase(); db.Open(); _ = ReadHead(db, null); }
                    Current();
                }
                catch { retired = true; throw; }
            }
        }

        private string ChunkContext(int index) => scope.PeerId + "/" + JobId + "/" + record["nonce"]!.GetValue<string>() + "/" + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
        private byte[] ReadChunkCore(int index)
        {
            Require();
            if (index < 0 || index >= record["chunks"]!.AsArray().Count) throw DeviceFileControl.Error("media_source_cache_chunk_bounds");
            byte[] cipher;
            var wanted = (int)Math.Min(DeviceFileManifest.ChunkBytes, Manifest.TotalBytes - (long)index * DeviceFileManifest.ChunkBytes);
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open(); _ = ReadHead(db, null);
                using var read = db.CreateCommand();
                read.CommandText = "SELECT value FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job AND number=$number AND length(value)=$length";
                read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", JobId); read.Parameters.AddWithValue("$number", index);
                read.Parameters.AddWithValue("$length", wanted + 28);
                cipher = read.ExecuteScalar() as byte[] ?? throw DeviceFileControl.Error("media_source_cache_original_chunk_required");
            }
            if (cipher.Length != wanted + 28 || SourceDigest(cipher) != record["chunks"]![index]!.GetValue<string>())
                throw DeviceFileControl.Error("media_source_cache_chunk_changed");
            var plain = store.Open("native_media_source_chunk", ChunkContext(index), cipher);
            try { if (plain.Length != wanted) throw DeviceFileControl.Error("media_source_cache_chunk_changed"); Require(); return plain; }
            catch { CryptographicOperations.ZeroMemory(plain); throw; }
        }
        internal byte[] ReadChunk(int index)
        {
            lock (cacheGate)
            {
                try
                {
                    if (record["phase"]!.GetValue<string>() != "ready") throw DeviceFileControl.Error("media_source_cache_ready_required");
                    return ReadChunkCore(index);
                }
                catch { retired = true; throw; }
            }
        }

        private void Write(JsonObject next, int? index = null, byte[]? payload = null)
        {
            Current();
            byte[]? chunk = index is int number ? store.Seal("native_media_source_chunk", ChunkContext(number), payload!) : null;
            if (chunk is not null) next["chunks"]!.AsArray().Add(SourceDigest(chunk));
            var plain = TelefonCrypto.Canonical(next); byte[] cipher;
            try
            {
                if (plain.Length > NativeSourceRecordLimit) throw DeviceFileControl.Error("media_source_cache_record_bound");
                cipher = store.Seal("native_media_source_job", scope.PeerId + "/" + JobId, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            _ = store.ReadSourceRecord(cipher, scope.PeerId, JobId, scope);
            lock (store.gate)
            {
                Current(); using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
                if (version.Length != 0)
                {
                    _ = ReadHead(db, transaction);
                    if (next["phase"]?.GetValue<string>() == "ready" && record["previous"] is JsonObject previousEnd)
                    {
                        var retained = store.SourceRecords(db, transaction, scope).Where(item => item.JobId != JobId).ToList();
                        if (!JsonNode.DeepEquals(previousEnd, store.CompletedSourcePredecessor(db, transaction, scope, retained, record["originals"]!.AsObject(), Manifest)))
                            throw DeviceFileControl.Error("media_source_cache_previous_changed");
                    }
                }
                else
                {
                    var previous = store.SourceRecords(db, transaction, scope);
                    if (previous.Count >= NativeSourceHistoryLimit || previous.Sum(item => TelefonProtocolContract.Integer(item.Body["manifest"]!["total_bytes"])) + Manifest.TotalBytes > NativeSourceCacheLimit ||
                        previous.Any(item => item.JobId == JobId))
                        throw DeviceFileControl.Error("media_source_cache_original_preparation_required");
                    var selected = record["previous"];
                    if (selected is null)
                    {
                        if (previous.Any(item => JsonNode.DeepEquals(item.Body["originals"]!.AsObject().Single().Value, record["originals"]!.AsObject().Single().Value)))
                            throw DeviceFileControl.Error("media_source_cache_original_preparation_required");
                    }
                    else if (!JsonNode.DeepEquals(selected, store.CompletedSourcePredecessor(db, transaction, scope, previous, record["originals"]!.AsObject(), Manifest)))
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
                    write.Parameters.AddWithValue("$peer", scope.PeerId); write.Parameters.AddWithValue("$job", JobId); write.Parameters.AddWithValue("$number", index!.Value); write.Parameters.AddWithValue("$value", chunk); write.ExecuteNonQuery();
                }
                Current(); transaction.Commit(); record = next; version = SourceDigest(cipher); _ = ReadHead(db, null); Current();
            }
        }

        private void Freeze()
        {
            Write(record.DeepClone().AsObject()); // Durable reservation BEFORE copying any source byte.
            for (long offset = 0; offset < Manifest.TotalBytes;)
            {
                var index = record["chunks"]!.AsArray().Count;
                var bytes = source.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, Manifest.TotalBytes - offset));
                try { Write(record.DeepClone().AsObject(), index, bytes); offset += bytes.Length; }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            for (var index = 0; index < record["chunks"]!.AsArray().Count; index++)
            {
                var bytes = ReadChunkCore(index);
                try { digest.AppendData(bytes); } finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            // Hash the decoded cache, not just the source or encrypted records.
            if (Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != Manifest.Files[0].Sha256)
                throw DeviceFileControl.Error("media_source_cache_content_changed");
            var ready = record.DeepClone().AsObject(); ready["phase"] = "ready"; Write(ready); Require();
        }
        internal void RequireIoEnded()
        {
            if (!sourceIoEnded || !retired) throw DeviceFileControl.Error("media_source_cache_io_pending");
            // After the volatile native-end publication the record is immutable:
            // all old readers drained and retired forbids every new source read.
            // Do not take cache/end locks underneath a protected store transaction.
            store.RequireNativeMediaStorageKey();
            lock (store.gate) { using var db = store.OpenNativeMediaDatabase(); db.Open(); _ = ReadHead(db, null); }
        }
        public void Dispose()
        {
            retired = true;
            lock (endGate)
            {
                if (sourceIoEnded) return;
                lock (cacheGate) { } // Wait for the exact cache reader, not a cancellation flag.
                source.Dispose(); // Includes the actual held file/album/root handles.
                sourceIoEnded = true; // Never set when native disposal failed.
            }
        }

        internal static NativePreparedMediaSource Create(TelefonStore store, NativeMappedMediaSource source, bool completedSuccessor = false)
        {
            if (!ReferenceEquals(source.Store, store)) throw DeviceFileControl.Error("media_source_cache_native_owner_required");
            source.Require(); var scope = store.MediaPreferenceScope(source.PeerId); var manifest = source.PrepareManifest();
            var wire = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())["body"]!["manifest"]!.DeepClone();
            var body = new JsonObject { ["format"] = 1, ["scope"] = new JsonObject { ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey,
                ["pairing_epoch"] = scope.PairingEpoch, ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey },
                ["nonce"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), ["provenance"] = source.Provenance,
                ["manifest"] = wire, ["manifest_sha256"] = manifest.Fingerprint, ["originals"] = source.PreparedOriginalReferences(), ["phase"] = "planned", ["chunks"] = new JsonArray() };
            if (completedSuccessor)
            {
                lock (store.gate)
                {
                    source.Require(); using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
                    var previous = store.CompletedSourcePredecessor(db, transaction, scope, store.SourceRecords(db, transaction, scope), body["originals"]!.AsObject(), manifest);
                    if (previous is not null) { body["format"] = 2; body["previous"] = previous; }
                    source.Require(); transaction.Commit();
                }
            }
            var result = new NativePreparedMediaSource(store, source, scope, body);
            try { result.Freeze(); return result; } catch { result.retired = true; throw; } // Never erase partial/history or adopt it on retry.
        }
    }
    private NativePreparedMediaSource FreezeNativeMappedMediaSource(NativeMappedMediaSource source, bool completedSuccessor = false) =>
        NativePreparedMediaSource.Create(this, source, completedSuccessor);
}
