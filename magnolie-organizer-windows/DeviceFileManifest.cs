using System.Buffers.Binary;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record DeviceManifestFile(string Id, string Path, long Size, string Sha256);

// General device-file manifest, not a KDE aggregate hint or a Notes book ACK.
// Parsing/constructing it never authorizes staging, resume or publication.
internal sealed class DeviceFileManifest
{
    internal const int ChunkBytes = 65536;
    internal const int MaxFiles = 128;
    internal const long MaxFileBytes = 50 * 1024 * 1024;
    internal const long MaxTotalBytes = 400 * 1024 * 1024;
    private static readonly Regex Id = new("\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant);
    private static readonly Regex Sha = new("\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
    private static readonly Regex Device = new("\\A[A-Za-z0-9_-]{16,160}\\z", RegexOptions.CultureInvariant);
    internal string TransferId { get; }
    internal string SourceId { get; }
    internal string SenderId { get; }
    internal string ReceiverId { get; }
    internal ReadOnlyCollection<DeviceManifestFile> Files { get; }
    internal long TotalBytes { get; }
    internal string Fingerprint { get; }

    internal DeviceFileManifest(string transferId, string sourceId, string senderId, string receiverId,
        IReadOnlyList<DeviceManifestFile> files, long totalBytes)
    {
        if (!Id.IsMatch(transferId) || !Id.IsMatch(sourceId) || !Device.IsMatch(senderId) || !Device.IsMatch(receiverId) ||
            senderId == receiverId || files.Count is < 1 or > MaxFiles || totalBytes is < 0 or > MaxTotalBytes)
            throw new InvalidDataException("invalid_file_manifest_identity_or_bounds");
        var copy = files.ToArray();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var file in copy)
        {
            if (file is null || !Id.IsMatch(file.Id) || !Sha.IsMatch(file.Sha256) || file.Size is < 0 or > MaxFileBytes ||
                !ids.Add(file.Id) || !PortablePath(file.Path)) throw new InvalidDataException("invalid_file_manifest_member");
        }
        for (var first = 0; first < copy.Length; first++)
            for (var second = first + 1; second < copy.Length; second++)
                if (CollidingPaths(copy[first].Path, copy[second].Path)) throw new InvalidDataException("ambiguous_file_manifest_paths");
        if (copy.Sum(file => file.Size) != totalBytes) throw new InvalidDataException("file_manifest_total_mismatch");
        TransferId = transferId; SourceId = sourceId; SenderId = senderId; ReceiverId = receiverId;
        Files = Array.AsReadOnly(copy); TotalBytes = totalBytes;
        Fingerprint = ComputeFingerprint();
    }

    private static bool PortablePath(string path)
    {
        if (string.IsNullOrEmpty(path) || path.Length > 2048) return false;
        try
        {
            if (path.EnumerateRunes().Count() > 1024 || Encoding.UTF8.GetByteCount(path) > 4096 ||
                path.Normalize(NormalizationForm.FormC) != path) return false;
            var parts = path.Split('/');
            return parts.Length <= 16 && parts.All(KdeShareProtocol.SafeName);
        }
        catch (ArgumentException) { return false; }
    }

    private static bool CollidingPaths(string first, string second)
    {
        var a = first.Split('/'); var b = second.Split('/');
        // Conservative receiver preflight: case/diacritic-equivalent aliases
        // are rejected rather than ever acquiring the same destination file.
        // Native target planning still has to enforce its actual filesystem rules.
        for (var index = 0; index < Math.Min(a.Length, b.Length); index++)
            if (CultureInfo.InvariantCulture.CompareInfo.Compare(a[index], b[index],
                CompareOptions.IgnoreCase | CompareOptions.IgnoreNonSpace) != 0) return false;
        return true; // duplicate file or file/parent-directory collision
    }

    private string ComputeFingerprint()
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        hash.AppendData(Encoding.ASCII.GetBytes("magnolie-file-manifest-v1\0"));
        void UInt32(uint value) { Span<byte> bytes = stackalloc byte[4]; BinaryPrimitives.WriteUInt32BigEndian(bytes, value); hash.AppendData(bytes); }
        void UInt64(ulong value) { Span<byte> bytes = stackalloc byte[8]; BinaryPrimitives.WriteUInt64BigEndian(bytes, value); hash.AppendData(bytes); }
        void Text(string value) { var bytes = Encoding.UTF8.GetBytes(value); UInt32((uint)bytes.Length); hash.AppendData(bytes); }
        foreach (var value in new[] { TransferId, SourceId, SenderId, ReceiverId }) Text(value);
        UInt32(ChunkBytes); UInt32((uint)Files.Count); UInt64((ulong)TotalBytes);
        foreach (var file in Files)
        { Text(file.Id); Text(file.Path); UInt64((ulong)file.Size); hash.AppendData(Convert.FromHexString(file.Sha256)); }
        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    internal static void Exact(JsonElement value, params string[] fields)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("file_manifest_object_required");
        var names = value.EnumerateObject().Select(property => property.Name).ToArray();
        if (names.Length != fields.Length || !names.ToHashSet(StringComparer.Ordinal).SetEquals(fields))
            throw new InvalidDataException("unexpected_or_duplicate_file_manifest_fields");
    }
    internal static string Text(JsonElement value, string field) => value.GetProperty(field).ValueKind == JsonValueKind.String
        ? value.GetProperty(field).GetString()! : throw new InvalidDataException("file_manifest_string_required");
    internal static long Integer(JsonElement value, string field) => value.GetProperty(field).ValueKind == JsonValueKind.Number &&
        value.GetProperty(field).TryGetInt64(out var number) && number >= 0 ? number : throw new InvalidDataException("file_manifest_integer_required");

    internal static DeviceFileManifest Parse(JsonElement root)
    {
        Exact(root, "format", "transfer_id", "source_id", "sender_id", "receiver_id", "chunk_bytes", "total_bytes", "files");
        if (Integer(root, "format") != 1 || Integer(root, "chunk_bytes") != ChunkBytes ||
            root.GetProperty("files").ValueKind != JsonValueKind.Array || root.GetProperty("files").GetArrayLength() is < 1 or > MaxFiles)
            throw new InvalidDataException("unsupported_file_manifest_format_or_count");
        var files = root.GetProperty("files").EnumerateArray().Select(file =>
        {
            Exact(file, "id", "path", "size", "sha256");
            return new DeviceManifestFile(Text(file, "id"), Text(file, "path"), Integer(file, "size"), Text(file, "sha256"));
        }).ToArray();
        return new(Text(root, "transfer_id"), Text(root, "source_id"), Text(root, "sender_id"), Text(root, "receiver_id"),
            files, Integer(root, "total_bytes"));
    }
}
