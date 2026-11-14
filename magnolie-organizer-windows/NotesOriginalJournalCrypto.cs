using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Independent existing native journal key ONLY. The accessor returns an owned
// 32-byte copy; all copies/plain buffers are cleared. No key backend, key creation,
// replacement, source consent, request nonce, filesystem or sender is supplied.
internal sealed class NotesOriginalJournalCrypto
{
    private readonly Func<byte[]?> existingJournalKey;
    internal NotesOriginalJournalCrypto(Func<byte[]?> existingJournalKey)
    { this.existingJournalKey = existingJournalKey ?? throw new ArgumentNullException(nameof(existingJournalKey)); }
    internal enum Purpose { UnconfirmedRequest, SavedAcknowledgment }
    private const int Limit = 1024 * 1024;

    private byte[] Key()
    {
        var key = existingJournalKey() ?? throw new InvalidOperationException("notes_original_existing_journal_key_required");
        if (key.Length == 32) return key;
        CryptographicOperations.ZeroMemory(key);
        throw new CryptographicException("notes_original_existing_journal_key_invalid");
    }
    internal string Identity()
    {
        var key = Key();
        try { return Convert.ToHexString(SHA256.HashData(key)).ToLowerInvariant(); }
        finally { CryptographicOperations.ZeroMemory(key); }
    }
    private static byte[] Aad(Purpose purpose, string id)
    {
        if (!NotesOriginalSchema.Hex(id)) throw new InvalidDataException("notes_original_history_key_invalid");
        var kind = purpose switch { Purpose.UnconfirmedRequest => "unconfirmed-request", Purpose.SavedAcknowledgment => "saved-ack", _ => throw new ArgumentOutOfRangeException(nameof(purpose)) };
        return Encoding.UTF8.GetBytes("Magnolie/notes-original/" + kind + "/windows/v1\0" + id);
    }

    internal string Physical(string nativeBinding, string localId)
    {
        if (!Path.IsPathFullyQualified(nativeBinding) || string.IsNullOrEmpty(localId)) throw new InvalidDataException("notes_original_native_physical_binding_required");
        var key = Key();
        try
        {
            var input = "Magnolie/notes-original/physical-slot/windows/v1\0"u8.ToArray()
                .Concat(NativeBookJson.Canonical(new JsonArray(nativeBinding, localId))).ToArray();
            return Convert.ToHexString(HMACSHA256.HashData(key, input)).ToLowerInvariant();
        }
        finally { CryptographicOperations.ZeroMemory(key); }
    }

    internal string Seal(Purpose purpose, string id, JsonObject record)
    {
        var aad = Aad(purpose, id); var clear = NativeBookJson.Canonical(record);
        try
        {
            if (clear.Length > Limit) throw new InvalidDataException("notes_original_history_record_budget");
            var key = Key();
            try
            {
                var nonce = RandomNumberGenerator.GetBytes(12); var cipher = new byte[clear.Length]; var tag = new byte[16];
                using (var aes = new AesGcm(key, 16)) aes.Encrypt(nonce, clear, cipher, tag, aad);
                return new JsonObject { ["format"] = 1, ["nonce"] = Convert.ToBase64String(nonce), ["cipher"] = Convert.ToBase64String(cipher),
                    ["tag"] = Convert.ToBase64String(tag) }.ToJsonString();
            }
            finally { CryptographicOperations.ZeroMemory(key); }
        }
        finally { CryptographicOperations.ZeroMemory(clear); }
    }

    internal JsonObject Open(Purpose purpose, string id, string encrypted)
    {
        var aad = Aad(purpose, id);
        if (Encoding.UTF8.GetByteCount(encrypted) > 2 * Limit) throw new InvalidDataException("notes_original_history_record_budget");
        var frame = Parse(encrypted); NotesOriginalSchema.Fields(frame, "format", "nonce", "cipher", "tag");
        if (NotesOriginalSchema.Integer(frame, "format") != 1) throw new InvalidDataException("notes_original_history_record_format");
        var nonce = Convert.FromBase64String(NotesOriginalSchema.Text(frame, "nonce")); var cipher = Convert.FromBase64String(NotesOriginalSchema.Text(frame, "cipher"));
        var tag = Convert.FromBase64String(NotesOriginalSchema.Text(frame, "tag"));
        if (nonce.Length != 12 || tag.Length != 16 || cipher.Length > Limit) throw new InvalidDataException("notes_original_history_record_invalid");
        var key = Key(); var clear = new byte[cipher.Length];
        try
        {
            using (var aes = new AesGcm(key, 16)) aes.Decrypt(nonce, cipher, tag, clear, aad);
            var value = Parse(new UTF8Encoding(false, true).GetString(clear));
            if (!NativeBookJson.Canonical(value).AsSpan().SequenceEqual(clear)) throw new InvalidDataException("notes_original_noncanonical_history");
            return value; // Read-only data, deliberately not provider replay/ACK rights.
        }
        finally { CryptographicOperations.ZeroMemory(key); CryptographicOperations.ZeroMemory(clear); }
    }

    internal static JsonObject Parse(string text)
    {
        using var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 32 });
        static void Unique(JsonElement value)
        {
            if (value.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var pair in value.EnumerateObject())
                { if (!names.Add(pair.Name)) throw new InvalidDataException("notes_original_duplicate_history_field"); Unique(pair.Value); }
            }
            else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) Unique(item);
        }
        Unique(document.RootElement);
        return JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("notes_original_history_object_required");
    }
}
