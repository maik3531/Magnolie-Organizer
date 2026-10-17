using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record PasswordSource(string Raw, string Plain, bool Encrypted, string StateRevision, string BookRevision)
{
    internal static PasswordSource Read(AtomicStore store, string path, EncryptionService encryption)
    {
        var raw = store.Read(path) ?? throw new FileNotFoundException();
        var encrypted = EncryptionService.IsEncrypted(raw);
        var plain = encrypted ? encryption.DecryptDataWithSession(raw) : raw;
        using var document = JsonDocument.Parse(plain);
        if (document.RootElement.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
        // The existing MCP book token hashes its serialized document as a canonical
        // JSON string, rather than hashing the unquoted document bytes.
        var bookRevision = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(JsonValue.Create(plain)!))).ToLowerInvariant();
        return new(raw, plain, encrypted, BaumSyncSnapshot.Hash(raw), bookRevision);
    }

    internal void Require(string stateRevision, string bookRevision)
    {
        if (StateRevision != stateRevision || BookRevision != bookRevision) throw new InvalidOperationException("mcp_conflict");
    }
}
