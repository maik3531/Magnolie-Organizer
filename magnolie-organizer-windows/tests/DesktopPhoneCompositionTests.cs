using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DesktopPhoneCompositionTests
{
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
        foreach (var name in new[] { "PhoneCameraControlBinding", "PhoneCameraSession", "PhoneCameraMediaChannel", "IPhoneCameraOutputs" })
            TestAssert.That(types.Contains(name) == camera, "Optional camera composition mismatch: " + name);
        TestAssert.That(types.Contains("DeviceFileNativeDirectory") == photos, "Optional photo composition mismatch");
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, camera, photos, sha256 = hash, mode = "readonly-actual-pe-metadata" }));
        return 0;
    }
}
