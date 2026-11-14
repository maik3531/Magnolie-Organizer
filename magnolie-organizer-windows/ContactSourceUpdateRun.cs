using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Trusted native admissions only, never objects deserialized from the renderer
// or saved mappings. CanUpdate is a CURRENT native capability observation;
// RequireCurrent must recheck the exact source/connection/grant before each IO.
internal sealed record ContactSourceAdmission(string Source, IContactRemote Remote, bool? CanUpdate,
    Func<CancellationToken, Task> RequireCurrent);
internal sealed record ContactSourceUpdateResult(JsonArray Contacts,
    IReadOnlyDictionary<string, ContactSyncCounts> Sources);
internal sealed record SavedContactSourceUpdateResult(NativeBookSaveState OriginalBook,
    JsonArray Contacts, IReadOnlyDictionary<string, ContactSyncCounts> Sources);

// Update existing original bindings ONLY. No create/delete, default-addressbook
// retarget, UID guess, new provider grant, or independent success cursor.
internal static class ContactSourceUpdateRun
{
    // Automatic callers must use a native durable-save witness, not a renderer
    // "saved" flag, an imported syncEpoch, or request-supplied contact JSON.
    // Admissions are still produced separately from explicit native grants and
    // fresh provider observations; no document field here can grant a source.
    internal static async Task<SavedContactSourceUpdateResult> RunSavedAsync(
        Func<NativeActorBookSnapshot?> captureSavedBook, Func<NativeBookSaveState?> currentSavedBook,
        IReadOnlyList<ContactSourceAdmission> admissions, CancellationToken cancellation = default,
        string homeCountry = "")
    {
        cancellation.ThrowIfCancellationRequested();
        var snapshot = captureSavedBook() ?? throw new InvalidOperationException("contact_source_book_not_saved");
        var contacts = SavedContacts(snapshot);
        void RequireOriginal()
        {
            cancellation.ThrowIfCancellationRequested();
            if (currentSavedBook() != snapshot.SavedBook)
                throw new InvalidOperationException("contact_source_saved_book_changed");
        }
        RequireOriginal();
        var result = await RunAsync(contacts, admissions, () => Task.CompletedTask, RequireOriginal, cancellation, homeCountry);
        RequireOriginal();
        return new(snapshot.SavedBook, result.Contacts, result.Sources);
    }

    internal static JsonArray SavedContacts(NativeActorBookSnapshot snapshot)
    {
        var data = JsonNode.Parse(snapshot.Text) as JsonObject ?? throw new InvalidDataException("contact_source_book_invalid");
        if (data["kontakte"] is not JsonArray contacts) throw new InvalidDataException("contact_source_book_invalid");
        if (data["syncNachRestore"]?["additiv"]?.GetValue<bool>() == true ||
            data["syncNachRestore"]?["loeschungsfrei"]?.GetValue<bool>() == true ||
            data["syncMetadaten"]?["ersteSyncLoeschungsfrei"]?.GetValue<bool>() == true)
            throw new InvalidOperationException("contact_source_restore_pending");
        return contacts;
    }

    internal static async Task<ContactSourceUpdateResult> RunAsync(JsonArray originalContacts,
        IReadOnlyList<ContactSourceAdmission> admissions, Func<Task> requireSaved,
        Action originalCurrent, CancellationToken cancellation = default, string homeCountry = "")
    {
        if (admissions.Any(source => string.IsNullOrWhiteSpace(source.Source)) ||
            admissions.GroupBy(source => source.Source, StringComparer.Ordinal).Any(group => group.Count() != 1))
            throw new InvalidDataException("contact_source_admission_ambiguous");
        var contacts = originalContacts.DeepClone().AsArray();
        var results = new Dictionary<string, ContactSyncCounts>(StringComparer.Ordinal);
        originalCurrent(); cancellation.ThrowIfCancellationRequested();
        await requireSaved(); // Original durable SaveACK, not mere local editing.
        originalCurrent(); cancellation.ThrowIfCancellationRequested();
        foreach (var admission in admissions)
        {
            originalCurrent(); cancellation.ThrowIfCancellationRequested();
            var bound = contacts.OfType<JsonObject>().Where(contact => contact["sync"]?.GetValue<bool>() == true &&
                ContactFields.Source(contact, admission.Source) is JsonObject mapping && ContactFields.Text(mapping, "id").Length > 0 &&
                ContactFields.Dirty(contact, mapping)).ToArray();
            if (bound.Length == 0) continue;
            if (admission.CanUpdate != true)
            { results[admission.Source] = new(0, 0, 0, 0, bound.Length); continue; }
            try
            {
                var remote = new BoundRemote(admission, bound, originalCurrent);
                var selected = new JsonArray(bound.Select(item => (JsonNode)item.DeepClone()).ToArray());
                var result = await new ContactSyncEngine().SyncAsync(admission.Source, selected, [], 0, remote, cancellation,
                    beforeMutation: () => remote.CheckAsync(cancellation), homeCountry: homeCountry);
                originalCurrent(); cancellation.ThrowIfCancellationRequested();
                // A native run may produce a retained source-specific conflict,
                // but never append a different provider record or drop a person.
                var returned = result.Contacts.OfType<JsonObject>().ToArray();
                if (returned.Length != bound.Length || result.Tombstones.Count != 0 ||
                    !returned.Select(LocalId).Order(StringComparer.Ordinal).SequenceEqual(bound.Select(LocalId).Order(StringComparer.Ordinal)) ||
                    returned.Any(item => ContactFields.Text(item, "uid") != ContactFields.Text(bound.Single(before => LocalId(before) == LocalId(item)), "uid")))
                    throw new InvalidDataException("contact_source_update_identity_changed");
                foreach (var item in returned)
                {
                    var index = contacts.IndexOf(bound.Single(before => LocalId(before) == LocalId(item)));
                    contacts[index] = item.DeepClone();
                }
                results[admission.Source] = result.Counts;
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception)
            {
                // Unknown write/readback leaves this source's original baseline
                // pending; another independently admitted source may continue.
                originalCurrent(); cancellation.ThrowIfCancellationRequested();
                results[admission.Source] = new(0, 0, 0, 0, bound.Length);
            }
        }
        return new(contacts, results);
    }
    private static string LocalId(JsonObject contact)
    {
        var id = ContactFields.Text(contact, "id");
        if (id.Length == 0 || ContactFields.Text(contact, "uid").Length == 0)
            throw new InvalidDataException("contact_source_local_identity_missing");
        return id;
    }
    private sealed class BoundRemote : IContactRemote
    {
        private readonly ContactSourceAdmission admission;
        private readonly Action originalCurrent;
        private readonly Dictionary<string, string> bindings;
        internal BoundRemote(ContactSourceAdmission admission, JsonObject[] contacts, Action originalCurrent)
        {
            this.admission = admission; this.originalCurrent = originalCurrent;
            if (contacts.Select(LocalId).Distinct(StringComparer.Ordinal).Count() != contacts.Length)
                throw new InvalidDataException("contact_source_local_identity_ambiguous");
            bindings = contacts.ToDictionary(contact => ContactFields.Text(ContactFields.Source(contact, admission.Source)!, "id"),
                contact => ContactFields.Text(contact, "uid"), StringComparer.Ordinal);
        }
        public bool SupportsYearlessBirthdays => admission.Remote.SupportsYearlessBirthdays;
        public bool? CanWrite => admission.CanUpdate == true && admission.Remote.CanWrite != false;
        internal async Task CheckAsync(CancellationToken cancellation)
        {
            originalCurrent(); cancellation.ThrowIfCancellationRequested();
            await admission.RequireCurrent(cancellation);
            originalCurrent(); cancellation.ThrowIfCancellationRequested();
        }
        public async Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellation)
        {
            await CheckAsync(cancellation);
            var all = await admission.Remote.ReadAsync(cancellation);
            await CheckAsync(cancellation);
            var selected = all.Where(item => bindings.ContainsKey(item.Id)).ToArray();
            if (selected.Length != bindings.Count || selected.Select(item => item.Id).Distinct(StringComparer.Ordinal).Count() != bindings.Count)
                throw new InvalidDataException("contact_source_original_record_missing_or_ambiguous");
            return selected;
        }
        public async Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellation)
        {
            if (!bindings.TryGetValue(remote.Id, out var originalUid) || uid != originalUid || ContactFields.Text(contact, "uid") != originalUid)
                throw new InvalidDataException("contact_source_original_binding_required");
            await CheckAsync(cancellation);
            // Receipt.Data deliberately projects the canonical local UID. Only
            // the pre-write source UID can witness native provider identity;
            // content hashes intentionally do not include it (#617).
            var originalNativeUid = ContactFields.Text(remote.Data, "uid");
            var written = await admission.Remote.UpdateAsync(remote, uid, contact, cancellation);
            await CheckAsync(cancellation);
            if (written.Id != remote.Id || string.IsNullOrWhiteSpace(written.ETag) || written.ETag.Trim() == "*")
                throw new InvalidDataException("contact_source_write_receipt_unbound");
            var readback = await admission.Remote.ReadAsync(cancellation);
            await CheckAsync(cancellation);
            var matches = readback.Where(item => item.Id == remote.Id).ToArray();
            if (matches.Length != 1 || matches[0].ETag != written.ETag ||
                ContactFields.Text(matches[0].Data, "uid") != originalNativeUid ||
                ContactFields.ContentHash(matches[0].Data) != ContactFields.ContentHash(written.Data))
                throw new InvalidDataException("contact_source_write_readback_changed");
            return written; // Keep adapter's canonical UID projection, verified against actual source readback.
        }
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellation) =>
            throw new InvalidOperationException("contact_source_update_cannot_create");
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellation) =>
            throw new InvalidOperationException("contact_source_update_cannot_delete");
    }
}
