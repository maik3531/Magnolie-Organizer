using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraAudioRuntimeTests
{
    private static byte[] Fixture()
    {
        var bytes = new byte[256]; bytes[0] = (byte)'M'; bytes[1] = (byte)'Z';
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(60), 128);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(128), 0x4550);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(132), 0x8664); return bytes;
    }
    private static byte[] Descriptor(byte[] bytes) => Encoding.UTF8.GetBytes(
        "magnolie-phone-audio-runtime-v1\narchitecture=x64\nsha256=" + Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() + "\n" +
        string.Join("\n", PhoneCameraAudioRuntimePayload.SourceFiles.Select(name => "source=" + name + "|" + new string('a', 64))) + "\n");
    internal static Task ImmutableResourceAsync()
    {
        var bytes = Fixture(); var original = bytes.ToArray(); var descriptor = Descriptor(bytes);
        var payload = PhoneCameraAudioRuntimePayload.VerifyEmbeddedSnapshot(bytes, descriptor);
        bytes[0] = 0; descriptor[0] = 0;
        using var output = new MemoryStream(); payload.WriteSnapshot(output);
        TestAssert.That(output.ToArray().SequenceEqual(original) && payload.Sha256 == Convert.ToHexString(SHA256.HashData(original)).ToLowerInvariant(), "Mutable input replaced runtime identity");
        TestAssert.That(PhoneCameraAudioRuntimePayload.LoadEmbedded() is null, "Ordinary test host acquired external runtime fallback");
        return Task.CompletedTask;
    }
    internal static Task PeAndDigestAsync()
    {
        var bytes = Fixture(); var descriptor = Descriptor(bytes); bytes[^1] ^= 1;
        TestAssert.Throws<CryptographicException>(() => PhoneCameraAudioRuntimePayload.VerifyEmbeddedSnapshot(bytes, descriptor), "Changed runtime bytes accepted");
        foreach (var change in new Action<byte[]>[] { b => b[0] = 0,
            b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), int.MaxValue),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(132), 0xaa64),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(150), 0x2000) })
        {
            bytes = Fixture(); change(bytes);
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioRuntimePayload.VerifyEmbeddedSnapshot(bytes, Descriptor(bytes)), "Non-x64/executable runtime accepted");
        }
        return Task.CompletedTask;
    }
    internal static Task StrictManifestAsync()
    {
        var bytes = Fixture(); var original = Encoding.UTF8.GetString(Descriptor(bytes));
        foreach (var text in new[] { original + "external=foreign.exe\n", original.TrimEnd(),
            original.Replace("architecture=x64", "architecture=arm64", StringComparison.Ordinal),
            original.Replace("PhoneCameraAudioWorker.h", "foreign.exe", StringComparison.Ordinal),
            original.Replace(new string('a', 64), new string('A', 64), StringComparison.Ordinal) })
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioRuntimePayload.VerifyEmbeddedSnapshot(bytes, Encoding.UTF8.GetBytes(text)), "Unbound runtime manifest accepted");
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioRuntimePayload.VerifyEmbeddedSnapshot(bytes, new byte[8193]), "Unbounded runtime manifest accepted");
        TestAssert.That(PhoneCameraAudioRuntimePayload.Filename == "Magnolie.PhoneAudioWorker.x64.exe", "Runtime filename drifted");
        return Task.CompletedTask;
    }
    internal static int InspectProduct(string assembly, bool expected)
    {
        using var input = File.OpenRead(assembly); using var pe = new PEReader(input);
        var metadata = pe.GetMetadataReader();
        var present = metadata.TypeDefinitions.Select(h => metadata.GetTypeDefinition(h)).Any(t =>
            metadata.GetString(t.Namespace) == "MagnolieOrganizer.Windows" && metadata.GetString(t.Name) == nameof(PhoneCameraAudioRuntimePayload));
        TestAssert.That(present == expected, "Optional runtime type composition mismatch");
        var entries = metadata.ManifestResources.Select(h => metadata.GetManifestResource(h)).ToArray();
        byte[] Resource(string name)
        {
            var matches = entries.Where(r => metadata.GetString(r.Name) == name).ToArray();
            TestAssert.That(matches.Length == 1 && matches[0].Implementation.IsNil, "Runtime resource missing or external");
            var section = pe.GetSectionData(pe.PEHeaders.CorHeader!.ResourcesDirectory.RelativeVirtualAddress);
            var offset = checked((int)matches[0].Offset);
            var size = BinaryPrimitives.ReadInt32LittleEndian(section.GetContent(offset, 4).AsSpan());
            TestAssert.That(size > 0 && size <= 8 * 1024 * 1024, "Invalid runtime resource size");
            return section.GetContent(offset + 4, size).ToArray();
        }
        string? digest = null;
        if (expected)
        {
            var payload = PhoneCameraAudioRuntimePayload.VerifyEmbeddedSnapshot(Resource(PhoneCameraAudioRuntimePayload.Filename), Resource("Magnolie.PhoneAudioWorker.manifest"));
            digest = payload.Sha256;
            var sibling = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(assembly))!, PhoneCameraAudioRuntimePayload.Filename);
            TestAssert.That(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(sibling))).ToLowerInvariant() == digest,
                "Embedded identity differs from copied fixed worker sibling");
        }
        else TestAssert.That(!entries.Any(r => metadata.GetString(r.Name).StartsWith("Magnolie.PhoneAudioWorker.", StringComparison.Ordinal)), "Base composition retained runtime resource");
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, expected, workerSha256 = digest, mode = "readonly-actual-product-resources-and-sibling-no-execution" }));
        return 0;
    }
}
