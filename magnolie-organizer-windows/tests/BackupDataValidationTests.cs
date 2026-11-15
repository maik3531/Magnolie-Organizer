using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class BackupDataValidationTests
{
    internal static void Run()
    {
        foreach (var text in new[] { "{}", "{\"unrelated\":true}", "{\"notizen\":\"not a list\"}", "{\"kontakte\":{}}",
            "{\"einstellungen\":[]}", "{\"notizen\":[],\"aufgaben\":true}", "{\"notizen\":null}",
            "{\"customOrganizer\":[]}", "{\"notizen\":[],\"gesundheit\":\"invalid\"}" })
        {
            var data = JsonNode.Parse(text)!.AsObject(); var before = data.ToJsonString();
            TestAssert.Throws<InvalidDataException>(() => BackupDataValidation.Validate(data), "Unrelated JSON or malformed profile was accepted as a backup");
            TestAssert.That(data.ToJsonString() == before, "Rejected backup was modified during validation");
        }
        foreach (var text in new[] { "{\"notizen\":[]}", "{\"notizen\":[{\"id\":\"n\",\"text\":\"Synthetic note\"}]}",
            "{\"einstellungen\":{}}", "{\"gesundheit\":{\"future\":[1]}}", "{\"notizen\":null,\"termine\":[]}",
            "{\"kontakte\":[],\"future\":{\"keep\":[1,2]}}", "{\"version\":1,\"aufgaben\":[{\"titel\":\"Legacy task\"}]}" })
        {
            var data = JsonNode.Parse(text)!.AsObject(); var before = data.ToJsonString();
            BackupDataValidation.Validate(data);
            TestAssert.That(data.ToJsonString() == before, "Legacy partial/empty profile or unknown fields were rewritten");
        }
        foreach (var valid in new[] { false, true })
        {
            var encoder = new EncryptionService(); var decoder = new EncryptionService();
            try
            {
                var envelope = encoder.Enable(valid ? "{\"notizen\":[]}" : "{\"notizen\":\"not a list\"}", "synthetic-backup-only");
                var data = JsonNode.Parse(decoder.Unlock(envelope, "synthetic-backup-only"))!.AsObject();
                if (valid) BackupDataValidation.Validate(data);
                else TestAssert.Throws<InvalidDataException>(() => BackupDataValidation.Validate(data), "Encryption bypassed the backup shape guard");
            }
            finally { encoder.Clear(); decoder.Clear(); }
        }
        // Exact native callers must reject before any positive preview or the
        // restore's phone fence, mutation lock, checkpoint or profile write.
        var source = File.ReadAllText("BridgeDispatcher.cs");
        var previewStart = source.IndexOf("private async Task PreviewBackupAsync(", StringComparison.Ordinal);
        var restoreStart = source.IndexOf("private async Task RestoreBackupAsync(", StringComparison.Ordinal);
        var preview = source[previewStart..restoreStart];
        var restore = source[restoreStart..source.IndexOf("private static void RequireJsonObject(", restoreStart, StringComparison.Ordinal)];
        var previewGuard = preview.IndexOf("BackupDataValidation.Validate(data);", StringComparison.Ordinal);
        var restoreGuard = restore.IndexOf("BackupDataValidation.Validate(restoredData);", StringComparison.Ordinal);
        TestAssert.That(previewGuard >= 0 && previewGuard < preview.IndexOf("await form.SendAsync", StringComparison.Ordinal) &&
            restoreGuard >= 0 && restoreGuard < restore.IndexOf("await FencePhoneRestoreAsync();", StringComparison.Ordinal) &&
            restoreGuard < restore.IndexOf("MutationGate.Global.WaitAsync", StringComparison.Ordinal),
            "Native preview/restore caller moved backup validation after acceptance or mutation");
    }
}
