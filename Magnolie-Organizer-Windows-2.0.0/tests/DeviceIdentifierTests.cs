using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceIdentifierTests
{
    internal static void Run(JsonObject ordinary)
    {
        var body = ordinary.DeepClone().AsObject(); body["version"] = 4;
        body["identifiers"] = new JsonObject {
            ["phone_number"] = new JsonObject { ["status"] = "permission_missing", ["value"] = "" },
            ["serial"] = new JsonObject { ["status"] = "os_restricted", ["value"] = "" },
            ["imei"] = new JsonObject { ["status"] = "available", ["value"] = "000000000000001" } };
        TelefonDeviceStatusContract.ValidateReport(body);
        var request = TelefonCoordinator.DeviceStatusRequest(body["request_id"]!.GetValue<string>(), new JsonArray(1, 2, 3, 4), true);
        TestAssert.That(request.Count == 3 && request["include_identifiers"]!.GetValue<bool>(), "Explicit v4 request missing.");
        var invalid = body.DeepClone().AsObject(); invalid["identifiers"]!["imei"]!["value"] = 1;
        TestAssert.Throws<InvalidDataException>(() => TelefonDeviceStatusContract.ValidateReport(invalid), "IMEI must remain a string.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-identifiers-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); paths.EnsureDirectories(); var store = new TelefonStore(paths, new byte[32]);
            var peer = new TelefonPeer("11111111-1111-4111-8111-111111111111", "Fixture", new byte[32],
                StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers(new[] { peer });
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            TestAssert.That(!store.SendIdentifierRequest(peer, request, now, () => { }), "Ownership was bypassed.");
            store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            TestAssert.That(!store.AcceptIdentifiers(peer, body, now, now + 60_000), "Unsolicited identifiers accepted.");
            TestAssert.That(store.SendIdentifierRequest(peer, request, now, () => { }), "Own-device request blocked.");
            TestAssert.That(store.AcceptIdentifiers(peer, body, now, now + 60_000), "Matching identifiers rejected.");
            TestAssert.That(!store.AcceptIdentifiers(peer, body, now, now + 60_000), "Replayed identifiers accepted.");
            store.SaveStatus(peer.Id, body);
            TestAssert.That(!store.LoadStatus(peer.Id)!.ContainsKey("identifiers") && !File.ReadAllText(paths.TelefonStatusCache).Contains("000000000000001"), "Plaintext status cache leaked identifiers.");
            TestAssert.Throws<InvalidDataException>(() => store.Enqueue(peer.Id, "device_status.report", body, 60_000, now), "Identifiers entered durable queue.");
            var incoming = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = "device_status.report", ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body.DeepClone() };
            var ack = store.CommitIncoming(peer.Id, incoming, now, (_, _) => null); store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
            TestAssert.That(!store.LoadRecent(peer.Id, "device_status.report").Single()!.AsObject().ContainsKey("identifiers"), "Durable inbox retained identifiers.");
            var falseRequest = request.DeepClone().AsObject(); falseRequest["include_identifiers"] = false;
            store.SendIdentifierRequest(peer, falseRequest, now, () => { });
            TestAssert.That(!store.AcceptIdentifiers(peer, body, now, now + 60_000), "False request accepted identifiers.");
            store.SendIdentifierRequest(peer, request, now, () => { });
            var changedPeer = peer with { PublicKey = Enumerable.Repeat((byte)1, 32).ToArray() };
            TestAssert.That(!store.AcceptIdentifiers(changedPeer, body, now, now + 60_000), "Changed peer key accepted identifiers.");
            store.SendIdentifierRequest(peer, request, now, () => { }); store.SetPersonalSettings(peer.Id, ownDevice: false);
            store.SetPersonalSettings(peer.Id, ownDevice: true);
            TestAssert.That(!store.AcceptIdentifiers(peer, body, now, now + 60_000), "Revoked request revived.");
            store.SendIdentifierRequest(peer, request, now, () => { });
            TestAssert.That(!store.AcceptIdentifiers(peer, body, now + 60_001, now + 120_000), "Expired request accepted.");
            store.SendIdentifierRequest(peer, request, now, () => { }); store.RemovePeer(peer.Id);
            TestAssert.That(!store.AcceptIdentifiers(peer, body, now, now + 60_000), "Unpaired identifiers accepted.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
