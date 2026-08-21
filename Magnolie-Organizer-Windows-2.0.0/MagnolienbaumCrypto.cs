using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Security;

namespace MagnolieOrganizer.Windows;

internal static class MagnolienbaumCrypto
{
    internal static readonly byte[] Context = "magnolienbaum"u8.ToArray();

    internal static (byte[] Private, byte[] Public) GenerateX25519()
    {
        var secret = new X25519PrivateKeyParameters(new SecureRandom());
        return (secret.GetEncoded(), secret.GeneratePublicKey().GetEncoded());
    }

    internal static byte[] X25519(byte[] privateKey, byte[] publicKey)
    {
        if (privateKey.Length != 32 || publicKey.Length != 32)
            throw new CryptographicException("Ein X25519-Schlüssel ist ungültig.");
        var secret = new X25519PrivateKeyParameters(privateKey, 0);
        var shared = new byte[32];
        secret.GenerateSecret(new X25519PublicKeyParameters(publicKey, 0), shared, 0);
        if (shared.All(value => value == 0)) throw new CryptographicException("Der X25519-Schlüssel ist ungültig.");
        return shared;
    }

    internal static byte[] X25519Public(byte[] privateKey)
    {
        if (privateKey.Length != 32) throw new CryptographicException("Ein X25519-Schlüssel ist ungültig.");
        return new X25519PrivateKeyParameters(privateKey, 0).GeneratePublicKey().GetEncoded();
    }

    internal static byte[] HkdfSha256(byte[] input, byte[]? salt, byte[] info, int length)
    {
        if (length is < 1 or > 8160) throw new ArgumentOutOfRangeException(nameof(length));
        using var extract = new HMACSHA256(salt is { Length: > 0 } ? salt : new byte[32]);
        var pseudoRandomKey = extract.ComputeHash(input);
        var result = new byte[length];
        var previous = Array.Empty<byte>();
        var written = 0;
        for (byte counter = 1; written < length; counter++)
        {
            using var expand = new HMACSHA256(pseudoRandomKey);
            var blockInput = new byte[previous.Length + info.Length + 1];
            previous.CopyTo(blockInput, 0);
            info.CopyTo(blockInput, previous.Length);
            blockInput[^1] = counter;
            previous = expand.ComputeHash(blockInput);
            var count = Math.Min(previous.Length, length - written);
            previous.AsSpan(0, count).CopyTo(result.AsSpan(written));
            written += count;
        }
        CryptographicOperations.ZeroMemory(pseudoRandomKey);
        CryptographicOperations.ZeroMemory(previous);
        return result;
    }

    internal static byte[] PartnerKey(byte[] privateKey, byte[] partnerPublic, string ownId, string partnerId)
    {
        var ids = new[] { ownId, partnerId }.Order(StringComparer.Ordinal).ToArray();
        var info = Context.Concat(Encoding.UTF8.GetBytes(ids[0] + "|" + ids[1])).ToArray();
        var shared = X25519(privateKey, partnerPublic);
        try { return HkdfSha256(shared, null, info, 32); }
        finally { CryptographicOperations.ZeroMemory(shared); }
    }

    internal static string Fingerprint(byte[] publicKey)
    {
        var hash = SHA256.HashData(publicKey.Concat(Context).ToArray());
        return string.Join("-", Convert.ToHexString(hash.AsSpan(0, 8)).Chunk(4).Select(chars => new string(chars)));
    }

    internal static string PairingCode(byte[] first, byte[] second)
    {
        var ordered = Compare(first, second) <= 0 ? (first, second) : (second, first);
        var hash = SHA256.HashData(ordered.Item1.Concat(ordered.Item2).Concat(Context).ToArray());
        var text = (BinaryPrimitives.ReadUInt32BigEndian(hash) % 1_000_000).ToString("D6");
        return text[..3] + " " + text[3..];
    }

    internal static byte[] Canonical(JsonNode node)
    {
        var builder = new StringBuilder();
        WriteCanonical(builder, node);
        return Encoding.UTF8.GetBytes(builder.ToString());
    }

    internal static string Base64Url(byte[] value) => Convert.ToBase64String(value).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    internal static byte[] ReadBase64Url(string value, int length)
    {
        if (value.Contains('=') || value.Length > 200) throw new InvalidDataException("Die Paarungsdatei ist beschädigt.");
        try
        {
            var raw = Convert.FromBase64String(value.Replace('-', '+').Replace('_', '/') + new string('=', (4 - value.Length % 4) % 4));
            return raw.Length == length ? raw : throw new InvalidDataException("Die Paarungsdatei ist beschädigt.");
        }
        catch (FormatException error) { throw new InvalidDataException("Die Paarungsdatei ist beschädigt.", error); }
    }

    internal static byte[] Hmac(byte[] key, byte[] prefix, JsonNode value)
    {
        using var hmac = new HMACSHA256(key);
        return hmac.ComputeHash(prefix.Concat(Canonical(value)).ToArray());
    }

    internal static JsonObject EncryptBaum1(byte[] key, string sender, long counter, JsonNode content, byte[]? nonce = null)
    {
        nonce ??= RandomNumberGenerator.GetBytes(12);
        var plain = Encoding.UTF8.GetBytes(content.ToJsonString(new JsonSerializerOptions { WriteIndented = false }));
        var header = Baum1Header(sender, counter);
        var encrypted = new byte[plain.Length];
        var tag = new byte[16];
        using (var aes = new AesGcm(key, 16)) aes.Encrypt(nonce, plain, encrypted, tag, header);
        return new JsonObject { ["magnolie"] = "baum-1", ["von"] = sender, ["zaehler"] = counter,
            ["nonce"] = Convert.ToBase64String(nonce), ["daten"] = Convert.ToBase64String(encrypted.Concat(tag).ToArray()) };
    }

    internal static JsonNode DecryptBaum1(byte[] key, JsonObject envelope, string expectedSender, long lastCounter, out long counter)
    {
        if (envelope["magnolie"]?.GetValue<string>() != "baum-1" || envelope["von"]?.GetValue<string>() != expectedSender)
            throw new CryptographicException("Die Nachricht stammt von einem anderen Zweig.");
        counter = envelope["zaehler"] is JsonValue counterValue && counterValue.TryGetValue<long>(out var longCounter)
            ? longCounter : envelope["zaehler"]?.GetValue<int>() ?? 0;
        if (counter <= lastCounter) throw new CryptographicException("Diese Nachricht wurde bereits empfangen.");
        var nonce = Convert.FromBase64String(envelope["nonce"]?.GetValue<string>() ?? "");
        var combined = Convert.FromBase64String(envelope["daten"]?.GetValue<string>() ?? "");
        if (nonce.Length != 12 || combined.Length < 16) throw new CryptographicException("Die Nachricht ist beschädigt.");
        var header = Baum1Header(expectedSender, counter);
        var plain = new byte[combined.Length - 16];
        using (var aes = new AesGcm(key, 16)) aes.Decrypt(nonce, combined.AsSpan(0, plain.Length), combined.AsSpan(plain.Length), plain, header);
        return JsonNode.Parse(plain) ?? throw new CryptographicException("Der Inhalt ist unlesbar.");
    }

    private static int Compare(byte[] left, byte[] right)
    {
        for (var index = 0; index < Math.Min(left.Length, right.Length); index++)
            if (left[index] != right[index]) return left[index].CompareTo(right[index]);
        return left.Length.CompareTo(right.Length);
    }

    private static byte[] Baum1Header(string sender, long counter) => Encoding.UTF8.GetBytes(
        $"{{\"von\": {JsonSerializer.Serialize(sender)}, \"zaehler\": {counter}}}");

    private static void WriteCanonical(StringBuilder builder, JsonNode? node)
    {
        if (node is null) { builder.Append("null"); return; }
        if (node is JsonObject obj)
        {
            builder.Append('{'); var first = true;
            foreach (var item in obj.OrderBy(item => item.Key, StringComparer.Ordinal))
            {
                if (!first) builder.Append(','); first = false;
                WriteString(builder, item.Key); builder.Append(':'); WriteCanonical(builder, item.Value);
            }
            builder.Append('}'); return;
        }
        if (node is JsonArray array)
        {
            builder.Append('[');
            for (var index = 0; index < array.Count; index++) { if (index > 0) builder.Append(','); WriteCanonical(builder, array[index]); }
            builder.Append(']'); return;
        }
        using var document = JsonDocument.Parse(node.ToJsonString());
        var element = document.RootElement;
        if (element.ValueKind == JsonValueKind.String) WriteString(builder, element.GetString()!);
        else builder.Append(element.GetRawText().ToLowerInvariant());
    }

    private static void WriteString(StringBuilder builder, string value)
    {
        builder.Append('"');
        foreach (var rune in value.EnumerateRunes())
        {
            var number = rune.Value;
            switch (number)
            {
                case 8: builder.Append("\\b"); break; case 9: builder.Append("\\t"); break;
                case 10: builder.Append("\\n"); break; case 12: builder.Append("\\f"); break;
                case 13: builder.Append("\\r"); break; case 34: builder.Append("\\\""); break;
                case 92: builder.Append("\\\\"); break;
                default:
                    if (number is >= 0x20 and <= 0x7e) builder.Append((char)number);
                    else if (number <= 0xffff) builder.Append("\\u").Append(number.ToString("x4"));
                    else
                    {
                        number -= 0x10000;
                        builder.Append("\\u").Append((0xd800 + (number >> 10)).ToString("x4"));
                        builder.Append("\\u").Append((0xdc00 + (number & 0x3ff)).ToString("x4"));
                    }
                    break;
            }
        }
        builder.Append('"');
    }
}
