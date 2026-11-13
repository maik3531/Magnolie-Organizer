using System.Buffers.Binary;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraSourcePayloadTests
{
    private static byte[] Image()
    {
        var bytes = new byte[256]; bytes[0] = (byte)'M'; bytes[1] = (byte)'Z';
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(60), 128);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(128), 0x4550);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(132), 0x8664);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(150), 0x2002);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(152), 0x20b);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(222), 0x4140); return bytes;
    }
    private static byte[] Descriptor(byte[] image) => Encoding.UTF8.GetBytes(
        "magnolie-phone-camera-source-v1\narchitecture=x64\nclassId=" + PhoneCameraSourcePayload.ClassId +
        "\nsha256=" + Convert.ToHexString(SHA256.HashData(image)).ToLowerInvariant() + "\n" +
        string.Join("\n", PhoneCameraSourcePayload.SourceFiles.Select(n => "source=" + n + "|" + new string('a', 64))) + "\n");
    internal static Task ImmutableResourcesAsync()
    {
        var bytes = Image(); var original = bytes.ToArray(); var manifest = Descriptor(bytes);
        var payload = PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(bytes, manifest);
        bytes[0] = 0; manifest[0] = 0;
        using var output = new MemoryStream(); payload.WriteSnapshot(output);
        TestAssert.That(output.ToArray().SequenceEqual(original), "Source retained mutable input");
        TestAssert.That(PhoneCameraSourcePayload.LoadEmbedded() is null, "Host acquired external fallback");
        using var image = new MemoryStream(original); using var descriptor = new MemoryStream(Descriptor(original));
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraSourcePayload.ReadResources(image, null), "Missing descriptor accepted");
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraSourcePayload.ReadResources(null, descriptor), "Missing image accepted");
        using var oversized = new MemoryStream(new byte[8193]);
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraSourcePayload.ReadResources(image, oversized), "Unbounded resource accepted");
        TestAssert.That(PhoneCameraSourcePayload.SourceFiles.Count == 17, "Source catalog changed");
        return Task.CompletedTask;
    }
    internal static Task PeAndDigestAsync()
    {
        var bytes = Image(); var manifest = Descriptor(bytes); bytes[^1] ^= 1;
        TestAssert.Throws<CryptographicException>(() => PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(bytes, manifest), "Changed source accepted");
        foreach (var change in new Action<byte[]>[] { b => b[0] = 0,
            b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), int.MaxValue),
            b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), -1),
            b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), 161),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(132), 0xaa64),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(150), 2),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(150), 0x2000),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(152), 0x10b),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(222), 0x4100),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(222), 0x4040),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(222), 0x140) })
        {
            bytes = Image(); change(bytes);
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(bytes, Descriptor(bytes)), "Invalid role/architecture/protection accepted");
        }
        foreach (var size in new[] { 127, 8 * 1024 * 1024 + 1 })
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(new byte[size], []), "Invalid image bounds accepted");
        return Task.CompletedTask;
    }
    internal static Task StrictDescriptorAsync()
    {
        var bytes = Image(); var text = Encoding.UTF8.GetString(Descriptor(bytes));
        foreach (var invalid in new[] { text.TrimEnd(), text + "path=external.dll\n", text.Replace("architecture=x64", "architecture=arm64", StringComparison.Ordinal),
            text.Replace(PhoneCameraSourcePayload.ClassId, Guid.Empty.ToString(), StringComparison.Ordinal),
            text.Replace("PhoneCameraSamples.h", "foreign.h", StringComparison.Ordinal),
            text.Replace(new string('a', 64), new string('A', 64), StringComparison.Ordinal),
            text.Replace("PhoneCameraSamples.cpp", "PhoneCameraSamples.h", StringComparison.Ordinal) })
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(bytes, Encoding.UTF8.GetBytes(invalid)), "Unbound descriptor accepted");
        TestAssert.Throws<DecoderFallbackException>(() => PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(bytes, new byte[] { 255 }), "Invalid UTF8 accepted");
        var crlf = Encoding.UTF8.GetBytes(text.Replace("\n", "\r\n", StringComparison.Ordinal));
        TestAssert.That(PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(bytes, crlf).Sha256.Length == 64, "Builder CRLF refused");
        return Task.CompletedTask;
    }
    internal static int InspectProduct(string assembly, bool expected)
    {
        using var input = File.OpenRead(assembly); using var pe = new PEReader(input); var metadata = pe.GetMetadataReader();
        var types = metadata.TypeDefinitions.Select(h => metadata.GetTypeDefinition(h)).Select(t => metadata.GetString(t.Name)).ToHashSet();
        TestAssert.That(types.Contains(nameof(PhoneCameraSourcePayload)) == expected, "Source composition mismatch");
        TestAssert.That(types.Contains(nameof(PhoneCameraSetupJournal)) == expected, "Setup journal composition mismatch");
        TestAssert.That(types.Contains(nameof(PhoneCameraCombinedSetupWire)) == expected, "Combined setup wire composition mismatch");
        TestAssert.That(types.Contains(nameof(PhoneCameraSourceRegistration)) == expected, "Source registration composition mismatch");
        TestAssert.That(!metadata.MethodDefinitions.Any(h => {
            var name = metadata.GetString(metadata.GetMethodDefinition(h).Name);
            return name.StartsWith("JournalFixture", StringComparison.Ordinal) || name.StartsWith("CombinedWireFixture", StringComparison.Ordinal);
        }),
            "Product retained arbitrary journal-path factory or writer fault hook");
        var entries = metadata.ManifestResources.Select(h => metadata.GetManifestResource(h)).ToArray();
        byte[] Resource(string name)
        {
            var matches = entries.Where(r => metadata.GetString(r.Name) == name).ToArray();
            TestAssert.That(matches.Length == 1 && matches[0].Implementation.IsNil, "Source resource missing/external");
            var section = pe.GetSectionData(pe.PEHeaders.CorHeader!.ResourcesDirectory.RelativeVirtualAddress);
            var offset = checked((int)matches[0].Offset);
            var length = BinaryPrimitives.ReadInt32LittleEndian(section.GetContent(offset, 4).AsSpan());
            TestAssert.That(length > 0 && length <= 8 * 1024 * 1024, "Invalid source resource length");
            return section.GetContent(offset + 4, length).ToArray();
        }
        string? hash = null;
        if (expected)
        {
            var payload = PhoneCameraSourcePayload.VerifyEmbeddedSnapshot(Resource(PhoneCameraSourcePayload.Filename), Resource("Magnolie.PhoneCameraSource.manifest"));
            hash = payload.Sha256;
            var sibling = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(assembly))!, PhoneCameraSourcePayload.Filename);
            TestAssert.That(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(sibling))).ToLowerInvariant() == hash, "Source sibling changed");
        }
        else TestAssert.That(!entries.Any(r => metadata.GetString(r.Name).StartsWith("Magnolie.PhoneCameraSource.", StringComparison.Ordinal)), "BASE retained source resource");
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, expected, sourceSha256 = hash, mode = "readonly-source-resources-sibling-no-load" }));
        return 0;
    }
}
