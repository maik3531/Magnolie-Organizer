using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

// Actual SaveAsync is generated from current BridgeDispatcher.cs into the SAME
// CoreTests build. Only GUI, reminder/cloud and snapshot notifications are test
// endpoints; crypto, atomic file writes, document gate and saved witness are real.
internal sealed partial class PersonalActorNativeSaveHost
{
    private readonly WindowsPaths paths;
    private readonly EncryptionService encryption = new();
    private readonly AtomicStore store;
    private readonly NativeBookOwnerScope actorBookOwner = new();
    private readonly ContactCleanupSnapshot contactCleanupSnapshot = new();
    private readonly SyncSnapshotHandoff syncSnapshotHandoff = new();
    private readonly BaumSyncSnapshot baumSyncSnapshot = new();
    private readonly CancellationTokenSource backgroundLifetime = new();
    private readonly Replies form = new();
    private string currentPlainText, currentEnvelope;
    private bool plainTextAvailable;
    private bool currentPlainTextAvailable { get => plainTextAvailable; set { actorBookOwner.SetReady(value); plainTextAvailable = value; } }
    private bool restoreInProgress = false, disposed = false;
    internal bool FailAfterPrimary;
    internal int Snapshots;
    internal readonly List<string> Errors = [];
    internal const string Password = "synthetic-only-native-bridge-save";
    internal PersonalActorNativeSaveHost(string root, string before)
    {
        paths = new WindowsPaths(root); currentPlainText = before;
        store = new AtomicStore(stage => { if (FailAfterPrimary && stage == AtomicStore.WriteStage.PrimaryReplaced) throw new IOException("Synthetic post-rename failure"); });
        currentEnvelope = encryption.Enable(before, Password); store.WriteRecoverableJson(paths.Data, currentEnvelope);
        currentPlainTextAvailable = true;
        actorBookOwner.RecordSaved(Path.GetFullPath(paths.Data), true, BaumSyncSnapshot.Hash(before));
    }
    internal string DataPath => paths.Data;
    internal bool Available => currentPlainTextAvailable;
    internal IReadOnlyList<(string Callback, JsonObject Value)> Responses => form.Values;
    internal string? Source() => actorBookOwner.Current(Path.GetFullPath(paths.Data), currentPlainTextAvailable && !restoreInProgress && !disposed);
    internal NativeBookSaveState? Saved()
    {
        var saved = actorBookOwner.SaveState(Path.GetFullPath(paths.Data), currentPlainTextAvailable && !restoreInProgress && !disposed);
        return saved is not null && saved.Sha256 == BaumSyncSnapshot.Hash(currentPlainText) ? saved : null;
    }
    internal NativeActorBookSnapshot? Snapshot() => NativeActorBookSnapshot.Capture(Saved, () => currentPlainTextAvailable ? currentPlainText : null);
    private NativeBookSaveState? NativeActorSavedBook() => Saved();
    internal static async Task VerifyOrdinaryAsync(string beforeText, string afterText)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-actual-save-regression-" + Guid.NewGuid().ToString("N"));
        try
        {
            var before = JsonNode.Parse(beforeText)!.AsObject(); var after = JsonNode.Parse(afterText)!.AsObject();
            before["syncEpoch"] = "native-save-test-epoch"; after["syncEpoch"] = "native-save-test-epoch";
            var host = new PersonalActorNativeSaveHost(root, before.ToJsonString()); var saved = host.Saved();
            using (var message = JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = after.ToJsonString() }.ToJsonString()))
                await host.SaveAsync(message.RootElement);
            TestAssert.That(host.Responses.Last().Value["ok"]!.GetValue<bool>() && host.Saved()?.Sequence == saved!.Sequence + 1 &&
                new EncryptionService().Unlock(File.ReadAllText(host.DataPath), Password) == after.ToJsonString(), "Ordinary actual SaveAsync changed its encrypted save/witness contract.");
            var bytes = File.ReadAllBytes(host.DataPath); saved = host.Saved(); var snapshots = host.Snapshots;
            foreach (var invalidId in new[] { false, true })
            {
                var rejected = after.DeepClone().AsObject(); if (!invalidId) rejected["syncEpoch"] = "stale-epoch";
                using var message = JsonDocument.Parse(new JsonObject { ["id"] = invalidId ? 0 : 2, ["text"] = rejected.ToJsonString() }.ToJsonString());
                await host.SaveAsync(message.RootElement);
                TestAssert.That(!host.Responses.Last().Value["ok"]!.GetValue<bool>() && host.Saved() == saved && host.Snapshots == snapshots &&
                    bytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)), "Ordinary epoch/id denial changed saved file or created a snapshot.");
            }
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }
    private static string Text(JsonElement value, string key) => value.TryGetProperty(key, out var node) ? node.GetString() ?? "" : "";
    private static int Integer(JsonElement value, string key) => value.TryGetProperty(key, out var node) ? node.GetInt32() : 0;
    private static bool Boolean(JsonElement value, string key) => value.TryGetProperty(key, out var node) && node.GetBoolean();
    private static string T(string value) => value;
    private Task RetryRestoreRepairAsync() => Task.CompletedTask;
    private void CreateSnapshot(SnapshotReason reason) => Snapshots++;
    private void RefreshReminderData(string text, bool encrypted) { }
    private void UpdateReminderRuntime(string text) { }
    private Task RunCloudBackupAfterSaveAsync(string text, bool force) => Task.CompletedTask;
    private Task ReportErrorAsync(string operation, string error) { Errors.Add(error); return Task.CompletedTask; }
    private sealed class Replies
    {
        internal readonly List<(string Callback, JsonObject Value)> Values = [];
        internal Task SendAsync(string callback, object value) { Values.Add((callback, JsonSerializer.SerializeToNode(value)!.AsObject())); return Task.CompletedTask; }
    }
}
