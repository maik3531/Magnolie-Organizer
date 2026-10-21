using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    internal sealed class CallPreparation(Action before, Action receiptWritten)
    {
        internal void Before() => before();
        internal void ReceiptWritten() => receiptWritten();
    }
    private sealed class CallActorError : Exception
    {
        internal string Code { get; }
        internal CallActorError(string code) : base(code) { Code = code; }
    }
    private sealed class CallActorJob
    {
        internal required string Id, Token, PeerId, Fingerprint, Operation, Command;
        internal required JsonObject Body, Authority;
        internal required TelefonConnection Connection;
        internal string Phase = "reserved", Error = "none";
        internal long Deadline = Environment.TickCount64 + 15000, RetainUntil = Environment.TickCount64 + 1800000;
        internal bool DispatchStarted, TransportDispatched, ReceiptPersisted, CancelRequested, WorkerActive;
        internal JsonObject? Result;
    }
    private readonly Dictionary<string, CallActorJob> callActors = new(StringComparer.Ordinal);
    private readonly Dictionary<string, CallActorJob> callActorReferences = new(StringComparer.Ordinal);
    private static bool CallActorActive(CallActorJob job) => job.Phase is "reserved" or "dispatching" or "awaiting_phone";
    private static string CallActorKind(string command) => command == "dial" ? "dial_request.command" : command + "_call.command";
    private static void FailCallActor(CallActorJob job, string code)
    { if (job.Phase is not ("reported" or "cancelled")) { job.Phase = "failed"; job.Error = code; } }

    private void ReapCallActors()
    {
        var now = Environment.TickCount64;
        foreach (var (id, job) in callActors.ToArray())
        {
            if (CallActorActive(job) && now >= job.Deadline) FailCallActor(job, job.DispatchStarted ? "native_timeout_after_dispatch" : "native_timeout");
            if (now >= job.RetainUntil && !job.WorkerActive)
            {
                callActors.Remove(id);
                if (callActorReferences.GetValueOrDefault(job.Operation) == job) callActorReferences.Remove(job.Operation);
            }
        }
    }
    private CallActorJob RequireCallActor(JsonObject request)
    {
        var id = McpText(request, "actorId"); var token = McpText(request, "ownerToken");
        if (!callActors.TryGetValue(id, out var job) || !Regex.IsMatch(token, "\\A[a-f0-9]{64}\\z") ||
            !CryptographicOperations.FixedTimeEquals(Convert.FromHexString(token), Convert.FromHexString(job.Token)) ||
            McpText(request, "peerId") != job.PeerId || !McpText(request, "fingerprint").Equals(job.Fingerprint, StringComparison.OrdinalIgnoreCase))
            throw new CallActorError("not_found");
        return job;
    }
    private void GuardCallActor(CallActorJob job, bool full = false)
    {
        if (!CallActorActive(job) || job.CancelRequested) throw new CallActorError("cancelled");
        if (Environment.TickCount64 >= job.Deadline) throw new CallActorError(job.DispatchStarted ? "native_timeout_after_dispatch" : "native_timeout");
        CallAuthoritySnapshot snapshot;
        try { snapshot = CaptureCallAuthority(job.PeerId, job.Fingerprint); }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or McpRequestException or McpConflictException)
        { throw new CallActorError("source_changed"); }
        var current = snapshot.Authority.DeepClone().AsObject(); var expected = job.Authority.DeepClone().AsObject();
        if (!full) { current.Remove("call"); expected.Remove("call"); }
        if (snapshot.Connection != job.Connection || !JsonNode.DeepEquals(current, expected)) throw new CallActorError("source_changed");
    }
    private static JsonObject CallActorSummary(CallActorJob job) => new() {
        ["actor_id"] = job.Id, ["operation_id"] = job.Operation, ["command"] = job.Command, ["phase"] = job.Phase,
        ["dispatch_started"] = job.DispatchStarted, ["transport_dispatched"] = job.TransportDispatched, ["receipt_persisted"] = job.ReceiptPersisted,
        ["phone_result_received"] = job.Result is not null, ["phone_result"] = job.Result?.DeepClone(), ["cancel_requested"] = job.CancelRequested,
        ["remote_recall_confirmed"] = false, ["native_outcome_unknown"] = job.DispatchStarted && job.Result is null && job.Phase is "failed" or "cancelled",
        ["error_code"] = job.Error };

    private JsonObject ExecuteMcpCallActor(JsonObject request)
    {
        try
        {
            lock (gate)
            {
                ReapCallActors(); var action = McpText(request, "action", true);
                if (action == "call_actor_create")
                {
                    TelefonProtocolContract.ExactObject(request, "action", "peerId", "fingerprint", "sourceRevision", "operationId", "command", "destination", "callRef", "callRevision");
                    var id = McpText(request, "peerId", true); var fingerprint = McpText(request, "fingerprint", true);
                    var snapshot = CaptureCallAuthority(id, fingerprint); var source = McpText(request, "sourceRevision", true);
                    if (!Regex.IsMatch(source, "\\A[a-f0-9]{64}\\z")) throw new InvalidDataException();
                    if (source != snapshot.Context["source_revision"]!.GetValue<string>()) throw new CallActorError("source_changed");
                    var command = McpText(request, "command", true);
                    if (command is not ("dial" or "answer" or "end")) throw new InvalidDataException();
                    var permission = command == "dial" ? "dial_request" : command + "_call";
                    var scopedEnd = command == "end" && snapshot.Context["call"]?["scope"]?.GetValue<string>() == "outgoing_request" &&
                        snapshot.Context["call"]?["state"]?.GetValue<string>() == "offhook" && RemoteCapability(snapshot.Peer, "end_call");
                    if (snapshot.Context["permissions"]![permission]?.GetValue<bool>() != true && !scopedEnd) throw new CallActorError("not_granted");
                    var operation = McpText(request, "operationId", true); var destination = McpText(request, "destination");
                    var reference = McpText(request, "callRef"); var revision = McpText(request, "callRevision");
                    JsonObject body;
                    if (command == "dial")
                    {
                        if (reference.Length != 0 || revision.Length != 0) throw new InvalidDataException();
                        body = new() { ["to"] = destination, ["client_ref"] = operation };
                    }
                    else
                    {
                        if (destination.Length != 0 || snapshot.Context["call"] is not JsonObject observed || observed["call_ref"]?.GetValue<string>() != reference ||
                            observed["revision"]?.GetValue<string>() != revision) throw new CallActorError("not_granted");
                        if (!Regex.IsMatch(revision, "\\A[1-9][0-9]{0,18}\\z") || !long.TryParse(revision, NumberStyles.None, CultureInfo.InvariantCulture, out var counter) || counter <= 0)
                            throw new InvalidDataException();
                        body = new() { ["command_ref"] = operation, ["call_ref"] = reference,
                            ["expected_state"] = command == "answer" ? "ringing" : observed["state"]!.DeepClone() };
                        if (command == "end") body["expected_revision"] = counter;
                    }
                    TelefonCallContract.Validate(CallActorKind(command), body);
                    if (callActorReferences.ContainsKey(operation) || store.HasCommand(id, operation)) throw new CallActorError("conflict");
                    if (callActors.Count >= 128 || callActors.Values.Count(value => CallActorActive(value) || value.WorkerActive) >= 4) throw new CallActorError("native_busy");
                    var job = new CallActorJob { Id = Guid.NewGuid().ToString("D"), Token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(),
                        PeerId = id, Fingerprint = fingerprint, Operation = operation, Command = command, Body = body.DeepClone().AsObject(),
                        Authority = snapshot.Authority.DeepClone().AsObject(), Connection = snapshot.Connection };
                    callActors[job.Id] = job; callActorReferences[operation] = job;
                    return new() { ["ok"] = true, ["callActorHandle"] = new JsonObject { ["actor_id"] = job.Id, ["owner_token"] = job.Token }, ["callActor"] = CallActorSummary(job) };
                }
                if (action is not ("call_actor_start" or "call_actor_status" or "call_actor_cancel")) throw new InvalidDataException();
                TelefonProtocolContract.ExactObject(request, "action", "peerId", "fingerprint", "actorId", "ownerToken");
                var actor = RequireCallActor(request);
                if (action == "call_actor_cancel")
                {
                    if (CallActorActive(actor)) { actor.Phase = "cancelled"; actor.CancelRequested = true; actor.Error = "cancelled"; }
                }
                else if (action == "call_actor_start")
                {
                    GuardCallActor(actor, true);
                    if (actor.Phase != "reserved") throw new CallActorError("conflict");
                    actor.Phase = "dispatching"; actor.Deadline = Environment.TickCount64 + 15000; actor.WorkerActive = true;
                    Track(McpServiceTask(() => RunCallActorAsync(actor)));
                }
                else if (CallActorActive(actor))
                {
                    try { GuardCallActor(actor); } catch (CallActorError error) { FailCallActor(actor, error.Code); }
                }
                return new() { ["ok"] = true, ["callActor"] = CallActorSummary(actor) };
            }
        }
        catch (CallActorError error) { return new() { ["ok"] = false, ["code"] = error.Code }; }
        catch (Exception error) when (error is InvalidDataException or FormatException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (Exception error) when (error is McpRequestException or McpConflictException or InvalidOperationException) { return new() { ["ok"] = false, ["code"] = "not_granted" }; }
    }

    private async Task RunCallActorAsync(CallActorJob job)
    {
        try
        {
            var preparation = new CallPreparation(() => GuardCallActor(job, true), () => job.ReceiptPersisted = true);
            if (job.Command == "dial") await RequestDialAsync(job.PeerId, job.Body["to"]!.GetValue<string>(), job.Operation, "mcp", preparation);
            else if (job.Command == "answer") await RequestAnswerAsync(job.PeerId, job.Body["call_ref"]!.GetValue<string>(), job.Operation, "mcp", preparation);
            else await RequestEndCallAsync(job.PeerId, job.Body["call_ref"]!.GetValue<string>(), job.Body["expected_revision"]!.GetValue<long>(), job.Operation, "mcp", preparation);
            lock (gate) if (job.Phase == "dispatching") FailCallActor(job, "source_changed");
        }
        catch (CallActorError error) { lock (gate) FailCallActor(job, error.Code); }
        catch (Exception error) when (error is IOException or InvalidOperationException or InvalidDataException or Microsoft.Data.Sqlite.SqliteException or OperationCanceledException)
        { lock (gate) FailCallActor(job, job.DispatchStarted ? "native_operation_failed_after_dispatch" : "native_operation_failed"); }
        finally { lock (gate) job.WorkerActive = false; }
    }

    private bool ClaimPrivateCallActor(TelefonConnection source, TelefonPeer peer, JsonObject message)
    {
        ReapCallActors(); var body = message["body"]!.AsObject();
        var reference = body[message["kind"]?.GetValue<string>() == "dial_request.command" ? "client_ref" : "command_ref"]!.GetValue<string>();
        if (!callActorReferences.TryGetValue(reference, out var job) || job.Phase != "dispatching" || job.DispatchStarted || job.PeerId != peer.Id || job.Connection != source ||
            message["kind"]?.GetValue<string>() != CallActorKind(job.Command) || !JsonNode.DeepEquals(body, job.Body) || store.CommandOrigin(peer.Id, reference) != "mcp") return false;
        GuardCallActor(job, true); job.DispatchStarted = true; job.ReceiptPersisted = true; job.Phase = "awaiting_phone"; return true;
    }
    private void PrivateCallActorTransportSent(JsonObject message)
    {
        lock (gate)
        {
            var body = message["body"]!.AsObject(); var reference = body[message["kind"]?.GetValue<string>() == "dial_request.command" ? "client_ref" : "command_ref"]!.GetValue<string>();
            if (callActorReferences.TryGetValue(reference, out var job)) job.TransportDispatched = true;
        }
    }
    internal void ReceivePrivateCallActorResult(TelefonConnection source, TelefonPeer peer, string kind, JsonObject body)
    {
        lock (gate)
        {
            ReapCallActors(); var reference = body[kind == "dial_request.result" ? "client_ref" : "command_ref"]!.GetValue<string>();
            if (!callActorReferences.TryGetValue(reference, out var job) || job.Phase != "awaiting_phone" || !job.DispatchStarted || source != job.Connection || peer.Id != job.PeerId ||
                Convert.ToBase64String(peer.PublicKey) != job.Authority["key"]!.GetValue<string>() || kind != CallActorKind(job.Command).Replace(".command", ".result", StringComparison.Ordinal) ||
                job.Command != "dial" && body["call_ref"]?.GetValue<string>() != job.Body["call_ref"]?.GetValue<string>()) return;
            try { GuardCallActor(job); } catch (CallActorError error) { FailCallActor(job, error.Code); return; }
            job.Result = body.DeepClone().AsObject(); job.Phase = "reported";
        }
    }
}
