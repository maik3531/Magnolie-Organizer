using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Native ordinary-saved choices only. Caller holds owner/epoch/TTL/scope
    // gates; the confirmed-claim callback is the original actual SaveACK, not
    // book bytes or a saved Boolean. Preparation grants no transport authority.
    internal IReadOnlyList<JsonObject> QueueActorFixedDecisions(string peerId, string runId, IReadOnlyList<JsonObject> input,
        string expectedSource, NativeBookSaveState savedClaim, Func<string?> currentSource, Func<NativeBookSaveState?> currentConfirmedClaim)
    {
        PersonalSyncActorContract.Start(runId);
        static bool Hex(string value) => value.Length == 64 && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
        if (!TelefonProtocolContract.IsUuidV4(peerId) || !Hex(expectedSource) || savedClaim.Sequence <= 0 || !Hex(savedClaim.BookSource) || !Hex(savedClaim.Sha256) || input.Count is < 1 or > 256)
            throw new InvalidDataException("invalid_native_fixed_decision_binding");
        ArgumentNullException.ThrowIfNull(currentSource); ArgumentNullException.ThrowIfNull(currentConfirmedClaim);
        var choices = input.Select(value => value.DeepClone().AsObject()).ToArray();
        foreach (var chunk in choices.Chunk(32)) PersonalSyncContract.ValidateBody("personal_sync.deletion_decision", new JsonObject {
            ["format"] = 1, ["run_id"] = runId, ["decision_id"] = runId, ["decisions"] = new JsonArray(chunk.Select(value => (JsonNode)value.DeepClone()).ToArray()) });
        var ids = choices.Select(value => value["proposal_id"]!.GetValue<string>()).ToArray();
        if (!ids.SequenceEqual(ids.Distinct(StringComparer.Ordinal).OrderBy(value => value, StringComparer.Ordinal)))
            throw new InvalidDataException("ambiguous_native_fixed_decisions");
        var privatePeer = PersonalSyncActorContract.StoragePeer(runId); var ledgerKey = $"personal_actor_fixed:{privatePeer}:{runId}";
        const long ttl = 86400000; var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        void RequireCurrent()
        { if (RestoreFenced || currentSource() != expectedSource || currentConfirmedClaim() != savedClaim) throw new InvalidOperationException("actor_fixed_decision_source_changed"); }
        lock (gate)
        {
            if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
            using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction(); RequireCurrent();
            var targets = new JsonArray(); var identities = new HashSet<(string Kind, string Parent, string Id)>();
            foreach (var choice in choices)
            {
                var key = $"personal_proposal_kind:{privatePeer}:in:{choice["proposal_id"]!.GetValue<string>()}";
                using var read = db.CreateCommand(); read.Transaction = transaction; read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", key);
                if (read.ExecuteScalar() is not byte[] encrypted) throw new InvalidOperationException("actor_fixed_decision_target_proof_missing");
                var proof = OpenFixedControlObject("personal_proposal_kind", key, encrypted);
                if (TelefonProtocolContract.Integer(proof["expires_ms"]) <= now || !JsonNode.DeepEquals(proof["clock"], choice["expected_clock"]) || proof["target"] is not JsonObject native)
                    throw new InvalidOperationException("actor_fixed_decision_target_proof_missing");
                TelefonProtocolContract.ExactObject(native, "proposal_id", "kind", "id", "parent_id", "prior_hash");
                if (!JsonNode.DeepEquals(native["proposal_id"], choice["proposal_id"]) || !JsonNode.DeepEquals(native["kind"], proof["kind"]) ||
                    native["kind"]!.GetValue<string>() is not ("note" or "task" or "attachment")) throw new InvalidOperationException("actor_fixed_decision_target_proof_changed");
                var target = native.DeepClone().AsObject(); target["clock"] = proof["clock"]!.DeepClone();
                var proposal = target.DeepClone().AsObject(); proposal["deleted_ms"] = 0; proposal["label"] = "";
                PersonalSyncContract.ValidateBody("personal_sync.deletion_proposals", new JsonObject { ["format"] = 1, ["run_id"] = runId,
                    ["proposal_batch_id"] = runId, ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(proposal) });
                if (!identities.Add((target["kind"]!.GetValue<string>(), target["parent_id"]!.GetValue<string>(), target["id"]!.GetValue<string>())))
                    throw new InvalidDataException("ambiguous_native_fixed_targets");
                targets.Add(target);
            }
            var identity = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(new JsonObject { ["peer_id"] = peerId, ["run_id"] = runId,
                ["source"] = expectedSource, ["saved_claim"] = new JsonObject { ["book_source"] = savedClaim.BookSource, ["sequence"] = savedClaim.Sequence, ["sha256"] = savedClaim.Sha256 },
                ["choices"] = new JsonArray(choices.Select(value => (JsonNode)value.DeepClone()).ToArray()), ["targets"] = targets }))).ToLowerInvariant();
            using (var previous = db.CreateCommand())
            {
                previous.Transaction = transaction; previous.CommandText = "SELECT value FROM meta WHERE key=$key"; previous.Parameters.AddWithValue("$key", ledgerKey);
                if (previous.ExecuteScalar() is byte[] encrypted)
                {
                    var recorded = OpenFixedControlObject("personal_actor_fixed", ledgerKey, encrypted);
                    TelefonProtocolContract.ExactObject(recorded, "identity", "expires_ms", "frames");
                    var expiry = TelefonProtocolContract.Integer(recorded["expires_ms"]);
                    if (recorded["identity"]!.GetValue<string>() != identity || expiry <= now || recorded["frames"] is not JsonArray frames || frames.Count != (choices.Length + 31) / 32)
                        throw new InvalidOperationException("actor_fixed_decision_group_identity_changed");
                    var frameIds = new HashSet<string>(StringComparer.Ordinal);
                    for (var index = 0; index < frames.Count; index++)
                    {
                        var wire = frames[index]!.AsObject(); TelefonProtocolContract.ExactObject(wire, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
                        var id = wire["message_id"]!.GetValue<string>();
                        if (wire["type"]!.GetValue<string>() != "message" || TelefonProtocolContract.Integer(wire["v"]) != 1 ||
                            TelefonProtocolContract.Integer(wire["created_ms"]) != expiry - ttl || TelefonProtocolContract.Integer(wire["expires_ms"]) != expiry ||
                            wire["kind"]!.GetValue<string>() != PersonalSyncActorContract.DataKind || !TelefonProtocolContract.IsUuidV4(id) || !frameIds.Add(id))
                            throw new InvalidDataException("actor_fixed_decision_group_frame_changed");
                        var semantic = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
                        if (semantic.Kind != "personal_sync.deletion_decision" || semantic.Body["run_id"]!.GetValue<string>() != runId ||
                            !JsonNode.DeepEquals(semantic.Body["decisions"], new JsonArray(choices.Skip(index * 32).Take(32).Select(value => (JsonNode)value.DeepClone()).ToArray())))
                            throw new InvalidDataException("actor_fixed_decision_group_frame_changed");
                    }
                    RequireCurrent(); return frames.Select(value => value!.DeepClone().AsObject()).ToArray(); // Never requeue a prior ACKed original.
                }
            }
            using (var count = db.CreateCommand())
            {
                count.Transaction = transaction; count.CommandText = "SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_fixed:%'";
                if (Convert.ToInt64(count.ExecuteScalar()) >= 32) throw new InvalidOperationException("queue_full");
            }
            var prepared = choices.Chunk(32).Select(chunk => {
                var body = new JsonObject { ["format"] = 1, ["run_id"] = runId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(chunk.Select(value => (JsonNode)value.DeepClone()).ToArray()) };
                var wire = PersonalSyncActorContract.WireMessage(new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                    ["kind"] = "personal_sync.deletion_decision", ["created_ms"] = now, ["expires_ms"] = now + ttl, ["body"] = body }, runId);
                return (Wire: wire, Payload: Seal("outbox", wire["message_id"]!.GetValue<string>(), TelefonCrypto.Canonical(wire)));
            }).ToArray();
            using (var size = db.CreateCommand())
            {
                size.Transaction = transaction; size.CommandText = "SELECT COALESCE(SUM(length(payload)),0) FROM outbox";
                if (Convert.ToInt64(size.ExecuteScalar()) + prepared.Sum(value => (long)value.Payload.Length) > OutboxLimitBytes) throw new InvalidOperationException("queue_full");
            }
            foreach (var item in prepared)
            {
                using var insert = db.CreateCommand(); insert.Transaction = transaction;
                insert.CommandText = "INSERT INTO outbox(message_id,peer_id,kind,created_ms,expires_ms,payload,attempts,next_attempt_ms,last_error,transport_policy) VALUES($id,$peer,'personal_sync.deletion_decision',$now,$expires,$payload,0,$now,'','any')";
                insert.Parameters.AddWithValue("$id", item.Wire["message_id"]!.GetValue<string>()); insert.Parameters.AddWithValue("$peer", peerId);
                insert.Parameters.AddWithValue("$now", now); insert.Parameters.AddWithValue("$expires", now + ttl); insert.Parameters.AddWithValue("$payload", item.Payload); insert.ExecuteNonQuery();
            }
            using (var ledger = db.CreateCommand())
            {
                var recorded = new JsonObject { ["identity"] = identity, ["expires_ms"] = now + ttl, ["frames"] = new JsonArray(prepared.Select(value => (JsonNode)value.Wire.DeepClone()).ToArray()) };
                ledger.Transaction = transaction; ledger.CommandText = "INSERT INTO meta(key,value) VALUES($key,$value)";
                ledger.Parameters.AddWithValue("$key", ledgerKey); ledger.Parameters.AddWithValue("$value", Seal("personal_actor_fixed", ledgerKey, TelefonCrypto.Canonical(recorded))); ledger.ExecuteNonQuery();
            }
            RequireCurrent(); transaction.Commit(); return prepared.Select(value => value.Wire.DeepClone().AsObject()).ToArray();
        }
    }

    private JsonObject OpenFixedControlObject(string category, string key, byte[] encrypted)
    {
        var clear = Open(category, key, encrypted);
        try { return JsonNode.Parse(clear)!.AsObject(); }
        finally { CryptographicOperations.ZeroMemory(clear); }
    }

    internal void PurgeActorFixedControls(SqliteConnection db, SqliteTransaction transaction, string privatePeer)
    {
        var rows = new List<(string Key, byte[] Payload)>();
        using (var read = db.CreateCommand())
        {
            read.Transaction = transaction; read.CommandText = "SELECT key,value FROM meta WHERE key LIKE $prefix"; read.Parameters.AddWithValue("$prefix", $"personal_actor_fixed:{privatePeer}:%");
            using var reader = read.ExecuteReader(); while (reader.Read()) rows.Add((reader.GetString(0), (byte[])reader[1]));
        }
        foreach (var row in rows)
        {
            var recorded = OpenFixedControlObject("personal_actor_fixed", row.Key, row.Payload);
            foreach (var wire in recorded["frames"]!.AsArray().OfType<JsonObject>())
            {
                var semantic = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
                if (semantic.Kind != "personal_sync.deletion_decision" || PersonalSyncActorContract.StoragePeer(semantic.Body["run_id"]!.GetValue<string>()) != privatePeer)
                    throw new InvalidDataException("actor_fixed_decision_cleanup_namespace_changed");
                var id = wire["message_id"]!.GetValue<string>();
                using (var read = db.CreateCommand())
                {
                    read.Transaction = transaction; read.CommandText = "SELECT kind,payload FROM outbox WHERE message_id=$id"; read.Parameters.AddWithValue("$id", id);
                    using var reader = read.ExecuteReader(); if (!reader.Read()) continue;
                    if (reader.GetString(0) != semantic.Kind || !JsonNode.DeepEquals(OpenFixedControlObject("outbox", id, (byte[])reader[1]), wire))
                        throw new InvalidDataException("actor_fixed_decision_cleanup_frame_changed");
                }
                using var remove = db.CreateCommand(); remove.Transaction = transaction; remove.CommandText = "DELETE FROM outbox WHERE message_id=$id AND kind='personal_sync.deletion_decision'";
                remove.Parameters.AddWithValue("$id", id); remove.ExecuteNonQuery();
            }
        }
    }
}
