using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeClipboardReceiveProposal(string Id, string DeviceId, string Text, bool Automatic);

internal sealed partial class KdeConnectDirectBackend
{
    internal const string ClipboardPacket = "kdeconnect.clipboard", ClipboardConnectPacket = "kdeconnect.clipboard.connect";
    private sealed record ClipboardPreferences(bool Enabled, string Device, bool Automatic, Func<bool> Permitted);
    private sealed record ClipboardOffer(KdeClipboardReceiveProposal Proposal, Connection Connection,
        ClipboardPreferences Preferences, DateTimeOffset Expires);
    private ClipboardPreferences clipboardPreferences = new(false, "", false, () => false);
    private readonly Dictionary<string, ClipboardOffer> clipboardOffers = new(StringComparer.Ordinal);
    private Connection? clipboardTimestampConnection;
    private long clipboardTimestamp = -1;
    internal event Action<KdeClipboardReceiveProposal>? ClipboardProposed;

    private bool ClipboardReceiveAdvertised
    {
        get
        {
            var preferences = Volatile.Read(ref clipboardPreferences);
            try { return !disposed && preferences.Enabled && preferences.Permitted(); }
            catch (Exception) { return false; }
        }
    }

    internal void ConfigureClipboardReceive(bool enabled, string device, bool automatic, Func<bool>? permitted = null)
    {
        lock (activeGate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (enabled && (permitted?.Invoke() != true || !store.LoadPeers().Any(peer => peer.Paired && peer.Id == device)))
                throw new InvalidOperationException("incoming_selected_paired_device_required");
            Volatile.Write(ref clipboardPreferences, new(enabled, enabled ? device : "", enabled && automatic, permitted ?? (() => false)));
            clipboardOffers.Clear();
        }
        if (activeDiscovery) BroadcastIdentity();
    }

    private bool ClipboardConnectionCurrent(Connection connection, ClipboardPreferences preferences) =>
        !disposed && ReferenceEquals(preferences, clipboardPreferences) && preferences.Enabled && preferences.Permitted() &&
        preferences.Device == connection.Identity.DeviceId && !connection.Closed &&
        active.TryGetValue(preferences.Device, out var live) && ReferenceEquals(live, connection) &&
        store.LoadPeers().Any(peer => peer.Paired && peer.Id == preferences.Device &&
            peer.CertificatePin == KdeConnectProtocol.CertificatePin(connection.Certificate));

    private void HandleClipboardPacket(Connection connection, KdeConnectPacket packet)
    {
        KdeClipboardReceiveProposal? proposal = null;
        lock (activeGate)
        {
            var preferences = clipboardPreferences;
            if (!ClipboardConnectionCurrent(connection, preferences) ||
                !connection.Identity.OutgoingCapabilities.Contains(packet.Type)) return;
            var connect = packet.Type == ClipboardConnectPacket;
            if (packet.PayloadSize is not null || packet.Body.Count != (connect ? 2 : 1) ||
                packet.Body["content"] is not JsonValue value || !value.TryGetValue<string>(out var text) ||
                new UTF8Encoding(false, true).GetByteCount(text) > 64 * 1024)
                throw new InvalidDataException("incoming_clipboard_invalid");
            if (connect)
            {
                if (packet.Body["timestamp"] is not JsonValue stamp || !stamp.TryGetValue<long>(out var timestamp) || timestamp < 0)
                    throw new InvalidDataException("incoming_clipboard_timestamp_invalid");
                if (!ReferenceEquals(clipboardTimestampConnection, connection))
                { clipboardTimestampConnection = connection; clipboardTimestamp = -1; }
                if (timestamp == 0 || timestamp <= clipboardTimestamp) return;
                clipboardTimestamp = timestamp;
            }
            foreach (var expired in clipboardOffers.Where(entry => entry.Value.Expires <= DateTimeOffset.UtcNow).Select(entry => entry.Key).ToArray())
                clipboardOffers.Remove(expired);
            if (clipboardOffers.Count >= 8) return;
            proposal = new(Guid.NewGuid().ToString("N"), preferences.Device, text, preferences.Automatic);
            clipboardOffers.Add(proposal.Id, new(proposal, connection, preferences, DateTimeOffset.UtcNow.AddMinutes(5)));
        }
        SafeInvoke(ClipboardProposed, proposal);
    }

    internal KdeClipboardReceiveProposal? CurrentClipboardReceiveProposal(string id)
    {
        lock (activeGate)
        {
            if (!clipboardOffers.TryGetValue(id, out var offer)) return null;
            if (offer.Expires <= DateTimeOffset.UtcNow || !ClipboardConnectionCurrent(offer.Connection, offer.Preferences))
            { clipboardOffers.Remove(id); return null; }
            return offer.Proposal;
        }
    }

    internal string? TakeClipboardReceive(string id, bool accept)
    {
        lock (activeGate)
        {
            var proposal = CurrentClipboardReceiveProposal(id);
            clipboardOffers.Remove(id);
            return accept ? proposal?.Text : null;
        }
    }
}
