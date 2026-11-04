using System.Diagnostics;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileConnectionSourcesTests
{
    private static JsonObject Request(DeviceFileConnectionMetadataTests.Fixture fixture)
    {
        var message = DeviceFileConnectionTransportTests.OpenFrames(fixture.Stream.ToArray()).Single();
        var parsed = DeviceFileSources.ParseRequest(message, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(parsed.Operation == "status" && parsed.Enabled is null && parsed.Kinds.Count == 0 && parsed.RunId is null,
            "Status command enabled policy or started source I/O.");
        return message;
    }
    private static JsonObject Reply(JsonObject request)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = DeviceFileSources.ResultKind, ["created_ms"] = now, ["expires_ms"] = now + 60000,
            ["body"] = new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(), ["operation"] = "status",
                ["version"] = new string('d', 64), ["revision"] = 1, ["enabled"] = false, ["associated"] = false,
                ["repair_pending"] = false, ["kinds"] = new JsonArray() } };
    }
    private static async Task FailsAsync<T>(Task task, string message) where T : Exception
    {
        try { await task; }
        catch (T) { return; }
        throw new InvalidOperationException(message);
    }

    internal static async Task StatusAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        var owner = await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
        var legacy = 0; fixture.DuringReceive = () => legacy++;
        var grants = fixture.Store.LocalGrants().ToJsonString();
        var pending = fixture.Connection.ReadNativeFileSourceStatusAsync();
        var request = Request(fixture);
        TestAssert.That(!pending.IsCompleted, "Queue acceptance fabricated a source status.");
        await FailsAsync<InvalidDataException>(fixture.Connection.ReadNativeFileSourceStatusAsync(), "Native source commands overlapped.");
        var reply = Reply(request);
        await fixture.Connection.HandlePlainAsync(reply);
        var status = await pending;
        TestAssert.That(status.Operation == "status" && !status.Enabled && status.Revision == 1 && status.Version == new string('d', 64),
            "Exact native status reply was not delivered.");
        TestAssert.That(legacy == 0 && !fixture.Store.HasIncomingReceipt(fixture.Peer.Id, reply["message_id"]!.GetValue<string>()) &&
            fixture.Store.OutboxMessage(fixture.Peer.Id, request["message_id"]!.GetValue<string>()) is null,
            "Native source metadata entered the legacy callback/inbox/outbox.");
        TestAssert.That(DeviceFileConnectionTransportTests.OpenFrames(fixture.Stream.ToArray()).Count == 1 &&
            fixture.Store.LocalGrants().ToJsonString() == grants && owner.Binding(new string('c', 64)) is null,
            "Status read created generic ACKs, grants or source READ.");
        var next = owner.ReceiverCommandTicket(); owner.FinishReceiverCommand(next);
    }

    internal static async Task RejectAsync()
    {
        foreach (var bad in new[] { "request", "operation", "schema", "expired", "withdrawn", "kind" })
        {
            using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
            var owner = await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
            var pending = fixture.Connection.ReadNativeFileSourceStatusAsync();
            var reply = Reply(Request(fixture));
            if (bad == "request") reply["body"]!["request_id"] = Guid.NewGuid().ToString("D");
            if (bad == "operation") reply["body"]!["operation"] = "configure";
            if (bad == "schema") reply["body"]!["enabled"] = 1;
            if (bad == "expired") { reply["created_ms"] = 0; reply["expires_ms"] = 1; }
            if (bad == "withdrawn") fixture.Store.UpdatePeerProtocol(fixture.Peer.Id, 2, TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject(), 0, null);
            if (bad == "kind") reply["kind"] = DeviceFileSources.CatalogKind;
            await FailsAsync<InvalidDataException>(fixture.Connection.HandlePlainAsync(reply), "Foreign native source result accepted: " + bad);
            await FailsAsync<InvalidDataException>(pending, "Rejected result completed source status: " + bad);
            TestAssert.That(!fixture.Store.HasIncomingReceipt(fixture.Peer.Id, reply["message_id"]!.GetValue<string>()) &&
                owner.Binding(new string('c', 64)) is null, "Rejected native metadata created a legacy receipt or READ: " + bad);
        }
    }

    internal static async Task CancelAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        var owner = await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
        using var already = new CancellationTokenSource(); already.Cancel();
        await FailsAsync<OperationCanceledException>(fixture.Connection.ReadNativeFileSourceStatusAsync(already.Token), "Already cancelled command sent data.");
        TestAssert.That(fixture.Stream.Length == 0, "Cancelled-before-admission status wrote output.");
        using var cancel = new CancellationTokenSource();
        var pending = fixture.Connection.ReadNativeFileSourceStatusAsync(cancel.Token);
        var old = Request(fixture);
        cancel.Cancel();
        await FailsAsync<OperationCanceledException>(pending, "Caller cancellation did not retire the exact metadata command.");
        var ticket = owner.ReceiverCommandTicket(); owner.FinishReceiverCommand(ticket);
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        var fresh = fixture.Connection.ReadNativeFileSourceStatusAsync(); var current = Request(fixture);
        TestAssert.That(current["message_id"]!.GetValue<string>() != old["message_id"]!.GetValue<string>(), "Cancelled command identity was reused.");
        await fixture.Connection.HandlePlainAsync(Reply(current)); await fresh;
        await FailsAsync<InvalidDataException>(fixture.Connection.HandlePlainAsync(Reply(old)), "Retired metadata reply fell through or revived its owner.");
    }

    internal static async Task CloseAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
        var pending = fixture.Connection.ReadNativeFileSourceStatusAsync(); Request(fixture);
        fixture.Connection.Dispose();
        await FailsAsync<InvalidDataException>(pending, "Native route disposal left a pending metadata task.");
    }

    internal static async Task OutputFailureAsync()
    {
        foreach (var changed in new[] { false, true })
        {
            using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
            var owner = await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
            fixture.Stream.Fail = !changed;
            if (changed) fixture.Stream.BeforeWrite = () => fixture.Store.UpdatePeerProtocol(fixture.Peer.Id, 2,
                TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject(), 0, null);
            var pending = fixture.Connection.ReadNativeFileSourceStatusAsync();
            if (changed) await FailsAsync<InvalidDataException>(pending, "Metadata withdrawal during source output was accepted.");
            else await FailsAsync<IOException>(pending, "Source output failure fabricated status success.");
            TestAssert.That(!owner.NeedsPacket, "Uncertain source output left its native control owner alive.");
            fixture.Stream.BeforeWrite = null; fixture.Stream.Fail = false;
        }
    }

    internal static async Task PromptWithdrawalAsync()
    {
        foreach (var changed in new[] { "metadata", "session" })
        {
            using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
            await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
            var pending = fixture.Connection.ReadNativeFileSourceStatusAsync();
            var request = Request(fixture);
            if (changed == "metadata") await fixture.Connection.HandlePlainAsync(fixture.Message("personal_sync.settings", own: false));
            else
            {
                var replacement = new DeviceFileControlPacket(new(3, new string('a', 64)), new string('f', 64), 1, null);
                await fixture.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(replacement, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
            }
            await FailsAsync<InvalidDataException>(pending.WaitAsync(TimeSpan.FromSeconds(2)), "Withdrawal waited for the old metadata deadline: " + changed);
            await FailsAsync<InvalidDataException>(fixture.Connection.HandlePlainAsync(Reply(request)), "Old status reply revived withdrawn metadata: " + changed);
        }
    }

    internal static async Task TimeoutAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        var owner = await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
        var watch = Stopwatch.StartNew();
        var pending = fixture.Connection.ReadNativeFileSourceStatusAsync(); Request(fixture);
        await FailsAsync<TimeoutException>(pending, "Real bounded metadata deadline did not expire.");
        TestAssert.That(watch.Elapsed >= TimeSpan.FromMilliseconds(DeviceFileControl.MaximumTtlMs - 1000) && watch.Elapsed < TimeSpan.FromSeconds(90),
            "Metadata timeout did not use its real bounded lifetime.");
        var ticket = owner.ReceiverCommandTicket(); owner.FinishReceiverCommand(ticket);
    }
}
