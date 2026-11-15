using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class MagnolienbaumCoordinator
{
    internal sealed record NotesSetupPeerView(string Id, string PublicKey, string Label);
    private sealed record NotesSetupPeerProof(MagnolienbaumCoordinator Owner, NotesPins Peer, NotesPins Own,
        long Generation, string Epoch, byte[] OwnIdentityHash);
    internal sealed class NativeNotesSetupPeer(object proof)
    {
        private NotesSetupPeerProof Native() => proof as NotesSetupPeerProof ?? throw new InvalidOperationException("notes_setup_native_peer_required");
        internal (NotesPins Peer, NotesPins Own) RequireCurrent(MagnolienbaumCoordinator owner)
        {
            var native = Native();
            if (!ReferenceEquals(native.Owner, owner)) throw new InvalidOperationException("notes_setup_peer_owner_changed");
            lock (owner.gate)
            {
                var peer = owner.Partner(native.Peer.Id);
                if (owner.disposed || owner.outboxPaused || !Boolean(owner.state, "an") ||
                    owner.notesReceiveGeneration != native.Generation || String(owner.state, "syncEpoch") != native.Epoch ||
                    new NotesPins(String(owner.state, "kennung"), String(owner.state, "oeffentlich")) != native.Own ||
                    !CryptographicOperations.FixedTimeEquals(SHA256.HashData(Encoding.UTF8.GetBytes(String(owner.state, "geheim"))), native.OwnIdentityHash) ||
                    peer is null || new NotesPins(String(peer, "kennung"), String(peer, "oeffentlich")) != native.Peer ||
                    !Boolean(peer, "bestaetigt") || !Boolean(peer, "vertraut") || !Boolean(peer, "kontaktSync"))
                    throw new InvalidOperationException("notes_setup_native_peer_context_changed");
                return (native.Peer, native.Own);
            }
        }
        internal NotesSetupPeerView Display()
        {
            var native = Native();
            lock (native.Owner.gate)
            {
                RequireCurrent(native.Owner);
                return new(native.Peer.Id, native.Peer.PublicKey, String(native.Owner.Partner(native.Peer.Id)!, "name"));
            }
        }
    }

    // Read ONLY the already loaded coordinator. No identity/store/service factory.
    internal IReadOnlyList<NativeNotesSetupPeer> CaptureNotesSetupPeers()
    {
        lock (gate)
        {
            if (disposed || outboxPaused || !Boolean(state, "an") || String(state, "geheim").Length == 0 ||
                notesSetupReceive is not null || notesSetupStop is not null)
                throw new InvalidOperationException("notes_setup_existing_active_tree_required");
            var own = new NotesPins(String(state, "kennung"), String(state, "oeffentlich"));
            var peers = (state["partner"] as JsonArray ?? []).OfType<JsonObject>()
                .Where(peer => Boolean(peer, "bestaetigt") && Boolean(peer, "vertraut") && Boolean(peer, "kontaktSync")).ToArray();
            if (peers.Length is < 1 or > 32 || peers.Select(peer => String(peer, "kennung")).Distinct(StringComparer.Ordinal).Count() != peers.Length)
                throw new InvalidOperationException("notes_setup_native_peer_catalog_unavailable");
            return peers.Select(peer => new NativeNotesSetupPeer(new NotesSetupPeerProof(this,
                new(String(peer, "kennung"), String(peer, "oeffentlich")), own, notesReceiveGeneration, String(state, "syncEpoch"),
                SHA256.HashData(Encoding.UTF8.GetBytes(String(state, "geheim")))))).ToArray();
        }
    }
}
