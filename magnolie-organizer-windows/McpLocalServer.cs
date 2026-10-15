using System.Collections.Concurrent;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class McpLocalServer : IDisposable
{
    internal const int MaximumFrame = 1024 * 1024;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private readonly CancellationTokenSource lifetime = new();
    private readonly SemaphoreSlim slots = new(8, 8);
    private readonly ConcurrentDictionary<string, NamedPipeServerStream> clients = new();
    private readonly ConcurrentDictionary<string, Pending> pending = new();
    private readonly Func<object, Task> send;
    private readonly Func<string, Task> closeSession;
    private readonly string name;
    private readonly Task accept;
    private readonly ConcurrentDictionary<Task, byte> work = new();
    private int disposed;
    private sealed record Pending(string Session, TaskCompletionSource<JsonNode?> Completion, JsonNode? RequestId, bool Notification);

    private static JsonNode? NormalizeId(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.String) return JsonValue.Create(value.GetString());
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) &&
            double.IsFinite(number) && Math.Truncate(number) == number && Math.Abs(number) <= 9007199254740991)
            return JsonValue.Create((long)number);
        return null;
    }

    internal static string PipeName(string profile) => "MagnolieOrganizer.Mcp." +
        Convert.ToHexString(SHA256.HashData(Utf8.GetBytes(Path.GetFullPath(profile).TrimEnd(Path.DirectorySeparatorChar).ToUpperInvariant())))[..40];

    internal McpLocalServer(string profile, Func<object, Task> send, Func<string, Task> closeSession)
    {
        name = PipeName(profile);
        this.send = send;
        this.closeSession = closeSession;
        accept = AcceptAsync();
    }

    private void Track(Task task)
    {
        work.TryAdd(task, 0);
        _ = task.ContinueWith(completed => { work.TryRemove(completed, out _); _ = completed.Exception; },
            CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
    }

    private async Task AcceptAsync()
    {
        while (!lifetime.IsCancellationRequested)
        {
            NamedPipeServerStream? pipe = null;
            try
            {
                pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 8, PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await pipe.WaitForConnectionAsync(lifetime.Token);
                if (clients.Count >= 8) { pipe.Dispose(); continue; }
                var session = Convert.ToHexString(RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
                clients[session] = pipe;
                Track(ClientAsync(pipe, session));
                pipe = null;
            }
            catch (Exception error) when (error is OperationCanceledException or IOException or UnauthorizedAccessException)
            {
                pipe?.Dispose();
                if (!lifetime.IsCancellationRequested) await Task.Delay(250, lifetime.Token).ConfigureAwait(ConfigureAwaitOptions.SuppressThrowing);
            }
        }
    }

    internal bool Reply(string session, string invocation, JsonElement response)
    {
        if (!clients.ContainsKey(session) || !pending.TryGetValue(invocation, out var item) || item.Session != session) return false;
        if (response.ValueKind == JsonValueKind.Null)
        {
            if (!item.Notification) return false;
        }
        else
        {
            if (item.Notification || response.ValueKind != JsonValueKind.Object ||
                !response.TryGetProperty("jsonrpc", out var version) || version.ValueKind != JsonValueKind.String || version.GetString() != "2.0" ||
                !response.TryGetProperty("id", out var responseId)) return false;
            var actualId = NormalizeId(responseId);
            if (actualId is null && responseId.ValueKind != JsonValueKind.Null || !JsonNode.DeepEquals(actualId, item.RequestId)) return false;
        }
        JsonNode? result = response.ValueKind == JsonValueKind.Null ? null : JsonNode.Parse(response.GetRawText());
        if (result is not null && Utf8.GetByteCount(result.ToJsonString()) + 1 > MaximumFrame)
            result = Error(-32000, "Product result exceeds transport limit; use a smaller page", result["id"]?.DeepClone());
        return item.Completion.TrySetResult(result);
    }

    private static JsonObject Error(int code, string message, JsonNode? id = null) => new()
    { ["jsonrpc"] = "2.0", ["id"] = id, ["error"] = new JsonObject { ["code"] = code, ["message"] = message } };

    private static async Task<string?> ReadFrameAsync(StreamReader reader, CancellationToken token)
    {
        var text = new StringBuilder();
        var character = new char[1];
        while (await reader.ReadAsync(character.AsMemory(), token) != 0)
        {
            if (character[0] == '\n')
            {
                var value = text.ToString();
                if (Utf8.GetByteCount(value) + 1 > MaximumFrame) throw new InvalidDataException("MCP frame too large");
                return value;
            }
            if (text.Length >= MaximumFrame) throw new InvalidDataException("MCP frame too large");
            text.Append(character[0]);
        }
        if (text.Length != 0) throw new InvalidDataException("Incomplete MCP frame");
        return null;
    }

    private async Task ClientAsync(NamedPipeServerStream pipe, string session)
    {
        using var writerGate = new SemaphoreSlim(1, 1);
        var own = new List<Task>();
        async Task WriteAsync(JsonNode? response)
        {
            if (response is null) return;
            var bytes = Utf8.GetBytes(response.ToJsonString() + "\n");
            await writerGate.WaitAsync(lifetime.Token);
            try { await pipe.WriteAsync(bytes, lifetime.Token); await pipe.FlushAsync(lifetime.Token); }
            finally { writerGate.Release(); }
        }
        async Task FinishAsync(string invocation, Pending item, JsonNode? message)
        {
            try
            {
                var response = await item.Completion.Task.WaitAsync(TimeSpan.FromSeconds(35), lifetime.Token);
                await WriteAsync(response);
            }
            catch (TimeoutException)
            {
                try { if (message is JsonObject obj && obj.ContainsKey("id")) await WriteAsync(Error(-32000,
                    "Product response timed out; check current state before retrying", message["id"]?.DeepClone())); }
                finally { pipe.Dispose(); }
            }
            catch (Exception error) when (error is OperationCanceledException or IOException or ObjectDisposedException) { }
            finally { pending.TryRemove(invocation, out _); slots.Release(); }
        }
        try
        {
            using var reader = new StreamReader(pipe, Utf8, false, 4096, leaveOpen: true);
            while (await ReadFrameAsync(reader, lifetime.Token) is { } frame)
            {
                JsonNode? message;
                try { message = JsonNode.Parse(frame, documentOptions: new JsonDocumentOptions { MaxDepth = 64 }); ValidateKeys(message); }
                catch (Exception error) when (error is JsonException or ArgumentException)
                { await WriteAsync(Error(-32700, "Parse error")); continue; }
                if (!slots.Wait(0))
                {
                    if (message is JsonObject obj && obj.ContainsKey("id")) await WriteAsync(Error(-32000, "Too many pending requests", obj["id"]?.DeepClone()));
                    continue;
                }
                var invocation = Convert.ToHexString(RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
                var expectedId = message is JsonObject envelope && envelope.ContainsKey("id")
                    ? NormalizeId(JsonSerializer.SerializeToElement(envelope["id"])) : null;
                var notification = message is JsonObject notice && !notice.ContainsKey("id") &&
                    notice["jsonrpc"] is JsonValue protocol && protocol.TryGetValue<string>(out var protocolVersion) && protocolVersion == "2.0" &&
                    notice["method"] is JsonValue method && method.TryGetValue<string>(out _) &&
                    (!notice.ContainsKey("params") || notice["params"] is JsonObject);
                var item = new Pending(session, new(TaskCreationOptions.RunContinuationsAsynchronously), expectedId, notification);
                pending[invocation] = item;
                try { await send(new { session, invocation, message }); }
                catch { item.Completion.TrySetResult(message is JsonObject obj && obj.ContainsKey("id")
                    ? Error(-32000, "Product interface unavailable", obj["id"]?.DeepClone()) : null); }
                own.RemoveAll(task => task.IsCompleted);
                own.Add(FinishAsync(invocation, item, message));
            }
        }
        catch (InvalidDataException) { try { await WriteAsync(Error(-32600, "MCP frame exceeds limit or is incomplete")); } catch (IOException) { } }
        catch (Exception error) when (error is OperationCanceledException or IOException or ObjectDisposedException or DecoderFallbackException) { }
        finally
        {
            clients.TryRemove(session, out _);
            foreach (var item in pending.Values.Where(item => item.Session == session)) item.Completion.TrySetResult(null);
            try { await Task.WhenAll(own); } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
            pipe.Dispose();
            try { await closeSession(session); } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException or TimeoutException or InvalidOperationException) { }
        }
    }

    private static void ValidateKeys(JsonNode? value)
    {
        // Enumerating JsonObject forces duplicate-property detection in JsonNode.
        if (value is JsonObject obj) foreach (var pair in obj) ValidateKeys(pair.Value);
        else if (value is JsonArray array) foreach (var item in array) ValidateKeys(item);
    }

    internal static async Task<int> RunStdioAsync(string profile, Stream input, Stream output, CancellationToken token)
    {
        using var pipe = new NamedPipeClientStream(".", PipeName(profile), PipeDirection.InOut,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        try
        {
            await pipe.ConnectAsync(3000, token);
            using var reader = new StreamReader(input, Utf8, false, 4096, leaveOpen: true);
            using var stop = CancellationTokenSource.CreateLinkedTokenSource(token);
            var receive = pipe.CopyToAsync(output, stop.Token);
            while (true)
            {
                var next = ReadFrameAsync(reader, stop.Token);
                if (await Task.WhenAny(next, receive) == receive)
                {
                    stop.Cancel();
                    _ = next.ContinueWith(completed => { _ = completed.Exception; }, CancellationToken.None,
                        TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
                    await receive;
                    return 1;
                }
                var frame = await next;
                if (frame is null) break;
                await pipe.WriteAsync(Utf8.GetBytes(frame + "\n"), token);
                await pipe.FlushAsync(token);
            }
            stop.Cancel();
            try { await receive; } catch (OperationCanceledException) { }
            await output.FlushAsync(token);
            return 0;
        }
        catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException or UnauthorizedAccessException or DecoderFallbackException) { return 1; }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        lifetime.Cancel();
        foreach (var pipe in clients.Values) pipe.Dispose();
        foreach (var item in pending.Values) item.Completion.TrySetCanceled();
        // GUI callbacks may be waiting on this thread; teardown must not synchronously join them.
        _ = Task.Run(async () =>
        {
            try { await accept; await Task.WhenAll(work.Keys); }
            catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
            finally { lifetime.Dispose(); slots.Dispose(); }
        });
    }
}
