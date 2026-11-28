using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ScopedRunStorageTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "scoped-run-" + Guid.NewGuid().ToString("N"));
        var key = Enumerable.Repeat((byte)57, 32).ToArray();
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, key);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)59, 32).ToArray());
            store.SavePeers([peer]); store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            var request = new JsonObject { ["format"] = 3, ["run_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            var runId = request["run_id"]!.GetValue<string>(); var reference = PhoneContentScope.Reference(PhoneContentScope.Create(["note"], ["task"]));
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var expires = now + 60000;
            var runs = new PersonalSyncStore(store); runs.RememberScopedRun(peer.Id, peer.PublicKey, request, reference, now, expires);
            var unsupported = request.DeepClone().AsObject();
            unsupported["run_id"] = Guid.NewGuid().ToString("D");
            unsupported["trigger"] = PersonalSyncContract.AutoConnectionTrigger;
            var unsupportedId = unsupported["run_id"]!.GetValue<string>();
            TestAssert.Throws<InvalidDataException>(() =>
                runs.RememberScopedRun(peer.Id, peer.PublicKey, unsupported, reference, now, expires),
                "An unsupported connection request entered the scoped run store.");
            TestAssert.Throws<InvalidDataException>(() => runs.RememberRun(peer.Id, unsupported, now, expires),
                "An unsupported connection request entered the ordinary run store.");
            TestAssert.That(runs.LoadRun(peer.Id, unsupportedId, now) is null,
                "An unsupported connection request left behind a durable run.");
            TestScopedConnectionReceipt(store, runs, peer, unsupported, now);
            TestScopedOriginalManifest(store, runs, peer, unsupported, now);
            var reopened = new TelefonStore(paths, key); var loaded = new PersonalSyncStore(reopened);
            TestAssert.That(JsonNode.DeepEquals(reference, loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now)) &&
                JsonNode.DeepEquals(request, loaded.LoadRun(peer.Id, runId, now)!.Request), "Run or scope reference did not survive reopen.");
            loaded.RememberScopedRun(peer.Id, peer.PublicKey, request, reference, now, expires);
            TestAssert.Throws<InvalidDataException>(() => loaded.RememberScopedRun(peer.Id, peer.PublicKey, request, reference, now, expires + 1), "Replay extended scoped run lifetime.");
            var changed = reference.DeepClone().AsObject(); changed["scope_revision"] = 2;
            TestAssert.Throws<InvalidDataException>(() => loaded.RememberScopedRun(peer.Id, peer.PublicKey, request, changed, now, expires), "Run changed membership after persistence.");
            reopened.ChangeSharedSetting(peer.Id, peer.PublicKey, "time_mode", JsonValue.Create("two_way")!);
            TestAssert.That(JsonNode.DeepEquals(reference, loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now)), "Separate time direction invalidated note/task run.");
            reopened.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("two_way")!);
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now), "Changed content choice retained old scoped authorization.");
            reopened.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now), "Returning to scope mode revived old run.");
            var legacy = request.DeepClone().AsObject(); legacy["run_id"] = Guid.NewGuid().ToString("D"); loaded.RememberRun(peer.Id, legacy, now, expires);
            TestAssert.Throws<InvalidDataException>(() => loaded.RememberScopedRun(peer.Id, peer.PublicKey, legacy, reference, now, expires), "Legacy run identity was adopted as scoped.");
            var fresh = request.DeepClone().AsObject(); fresh["run_id"] = Guid.NewGuid().ToString("D");
            loaded.RememberScopedRun(peer.Id, peer.PublicKey, fresh, reference, now, expires);
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, Enumerable.Repeat((byte)61, 32).ToArray(), fresh["run_id"]!.GetValue<string>(), now), "Different paired key reused scoped metadata.");
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, peer.PublicKey, fresh["run_id"]!.GetValue<string>(), expires + 1), "Expired scoped run stayed valid.");
            loaded.CleanupExpiredRuns(expires + 1);
            using var db = reopened.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
            query.CommandText = "SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_scope:%'";
            TestAssert.That((long)query.ExecuteScalar()! == 0, "Expired run cleanup left scoped bindings behind.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    private static void TestScopedConnectionReceipt(TelefonStore store, PersonalSyncStore runs, TelefonPeer peer, JsonObject request, long now)
    {
        store.ChangeSharedSetting(peer.Id, peer.PublicKey, "auto_mode", JsonValue.Create("connection")!);
        var original = new string('a', 64);
        var current = original;
        string CurrentReader() => current;
        var manifest = PhoneContentScope.Create(["note"], ["task"]);
        var message = new JsonObject {
            ["type"] = "message", ["v"] = 1, ["kind"] = PhoneContentScope.DataKind, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = PhoneContentScope.Wrap("personal_sync.request", request, manifest)
        };
        var id = message["message_id"]!.GetValue<string>();
        var runId = request["run_id"]!.GetValue<string>();
        using var db = store.OpenDatabase(); db.Open(); using var statement = db.CreateCommand();
        statement.CommandText = "CREATE TRIGGER fail_connection_request_receipt BEFORE INSERT ON dedupe " +
            $"WHEN NEW.message_id='{id}' BEGIN SELECT RAISE(ABORT,'synthetic receipt write failure'); END";
        statement.ExecuteNonQuery();
        TestAssert.Throws<Microsoft.Data.Sqlite.SqliteException>(() =>
            runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, message, now, original, CurrentReader),
            "The synthetic receipt failure did not abort the grouped write.");
        TestAssert.That(runs.LoadRun(peer.Id, runId, now) is null && !store.HasIncomingReceipt(peer.Id, id) &&
            runs.ScopedRunReference(peer.Id, peer.PublicKey, runId, now) is null, "Failed receipt left a run or scope binding behind.");
        statement.CommandText = "DROP TRIGGER fail_connection_request_receipt"; statement.ExecuteNonQuery();
        TestAssert.That(runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, message, now, original, CurrentReader).Status == "accepted" &&
            runs.LoadRun(peer.Id, runId, now)?.Policy == "connection_only" && store.ReceivedMatches(peer.Id, message),
            "The exact connection request did not persist its typed run and receipt.");
        TestAssert.That(runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, message, now, original, CurrentReader).Status == "duplicate",
            "Exact request on the original reader did not reuse its positive receipt.");
        current = new string('b', 64);
        TestAssert.Throws<InvalidOperationException>(() =>
            runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, message, now, current, CurrentReader),
            "Replacement reader reused the original positive receipt.");
        var changed = message.DeepClone().AsObject(); changed["created_ms"] = now - 1;
        current = original;
        TestAssert.Throws<InvalidDataException>(() =>
            runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, changed, now, original, CurrentReader),
            "Different wire bytes reused the original positive receipt.");
    }

    private static void TestScopedOriginalManifest(TelefonStore store, PersonalSyncStore runs, TelefonPeer peer,
        JsonObject requestTemplate, long now)
    {
        var manifest = PhoneContentScope.Create(["note", "note-two"], []);
        var authority = new string('c', 64);
        JsonObject Frame(string kind, JsonObject body, long expires) => new()
        {
            ["type"] = "message", ["v"] = 1, ["kind"] = PhoneContentScope.DataKind, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["created_ms"] = now, ["expires_ms"] = expires, ["body"] = PhoneContentScope.Wrap(kind, body, manifest)
        };
        JsonObject Note(string id, int size)
        {
            var value = new JsonObject
            {
                ["title"] = id, ["text"] = "", ["html"] = "", ["notebook_id"] = "", ["symbol"] = "",
                ["created_ms"] = 1, ["modified_ms"] = 1,
                ["attachments"] = new JsonArray(new JsonObject
                {
                    ["attachment_id"] = "attachment-" + id, ["name"] = id + ".png", ["kind"] = "image",
                    ["mime"] = "image/png", ["size"] = size, ["sha256"] = new string('d', 64)
                })
            };
            return new JsonObject { ["kind"] = "note", ["id"] = id, ["modified_ms"] = 1, ["state"] = "live",
                ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 1 }),
                ["value"] = value, ["hash"] = PersonalSyncContract.ProjectionHash(value) };
        }
        (JsonObject First, JsonObject Last) Start(int secondSize)
        {
            var request = requestTemplate.DeepClone().AsObject();
            var runId = Guid.NewGuid().ToString("D"); request["run_id"] = runId;
            runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, Frame("personal_sync.request", request, now + 60000),
                now, authority, () => authority);
            var first = Note("note", 123); var last = Note("note-two", secondSize);
            var aggregate = PersonalSyncContract.RecordsHash(new JsonArray(first.DeepClone(), last.DeepClone()));
            JsonObject Batch(JsonObject record, int sequence, bool final, long expires) =>
                Frame("personal_sync.batch", new JsonObject
                {
                    ["format"] = 3, ["run_id"] = runId, ["batch_id"] = Guid.NewGuid().ToString("D"), ["sequence"] = sequence,
                    ["last"] = final, ["reply"] = false, ["records"] = new JsonArray(record), ["records_hash"] = aggregate
                }, expires);
            return (Batch(first, 0, false, now + 10000), Batch(last, 1, true, now + 60000));
        }
        (TelefonAck Ack, PersonalSyncStagedBatch? Complete) Stage(JsonObject message, long at) =>
            runs.StageScopedConnectionBatch(peer.Id, message, manifest, "wifi", at, authority, () => authority);
        string MessageId(JsonObject envelope) => envelope["message_id"]!.GetValue<string>();

        var matching = Start(123);
        TestAssert.That(Stage(matching.First, now).Complete is null, "A partial original batch was treated as complete.");
        var accepted = Stage(matching.Last, now);
        var ready = accepted.Complete;
        TestAssert.That(accepted.Ack.Status == "accepted" && ready is { HasScopedOriginals: true } &&
            ready.ExpiresMs == now + 10000 && ready.PendingMessageId == MessageId(matching.Last),
            "Shared original bytes with distinct local names did not retain the exact batch identity and shortest lifetime.");
        TestAssert.That(Stage(matching.Last, now).Ack.Status == "duplicate", "The exact original batch did not retain its receipt.");
        TestAssert.Throws<InvalidOperationException>(() => runs.RequireScopedConnectionBatchForSave(peer.Id, MessageId(matching.Last),
            ready!.CommitToken, now, (_, _) => authority, _ => true), "An original descriptor permitted a save without verified bytes.");

        var conflict = Start(124);
        Stage(conflict.First, now);
        TestAssert.Throws<InvalidDataException>(() => Stage(conflict.Last, now), "The same hash described conflicting original byte lengths.");
        TestAssert.That(!store.HasIncomingReceipt(peer.Id, MessageId(conflict.Last)), "A conflicting original manifest left a positive receipt.");

        var expired = Start(123);
        Stage(expired.First, now);
        TestAssert.Throws<InvalidOperationException>(() => Stage(expired.Last, now + 10000), "A later batch renewed an expired original receipt.");
        TestAssert.That(!store.HasIncomingReceipt(peer.Id, MessageId(expired.Last)), "An expired original manifest left a positive receipt.");
    }
}
