using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class ContactSourceApprovalStore
{
    // Operation-local writer witness, not a serialized save acknowledgement.
    internal sealed record SaveIntent(ContactSourceApprovalStore Store, string KeyIdentity, string Generation,
        string Token, NativeActorBookSnapshot? Previous, string NextContent, ContactSourcePrimaryBook? PreviousPrimary = null)
    { internal object? NativeWitness { get; init; } }

    private sealed record SaveWitness(ContactSourceApprovalStore Store, string KeyIdentity, string Generation,
        string Token, NativeActorBookSnapshot? Previous, string NextContent, ContactSourcePrimaryBook? Primary);

    private void RequireSaveWitness(SaveIntent intent)
    {
        if (intent.NativeWitness is not SaveWitness witness || witness.Store != this || intent.Store != this ||
            intent.KeyIdentity != witness.KeyIdentity || intent.Generation != witness.Generation || intent.Token != witness.Token ||
            !ReferenceEquals(intent.Previous, witness.Previous) || intent.NextContent != witness.NextContent ||
            !ReferenceEquals(intent.PreviousPrimary, witness.Primary))
            throw new InvalidOperationException("contact_source_native_save_intent_required");
    }

    private sealed record SaveObservation(string Binding, string Content, NativeActorBookSnapshot? Snapshot, ContactSourcePrimaryBook? Primary)
    {
        internal bool Same(SaveObservation other) => Binding == other.Binding && Content == other.Content &&
            (Snapshot is not null && other.Snapshot is not null ? SameSnapshot(Snapshot, other.Snapshot) :
                Snapshot is null && other.Snapshot is null && Primary is not null && other.Primary is not null && Primary.Same(other.Primary));
    }
    private SaveObservation ObserveSaved()
    { var saved = Saved(); return new(saved.Binding, saved.Content, saved.Snapshot, null); }
    private SaveObservation ObservePrimary()
    {
        var primary = capturePrimary?.Invoke() ?? throw new InvalidOperationException("contact_source_native_primary_required");
        var binding = bookBinding();
        if (binding != primary.Binding) throw new InvalidOperationException("contact_source_native_primary_binding_changed");
        return new(binding, primary.Content, null, primary);
    }

    private JsonObject? ReadIntent(ContactSourcePrivateFiles.Session session, State state)
    {
        var raw = session.Read(".save-intent.json", 16 * 1024);
        if (raw is null) return null;
        var envelope = Parse(raw);
        Fields(envelope, "payload", "mac");
        var intent = envelope["payload"] as JsonObject ?? throw new InvalidDataException("contact_source_save_intent_invalid");
        var signature = Text(envelope, "mac");
        if (!IsHex(signature) || !CryptographicOperations.FixedTimeEquals(Convert.FromHexString(signature),
                Convert.FromHexString(Tag(state.Key, "book-save", Canonical(intent)))))
            throw new CryptographicException("contact_source_save_intent_invalid");
        Fields(intent, "version", "generation", "book", "old", "new", "token");
        if (intent["version"]?.GetValue<int>() != 1 ||
            new[] { "generation", "book", "old", "new", "token" }.Any(name => !IsHex(Text(intent, name))) ||
            Text(intent, "generation") != Text(state.Payload, "generation") || Text(intent, "book") != Text(state.Payload, "book") ||
            ((JsonArray)state.Payload["sources"]!).Count == 0 ||
            (Text(state.Payload, "content") != Text(intent, "old") && Text(state.Payload, "content") != Text(intent, "new")))
            throw new InvalidDataException("contact_source_save_intent_invalid");
        return intent;
    }

    // Signed human intent only; NEVER usable permission. No book/account IO.
    internal bool HasDesiredConsent()
    {
        using var session = files.Open();
        if (session is null) return false;
        using var state = Read(session);
        return ((JsonArray)state.Payload["sources"]!).Count > 0;
    }

    internal SaveIntent? PrepareSave(NativeActorBookSnapshot previous, string nextText)
        => PrepareSaveCore(new SaveObservation("", "", previous, null), nextText, primary: false);

    internal SaveIntent? PreparePrimarySave(ContactSourcePrimaryBook previous, string nextText)
        => PrepareSaveCore(new SaveObservation("", "", null, previous), nextText, primary: true);

    private SaveIntent? PrepareSaveCore(SaveObservation previous, string nextText, bool primary)
    {
        using var before = Active();
        if (before is null) return null;
        if (primary && captureBook() is not null)
            throw new InvalidOperationException("contact_source_primary_requires_unsaved_restart");
        var proposed = JsonNode.Parse(nextText) as JsonObject ?? throw new InvalidDataException("contact_source_native_book_required");
        var nextContent = NativeBookJson.Hash(proposed);
        var saved = primary ? ObservePrimary() : ObserveSaved(); // Callbacks outside the file lock.
        if ((primary ? previous.Primary is null || saved.Primary is null || !saved.Primary.Same(previous.Primary) :
                previous.Snapshot is null || saved.Snapshot is null || !SameSnapshot(saved.Snapshot, previous.Snapshot)) ||
            Text(before.Payload, "content") != saved.Content ||
            Text(before.Payload, "book") != Tag(before.Key, "book", Encoding.UTF8.GetBytes(saved.Binding)))
            throw new InvalidOperationException("contact_source_approval_book_changed");
        var intent = new JsonObject { ["version"] = 1, ["generation"] = Text(before.Payload, "generation"),
            ["book"] = Text(before.Payload, "book"), ["old"] = saved.Content, ["new"] = nextContent,
            ["token"] = Hex(RandomNumberGenerator.GetBytes(32)) };
        using (var session = files.Open() ?? throw new IOException("contact_source_private_store_missing"))
        {
            using var actual = Read(session);
            if (!actual.Key.AsSpan().SequenceEqual(before.Key) || !NativeBookJson.Same(actual.Payload, before.Payload))
                throw new InvalidOperationException("contact_source_approval_context_changed");
            if (ReadIntent(session, actual) is not null) throw new InvalidOperationException("contact_source_native_save_pending");
            session.Write(".save-intent.json", Encoding.UTF8.GetString(Canonical(new JsonObject
                { ["payload"] = intent.DeepClone(), ["mac"] = Tag(before.Key, "book-save", Canonical(intent)) })), 16 * 1024);
            var observed = ReadIntent(session, actual);
            if (observed is null || !NativeBookJson.Same(observed, intent)) throw new IOException("contact_source_save_intent_unconfirmed");
        }
        var after = primary ? ObservePrimary() : ObserveSaved();
        if (!after.Same(saved))
            throw new InvalidOperationException("contact_source_approval_book_changed");
        return new(this, before.Identity, Text(intent, "generation"), Text(intent, "token"), previous.Snapshot, nextContent, previous.Primary)
        { NativeWitness = new SaveWitness(this, before.Identity, Text(intent, "generation"), Text(intent, "token"),
            previous.Snapshot, nextContent, previous.Primary) };
    }

    // Invoke only after actual native writer success AND completion of repairs.
    // Neither proposed JSON nor a renderer acknowledgement can substitute for
    // the separately observed actual current saved-book witness.
    internal string ConfirmSave(SaveIntent expected, NativeActorBookSnapshot confirmed)
    {
        RequireSaveWitness(expected);
        return AdvanceSaved(confirmed, expected) ?? throw new InvalidOperationException("contact_source_save_intent_missing");
    }

    internal string? RecoverSaved(NativeActorBookSnapshot confirmed)
    {
        if (!HasDesiredConsent()) return null;
        return AdvanceSaved(confirmed, null);
    }

    private string? AdvanceSaved(NativeActorBookSnapshot confirmed, SaveIntent? expected)
    {
        var saved = ObserveSaved();
        if (saved.Snapshot is null || !SameSnapshot(saved.Snapshot, confirmed)) throw new InvalidOperationException("contact_source_native_saved_book_required");
        return AdvanceObserved(saved, expected, ObserveSaved);
    }

    internal string? RecoverPrimary(ContactSourcePrimaryBook confirmed)
    {
        if (!HasDesiredConsent()) return null;
        var primary = ObservePrimary();
        if (primary.Primary is null || !primary.Primary.Same(confirmed)) throw new InvalidOperationException("contact_source_native_primary_changed");
        return AdvanceObserved(primary, null, ObservePrimary); // NEVER issues a saved-book or usable approval.
    }

    private string? AdvanceObserved(SaveObservation saved, SaveIntent? expected, Func<SaveObservation> observe)
    {
        using (var session = files.Open() ?? throw new IOException("contact_source_private_store_missing"))
        {
            using var state = Read(session);
            var intent = ReadIntent(session, state);
            if (intent is null)
            {
                if (expected is null) return null;
                throw new InvalidOperationException("contact_source_save_intent_missing");
            }
            if (Text(state.Payload, "book") != Tag(state.Key, "book", Encoding.UTF8.GetBytes(saved.Binding)))
                throw new InvalidOperationException("contact_source_approval_book_changed");
            if (expected is not null && (expected.KeyIdentity != state.Identity || expected.Generation != Text(intent, "generation") ||
                expected.Token != Text(intent, "token") || expected.NextContent != Text(intent, "new") ||
                (expected.Previous is not null ?
                    NativeBookJson.Hash(JsonNode.Parse(expected.Previous.Text)!) != Text(intent, "old") || saved.Snapshot is null ||
                    expected.Previous.SavedBook.BookSource != saved.Snapshot.SavedBook.BookSource ||
                    saved.Snapshot.SavedBook.Sequence <= expected.Previous.SavedBook.Sequence :
                    expected.PreviousPrimary is null || expected.PreviousPrimary.Content != Text(intent, "old") ||
                    expected.PreviousPrimary.Binding != saved.Binding || saved.Snapshot is null) ||
                saved.Content != Text(intent, "new")))
                throw new InvalidOperationException("contact_source_native_save_changed");
            // Recovery cannot adopt unrelated edits or roll a completed new
            // content record back to the old content after an uncertain save.
            if ((saved.Content != Text(intent, "old") && saved.Content != Text(intent, "new")) ||
                (Text(state.Payload, "content") == Text(intent, "new") && saved.Content != Text(intent, "new")))
                throw new InvalidOperationException("contact_source_save_outcome_unknown");
            if (Text(state.Payload, "content") != saved.Content)
            {
                var payload = state.Payload.DeepClone().AsObject(); payload["content"] = saved.Content;
                // Keep the authenticated intent throughout replacement and
                // readback. It quarantines partial/unknown outcomes on failure.
                session.Write("approval.json", Envelope(state.Key, payload), StateLimit);
                using var actual = Read(session);
                if (!actual.Key.AsSpan().SequenceEqual(state.Key) || !NativeBookJson.Same(actual.Payload, payload))
                    throw new IOException("contact_source_save_advance_unconfirmed");
            }
            session.Delete(".save-intent.json");
        }
        var after = observe();
        if (!after.Same(saved))
            throw new InvalidOperationException("contact_source_approval_book_changed");
        return saved.Content;
    }
}
