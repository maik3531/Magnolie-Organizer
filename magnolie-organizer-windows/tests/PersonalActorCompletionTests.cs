using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorCompletionTests
{
    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "actor-completion-" + Guid.NewGuid().ToString("N"));
        internal readonly string Peer = "11111111-1111-4111-8111-111111111111", Fingerprint = "AAAA-BBBB-CCCC-DDDD";
        internal readonly TelefonStore Store;
        internal readonly PersonalSyncActorStore Registry;
        internal readonly PersonalActorHandle Handle;
        internal readonly JsonObject Data, Control;
        internal readonly Func<string, JsonObject?, bool?> Guard;
        internal string Source = new('a', 64);
        internal long Now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), Mono = 1000000;
        internal bool Ready = true, Lost, Saved, LoseOnPost;
        private int putCalls;
        private const string Expected = "77777777-7777-4777-8777-777777777777";
        internal Fixture()
        {
            Store = new TelefonStore(new WindowsPaths(Root), Enumerable.Repeat((byte)37, 32).ToArray());
            Registry = NewRegistry(); Handle = Registry.Create(Peer, Fingerprint, Source);
            Data = Message(PersonalSyncActorContract.DataKind, PersonalSyncActorContract.Wrap(Handle.ActorId, "personal_sync.request",
                new JsonObject { ["format"] = 3, ["run_id"] = Handle.ActorId, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") }));
            Registry.Put(Handle, Data);
            Control = Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Handle.ActorId, Expected));
            Guard = Check;
        }
        private bool? Check(string operation, JsonObject? wire)
        {
            if (Lost) return false;
            if (!Ready || operation == "finish" && !Saved) return null;
            if (operation == "put")
            {
                if (LoseOnPost && ++putCalls % 2 == 0) return false;
                if (wire!["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind && wire["body"]!["message_id"]!.GetValue<string>() != Expected)
                    throw new InvalidDataException("Unexpected native completion control.");
            }
            return true;
        }
        internal PersonalSyncActorStore NewRegistry(string? epoch = null) => new(Store,
            (id, fingerprint) => id == Peer && fingerprint == Fingerprint ? Source : null,
            epoch: epoch, clock: () => Now, monotonicClock: () => Mono);
        internal JsonObject Message(string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1,
            ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["created_ms"] = Now, ["expires_ms"] = Now + 60000, ["body"] = body };
        internal long Count(string table)
        {
            using var db = Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand(); command.CommandText = $"SELECT COUNT(*) FROM {table}";
            return Convert.ToInt64(command.ExecuteScalar());
        }
        internal byte[] Binding()
        {
            using var db = Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
            command.CommandText = "SELECT payload FROM personal_actor_context WHERE actor_id=$actor"; command.Parameters.AddWithValue("$actor", Handle.ActorId);
            return (byte[])command.ExecuteScalar()!;
        }
        internal void RestoreBinding(byte[] payload)
        {
            using var db = Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
            command.CommandText = "UPDATE personal_actor_context SET payload=$payload WHERE actor_id=$actor";
            command.Parameters.AddWithValue("$payload", payload); command.Parameters.AddWithValue("$actor", Handle.ActorId); command.ExecuteNonQuery();
        }
        public void Dispose() { SqliteConnection.ClearAllPools(); if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }

    internal static Task RunAsync()
    {
        using (var f = new Fixture())
        {
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.ReadCompletionControls(f.Handle), "Normal data owner unexpectedly became metadata owner.");
            TestAssert.That(JsonNode.DeepEquals(f.Registry.Read(f.Handle, f.Data["message_id"]!.GetValue<string>()), f.Data), "Failed metadata lookup damaged normal data access.");
            f.Registry.BeginCompletion(f.Handle, f.Guard); f.Registry.BeginCompletion(f.Handle, f.Guard);
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.Read(f.Handle, f.Data["message_id"]!.GetValue<string>()), "Completion owner retained data read.");
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.Put(f.Handle, f.Data), "Completion owner retained data write.");
            TestAssert.Throws<InvalidDataException>(() => f.Registry.PutCompletionControl(f.Handle, f.Data), "Data entered metadata-only storage.");
            f.Source = new string('b', 64);
            TestAssert.That(f.Registry.PutCompletionControl(f.Handle, f.Control) && !f.Registry.PutCompletionControl(f.Handle, f.Control) &&
                JsonNode.DeepEquals(f.Registry.ReadCompletionControls(f.Handle), new JsonArray(f.Control.DeepClone())) && f.Registry.Status(f.Handle)["packets"]!.GetValue<int>() == 2,
                "Metadata was lost, duplicated, or confused with the old data table.");
            using (var db = f.Store.OpenDatabase())
            {
                db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT payload FROM personal_actor_completion_wire";
                TestAssert.That(!Encoding.UTF8.GetString((byte[])read.ExecuteScalar()!).Contains("77777777-7777-4777-8777-777777777777", StringComparison.Ordinal), "Metadata was not sealed.");
            }
            f.Now += 61000;
            TestAssert.That(f.Registry.ReadCompletionControls(f.Handle).Count == 1, "Recorded control metadata was mistaken for a new network frame.");
            TestAssert.Throws<InvalidDataException>(() => f.Registry.PutCompletionControl(f.Handle, f.Control), "Expired network frame was re-admitted.");
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.FinishCompletion(f.Handle), "Callback waiting for save was treated as completion.");
            f.Saved = true; f.Registry.FinishCompletion(f.Handle); f.Registry.FinishCompletion(f.Handle);
            TestAssert.That(f.Registry.Status(f.Handle)["phase"]!.GetValue<string>() == "completed", "Metadata completion was not idempotent.");
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.RequireCurrent(f.Handle), "Completed owner revived data.");
        }
        using (var f = new Fixture())
        {
            f.Registry.BeginCompletion(f.Handle, f.Guard); f.Ready = false;
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.PutCompletionControl(f.Handle, f.Control), "Incomplete fresh evidence admitted metadata.");
            TestAssert.That(f.Registry.Status(f.Handle)["phase"]!.GetValue<string>() == "completion", "Waiting scope was prematurely retired.");
            f.Ready = true;
            var unexpected = f.Control.DeepClone().AsObject(); unexpected["body"]!["message_id"] = Guid.NewGuid().ToString("D");
            TestAssert.Throws<InvalidDataException>(() => f.Registry.PutCompletionControl(f.Handle, unexpected), "Unexpected correlated identity accepted.");
            var wrong = new PersonalActorHandle(f.Handle.ActorId, new string('0', 64));
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.Cancel(wrong), "Foreign owner stole completion cap.");
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.ReadCompletionControls(wrong), "Foreign owner read metadata.");
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.BeginCompletion(f.Handle, (_, _) => true), "Registered callback was replaced.");
            TestAssert.That(f.Registry.PutCompletionControl(f.Handle, f.Control), "Bad control/owner poisoned valid metadata owner.");
            var changed = f.Control.DeepClone().AsObject(); changed["body"]!["status"] = "duplicate";
            TestAssert.Throws<InvalidDataException>(() => f.Registry.PutCompletionControl(f.Handle, changed), "Changed packet replaced an earlier receipt.");
            f.Lost = true; TestAssert.Throws<InvalidOperationException>(() => f.Registry.ReadCompletionControls(f.Handle), "Lost authority still read metadata.");
            f.Lost = false; TestAssert.Throws<InvalidOperationException>(() => f.Registry.ReadCompletionControls(f.Handle), "Authority regrant revived retired cap.");
        }
        using (var f = new Fixture())
        {
            f.Registry.BeginCompletion(f.Handle, f.Guard); f.LoseOnPost = true;
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.PutCompletionControl(f.Handle, f.Control), "Failed native post-check committed metadata.");
            TestAssert.That(f.Count("personal_actor_completion_wire") == 0 && f.Registry.Status(f.Handle)["phase"]!.GetValue<string>() == "cancelled", "Rollback revived denied owner or retained packet.");
        }
        foreach (var mode in new[] { "wall_expiry", "mono_expiry", "wall_rollback", "mono_rollback" })
        {
            using var f = new Fixture(); f.Registry.BeginCompletion(f.Handle, f.Guard);
            if (mode == "wall_expiry") f.Now += PersonalSyncActorStore.LifetimeMs + 1;
            if (mode == "mono_expiry") f.Mono += PersonalSyncActorStore.LifetimeMs + 1;
            if (mode == "wall_rollback") f.Now--;
            if (mode == "mono_rollback") f.Mono--;
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.ReadCompletionControls(f.Handle), "Invalid completion lease accepted: " + mode);
        }
        using (var f = new Fixture())
        {
            var binding = f.Binding(); f.Registry.BeginCompletion(f.Handle, f.Guard); f.RestoreBinding(binding);
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.Read(f.Handle, f.Data["message_id"]!.GetValue<string>()), "Historical binding revived closed data owner.");
            TestAssert.That(f.Registry.Reap() == 1, "Volatile closed-data fence was not preserved by reaping.");
        }
        using (var f = new Fixture())
        {
            f.Registry.BeginCompletion(f.Handle, f.Guard);
            var reopened = f.NewRegistry(f.Registry.Epoch);
            TestAssert.Throws<InvalidOperationException>(() => reopened.ReadCompletionControls(f.Handle), "Replacement registry inherited volatile native validator.");
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.PutCompletionControl(f.Handle, f.Control), "Cancelled replacement owner reopened metadata.");
        }
        using (var f = new Fixture())
        {
            f.Registry.BeginCompletion(f.Handle, f.Guard);
            for (var index = 0; index < 3; index++) f.Registry.Create(f.Peer, f.Fingerprint, f.Source);
            TestAssert.Throws<InvalidOperationException>(() => f.Registry.Create(f.Peer, f.Fingerprint, f.Source), "Completion owner escaped active capacity.");
            f.Registry.Cancel(f.Handle); f.Registry.Create(f.Peer, f.Fingerprint, f.Source);
        }
        ExactSavedDecisionCorrelation();
        NativeSentAcknowledgmentCorrelation();
        MixedAcknowledgmentDirections();
        return Task.CompletedTask;
    }

    private sealed class DecisionFixture : IDisposable
    {
        internal readonly Fixture Native = new();
        internal readonly NativeBookOwnerScope Book = new();
        internal readonly JsonObject Before, After, Frame, Ack;
        internal JsonObject? Scope;
        internal string? Authority = new string('a', 64);
        internal readonly PersonalActorDecisionCompletion Completion;
        internal DecisionFixture(bool restore = false, bool ownAck = false)
        {
            var path = Path.Combine(TestSource.Root("contracts/notes-actor-completion-scope.json"), "contracts", "notes-actor-completion-scope.json");
            var vector = JsonNode.Parse(File.ReadAllText(path))!["cases"]!.AsArray().OfType<JsonObject>().Single(value => value["name"]!.GetValue<string>() == "delete-note");
            Before = vector["before"]!.DeepClone().AsObject(); After = (restore ? Before : vector["actual_after"]!).DeepClone().AsObject(); Scope = Before;
            var decisions = vector["decisions"]!.DeepClone().AsArray();
            if (restore) decisions[0]!["decision"] = "restore";
            var body = new JsonObject { ["format"] = 1, ["run_id"] = Native.Handle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = decisions };
            Frame = PersonalSyncActorContract.WireMessage(Native.Message("personal_sync.deletion_decision", body), Native.Handle.ActorId);
            Ack = Native.Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Native.Handle.ActorId, Frame["message_id"]!.GetValue<string>()));
            Book.SetReady(true); Book.RecordSaved("native-synthetic-writer", true, new string('a', 64));
            Completion = new(Native.Handle.ActorId, vector["native_targets"]!.AsArray(), [Frame], () => Authority, () => Scope,
                () => Book.SaveState("native-synthetic-writer", true), () => Native.Registry.ReadCompletionControls(Native.Handle),
                nativeSentAcknowledgments: ownAck ? [Ack] : []);
            Native.Registry.BeginCompletion(Native.Handle, Completion.Validator);
        }
        internal void Sql(string sql)
        {
            using var db = Native.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand(); command.CommandText = sql; command.ExecuteNonQuery();
        }
        public void Dispose() => Native.Dispose();
    }

    private static void MixedAcknowledgmentDirections()
    {
        var path = Path.Combine(TestSource.Root("contracts/notes-actor-completion-scope.json"), "contracts", "notes-actor-completion-scope.json");
        var vector = JsonNode.Parse(File.ReadAllText(path))!["cases"]!.AsArray().OfType<JsonObject>().Single(value => value["name"]!.GetValue<string>() == "delete-parent-and-attachment");
        foreach (var ownFirst in new[] { true, false })
        {
            using var native = new Fixture(); var book = new NativeBookOwnerScope();
            book.SetReady(true); book.RecordSaved("mixed-native-profile", true, new string('a', 64));
            var observed = vector["before"]!.DeepClone().AsObject();
            var frames = vector["decisions"]!.AsArray().Select(decision => PersonalSyncActorContract.WireMessage(
                native.Message("personal_sync.deletion_decision", new JsonObject { ["format"] = 1, ["run_id"] = native.Handle.ActorId,
                    ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = new JsonArray(decision!.DeepClone()) }), native.Handle.ActorId)).ToArray();
            var peerAck = native.Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(native.Handle.ActorId, frames[0]["message_id"]!.GetValue<string>()));
            var ownAck = native.Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(native.Handle.ActorId, frames[1]["message_id"]!.GetValue<string>()));
            var completion = new PersonalActorDecisionCompletion(native.Handle.ActorId, vector["native_targets"]!.AsArray(), frames,
                () => new string('a', 64), () => observed, () => book.SaveState("mixed-native-profile", true),
                () => native.Registry.ReadCompletionControls(native.Handle), nativeSentAcknowledgments: [ownAck]);
            native.Registry.BeginCompletion(native.Handle, completion.Validator);
            native.Registry.CheckCompletionSend(native.Handle, frames[0]);
            TestAssert.Throws<InvalidDataException>(() => native.Registry.CheckCompletionSend(native.Handle, frames[1]), "Mixed incoming reference became outgoing data.");
            observed = vector["actual_after"]!.DeepClone().AsObject();
            TestAssert.Throws<InvalidOperationException>(() => native.Registry.PutCompletionControl(native.Handle, ownAck), "Mixed own ACK persisted before native send.");
            foreach (var own in new[] { ownFirst, !ownFirst })
            {
                var wire = own ? ownAck : peerAck;
                if (own) completion.RecordSuccessfulAcknowledgmentSend(wire);
                TestAssert.That(native.Registry.PutCompletionControl(native.Handle, wire), "Mixed exact receipt was not persisted.");
                completion.RecordPersisted(wire);
                if (completion.Summary()["saved"]!.GetValue<int>() == 1)
                    TestAssert.Throws<InvalidOperationException>(() => native.Registry.FinishCompletion(native.Handle), "One receipt direction substituted for both.");
            }
            TestAssert.That(completion.Summary()["saved"]!.GetValue<int>() == 2 && completion.Summary()["expected"]!.GetValue<int>() == 2, "Mixed receipt sets were not kept distinct.");
            native.Registry.FinishCompletion(native.Handle);
            TestAssert.Throws<InvalidOperationException>(() => native.Registry.RequireCurrent(native.Handle), "Mixed completion revived data.");
        }
    }

    private static void NativeSentAcknowledgmentCorrelation()
    {
        using (var f = new DecisionFixture(ownAck: true))
        {
            var id = f.Frame["message_id"]!.GetValue<string>();
            TestAssert.That(f.Completion.ExpectsNativeAcknowledgment(id) && !f.Completion.ExpectsNativeAcknowledgment(Guid.NewGuid().ToString("D")),
                "Native ACK direction was not bound to the exact decision frame.");
            TestAssert.Throws<InvalidDataException>(() => f.Native.Registry.CheckCompletionSend(f.Native.Handle, f.Frame), "Incoming reference frame became outgoing data.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.CheckCompletionSend(f.Native.Handle, f.Ack), "Own ACK was sendable before the exact resulting scope.");
            f.Scope = f.After;
            f.Native.Registry.CheckCompletionSend(f.Native.Handle, f.Ack);
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "An unsent own ACK became persisted success.");
            TestAssert.Throws<InvalidOperationException>(() => f.Completion.RecordPersisted(f.Ack), "An outbox/peer claim substituted for native ACK send.");
            var forged = f.Ack.DeepClone().AsObject(); forged["message_id"] = Guid.NewGuid().ToString("D");
            TestAssert.Throws<InvalidDataException>(() => f.Completion.RecordSuccessfulAcknowledgmentSend(forged), "Another ACK identity acquired the native send receipt.");
            TestAssert.That(f.Completion.Summary()["saved"]!.GetValue<int>() == 0, "Unsent native ACK counted as saved.");
            // This is the native post-I/O marker contract, not a transport test.
            f.Completion.RecordSuccessfulAcknowledgmentSend(f.Ack);
            f.Sql("CREATE TRIGGER own_ack_failure BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic own ACK write failure'); END");
            TestAssert.Throws<SqliteException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Own ACK persistence failure disappeared.");
            TestAssert.Throws<InvalidOperationException>(() => f.Completion.RecordPersisted(f.Ack), "Send alone substituted for protected persistence.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.FinishCompletion(f.Native.Handle), "Sent but unpersisted own ACK finished completion.");
            f.Sql("DROP TRIGGER own_ack_failure");
            TestAssert.That(f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Sent own ACK was not persisted.");
            f.Completion.RecordPersisted(f.Ack);
            TestAssert.That(!f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Native ACK replay duplicated a row.");
            f.Completion.RecordPersisted(f.Ack);
            TestAssert.That(f.Completion.Summary()["saved"]!.GetValue<int>() == 1, "Exact sent and persisted own ACK was not counted once.");
            f.Native.Registry.FinishCompletion(f.Native.Handle);
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.RequireCurrent(f.Native.Handle), "Own ACK completion revived data access.");
        }
        foreach (var mode in new[] { "authority", "book", "profile", "scope" })
        {
            using var f = new DecisionFixture(ownAck: true);
            f.Scope = f.After;
            if (mode == "authority") f.Authority = new string('b', 64);
            if (mode == "book") f.Book.RecordSaved("native-synthetic-writer", true, new string('b', 64));
            if (mode == "profile") f.Book.Invalidate();
            if (mode == "scope") f.Scope = PhoneContentScope.Create(["foreign"], ["t"]);
            TestAssert.Throws<InvalidOperationException>(() => f.Completion.RecordSuccessfulAcknowledgmentSend(f.Ack), "Changed native state marked ACK sent: " + mode);
            TestAssert.That(f.Completion.Summary()["saved"]!.GetValue<int>() == 0, "Changed native state counted own ACK: " + mode);
        }
        using (var f = new DecisionFixture(restore: true, ownAck: true))
        {
            f.Native.Registry.CheckCompletionSend(f.Native.Handle, f.Ack);
            f.Completion.RecordSuccessfulAcknowledgmentSend(f.Ack);
            f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack); f.Completion.RecordPersisted(f.Ack);
            f.Native.Registry.FinishCompletion(f.Native.Handle);
        }
    }

    private static void ExactSavedDecisionCorrelation()
    {
        using (var f = new DecisionFixture())
        {
            f.Native.Registry.CheckCompletionSend(f.Native.Handle, f.Frame);
            TestAssert.That(f.Native.Registry.Reap() == 0, "Maintenance retired an exact native completion owner.");
            var changed = f.Frame.DeepClone().AsObject(); changed["message_id"] = Guid.NewGuid().ToString("D");
            TestAssert.Throws<InvalidDataException>(() => f.Native.Registry.CheckCompletionSend(f.Native.Handle, changed), "Another queued identity inherited native terminal send rights.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Success before resulting scope was counted.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.FinishCompletion(f.Native.Handle), "Missing fresh scope and receipt finished deletion.");
            f.Scope = f.After;
            TestAssert.Throws<InvalidOperationException>(() => f.Completion.RecordPersisted(f.Ack), "Queue acceptance substituted for encrypted metadata persistence.");
            f.Sql("CREATE TRIGGER decision_write_failure BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END");
            TestAssert.Throws<SqliteException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Actual SQLite write failure disappeared.");
            TestAssert.Throws<InvalidOperationException>(() => f.Completion.RecordPersisted(f.Ack), "Failed SQL transaction counted as saved.");
            f.Sql("DROP TRIGGER decision_write_failure");
            TestAssert.That(f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Exact completion ACK was not persisted.");
            f.Completion.RecordPersisted(f.Ack);
            TestAssert.That(f.Completion.Summary()["saved"]!.GetValue<int>() == 1 && f.Native.Registry.FinishCompletion(f.Native.Handle)["phase"]!.GetValue<string>() == "completed", "Fresh saved claim and actual native ACK did not complete.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.RequireCurrent(f.Native.Handle), "Completed receipt reopened content.");
        }
        using (var f = new DecisionFixture(restore: true))
        {
            f.Scope = null;
            TestAssert.That(f.Native.Registry.Reap() == 0, "Maintenance confused a pending fresh scope with revoked ownership.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Incomplete scope accepted a receipt.");
            f.Scope = f.Before;
            TestAssert.That(f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Exact same-scope restore failed.");
            f.Completion.RecordPersisted(f.Ack);
            TestAssert.That(!f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Exact ACK replay duplicated a row.");
            f.Completion.RecordPersisted(f.Ack); f.Native.Registry.FinishCompletion(f.Native.Handle);
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.RequireCurrent(f.Native.Handle), "Restore receipt revived a data owner.");
        }
        foreach (var mode in new[] { "authority", "book", "profile", "scope" })
        {
            using var f = new DecisionFixture();
            if (mode == "authority") f.Authority = new string('b', 64);
            if (mode == "book") f.Book.RecordSaved("native-synthetic-writer", true, new string('b', 64));
            if (mode == "profile") f.Book.Invalidate();
            if (mode == "scope") f.Scope = PhoneContentScope.Create(["foreign"], ["t"]);
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack), "Unrelated native state accepted receipt: " + mode);
            TestAssert.That(f.Completion.Summary()["saved"]!.GetValue<int>() == 0, "Unrelated state claimed saved: " + mode);
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.RequireCurrent(f.Native.Handle), "Unrelated state revived data: " + mode);
        }
        using (var f = new DecisionFixture())
        {
            var rejected = f.Native.Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(f.Native.Handle.ActorId, f.Frame["message_id"]!.GetValue<string>(), "rejected", "temporary_failure"));
            f.Native.Registry.PutCompletionControl(f.Native.Handle, rejected); f.Completion.RecordPersisted(rejected);
            TestAssert.That(f.Completion.Summary()["saved"]!.GetValue<int>() == 0, "Temporary rejection became a saved receipt.");
            TestAssert.Throws<InvalidOperationException>(() => f.Native.Registry.FinishCompletion(f.Native.Handle), "Temporary rejection completed native deletion.");
            f.Scope = f.After; f.Native.Registry.PutCompletionControl(f.Native.Handle, f.Ack); f.Completion.RecordPersisted(f.Ack);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Registry.PutCompletionControl(f.Native.Handle, rejected), "Remote outcome downgraded after success.");
            f.Native.Registry.FinishCompletion(f.Native.Handle);
        }
    }
}
