using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    private (string Key, string Actor) SharedSettingsBinding(string peerId, byte[] expectedPublic)
    {
        var peer = LoadPeers().SingleOrDefault(value => value.Id == peerId && value.State == "paired");
        if (peer is null || expectedPublic.Length != 32 || !CryptographicOperations.FixedTimeEquals(peer.PublicKey, expectedPublic))
            throw new InvalidOperationException("shared_settings_peer_changed");
        var identity = LoadOrCreateIdentity();
        try { return ($"personal_shared_settings:{peerId}:{Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant()}:consent", identity.Id); }
        finally { CryptographicOperations.ZeroMemory(identity.PrivateKey); }
    }

    internal JsonObject? SharedSettings(string peerId, byte[] expectedPublic)
    {
        lock (gate)
        {
            var (key, actor) = SharedSettingsBinding(peerId, expectedPublic);
            using var db = OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", key);
            if (read.ExecuteScalar() is not byte[] sealedValue) return null;
            var value = JsonNode.Parse(Open("shared_settings", key, sealedValue))!.AsObject();
            // Validate both identities without altering state or granting anything.
            SharedSyncSettings.Merge(value, value, actor, peerId);
            return value;
        }
    }

    private JsonObject UpdateSharedSettings(string peerId, byte[] expectedPublic, Func<JsonObject, string, JsonObject> apply, JsonObject? initial)
    {
        lock (gate)
        {
            if (RestoreFenced) throw new InvalidOperationException("restore_unavailable");
            var (key, actor) = SharedSettingsBinding(peerId, expectedPublic);
            using var db = OpenDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            JsonObject previous;
            using (var read = db.CreateCommand())
            {
                read.Transaction = transaction; read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", key);
                previous = read.ExecuteScalar() is byte[] value ? JsonNode.Parse(Open("shared_settings", key, value))!.AsObject() : SharedSyncSettings.Create(actor, initial);
            }
            var next = apply(previous, actor);
            SharedSyncSettings.Merge(next, next, actor, peerId);
            if (SharedSettingsBinding(peerId, expectedPublic).Key != key) throw new InvalidOperationException("shared_settings_peer_changed");
            using var save = db.CreateCommand(); save.Transaction = transaction;
            save.CommandText = "INSERT OR REPLACE INTO meta(key,value) VALUES($key,$value)";
            save.Parameters.AddWithValue("$key", key); save.Parameters.AddWithValue("$value", Seal("shared_settings", key, TelefonCrypto.Canonical(next)));
            save.ExecuteNonQuery(); transaction.Commit();
            return next;
        }
    }

    internal JsonObject ChangeSharedSetting(string peerId, byte[] expectedPublic, string field, JsonNode value, JsonObject? initial = null) =>
        UpdateSharedSettings(peerId, expectedPublic, (body, actor) => SharedSyncSettings.Change(body, actor, peerId, field, value), initial);

    internal JsonObject MergeSharedSettings(string peerId, byte[] expectedPublic, JsonObject incoming, JsonObject? initial = null) =>
        UpdateSharedSettings(peerId, expectedPublic, (body, actor) => SharedSyncSettings.Merge(body, incoming, actor, peerId), initial);
}
