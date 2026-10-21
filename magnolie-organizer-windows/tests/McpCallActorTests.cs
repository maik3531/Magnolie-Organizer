using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpCallActorTests
{
    internal static async Task Prepare(OutgoingDialTests.Fixture f)
    {
        await f.Receive("capabilities.update", TelefonProtocolContract.DesktopCapabilities());
        await f.Receive("grants.update", new JsonObject { ["revision"] = 1L, ["grants"] = f.Peer.Grants.DeepClone() });
    }
    internal static async Task<JsonObject> Create(OutgoingDialTests.Fixture f, string command, string operation, string reference = "", long revision = 0)
    {
        var context = f.Host.McpCallContext(f.Peer.Id, TelefonCrypto.Fingerprint(f.Peer.PublicKey));
        var value = await f.Host.ExecuteMcpAsync(new JsonObject { ["action"] = "call_actor_create", ["peerId"] = f.Peer.Id,
            ["fingerprint"] = context["fingerprint"]!.DeepClone(), ["sourceRevision"] = context["source_revision"]!.DeepClone(),
            ["operationId"] = operation, ["command"] = command, ["destination"] = command == "dial" ? "+49301234567" : "",
            ["callRef"] = reference, ["callRevision"] = revision == 0 ? "" : revision.ToString(System.Globalization.CultureInfo.InvariantCulture) }, default);
        TestAssert.That(value["ok"]!.GetValue<bool>(), value.ToJsonString()); return value["callActorHandle"]!.AsObject();
    }
    internal static Task<JsonObject> Control(OutgoingDialTests.Fixture f, JsonObject handle, string action) => f.Host.ExecuteMcpAsync(new JsonObject {
        ["action"] = action, ["peerId"] = f.Peer.Id, ["fingerprint"] = TelefonCrypto.Fingerprint(f.Peer.PublicKey),
        ["actorId"] = handle["actor_id"]!.DeepClone(), ["ownerToken"] = handle["owner_token"]!.DeepClone() }, default);
    internal static async Task<JsonObject> WaitTransport(OutgoingDialTests.Fixture f, JsonObject handle)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while (true)
        {
            var status = await Control(f, handle, "call_actor_status"); TestAssert.That(status["ok"]!.GetValue<bool>(), status.ToJsonString());
            var actor = status["callActor"]!.AsObject();
            if (actor["transport_dispatched"]!.GetValue<bool>() || actor["phase"]!.GetValue<string>() is "failed" or "cancelled") return actor;
            await Task.Delay(5, deadline.Token);
        }
    }
    internal static async Task RunAsync()
    {
        await Reservation();
        foreach (var command in new[] { "dial", "answer", "end" }) await Command(command);
        await CancelLate();
        await ScopedOutgoingEnd(); await LocalGrantEpoch(); await SourceGuardReleased();
    }
    private static async Task Reservation()
    {
        using var f = new OutgoingDialTests.Fixture(foregroundEnabled: true); await Prepare(f);
        var before = f.Wire.Length; var operation = Guid.NewGuid().ToString("D"); var handle = await Create(f, "dial", operation);
        TestAssert.That(f.Wire.Length == before && !f.Store.HasCommand(f.Peer.Id, operation), "Reservation dispatched or wrote a call command.");
        var wrong = handle.DeepClone().AsObject(); wrong["owner_token"] = new string('0', 64);
        var foreign = await Control(f, wrong, "call_actor_start"); TestAssert.That(foreign["code"]!.GetValue<string>() == "not_found", "Foreign owner started reserved call.");
        var cancelled = await Control(f, handle, "call_actor_cancel"); TestAssert.That(cancelled["callActor"]!["phase"]!.GetValue<string>() == "cancelled", "Reservation was not cancelled.");
        TestAssert.That((await Control(f, handle, "call_actor_start"))["ok"]!.GetValue<bool>() == false && f.Wire.Length == before && !f.Store.HasCommand(f.Peer.Id, operation), "Cancelled reservation still executed.");
    }
    private static JsonObject Call(string reference, string state)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["call_ref"] = reference, ["revision"] = 1L, ["state"] = state, ["direction"] = "incoming", ["number"] = "", ["number_status"] = "not_shared",
            ["started_ms"] = now, ["offhook_ms"] = state == "offhook" ? now : 0L, ["ended_ms"] = 0L, ["occurred_ms"] = now,
            ["spam_status"] = "unknown", ["control_origin"] = "phone", ["battery_percent"] = -1, ["battery_captured_ms"] = 0L };
    }
    private static async Task Command(string command)
    {
        using var f = new OutgoingDialTests.Fixture(foregroundEnabled: true);
        foreach (var name in new[] { "incoming_call_state", "answer_call", "end_call" }) { f.Peer.Grants[name] = true; f.Store.SetLocalGrant(name, true); }
        f.Store.SavePeers([f.Peer]); await Prepare(f);
        var reference = command == "dial" ? "" : Guid.NewGuid().ToString("D");
        if (command != "dial") await f.Receive("incoming_call_state.event", Call(reference, command == "end" ? "offhook" : "ringing"));
        f.Events.Clear(); f.Results.Clear(); var operation = Guid.NewGuid().ToString("D");
        var handle = await Create(f, command, operation, reference, command == "dial" ? 0 : 1);
        TestAssert.That((await Control(f, handle, "call_actor_start"))["ok"]!.GetValue<bool>(), "Native call actor start failed.");
        var pending = await WaitTransport(f, handle);
        TestAssert.That(pending["phase"]!.GetValue<string>() == "awaiting_phone" && pending["receipt_persisted"]!.GetValue<bool>() && !pending["phone_result_received"]!.GetValue<bool>(), pending.ToJsonString());
        var wire = f.WireMessages().Last(value => value["kind"]?.GetValue<string>() == (command == "dial" ? "dial_request.command" : command + "_call.command"));
        await f.Connection.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = wire["message_id"]!.DeepClone(), ["status"] = "accepted", ["error"] = "none" });
        TestAssert.That((await Control(f, handle, "call_actor_status"))["callActor"]!["phone_result_received"]!.GetValue<bool>() == false, "Transport ACK completed a native call action.");
        var result = new JsonObject { ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
        if (command == "dial") result["client_ref"] = operation; else { result["command_ref"] = operation; result["call_ref"] = reference; }
        await f.Receive(command == "dial" ? "dial_request.result" : command + "_call.result", result);
        var done = (await Control(f, handle, "call_actor_status"))["callActor"]!.AsObject();
        TestAssert.That(done["phase"]!.GetValue<string>() == "reported" && done["phone_result_received"]!.GetValue<bool>() && JsonNode.DeepEquals(done["phone_result"], result), done.ToJsonString());
        TestAssert.That(f.Results.Count == 0 && f.Store.CommandOrigin(f.Peer.Id, operation) == "mcp", "Private actor changed GUI command status or lost persistent origin.");
    }
    private static async Task CancelLate()
    {
        using var f = new OutgoingDialTests.Fixture(foregroundEnabled: true); await Prepare(f);
        var operation = Guid.NewGuid().ToString("D"); var handle = await Create(f, "dial", operation);
        await Control(f, handle, "call_actor_start"); var sent = await WaitTransport(f, handle);
        TestAssert.That(sent["dispatch_started"]!.GetValue<bool>(), sent.ToJsonString());
        var cancelled = (await Control(f, handle, "call_actor_cancel"))["callActor"]!;
        TestAssert.That(cancelled["native_outcome_unknown"]!.GetValue<bool>() && cancelled["remote_recall_confirmed"]!.GetValue<bool>() == false, "Cancel claimed remote recall.");
        await f.Receive("dial_request.result", new JsonObject { ["client_ref"] = operation, ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() });
        TestAssert.That((await Control(f, handle, "call_actor_status"))["callActor"]!["phone_result"] is null && f.Results.Count == 0, "Late private result was adopted by cancelled owner or GUI.");
    }
    private static async Task ScopedOutgoingEnd()
    {
        using var f = new OutgoingDialTests.Fixture(foregroundEnabled: true); await Prepare(f);
        var grantsBefore = f.Store.LocalGrants().DeepClone();
        var dial = Guid.NewGuid().ToString("D"); var dialOwner = await Create(f, "dial", dial);
        await Control(f, dialOwner, "call_actor_start"); var sent = await WaitTransport(f, dialOwner);
        TestAssert.That(sent["transport_dispatched"]!.GetValue<bool>(), sent.ToJsonString());
        var call = Call(dial, "offhook"); call["direction"] = "outgoing"; call["control_origin"] = "desktop";
        await f.Receive("incoming_call_state.event", call);
        var context = f.Host.McpCallContext(f.Peer.Id, TelefonCrypto.Fingerprint(f.Peer.PublicKey));
        TestAssert.That(context["permissions"]!["incoming_call_state"]!.GetValue<bool>() == false &&
            context["call"]?["scope"]?.GetValue<string>() == "outgoing_request", "Existing scoped outgoing authority was replaced by global GUI grants or lost.");
        var end = Guid.NewGuid().ToString("D"); var endOwner = await Create(f, "end", end, dial, 1);
        await Control(f, endOwner, "call_actor_start"); var ending = await WaitTransport(f, endOwner);
        TestAssert.That(ending["phase"]!.GetValue<string>() == "awaiting_phone", ending.ToJsonString());
        await f.Receive("end_call.result", new JsonObject { ["command_ref"] = end, ["call_ref"] = dial, ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() });
        TestAssert.That((await Control(f, endOwner, "call_actor_status"))["callActor"]!["phone_result_received"]!.GetValue<bool>() &&
            JsonNode.DeepEquals(f.Store.LocalGrants(), grantsBefore) && f.Results.Count == 0, "Ending an owned scoped call changed GUI grants or lost its private report.");
    }
    private static async Task LocalGrantEpoch()
    {
        using var f = new OutgoingDialTests.Fixture(foregroundEnabled: true); await Prepare(f);
        var before = f.Host.McpCallContext(f.Peer.Id, TelefonCrypto.Fingerprint(f.Peer.PublicKey));
        await f.Host.SetGrantAsync(f.Peer.Id, "answer_call", true);
        await f.Host.SetGrantAsync(f.Peer.Id, "answer_call", false);
        var after = f.Host.McpCallContext(f.Peer.Id, TelefonCrypto.Fingerprint(f.Peer.PublicKey));
        TestAssert.That(before["source_revision"]!.GetValue<string>() != after["source_revision"]!.GetValue<string>(), "Revocation/regrant restored an old native source token.");
    }
    private sealed class SourceGuardStream : MemoryStream
    {
        internal Func<bool>? GuardHeld;
        internal bool Checking;
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (Checking && GuardHeld?.Invoke() == true) throw new InvalidOperationException("Private socket write held the native source guard.");
            return base.WriteAsync(buffer, cancellationToken);
        }
    }
    private static async Task SourceGuardReleased()
    {
        using var wire = new SourceGuardStream();
        using var f = new OutgoingDialTests.Fixture(foregroundEnabled: true, wire: wire); await Prepare(f);
        var gate = typeof(TelefonCoordinator).GetField("gate", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(f.Host)!;
        wire.GuardHeld = () => Monitor.IsEntered(gate); wire.Checking = true;
        var owner = await Create(f, "dial", Guid.NewGuid().ToString("D")); await Control(f, owner, "call_actor_start");
        var sent = await WaitTransport(f, owner); wire.Checking = false;
        TestAssert.That(sent["transport_dispatched"]!.GetValue<bool>() && sent["phase"]!.GetValue<string>() == "awaiting_phone", sent.ToJsonString());
        await Control(f, owner, "call_actor_cancel");
    }
}
