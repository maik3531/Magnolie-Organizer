namespace MagnolieOrganizer.Windows;

// Session-local native consent authority. No JSON loader/setter and no implicit
// grant from discovery, a mapping, account availability or renderer settings.
// A native settings UI must supply the explicit decision callback. This is NOT
// persistent consent: restarting/locking/changing account requires approval anew.
internal sealed class ContactSourceApprovalScope
{
    private readonly object gate = new();
    private readonly Func<NativeBookSaveState?> currentBook;
    private readonly Func<NextcloudSettingsSnapshot> currentAccount;
    private readonly Dictionary<string, Uri> approved = new(StringComparer.Ordinal);
    private string owner = "", revision = "";
    private long generation;
    private sealed class ConsentWitness(ContactSourceApprovalScope owner, string source, Uri collection, string revision, long generation)
    {
        internal void Require(NativeDavContactUpdateApproval approval, CancellationToken cancellation)
        {
            if (approval.Source != source || approval.Collection != collection || approval.Collection.OriginalString != collection.OriginalString ||
                approval.AccountRevision != revision)
                throw new UnauthorizedAccessException("contact_source_native_decision_retargeted");
            owner.Require(generation, source, collection, revision, cancellation);
        }
    }

    internal static void RequireNativeDecision(NativeDavContactUpdateApproval approval, CancellationToken cancellation)
    {
        if (approval.NativeConsent is not ConsentWitness witness)
            throw new UnauthorizedAccessException("contact_source_native_decision_required");
        witness.Require(approval, cancellation);
    }

    private void Require(long capturedGeneration, string source, Uri collection, string capturedRevision, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        lock (gate)
        {
            InvalidateStale(currentBook(), currentAccount());
            if (generation != capturedGeneration || revision != capturedRevision || !approved.TryGetValue(source, out var href) || href != collection)
                throw new UnauthorizedAccessException("contact_source_explicit_approval_withdrawn");
        }
        cancellation.ThrowIfCancellationRequested();
    }

    internal ContactSourceApprovalScope(Func<NativeBookSaveState?> currentBook,
        Func<NextcloudSettingsSnapshot> currentAccount)
    { this.currentBook = currentBook; this.currentAccount = currentAccount; }

    internal void Revoke()
    {
        lock (gate)
        { approved.Clear(); owner = revision = ""; generation++; }
    }

    // The callback is a native user-decision boundary, NOT a renderer answer or
    // automatic "all writable sources" predicate. Null means explicit cancel.
    internal async Task<bool> ConfigureAsync(IReadOnlyList<NextcloudDavSource> nativeCatalog,
        Func<IReadOnlyList<NextcloudDavSource>, IReadOnlyList<string>, CancellationToken,
            Task<IReadOnlyList<string>?>> askNativeUser,
        CancellationToken cancellation = default)
    {
        ArgumentNullException.ThrowIfNull(askNativeUser);
        cancellation.ThrowIfCancellationRequested();
        var book = currentBook() ?? throw new InvalidOperationException("contact_source_book_not_saved");
        var account = currentAccount();
        if (account.Settings?.DavActive != true || !account.CredentialPresent || string.IsNullOrEmpty(account.Revision) ||
            account.Settings.AccountType is not ("nextcloud" or "generic-dav"))
            throw new UnauthorizedAccessException("contact_source_account_not_available");
        var choices = nativeCatalog.Where(source => source.CanUpdate == true && !source.ReadOnly &&
            source.Uid == NextcloudDavClient.StableSourceId("addressbook", source.Href, account.Settings.AccountType)).ToArray();
        if (choices.Select(source => source.Uid).Distinct(StringComparer.Ordinal).Count() != choices.Length)
            throw new InvalidDataException("contact_source_approval_catalog_ambiguous");
        long originalGeneration; string[] selected;
        lock (gate)
        {
            InvalidateStale(book, account);
            originalGeneration = generation;
            selected = approved.Keys.ToArray();
        }
        var answer = await askNativeUser(Array.AsReadOnly(choices), Array.AsReadOnly(selected), cancellation);
        cancellation.ThrowIfCancellationRequested();
        lock (gate)
        {
            if (generation != originalGeneration || currentBook() != book || currentAccount().Revision != account.Revision)
                throw new InvalidOperationException("contact_source_approval_context_changed");
            if (answer is null) return false;
            var ids = answer.ToArray();
            if (ids.Distinct(StringComparer.Ordinal).Count() != ids.Length || ids.Any(id => !choices.Any(source => source.Uid == id)))
                throw new InvalidDataException("contact_source_approval_selection_invalid");
            approved.Clear();
            foreach (var id in ids) approved.Add(id, choices.Single(source => source.Uid == id).Href);
            owner = book.BookSource; revision = account.Revision; generation++;
            return true;
        }
    }

    internal IReadOnlyList<NativeDavContactUpdateApproval> Capture()
    {
        lock (gate)
        {
            if (approved.Count == 0) return [];
            InvalidateStale(currentBook(), currentAccount());
            var capturedGeneration = generation;
            var capturedRevision = revision;
            return approved.Select(pair =>
            {
                var witness = new ConsentWitness(this, pair.Key, pair.Value, capturedRevision, capturedGeneration);
                return new NativeDavContactUpdateApproval(pair.Key, pair.Value, capturedRevision, token =>
                    { Require(capturedGeneration, pair.Key, pair.Value, capturedRevision, token); return Task.CompletedTask; }) { NativeConsent = witness };
            }).ToArray();
        }
    }

    private void InvalidateStale(NativeBookSaveState? book, NextcloudSettingsSnapshot account)
    {
        if (approved.Count > 0 && (book?.BookSource != owner || account.Revision != revision ||
            account.Settings?.DavActive != true || !account.CredentialPresent))
        { approved.Clear(); owner = revision = ""; generation++; }
    }
}
