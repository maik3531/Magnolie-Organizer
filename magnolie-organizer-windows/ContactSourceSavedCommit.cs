using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record ContactSourceCommitOffer(string Token, string OriginalSha256, JsonArray Contacts);

// Native-issued one-use result/save authority. Returning a provider result or
// receiving a renderer "saved" message does not commit source baselines.
internal sealed class ContactSourceSavedCommit(Func<NativeBookSaveState?> currentSavedBook)
{
    private readonly object gate = new();
    private readonly Func<NativeBookSaveState?> current = currentSavedBook;
    private Pending? pending;
    internal sealed record Pending(string Token, NativeBookSaveState Original, JsonObject Expected)
    { internal bool Writing; }

    internal ContactSourceCommitOffer Stage(NativeActorBookSnapshot snapshot, SavedContactSourceUpdateResult result)
    {
        lock (gate)
        {
            if (pending?.Writing == true || current() != snapshot.SavedBook || result.OriginalBook != snapshot.SavedBook)
                throw new InvalidOperationException("contact_source_saved_book_changed");
            var expected = JsonNode.Parse(snapshot.Text)!.AsObject();
            var before = ContactSourceUpdateRun.SavedContacts(snapshot).OfType<JsonObject>().ToArray();
            var after = result.Contacts.OfType<JsonObject>().ToArray();
            static string Identity(JsonObject contact) => ContactFields.Text(contact, "id") + "\0" + ContactFields.Text(contact, "uid");
            if (before.Length != result.Contacts.Count || after.Length != before.Length ||
                !before.Select(Identity).SequenceEqual(after.Select(Identity)))
                throw new InvalidDataException("contact_source_update_identity_changed");
            expected["kontakte"] = result.Contacts.DeepClone();
            var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
            pending = new(token, snapshot.SavedBook, expected);
            return new(token, snapshot.SavedBook.Sha256, result.Contacts.DeepClone().AsArray());
        }
    }

    // Must be called under the native writer's existing mutation gate. The
    // invocation rechecks again immediately around the real native write.
    internal SaveInvocation Prepare(string token, JsonObject proposed)
    {
        lock (gate)
        {
            var claim = pending;
            Require(claim, token, proposed);
            return new(this, claim!);
        }
    }

    private void Require(Pending? claim, string token, JsonObject proposed)
    {
        if (claim is null || !ReferenceEquals(pending, claim) || claim.Writing || token != claim.Token ||
            current() != claim.Original || !JsonNode.DeepEquals(claim.Expected, proposed))
            throw new InvalidOperationException("contact_source_result_save_not_current");
    }

    internal void Invalidate()
    { lock (gate) pending = null; }

    internal sealed class SaveInvocation
    {
        private readonly ContactSourceSavedCommit owner;
        private readonly Pending claim;
        internal string Token => claim.Token;
        internal bool Completed { get; private set; }
        internal SaveInvocation(ContactSourceSavedCommit owner, Pending claim)
        { this.owner = owner; this.claim = claim; }

        internal void Write(string payload, Action<string> nativeWriter)
        {
            lock (owner.gate)
            {
                var proposed = JsonNode.Parse(payload) as JsonObject ?? throw new InvalidDataException("contact_source_result_invalid");
                owner.Require(claim, claim.Token, proposed);
                claim.Writing = true;
            }
            try
            {
                nativeWriter(payload); // Existing encryption/recovery/atomic writer ONLY.
                lock (owner.gate)
                {
                    var saved = owner.current();
                    if (!ReferenceEquals(owner.pending, claim) || saved is null || saved.BookSource != claim.Original.BookSource ||
                        saved.Sequence != claim.Original.Sequence + 1 || saved.Sha256 != BaumSyncSnapshot.Hash(payload))
                        throw new InvalidOperationException("contact_source_result_save_unconfirmed");
                    owner.pending = null; Completed = true;
                }
            }
            catch
            {
                lock (owner.gate) { if (ReferenceEquals(owner.pending, claim)) owner.pending = null; }
                throw;
            }
        }
    }
}
