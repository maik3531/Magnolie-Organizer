using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class EncryptionService
{
    private const string Marker = "magnolie-verschluesselt";
    private const string LegacyAlgorithm = "AES-256-GCM/PBKDF2-SHA256";
    private const string DataAlgorithm = "AES-256-GCM+DEK/PBKDF2-SHA256";
    private const int DefaultRounds = 240_000;
    private static readonly byte[] MarkerAad = Encoding.UTF8.GetBytes(Marker);
    private static readonly byte[] DataAad = Encoding.UTF8.GetBytes("magnolie-daten-v2");

    internal EncryptionSession? Session { get; private set; }

    internal static bool IsEncrypted(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return false;
        try
        {
            using var document = JsonDocument.Parse(text);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return false;
            var encrypted = root.TryGetProperty("magnolie", out var marker) && marker.ValueKind == JsonValueKind.String &&
                marker.GetString() == Marker;
            if (!encrypted && (root.TryGetProperty("verfahren", out _) || root.TryGetProperty("salz", out _) ||
                root.TryGetProperty("dekDaten", out _) || root.TryGetProperty("datenNonce", out _)))
                throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
            return encrypted;
        }
        catch (JsonException error) when (text.Contains(Marker, StringComparison.Ordinal))
        { throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.", error); }
        catch (JsonException) { return false; }
    }

    internal string Unlock(string envelope, string password)
    {
        using var document = JsonDocument.Parse(envelope);
        var root = document.RootElement;
        ValidateMarker(root);
        var version = RequiredInt(root, "fassung");
        if (version == 1) return UnlockLegacy(root, password);
        if (version != 2 || RequiredString(root, "verfahren") != DataAlgorithm)
            throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");

        var rounds = ValidRounds(root);
        var dekId = Bytes(root, "dekKennung", 16);
        var salt = Bytes(root, "salz", 16);
        var dekNonce = Bytes(root, "dekNonce", 12);
        var wrappedDek = Bytes(root, "dekDaten", 48);
        var dataNonce = Bytes(root, "datenNonce", 12);
        var encryptedData = Bytes(root, "daten", minimum: 16);
        var keyEncryptionKey = Derive(password, salt, rounds);
        byte[] dek;
        try { dek = Decrypt(keyEncryptionKey, dekNonce, wrappedDek, Aad("dek", dekId)); }
        catch (CryptographicException) { throw new CryptographicException("Das Kennwort ist falsch."); }
        if (dek.Length != 32) throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
        byte[] plain;
        try { plain = Decrypt(dek, dataNonce, encryptedData, Aad("inhalt", dekId)); }
        catch (CryptographicException) { throw new CryptographicException("Die verschlüsselte Datei ist beschädigt."); }
        Session = new EncryptionSession(dek, dekId, rounds, salt, dekNonce, wrappedDek);
        return Encoding.UTF8.GetString(plain);
    }

    internal string Enable(string plainText, string password)
    {
        if (string.IsNullOrEmpty(password)) throw new CryptographicException("Das Kennwort darf nicht leer sein.");
        var dek = RandomNumberGenerator.GetBytes(32);
        var dekId = RandomNumberGenerator.GetBytes(16);
        Session = Wrap(dek, dekId, password, DefaultRounds);
        return EncryptData(plainText);
    }

    internal string ChangePassword(string envelope, string oldPassword, string newPassword)
    {
        _ = Unlock(envelope, oldPassword);
        if (Session is null) throw new CryptographicException("Der Datenschlüssel fehlt.");
        Session = Wrap(Session.Dek, Session.DekId, newPassword, DefaultRounds);
        return RewrapEnvelope(envelope, Session);
    }

    internal EncryptionService CloneUnlocked()
    {
        var session = Session ?? throw new CryptographicException("Der Organizer ist nicht entsperrt.");
        return new EncryptionService { Session = new EncryptionSession(session.Dek.ToArray(), session.DekId.ToArray(),
            session.Rounds, session.Salt.ToArray(), session.DekNonce.ToArray(), session.WrappedDek.ToArray()) };
    }

    internal string ChangePasswordWithSession(string envelope, string newPassword)
    {
        _ = DecryptDataWithSession(envelope);
        var session = Session ?? throw new CryptographicException("Der Datenschlüssel fehlt.");
        Session = Wrap(session.Dek, session.DekId, newPassword, DefaultRounds);
        return RewrapEnvelope(envelope, Session);
    }

    internal string RewrapWithSession(string envelope)
    {
        _ = DecryptDataWithSession(envelope);
        return RewrapEnvelope(envelope, Session!);
    }

    internal string Disable(string envelope, string password)
    {
        var plain = Unlock(envelope, password);
        Clear();
        return plain;
    }

    internal string DisableWithSession(string envelope)
    {
        var plain = DecryptDataWithSession(envelope);
        Clear();
        return plain;
    }

    internal string EncryptData(string plainText)
    {
        var session = Session ?? throw new CryptographicException("Der Organizer ist nicht entsperrt.");
        var nonce = RandomNumberGenerator.GetBytes(12);
        var encrypted = Encrypt(session.Dek, nonce, Encoding.UTF8.GetBytes(plainText), Aad("inhalt", session.DekId));
        var root = BaseEnvelope(session);
        root["datenNonce"] = Convert.ToBase64String(nonce);
        root["daten"] = Convert.ToBase64String(encrypted);
        return root.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    }

    internal string DecryptDataWithSession(string envelope)
    {
        var session = Session ?? throw new CryptographicException("Der Organizer ist nicht entsperrt.");
        using var document = JsonDocument.Parse(envelope);
        var root = document.RootElement;
        ValidateMarker(root);
        if (RequiredInt(root, "fassung") != 2 || RequiredString(root, "verfahren") != DataAlgorithm ||
            !CryptographicOperations.FixedTimeEquals(Bytes(root, "dekKennung", 16), session.DekId))
            throw new CryptographicException("Der Snapshot gehört nicht zur aktiven Datenschutzsitzung.");
        try
        {
            return Encoding.UTF8.GetString(Decrypt(session.Dek, Bytes(root, "datenNonce", 12),
                Bytes(root, "daten", minimum: 16), Aad("inhalt", session.DekId)));
        }
        catch (CryptographicException)
        {
            throw new CryptographicException("Der verschlüsselte Snapshot ist beschädigt.");
        }
    }

    internal void Clear()
    {
        if (Session is not null)
        {
            CryptographicOperations.ZeroMemory(Session.Dek);
            Session = null;
        }
    }

    private string UnlockLegacy(JsonElement root, string password)
    {
        if (RequiredString(root, "verfahren") != LegacyAlgorithm)
            throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
        var rounds = ValidRounds(root);
        var salt = Bytes(root, "salz", 16);
        var nonce = Bytes(root, "nonce", 12);
        var encrypted = Bytes(root, "daten", minimum: 16);
        try
        {
            var plain = Decrypt(Derive(password, salt, rounds), nonce, encrypted, MarkerAad);
            var text = Encoding.UTF8.GetString(plain);
            Session = null;
            return text;
        }
        catch (CryptographicException)
        {
            throw new CryptographicException("Das Kennwort ist falsch.");
        }
    }

    private static EncryptionSession Wrap(byte[] dek, byte[] dekId, string password, int rounds)
    {
        if (string.IsNullOrEmpty(password)) throw new CryptographicException("Das Kennwort darf nicht leer sein.");
        var salt = RandomNumberGenerator.GetBytes(16);
        var nonce = RandomNumberGenerator.GetBytes(12);
        var wrapped = Encrypt(Derive(password, salt, rounds), nonce, dek, Aad("dek", dekId));
        return new EncryptionSession(dek, dekId, rounds, salt, nonce, wrapped);
    }

    private static JsonObject BaseEnvelope(EncryptionSession session) => new()
    {
        ["magnolie"] = Marker,
        ["fassung"] = 2,
        ["verfahren"] = DataAlgorithm,
        ["dekKennung"] = Convert.ToBase64String(session.DekId),
        ["runden"] = session.Rounds,
        ["salz"] = Convert.ToBase64String(session.Salt),
        ["dekNonce"] = Convert.ToBase64String(session.DekNonce),
        ["dekDaten"] = Convert.ToBase64String(session.WrappedDek)
    };

    private static string RewrapEnvelope(string envelope, EncryptionSession session)
    {
        var root = JsonNode.Parse(envelope)?.AsObject()
            ?? throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
        foreach (var field in BaseEnvelope(session)) root[field.Key] = field.Value?.DeepClone();
        return root.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    }

    private static byte[] Derive(string password, byte[] salt, int rounds) =>
        Rfc2898DeriveBytes.Pbkdf2(Encoding.UTF8.GetBytes(password ?? ""), salt, rounds,
            HashAlgorithmName.SHA256, 32);

    private static byte[] Encrypt(byte[] key, byte[] nonce, byte[] plain, byte[] aad)
    {
        var cipher = new byte[plain.Length];
        var tag = new byte[16];
        using var aes = new AesGcm(key, 16);
        aes.Encrypt(nonce, plain, cipher, tag, aad);
        return cipher.Concat(tag).ToArray();
    }

    private static byte[] Decrypt(byte[] key, byte[] nonce, byte[] encrypted, byte[] aad)
    {
        if (encrypted.Length < 16) throw new CryptographicException();
        var cipher = encrypted[..^16];
        var tag = encrypted[^16..];
        var plain = new byte[cipher.Length];
        using var aes = new AesGcm(key, 16);
        aes.Decrypt(nonce, cipher, tag, plain, aad);
        return plain;
    }

    private static byte[] Aad(string purpose, byte[] dekId) =>
        DataAad.Concat(new byte[] { 0 }).Concat(Encoding.ASCII.GetBytes(purpose))
            .Concat(new byte[] { 0 }).Concat(dekId).ToArray();

    private static void ValidateMarker(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object || RequiredString(root, "magnolie") != Marker)
            throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
    }

    private static int ValidRounds(JsonElement root)
    {
        var rounds = RequiredInt(root, "runden");
        if (rounds is < 50_000 or > 1_000_000)
            throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
        return rounds;
    }

    private static string RequiredString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? throw new CryptographicException() : throw new CryptographicException();

    private static int RequiredInt(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt32(out var result)
            ? result : throw new CryptographicException();

    private static byte[] Bytes(JsonElement root, string name, int? exact = null, int minimum = 0)
    {
        byte[] result;
        try { result = Convert.FromBase64String(RequiredString(root, name)); }
        catch (FormatException) { throw new CryptographicException("Die verschlüsselte Datei ist beschädigt."); }
        if ((exact.HasValue && result.Length != exact.Value) || result.Length < minimum)
            throw new CryptographicException("Die verschlüsselte Datei ist beschädigt.");
        return result;
    }
}

internal sealed record EncryptionSession(
    byte[] Dek,
    byte[] DekId,
    int Rounds,
    byte[] Salt,
    byte[] DekNonce,
    byte[] WrappedDek);
