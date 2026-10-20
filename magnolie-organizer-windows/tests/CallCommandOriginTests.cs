using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CallCommandOriginTests
{
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    private static string? State(TelefonStore store, string peer, string reference)
    {
        using var database = store.OpenDatabase(); database.Open(); using var query = database.CreateCommand();
        query.CommandText = "SELECT state FROM command_effect WHERE peer_id=$peer AND client_ref=$reference";
        query.Parameters.AddWithValue("$peer", peer); query.Parameters.AddWithValue("$reference", reference); return query.ExecuteScalar() as string;
    }
    internal static async Task RunAsync()
    {
        foreach (var action in new[] { "dial", "answer", "end" }) foreach (var origin in new[] { "gui", "mcp" }) await Route(action, origin);
        await PrivateRevocation(); Migration();
    }
    private static async Task Route(string action, string origin)
    {
        using var f = new OutgoingDialTests.Fixture();
        foreach (var name in new[] { "incoming_call_state", "incoming_call_number", "answer_call", "end_call" }) { f.Peer.Grants[name] = true; f.Store.SetLocalGrant(name, true); }
        f.Store.SavePeers([f.Peer]);
        var reference = Guid.NewGuid().ToString("D"); var callRef = Guid.NewGuid().ToString("D"); var now = Now();
        var call = new JsonObject { ["call_ref"] = callRef, ["revision"] = 1L, ["state"] = action == "end" ? "offhook" : "ringing", ["direction"] = "incoming",
            ["number"] = "", ["number_status"] = "not_shared", ["started_ms"] = now, ["offhook_ms"] = action == "end" ? now : 0L,
            ["ended_ms"] = 0L, ["occurred_ms"] = now, ["spam_status"] = "unknown", ["control_origin"] = "phone", ["battery_percent"] = -1, ["battery_captured_ms"] = 0L };
        if (action != "dial") await f.Receive("incoming_call_state.event", call);
        f.Results.Clear(); f.Events.Clear();
        var observed = new List<(TelefonConnection Connection, TelefonPeer Peer, string Kind, JsonObject Body)>();
        f.Host.PrivateCallResultObserver = (source, peer, kind, body) => observed.Add((source, peer, kind, body));
        if (action == "dial") await f.Host.RequestDialAsync(f.Peer.Id, "+49301234567", reference, origin);
        else if (action == "answer") await f.Host.RequestAnswerAsync(f.Peer.Id, callRef, reference, origin);
        else await f.Host.RequestEndCallAsync(f.Peer.Id, callRef, 1, reference, origin);
        TestAssert.That(f.Store.CommandOrigin(f.Peer.Id, reference) == origin && f.WireMessages().Where(value => value["kind"]?.GetValue<string>().EndsWith(".command", StringComparison.Ordinal) == true)
            .All(value => !value["body"]!.AsObject().ContainsKey("origin")), "Local origin was lost or entered the phone protocol.");
        if (origin == "mcp") TestAssert.That(f.Results.Count == 0, "Private queued call changed GUI status.");
        f.Results.Clear();
        var resultKind = action == "dial" ? "dial_request.result" : action + "_call.result";
        var result = new JsonObject { ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = Now() };
        if (action == "dial") result["client_ref"] = reference;
        else { result["command_ref"] = reference; result["call_ref"] = callRef; }
        await f.Receive(resultKind, result);
        TestAssert.That(State(f.Store, f.Peer.Id, reference) == "submitted", "Native call result did not update its existing command receipt.");
        if (origin == "gui") TestAssert.That(f.Results.Count == 1 && observed.Count == 0, "Ordinary GUI reply was rerouted.");
        else TestAssert.That(f.Results.Count == 0 && observed.Count == 1 && observed[0].Connection == f.Connection && observed[0].Peer.Id == f.Peer.Id &&
            observed[0].Kind == resultKind && JsonNode.DeepEquals(observed[0].Body, result), "Private result lost its actual source or entered GUI status.");
        var reopened = new TelefonStore(new WindowsPaths(f.Root), new byte[32]);
        TestAssert.That(reopened.CommandOrigin(f.Peer.Id, reference) == origin && reopened.UpdateCommandOrigin(Guid.NewGuid().ToString("D"), reference, "failed") is null &&
            State(reopened, f.Peer.Id, reference) == "submitted", "Reopen or a foreign peer changed command ownership.");
    }
    private static async Task PrivateRevocation()
    {
        using var f = new OutgoingDialTests.Fixture(); var reference = Guid.NewGuid().ToString("D");
        await f.Host.RequestDialAsync(f.Peer.Id, "+49301234567", reference, "mcp");
        typeof(TelefonCoordinator).GetMethod("RevokeDial", BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(f.Host, [f.Peer.Id]);
        await f.Receive("dial_request.result", new JsonObject { ["client_ref"] = reference, ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = Now() });
        TestAssert.That(f.Results.Count == 0 && f.Store.CommandOrigin(f.Peer.Id, reference) == "mcp", "Revocation or a late private reply changed GUI state.");
    }
    private static void Migration()
    {
        using var f = new OutgoingDialTests.Fixture(); var reference = Guid.NewGuid().ToString("D");
        f.Store.RememberCommand(f.Peer.Id, reference, Now()); f.Store.UpdateCommand(f.Peer.Id, reference, "submitted");
        using (var database = f.Store.OpenDatabase()) {
            database.Open(); using var command = database.CreateCommand();
            command.CommandText = "ALTER TABLE command_effect RENAME TO previous_command_effect; CREATE TABLE command_effect(client_ref TEXT PRIMARY KEY,state TEXT NOT NULL,first_seen_ms INTEGER NOT NULL,peer_id TEXT NOT NULL DEFAULT ''); INSERT INTO command_effect SELECT client_ref,state,first_seen_ms,peer_id FROM previous_command_effect; DROP TABLE previous_command_effect;";
            command.ExecuteNonQuery();
        }
        var migrated = new TelefonStore(new WindowsPaths(f.Root), new byte[32]);
        TestAssert.That(migrated.CommandOrigin(f.Peer.Id, reference) == "gui" && State(migrated, f.Peer.Id, reference) == "submitted", "Legacy GUI command migration changed its origin or state.");
    }
}
