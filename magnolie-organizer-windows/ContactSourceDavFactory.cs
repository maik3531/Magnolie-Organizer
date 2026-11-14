namespace MagnolieOrganizer.Windows;

// Native caller inputs only. A discovered collection or saved contact mapping
// must never be converted to this approval without a separate explicit grant.
internal sealed record NativeDavContactUpdateApproval(string Source, Uri Collection,
    string AccountRevision, Func<CancellationToken, Task> RequireApproved);

// One connection per approved source: no shared mutable BeforeMutation callback
// and no routing of Thunderbird/Graph/system books through a DAV account.
internal sealed class ContactSourceDavFactory : IDisposable
{
    private readonly NextcloudMailboxSettingsStore settings;
    private readonly NativeDavContactUpdateApproval approval;
    private readonly Action requireBookCurrent;
    private readonly Func<CancellationToken, Task> protectBeforeMutation;
    private readonly NextcloudDavClient client;
    private readonly CancellationToken lifetime;
    private bool disposed;
    internal ContactSourceAdmission Admission { get; private set; } = null!;

    private ContactSourceDavFactory(NextcloudMailboxSettingsStore settings,
        NativeDavContactUpdateApproval approval, Action requireBookCurrent,
        Func<CancellationToken, Task> protectBeforeMutation, HttpClient? transport,
        CancellationToken cancellation)
    {
        this.settings = settings; this.approval = approval;
        this.requireBookCurrent = requireBookCurrent;
        this.protectBeforeMutation = protectBeforeMutation; lifetime = cancellation;
        client = new NextcloudDavClient(settings, transport);
        client.BeforeMutation = async () =>
        {
            await RequireCurrentAsync(lifetime);
            await protectBeforeMutation(lifetime);
            // Snapshot creation is asynchronous: recheck approval, connection,
            // book and actual privilege again before the prepared PUT is sent.
            await RequireCurrentAsync(lifetime);
        };
    }

    internal static async Task<ContactSourceDavFactory> OpenAsync(
        NextcloudMailboxSettingsStore settings, NativeDavContactUpdateApproval approval,
        Action requireBookCurrent, Func<CancellationToken, Task> protectBeforeMutation,
        CancellationToken cancellation = default, HttpClient? transport = null)
    {
        ArgumentNullException.ThrowIfNull(approval.RequireApproved);
        ArgumentNullException.ThrowIfNull(requireBookCurrent);
        ArgumentNullException.ThrowIfNull(protectBeforeMutation);
        var factory = new ContactSourceDavFactory(settings, approval, requireBookCurrent,
            protectBeforeMutation, transport, cancellation);
        try
        {
            var source = await factory.ObserveCurrentAsync(cancellation);
            factory.Admission = new(approval.Source, new NextcloudCardDavRemote(factory.client, source),
                source.CanUpdate, factory.RequireCurrentAsync);
            return factory;
        }
        catch { factory.Dispose(); throw; }
    }

    private async Task RequireAuthorityAsync(CancellationToken cancellation)
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        lifetime.ThrowIfCancellationRequested(); cancellation.ThrowIfCancellationRequested();
        requireBookCurrent();
        await approval.RequireApproved(cancellation);
        requireBookCurrent();
        lifetime.ThrowIfCancellationRequested(); cancellation.ThrowIfCancellationRequested();
        var current = settings.ReadSnapshot();
        var accountType = current.Settings?.AccountType;
        if (current.Revision != approval.AccountRevision || string.IsNullOrEmpty(approval.AccountRevision) ||
            current.Settings?.DavActive != true || !current.CredentialPresent ||
            accountType is not ("nextcloud" or "generic-dav") ||
            approval.Source != NextcloudDavClient.StableSourceId("addressbook", approval.Collection, accountType))
            throw new UnauthorizedAccessException("contact_source_account_or_approval_changed");
    }

    private async Task<NextcloudDavSource> ObserveCurrentAsync(CancellationToken cancellation)
    {
        await RequireAuthorityAsync(cancellation);
        var sources = await client.ListSourcesAsync(cancellation, calendars: false);
        await RequireAuthorityAsync(cancellation);
        var matches = sources.AddressBooks.Where(source => source.Uid == approval.Source).ToArray();
        if (matches.Length != 1 || matches[0].Href != approval.Collection ||
            matches[0].ReadOnly || matches[0].CanUpdate != true)
            throw new UnauthorizedAccessException("contact_source_update_not_currently_allowed");
        return matches[0];
    }

    private async Task RequireCurrentAsync(CancellationToken cancellation) =>
        _ = await ObserveCurrentAsync(cancellation);

    public void Dispose()
    {
        if (disposed) return;
        disposed = true; client.Dispose();
    }
}
