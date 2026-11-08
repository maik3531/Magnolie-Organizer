using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
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
            body = new JsonObject { ["format"] = 1, ["cache_version"] = cache.Version, ["nonce"] = cache.Nonce,
                ["offer"] = run.Offer.DeepClone(), ["permission_epoch"] = run.PermissionEpoch, ["phase"] = "offer_planned",
                ["acceptance"] = null, ["sent_chunks"] = new JsonArray(), ["pending_chunk"] = null, ["peer_saved"] = null };
            Write(body.DeepClone().AsObject()); // Intent committed before the FIRST actual secure offer byte.
        }

        private void Write(JsonObject next)
        {
            run.Require();
            var plain = TelefonCrypto.Canonical(next); byte[] cipher;
            try
            {
                if (plain.Length > 32768) throw DeviceFileControl.Error("media_source_exchange_bound");
                cipher = store.Seal("native_media_source_exchange", cache.PeerId + "/" + cache.JobId, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            lock (store.gate)
            {
                run.Require(); using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
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
                command.CommandText = "INSERT INTO native_media_source_exchanges(peer_id,job_id,value) VALUES($peer,$job,$value) ON CONFLICT(peer_id,job_id) DO UPDATE SET value=excluded.value";
                command.Parameters.AddWithValue("$value", cipher); command.ExecuteNonQuery(); run.Require(); transaction.Commit();
                body = next; version = SourceDigest(cipher);
                command.Transaction = null; command.CommandText = "SELECT value FROM native_media_source_exchanges WHERE peer_id=$peer AND job_id=$job";
                if (command.ExecuteScalar() is not byte[] saved || SourceDigest(saved) != version) throw DeviceFileControl.Error("media_source_exchange_readback_failed");
                run.Require();
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
            var next = body.DeepClone().AsObject(); next["phase"] = "accepted"; next["acceptance"] = acceptance.DeepClone(); Write(next);
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
            var next = body.DeepClone().AsObject(); next["phase"] = "peer_saved"; next["peer_saved"] = saved.DeepClone(); Write(next);
        }
        internal void PeerReadback(JsonObject readback)
        {
            if (!run.ExpectReadback || Phase != "peer_saved" || body["pending_chunk"] is not null || !AllChunksSent || body["peer_readback"] is not null)
                throw DeviceFileControl.Error("media_source_exchange_readback_state");
            var next = body.DeepClone().AsObject(); next["phase"] = "peer_readback"; next["peer_readback"] = readback.DeepClone(); Write(next);
        }
    }
}
