using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NotesOriginalReturnHashTests
{
    internal static void Run()
    {
        var fixture = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "resources", "contact-original-return-hash-v1-vectors.json")))!.AsObject();
        foreach (var vector in fixture["vectors"]!.AsArray().OfType<JsonObject>())
            TestAssert.That(NotesOriginalReturnHash.ContentHash(vector["contact"]!.AsObject()) == vector["sha256"]!.GetValue<string>(),
                "Native Notes content fingerprint mismatch: " + vector["name"]!.GetValue<string>());
        foreach (var text in new[] { "{\"auto\":true}", "{\"vorname\":true}", "{\"vcardName\":\"N:bad\"}",
            "{\"telefone\":[{\"art\":\"privat\",\"wert\":123}]}", "{\"gruppen\":[null]}" })
            TestAssert.Throws<InvalidDataException>(() => NotesOriginalReturnHash.ContentHash(JsonNode.Parse(text)!.AsObject()), "Invalid Notes projection was coerced");
        TestAssert.Throws<InvalidDataException>(() => NotesOriginalReturnHash.ContentHash(new JsonObject { ["vorname"] = "\ud800" }), "Unpaired surrogate became a Notes fingerprint");
        Console.WriteLine("NOTES ORIGINAL HASH PASS shared vectors and strict projection");
    }
}
