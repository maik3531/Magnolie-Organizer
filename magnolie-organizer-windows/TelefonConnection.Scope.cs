using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private PhoneContentScope.Session? receivedContentScope;
    private string ScopePublicKey => Convert.ToHexString(peer.PublicKey);
    private bool ContentScopeControlsReady
    {
        get
        {
            if (!SharedSettingsReady) return false;
            var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (current is null || !PhoneContentScope.Supported(SharedLocalCapabilities(), current.Capabilities)) return false;
            if (new[] { "personal_notes_sync", "personal_tasks_sync" }.Any(name =>
                    store.LocalGrants()[name]?.GetValue<bool>() != true || current.Grants[name]?.GetValue<bool>() != true)) return false;
            var settings = store.SharedSettings(peer.Id, peer.PublicKey);
            return settings is not null && SharedSyncSettings.Effective(settings)["content_mode"]?.GetValue<string>() == "phone_scope";
        }
    }

    internal JsonObject CurrentContentScope(JsonObject claimed)
    {
        if (!ContentScopeControlsReady || receivedContentScope is null)
            throw new InvalidOperationException("Current content scope is unavailable.");
        // The session object is owned by this TelefonConnection, not a persisted global map.
        return receivedContentScope.Current(peer.Id, ScopePublicKey, 0, claimed);
    }

    private async Task HandleContentScopeAsync(JsonObject message)
    {
        var now = Now(); TelefonMessageContract.ValidateMessage(message, now, true);
        var ack = store.CommitIncoming(peer.Id, message, now, (_, _) => ContentScopeControlsReady ? null : "not_granted",
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
                    if (!ContentScopeControlsReady) throw new InvalidOperationException("not_granted");
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
