using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class ContactSourceApprovalStore
{
    // Operation-local writer witness, not a serialized save acknowledgement.
    internal sealed record SaveIntent(ContactSourceApprovalStore Store, string KeyIdentity, string Generation,
        string Token, NativeActorBookSnapshot Previous, string NextContent);

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
    {
        using var before = Active();
        if (before is null) return null;
        var proposed = JsonNode.Parse(nextText) as JsonObject ?? throw new InvalidDataException("contact_source_native_book_required");
        var nextContent = NativeBookJson.Hash(proposed);
        var saved = Saved(); // Native callbacks deliberately outside the file lock.
        if (!SameSnapshot(saved.Snapshot, previous) || Text(before.Payload, "content") != saved.Content ||
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
        var after = Saved();
        if (!SameSnapshot(after.Snapshot, saved.Snapshot) || after.Binding != saved.Binding)
            throw new InvalidOperationException("contact_source_approval_book_changed");
        return new(this, before.Identity, Text(intent, "generation"), Text(intent, "token"), previous, nextContent);
    }

    // Invoke only after actual native writer success AND completion of repairs.
    // Neither proposed JSON nor a renderer acknowledgement can substitute for
    // the separately observed actual current saved-book witness.
    internal string ConfirmSave(SaveIntent expected, NativeActorBookSnapshot confirmed)
    {
        if (expected.Store != this) throw new ArgumentException("contact_source_native_save_intent_required");
        return AdvanceSaved(confirmed, expected) ?? throw new InvalidOperationException("contact_source_save_intent_missing");
    }

    internal string? RecoverSaved(NativeActorBookSnapshot confirmed)
    {
        if (!HasDesiredConsent()) return null;
        return AdvanceSaved(confirmed, null);
    }

    private string? AdvanceSaved(NativeActorBookSnapshot confirmed, SaveIntent? expected)
    {
        var saved = Saved();
        if (!SameSnapshot(saved.Snapshot, confirmed)) throw new InvalidOperationException("contact_source_native_saved_book_required");
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
                NativeBookJson.Hash(JsonNode.Parse(expected.Previous.Text)!) != Text(intent, "old") ||
                expected.Previous.SavedBook.BookSource != confirmed.SavedBook.BookSource ||
                confirmed.SavedBook.Sequence <= expected.Previous.SavedBook.Sequence ||
                SameSnapshot(expected.Previous, confirmed) || saved.Content != Text(intent, "new")))
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
        var after = Saved();
        if (!SameSnapshot(after.Snapshot, saved.Snapshot) || after.Binding != saved.Binding)
            throw new InvalidOperationException("contact_source_approval_book_changed");
        return saved.Content;
    }
}
