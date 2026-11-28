using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Refs #330. One original root journal, explicitly format2. Uses the same
    // protected table/CAS and serial writer as legacy, but no single-file END.
    internal sealed class NativeMediaBatchSourceExchange
    {
        private readonly NativePreparedMediaBatch cache;
        private readonly TelefonConnection.NativeMediaBatchSendRun run;
        private readonly TelefonStore store;
        private JsonObject body;
        private string? version;
        internal string Phase => body["phase"]!.GetValue<string>();
        internal JsonObject Observation => body.DeepClone().AsObject();
        private bool AllChunksSent => cache.Manifest.Files.All(file =>
            body["sent_chunks"]![file.Id]!.AsArray().Count == (file.Size + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes);

        internal NativeMediaBatchSourceExchange(TelefonConnection.NativeMediaBatchSendRun run)
        {
            this.run = run; cache = run.Cache; store = cache.OwnerStore; run.Require();
            if (cache.Recovery is { } recovery)
            {
                body = recovery.Exchange; version = recovery.ExchangeVersion; Require();
                return;
            }
            var sent = new JsonObject(); foreach (var file in cache.Manifest.Files) sent[file.Id] = new JsonArray();
            body = new JsonObject { ["format"] = 2, ["cache_version"] = cache.Version, ["nonce"] = cache.Nonce,
                ["offer"] = run.Offer.DeepClone(), ["permission_epoch"] = run.PermissionEpoch, ["phase"] = "offer_planned",
                ["acceptance"] = null, ["sent_chunks"] = sent, ["pending_chunk"] = null, ["peer_saved"] = null, ["peer_readback"] = null,
                ["reader_id"] = run.ReaderId };
            Write(body.DeepClone().AsObject());
        }

        private void CheckCipher(byte[] cipher)
        {
            if (SourceDigest(cipher) != version) throw DeviceFileControl.Error("media_source_exchange_changed");
            var clear = store.Open("native_media_source_exchange", cache.PeerId + "/" + cache.JobId, cipher);
            try { if (!JsonNode.DeepEquals(JsonNode.Parse(clear), body)) throw DeviceFileControl.Error("media_source_exchange_changed"); }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }

        internal void Require()
        {
            cache.RequireHeads((db, transaction) =>
            {
                using var read = db.CreateCommand(); read.Transaction = transaction;
                read.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job AND length(value) BETWEEN 29 AND 1048604";
                read.Parameters.AddWithValue("$peer", cache.PeerId); read.Parameters.AddWithValue("$job", cache.JobId);
                if (read.ExecuteScalar() is not byte[] cipher) throw DeviceFileControl.Error("media_source_exchange_changed");
                CheckCipher(cipher);
            });
        }

        internal void RequireLocalRetirementHead(NativeBatchSourceRetirement owner)
        {
            if (!owner.OwnsExchange(this)) throw DeviceFileControl.Error("media_source_batch_original_retirement_owner_required");
            lock (store.gate)
            {
                using var db = store.OpenNativeMediaDatabase(); db.Open(); using var read = db.CreateCommand();
                read.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job AND length(value) BETWEEN 29 AND 1048604";
                read.Parameters.AddWithValue("$peer", cache.PeerId); read.Parameters.AddWithValue("$job", cache.JobId);
                if (read.ExecuteScalar() is not byte[] cipher) throw DeviceFileControl.Error("media_source_exchange_changed");
                CheckCipher(cipher);
            }
        }

        private void Write(JsonObject next, NativeBatchSourceRetirement? retirement = null)
        {
            void Current() { if (retirement is null) run.Require(); else retirement.Current(); }
            Current(); var plain = TelefonCrypto.Canonical(next); byte[] cipher;
            try
            {
                if (plain.Length > 1048576) throw DeviceFileControl.Error("media_source_exchange_bound");
                cipher = store.Seal("native_media_source_exchange", cache.PeerId + "/" + cache.JobId, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            lock (store.gate)
            {
                Current(); using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
                using var command = db.CreateCommand(); command.Transaction = transaction;
                command.CommandText = "CREATE TABLE IF NOT EXISTS native_media_source_exchanges(peer_id TEXT NOT NULL,job_id TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,job_id))";
                command.ExecuteNonQuery();
                command.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job";
                command.Parameters.AddWithValue("$peer", cache.PeerId); command.Parameters.AddWithValue("$job", cache.JobId);
                var previous = command.ExecuteScalar();
                if (version is null)
                { if (previous is not null) throw DeviceFileControl.Error("media_source_exchange_original_attempt_required"); }
                else if (previous is byte[] held) CheckCipher(held);
                else throw DeviceFileControl.Error("media_source_exchange_changed");
                command.CommandText = "INSERT INTO native_media_source_exchanges(peer_id,job_id,value) VALUES($peer,$job,$value) ON CONFLICT(peer_id,job_id) DO UPDATE SET value=excluded.value";
                command.Parameters.AddWithValue("$value", cipher); command.ExecuteNonQuery(); Current();
                retirement?.RequireBackupAnchor(db, transaction); transaction.Commit();
                body = next; version = SourceDigest(cipher);
                command.Transaction = null; command.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job";
                if (command.ExecuteScalar() is not byte[] saved) throw DeviceFileControl.Error("media_source_exchange_readback_failed");
                CheckCipher(saved); Current();
            }
        }

        internal void OfferSent()
        {
            if (Phase != "offer_planned") throw DeviceFileControl.Error("media_source_exchange_offer_state");
            var next = body.DeepClone().AsObject(); next["phase"] = "offer_sent"; Write(next);
        }
        internal void Accepted(JsonObject message)
        {
            if (Phase != "offer_sent") throw DeviceFileControl.Error("media_source_exchange_accept_state");
            var next = body.DeepClone().AsObject(); next["phase"] = "accepted"; next["acceptance"] = message.DeepClone(); Write(next);
        }
        internal void PlanChunk(DeviceFileChunkRequest request)
        {
            var file = cache.Manifest.Files.SingleOrDefault(file => file.Id == request.FileId);
            if (Phase != "accepted" || body["pending_chunk"] is not null || file is null || request.ChunkIndex < 0 ||
                (long)request.ChunkIndex * DeviceFileManifest.ChunkBytes >= file.Size)
                throw DeviceFileControl.Error("media_source_exchange_chunk_state");
            var next = body.DeepClone().AsObject();
            next["pending_chunk"] = new JsonObject { ["request_id"] = request.RequestId, ["chunk_index"] = request.ChunkIndex, ["file_id"] = request.FileId };
            Write(next);
        }
        internal void ChunkSent(DeviceFileChunkRequest request)
        {
            var pending = body["pending_chunk"];
            if (Phase != "accepted" || pending?["request_id"]?.GetValue<string>() != request.RequestId ||
                pending["file_id"]!.GetValue<string>() != request.FileId || pending["chunk_index"]!.GetValue<int>() != request.ChunkIndex)
                throw DeviceFileControl.Error("media_source_exchange_original_chunk_required");
            var next = body.DeepClone().AsObject(); next["pending_chunk"] = null;
            var sent = next["sent_chunks"]![request.FileId]!.AsArray();
            if (!sent.Any(value => value!.GetValue<int>() == request.ChunkIndex)) sent.Add(request.ChunkIndex);
            Write(next);
        }
        internal void PeerSaved(JsonObject message)
        {
            if (Phase != "accepted" || body["pending_chunk"] is not null || !AllChunksSent)
                throw DeviceFileControl.Error("media_source_exchange_unsent_chunks");
            var next = body.DeepClone().AsObject(); next["phase"] = "peer_saved"; next["peer_saved"] = message.DeepClone(); Write(next);
        }
        internal void PeerReadback(JsonObject message)
        {
            if (Phase != "peer_saved" || body["pending_chunk"] is not null || !AllChunksSent || body["peer_readback"] is not null)
                throw DeviceFileControl.Error("media_source_exchange_readback_state");
            var next = body.DeepClone().AsObject(); next["phase"] = "peer_readback"; next["peer_readback"] = message.DeepClone();
            if (run.RecoveryRequest is { } request)
                next["recovery"] = new JsonObject { ["request"] = request.DeepClone(), ["permission_epoch"] = run.PermissionEpoch, ["reader_id"] = run.ReaderId };
            Write(next);
        }

        internal void PlanRetirement(NativeBatchSourceRetirement owner, JsonObject plan)
        {
            run.Require();
            if (!owner.MatchesOriginalRun(run) || Phase != "peer_readback" || !AllChunksSent || body["pending_chunk"] is not null || body["source_retirement"] is not null)
                throw DeviceFileControl.Error("media_source_batch_retirement_existing_intent_held");
            var next = body.DeepClone().AsObject(); next["phase"] = "end_planned"; next["source_retirement"] = plan.DeepClone(); Write(next);
        }

        internal void FinishRetirement(NativeBatchSourceRetirement owner)
        {
            owner.Current();
            if (!owner.PermitsTerminalWrite(this) || Phase != "end_planned" || !AllChunksSent || body["pending_chunk"] is not null || body["source_end"] is not null)
                throw DeviceFileControl.Error("media_source_batch_original_retirement_owner_required");
            var next = body.DeepClone().AsObject(); next["phase"] = "source_ended";
            next["source_end"] = new JsonObject { ["format"] = 2, ["job_id"] = cache.JobId,
                ["cache_version"] = body["cache_version"]!.DeepClone(), ["nonce"] = body["nonce"]!.DeepClone(),
                ["retirement_sha256"] = DeviceFileControl.Digest("magnolie-native-source-batch-retirement-v1\0", body["source_retirement"]!),
                ["readback_sha256"] = body["peer_readback"]!["body"]!["readback_sha256"]!.DeepClone() };
            Write(next, owner);
        }
    }
}
