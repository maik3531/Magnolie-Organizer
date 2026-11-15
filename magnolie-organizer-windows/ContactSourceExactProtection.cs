using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Called under the actual native book gate before provider IO. Archive content
// equality is coverage ONLY; independent actual saved/primary authority is required.
internal sealed class ContactSourceExactProtection(RecoveryJournal journal, string nativeBinding,
    Func<NativeActorBookSnapshot?> capture, Func<ContactSourcePrimaryBook> primary, string appVersion,
    Func<string, string>? protect = null, Func<string, string>? unprotect = null)
{
    internal SnapshotInfo Protect(NativeActorBookSnapshot original)
    {
        ArgumentNullException.ThrowIfNull(original);
        if (!Path.IsPathFullyQualified(nativeBinding)) throw new InvalidOperationException("contact_source_native_binding_required");
        var data = JsonNode.Parse(original.Text) as JsonObject ?? throw new InvalidDataException("contact_source_original_book_required");
        var content = NativeBookJson.Hash(data);
        void RequireSaved()
        {
            if (capture()?.SavedBook != original.SavedBook) throw new InvalidOperationException("contact_source_saved_book_changed");
        }
        RequireSaved();
        var before = primary();
        if (before.Binding != Path.GetFullPath(nativeBinding) || before.PlainHash != original.SavedBook.Sha256 || before.Content != content)
            throw new InvalidOperationException("contact_source_native_primary_changed");
        if (before.Encrypted != (protect is not null))
            throw new InvalidOperationException("contact_source_protection_encryption_changed");
        var point = journal.CreateExactBook(data, appVersion, protect, unprotect);
        var payload = journal.ReadPayload(point.Id);
        if (EncryptionService.IsEncrypted(payload))
            payload = (unprotect ?? throw new InvalidOperationException("contact_source_protection_session_required"))(payload);
        var actual = GesamtarchivService.ReadOriginalBook(payload).Daten;
        if (NativeBookJson.Hash(actual) != content) throw new InvalidOperationException("contact_source_exact_protection_required");
        RequireSaved();
        if (!before.Same(primary())) throw new InvalidOperationException("contact_source_native_primary_changed");
        RequireSaved();
        return point;
    }
}
