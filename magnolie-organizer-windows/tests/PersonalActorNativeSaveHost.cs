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
    private ContactSourceSavedCommit? contactSourceSavedCommit;
    private ContactSourceSavedCommit OriginalContactCommit => contactSourceSavedCommit ??= new(NativeActorSavedBook);
    internal ContactSourceSavedCommit SourceResultCommit => OriginalContactCommit;
    internal ContactSourceApprovalStore? ApprovalStore;
    internal Func<int, string, bool, Task>? SaveAckObserver;
    private ContactSourceApprovalStore? OriginalContactApprovals => ApprovalStore;
    private async Task OriginalContactSaveAcknowledgedAsync(int id, string hash, bool recognized)
    {
        TestAssert.That(MutationGate.Global.Wait(0), "Actual contact restore continuation still held the writer mutation gate");
        MutationGate.Global.Release();
        if (SaveAckObserver is not null) await SaveAckObserver(id, hash, recognized);
    }
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
    internal PersonalActorNativeSaveHost(string root, string before, bool reopen = false)
    {
        paths = new WindowsPaths(root); currentPlainText = before;
        store = new AtomicStore(stage => { if (FailAfterPrimary && stage == AtomicStore.WriteStage.PrimaryReplaced) throw new IOException("Synthetic post-rename failure"); });
        if (reopen)
        {
            currentEnvelope = store.Read(paths.Data) ?? throw new FileNotFoundException();
            currentPlainText = encryption.Unlock(currentEnvelope, Password);
        }
        else
        { currentEnvelope = encryption.Enable(before, Password); store.WriteRecoverableJson(paths.Data, currentEnvelope); }
        currentPlainTextAvailable = true;
        if (!reopen) actorBookOwner.RecordSaved(Path.GetFullPath(paths.Data), true, BaumSyncSnapshot.Hash(before));
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
    private NativeActorBookSnapshot? NativeActorBook() => Snapshot();
    internal ContactSourcePrimaryBook Primary() => ContactSourcePrimaryBook.Capture(paths.Data, store, encryption,
        () => currentPlainTextAvailable && !restoreInProgress && !disposed);
    private NativeBookSaveState? NativeActorSavedBook() => Saved();
    internal ContactSourceCommitOffer StageOriginalContactResult(SavedContactSourceUpdateResult result) =>
        OriginalContactCommit.Stage(Snapshot()!, result);
    internal async Task<JsonObject> SaveBridgeEnvelopeAsync(JsonObject message)
    {
        using var parsed = BridgeDispatcherContract.Parse(message.ToJsonString());
        await SaveAsync(parsed.RootElement);
        return form.Values.Last().Value;
    }
    internal async Task<JsonObject> SaveOriginalContactResultAsync(string token, JsonObject candidate, bool mixedTree = false)
    {
        var message = new JsonObject { ["id"] = form.Values.Count + 1, ["text"] = candidate.ToJsonString(), ["kontaktOriginalLauf"] = token };
        if (mixedTree) message["baumSyncLauf"] = new JsonObject();
        using var parsed = JsonDocument.Parse(message.ToJsonString());
        await SaveAsync(parsed.RootElement);
        return form.Values.Last().Value;
    }
    internal static async Task VerifyOriginalContactResultAsync(string beforeText)
    {
        foreach (var mode in new[] { "success", "forged", "mixed-content", "mixed-tree", "changed-book", "locked", "failed-primary", "ordinary-save" })
        {
            var root = Path.Combine(Path.GetTempPath(), "magnolie-actual-source-result-save-" + Guid.NewGuid().ToString("N"));
            try
            {
                var host = new PersonalActorNativeSaveHost(root, beforeText);
                var original = host.Saved()!; var originalBytes = File.ReadAllBytes(host.DataPath);
                var contacts = JsonNode.Parse(beforeText)!["kontakte"]!.DeepClone().AsArray(); contacts[0]!["notiz"] = "Native confirmed result";
                var offer = host.StageOriginalContactResult(new(original, contacts, new Dictionary<string, ContactSyncCounts>()));
                var proposed = JsonNode.Parse(beforeText)!.AsObject(); proposed["kontakte"] = offer.Contacts.DeepClone();
                if (mode == "forged") offer = offer with { Token = new string('0', 64) };
                if (mode == "mixed-content") proposed["unexpectedOtherDomain"] = "not part of native result";
                if (mode == "changed-book") host.actorBookOwner.RecordSaved(Path.GetFullPath(host.paths.Data), true, BaumSyncSnapshot.Hash(beforeText));
                if (mode == "locked") host.currentPlainTextAvailable = false;
                if (mode == "failed-primary") host.FailAfterPrimary = true;
                var response = await host.SaveOriginalContactResultAsync(mode == "ordinary-save" ? "" : offer.Token, proposed, mode == "mixed-tree");
                if (mode is "success" or "ordinary-save")
                {
                    TestAssert.That(response["ok"]!.GetValue<bool>() && host.Saved()!.Sequence == original.Sequence + 1 && host.Snapshots == 1 &&
                        new EncryptionService().Unlock(File.ReadAllText(host.DataPath), Password) == proposed.ToJsonString(),
                        "Actual source result SaveAsync bypassed encrypted native writer/snapshot/witness");
                    TestAssert.That(response["kontaktOriginalGespeichert"]!.GetValue<string>() == (mode == "success" ? offer.Token : ""),
                        "Actual SaveAsync claimed result delivery without the native one-use proof");
                    var bytes = File.ReadAllBytes(host.DataPath); var saved = host.Saved();
                    var replay = await host.SaveOriginalContactResultAsync(offer.Token, proposed);
                    TestAssert.That(!replay["ok"]!.GetValue<bool>() && saved == host.Saved() && host.Snapshots == 1 &&
                        bytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)), "Result proof replay wrote/snapshotted again");
                }
                else
                {
                    TestAssert.That(!response["ok"]!.GetValue<bool>() && response["kontaktOriginalGespeichert"] is null,
                        "Actual SaveAsync acknowledged stale/mixed/failed source result: " + mode);
                    if (mode == "failed-primary") TestAssert.That(host.Saved() is null && host.Snapshots == 1 &&
                        new EncryptionService().Unlock(File.ReadAllText(host.DataPath), Password) == proposed.ToJsonString(),
                        "Failed-after-primary result acquired a native saved witness or lost controlled failure");
                    else TestAssert.That(host.Snapshots == 0 && originalBytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)),
                        "Rejected result mutated encrypted store/snapshot: " + mode);
                }
            }
            finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
        }
    }
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
