using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PersonalSyncStore
{
    private static string ConnectionOriginalResultsKey(string peerId, string runId) => $"personal_report:{peerId}:{runId}:connection_original_results";

    internal void QueueScopedOriginalResults(string peerId, string messageId, string token, NativeBookSaveState saved,
        long now, Func<JsonObject, JsonObject, string> currentAuthority, Func<string, bool> acknowledgementWritten,
        Func<NativeBookSaveState?> currentBook)
    {
        if (Store.RestoreFenced || currentBook() != saved)
            throw new InvalidOperationException("The original results have no confirmed saved book.");
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var (run, reference, authority, batch, _) = ReadScopedConnectionInput(db, transaction, peerId, messageId, token,
            now, currentAuthority, acknowledgementWritten);
        if (!batch.HasScopedOriginals && !batch.Reply) throw new InvalidOperationException("The confirmed book has no scoped original results.");
        ReadCompletedScopedOriginals(db, transaction, batch, now, includeData: false);
        var key = ConnectionOriginalResultsKey(peerId, run.RunId);
        if (ReadMeta(key, "personal_connection_reply", (db, transaction)) is not null)
            throw new InvalidOperationException("The scoped original results are already queued.");
        var expires = Math.Min(batch.ExpiresMs, run.ExpiresMs);
        var hashes = ScopedOriginalDescriptors(batch.Records).Select(descriptor => descriptor["sha256"]!.GetValue<string>())
            .Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        using var insert = db.CreateCommand(); insert.Transaction = transaction;
        insert.CommandText = """
            INSERT INTO outbox (message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy)
            VALUES($id,$peer,$kind,$now,$expires,$payload,0,$now,'','connection_only')
            """;
        var messageParameter = insert.Parameters.Add("$id", SqliteType.Text);
        var payloadParameter = insert.Parameters.Add("$payload", SqliteType.Blob);
        insert.Parameters.AddWithValue("$peer", peerId); insert.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind);
        insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", expires);
        var capacity = Scalar(db, transaction, "SELECT COALESCE(SUM(length(payload)),0) FROM outbox");
        var ids = new JsonArray();
        foreach (var hash in hashes)
        {
            var id = Guid.NewGuid().ToString("D");
            var frame = new JsonObject
            {
                ["type"] = "message", ["v"] = 1, ["kind"] = PhoneContentScope.DataKind, ["message_id"] = id,
                ["created_ms"] = now, ["expires_ms"] = expires,
                ["body"] = PhoneContentScope.ValidateData(new JsonObject
                {
                    ["format"] = PhoneContentScope.Version, ["scope"] = reference.DeepClone(),
                    ["kind"] = "personal_sync.attachment_result", ["body"] = new JsonObject
                    {
                        ["format"] = 2, ["run_id"] = run.RunId, ["reply"] = batch.Reply, ["records_hash"] = batch.RecordsHash,
                        ["sha256"] = hash, ["state"] = "complete", ["error"] = "none"
                    }
                })
            };
            TelefonMessageContract.ValidateMessage(frame, now, false);
            var encrypted = Store.Seal("outbox", id, TelefonCrypto.Canonical(frame));
            capacity = checked(capacity + encrypted.Length);
            if (capacity > TelefonStore.OutboxLimitBytes) throw new InvalidOperationException("queue_full");
            messageParameter.Value = id; payloadParameter.Value = encrypted;
            insert.ExecuteNonQuery();
            ids.Add(id);
        }
        var plan = new JsonObject
        {
            ["authority"] = authority, ["request"] = run.Request.DeepClone(), ["scope"] = reference.DeepClone(),
            ["input_message"] = messageId, ["token"] = token, ["record_hash"] = batch.RecordsHash,
            ["book_source"] = saved.BookSource, ["book_sequence"] = saved.Sequence, ["book_sha256"] = saved.Sha256,
            ["message_ids"] = ids, ["acknowledged"] = 0, ["expires_ms"] = expires,
            ["incoming_reply"] = batch.Reply,
            ["original_hashes"] = new JsonArray(hashes.Select(hash => (JsonNode?)JsonValue.Create(hash)).ToArray())
        };
        WriteMeta(key, "personal_connection_reply", plan, false, (db, transaction));
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        transaction.Commit();
    }
}
