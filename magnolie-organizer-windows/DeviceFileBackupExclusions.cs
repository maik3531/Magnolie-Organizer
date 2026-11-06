namespace MagnolieOrganizer.Windows;

// Managed backup storage always uses a dedicated Backup child, including at
// optional alternative parents. This exclusion is deliberately independent of
// catalog availability, pairing, current destination and retention/history.
// It is a deny-only classifier, never directory ownership or absence evidence.
internal static class NativeMediaBackupExclusions
{
    private static bool HasBackupComponent(string path) => path.Split('\\').Any(component => component.Equals("Backup", StringComparison.OrdinalIgnoreCase));

    internal static bool ContainsBackupDirectory(string nativeDirectory)
    {
        _ = DeviceFileNativeDirectory.NtDirectoryName(nativeDirectory);
        return HasBackupComponent(nativeDirectory[3..]);
    }

    internal static void RequireMediaDirectory(string nativeDirectory, string? canonicalVolumePath = null)
    {
        if (ContainsBackupDirectory(nativeDirectory) || canonicalVolumePath is not null && HasBackupComponent(canonicalVolumePath))
            throw DeviceFileControl.Error("media_backup_subtree_excluded");
    }

    internal static void RequireMediaDirectory(DeviceFileNativeDirectory nativeDirectory)
    {
        _ = nativeDirectory.CurrentIdentity();
        RequireMediaDirectory(nativeDirectory.NativePath, nativeDirectory.VolumePath);
    }
}
