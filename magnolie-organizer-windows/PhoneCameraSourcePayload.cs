using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

// Immutable build identity only, not installation, COM activation or capture
// authority. Never consult adjacent manifests, settings or runtime paths here.
internal sealed class PhoneCameraSourcePayload
{
    internal const string Filename = "Magnolie.PhoneCameraSource.x64.dll";
    internal const string ClassId = "dab1e726-131a-4a3a-abea-6a8ca1b4f571";
    private readonly byte[] binary;
    internal string Sha256 { get; }
    internal static IReadOnlyList<string> SourceFiles { get; } = Array.AsReadOnly(new[] {
        "PhoneCameraSamples", "PhoneCameraClock", "PhoneCameraSource", "PhoneCameraActivate",
        "PhoneCameraFactory", "PhoneCameraDormantSource", "PhoneCameraModule", "PhoneCameraPipe", "PhoneCameraOutputLease",
        "PhoneCameraFrameServerPeer", "PhoneCameraBrokerProtocol", "PhoneCameraBrokerChannel", "PhoneCameraSourceBroker"
    }.SelectMany(name => new[] { "native/phone-camera/" + name + ".h", "native/phone-camera/" + name + ".cpp" })
        .Concat(new[] { "native/phone-camera/PhoneCameraModule.def", "werkzeuge/phone_camera_source.py", "PhoneCameraSource.targets" }).ToArray());
    private PhoneCameraSourcePayload(byte[] image, string hash) { binary = image; Sha256 = hash; }
    internal static PhoneCameraSourcePayload? LoadEmbedded()
    {
        var assembly = typeof(PhoneCameraSourcePayload).Assembly;
        using var image = assembly.GetManifestResourceStream(Filename);
        using var descriptor = assembly.GetManifestResourceStream("Magnolie.PhoneCameraSource.manifest");
        return ReadResources(image, descriptor);
    }
    internal static PhoneCameraSourcePayload? ReadResources(Stream? image, Stream? descriptor)
    {
        if (image is null && descriptor is null) return null;
        if (image is null || descriptor is null) throw new InvalidDataException("webcam_source_resources_incomplete");
        return VerifyEmbeddedSnapshot(ReadBounded(image, 8 * 1024 * 1024), ReadBounded(descriptor, 8192));
    }
    internal static PhoneCameraSourcePayload VerifyEmbeddedSnapshot(ReadOnlySpan<byte> image, ReadOnlySpan<byte> descriptor)
    {
        if (image.Length is < 128 or > 8 * 1024 * 1024) throw new InvalidDataException("webcam_source_size_invalid");
        var bytes = image.ToArray();
        var pe = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(60));
        if (bytes[0] != 'M' || bytes[1] != 'Z' || pe < 64 || pe > bytes.Length - 96 ||
            BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(pe)) != 0x4550 ||
            BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 4)) != 0x8664 ||
            (BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 22)) & 0x2002) != 0x2002 ||
            BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 24)) != 0x20b ||
            (BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 94)) & 0x4140) != 0x4140)
            throw new InvalidDataException("webcam_source_x64_dll_protections_required");
        if (descriptor.Length is < 1 or > 8192) throw new InvalidDataException("webcam_source_manifest_invalid");
        var lines = new UTF8Encoding(false, true).GetString(descriptor).Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');
        if (lines.Length != SourceFiles.Count + 5 || lines[^1] != "" || lines[0] != "magnolie-phone-camera-source-v1" ||
            lines[1] != "architecture=x64" || lines[2] != "classId=" + ClassId)
            throw new InvalidDataException("webcam_source_manifest_invalid");
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        if (lines[3] != "sha256=" + hash) throw new CryptographicException("webcam_source_checksum_changed");
        for (int i = 0; i < SourceFiles.Count; ++i)
        {
            var prefix = "source=" + SourceFiles[i] + "|";
            if (!lines[i + 4].StartsWith(prefix, StringComparison.Ordinal) || lines[i + 4].Length != prefix.Length + 64 ||
                lines[i + 4].AsSpan(prefix.Length).ContainsAnyExcept("0123456789abcdef"))
                throw new InvalidDataException("webcam_source_sources_invalid");
        }
        return new PhoneCameraSourcePayload(bytes, hash);
    }
    internal void WriteSnapshot(Stream destination) => destination.Write(binary);
    private static byte[] ReadBounded(Stream stream, int maximum)
    {
        using var output = new MemoryStream(); var buffer = new byte[16384];
        while (true)
        {
            var count = stream.Read(buffer); if (count == 0) return output.ToArray();
            if (output.Length + count > maximum) throw new InvalidDataException("webcam_source_resource_size_invalid");
            output.Write(buffer, 0, count);
        }
    }
}
