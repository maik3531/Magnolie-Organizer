using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

// Loader authority is an immutable resource, never an adjacent manifest or hash
// supplied by a user/configuration. No path, staging or loading is done here.
internal sealed class PhoneCameraAudioParentPayload
{
    internal const string Filename = "Magnolie.PhoneAudioParent.x64.dll";
    private readonly byte[] binary;
    internal string Sha256 { get; }
    internal static IReadOnlyList<string> SourceFiles { get; } = Array.AsReadOnly(new[] {
        "native/phone-camera/PhoneCameraAudioParent.h", "native/phone-camera/PhoneCameraAudioParent.cpp",
        "native/phone-camera/PhoneCameraClock.h", "native/phone-camera/PhoneCameraClock.cpp",
        "native/phone-camera/PhoneCameraPipe.h", "native/phone-camera/PhoneCameraPipe.cpp",
        "native/phone-camera/PhoneCameraOutputLease.h", "native/phone-camera/PhoneCameraOutputLease.cpp",
        "native/phone-camera/PhoneCameraOutputPublisher.h", "native/phone-camera/PhoneCameraOutputPublisher.cpp",
        "native/phone-camera/PhoneCameraRuntimeProcess.h", "native/phone-camera/PhoneCameraRuntimeProcess.cpp",
        "native/phone-camera/PhoneCameraRuntimeStatus.h", "native/phone-camera/PhoneCameraRuntimeStatus.cpp",
        "native/phone-camera/PhoneCameraSamples.h", "werkzeuge/phone_audio_parent.py", "PhoneCameraAudioParent.targets"
    });
    private PhoneCameraAudioParentPayload(byte[] image, string hash) { binary = image; Sha256 = hash; }
    internal static PhoneCameraAudioParentPayload? LoadEmbedded()
    {
        var assembly = typeof(PhoneCameraAudioParentPayload).Assembly;
        using var image = assembly.GetManifestResourceStream(Filename);
        using var descriptor = assembly.GetManifestResourceStream("Magnolie.PhoneAudioParent.manifest");
        if (image is null && descriptor is null) return null;
        if (image is null || descriptor is null) throw new InvalidDataException("webcam_audio_parent_resources_incomplete");
        return VerifyEmbeddedSnapshot(ReadBounded(image, 8 * 1024 * 1024), ReadBounded(descriptor, 8192));
    }
    internal static PhoneCameraAudioParentPayload VerifyEmbeddedSnapshot(ReadOnlySpan<byte> image, ReadOnlySpan<byte> descriptor)
    {
        if (image.Length is < 128 or > 8 * 1024 * 1024) throw new InvalidDataException("webcam_audio_parent_size_invalid");
        var bytes = image.ToArray();
        var pe = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(60));
        if (bytes[0] != 'M' || bytes[1] != 'Z' || pe < 64 || pe > bytes.Length - 26 ||
            BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(pe)) != 0x4550 ||
            BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 4)) != 0x8664 ||
            (BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 22)) & 0x2002) != 0x2002 ||
            BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 24)) != 0x20b)
            throw new InvalidDataException("webcam_audio_parent_x64_dll_required");
        if (descriptor.Length is < 1 or > 8192) throw new InvalidDataException("webcam_audio_parent_manifest_invalid");
        var lines = new UTF8Encoding(false, true).GetString(descriptor).Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');
        if (lines.Length != SourceFiles.Count + 4 || lines[^1] != "" || lines[0] != "magnolie-phone-audio-parent-v1" || lines[1] != "architecture=x64")
            throw new InvalidDataException("webcam_audio_parent_manifest_invalid");
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        if (lines[2] != "sha256=" + hash) throw new CryptographicException("webcam_audio_parent_checksum_changed");
        for (int i = 0; i < SourceFiles.Count; ++i)
        {
            var prefix = "source=" + SourceFiles[i] + "|";
            if (!lines[i + 3].StartsWith(prefix, StringComparison.Ordinal) || lines[i + 3].Length != prefix.Length + 64 ||
                lines[i + 3].AsSpan(prefix.Length).ContainsAnyExcept("0123456789abcdef"))
                throw new InvalidDataException("webcam_audio_parent_sources_invalid");
        }
        return new PhoneCameraAudioParentPayload(bytes, hash);
    }
    internal void WriteSnapshot(Stream destination) => destination.Write(binary);
    private static byte[] ReadBounded(Stream stream, int maximum)
    {
        using var output = new MemoryStream(); var buffer = new byte[16384];
        while (true)
        {
            var count = stream.Read(buffer); if (count == 0) return output.ToArray();
            if (output.Length + count > maximum) throw new InvalidDataException("webcam_audio_parent_resource_size_invalid");
            output.Write(buffer, 0, count);
        }
    }
}
