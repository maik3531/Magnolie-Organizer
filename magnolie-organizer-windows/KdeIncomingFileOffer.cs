using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeSavedIncomingFile(Guid Id, string Name, string Path, long Size, string Sha256);

// Created only from a complete native staging object. IPC may refer to an offer
// ID, but must never supply these source/stream/authority callbacks itself.
internal sealed class KdeIncomingFileOffer : IAsyncDisposable
{
    private readonly KdeReceiveSource source;
    private readonly Func<KdeReceiveSource?> currentSource;
    private readonly Func<DateTimeOffset> clock;
    private readonly DateTimeOffset deadline;
    private readonly Func<string, bool> ownStaging;
    private readonly Action<KdeReceiveSource, Action> publicationGate;
    private readonly SemaphoreSlim operation = new(1, 1);
    private readonly CancellationTokenSource lifetime = new();
    private readonly object state = new();
    private readonly List<KdeStagedIncomingMember> remaining;
    private readonly List<KdeSavedIncomingFile> saved = [];
    private readonly HashSet<string> ownedStaging;
    private readonly Dictionary<string, string> ownedTemporary = new(StringComparer.Ordinal);
    private string destination = "";
    private volatile bool closed;
    private volatile bool disposeComplete;

    internal KdeIncomingFileOffer(KdeReceiveSource source, Func<KdeReceiveSource?> currentSource,
        Func<DateTimeOffset> clock, DateTimeOffset deadline, Func<string, bool> ownStaging,
        IReadOnlyList<KdeStagedIncomingMember> members, Action<KdeReceiveSource, Action> publicationGate)
    {
        ArgumentNullException.ThrowIfNull(publicationGate);
        this.source = source; this.currentSource = currentSource; this.clock = clock;
        this.deadline = deadline; this.ownStaging = ownStaging; this.publicationGate = publicationGate;
        remaining = members.ToList();
        ownedStaging = members.Select(value => value.StagedPath).ToHashSet(StringComparer.Ordinal);
        ReservedBytes = members.Sum(value => value.Size);
    }

    internal long ReservedBytes { get; }
    internal int RemainingCount { get { lock (state) return remaining.Count; } }
    internal IReadOnlyList<KdeSavedIncomingFile> Saved { get { lock (state) return saved.ToArray(); } }

    private void Require()
    {
        lifetime.Token.ThrowIfCancellationRequested();
        var current = currentSource();
        if (closed || clock() >= deadline || current is null || current.DeviceId != source.DeviceId ||
            current.CertificateFingerprint != source.CertificateFingerprint || current.Generation != source.Generation ||
            !ReferenceEquals(current.Connection, source.Connection))
            throw new InvalidOperationException("incoming_offer_source_expired_or_changed");
    }

    internal IReadOnlyList<KdeIncomingMember> Proposal()
    {
        Require();
        lock (state) return remaining.Select(value => new KdeIncomingMember(value.Name, value.Size)).ToArray();
    }

    private static string SelectedDirectory(string directory)
    {
        if (!Path.IsPathFullyQualified(directory) || !Directory.Exists(directory))
            throw new InvalidDataException("incoming_destination_must_exist");
        var full = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
        if (!KdeIncomingFileBatch.RealDirectoryChain(full)) throw new IOException("incoming_destination_is_linked");
        return full;
    }

    private static string AlternativeName(string name, int number)
    {
        if (number == 0) return name;
        var dot = name.LastIndexOf('.');
        var stem = dot > 0 ? name[..dot] : name;
        var extension = dot > 0 ? name[dot..] : "";
        var marker = " (" + number.ToString(System.Globalization.CultureInfo.InvariantCulture) + ")";
        string Fit(string value, int maximum)
        {
            var length = Math.Min(maximum, value.Length);
            if (length > 0 && char.IsHighSurrogate(value[length - 1])) length--;
            return value[..length];
        }
        extension = Fit(extension, 255 - marker.Length - 1);
        stem = Fit(stem, 255 - marker.Length - extension.Length);
        if (stem.Length == 0) stem = "_";
        return stem + marker + extension;
    }

    private async Task<string> CopyVerifiedAsync(KdeStagedIncomingMember member, string directory, CancellationToken cancellation)
    {
        Require();
        if (!ownStaging(member.StagedPath)) throw new IOException("incoming_staging_path_changed");
        var temporary = Path.Combine(directory, ".magnolie-incoming-" + Guid.NewGuid().ToString("N") + ".part");
        await using var input = new FileStream(member.StagedPath, FileMode.Open, FileAccess.Read, FileShare.Read,
            65536, FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (input.Length != member.Size) throw new InvalidDataException("incoming_staged_size_changed");
        await using var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
            65536, FileOptions.Asynchronous | FileOptions.SequentialScan);
        ownedTemporary.Add(temporary, directory);
        using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[65536];
        long received = 0;
        int count;
        while ((count = await input.ReadAsync(buffer, cancellation).ConfigureAwait(false)) != 0)
        {
            Require();
            received += count;
            if (received > member.Size) throw new InvalidDataException("incoming_staged_size_changed");
            digest.AppendData(buffer, 0, count);
            await output.WriteAsync(buffer.AsMemory(0, count), cancellation).ConfigureAwait(false);
            Require();
        }
        if (received != member.Size || Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != member.Sha256)
            throw new InvalidDataException("incoming_staged_content_changed");
        await output.FlushAsync(cancellation).ConfigureAwait(false);
        output.Flush(flushToDisk: true);
        Require();
        return temporary;
    }

    private void CleanupTemporary()
    {
        foreach (var (path, directory) in ownedTemporary.ToArray())
        {
            if (!KdeIncomingFileBatch.RealDirectoryChain(directory)) throw new IOException("incoming_temporary_cleanup_path_changed");
            File.Delete(path);
            ownedTemporary.Remove(path);
        }
    }

    private void CleanupStaged(string path)
    {
        if (!ownStaging(path)) throw new IOException("incoming_staging_cleanup_path_changed");
        File.Delete(path);
        ownedStaging.Remove(path);
    }

    internal async Task<IReadOnlyList<KdeSavedIncomingFile>> PublishAsync(string directory, CancellationToken cancellation = default)
    {
        using var active = CancellationTokenSource.CreateLinkedTokenSource(cancellation, lifetime.Token);
        await operation.WaitAsync(active.Token).ConfigureAwait(false);
        try
        {
            Require();
            var selected = SelectedDirectory(directory);
            var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            lock (state)
                if (destination.Length != 0 && !string.Equals(destination, selected, comparison))
                    throw new InvalidOperationException("incoming_partial_destination_changed");
            while (true)
            {
                KdeStagedIncomingMember? member;
                lock (state) member = remaining.FirstOrDefault();
                if (member is null) return Saved;
                active.Token.ThrowIfCancellationRequested();
                Require();
                try
                {
                    var temporary = await CopyVerifiedAsync(member, selected, active.Token).ConfigureAwait(false);
                    var committed = false;
                    for (var number = 0; number < 10000 && !committed; number++)
                    {
                        var name = AlternativeName(member.Name, number);
                        var target = Path.Combine(selected, name);
                        try
                        {
                            // The native controller must serialize this callback
                            // with source/configuration revocation. Recheck inside
                            // that gate, at the actual no-overwrite publication.
                            publicationGate(source, () =>
                            {
                                Require(); active.Token.ThrowIfCancellationRequested();
                                SelectedDirectory(selected);
                                File.Move(temporary, target, overwrite: false);
                                ownedTemporary.Remove(temporary);
                                lock (state)
                                {
                                    saved.Add(new(member.Id, name, target, member.Size, member.Sha256));
                                    remaining.RemoveAt(0); destination = selected;
                                }
                                committed = true;
                            });
                            if (!committed) throw new InvalidOperationException("incoming_native_publication_gate_did_not_commit");
                        }
                        catch (IOException) when (!committed && (File.Exists(target) || Directory.Exists(target))) { }
                    }
                    if (!committed) throw new IOException("incoming_collision_limit_reached");
                    CleanupStaged(member.StagedPath);
                }
                finally { CleanupTemporary(); }
            }
        }
        finally { operation.Release(); }
    }

    public async ValueTask DisposeAsync()
    {
        lock (state)
        {
            if (disposeComplete) return;
            lifetime.Cancel();
        }
        await operation.WaitAsync().ConfigureAwait(false);
        try
        {
            closed = true;
            CleanupTemporary();
            foreach (var path in ownedStaging.ToArray()) CleanupStaged(path);
            lock (state)
            {
                remaining.Clear();
                disposeComplete = true;
                lifetime.Dispose();
            }
        }
        finally { operation.Release(); }
    }
}
