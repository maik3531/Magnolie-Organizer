using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalSavedAckIntents
{
    private sealed record TerminalNative(RestoredProof Restored, string Key, string FrameHash);
    internal sealed record Retirement(JsonObject Original, JsonObject Settled);
    internal sealed class TerminalProof(object proof)
    {
        internal Retirement RequireFor(NotesOriginalRequestIntents requests)
        {
            if (proof is not TerminalNative native || !ReferenceEquals(native.Restored.History.Store.requests, requests))
                throw new InvalidOperationException("notes_terminal_owned_native_proof_required");
            return native.Restored.History.Store.RequireTerminal(native);
        }
    }

    private static string TerminalKey(JsonObject history) => NotesOriginalSchema.Hash(new JsonObject {
        ["kind"] = "notes-original-terminal", ["ack"] = Key(history), ["request"] = history["request_intention"]!.DeepClone() });

    private static JsonObject TerminalRecord(JsonObject history, JsonObject terminal) => new() {
        ["version"] = 1, ["state"] = "settled", ["ack_key"] = Key(history), ["ack_sha256"] = NotesOriginalSchema.Hash(history),
        ["request_intention"] = history["request_intention"]!.DeepClone(), ["physical"] = history["request_history"]!["physical"]!.DeepClone(),
        ["terminal"] = terminal.DeepClone() };

    private JsonObject RequireTerminalMarker(JsonObject history, JsonObject marker)
    {
        NotesOriginalSchema.Fields(marker, "key", "sha256");
        var key = TerminalKey(history);
        if (NotesOriginalSchema.Text(marker, "key") != key) throw new InvalidOperationException("notes_terminal_history_key_changed");
        var context = Crypto();
        if (context.Identity != NotesOriginalSchema.Text(history, "journal_identity")) throw new InvalidOperationException("notes_terminal_journal_changed");
        using var directory = files.Open() ?? throw new IOException("notes_terminal_history_missing");
        Identity(directory, context.Identity, initialize: false);
        var encrypted = directory.Read("a-" + key + ".json", Limit) ?? throw new IOException("notes_terminal_history_missing");
        var record = context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, encrypted);
        var terminal = history["result"]!.DeepClone().AsObject(); terminal["art"] = "kontakt_original_abschlussstatus";
        terminal["phase"] = "settled"; terminal["desktop_sha256"] = history["saved_book"]![2]!.DeepClone();
        if (!JsonNode.DeepEquals(record, TerminalRecord(history, terminal)) || NotesOriginalSchema.Hash(record) != NotesOriginalSchema.Text(marker, "sha256"))
            throw new InvalidOperationException("notes_terminal_history_changed");
        return record;
    }

    internal TerminalProof SealTerminal(RestoredAck restored)
    {
        var proof = (RestoredProof)restored.RequireOwner(this);
        var history = RequireRestored(proof);
        if (NotesOriginalSchema.Text(proof.Result, "art") != "kontakt_original_abschlussstatus" || NotesOriginalSchema.Text(proof.Result, "phase") != "settled")
            throw new InvalidOperationException("notes_terminal_fresh_settled_status_required");
        var record = TerminalRecord(history, proof.Result); var key = TerminalKey(history); var context = Crypto();
        if (context.Identity != proof.History.Identity) throw new InvalidOperationException("notes_terminal_journal_changed");
        lock (gate)
        {
            using var directory = files.Open() ?? throw new IOException("notes_terminal_history_missing");
            Identity(directory, context.Identity, initialize: false);
            var prior = directory.Read("a-" + key + ".json", Limit);
            if (prior is not null && !JsonNode.DeepEquals(context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, prior), record))
                throw new InvalidOperationException("notes_terminal_conflicting_history");
            var encrypted = prior ?? context.Crypto.Seal(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, record);
            directory.Write("a-" + key + ".json", encrypted, Limit); stage("terminal-written");
            if (directory.Read("a-" + key + ".json", Limit) != encrypted) throw new IOException("notes_terminal_durability_unconfirmed");
        }
        stage("terminal-readback");
        var native = new TerminalNative(proof, key, NotesOriginalSchema.Hash(record));
        RequireTerminal(native); return new(native);
    }

    private Retirement RequireTerminal(TerminalNative proof)
    {
        var history = RequireRestored(proof.Restored);
        if (NotesOriginalSchema.Text(proof.Restored.Result, "phase") != "settled") throw new InvalidOperationException("notes_terminal_fresh_settled_status_required");
        var marker = new JsonObject { ["key"] = proof.Key, ["sha256"] = proof.FrameHash };
        RequireTerminalMarker(history, marker);
        var original = history["request_history"]!.DeepClone().AsObject();
        var settled = original.DeepClone().AsObject(); settled["state"] = "request_settled"; settled["terminal"] = marker;
        return new(original, settled);
    }
}
