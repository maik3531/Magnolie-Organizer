using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DesktopPhoneCompositionTests
{
    internal static int HelperReadOnly(string assembly)
    {
        using var input = File.OpenRead(assembly); using var pe = new PEReader(input);
        var metadata = pe.GetMetadataReader();
        byte[] Resource(string name)
        {
            var entries = metadata.ManifestResources.Select(h => metadata.GetManifestResource(h))
                .Where(r => metadata.GetString(r.Name) == name).ToArray();
            TestAssert.That(entries.Length == 1 && entries[0].Implementation.IsNil, "Embedded helper resource missing/external");
            var directory = pe.PEHeaders.CorHeader!.ResourcesDirectory;
            var section = pe.GetSectionData(directory.RelativeVirtualAddress);
            var offset = checked((int)entries[0].Offset);
            var size = System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(section.GetContent(offset, 4).AsSpan());
            TestAssert.That(size > 0 && size <= 8 * 1024 * 1024, "Embedded helper size invalid");
            return section.GetContent(offset + 4, size).ToArray();
        }
        var helper = PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(Resource("Magnolie.PhoneAudioSetup.x64.exe"), Resource("Magnolie.PhoneAudioSetup.manifest"));
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, helperSha256 = helper.Sha256, mode = "readonly-actual-pe-embedded-helper-no-execution" }));
        return 0;
    }
    // Inspect the actual compiled Windows PE without loading WinForms, starting
    // the app, installing anything, or creating a profile/native endpoint.
    internal static int ReadOnly(string assembly, bool camera, bool photos)
    {
        using var input = File.OpenRead(assembly);
        var hash = Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant(); input.Position = 0;
        using var pe = new PEReader(input); TestAssert.That(pe.HasMetadata, "Missing actual Windows metadata");
        var metadata = pe.GetMetadataReader();
        var types = metadata.TypeDefinitions.Select(handle => metadata.GetTypeDefinition(handle))
            .Where(type => metadata.GetString(type.Namespace) == "MagnolieOrganizer.Windows")
            .Select(type => metadata.GetString(type.Name)).ToHashSet(StringComparer.Ordinal);
        TestAssert.That(types.Contains("PhoneCameraControl"), "Always-present reserved protocol boundary omitted");
        foreach (var name in new[] { "PhoneCameraControlBinding", "PhoneCameraSession", "PhoneCameraMediaChannel", "IPhoneCameraOutputs",
            "PhoneCameraAudioSetup", "PhoneCameraAudioHelperPayload", "PhoneCameraAudioStaging", "PhoneCameraAudioSetupUi" })
            TestAssert.That(types.Contains(name) == camera, "Optional camera composition mismatch: " + name);
        if (!camera)
            TestAssert.That(!metadata.ManifestResources.Any(h => metadata.GetString(metadata.GetManifestResource(h).Name).StartsWith("Magnolie.PhoneAudioSetup.", StringComparison.Ordinal)),
                "Excluded camera composition retained a privileged helper resource");
        TestAssert.That(types.Contains("DeviceFileNativeDirectory") == photos, "Optional photo composition mismatch");
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, camera, photos, sha256 = hash, mode = "readonly-actual-pe-metadata" }));
        return 0;
    }
}
