namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private readonly object serviceGate = new();
    private readonly CancellationTokenSource backgroundLifetime = new();
    private CancellationTokenSource restoreLifetime = new();
    private readonly Dictionary<string, Task> networkTails = new(StringComparer.Ordinal);
    private CancellationTokenSource? graphSignIn;
    private CancellationTokenSource? activeSync;
    private bool graphSync;
    private int graphRevision;
    private int networkGeneration;
    private volatile bool restoreInProgress;
    private string? restoreToken;
    private bool restoreContentCommitted;
    private readonly HashSet<string> personalUiPending = new(StringComparer.Ordinal);
    private readonly System.Collections.Concurrent.ConcurrentDictionary<Task, byte> backgroundWork = new();
    private MagnolienbaumCoordinator? baumInstance;
    private TelefonCoordinator? telefonInstance;
    private KdeConnectSms? kdeInstance;
    private readonly CloudBackupWorker cloudWorker;
    private MagnolienbaumCoordinator baum
    {
        get { lock (serviceGate) { ObjectDisposedException.ThrowIf(disposed, this); return baumInstance ??= new(paths, form.SendAsync); } }
    }
    private TelefonCoordinator telefon
    {
        get
        {
            lock (serviceGate)
            {
                ObjectDisposedException.ThrowIf(disposed, this);
                if (telefonInstance is not null) return telefonInstance;
                var created = new TelefonCoordinator(paths, HandleTelefonEventAsync, KdeStatusForWebAsync,
                    new WindowsBluetoothRadio(), foregroundEnabled: setupSelections?.ForegroundPhoneTransports.Any(t => t is "wifi" or "bluetooth") == true);
                telefonInstance = created; form.SetTelefonCoordinator(created); return created;
            }
        }
    }
    private KdeConnectSms kdeConnectSms
    {
        get
        {
            lock (serviceGate)
            {
                ObjectDisposedException.ThrowIf(disposed, this);
                if (kdeInstance is not null) return kdeInstance;
                var created = new KdeConnectSms(paths);
                try
                {
                    created.StatusChanged += HandleKdeStatusChanged; created.SmsReceived += HandleKdeSmsReceived;
                    created.PairingChanged += HandleKdePairingChanged; kdeInstance = created; return created;
                }
                catch { created.Dispose(); throw; }
            }
        }
    }
    private Task QueueBackground(Func<Task> action, Task? predecessor = null, int? generation = null)
    {
        lock (serviceGate)
        {
            if (disposed) return Task.CompletedTask;
            var task = Task.Run(async () =>
            {
                try
                {
                    // A worker may emit commands requiring this lane. Never await it while holding the lane.
                    if (predecessor is not null) await predecessor.WaitAsync(backgroundLifetime.Token).ConfigureAwait(false);
                    if (generation is not null && generation != Volatile.Read(ref networkGeneration)) return;
                    if (generation is null)
                    { await bridgeCommands.WaitAsync(backgroundLifetime.Token).ConfigureAwait(false); bridgeCommands.Release(); }
                    backgroundLifetime.Token.ThrowIfCancellationRequested(); await action().ConfigureAwait(false);
                }
                catch (Exception error)
                {
                    if (!disposed) RotatingLog.Append(Path.Combine(paths.Logs, "background.log"), error.Message);
                }
            });
            backgroundWork.TryAdd(task, 0);
            _ = task.ContinueWith(done => backgroundWork.TryRemove(done, out _), CancellationToken.None,
                TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
            return task;
        }
    }
    private void QueueNetworkCommand(Func<Task> action, string owner = "baum")
    {
        lock (serviceGate)
        {
            if (restoreInProgress) return;
            networkTails[owner] = QueueBackground(action, networkTails.GetValueOrDefault(owner) ?? Task.CompletedTask, networkGeneration);
        }
    }
    private CancellationTokenSource NetworkDeadline(TimeSpan timeout)
    {
        lock (serviceGate)
        {
            var result = CancellationTokenSource.CreateLinkedTokenSource(backgroundLifetime.Token, restoreLifetime.Token);
            if (restoreInProgress) result.Cancel();
            result.CancelAfter(timeout); return result;
        }
    }
    private async Task ResumeOptionalServicesAsync()
    {
        await RetryRestoreRepairAsync().ConfigureAwait(false);
        if (restoreInProgress) return;
        try { await baum.ResumeAsync().ConfigureAwait(false); }
        catch (Exception error) { if (!disposed) await ReportErrorAsync("baum_stand", error.Message); }
        try { _ = kdeConnectSms; }
        catch (Exception error) { if (!disposed) await ReportErrorAsync("telefon_stand", error.Message); }
        try { await telefon.ResumeAsync().ConfigureAwait(false); await telefon.ReportStatusAsync().ConfigureAwait(false); await telefon.ReplayPersonalSyncAsync().ConfigureAwait(false); }
        catch (Exception error) { if (!disposed) await ReportErrorAsync("telefon_stand", error.Message); }
    }
    private async Task FencePhoneRestoreAsync()
    {
        var fence = Path.Combine(paths.Telefon, "restore-fence.json");
        if (Path.Exists(fence) || Path.Exists(AtomicStore.BackupPath(fence)))
        { restoreInProgress = true; throw new InvalidOperationException(T("Synchronization failed.")); }
        lock (personalSyncGate)
        {
            if (personalUiPending.Count != 0) throw new InvalidOperationException(T("Wait for personal synchronization to finish before restoring."));
            restoreInProgress = true;
            restoreToken = Guid.NewGuid().ToString("D");
            restoreContentCommitted = false;
        }
        Task queued;
        lock (serviceGate)
        {
            networkGeneration++; restoreLifetime.Cancel();
            queued = Task.WhenAll(networkTails.Where(item => item.Key is "baum" or "phone" or "sync" or "kde").Select(item => item.Value));
        }
        ClearPersonalSyncRuntime();
        try { await telefon.FenceForRestoreAsync(restoreToken).ConfigureAwait(false); }
        finally
        {
            await queued.ConfigureAwait(false);
            lock (serviceGate) { restoreLifetime.Dispose(); restoreLifetime = new CancellationTokenSource(); }
            ClearPersonalSyncRuntime();
        }
    }

    private async Task<string> ReleaseRestoreFence()
    {
        if (restoreToken is null) return "";
        try
        {
            if (restoreToken is not null && !restoreContentCommitted && telefon.PendingRestore is not null)
            {
                var snapshot = telefon.PendingRestore?["snapshot"]?.GetValue<string>();
                if (snapshot is not null) recovery.ReleaseRestoreLease(snapshot);
                telefon.AbortRestore(restoreToken);
            }
            if (telefon.PendingRestore is not null) return T("Synchronization failed.");
        }
        catch (Exception error)
        {
            await ReportErrorAsync("restore_abort", error.Message);
            return T("Synchronization failed.");
        }
        lock (serviceGate)
        {
            if (restoreLifetime.IsCancellationRequested)
            { restoreLifetime.Dispose(); restoreLifetime = new CancellationTokenSource(); }
            restoreInProgress = false;
            restoreToken = null;
        }
        _ = QueueBackground(() => telefon.ResumeAsync());
        return "";
    }

    private async Task RetryRestoreRepairAsync()
    {
        var fence = Path.Combine(paths.Telefon, "restore-fence.json");
        if (!Path.Exists(fence) && !Path.Exists(AtomicStore.BackupPath(fence))) return;
        if (!await MutationGate.Global.WaitAsync(0)) return;
        try
        {
            // The persistent barrier itself may be unreadable. Fail closed before
            // parsing it; otherwise a repair exception could leave Save enabled.
            restoreInProgress = true;
            var pending = telefon.PendingRestore;
            if (pending is null) { restoreInProgress = false; return; }
            restoreToken = pending["token"]?.GetValue<string>() ?? throw new InvalidDataException();
            var stored = store.Read(paths.Data);
            var hash = TelefonStore.ProfileHash(stored);
            if (hash == pending["before"]?.GetValue<string>())
            { restoreContentCommitted = false; await ReleaseRestoreFence(); return; }
            if (hash != pending["after"]?.GetValue<string>()) throw new InvalidDataException();
            restoreContentCommitted = true;
            // Locked startup cannot regenerate derived data. Unlock/start or the periodic tick retries.
            if (!currentPlainTextAvailable) return;
            var epoch = System.Text.Json.Nodes.JsonNode.Parse(currentPlainText)?["syncEpoch"]?.GetValue<string>();
            if (epoch != pending["epoch"]?.GetValue<string>()) throw new InvalidDataException();
            var warning = await CompleteRestoreRuntimeAsync(currentPlainText, EncryptionService.IsEncrypted(stored!), resumeTree: true);
            if (warning.Length != 0) await form.SendAsync("App.syncFehler", warning);
        }
        catch (Exception error)
        {
            await ReportErrorAsync("restore_repair", error.Message);
            await form.SendAsync("App.syncFehler", T("Synchronization failed."));
        }
        finally { MutationGate.Global.Release(); }
    }
}
