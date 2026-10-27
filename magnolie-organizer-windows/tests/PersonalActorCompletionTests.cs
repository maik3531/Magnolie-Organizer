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
        private JsonObject Message(string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1,
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
        return Task.CompletedTask;
    }
}
