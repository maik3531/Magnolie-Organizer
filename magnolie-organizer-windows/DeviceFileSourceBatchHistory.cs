using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Refs #330. Protected historical DATA only. No source factory, native
    // backup/root reopen, raw-payload unseal, grant, clock or restart adoption.
    private JsonObject CompletedBatchPredecessors(SqliteConnection db, SqliteTransaction transaction, NativeMediaPreferenceScope scope,
        List<(string JobId, byte[] Cipher, JsonObject Body)> records, JsonObject next, DeviceFileManifest manifest)
    {
        RequireLocalSourceGenerationHistory(records, next);
        var history = new BatchHistory(this, db, transaction, scope, records);
        var result = new JsonObject();
        foreach (var file in manifest.Files) result[file.Id] = history.Resolve(next["origins"]![file.Id]!.AsObject(), file, manifest)?.DeepClone();
        return result;
    }

    private JsonObject ValidatedPendingBatchRetirement(SqliteConnection db, SqliteTransaction transaction, NativeMediaPreferenceScope scope,
        List<(string JobId, byte[] Cipher, JsonObject Body)> records, string jobId, string exchangeVersion) =>
        new BatchHistory(this, db, transaction, scope, records).PendingRetirement(jobId, exchangeVersion);

    internal sealed record PendingSavedPhotoBatch(JsonObject Job, string JobVersion, JsonObject Exchange,
        string ExchangeVersion, RemoteSavedConfirmation Saved);

    private sealed class BatchHistory(TelefonStore store, SqliteConnection db, SqliteTransaction transaction,
        NativeMediaPreferenceScope scope, List<(string JobId, byte[] Cipher, JsonObject Body)> records)
    {
        private sealed record Root(JsonObject Body, DeviceFileManifest Manifest, string Version, string ExchangeVersion,
            Dictionary<string, string> Publications, JsonObject Exchange, bool Ended);
        // Memo lives only in this synchronous protected-DB snapshot/call tree.
        private readonly Dictionary<string, Root> complete = new(StringComparer.Ordinal);
        private readonly HashSet<string> checking = new(StringComparer.Ordinal);
        private readonly Dictionary<string, JsonObject?> legacy = new(StringComparer.Ordinal);
        private readonly HashSet<string> checkedGraphs = new(StringComparer.Ordinal);
        private static string Text(JsonNode value, string key) => TelefonMessagingContract.String(value.AsObject(), key);
        private static long Number(JsonNode? value) => TelefonProtocolContract.Integer(value);
        private static InvalidDataException Error() => DeviceFileControl.Error("media_source_batch_completed_previous_required");

        internal JsonObject PendingRetirement(string jobId, string exchangeVersion)
        {
            var root = ValidateRoot(jobId, allowPlanned: true);
            if (root.Ended || root.ExchangeVersion != exchangeVersion) throw Error();
            return root.Exchange.DeepClone().AsObject();
        }

        internal PendingSavedPhotoBatch? FindSavedPhotos(JsonObject origins)
        {
            PendingSavedPhotoBatch? pending = null;
            foreach (var source in records.Where(item => Number(item.Body["format"]) == 5))
            {
                var savedOrigins = source.Body["origins"]!.AsObject();
                if (!savedOrigins.Any(old => origins.Any(current => JsonNode.DeepEquals(old.Value, current.Value)))) continue;
                var (body, exchangeVersion) = Exchange(source.JobId, batch: true);
                if (Text(body, "phase") == "source_ended") continue;
                var version = SourceDigest(source.Cipher);
                if (pending is not null || Text(source.Body, "phase") != "ready" || Text(body, "phase") != "peer_saved" ||
                    body["peer_readback"] is not null || savedOrigins.Count != origins.Count ||
                    !savedOrigins.All(old => origins.Any(current => JsonNode.DeepEquals(old.Value, current.Value))) ||
                    !body.ContainsKey("reader_id") || !DeviceFileControl.Hash(Text(body, "reader_id")) ||
                    source.Body["predecessors"]!.AsObject().Any(previous => previous.Value is not null))
                    throw Error();
                TelefonProtocolContract.ExactObject(body, "format", "cache_version", "nonce", "offer", "permission_epoch", "phase", "acceptance",
                    "sent_chunks", "pending_chunk", "peer_saved", "peer_readback", "reader_id");
                var manifest = BatchManifest(source.Body);
                var (media, _, receipts) = OriginalSaved(source.Body, manifest, version, body);
                if (media.MediaType != "images" || Number(body["peer_saved"]!["created_ms"]) < Number(body["acceptance"]!["created_ms"]))
                    throw Error();
                foreach (var file in manifest.Files)
                {
                    var origin = savedOrigins[file.Id]!.AsObject();
                    ValidateOriginalGraph(origin, file, manifest);
                    if (!JsonNode.DeepEquals(media.PcOrigins[file.Id], new JsonObject { ["format"] = 1,
                        ["origin_sha256"] = PcOriginDigest(origin), ["previous_publication_sha256"] = null }))
                        throw Error();
                }
                VerifyCiphers(source.JobId, source.Body, manifest);
                pending = new(source.Body, version, body, exchangeVersion, receipts);
            }
            return pending;
        }

        private (JsonObject Body, string Version) Exchange(string job, bool batch)
        {
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_source_exchanges'";
            if (read.ExecuteScalar() is null) throw Error();
            read.CommandText = "SELECT length(value),value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job";
            read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", job);
            using var row = read.ExecuteReader();
            if (!row.Read() || row.GetInt64(0) is < 29 || row.GetInt64(0) > (batch ? 1048576 : 32768) + 28) throw Error();
            var cipher = (byte[])row[1]; var clear = store.Open("native_media_source_exchange", scope.PeerId + "/" + job, cipher);
            try { return (JsonNode.Parse(clear)!.AsObject(), SourceDigest(cipher)); }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }

        private static JsonObject Reference(string job, string version, string exchange, DeviceManifestFile file, string publication) => new()
        { ["job_id"] = job, ["job_version"] = version, ["exchange_version"] = exchange, ["file_id"] = file.Id,
            ["publication_sha256"] = publication, ["size"] = file.Size, ["sha256"] = file.Sha256 };

        private JsonObject? Legacy(JsonObject origin, DeviceManifestFile file, DeviceFileManifest target)
        {
            var token = PcOriginDigest(origin);
            if (legacy.TryGetValue(token, out var known)) return known;
            var old = records.Where(item => Number(item.Body["format"]) != 5).ToList();
            var single = new DeviceFileManifest(target.TransferId, target.SourceId, target.SenderId, target.ReceiverId, [file], file.Size);
            var previous = store.CompletedSourcePredecessor(db, transaction, scope, old,
                new JsonObject { ["format"] = 3, ["local_origin"] = origin.DeepClone() }, single, allowUnchanged: true);
            if (previous is null) { legacy[token] = null; return null; }
            var job = Text(previous, "job_id"); var source = old.Single(item => item.JobId == job);
            var manifest = BatchManifest(source.Body); var saved = Exchange(job, batch: false);
            if (saved.Version != Text(previous, "exchange_version")) throw Error();
            var receipt = saved.Body["peer_saved"]!["receipts"]!.AsArray().Single()!;
            var result = Reference(job, SourceDigest(source.Cipher), saved.Version, manifest.Files.Single(), Text(receipt, "receipt_sha256"));
            legacy[token] = result; return result;
        }

        internal JsonObject? Resolve(JsonObject origin, DeviceManifestFile file, DeviceFileManifest target)
        {
            var refs = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
            var parents = new Dictionary<string, string?>(StringComparer.Ordinal);
            var seed = Legacy(origin, file, target);
            if (seed is not null) { refs.Add(Text(seed, "job_id"), seed); parents.Add(Text(seed, "job_id"), null); }
            foreach (var source in records.Where(item => Number(item.Body["format"]) == 5))
            {
                var ids = source.Body["origins"]!.AsObject().Where(pair => JsonNode.DeepEquals(pair.Value, origin)).Select(pair => pair.Key).ToArray();
                if (ids.Length == 0) continue;
                if (ids.Length != 1) throw Error();
                var root = ValidateRoot(source.JobId); var member = root.Manifest.Files.Single(value => value.Id == ids[0]);
                refs.Add(source.JobId, Reference(source.JobId, root.Version, root.ExchangeVersion, member, root.Publications[member.Id]));
                parents.Add(source.JobId, source.Body["predecessors"]![member.Id] is JsonObject previous ? Text(previous, "job_id") : null);
            }
            if (refs.Count == 0) return null;
            var used = new HashSet<string>(StringComparer.Ordinal);
            foreach (var (job, parent) in parents)
                if (parent is not null)
                {
                    if (!refs.TryGetValue(parent, out var expected) || !used.Add(parent)) throw Error();
                    var body = records.Single(item => item.JobId == job).Body;
                    var fid = body["origins"]!.AsObject().Single(pair => JsonNode.DeepEquals(pair.Value, origin)).Key;
                    if (!JsonNode.DeepEquals(body["predecessors"]![fid], expected)) throw Error();
                }
            var leaves = refs.Keys.Where(job => !used.Contains(job)).ToArray();
            if (leaves.Length != 1) throw Error();
            var visited = new HashSet<string>(StringComparer.Ordinal); string? cursor = leaves[0];
            while (cursor is not null)
            {
                if (!visited.Add(cursor) || visited.Count > NativeSourceHistoryLimit) throw Error();
                cursor = parents[cursor];
            }
            if (visited.Count != refs.Count) throw Error();
            return refs[leaves[0]];
        }

        private void ValidateOriginalGraph(JsonObject origin, DeviceManifestFile file, DeviceFileManifest target)
        {
            // Validate even a root's NON-selected earlier members. A declared
            // null cannot hide a legacy parent, second genesis or disconnected
            // cycle. Later pending descendants are not completion evidence and
            // do not block unrelated members of an already completed root.
            var token = PcOriginDigest(origin);
            if (checkedGraphs.Contains(token)) return;
            var parents = new Dictionary<string, string?>(StringComparer.Ordinal);
            var seed = Legacy(origin, file, target);
            if (seed is not null) parents.Add(Text(seed, "job_id"), null);
            foreach (var source in records.Where(item => Number(item.Body["format"]) == 5))
            {
                var ids = source.Body["origins"]!.AsObject().Where(pair => JsonNode.DeepEquals(pair.Value, origin)).Select(pair => pair.Key).ToArray();
                if (ids.Length == 0) continue;
                if (ids.Length != 1) throw Error();
                parents.Add(source.JobId, source.Body["predecessors"]![ids[0]] is JsonObject previous ? Text(previous, "job_id") : null);
            }
            if (parents.Values.Count(value => value is null) != 1) throw Error();
            foreach (var job in parents.Keys)
            {
                var seen = new HashSet<string>(StringComparer.Ordinal); string? cursor = job;
                while (cursor is not null)
                {
                    if (!seen.Add(cursor) || seen.Count > NativeSourceHistoryLimit || !parents.TryGetValue(cursor, out var parent)) throw Error();
                    cursor = parent;
                }
            }
            checkedGraphs.Add(token);
        }

        private Root ValidateRoot(string job, bool allowPlanned = false)
        {
            if (complete.TryGetValue(job, out var cached))
            {
                if (!allowPlanned && !cached.Ended) throw Error();
                return cached;
            }
            if (!checking.Add(job) || checking.Count > NativeSourceHistoryLimit) throw Error();
            try
            {
                var source = records.SingleOrDefault(item => item.JobId == job);
                if (source.Body is null || Number(source.Body["format"]) != 5 || Text(source.Body, "phase") != "ready") throw Error();
                var manifest = BatchManifest(source.Body); var (body, exchangeVersion) = Exchange(job, batch: true);
                var ended = Text(body, "phase") == "source_ended";
                var fields = new[] { "format", "cache_version", "nonce", "offer", "permission_epoch", "phase", "acceptance",
                    "sent_chunks", "pending_chunk", "peer_saved", "peer_readback", "source_retirement" };
                if (body.ContainsKey("reader_id"))
                {
                    if (!DeviceFileControl.Hash(Text(body, "reader_id"))) throw Error();
                    fields = fields.Append("reader_id").ToArray();
                }
                if (body.ContainsKey("recovery")) fields = fields.Append("recovery").ToArray();
                TelefonProtocolContract.ExactObject(body, ended ? fields.Append("source_end").ToArray() : fields);
                var version = SourceDigest(source.Cipher);
                if (!ended && (!allowPlanned || Text(body, "phase") != "end_planned")) throw Error();
                var (media, accepted, receipts) = OriginalSaved(source.Body, manifest, version, body);
                var readback = body["peer_readback"]!.AsObject();
                var recovery = body.ContainsKey("recovery")
                    ? TelefonProtocolContract.ExactObject(body["recovery"]!, "request", "permission_epoch", "reader_id") : null;
                if (recovery is not null && (!body.ContainsKey("reader_id") || !DeviceFileControl.Hash(Text(recovery, "reader_id")) ||
                    Text(body, "reader_id") == Text(recovery, "reader_id"))) throw Error();
                var binding = new DeviceTransferBinding(scope.LocalId, scope.PeerId, scope.LocalKey, scope.PeerKey,
                    recovery is null ? accepted.PermissionEpoch : Text(recovery, "permission_epoch"),
                    Text(readback["body"]!, "destination_token"));
                binding.Validate();
                var at = Number(readback["created_ms"]);
                var observed = recovery is null
                    ? DevicePublishedBatchReadbackEnvelope.Parse(readback, media.Offer, binding, media.MediaType, at)
                    : DeviceSavedBatchReadback.ParseReply(recovery["request"]!.AsObject(), readback, media.Offer, body["peer_saved"]!.AsObject(),
                        receipts, binding with { DestinationToken = manifest.Fingerprint }, binding, at);
                if (recovery is null && Number(readback["expires_ms"]) > Number(body["acceptance"]!["expires_ms"])) throw Error();
                var publications = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var file in manifest.Files)
                {
                    var receipt = receipts.Members.Single(value => value.FileId == file.Id); var member = observed.Body["members"]![file.Id]!;
                    if (Text(member, "publication_sha256") != receipt.ReceiptSha256 || Text(member, "mime_type") != Text(source.Body["mime_types"]!, file.Id)) throw Error();
                    publications.Add(file.Id, receipt.ReceiptSha256);
                    var origin = source.Body["origins"]![file.Id]!.AsObject();
                    ValidateOriginalGraph(origin, file, manifest);
                    var previous = source.Body["predecessors"]![file.Id] as JsonObject;
                    if (previous is not null)
                    {
                        var parentId = Text(previous, "job_id"); var parent = records.SingleOrDefault(item => item.JobId == parentId);
                        JsonObject? expected;
                        if (parent.Body is null) throw Error();
                        if (Number(parent.Body["format"]) == 5)
                        {
                            var old = ValidateRoot(parentId); var ids = old.Body["origins"]!.AsObject().Where(pair => JsonNode.DeepEquals(pair.Value, origin)).Select(pair => pair.Key).ToArray();
                            if (ids.Length != 1) throw Error(); var oldFile = old.Manifest.Files.Single(value => value.Id == ids[0]);
                            expected = Reference(parentId, old.Version, old.ExchangeVersion, oldFile, old.Publications[oldFile.Id]);
                        }
                        else expected = Legacy(origin, file, manifest);
                        if (!JsonNode.DeepEquals(previous, expected)) throw Error();
                    }
                    var pc = media.PcOrigins[file.Id]!.AsObject();
                    if (!JsonNode.DeepEquals(pc, new JsonObject { ["format"] = 1, ["origin_sha256"] = PcOriginDigest(origin),
                        ["previous_publication_sha256"] = previous?["publication_sha256"]?.DeepClone() })) throw Error();
                }
                ValidateEnd(source.Body, manifest, version, body, observed.Body, planned: !ended);
                VerifyCiphers(job, source.Body, manifest);
                var result = new Root(source.Body, manifest, version, exchangeVersion, publications, body, ended); complete.Add(job, result); return result;
            }
            finally { checking.Remove(job); }
        }

        private (NativeMediaOffer Media, RemoteFileAcceptance Accepted, RemoteSavedConfirmation Saved) OriginalSaved(
            JsonObject source, DeviceFileManifest manifest, string version, JsonObject body)
        {
            if (Number(body["format"]) != 2 || Text(body, "cache_version") != version ||
                Text(body, "nonce") != Text(source, "nonce") || body["pending_chunk"] is not null) throw Error();
            var offer = body["offer"]!.AsObject();
            var media = MediaOfferEnvelope.Validate(offer, scope.LocalId, scope.PeerId, Number(offer["created_ms"]), allowPcBatch: true);
            if (!media.PcBatch || media.Manifest.Fingerprint != manifest.Fingerprint || media.Originals.Count != 0 ||
                !JsonNode.DeepEquals(media.Settings, source["provenance"]!["settings"]) || media.MediaType != Text(source["provenance"]!, "media_type") ||
                !JsonNode.DeepEquals(media.MimeTypes, source["mime_types"]) ||
                Text(body, "permission_epoch") != Text(source["provenance"]!["sending_binding"]!, "permission_epoch")) throw Error();
            var acceptance = body["acceptance"]!.AsObject(); var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, Number(acceptance["created_ms"]));
            if (accepted.OfferId != Text(offer, "message_id") || accepted.ManifestSha256 != manifest.Fingerprint || accepted.TransferId != manifest.TransferId ||
                accepted.PermissionEpoch != Text(body, "permission_epoch") || Number(acceptance["created_ms"]) < Number(offer["created_ms"]) ||
                Number(acceptance["expires_ms"]) > Number(offer["expires_ms"])) throw Error();
            var saved = body["peer_saved"]!.AsObject(); var receipts = DeviceFileSavedEnvelope.Parse(saved, manifest, accepted, Number(saved["created_ms"]));
            if (Number(saved["expires_ms"]) > Number(acceptance["expires_ms"])) throw Error();
            var sent = body["sent_chunks"]!.AsObject();
            if (!sent.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(manifest.Files.Select(file => file.Id))) throw Error();
            foreach (var file in manifest.Files)
            {
                var chunks = sent[file.Id]!.AsArray(); var count = (int)((file.Size + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes);
                if (chunks.Count != count || !chunks.Select(Number).ToHashSet().SetEquals(Enumerable.Range(0, count).Select(index => (long)index))) throw Error();
            }
            return (media, accepted, receipts);
        }

        private static void ValidateEnd(JsonObject ready, DeviceFileManifest manifest, string version, JsonObject body, JsonObject readback, bool planned)
        {
            var plan = TelefonProtocolContract.ExactObject(body["source_retirement"]!, "format", "job_id", "cache_version", "nonce", "manifest_sha256",
                "storage_parent", "backups", "saved_sha256", "readback_sha256");
            var end = planned ? null : TelefonProtocolContract.ExactObject(body["source_end"]!, "format", "job_id", "cache_version", "nonce", "retirement_sha256", "readback_sha256");
            _ = NativeMediaBackupParent.Parse(plan["storage_parent"]!); // Metadata only, never OpenNative.
            if (Number(plan["format"]) != 1 || Text(plan, "job_id") != manifest.SourceId ||
                Text(plan, "cache_version") != version || Text(plan, "nonce") != Text(ready, "nonce") || Text(plan, "manifest_sha256") != manifest.Fingerprint ||
                Text(plan, "saved_sha256") != DeviceFileControl.Digest("magnolie-native-source-batch-saved-v1\0", body["peer_saved"]!) ||
                Text(plan, "readback_sha256") != Text(readback, "readback_sha256")) throw Error();
            if (end is not null && (Number(end["format"]) != 2 || Text(end, "job_id") != manifest.SourceId || Text(end, "cache_version") != version ||
                Text(end, "nonce") != Text(ready, "nonce") || Text(end, "retirement_sha256") != DeviceFileControl.Digest("magnolie-native-source-batch-retirement-v1\0", plan) ||
                Text(end, "readback_sha256") != Text(readback, "readback_sha256"))) throw Error();
            var backups = plan["backups"]!.AsObject();
            if (!backups.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(manifest.Files.Select(file => file.Id))) throw Error();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var file in manifest.Files)
            {
                var value = TelefonProtocolContract.ExactObject(backups[file.Id]!, "id", "object_key", "saved_ms", "name", "record_sha256");
                var provenance = BatchBackupProvenance(ready, version, manifest, file);
                var record = new JsonObject { ["id"] = value["id"]!.DeepClone(), ["object_key"] = value["object_key"]!.DeepClone(),
                    ["saved_ms"] = value["saved_ms"]!.DeepClone(), ["name"] = value["name"]!.DeepClone(), ["provenance"] = provenance };
                ValidatePreparedBatchPcBackup(record, provenance);
                if (!ids.Add(Text(value, "id")) || Text(value, "id") != DeviceFileControl.Digest("magnolie-native-media-backup-version-v1\0", provenance) ||
                    Number(value["saved_ms"]) is < 1 or > NativeMediaBackupPolicy.MaximumTimestampMs ||
                    Text(value, "record_sha256") != DeviceFileControl.Digest("magnolie-native-media-backup-reference-v1\0", record)) throw Error();
            }
        }

        private void VerifyCiphers(string job, JsonObject ready, DeviceFileManifest manifest)
        {
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT number,value FROM native_media_source_chunks WHERE peer_id=$peer AND job_id=$job ORDER BY number";
            read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$job", job);
            using var rows = read.ExecuteReader(); var routes = BatchRoutes(manifest).ToArray(); var number = 0;
            while (rows.Read())
            {
                if (number >= routes.Length || rows.GetInt32(0) != number || rows[1] is not byte[] cipher ||
                    cipher.Length != BatchChunkSize(routes[number].File, routes[number].Index) + 28 ||
                    SourceDigest(cipher) != Text(ready["chunks"]![number]!, "sha256")) throw Error();
                number++;
            }
            if (number != routes.Length) throw Error();
        }
    }
}
