using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class PersonalSyncStore
{
    private const string ConnectionOriginalPolicy = "connection_only";
    private const int ConnectionWindowSize = 8;

    internal ScopedOriginalWindow? QueueScopedOriginalWindow(string peerId, string messageId, string token, long now,
        Func<JsonObject, JsonObject, string> currentAuthority, Func<string, bool> acknowledgementWritten)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var (run, reference, authority, batch, _) = ReadScopedConnectionInput(db, transaction, peerId, messageId, token, now,
            currentAuthority, acknowledgementWritten);
        var expires = Math.Min(batch.ExpiresMs, run.ExpiresMs);
        foreach (var descriptor in ScopedOriginalDescriptors(batch.Records)
            .DistinctBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal)
            .OrderBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal))
        {
            var hash = descriptor["sha256"]!.GetValue<string>();
            var size = TelefonProtocolContract.Integer(descriptor["size"]);
            var total = checked((int)((size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw));
            var indices = ReadScopedOriginalIndices(db, transaction, batch, hash);
            var start = Enumerable.Range(0, total).FirstOrDefault(index => !indices.Contains(index), -1);
            if (start < 0) continue;
            var end = start + 1;
            while (end < total && end < start + ConnectionWindowSize && !indices.Contains(end)) end++;

            var content = new JsonObject
            {
                ["format"] = 2, ["run_id"] = run.RunId, ["reply"] = batch.Reply, ["records_hash"] = batch.RecordsHash,
                ["wants"] = new JsonArray(new JsonObject { ["sha256"] = hash, ["ranges"] = new JsonArray(new JsonArray(start, end)) })
            };
            var id = Guid.NewGuid().ToString("D");
            var frame = new JsonObject
            {
                ["type"] = "message", ["v"] = 1, ["kind"] = PhoneContentScope.DataKind, ["message_id"] = id,
                ["created_ms"] = now, ["expires_ms"] = expires,
                ["body"] = PhoneContentScope.ValidateData(new JsonObject
                {
                    ["format"] = PhoneContentScope.Version, ["scope"] = reference.DeepClone(),
                    ["kind"] = "personal_sync.attachment_request", ["body"] = content
                })
            };
            TelefonMessageContract.ValidateMessage(frame, now, false);
            var encrypted = Store.Seal("outbox", id, TelefonCrypto.Canonical(frame));
            if (Scalar(db, transaction, "SELECT COALESCE(SUM(length(payload)),0) FROM outbox") + encrypted.Length > TelefonStore.OutboxLimitBytes)
                throw new InvalidOperationException("queue_full");
            StageAttachmentCore(peerId, run.RunId, batch.Reply, batch.RecordsHash, descriptor, "incoming",
                ConnectionOriginalPolicy, expires, [], (db, transaction));
            using var insert = db.CreateCommand(); insert.Transaction = transaction;
            insert.CommandText = """
                INSERT INTO outbox (message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy)
                VALUES ($id,$peer,$kind,$now,$expires,$payload,0,$now,'','connection_only')
                """;
            insert.Parameters.AddWithValue("$id", id); insert.Parameters.AddWithValue("$peer", peerId);
            insert.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind); insert.Parameters.AddWithValue("$now", now);
            insert.Parameters.AddWithValue("$expires", expires); insert.Parameters.AddWithValue("$payload", encrypted);
            insert.ExecuteNonQuery();
            var window = new ScopedOriginalWindow(batch, run.Request, reference, authority, descriptor, start, end, total, frame);
            RequireScopedOriginalWindow(db, transaction, window, now, currentAuthority);
            transaction.Commit();
            return window;
        }
        return null;
    }

    internal void RequireScopedOriginalWindow(ScopedOriginalWindow window, long now,
        Func<JsonObject, JsonObject, string> currentAuthority)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
        RequireScopedOriginalWindow(db, transaction, window, now, currentAuthority);
    }

    private void RequireScopedOriginalWindow(SqliteConnection db, SqliteTransaction transaction, ScopedOriginalWindow window,
        long now, Func<JsonObject, JsonObject, string> currentAuthority)
    {
        if (Store.RestoreFenced || window.ExpiresMs <= now || currentAuthority(window.Request, window.Reference) != window.Authority)
            throw new InvalidOperationException("The original attachment window lost its original reader.");
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = """
            SELECT payload FROM outbox WHERE peer_id=$peer AND message_id=$id AND kind=$kind
            AND transport_policy='connection_only' AND expires_ms=$expires
            """;
        read.Parameters.AddWithValue("$peer", window.Batch.PeerId); read.Parameters.AddWithValue("$id", window.Id);
        read.Parameters.AddWithValue("$kind", PhoneContentScope.DataKind); read.Parameters.AddWithValue("$expires", window.ExpiresMs);
        if (read.ExecuteScalar() is not byte[] payload ||
            !JsonNode.DeepEquals(JsonNode.Parse(Store.Open("outbox", window.Id, payload)), window.Frame))
            throw new InvalidOperationException("The exact original attachment window is no longer staged.");
    }

    internal TelefonAck? ScopedOriginalChunkDuplicate(string peerId, JsonObject envelope, JsonObject request, JsonObject reference,
        string authority, long now, Func<JsonObject, JsonObject, string> currentAuthority)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
        var id = envelope["message_id"]!.GetValue<string>();
        var exact = ReadConnectionReceipt(db, transaction, peerId, id, now);
        if (exact is null) return null;
        if (!JsonNode.DeepEquals(exact, envelope)) throw new InvalidDataException("Conflicting scoped original chunk receipt.");
        var runId = request["run_id"]!.GetValue<string>();
        if (Store.RestoreFenced || currentAuthority(request, reference) != authority ||
            ReadMeta(RunKey(peerId, runId), "personal_run", (db, transaction))?["connection_authority"]?.GetValue<string>() != authority ||
            !JsonNode.DeepEquals(ReadMeta($"personal_scope:{peerId}:{runId}", "personal_scope", (db, transaction))?["scope"], reference))
            throw new InvalidOperationException("The original chunk receipt belongs to another reader.");
        return new TelefonAck(id, "duplicate", "none");
    }

    internal (TelefonAck Ack, bool WindowComplete) StageScopedOriginalChunk(ScopedOriginalWindow window, JsonObject envelope,
        long now, Func<JsonObject, JsonObject, string> currentAuthority)
    {
        TelefonMessageContract.ValidateMessage(envelope, now, true);
        var wrapper = envelope["body"]!.AsObject();
        var body = wrapper["body"]!.AsObject();
        var index = checked((int)TelefonProtocolContract.Integer(body["index"]));
        if (envelope["kind"]?.GetValue<string>() != PhoneContentScope.DataKind ||
            wrapper["kind"]?.GetValue<string>() != "personal_sync.attachment_chunk" || !JsonNode.DeepEquals(wrapper["scope"], window.Reference) ||
            body["run_id"]?.GetValue<string>() != window.Batch.RunId || body["reply"]?.GetValue<bool>() != window.Batch.Reply ||
            body["records_hash"]?.GetValue<string>() != window.Batch.RecordsHash || body["sha256"]?.GetValue<string>() != window.Hash ||
            index < window.Start || index >= window.End || TelefonProtocolContract.Integer(envelope["expires_ms"]) > window.ExpiresMs)
            throw new InvalidOperationException("The original chunk is outside the actual attachment window.");

        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        RequireScopedOriginalWindow(db, transaction, window, now, currentAuthority);
        var batch = window.Batch;
        var indices = ReadScopedOriginalIndices(db, transaction, batch, window.Hash);
        if (!indices.Add(index)) throw new InvalidDataException("An original chunk index already has another message identity.");
        var raw = Convert.FromBase64String(body["data"]!.GetValue<string>());
        try
        {
            StageAttachmentCore(batch.PeerId, batch.RunId, batch.Reply, batch.RecordsHash, window.Descriptor, "incoming",
                ConnectionOriginalPolicy, window.ExpiresMs, [(index, raw)], (db, transaction));
            if (indices.Count == window.Total)
                VerifyScopedOriginal(db, transaction, batch, window.Descriptor, window.Total);
            WriteConnectionReceipt(db, transaction, batch.PeerId, envelope, now);
            RequireScopedOriginalWindow(db, transaction, window, now, currentAuthority);
            transaction.Commit();
        }
        finally { CryptographicOperations.ZeroMemory(raw); }
        var complete = Enumerable.Range(window.Start, window.End - window.Start).All(indices.Contains);
        return (new TelefonAck(envelope["message_id"]!.GetValue<string>(), "accepted", "none"), complete);
    }

    internal void RetireScopedOriginalWindow(ScopedOriginalWindow window, long now,
        Func<JsonObject, JsonObject, string> currentAuthority)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        RequireScopedOriginalWindow(db, transaction, window, now, currentAuthority);
        var batch = window.Batch;
        var indices = ReadScopedOriginalIndices(db, transaction, batch, window.Hash);
        if (!Enumerable.Range(window.Start, window.End - window.Start).All(indices.Contains))
            throw new InvalidOperationException("The original attachment window still has missing chunks.");
        if (indices.Count == window.Total)
            MarkScopedOriginalComplete(db, transaction, batch.PeerId, batch.RunId, batch.Reply, batch.RecordsHash, window.Hash,
                "incoming", window.ExpiresMs, now);
        using var remove = db.CreateCommand(); remove.Transaction = transaction;
        remove.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND message_id=$id AND transport_policy='connection_only'";
        remove.Parameters.AddWithValue("$peer", window.Batch.PeerId); remove.Parameters.AddWithValue("$id", window.Id);
        if (remove.ExecuteNonQuery() != 1 || currentAuthority(window.Request, window.Reference) != window.Authority)
            throw new InvalidOperationException("The original attachment window could not be retired.");
        transaction.Commit();
    }

    private void MarkScopedOriginalComplete(SqliteConnection db, SqliteTransaction transaction, string peerId, string runId, bool reply,
        string recordsHash, string hash, string direction, long expires, long now)
    {
        var transfer = LoadAttachmentMetadata(peerId, runId, reply, recordsHash, hash, direction, now, (db, transaction));
        if (transfer["transport_policy"]?.GetValue<string>() != ConnectionOriginalPolicy)
            throw new InvalidOperationException("The original attachment transfer has a different policy.");
        transfer["complete"] = true;
        var primary = TransferPrimary(peerId, runId, reply, recordsHash, hash, direction);
        using var mark = db.CreateCommand(); mark.Transaction = transaction;
        mark.CommandText = """
            UPDATE personal_attachment_transfer SET complete=1, metadata=$metadata
            WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash
            AND direction=$direction AND transport_policy='connection_only' AND expires_ms=$expires AND complete=0
            """;
        Parameters(mark, peerId, runId, reply);
        mark.Parameters.AddWithValue("$records", recordsHash); mark.Parameters.AddWithValue("$hash", hash);
        mark.Parameters.AddWithValue("$direction", direction); mark.Parameters.AddWithValue("$expires", expires);
        mark.Parameters.AddWithValue("$metadata", Store.Seal("personal_attachment_transfer", primary, TelefonCrypto.Canonical(transfer)));
        if (mark.ExecuteNonQuery() != 1) throw new InvalidOperationException("The completed original transfer was not recorded.");
    }

    internal (PersonalSyncStagedBatch Batch, JsonObject Request, JsonObject Reference, JsonObject Data) PrepareScopedOriginalOffer(
        string peerId, string messageId, string token, long now, Func<JsonObject, JsonObject, string> currentAuthority,
        Func<string, bool> acknowledgementWritten)
    {
        using var db = Store.OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
        var (run, reference, authority, batch, _) = ReadScopedConnectionInput(db, transaction, peerId, messageId, token,
            now, currentAuthority, acknowledgementWritten);
        if (!batch.HasScopedOriginals) throw new InvalidOperationException("There are no scoped originals to offer.");
        var data = ReadCompletedScopedOriginals(db, transaction, batch, now, includeData: true);
        if (Store.RestoreFenced || currentAuthority(run.Request, reference) != authority)
            throw new InvalidOperationException("The original attachment offer lost its reader.");
        return (batch, run.Request, reference, data);
    }

    private JsonObject ReadCompletedScopedOriginals(SqliteConnection db, SqliteTransaction transaction,
        PersonalSyncStagedBatch batch, long now, bool includeData)
    {
        var values = new JsonObject();
        foreach (var descriptor in ScopedOriginalDescriptors(batch.Records)
            .DistinctBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal))
        {
            var hash = descriptor["sha256"]!.GetValue<string>();
            var mime = descriptor["mime"]!.GetValue<string>();
            var size = TelefonProtocolContract.Integer(descriptor["size"]);
            var transfer = LoadAttachmentMetadata(batch.PeerId, batch.RunId, batch.Reply, batch.RecordsHash, hash, "incoming", now, (db, transaction));
            if (transfer["transport_policy"]?.GetValue<string>() != ConnectionOriginalPolicy || transfer["complete"]?.GetValue<bool>() != true ||
                TelefonProtocolContract.Integer(transfer["expires_ms"]) != batch.ExpiresMs ||
                TelefonProtocolContract.Integer(transfer["size"]) != size || transfer["mime"]?.GetValue<string>() != mime)
                throw new InvalidOperationException("The declared original has no exact completed transfer.");
            var total = checked((int)((size + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw));
            if (!includeData) continue;
            using var output = new MemoryStream(checked((int)size));
            try
            {
                VerifyScopedOriginal(db, transaction, batch, descriptor, total, output);
                values[hash] = $"data:{mime};base64,{Convert.ToBase64String(output.GetBuffer(), 0, checked((int)output.Length))}";
            }
            finally { CryptographicOperations.ZeroMemory(output.GetBuffer()); }
        }
        return values;
    }

    private static void VerifyScopedOriginalBook(JsonArray batchRecords, JsonObject candidate,
        Action<JsonObject, byte[]>? originalVerified = null)
    {
        var state = candidate["personalSync"]?.AsObject() ?? throw new InvalidDataException("The proposed original book has no personal sync identities.");
        var records = batchRecords.OfType<JsonObject>().Where(record => record["kind"]?.GetValue<string>() == "note" &&
            record["value"]?["attachments"] is JsonArray { Count: > 0 }).ToDictionary(record => record["id"]!.GetValue<string>(), StringComparer.Ordinal);
        var found = new HashSet<string>(StringComparer.Ordinal);
        foreach (var note in (candidate["notizen"] as JsonArray ?? []).OfType<JsonObject>())
        {
            var wireId = PersonalActorOutgoingProducer.NoteWireId(note["id"]!.GetValue<string>(), state);
            if (!records.TryGetValue(wireId, out var record)) continue;
            if (!found.Add(wireId)) throw new InvalidDataException("The proposed book has ambiguous original note identities.");
            var attachments = (note["anhaenge"] as JsonArray ?? []).OfType<JsonObject>().ToLookup(item =>
                PersonalActorOutgoingProducer.AttachmentId(wireId, item["id"]!.GetValue<string>(), state), StringComparer.Ordinal);
            foreach (var descriptor in record["value"]!["attachments"]!.AsArray().OfType<JsonObject>())
            {
                var id = PersonalActorOutgoingProducer.AttachmentId(wireId, descriptor["attachment_id"]!.GetValue<string>(), state);
                var matches = attachments[id].Take(2).ToArray();
                if (matches.Length != 1 || !JsonNode.DeepEquals(matches[0]["name"], descriptor["name"]) ||
                    !JsonNode.DeepEquals(matches[0]["art"], descriptor["kind"]))
                    throw new InvalidDataException("The proposed book has no exact original attachment identity.");
                var (mime, raw) = PersonalSyncContract.DecodeDataUrl(matches[0]["daten"]!.GetValue<string>());
                try
                {
                    if (!PersonalSyncContract.AttachmentSourceMatches([descriptor], mime, raw.LongLength) ||
                        Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() != descriptor["sha256"]!.GetValue<string>())
                        throw new InvalidDataException("The proposed book changed the original attachment bytes.");
                    originalVerified?.Invoke(descriptor, raw);
                }
                finally { CryptographicOperations.ZeroMemory(raw); }
            }
        }
        if (found.Count != records.Count) throw new InvalidDataException("The proposed book is missing a note with original attachments.");
    }

    private static HashSet<int> ReadScopedOriginalIndices(SqliteConnection db, SqliteTransaction transaction, PersonalSyncStagedBatch batch,
        string hash)
    {
        using var command = ScopedOriginalChunks(db, transaction, batch, hash, "chunk_index");
        using var rows = command.ExecuteReader();
        var indices = new HashSet<int>();
        while (rows.Read()) indices.Add(rows.GetInt32(0));
        return indices;
    }

    private static SqliteCommand ScopedOriginalChunks(SqliteConnection db, SqliteTransaction transaction, PersonalSyncStagedBatch batch,
        string hash, string columns)
    {
        var command = db.CreateCommand(); command.Transaction = transaction;
        command.CommandText = $"SELECT {columns} FROM personal_attachment_chunk " +
            "WHERE peer_id=$peer AND run_id=$run AND reply=$reply AND records_hash=$records AND sha256=$hash AND direction='incoming' ORDER BY chunk_index";
        Parameters(command, batch.PeerId, batch.RunId, batch.Reply);
        command.Parameters.AddWithValue("$records", batch.RecordsHash); command.Parameters.AddWithValue("$hash", hash);
        return command;
    }

    private void VerifyScopedOriginal(SqliteConnection db, SqliteTransaction transaction, PersonalSyncStagedBatch batch,
        JsonObject descriptor, int total, Stream? output = null)
    {
        var hash = descriptor["sha256"]!.GetValue<string>();
        using var command = ScopedOriginalChunks(db, transaction, batch, hash, "chunk_index,payload");
        using var rows = command.ExecuteReader();
        using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var size = 0L;
        var index = 0;
        while (rows.Read())
        {
            if (rows.GetInt32(0) != index) throw new InvalidDataException("Noncontiguous original chunks.");
            var primary = ChunkPrimary(batch.PeerId, batch.RunId, batch.Reply, batch.RecordsHash, hash, "incoming", index);
            var bytes = Store.Open("personal_attachment_chunk", primary, (byte[])rows[1]);
            try
            {
                if (index == 0 && PersonalSyncContract.MimeFromMagic(bytes) != descriptor["mime"]!.GetValue<string>())
                    throw new InvalidDataException("The original does not have its declared file type.");
                digest.AppendData(bytes);
                output?.Write(bytes);
                size += bytes.Length;
                index++;
            }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }
        if (index != total || size != TelefonProtocolContract.Integer(descriptor["size"]) ||
            Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != hash)
            throw new InvalidDataException("The original does not match its declared size and hash.");
    }
}

internal sealed record ScopedOriginalWindow(PersonalSyncStagedBatch Batch, JsonObject Request, JsonObject Reference, string Authority,
    JsonObject Descriptor, int Start, int End, int Total, JsonObject Frame)
{
    internal string Id => Frame["message_id"]!.GetValue<string>();
    internal string Hash => Descriptor["sha256"]!.GetValue<string>();
    internal long ExpiresMs => TelefonProtocolContract.Integer(Frame["expires_ms"]);
}
