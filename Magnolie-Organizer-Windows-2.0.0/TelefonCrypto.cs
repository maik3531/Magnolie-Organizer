using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Security;

namespace MagnolieOrganizer.Windows;

internal static class TelefonCrypto
{
    internal const string Protocol = "magnolie-phone/1";

    internal static (byte[] Private, byte[] Public) GenerateX25519()
    {
        var secret = new X25519PrivateKeyParameters(new SecureRandom());
        return (secret.GetEncoded(), secret.GeneratePublicKey().GetEncoded());
    }

    internal static byte[] X25519(byte[] privateKey, byte[] publicKey)
    {
        if (privateKey.Length != 32 || publicKey.Length != 32) throw new CryptographicException("Ungültiger X25519-Schlüssel.");
        var result = new byte[32];
        new X25519PrivateKeyParameters(privateKey, 0).GenerateSecret(new X25519PublicKeyParameters(publicKey, 0), result, 0);
        if (result.All(value => value == 0)) throw new CryptographicException("Ungültiger X25519-Schlüssel.");
        return result;
    }

    internal static byte[] X25519Public(byte[] privateKey)
    {
        if (privateKey.Length != 32) throw new CryptographicException("Ungültiger X25519-Schlüssel.");
        return new X25519PrivateKeyParameters(privateKey, 0).GeneratePublicKey().GetEncoded();
    }

    internal static byte[] Hkdf(byte[] input, byte[]? salt, byte[] info, int length)
    {
        using var extract = new HMACSHA256(salt is { Length: > 0 } ? salt : new byte[32]);
        var prk = extract.ComputeHash(input);
        var result = new byte[length];
        var previous = Array.Empty<byte>();
        var offset = 0;
        for (byte counter = 1; offset < length; counter++)
        {
            using var expand = new HMACSHA256(prk);
            previous = expand.ComputeHash(previous.Concat(info).Append(counter).ToArray());
            var count = Math.Min(previous.Length, length - offset);
            previous.AsSpan(0, count).CopyTo(result.AsSpan(offset));
            offset += count;
        }
        CryptographicOperations.ZeroMemory(prk);
        CryptographicOperations.ZeroMemory(previous);
        return result;
    }

    internal static byte[] Canonical(JsonNode node)
    {
        var builder = new StringBuilder();
        WriteCanonical(builder, node);
        return Encoding.UTF8.GetBytes(builder.ToString());
    }

    internal static PairingSecrets Pairing(byte[] ownEphemeralPrivate, byte[] peerEphemeralPublic,
        byte[] ownStaticPrivate, byte[] peerStaticPublic, JsonObject init, JsonObject response)
    {
        var transcript = SHA256.HashData(Canonical(init).Concat(Canonical(response)).ToArray());
        var ephemeral = X25519(ownEphemeralPrivate, peerEphemeralPublic);
        var staticallyShared = X25519(ownStaticPrivate, peerStaticPublic);
        var input = ephemeral.Concat(staticallyShared).ToArray();
        var salt = SHA256.HashData(Label("magnolie-phone-pair-v1/salt\0").Concat(transcript).ToArray());
        var key = Hkdf(input, salt, Label("magnolie-phone-pair-v1/key\0").Concat(transcript).ToArray(), 32);
        using var hmac = new HMACSHA256(key);
        var hash = hmac.ComputeHash(Label("magnolie-phone-pair-v1/code\0").Concat(transcript).ToArray());
        var digits = (BinaryPrimitives.ReadUInt32BigEndian(hash) % 1_000_000).ToString("D6");
        CryptographicOperations.ZeroMemory(ephemeral);
        CryptographicOperations.ZeroMemory(staticallyShared);
        CryptographicOperations.ZeroMemory(input);
        return new PairingSecrets(transcript, key, digits[..3] + " " + digits[3..]);
    }

    internal static byte[] PairProof(byte[] key, string phase, string side, byte[] transcript)
    {
        using var hmac = new HMACSHA256(key);
        return hmac.ComputeHash(Label($"magnolie-phone-pair-v1/{phase}\0").Concat(Encoding.UTF8.GetBytes(side)).Concat(transcript).ToArray());
    }

    internal static string Fingerprint(byte[] publicKey)
    {
        var hash = SHA256.HashData(Label("magnolie-phone-fingerprint-v1\0").Concat(publicKey).ToArray());
        return string.Join("-", Convert.ToHexString(hash.AsSpan(0, 8)).Chunk(4).Select(value => new string(value)));
    }

    internal static byte[] StrictBase64(JsonObject value, string name, int length)
    {
        try
        {
            var text = value[name]?.GetValue<string>() ?? "";
            var bytes = Convert.FromBase64String(text);
            if (bytes.Length != length || Convert.ToBase64String(bytes) != text) throw new FormatException();
            return bytes;
        }
        catch (Exception error) when (error is FormatException or InvalidOperationException)
        { throw new InvalidDataException($"Das Feld {name} ist ungültig.", error); }
    }

    private static byte[] Label(string value) => Encoding.UTF8.GetBytes(value);

    private static void WriteCanonical(StringBuilder builder, JsonNode? node)
    {
        if (node is null) { builder.Append("null"); return; }
        if (node is JsonObject obj)
        {
            builder.Append('{'); var first = true;
            foreach (var item in obj.OrderBy(item => item.Key, UnicodeCodePointComparer.Instance))
            {
                if (!first) builder.Append(','); first = false;
                WriteString(builder, item.Key); builder.Append(':'); WriteCanonical(builder, item.Value);
            }
            builder.Append('}'); return;
        }
        if (node is JsonArray array)
        {
            builder.Append('[');
            for (var index = 0; index < array.Count; index++)
            { if (index > 0) builder.Append(','); WriteCanonical(builder, array[index]); }
            builder.Append(']'); return;
        }
        if (node is JsonValue value && value.TryGetValue<string>(out var text))
        { WriteString(builder, text); return; }
        using var document = JsonDocument.Parse(node.ToJsonString());
        var element = document.RootElement;
        if (element.ValueKind == JsonValueKind.Number && !element.TryGetInt64(out _))
            throw new InvalidDataException("Bruchzahlen sind im Telefonprotokoll nicht erlaubt.");
        builder.Append(element.GetRawText());
    }

    private static void WriteString(StringBuilder builder, string value)
    {
        builder.Append('"');
        foreach (var rune in value.EnumerateRunes())
        {
            switch (rune.Value)
            {
                case '"': builder.Append("\\\""); break;
                case '\\': builder.Append("\\\\"); break;
                case '\b': builder.Append("\\b"); break;
                case '\f': builder.Append("\\f"); break;
                case '\n': builder.Append("\\n"); break;
                case '\r': builder.Append("\\r"); break;
                case '\t': builder.Append("\\t"); break;
                case < 0x20: builder.Append("\\u").Append(rune.Value.ToString("x4")); break;
                default: builder.Append(rune); break;
            }
        }
        builder.Append('"');
    }

    private sealed class UnicodeCodePointComparer : IComparer<string>
    {
        internal static readonly UnicodeCodePointComparer Instance = new();

        public int Compare(string? left, string? right)
        {
            if (ReferenceEquals(left, right)) return 0;
            if (left is null) return -1;
            if (right is null) return 1;
            var leftRunes = left.EnumerateRunes().GetEnumerator();
            var rightRunes = right.EnumerateRunes().GetEnumerator();
            while (true)
            {
                var hasLeft = leftRunes.MoveNext();
                var hasRight = rightRunes.MoveNext();
                if (!hasLeft || !hasRight) return hasLeft.CompareTo(hasRight);
                var comparison = leftRunes.Current.Value.CompareTo(rightRunes.Current.Value);
                if (comparison != 0) return comparison;
            }
        }
    }
}

internal sealed record PairingSecrets(byte[] Transcript, byte[] Key, string Code) : IDisposable
{
    public void Dispose() { CryptographicOperations.ZeroMemory(Transcript); CryptographicOperations.ZeroMemory(Key); }
}
