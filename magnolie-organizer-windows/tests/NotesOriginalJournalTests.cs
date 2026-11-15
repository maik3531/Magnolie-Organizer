using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NotesOriginalJournalTests
{
    internal static void Run(string root)
    {
        Crypto();
        Layout(Path.Combine(root, "layout"));
        Console.WriteLine("Notes independent journal primitives: crypto isolation/tamper/canonical/key clearing and narrow private layout passed (no send authority).");
    }

    private static void Crypto()
    {
        const string id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        var copies = new List<byte[]>();
        byte[] Existing()
        { var value = Enumerable.Repeat((byte)42, 32).ToArray(); copies.Add(value); return value; }
        var crypto = new NotesOriginalJournalCrypto(Existing);
        var payload = new JsonObject { ["synthetic"] = "private-only", ["nested"] = new JsonArray(1, "🌱") };
        var frame = crypto.Seal(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, payload);
        TestAssert.That(!frame.Contains("private-only", StringComparison.Ordinal) &&
            JsonNode.DeepEquals(payload, crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, frame)), "History did not encrypt/roundtrip");
        TestAssert.That(crypto.Identity() == Convert.ToHexString(SHA256.HashData(Enumerable.Repeat((byte)42, 32).ToArray())).ToLowerInvariant(), "Existing journal identity changed");
        var binding = Path.GetFullPath("synthetic-native-book");
        var physical = crypto.Physical(binding, "contact");
        TestAssert.That(physical == crypto.Physical(binding, "contact") && physical != crypto.Physical(binding, "other-contact") &&
            physical != crypto.Physical(binding + "-other", "contact"), "Physical HMAC lost exact binding");
        TestAssert.Throws<CryptographicException>(() => crypto.Open(NotesOriginalJournalCrypto.Purpose.SavedAcknowledgment, id, frame), "Request became saved ACK");
        TestAssert.Throws<CryptographicException>(() => crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, new string('b', 64), frame), "Record ID substitution accepted");
        var other = new NotesOriginalJournalCrypto(() => Enumerable.Repeat((byte)43, 32).ToArray());
        TestAssert.Throws<CryptographicException>(() => other.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, frame), "Replacement key opened history");
        foreach (var field in new[] { "nonce", "cipher", "tag" })
        {
            var damaged = JsonNode.Parse(frame)!.AsObject(); var bytes = Convert.FromBase64String(damaged[field]!.GetValue<string>());
            bytes[0] ^= 1; damaged[field] = Convert.ToBase64String(bytes);
            TestAssert.Throws<CryptographicException>(() => crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, damaged.ToJsonString()), "Tamper accepted: " + field);
        }
        var duplicate = frame.Insert(1, "\"format\":1,");
        TestAssert.Throws<InvalidDataException>(() => crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, duplicate), "Duplicate envelope accepted");
        string Raw(string clear)
        {
            var key = Enumerable.Repeat((byte)42, 32).ToArray(); var plain = Encoding.UTF8.GetBytes(clear);
            try
            {
                var nonce = RandomNumberGenerator.GetBytes(12); var cipher = new byte[plain.Length]; var tag = new byte[16];
                using (var aes = new AesGcm(key, 16)) aes.Encrypt(nonce, plain, cipher, tag,
                    Encoding.UTF8.GetBytes("Magnolie/notes-original/unconfirmed-request/windows/v1\0" + id));
                return new JsonObject { ["format"] = 1, ["nonce"] = Convert.ToBase64String(nonce), ["cipher"] = Convert.ToBase64String(cipher), ["tag"] = Convert.ToBase64String(tag) }.ToJsonString();
            }
            finally { CryptographicOperations.ZeroMemory(key); CryptographicOperations.ZeroMemory(plain); }
        }
        foreach (var clear in new[] { "{ \"value\":1}", "{\"nested\":{\"x\":1,\"x\":2}}", "[]" })
            TestAssert.Throws<InvalidDataException>(() => crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, Raw(clear)), "Noncanonical/duplicate/nonobject plaintext accepted");
        TestAssert.Throws<InvalidOperationException>(() => new NotesOriginalJournalCrypto(() => null).Identity(), "Missing key silently created");
        var badKey = new byte[] { 1, 2, 3 };
        TestAssert.Throws<CryptographicException>(() => new NotesOriginalJournalCrypto(() => badKey).Identity(), "Invalid key accepted");
        TestAssert.That(badKey.All(value => value == 0) && copies.All(value => value.All(item => item == 0)), "Owned key copies not cleared on success/failure");
        TestAssert.Throws<ArgumentNullException>(() => new NotesOriginalJournalCrypto(null!), "Missing accessor accepted");
        TestAssert.Throws<InvalidDataException>(() => crypto.Seal(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, "../wrong", payload), "Invalid record ID accepted");
        TestAssert.Throws<InvalidDataException>(() => crypto.Seal(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id,
            new JsonObject { ["large"] = new string('x', 1024 * 1024) }), "Plaintext budget ignored");
        TestAssert.Throws<InvalidDataException>(() => crypto.Open(NotesOriginalJournalCrypto.Purpose.UnconfirmedRequest, id, new string('x', 2 * 1024 * 1024 + 1)), "Envelope budget ignored");
    }

    private static void Layout(string root)
    {
        var boundary = new ContactSourcePrivateFiles(root, controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
        TestAssert.That(boundary.Open() is null && !Directory.Exists(root), "Journal read created root");
        var leaf = "r-" + new string('a', 64) + ".json";
        using (var session = boundary.Open(create: true)!)
        {
            TestAssert.That(session.RootCreated, "New native root not marked");
            foreach (var name in new[] { ".journal-key", leaf, "p-" + new string('b', 64) + ".json", "a-" + new string('c', 64) + ".json" })
            { session.Write(name, "synthetic", 1024); TestAssert.That(session.Read(name, 1024) == "synthetic", "Narrow journal leaf failed"); }
            foreach (var name in new[] { "approval.json", ".key.dpapi", ".transaction", ".lock", "../" + leaf, "x-" + new string('a', 64) + ".json",
                "r-" + new string('A', 64) + ".json", leaf + ".bak", "r-" + new string('a', 63) + ".json" })
            {
                TestAssert.Throws<ArgumentException>(() => session.Read(name, 10), "Unknown journal read admitted");
                TestAssert.Throws<ArgumentException>(() => session.Write(name, "x", 10), "Unknown journal write admitted");
                TestAssert.Throws<ArgumentException>(() => session.Delete(name), "Unknown journal delete admitted");
            }
            var text = new string('x', 300 * 1024); session.Write(leaf, text, 2 * 1024 * 1024);
            TestAssert.That(session.Read(leaf, 2 * 1024 * 1024) == text, "Journal-only extended budget failed");
            TestAssert.Throws<ArgumentOutOfRangeException>(() => session.Read(leaf, 2 * 1024 * 1024 + 1), "Journal read limit expanded");
        }
        using (var again = boundary.Open()!) TestAssert.That(!again.RootCreated, "Existing root claimed fresh initialization");
        var consent = new ContactSourcePrivateFiles(root + "-consent", controlledUnix: !OperatingSystem.IsWindows());
        using (var session = consent.Open(create: true)!)
        {
            TestAssert.Throws<ArgumentException>(() => session.Write(leaf, "x", 10), "Consent layout admitted journal leaves");
            TestAssert.Throws<ArgumentOutOfRangeException>(() => session.Write("approval.json", "x", 300 * 1024), "Default consent limit changed");
        }
    }
}
