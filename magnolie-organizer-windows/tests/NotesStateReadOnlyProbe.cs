using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using System.Reflection;
using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Existing preference vectors and envelope counters only, never note/report content.
internal static class NotesStateReadOnlyProbe
{
    internal static async Task<int> RunAsync(string receipt, string? batchCopy = null)
    {
        if (!OperatingSystem.IsWindows() || File.Exists(receipt)) throw new InvalidOperationException("New Windows diagnostic receipt required.");
        if (batchCopy is not null && (File.Exists(batchCopy) || Path.GetDirectoryName(Path.GetFullPath(batchCopy)) != Path.GetDirectoryName(Path.GetFullPath(receipt))))
            throw new InvalidOperationException("New adjacent private copy required.");
        var paths = new WindowsPaths(); var store = new TelefonStore(paths); var peer = store.LoadPeers().Single();
        var shared = store.SharedSettings(peer.Id, peer.PublicKey);
        var output = new JsonObject { ["writes"] = false, ["peerId"] = peer.Id, ["state"] = peer.State,
            ["localGrants"] = store.LocalGrants(), ["remoteGrants"] = peer.Grants.DeepClone(), ["sharedCurrent"] = shared,
            ["recentShared"] = store.LoadRecent(peer.Id, SharedSyncSettings.Kind, 8),
            ["recentRequests"] = store.LoadRecent(peer.Id, "personal_sync.request", 8) };
        var database = Path.Combine(paths.Root, "Telefon", "phone.db");
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        connection.Open(); var counters = new JsonArray();
        var incoming = new JsonArray();
        using (var query = connection.CreateCommand()) {
            query.CommandText = "SELECT message_id,payload,state FROM inbox WHERE peer_id=$peer AND kind=$kind ORDER BY received_ms DESC LIMIT 8";
            query.Parameters.AddWithValue("$peer", peer.Id); query.Parameters.AddWithValue("$kind", SharedSyncSettings.Kind);
            var open = typeof(TelefonStore).GetMethod("Open", BindingFlags.NonPublic | BindingFlags.Instance)!;
            var identity = store.LoadOrCreateIdentity(); var actor = identity.Id; CryptographicOperations.ZeroMemory(identity.PrivateKey);
            using var rows = query.ExecuteReader(); while (rows.Read()) {
                var clear = (byte[])open.Invoke(store, ["inbox", peer.Id + rows.GetString(0), (byte[])rows[1]])!;
                JsonObject body;
                try { body = JsonNode.Parse(clear)!["body"]!.DeepClone().AsObject(); } finally { CryptographicOperations.ZeroMemory(clear); }
                var item = new JsonObject { ["state"] = rows.GetString(2), ["body"] = body };
                try { _ = SharedSyncSettings.Merge(shared!, body, actor, peer.Id); item["mergeValid"] = true; }
                catch (Exception error) { item["mergeValid"] = false; item["mergeError"] = error.GetType().Name + ":" + error.Message; }
                incoming.Add(item);
            }
        }
        output["incomingSharedControls"] = incoming;
        var batches = new JsonArray();
        var receivedBatches = store.LoadRecent(peer.Id, "personal_sync.batch", 8);
        if (batchCopy is not null)
        {
            var bytes = TelefonCrypto.Canonical(receivedBatches);
            try
            {
                await using var copy = new FileStream(batchCopy, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                await copy.WriteAsync(bytes);
                output["privateBatchCopySha256"] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }
        foreach (var batch in receivedBatches.OfType<JsonObject>())
        {
            var records = new JsonArray();
            foreach (var record in (batch["records"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                var item = new JsonObject();
                foreach (var field in new[] { "kind", "id", "state", "clock", "hash", "modified_ms" })
                    item[field] = record[field]?.DeepClone();
                records.Add(item);
            }
            batches.Add(new JsonObject { ["run_id"] = batch["run_id"]?.DeepClone(), ["format"] = batch["format"]?.DeepClone(),
                ["reply"] = batch["reply"]?.DeepClone(), ["records"] = records });
        }
        output["incomingBatchMetadata"] = batches;
        foreach (var table in new[] { "inbox", "outbox" }) {
            using var query = connection.CreateCommand();
            query.CommandText = table == "inbox" ? "SELECT kind,state,COUNT(*),MAX(received_ms) FROM inbox WHERE peer_id=$peer GROUP BY kind,state" :
                "SELECT kind,last_error,COUNT(*),MAX(created_ms) FROM outbox WHERE peer_id=$peer GROUP BY kind,last_error";
            query.Parameters.AddWithValue("$peer", peer.Id);
            using var rows = query.ExecuteReader(); while (rows.Read()) counters.Add(new JsonObject {
                ["table"] = table, ["kind"] = rows.GetString(0), ["status"] = rows.GetString(1), ["count"] = rows.GetInt64(2), ["lastMs"] = rows.GetInt64(3)
            });
        }
        output["envelopeCounters"] = counters;
        await File.WriteAllTextAsync(receipt, output.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine("Read existing Notes preference/control metadata without synchronization.");
        return 0;
    }
}
