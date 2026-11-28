using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PersonalSyncStore
{
    internal TelefonAck StageScopedOutgoingOriginalControl(string peerId, JsonObject envelope, long now, bool reply,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook)
    {
        var wrapper = envelope["body"]!.AsObject();
        var kind = wrapper["kind"]!.GetValue<string>();
        var body = wrapper["body"]!.AsObject();
        if (body["reply"]?.GetValue<bool>() != reply)
            throw new InvalidOperationException("The original control has the wrong direction.");
        var runId = body["run_id"]!.GetValue<string>();
        var aggregate = body["records_hash"]!.GetValue<string>();
        var id = envelope["message_id"]!.GetValue<string>();
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var key = reply ? ConnectionReplyKey(peerId, runId) : ConnectionStartKey(peerId, runId);
        var planType = reply ? "personal_connection_reply" : "personal_connection_start";
        var plan = ReadMeta(key, planType, (db, transaction));
        if (plan is null) throw new IOException("The scoped reply has not been written.");
        var expiry = TelefonProtocolContract.Integer(plan["expires_ms"]);
        if (expiry <= now || plan["record_hash"]?.GetValue<string>() != aggregate ||
            !JsonNode.DeepEquals(plan["scope"], wrapper["scope"]) || plan["outgoing_hashes"] is not JsonArray hashes || hashes.Count == 0)
            throw new InvalidOperationException("The original control does not match the scoped reply plan.");
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        if (ReadConnectionReceipt(db, transaction, peerId, id, now) is { } prior)
        {
            if (!JsonNode.DeepEquals(prior, envelope)) throw new InvalidDataException("Conflicting reply original control receipt.");
            return new TelefonAck(id, "duplicate", "none");
        }
        if (TelefonProtocolContract.Integer(plan["acknowledged"]) != plan["message_ids"]!.AsArray().Count - (reply ? 1 : 0) ||
            plan["outgoing_window"] is not null)
            throw new IOException("The prior reply frames are still awaiting actual acknowledgements.");
        if (kind == "personal_sync.attachment_request")
            plan["outgoing_window"] = StageOutgoingOriginalWindow(db, transaction, peerId, runId, aggregate, hashes, plan, envelope, now, expiry, reply);
        else if (kind == "personal_sync.attachment_result")
        {
            var hash = body["sha256"]!.GetValue<string>();
            var transfer = RequireOutgoingOriginal(db, transaction, peerId, runId, aggregate, hash, hashes, now, expiry, reply);
            var count = checked((int)TelefonProtocolContract.Integer(transfer["total_chunks"]));
            if (body["state"]?.GetValue<string>() != "complete" || body["error"]?.GetValue<string>() != "none" ||
                ReplyChunkMask(plan, hash) != (1L << count) - 1)
                throw new InvalidOperationException("The reply original lacks positive acknowledgements for all its chunks.");
            MarkScopedOriginalComplete(db, transaction, peerId, runId, reply, aggregate, hash, "outgoing", expiry, now);
            var completed = plan["outgoing_results"] as JsonObject ?? new JsonObject();
            completed.Add(hash, id);
            if (completed.Parent is null) plan["outgoing_results"] = completed;
        }
        else throw new InvalidDataException("Unknown scoped reply original control.");
        WriteConnectionReceipt(db, transaction, peerId, envelope, now);
        WriteMeta(key, planType, plan, true, (db, transaction));
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        transaction.Commit();
        return new TelefonAck(id, "accepted", "none");
    }

    private JsonObject StageOutgoingOriginalWindow(SqliteConnection db, SqliteTransaction transaction, string peerId, string runId,
        string aggregate, JsonArray hashes, JsonObject plan, JsonObject envelope, long now, long expiry, bool reply)
    {
        var body = envelope["body"]!["body"]!.AsObject();
        var windowExpiry = Math.Min(expiry, TelefonProtocolContract.Integer(envelope["expires_ms"]));
        var frames = new JsonArray();
        var capacity = Scalar(db, transaction, "SELECT COALESCE(SUM(length(payload)),0) FROM outbox");
        using var insert = db.CreateCommand(); insert.Transaction = transaction;
        insert.CommandText = """
            INSERT INTO outbox (message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy)
            VALUES($id,$peer,$kind,$now,$expires,$payload,0,$now,'','connection_only')
            """;
        var id = insert.Parameters.Add("$id", SqliteType.Text);
        var payload = insert.Parameters.Add("$payload", SqliteType.Blob);
        insert.Parameters.AddWithValue("$peer", peerId); insert.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind);
        insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", windowExpiry);
        foreach (var want in body["wants"]!.AsArray().OfType<JsonObject>())
        {
            var hash = want["sha256"]!.GetValue<string>();
            var transfer = RequireOutgoingOriginal(db, transaction, peerId, runId, aggregate, hash, hashes, now, expiry, reply);
            var total = TelefonProtocolContract.Integer(transfer["total_chunks"]);
            var acknowledged = ReplyChunkMask(plan, hash);
            foreach (var range in want["ranges"]!.AsArray().OfType<JsonArray>())
            {
                var start = checked((int)TelefonProtocolContract.Integer(range[0]));
                var end = checked((int)TelefonProtocolContract.Integer(range[1]));
                if (end > total || frames.Count + end - start > ConnectionWindowSize)
                    throw new InvalidOperationException("The requested reply original range exceeds its bounded window.");
                for (var index = start; index < end; index++)
                {
                    if ((acknowledged & 1L << index) != 0)
                        throw new InvalidOperationException("The reply original chunk was already positively acknowledged.");
                    var raw = ReadOutgoingScopedOriginalChunk(db, transaction, peerId, runId, aggregate, hash, index, reply);
                    try
                    {
                        var messageId = Guid.NewGuid().ToString("D");
                        var frame = new JsonObject
                        {
                            ["type"] = "message", ["v"] = 1, ["kind"] = PhoneContentScope.DataKind, ["message_id"] = messageId,
                            ["created_ms"] = now, ["expires_ms"] = windowExpiry,
                            ["body"] = PhoneContentScope.ValidateData(new JsonObject
                            {
                                ["format"] = PhoneContentScope.Version, ["scope"] = plan["scope"]!.DeepClone(),
                                ["kind"] = "personal_sync.attachment_chunk", ["body"] = new JsonObject
                                {
                                    ["format"] = 2, ["run_id"] = runId, ["reply"] = reply, ["records_hash"] = aggregate,
                                    ["sha256"] = hash, ["index"] = index, ["data"] = Convert.ToBase64String(raw)
                                }
                            })
                        };
                        TelefonMessageContract.ValidateMessage(frame, now, false);
                        var encrypted = Store.Seal("outbox", messageId, TelefonCrypto.Canonical(frame));
                        capacity = checked(capacity + encrypted.Length);
                        if (capacity > TelefonStore.OutboxLimitBytes) throw new InvalidOperationException("queue_full");
                        id.Value = messageId; payload.Value = encrypted;
                        insert.ExecuteNonQuery();
                        frames.Add(new JsonObject { ["message_id"] = messageId, ["sha256"] = hash, ["index"] = index });
                    }
                    finally { CryptographicOperations.ZeroMemory(raw); }
                }
            }
        }
        return new JsonObject { ["request_id"] = envelope["message_id"]!.DeepClone(), ["expires_ms"] = windowExpiry, ["frames"] = frames };
    }

    private JsonObject RequireOutgoingOriginal(SqliteConnection db, SqliteTransaction transaction, string peerId, string runId,
        string aggregate, string hash, JsonArray hashes, long now, long expiry, bool reply)
    {
        if (!hashes.Any(value => value?.GetValue<string>() == hash))
            throw new InvalidOperationException("The reply original is outside the declared book.");
        var transfer = LoadAttachmentMetadata(peerId, runId, reply, aggregate, hash, "outgoing", now, (db, transaction));
        if (transfer["transport_policy"]?.GetValue<string>() != ConnectionOriginalPolicy ||
            transfer["complete"]?.GetValue<bool>() != false || TelefonProtocolContract.Integer(transfer["expires_ms"]) != expiry)
            throw new InvalidOperationException("The reply original no longer belongs to its current window.");
        return transfer;
    }

    private byte[] ReadOutgoingScopedOriginalChunk(SqliteConnection db, SqliteTransaction transaction,
        string peerId, string runId, string aggregate, string hash, int index, bool reply)
    {
        using var command = db.CreateCommand(); command.Transaction = transaction;
        command.CommandText = """
            SELECT payload FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run AND reply=$reply
            AND records_hash=$records AND sha256=$hash AND direction='outgoing' AND chunk_index=$index
            """;
        Parameters(command, peerId, runId, reply);
        command.Parameters.AddWithValue("$records", aggregate); command.Parameters.AddWithValue("$hash", hash);
        command.Parameters.AddWithValue("$index", index);
        if (command.ExecuteScalar() is not byte[] encrypted) throw new InvalidOperationException("The saved reply original bytes are missing.");
        return Store.Open("personal_attachment_chunk", ChunkPrimary(peerId, runId, reply, aggregate, hash, "outgoing", index), encrypted);
    }

    private static long ReplyChunkMask(JsonObject plan, string hash) =>
        plan["outgoing_acked_chunks"]?[hash] is { } mask ? TelefonProtocolContract.Integer(mask) : 0;

    private static void AcknowledgeScopedOutgoingChunk(JsonObject plan)
    {
        var frames = plan["outgoing_window"]!["frames"]!.AsArray();
        var first = frames[0]!.AsObject();
        var hash = first["sha256"]!.GetValue<string>();
        var index = checked((int)TelefonProtocolContract.Integer(first["index"]));
        var acknowledged = plan["outgoing_acked_chunks"] as JsonObject ?? new JsonObject();
        acknowledged[hash] = ReplyChunkMask(plan, hash) | 1L << index;
        if (acknowledged.Parent is null) plan["outgoing_acked_chunks"] = acknowledged;
        frames.RemoveAt(0);
        if (frames.Count == 0) plan.Remove("outgoing_window");
    }
}
