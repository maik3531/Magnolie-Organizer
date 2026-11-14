using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record ContactSourceNativeResult(ContactSourceCommitOffer? Offer, int SourceErrors, int Grants);

// Shared native command implementation. Consent/network/protection callbacks
// originate in the native host, never in document or bridge arguments.
internal sealed class ContactSourceNativeSession(
    Func<NativeActorBookSnapshot?> captureBook, Func<NativeBookSaveState?> currentBook,
    NextcloudMailboxSettingsStore settings, ContactSourceSavedCommit commit,
    Func<bool> wlanAvailable, Action<NativeActorBookSnapshot> protect,
    HttpClient? transport = null)
{
    private readonly ContactSourceApprovalScope approvals = new(currentBook, settings.ReadSnapshot);
    private readonly object gate = new();
    private CancellationTokenSource? active;
    internal int GrantCount => approvals.Capture().Count;

    internal void Revoke()
    {
        approvals.Revoke(); commit.Invalidate();
        lock (gate) active?.Cancel();
    }

    internal async Task<bool> ConfigureAsync(
        Func<IReadOnlyList<NextcloudDavSource>, IReadOnlyList<string>, CancellationToken,
            Task<IReadOnlyList<string>?>> askNativeUser,
        CancellationToken cancellation = default)
    {
        lock (gate) { if (active is not null) throw new InvalidOperationException("native_busy"); }
        var snapshot = captureBook() ?? throw new InvalidOperationException("contact_source_book_not_saved");
        _ = ContactSourceUpdateRun.SavedContacts(snapshot);
        var account = settings.ReadSnapshot();
        if (account.Settings?.DavActive != true || !account.CredentialPresent)
            throw new UnauthorizedAccessException("contact_source_account_not_available");
        using var client = new NextcloudDavClient(settings, transport);
        var catalog = await client.ListSourcesAsync(cancellation, calendars: false);
        if (currentBook() != snapshot.SavedBook || settings.ReadSnapshot().Revision != account.Revision)
            throw new InvalidOperationException("contact_source_approval_context_changed");
        return await approvals.ConfigureAsync(catalog.AddressBooks, askNativeUser, cancellation);
    }

    internal async Task<ContactSourceNativeResult> RunAsync(string expectedSavedHash,
        CancellationToken cancellation = default, string homeCountry = "")
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        lock (gate)
        {
            if (active is not null) throw new InvalidOperationException("native_busy");
            active = lifetime;
        }
        try
        {
            NativeActorBookSnapshot snapshot;
            IReadOnlyList<NativeDavContactUpdateApproval> grants;
            await MutationGate.Global.WaitAsync(lifetime.Token);
            try
            {
                snapshot = captureBook() ?? throw new InvalidOperationException("contact_source_book_not_saved");
                _ = ContactSourceUpdateRun.SavedContacts(snapshot);
                if (snapshot.SavedBook.Sha256 != expectedSavedHash)
                    throw new InvalidOperationException("contact_source_saved_book_changed");
                grants = approvals.Capture();
            }
            finally { MutationGate.Global.Release(); }
            if (grants.Count == 0) return new(null, 0, 0);
            void RequireWlan()
            {
                lifetime.Token.ThrowIfCancellationRequested();
                if (!wlanAvailable()) throw new InvalidOperationException("contact_source_wlan_required");
            }
            RequireWlan();
            grants = grants.Select(grant => grant with { RequireApproved = async token =>
            {
                RequireWlan(); await grant.RequireApproved(token); RequireWlan();
            } }).ToArray();
            var protectedOriginal = false;
            async Task Protect(NativeActorBookSnapshot original, CancellationToken token)
            {
                await MutationGate.Global.WaitAsync(token);
                try
                {
                    RequireWlan();
                    if (currentBook() != original.SavedBook) throw new InvalidOperationException("contact_source_saved_book_changed");
                    if (!protectedOriginal)
                    {
                        protect(original);
                        if (currentBook() != original.SavedBook) throw new InvalidOperationException("contact_source_saved_book_changed");
                        protectedOriginal = true;
                    }
                }
                finally { MutationGate.Global.Release(); }
            }
            var result = await ContactSourceSavedDavRun.RunAsync(() => snapshot, currentBook, grants,
                _ => settings, Protect, lifetime.Token, homeCountry, _ => transport);
            await MutationGate.Global.WaitAsync(lifetime.Token);
            try
            {
                if (currentBook() != snapshot.SavedBook) throw new InvalidOperationException("contact_source_saved_book_changed");
                var offer = JsonNode.DeepEquals(ContactSourceUpdateRun.SavedContacts(snapshot), result.Contacts)
                    ? null : commit.Stage(snapshot, result);
                return new(offer, result.Sources.Values.Sum(value => value.Errors), GrantCount);
            }
            finally { MutationGate.Global.Release(); }
        }
        finally { lock (gate) { if (ReferenceEquals(active, lifetime)) active = null; } }
    }
}
