using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native orchestration only. Account resolution, approvals and protection are
// trusted callbacks; none are reconstructed from the saved book or renderer.
// Returned baselines are staged data, NOT a durable save/commit acknowledgment.
internal static class ContactSourceSavedDavRun
{
    internal static async Task<SavedContactSourceUpdateResult> RunAsync(
        Func<NativeActorBookSnapshot?> captureSavedBook,
        Func<NativeBookSaveState?> currentSavedBook,
        IReadOnlyList<NativeDavContactUpdateApproval> approvals,
        Func<NativeDavContactUpdateApproval, NextcloudMailboxSettingsStore> accountForApproval,
        Func<NativeActorBookSnapshot, CancellationToken, Task> protectBeforeMutation,
        CancellationToken cancellation = default, string homeCountry = "",
        Func<NativeDavContactUpdateApproval, HttpClient?>? transportForApproval = null)
    {
        ArgumentNullException.ThrowIfNull(protectBeforeMutation);
        cancellation.ThrowIfCancellationRequested();
        var snapshot = captureSavedBook() ?? throw new InvalidOperationException("contact_source_book_not_saved");
        // Restore/save fences apply BEFORE even provider discovery, not only
        // before the eventual content read or write in the coordinator.
        var contacts = ContactSourceUpdateRun.SavedContacts(snapshot);
        if (approvals.Any(item => string.IsNullOrWhiteSpace(item.Source)) ||
            approvals.Select(item => item.Source).Distinct(StringComparer.Ordinal).Count() != approvals.Count)
            throw new InvalidDataException("contact_source_admission_ambiguous");
        void RequireOriginal()
        {
            cancellation.ThrowIfCancellationRequested();
            if (currentSavedBook() != snapshot.SavedBook)
                throw new InvalidOperationException("contact_source_saved_book_changed");
        }
        RequireOriginal();
        var factories = new List<ContactSourceDavFactory>();
        var admissions = new List<ContactSourceAdmission>();
        try
        {
            foreach (var approval in approvals)
            {
                RequireOriginal();
                // An approved but unbound/clean source needs no provider IO.
                // This is a plan filter, never a grant inferred from mappings.
                if (!contacts.OfType<JsonObject>().Any(contact => contact["sync"]?.GetValue<bool>() == true &&
                    ContactFields.Source(contact, approval.Source) is JsonObject mapping &&
                    ContactFields.Text(mapping, "id").Length > 0 && ContactFields.Dirty(contact, mapping))) continue;
                try
                {
                    var factory = await ContactSourceDavFactory.OpenAsync(accountForApproval(approval), approval,
                        RequireOriginal, token => protectBeforeMutation(snapshot, token), cancellation,
                        transportForApproval?.Invoke(approval));
                    factories.Add(factory);
                    RequireOriginal();
                    admissions.Add(factory.Admission);
                }
                catch (OperationCanceledException) { throw; }
                catch (Exception)
                {
                    // Missing/revoked/offline accounts and unknown privileges
                    // hold only this source. Book/lifetime changes still abort.
                    RequireOriginal();
                    admissions.Add(new(approval.Source, HeldRemote.Instance, null, _ => Task.CompletedTask));
                }
            }
            RequireOriginal();
            return await ContactSourceUpdateRun.RunSavedAsync(() => snapshot, currentSavedBook,
                admissions, cancellation, homeCountry);
        }
        finally
        {
            foreach (var factory in factories) factory.Dispose();
        }
    }

    private sealed class HeldRemote : IContactRemote
    {
        internal static readonly HeldRemote Instance = new();
        public bool? CanWrite => false;
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken token) =>
            throw new InvalidOperationException("contact_source_held");
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken token) =>
            throw new InvalidOperationException("contact_source_update_cannot_create");
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken token) =>
            throw new InvalidOperationException("contact_source_held");
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken token) =>
            throw new InvalidOperationException("contact_source_update_cannot_delete");
    }
}
