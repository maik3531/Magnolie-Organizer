using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneContactGroupTests
{
    private static JsonObject Request(string action = "prepare", string? token = null) => action == "prepare" ? new()
    { ["version"] = PhoneContactRead.GroupWriteVersion, ["request_id"] = Guid.NewGuid().ToString("D"), ["action"] = action, ["uid"] = "lookup:fixture" } : new()
    { ["version"] = PhoneContactRead.GroupWriteVersion, ["request_id"] = Guid.NewGuid().ToString("D"), ["action"] = action, ["uid"] = "lookup:fixture",
        ["token"] = token ?? Guid.NewGuid().ToString("D"), ["groups"] = new JsonArray("Work", "Own group") };
    private static JsonObject Account() => new() { ["name"] = "fixture@example.test", ["type"] = "com.google", ["data_set"] = "" };
    private static JsonObject Report(JsonObject request, string token) => new()
    {
        ["version"] = PhoneContactRead.GroupWriteVersion, ["request_id"] = request["request_id"]!.DeepClone(), ["action"] = request["action"]!.DeepClone(),
        ["uid"] = request["uid"]!.DeepClone(), ["token"] = token,
        ["state"] = request["action"]!.GetValue<string>() == "prepare" ? "prepared" : "saved",
        ["groups"] = request["action"]!.GetValue<string>() == "prepare" ? new JsonArray("Coworkers") : request["groups"]!.DeepClone(),
        ["catalog"] = request["action"]!.GetValue<string>() == "prepare" ? new JsonArray("Coworkers", "Work") : new JsonArray(),
        ["account"] = Account()
    };
    private static JsonObject Envelope(JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["kind"] = "device_status.report", ["message_id"] = Guid.NewGuid().ToString("D"),
            ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body };
    }

    internal static async Task RunAsync()
    {
        var request = Request(); PhoneContactRead.ValidateGroupRequest(request); TelefonDeviceStatusContract.ValidateRequest(request);
        var probe = new JsonObject { ["version"] = PhoneContactRead.GroupProbeVersion, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "diagnostics", ["uid"] = "native-lookup" };
        PhoneContactRead.ValidateGroupProbeRequest(probe); TelefonDeviceStatusContract.ValidateRequest(probe);
        var probeReport = new JsonObject(probe.Select(pair => KeyValuePair.Create(pair.Key, pair.Value?.DeepClone())))
        { ["state"] = "failed", ["stage"] = "groups", ["error_type"] = "IllegalArgumentException", ["reason"] = "contact_groups_unknown",
            ["raw_count"] = 1, ["version_count"] = 1, ["account_count"] = 1, ["mime_supported"] = false, ["reader_complete"] = true };
        PhoneContactRead.ValidateGroupProbeReport(probeReport); TelefonDeviceStatusContract.ValidateReport(probeReport);
        foreach (var change in new[] { "account", "count", "private_error", "available" })
        {
            var invalid = probeReport.DeepClone().AsObject();
            if (change == "account") invalid["account"] = Account();
            if (change == "count") invalid["raw_count"] = true;
            if (change == "private_error") invalid["error_type"] = "Exception: private account";
            if (change == "available") invalid["state"] = "available";
            TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateGroupProbeReport(invalid), "Invalid/private diagnostic passed: " + change);
        }
        var writeProbe = probe.DeepClone().AsObject(); writeProbe["groups"] = new JsonArray("Work");
        TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateGroupProbeRequest(writeProbe), "Debug probe accepted contact mutation fields.");
        var oldRequest = Request(); oldRequest["version"] = 16;
        TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateGroupRequest(oldRequest), "Old account-less write schema was accepted.");
        var oldReport = Report(request, Guid.NewGuid().ToString("D")); oldReport["version"] = 16;
        TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateGroupReport(oldReport), "Old account-less report schema was accepted.");
        var missingAccount = Report(request, Guid.NewGuid().ToString("D")); missingAccount.Remove("account");
        TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateGroupReport(missingAccount), "Account-less report was accepted.");
        TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateRequest(request), "Read-only contacts accepted a group write resource.");
        foreach (var bad in new[] { Request("apply"), Request("apply"), Request("apply") }.Select((value, index) => {
            if (index == 0) value["token"] = "invalid";
            if (index == 1) value["groups"] = new JsonArray("Work", " work ");
            if (index == 2) value["groups"] = new JsonArray(true);
            return value;
        })) TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateGroupRequest(bad), "Malformed group intent was accepted.");
        await BoundRoundTripAsync();
    }

    internal static async Task TransportRoundTripAsync(TelefonCoordinator coordinator, TelefonPeer peer, string uid, CancellationToken cancellation)
    {
        var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
        JsonObject Body(string action = "prepare", string? token = null)
        { var body = Request(action, token); body["uid"] = uid; return body; }
        var prepared = await coordinator.ContactGroupsAsync(peer.Id, fingerprint, Body(), cancellation);
        TestAssert.That(prepared["groups"]!.ToJsonString() == new JsonArray("Coworkers").ToJsonString(), "Native initial memberships differ.");
        TestAssert.That(prepared["account"]!["name"]!.GetValue<string>() == "fixture@example.test" &&
            prepared["account"]!["type"]!.GetValue<string>() == "synthetic-provider", "Native account identity was lost.");
        var apply = Body("apply", prepared["token"]!.GetValue<string>());
        apply["groups"] = new JsonArray("Own group", "Work");
        var saved = await coordinator.ContactGroupsAsync(peer.Id, fingerprint, apply, cancellation);
        TestAssert.That(saved["state"]!.GetValue<string>() == "saved" && JsonNode.DeepEquals(saved["groups"], apply["groups"]), "Actual native write readback differs.");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactGroupsAsync(peer.Id, fingerprint, apply, cancellation),
            "A consumed transport preparation was reused.");
        var fresh = await coordinator.ContactGroupsAsync(peer.Id, fingerprint, Body(), cancellation);
        TestAssert.That(JsonNode.DeepEquals(fresh["groups"], apply["groups"]), "A fresh provider snapshot resurrected old memberships.");
        var clear = Body("apply", fresh["token"]!.GetValue<string>()); clear["groups"] = new JsonArray();
        var cleared = await coordinator.ContactGroupsAsync(peer.Id, fingerprint, clear, cancellation);
        TestAssert.That(cleared["state"]!.GetValue<string>() == "saved" && cleared["groups"]!.AsArray().Count == 0, "Native membership clear was not read back.");
        Console.WriteLine("C# Notes live native group write/readback passed.");
    }

    internal static async Task TransportProbeAsync(TelefonCoordinator coordinator, TelefonPeer peer, string uid, CancellationToken cancellation)
    {
        var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
        var request = new JsonObject { ["version"] = PhoneContactRead.GroupProbeVersion, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "diagnostics", ["uid"] = uid };
        var result = await coordinator.ContactGroupsAsync(peer.Id, fingerprint, request, cancellation);
        TestAssert.That(result["state"]!.GetValue<string>() == "available" && result["stage"]!.GetValue<string>() == "complete" &&
            result["reader_complete"]!.GetValue<bool>() && result["raw_count"]!.GetValue<int>() == 2 && result["account_count"]!.GetValue<int>() == 2,
            "Real native diagnostic result was lost or changed.");
        TestAssert.That(!result.ContainsKey("account") && !result.ContainsKey("groups") && !result.ContainsKey("token"),
            "A diagnostic exposed group/account data or a write ticket.");
        Console.WriteLine("C# Notes read-only native contact-group diagnostic passed.");
    }

    private static async Task BoundRoundTripAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "phone-groups-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var peer = new TelefonPeer("22222222-2222-4222-8222-222222222222", "Fixture", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            JsonObject? nativeStatus = null;
            using var coordinator = new TelefonCoordinator(paths, (name, value) => {
                if (name == "App.telefonVerbindungStand") nativeStatus = JsonSerializer.SerializeToNode(value)!.AsObject();
                return Task.CompletedTask;
            }, dataStore: store);
            var accept = typeof(TelefonCoordinator).GetMethod("AcceptContactGroupRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using var stream = new MemoryStream();
            using var connection = new TelefonConnection(peer, stream, new byte[32], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi")
            { ContactGroupReportReceived = (source, value) => (TelefonAck)accept.Invoke(coordinator, [source, peer, value])! };
            using var otherStream = new MemoryStream();
            using var other = new TelefonConnection(peer, otherStream, new byte[32], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi")
            { ContactGroupReportReceived = (source, value) => (TelefonAck)accept.Invoke(coordinator, [source, peer, value])! };
            foreach (var value in new[] { connection, other }) foreach (var field in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" })
                typeof(TelefonConnection).GetField(field, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(value, true);
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            TestAssert.That(coordinator.ContactGroupsAvailable(peer.Id), "Fresh own-peer write capability was not available.");
            await coordinator.ReportStatusAsync();
            var guiPeer = new JsonObject(PhoneContactRead.GuiAvailability(nativeStatus!["telefone"]!.AsArray().Single()!.AsObject()));
            TestAssert.That(guiPeer["contacts_read_available"]!.GetValue<bool>() && guiPeer["contact_groups_write_available"]!.GetValue<bool>(),
                "The real native contact availability was lost on its GUI projection.");
            var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
            var prepare = Request(); var token = Guid.NewGuid().ToString("D");
            var pending = coordinator.ContactGroupsAsync(peer.Id, fingerprint, prepare, CancellationToken.None);
            await other.HandlePlainAsync(Envelope(Report(prepare, token)));
            TestAssert.That(!pending.IsCompleted, "A replacement source connection satisfied the group preparation.");
            await connection.HandlePlainAsync(Envelope(Report(prepare, token)));
            var prepared = await pending.WaitAsync(TimeSpan.FromSeconds(2));
            TestAssert.That(prepared["state"]!.GetValue<string>() == "prepared", "Preparation claimed a save.");
            var apply = Request("apply", token); var saved = coordinator.ContactGroupsAsync(peer.Id, fingerprint, apply, CancellationToken.None);
            var wrong = Report(apply, token); wrong["groups"] = new JsonArray("Coworkers");
            await connection.HandlePlainAsync(Envelope(wrong));
            TestAssert.That(!saved.IsCompleted, "A report with the previous groups claimed successful storage.");
            var foreignAccount = Report(apply, token); foreignAccount["account"]!["name"] = "other@example.test";
            await connection.HandlePlainAsync(Envelope(foreignAccount));
            TestAssert.That(!saved.IsCompleted, "A report from a different account claimed successful storage.");
            await connection.HandlePlainAsync(Envelope(Report(apply, token)));
            TestAssert.That((await saved.WaitAsync(TimeSpan.FromSeconds(2)))["state"]!.GetValue<string>() == "saved", "Saved readback was lost.");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactGroupsAsync(peer.Id, fingerprint, Request("apply", token), CancellationToken.None),
                "A consumed preparation token was reused.");
            TestAssert.That(store.LoadStatus(peer.Id) is null, "Contact groups/account leaked into ordinary device-status history.");
            online.Remove(peer.Id);
            await coordinator.ReportStatusAsync();
            guiPeer = new JsonObject(PhoneContactRead.GuiAvailability(nativeStatus!["telefone"]!.AsArray().Single()!.AsObject()));
            TestAssert.That(!guiPeer["contacts_read_available"]!.GetValue<bool>() && !guiPeer["contact_groups_write_available"]!.GetValue<bool>(),
                "An offline phone retained contact access in the shared GUI projection.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }
}
