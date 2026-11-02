namespace MagnolieOrganizer.Windows;

internal sealed record PhotoContentWitness
{
    internal string Sha256 { get; }
    internal long Size { get; }
    internal PhotoContentWitness(string sha256, long size)
    {
        RequireSha(sha256);
        if (size is < 0 or > DeviceFileManifest.MaxFileBytes) throw new InvalidDataException("photo_plan_invalid_content_size");
        Sha256 = sha256; Size = size;
    }
    internal static void RequireSha(string value)
    {
        if (value is not { Length: 64 } || value.Any(character => !char.IsAsciiHexDigitLower(character)))
            throw new InvalidDataException("photo_plan_invalid_witness");
    }
}

internal sealed record NativePhotoAssociation
{
    internal DeviceTransferBinding Binding { get; }
    internal string SourceEpoch { get; }
    internal string PhotoId { get; }
    internal string TargetMappingToken { get; }
    internal NativePhotoAssociation(DeviceTransferBinding binding, string sourceEpoch, string photoId, string targetMappingToken)
    {
        binding.Validate();
        if (binding.SenderId == binding.ReceiverId || new[] { binding.SenderId, binding.ReceiverId }.Any(id =>
            id is not { Length: >= 16 and <= 160 } || id.Any(character => !char.IsAsciiLetterOrDigit(character) && character is not ('_' or '-'))))
            throw new InvalidDataException("photo_plan_invalid_native_association");
        foreach (var value in new[] { sourceEpoch, photoId, targetMappingToken }) PhotoContentWitness.RequireSha(value);
        Binding = binding; SourceEpoch = sourceEpoch; PhotoId = photoId; TargetMappingToken = targetMappingToken;
    }
}

internal sealed record NativePhotoBaseline
{
    internal NativePhotoAssociation Association { get; }
    internal PhotoContentWitness Content { get; }
    internal string ReceiptSha256 { get; }
    internal NativePhotoBaseline(NativePhotoAssociation association, PhotoContentWitness content, string receiptSha256)
    {
        ArgumentNullException.ThrowIfNull(association); ArgumentNullException.ThrowIfNull(content);
        PhotoContentWitness.RequireSha(receiptSha256);
        Association = association; Content = content; ReceiptSha256 = receiptSha256;
    }
}

internal sealed record NativePhotoObservation
{
    // "missing" never means deletion. "deleted" requires genuine native
    // deletion evidence, not an incomplete scan or Android permission flag.
    internal string State { get; }
    internal PhotoContentWitness? Content { get; }
    internal bool Managed { get; }
    internal bool InsertionProven { get; }
    internal NativePhotoObservation(string state, PhotoContentWitness? content = null, bool managed = false, bool insertionProven = false)
    {
        if (state is not ("present" or "missing" or "deleted" or "unknown") ||
            (state == "present" ? content is null : content is not null || managed || insertionProven))
            throw new InvalidDataException("photo_plan_invalid_native_observation");
        State = state; Content = content; Managed = managed; InsertionProven = insertionProven;
    }
}

internal sealed record PhotoSyncPlanPolicy
{
    internal string Direction { get; }
    internal bool PhoneDeletionsToDesktop { get; }
    internal bool DesktopDeletionsToPhone { get; }
    internal PhotoSyncPlanPolicy(string direction = "phone_to_desktop", bool phoneDeletionsToDesktop = false, bool desktopDeletionsToPhone = false)
    {
        if (direction is not ("phone_to_desktop" or "bidirectional")) throw new InvalidDataException("photo_plan_invalid_policy");
        Direction = direction; PhoneDeletionsToDesktop = phoneDeletionsToDesktop; DesktopDeletionsToPhone = desktopDeletionsToPhone;
    }
}

// Genuine native no-loss adapters only, never activated by a wire/UI Boolean.
internal sealed record NativePhotoPlanSupport(bool CreateDesktop = false, bool ReplaceDesktop = false,
    bool TrashDesktop = false, bool ReplacePhone = false, bool DeletePhone = false);

internal sealed record PhotoSyncProposal(string Kind, string? BaselineReceipt,
    PhotoContentWitness? ExpectedPhone, PhotoContentWitness? ExpectedDesktop)
{
    internal bool GrantsWriteAuthority => false;
    internal bool IsSavedReceipt => false;
}

// Pure three-way comparison only. Inputs belong to authenticated native receipt
// storage/observations, never network claims. No I/O, accepted baseline, writes,
// deletions or saved receipt is produced. Execution needs separate fresh native
// identity/grants/ownership/CAS and actual publication/readback.
internal static class PhotoSyncPlan
{
    internal static PhotoSyncProposal Compare(NativePhotoAssociation association, NativePhotoBaseline? baseline,
        NativePhotoObservation phone, NativePhotoObservation desktop, PhotoSyncPlanPolicy? policy = null, NativePhotoPlanSupport? support = null)
    {
        ArgumentNullException.ThrowIfNull(association); ArgumentNullException.ThrowIfNull(phone); ArgumentNullException.ThrowIfNull(desktop);
        policy ??= new(); support ??= new();
        PhotoSyncProposal Result(string kind) => new(kind, baseline?.ReceiptSha256, phone.Content, desktop.Content);
        if (baseline is not null && baseline.Association != association) return Result("pause_scope_changed");
        if (phone.State == "unknown" || desktop.State == "unknown") return Result("pause_unknown");
        if (baseline is null)
        {
            if (phone.State == "present")
            {
                if (desktop.State == "present") return Result("conflict_unmanaged_target");
                return Result(support.CreateDesktop ? "copy_phone_new" : "unsupported_desktop_create");
            }
            return Result(desktop.State == "present" ? "keep_unmanaged_desktop" : "nothing_to_sync");
        }
        if (phone.State == "missing" || desktop.State == "missing") return Result("pause_unconfirmed_absence");
        if (desktop.State == "present" && !desktop.Managed) return Result("conflict_unmanaged_target");
        var common = baseline.Content;
        if (phone.State == "present" && desktop.State == "present")
        {
            if (phone.Content == common && desktop.Content == common) return Result("unchanged");
            if (phone.Content == desktop.Content) return Result(phone.InsertionProven ? "confirm_equal_content" : "conflict_unproven_source_identity");
            if (phone.Content != common && desktop.Content != common) return Result("conflict_edit_edit");
            if (phone.Content != common)
            {
                if (!phone.InsertionProven) return Result("conflict_unproven_source_identity");
                return Result(support.ReplaceDesktop ? "replace_managed_desktop" : "unsupported_desktop_replace");
            }
            if (policy.Direction == "phone_to_desktop") return Result("keep_local_edit");
            if (!phone.InsertionProven) return Result("conflict_unproven_source_identity");
            return Result(support.ReplacePhone ? "replace_phone" : "unsupported_phone_replace");
        }
        if (phone.State == "deleted" && desktop.State == "deleted") return Result("both_deleted");
        if (phone.State == "deleted")
        {
            if (desktop.Content != common) return Result("conflict_edit_delete");
            if (!policy.PhoneDeletionsToDesktop) return Result("keep_desktop_copy");
            return Result(support.TrashDesktop ? "trash_managed_desktop" : "unsupported_desktop_trash");
        }
        if (phone.Content != common) return Result("conflict_edit_delete");
        if (!policy.DesktopDeletionsToPhone) return Result("keep_phone_copy");
        if (policy.Direction != "bidirectional" || !support.DeletePhone) return Result("unsupported_phone_delete");
        return Result(phone.InsertionProven ? "delete_phone" : "conflict_unproven_source_identity");
    }
}
