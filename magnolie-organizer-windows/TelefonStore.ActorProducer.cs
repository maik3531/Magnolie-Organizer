using System.Text.Json.Nodes;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Internal native primitive only. Caller holds source/owner gates; neither
    // a wire target list nor a saved Boolean can substitute for these witnesses.
    internal IReadOnlyList<JsonObject> QueueActorDeletionProposals(string peerId, string runId, IReadOnlyList<JsonObject> input,
        string expectedSource, NativeBookSaveState savedBook, Func<string?> currentSource, Func<NativeBookSaveState?> currentSavedBook)
    {
        PersonalSyncActorContract.Start(runId);
        static bool Hex(string value) => value.Length == 64 && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
        if (!TelefonProtocolContract.IsUuidV4(peerId) || !Hex(expectedSource) || savedBook.Sequence <= 0 || !Hex(savedBook.BookSource) || !Hex(savedBook.Sha256))
            throw new InvalidDataException("invalid_native_proposal_group_binding");
        ArgumentNullException.ThrowIfNull(currentSource); ArgumentNullException.ThrowIfNull(currentSavedBook);
        if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
        if (input.Count is < 1 or > 8) throw new InvalidDataException("invalid_native_proposal_group");
        var bodies = input.Select(body => body.DeepClone().AsObject()).ToArray();
        var ids = new List<string>(); var targets = new HashSet<(string Kind, string Id, string Parent)>();
        for (var index = 0; index < bodies.Length; index++)
        {
            var body = bodies[index]; PersonalSyncContract.ValidateBody("personal_sync.deletion_proposals", body);
            var proposals = body["proposals"]!.AsArray();
            if (body["run_id"]!.GetValue<string>() != runId || body["proposal_batch_id"]!.GetValue<string>() != bodies[0]["proposal_batch_id"]!.GetValue<string>() ||
                body["sequence"]!.GetValue<int>() != index || body["last"]!.GetValue<bool>() != (index == bodies.Length - 1) ||
                proposals.Count is < 1 or > 32 || index < bodies.Length - 1 && proposals.Count != 32)
                throw new InvalidDataException("incomplete_native_proposal_group");
            foreach (var proposal in proposals.OfType<JsonObject>())
            {
                ids.Add(proposal["proposal_id"]!.GetValue<string>());
                if (!targets.Add((proposal["kind"]!.GetValue<string>(), proposal["id"]!.GetValue<string>(), proposal["parent_id"]!.GetValue<string>())))
                    throw new InvalidDataException("ambiguous_native_proposal_group");
            }
        }
        if (!ids.SequenceEqual(ids.Distinct(StringComparer.Ordinal).OrderBy(value => value, StringComparer.Ordinal)))
            throw new InvalidDataException("ambiguous_native_proposal_group");
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); const long ttl = 86_400_000;
        var prepared = bodies.Select(body => {
            var semantic = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = "personal_sync.deletion_proposals", ["created_ms"] = now, ["expires_ms"] = now + ttl, ["body"] = body.DeepClone() };
            TelefonMessageContract.ValidateMessage(semantic, now, false);
            var wire = PersonalSyncActorContract.WireMessage(semantic, runId);
            return (Wire: wire, Body: body, Payload: Seal("outbox", wire["message_id"]!.GetValue<string>(), TelefonCrypto.Canonical(wire)));
        }).ToArray();
        var privatePeer = PersonalSyncActorContract.StoragePeer(runId);
        var ledgerKey = $"personal_actor_producer:{privatePeer}:{runId}";
        var identity = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(new JsonObject {
            ["peer_id"] = peerId, ["run_id"] = runId, ["source"] = expectedSource,
            ["saved_book"] = new JsonObject { ["book_source"] = savedBook.BookSource, ["sequence"] = savedBook.Sequence, ["sha256"] = savedBook.Sha256 },
            ["bodies"] = new JsonArray(bodies.Select(body => (JsonNode)body.DeepClone()).ToArray()) }))).ToLowerInvariant();
        void RequireCurrent()
        { if (RestoreFenced || currentSource() != expectedSource || currentSavedBook() != savedBook) throw new InvalidOperationException("actor_producer_source_changed"); }
        lock (gate)
        {
            if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
            using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(); RequireCurrent();
            using (var previous = db.CreateCommand())
            {
                previous.Transaction = transaction; previous.CommandText = "SELECT value FROM meta WHERE key=$key"; previous.Parameters.AddWithValue("$key", ledgerKey);
                if (previous.ExecuteScalar() is byte[] sealedValue)
                {
                    var clear = Open("personal_actor_producer", ledgerKey, sealedValue);
                    try
                    {
                        var recorded = JsonNode.Parse(clear)!.AsObject();
                        TelefonProtocolContract.ExactObject(recorded, "identity", "expires_ms", "frames");
                        if (recorded["identity"]!.GetValue<string>() != identity || TelefonProtocolContract.Integer(recorded["expires_ms"]) <= now ||
                            recorded["frames"] is not JsonArray frames || frames.Count != bodies.Length)
                            throw new InvalidOperationException("actor_producer_group_identity_changed");
                        var frameIds = new HashSet<string>(StringComparer.Ordinal);
                        for (var index = 0; index < frames.Count; index++)
                        {
                            var wire = frames[index]!.AsObject(); var id = wire["message_id"]!.GetValue<string>();
                            if (wire["kind"]!.GetValue<string>() != PersonalSyncActorContract.DataKind || !TelefonProtocolContract.IsUuidV4(id) || !frameIds.Add(id) ||
                                TelefonProtocolContract.Integer(wire["expires_ms"]) != TelefonProtocolContract.Integer(recorded["expires_ms"]) ||
                                !JsonNode.DeepEquals(PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject()).Body, bodies[index]))
                                throw new InvalidDataException("actor_producer_group_frame_changed");
                        }
                        RequireCurrent(); return frames.Select(frame => frame!.DeepClone().AsObject()).ToArray();
                    }
                    finally { CryptographicOperations.ZeroMemory(clear); }
                }
            }
            using (var count = db.CreateCommand())
            {
                count.Transaction = transaction; count.CommandText = "SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_producer:%'";
                if (Convert.ToInt64(count.ExecuteScalar()) >= 32) throw new InvalidOperationException("queue_full");
            }
            using (var size = db.CreateCommand())
            {
                size.Transaction = transaction; size.CommandText = "SELECT COALESCE(SUM(length(payload)),0) FROM outbox";
                if (Convert.ToInt64(size.ExecuteScalar()) + prepared.Sum(item => (long)item.Payload.Length) > OutboxLimitBytes)
                    throw new InvalidOperationException("queue_full");
            }
            foreach (var item in prepared)
            {
                RememberPersonalProposalKinds(db, transaction, privatePeer, item.Body, true, now);
                using var insert = db.CreateCommand(); insert.Transaction = transaction;
                insert.CommandText = "INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES($id,$peer,'personal_sync.deletion_proposals',$now,$expires,$payload,0,$now,'','any')";
                insert.Parameters.AddWithValue("$id", item.Wire["message_id"]!.GetValue<string>()); insert.Parameters.AddWithValue("$peer", peerId);
                insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", now + ttl); insert.Parameters.AddWithValue("$payload", item.Payload); insert.ExecuteNonQuery();
            }
            using (var ledger = db.CreateCommand())
            {
                var recorded = new JsonObject { ["identity"] = identity, ["expires_ms"] = now + ttl,
                    ["frames"] = new JsonArray(prepared.Select(item => (JsonNode)item.Wire.DeepClone()).ToArray()) };
                ledger.Transaction = transaction; ledger.CommandText = "INSERT INTO meta(key,value) VALUES($key,$value)";
                ledger.Parameters.AddWithValue("$key", ledgerKey); ledger.Parameters.AddWithValue("$value", Seal("personal_actor_producer", ledgerKey, TelefonCrypto.Canonical(recorded))); ledger.ExecuteNonQuery();
            }
            RequireCurrent(); transaction.Commit();
        }
        return prepared.Select(item => item.Wire.DeepClone().AsObject()).ToArray();
    }
}
