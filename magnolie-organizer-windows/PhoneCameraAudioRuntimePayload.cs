using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

/// <summary>Immutable resource identity for the installed native runtime sibling.
/// Never load a trust manifest/hash/path from configuration or beside the EXE.</summary>
internal sealed class PhoneCameraAudioRuntimePayload
{
    internal const string Filename = "Magnolie.PhoneAudioWorker.x64.exe";
    private readonly byte[] binary;
    internal string Sha256 { get; }
    private static readonly string[] Sources = [
        "native/phone-camera/PhoneCameraAudioWorker.h", "native/phone-camera/PhoneCameraAudioWorker.cpp",
        "native/phone-camera/PhoneCameraAudioRender.h", "native/phone-camera/PhoneCameraAudioRender.cpp",
        "native/phone-camera/PhoneCameraClock.h", "native/phone-camera/PhoneCameraClock.cpp",
        "native/phone-camera/PhoneCameraSamples.h", "native/phone-camera/PhoneCameraSamples.cpp",
        "native/phone-camera/PhoneCameraPipe.h", "native/phone-camera/PhoneCameraPipe.cpp",
        "native/phone-camera/PhoneCameraRelay.h", "native/phone-camera/PhoneCameraRelay.cpp",
        "native/phone-camera/PhoneCameraOutputLease.h", "native/phone-camera/PhoneCameraOutputLease.cpp",
        "native/phone-camera/PhoneCameraOutputPublisher.h", "native/phone-camera/PhoneCameraOutputPublisher.cpp",
        "native/phone-camera/PhoneCameraRuntimeProcess.h", "native/phone-camera/PhoneCameraRuntimeProcess.cpp",
        "native/phone-camera/PhoneCameraRuntimeStatus.h", "native/phone-camera/PhoneCameraRuntimeStatus.cpp",
        "native/phone-camera/PhoneCameraSource.h", "werkzeuge/phone_audio_runtime.py", "PhoneCameraAudioRuntime.targets"
    ];
    internal static IReadOnlyList<string> SourceFiles { get; } = Array.AsReadOnly(Sources);
    private PhoneCameraAudioRuntimePayload(byte[] binary, string hash) { this.binary = binary; Sha256 = hash; }
    internal static PhoneCameraAudioRuntimePayload? LoadEmbedded()
    {
        var assembly = typeof(PhoneCameraAudioRuntimePayload).Assembly;
        using var image = assembly.GetManifestResourceStream(Filename);
        using var descriptor = assembly.GetManifestResourceStream("Magnolie.PhoneAudioWorker.manifest");
        if (image is null && descriptor is null) return null; // Absent means unavailable, never download/stage an alternative.
        if (image is null || descriptor is null) throw new InvalidDataException("webcam_audio_runtime_resources_incomplete");
        return VerifyEmbeddedSnapshot(ReadBounded(image, 8 * 1024 * 1024), ReadBounded(descriptor, 8192));
    }
    internal static PhoneCameraAudioRuntimePayload VerifyEmbeddedSnapshot(ReadOnlySpan<byte> image, ReadOnlySpan<byte> descriptor)
    {
        var bytes = image.ToArray();
        if (bytes.Length is < 128 or > 8 * 1024 * 1024 || bytes[0] != 'M' || bytes[1] != 'Z')
            throw new InvalidDataException("webcam_audio_runtime_pe_invalid");
        var pe = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(60));
        if (pe < 64 || pe > bytes.Length - 26 || BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(pe)) != 0x4550 ||
            BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 4)) != 0x8664 ||
            (BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 22)) & 0x2000) != 0)
            throw new InvalidDataException("webcam_audio_runtime_native_x64_executable_required");
        if (descriptor.Length is < 1 or > 8192) throw new InvalidDataException("webcam_audio_runtime_manifest_invalid");
        var lines = new UTF8Encoding(false, true).GetString(descriptor).Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');
        if (lines.Length != Sources.Length + 4 || lines[^1] != "" || lines[0] != "magnolie-phone-audio-runtime-v1" || lines[1] != "architecture=x64")
            throw new InvalidDataException("webcam_audio_runtime_manifest_invalid");
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        if (lines[2] != "sha256=" + hash) throw new CryptographicException("webcam_audio_runtime_checksum_changed");
        for (int i = 0; i < Sources.Length; ++i)
        {
            var prefix = "source=" + Sources[i] + "|";
            if (!lines[i + 3].StartsWith(prefix, StringComparison.Ordinal) || lines[i + 3].Length != prefix.Length + 64 ||
                lines[i + 3].AsSpan(prefix.Length).ContainsAnyExcept("0123456789abcdef"))
                throw new InvalidDataException("webcam_audio_runtime_source_manifest_invalid");
        }
        return new PhoneCameraAudioRuntimePayload(bytes, hash);
    }
    internal void WriteSnapshot(Stream destination) => destination.Write(binary);
    private static byte[] ReadBounded(Stream stream, int maximum)
    {
        using var output = new MemoryStream(); var buffer = new byte[16384];
        while (true)
        {
            var count = stream.Read(buffer); if (count == 0) break;
            if (output.Length + count > maximum) throw new InvalidDataException("webcam_audio_runtime_resource_size_invalid");
            output.Write(buffer, 0, count);
        }
        return output.ToArray();
    }
}
