using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class MagnolienbaumFsSession : IDisposable
{
    internal MagnolienbaumFsSession(string sid, byte[] transcript, byte[] encryptionKey, byte[] acknowledgementKey)
    {
        Sid = sid; Transcript = transcript; EncryptionKey = encryptionKey; AcknowledgementKey = acknowledgementKey;
    }

    internal string Sid { get; }
    internal byte[] Transcript { get; }
    internal byte[] EncryptionKey { get; }
    internal byte[] AcknowledgementKey { get; }
    internal bool Consumed { get; set; }

    public void Dispose()
    {
        CryptographicOperations.ZeroMemory(EncryptionKey);
        CryptographicOperations.ZeroMemory(AcknowledgementKey);
        CryptographicOperations.ZeroMemory(Transcript);
    }
}

internal sealed record MagnolienbaumFsStart(JsonObject Message, byte[] EphemeralPrivate) : IDisposable
{
    public void Dispose() => CryptographicOperations.ZeroMemory(EphemeralPrivate);
}

internal static class MagnolienbaumFs1
{
    private static readonly byte[] AuthInfo = "magnolienbaum\0baum-fs1\0auth"u8.ToArray();
    private static readonly byte[] KeyInfoPrefix = "magnolienbaum\0baum-fs1\0keys\0"u8.ToArray();
    private static readonly byte[] DataAadPrefix = "magnolienbaum\0baum-fs1\0data\0"u8.ToArray();

    internal static byte[] AuthKey(JsonObject state, JsonObject partner)
    {
        var staticallyShared = MagnolienbaumCrypto.PartnerKey(
            Convert.FromBase64String(Text(state, "geheim")), Convert.FromBase64String(Text(partner, "oeffentlich")),
            Text(state, "kennung"), Text(partner, "kennung"));
        try { return MagnolienbaumCrypto.HkdfSha256(staticallyShared, null, AuthInfo, 32); }
        finally { CryptographicOperations.ZeroMemory(staticallyShared); }
    }

    internal static MagnolienbaumFsStart BuildStart(JsonObject state, JsonObject partner, byte[]? sid = null, byte[]? ephemeralPrivate = null)
    {
        sid ??= RandomNumberGenerator.GetBytes(16);
        ephemeralPrivate ??= MagnolienbaumCrypto.GenerateX25519().Private;
        if (sid.Length != 16 || ephemeralPrivate.Length != 32) throw new ArgumentException("Die sicheren Sitzungsdaten sind ungültig.");
        var core = new JsonObject { ["magnolie"] = "baum-fs1-start", ["von"] = Text(state, "kennung"),
            ["an"] = Text(partner, "kennung"), ["sid"] = Convert.ToBase64String(sid),
            ["epk"] = Convert.ToBase64String(MagnolienbaumCrypto.X25519Public(ephemeralPrivate)) };
        var auth = AuthKey(state, partner);
        try { core["mac"] = Convert.ToBase64String(Mac(auth, "start\0"u8.ToArray(), core)); }
        finally { CryptographicOperations.ZeroMemory(auth); }
        return new MagnolienbaumFsStart(core, ephemeralPrivate);
    }

    internal static (JsonObject Response, MagnolienbaumFsSession Session) BuildResponse(
        JsonObject state, JsonObject partner, JsonObject start, byte[]? ephemeralPrivate = null)
    {
        var auth = ValidateStart(state, partner, start, out var startCore);
        ephemeralPrivate ??= MagnolienbaumCrypto.GenerateX25519().Private;
        if (ephemeralPrivate.Length != 32) throw new ArgumentException("Der ephemere Schlüssel ist ungültig.");
        try
        {
            var responseCore = new JsonObject { ["magnolie"] = "baum-fs1-antwort", ["von"] = Text(state, "kennung"),
                ["an"] = Text(partner, "kennung"), ["sid"] = Text(startCore, "sid"),
                ["epk"] = Convert.ToBase64String(MagnolienbaumCrypto.X25519Public(ephemeralPrivate)),
                ["startHash"] = Convert.ToBase64String(SHA256.HashData(MagnolienbaumCrypto.Canonical(startCore))) };
            var response = responseCore.DeepClone().AsObject();
            response["mac"] = Convert.ToBase64String(Mac(auth, "answer\0"u8.ToArray(), responseCore));
            return (response, DeriveSession(ephemeralPrivate, ReadBase64(Text(startCore, "epk"), 32), auth, startCore, responseCore));
        }
        finally
        {
            CryptographicOperations.ZeroMemory(auth);
            CryptographicOperations.ZeroMemory(ephemeralPrivate);
        }
    }

    internal static MagnolienbaumFsSession OpenResponse(JsonObject state, JsonObject partner,
        JsonObject start, JsonObject response, byte[] ephemeralPrivate)
    {
        var startCore = start.DeepClone().AsObject(); startCore.Remove("mac");
        RequireFields(response, "magnolie", "von", "an", "sid", "epk", "startHash", "mac");
        var expectedStartHash = SHA256.HashData(MagnolienbaumCrypto.Canonical(startCore));
        if (Text(response, "magnolie") != "baum-fs1-antwort" || Text(response, "von") != Text(partner, "kennung") ||
            Text(response, "an") != Text(state, "kennung") || Text(response, "sid") != Text(start, "sid") ||
            !CryptographicOperations.FixedTimeEquals(ReadBase64(Text(response, "startHash"), 32), expectedStartHash))
            throw new CryptographicException("Die sichere Sitzungsantwort ist ungültig.");
        var responseCore = response.DeepClone().AsObject(); var receivedMac = ReadBase64(Text(responseCore, "mac"), 32); responseCore.Remove("mac");
        var auth = AuthKey(state, partner);
        try
        {
            if (!CryptographicOperations.FixedTimeEquals(receivedMac, Mac(auth, "answer\0"u8.ToArray(), responseCore)))
                throw new CryptographicException("Die sichere Sitzungsantwort ist ungültig.");
            return DeriveSession(ephemeralPrivate, ReadBase64(Text(responseCore, "epk"), 32), auth, startCore, responseCore);
        }
        finally { CryptographicOperations.ZeroMemory(auth); }
    }

    internal static JsonObject BuildEnvelope(MagnolienbaumFsSession session, string ownId, string partnerId,
        JsonNode content, string transportId, byte[]? nonce = null)
    {
        _ = ReadBase64(transportId, 16);
        nonce ??= RandomNumberGenerator.GetBytes(12);
        if (nonce.Length != 12) throw new ArgumentException("Die Nachrichtennonce ist ungültig.");
        var header = new JsonObject { ["magnolie"] = "baum-fs1", ["von"] = ownId, ["an"] = partnerId,
            ["sid"] = session.Sid, ["mid"] = transportId, ["nonce"] = Convert.ToBase64String(nonce) };
        var plain = MagnolienbaumCrypto.Canonical(content); var encrypted = new byte[plain.Length]; var tag = new byte[16];
        var aad = DataAadPrefix.Concat(MagnolienbaumCrypto.Canonical(header)).ToArray();
        using (var aes = new AesGcm(session.EncryptionKey, 16)) aes.Encrypt(nonce, plain, encrypted, tag, aad);
        var envelope = header.DeepClone().AsObject(); envelope["daten"] = Convert.ToBase64String(encrypted.Concat(tag).ToArray());
        return envelope;
    }

    internal static (JsonNode Content, string TransportId) OpenEnvelope(MagnolienbaumFsSession session,
        string ownId, string partnerId, JsonObject envelope)
    {
        if (session.Consumed) throw new CryptographicException("Die sichere Sitzung wurde bereits verwendet.");
        session.Consumed = true;
        RequireFields(envelope, "magnolie", "von", "an", "sid", "mid", "nonce", "daten");
        if (Text(envelope, "magnolie") != "baum-fs1" || Text(envelope, "von") != partnerId ||
            Text(envelope, "an") != ownId || Text(envelope, "sid") != session.Sid)
            throw new CryptographicException("Die sichere Nachricht ist ungültig.");
        var transportId = Text(envelope, "mid"); _ = ReadBase64(transportId, 16);
        var nonce = ReadBase64(Text(envelope, "nonce"), 12);
        var combined = ReadBase64Variable(Text(envelope, "daten"));
        if (combined.Length < 16) throw new CryptographicException("Die sichere Nachricht ist ungültig.");
        var header = envelope.DeepClone().AsObject(); header.Remove("daten");
        var aad = DataAadPrefix.Concat(MagnolienbaumCrypto.Canonical(header)).ToArray();
        var plain = new byte[combined.Length - 16];
        try
        {
            using (var aes = new AesGcm(session.EncryptionKey, 16))
                aes.Decrypt(nonce, combined.AsSpan(0, plain.Length), combined.AsSpan(plain.Length), plain, aad);
            return (JsonNode.Parse(plain) ?? throw new CryptographicException("Der Inhalt ist unlesbar."), transportId);
        }
        catch (Exception error) when (error is not CryptographicException)
        { throw new CryptographicException("Die sichere Nachricht konnte nicht geöffnet werden.", error); }
    }

    internal static JsonObject BuildAcknowledgement(MagnolienbaumFsSession session, JsonObject envelope)
    {
        var core = new JsonObject { ["magnolie"] = "baum-fs1-ack", ["sid"] = session.Sid, ["mid"] = Text(envelope, "mid") };
        var binding = AckBinding(session, envelope, core);
        core["mac"] = Convert.ToBase64String(Mac(session.AcknowledgementKey, "ack\0"u8.ToArray(), binding));
        return core;
    }

    internal static bool VerifyAcknowledgement(MagnolienbaumFsSession session, JsonObject envelope, JsonObject response)
    {
        try
        {
            RequireFields(response, "magnolie", "sid", "mid", "mac");
            if (Text(response, "magnolie") != "baum-fs1-ack" || Text(response, "sid") != session.Sid ||
                Text(response, "mid") != Text(envelope, "mid")) return false;
            var core = response.DeepClone().AsObject(); var received = ReadBase64(Text(core, "mac"), 32); core.Remove("mac");
            return CryptographicOperations.FixedTimeEquals(received,
                Mac(session.AcknowledgementKey, "ack\0"u8.ToArray(), AckBinding(session, envelope, core)));
        }
        catch (Exception) { return false; }
    }

    private static byte[] ValidateStart(JsonObject state, JsonObject partner, JsonObject start, out JsonObject core)
    {
        RequireFields(start, "magnolie", "von", "an", "sid", "epk", "mac");
        if (Text(start, "magnolie") != "baum-fs1-start" || Text(start, "von") != Text(partner, "kennung") ||
            Text(start, "an") != Text(state, "kennung")) throw new CryptographicException("Die sichere Sitzungsanfrage ist ungültig.");
        _ = ReadBase64(Text(start, "sid"), 16); _ = ReadBase64(Text(start, "epk"), 32);
        core = start.DeepClone().AsObject(); var received = ReadBase64(Text(core, "mac"), 32); core.Remove("mac");
        var auth = AuthKey(state, partner);
        if (!CryptographicOperations.FixedTimeEquals(received, Mac(auth, "start\0"u8.ToArray(), core)))
        { CryptographicOperations.ZeroMemory(auth); throw new CryptographicException("Die sichere Sitzungsanfrage ist ungültig."); }
        return auth;
    }

    private static MagnolienbaumFsSession DeriveSession(byte[] ownPrivate, byte[] remotePublic, byte[] auth,
        JsonObject startCore, JsonObject responseCore)
    {
        var shared = MagnolienbaumCrypto.X25519(ownPrivate, remotePublic);
        var transcript = SHA256.HashData(MagnolienbaumCrypto.Canonical(startCore).Concat(new byte[] { 0 })
            .Concat(MagnolienbaumCrypto.Canonical(responseCore)).ToArray());
        var salt = Mac(auth, "key\0"u8.ToArray(), new JsonObject { ["transkript"] = Convert.ToBase64String(transcript) });
        var material = MagnolienbaumCrypto.HkdfSha256(shared, salt, KeyInfoPrefix.Concat(transcript).ToArray(), 64);
        try { return new MagnolienbaumFsSession(Text(startCore, "sid"), transcript, material[..32], material[32..]); }
        finally
        {
            CryptographicOperations.ZeroMemory(shared); CryptographicOperations.ZeroMemory(salt);
            CryptographicOperations.ZeroMemory(material);
        }
    }

    private static JsonObject AckBinding(MagnolienbaumFsSession session, JsonObject envelope, JsonObject core) => new()
    {
        ["transkript"] = Convert.ToBase64String(session.Transcript),
        ["umschlagHash"] = Convert.ToHexString(SHA256.HashData(MagnolienbaumCrypto.Canonical(envelope))).ToLowerInvariant(),
        ["ack"] = core.DeepClone()
    };

    private static byte[] Mac(byte[] key, byte[] prefix, JsonNode core) => MagnolienbaumCrypto.Hmac(key, prefix, core);

    private static byte[] ReadBase64(string text, int length)
    {
        var raw = ReadBase64Variable(text);
        return raw.Length == length ? raw : throw new InvalidDataException("Die sichere Sitzung ist beschädigt.");
    }

    private static byte[] ReadBase64Variable(string text)
    {
        if (string.IsNullOrEmpty(text) || text.Any(char.IsWhiteSpace)) throw new InvalidDataException("Die sichere Sitzung ist beschädigt.");
        try
        {
            var raw = Convert.FromBase64String(text);
            if (Convert.ToBase64String(raw) != text) throw new FormatException();
            return raw;
        }
        catch (FormatException error) { throw new InvalidDataException("Die sichere Sitzung ist beschädigt.", error); }
    }

    private static void RequireFields(JsonObject value, params string[] fields)
    {
        if (value.Count != fields.Length || !value.Select(item => item.Key).ToHashSet(StringComparer.Ordinal).SetEquals(fields))
            throw new InvalidDataException("Die sichere Sitzung ist beschädigt.");
    }

    private static string Text(JsonObject value, string name) => value[name]?.GetValue<string>() ?? "";
}
