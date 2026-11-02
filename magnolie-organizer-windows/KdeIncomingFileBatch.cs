using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeReceiveSource(string DeviceId, string CertificateFingerprint, object Connection, long Generation);
internal sealed record KdeIncomingMember(string Name, long Size);
internal sealed record KdeStagedIncomingMember(Guid Id, string Name, long Size, string StagedPath, string Sha256);

// No listener, store constructor or consent side effect. The receiver must own
// the staging directory and provide fresh native source observations.
internal sealed class KdeIncomingFileBatch : IDisposable
{
    internal const int MaxFiles = 128;
    internal const long MaxBytes = 400 * 1024 * 1024;
    private readonly object gate = new();
    private readonly KdeReceiveSource source;
    private readonly Func<KdeReceiveSource?> currentSource;
    private readonly Func<DateTimeOffset> clock;
    private readonly string stagingDirectory;
    private readonly DateTimeOffset deadline;
    private readonly List<Member> members = [];
    private int count;
    private long total;
    private bool sealedList;
    private bool closed;

    private sealed class Member(Guid id, KdeShareAnnouncement value)
    {
        internal readonly Guid Id = id;
        internal readonly string Name = value.Name;
        internal readonly long Size = value.Size;
        internal KdeStagedIncomingMember? Staged;
    }

    internal KdeIncomingFileBatch(KdeReceiveSource source, string stagingDirectory,
        long count, long total, DateTimeOffset deadline, Func<KdeReceiveSource?> currentSource,
        Func<DateTimeOffset>? clock = null)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (string.IsNullOrEmpty(source.DeviceId) || source.DeviceId.Length > 200 || source.DeviceId.Any(char.IsControl) ||
            source.Connection is null || source.Generation < 0 || source.CertificateFingerprint is not { Length: 64 } ||
            source.CertificateFingerprint.Any(character => !char.IsAsciiHexDigitLower(character)))
            throw new ArgumentException("invalid_receive_source");
        this.source = source;
        this.currentSource = currentSource ?? throw new ArgumentNullException(nameof(currentSource));
        this.clock = clock ?? (() => DateTimeOffset.UtcNow);
        this.deadline = deadline;
        if (deadline <= this.clock() || deadline > this.clock().AddMinutes(10))
            throw new ArgumentException("invalid_receive_deadline");
        this.stagingDirectory = Path.TrimEndingDirectorySeparator(Path.GetFullPath(stagingDirectory));
        if (!Directory.Exists(this.stagingDirectory) || !RealDirectoryChain(this.stagingDirectory))
            throw new ArgumentException("private_existing_staging_directory_required");
        Update(count, total);
    }

    internal static bool RealDirectoryChain(string directory)
    {
        for (var item = new DirectoryInfo(directory); item is not null; item = item.Parent)
            if (!item.Exists || (item.Attributes & FileAttributes.ReparsePoint) != 0) return false;
        return true;
    }

    private bool OwnStagingPath(string path)
    {
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        return Path.IsPathFullyQualified(path) && KdeShareProtocol.SafeName(Path.GetFileName(path)) &&
            string.Equals(Path.GetDirectoryName(Path.GetFullPath(path)), stagingDirectory, comparison) &&
            RealDirectoryChain(stagingDirectory) &&
            (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) == 0);
    }

    private void Require(bool allowSealed = false)
    {
        var current = currentSource();
        if (closed || sealedList && !allowSealed || clock() >= deadline || current is null ||
            current.DeviceId != source.DeviceId || current.CertificateFingerprint != source.CertificateFingerprint ||
            current.Generation != source.Generation || !ReferenceEquals(current.Connection, source.Connection))
            throw new InvalidOperationException("incoming_batch_source_expired_or_changed");
    }

    internal long ReservedBytes { get { lock (gate) return total; } }
    internal bool AcceptingAnnouncements { get { lock (gate) return !closed && !sealedList && members.Count < count; } }

    internal void Update(long newCount, long newTotal)
    {
        lock (gate)
        {
            Require();
            if (newCount is < 1 or > MaxFiles || newTotal is < 0 or > MaxBytes || newCount < count || newTotal < total)
                throw new InvalidDataException("invalid_incoming_batch_bounds");
            count = (int)newCount;
            total = newTotal;
        }
    }

    internal void Announce(Guid memberId, KdeShareAnnouncement value)
    {
        lock (gate)
        {
            Require();
            if (memberId == Guid.Empty || members.Any(member => member.Id == memberId) ||
                !KdeShareProtocol.SafeName(value.Name) || value.Size is < 0 or > KdeShareProtocol.MaxFileBytes ||
                value.NumberOfFiles is null || value.TotalPayloadSize is null)
                throw new InvalidDataException("invalid_incoming_batch_member");
            Update(value.NumberOfFiles.Value, value.TotalPayloadSize.Value);
            var sum = members.Sum(member => member.Size) + value.Size;
            if (members.Count >= count || sum > total || members.Count + 1 == count && sum != total)
                throw new InvalidDataException("incoming_batch_member_exceeds_bounds");
            members.Add(new(memberId, value));
        }
    }

    internal bool Stage(Guid memberId, string path)
    {
        lock (gate)
        {
            Require();
            var member = members.SingleOrDefault(value => value.Id == memberId);
            if (member is null || member.Staged is not null || !OwnStagingPath(path))
                throw new InvalidDataException("unannounced_or_unsafe_staging_member");
            using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
                bufferSize: 65536, FileOptions.SequentialScan);
            if (input.Length != member.Size) throw new InvalidDataException("incoming_staged_size_changed");
            using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var buffer = new byte[65536];
            long read = 0;
            int length;
            while ((length = input.Read(buffer)) != 0)
            {
                read += length;
                if (read > member.Size) throw new InvalidDataException("incoming_staged_size_changed");
                digest.AppendData(buffer, 0, length);
                Require();
            }
            if (read != member.Size) throw new InvalidDataException("incoming_staged_size_changed");
            Require();
            member.Staged = new(member.Id, member.Name, member.Size, path,
                Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant());
            sealedList = members.Count == count && members.All(value => value.Staged is not null);
            return sealedList;
        }
    }

    internal IReadOnlyList<KdeIncomingMember> Proposal()
    {
        lock (gate)
        {
            Require(allowSealed: true);
            if (!sealedList) throw new InvalidOperationException("incomplete_incoming_batch");
            return members.Select(value => new KdeIncomingMember(value.Name, value.Size)).ToArray();
        }
    }

    internal IReadOnlyList<KdeStagedIncomingMember> Take()
    {
        lock (gate)
        {
            Proposal();
            var result = members.Select(value => value.Staged!).ToArray();
            closed = true;
            members.Clear();
            return result;
        }
    }

    internal KdeIncomingFileOffer CreateOffer(Action<KdeReceiveSource, Action> publicationGate)
    {
        lock (gate)
        {
            Proposal();
            var offer = new KdeIncomingFileOffer(source, currentSource, clock, deadline, OwnStagingPath,
                members.Select(value => value.Staged!).ToArray(), publicationGate);
            closed = true;
            members.Clear();
            return offer;
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            closed = true;
            foreach (var member in members)
                if (member.Staged is not null && OwnStagingPath(member.Staged.StagedPath))
                    File.Delete(member.Staged.StagedPath);
            members.Clear();
        }
    }
}
