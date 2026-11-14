using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalChoiceStore
{
    // Mutating save/recovery calls belong to the existing serial native book
    // worker under its mutation gate, never receive or concurrent UI hydration.
    private sealed record SaveProof(NotesOriginalChoiceStore Store, string KeyIdentity, string Generation, string Token,
        NativeActorBookSnapshot? Previous, ContactSourcePrimaryBook? PreviousPrimary, string NextContent, string NextSha256);
    internal sealed class SaveIntent(object proof)
    {
        private SaveProof Native() => proof as SaveProof ?? throw new InvalidOperationException("notes_choice_native_save_intent_required");
        internal object RequireNative(NotesOriginalChoiceStore store)
        {
            var native = Native();
            if (!ReferenceEquals(native.Store, store)) throw new InvalidOperationException("notes_choice_owned_save_intent_required");
            return native;
        }
    }
    private sealed record Observation(string Binding, string Content, NativeActorBookSnapshot? Snapshot, ContactSourcePrimaryBook Primary)
    {
        internal bool Same(Observation other) => Binding == other.Binding && Content == other.Content && Primary.Same(other.Primary) &&
            (Snapshot is null ? other.Snapshot is null : other.Snapshot is not null && Snapshot.SavedBook == other.Snapshot.SavedBook && Snapshot.Text == other.Snapshot.Text);
    }

    private JsonObject? ReadIntent(ContactSourcePrivateFiles.Session directory, State state)
    {
        var raw = directory.Read(".save-intent.json", 16 * 1024);
        if (raw is null) return null;
        var envelope = Parse(raw); NotesOriginalSchema.Fields(envelope, "payload", "mac");
        if (envelope["payload"] is not JsonObject intent || !NotesOriginalSchema.Hex(Text(envelope, "mac")) ||
            !CryptographicOperations.FixedTimeEquals(Convert.FromHexString(Text(envelope, "mac")),
                Convert.FromHexString(Tag(state.Key, "book-save", Canonical(intent)))))
            throw new CryptographicException("notes_choice_save_intent_invalid");
        NotesOriginalSchema.Fields(intent, "version", "generation", "book", "old", "new", "token", "next_sha256");
        if (NotesOriginalSchema.Integer(intent, "version") != 1 ||
            new[] { "generation", "book", "old", "new", "token", "next_sha256" }.Any(name => !NotesOriginalSchema.Hex(Text(intent, name))) ||
            Text(intent, "generation") != Text(state.Payload, "generation") || Text(intent, "book") != Text(state.Payload, "book") ||
            state.Payload["choices"]!.AsArray().Count == 0 ||
            Text(state.Payload, "content") != Text(intent, "old") && Text(state.Payload, "content") != Text(intent, "new"))
            throw new InvalidDataException("notes_choice_save_intent_invalid");
        return intent;
    }

    private static bool RecognizesContent(State state, string content) => Text(state.Payload, "content") == content ||
        state.Intent is not null && Text(state.Payload, "content") == Text(state.Intent, "old") && Text(state.Intent, "new") == content;

    private Observation Observe(bool requireSaved)
    {
        var snapshot = capture(); var actual = primary(); var path = binding();
        if (!Path.IsPathFullyQualified(path) || actual.Binding != Path.GetFullPath(path))
            throw new InvalidOperationException("notes_choice_native_primary_binding_changed");
        if (snapshot is not null)
        {
            if (snapshot.SavedBook.Sha256 != actual.PlainHash || NativeBookJson.Hash(JsonNode.Parse(snapshot.Text)!) != actual.Content)
                throw new InvalidOperationException("notes_choice_native_primary_changed");
        }
        else
        {
            if (requireSaved) throw new InvalidOperationException("notes_choice_real_saved_book_required");
            var model = currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_choice_owned_native_model_required");
            if (BaumSyncSnapshot.Hash(model) != actual.PlainHash || NativeBookJson.Hash(JsonNode.Parse(model)!) != actual.Content)
                throw new InvalidOperationException("notes_choice_owned_native_model_changed");
        }
        return new(path, actual.Content, snapshot, actual);
    }

    internal SaveIntent? PrepareCurrentSave(string nextText)
    {
        if (!HasDesiredConsent()) return null;
        var observed = Observe(requireSaved: false);
        AdvanceObserved(observed, null);
        using var before = Read() ?? throw new IOException("notes_choice_private_state_missing");
        var next = JsonNode.Parse(nextText) as JsonObject ?? throw new InvalidDataException("notes_choice_native_book_required");
        if (before.Payload["choices"]!.AsArray().Count == 0) return null;
        if (before.Intent is not null || Text(before.Payload, "content") != observed.Content ||
            Text(before.Payload, "book") != Tag(before.Key, "book", observed.Binding))
            throw new InvalidOperationException("notes_choice_native_save_pending");
        var intent = new JsonObject { ["version"] = 1, ["generation"] = before.Payload["generation"]!.DeepClone(),
            ["book"] = before.Payload["book"]!.DeepClone(), ["old"] = observed.Content, ["new"] = NativeBookJson.Hash(next),
            ["next_sha256"] = BaumSyncSnapshot.Hash(nextText), ["token"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant() };
        using (var directory = files.Open() ?? throw new IOException("notes_choice_private_state_missing"))
        {
            using var current = Read(directory) ?? throw new IOException("notes_choice_private_state_missing");
            if (current.Identity != before.Identity || Canonical(current.Payload) != Canonical(before.Payload) || current.Intent is not null)
                throw new InvalidOperationException("notes_choice_private_context_changed");
            var envelope = new JsonObject { ["payload"] = intent.DeepClone(), ["mac"] = Tag(before.Key, "book-save", Canonical(intent)) };
            directory.Write(".save-intent.json", envelope.ToJsonString(), 16 * 1024);
            saveStage("intent-written");
            var check = ReadIntent(directory, current);
            if (check is null || Canonical(check) != Canonical(intent)) throw new IOException("notes_choice_save_intent_unconfirmed");
        }
        if (!observed.Same(Observe(requireSaved: observed.Snapshot is not null)))
            throw new InvalidOperationException("notes_choice_native_book_changed");
        return new(new SaveProof(this, before.Identity, Text(intent, "generation"), Text(intent, "token"),
            observed.Snapshot, observed.Snapshot is null ? observed.Primary : null, Text(intent, "new"), Text(intent, "next_sha256")));
    }

    internal void ConfirmSave(SaveIntent expected, NativeActorBookSnapshot confirmed)
    {
        var proof = (SaveProof)expected.RequireNative(this);
        var observed = Observe(requireSaved: true);
        if (observed.Snapshot!.SavedBook != confirmed.SavedBook || observed.Snapshot.Text != confirmed.Text ||
            confirmed.SavedBook.Sha256 != proof.NextSha256 || observed.Content != proof.NextContent ||
            (proof.Previous is not null ? confirmed.SavedBook.BookSource != proof.Previous.SavedBook.BookSource ||
                confirmed.SavedBook.Sequence != checked(proof.Previous.SavedBook.Sequence + 1) :
                proof.PreviousPrimary is null || observed.Binding != proof.PreviousPrimary.Binding))
            throw new InvalidOperationException("notes_choice_actual_save_changed");
        AdvanceObserved(observed, proof);
    }

    internal void RecoverSaved(NativeActorBookSnapshot confirmed)
    {
        var observed = Observe(requireSaved: true);
        if (observed.Snapshot!.SavedBook != confirmed.SavedBook || observed.Snapshot.Text != confirmed.Text)
            throw new InvalidOperationException("notes_choice_actual_save_changed");
        AdvanceObserved(observed, null);
    }

    internal void RecoverPrimary(ContactSourcePrimaryBook confirmed)
    {
        var observed = Observe(requireSaved: false);
        if (!observed.Primary.Same(confirmed)) throw new InvalidOperationException("notes_choice_native_primary_changed");
        AdvanceObserved(observed, null); // Permission bookkeeping only; never RecordSaved or a SavedWitness.
    }

    private void AdvanceObserved(Observation observed, SaveProof? expected)
    {
        using (var directory = files.Open() ?? throw new IOException("notes_choice_private_state_missing"))
        {
            using var state = Read(directory) ?? throw new IOException("notes_choice_private_state_missing");
            var intent = state.Intent;
            if (intent is null)
            {
                if (expected is not null) throw new InvalidOperationException("notes_choice_save_intent_missing");
                if (state.Payload["choices"]!.AsArray().Count > 0 && (Text(state.Payload, "content") != observed.Content ||
                        Text(state.Payload, "book") != Tag(state.Key, "book", observed.Binding)))
                    throw new InvalidOperationException("notes_choice_unknown_native_book");
                return;
            }
            if (Text(state.Payload, "book") != Tag(state.Key, "book", observed.Binding) || !RecognizesContent(state, observed.Content) ||
                expected is not null && (state.Identity != expected.KeyIdentity || Text(intent, "generation") != expected.Generation ||
                    Text(intent, "token") != expected.Token || Text(intent, "new") != expected.NextContent || Text(intent, "next_sha256") != expected.NextSha256))
                throw new InvalidOperationException("notes_choice_save_outcome_unknown");
            if (Text(state.Payload, "content") != observed.Content)
            {
                var payload = state.Payload.DeepClone().AsObject(); payload["content"] = observed.Content;
                directory.Write("approval.json", EncodePayload(state.Key, payload), Limit);
                saveStage("content-written");
                using var actual = Read(directory) ?? throw new IOException("notes_choice_private_state_missing");
                if (actual.Identity != state.Identity || Canonical(actual.Payload) != Canonical(payload))
                    throw new IOException("notes_choice_save_advance_unconfirmed");
                saveStage("content-readback");
            }
            saveStage("before-intent-delete");
            directory.Delete(".save-intent.json");
            saveStage("intent-deleted");
        }
        if (!observed.Same(Observe(requireSaved: observed.Snapshot is not null)))
            throw new InvalidOperationException("notes_choice_native_book_changed");
    }

    private static string EncodePayload(byte[] key, JsonObject payload)
    {
        Validate(payload); var clear = NativeBookJson.Canonical(payload);
        try
        {
            if (clear.Length > 128 * 1024) throw new InvalidDataException("notes_choice_record_budget");
            var nonce = RandomNumberGenerator.GetBytes(12); var cipher = new byte[clear.Length]; var tag = new byte[16];
            using (var aes = new AesGcm(key, 16)) aes.Encrypt(nonce, clear, cipher, tag, Domain);
            return new JsonObject { ["version"] = 1, ["nonce"] = Convert.ToBase64String(nonce), ["cipher"] = Convert.ToBase64String(cipher),
                ["tag"] = Convert.ToBase64String(tag) }.ToJsonString();
        }
        finally { CryptographicOperations.ZeroMemory(clear); }
    }
}
