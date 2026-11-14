using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalSavedAckIntents
{
    private sealed record HistoryProof(NotesOriginalSavedAckIntents Store, NotesOriginalChoiceStore Consent,
        string Key, string Identity, string FrameHash, long Generation);
    internal sealed class HistoryQuery(object proof)
    {
        private HistoryProof Native() => proof as HistoryProof ?? throw new InvalidOperationException("notes_ack_private_history_query_required");
        internal object RequireOwner(NotesOriginalSavedAckIntents store)
        {
            var native = Native();
            if (!ReferenceEquals(native.Store, store)) throw new InvalidOperationException("notes_ack_owned_history_query_required");
            return native;
        }
        internal JsonObject Request(NotesOriginalNegotiation protocol)
        {
            var native = Native(); var record = native.Store.RequireHistory(native, protocol);
            var body = new JsonObject { ["art"] = "kontakt_original_statusanfrage", ["fassung"] = 1 };
            foreach (var name in new[] { "request_id", "request_sha256", "share_id", "before_basis", "target_sha256" })
                body[name] = record["result"]![name]!.DeepClone();
            return body; // Target-free and no ACK authority.
        }
    }

    private sealed record RestoredProof(HistoryProof History, JsonObject Result, MagnolienbaumCoordinator.NativeNotesOrigin Origin,
        string Transport, NotesOriginalNegotiation Protocol);
    internal sealed class RestoredAck(object proof)
    {
        private RestoredProof Native() => proof as RestoredProof ?? throw new InvalidOperationException("notes_ack_fresh_native_reauthorization_required");
        internal JsonObject Body()
        {
            var native = Native(); var record = native.History.Store.RequireRestored(native);
            var body = record["result"]!.DeepClone().AsObject(); body["art"] = "kontakt_original_saveack";
            body["desktop_sha256"] = record["saved_book"]![2]!.DeepClone(); return body;
        }
        internal bool TerminalConfirmed()
        {
            var native = Native(); native.History.Store.RequireRestored(native);
            return NotesOriginalSchema.Text(native.Result, "phase") == "settled";
        } // Observation only: does not install mappings or release a physical hold.
    }

    internal RestoredAck Reauthorize(HistoryQuery query, JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin,
        string transport, NotesOriginalNegotiation protocol)
    {
        // Deferred native worker only, never receive: this reads private history
        // and current book/source state. The receive callback stages body/origin.
        var history = (HistoryProof)query.RequireOwner(this);
        var proof = new RestoredProof(history, body.DeepClone().AsObject(), origin, transport, protocol);
        RequireRestored(proof); return new(proof);
    }

    private JsonObject RequireRestored(RestoredProof proof)
    {
        var record = RequireHistory(proof.History, proof.Protocol);
        if (proof.Origin.RequireCurrent(proof.Result, proof.Transport) != proof.Protocol.RequireCurrent())
            throw new InvalidOperationException("notes_ack_fresh_result_pins_changed");
        var expected = record["result"]!.DeepClone().AsObject();
        if (NotesOriginalSchema.Text(proof.Result, "art") == "kontakt_original_abschlussstatus")
        {
            var phase = NotesOriginalSchema.Text(proof.Result, "phase");
            if (phase is not ("prepared" or "settled")) throw new InvalidDataException("notes_ack_terminal_phase_invalid");
            expected["art"] = "kontakt_original_abschlussstatus"; expected["phase"] = phase;
            expected["desktop_sha256"] = record["saved_book"]![2]!.DeepClone();
        }
        if (!MagnolienbaumCrypto.Canonical(expected).AsSpan().SequenceEqual(MagnolienbaumCrypto.Canonical(proof.Result)))
            throw new InvalidOperationException("notes_ack_fresh_result_history_changed");
        proof.Origin.RequireCurrent(proof.Result, proof.Transport);
        RequireHistory(proof.History, proof.Protocol); return record;
    }

    internal HistoryQuery ReadOnlyQuery(string key, NotesOriginalChoiceStore consent, NotesOriginalNegotiation protocol)
    {
        var record = LoadHeld(key) ?? throw new InvalidOperationException("notes_ack_genuine_history_required");
        long epoch; lock (gate) epoch = generation;
        var proof = new HistoryProof(this, consent, key, NotesOriginalSchema.Text(record, "journal_identity"), NotesOriginalSchema.Hash(record), epoch);
        RequireHistory(proof, protocol); return new(proof);
    }

    private JsonObject RequireHistory(HistoryProof proof, NotesOriginalNegotiation protocol)
    {
        lock (gate)
            if (!ReferenceEquals(proof.Store, this) || proof.Generation != generation) throw new InvalidOperationException("notes_ack_history_process_expired");
        var pins = protocol.RequireCurrent();
        var record = LoadHeld(proof.Key) ?? throw new InvalidOperationException("notes_ack_genuine_history_required");
        if (NotesOriginalSchema.Text(record, "journal_identity") != proof.Identity || NotesOriginalSchema.Hash(record) != proof.FrameHash)
            throw new InvalidOperationException("notes_ack_genuine_history_changed");
        var source = record["request_history"]!["source"]!.AsObject();
        if (source["peer"]![0]!.GetValue<string>() != pins.Peer.Id || source["peer"]![1]!.GetValue<string>() != pins.Peer.PublicKey ||
            source["own"]![0]!.GetValue<string>() != pins.Own.Id || source["own"]![1]!.GetValue<string>() != pins.Own.PublicKey)
            throw new InvalidOperationException("notes_ack_history_protocol_pins_changed");
        var binding = proof.Consent.VerifySavedHistory(record);
        var physical = requests.LoadPhysical(binding, NotesOriginalSchema.Text(source, "local_id"));
        if (!JsonNode.DeepEquals(physical, record["request_history"])) throw new InvalidOperationException("notes_ack_history_physical_changed");
        protocol.RequireCurrent();
        lock (gate) if (proof.Generation != generation) throw new InvalidOperationException("notes_ack_history_process_expired");
        return record;
    }
}
