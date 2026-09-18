using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class CloudBackupWorker : IAsyncDisposable
{
    private readonly string statePath;
    private readonly Func<string, object, Task> emit;
    private readonly CancellationTokenSource lifetime = new();
    private readonly SemaphoreSlim wake = new(0, 1);
    private readonly SemaphoreSlim execution = new(1, 1);
    private readonly Task worker;
    private readonly Func<DateTimeOffset> clock;
    private readonly TimeSpan pollingInterval;
    private readonly Func<JsonObject, CloudBackupSettings, CancellationToken, string> create;
    private readonly Func<bool> passwordAvailable;
    private string? snapshot;
    private DateTimeOffset retryAfter;
    internal CloudBackupWorker(CloudBackupService service, string statePath, string version, Func<string, object, Task> emit,
        Func<DateTimeOffset>? clock = null, TimeSpan? pollingInterval = null,
        Func<JsonObject, CloudBackupSettings, CancellationToken, string>? create = null, Func<bool>? passwordAvailable = null)
    {
        this.statePath = statePath; this.emit = emit;
        this.clock = clock ?? (() => DateTimeOffset.UtcNow);
        this.pollingInterval = pollingInterval ?? TimeSpan.FromMinutes(1);
        this.create = create ?? ((data, settings, token) => service.CreateVerified(data, settings, version, cancellation: token));
        this.passwordAvailable = passwordAvailable ?? (() => service.PasswordAvailable);
        worker = Task.Run(RunAsync);
    }
    internal void UpdateSnapshot(string savedPlainText)
    {
        Volatile.Write(ref snapshot, savedPlainText);
        if (!lifetime.IsCancellationRequested && wake.CurrentCount == 0) try { wake.Release(); } catch (SemaphoreFullException) { }
    }
    internal Task RunNowAsync() => Task.Run(() => CheckAsync(true));
    private async Task RunAsync()
    {
        try
        {
            while (!lifetime.IsCancellationRequested)
            {
                await wake.WaitAsync(pollingInterval, lifetime.Token).ConfigureAwait(false);
                await CheckAsync(false).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
    }
    private async Task CheckAsync(bool force)
    {
        await execution.WaitAsync(lifetime.Token).ConfigureAwait(false);
        try
        {
            var text = Volatile.Read(ref snapshot); if (text is null) return;
            var data = JsonNode.Parse(text)!.AsObject(); var settings = CloudBackupService.Settings(data);
            var now = clock();
            if (!force && now < retryAfter) return;
            var files = new AtomicStore(); var successes = JsonNode.Parse(files.ReadRecoverableJson(statePath) ?? "{}")!.AsObject();
            var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(settings.Folder)));
            var last = successes[key]?.GetValue<string>() ?? settings.LastSuccess;
            if (!force && !CloudBackupService.IsDue(settings.Enabled, settings.Interval, last, now)) return;
            retryAfter = now.AddMinutes(5);
            if (settings.Folder.Length == 0) { await Status("folder_missing"); return; }
            if (!passwordAvailable()) { await Status("secret_unavailable"); return; }
            create(data, settings, lifetime.Token);
            var success = clock().ToString("O"); successes[key] = success;
            files.WriteRecoverableJson(statePath, successes.ToJsonString());
            await emit("App.cloudSicherungStand", new { kennwortVorhanden = true, status = "success", letzterErfolg = success }).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        catch (Exception)
        {
            retryAfter = clock().AddMinutes(5);
            try { await Status("failed"); } catch (Exception) { }
        }
        finally { execution.Release(); }
    }
    private Task Status(string status) => emit("App.cloudSicherungStand", new { kennwortVorhanden = passwordAvailable(), status });
    public async ValueTask DisposeAsync()
    {
        lifetime.Cancel();
        await worker.ConfigureAwait(false);
        await execution.WaitAsync().ConfigureAwait(false); execution.Release();
    }
}
