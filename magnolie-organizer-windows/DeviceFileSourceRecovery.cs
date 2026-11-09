namespace MagnolieOrganizer.Windows;

// Local new-file recovery only. Neither this choice nor its completed journal
// grants synchronized source replacement, phone publication or deletion.
internal sealed record NativeIndependentPcBackupRestoreChoice(NativeMediaBackupParent Source, NativeMediaBackupParent Output,
    NativeMediaBackupVersion Selected, NativeMediaBookPermit Permit, string Operation);

internal sealed partial class TelefonStore
{
    internal IReadOnlyList<NativeMediaBackupVersion> NativeIndependentPcBackupVersions(NativeMediaBackupParent source, Func<bool> nativePermit)
    {
        lock (gate)
        {
            void Current() { if (RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed"); }
            using var catalog = new MediaBackupCatalog(this, source, Current, false);
            return catalog.RecoveryVersions().Where(catalog.IsPreparedPcVersion).ToArray();
        }
    }

    private void RequireIndependentRecoveryMember(Microsoft.Data.Sqlite.SqliteConnection db, DeviceFileNativeDirectory.Identity identity)
    {
        using var exists = db.CreateCommand(); exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_backup_restore_events'";
        if (exists.ExecuteScalar() is null) return;
        using var budget = db.CreateCommand();
        budget.CommandText = "SELECT count(*) FROM (SELECT 1 FROM native_media_backup_restore_events LIMIT 8193)";
        if (Convert.ToInt64(budget.ExecuteScalar()) > 8192) throw DeviceFileControl.Error("media_collection_recovery_history_held");
        using var read = db.CreateCommand();
        read.CommandText = "SELECT DISTINCT scope FROM native_media_backup_restore_events ORDER BY scope LIMIT 4097";
        var scopes = new List<string>();
        using (var rows = read.ExecuteReader()) while (rows.Read()) scopes.Add(rows.GetString(0));
        if (scopes.Count > 4096 || scopes.Any(scope => !DeviceFileControl.Hash(scope)))
            throw DeviceFileControl.Error("media_collection_recovery_history_held");
        var file = NativeMediaReceiveJob.NativeIdentity(identity);
        foreach (var scope in scopes)
            foreach (var head in BackupRestoreHeads(db, null, scope))
                if (System.Text.Json.Nodes.JsonNode.DeepEquals(head.Body["identity"], file))
                    throw DeviceFileControl.Error("media_collection_existing_recovery_required");
    }
}

internal sealed partial class TelefonCoordinator
{
    internal IReadOnlyList<NativeMediaBackupVersion> ReadNativeIndependentPcBackupChoices(NativeMediaBackupParent source)
    {
        var permit = NativeMediaLocalBookPermit();
        bool Current() { permit.Require(); return true; }
        var result = store.NativeIndependentPcBackupVersions(source, Current); permit.Require(); return result;
    }

    internal NativeIndependentPcBackupRestoreChoice PrepareNativeIndependentPcBackupRestore(NativeMediaBackupParent source,
        string id, string version, DeviceFileNativeDirectory output)
    {
        var permit = NativeMediaLocalBookPermit(); permit.Require();
        var parent = NativeMediaBackupParent.Capture(output);
        bool Current() { permit.Require(); return NativeMediaBackupParent.Capture(output) == parent; }
        var selected = store.NativeIndependentPcBackupVersions(source, Current).SingleOrDefault(item => item.Id == id && item.RecordSha256 == version)
            ?? throw DeviceFileControl.Error("media_backup_stale_selection");
        permit.Require(); return new(source, parent, selected, permit, Guid.NewGuid().ToString("N"));
    }

    internal NativeMediaBackupRestoration RestoreConfirmedNativeIndependentPcBackup(NativeIndependentPcBackupRestoreChoice choice)
        => NativeMediaLocalOperation(() => store.RestoreNativeIndependentPcBackupToNewFile(choice.Output, choice.Source, choice.Selected,
            choice.Permit, choice.Operation));
}
