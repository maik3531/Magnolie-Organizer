using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed record PendingSavedVideo(JsonObject Exchange, string ExchangeVersion, RemoteSavedConfirmation Saved);

    private static RemoteSavedConfirmation ValidateOriginalVideoSaved(JsonObject job, string version, JsonObject exchange,
        DeviceFileManifest manifest, NativeMediaPreferenceScope scope)
    {
        static long Time(JsonObject frame, string key) => TelefonProtocolContract.Integer(frame[key]);
        static InvalidDataException Error() => DeviceFileControl.Error("media_source_video_original_saved_required");
        if (Time(exchange, "format") != 2 || !DeviceFileControl.Hash(exchange["reader_id"]?.GetValue<string>() ?? "") ||
            exchange["cache_version"]?.GetValue<string>() != version || !JsonNode.DeepEquals(job["nonce"], exchange["nonce"]) ||
            exchange["pending_chunk"] is not null || job["local_origin"] is not JsonObject origin || job["previous"] is not null ||
            exchange["acceptance_envelope"] is not JsonObject acceptedFrame || exchange["saved_envelope"] is not JsonObject savedFrame ||
            !JsonNode.DeepEquals(exchange["acceptance"], acceptedFrame["body"]) ||
            !JsonNode.DeepEquals(exchange["peer_saved"], savedFrame["body"])) throw Error();
        var offer = exchange["offer"]!.AsObject();
        var media = MediaOfferEnvelope.Validate(offer, scope.LocalId, scope.PeerId, Time(offer, "created_ms"));
        var file = manifest.Files.Single();
        var pc = new JsonObject { ["format"] = 1, ["origin_sha256"] = PcOriginDigest(origin), ["previous_publication_sha256"] = null };
        if (media.PcBatch || media.MediaType != "video" || file.Size <= 0 || media.Manifest.Fingerprint != manifest.Fingerprint ||
            media.MimeTypes[file.Id]?.GetValue<string>() != "video/mp4" || media.Originals.Count != 0 ||
            media.PcOrigins.Count != 1 || !JsonNode.DeepEquals(media.PcOrigins[file.Id], pc) ||
            !JsonNode.DeepEquals(media.Settings, job["provenance"]!["settings"]) ||
            !JsonNode.DeepEquals(exchange["permission_epoch"], job["provenance"]!["sending_binding"]!["permission_epoch"]))
            throw Error();
        var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptedFrame, Time(acceptedFrame, "created_ms"));
        if (accepted.OfferId != offer["message_id"]!.GetValue<string>() ||
            accepted.PermissionEpoch != exchange["permission_epoch"]!.GetValue<string>() ||
            Time(acceptedFrame, "created_ms") < Time(offer, "created_ms") || Time(savedFrame, "created_ms") < Time(acceptedFrame, "created_ms") ||
            Time(savedFrame, "expires_ms") > Time(acceptedFrame, "expires_ms") || Time(acceptedFrame, "expires_ms") > Time(offer, "expires_ms"))
            throw Error();
        var count = (int)((file.Size + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes);
        if (exchange["sent_chunks"] is not JsonArray sent || sent.Count != count ||
            !sent.Select(TelefonProtocolContract.Integer).ToHashSet().SetEquals(Enumerable.Range(0, count).Select(index => (long)index)))
            throw Error();
        return DeviceFileSavedEnvelope.Parse(savedFrame, manifest, accepted, Time(savedFrame, "created_ms"));
    }

    internal sealed class NativeMediaSourceExchange
    {
        private readonly NativePreparedMediaSource cache;
        private readonly TelefonConnection.NativeMediaSendRun run;
        private readonly TelefonStore store;
        private JsonObject body;
        private string? version;
        internal bool AllChunksSent => body["sent_chunks"]!.AsArray().Count == (cache.Manifest.TotalBytes + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes;
        internal string Phase => body["phase"]!.GetValue<string>();
        internal void Require()
        {
            cache.Require();
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open(); using var read = db.CreateCommand();
                read.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job AND length(value) BETWEEN 29 AND 32796";
                read.Parameters.AddWithValue("$peer", cache.PeerId); read.Parameters.AddWithValue("$job", cache.JobId);
                if (read.ExecuteScalar() is not byte[] cipher || SourceDigest(cipher) != version) throw DeviceFileControl.Error("media_source_exchange_changed");
                var clear = store.Open("native_media_source_exchange", cache.PeerId + "/" + cache.JobId, cipher);
                try { if (!JsonNode.DeepEquals(JsonNode.Parse(clear), body)) throw DeviceFileControl.Error("media_source_exchange_changed"); }
                finally { CryptographicOperations.ZeroMemory(clear); }
            }
            cache.Require();
        }

        internal NativeMediaSourceExchange(TelefonConnection.NativeMediaSendRun run)
        {
            this.run = run; cache = run.Cache; store = cache.OwnerStore; run.Require();
            if (cache.Recovery is { } recovery)
            {
                body = recovery.Exchange.DeepClone().AsObject();
                version = recovery.ExchangeVersion;
                Require();
                return;
            }
            body = new JsonObject { ["format"] = 1, ["cache_version"] = cache.Version, ["nonce"] = cache.Nonce,
                ["offer"] = run.Offer.DeepClone(), ["permission_epoch"] = run.PermissionEpoch, ["phase"] = "offer_planned",
                ["acceptance"] = null, ["sent_chunks"] = new JsonArray(), ["pending_chunk"] = null, ["peer_saved"] = null };
            if (cache.NewTypedVideoOnly)
            {
                body["format"] = 2;
                body["reader_id"] = run.ReaderId;
                body["acceptance_envelope"] = null;
                body["saved_envelope"] = null;
            }
            Write(body.DeepClone().AsObject()); // Intent committed before the FIRST actual secure offer byte.
        }

        private void Write(JsonObject next, bool sourceEnded = false, Action? requireTerminal = null)
        {
            void RequireOwner()
            {
                if (sourceEnded) cache.RequireIoEnded();
                else run.Require();
                requireTerminal?.Invoke();
            }
            RequireOwner();
            var plain = TelefonCrypto.Canonical(next); byte[] cipher;
            try
            {
                if (plain.Length > 32768) throw DeviceFileControl.Error("media_source_exchange_bound");
                cipher = store.Seal("native_media_source_exchange", cache.PeerId + "/" + cache.JobId, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            lock (store.gate)
            {
                RequireOwner(); using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
                using var command = db.CreateCommand(); command.Transaction = transaction;
                command.CommandText = "CREATE TABLE IF NOT EXISTS native_media_source_exchanges(peer_id TEXT NOT NULL,job_id TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,job_id))";
                command.ExecuteNonQuery();
                command.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job AND length(value) BETWEEN 29 AND 32796";
                command.Parameters.AddWithValue("$peer", cache.PeerId); command.Parameters.AddWithValue("$job", cache.JobId);
                var previous = command.ExecuteScalar();
                if (version is null)
                {
                    command.CommandText = "SELECT count(*) FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job";
                    if (Convert.ToInt64(command.ExecuteScalar()) != 0) throw DeviceFileControl.Error("media_source_exchange_original_attempt_required");
                }
                else
                {
                    if (previous is not byte[] held || SourceDigest(held) != version) throw DeviceFileControl.Error("media_source_exchange_changed");
                    var clear = store.Open("native_media_source_exchange", cache.PeerId + "/" + cache.JobId, held);
                    try { if (!JsonNode.DeepEquals(JsonNode.Parse(clear), body)) throw DeviceFileControl.Error("media_source_exchange_changed"); }
                    finally { CryptographicOperations.ZeroMemory(clear); }
                }
                if (requireTerminal is not null) cache.VerifyRecoveryCiphers(db, transaction);
                command.CommandText = "INSERT INTO native_media_source_exchanges(peer_id,job_id,value) VALUES($peer,$job,$value) ON CONFLICT(peer_id,job_id) DO UPDATE SET value=excluded.value";
                command.Parameters.AddWithValue("$value", cipher); command.ExecuteNonQuery(); RequireOwner(); transaction.Commit();
                body = next; version = SourceDigest(cipher);
                command.Transaction = null; command.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job";
                if (command.ExecuteScalar() is not byte[] saved || SourceDigest(saved) != version) throw DeviceFileControl.Error("media_source_exchange_readback_failed");
                RequireOwner();
            }
        }
        internal void OfferSent()
        {
            if (Phase != "offer_planned") throw DeviceFileControl.Error("media_source_exchange_offer_state");
            var next = body.DeepClone().AsObject(); next["phase"] = "offer_sent"; Write(next);
        }
        internal void Accepted(JsonObject acceptance)
        {
            if (Phase != "offer_sent") throw DeviceFileControl.Error("media_source_exchange_accept_state");
            var next = body.DeepClone().AsObject();
            next["phase"] = "accepted";
            next["acceptance"] = acceptance["body"]!.DeepClone();
            if (cache.NewTypedVideoOnly) next["acceptance_envelope"] = acceptance.DeepClone();
            Write(next);
        }
        internal void PlanChunk(DeviceFileChunkRequest request)
        {
            if (Phase != "accepted" || body["pending_chunk"] is not null) throw DeviceFileControl.Error("media_source_exchange_chunk_state");
            var next = body.DeepClone().AsObject();
            next["pending_chunk"] = new JsonObject { ["request_id"] = request.RequestId, ["chunk_index"] = request.ChunkIndex, ["file_id"] = request.FileId };
            Write(next);
        }
        internal void ChunkSent(DeviceFileChunkRequest request)
        {
            if (Phase != "accepted" || body["pending_chunk"]?["request_id"]?.GetValue<string>() != request.RequestId)
                throw DeviceFileControl.Error("media_source_exchange_original_chunk_required");
            var next = body.DeepClone().AsObject(); next["pending_chunk"] = null;
            var sent = next["sent_chunks"]!.AsArray();
            if (!sent.Any(value => value!.GetValue<int>() == request.ChunkIndex)) sent.Add(request.ChunkIndex);
            Write(next);
        }
        internal void PeerSaved(JsonObject saved)
        {
            if (Phase != "accepted" || body["pending_chunk"] is not null || !AllChunksSent)
                throw DeviceFileControl.Error("media_source_exchange_unsent_chunks");
            var next = body.DeepClone().AsObject();
            next["phase"] = "peer_saved";
            next["peer_saved"] = saved["body"]!.DeepClone();
            if (cache.NewTypedVideoOnly) next["saved_envelope"] = saved.DeepClone();
            Write(next);
        }
        internal void PeerReadback(RemotePublishedReadback readback, JsonObject frame)
        {
            if (!run.ExpectReadback || Phase != "peer_saved" || body["pending_chunk"] is not null || !AllChunksSent || body["peer_readback"] is not null)
                throw DeviceFileControl.Error("media_source_exchange_readback_state");
            var next = body.DeepClone().AsObject();
            next["phase"] = "peer_readback";
            next["peer_readback"] = readback.Body;
            if (run.RecoveryRequest is { } request)
                next["recovery"] = new JsonObject { ["request"] = request.DeepClone(), ["reply"] = frame.DeepClone(),
                    ["reader_id"] = run.ReaderId, ["permission_epoch"] = run.PermissionEpoch,
                    ["backup"] = run.RecoveryBackup!.Evidence() };
            Write(next);
        }
        internal void SourceEnd()
        {
            if (!run.OutputDrained || !run.ExpectReadback || !run.Readback.Task.IsCompletedSuccessfully ||
                Phase != "peer_readback" || body["pending_chunk"] is not null || !AllChunksSent || body["source_end"] is not null)
                throw DeviceFileControl.Error("media_source_exchange_native_end_required");
            Require(); // Last original live cache/head check, before native disposal.
            var next = body.DeepClone().AsObject();
            next["phase"] = "source_ended";
            next["source_end"] = new JsonObject { ["format"] = 1, ["job_id"] = cache.JobId,
                ["cache_version"] = body["cache_version"]!.DeepClone(), ["nonce"] = body["nonce"]!.DeepClone(),
                ["readback_sha256"] = body["peer_readback"]!["readback_sha256"]!.DeepClone() };
            cache.Dispose();
            // This private terminal write uses only the exact ended native owner
            // and CAS of both original protected heads. It cannot reopen source IO.
            if (run.RecoveryBackup is { } backup)
                store.WithVerifiedRecoveredVideoBackup(backup, cache.Manifest.Files.Single().Id, run.RequireRecoveryEnd,
                    requireBackup => Write(next, sourceEnded: true, requireTerminal: requireBackup));
            else Write(next, sourceEnded: true);
        }
    }
}
