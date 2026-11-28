using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PersonalSyncStore(TelefonStore store)
{
    private TelefonStore Store => store;
    internal const long RunLifetimeMs = 86_400_000;
    internal const long MaximumAttachmentBytes = 8L * 1024 * 1024;
    private const long MaximumGlobalChunkBytes = 100L * 1024 * 1024;
    private const long MaximumRunChunkBytes = 50L * 1024 * 1024;
    private const int MaximumActiveTransfersPerPeer = 4;
    private const int MaximumAttachmentsPerRun = 64;
    private const int MaximumChunkRows = 4096;

    internal void RememberRun(string peerId, JsonObject request, long now, long? claimedExpiresMs = null,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context = null)
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        PersonalSyncContract.ValidateBody("personal_sync.request", request); var runId = request["run_id"]!.GetValue<string>();
        var expires = Math.Min(checked(now + RunLifetimeMs), claimedExpiresMs ?? long.MaxValue);
        if (expires <= now) throw new InvalidDataException("Personal-Sync-Lauf ist abgelaufen.");
        var key = RunKey(peerId, runId); var existing = ReadMeta(key, "personal_run", context);
        if (existing is not null)
        {
            if (!JsonNode.DeepEquals(existing["body"], request) || claimedExpiresMs > existing["expires_ms"]?.GetValue<long>()) throw new InvalidDataException("Widersprüchlicher Personal-Sync-Lauf.");
            return;
        }
        WriteMeta(key, "personal_run", new JsonObject { ["body"] = request.DeepClone(), ["created_ms"] = now, ["expires_ms"] = expires }, false, context);
    }

    internal PersonalSyncRun? LoadRun(string peerId, string runId, long now,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context = null)
    {
        var value = ReadMeta(RunKey(peerId, runId), "personal_run", context); if (value is null) return null;
        var body = value["body"] as JsonObject ?? throw new InvalidDataException("Personal-Sync-Lauf beschädigt.");
        var trigger = body["trigger"]!.GetValue<string>();
        if (trigger == PersonalSyncContract.AutoConnectionTrigger)
        {
            PersonalSyncContract.ValidateScopedConnectionRequest(body);
            if (value["connection_authority"] is not JsonValue authority || !authority.TryGetValue<string>(out var bound) ||
                !ValidConnectionAuthority(bound)) throw new InvalidDataException("A scoped connection run has no reader authority.");
        }
        else PersonalSyncContract.ValidateBody("personal_sync.request", body);
        var expires = TelefonProtocolContract.Integer(value["expires_ms"]);
        var policy = trigger switch
        {
            "auto_wifi" => "wifi_only",
            PersonalSyncContract.AutoConnectionTrigger => "connection_only",
            _ => "any"
        };
        return new PersonalSyncRun(runId, policy, expires, expires <= now, body.DeepClone().AsObject());
    }

    internal void RememberScopedRun(string peerId, byte[] expectedPublic, JsonObject request, JsonObject reference, long now, long expires)
        => RememberScopedRun(peerId, expectedPublic, request, reference, now, expires, null, null, null);

    internal TelefonAck RememberScopedConnectionRequest(string peerId, byte[] expectedPublic, JsonObject envelope, long now,
        string authority, Func<string> currentAuthority)
    {
        TelefonMessageContract.ValidateMessage(envelope, now, true);
        if (envelope["kind"]?.GetValue<string>() != PhoneContentScope.DataKind ||
            envelope["body"] is not JsonObject wrapped || wrapped["kind"]?.GetValue<string>() != "personal_sync.request")
            throw new InvalidDataException("Scoped automatic connection request envelope required.");
        if (!ValidConnectionAuthority(authority)) throw new InvalidOperationException("Connection reader authority unavailable.");
        var request = wrapped["body"]!.AsObject();
        PersonalSyncContract.ValidateScopedConnectionRequest(request);
        var duplicate = RememberScopedRun(peerId, expectedPublic, request, wrapped["scope"]!.AsObject(), now,
            TelefonProtocolContract.Integer(envelope["expires_ms"]), envelope, authority, currentAuthority);
        return new TelefonAck(envelope["message_id"]!.GetValue<string>(), duplicate ? "duplicate" : "accepted", "none");
    }

    private static bool ValidConnectionAuthority(string value) =>
        value.Length == 64 && value.All(letter => "0123456789abcdef".Contains(letter));

    private bool RememberScopedRun(string peerId, byte[] expectedPublic, JsonObject request, JsonObject reference, long now,
        long expires, JsonObject? envelope, string? authority, Func<string>? currentAuthority)
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        var connection = authority is not null;
        if (!connection) PersonalSyncContract.ValidateBody("personal_sync.request", request);
        PhoneContentScope.ValidateReference(reference);
        if (request["format"]!.GetValue<int>() is not (3 or 14) || expires <= now) throw new InvalidDataException("Invalid scoped run.");
        using var db = store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var settings = store.SharedSettings(peerId, expectedPublic) ?? throw new InvalidOperationException("Shared preferences unavailable.");
        if (SharedSyncSettings.Effective(settings)["content_mode"]?.GetValue<string>() != "phone_scope")
            throw new InvalidOperationException("Current content mode is not scoped.");
        var identity = store.LoadOrCreateIdentity(); var actor = identity.Id;
        CryptographicOperations.ZeroMemory(identity.PrivateKey);
        var policy = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(settings["settings"]!["content_mode"]!.AsObject()))).ToLowerInvariant();
        var binding = new JsonObject { ["peer_key"] = Convert.ToHexString(expectedPublic), ["local_actor"] = actor,
            ["scope"] = reference.DeepClone(), ["content_policy"] = policy };
        var runId = request["run_id"]!.GetValue<string>(); var runKey = RunKey(peerId, runId); var scopeKey = $"personal_scope:{peerId}:{runId}";
        var receiptId = envelope?["message_id"]?.GetValue<string>();
        void RequireCurrentConnection()
        {
            if (!connection) return;
            if (currentAuthority!() != authority ||
                (SharedSyncSettings.Effective(settings)["auto_mode"]?.GetValue<string>() != "connection"))
                throw new InvalidOperationException("The negotiated connection request reader changed.");
        }
        RequireCurrentConnection();
        JsonObject? Read(string key, string type)
        {
            using var query = db.CreateCommand(); query.Transaction = transaction; query.CommandText = "SELECT value FROM meta WHERE key=$key";
            query.Parameters.AddWithValue("$key", key);
            return query.ExecuteScalar() is byte[] raw ? JsonNode.Parse(store.Open(type, key, raw))!.AsObject() : null;
        }
        var oldRun = Read(runKey, "personal_run"); var oldScope = Read(scopeKey, "personal_scope");
        if ((oldRun is null) != (oldScope is null)) throw new InvalidDataException("Cannot reinterpret a legacy run as scoped.");
        if (oldRun is not null)
        {
            if (connection)
            {
                if (oldRun["connection_authority"]?.GetValue<string>() != authority)
                    throw new InvalidOperationException("The connection run belongs to another reader.");
                if (oldRun["connection_request_id"]?.GetValue<string>() != receiptId ||
                    !JsonNode.DeepEquals(ReadConnectionReceipt(db, transaction, peerId, receiptId!, now), envelope))
                    throw new InvalidDataException("Conflicting connection request receipt.");
            }
            if (!JsonNode.DeepEquals(oldRun["body"], request) || !JsonNode.DeepEquals(oldScope, binding) ||
                TelefonProtocolContract.Integer(oldRun["expires_ms"]) <= now || expires > TelefonProtocolContract.Integer(oldRun["expires_ms"]))
                throw new InvalidDataException("Conflicting or expired scoped run.");
            RequireCurrentConnection();
            transaction.Commit(); return true;
        }
        var run = new JsonObject { ["body"] = request.DeepClone(), ["created_ms"] = now, ["expires_ms"] = Math.Min(checked(now + RunLifetimeMs), expires) };
        if (connection)
        {
            run["connection_authority"] = authority;
            run["connection_request_id"] = receiptId;
        }
        foreach (var item in new[] { (Key: runKey, Type: "personal_run", Value: run), (Key: scopeKey, Type: "personal_scope", Value: binding) })
        {
            using var insert = db.CreateCommand(); insert.Transaction = transaction; insert.CommandText = "INSERT INTO meta(key,value) VALUES($key,$value)";
            insert.Parameters.AddWithValue("$key", item.Key); insert.Parameters.AddWithValue("$value", store.Seal(item.Type, item.Key, TelefonCrypto.Canonical(item.Value)));
            insert.ExecuteNonQuery();
        }
        if (connection)
        {
            WriteConnectionReceipt(db, transaction, peerId, envelope!, now);
            RequireCurrentConnection();
        }
        if (store.RestoreFenced || !JsonNode.DeepEquals(settings, store.SharedSettings(peerId, expectedPublic)))
            throw new InvalidOperationException("Shared scope binding changed.");
        transaction.Commit();
        return false;
    }

    private void WriteConnectionReceipt(SqliteConnection db, SqliteTransaction transaction, string peerId, JsonObject envelope, long now)
    {
        var id = envelope["message_id"]!.GetValue<string>();
        using var receipt = db.CreateCommand(); receipt.Transaction = transaction;
        receipt.CommandText = "INSERT INTO inbox VALUES($id,$peer,$kind,$now,$expires,$payload,'processed'); " +
            "INSERT INTO dedupe VALUES($id,$peer,'accepted','none',$now)";
        receipt.Parameters.AddWithValue("$id", id); receipt.Parameters.AddWithValue("$peer", peerId);
        receipt.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind);
        receipt.Parameters.AddWithValue("$now", now);
        receipt.Parameters.AddWithValue("$expires", TelefonProtocolContract.Integer(envelope["expires_ms"]));
        receipt.Parameters.AddWithValue("$payload", store.Seal("inbox", peerId + id, TelefonCrypto.Canonical(envelope)));
        receipt.ExecuteNonQuery();
    }

    private JsonObject? ReadConnectionReceipt(SqliteConnection db, SqliteTransaction transaction, string peerId, string id, long now)
    {
        using var receipt = db.CreateCommand(); receipt.Transaction = transaction;
        receipt.CommandText = """
            SELECT i.payload FROM inbox i JOIN dedupe d ON i.peer_id=d.peer_id AND i.message_id=d.message_id
            WHERE i.peer_id=$peer AND i.message_id=$id AND i.kind=$kind AND i.state='processed' AND i.expires_ms>$now
                AND d.result='accepted' AND d.error='none'
            """;
        receipt.Parameters.AddWithValue("$peer", peerId); receipt.Parameters.AddWithValue("$id", id);
        receipt.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind); receipt.Parameters.AddWithValue("$now", now);
        return receipt.ExecuteScalar() is byte[] payload ? JsonNode.Parse(store.Open("inbox", peerId + id, payload))!.AsObject() : null;
    }

    internal JsonObject? ScopedRunReference(string peerId, byte[] expectedPublic, string runId, long now)
    {
        var binding = ReadMeta($"personal_scope:{peerId}:{runId}", "personal_scope");
        if (binding is null) return null;
        var settings = store.SharedSettings(peerId, expectedPublic) ?? throw new InvalidOperationException("Shared preferences unavailable.");
        TelefonProtocolContract.ExactObject(binding, "peer_key", "local_actor", "scope", "content_policy");
        var scope = binding["scope"] as JsonObject ?? throw new InvalidDataException("Scope reference missing.");
        PhoneContentScope.ValidateReference(scope);
        var identity = store.LoadOrCreateIdentity(); var actor = identity.Id;
        CryptographicOperations.ZeroMemory(identity.PrivateKey);
        var policy = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(settings["settings"]!["content_mode"]!.AsObject()))).ToLowerInvariant();
        var run = LoadRun(peerId, runId, now);
        if (store.RestoreFenced || binding["peer_key"]?.GetValue<string>() != Convert.ToHexString(expectedPublic) ||
            binding["local_actor"]?.GetValue<string>() != actor || binding["content_policy"]?.GetValue<string>() != policy ||
            SharedSyncSettings.Effective(settings)["content_mode"]?.GetValue<string>() != "phone_scope" || run is null || run.Expired)
            throw new InvalidOperationException("Scoped run is no longer current.");
        return scope.DeepClone().AsObject();
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
            using var meta = database.CreateCommand(); meta.Transaction = transaction; meta.CommandText = "DELETE FROM meta WHERE key=$key OR key=$scope OR key LIKE $report OR key LIKE $applied"; meta.Parameters.AddWithValue("$key", item.Key); meta.Parameters.AddWithValue("$scope", $"personal_scope:{item.PeerId}:{item.RunId}"); meta.Parameters.AddWithValue("$report", $"personal_report:{item.PeerId}:{item.RunId}%"); meta.Parameters.AddWithValue("$applied", $"personal_applied:{item.PeerId}:{item.RunId}%"); meta.ExecuteNonQuery();
        }
        transaction.Commit();
    }

    internal PersonalSyncStagedBatch? StageBatch(string peerId, JsonObject message, string transport, long now)
        => StageBatch(peerId, message, transport, now, null, out _);

    internal (TelefonAck Ack, PersonalSyncStagedBatch? Complete) StageScopedConnectionBatch(string peerId, JsonObject envelope, JsonObject manifest, string transport,
        long now, string authority, Func<string> currentAuthority)
    {
        TelefonMessageContract.ValidateMessage(envelope, now, true);
        if (envelope["kind"]?.GetValue<string>() != PhoneContentScope.DataKind)
            throw new InvalidDataException("Scoped automatic batch envelope required.");
        var (kind, body) = PhoneContentScope.Unwrap(envelope["body"]!.AsObject(), manifest);
        if (kind != "personal_sync.batch" || !ValidConnectionAuthority(authority))
            throw new InvalidOperationException("The connection batch is not authorized.");
        var modules = LoadRun(peerId, body["run_id"]!.GetValue<string>(), now)?.Request["modules"]?.AsArray();
        var members = manifest["members"]!.AsObject();
        var notes = members["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        var tasks = members["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        foreach (var record in body["records"]!.AsArray().OfType<JsonObject>())
        {
            var itemKind = record["kind"]!.GetValue<string>(); var id = record["id"]!.GetValue<string>();
            var module = itemKind == "task" ? "tasks" : "notes";
            if (modules?.Any(value => value?.GetValue<string>() == module) != true ||
                (itemKind == "task" && !tasks.Contains(id)) || (itemKind == "note" && !notes.Contains(id)))
                throw new InvalidOperationException("A connection batch record is outside the requested scope.");
        }
        var inner = envelope.DeepClone().AsObject(); inner["kind"] = kind; inner["body"] = body;
        var complete = StageBatch(peerId, inner, transport, now, (envelope, manifest, authority, currentAuthority), out var duplicate);
        return (new TelefonAck(envelope["message_id"]!.GetValue<string>(), duplicate ? "duplicate" : "accepted", "none"), complete);
    }

    private PersonalSyncStagedBatch? StageBatch(string peerId, JsonObject message, string transport, long now,
        (JsonObject Envelope, JsonObject Manifest, string Authority, Func<string> CurrentAuthority)? scope, out bool duplicate)
    {
        duplicate = false;
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        TelefonMessageContract.ValidateMessage(message, now, true); if (message["kind"]?.GetValue<string>() != "personal_sync.batch") throw new InvalidDataException("Kein Personal-Sync-Batch.");
        var body = message["body"]!.AsObject(); var runId = body["run_id"]!.GetValue<string>(); var run = LoadRun(peerId, runId, now) ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
        if (body["format"]!.GetValue<int>() != run.Request["format"]!.GetValue<int>()) throw new InvalidDataException("Widersprüchlicher Personal-Sync-Lauf.");
        PersonalSyncContract.ValidateSelectedRecords(run.Request, body["records"]!.AsArray().OfType<JsonObject>());
        if (run.Expired || run.Policy == "wifi_only" && transport != "wifi" ||
            (run.Policy == "connection_only") != scope.HasValue) throw new InvalidDataException("Personal-Sync-Transportpolicy verletzt.");
        var reply = body["reply"]!.GetValue<bool>(); var sequence = checked((int)TelefonProtocolContract.Integer(body["sequence"])); if (sequence >= 4096) throw new InvalidDataException("Zu viele Personal-Sync-Batches.");
        var primary = BatchPrimary(peerId, runId, reply, sequence); var payload = store.Seal("personal_batch", primary, TelefonCrypto.Canonical(message));
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        void RequireCurrentConnection()
        {
            if (scope is not { } bound) return;
            var stored = ReadMeta(RunKey(peerId, runId), "personal_run", (connection, transaction));
            var binding = ReadMeta($"personal_scope:{peerId}:{runId}", "personal_scope", (connection, transaction));
            if (store.RestoreFenced || bound.CurrentAuthority() != bound.Authority || transport is not ("wifi" or "bluetooth") ||
                stored?["connection_authority"]?.GetValue<string>() != bound.Authority ||
                !JsonNode.DeepEquals(binding?["scope"], bound.Envelope["body"]?["scope"]) ||
                TelefonProtocolContract.Integer(message["expires_ms"]) <= now || TelefonProtocolContract.Integer(message["expires_ms"]) > run.ExpiresMs)
                throw new InvalidOperationException("The connection batch no longer owns the original reader.");
            if (reply != (stored?["connection_start_id"] is not null) ||
                reply && !ScopedInitialAcknowledged(connection, transaction, peerId, runId, now, bound.Authority, binding!["scope"]!.AsObject()))
                throw new InvalidOperationException("The connection batch direction does not own an acknowledged initial group.");
        }
        RequireCurrentConnection();
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
                token = reader.GetString(4); reader.Close();
                if (scope is { } bound)
                {
                    if (!JsonNode.DeepEquals(ReadConnectionReceipt(connection, transaction, peerId,
                        message["message_id"]!.GetValue<string>(), now), bound.Envelope))
                        throw new InvalidDataException("Conflicting connection batch receipt.");
                    RequireCurrentConnection();
                    duplicate = true;
                    var scoped = CompleteBatch(connection, peerId, runId, reply, token, transaction, scopedNow: now);
                    transaction.Commit();
                    return scoped;
                }
                transaction.Commit();
                return CompleteBatch(connection, peerId, runId, reply, token);
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
        var complete = CompleteBatch(connection, peerId, runId, reply, token, transaction, scopedNow: scope.HasValue ? now : null);
        if (complete?.Records.Count > 100_000) throw new InvalidDataException("Personal-Sync-Lauf ist zu groß.");
        if (scope is { } accepted)
        {
            if (complete is not null)
            {
                var records = complete.Records.OfType<JsonObject>().ToArray();
                if (PhoneContentScope.FilterRecords(records, accepted.Manifest).Count != records.Length)
                    throw new InvalidOperationException("The completed connection batch contains a notebook outside the requested scope.");
            }
            WriteConnectionReceipt(connection, transaction, peerId, accepted.Envelope, now);
            RequireCurrentConnection();
        }
        transaction.Commit(); return complete;
    }

    internal bool RequireScopedConnectionBatchForSave(string peerId, string messageId, string token, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<string, bool> acknowledgementWritten, JsonObject? candidate = null)
    {
        if (store.RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        using var db = store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
        var input = ReadScopedConnectionInput(db, transaction, peerId, messageId, token, now, currentAuthority, acknowledgementWritten);
        if (input.Batch.HasScopedOriginals)
        {
            if (candidate is null) throw new InvalidOperationException("The scoped original attachments need the proposed book.");
            ReadCompletedScopedOriginals(db, transaction, input.Batch, now, includeData: false);
            VerifyScopedOriginalBook(input.Batch.Records, candidate);
            if (store.RestoreFenced || currentAuthority(input.Run.Request, input.Reference) != input.Authority)
                throw new InvalidOperationException("The scoped originals lost their reader before the native write.");
        }
        return input.Batch.HasScopedOriginals || input.Batch.Reply;
    }

    private (PersonalSyncRun Run, JsonObject Reference, string Authority, PersonalSyncStagedBatch Batch, long Started) ReadScopedConnectionInput(SqliteConnection db,
        SqliteTransaction transaction, string peerId, string messageId, string token, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<string, bool> acknowledgementWritten)
    {
        var batch = ReadConnectionReceipt(db, transaction, peerId, messageId, now);
        if (batch?["body"] is not JsonObject wrapper || wrapper["kind"]?.GetValue<string>() != "personal_sync.batch" ||
            wrapper["body"] is not JsonObject body || wrapper["scope"] is not JsonObject reference)
            throw new InvalidOperationException("The scoped connection batch receipt is missing.");
        var reply = body["reply"]!.GetValue<bool>();
        var runId = body["run_id"]!.GetValue<string>();
        var run = LoadRun(peerId, runId, now, (db, transaction));
        var binding = ReadMeta(RunKey(peerId, runId), "personal_run", (db, transaction));
        var scope = ReadMeta($"personal_scope:{peerId}:{runId}", "personal_scope", (db, transaction));
        if (run is not { Expired: false, Policy: "connection_only" } || binding is null || !JsonNode.DeepEquals(scope?["scope"], reference))
            throw new InvalidOperationException("The original connection request is no longer current.");
        var authority = currentAuthority(run.Request, reference);
        if (binding["connection_authority"]?.GetValue<string>() != authority)
            throw new InvalidOperationException("The connection batch belongs to another reader.");
        if (reply)
        {
            if (binding["connection_start_id"] is null || !ScopedInitialAcknowledged(db, transaction, peerId, runId, now, authority, reference))
                throw new InvalidOperationException("The scoped reply has no completed initial group.");
        }
        else if (binding["connection_request_id"] is not JsonValue requestId ||
            ReadConnectionReceipt(db, transaction, peerId, requestId.GetValue<string>(), now)?["body"] is not JsonObject request ||
            request["kind"]?.GetValue<string>() != "personal_sync.request" ||
            !JsonNode.DeepEquals(request["scope"], reference) || !JsonNode.DeepEquals(request["body"], run.Request))
            throw new InvalidOperationException("The received connection request has no exact receipt.");
        var complete = CompleteBatch(db, peerId, runId, reply, token, transaction, (reference, now, acknowledgementWritten), now);
        if (complete?.PendingMessageId != messageId)
            throw new InvalidOperationException("The scoped batch is not ready.");
        if (store.RestoreFenced || currentAuthority(run.Request, reference) != authority)
            throw new InvalidOperationException("The scoped batch changed before the native write.");
        return (run, reference, authority, complete, TelefonProtocolContract.Integer(binding["created_ms"]));
    }

    internal void QueueScopedConnectionReply(string peerId, string messageId, string token, NativeBookSaveState saved,
        IReadOnlyList<JsonObject> batches, int conflicts, int oversized, string transport, long now, Func<JsonObject, JsonObject, string> currentAuthority,
        Func<JsonObject, JsonObject> currentScope, Func<string, bool> acknowledgementWritten, Func<bool> currentBook, string? savedText = null)
    {
        if (store.RestoreFenced || !currentBook()) throw new InvalidOperationException("The scoped connection reply has no current saved book.");
        if (batches.Count is < 1 or > 4096) throw new InvalidDataException("Invalid scoped connection reply batch count.");
        using var db = store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var (run, reference, authority, input, started) = ReadScopedConnectionInput(db, transaction, peerId, messageId, token, now,
            currentAuthority, acknowledgementWritten);
        if (input.Reply) throw new InvalidOperationException("An initiated run cannot send a second reply.");
        var key = ConnectionReplyKey(peerId, run.RunId);
        if (ReadMeta(key, "personal_connection_reply", (db, transaction)) is not null)
            throw new InvalidOperationException("The scoped connection reply is already queued.");

        var records = new JsonArray();
        var batchIds = new HashSet<string>(StringComparer.Ordinal);
        var declared = batches[0]["records_hash"]?.GetValue<string>();
        for (var index = 0; index < batches.Count; index++)
        {
            var batch = batches[index];
            PersonalSyncContract.ValidateBody("personal_sync.batch", batch);
            if (batch["run_id"]!.GetValue<string>() != run.RunId || batch["format"]!.GetValue<int>() != run.Request["format"]!.GetValue<int>() ||
                !batch["reply"]!.GetValue<bool>() || TelefonProtocolContract.Integer(batch["sequence"]) != index ||
                batch["last"]!.GetValue<bool>() != (index == batches.Count - 1) || batch["records_hash"]!.GetValue<string>() != declared ||
                !batchIds.Add(batch["batch_id"]!.GetValue<string>()))
                throw new InvalidDataException("Conflicting scoped connection reply batch.");
            foreach (var record in batch["records"]!.AsArray()) records.Add(record!.DeepClone());
            if (records.Count > 100_000) throw new InvalidDataException("The scoped connection reply is too large.");
        }
        var selected = records.OfType<JsonObject>().ToArray();
        var manifest = currentScope(reference);
        if (declared != PersonalSyncContract.RecordsHash(records) || PhoneContentScope.FilterRecords(selected, manifest).Count != selected.Length ||
            selected.Any(record => !run.Request["modules"]!.AsArray().Any(module => module!.GetValue<string>() ==
                    (record["kind"]!.GetValue<string>() == "task" ? "tasks" : "notes"))))
            throw new InvalidDataException("Scoped connection reply records do not match their manifest.");
        var hasReplyOriginals = ValidateScopedOriginalManifest(records);
        var expires = input.HasScopedOriginals || hasReplyOriginals ? input.ExpiresMs : run.ExpiresMs;
        var outgoingHashes = new HashSet<string>(StringComparer.Ordinal);
        long outgoingBytes = 0;
        if (hasReplyOriginals)
        {
            if (savedText is null || BaumSyncSnapshot.Hash(savedText) != saved.Sha256)
                throw new InvalidOperationException("The reply originals need the exact native saved document.");
            VerifyScopedOriginalBook(records, JsonNode.Parse(savedText)!.AsObject(), (descriptor, bytes) =>
            {
                if (!outgoingHashes.Add(descriptor["sha256"]!.GetValue<string>())) return;
                StageAttachmentCore(peerId, run.RunId, true, declared!, descriptor, "outgoing", ConnectionOriginalPolicy, expires,
                    bytes.Chunk(PersonalSyncContract.ChunkRaw).Select((chunk, index) => (index, chunk)), (db, transaction));
                outgoingBytes += bytes.LongLength;
            });
        }
        var incomingOriginals = ScopedOriginalDescriptors(input.Records)
            .DistinctBy(descriptor => descriptor["sha256"]!.GetValue<string>(), StringComparer.Ordinal).ToArray();

        using var insert = db.CreateCommand();
        insert.Transaction = transaction;
        insert.CommandText = """
            INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy)
            VALUES($id,$peer,$kind,$now,$expires,$payload,0,$now,'','connection_only')
            """;
        var id = insert.Parameters.Add("$id", SqliteType.Text);
        var payload = insert.Parameters.Add("$payload", SqliteType.Blob);
        insert.Parameters.AddWithValue("$peer", peerId); insert.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind);
        insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", expires);
        using var usage = db.CreateCommand();
        usage.Transaction = transaction;
        usage.CommandText = "SELECT COALESCE(SUM(length(payload)),0) FROM outbox";
        var size = (long)usage.ExecuteScalar()!;
        var ids = new JsonArray();
        var report = new JsonObject { ["format"] = run.Request["format"]!.DeepClone(), ["run_id"] = run.RunId,
            ["state"] = oversized == 0 ? "complete" : "partial", ["trigger"] = PersonalSyncContract.AutoConnectionTrigger,
            ["transport"] = transport, ["sent"] = CountRecords(records), ["received"] = CountRecords(input.Records),
            ["conflicts"] = conflicts, ["oversized_skipped"] = oversized, ["attachments_omitted"] = 0,
            ["started_ms"] = started, ["finished_ms"] = now, ["error"] = "none",
            ["attachments"] = new JsonObject { ["declared"] = outgoingHashes.Count, ["requested"] = incomingOriginals.Length,
                ["sent"] = outgoingHashes.Count, ["received"] = incomingOriginals.Length,
                ["reused"] = 0, ["preserved"] = 0, ["failed"] = 0, ["bytes"] = outgoingBytes + incomingOriginals.Sum(item =>
                    TelefonProtocolContract.Integer(item["size"])) },
            ["deletions"] = new JsonObject { ["pending"] = 0, ["deleted"] = 0, ["restored"] = 0, ["conflicts"] = 0,
                ["blocked"] = 0, ["trash"] = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0, ["attachments"] = 0 } } };
        foreach (var (kind, body) in batches.Select(batch => (Kind: "personal_sync.batch", Body: batch)).Append(("personal_sync.report", report)))
        {
            var messageIdToSend = Guid.NewGuid().ToString("D");
            var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = messageIdToSend,
                ["kind"] = PhoneContentScope.DataKind, ["created_ms"] = now, ["expires_ms"] = expires,
                ["body"] = PhoneContentScope.Wrap(kind, body, manifest) };
            TelefonMessageContract.ValidateMessage(message, now, false);
            var bytes = store.Seal("outbox", messageIdToSend, TelefonCrypto.Canonical(message));
            size = checked(size + bytes.Length);
            if (size > TelefonStore.OutboxLimitBytes) throw new InvalidOperationException("queue_full");
            id.Value = messageIdToSend; payload.Value = bytes;
            insert.ExecuteNonQuery();
            ids.Add(messageIdToSend);
        }
        WriteMeta(key, "personal_connection_reply", new JsonObject { ["authority"] = authority, ["request"] = run.Request.DeepClone(),
            ["scope"] = reference.DeepClone(), ["input_message"] = messageId, ["token"] = token, ["record_hash"] = declared,
            ["book_source"] = saved.BookSource, ["book_sequence"] = saved.Sequence, ["book_sha256"] = saved.Sha256,
            ["message_ids"] = ids, ["acknowledged"] = 0, ["expires_ms"] = expires,
            ["requires_input_results"] = input.HasScopedOriginals,
            ["outgoing_hashes"] = new JsonArray(outgoingHashes.Order(StringComparer.Ordinal).Select(hash => (JsonNode?)JsonValue.Create(hash)).ToArray())
            }, false, (db, transaction));
        if (store.RestoreFenced || !currentBook() || currentAuthority(run.Request, reference) != authority)
            throw new InvalidOperationException("The scoped connection reply lost its reader or saved book.");
        transaction.Commit();
    }

    private static JsonObject CountRecords(JsonArray records) => new()
    {
        ["notes"] = records.Count(record => record?["kind"]?.GetValue<string>() == "note"),
        ["tasks"] = records.Count(record => record?["kind"]?.GetValue<string>() == "task"),
        ["notebooks"] = records.Count(record => record?["kind"]?.GetValue<string>() == "notebook")
    };

    internal JsonObject? NextScopedConnectionReply(string peerId, string runId, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook, Func<string, bool> controlAckWritten)
    {
        using var db = store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
        return ReadScopedConnectionReply(db, transaction, peerId, runId, now, currentAuthority, currentBook, controlAckWritten)?.Message;
    }

    internal bool AcknowledgeScopedConnectionReply(string peerId, string runId, JsonObject sent, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook, Func<string, bool> controlAckWritten, out bool more)
    {
        more = false;
        using var db = store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var current = ReadScopedConnectionReply(db, transaction, peerId, runId, now, currentAuthority, currentBook, controlAckWritten);
        if (current is not { } frame || !JsonNode.DeepEquals(frame.Message, sent)) return false;
        using var remove = db.CreateCommand();
        remove.Transaction = transaction;
        remove.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND message_id=$id AND transport_policy='connection_only'";
        remove.Parameters.AddWithValue("$peer", peerId);
        remove.Parameters.AddWithValue("$id", sent["message_id"]!.GetValue<string>());
        if (remove.ExecuteNonQuery() != 1) return false;
        var count = TelefonProtocolContract.Integer(frame.Plan["acknowledged"]);
        if (frame.Chunk) AcknowledgeScopedOutgoingChunk(frame.Plan);
        else frame.Plan["acknowledged"] = ++count;
        WriteMeta(frame.Key, "personal_connection_reply", frame.Plan, true, (db, transaction));
        RequireScopedReplyAuthority(frame.Plan, currentAuthority, currentBook);
        transaction.Commit();
        more = count < frame.Plan["message_ids"]!.AsArray().Count ||
            frame.Key == ConnectionOriginalResultsKey(peerId, runId) &&
            ReadMeta(ConnectionReplyKey(peerId, runId), "personal_connection_reply") is not null;
        return true;
    }

    private (string Key, JsonObject Plan, JsonObject Message, bool Chunk)? ReadScopedConnectionReply(SqliteConnection db, SqliteTransaction transaction,
        string peerId, string runId, long now, Func<JsonObject, JsonObject, string> currentAuthority, Func<NativeBookSaveState?> currentBook,
        Func<string, bool> controlAckWritten)
    {
        var resultKey = ConnectionOriginalResultsKey(peerId, runId);
        var results = ReadMeta(resultKey, "personal_connection_reply", (db, transaction));
        var replyKey = ConnectionReplyKey(peerId, runId);
        var reply = ReadMeta(replyKey, "personal_connection_reply", (db, transaction));
        var resultsComplete = results is not null && TelefonProtocolContract.Integer(results["acknowledged"]) == results["message_ids"]!.AsArray().Count;
        var sendResults = results is not null && !resultsComplete;
        var plan = sendResults ? results : reply;
        var run = LoadRun(peerId, runId, now, (db, transaction));
        if (plan is null || run is not { Expired: false, Policy: "connection_only" }) return null;
        var expires = TelefonProtocolContract.Integer(plan["expires_ms"]);
        var originals = plan["original_hashes"] as JsonArray;
        if (expires <= now || expires > run.ExpiresMs || !JsonNode.DeepEquals(plan["request"], run.Request))
            throw new InvalidDataException("The scoped reply plan no longer matches its run.");
        var ids = plan["message_ids"]!.AsArray();
        var cursor = checked((int)TelefonProtocolContract.Integer(plan["acknowledged"]));
        if (cursor == ids.Count) return null;
        if (cursor < 0 || cursor >= ids.Count || originals is not null && originals.Count != ids.Count)
            throw new InvalidDataException("Invalid scoped reply acknowledgement index.");
        RequireScopedReplyAuthority(plan, currentAuthority, currentBook);
        if (!sendResults && plan["requires_input_results"]?.GetValue<bool>() == true)
        {
            if (!resultsComplete || results is null || !JsonNode.DeepEquals(results["input_message"], plan["input_message"]) ||
                !JsonNode.DeepEquals(results["token"], plan["token"])) return null;
            RequireScopedReplyAuthority(results, currentAuthority, currentBook);
        }
        var report = originals is null && cursor == ids.Count - 1;
        var window = report ? plan["outgoing_window"] as JsonObject : null;
        var chunk = window?["frames"]?[0] as JsonObject;
        if (chunk is not null)
        {
            expires = TelefonProtocolContract.Integer(window!["expires_ms"]);
            var requestId = window["request_id"]!.GetValue<string>();
            if (expires <= now || !controlAckWritten(requestId) ||
                ReadConnectionReceipt(db, transaction, peerId, requestId, now) is null) return null;
        }
        else if (report && plan["outgoing_hashes"] is JsonArray outgoing)
        {
            foreach (var entry in outgoing)
            {
                var hash = entry!.GetValue<string>();
                var resultId = plan["outgoing_results"]?[hash]?.GetValue<string>();
                if (resultId is null || !controlAckWritten(resultId) || ReadConnectionReceipt(db, transaction, peerId, resultId, now) is null ||
                    LoadAttachmentMetadata(peerId, runId, true, plan["record_hash"]!.GetValue<string>(),
                        hash, "outgoing", now, (db, transaction))["complete"]?.GetValue<bool>() != true) return null;
            }
        }
        var id = (chunk?["message_id"] ?? ids[cursor])!.GetValue<string>();
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = """
            SELECT payload FROM outbox WHERE peer_id=$peer AND message_id=$id AND kind=$kind
                AND transport_policy='connection_only' AND expires_ms=$expires
            """;
        read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$id", id);
        read.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind); read.Parameters.AddWithValue("$expires", expires);
        if (read.ExecuteScalar() is not byte[] bytes) return null; // A missing outbox row cannot advance the plan.
        var message = JsonNode.Parse(store.Open("outbox", id, bytes))!.AsObject();
        TelefonMessageContract.ValidateMessage(message, now, false);
        var wrapped = message["body"]!.AsObject();
        var body = wrapped["body"]!.AsObject();
        var expectedKind = chunk is not null ? "personal_sync.attachment_chunk" :
            originals is not null ? "personal_sync.attachment_result" : report ? "personal_sync.report" : "personal_sync.batch";
        if (message["message_id"]?.GetValue<string>() != id || message["kind"]?.GetValue<string>() != PhoneContentScope.DataKind ||
            TelefonProtocolContract.Integer(message["expires_ms"]) != expires || !JsonNode.DeepEquals(wrapped["scope"], plan["scope"]) ||
            wrapped["kind"]?.GetValue<string>() != expectedKind || body["run_id"]?.GetValue<string>() != runId)
            throw new InvalidDataException("The scoped reply message differs from its plan.");
        var validBody = chunk is not null
            ? TelefonProtocolContract.Integer(body["format"]) == 2 && body["reply"]?.GetValue<bool>() == true &&
                JsonNode.DeepEquals(body["sha256"], chunk["sha256"]) && JsonNode.DeepEquals(body["index"], chunk["index"]) &&
                JsonNode.DeepEquals(body["records_hash"], plan["record_hash"])
            : originals is not null
            ? TelefonProtocolContract.Integer(body["format"]) == 2 &&
                body["reply"]?.GetValue<bool>() == (plan["incoming_reply"]?.GetValue<bool>() == true) &&
                JsonNode.DeepEquals(body["sha256"], originals[cursor]) && JsonNode.DeepEquals(body["records_hash"], plan["record_hash"]) &&
                body["state"]?.GetValue<string>() == "complete" && body["error"]?.GetValue<string>() == "none"
            : JsonNode.DeepEquals(body["format"], run.Request["format"]) &&
                (report ? body["trigger"]?.GetValue<string>() == PersonalSyncContract.AutoConnectionTrigger :
                body["reply"]?.GetValue<bool>() == true && TelefonProtocolContract.Integer(body["sequence"]) == cursor &&
                JsonNode.DeepEquals(body["records_hash"], plan["record_hash"]));
        if (!validBody)
            throw new InvalidDataException("The scoped reply message differs from its plan.");
        return (sendResults ? resultKey : replyKey, plan, message, chunk is not null);
    }

    private void RequireScopedReplyAuthority(JsonObject plan, Func<JsonObject, JsonObject, string> currentAuthority,
        Func<NativeBookSaveState?> currentBook)
    {
        if (store.RestoreFenced || currentBook() is not { } saved || saved.BookSource != plan["book_source"]!.GetValue<string>() ||
            saved.Sequence != TelefonProtocolContract.Integer(plan["book_sequence"]) || saved.Sha256 != plan["book_sha256"]!.GetValue<string>() ||
            currentAuthority(plan["request"]!.AsObject(), plan["scope"]!.AsObject()) != plan["authority"]!.GetValue<string>())
            throw new InvalidOperationException("The scoped reply lost its original reader or saved book.");
    }

    private static string ConnectionReplyKey(string peerId, string runId) => $"personal_report:{peerId}:{runId}:connection_reply";

    internal bool CommitBatch(string peerId, string pendingMessageId, string token, long now, out IReadOnlyList<string> messageIds,
        IReadOnlyList<(string MessageId, string Token)>? actorIntents = null)
    {
        if (store.RestoreFenced) { messageIds = []; return false; }
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        string runId; bool reply;
        using (var identity = connection.CreateCommand()) { identity.Transaction = transaction; identity.CommandText = "SELECT run_id,reply FROM personal_batch WHERE peer_id=$peer AND message_id=$message AND commit_token=$token"; identity.Parameters.AddWithValue("$peer", peerId); identity.Parameters.AddWithValue("$message", pendingMessageId); identity.Parameters.AddWithValue("$token", token); using var reader = identity.ExecuteReader(); if (!reader.Read()) { messageIds = []; return false; } runId = reader.GetString(0); reply = reader.GetBoolean(1); }
        if (string.IsNullOrEmpty(token) ||
            LoadRun(peerId, runId, now, (connection, transaction)) is not { Expired: false, Policy: not "connection_only" })
        { messageIds = []; return false; }
        var complete = CompleteBatch(connection, peerId, runId, reply, token, transaction);
        if (complete is null || complete.PendingMessageId != pendingMessageId)
        { messageIds = []; return false; }
        using (var expired = connection.CreateCommand())
        {
            expired.Transaction = transaction;
            expired.CommandText = "SELECT COUNT(*) FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND expires_ms<=$now";
            Parameters(expired, peerId, runId, reply); expired.Parameters.AddWithValue("$now", now);
            if (Convert.ToInt64(expired.ExecuteScalar()) != 0) { messageIds = []; return false; }
        }
        var ids = new List<string>(); using (var read = connection.CreateCommand()) { read.Transaction = transaction; read.CommandText = "SELECT message_id FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND commit_token=$token ORDER BY sequence"; Parameters(read, peerId, runId, reply); read.Parameters.AddWithValue("$token", token); using var reader = read.ExecuteReader(); while (reader.Read()) ids.Add(reader.GetString(0)); }
        if (actorIntents is not null || (PersonalSyncActorContract.IsStoragePeer(peerId) && !reply))
        {
            if (peerId != PersonalSyncActorContract.StoragePeer(runId) || reply || actorIntents?.Count > 256)
                throw new InvalidDataException("invalid_actor_commit_intents");
            var expected = actorIntents ?? [];
            if (expected.Any(item => string.IsNullOrEmpty(item.MessageId) || string.IsNullOrEmpty(item.Token)) ||
                expected.Select(item => item.MessageId).Distinct(StringComparer.Ordinal).Count() != expected.Count)
                throw new InvalidDataException("invalid_actor_commit_intents");
            var actual = new HashSet<(string MessageId, string Token)>();
            using (var read = connection.CreateCommand())
            {
                read.Transaction = transaction; read.CommandText = "SELECT message_id,commit_token,payload,expires_ms FROM personal_domain WHERE peer_id=$peer";
                read.Parameters.AddWithValue("$peer", peerId); using var reader = read.ExecuteReader();
                while (reader.Read())
                {
                    var raw = store.Open("personal_domain", reader.GetString(0), (byte[])reader[2]);
                    try
                    {
                        if (reader.GetInt64(3) <= now || JsonNode.Parse(raw)?["body"]?["run_id"]?.GetValue<string>() != runId)
                        { messageIds = []; return false; }
                    }
                    finally { CryptographicOperations.ZeroMemory(raw); }
                    actual.Add((reader.GetString(0), reader.GetString(1)));
                }
            }
            if (!actual.SetEquals(expected)) { messageIds = []; return false; }
            foreach (var item in expected)
                if (!CommitDecisionIntentInTransaction(connection, transaction, peerId, item.MessageId, item.Token, "accepted", "none", now))
                    throw new InvalidOperationException("actor_commit_intent_changed");
        }
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
        var result = CommitDecisionIntentInTransaction(connection, transaction, peerId, messageId, token, outcome == "applied" ? "accepted" : "rejected", error, now);
        if (result) transaction.Commit();
        return result;
    }

    private static bool CommitDecisionIntentInTransaction(SqliteConnection connection, SqliteTransaction transaction,
        string peerId, string messageId, string token, string result, string error, long now)
    {
        using var read = connection.CreateCommand(); read.Transaction = transaction; read.CommandText = "SELECT kind FROM personal_domain WHERE peer_id=$peer AND message_id=$message AND commit_token=$token"; read.Parameters.AddWithValue("$peer", peerId); read.Parameters.AddWithValue("$message", messageId); read.Parameters.AddWithValue("$token", token); var kind = read.ExecuteScalar() as string;
        if (kind is null) return false;
        using (var inbox = connection.CreateCommand()) { inbox.Transaction = transaction; inbox.CommandText = "UPDATE inbox SET state='processed' WHERE peer_id=$peer AND message_id=$message"; inbox.Parameters.AddWithValue("$peer", peerId); inbox.Parameters.AddWithValue("$message", messageId); inbox.ExecuteNonQuery(); }
        using (var dedupe = connection.CreateCommand()) { dedupe.Transaction = transaction; dedupe.CommandText = "UPDATE dedupe SET result=$result,error=$error,seen_ms=$now WHERE peer_id=$peer AND message_id=$message"; dedupe.Parameters.AddWithValue("$message", messageId); dedupe.Parameters.AddWithValue("$peer", peerId); dedupe.Parameters.AddWithValue("$result", result); dedupe.Parameters.AddWithValue("$error", error); dedupe.Parameters.AddWithValue("$now", now); dedupe.ExecuteNonQuery(); }
        using (var delete = connection.CreateCommand()) { delete.Transaction = transaction; delete.CommandText = "DELETE FROM personal_domain WHERE peer_id=$peer AND message_id=$message AND commit_token=$token"; delete.Parameters.AddWithValue("$peer", peerId); delete.Parameters.AddWithValue("$message", messageId); delete.Parameters.AddWithValue("$token", token); delete.ExecuteNonQuery(); }
        return true;
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
            if (LoadRun(identity.PeerId, identity.RunId, now) is { Expired: false, Policy: not "connection_only" } &&
                CompleteBatch(database, identity.PeerId, identity.RunId, identity.Reply, identity.Token) is { } batch) result.Add(batch);
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

    internal bool OutgoingAttachmentComplete(string peerId, string runId, bool reply, string recordsHash, string hash, long now) =>
        LoadAttachmentMetadata(peerId, runId, reply, recordsHash, hash, "outgoing", now)["complete"]!.GetValue<bool>();

    internal void CompleteOutgoingAttachment(string peerId, string runId, bool reply, string recordsHash, string hash, long now)
    {
        var metadata = LoadAttachmentMetadata(peerId, runId, reply, recordsHash, hash, "outgoing", now); metadata["complete"] = true;
        var primary = TransferPrimary(peerId, runId, reply, recordsHash, hash, "outgoing"); var encrypted = store.Seal("personal_attachment_transfer", primary, TelefonCrypto.Canonical(metadata));
        using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "UPDATE personal_attachment_transfer SET complete=1,metadata=$metadata WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction='outgoing'";
        Parameters(command, peerId, runId, reply); command.Parameters.AddWithValue("$records", recordsHash); command.Parameters.AddWithValue("$hash", hash); command.Parameters.AddWithValue("$metadata", encrypted); command.ExecuteNonQuery();
    }

    internal void StageAttachment(string peerId, string runId, bool reply, string recordsHash, JsonObject descriptor,
        string direction, string policy, long expiresMs, IEnumerable<(int Index, byte[] Data)> chunks,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context = null)
    {
        if (policy is not ("any" or "wifi_only")) throw new InvalidDataException("Attachment-Metadaten ungültig.");
        StageAttachmentCore(peerId, runId, reply, recordsHash, descriptor, direction, policy, expiresMs, chunks, context);
    }

    private void StageAttachmentCore(string peerId, string runId, bool reply, string recordsHash, JsonObject descriptor,
        string direction, string policy, long expiresMs, IEnumerable<(int Index, byte[] Data)> chunks,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context)
    {
        if (direction is not ("incoming" or "outgoing")) throw new InvalidDataException("Attachment-Metadaten ungültig.");
        PersonalSyncContract.ValidateAttachmentDescriptor(descriptor);
        var hash = descriptor["sha256"]?.GetValue<string>() ?? throw new InvalidDataException(); var size = TelefonProtocolContract.Integer(descriptor["size"]); var mime = descriptor["mime"]?.GetValue<string>() ?? throw new InvalidDataException(); var attachmentId = descriptor["attachment_id"]?.GetValue<string>() ?? throw new InvalidDataException();
        if (size is < 1 or > MaximumAttachmentBytes || expiresMs <= 0) throw new InvalidDataException("Attachment-Metadaten ungültig.");
        var indexed = chunks.Select(item => (item.Index, Data: item.Data.ToArray())).ToArray();
        var totalChunks = checked((int)((size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw));
        if (indexed.Select(item => item.Index).Distinct().Count() != indexed.Length || indexed.Any(item => item.Index < 0 || item.Index >= totalChunks || item.Data.Length != (item.Index + 1 < totalChunks ? PersonalSyncContract.ChunkRaw : size - (long)item.Index * PersonalSyncContract.ChunkRaw))) throw new InvalidDataException("Attachment-Chunk ungültig.");
        var metadata = new JsonObject { ["peer_id"] = peerId, ["run_id"] = runId, ["reply"] = reply, ["attachment_id"] = attachmentId, ["records_hash"] = recordsHash, ["sha256"] = hash, ["direction"] = direction, ["total_chunks"] = (size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw, ["size"] = size, ["mime"] = mime, ["expires_ms"] = expiresMs, ["complete"] = false, ["transport_policy"] = policy };
        var transferPrimary = TransferPrimary(peerId, runId, reply, recordsHash, hash, direction); var encryptedMetadata = store.Seal("personal_attachment_transfer", transferPrimary, TelefonCrypto.Canonical(metadata));
        using var owned = context is null ? store.OpenDatabase() : null;
        owned?.Open();
        using var ownedTransaction = owned?.BeginTransaction();
        var connection = context?.Connection ?? owned!;
        var transaction = context?.Transaction ?? ownedTransaction!;
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
        ownedTransaction?.Commit();
    }

    internal void StageAttachmentChunk(string peerId, string runId, bool reply, string recordsHash, string hash,
        string direction, int index, byte[] data, long expiresMs)
    {
        if (direction is not ("incoming" or "outgoing") || index < 0 || data.Length is < 1 or > PersonalSyncContract.ChunkRaw || expiresMs <= 0)
            throw new InvalidDataException("Attachment-Chunk ungültig.");
        var primary = ChunkPrimary(peerId, runId, reply, recordsHash, hash, direction, index);
        using var connection = store.OpenDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
        long size;
        using (var transfer = connection.CreateCommand()) { transfer.Transaction = transaction; transfer.CommandText = "SELECT size FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction AND expires_ms>0 AND transport_policy IN ('any','wifi_only')"; Parameters(transfer, peerId, runId, reply); transfer.Parameters.AddWithValue("$records", recordsHash); transfer.Parameters.AddWithValue("$hash", hash); transfer.Parameters.AddWithValue("$direction", direction); size = transfer.ExecuteScalar() as long? ?? throw new InvalidDataException("Attachment-Manifest fehlt."); }
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
        store.PurgeActorFixedControls(connection, transaction, peerId);
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

    private PersonalSyncStagedBatch? CompleteBatch(SqliteConnection connection, string peerId, string runId, bool reply, string token,
        SqliteTransaction? transaction = null, (JsonObject Reference, long Now, Func<string, bool> AcknowledgementWritten)? protectedSave = null,
        long? scopedNow = null)
    {
        var rows = new List<(int Sequence, bool Last, string MessageId, byte[] Payload)>(); using var command = connection.CreateCommand();
        command.Transaction = transaction; command.CommandText = "SELECT sequence,last,message_id,payload,commit_token FROM personal_batch WHERE peer_id=$peer AND run_id=$run AND reply=$reply ORDER BY sequence";
        Parameters(command, peerId, runId, reply);
        using (var reader = command.ExecuteReader())
            while (reader.Read())
            {
                if (protectedSave.HasValue && reader.GetString(4) != token)
                    throw new InvalidOperationException("The scoped batch does not own the native commit token.");
                rows.Add((reader.GetInt32(0), reader.GetBoolean(1), reader.GetString(2), (byte[])reader[3]));
            }
        var finals = rows.Where(row => row.Last).ToArray(); if (finals.Length > 1 || finals.Length == 1 && rows.Any(row => row.Sequence > finals[0].Sequence)) throw new InvalidDataException("Widersprüchliches Batch-Ende.");
        if (finals.Length != 1 || !rows.Select(row => row.Sequence).SequenceEqual(Enumerable.Range(0, finals[0].Sequence + 1))) return null;
        var records = new JsonArray(); string? advertised = null;
        var expires = long.MaxValue;
        var request = ReadMeta(RunKey(peerId, runId), "personal_run", transaction is null ? null : (connection, transaction))?["body"] as JsonObject
            ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
        var format = request["format"]!.GetValue<int>();
        foreach (var row in rows)
        {
            var message = JsonNode.Parse(store.Open("personal_batch", BatchPrimary(peerId, runId, reply, row.Sequence), row.Payload))!.AsObject();
            var body = message["body"]!.AsObject();
            expires = Math.Min(expires, TelefonProtocolContract.Integer(message["expires_ms"]));
            if (protectedSave is { } proof)
            {
                var wrapped = message.DeepClone().AsObject(); wrapped["kind"] = PhoneContentScope.DataKind;
                wrapped["body"] = new JsonObject { ["format"] = PhoneContentScope.Version, ["scope"] = proof.Reference.DeepClone(),
                    ["kind"] = "personal_sync.batch", ["body"] = body.DeepClone() };
                if (!proof.AcknowledgementWritten(row.MessageId) ||
                    !JsonNode.DeepEquals(ReadConnectionReceipt(connection, transaction!, peerId, row.MessageId, proof.Now), wrapped))
                    throw new InvalidOperationException("An exact scoped batch receipt is missing.");
            }
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
        if (scopedNow is { } now && expires <= now)
            throw new InvalidOperationException("A batch receipt on the original connection has expired.");
        return new PersonalSyncStagedBatch(peerId, runId, reply, finals[0].MessageId, token, records, advertised ?? "", format,
            expires, scopedNow.HasValue && ValidateScopedOriginalManifest(records));
    }

    private static bool ValidateScopedOriginalManifest(JsonArray records)
    {
        var originals = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        long bytes = 0;
        foreach (var descriptor in ScopedOriginalDescriptors(records))
        {
            var hash = descriptor["sha256"]!.GetValue<string>();
            var size = TelefonProtocolContract.Integer(descriptor["size"]);
            if (originals.TryGetValue(hash, out var previous))
            {
                if (!PersonalSyncContract.AttachmentSourceMatches([previous], descriptor["mime"]!.GetValue<string>(), size))
                    throw new InvalidDataException("Conflicting scoped connection original descriptor.");
                continue;
            }
            originals.Add(hash, descriptor);
            bytes += size;
            if (originals.Count > MaximumAttachmentsPerRun || bytes > MaximumRunChunkBytes)
                throw new InvalidDataException("Scoped connection originals exceed the Windows staging limits.");
        }
        return originals.Count != 0;
    }

    private static IEnumerable<JsonObject> ScopedOriginalDescriptors(JsonArray records) =>
        records.OfType<JsonObject>().Where(record => record["kind"]?.GetValue<string>() == "note")
            .SelectMany(record => (record["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>());

    private JsonObject? ReadMeta(string key, string type,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context = null)
    {
        using var owned = context is null ? store.OpenDatabase() : null;
        owned?.Open();
        using var command = (context?.Connection ?? owned!).CreateCommand();
        command.Transaction = context?.Transaction;
        command.CommandText = "SELECT value FROM meta WHERE key=$key";
        command.Parameters.AddWithValue("$key", key);
        return command.ExecuteScalar() is byte[] encrypted ? JsonNode.Parse(store.Open(type, key, encrypted))!.AsObject() : null;
    }
    private JsonObject LoadAttachmentMetadata(string peerId, string runId, bool reply, string recordsHash, string hash, string direction, long now,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context = null)
    {
        using var owned = context is null ? store.OpenDatabase() : null;
        owned?.Open();
        using var command = (context?.Connection ?? owned!).CreateCommand(); command.Transaction = context?.Transaction;
        command.CommandText = "SELECT size,mime,transport_policy,expires_ms,complete,metadata FROM personal_attachment_transfer WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction=$direction"; Parameters(command, peerId, runId, reply); command.Parameters.AddWithValue("$records", recordsHash); command.Parameters.AddWithValue("$hash", hash); command.Parameters.AddWithValue("$direction", direction); using var reader = command.ExecuteReader(); if (!reader.Read()) throw new InvalidDataException("Attachment-Manifest fehlt.");
        if (context is null && reader.GetString(2) is not ("any" or "wifi_only")) throw new InvalidOperationException("The attachment requires its original reader.");
        var metadata = JsonNode.Parse(store.Open("personal_attachment_transfer", TransferPrimary(peerId, runId, reply, recordsHash, hash, direction), (byte[])reader[5]))!.AsObject();
        if (metadata["peer_id"]?.GetValue<string>() != peerId || metadata["run_id"]?.GetValue<string>() != runId || metadata["reply"]?.GetValue<bool>() != reply || metadata["records_hash"]?.GetValue<string>() != recordsHash || metadata["sha256"]?.GetValue<string>() != hash || metadata["direction"]?.GetValue<string>() != direction || metadata["size"]?.GetValue<long>() != reader.GetInt64(0) || metadata["mime"]?.GetValue<string>() != reader.GetString(1) || metadata["transport_policy"]?.GetValue<string>() != reader.GetString(2) || metadata["expires_ms"]?.GetValue<long>() != reader.GetInt64(3) || metadata["complete"]?.GetValue<bool>() != reader.GetBoolean(4) || reader.GetInt64(3) <= now) throw new InvalidDataException("Unauthentisierte oder abgelaufene Attachment-Metadaten.");
        return metadata;
    }
    private void WriteMeta(string key, string type, JsonObject value, bool replace,
        (SqliteConnection Connection, SqliteTransaction Transaction)? context = null)
    {
        using var owned = context is null ? store.OpenDatabase() : null;
        owned?.Open();
        using var command = (context?.Connection ?? owned!).CreateCommand();
        command.Transaction = context?.Transaction;
        command.CommandText = $"INSERT OR {(replace ? "REPLACE" : "IGNORE")} INTO meta(key,value) VALUES($key,$value)";
        command.Parameters.AddWithValue("$key", key);
        command.Parameters.AddWithValue("$value", store.Seal(type, key, TelefonCrypto.Canonical(value)));
        command.ExecuteNonQuery();
    }
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
internal sealed record PersonalSyncStagedBatch(string PeerId, string RunId, bool Reply, string PendingMessageId, string CommitToken, JsonArray Records,
    string RecordsHash, int Format, long ExpiresMs, bool HasScopedOriginals);
internal sealed record PersonalSyncDecisionIntent(string PeerId, string PendingMessageId, string CommitToken, string Kind, JsonObject Body);
