using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization.Metadata;
using System.Text;

namespace MagnolieOrganizer.Windows;

internal sealed class MagnolienbaumStore
{
    private const string Alphabet = "abcdefghijkmnopqrstuvwxyz23456789";
    private readonly WindowsPaths paths;
    private readonly AtomicStore store;
    private readonly Func<byte[], byte[]> protectSecret;
    private readonly Func<byte[], byte[]> unprotectSecret;
    private static readonly byte[] SecretEntropy = Encoding.UTF8.GetBytes("magnolienbaum-identity-v1");

    internal MagnolienbaumStore(WindowsPaths paths, AtomicStore? store = null,
        Func<byte[], byte[]>? protectSecret = null, Func<byte[], byte[]>? unprotectSecret = null)
    {
        this.paths = paths;
        this.store = store ?? new AtomicStore();
        this.protectSecret = protectSecret ?? ProtectSecret;
        this.unprotectSecret = unprotectSecret ?? UnprotectSecret;
    }

    internal JsonObject LoadOrCreate()
    {
        var text = store.Read(paths.Baum, 4 * 1024 * 1024);
        if (text is null)
        {
            var pair = MagnolienbaumCrypto.GenerateX25519();
            var state = new JsonObject { ["kennung"] = RandomId(16), ["name"] = Environment.MachineName.Split('.')[0],
                ["geheim"] = Convert.ToBase64String(pair.Private), ["oeffentlich"] = Convert.ToBase64String(pair.Public),
                ["an"] = false, ["port"] = 8737, ["partner"] = new JsonArray() };
            SaveState(state);
            return state;
        }
        JsonObject result;
        try { result = JsonNode.Parse(text) as JsonObject ?? throw new JsonException(); }
        catch (JsonException error) { throw new InvalidDataException("Die Magnolienbaum-Identitätsdatei ist beschädigt.", error); }
        var migrated = result["geheim"] is not null;
        if (!migrated)
        {
            try
            {
                var protectedSecret = Convert.FromBase64String(result["geheimGeschuetzt"]?.GetValue<string>() ?? "");
                var secret = unprotectSecret(protectedSecret);
                if (secret.Length != 32) throw new CryptographicException();
                result["geheim"] = Convert.ToBase64String(secret);
                CryptographicOperations.ZeroMemory(secret);
                result.Remove("geheimGeschuetzt");
            }
            catch (Exception error) when (error is FormatException or InvalidOperationException or CryptographicException)
            { throw new InvalidDataException("Die Magnolienbaum-Identitätsdatei ist beschädigt.", error); }
        }
        ValidateState(result);
        foreach (var partner in result["partner"]!.AsArray().OfType<JsonObject>())
        {
            if (partner["paarungsart"]?.GetValue<string>() != "datei-v2" ||
                partner["protokoll"]?.GetValue<string>() == "baum-fs1") continue;
            partner["protokoll"] = "baum-fs1";
            migrated = true;
        }
        if (migrated) SaveState(result);
        return result;
    }

    internal void SaveState(JsonObject state)
    {
        ValidateState(state);
        var persisted = state.DeepClone().AsObject();
        var secret = Convert.FromBase64String(persisted["geheim"]!.GetValue<string>());
        byte[]? protectedSecret = null;
        try
        {
            protectedSecret = protectSecret(secret);
            persisted["geheimGeschuetzt"] = Convert.ToBase64String(protectedSecret);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(secret);
            if (protectedSecret is not null) CryptographicOperations.ZeroMemory(protectedSecret);
        }
        persisted.Remove("geheim");
        store.Write(paths.Baum, persisted.ToJsonString(Indented), 4 * 1024 * 1024);
    }
    internal JsonArray LoadOutbox() => LoadArray(paths.BaumOutbox);
    internal JsonArray LoadInbox() => LoadArray(paths.BaumInbox);
    internal void SaveOutbox(JsonArray value) => store.Write(paths.BaumOutbox, value.ToJsonString(Indented));
    internal void SaveInbox(JsonArray value) => store.Write(paths.BaumInbox, value.ToJsonString(Indented));

    internal static string RandomId(int length) => new(Enumerable.Range(0, length)
        .Select(_ => Alphabet[RandomNumberGenerator.GetInt32(Alphabet.Length)]).ToArray());

    private JsonArray LoadArray(string path)
    {
        var text = store.Read(path, AtomicStore.MaxDataBytes);
        if (text is null) return new JsonArray();
        try { return JsonNode.Parse(text) as JsonArray ?? throw new JsonException(); }
        catch (JsonException error) { throw new InvalidDataException("Eine Magnolienbaum-Ablage ist beschädigt.", error); }
    }

    private static void ValidateState(JsonObject state)
    {
        try
        {
            if (Convert.FromBase64String(state["geheim"]?.GetValue<string>() ?? "").Length != 32 ||
                Convert.FromBase64String(state["oeffentlich"]?.GetValue<string>() ?? "").Length != 32 ||
                string.IsNullOrEmpty(state["kennung"]?.GetValue<string>()) || state["partner"] is not JsonArray)
                throw new InvalidDataException("Die Magnolienbaum-Identitätsdatei ist beschädigt.");
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var partner in state["partner"]!.AsArray())
            {
                if (partner is not JsonObject item) throw new InvalidDataException("Die Magnolienbaum-Identitätsdatei ist beschädigt.");
                var id = item["kennung"]?.GetValue<string>() ?? "";
                var publicText = item["oeffentlich"]?.GetValue<string>() ?? "";
                var publicKey = Convert.FromBase64String(publicText);
                if (id.Length is < 1 or > 32 || !ids.Add(id) || publicKey.Length != 32 ||
                    Convert.ToBase64String(publicKey) != publicText ||
                    item["name"] is JsonNode nameNode && nameNode.GetValue<string>().Length > 60 ||
                    item["port"] is JsonNode portNode && portNode.GetValue<int>() is < 1 or > 65535 ||
                    item["fernPort"] is JsonNode remotePortNode && remotePortNode.GetValue<int>() is < 1 or > 65535)
                    throw new InvalidDataException("Die Magnolienbaum-Identitätsdatei ist beschädigt.");
            }
        }
        catch (Exception error) when (error is FormatException or InvalidOperationException)
        { throw new InvalidDataException("Die Magnolienbaum-Identitätsdatei ist beschädigt.", error); }
    }

    private static byte[] ProtectSecret(byte[] secret) => OperatingSystem.IsWindows()
        ? ProtectedData.Protect(secret, SecretEntropy, DataProtectionScope.CurrentUser) : secret.ToArray();

    private static byte[] UnprotectSecret(byte[] secret) => OperatingSystem.IsWindows()
        ? ProtectedData.Unprotect(secret, SecretEntropy, DataProtectionScope.CurrentUser) : secret.ToArray();

    private static readonly JsonSerializerOptions Indented = new() { WriteIndented = true, TypeInfoResolver = new DefaultJsonTypeInfoResolver() };
}
