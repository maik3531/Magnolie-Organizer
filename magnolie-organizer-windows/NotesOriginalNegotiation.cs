using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native protocol support only: not a source grant, writer witness, durable
// request nonce or production sender. Short-lived real origins stay short-lived.
internal sealed class NotesOriginalNegotiation
{
    private readonly object gate = new();
    private readonly MagnolienbaumCoordinator.NotesPins peer, own;
    private readonly string challenge = Guid.NewGuid().ToString();
    private bool active = true;
    private Offer? offer;
    private sealed record Offer(JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport);

    internal NotesOriginalNegotiation(MagnolienbaumCoordinator.NotesPins peer, MagnolienbaumCoordinator.NotesPins own)
    {
        if (string.IsNullOrEmpty(peer.Id) || string.IsNullOrEmpty(peer.PublicKey) ||
            string.IsNullOrEmpty(own.Id) || string.IsNullOrEmpty(own.PublicKey))
            throw new ArgumentException("notes_original_native_protocol_pins_required");
        this.peer = peer; this.own = own;
    }

    internal JsonObject Probe()
    {
        lock (gate)
        {
            if (!active) throw new InvalidOperationException("notes_original_protocol_cancelled");
            return new() { ["art"] = "kontakt_original_aushandlung", ["fassung"] = 1,
                ["challenge"] = challenge, ["antwort"] = false, ["profil"] = "notes-original-return-draft1" };
        }
    }

    internal (MagnolienbaumCoordinator.NotesPins Peer, MagnolienbaumCoordinator.NotesPins Own) NativeProbePins()
    {
        lock (gate)
        {
            if (!active) throw new InvalidOperationException("notes_original_protocol_cancelled");
            return (peer, own);
        }
    } // Support probe only, never source permission.

    internal void Accept(JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport)
    {
        var expected = Probe(); expected["antwort"] = true;
        var owned = body.DeepClone().AsObject();
        if (!MagnolienbaumCrypto.Canonical(expected).AsSpan().SequenceEqual(MagnolienbaumCrypto.Canonical(owned)) ||
            origin.RequireCurrent(owned, transport) != (peer, own))
            throw new InvalidOperationException("notes_original_protocol_offer_changed");
        origin.RequireCurrent(owned, transport);
        lock (gate)
        {
            if (!active) throw new InvalidOperationException("notes_original_protocol_cancelled");
            offer = new(owned, origin, transport);
        }
        RequireCurrent();
    }

    internal (MagnolienbaumCoordinator.NotesPins Peer, MagnolienbaumCoordinator.NotesPins Own) RequireCurrent()
    {
        Offer current;
        lock (gate)
        {
            if (!active || offer is null) throw new InvalidOperationException("notes_original_protocol_not_negotiated");
            current = offer;
        }
        if (current.Origin.RequireCurrent(current.Body, current.Transport) != (peer, own))
            throw new InvalidOperationException("notes_original_protocol_offer_changed");
        lock (gate)
            if (!active || !ReferenceEquals(offer, current))
                throw new InvalidOperationException("notes_original_protocol_offer_changed");
        return (peer, own);
    }

    internal void Cancel()
    { lock (gate) { active = false; offer = null; } }
}
