using System.Text.Json.Nodes;
using System.Reflection;
using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneContactValueWriteTests
{
    internal static async Task RunAsync()
    {
        var prepare = new JsonObject { ["version"] = 19, ["request_id"] = "11111111-1111-4111-8111-111111111111",
            ["action"] = "prepare", ["uid"] = "lookup:🧪", ["field_names"] = new JsonArray("telefone", "emailEintraege") };
        var account = new JsonObject { ["name"] = "fixture@example.invalid", ["type"] = "provider", ["data_set"] = "" };
        var fields = new JsonObject { ["telefone"] = new JsonArray(new JsonObject { ["art"] = "mobil", ["wert"] = "+49 111" }), ["emailEintraege"] = new JsonArray() };
        var report = new JsonObject { ["version"] = 19, ["request_id"] = prepare["request_id"]!.DeepClone(), ["action"] = "prepare",
            ["uid"] = prepare["uid"]!.DeepClone(), ["token"] = "22222222-2222-4222-8222-222222222222", ["account"] = account.DeepClone(),
            ["state"] = "prepared", ["fields"] = fields.DeepClone() };
        PhoneContactValueWrite.ValidateCorrelatedReport(report, prepare);
        var apply = prepare.DeepClone().AsObject(); apply.Remove("field_names"); apply["action"] = "apply";
        apply["token"] = report["token"]!.DeepClone(); apply["fields"] = fields.DeepClone();
        report["action"] = "apply"; report["state"] = "saved";
        PhoneContactValueWrite.ValidateCorrelatedReport(report, apply, account);
        foreach (var change in new[] { "request_id", "uid", "token", "account", "fields", "readback", "state" })
        {
            var wrong = report.DeepClone().AsObject();
            if (change is "request_id" or "token") wrong[change] = "33333333-3333-4333-8333-333333333333";
            else if (change == "uid") wrong[change] = "other-native-contact";
            else if (change == "account") wrong["account"]!["name"] = "foreign@example.invalid";
            else if (change == "fields") wrong["fields"]!.AsObject().Remove("emailEintraege");
            else if (change == "readback") wrong["fields"]!["telefone"]![0]!["wert"] = "previous number";
            else wrong["state"] = "prepared";
            TestAssert.Throws<InvalidDataException>(() => PhoneContactValueWrite.ValidateCorrelatedReport(wrong, apply, account), "Mismatched contact-value receipt accepted: " + change);
        }
        foreach (var change in new[] { "kind", "boolean", "surrogate", "extra", "too-many" })
        {
            var wrong = apply.DeepClone().AsObject(); var row = wrong["fields"]!["telefone"]![0]!;
            if (change == "kind") row["art"] = "fax";
            else if (change == "boolean") row["wert"] = true;
            else if (change == "surrogate") row["wert"] = "\uD800";
            else if (change == "extra") wrong["arbitrary_write"] = true;
            else wrong["fields"]!["telefone"] = new JsonArray(Enumerable.Range(0, 101).Select(i => (JsonNode)new JsonObject { ["art"] = "mobil", ["wert"] = i.ToString() }).ToArray());
            TestAssert.Throws<Exception>(() => PhoneContactValueWrite.ValidateRequestShape(wrong), "Malformed contact value accepted: " + change);
        }
        TestAssert.That(TelefonProtocolContract.DesktopCapabilities()["items"]!["device_status"]!["versions"]!.AsArray().Count(value => value!.GetValue<int>() == 19) == 1,
            "The wired typed value writer was omitted or advertised twice.");
        var card = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Synthetic\r\nTEL;TYPE=CELL:111\r\nEMAIL:hidden@example.invalid\r\nEND:VCARD\r\n";
        var parsed = ExchangeCodec.ParseVCard(card).Kontakte.Single()!.AsObject();
        TestAssert.That(PhoneContactValueWrite.ReadableFields(card, parsed).SequenceEqual(["telefone"]),
            "A filtered native email was reported as a complete empty field.");
        card = card.Replace("hidden@example.invalid", "known@example.test", StringComparison.Ordinal);
        parsed = ExchangeCodec.ParseVCard(card).Kontakte.Single()!.AsObject();
        TestAssert.That(PhoneContactValueWrite.ReadableFields(card, parsed).ToHashSet().SetEquals(["telefone", "emailEintraege"]),
            "A complete typed native card lost its field-completeness proof.");
        await BoundRoundTripAsync();
    }

    internal static async Task TransportRoundTripAsync(TelefonCoordinator coordinator, TelefonPeer peer, string uid, CancellationToken cancellation)
    {
        var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
        JsonObject Prepare(params string[] names) => new() { ["version"] = 19, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "prepare", ["uid"] = uid, ["field_names"] = new JsonArray(names.Select(name => JsonValue.Create(name)).ToArray()) };
        JsonObject Apply(JsonObject prepared, JsonObject fields) => new() { ["version"] = 19, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "apply", ["uid"] = uid, ["token"] = prepared["token"]!.DeepClone(), ["fields"] = fields.DeepClone() };
        var prepared = await coordinator.ContactValuesAsync(peer.Id, fingerprint, Prepare("telefone", "emailEintraege"), cancellation);
        TestAssert.That(prepared["fields"]!["telefone"]![0]!["wert"]!.GetValue<string>() == "111" &&
            prepared["fields"]!["emailEintraege"]![0]!["wert"]!.GetValue<string>() == "old@example.invalid", "Native initial field snapshot differs.");
        var fields = new JsonObject { ["telefone"] = new JsonArray(new JsonObject { ["art"] = "mobil", ["wert"] = "222" }),
            ["emailEintraege"] = new JsonArray(new JsonObject { ["art"] = "arbeit", ["wert"] = "new@example.invalid" }) };
        var apply = Apply(prepared, fields);
        var saved = await coordinator.ContactValuesAsync(peer.Id, fingerprint, apply, cancellation);
        TestAssert.That(JsonNode.DeepEquals(saved["fields"], fields) && JsonNode.DeepEquals(saved["account"], prepared["account"]), "Native saved value/account readback differs.");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactValuesAsync(peer.Id, fingerprint, apply, cancellation), "Native field ticket was replayed.");
        prepared = await coordinator.ContactValuesAsync(peer.Id, fingerprint, Prepare("emailEintraege"), cancellation);
        TestAssert.That(prepared["fields"]!["emailEintraege"]![0]!["wert"]!.GetValue<string>() == "new@example.invalid", "Fresh native field read resurrected the old value.");
        saved = await coordinator.ContactValuesAsync(peer.Id, fingerprint, Apply(prepared, new JsonObject { ["emailEintraege"] = new JsonArray() }), cancellation);
        TestAssert.That(saved["fields"]!["emailEintraege"]!.AsArray().Count == 0, "Selected native list was not actually cleared.");
        Console.WriteLine("C# Notes live native field write/readback passed.");
    }

    private static async Task BoundRoundTripAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "phone-values-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, Enumerable.Repeat((byte)21, 32).ToArray());
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            var peer = new TelefonPeer("22222222-2222-4222-8222-222222222222", "Synthetic", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities, GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]);
            using var coordinator = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store);
            var flags = BindingFlags.Instance | BindingFlags.NonPublic;
            var accept = typeof(TelefonCoordinator).GetMethod("AcceptContactGroupRead", flags)!;
            using var stream = new MemoryStream(); using var otherStream = new MemoryStream();
            TelefonConnection Connection(Stream pipe) => new(peer, pipe, new byte[32], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi") {
                ContactGroupReportReceived = (source, value) => (TelefonAck)accept.Invoke(coordinator, [source, peer, value])!
            };
            using var connection = Connection(stream); using var other = Connection(otherStream);
            foreach (var source in new[] { connection, other }) foreach (var field in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" })
                typeof(TelefonConnection).GetField(field, flags)!.SetValue(source, true);
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", flags)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            var fingerprint = Convert.ToHexString(SHA256.HashData(peer.PublicKey)).ToLowerInvariant();
            JsonObject Request() => new() { ["version"] = 19, ["request_id"] = Guid.NewGuid().ToString("D"), ["action"] = "prepare",
                ["uid"] = "lookup:fixture", ["field_names"] = new JsonArray("telefone", "emailEintraege") };
            var account = new JsonObject { ["name"] = "synthetic@example.invalid", ["type"] = "provider", ["data_set"] = "" };
            var fields = new JsonObject { ["telefone"] = new JsonArray(new JsonObject { ["art"] = "mobil", ["wert"] = "222" }), ["emailEintraege"] = new JsonArray() };
            JsonObject Report(JsonObject request, string token) => new() {
                ["version"] = 19, ["request_id"] = request["request_id"]!.DeepClone(), ["action"] = request["action"]!.DeepClone(),
                ["uid"] = request["uid"]!.DeepClone(), ["token"] = token, ["account"] = account.DeepClone(),
                ["state"] = request["action"]!.GetValue<string>() == "prepare" ? "prepared" : "saved", ["fields"] = fields.DeepClone()
            };
            JsonObject Envelope(JsonObject body) {
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                return new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = "device_status.report", ["message_id"] = Guid.NewGuid().ToString("D"),
                    ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body };
            }
            var prepare = Request(); var token = Guid.NewGuid().ToString("D");
            await TestAssert.ThrowsAsync<InvalidDataException>(() => coordinator.ContactGroupsAsync(peer.Id, fingerprint, prepare, default),
                "The legacy group-only operation accepted a value-write request.");
            TestAssert.That(coordinator.ContactValuesAvailable(peer.Id), "Fresh resource-19 peer is not available to the native staged consumer.");
            var pending = coordinator.ContactValuesAsync(peer.Id, fingerprint, prepare, default);
            await other.HandlePlainAsync(Envelope(Report(prepare, token)));
            TestAssert.That(!pending.IsCompleted, "A replacement channel satisfied a field preparation.");
            await connection.HandlePlainAsync(Envelope(Report(prepare, token)));
            var prepared = await pending.WaitAsync(TimeSpan.FromSeconds(2));
            var apply = prepare.DeepClone().AsObject(); apply.Remove("field_names"); apply["action"] = "apply";
            apply["request_id"] = Guid.NewGuid().ToString("D"); apply["token"] = prepared["token"]!.DeepClone(); apply["fields"] = fields.DeepClone();
            var incomplete = apply.DeepClone().AsObject(); incomplete["fields"]!.AsObject().Remove("emailEintraege");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactValuesAsync(peer.Id, fingerprint, incomplete, default),
                "A ticket's selected fields were widened or narrowed.");
            var saved = coordinator.ContactValuesAsync(peer.Id, fingerprint, apply, default);
            var wrong = Report(apply, token); wrong["fields"]!["telefone"]![0]!["wert"] = "old value";
            await connection.HandlePlainAsync(Envelope(wrong));
            TestAssert.That(!saved.IsCompleted, "An old native field value claimed saved.");
            wrong = Report(apply, token); wrong["account"]!["name"] = "foreign@example.invalid";
            await connection.HandlePlainAsync(Envelope(wrong));
            TestAssert.That(!saved.IsCompleted, "A foreign account claimed saved field values.");
            await connection.HandlePlainAsync(Envelope(Report(apply, token)));
            TestAssert.That((await saved.WaitAsync(TimeSpan.FromSeconds(2)))["state"]!.GetValue<string>() == "saved", "Verified actual field readback was lost.");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ContactValuesAsync(peer.Id, fingerprint, apply, default), "A consumed field ticket was replayed.");
            TestAssert.That(store.LoadStatus(peer.Id) is null, "Contact values or account identity leaked to general status history.");
            online.Remove(peer.Id);
            TestAssert.That(!coordinator.ContactValuesAvailable(peer.Id), "An offline source retained field write availability.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
