using System.Buffers.Binary;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraAudioParentPayloadTests
{
    private static byte[] Image()
    {
        var bytes = new byte[256]; bytes[0] = (byte)'M'; bytes[1] = (byte)'Z';
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(60), 128);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(128), 0x4550);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(132), 0x8664);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(150), 0x2002);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(152), 0x20b); return bytes;
    }
    private static byte[] Descriptor(byte[] image) => Encoding.UTF8.GetBytes(
        "magnolie-phone-audio-parent-v1\narchitecture=x64\nsha256=" + Convert.ToHexString(SHA256.HashData(image)).ToLowerInvariant() + "\n" +
        string.Join("\n", PhoneCameraAudioParentPayload.SourceFiles.Select(n => "source=" + n + "|" + new string('a', 64))) + "\n");
    internal static Task ImmutableSnapshotAsync()
    {
        var bytes = Image(); var original = bytes.ToArray(); var manifest = Descriptor(bytes);
        var payload = PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(bytes, manifest);
        bytes[0] = 0; manifest[0] = 0;
        using var output = new MemoryStream(); payload.WriteSnapshot(output);
        TestAssert.That(output.ToArray().SequenceEqual(original) && payload.Sha256 == Convert.ToHexString(SHA256.HashData(original)).ToLowerInvariant(), "Parent identity retained mutable caller storage");
        TestAssert.That(PhoneCameraAudioParentPayload.LoadEmbedded() is null, "Ordinary host acquired an external parent DLL fallback");
        TestAssert.That(PhoneCameraAudioParentPayload.Filename == "Magnolie.PhoneAudioParent.x64.dll", "Fixed parent filename changed");
        return Task.CompletedTask;
    }
    internal static Task PeAndDigestAsync()
    {
        var bytes = Image(); var manifest = Descriptor(bytes); bytes[^1] ^= 1;
        TestAssert.Throws<CryptographicException>(() => PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(bytes, manifest), "Changed DLL accepted");
        foreach (var change in new Action<byte[]>[] { b => b[0] = 0,
            b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), int.MaxValue),
            b => BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(60), -1),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(132), 0xaa64),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(150), 2),
            b => BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(152), 0x10b) })
        {
            bytes = Image(); change(bytes);
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(bytes, Descriptor(bytes)), "Not x64 PE32+ DLL accepted");
        }
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(new byte[127], []), "Truncated DLL accepted");
        return Task.CompletedTask;
    }
    internal static Task StrictDescriptorAsync()
    {
        var bytes = Image(); var text = Encoding.UTF8.GetString(Descriptor(bytes));
        foreach (var invalid in new[] { text.TrimEnd(), text + "path=external.dll\n", text.Replace("architecture=x64", "architecture=arm64", StringComparison.Ordinal),
            text.Replace("PhoneCameraAudioParent.h", "foreign.h", StringComparison.Ordinal), text.Replace(new string('a', 64), new string('A', 64), StringComparison.Ordinal) })
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(bytes, Encoding.UTF8.GetBytes(invalid)), "Unbound descriptor accepted");
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(bytes, new byte[8193]), "Unbounded descriptor accepted");
        return Task.CompletedTask;
    }
    internal static int InspectProduct(string assembly, bool expected)
    {
        using var input = File.OpenRead(assembly); using var pe = new PEReader(input); var metadata = pe.GetMetadataReader();
        var types = metadata.TypeDefinitions.Select(h => metadata.GetTypeDefinition(h)).Select(t => metadata.GetString(t.Name)).ToHashSet();
        TestAssert.That(types.Contains(nameof(PhoneCameraAudioParentPayload)) == expected, "Parent composition mismatch");
        TestAssert.That(types.Contains("PhoneCameraAudioParentModule") == expected, "Optional parent loader composition mismatch");
        TestAssert.That(types.Contains("PhoneCameraAudioParentRuntime") == expected && !types.Contains("DiagnosticPlan"), "Runtime composition retained diagnostic call table");
        TestAssert.That(!metadata.MethodDefinitions.Any(h => metadata.GetString(metadata.GetMethodDefinition(h).Name) == "ProbeHeldPath"),
            "Product retained test-only held-path access");
        TestAssert.That(!metadata.MethodDefinitions.Any(h => metadata.GetString(metadata.GetMethodDefinition(h).Name) is "CreateDiagnostic" or "ReleaseStoppedDiagnosticFixture"),
            "Product retained private runtime test factory");
        TestAssert.That(!types.Contains("PhoneCameraPublicationProbe") && !metadata.FieldDefinitions.Any(h =>
            metadata.GetString(metadata.GetFieldDefinition(h).Name) == "WebcamWriterWaitProbe"), "Product retained test-only publication observer");
        var entries = metadata.ManifestResources.Select(h => metadata.GetManifestResource(h)).ToArray();
        byte[] Resource(string name)
        {
            var matches = entries.Where(r => metadata.GetString(r.Name) == name).ToArray();
            TestAssert.That(matches.Length == 1 && matches[0].Implementation.IsNil, "Parent resource missing/external");
            var section = pe.GetSectionData(pe.PEHeaders.CorHeader!.ResourcesDirectory.RelativeVirtualAddress);
            var offset = checked((int)matches[0].Offset);
            var length = BinaryPrimitives.ReadInt32LittleEndian(section.GetContent(offset, 4).AsSpan());
            TestAssert.That(length > 0 && length <= 8 * 1024 * 1024, "Invalid parent resource length");
            return section.GetContent(offset + 4, length).ToArray();
        }
        string? hash = null;
        if (expected)
        {
            var payload = PhoneCameraAudioParentPayload.VerifyEmbeddedSnapshot(Resource(PhoneCameraAudioParentPayload.Filename), Resource("Magnolie.PhoneAudioParent.manifest"));
            hash = payload.Sha256;
            var sibling = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(assembly))!, PhoneCameraAudioParentPayload.Filename);
            TestAssert.That(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(sibling))).ToLowerInvariant() == hash, "Parent sibling differs from embedded identity");
        }
        else TestAssert.That(!entries.Any(r => metadata.GetString(r.Name).StartsWith("Magnolie.PhoneAudioParent.", StringComparison.Ordinal)), "BASE retained parent resource");
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, expected, parentSha256 = hash, mode = "readonly-parent-resources-sibling-no-load", noPublicationTestObserver = true }));
        return 0;
    }
}
