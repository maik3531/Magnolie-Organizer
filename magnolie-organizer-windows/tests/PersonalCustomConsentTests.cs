using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalCustomConsentTests
{
    internal static void Run()
    {
        const string marker = "contracts/personal-custom-consent-v4-vectors.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(marker), marker)))!.AsObject();
        var source = vectors["source_id"]!.GetValue<string>();
        foreach (var raw in vectors["identities"]!.AsArray())
        {
            var item = raw!["item_id"]!.GetValue<string>(); var expected = raw["id"]!.GetValue<string>();
            TestAssert.That(PersonalSyncContract.CustomSourceId(source, item) == expected, "Custom identity vector mismatch.");
            TestAssert.That(PersonalSyncContract.CustomSourceId(vectors["other_source_id"]!.GetValue<string>(), item) != expected, "Custom source collision.");
        }
        TestAssert.That(PersonalSyncContract.CustomSourceId(source, new string('a', 640)) == vectors["long_identity"]!["id"]!.GetValue<string>(), "Long identity mismatch.");
        TestAssert.That(PersonalSyncContract.CustomSourceId(source, string.Concat(Enumerable.Repeat("\U0001f331", 160))) ==
            vectors["unicode_identity"]!["id"]!.GetValue<string>(), "Unicode identity mismatch.");
        foreach (var id in new[] { "", new string('a', 641), "\ud800", "a\0b", "a\nb", "a\u007fb" })
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.CustomSourceId(source, id), "Invalid identity accepted.");
        var local = vectors["local"]!.AsObject(); var remote = vectors["remote"]!.AsObject();
        foreach (var invalid in vectors["invalid_settings"]!.AsArray())
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateCustomSettings(invalid!.AsObject()), "Invalid custom settings accepted.");
        var versions = new[] { 1, 2, 3, 4 };
        bool Allowed(JsonObject? l, JsonObject? r, int[] lv, int[] rv, bool own = true, bool otherOwn = true) =>
            PersonalSyncContract.CustomScopeAllowed(l, r, lv, rv, own, otherOwn, remote["epoch"]!.GetValue<string>(), local["epoch"]!.GetValue<string>(), 1, 1);
        TestAssert.That(Allowed(local, remote, versions, versions), "Bilateral scope unexpectedly denied.");
        TestAssert.That(!Allowed(null, remote, versions, versions) && !Allowed(local, null, versions, versions) &&
            !Allowed(local, remote, [1, 2, 3], versions) && !Allowed(local, remote, versions, [1, 2, 3]) &&
            !Allowed(local, remote, versions, versions, false) && !Allowed(local, remote, versions, versions, true, false) &&
            !Allowed(local, vectors["revoked"]!.AsObject(), versions, versions) &&
            !Allowed(local, vectors["reenabled"]!.AsObject(), versions, versions), "Missing consent or stale fence accepted.");
        var reusedEpoch = remote.DeepClone().AsObject(); reusedEpoch["revision"] = 3;
        TestAssert.That(!Allowed(local, reusedEpoch, versions, versions), "Older run revived by epoch reuse.");
        JsonObject? current = null;
        foreach (var key in new[] { "remote", "remote", "revoked", "reenabled" })
            current = JsonNode.Parse(PersonalSyncContract.AcceptCustomSettings(current, vectors[key]!.AsObject()).ToJsonString())!.AsObject();
        foreach (var key in new[] { "remote", "revoked" })
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.AcceptCustomSettings(current, vectors[key]!.AsObject()), "Settings rollback accepted.");
        var changed = current!.DeepClone().AsObject(); changed["enabled"] = false;
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.AcceptCustomSettings(current, changed), "Equivocation accepted.");
        changed = current.DeepClone().AsObject(); changed["revision"] = 4;
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.AcceptCustomSettings(current, changed), "Epoch reuse accepted.");
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.settings", local), "Legacy settings widened.");
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateBody("personal_sync.custom_settings", local), "Incomplete scope activated.");
        var wire = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(marker), "contracts/personal-custom-v4-vectors.json")))!.AsObject();
        foreach (var name in new[] { "batch", "deletion" }) PersonalSyncContract.ValidateCustomBody("personal_sync.custom_batch", wire[name]!.AsObject());
        TestAssert.That(System.Text.Encoding.UTF8.GetString(TelefonCrypto.Canonical(JsonNode.Parse("{\"n\":-0,\"ordinal\":-1}")!)) == "{\"n\":0,\"ordinal\":-1}", "Parsed negative zero was not canonicalized.");
        TestAssert.That(System.Text.Encoding.UTF8.GetString(TelefonCrypto.Canonical(wire["batch"]!)) == wire["canonical"]!.GetValue<string>(), "Legacy golden canonical bytes changed.");
        foreach (var raw in new[] { "\"\\ud800\"", "{\"\\udfff\":1}", "0.5", "1e0" }) {
            var rejected = false;
            try { TelefonCrypto.Canonical(JsonNode.Parse(raw)!); } catch (Exception) { rejected = true; }
            TestAssert.That(rejected, "Invalid parsed canonical edge accepted: " + raw);
        }
        TestAssert.Throws<System.Text.EncoderFallbackException>(() => TelefonCrypto.Canonical(JsonValue.Create("\ud800")!), "Programmatic surrogate replaced.");
        TestAssert.That(System.Text.Encoding.UTF8.GetString(TelefonCrypto.Canonical(JsonNode.Parse("\"\\ud83d\\ude00\"")!)) == "\"\U0001f600\"", "Valid surrogate pair changed.");
        var invalidUtf8Rejected = false;
        try { TelefonCrypto.Canonical(JsonNode.Parse(new byte[] { 34, 255, 34 })!); } catch (Exception) { invalidUtf8Rejected = true; }
        TestAssert.That(invalidUtf8Rejected, "Malformed UTF-8 was silently replaced.");
        foreach (var zone in new[] { "UTC", "GMT", "Europe/Berlin", "US/Eastern", "Asia/Calcutta", "Etc/GMT+5", "EST", "MST", "HST", "CET", "EET", "MET", "WET", "EST5EDT", "CST6CDT", "MST7MDT", "PST8PDT",
            "W. Europe Standard Time", "+01:00", "GMT+01:00", "UTC+01:00", "Z", "Unknown/Shape", "localtime", "posixrules", "right/Europe/Berlin", "SystemV/EST5", "europe/berlin" }) {
            var body = wire["batch"]!.DeepClone().AsObject(); var record = body["upserts"]![0]!.AsObject();
            record["value"]!["timezone"] = zone; record["hash"] = PersonalSyncContract.ProjectionHash(record["value"]!.AsObject());
            if (Array.IndexOf(new[] { "UTC", "GMT", "Europe/Berlin", "US/Eastern", "Asia/Calcutta", "Etc/GMT+5", "EST", "MST", "HST", "CET", "EET", "MET", "WET", "EST5EDT", "CST6CDT", "MST7MDT", "PST8PDT" }, zone) >= 0)
                try { PersonalSyncContract.ValidateCustomBody("personal_sync.custom_batch", body); }
                catch (Exception error) { throw new InvalidOperationException("IANA alias rejected: " + zone, error); }
            else TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.ValidateCustomBody("personal_sync.custom_batch", body), "Non-IANA zone accepted: " + zone);
        }
        var directory = Path.Combine(Path.GetTempPath(), "personal-custom-consent-" + Guid.NewGuid().ToString("N"));
        try
        {
            var key = Enumerable.Repeat((byte)19, 32).ToArray(); var paths = new WindowsPaths(directory);
            var liveSource = JsonNode.Parse("{\"personalSync\":{\"actor_id\":\"live-source\",\"custom_revision\":100,\"custom_entities\":{}}}")!.AsObject();
            var archivedSource = JsonNode.Parse("{\"personalSync\":{\"actor_id\":\"archived-source\",\"custom_revision\":10,\"custom_entities\":{\"retired\":{}},\"custom_auto_hash\":\"old\"}}")!.AsObject();
            RestoreSyncState.Prepare(archivedSource, live: liveSource);
            TestAssert.That(archivedSource["personalSync"]!["actor_id"]!.GetValue<string>() == "live-source" &&
                archivedSource["personalSync"]!["custom_revision"]!.GetValue<int>() == 100 &&
                archivedSource["personalSync"]!["custom_entities"]!.AsObject().Count == 0 &&
                archivedSource["personalSync"]!["custom_auto_hash"] is null, "Restore rewound source history or reintroduced retired entities.");
            var store = new TelefonStore(paths, key);
            var peer = new TelefonPeer(source, "Synthetic", Enumerable.Repeat((byte)112, 32).ToArray(),
                StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(source, ownDevice: true, remoteOwnDevice: true);
            TestAssert.That(store.CustomSettings(source).Count == 0, "Upgrade silently authorized Custom.");
            store.SetCustomSettings(source, remote, false); store.SetCustomSettings(source, local, true);
            var batch = wire["batch"]!.AsObject();
            var id = store.Enqueue(source, "personal_sync.custom_batch", batch, 60_000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            store.SetCustomSettings(source, local, true);
            TestAssert.That(store.OutboxMessage(source, id) is not null, "Identical settings destroyed a pending batch.");
            store = new TelefonStore(paths, key);
            TestAssert.That(store.CustomAllowed(source, "personal_sync.custom_batch", batch, true), "Durable Custom consent disappeared.");
            var receipts = new List<JsonObject>();
            using (var connection = new TelefonConnection(peer, new MemoryStream(), new byte[16], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi",
                body => { receipts.Add(body.DeepClone().AsObject()); return Task.CompletedTask; })) {
                var receiveAck = typeof(TelefonConnection).GetMethod("HandlePlainAsync", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!;
                void Ack(string messageId, string status, string error) => ((Task)receiveAck.Invoke(connection,
                    [new JsonObject { ["type"] = "ack", ["message_id"] = messageId, ["status"] = status, ["error"] = error }])!).GetAwaiter().GetResult();
                foreach (var status in new[] { "accepted", "duplicate", "rejected" }) {
                    var deletionId = store.Enqueue(source, "personal_sync.custom_batch", wire["deletion"]!.AsObject(), 60_000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    TestAssert.That(receipts.Count == 0, "Queueing fabricated a receipt.");
                    Ack(deletionId, "rejected", "temporary_failure");
                    TestAssert.That(receipts.Count == 0 && store.OutboxMessage(source, deletionId) is not null, "Temporary failure retired a deletion.");
                    Ack(deletionId, status, status == "rejected" ? "not_granted" : "none");
                    TestAssert.That(receipts.Count == (status == "rejected" ? 0 : 1), "Receiver confirmation was not required.");
                    if (receipts.Count != 0) TestAssert.That(receipts[0].Count == 3 && receipts[0]["upserts"] is null &&
                        JsonNode.DeepEquals(receipts[0]["deletions"], wire["deletion"]!["deletions"]), "Receipt leaked upserts or lost deletion identity.");
                    receipts.Clear(); Ack(deletionId, "duplicate", "none");
                    TestAssert.That(receipts.Count == 0, "Unknown queue identity fabricated a receipt.");
                }
            }
            store.SetCustomSettings(source, vectors["revoked"]!.AsObject(), false);
            TestAssert.That(store.OutboxMessage(source, id) is null && !store.CustomAllowed(source, "personal_sync.custom_batch", batch, true), "Revocation did not cancel the queued batch.");
            store.SetCustomSettings(source, vectors["reenabled"]!.AsObject(), false);
            TestAssert.That(!store.CustomAllowed(source, "personal_sync.custom_batch", batch, true), "Stale batch revived after off/on.");
            var local7 = TelefonStore.NewCustomSettings(false, 7);
            var remote7 = TelefonStore.NewCustomSettings(true, 7);
            store.SetCustomSettings(source, local7, false); store.SetCustomSettings(source, remote7, true);
            store.BeginRestore(); store.CompleteRestore(Guid.NewGuid().ToString());
            store = new TelefonStore(paths, key);
            TestAssert.That(JsonNode.DeepEquals(store.CustomSettings(source)["local"], local7) &&
                JsonNode.DeepEquals(store.CustomSettings(source)["remote"], remote7), "Content restore reset live consent history.");
            var enabled8 = TelefonStore.NewCustomSettings(true, 8);
            store.SetCustomSettings(source, enabled8, false);
            TestAssert.That(JsonNode.DeepEquals(PersonalSyncContract.AcceptCustomSettings(local7, enabled8), enabled8),
                "First post-restore enable cannot converge.");
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncContract.AcceptCustomSettings(enabled8, local7), "Old consent accepted after restore.");
            store.RemovePeer(source); store.SavePeers([peer]);
            TestAssert.That(store.CustomSettings(source).Count == 0, "Re-pair inherited old Custom authorization.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }
}
