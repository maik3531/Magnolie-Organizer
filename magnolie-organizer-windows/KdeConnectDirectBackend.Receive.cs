using System.Text;
using System.Text.Json.Nodes;
using System.Threading.Channels;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeFileReceiveProposal(string Id, string DeviceId, IReadOnlyList<KdeIncomingMember> Files,
    long Size, DateTimeOffset ExpiresAt, bool DestinationFixed);
internal sealed record KdeFileReceiveProgress(string Id, string DeviceId, string State, long Bytes, long TotalBytes);

internal sealed partial class KdeConnectDirectBackend
{
    private sealed record ReceivePreferences(bool Enabled, string DeviceId, string Directory, long Epoch, Func<bool> Permitted);
    private sealed class ReceiveContext(string id, Connection connection, ReceivePreferences preferences,
        KdeReceiveSource source, DateTimeOffset deadline, long bytes, CancellationToken cancellation)
    {
        internal readonly string Id = id;
        internal readonly Connection Connection = connection;
        internal readonly int ConnectionGeneration = connection.Generation;
        internal readonly ReceivePreferences Preferences = preferences;
        internal readonly KdeReceiveSource Source = source;
        internal readonly DateTimeOffset Deadline = deadline;
        internal readonly CancellationTokenSource Cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        internal readonly HashSet<Guid> Emitted = [];
        internal readonly HashSet<string> RawDownloads = new(StringComparer.Ordinal);
        internal KdeIncomingFileBatch? Batch;
        internal KdeIncomingFileOffer? Offer;
        internal long Reserved = bytes;
        internal long Received;
        internal volatile bool Valid = true;
        internal string Phase = "collecting";
        internal int CleanupStarted;
        internal int ActiveDownload;
        internal bool Accepting;
    }
    private sealed record ReceiveWork(ReceiveContext Context, Guid MemberId, KdeShareAnnouncement Announcement);
    private ReceivePreferences receivePreferences = new(false, "", "", 0, () => false);
    private readonly string receiveRootToken = Guid.NewGuid().ToString("N");
    private readonly string receiveRoot;
    private bool receiveRootOwned;
    private readonly Dictionary<string, ReceiveContext> receiveContexts = new(StringComparer.Ordinal);
    private readonly Channel<ReceiveWork> receiveQueue = Channel.CreateBounded<ReceiveWork>(new BoundedChannelOptions(8 * KdeIncomingFileBatch.MaxFiles)
        { SingleReader = true, SingleWriter = false, FullMode = BoundedChannelFullMode.Wait });
    private Task? receiveWorker;
    internal event Action<KdeFileReceiveProposal>? FileProposed;
    internal event Action<KdeFileReceiveProgress>? FileReceiveProgress;
    internal event Action<KdeSavedIncomingFile>? FileSaved;

    private bool FileReceiveAdvertised
    {
        get
        {
            var preferences = Volatile.Read(ref receivePreferences);
            try { return !disposed && preferences.Enabled && preferences.Permitted(); }
            catch (Exception) { return false; }
        }
    }
    private string ReceiveMarker => Path.Combine(receiveRoot, ".magnolie-owner");
    private string ReceiveMarkerText => "magnolie-kde-staging-v1\n" + receiveRootToken + "\n";

    private void EnsureReceiveRoot()
    {
        if (receiveRootOwned)
        {
            if (!KdeIncomingFileBatch.RealDirectoryChain(receiveRoot) || !File.Exists(ReceiveMarker) ||
                (File.GetAttributes(ReceiveMarker) & FileAttributes.ReparsePoint) != 0 ||
                new FileInfo(ReceiveMarker).Length > 128 || File.ReadAllText(ReceiveMarker) != ReceiveMarkerText)
                throw new IOException("incoming_private_root_changed");
            return;
        }
        if (Directory.Exists(receiveRoot) || File.Exists(receiveRoot)) throw new IOException("incoming_private_root_already_exists");
        Directory.CreateDirectory(receiveRoot);
        var markerCreated = false;
        try
        {
            if (!KdeIncomingFileBatch.RealDirectoryChain(receiveRoot)) throw new IOException("incoming_private_root_linked");
            using var marker = new FileStream(ReceiveMarker, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            markerCreated = true;
            var bytes = Encoding.UTF8.GetBytes(ReceiveMarkerText); marker.Write(bytes); marker.Flush(flushToDisk: true);
            receiveRootOwned = true;
        }
        catch
        {
            receiveRootOwned = false;
            if (markerCreated && KdeIncomingFileBatch.RealDirectoryChain(receiveRoot) &&
                (File.GetAttributes(ReceiveMarker) & FileAttributes.ReparsePoint) == 0) File.Delete(ReceiveMarker);
            // Never recursively clean an unexpected or unproved directory.
            if (Directory.Exists(receiveRoot) && !Directory.EnumerateFileSystemEntries(receiveRoot).Any()) Directory.Delete(receiveRoot);
            throw;
        }
    }

    internal JsonObject ConfigureFileReceive(bool enabled, string deviceId, string directory, Func<bool>? permitted = null)
    {
        List<ReceiveContext> previous;
        lock (activeGate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (enabled)
            {
                if (permitted?.Invoke() != true || !store.LoadPeers().Any(peer => peer.Paired && peer.Id == deviceId))
                    throw new InvalidOperationException("incoming_selected_paired_device_required");
                if (directory.Length != 0 && (!Path.IsPathFullyQualified(directory) || !Directory.Exists(directory) ||
                    !KdeIncomingFileBatch.RealDirectoryChain(directory))) throw new InvalidDataException("incoming_destination_must_exist");
                EnsureReceiveRoot();
            }
            Volatile.Write(ref receivePreferences, new(enabled, enabled ? deviceId : "", enabled ? directory : "",
                checked(receivePreferences.Epoch + 1), permitted ?? (() => false)));
            previous = receiveContexts.Values.Where(context => context.Valid).ToList();
            foreach (var context in previous) context.Valid = false;
            if (enabled && receiveWorker is null)
            { receiveWorker = ReceiveFilesLoopAsync(lifetime.Token); Track(receiveWorker); }
        }
        foreach (var context in previous) Track(DropReceiveContextAsync(context, "rejected"));
        if (activeDiscovery) BroadcastIdentity();
        return FileReceiveStatus();
    }

    private KdeReceiveSource? CurrentReceiveSource(ReceiveContext context)
    {
        try
        {
            var preferences = Volatile.Read(ref receivePreferences);
            if (disposed || !context.Valid || !ReferenceEquals(preferences, context.Preferences) || !preferences.Enabled ||
                preferences.DeviceId != context.Source.DeviceId || !preferences.Permitted() ||
                context.Connection.Closed || context.Connection.Generation != context.ConnectionGeneration ||
                !active.TryGetValue(context.Source.DeviceId, out var current) || !ReferenceEquals(current, context.Connection) ||
                !store.LoadPeers().Any(peer => peer.Paired && peer.Id == context.Source.DeviceId &&
                    peer.CertificatePin == context.Source.CertificateFingerprint)) return null;
            return context.Source;
        }
        catch (Exception error) when (error is IOException or System.Security.Cryptography.CryptographicException or
            InvalidOperationException or InvalidDataException or UnauthorizedAccessException or System.Text.Json.JsonException)
        { return null; }
    }

    internal JsonObject FileReceiveStatus()
    {
        CleanupFileReceives(DateTimeOffset.UtcNow);
        lock (activeGate)
        {
            var preferences = receivePreferences;
            var proposals = new JsonArray();
            foreach (var context in receiveContexts.Values.Where(value => value.Valid && value.Phase == "offered"))
                try
                {
                    proposals.Add(new JsonObject { ["id"] = context.Id, ["device_id"] = context.Source.DeviceId,
                        ["files"] = new JsonArray(context.Offer!.Proposal().Select(member => (JsonNode)new JsonObject {
                            ["name"] = member.Name, ["size"] = member.Size }).ToArray()) });
                }
                catch (Exception error) when (error is InvalidOperationException or OperationCanceledException) { }
            return new JsonObject { ["file_enabled"] = preferences.Enabled, ["allowed_now"] = FileReceiveAdvertised, ["device_id"] = preferences.DeviceId,
                ["download_directory"] = preferences.Directory, ["pending_count"] = receiveContexts.Count,
                ["reserved_bytes"] = receiveContexts.Values.Sum(context => context.Reserved),
                ["cleanup_pending"] = receiveContexts.Values.Count(context => !context.Valid),
                ["proposals"] = proposals };
        }
    }

    private void HandleFileReceivePacket(Connection connection, KdeConnectPacket packet)
    {
        ReceiveContext? context = null;
        try
        {
            lock (activeGate)
            {
                var preferences = receivePreferences;
                if (!preferences.Enabled || preferences.DeviceId != connection.Identity.DeviceId || !preferences.Permitted() ||
                    connection.Closed || !active.TryGetValue(preferences.DeviceId, out var current) || !ReferenceEquals(current, connection) ||
                    !connection.Identity.OutgoingCapabilities.Contains(KdeShareProtocol.Request)) return;
                var pin = KdeConnectProtocol.CertificatePin(connection.Certificate);
                if (!store.LoadPeers().Any(peer => peer.Paired && peer.Id == preferences.DeviceId && peer.CertificatePin == pin)) return;
                if (packet.Type == KdeShareProtocol.Update)
                {
                    context = receiveContexts.Values.LastOrDefault(value => value.Valid && value.Phase == "collecting" &&
                        ReferenceEquals(value.Connection, connection));
                    if (context is null) return;
                    var update = KdeShareProtocol.ParseUpdate(packet.Body);
                    UpdateReceiveBounds(context, update.NumberOfFiles, update.TotalPayloadSize);
                    return;
                }
                var announcement = KdeShareProtocol.Parse(packet);
                context = receiveContexts.Values.FirstOrDefault(value => value.Valid && value.Phase == "collecting" &&
                    ReferenceEquals(value.Connection, connection) && value.Batch!.AcceptingAnnouncements);
                if (context is null)
                {
                    if (receiveContexts.Count >= 8) throw new InvalidOperationException("incoming_offer_limit_reached");
                    var count = announcement.NumberOfFiles ?? 1;
                    var total = announcement.TotalPayloadSize ?? (count == 1 ? announcement.Size : -1);
                    if (receiveContexts.Values.Sum(value => value.Reserved) + total > KdeIncomingFileBatch.MaxBytes)
                        throw new InvalidDataException("incoming_staging_quota_exceeded");
                    var id = Guid.NewGuid().ToString("N");
                    context = new(id, connection, preferences, new(preferences.DeviceId, pin, connection, preferences.Epoch),
                        DateTimeOffset.UtcNow.AddMinutes(10), total, lifetime.Token);
                    context.Cancellation.CancelAfter(TimeSpan.FromMinutes(10));
                    context.Batch = new(context.Source, receiveRoot, count, total, context.Deadline, () => CurrentReceiveSource(context));
                    receiveContexts.Add(id, context);
                }
                var normalized = announcement with { NumberOfFiles = announcement.NumberOfFiles ?? 1,
                    TotalPayloadSize = announcement.TotalPayloadSize ?? announcement.Size };
                UpdateReceiveBounds(context, normalized.NumberOfFiles!.Value, normalized.TotalPayloadSize!.Value);
                var memberId = Guid.NewGuid(); context.Batch!.Announce(memberId, normalized);
                if (!receiveQueue.Writer.TryWrite(new(context, memberId, normalized)))
                    throw new IOException("incoming_queue_full");
            }
        }
        catch (Exception error) when (error is InvalidDataException or InvalidOperationException or IOException)
        {
            if (context is not null) Track(DropReceiveContextAsync(context, "failed"));
            else SafeInvoke(FileReceiveProgress, new KdeFileReceiveProgress("", connection.Identity.DeviceId, "failed", 0, 0));
        }
    }

    private void UpdateReceiveBounds(ReceiveContext context, long count, long total)
    {
        if (total < 0 || receiveContexts.Values.Where(value => !ReferenceEquals(value, context)).Sum(value => value.Reserved) + total > KdeIncomingFileBatch.MaxBytes)
            throw new InvalidDataException("incoming_staging_quota_exceeded");
        context.Batch!.Update(count, total); context.Reserved = total;
    }

    private async Task ReceiveFilesLoopAsync(CancellationToken cancellation)
    {
        try
        {
            await foreach (var work in receiveQueue.Reader.ReadAllAsync(cancellation).ConfigureAwait(false))
            {
                var context = work.Context;
                lock (activeGate)
                {
                    if (!context.Valid || context.Phase != "collecting" || !receiveContexts.TryGetValue(context.Id, out var found) || !ReferenceEquals(found, context)) continue;
                    context.ActiveDownload = 1;
                }
                string? ownedDownload = null;
                var createdDownload = false;
                var adopted = false;
                try
                {
                    if (CurrentReceiveSource(context) is null) throw new InvalidOperationException("incoming_source_changed");
                    var token = context.Cancellation.Token;
                    ownedDownload = Path.Combine(receiveRoot, "incoming-" + Guid.NewGuid().ToString("N") + ".part");
                    KdeIncomingPayloadReceipt receipt;
                    await using (var output = new FileStream(ownedDownload, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                        65536, FileOptions.Asynchronous | FileOptions.SequentialScan))
                    {
                        createdDownload = true;
                        lock (activeGate) context.RawDownloads.Add(ownedDownload);
                        var before = context.Received;
                        receipt = await ReceiveFilePayloadTransportAsync(context.Connection.Address, work.Announcement.Port,
                            local.Certificate, context.Source.DeviceId, context.Source.CertificateFingerprint, work.Announcement.Size,
                            output, () => CurrentReceiveSource(context) is not null, token,
                            bytes => SafeInvoke(FileReceiveProgress, new KdeFileReceiveProgress(context.Id, context.Source.DeviceId,
                                "receiving", before + bytes, context.Reserved))).ConfigureAwait(false);
                        await output.FlushAsync(token).ConfigureAwait(false); output.Flush(flushToDisk: true);
                    }
                    var batch = context.Batch ?? throw new InvalidOperationException("incoming_batch_not_active");
                    var complete = batch.Stage(work.MemberId, ownedDownload, receipt.Sha256);
                    adopted = true;
                    lock (activeGate) context.RawDownloads.Remove(ownedDownload);
                    context.Received += receipt.Bytes;
                    if (!complete) continue;
                    KdeFileReceiveProposal proposal;
                    lock (activeGate)
                    {
                        if (!context.Valid || CurrentReceiveSource(context) is null) throw new InvalidOperationException("incoming_source_changed");
                        context.Offer = batch.CreateOffer((expected, action) =>
                        {
                            lock (activeGate)
                            {
                                if (!context.Valid || !context.Accepting || !receiveContexts.TryGetValue(context.Id, out var current) ||
                                    !ReferenceEquals(current, context) || !ReferenceEquals(expected.Connection, context.Connection) ||
                                    CurrentReceiveSource(context) is null) throw new InvalidOperationException("incoming_publication_source_changed");
                                action();
                            }
                        });
                        batch.Dispose(); context.Batch = null; context.Phase = "offered";
                        proposal = ReceiveProposal(context);
                    }
                    SafeInvoke(FileProposed, proposal);
                }
                catch (Exception error) when (error is IOException or InvalidDataException or InvalidOperationException or
                    OperationCanceledException or System.Security.Authentication.AuthenticationException or UnauthorizedAccessException)
                { await DropReceiveContextAsync(context, "failed").ConfigureAwait(false); }
                finally
                {
                    try
                    {
                        if (!adopted && createdDownload && ownedDownload is not null)
                        {
                            EnsureReceiveRoot(); File.Delete(ownedDownload);
                            lock (activeGate) context.RawDownloads.Remove(ownedDownload);
                        }
                    }
                    catch (Exception error) when (error is IOException or UnauthorizedAccessException)
                    { DebugLog("receive.download_cleanup_failed", "owned_context=" + context.Id + " type=" + error.GetType().Name); }
                    lock (activeGate) context.ActiveDownload = 0;
                    if (!context.Valid) await DropReceiveContextAsync(context, "failed").ConfigureAwait(false);
                }
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
    }

    private KdeFileReceiveProposal ReceiveProposal(ReceiveContext context) => new(context.Id, context.Source.DeviceId,
        context.Offer!.Proposal(), context.Reserved, context.Deadline, context.Offer.Saved.Count != 0);

    internal Task<JsonObject> AcceptFileReceiveAsync(string id, string directory, CancellationToken cancellation = default)
    {
        ReceiveContext context;
        CancellationToken contextCancellation;
        CancellationToken backendCancellation;
        lock (activeGate)
        {
            if (!receiveContexts.TryGetValue(id, out context!) || !context.Valid || context.Phase != "offered" || context.Accepting ||
                CurrentReceiveSource(context) is null) throw new InvalidOperationException("incoming_offer_not_available");
            context.Accepting = true; context.Phase = "publishing";
            contextCancellation = context.Cancellation.Token;
            backendCancellation = lifetime.Token;
        }
        var task = Task.Run(async () =>
        {
            using var acceptedLifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, contextCancellation, backendCancellation);
            var ok = false;
            try
            {
                var selected = directory.Length != 0 ? directory : context.Offer!.BoundDestination.Length != 0
                    ? context.Offer.BoundDestination : context.Preferences.Directory;
                await context.Offer!.PublishAsync(selected, acceptedLifetime.Token).ConfigureAwait(false); ok = true;
            }
            catch (Exception error) when (error is IOException or InvalidDataException or InvalidOperationException or
                OperationCanceledException or UnauthorizedAccessException)
            { SafeInvoke(FileReceiveProgress, new KdeFileReceiveProgress(id, context.Source.DeviceId, "failed", context.Received, context.Reserved)); }
            var saved = context.Offer!.Saved;
            foreach (var file in saved)
            {
                bool emit;
                lock (activeGate) emit = context.Emitted.Add(file.Id);
                if (emit) SafeInvoke(FileSaved, file);
            }
            var keep = false;
            KdeFileReceiveProposal? retry = null;
            lock (activeGate)
            {
                context.Accepting = false;
                keep = context.Valid && CurrentReceiveSource(context) is not null && context.Offer.RemainingCount != 0;
                if (keep)
                {
                    context.Phase = "offered";
                    try { retry = ReceiveProposal(context); }
                    catch (Exception error) when (error is InvalidOperationException or OperationCanceledException) { keep = false; }
                }
            }
            if (!keep) await DropReceiveContextAsync(context, ok ? "saved" : "failed").ConfigureAwait(false);
            else SafeInvoke(FileProposed, retry!);
            bool cleanupPending;
            lock (activeGate) cleanupPending = !keep && receiveContexts.ContainsKey(id);
            return new JsonObject { ["ok"] = ok, ["id"] = id, ["remaining_count"] = context.Offer.RemainingCount,
                ["saved_count"] = saved.Count, ["cleanup_pending"] = cleanupPending,
                ["error"] = ok ? "" : "incoming_reception_failed" };
        }, CancellationToken.None);
        Track(task); return task;
    }

    internal async Task RejectFileReceiveAsync(string id)
    {
        ReceiveContext? context;
        lock (activeGate) receiveContexts.TryGetValue(id, out context);
        if (context is null) throw new InvalidOperationException("incoming_offer_not_available");
        await DropReceiveContextAsync(context, "rejected").ConfigureAwait(false);
    }

    private async Task DropReceiveContextAsync(ReceiveContext context, string reason)
    {
        lock (activeGate) { context.Valid = false; context.Phase = "cleanup"; }
        if (Interlocked.CompareExchange(ref context.CleanupStarted, 1, 0) != 0) return;
        context.Cancellation.Cancel();
        try
        {
            if (Volatile.Read(ref context.ActiveDownload) != 0)
            { Interlocked.Exchange(ref context.CleanupStarted, 0); return; }
            EnsureReceiveRoot();
            foreach (var path in context.RawDownloads.ToArray())
            {
                File.Delete(path);
                context.RawDownloads.Remove(path);
            }
            context.Batch?.Dispose();
            if (context.Offer is not null) await context.Offer.DisposeAsync().ConfigureAwait(false);
            lock (activeGate) receiveContexts.Remove(context.Id);
            context.Cancellation.Dispose();
            SafeInvoke(FileReceiveProgress, new KdeFileReceiveProgress(context.Id, context.Source.DeviceId, reason, context.Received, context.Reserved));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Interlocked.Exchange(ref context.CleanupStarted, 0);
            DebugLog("receive.cleanup_failed", "owned_context=" + context.Id + " type=" + error.GetType().Name);
        }
    }

    private void CleanupFileReceives(DateTimeOffset now)
    {
        ReceiveContext[] expired;
        lock (activeGate) expired = receiveContexts.Values.Where(context =>
            !context.Valid || context.Deadline <= now || CurrentReceiveSource(context) is null).ToArray();
        foreach (var context in expired) Track(DropReceiveContextAsync(context, "expired"));
    }

    private void RevokeFileReceives(Connection connection)
    {
        ReceiveContext[] contexts;
        lock (activeGate) contexts = receiveContexts.Values.Where(context => ReferenceEquals(context.Connection, connection)).ToArray();
        foreach (var context in contexts) Track(DropReceiveContextAsync(context, "expired"));
    }

    private async Task DisposeFileReceivesAsync()
    {
        ReceiveContext[] contexts;
        lock (activeGate) contexts = receiveContexts.Values.ToArray();
        foreach (var context in contexts) await DropReceiveContextAsync(context, "rejected").ConfigureAwait(false);
        if (!receiveRootOwned) return;
        EnsureReceiveRoot();
        if (receiveContexts.Count != 0) throw new IOException("incoming_cleanup_pending");
        File.Delete(ReceiveMarker);
        Directory.Delete(receiveRoot, recursive: false);
        receiveRootOwned = false;
    }
}
