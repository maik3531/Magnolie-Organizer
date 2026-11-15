using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native-only draft receive lane. No controller, source consent, provider writer
// or capability is constructed/advertised by adding this bounded origin issuer.
internal sealed partial class MagnolienbaumCoordinator
{
    private long notesReceiveGeneration;
    internal Func<JsonObject, JsonObject, NativeNotesOrigin, string, bool>? NotesOriginalReceive { get; set; }

    internal readonly record struct NotesPins(string Id, string PublicKey);
    private sealed record NotesReceiveProof(MagnolienbaumCoordinator Owner, NotesPins Peer, NotesPins Own,
        string Transport, byte[] ContentHash, long Expires, long Generation);

    internal sealed class NativeNotesOrigin(object proof)
    {
        internal (NotesPins Peer, NotesPins Own) RequireCurrent(JsonObject body, string transport)
        {
            if (proof is not NotesReceiveProof native)
                throw new InvalidOperationException("notes_original_native_fs1_origin_required");
            lock (native.Owner.gate)
            {
                var owner = native.Owner;
                var peer = owner.Partner(native.Peer.Id);
                var canonical = MagnolienbaumCrypto.Canonical(body);
                if (owner.disposed || owner.outboxPaused || !Boolean(owner.state, "an") ||
                    owner.notesReceiveGeneration != native.Generation || native.Expires <= Stopwatch.GetTimestamp() ||
                    new NotesPins(String(owner.state, "kennung"), String(owner.state, "oeffentlich")) != native.Own ||
                    peer is null || new NotesPins(String(peer, "kennung"), String(peer, "oeffentlich")) != native.Peer ||
                    !Boolean(peer, "bestaetigt") || !Boolean(peer, "vertraut") || !Boolean(peer, "kontaktSync") ||
                    transport != native.Transport || canonical.Length > 256 * 1024 ||
                    !CryptographicOperations.FixedTimeEquals(SHA256.HashData(canonical), native.ContentHash))
                    throw new InvalidOperationException("notes_original_fs1_origin_changed");
                return (native.Peer, native.Own);
            }
        }
    }

    private static bool IsNotesOriginalDraft(string kind) => kind is "kontakt_original_aushandlung" or
        "kontakt_original_export" or "kontakt_original_ergebnis" or "kontakt_original_abschlussstatus" or
        "kontakt_original_anfrage" or "kontakt_original_saveack" or "kontakt_original_statusanfrage";

    private void ReceiveNotesOriginal(JsonObject peer, JsonObject body, string transport, IncomingFsSession incoming)
    {
        // Called by real decrypted FS1 receive under the existing tree gate.
        // The explicitly injected native callback MUST stage only: no book lock,
        // file/key access, writer waits, renderer dispatch or networking here.
        var receive = NotesOriginalReceive;
        var setup = notesSetupReceive;
        if (receive is null && setup is null || String(body, "art") is not ("kontakt_original_aushandlung" or
                "kontakt_original_export" or "kontakt_original_ergebnis" or "kontakt_original_abschlussstatus"))
            throw new InvalidOperationException("notes_original_native_receiver_required");
        var canonical = MagnolienbaumCrypto.Canonical(body);
        if (canonical.Length > 256 * 1024)
            throw new InvalidDataException("notes_original_receive_budget");
        var proof = new NotesReceiveProof(this, new(incoming.PartnerId, incoming.PartnerPublicKey),
            new(incoming.OwnId, incoming.OwnPublicKey), transport, SHA256.HashData(canonical), incoming.Expires, incoming.NotesGeneration);
        var origin = new NativeNotesOrigin(proof);
        origin.RequireCurrent(body, transport);
        var setupStaged = String(body, "art") is ("kontakt_original_aushandlung" or "kontakt_original_export") &&
            setup?.Invoke(body.DeepClone().AsObject(), origin, transport) == true;
        // Our setup challenge is exclusive. Exports may also reach an already
        // granted worker; results/terminal history never go through setup.
        var exclusive = setupStaged && String(body, "art") == "kontakt_original_aushandlung";
        var workerStaged = !exclusive && receive?.Invoke(peer.DeepClone().AsObject(), body.DeepClone().AsObject(), origin, transport) == true;
        if (!setupStaged && !workerStaged)
            throw new InvalidOperationException("notes_original_receive_held");
        origin.RequireCurrent(body, transport);
        WakeNotesMaintenance(); // Bounded semaphore release only, no native/file/network work here.
    }
}
