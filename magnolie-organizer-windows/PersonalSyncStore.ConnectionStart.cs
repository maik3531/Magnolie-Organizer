using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PersonalSyncStore
{
    private static string ConnectionStartKey(string peerId, string runId) => $"personal_report:{peerId}:{runId}:connection_start";

    private bool ScopedInitialAcknowledged(SqliteConnection db, SqliteTransaction transaction, string peerId,
        string runId, long now, string authority, JsonObject reference)
    {
        var state = ReadMeta(ConnectionStartKey(peerId, runId), "personal_connection_start", (db, transaction));
        if (state is null || TelefonProtocolContract.Integer(state["expires_ms"]) <= now ||
            state["authority"]?.GetValue<string>() != authority || !JsonNode.DeepEquals(state["scope"], reference) ||
            TelefonProtocolContract.Integer(state["acknowledged"]) != state["message_ids"]!.AsArray().Count ||
            state["outgoing_window"] is not null) return false;
        var aggregate = state["record_hash"]!.GetValue<string>();
        return state["outgoing_hashes"]!.AsArray().All(item =>
        {
            var hash = item!.GetValue<string>();
            var resultId = state["outgoing_results"]?[hash]?.GetValue<string>();
            return resultId is not null && ReadConnectionReceipt(db, transaction, peerId, resultId, now) is not null &&
                LoadAttachmentMetadata(peerId, runId, false, aggregate, hash, "outgoing", now, (db, transaction))["complete"]?.GetValue<bool>() == true;
        });
    }

    internal void StageScopedConnectionStart(string peerId, byte[] publicKey, JsonObject request, JsonObject manifest,
        IReadOnlyList<JsonObject> batches, string savedText, NativeBookSaveState saved, long now, string authority,
        Func<string> currentAuthority, Func<bool> currentBook)
    {
        PersonalSyncContract.ValidateScopedConnectionRequest(request);
        if (!ValidConnectionAuthority(authority) || !currentBook() || BaumSyncSnapshot.Hash(savedText) != saved.Sha256)
            throw new InvalidOperationException("The connection start has no exact saved book and reader.");
        if (batches.Count is < 1 or > 4096) throw new InvalidDataException("Invalid initial connection batch count.");
        var reference = PhoneContentScope.Reference(manifest);
        var runId = request["run_id"]!.GetValue<string>();
        var records = new JsonArray();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var aggregate = batches[0]["records_hash"]?.GetValue<string>();
        for (var index = 0; index < batches.Count; index++)
        {
            var batch = batches[index];
            PersonalSyncContract.ValidateBody("personal_sync.batch", batch);
            if (batch["run_id"]!.GetValue<string>() != runId || !JsonNode.DeepEquals(batch["format"], request["format"]) ||
                batch["reply"]!.GetValue<bool>() || TelefonProtocolContract.Integer(batch["sequence"]) != index ||
                batch["last"]!.GetValue<bool>() != (index == batches.Count - 1) || batch["records_hash"]!.GetValue<string>() != aggregate ||
                !ids.Add(batch["batch_id"]!.GetValue<string>()))
                throw new InvalidDataException("Conflicting initial connection batch.");
            foreach (var record in batch["records"]!.AsArray()) records.Add(record!.DeepClone());
            if (records.Count > 100_000) throw new InvalidDataException("The initial connection batch is too large.");
        }
        var selected = records.OfType<JsonObject>().ToArray();
        PersonalSyncContract.ValidateSelectedRecords(request, selected, complete: true);
        if (aggregate != PersonalSyncContract.RecordsHash(records) || PhoneContentScope.FilterRecords(selected, manifest).Count != selected.Length)
            throw new InvalidDataException("The initial connection records do not match the accepted scope.");

        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        void RequireCurrent()
        {
            if (Store.RestoreFenced || !currentBook() || currentAuthority() != authority)
                throw new InvalidOperationException("The initial connection group lost its reader or book.");
        }
        RequireCurrent();
        if (ReadMeta(RunKey(peerId, runId), "personal_run", (db, transaction)) is not null ||
            ReadMeta($"personal_scope:{peerId}:{runId}", "personal_scope", (db, transaction)) is not null)
            throw new InvalidOperationException("This connection run already has a durable identity.");
        var shared = Store.SharedSettings(peerId, publicKey) ?? throw new InvalidOperationException("Shared preferences are unavailable.");
        var effective = SharedSyncSettings.Effective(shared);
        if (effective["auto_mode"]?.GetValue<string>() != "connection" || effective["content_mode"]?.GetValue<string>() != "phone_scope")
            throw new InvalidOperationException("The shared choice does not allow this scoped connection start.");
        var identity = Store.LoadOrCreateIdentity();
        CryptographicOperations.ZeroMemory(identity.PrivateKey);
        var key = ConnectionStartKey(peerId, runId);
        // The request has the shortest wire lifetime. Batch and original
        // rows must not outlive the request that authorizes the group.
        var expiry = checked(now + 3_600_000);
        var hashes = new HashSet<string>(StringComparer.Ordinal);
        if (ValidateScopedOriginalManifest(records))
            VerifyScopedOriginalBook(records, JsonNode.Parse(savedText)!.AsObject(), (descriptor, bytes) =>
            {
                if (!hashes.Add(descriptor["sha256"]!.GetValue<string>())) return;
                StageAttachmentCore(peerId, runId, false, aggregate!, descriptor, "outgoing", ConnectionOriginalPolicy, expiry,
                    bytes.Chunk(PersonalSyncContract.ChunkRaw).Select((chunk, index) => (index, chunk)), (db, transaction));
            });
        using var insert = db.CreateCommand(); insert.Transaction = transaction;
        insert.CommandText = """
            INSERT INTO outbox (message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy)
            VALUES($id,$peer,$kind,$now,$expiry,$payload,0,$now,'','connection_only')
            """;
        var id = insert.Parameters.Add("$id", SqliteType.Text);
        var payload = insert.Parameters.Add("$payload", SqliteType.Blob);
        insert.Parameters.AddWithValue("$peer", peerId); insert.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind);
        insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expiry", expiry);
        var capacity = Scalar(db, transaction, "SELECT COALESCE(SUM(length(payload)),0) FROM outbox");
        var messageIds = new JsonArray();
        foreach (var (kind, body) in batches.Select(batch => (Kind: "personal_sync.batch", Body: batch))
            .Prepend(("personal_sync.request", request)))
        {
            var messageId = Guid.NewGuid().ToString("D");
            var frame = new JsonObject
            {
                ["type"] = "message", ["v"] = 1, ["kind"] = PhoneContentScope.DataKind, ["message_id"] = messageId,
                ["created_ms"] = now, ["expires_ms"] = expiry, ["body"] = PhoneContentScope.Wrap(kind, body, manifest)
            };
            TelefonMessageContract.ValidateMessage(frame, now, false);
            var encrypted = Store.Seal("outbox", messageId, TelefonCrypto.Canonical(frame));
            capacity = checked(capacity + encrypted.Length);
            if (capacity > TelefonStore.OutboxLimitBytes) throw new InvalidOperationException("queue_full");
            id.Value = messageId; payload.Value = encrypted;
            insert.ExecuteNonQuery();
            messageIds.Add(messageId);
        }
        var run = new JsonObject
        {
            ["body"] = request.DeepClone(), ["created_ms"] = now, ["expires_ms"] = expiry,
            ["connection_authority"] = authority, ["connection_start_id"] = messageIds[0]!.DeepClone()
        };
        var binding = new JsonObject
        {
            ["peer_key"] = Convert.ToHexString(publicKey), ["local_actor"] = identity.Id, ["scope"] = reference.DeepClone(),
            ["content_policy"] = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(shared["settings"]!["content_mode"]!.AsObject()))).ToLowerInvariant()
        };
        var plan = new JsonObject
        {
            ["authority"] = authority, ["request"] = request.DeepClone(), ["scope"] = reference.DeepClone(), ["record_hash"] = aggregate,
            ["book_source"] = saved.BookSource, ["book_sequence"] = saved.Sequence, ["book_sha256"] = saved.Sha256,
            ["message_ids"] = messageIds, ["acknowledged"] = 0, ["expires_ms"] = expiry,
            ["outgoing_hashes"] = new JsonArray(hashes.Order(StringComparer.Ordinal).Select(hash => (JsonNode?)JsonValue.Create(hash)).ToArray())
        };
        WriteMeta(RunKey(peerId, runId), "personal_run", run, false, (db, transaction));
        WriteMeta($"personal_scope:{peerId}:{runId}", "personal_scope", binding, false, (db, transaction));
        WriteMeta(key, "personal_connection_start", plan, false, (db, transaction));
        RequireCurrent();
        transaction.Commit();
    }

    internal JsonObject? NextScopedConnectionStart(string peerId, string runId, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook, Func<string, bool> controlAckWritten)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
        return ReadScopedConnectionStart(db, transaction, peerId, runId, now, currentAuthority, currentBook, controlAckWritten)?.Frame;
    }

    internal bool AcknowledgeScopedConnectionStart(string peerId, string runId, JsonObject written, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook, Func<string, bool> controlAckWritten,
        out bool complete)
    {
        complete = false;
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var current = ReadScopedConnectionStart(db, transaction, peerId, runId, now, currentAuthority, currentBook, controlAckWritten);
        if (current is not { } item || !JsonNode.DeepEquals(written, item.Frame)) return false;
        var id = written["message_id"]!.GetValue<string>();
        using var delete = db.CreateCommand(); delete.Transaction = transaction;
        delete.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND message_id=$id AND transport_policy='connection_only'";
        delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$id", id);
        if (delete.ExecuteNonQuery() != 1) return false;
        var cursor = item.Cursor;
        if (item.Chunk) AcknowledgeScopedOutgoingChunk(item.Plan);
        else item.Plan["acknowledged"] = ++cursor;
        WriteMeta(ConnectionStartKey(peerId, runId), "personal_connection_start", item.Plan, true, (db, transaction));
        RequireScopedReplyAuthority(item.Plan, currentAuthority, currentBook);
        transaction.Commit();
        complete = cursor == item.Plan["message_ids"]!.AsArray().Count && item.Plan["outgoing_window"] is null;
        return true;
    }

    private (JsonObject Frame, JsonObject Plan, int Cursor, bool Chunk)? ReadScopedConnectionStart(SqliteConnection db, SqliteTransaction transaction,
        string peerId, string runId, long now, Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook,
        Func<string, bool> controlAckWritten)
    {
        var key = ConnectionStartKey(peerId, runId);
        var plan = ReadMeta(key, "personal_connection_start", (db, transaction));
        var run = LoadRun(peerId, runId, now, (db, transaction));
        if (plan is null || run is not { Expired: false, Policy: "connection_only" }) return null;
        var expiry = TelefonProtocolContract.Integer(plan["expires_ms"]);
        var ids = plan["message_ids"]!.AsArray();
        var cursor = checked((int)TelefonProtocolContract.Integer(plan["acknowledged"]));
        var binding = ReadMeta(RunKey(peerId, runId), "personal_run", (db, transaction));
        if (expiry != run.ExpiresMs || cursor < 0 || cursor > ids.Count || ids.Count < 2 ||
            !JsonNode.DeepEquals(plan["request"], run.Request) ||
            !JsonNode.DeepEquals(binding?["connection_start_id"], ids[0]) ||
            !JsonNode.DeepEquals(binding?["connection_authority"], plan["authority"]))
            throw new InvalidDataException("The initial connection plan differs from its durable run.");
        var window = cursor == ids.Count ? plan["outgoing_window"] as JsonObject : null;
        var chunk = window?["frames"]?[0] as JsonObject;
        if (cursor == ids.Count && chunk is null) return null;
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        if (chunk is not null)
        {
            expiry = TelefonProtocolContract.Integer(window!["expires_ms"]);
            var requestId = window["request_id"]!.GetValue<string>();
            if (expiry <= now || !controlAckWritten(requestId) || ReadConnectionReceipt(db, transaction, peerId, requestId, now) is null)
                return null;
        }
        var id = (chunk?["message_id"] ?? ids[cursor])!.GetValue<string>();
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = """
            SELECT payload FROM outbox WHERE peer_id=$peer AND message_id=$id AND kind=$kind
            AND transport_policy='connection_only' AND expires_ms=$expiry
            """;
        read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$id", id);
        read.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind); read.Parameters.AddWithValue("$expiry", expiry);
        if (read.ExecuteScalar() is not byte[] payload) return null;
        var frame = JsonNode.Parse(Store.Open("outbox", id, payload))!.AsObject();
        TelefonMessageContract.ValidateMessage(frame, now, false);
        var wrapper = frame["body"]!.AsObject();
        var body = wrapper["body"]!.AsObject();
        var expectedKind = chunk is not null ? "personal_sync.attachment_chunk" : cursor == 0 ? "personal_sync.request" : "personal_sync.batch";
        if (frame["message_id"]!.GetValue<string>() != id || frame["kind"]!.GetValue<string>() != PhoneContentScope.DataKind ||
            TelefonProtocolContract.Integer(frame["expires_ms"]) != expiry || !JsonNode.DeepEquals(wrapper["scope"], plan["scope"]) ||
            wrapper["kind"]!.GetValue<string>() != expectedKind || body["run_id"]!.GetValue<string>() != runId)
            throw new InvalidDataException("The initial connection outbox frame differs from its plan.");
        var validBody = chunk is not null
            ? TelefonProtocolContract.Integer(body["format"]) == 2 && body["reply"]?.GetValue<bool>() == false &&
                JsonNode.DeepEquals(body["sha256"], chunk["sha256"]) && JsonNode.DeepEquals(body["index"], chunk["index"]) &&
                JsonNode.DeepEquals(body["records_hash"], plan["record_hash"])
            : cursor == 0 ? JsonNode.DeepEquals(body, run.Request) : JsonNode.DeepEquals(body["format"], run.Request["format"]) &&
                !body["reply"]!.GetValue<bool>() && TelefonProtocolContract.Integer(body["sequence"]) == cursor - 1 &&
                body["last"]!.GetValue<bool>() == (cursor == ids.Count - 1) && JsonNode.DeepEquals(body["records_hash"], plan["record_hash"]);
        if (!validBody) throw new InvalidDataException("The initial connection outbox body differs from its plan.");
        return (frame, plan, cursor, chunk is not null);
    }
}
