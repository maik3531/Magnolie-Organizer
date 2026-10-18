using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class NoteSendJobs : IDisposable
{
    private sealed class Job
    {
        internal required string Id, RequestHash, Revision, Directory, Pdf, Kind, Recipient, Subject;
        internal string Phase = "preparing", Error = "none";
        internal bool Cancelled, Dispatched, Unknown, Rendering = true;
        internal DateTimeOffset? Finished;
        internal NoteSendReceipt? Receipt;
        internal readonly CancellationTokenSource Cancellation = new();
        internal Task? Work;
    }
    private readonly string root;
    private readonly Func<NoteSendSettings> readSettings;
    private readonly Func<string, string, Task> renderPdf;
    private readonly Func<NoteMailClient> discover;
    private readonly Func<NoteSendSettings, string, string, string, string, string, NoteSendReceipt> handoff;
    private readonly byte[] revisionKey = RandomNumberGenerator.GetBytes(32);
    private readonly object gate = new();
    private readonly SemaphoreSlim mailGate = new(1, 1);
    private readonly Dictionary<string, Job> jobs = new(StringComparer.Ordinal);
    private bool disposed;

    internal NoteSendJobs(string root, Func<NoteSendSettings> readSettings, Func<string, string, Task> renderPdf,
        Func<NoteMailClient>? discover = null,
        Func<NoteSendSettings, string, string, string, string, string, NoteSendReceipt>? handoff = null)
    {
        this.root = Path.GetFullPath(root); this.readSettings = readSettings; this.renderPdf = renderPdf;
        this.discover = discover ?? NoteSendTransport.DiscoverMailClient;
        this.handoff = handoff ?? ((settings, kind, target, subject, pdf, directory) => NoteSendTransport.Handoff(settings, kind, target, subject, pdf, directory));
        EnsurePrivateDirectory(this.root); Prune();
    }
    private static void EnsurePrivateDirectory(string path)
    {
        Directory.CreateDirectory(path);
        for (var current = new DirectoryInfo(path); current is not null; current = current.Parent)
            if ((current.Attributes & FileAttributes.ReparsePoint) != 0) throw new NoteSendException("invalid_document");
        if (OperatingSystem.IsWindows())
        {
            var identity = WindowsIdentity.GetCurrent().User ?? throw new NoteSendException("native_unavailable");
            var security = new DirectorySecurity(); security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new FileSystemAccessRule(identity, FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            new DirectoryInfo(path).SetAccessControl(security);
        }
        else File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
    }
    private (NoteSendSettings Settings, NoteMailClient Client, string Revision) Context()
    {
        if (disposed) throw new NoteSendException("native_unavailable");
        var settings = readSettings(); var client = discover();
        var material = JsonSerializer.SerializeToUtf8Bytes(new { settings.Enabled, settings.FaxServer, client.Supported, client.Available, client.Id, client.Name, root });
        return (settings, client, Convert.ToHexString(HMACSHA256.HashData(revisionKey, material)).ToLowerInvariant());
    }
    internal JsonObject Read()
    {
        Prune();
        var (settings, client, revision) = Context();
        return new JsonObject { ["revision"] = revision, ["settings"] = new JsonObject { ["enabled"] = settings.Enabled, ["faxServer"] = settings.FaxServer },
            ["capabilities"] = new JsonObject { ["enabled"] = settings.Enabled,
                ["email"] = new JsonObject { ["supported"] = client.Supported, ["available"] = client.Available, ["client"] = client.Name },
                ["fax"] = new JsonObject { ["supported"] = false, ["available"] = false, ["configured"] = settings.FaxServer.Length > 0 } } };
    }
    private Job Find(string token) => jobs.TryGetValue(token, out var job) ? job : throw new NoteSendException("not_found");
    private static JsonObject Value(Job job) => new()
    {
        ["operation_id"] = job.Id, ["phase"] = job.Phase, ["error_code"] = job.Error,
        ["native_outcome_unknown"] = job.Unknown || job.Phase == "external_pending", ["cancel_requested"] = job.Cancelled,
        ["can_cancel"] = !job.Dispatched && job.Phase is "preparing" or "ready", ["handed_off"] = job.Phase == "handed_off", ["delivery_confirmed"] = false,
        ["adapter"] = job.Receipt?.Adapter, ["document"] = job.Receipt is { } receipt
            ? new JsonObject { ["bytes"] = receipt.Document.Bytes, ["sha256"] = receipt.Document.Sha256 } : null
    };
    internal JsonObject Status(string token) { Prune(); lock (gate) return Value(Find(token)); }
    internal JsonObject Begin(string html, string kind, string target, string subject, string expectedRevision, string operationId)
    {
        Prune(); var (settings, client, revision) = Context();
        if (expectedRevision != revision) throw new NoteSendException("conflict");
        if (!settings.Enabled) throw new NoteSendException("feature_disabled");
        if (kind != "email") throw new NoteSendException("unsupported_adapter");
        if (!client.Available) throw new NoteSendException("native_unavailable");
        target = NoteSendTransport.Recipient(kind, target); subject = subject.Trim();
        if (subject.Length > 200 || subject.Any(character => char.IsControl(character))) throw new NoteSendException("invalid_subject");
        if (string.IsNullOrWhiteSpace(html) || Encoding.UTF8.GetByteCount(html) > 750000) throw new NoteSendException("invalid_document");
        if (!System.Text.RegularExpressions.Regex.IsMatch(operationId, "^[a-f0-9]{48}$")) throw new NoteSendException("invalid_selection");
        var requestHash = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(new[] { html, kind, target, subject, expectedRevision }))).ToLowerInvariant();
        Job job;
        lock (gate)
        {
            if (jobs.TryGetValue(operationId, out var previous)) return previous.RequestHash == requestHash ? Value(previous) : throw new NoteSendException("conflict");
            if (jobs.Count >= 32 || jobs.Values.Count(item => item.Finished is null || item.Rendering) >= 4) throw new NoteSendException("native_busy");
            var directory = Path.Combine(root, operationId);
            if (Directory.Exists(directory) || File.Exists(directory)) throw new NoteSendException("conflict");
            EnsurePrivateDirectory(directory);
            File.WriteAllText(Path.Combine(directory, "owned.json"), "{\"version\":1,\"owner\":\"magnolie-note-send\"}");
            job = new Job { Id = operationId, RequestHash = requestHash, Revision = revision, Directory = directory,
                Pdf = Path.Combine(directory, "document.pdf"), Kind = kind, Recipient = target, Subject = subject };
            jobs.Add(operationId, job);
            if (ExecutionContext.IsFlowSuppressed()) job.Work = Task.Run(() => RunAsync(job, html));
            else { using (ExecutionContext.SuppressFlow()) job.Work = Task.Run(() => RunAsync(job, html)); }
            return Value(job);
        }
    }
    private async Task RunAsync(Job job, string html)
    {
        var ownsMailGate = false;
        try
        {
            await renderPdf(html, job.Pdf);
            lock (gate) { job.Rendering = false; if (job.Cancelled || disposed) throw new OperationCanceledException(); job.Phase = "ready"; }
            NoteSendTransport.PdfReceipt(job.Pdf, job.Directory);
            await mailGate.WaitAsync(job.Cancellation.Token); ownsMailGate = true;
            var (settings, client, revision) = Context();
            lock (gate)
            {
                if (job.Cancelled || disposed) throw new OperationCanceledException();
                if (revision != job.Revision || !settings.Enabled || !client.Available) throw new NoteSendException("conflict");
                job.Dispatched = true; job.Phase = "external_pending";
            }
            var receipt = await OnStaAsync(() => handoff(settings, job.Kind, job.Recipient, job.Subject, job.Pdf, job.Directory));
            lock (gate) { job.Receipt = receipt; job.Phase = receipt.Stage; }
        }
        catch (OperationCanceledException)
        { lock (gate) { job.Cancelled = true; job.Phase = "cancelled"; job.Unknown = job.Dispatched; } }
        catch (NoteSendException error)
        { lock (gate) { job.Dispatched = error.Dispatched; job.Unknown = error.Dispatched; job.Phase = "failed"; job.Error = error.Code; } }
        catch (Exception)
        { lock (gate) { job.Phase = "failed"; job.Error = job.Dispatched ? "native_operation_failed" : "document_failed"; job.Unknown = job.Dispatched; } }
        finally
        {
            if (ownsMailGate) mailGate.Release();
            lock (gate)
            {
                job.Rendering = false; job.Finished = DateTimeOffset.UtcNow;
                try
                {
                    if ((!job.Dispatched || job.Receipt?.Stage == "cancelled") && Directory.Exists(job.Directory)) Directory.Delete(job.Directory, true);
                    else if (Directory.Exists(job.Directory)) Directory.SetLastWriteTimeUtc(job.Directory, job.Finished.Value.UtcDateTime);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }
    private static Task<NoteSendReceipt> OnStaAsync(Func<NoteSendReceipt> action)
    {
        var completion = new TaskCompletionSource<NoteSendReceipt>(TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() => { try { completion.TrySetResult(action()); } catch (Exception error) { completion.TrySetException(error); } })
            { IsBackground = true, Name = "Magnolie note mail handoff" };
        if (OperatingSystem.IsWindows()) thread.SetApartmentState(ApartmentState.STA);
        if (ExecutionContext.IsFlowSuppressed()) thread.Start();
        else { using (ExecutionContext.SuppressFlow()) thread.Start(); }
        return completion.Task;
    }
    internal JsonObject Cancel(string token)
    {
        lock (gate)
        {
            var job = Find(token); var accepted = !job.Dispatched && job.Phase is "preparing" or "ready";
            if (accepted) { job.Cancelled = true; job.Phase = "cancelled"; job.Cancellation.Cancel(); }
            var value = Value(job); value["cancel_accepted"] = accepted; return value;
        }
    }
    private void Prune()
    {
        lock (gate)
        {
            var now = DateTimeOffset.UtcNow;
            foreach (var job in jobs.Values.Where(item => item.Finished is { } finished && now - finished > TimeSpan.FromDays(1)).ToArray())
            { jobs.Remove(job.Id); job.Cancellation.Dispose(); }
            foreach (var directory in new DirectoryInfo(root).EnumerateDirectories())
            {
                if (!System.Text.RegularExpressions.Regex.IsMatch(directory.Name, "^[a-f0-9]{48}$") || jobs.ContainsKey(directory.Name) ||
                    (directory.Attributes & FileAttributes.ReparsePoint) != 0 || now.UtcDateTime - directory.LastWriteTimeUtc < TimeSpan.FromDays(1)) continue;
                try
                {
                    var marker = new FileInfo(Path.Combine(directory.FullName, "owned.json"));
                    if (!marker.Exists || marker.Length > 4096 || (marker.Attributes & FileAttributes.ReparsePoint) != 0) continue;
                    using var document = JsonDocument.Parse(File.ReadAllText(marker.FullName));
                    if (document.RootElement.GetProperty("version").GetInt32() == 1 && document.RootElement.GetProperty("owner").GetString() == "magnolie-note-send") directory.Delete(true);
                }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or KeyNotFoundException or InvalidOperationException) { }
            }
        }
    }
    public void Dispose()
    {
        lock (gate)
        {
            disposed = true;
            foreach (var job in jobs.Values.Where(job => !job.Dispatched && job.Finished is null)) { job.Cancelled = true; job.Cancellation.Cancel(); }
        }
    }
}
