using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Independent genuine saved history only. Loading JSON never issues an ACK proof.
// No terminal retirement, restored reauthorization or production sender yet.
internal sealed class NotesOriginalSavedAckIntents
{
    private const int Limit = 2 * 1024 * 1024;
    private readonly ContactSourcePrivateFiles files;
    private readonly Func<byte[]?> existingKey;
    private readonly NotesOriginalRequestIntents requests;
    private readonly Action<string> stage;
    private readonly object gate = new();
    private long generation;
    private sealed record SavedProof(NotesOriginalSavedAckIntents Store, NotesOriginalPendingResult Pending,
        string Key, string Identity, string FrameHash, string CipherHash, long Generation);
    internal sealed class SavedAck(object proof)
    {
        internal JsonObject Body()
        {
            if (proof is not SavedProof native) throw new InvalidOperationException("notes_ack_native_saved_proof_required");
            return native.Store.Body(native);
        }
    }

    internal NotesOriginalSavedAckIntents(ContactSourcePrivateFiles files, Func<byte[]?> existingKey,
        NotesOriginalRequestIntents requests, Action<string>? stage = null)
    {
        this.files = files ?? throw new ArgumentNullException(nameof(files));
        this.existingKey = existingKey ?? throw new ArgumentNullException(nameof(existingKey));
        this.requests = requests ?? throw new ArgumentNullException(nameof(requests)); this.stage = stage ?? (_ => { });
    }

    private (NotesOriginalJournalCrypto Crypto, string Identity) Crypto()
    {
        var identity = new NotesOriginalJournalCrypto(existingKey).Identity();
        return (new(() =>
        {
            var key = existingKey(); if (key is null) return null;
            if (key.Length == 32 && Convert.ToHexString(SHA256.HashData(key)).ToLowerInvariant() == identity) return key;
            CryptographicOperations.ZeroMemory(key); throw new CryptographicException("notes_ack_journal_key_changed");
        }), identity);
    }

    private static void Identity(ContactSourcePrivateFiles.Session directory, string identity, bool initialize)
    {
        var prior = directory.Read(".journal-key", 128);
        if (prior is null && initialize && directory.RootCreated)
        {
            directory.Write(".journal-key", identity + "\n", 128); prior = directory.Read(".journal-key", 128);
        }
        if (prior != identity + "\n") throw new InvalidOperationException("notes_ack_journal_identity_changed");
    }

    private JsonObject Capture(NotesOriginalPendingResult pending)
    {
        var request = requests.SavedRequest(pending);
        var saved = pending.CaptureSavedResult();
        var result = saved["result"]!.AsObject();
        if (NotesOriginalSchema.Text(result, "request_sha256") != NotesOriginalSchema.Text(request.Frame, "request_sha256"))
            throw new InvalidOperationException("notes_ack_request_history_changed");
        saved["version"] = 1; saved["state"] = "saved_ack_pending";
        saved["request_intention"] = request.Key; saved["journal_identity"] = request.KeyIdentity;
        saved["request_history"] = request.Frame;
        return saved;
    }

    private static string Key(JsonObject frame) => NotesOriginalSchema.Hash(frame["request_history"]!["request"]!.AsObject());
    private static JsonObject Validate(string key, JsonObject frame)
    {
        NotesOriginalSchema.Fields(frame, "version", "state", "request_intention", "journal_identity", "request_history", "result", "saved_book");
        if (NotesOriginalSchema.Integer(frame, "version") != 1 || NotesOriginalSchema.Text(frame, "state") != "saved_ack_pending" ||
            !NotesOriginalSchema.Hex(NotesOriginalSchema.Text(frame, "request_intention")) || !NotesOriginalSchema.Hex(NotesOriginalSchema.Text(frame, "journal_identity")) ||
            frame["request_history"] is not JsonObject history || history["request"] is not JsonObject request ||
            frame["result"] is not JsonObject result || frame["saved_book"] is not JsonArray saved || saved.Count != 3 ||
            string.IsNullOrEmpty(NotesOriginalSchema.String(saved[0])) || saved[1] is not JsonValue sequence || !sequence.TryGetValue<long>(out var number) || number < 1 ||
            !NotesOriginalSchema.Hex(NotesOriginalSchema.String(saved[2])) || Key(frame) != key)
            throw new InvalidDataException("notes_ack_private_history_invalid");
        NotesOriginalSchema.Fields(result, "art", "fassung", "request_id", "request_sha256", "share_id", "before_basis", "target_sha256", "receipt_id", "native_revision", "next_basis");
        NotesOriginalRequestIntents.Validate(NotesOriginalSchema.Text(frame, "request_intention"), NotesOriginalSchema.Text(history, "physical"), history);
        if (NotesOriginalSchema.Text(result, "art") != "kontakt_original_ergebnis" || NotesOriginalSchema.Integer(result, "fassung") != 1 ||
            new[] { "request_id", "share_id", "before_basis", "target_sha256" }.Any(name => NotesOriginalSchema.Text(result, name) != NotesOriginalSchema.Text(request, name)) ||
            NotesOriginalSchema.Text(result, "request_sha256") != key || NotesOriginalSchema.Text(history, "request_sha256") != key ||
            !NotesOriginalSchema.Uuid(NotesOriginalSchema.Text(result, "receipt_id")) || !NotesOriginalSchema.Hex(NotesOriginalSchema.Text(result, "next_basis")) ||
            NotesOriginalSchema.Text(result, "next_basis") == NotesOriginalSchema.Text(result, "before_basis") ||
            NotesOriginalSchema.Integer(result, "native_revision") <= NotesOriginalSchema.Integer(history["export"]!.AsObject(), "native_revision"))
            throw new InvalidDataException("notes_ack_private_correlation_invalid");
        return frame;
    }

    internal SavedAck Seal(NotesOriginalPendingResult pending)
    {
        var record = Capture(pending); var context = Crypto(); var key = Key(record); Validate(key, record);
        if (NotesOriginalSchema.Text(record, "journal_identity") != context.Identity) throw new InvalidOperationException("notes_ack_independent_journal_changed");
        string encrypted; long started;
        lock (gate)
        {
            started = generation;
            using var directory = files.Open(create: true) ?? throw new IOException("notes_ack_private_root_required");
            Identity(directory, context.Identity, initialize: true);
            var prior = directory.Read("a-" + key + ".json", Limit);
            if (prior is not null)
            {
                if (!JsonNode.DeepEquals(Validate(key, context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, prior)), record))
                    throw new InvalidOperationException("notes_ack_existing_history_held");
                encrypted = prior;
            }
            else
            {
                encrypted = context.Crypto.Seal(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, record);
                directory.Write("a-" + key + ".json", encrypted, Limit); stage("history-written");
            }
            if (directory.Read("a-" + key + ".json", Limit) != encrypted ||
                !JsonNode.DeepEquals(record, Validate(key, context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, encrypted))))
                throw new IOException("notes_ack_durability_unconfirmed");
        }
        stage("after-readback");
        if (!JsonNode.DeepEquals(Capture(pending), record)) throw new InvalidOperationException("notes_ack_native_saved_frame_changed");
        lock (gate)
        {
            if (generation != started) throw new InvalidOperationException("notes_ack_process_stopped");
            return new(new SavedProof(this, pending, key, context.Identity, NotesOriginalSchema.Hash(record), HashCipher(encrypted), started));
        }
    }

    private static string HashCipher(string encrypted) => Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(encrypted))).ToLowerInvariant();
    internal JsonObject? LoadHeld(string key)
    {
        if (!NotesOriginalSchema.Hex(key)) throw new InvalidDataException("notes_ack_private_key_invalid");
        var context = Crypto();
        using var directory = files.Open(); if (directory is null) return null;
        Identity(directory, context.Identity, initialize: false);
        var encrypted = directory.Read("a-" + key + ".json", Limit);
        if (encrypted is null) return null;
        var record = Validate(key, context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, key, encrypted));
        if (NotesOriginalSchema.Text(record, "journal_identity") != context.Identity) throw new InvalidOperationException("notes_ack_journal_key_changed");
        return record.DeepClone().AsObject(); // Never a SavedAck instance.
    }

    private JsonObject Body(SavedProof proof)
    {
        var current = Capture(proof.Pending); var context = Crypto();
        if (context.Identity != proof.Identity || NotesOriginalSchema.Hash(current) != proof.FrameHash)
            throw new InvalidOperationException("notes_ack_native_saved_frame_changed");
        lock (gate)
        {
            if (generation != proof.Generation) throw new InvalidOperationException("notes_ack_process_stopped");
            using var directory = files.Open() ?? throw new IOException("notes_ack_private_history_missing");
            Identity(directory, context.Identity, initialize: false);
            var encrypted = directory.Read("a-" + proof.Key + ".json", Limit) ?? throw new IOException("notes_ack_private_history_missing");
            if (HashCipher(encrypted) != proof.CipherHash || NotesOriginalSchema.Hash(Validate(proof.Key,
                    context.Crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, proof.Key, encrypted))) != proof.FrameHash)
                throw new InvalidOperationException("notes_ack_private_history_changed");
        }
        if (!JsonNode.DeepEquals(Capture(proof.Pending), current)) throw new InvalidOperationException("notes_ack_native_saved_frame_changed");
        var body = current["result"]!.DeepClone().AsObject(); body["art"] = "kontakt_original_saveack";
        body["desktop_sha256"] = current["saved_book"]![2]!.DeepClone(); return body;
    }

    internal void Stop() { lock (gate) generation++; }
}
