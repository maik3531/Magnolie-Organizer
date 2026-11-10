using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraAudioHelperTests
{
    // A non-executable header fixture exercises validation only; it is never
    // written, selected as a product fallback, started or elevated.
    private static byte[] Fixture()
    {
        var bytes = new byte[256]; bytes[0] = (byte)'M'; bytes[1] = (byte)'Z';
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(60), 128);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(128), 0x4550);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(132), 0x8664);
        return bytes;
    }
    private static byte[] Descriptor(byte[] bytes)
    {
        string[] sources = [
            "native/phone-camera/PhoneCameraCablePackage.h", "native/phone-camera/PhoneCameraCablePackage.cpp",
            "native/phone-camera/PhoneCameraCableSetup.h", "native/phone-camera/PhoneCameraCableSetup.cpp",
            "native/phone-camera/PhoneCameraCableSetupMain.cpp", "werkzeuge/phone_audio_helper.py", "PhoneCameraAudioHelper.targets"
        ];
        return Encoding.UTF8.GetBytes("magnolie-phone-audio-helper-v1\narchitecture=x64\nsha256=" +
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() + "\n" +
            string.Join("\n", sources.Select(s => "source=" + s + "|" + new string('a', 64))) + "\n");
    }
    internal static Task ImmutableSnapshotAsync()
    {
        var bytes = Fixture(); var expected = bytes.ToArray();
        var payload = PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(bytes, Descriptor(bytes)); bytes[0] = 0;
        using var saved = new MemoryStream(); payload.WriteSnapshot(saved);
        TestAssert.That(saved.ToArray().SequenceEqual(expected) && payload.Sha256 == Convert.ToHexString(SHA256.HashData(expected)).ToLowerInvariant(),
            "Caller mutation replaced verified helper snapshot");
        // Ordinary test composition intentionally has no product binary.
        TestAssert.That(PhoneCameraAudioHelperPayload.LoadEmbedded() is null, "Missing embedded helper acquired an external fallback");
        return Task.CompletedTask;
    }
    internal static Task TamperAndPeAsync()
    {
        var bytes = Fixture(); var manifest = Descriptor(bytes); bytes[^1] ^= 1;
        TestAssert.Throws<CryptographicException>(() => PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(bytes, manifest), "Helper digest mismatch admitted");
        foreach (var change in new Action<byte[]>[] {
            b => b[0] = 0, b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), int.MaxValue),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(132), 0xaa64),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(150), 0x2000) })
        {
            bytes = Fixture(); change(bytes);
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(bytes, Descriptor(bytes)), "Invalid PE/machine/DLL helper admitted");
        }
        return Task.CompletedTask;
    }
    internal static Task StrictSourceDescriptorAsync()
    {
        var bytes = Fixture(); var original = Encoding.UTF8.GetString(Descriptor(bytes));
        foreach (var text in new[] { original + "external=https://foreign.invalid/helper.exe\n", original.TrimEnd(),
            original.Replace("architecture=x64", "architecture=arm64", StringComparison.Ordinal),
            original.Replace("source=native/phone-camera/PhoneCameraCableSetup.h", "source=foreign.exe", StringComparison.Ordinal),
            original.Replace(new string('a', 64), new string('A', 64), StringComparison.Ordinal) })
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(bytes, Encoding.UTF8.GetBytes(text)), "Malformed/unbound source descriptor admitted");
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(bytes, new byte[8193]), "Unbounded helper descriptor admitted");
        return Task.CompletedTask;
    }
}
