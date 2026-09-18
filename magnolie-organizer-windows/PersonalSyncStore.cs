using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed class PersonalSyncStore(TelefonStore store)
{
    internal const long RunLifetimeMs = 86_400_000;
    internal const long MaximumAttachmentBytes = 8L * 1024 * 1024;
    private const long MaximumGlobalChunkBytes = 100L * 1024 * 1024;
    private const long MaximumRunChunkBytes = 50L * 1024 * 1024;
    private const int MaximumActiveTransfersPerPeer = 4;
    private const int MaximumAttachmentsPerRun = 64;
    private const int MaximumChunkRows = 4096;

    internal void RememberRun(string peerId, JsonObject request, long now, long? claimedExpiresMs = null)
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        PersonalSyncContract.ValidateBody("personal_sync.request", request); var runId = request["run_id"]!.GetValue<string>();
        var expires = Math.Min(checked(now + RunLifetimeMs), claimedExpiresMs ?? long.MaxValue);
        if (expires <= now) throw new InvalidDataException("Personal-Sync-Lauf ist abgelaufen.");
        var key = RunKey(peerId, runId); var existing = ReadMeta(key, "personal_run");
        if (existing is not null)
        {
            if (!JsonNode.DeepEquals(existing["body"], request) || claimedExpiresMs > existing["expires_ms"]?.GetValue<long>()) throw new InvalidDataException("Widersprüchlicher Personal-Sync-Lauf.");
            return;
        }
        WriteMeta(key, "personal_run", new JsonObject { ["body"] = request.DeepClone(), ["created_ms"] = now, ["expires_ms"] = expires }, false);
    }

    internal PersonalSyncRun? LoadRun(string peerId, string runId, long now)
    {
        var value = ReadMeta(RunKey(peerId, runId), "personal_run"); if (value is null) return null;
        var body = value["body"] as JsonObject ?? throw new InvalidDataException("Personal-Sync-Lauf beschädigt.");
        PersonalSyncContract.ValidateBody("personal_sync.request", body); var expires = TelefonProtocolContract.Integer(value["expires_ms"]);
        return new PersonalSyncRun(runId, body["trigger"]!.GetValue<string>() == "auto_wifi" ? "wifi_only" : "any", expires, expires <= now, body.DeepClone().AsObject());
    }

    internal IReadOnlyList<PersonalSyncRun> CurrentRuns(string peerId, long now)
    {
        var ids = new List<string>(); using (var connection = store.OpenDatabase())
        {
            connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT key FROM meta WHERE key LIKE $prefix"; command.Parameters.AddWithValue("$prefix", $"personal_run:{peerId}:%");
            using var reader = command.ExecuteReader(); while (reader.Read()) ids.Add(reader.GetString(0).Split(':', 3)[2]);
        }
        return ids.Select(id => LoadRun(peerId, id, now)).OfType<PersonalSyncRun>().Where(run => !run.Expired).ToArray();
    }

    internal void CleanupExpiredRuns(long now)
    {
        var expired = new List<(string PeerId, string RunId, string Key)>();
        using (var connection = store.OpenDatabase())
        {
            connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT key,value FROM meta WHERE key LIKE 'personal_run:%'";
            using var reader = command.ExecuteReader(); while (reader.Read())
            {
                var key = reader.GetString(0); var value = JsonNode.Parse(store.Open("personal_run", key, (byte[])reader[1]))!.AsObject();
                if (TelefonProtocolContract.Integer(value["expires_ms"]) <= now)
                {
                    var parts = key.Split(':', 3); if (parts.Length == 3) expired.Add((parts[1], parts[2], key));
                }
            }
        }
        if (expired.Count == 0) return;
        using var database = store.OpenDatabase(); database.Open(); using var transaction = database.BeginTransaction();
        foreach (var item in expired)
        {
            foreach (var table in new[] { "personal_batch", "personal_attachment_chunk", "personal_attachment_transfer" }) DeleteRun(database, transaction, table, item.PeerId, item.RunId);
            using var meta = database.CreateCommand(); meta.Transaction = transaction; meta.CommandText = "DELETE FROM meta WHERE key=$key OR key LIKE $report OR key LIKE $applied"; meta.Parameters.AddWithValue("$key", item.Key); meta.Parameters.AddWithValue("$report", $"personal_report:{item.PeerId}:{item.RunId}%"); meta.Parameters.AddWithValue("$applied", $"personal_applied:{item.PeerId}:{item.RunId}%"); meta.ExecuteNonQuery();
        }
        transaction.Commit();
    }

    internal PersonalSyncStagedBatch? StageBatch(string peerId, JsonObject message, string transport, long now)
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        TelefonMessageContract.ValidateMessage(message, now, true); if (message["kind"]?.GetValue<string>() != "personal_sync.batch") throw new InvalidDataException("Kein Personal-Sync-Batch.");
        var body = message["body"]!.AsObject(); var runId = body["run_id"]!.GetValue<string>(); var run = LoadRun(peerId, runId, now) ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
        if (body["format"]!.GetValue<int>() != run.Request["format"]!.GetValue<int>()) throw new InvalidDataException("Widersprüchlicher Personal-Sync-Lauf.");
        if (run.Expired || run.Policy == "wifi_only" && transport != "wifi") throw new InvalidDataException("Personal-Sync-Transportpolicy verletzt.");
        var reply = body["reply"]!.GetValue<bool>(); var sequence = checked((int)TelefonProtocolContract.Integer(body["sequence"])); if (sequence >= 4096) throw new InvalidDataException("Zu viele Personal-Sync-Batches.");
        var primary = BatchPrimary(peerId, runId, reply, sequence); var payload = store.Seal("personal_batch", primary, TelefonCrypto.Canonical(message));
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        string token;
        using (var applied = connection.CreateCommand())
        {
            applied.Transaction = transaction;
            applied.CommandText = "SELECT COUNT(*) FROM meta WHERE key=$key";
            applied.Parameters.AddWithValue("$key", $"personal_applied:{peerId}:{runId}:{(reply ? 1 : 0)}");
            if (Convert.ToInt64(applied.ExecuteScalar()) != 0) throw new InvalidDataException("Widersprüchliche Batch-Sequenz.");
        }
        using (var old = connection.CreateCommand())
        {
            old.Transaction = transaction; old.CommandText = "SELECT batch_id,message_id,payload,last,commit_token FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND sequence=$sequence";
            Parameters(old, peerId, runId, reply); old.Parameters.AddWithValue("$sequence", sequence); using var reader = old.ExecuteReader();
            if (reader.Read())
            {
                var prior = JsonNode.Parse(store.Open("personal_batch", primary, (byte[])reader[2]));
                if (reader.GetString(0) != body["batch_id"]!.GetValue<string>() || reader.GetString(1) != message["message_id"]!.GetValue<string>() || reader.GetBoolean(3) != body["last"]!.GetValue<bool>() || !JsonNode.DeepEquals(prior, message)) throw new InvalidDataException("Widersprüchliche Batch-Sequenz.");
                token = reader.GetString(4); reader.Close(); transaction.Commit(); return CompleteBatch(connection, peerId, runId, reply, token);
            }
        }
        using (var limits = connection.CreateCommand())
        {
            limits.Transaction = transaction;
            limits.CommandText = "SELECT COUNT(*),COALESCE(SUM(length(payload)),0) FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply";
            Parameters(limits, peerId, runId, reply); using var reader = limits.ExecuteReader(); reader.Read();
            if (reader.GetInt64(0) >= 4096 || reader.GetInt64(1) + payload.Length > MaximumRunChunkBytes) throw new InvalidDataException("Personal-Sync-Lauf ist zu groß.");
        }
        using (var tokenCommand = connection.CreateCommand())
        {
            tokenCommand.Transaction = transaction; tokenCommand.CommandText = "SELECT commit_token FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply LIMIT 1"; Parameters(tokenCommand, peerId, runId, reply);
            token = tokenCommand.ExecuteScalar() as string ?? Convert.ToBase64String(RandomNumberGenerator.GetBytes(32));
        }
        using (var insert = connection.CreateCommand())
        {
            insert.Transaction = transaction; insert.CommandText = "INSERT INTO personal_batch VALUES($peer,$run,$reply,$sequence,$batch,$message,$now,$expires,$payload,$last,$token)"; Parameters(insert, peerId, runId, reply);
            insert.Parameters.AddWithValue("$sequence", sequence); insert.Parameters.AddWithValue("$batch", body["batch_id"]!.GetValue<string>()); insert.Parameters.AddWithValue("$message", message["message_id"]!.GetValue<string>());
            insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", message["expires_ms"]!.GetValue<long>()); insert.Parameters.AddWithValue("$payload", payload); insert.Parameters.AddWithValue("$last", body["last"]!.GetValue<bool>()); insert.Parameters.AddWithValue("$token", token); insert.ExecuteNonQuery();
        }
        var complete = CompleteBatch(connection, peerId, runId, reply, token);
        if (complete?.Records.Count > 100_000) throw new InvalidDataException("Personal-Sync-Lauf ist zu groß.");
        transaction.Commit(); return complete;
    }

    internal bool CommitBatch(string peerId, string pendingMessageId, string token, long now, out IReadOnlyList<string> messageIds)
    {
        if (store.RestoreFenced) { messageIds = []; return false; }
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        string runId; bool reply;
        using (var identity = connection.CreateCommand()) { identity.Transaction = transaction; identity.CommandText = "SELECT run_id,reply FROM personal_batch WHERE peer_id=$peer AND message_id=$message AND commit_token=$token"; identity.Parameters.AddWithValue("$peer", peerId); identity.Parameters.AddWithValue("$message", pendingMessageId); identity.Parameters.AddWithValue("$token", token); using var reader = identity.ExecuteReader(); if (!reader.Read()) { messageIds = []; return false; } runId = reader.GetString(0); reply = reader.GetBoolean(1); }
        var complete = CompleteBatch(connection, peerId, runId, reply, token);
        if (string.IsNullOrEmpty(token) || complete is null || complete.PendingMessageId != pendingMessageId ||
            LoadRun(peerId, runId, now) is not { Expired: false })
        { messageIds = []; return false; }
        using (var expired = connection.CreateCommand())
        {
            expired.Transaction = transaction;
            expired.CommandText = "SELECT COUNT(*) FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND expires_ms<=$now";
            Parameters(expired, peerId, runId, reply); expired.Parameters.AddWithValue("$now", now);
            if (Convert.ToInt64(expired.ExecuteScalar()) != 0) { messageIds = []; return false; }
        }
        var ids = new List<string>(); using (var read = connection.CreateCommand()) { read.Transaction = transaction; read.CommandText = "SELECT message_id FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND commit_token=$token ORDER BY sequence"; Parameters(read, peerId, runId, reply); read.Parameters.AddWithValue("$token", token); using var reader = read.ExecuteReader(); while (reader.Read()) ids.Add(reader.GetString(0)); }
        foreach (var id in ids)
        {
            using var inbox = connection.CreateCommand(); inbox.Transaction = transaction; inbox.CommandText = "UPDATE inbox SET state='processed' WHERE peer_id=$peer AND message_id=$message"; inbox.Parameters.AddWithValue("$peer", peerId); inbox.Parameters.AddWithValue("$message", id); inbox.ExecuteNonQuery();
            using var dedupe = connection.CreateCommand(); dedupe.Transaction = transaction; dedupe.CommandText = "UPDATE dedupe SET result='accepted',error='none',seen_ms=$now WHERE peer_id=$peer AND message_id=$message"; dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$message", id); dedupe.Parameters.AddWithValue("$now", now); dedupe.ExecuteNonQuery();
        }
        WriteApplied(connection, transaction, peerId, runId, reply, token, now);
        using (var chunks = connection.CreateCommand()) { chunks.Transaction = transaction; chunks.CommandText = "DELETE FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run AND reply=$reply"; Parameters(chunks, peerId, runId, reply); chunks.ExecuteNonQuery(); }
        using (var transfers = connection.CreateCommand()) { transfers.Transaction = transaction; transfers.CommandText = "DELETE FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply"; Parameters(transfers, peerId, runId, reply); transfers.ExecuteNonQuery(); }
        using (var delete = connection.CreateCommand()) { delete.Transaction = transaction; delete.CommandText = "DELETE FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND commit_token=$token"; Parameters(delete, peerId, runId, reply); delete.Parameters.AddWithValue("$token", token); delete.ExecuteNonQuery(); }
        transaction.Commit(); messageIds = ids; return ids.Count != 0;
    }

    internal PersonalSyncDecisionIntent StageDecisionIntent(string peerId, JsonObject message, string transport, long now)
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        TelefonMessageContract.ValidateMessage(message, now, true); var kind = message["kind"]!.GetValue<string>(); if (kind is not ("personal_sync.deletion_proposals" or "personal_sync.deletion_decision")) throw new InvalidDataException("Kein Löschintent.");
        var body = message["body"]!.AsObject(); var run = LoadRun(peerId, body["run_id"]!.GetValue<string>(), now) ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
        if (run.Expired || run.Policy == "wifi_only" && transport != "wifi") throw new InvalidDataException("Personal-Sync-Transportpolicy verletzt.");
        var messageId = message["message_id"]!.GetValue<string>(); var token = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)); var encrypted = store.Seal("personal_domain", messageId, TelefonCrypto.Canonical(message));
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        using (var old = connection.CreateCommand()) { old.Transaction = transaction; old.CommandText = "SELECT payload,commit_token FROM personal_domain WHERE peer_id=$peer AND message_id=$message"; old.Parameters.AddWithValue("$peer", peerId); old.Parameters.AddWithValue("$message", messageId); using var reader = old.ExecuteReader(); if (reader.Read()) { if (!JsonNode.DeepEquals(JsonNode.Parse(store.Open("personal_domain", messageId, (byte[])reader[0])), message)) throw new InvalidDataException("Widersprüchlicher Löschintent."); token = reader.GetString(1); reader.Close(); transaction.Commit(); return new PersonalSyncDecisionIntent(peerId, messageId, token, kind, body.DeepClone().AsObject()); } }
        using (var insert = connection.CreateCommand()) { insert.Transaction = transaction; insert.CommandText = "INSERT INTO personal_domain VALUES($peer,$message,$kind,$now,$expires,$payload,$token)"; insert.Parameters.AddWithValue("$peer", peerId); insert.Parameters.AddWithValue("$message", messageId); insert.Parameters.AddWithValue("$kind", kind); insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", message["expires_ms"]!.GetValue<long>()); insert.Parameters.AddWithValue("$payload", encrypted); insert.Parameters.AddWithValue("$token", token); insert.ExecuteNonQuery(); }
        transaction.Commit(); return new PersonalSyncDecisionIntent(peerId, messageId, token, kind, body.DeepClone().AsObject());
    }

    internal bool CommitDecisionIntent(string peerId, string messageId, string token, string outcome, long now)
    {
        if (store.RestoreFenced) return false;
        if (outcome == "temporary") return false;
        var error = outcome switch { "applied" => "none", "conflict" => "conflict", "restore_unavailable" => "restore_unavailable", "invalid" => "invalid_schema", "timeout" => "permanent_failure", _ => throw new InvalidDataException("Ungültiges Löschresultat.") };
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        using var read = connection.CreateCommand(); read.Transaction = transaction; read.CommandText = "SELECT kind FROM personal_domain WHERE peer_id=$peer AND message_id=$message AND commit_token=$token"; read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$message", messageId); read.Parameters.AddWithValue("$token", token); var kind = read.ExecuteScalar() as string;
        if (kind is null) return false;
        using (var inbox = connection.CreateCommand()) { inbox.Transaction = transaction; inbox.CommandText = "UPDATE inbox SET state='processed' WHERE peer_id=$peer AND message_id=$message"; inbox.Parameters.AddWithValue("$peer", peerId); inbox.Parameters.AddWithValue("$message", messageId); inbox.ExecuteNonQuery(); }
        using (var dedupe = connection.CreateCommand()) { dedupe.Transaction = transaction; dedupe.CommandText = "UPDATE dedupe SET result=$result,error=$error,seen_ms=$now WHERE peer_id=$peer AND message_id=$message"; dedupe.Parameters.AddWithValue("$message", messageId); dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$result", outcome == "applied" ? "accepted" : "rejected"); dedupe.Parameters.AddWithValue("$error", error); dedupe.Parameters.AddWithValue("$now", now); dedupe.ExecuteNonQuery(); }
        using (var delete = connection.CreateCommand()) { delete.Transaction = transaction; delete.CommandText = "DELETE FROM personal_domain WHERE peer_id=$peer AND message_id=$message AND commit_token=$token"; delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$message", messageId); delete.Parameters.AddWithValue("$token", token); delete.ExecuteNonQuery(); }
        transaction.Commit(); return true;
    }

    internal IReadOnlyList<PersonalSyncDecisionIntent> DecisionIntents(long now)
    {
        var result = new List<PersonalSyncDecisionIntent>(); using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
        command.CommandText = "SELECT peer_id,message_id,kind,payload,commit_token FROM personal_domain WHERE expires_ms>$now ORDER BY received_ms"; command.Parameters.AddWithValue("$now", now); using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            var peerId = reader.GetString(0); var message = JsonNode.Parse(store.Open("personal_domain", reader.GetString(1), (byte[])reader[3]))!.AsObject(); var body = message["body"]!.AsObject();
            if (LoadRun(peerId, body["run_id"]!.GetValue<string>(), now) is { Expired: false }) result.Add(new PersonalSyncDecisionIntent(peerId, reader.GetString(1), reader.GetString(4), reader.GetString(2), body.DeepClone().AsObject()));
        }
        return result;
    }

    internal IReadOnlyList<PersonalSyncStagedBatch> ReadyBatches(long now)
    {
        var identities = new List<(string PeerId, string RunId, bool Reply, string Token)>();
        using (var connection = store.OpenDatabase())
        {
            connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT DISTINCT peer_id,run_id,reply,commit_token FROM personal_batch WHERE expires_ms>$now"; command.Parameters.AddWithValue("$now", now);
            using var reader = command.ExecuteReader(); while (reader.Read()) identities.Add((reader.GetString(0), reader.GetString(1), reader.GetBoolean(2), reader.GetString(3)));
        }
        var result = new List<PersonalSyncStagedBatch>(); using var database = store.OpenDatabase(); database.Open();
        foreach (var identity in identities)
            if (LoadRun(identity.PeerId, identity.RunId, now) is { Expired: false } && CompleteBatch(database, identity.PeerId, identity.RunId, identity.Reply, identity.Token) is { } batch) result.Add(batch);
        return result;
    }

    internal void StageReport(string peerId, JsonObject body)
    {
        PersonalSyncContract.ValidateBody("personal_sync.report", body); var runId = body["run_id"]!.GetValue<string>(); var key = $"personal_report:{peerId}:{runId}";
        var request = ReadMeta(RunKey(peerId, runId), "personal_run")?["body"] as JsonObject ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
        if (body["format"]!.GetValue<int>() != request["format"]!.GetValue<int>() || body["trigger"]!.GetValue<string>() != request["trigger"]!.GetValue<string>())
            throw new InvalidDataException("Widersprüchlicher Personal-Sync-Lauf.");
        var prior = ReadMeta(key, "personal_report"); if (prior is not null && !JsonNode.DeepEquals(prior, body)) throw new InvalidDataException("Widersprüchlicher Personal-Sync-Bericht.");
        WriteMeta(key, "personal_report", body.DeepClone().AsObject(), false);
    }

    internal JsonObject? ReadyReport(string peerId, string runId, long now)
    {
        if (LoadRun(peerId, runId, now) is not { Expired: false }) return null;
        using (var connection = store.OpenDatabase())
        {
            connection.Open(); using var pending = connection.CreateCommand(); pending.CommandText = "SELECT COUNT(*) FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND direction='outgoing' AND complete=0"; pending.Parameters.AddWithValue("$peer", peerId); pending.Parameters.AddWithValue("$run", runId);
            if (Convert.ToInt64(pending.ExecuteScalar()) != 0) return null;
        }
        return ReadMeta($"personal_report:{peerId}:{runId}", "personal_report");
    }

    internal void DeleteReport(string peerId, string runId)
    {
        using var database = store.OpenDatabase(); database.Open(); using var delete = database.CreateCommand();
        delete.CommandText = "DELETE FROM meta WHERE key=$key";
        delete.Parameters.AddWithValue("$key", $"personal_report:{peerId}:{runId}"); delete.ExecuteNonQuery();
    }

    internal void CompleteOutgoingAttachment(string peerId, string runId, bool reply, string recordsHash, string hash, long now)
    {
        var metadata = LoadAttachmentMetadata(peerId, runId, reply, recordsHash, hash, "outgoing", now); metadata["complete"] = true;
        var primary = TransferPrimary(peerId, runId, reply, recordsHash, hash, "outgoing"); var encrypted = store.Seal("personal_attachment_transfer", primary, TelefonCrypto.Canonical(metadata));
        using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "UPDATE personal_attachment_transfer SET complete=1,metadata=$metadata WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction='outgoing'";
        Parameters(command, peerId, runId, reply); command.Parameters.AddWithValue("$records", recordsHash); command.Parameters.AddWithValue("$hash", hash); command.Parameters.AddWithValue("$metadata", encrypted); command.ExecuteNonQuery();
    }

    internal void StageAttachment(string peerId, string runId, bool reply, string recordsHash, JsonObject descriptor, string direction, string policy, long expiresMs, IEnumerable<(int Index, byte[] Data)> chunks)
    {
        if (direction is not ("incoming" or "outgoing") || policy is not ("any" or "wifi_only")) throw new InvalidDataException("Attachment-Metadaten ungültig.");
        PersonalSyncContract.ValidateAttachmentDescriptor(descriptor);
        var hash = descriptor["sha256"]?.GetValue<string>() ?? throw new InvalidDataException(); var size = TelefonProtocolContract.Integer(descriptor["size"]); var mime = descriptor["mime"]?.GetValue<string>() ?? throw new InvalidDataException(); var attachmentId = descriptor["attachment_id"]?.GetValue<string>() ?? throw new InvalidDataException();
        if (size is < 1 or > MaximumAttachmentBytes || expiresMs <= 0) throw new InvalidDataException("Attachment-Metadaten ungültig.");
        var indexed = chunks.Select(item => (item.Index, Data: item.Data.ToArray())).ToArray();
        var totalChunks = checked((int)((size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw));
        if (indexed.Select(item => item.Index).Distinct().Count() != indexed.Length || indexed.Any(item => item.Index < 0 || item.Index >= totalChunks || item.Data.Length != (item.Index + 1 < totalChunks ? PersonalSyncContract.ChunkRaw : size - (long)item.Index * PersonalSyncContract.ChunkRaw))) throw new InvalidDataException("Attachment-Chunk ungültig.");
        var metadata = new JsonObject { ["peer_id"] = peerId, ["run_id"] = runId, ["reply"] = reply, ["attachment_id"] = attachmentId, ["records_hash"] = recordsHash, ["sha256"] = hash, ["direction"] = direction, ["total_chunks"] = (size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw, ["size"] = size, ["mime"] = mime, ["expires_ms"] = expiresMs, ["complete"] = false, ["transport_policy"] = policy };
        var transferPrimary = TransferPrimary(peerId, runId, reply, recordsHash, hash, direction); var encryptedMetadata = store.Seal("personal_attachment_transfer", transferPrimary, TelefonCrypto.Canonical(metadata));
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        var exists = Scalar(connection, transaction, "SELECT COUNT(*) FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction", peerId, runId, reply, recordsHash, hash, direction) != 0;
        if (exists)
        {
            using var old = connection.CreateCommand(); old.Transaction = transaction; old.CommandText = "SELECT size,mime,transport_policy,expires_ms,metadata FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction"; Parameters(old, peerId, runId, reply); old.Parameters.AddWithValue("$records", recordsHash); old.Parameters.AddWithValue("$hash", hash); old.Parameters.AddWithValue("$direction", direction); using var reader = old.ExecuteReader(); reader.Read();
            var prior = JsonNode.Parse(store.Open("personal_attachment_transfer", transferPrimary, (byte[])reader[4]))!.AsObject();
            if (reader.GetInt64(0) != size || reader.GetString(1) != mime || reader.GetString(2) != policy || reader.GetInt64(3) != expiresMs || prior["attachment_id"]?.GetValue<string>() != attachmentId) throw new InvalidDataException("Widersprüchliche Attachment-Metadaten.");
        }
        var encryptedChunks = indexed.Select(item => (item.Index, Payload: store.Seal("personal_attachment_chunk", ChunkPrimary(peerId, runId, reply, recordsHash, hash, direction, item.Index), item.Data))).ToArray();
        EnsureAttachmentCapacity(connection, transaction, peerId, runId, reply, recordsHash, hash, direction, exists, encryptedChunks);
        using (var transfer = connection.CreateCommand()) { transfer.Transaction = transaction; transfer.CommandText = "INSERT OR IGNORE INTO personal_attachment_transfer VALUES($peer,$run,$reply,$records,$hash,$direction,$size,$mime,$policy,$expires,0,$metadata)"; Parameters(transfer, peerId, runId, reply); transfer.Parameters.AddWithValue("$records", recordsHash); transfer.Parameters.AddWithValue("$hash", hash); transfer.Parameters.AddWithValue("$direction", direction); transfer.Parameters.AddWithValue("$size", size); transfer.Parameters.AddWithValue("$mime", mime); transfer.Parameters.AddWithValue("$policy", policy); transfer.Parameters.AddWithValue("$expires", expiresMs); transfer.Parameters.AddWithValue("$metadata", encryptedMetadata); transfer.ExecuteNonQuery(); }
        foreach (var (index, encrypted) in encryptedChunks) { using var chunk = connection.CreateCommand(); chunk.Transaction = transaction; chunk.CommandText = "INSERT OR IGNORE INTO personal_attachment_chunk VALUES($peer,$run,$reply,$records,$hash,$direction,$index,$payload)"; Parameters(chunk, peerId, runId, reply); chunk.Parameters.AddWithValue("$records", recordsHash); chunk.Parameters.AddWithValue("$hash", hash); chunk.Parameters.AddWithValue("$direction", direction); chunk.Parameters.AddWithValue("$index", index); chunk.Parameters.AddWithValue("$payload", encrypted); chunk.ExecuteNonQuery(); }
        transaction.Commit();
    }

    internal void StageAttachmentChunk(string peerId, string runId, bool reply, string recordsHash, string hash,
        string direction, int index, byte[] data, long expiresMs)
    {
        if (direction is not ("incoming" or "outgoing") || index < 0 || data.Length is < 1 or > PersonalSyncContract.ChunkRaw || expiresMs <= 0)
            throw new InvalidDataException("Attachment-Chunk ungültig.");
        var primary = ChunkPrimary(peerId, runId, reply, recordsHash, hash, direction, index);
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        long size;
        using (var transfer = connection.CreateCommand()) { transfer.Transaction = transaction; transfer.CommandText = "SELECT size FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction AND expires_ms>0"; Parameters(transfer, peerId, runId, reply); transfer.Parameters.AddWithValue("$records", recordsHash); transfer.Parameters.AddWithValue("$hash", hash); transfer.Parameters.AddWithValue("$direction", direction); size = transfer.ExecuteScalar() as long? ?? throw new InvalidDataException("Attachment-Manifest fehlt."); }
        var total = checked((int)((size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw));
        if (index >= total || data.Length != (index + 1 < total ? PersonalSyncContract.ChunkRaw : size - (long)index * PersonalSyncContract.ChunkRaw)) throw new InvalidDataException("Attachment-Chunk ungültig.");
        using (var old = connection.CreateCommand())
        {
            old.Transaction = transaction; old.CommandText = "SELECT payload FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction AND chunk_index=$index";
            Parameters(old, peerId, runId, reply); old.Parameters.AddWithValue("$records", recordsHash); old.Parameters.AddWithValue("$hash", hash); old.Parameters.AddWithValue("$direction", direction); old.Parameters.AddWithValue("$index", index);
            if (old.ExecuteScalar() is byte[] prior && !store.Open("personal_attachment_chunk", primary, prior).SequenceEqual(data))
                throw new InvalidDataException("Widersprüchlicher Attachment-Chunk.");
        }
        var encrypted = store.Seal("personal_attachment_chunk", primary, data);
        EnsureAttachmentCapacity(connection, transaction, peerId, runId, reply, recordsHash, hash, direction, true, [(index, encrypted)]);
        using (var chunk = connection.CreateCommand())
        {
            chunk.Transaction = transaction; chunk.CommandText = "INSERT OR IGNORE INTO personal_attachment_chunk VALUES($peer,$run,$reply,$records,$hash,$direction,$index,$payload)";
            Parameters(chunk, peerId, runId, reply); chunk.Parameters.AddWithValue("$records", recordsHash); chunk.Parameters.AddWithValue("$hash", hash); chunk.Parameters.AddWithValue("$direction", direction); chunk.Parameters.AddWithValue("$index", index);
            chunk.Parameters.AddWithValue("$payload", encrypted); chunk.ExecuteNonQuery();
        }
        transaction.Commit();
    }

    internal IReadOnlyList<(int Start, int End)> MissingAttachmentRanges(string peerId, string runId, bool reply, string recordsHash, string hash, string direction, long now)
    {
        var metadata = LoadAttachmentMetadata(peerId, runId, reply, recordsHash, hash, direction, now); var present = new HashSet<int>();
        using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT chunk_index FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction"; Parameters(command, peerId, runId, reply); command.Parameters.AddWithValue("$records", recordsHash); command.Parameters.AddWithValue("$hash", hash); command.Parameters.AddWithValue("$direction", direction); using var reader = command.ExecuteReader(); while (reader.Read()) present.Add(reader.GetInt32(0));
        var ranges = new List<(int Start, int End)>(); var total = checked((int)TelefonProtocolContract.Integer(metadata["total_chunks"]));
        for (var index = 0; index < total; index++) if (!present.Contains(index)) { if (ranges.Count != 0 && ranges[^1].End == index) ranges[^1] = (ranges[^1].Start, index + 1); else ranges.Add((index, index + 1)); }
        return ranges;
    }

    internal byte[] ReadVerifiedAttachment(string peerId, string runId, bool reply, string recordsHash, string hash, string direction, string transport, long now)
    {
        var metadata = LoadAttachmentMetadata(peerId, runId, reply, recordsHash, hash, direction, now);
        if (metadata["transport_policy"]?.GetValue<string>() == "wifi_only" && transport != "wifi" || MissingAttachmentRanges(peerId, runId, reply, recordsHash, hash, direction, now).Count != 0) throw new InvalidDataException("Attachment ist nicht vollständig oder transportgebunden.");
        using var output = new MemoryStream(); using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT chunk_index,payload FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction ORDER BY chunk_index"; Parameters(command, peerId, runId, reply); command.Parameters.AddWithValue("$records", recordsHash); command.Parameters.AddWithValue("$hash", hash); command.Parameters.AddWithValue("$direction", direction); using var reader = command.ExecuteReader();
        while (reader.Read()) { var index = reader.GetInt32(0); var plain = store.Open("personal_attachment_chunk", ChunkPrimary(peerId, runId, reply, recordsHash, hash, direction, index), (byte[])reader[1]); output.Write(plain); CryptographicOperations.ZeroMemory(plain); }
        var result = output.ToArray(); if (result.LongLength != metadata["size"]?.GetValue<long>() || Convert.ToHexString(SHA256.HashData(result)).ToLowerInvariant() != hash || PersonalSyncContract.MimeFromMagic(result) != metadata["mime"]?.GetValue<string>()) { CryptographicOperations.ZeroMemory(result); throw new InvalidDataException("Attachment-Hash oder MIME-Magic ungültig."); }
        return result;
    }

    internal void PurgeProtocol(string peerId)
    {
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        foreach (var table in new[] { "personal_batch", "personal_domain", "personal_attachment_chunk", "personal_attachment_transfer" }) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = $"DELETE FROM {table} WHERE peer_id=$peer"; command.Parameters.AddWithValue("$peer", peerId); command.ExecuteNonQuery(); }
        using (var dedupe = connection.CreateCommand()) { dedupe.Transaction = transaction; dedupe.CommandText = "DELETE FROM dedupe WHERE peer_id=$peer AND message_id IN (SELECT message_id FROM inbox WHERE peer_id=$peer AND kind LIKE 'personal_sync.%')"; dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.ExecuteNonQuery(); }
        foreach (var table in new[] { "outbox", "inbox" }) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = $"DELETE FROM {table} WHERE peer_id=$peer AND kind LIKE 'personal_sync.%'"; command.Parameters.AddWithValue("$peer", peerId); command.ExecuteNonQuery(); }
        using (var meta = connection.CreateCommand()) { meta.Transaction = transaction; meta.CommandText = "DELETE FROM meta WHERE key LIKE $prefix OR key=$active"; meta.Parameters.AddWithValue("$prefix", "personal_%:" + peerId + ":%"); meta.Parameters.AddWithValue("$active", "personal_active_auto:" + peerId); meta.ExecuteNonQuery(); }
        transaction.Commit();
    }

    internal void PurgeModules(string peerId, IReadOnlySet<string> revoked)
    {
        if (revoked.Count == 0) return;
        var runs = new HashSet<string>(StringComparer.Ordinal);
        using (var connection = store.OpenDatabase())
        {
            connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT key,value FROM meta WHERE key LIKE $prefix"; command.Parameters.AddWithValue("$prefix", "personal_run:" + peerId + ":%"); using var reader = command.ExecuteReader();
            while (reader.Read())
            {
                var key = reader.GetString(0); var stored = JsonNode.Parse(store.Open("personal_run", key, (byte[])reader[1]))!.AsObject();
                var body = stored["body"]?.AsObject() ?? throw new InvalidDataException("Personal-Sync-Lauf beschädigt.");
                if ((body["modules"] as JsonArray)?.Any(item => revoked.Contains(item!.GetValue<string>())) == true) runs.Add(body["run_id"]!.GetValue<string>());
            }
        }
        if (runs.Count == 0) return;
        using var db = store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        foreach (var run in runs)
        {
            foreach (var table in new[] { "personal_batch", "personal_attachment_chunk", "personal_attachment_transfer" }) DeleteRun(db, transaction, table, peerId, run);
            using var meta = db.CreateCommand(); meta.Transaction = transaction; meta.CommandText = "DELETE FROM meta WHERE key LIKE $run OR key LIKE $report OR key LIKE $applied"; meta.Parameters.AddWithValue("$run", $"personal_run:{peerId}:{run}%"); meta.Parameters.AddWithValue("$report", $"personal_report:{peerId}:{run}%"); meta.Parameters.AddWithValue("$applied", $"personal_applied:{peerId}:{run}%"); meta.ExecuteNonQuery();
        }
        foreach (var table in new[] { "outbox", "inbox", "personal_domain" }) PurgeWireRuns(db, transaction, table, peerId, runs);
        transaction.Commit();
    }

    internal void PurgeDeletionProtocol(string peerId)
    {
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        using (var dedupe = connection.CreateCommand()) { dedupe.Transaction = transaction; dedupe.CommandText = "DELETE FROM dedupe WHERE peer_id=$peer AND message_id IN (SELECT message_id FROM inbox WHERE peer_id=$peer AND kind IN ('personal_sync.deletion_proposals','personal_sync.deletion_decision'))"; dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.ExecuteNonQuery(); }
        foreach (var table in new[] { "outbox", "inbox" }) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = $"DELETE FROM {table} WHERE peer_id=$peer AND kind IN ('personal_sync.deletion_proposals','personal_sync.deletion_decision')"; command.Parameters.AddWithValue("$peer", peerId); command.ExecuteNonQuery(); }
        using (var domain = connection.CreateCommand()) { domain.Transaction = transaction; domain.CommandText = "DELETE FROM personal_domain WHERE peer_id=$peer"; domain.Parameters.AddWithValue("$peer", peerId); domain.ExecuteNonQuery(); }
        transaction.Commit();
    }

    private PersonalSyncStagedBatch? CompleteBatch(SqliteConnection connection, string peerId, string runId, bool reply, string token)
    {
        var rows = new List<(int Sequence, bool Last, string MessageId, byte[] Payload)>(); using var command = connection.CreateCommand(); command.CommandText = "SELECT sequence,last,message_id,payload FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply ORDER BY sequence"; Parameters(command, peerId, runId, reply); using var reader = command.ExecuteReader(); while (reader.Read()) rows.Add((reader.GetInt32(0), reader.GetBoolean(1), reader.GetString(2), (byte[])reader[3]));
        var finals = rows.Where(row => row.Last).ToArray(); if (finals.Length > 1 || finals.Length == 1 && rows.Any(row => row.Sequence > finals[0].Sequence)) throw new InvalidDataException("Widersprüchliches Batch-Ende.");
        if (finals.Length != 1 || !rows.Select(row => row.Sequence).SequenceEqual(Enumerable.Range(0, finals[0].Sequence + 1))) return null;
        var records = new JsonArray(); string? advertised = null;
        var request = ReadMeta(RunKey(peerId, runId), "personal_run")?["body"] as JsonObject ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
        var format = request["format"]!.GetValue<int>();
        foreach (var row in rows)
        {
            var message = JsonNode.Parse(store.Open("personal_batch", BatchPrimary(peerId, runId, reply, row.Sequence), row.Payload))!.AsObject();
            var body = message["body"]!.AsObject();
            PersonalSyncContract.ValidateBody("personal_sync.batch", body);
            if (body["format"]!.GetValue<int>() != format) throw new InvalidDataException("Widersprüchlicher Personal-Sync-Lauf.");
            if (body["records_hash"] is JsonValue hash)
            {
                var current = hash.GetValue<string>();
                if (advertised is not null && advertised != current) throw new InvalidDataException("Widersprüchlicher records_hash.");
                advertised = current;
            }
            foreach (var record in body["records"]!.AsArray()) records.Add(record!.DeepClone());
        }
        if (advertised is not null && PersonalSyncContract.RecordsHash(records) != advertised) throw new InvalidDataException("Aggregierter records_hash ungültig.");
        return new PersonalSyncStagedBatch(peerId, runId, reply, finals[0].MessageId, token, records, advertised ?? "", format);
    }

    private JsonObject? ReadMeta(string key, string type) { using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT value FROM meta WHERE key=$key"; command.Parameters.AddWithValue("$key", key); return command.ExecuteScalar() is byte[] encrypted ? JsonNode.Parse(store.Open(type, key, encrypted))!.AsObject() : null; }
    private JsonObject LoadAttachmentMetadata(string peerId, string runId, bool reply, string recordsHash, string hash, string direction, long now)
    {
        using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "SELECT size,mime,transport_policy,expires_ms,complete,metadata FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction"; Parameters(command, peerId, runId, reply); command.Parameters.AddWithValue("$records", recordsHash); command.Parameters.AddWithValue("$hash", hash); command.Parameters.AddWithValue("$direction", direction); using var reader = command.ExecuteReader(); if (!reader.Read()) throw new InvalidDataException("Attachment-Manifest fehlt.");
        var metadata = JsonNode.Parse(store.Open("personal_attachment_transfer", TransferPrimary(peerId, runId, reply, recordsHash, hash, direction), (byte[])reader[5]))!.AsObject();
        if (metadata["peer_id"]?.GetValue<string>() != peerId || metadata["run_id"]?.GetValue<string>() != runId || metadata["reply"]?.GetValue<bool>() != reply || metadata["records_hash"]?.GetValue<string>() != recordsHash || metadata["sha256"]?.GetValue<string>() != hash || metadata["direction"]?.GetValue<string>() != direction || metadata["size"]?.GetValue<long>() != reader.GetInt64(0) || metadata["mime"]?.GetValue<string>() != reader.GetString(1) || metadata["transport_policy"]?.GetValue<string>() != reader.GetString(2) || metadata["expires_ms"]?.GetValue<long>() != reader.GetInt64(3) || metadata["complete"]?.GetValue<bool>() != reader.GetBoolean(4) || reader.GetInt64(3) <= now) throw new InvalidDataException("Unauthentisierte oder abgelaufene Attachment-Metadaten.");
        return metadata;
    }
    private void WriteMeta(string key, string type, JsonObject value, bool replace) { using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = $"INSERT OR {(replace ? "REPLACE" : "IGNORE")} INTO meta(key,value) VALUES($key,$value)"; command.Parameters.AddWithValue("$key", key); command.Parameters.AddWithValue("$value", store.Seal(type, key, TelefonCrypto.Canonical(value))); command.ExecuteNonQuery(); }
    private void WriteApplied(SqliteConnection connection, SqliteTransaction transaction, string peerId, string runId, bool reply, string token, long now) { var key = $"personal_applied:{peerId}:{runId}:{(reply ? 1 : 0)}"; var value = store.Seal("personal_applied", key, TelefonCrypto.Canonical(new JsonObject { ["commit_token"] = token, ["applied_ms"] = now })); using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = "INSERT OR REPLACE INTO meta VALUES($key,$value)"; command.Parameters.AddWithValue("$key", key); command.Parameters.AddWithValue("$value", value); command.ExecuteNonQuery(); }
    private void EnsureAttachmentCapacity(SqliteConnection connection, SqliteTransaction transaction, string peerId, string runId, bool reply, string recordsHash, string hash, string direction, bool transferExists, IReadOnlyList<(int Index, byte[] Payload)> chunks)
    {
        var additions = chunks.Where(item => Scalar(connection, transaction, "SELECT COUNT(*) FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction AND chunk_index=$index", peerId, runId, reply, recordsHash, hash, direction, item.Index) == 0).ToArray();
        var bytes = additions.Sum(item => (long)item.Payload.Length);
        if (!transferExists && (Scalar(connection, transaction, "SELECT COUNT(DISTINCT run_id||':'||reply||':'||direction) FROM personal_attachment_transfer WHERE peer_id=$peer", peerId) >= MaximumActiveTransfersPerPeer || Scalar(connection, transaction, "SELECT COUNT(DISTINCT sha256) FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run", peerId, runId) >= MaximumAttachmentsPerRun) ||
            Scalar(connection, transaction, "SELECT COUNT(*) FROM personal_attachment_chunk") + additions.Length > MaximumChunkRows ||
            Scalar(connection, transaction, "SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk") + bytes > MaximumGlobalChunkBytes ||
            Scalar(connection, transaction, "SELECT COALESCE(SUM(length(payload)),0) FROM personal_attachment_chunk WHERE peer_id=$peer AND run_id=$run", peerId, runId) + bytes > MaximumRunChunkBytes)
            throw new InvalidDataException("Attachment-Staging ist voll.");
    }
    private static long Scalar(SqliteConnection connection, SqliteTransaction transaction, string sql, string? peerId = null, string? runId = null, bool? reply = null, string? recordsHash = null, string? hash = null, string? direction = null, int? index = null) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = sql; if (peerId is not null) command.Parameters.AddWithValue("$peer", peerId); if (runId is not null) command.Parameters.AddWithValue("$run", runId); if (reply is not null) command.Parameters.AddWithValue("$reply", reply.Value); if (recordsHash is not null) command.Parameters.AddWithValue("$records", recordsHash); if (hash is not null) command.Parameters.AddWithValue("$hash", hash); if (direction is not null) command.Parameters.AddWithValue("$direction", direction); if (index is not null) command.Parameters.AddWithValue("$index", index.Value); return Convert.ToInt64(command.ExecuteScalar(), System.Globalization.CultureInfo.InvariantCulture); }
    private static void DeleteRun(SqliteConnection connection, SqliteTransaction transaction, string table, string peerId, string runId) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = $"DELETE FROM {table} WHERE peer_id=$peer AND run_id=$run"; command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$run", runId); command.ExecuteNonQuery(); }
    private void PurgeWireRuns(SqliteConnection connection, SqliteTransaction transaction, string table, string peerId, IReadOnlySet<string> runs)
    {
        using var read = connection.CreateCommand(); read.Transaction = transaction; read.CommandText = $"SELECT message_id,payload FROM {table} WHERE peer_id=$peer"; read.Parameters.AddWithValue("$peer", peerId); var remove = new List<string>(); using (var reader = read.ExecuteReader()) while (reader.Read()) { var id = reader.GetString(0); try { var primary = table == "inbox" ? peerId + id : id; var message = JsonNode.Parse(store.Open(table == "personal_domain" ? "personal_domain" : table, primary, (byte[])reader[1])) as JsonObject; if (message?["body"]?["run_id"]?.GetValue<string>() is string run && runs.Contains(run)) remove.Add(id); } catch { remove.Add(id); } }
        foreach (var id in remove) { using var delete = connection.CreateCommand(); delete.Transaction = transaction; delete.CommandText = $"DELETE FROM {table} WHERE peer_id=$peer AND message_id=$id"; delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$id", id); delete.ExecuteNonQuery(); if (table == "inbox") { using var dedupe = connection.CreateCommand(); dedupe.Transaction = transaction; dedupe.CommandText = "DELETE FROM dedupe WHERE peer_id=$peer AND message_id=$id"; dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$id", id); dedupe.ExecuteNonQuery(); } }
    }
    private static void Parameters(SqliteCommand command, string peerId, string runId, bool reply) { command.Parameters.AddWithValue("$peer", peerId); command.Parameters.AddWithValue("$run", runId); command.Parameters.AddWithValue("$reply", reply); }
    private static string RunKey(string peerId, string runId) => $"personal_run:{peerId}:{runId}";
    private static string BatchPrimary(string peerId, string runId, bool reply, int sequence) => $"{peerId}:{runId}:{(reply ? 1 : 0)}:{sequence}";
    private static string TransferPrimary(string peerId, string runId, bool reply, string recordsHash, string hash, string direction) => $"{peerId}:{runId}:{(reply ? 1 : 0)}:{direction}:{recordsHash}:{hash}";
    private static string ChunkPrimary(string peerId, string runId, bool reply, string recordsHash, string hash, string direction, int index) => $"{TransferPrimary(peerId, runId, reply, recordsHash, hash, direction)}:{index}";
}

internal sealed record PersonalSyncRun(string RunId, string Policy, long ExpiresMs, bool Expired, JsonObject Request);
internal sealed record PersonalSyncStagedBatch(string PeerId, string RunId, bool Reply, string PendingMessageId, string CommitToken, JsonArray Records, string RecordsHash, int Format);
internal sealed record PersonalSyncDecisionIntent(string PeerId, string PendingMessageId, string CommitToken, string Kind, JsonObject Body);
