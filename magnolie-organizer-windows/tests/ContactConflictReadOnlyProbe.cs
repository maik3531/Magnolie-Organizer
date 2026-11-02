using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Existing CoreTests diagnostic lane only. Never invokes a provider, GUI or save path.
internal static class ContactConflictReadOnlyProbe
{
    internal static JsonObject Analyze(JsonObject book)
    {
        var rows = new JsonArray(); var count = 0;
        foreach (var contact in (book["kontakte"] as JsonArray ?? []).OfType<JsonObject>())
        {
            if (contact["syncKonflikte"] is not JsonObject conflicts) continue;
            foreach (var pair in conflicts)
            {
                count++;
                if (rows.Count >= 256 || pair.Value?["kontakt"] is not JsonObject remote) continue;
                var localProjection = ContactFields.ConflictProjection(contact);
                var remoteProjection = ContactFields.ConflictProjection(remote);
                // Only allow schema field names, never source IDs, names, values or hashes.
                var fields = ContactFields.Names.Append("gruppen").Where(name =>
                    !JsonNode.DeepEquals(localProjection[name], remoteProjection[name])).Distinct().Order(StringComparer.Ordinal);
                var mapping = ContactFields.Source(contact, pair.Key);
                rows.Add(new JsonObject
                {
                    ["localDirty"] = ContactFields.Dirty(contact, mapping, remote),
                    ["baselineKnown"] = mapping?["inhaltFormat"]?.GetValue<string>() == "windows-contact-2" &&
                        !string.IsNullOrEmpty(mapping?["inhaltSha256"]?.GetValue<string>()),
                    ["semanticEqual"] = JsonNode.DeepEquals(localProjection, remoteProjection),
                    ["differentFields"] = new JsonArray(fields.Select(name => JsonValue.Create(name)).ToArray()),
                    ["groupsEqual"] = JsonNode.DeepEquals(localProjection["gruppen"], remoteProjection["gruppen"]),
                    ["hasPhoneGroupIntent"] = contact["telefonGruppenAenderung"] is JsonObject
                });
            }
        }
        return new JsonObject { ["version"] = 1, ["productWrites"] = false, ["conflictCount"] = count,
            ["truncated"] = count > rows.Count, ["conflicts"] = rows };
    }

    internal static async Task<int> RunAsync(string receipt)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (File.Exists(receipt)) throw new IOException("Diagnostic receipt already exists.");
        var path = new WindowsPaths().Data;
        if (new FileInfo(path).Length > 64 * 1024 * 1024) throw new InvalidDataException("Diagnostic size bound exceeded.");
        var bytes = await File.ReadAllBytesAsync(path);
        JsonObject output;
        try
        {
            var text = System.Text.Encoding.UTF8.GetString(bytes);
            if (EncryptionService.IsEncrypted(text)) throw new InvalidOperationException("Existing unlocked product session required.");
            output = Analyze(JsonNode.Parse(text)!.AsObject());
            var current = await File.ReadAllBytesAsync(path);
            try { output["sourceUnchangedDuringRead"] = CryptographicOperations.FixedTimeEquals(SHA256.HashData(bytes), SHA256.HashData(current)); }
            finally { CryptographicOperations.ZeroMemory(current); }
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
        using var file = new FileStream(receipt, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        await System.Text.Json.JsonSerializer.SerializeAsync(file, output);
        Console.WriteLine("CONTACT-CONFLICT-READONLY-METADATA-OK");
        return 0;
    }

    internal static void VerifyPrivacy()
    {
        var remote = new JsonObject { ["vorname"] = "Private remote name", ["vcardRoundtrip"] = new JsonArray("CATEGORIES:Private remote group") };
        var local = new JsonObject { ["id"] = "private-contact-id", ["vorname"] = "Private local name",
            ["vcardRoundtrip"] = new JsonArray("CATEGORIES:Private local group") };
        ContactFields.SetSource(local, "private-source-id", new RemoteContact("private-remote-id", "private-etag", 100, local.DeepClone().AsObject(), true));
        local["syncKonflikte"] = new JsonObject { ["private-source-id"] = new JsonObject { ["kontakt"] = remote } };
        var book = new JsonObject { ["kontakte"] = new JsonArray(local) }; var before = book.ToJsonString();
        var result = Analyze(book); var text = result.ToJsonString();
        TestAssert.That(book.ToJsonString() == before, "Readonly diagnostic changed its input.");
        TestAssert.That(!text.Contains("Private", StringComparison.OrdinalIgnoreCase) && !text.Contains("private-"), "Diagnostic leaked contact values or identities.");
        TestAssert.That(result["conflictCount"]!.GetValue<int>() == 1 && result["conflicts"]![0]!["localDirty"]!.GetValue<bool>() == false,
            "Known unchanged local baseline was diagnosed as dirty.");
        TestAssert.That(result["conflicts"]![0]!["groupsEqual"]!.GetValue<bool>() == false, "Changed group set was missed.");
    }
}
