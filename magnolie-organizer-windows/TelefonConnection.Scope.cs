using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private PhoneContentScope.Session? receivedContentScope;
    private string ScopePublicKey => Convert.ToHexString(peer.PublicKey);
    private bool ContentScopeSelected
    {
        get
        {
            var settings = store.SharedSettings(peer.Id, peer.PublicKey);
            return settings is not null && SharedSyncSettings.Effective(settings)["content_mode"]?.GetValue<string>() == "phone_scope";
        }
    }

    private bool ContentScopeAuthorized
    {
        get
        {
            if (!SharedControlsReady) return false;
            var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (current is null || !PhoneContentScope.Supported(SharedLocalCapabilities(), current.Capabilities)) return false;
            if (new[] { "personal_notes_sync", "personal_tasks_sync" }.Any(name =>
                    store.LocalGrants()[name]?.GetValue<bool>() != true || current.Grants[name]?.GetValue<bool>() != true)) return false;
            return ContentScopeSelected;
        }
    }

    private bool ContentScopeControlsReady => ContentScopeAuthorized && SharedSettingsReady;

    private void RequireContentScopeControls()
    {
        if (!ContentScopeAuthorized) throw new InvalidOperationException("Current content scope is unauthorized.");
        if (!SharedSettingsReady) throw new IOException("Shared preference agreement is pending.");
    }

    internal JsonObject CurrentContentScope(JsonObject claimed)
    {
        RequireContentScopeControls();
        if (receivedContentScope is null)
            throw new InvalidOperationException("Current content scope is unavailable.");
        // The session object is owned by this TelefonConnection, not a persisted global map.
        return receivedContentScope.Current(peer.Id, ScopePublicKey, 0, claimed);
    }

    internal JsonObject? DataContentScope(string kind, JsonObject body)
    {
        if (body["run_id"] is not JsonValue id || !id.TryGetValue<string>(out var runId)) return null;
        var reference = new PersonalSyncStore(store).ScopedRunReference(peer.Id, peer.PublicKey, runId, Now());
        if (reference is null) return null;
        if (kind is not ("personal_sync.request" or "personal_sync.batch" or "personal_sync.report" or
            "personal_sync.attachment_request" or "personal_sync.attachment_chunk" or "personal_sync.attachment_result"))
            throw new InvalidOperationException("Scoped runs do not transmit deletion decisions.");
        var manifest = CurrentContentScope(reference);
        if (kind == "personal_sync.batch")
        {
            var notes = manifest["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            var tasks = manifest["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            foreach (var value in body["records"]!.AsArray())
            {
                var record = value!.AsObject(); var type = record["kind"]!.GetValue<string>(); var recordId = record["id"]!.GetValue<string>();
                if (type == "note" && !notes.Contains(recordId) || type == "task" && !tasks.Contains(recordId))
                    throw new InvalidOperationException("Record outside current phone membership.");
            }
        }
        return manifest;
    }

    private async Task HandleScopedDataAsync(JsonObject message)
    {
        TelefonMessageContract.ValidateMessage(message, Now(), true);
        var id = message["message_id"]!.GetValue<string>(); var wrapped = message["body"]!.AsObject();
        string error;
        try
        {
            JsonObject inner;
            await store.NotePolicyGate.WaitAsync(cancellation);
            try
            {
                if (TelefonProtocolContract.Integer(message["expires_ms"]) <= Now()) throw new InvalidDataException("Scoped message expired.");
                var manifest = CurrentContentScope(wrapped["scope"]!.AsObject());
                var (kind, body) = PhoneContentScope.Unwrap(wrapped, manifest);
                inner = message.DeepClone().AsObject(); inner["kind"] = kind; inner["body"] = body;
                if (store.HasIncomingReceipt(peer.Id, id) && !store.ReceivedMatches(peer.Id, inner))
                    throw new InvalidDataException("Conflicting scoped message identity.");
                var runs = new PersonalSyncStore(store);
                if (kind == "personal_sync.request")
                    runs.RememberScopedRun(peer.Id, peer.PublicKey, body, wrapped["scope"]!.AsObject(), Now(), TelefonProtocolContract.Integer(message["expires_ms"]));
                else if (!JsonNode.DeepEquals(wrapped["scope"], runs.ScopedRunReference(peer.Id, peer.PublicKey, body["run_id"]!.GetValue<string>(), Now())))
                    throw new InvalidOperationException("Scoped run binding missing or different.");
            }
            finally { store.NotePolicyGate.Release(); }
            await HandlePlainBoundAsync(inner, wrapped["scope"]!.AsObject());
            return;
        }
        catch (InvalidDataException) { error = "invalid_schema"; }
        catch (InvalidOperationException) { error = "not_granted"; }
        catch (IOException) { error = "temporary_failure"; }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = id, ["status"] = "rejected", ["error"] = error });
    }

    private Task SendScopedOrPlainAsync(JsonObject message)
    {
        var manifest = DataContentScope(message["kind"]!.GetValue<string>(), message["body"]!.AsObject());
        if (manifest is null)
        {
            if (ContentScopeSelected && TelefonProtocolContract.PersonalKinds.Contains(message["kind"]!.GetValue<string>()) &&
                message["kind"]!.GetValue<string>() != "personal_sync.settings")
                throw new InvalidOperationException("Scoped preference does not permit raw content fallback.");
            return SendPlainAsync(message);
        }
        var wrapped = message.DeepClone().AsObject(); wrapped["kind"] = PhoneContentScope.DataKind;
        wrapped["body"] = PhoneContentScope.Wrap(message["kind"]!.GetValue<string>(), message["body"]!.AsObject(), manifest);
        return SendPlainAsync(wrapped);
    }

    private async Task HandleContentScopeAsync(JsonObject message)
    {
        var now = Now(); TelefonMessageContract.ValidateMessage(message, now, true);
        var ack = store.CommitIncoming(peer.Id, message, now, (_, _) => ContentScopeAuthorized ? null : "not_granted",
            deferAcceptance: true, reauthorizeDuplicates: true);
        if (ack.Status is "accepted" or "duplicate" && !store.ReceivedMatches(peer.Id, message))
            ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema");
        try
        {
            if (ack.Status is "accepted" or "duplicate")
            {
                await store.NotePolicyGate.WaitAsync(cancellation);
                try
                {
                    RequireContentScopeControls();
                    if (TelefonProtocolContract.Integer(message["expires_ms"]) <= now) throw new InvalidDataException("Expired scope frame.");
                    receivedContentScope ??= new PhoneContentScope.Session(peer.Id, ScopePublicKey, 0);
                    receivedContentScope.Receive(peer.Id, ScopePublicKey, 0, message["body"]!.AsObject());
                    if (ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
                }
                finally { store.NotePolicyGate.Release(); }
            }
        }
        catch (InvalidDataException) { ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema"); }
        catch (IOException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (InvalidOperationException) { ack = new TelefonAck(ack.MessageId, "rejected", "not_granted"); }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
    }
}
