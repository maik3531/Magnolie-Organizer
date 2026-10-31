using System.Text.Json.Nodes;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneContactGroupTitleWriteTests
{
    internal static async Task RunAsync()
    {
        var request = new JsonObject { ["version"] = 20, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "prepare", ["uid"] = "synthetic-lookup", ["old_title"] = "Work", ["new_title"] = "Arbeit" };
        var prepared = request.DeepClone().AsObject();
        prepared["token"] = Guid.NewGuid().ToString("D"); prepared["state"] = "prepared"; prepared["group_id"] = "42";
        prepared["group_identity"] = new string('a', 64);
        prepared["account"] = new JsonObject { ["name"] = "synthetic", ["type"] = "provider", ["data_set"] = "" };
        PhoneContactGroupTitleWrite.ValidateCorrelatedReport(prepared, request);
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var overlong = new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = "device_status.report", ["message_id"] = Guid.NewGuid().ToString("D"),
            ["created_ms"] = now, ["expires_ms"] = now + 60_001, ["body"] = prepared.DeepClone() };
        TestAssert.Throws<TelefonMessageException>(() => TelefonMessageContract.ValidateMessage(overlong, now, true), "A title report exceeded its bounded wire lifetime.");
        overlong["expires_ms"] = now + 60_000;
        TelefonMessageContract.ValidateMessage(overlong, now, true);
        var apply = request.DeepClone().AsObject(); apply["action"] = "apply"; apply["request_id"] = Guid.NewGuid().ToString("D");
        apply["token"] = prepared["token"]!.DeepClone();
        var saved = prepared.DeepClone().AsObject(); saved["action"] = "apply"; saved["state"] = "saved"; saved["request_id"] = apply["request_id"]!.DeepClone();
        PhoneContactGroupTitleWrite.ValidateCorrelatedReport(saved, apply, prepared);
        foreach (var (field, value) in new (string, JsonNode)[] {
            ("request_id", JsonValue.Create(Guid.NewGuid().ToString("D"))!), ("uid", JsonValue.Create("another-lookup")!),
            ("old_title", JsonValue.Create("Other")!), ("new_title", JsonValue.Create("Other")!),
            ("token", JsonValue.Create(Guid.NewGuid().ToString("D"))!), ("group_id", JsonValue.Create("43")!),
            ("group_identity", JsonValue.Create(new string('b', 64))!),
            ("account", new JsonObject { ["name"] = "another", ["type"] = "provider", ["data_set"] = "" }),
            ("state", JsonValue.Create("prepared")!), ("action", JsonValue.Create("prepare")!) })
        {
            var changed = saved.DeepClone().AsObject(); changed[field] = value;
            TestAssert.Throws<InvalidDataException>(() => PhoneContactGroupTitleWrite.ValidateCorrelatedReport(changed, apply, prepared),
                "Changed native group-title readback was accepted: " + field);
        }
        TestAssert.Throws<InvalidDataException>(() => PhoneContactGroupTitleWrite.ValidateCorrelatedReport(saved, apply), "Apply without native preparation was accepted.");
        foreach (var id in new[] { "0", "-1", "+1", "01", " 1", "1 ", "1.0", "9223372036854775808" })
        {
            var changed = prepared.DeepClone().AsObject(); changed["group_id"] = id;
            TestAssert.Throws<InvalidDataException>(() => PhoneContactGroupTitleWrite.ValidateReportShape(changed), "Noncanonical native group ID accepted.");
        }
        foreach (var title in new[] { "", " Work", "Work ", "Work", "Ar\nbeit", "Cafe\u0301", new string('x', 257), "\uD800" })
        {
            var changed = request.DeepClone().AsObject(); changed["new_title"] = title;
            TestAssert.Throws<InvalidDataException>(() => PhoneContactGroupTitleWrite.ValidateRequestShape(changed), "Invalid group title was accepted.");
        }
        var extra = request.DeepClone().AsObject(); extra["group_id"] = "42";
        TestAssert.Throws<InvalidDataException>(() => PhoneContactGroupTitleWrite.ValidateRequestShape(extra), "Caller-supplied native group ID was accepted in prepare.");
        var inspect = request.DeepClone().AsObject(); inspect["request_id"] = Guid.NewGuid().ToString("D"); inspect["action"] = "inspect";
        inspect["group_id"] = prepared["group_id"]!.DeepClone(); inspect["account"] = prepared["account"]!.DeepClone();
        var current = inspect.DeepClone().AsObject(); current["group_identity"] = prepared["group_identity"]!.DeepClone();
        current["state"] = "current"; current["current_title"] = "Arbeit";
        PhoneContactGroupTitleWrite.ValidateCorrelatedReport(current, inspect);
        TestAssert.That(PhoneContactGroupTitleWrite.MatchesSavedIntent(current, prepared), "Same native identity did not resolve a lost saved report.");
        foreach (var field in new[] { "current_title", "group_identity", "group_id", "account" })
        {
            var wrong = current.DeepClone().AsObject();
            if (field == "current_title") wrong[field] = "Other";
            else if (field == "group_identity") wrong[field] = new string('b', 64);
            else if (field == "group_id") wrong[field] = "43";
            else wrong[field]!["name"] = "another";
            TestAssert.That(!PhoneContactGroupTitleWrite.MatchesSavedIntent(wrong, prepared), "Another native identity/title confirmed an uncertain save.");
        }
        await NativeRoundTripAsync();
    }

    internal static async Task TransportRoundTripAsync(TelefonCoordinator coordinator, TelefonPeer peer, string uid, CancellationToken cancellation)
    {
        var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
        JsonObject Prepare(string oldTitle, string newTitle) => new() { ["version"] = 20, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "prepare", ["uid"] = uid, ["old_title"] = oldTitle, ["new_title"] = newTitle };
        var prepared = await coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, Prepare("Coworkers", "Arbeit"), cancellation);
        var apply = Prepare("Coworkers", "Arbeit"); apply["action"] = "apply"; apply["token"] = prepared["token"]!.DeepClone();
        await TestAssert.ThrowsAsync<TimeoutException>(() => coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, apply, cancellation), "The intentionally lost native result unexpectedly confirmed the rename.");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, apply, cancellation), "Native title ticket was replayed.");
        var inspect = Prepare("Coworkers", "Arbeit"); inspect["action"] = "inspect";
        inspect["group_id"] = prepared["group_id"]!.DeepClone(); inspect["account"] = prepared["account"]!.DeepClone();
        var observed = await coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, inspect, cancellation);
        TestAssert.That(PhoneContactGroupTitleWrite.MatchesSavedIntent(observed, prepared), "Native inspection did not resolve the actual saved title under the same group/source identity.");
        var current = await coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, Prepare("Arbeit", "Another"), cancellation);
        TestAssert.That(JsonNode.DeepEquals(current["group_id"], prepared["group_id"]), "Fresh native preparation did not find the same renamed group.");
        Console.WriteLine("C# Notes live native group-title identity/readback passed.");
    }

    private static async Task NativeRoundTripAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "phone-group-title-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, Enumerable.Repeat((byte)21, 32).ToArray());
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            TestAssert.That(capabilities["device_status"]!["versions"]!.AsArray().Count(value => value!.GetValue<int>() == 20) == 1, "Wired title capability was omitted or advertised twice.");
            var peer = new TelefonPeer("22222222-2222-4222-8222-222222222222", "Synthetic", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities, GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]);
            JsonObject? nativeStatus = null;
            using var coordinator = new TelefonCoordinator(paths, (name, value) => {
                if (name == "App.telefonVerbindungStand") nativeStatus = JsonSerializer.SerializeToNode(value)!.AsObject();
                return Task.CompletedTask;
            }, dataStore: store);
            var flags = BindingFlags.Instance | BindingFlags.NonPublic;
            var accept = typeof(TelefonCoordinator).GetMethod("AcceptContactGroupRead", flags)!;
            using var stream = new MemoryStream(); using var otherStream = new MemoryStream();
            TelefonConnection Connection(Stream wire) => new(peer, wire, new byte[32], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi") {
                ContactGroupReportReceived = (source, value) => (TelefonAck)accept.Invoke(coordinator, [source, peer, value])!
            };
            using var connection = Connection(stream); using var other = Connection(otherStream);
            foreach (var source in new[] { connection, other }) foreach (var field in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" })
                typeof(TelefonConnection).GetField(field, flags)!.SetValue(source, true);
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", flags)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
            JsonObject Request() => new() { ["version"] = 20, ["request_id"] = Guid.NewGuid().ToString("D"), ["action"] = "prepare",
                ["uid"] = "lookup:fixture", ["old_title"] = "Work", ["new_title"] = "Arbeit" };
            var account = new JsonObject { ["name"] = "synthetic", ["type"] = "provider", ["data_set"] = "" };
            JsonObject Report(JsonObject request, string token)
            {
                var result = request.DeepClone().AsObject(); result["token"] = token; result["group_id"] = "42"; result["account"] = account.DeepClone();
                result["group_identity"] = new string('a', 64);
                result["state"] = request["action"]!.GetValue<string>() == "prepare" ? "prepared" : "saved"; return result;
            }
            JsonObject Envelope(JsonObject body)
            {
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                return new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = "device_status.report", ["message_id"] = Guid.NewGuid().ToString("D"),
                    ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body };
            }
            var prepare = Request(); var token = Guid.NewGuid().ToString("D");
            TestAssert.That(coordinator.ContactGroupTitlesAvailable(peer.Id), "The wired title runtime was unavailable despite fresh explicit support.");
            coordinator.ContactGroupTitleWritesEnabled = false;
            TestAssert.That(!coordinator.ContactGroupTitlesAvailable(peer.Id), "Disabling title operations left them available.");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, prepare, default), "Disabled title runtime sent a preparation.");
            coordinator.ContactGroupTitleWritesEnabled = true;
            await coordinator.ReportStatusAsync();
            var gui = new JsonObject(PhoneContactRead.GuiAvailability(nativeStatus!["telefone"]!.AsArray().Single()!.AsObject()));
            TestAssert.That(gui["contact_group_titles_write_available"]!.GetValue<bool>(), "The actual native title capability was lost before GUI delivery.");
            await TestAssert.ThrowsAsync<InvalidDataException>(() => coordinator.ContactGroupsAsync(peer.Id, fingerprint, prepare, default), "Membership API accepted a title operation.");
            var pending = coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, prepare, default);
            await other.HandlePlainAsync(Envelope(Report(prepare, token)));
            TestAssert.That(!pending.IsCompleted, "A replacement session satisfied a title preparation.");
            await connection.HandlePlainAsync(Envelope(Report(prepare, token)));
            var prepared = await pending.WaitAsync(TimeSpan.FromSeconds(2));
            var apply = prepare.DeepClone().AsObject(); apply["action"] = "apply"; apply["request_id"] = Guid.NewGuid().ToString("D"); apply["token"] = prepared["token"]!.DeepClone();
            var retarget = apply.DeepClone().AsObject(); retarget["new_title"] = "Another";
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, retarget, default), "Preparation was retargeted before native apply.");
            var saved = coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, apply, default);
            foreach (var field in new[] { "group_id", "account" })
            {
                var wrong = Report(apply, token);
                if (field == "group_id") wrong[field] = "43"; else wrong[field]!["name"] = "another";
                await connection.HandlePlainAsync(Envelope(wrong));
                TestAssert.That(!saved.IsCompleted, "Another native identity claimed a saved group title.");
            }
            await connection.HandlePlainAsync(Envelope(Report(apply, token)));
            TestAssert.That((await saved.WaitAsync(TimeSpan.FromSeconds(2)))["group_id"]!.GetValue<string>() == "42", "Actual saved native group identity was lost.");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactGroupTitleAsync(peer.Id, fingerprint, apply, default), "Native title preparation was replayed.");
            online.Remove(peer.Id);
            TestAssert.That(!coordinator.ContactGroupTitlesAvailable(peer.Id), "Offline title writer remained available.");
            await coordinator.ReportStatusAsync();
            gui = new JsonObject(PhoneContactRead.GuiAvailability(nativeStatus!["telefone"]!.AsArray().Single()!.AsObject()));
            TestAssert.That(!gui["contact_group_titles_write_available"]!.GetValue<bool>(), "Offline title capability remained true in the GUI projection.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
