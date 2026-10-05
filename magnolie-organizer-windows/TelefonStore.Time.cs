using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    private readonly HashSet<string> failedTimePolicies = new(StringComparer.Ordinal);
    private TelefonPeer TimePeer(string id) => LoadPeers().SingleOrDefault(peer => peer.Id == id && peer.State == "paired")
        ?? throw new InvalidOperationException("Unknown time synchronization peer.");
    private string TimePolicyKey(string id) => "personal_time:" + id + ":" + Convert.ToHexString(TimePeer(id).PublicKey);

    internal bool TimePolicyFailed(string peerId) { lock (gate) return failedTimePolicies.Contains(peerId); }

    internal JsonObject TimeSettings(string peerId, bool allowFailed = false)
    {
        lock (gate)
        {
            if (!allowFailed && failedTimePolicies.Contains(peerId)) throw new InvalidOperationException("Time consent persistence failed.");
            return ReadTimeSettings(peerId);
        }
    }

    private JsonObject ReadTimeSettings(string peerId)
    {
        var key = TimePolicyKey(peerId);
        using var db = OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT value FROM meta WHERE key=$key"; query.Parameters.AddWithValue("$key", key);
        var settings = query.ExecuteScalar() is byte[] value ? JsonNode.Parse(Open("time_policy", key, value))!.AsObject() : new JsonObject();
        foreach (var side in new[] { "local", "remote" }) if (settings[side] is JsonObject policy) TimeSyncContract.ValidateSettings(policy);
        return settings;
    }

    internal void SetTimeSettings(string peerId, JsonObject body, bool remote = false)
    {
        lock (gate)
        {
            TimeSyncContract.ValidateSettings(body);
            if (RestoreFenced && body["enabled"]!.GetValue<bool>()) throw new InvalidOperationException("restore_unavailable");
            var previous = ReadTimeSettings(peerId); var next = previous.DeepClone().AsObject();
            var side = remote ? "remote" : "local";
            next[side] = TimeSyncContract.AcceptSettings(previous[side] as JsonObject, body).DeepClone();
            var key = TimePolicyKey(peerId);
            try
            {
                using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
                using var command = db.CreateCommand(); command.Transaction = transaction;
                command.CommandText = "INSERT OR REPLACE INTO meta(key,value) VALUES($key,$value)";
                command.Parameters.AddWithValue("$key", key); command.Parameters.AddWithValue("$value", Seal("time_policy", key, TelefonCrypto.Canonical(next)));
                command.ExecuteNonQuery();
                if (!JsonNode.DeepEquals(previous, next) || !body["enabled"]!.GetValue<bool>()) PurgeTime(db, transaction, peerId);
                transaction.Commit(); failedTimePolicies.Remove(peerId);
            }
            catch { failedTimePolicies.Add(peerId); throw; }
        }
    }

    private static void PurgeTime(SqliteConnection db, SqliteTransaction transaction, string peerId)
    {
        using var command = db.CreateCommand(); command.Transaction = transaction;
        command.CommandText = "DELETE FROM time_batch WHERE peer_id=$peer; DELETE FROM dedupe WHERE peer_id=$peer AND result='pending' AND message_id IN (SELECT message_id FROM inbox WHERE peer_id=$peer AND kind='personal_sync.time_batch' AND state!='processed'); DELETE FROM inbox WHERE peer_id=$peer AND kind='personal_sync.time_batch' AND state!='processed'; DELETE FROM outbox WHERE peer_id=$peer AND kind IN ('personal_sync.time_request','personal_sync.time_batch')";
        command.Parameters.AddWithValue("$peer", peerId); command.ExecuteNonQuery();
    }

    internal void PauseTime(string peerId)
    {
        lock (gate)
        {
            if (ReadTimeSettings(peerId)["local"] is JsonObject local)
                SetTimeSettings(peerId, TimeSyncContract.NewSettings(false, TelefonProtocolContract.Integer(local["revision"]) + 1));
            using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            PurgeTime(db, transaction, peerId); transaction.Commit();
        }
    }

    internal bool TimeSupported(string peerId)
    {
        var peer = TimePeer(peerId);
        return peer.Capabilities["personal_tasks_sync"]?["available"]?.GetValue<bool>() == true &&
            TelefonProtocolContract.DesktopCapabilities()["items"]?["personal_tasks_sync"]?["versions"] is JsonArray local &&
            local.Any(value => TelefonProtocolContract.Integer(value) == TimeSyncContract.Version) &&
            peer.Capabilities["personal_tasks_sync"]?["versions"] is JsonArray remote &&
            remote.Any(value => TelefonProtocolContract.Integer(value) == TimeSyncContract.Version);
    }

    internal bool TimePolicyAllowed(string peerId, JsonObject body, bool outgoing)
    {
        lock (gate)
        {
            if (RestoreFenced) return false;
            var policy = TimeSettings(peerId); var personal = PersonalSettings(peerId);
            // This is the durable policy check only. The connection also supplies
            // fresh controls and sent/received settings before this can authorize traffic.
            return TimeSyncContract.Allowed(body, policy[outgoing ? "remote" : "local"] as JsonObject,
                policy[outgoing ? "local" : "remote"] as JsonObject, personal.OwnDevice, personal.RemoteOwnDevice,
                true, new[] { 7 }, new[] { 7 });
        }
    }

    internal JsonObject StageTimeBatch(string peerId, JsonObject message, long now)
    {
        TelefonMessageContract.ValidateMessage(message, now, true);
        if (message["kind"]?.GetValue<string>() != TimeSyncContract.Batch) throw new InvalidDataException("Invalid time batch kind.");
        TimeSyncContract.Validate(TimeSyncContract.Batch, message["body"]!.AsObject(), false);
        var id = message["message_id"]!.GetValue<string>(); var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (expires <= now) throw new InvalidDataException("Expired time batch.");
        lock (gate)
        {
            if (!TimePolicyAllowed(peerId, message["body"]!.AsObject(), false)) throw new InvalidOperationException("not_granted");
            var owner = Convert.ToHexString(TimePeer(peerId).PublicKey); var key = peerId + ":" + id;
            using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            using var query = db.CreateCommand(); query.Transaction = transaction;
            query.CommandText = "SELECT payload FROM time_batch WHERE peer_id=$peer AND message_id=$id";
            query.Parameters.AddWithValue("$peer", peerId); query.Parameters.AddWithValue("$id", id);
            JsonObject value;
            if (query.ExecuteScalar() is byte[] encrypted)
            {
                value = JsonNode.Parse(Open("time_batch", key, encrypted))!.AsObject();
                if (value["owner"]?.GetValue<string>() != owner || !JsonNode.DeepEquals(value["message"], message))
                    throw new InvalidDataException("Conflicting time batch identity.");
            }
            else
            {
                using var count = db.CreateCommand(); count.Transaction = transaction;
                count.CommandText = "SELECT COUNT(*) FROM time_batch WHERE peer_id=$peer"; count.Parameters.AddWithValue("$peer", peerId);
                if (Convert.ToInt64(count.ExecuteScalar()) >= 128) throw new InvalidOperationException("Too many pending time batches.");
                value = new JsonObject { ["owner"] = owner, ["message"] = message.DeepClone(), ["token"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)) };
                using var insert = db.CreateCommand(); insert.Transaction = transaction;
                insert.CommandText = "INSERT INTO time_batch VALUES($peer,$id,$expires,$payload)";
                insert.Parameters.AddWithValue("$peer", peerId); insert.Parameters.AddWithValue("$id", id);
                insert.Parameters.AddWithValue("$expires", expires); insert.Parameters.AddWithValue("$payload", Seal("time_batch", key, TelefonCrypto.Canonical(value)));
                insert.ExecuteNonQuery();
            }
            transaction.Commit();
            return new JsonObject { ["device_id"] = peerId, ["body"] = message["body"]!.DeepClone(),
                ["pending_message_id"] = id, ["commit_token"] = value["token"]!.DeepClone() };
        }
    }

    internal bool HasTimeBatch(string peerId, string messageId)
    {
        using var db = OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT 1 FROM time_batch WHERE peer_id=$peer AND message_id=$id";
        query.Parameters.AddWithValue("$peer", peerId); query.Parameters.AddWithValue("$id", messageId);
        return query.ExecuteScalar() is not null;
    }

    internal bool TimeBatchTurn(string peerId, string? messageId = null)
    {
        using var db = OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT message_id FROM outbox WHERE peer_id=$peer AND kind='personal_sync.time_batch' AND expires_ms>$now ORDER BY created_ms,rowid LIMIT 1";
        query.Parameters.AddWithValue("$peer", peerId); query.Parameters.AddWithValue("$now", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        var first = query.ExecuteScalar() as string;
        return messageId is null ? first is null : first == messageId;
    }

    internal void SupersedeWifiTime(string peerId)
    {
        using var db = OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "DELETE FROM outbox WHERE peer_id=$peer AND transport_policy='wifi_only' AND kind IN ('personal_sync.time_batch','personal_sync.time_request')";
        command.Parameters.AddWithValue("$peer", peerId); command.ExecuteNonQuery();
    }

    internal bool CommitTimeBatch(string peerId, string messageId, string token, long now, Func<JsonObject, bool> authorize)
    {
        lock (gate)
        {
            using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            using var query = db.CreateCommand(); query.Transaction = transaction;
            query.CommandText = "SELECT payload FROM time_batch WHERE peer_id=$peer AND message_id=$id AND expires_ms>$now";
            query.Parameters.AddWithValue("$peer", peerId); query.Parameters.AddWithValue("$id", messageId); query.Parameters.AddWithValue("$now", now);
            if (query.ExecuteScalar() is not byte[] encrypted) return false;
            var value = JsonNode.Parse(Open("time_batch", peerId + ":" + messageId, encrypted))!.AsObject();
            var message = value["message"]!.AsObject();
            if (value["token"]?.GetValue<string>() != token || value["owner"]?.GetValue<string>() != Convert.ToHexString(TimePeer(peerId).PublicKey) ||
                TelefonProtocolContract.Integer(message["expires_ms"]) <= now || !TimePolicyAllowed(peerId, message["body"]!.AsObject(), false) || !authorize(message)) return false;
            using var commit = db.CreateCommand(); commit.Transaction = transaction;
            commit.CommandText = "UPDATE inbox SET state='processed' WHERE peer_id=$peer AND message_id=$id; INSERT OR REPLACE INTO dedupe VALUES($id,$peer,'accepted','none',$now); DELETE FROM time_batch WHERE peer_id=$peer AND message_id=$id";
            commit.Parameters.AddWithValue("$peer", peerId); commit.Parameters.AddWithValue("$id", messageId); commit.Parameters.AddWithValue("$now", now);
            commit.ExecuteNonQuery(); transaction.Commit(); return true;
        }
    }
}
