using System.IO.Pipes;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Channels;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpTransportTests
{
    internal static async Task RunAsync()
    {
        using (var legacySources = BridgeDispatcherContract.Parse("{\"cmd\":\"eds_status\"}")) { }
        using (var correlatedSources = BridgeDispatcherContract.Parse("{\"cmd\":\"eds_status\",\"requestId\":\"dddddddd-dddd-4ddd-8ddd-dddddddddddd\"}")) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"eds_status\",\"requestId\":42}"), "Native source correlation accepted the wrong request-ID type.");
        foreach (var command in new[] { "journal_liste", "journal_erzeugen", "journal_manuell", "journal_vorschau", "journal_loeschen", "journal_wiederherstellen" })
        {
            using var legacyRecovery = BridgeDispatcherContract.Parse(JsonSerializer.Serialize(new { cmd = command }));
            using var correlatedRecovery = BridgeDispatcherContract.Parse(JsonSerializer.Serialize(new { cmd = command, requestId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" }));
            TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse(JsonSerializer.Serialize(new { cmd = command, requestId = 42 })), "Native recovery correlation accepted the wrong request-ID type.");
        }
        using (var inspection = BridgeDispatcherContract.Parse("{\"cmd\":\"journal_vorschau\",\"verify\":false}")) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"journal_vorschau\",\"verify\":42}"), "Recovery inspection accepted an invalid verification mode.");
        var profile = Path.Combine(Path.GetTempPath(), "magnolie-mcp-fixture-" + Guid.NewGuid().ToString("N"));
        var incoming = Channel.CreateUnbounded<JsonObject>();
        var closed = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var server = new McpLocalServer(profile, payload =>
        {
            incoming.Writer.TryWrite(JsonSerializer.SerializeToNode(payload)!.AsObject());
            return Task.CompletedTask;
        }, session => { closed.TrySetResult(session); return Task.CompletedTask; });
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        try
        {
            using var client = new NamedPipeClientStream(".", McpLocalServer.PipeName(profile), PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            await client.ConnectAsync(timeout.Token);
            using var reader = new StreamReader(client, new UTF8Encoding(false, true), false, 4096, leaveOpen: true);
            async Task SendAsync(string text)
            {
                await client.WriteAsync(Encoding.UTF8.GetBytes(text + "\n"), timeout.Token);
                await client.FlushAsync(timeout.Token);
            }
            await SendAsync("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"fixture\"}");
            var request = await incoming.Reader.ReadAsync(timeout.Token);
            var session = request["session"]!.GetValue<string>();
            var invocation = request["invocation"]!.GetValue<string>();
            using var response = JsonDocument.Parse("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"value\":\"owned-fixture\"}}");
            TestAssert.That(!server.Reply("wrong", invocation, response.RootElement), "Wrong session settled a product request.");
            TestAssert.That(!server.Reply(session, "wrong", response.RootElement), "Wrong invocation settled a product request.");
            using var wrongId = JsonDocument.Parse("{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":{}}");
            using var missingResponse = JsonDocument.Parse("null");
            TestAssert.That(!server.Reply(session, invocation, wrongId.RootElement), "Wrong JSON-RPC ID settled a product request.");
            TestAssert.That(!server.Reply(session, invocation, missingResponse.RootElement), "A request was silently acknowledged as a notification.");
            TestAssert.That(server.Reply(session, invocation, response.RootElement), "Expected product reply was rejected.");
            TestAssert.That(!server.Reply(session, invocation, response.RootElement), "Replay settled a request twice.");
            var actual = JsonNode.Parse((await reader.ReadLineAsync(timeout.Token))!)!;
            TestAssert.That(actual["result"]!["value"]!.GetValue<string>() == "owned-fixture", "Product result was not returned over the real pipe.");
            foreach (var invalid in new[] { "not json", "{\"id\":1,\"id\":2}", "{\"value\":NaN}" })
            {
                await SendAsync(invalid);
                var failure = JsonNode.Parse((await reader.ReadLineAsync(timeout.Token))!)!;
                TestAssert.That(failure["error"]!["code"]!.GetValue<int>() == -32700, "Malformed frame reached the product.");
            }
            await SendAsync("{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"fixture\"}");
            var abandoned = await incoming.Reader.ReadAsync(timeout.Token);
            client.Dispose();
            TestAssert.That(await closed.Task.WaitAsync(timeout.Token) == session, "Disconnect did not revoke the product session.");
            TestAssert.That(!server.Reply(session, abandoned["invocation"]!.GetValue<string>(), response.RootElement),
                "Late reply survived disconnect.");
        }
        finally { server.Dispose(); server.Dispose(); }
        TestAssert.That(!Directory.Exists(profile), "MCP transport created an unexpected profile or token file.");
        await StdioDisconnectAsync();
    }

    private static async Task StdioDisconnectAsync()
    {
        var profile = Path.Combine(Path.GetTempPath(), "magnolie-mcp-stdio-fixture-" + Guid.NewGuid().ToString("N"));
        var incoming = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var server = new McpLocalServer(profile, _ => { incoming.TrySetResult(); return Task.CompletedTask; }, _ => Task.CompletedTask);
        var start = new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = false,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        if (string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath), "dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(typeof(McpTransportTests).Assembly.Location);
        start.ArgumentList.Add("--mcp-stdio-fixture");
        start.ArgumentList.Add(profile);
        using var child = Process.Start(start) ?? throw new InvalidOperationException("Fixture child did not start");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        try
        {
            await child.StandardInput.WriteLineAsync("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}");
            await child.StandardInput.FlushAsync(deadline.Token);
            await incoming.Task.WaitAsync(deadline.Token);
            // Keep stdin open: losing the product connection must still end the stdio host.
            server.Dispose();
            await child.WaitForExitAsync(deadline.Token);
            TestAssert.That(child.ExitCode == 1 && (await child.StandardError.ReadToEndAsync(deadline.Token)).Length == 0,
                "MCP stdio host survived product disconnect or emitted a diagnostic on its protocol streams.");
        }
        finally
        {
            if (!child.HasExited) { child.Kill(entireProcessTree: true); await child.WaitForExitAsync(); }
        }
    }
}
