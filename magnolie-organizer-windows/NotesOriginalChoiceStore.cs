using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Private native consent/known-book chain building blocks, not startup hydration,
// request history, a production controller or a renderer factory. Unknown books
// still hold; only this store's authenticated native save intents may advance.
internal sealed partial class NotesOriginalChoiceStore
{
    private sealed class ConsentKeyProtector : ISecretProtector
    {
        private static readonly byte[] Entropy = "Magnolie/native-notes-original-choice/key/v1"u8.ToArray();
        public byte[] Protect(byte[] plain)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
            return ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser);
        }
        public byte[] Unprotect(byte[] cipher)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
            return ProtectedData.Unprotect(cipher, Entropy, DataProtectionScope.CurrentUser);
        }
    }

    private sealed record SealProof(NotesOriginalChoiceStore Store, NotesOriginalExportChoice Choice,
        string KeyIdentity, string Generation, string Book, string Source);
    internal sealed class SourceSeal(object proof)
    {
        private SealProof Native() => proof as SealProof ?? throw new InvalidOperationException("notes_choice_private_seal_required");
        internal void RequireOwner(NotesOriginalExportChoice choice)
        { if (!ReferenceEquals(Native().Choice, choice)) throw new InvalidOperationException("notes_choice_owned_selection_required"); }
        internal void RequireCurrent()
        {
            var native = Native();
            native.Store.RequireRecord(native.KeyIdentity, native.Generation, native.Book, native.Source);
        }
        internal (string Binding, JsonObject Seal) RequestBinding(NotesOriginalExportChoice choice)
        {
            RequireOwner(choice); RequireCurrent(); var native = Native();
            var path = native.Store.binding();
            RequireCurrent();
            return (path, new JsonObject { ["key_sha256"] = native.KeyIdentity, ["generation"] = native.Generation,
                ["book"] = native.Book, ["source_sha256"] = NotesOriginalSchema.Hash(Parse(native.Source)) });
        }
    }

    private sealed class State(byte[] key, JsonObject payload) : IDisposable
    {
        internal byte[] Key { get; } = key;
        internal JsonObject Payload { get; } = payload;
        internal JsonObject? Intent { get; set; }
        internal string Identity => Convert.ToHexString(SHA256.HashData(Key)).ToLowerInvariant();
        public void Dispose() => CryptographicOperations.ZeroMemory(Key);
    }
    private sealed record Known(string Identity, JsonObject Payload, NativeActorBookSnapshot Snapshot);
    private sealed record RawState(string? Transaction, string? Key, string? Record, string? Intent);
    private readonly ContactSourcePrivateFiles files;
    private readonly Func<NativeActorBookSnapshot?> capture;
    private readonly Func<ContactSourcePrimaryBook> primary;
    private readonly Func<string> binding;
    private readonly ISecretProtector keyProtector;
    private readonly Func<string?>? currentNativeData;
    private readonly Action<string> saveStage;
    private static readonly byte[] Domain = "Magnolie/native-notes-original-choice/windows/v1\0"u8.ToArray();
    private const int Limit = 192 * 1024;

    internal NotesOriginalChoiceStore(ContactSourcePrivateFiles files, Func<NativeActorBookSnapshot?> capture,
        Func<ContactSourcePrimaryBook> primary, Func<string> binding, ISecretProtector? keyProtector = null,
        Func<string?>? currentNativeData = null, Action<string>? saveStage = null)
    {
        this.files = files ?? throw new ArgumentNullException(nameof(files));
        this.capture = capture ?? throw new ArgumentNullException(nameof(capture));
        this.primary = primary ?? throw new ArgumentNullException(nameof(primary));
        this.binding = binding ?? throw new ArgumentNullException(nameof(binding));
        this.keyProtector = keyProtector ?? new ConsentKeyProtector();
        this.currentNativeData = currentNativeData;
        this.saveStage = saveStage ?? (_ => { }); // Bounded native fault-injection hook, no permission callback.
    }

    private static string Canonical(JsonObject value) => Encoding.UTF8.GetString(NativeBookJson.Canonical(value));
    private static string Tag(byte[] key, string label, string value) => Convert.ToHexString(HMACSHA256.HashData(key,
        Domain.Concat(Encoding.UTF8.GetBytes(label + "\0" + value)).ToArray())).ToLowerInvariant();
    private static string Text(JsonObject value, string field) => NotesOriginalSchema.Text(value, field);
    private static RawState Raw(ContactSourcePrivateFiles.Session directory) => new(directory.Read(".transaction", 32),
        directory.Read(".key.dpapi", 16 * 1024), directory.Read("approval.json", Limit), directory.Read(".save-intent.json", Limit));
    private RawState ReadRaw()
    { using var directory = files.Open(); return directory is null ? new(null, null, null, null) : Raw(directory); }

    private static JsonObject Parse(string text)
    {
        using var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 16 });
        static void Unique(JsonElement value)
        {
            if (value.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var field in value.EnumerateObject())
                { if (!names.Add(field.Name)) throw new InvalidDataException("notes_choice_duplicate_field"); Unique(field.Value); }
            }
            else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) Unique(item);
        }
        Unique(document.RootElement);
        return JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("notes_choice_private_record_invalid");
    }

    private static void Validate(JsonObject payload)
    {
        NotesOriginalSchema.Fields(payload, "version", "generation", "book", "content", "choices");
        if (NotesOriginalSchema.Integer(payload, "version") != 1 || !NotesOriginalSchema.Hex(Text(payload, "generation")) ||
            !NotesOriginalSchema.Hex(Text(payload, "book")) || payload["choices"] is not JsonArray choices || choices.Count > 256 ||
            (choices.Count == 0) != (payload["content"] is null) || choices.Count > 0 && !NotesOriginalSchema.Hex(Text(payload, "content")))
            throw new InvalidDataException("notes_choice_private_record_invalid");
        var ids = new HashSet<string>(StringComparer.Ordinal); var shares = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in choices)
        {
            if (item is not JsonObject source) throw new InvalidDataException("notes_choice_private_source_invalid");
            NotesOriginalSchema.Fields(source, "peer", "own", "share_id", "setup_id", "local_id", "local_uid");
            foreach (var name in new[] { "peer", "own" })
                if (source[name] is not JsonArray pins || pins.Count != 2 || pins.Any(value => string.IsNullOrEmpty(NotesOriginalSchema.String(value))))
                    throw new InvalidDataException("notes_choice_private_source_invalid");
            if (!NotesOriginalSchema.Share(Text(source, "share_id")) || !NotesOriginalSchema.Uuid(Text(source, "setup_id")) ||
                string.IsNullOrEmpty(Text(source, "local_id")) || string.IsNullOrEmpty(Text(source, "local_uid")) || !ids.Add(Text(source, "local_id")))
                throw new InvalidDataException("notes_choice_private_source_invalid");
            var identity = new JsonObject { ["peer"] = source["peer"]!.DeepClone(), ["own"] = source["own"]!.DeepClone(), ["share"] = source["share_id"]!.DeepClone() };
            if (!shares.Add(Canonical(identity))) throw new InvalidDataException("notes_choice_ambiguous_selection");
        }
    }

    private State? Read()
    {
        using var directory = files.Open();
        if (directory is null) return null;
        return Read(directory);
    }

    private State? Read(ContactSourcePrivateFiles.Session directory)
    {
        var transaction = directory.Read(".transaction", 32);
        var keyText = directory.Read(".key.dpapi", 16 * 1024);
        var recordText = directory.Read("approval.json", Limit);
        if (transaction is null && keyText is null && recordText is null && directory.Read(".save-intent.json", Limit) is null) return null;
        if (transaction != "clean\n" || keyText is null || recordText is null)
            throw new InvalidOperationException("notes_choice_private_state_pending");
        byte[]? key = null;
        try
        {
            var wrapped = Convert.FromBase64String(keyText);
            if (wrapped.Length <= 32) throw new CryptographicException("notes_choice_wrapped_key_required");
            key = keyProtector.Unprotect(wrapped);
            if (key.Length != 32) throw new CryptographicException("notes_choice_private_key_invalid");
            var frame = Parse(recordText);
            NotesOriginalSchema.Fields(frame, "version", "nonce", "cipher", "tag");
            if (NotesOriginalSchema.Integer(frame, "version") != 1) throw new InvalidDataException("notes_choice_private_record_invalid");
            var nonce = Convert.FromBase64String(Text(frame, "nonce"));
            var cipher = Convert.FromBase64String(Text(frame, "cipher")); var tag = Convert.FromBase64String(Text(frame, "tag"));
            if (nonce.Length != 12 || tag.Length != 16 || cipher.Length > 128 * 1024) throw new InvalidDataException("notes_choice_private_record_invalid");
            var clear = new byte[cipher.Length];
            try
            {
                using var aes = new AesGcm(key, 16); aes.Decrypt(nonce, cipher, tag, clear, Domain);
                var payload = Parse(new UTF8Encoding(false, true).GetString(clear)); Validate(payload);
                if (!NativeBookJson.Canonical(payload).AsSpan().SequenceEqual(clear)) throw new InvalidDataException("notes_choice_noncanonical_record");
                var result = new State(key, payload);
                result.Intent = ReadIntent(directory, result);
                key = null; return result;
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }
        finally { if (key is not null) CryptographicOperations.ZeroMemory(key); }
    }

    internal bool HasDesiredConsent()
    { using var state = Read(); return state?.Payload["choices"]!.AsArray().Count > 0; }

    internal bool RecognizesSaved() => ReadKnown() is not null; // Correlation only, not a saved witness or ACK grant.

    internal string VerifySavedHistory(JsonObject history, bool requireExactTarget = true)
    {
        // Read-only native correlation, never a new SavedWitness/RecordSaved.
        // The history issuer must independently authenticate its own journal.
        using var state = Read() ?? throw new InvalidOperationException("notes_choice_private_source_missing");
        var observed = Observe(requireSaved: false);
        var original = history["request_history"]!.AsObject(); var source = original["source"]!.AsObject();
        var seal = original["source_seal"]!.AsObject();
        if (state.Identity != Text(seal, "key_sha256") || Text(state.Payload, "generation") != Text(seal, "generation") ||
            Text(state.Payload, "book") != Text(seal, "book") || Text(state.Payload, "book") != Tag(state.Key, "book", observed.Binding) ||
            !RecognizesContent(state, observed.Content) || state.Payload["choices"]!.AsArray().OfType<JsonObject>().Count(value =>
                Canonical(value) == Canonical(source)) != 1)
            throw new InvalidOperationException("notes_choice_historical_source_changed");
        var model = observed.Snapshot?.Text ?? currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_choice_owned_native_model_required");
        var contacts = JsonNode.Parse(model)!["kontakte"] as JsonArray ?? throw new InvalidDataException("notes_choice_native_contacts_required");
        var selected = contacts.OfType<JsonObject>().Where(value => Text(value, "id") == Text(source, "local_id")).ToArray();
        if (selected.Length != 1 || Text(selected[0], "uid") != Text(source, "local_uid") ||
            requireExactTarget && !JsonNode.DeepEquals(NotesOriginalExportChoice.Project(selected[0], original["export"]!["kontakt"]!.AsObject()), original["request"]!["ziel"]))
            throw new InvalidOperationException("notes_choice_historical_target_changed");
        var result = history["result"]!.AsObject();
        var expected = new JsonObject { ["fassung"] = 1, ["share_id"] = result["share_id"]!.DeepClone(), ["basis"] = result["next_basis"]!.DeepClone(),
            ["native_revision"] = NotesOriginalSchema.Integer(result, "native_revision").ToString(System.Globalization.CultureInfo.InvariantCulture) };
        foreach (var name in new[] { "request_id", "request_sha256", "target_sha256", "receipt_id" }) expected[name] = result[name]!.DeepClone();
        if (!JsonNode.DeepEquals(selected[0]["notesOriginalBasis"], expected)) throw new InvalidOperationException("notes_choice_historical_mapping_changed");
        using var again = Read();
        if (again is null || again.Identity != state.Identity || Canonical(again.Payload) != Canonical(state.Payload) ||
            !observed.Same(Observe(requireSaved: observed.Snapshot is not null)))
            throw new InvalidOperationException("notes_choice_historical_context_changed");
        return observed.Binding;
    }

    internal string VerifyUnconfirmedHistory(JsonObject history)
    {
        // Query correlation ONLY. Stored JSON cannot issue a pending mutation,
        // saved witness or ACK; actual recovery must later require fresh VERIFIED.
        using var state = Read() ?? throw new InvalidOperationException("notes_choice_private_source_missing");
        var observed = Observe(requireSaved: false);
        var source = history["source"]!.AsObject(); var seal = history["source_seal"]!.AsObject();
        if (state.Identity != Text(seal, "key_sha256") || Text(state.Payload, "generation") != Text(seal, "generation") ||
            Text(state.Payload, "book") != Text(seal, "book") || Text(state.Payload, "book") != Tag(state.Key, "book", observed.Binding) ||
            !RecognizesContent(state, observed.Content) || state.Payload["choices"]!.AsArray().OfType<JsonObject>().Count(value =>
                Canonical(value) == Canonical(source)) != 1)
            throw new InvalidOperationException("notes_choice_unconfirmed_source_changed");
        var model = observed.Snapshot?.Text ?? currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_choice_owned_native_model_required");
        var contacts = JsonNode.Parse(model)!["kontakte"] as JsonArray ?? throw new InvalidDataException("notes_choice_native_contacts_required");
        var selected = contacts.OfType<JsonObject>().Where(value => Text(value, "id") == Text(source, "local_id")).ToArray();
        if (selected.Length != 1 || Text(selected[0], "uid") != Text(source, "local_uid") ||
            !JsonNode.DeepEquals(NotesOriginalExportChoice.Project(selected[0], history["export"]!["kontakt"]!.AsObject()), history["request"]!["ziel"]))
            throw new InvalidOperationException("notes_choice_unconfirmed_target_changed");
        using var again = Read();
        if (again is null || again.Identity != state.Identity || Canonical(again.Payload) != Canonical(state.Payload) ||
            !observed.Same(Observe(requireSaved: observed.Snapshot is not null)))
            throw new InvalidOperationException("notes_choice_unconfirmed_context_changed");
        return observed.Binding;
    }

    internal NativeActorBookSnapshot? CurrentSavedForRecovery(JsonObject history)
    {
        VerifyUnconfirmedHistory(history);
        return capture(); // Actual native scope only. Never reconstruct from primary/model.
    }

    internal string OwnedBootstrapText(JsonObject history)
    {
        VerifyUnconfirmedHistory(history); var observed = Observe(requireSaved: false);
        if (observed.Snapshot is not null) throw new InvalidOperationException("notes_bootstrap_real_save_already_exists");
        var text = currentNativeData?.Invoke() ?? throw new InvalidOperationException("notes_bootstrap_owned_model_required");
        if (BaumSyncSnapshot.Hash(text) != observed.Primary.PlainHash || !observed.Same(Observe(requireSaved: false)))
            throw new InvalidOperationException("notes_bootstrap_owned_model_changed");
        VerifyUnconfirmedHistory(history); return text;
    }

    private Known? ReadKnown()
    {
        using var state = Read();
        if (state is null || state.Payload["choices"]!.AsArray().Count == 0) return null;
        // All native callbacks occur outside the private file session.
        var saved = capture() ?? throw new InvalidOperationException("notes_choice_real_saved_book_required");
        var actual = primary(); var nativeBinding = binding();
        if (!Path.IsPathFullyQualified(nativeBinding) || actual.Binding != Path.GetFullPath(nativeBinding) ||
            saved.SavedBook.Sha256 != actual.PlainHash || NativeBookJson.Hash(JsonNode.Parse(saved.Text)!) != actual.Content ||
            !RecognizesContent(state, actual.Content) || Text(state.Payload, "book") != Tag(state.Key, "book", nativeBinding))
            throw new InvalidOperationException("notes_choice_recognized_native_book_required");
        using var again = Read();
        if (again is null || again.Identity != state.Identity || Canonical(again.Payload) != Canonical(state.Payload) ||
            capture()?.SavedBook != saved.SavedBook || !actual.Same(primary()))
            throw new InvalidOperationException("notes_choice_private_context_changed");
        return new(state.Identity, state.Payload.DeepClone().AsObject(), saved);
    }

    private void RequireRecord(string identity, string generation, string book, string source)
    {
        var known = ReadKnown();
        if (known is null || known.Identity != identity || Text(known.Payload, "generation") != generation || Text(known.Payload, "book") != book ||
            known.Payload["choices"]!.AsArray().OfType<JsonObject>().Count(value => Canonical(value) == source) != 1)
            throw new InvalidOperationException("notes_choice_private_selection_changed");
        var selected = Parse(source);
        if (ContactSourceUpdateRun.SavedContacts(known.Snapshot).OfType<JsonObject>().Count(value =>
                Text(value, "id") == Text(selected, "local_id") && Text(value, "uid") == Text(selected, "local_uid")) != 1)
            throw new InvalidOperationException("notes_choice_native_contact_changed");
    }

    private RawState Publish(byte[] key, JsonObject payload, RawState expected)
    {
        var encoded = EncodePayload(key, payload);
        var protectedKey = keyProtector.Protect(key);
        try
        {
            if (protectedKey.Length <= 32) throw new CryptographicException("notes_choice_wrapped_key_required");
            var roundtrip = keyProtector.Unprotect(protectedKey);
            try
            {
                if (!CryptographicOperations.FixedTimeEquals(roundtrip, key)) throw new CryptographicException("notes_choice_key_readback_changed");
            }
            finally { CryptographicOperations.ZeroMemory(roundtrip); }
            using var directory = files.Open(create: true) ?? throw new IOException("notes_choice_private_root_required");
            if (Raw(directory) != expected) throw new InvalidOperationException("notes_choice_newer_private_decision");
            try
            {
                directory.Write(".transaction", "pending\n", 32);
                directory.Delete(".save-intent.json");
                directory.Write(".key.dpapi", Convert.ToBase64String(protectedKey), 16 * 1024);
                directory.Write("approval.json", encoded, Limit);
                directory.Write(".transaction", "clean\n", 32);
                return Raw(directory);
            }
            catch { try { directory.Write(".transaction", "pending\n", 32); } catch { } throw; }
        }
        finally { CryptographicOperations.ZeroMemory(protectedKey); }
    }

    internal void Approve(IReadOnlyList<NotesOriginalExportChoice> selections)
    {
        var choices = selections.ToArray();
        if (choices.Length == 0) { Revoke(); return; }
        if (choices.Length > 256) throw new InvalidDataException("notes_choice_selection_budget");
        var expected = ReadRaw();
        var snapshot = capture() ?? throw new InvalidOperationException("notes_choice_real_saved_book_required");
        var actual = primary(); var nativeBinding = binding();
        if (!Path.IsPathFullyQualified(nativeBinding) || actual.Binding != Path.GetFullPath(nativeBinding) || actual.PlainHash != snapshot.SavedBook.Sha256 ||
            actual.Content != NativeBookJson.Hash(JsonNode.Parse(snapshot.Text)!)) throw new InvalidOperationException("notes_choice_native_primary_changed");
        if (choices.Any(choice => choice.NativeBookSource != snapshot.SavedBook.BookSource))
            throw new InvalidOperationException("notes_choice_native_book_changed");
        var sources = choices.Select(choice => choice.PrivateSourceBinding()).ToArray();
        var key = RandomNumberGenerator.GetBytes(32);
        try
        {
            var payload = new JsonObject { ["version"] = 1, ["generation"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(),
                ["book"] = Tag(key, "book", nativeBinding), ["content"] = actual.Content,
                ["choices"] = new JsonArray(sources.Select(value => (JsonNode?)value.DeepClone()).ToArray()) };
            Validate(payload);
            var identity = Convert.ToHexString(SHA256.HashData(key)).ToLowerInvariant();
            for (var index = 0; index < choices.Length; index++) choices[index].AttachConsent(new(new SealProof(this, choices[index], identity,
                Text(payload, "generation"), Text(payload, "book"), Canonical(sources[index]))));
            var published = Publish(key, payload, expected);
            try
            {
                if (capture()?.SavedBook != snapshot.SavedBook || !actual.Same(primary())) throw new InvalidOperationException("notes_choice_native_book_changed");
                foreach (var choice in choices) choice.RequireCurrent();
            }
            catch
            {
                using var directory = files.Open();
                if (directory is not null && Raw(directory) == published) directory.Write(".transaction", "pending\n", 32);
                throw;
            }
        }
        finally { CryptographicOperations.ZeroMemory(key); }
    }

    internal NotesOriginalExportChoice Restore(JsonObject export, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport)
    {
        var pins = origin.RequireCurrent(export, transport);
        var known = ReadKnown() ?? throw new InvalidOperationException("notes_choice_source_not_granted");
        var matches = known.Payload["choices"]!.AsArray().OfType<JsonObject>().Where(value =>
            Text(value, "share_id") == Text(export, "share_id") && Text(value, "setup_id") == Text(export, "setup_id") &&
            value["peer"]![0]!.GetValue<string>() == pins.Peer.Id && value["peer"]![1]!.GetValue<string>() == pins.Peer.PublicKey &&
            value["own"]![0]!.GetValue<string>() == pins.Own.Id && value["own"]![1]!.GetValue<string>() == pins.Own.PublicKey).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("notes_choice_source_changed");
        var source = matches[0]; var sourceText = Canonical(source);
        void Current() => RequireRecord(known.Identity, Text(known.Payload, "generation"), Text(known.Payload, "book"), sourceText);
        var choice = new NotesOriginalExportChoice(export, origin, transport, known.Snapshot, capture, _ => Text(source, "local_id"), Current);
        if (Canonical(choice.PrivateSourceBinding()) != sourceText) throw new InvalidOperationException("notes_choice_contact_changed");
        choice.AttachConsent(new(new SealProof(this, choice, known.Identity, Text(known.Payload, "generation"), Text(known.Payload, "book"), sourceText)));
        choice.RequireCurrent(); return choice;
    }

    internal void Revoke()
    {
        var expected = ReadRaw();
        using var current = Read();
        if (current is null || current.Payload["choices"]!.AsArray().Count == 0) return;
        var key = RandomNumberGenerator.GetBytes(32);
        try
        {
            var payload = current.Payload.DeepClone().AsObject(); payload["generation"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
            payload["choices"] = new JsonArray(); payload["content"] = null; Publish(key, payload, expected);
        }
        finally { CryptographicOperations.ZeroMemory(key); }
    }
}
