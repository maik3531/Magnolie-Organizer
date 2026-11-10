using System.Reflection;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

/// <summary>Only immutable assembly resources may supply elevated helper bytes.
/// An external manifest/path is never a runtime trust source or install grant.</summary>
internal sealed class PhoneCameraAudioHelperPayload
{
    private readonly byte[] binary;
    internal string Sha256 { get; }
    internal const string Filename = "Magnolie.PhoneAudioSetup.x64.exe";
    private static readonly string[] Sources = [
        "native/phone-camera/PhoneCameraCablePackage.h", "native/phone-camera/PhoneCameraCablePackage.cpp",
        "native/phone-camera/PhoneCameraCableSetup.h", "native/phone-camera/PhoneCameraCableSetup.cpp",
        "native/phone-camera/PhoneCameraCableSetupMain.cpp", "werkzeuge/phone_audio_helper.py", "PhoneCameraAudioHelper.targets"
    ];
    private PhoneCameraAudioHelperPayload(byte[] binary, string sha256) { this.binary = binary; Sha256 = sha256; }
    internal static PhoneCameraAudioHelperPayload? LoadEmbedded()
    {
        var assembly = typeof(PhoneCameraAudioHelperPayload).Assembly;
        using var helper = assembly.GetManifestResourceStream("Magnolie.PhoneAudioSetup.x64.exe");
        using var manifest = assembly.GetManifestResourceStream("Magnolie.PhoneAudioSetup.manifest");
        if (helper is null && manifest is null) return null; // Named official manual setup, never download arbitrary code.
        if (helper is null || manifest is null) throw new InvalidDataException("webcam_audio_helper_resources_incomplete");
        return VerifyEmbeddedSnapshot(ReadBounded(helper, 8 * 1024 * 1024), ReadBounded(manifest, 8192));
    }
    internal static PhoneCameraAudioHelperPayload VerifyEmbeddedSnapshot(ReadOnlySpan<byte> executable, ReadOnlySpan<byte> descriptor)
    {
        var bytes = executable.ToArray();
        if (bytes.Length is < 128 or > 8 * 1024 * 1024 || bytes[0] != 'M' || bytes[1] != 'Z')
            throw new InvalidDataException("webcam_audio_helper_pe_invalid");
        var pe = System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(60));
        if (pe < 64 || pe > bytes.Length - 26 || System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(pe)) != 0x4550 ||
            System.Buffers.Binary.BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 4)) != 0x8664 ||
            (System.Buffers.Binary.BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(pe + 22)) & 0x2000) != 0)
            throw new InvalidDataException("webcam_audio_helper_x64_executable_required");
        if (descriptor.Length is < 1 or > 8192) throw new InvalidDataException("webcam_audio_helper_manifest_invalid");
        var text = new UTF8Encoding(false, true).GetString(descriptor);
        var lines = text.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');
        if (lines.Length != Sources.Length + 4 || lines[^1] != "" || lines[0] != "magnolie-phone-audio-helper-v1" || lines[1] != "architecture=x64")
            throw new InvalidDataException("webcam_audio_helper_manifest_invalid");
        var digest = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        if (lines[2] != "sha256=" + digest) throw new CryptographicException("webcam_audio_helper_checksum_changed");
        for (int i = 0; i < Sources.Length; ++i)
        {
            var prefix = "source=" + Sources[i] + "|";
            if (!lines[i + 3].StartsWith(prefix, StringComparison.Ordinal) || lines[i + 3].Length != prefix.Length + 64 ||
                lines[i + 3].AsSpan(prefix.Length).ContainsAnyExcept("0123456789abcdef"))
                throw new InvalidDataException("webcam_audio_helper_source_manifest_invalid");
        }
        return new PhoneCameraAudioHelperPayload(bytes, digest);
    }
    internal void WriteSnapshot(Stream destination) => destination.Write(binary);
    private static byte[] ReadBounded(Stream input, int maximum)
    {
        using var output = new MemoryStream(); var buffer = new byte[16384];
        while (true)
        {
            var read = input.Read(buffer); if (read == 0) break;
            if (output.Length + read > maximum) throw new InvalidDataException("webcam_audio_helper_resource_size_invalid");
            output.Write(buffer, 0, read);
        }
        return output.ToArray();
    }
}
