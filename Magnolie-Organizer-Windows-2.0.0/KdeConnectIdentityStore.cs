using System.Net;
using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal interface IKdeConnectSecretProtector
{
    byte[] Protect(byte[] plain);
    byte[] Unprotect(byte[] cipher);
}

internal sealed class KdeConnectDpapiProtector : IKdeConnectSecretProtector
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("magnolie-kde-connect-identity-v1");
    public byte[] Protect(byte[] plain)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("DPAPI ist nur unter Windows verfügbar.");
        return ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser);
    }
    public byte[] Unprotect(byte[] cipher)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("DPAPI ist nur unter Windows verfügbar.");
        return ProtectedData.Unprotect(cipher, Entropy, DataProtectionScope.CurrentUser);
    }
}

internal sealed record KdeConnectLocalIdentity(string Id, string Name, X509Certificate2 Certificate);
internal sealed record KdeConnectPeer(string Id, string Name, string CertificatePin, long PairedAtMs,
    bool Paired = true, string? LastAddress = null, int? LastPort = null, long? LastSeenMs = null);

internal sealed class KdeConnectIdentityStore
{
    private static readonly ConcurrentDictionary<string, object> PeerGates =
        new(StringComparer.OrdinalIgnoreCase);
    /// <summary>
    /// Name, unter dem dieser Rechner in der KDE-Connect-Geräteliste des
    /// Telefons erscheint.
    ///
    /// Der Rechnername gehört dazu. Ohne ihn heißt jeder Rechner gleich, und
    /// bei mehreren Organizern im Haushalt ist am Telefon nicht mehr
    /// erkennbar, welcher gemeint ist – eine Paarung ginge dann leicht an das
    /// falsche Gerät. Magnolienbaum und Telefonverbindung verwenden den
    /// Rechnernamen ohnehin bereits.
    ///
    /// KDE Connect lässt höchstens 128 Zeichen zu; überlange Rechnernamen
    /// werden deshalb gekürzt.
    /// </summary>
    internal static string DeviceName
    {
        get
        {
            const string product = "Magnolie Organizer";
            var machine = Environment.MachineName.Split('.')[0].Trim();
            if (machine.Length == 0) return product;
            var room = 128 - product.Length - 3;
            if (machine.Length > room) machine = machine[..room];
            return $"{product} ({machine})";
        }
    }

    internal const int MaxRememberedSms = 20_000;
    private readonly WindowsPaths paths;
    private readonly AtomicStore files = new();
    private readonly IKdeConnectSecretProtector protector;
    private readonly object gate;
    private HashSet<string>? seenSms;
    private Queue<string>? seenSmsOrder;

    internal KdeConnectIdentityStore(WindowsPaths paths, IKdeConnectSecretProtector? protector = null)
    {
        this.paths = paths;
        this.protector = protector ?? new KdeConnectDpapiProtector();
        gate = PeerGates.GetOrAdd(Path.GetFullPath(paths.KdeConnectPeers), _ => new object());
    }

    internal KdeConnectLocalIdentity LoadOrCreate()
    {
        paths.EnsureDirectories();
        if (File.Exists(paths.KdeConnectIdentity) || File.Exists(paths.KdeConnectIdentityKey))
        {
            if (!File.Exists(paths.KdeConnectIdentity) && File.Exists(paths.KdeConnectIdentityKey))
            {
                var recoveredProtectedPfx = Convert.FromBase64String(files.Read(paths.KdeConnectIdentityKey, 128 * 1024)!);
                var recoveredPfx = protector.Unprotect(recoveredProtectedPfx);
                try
                {
#pragma warning disable SYSLIB0057
                    using var certificate = new X509Certificate2(recoveredPfx, (string?)null,
                        X509KeyStorageFlags.UserKeySet | X509KeyStorageFlags.Exportable);
#pragma warning restore SYSLIB0057
                    var recoveredId = certificate.GetNameInfo(X509NameType.SimpleName, false);
                    if (recoveredId.Length is < 32 or > 38 || !certificate.HasPrivateKey)
                        throw new InvalidDataException("Die KDE-Connect-Identität ist unvollständig.");
                    files.Write(paths.KdeConnectIdentity, new JsonObject { ["storageVersion"] = 1,
                        ["deviceId"] = recoveredId, ["deviceName"] = DeviceName,
                        ["certificatePin"] = KdeConnectProtocol.CertificatePin(certificate) }.ToJsonString());
                }
                finally { CryptographicOperations.ZeroMemory(recoveredPfx); }
            }
            if (File.Exists(paths.KdeConnectIdentity) && !File.Exists(paths.KdeConnectIdentityKey))
            {
                if (LoadPeers().Count != 0) throw new InvalidDataException("Die KDE-Connect-Identität ist unvollständig.");
                File.Delete(paths.KdeConnectIdentity);
                return LoadOrCreate();
            }
            var metadata = JsonNode.Parse(files.Read(paths.KdeConnectIdentity, 16 * 1024)!)?.AsObject()
                ?? throw new InvalidDataException("Die KDE-Connect-Identität ist beschädigt.");
            if (metadata["storageVersion"]?.GetValue<int>() != 1) throw new InvalidDataException("Unbekannte KDE-Connect-Ablageversion.");
            var id = metadata["deviceId"]?.GetValue<string>() ?? ""; var name = metadata["deviceName"]?.GetValue<string>() ?? "";
            /* Altstaende trugen 41 Zeichen und konnten deshalb nie koppeln. Einmalig
               verwerfen und neu erzeugen; gepaart war mit einer solchen Kennung ohnehin
               nichts, weil Android sie vor TLS fallen liess. */
            if (id.Length is < 32 or > 38)
            {
                File.Delete(paths.KdeConnectIdentity);
                File.Delete(paths.KdeConnectIdentityKey);
                return LoadOrCreate();
            }
            var protectedPfx = Convert.FromBase64String(files.Read(paths.KdeConnectIdentityKey, 128 * 1024)!);
            var pfx = protector.Unprotect(protectedPfx);
            try
            {
#pragma warning disable SYSLIB0057
                // Schannel cannot use an ephemeral private key when this process is the TLS server.
                var certificate = new X509Certificate2(pfx, (string?)null, X509KeyStorageFlags.UserKeySet | X509KeyStorageFlags.Exportable);
#pragma warning restore SYSLIB0057
                if (!certificate.HasPrivateKey || certificate.GetECDsaPrivateKey() is null || id.Length < 4 || string.IsNullOrWhiteSpace(name))
                    throw new InvalidDataException("Die KDE-Connect-Identität ist ungültig.");
                if (!string.Equals(name, DeviceName, StringComparison.Ordinal))
                    files.Write(paths.KdeConnectIdentity, new JsonObject { ["storageVersion"] = 1, ["deviceId"] = id,
                        ["deviceName"] = DeviceName, ["certificatePin"] = KdeConnectProtocol.CertificatePin(certificate) }.ToJsonString());
                return new KdeConnectLocalIdentity(id, DeviceName, certificate);
            }
            finally { CryptographicOperations.ZeroMemory(pfx); }
        }

        /* Genau 32 Zeichen. Android verwirft Kennungen ausserhalb 32..38 Zeichen,
           bevor es den TLS-Handschlag beginnt - das fruehere "magnolie_" + 32 Hex
           ergab 41 und wurde stillschweigend fallengelassen. Gemessen am 16.08.2026
           mit kdelaenge.py: 41 Zeichen Zeitueberschreitung, 32 Zeichen TLS in 94 ms. */
        var createdId = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
        var createdName = DeviceName;
        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var request = new CertificateRequest("CN=" + createdId, key, HashAlgorithmName.SHA256);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature, true));
        request.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(request.PublicKey, false));
        using var generated = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(10));
        var exported = generated.Export(X509ContentType.Pfx);
        try { files.Write(paths.KdeConnectIdentityKey, Convert.ToBase64String(protector.Protect(exported))); }
        finally { CryptographicOperations.ZeroMemory(exported); }
        files.Write(paths.KdeConnectIdentity, new JsonObject { ["storageVersion"] = 1, ["deviceId"] = createdId,
            ["deviceName"] = createdName, ["certificatePin"] = KdeConnectProtocol.CertificatePin(generated) }.ToJsonString());
        return LoadOrCreate();
    }

    internal IReadOnlyList<KdeConnectPeer> LoadPeers()
    {
        lock (gate)
        try
        {
            var root = JsonNode.Parse(files.Read(paths.KdeConnectPeers, 256 * 1024) ?? "{\"storageVersion\":1,\"peers\":[]}")!.AsObject();
            if (root["storageVersion"]?.GetValue<int>() != 1) throw new InvalidDataException("Unbekannte KDE-Connect-Peerablage.");
            return (root["peers"] as JsonArray ?? []).Select(value => value!.AsObject()).Select(value =>
            {
                var address = value["lastAddress"]?.GetValue<string>();
                var port = value["lastPort"]?.GetValue<int>();
                var seen = value["lastSeenMs"]?.GetValue<long>();
                if ((address is null) != !port.HasValue || (address is null) != !seen.HasValue ||
                    address is not null && (!IPAddress.TryParse(address, out var parsed) ||
                    !KdeConnectDirectBackend.IsPrivateAddress(parsed) || port!.Value is < KdeConnectProtocol.FirstPort or > KdeConnectProtocol.LastPort || seen!.Value <= 0))
                    throw new InvalidDataException("Ungültiger gespeicherter KDE-Connect-Endpunkt.");
                return new KdeConnectPeer(value["deviceId"]!.GetValue<string>(), value["deviceName"]!.GetValue<string>(),
                    value["certificatePin"]!.GetValue<string>(), value["pairedAtMs"]!.GetValue<long>(),
                    value["paired"]?.GetValue<bool>() ?? true, address, port, seen);
            }).ToArray();
        }
        catch (Exception error) when (error is JsonException or FormatException or InvalidOperationException)
        { throw new InvalidDataException("Die KDE-Connect-Peerablage ist beschädigt.", error); }
    }

    internal void Pin(KdeConnectPeer peer)
    {
        lock (gate) WritePeers(LoadPeers().Where(value => value.Id != peer.Id).Append(peer));
    }

    internal void Remove(string id)
    {
        lock (gate) WritePeers(LoadPeers().Where(value => value.Id != id));
    }

    internal void MarkUnpaired(string id)
    {
        lock (gate) WritePeers(LoadPeers().Select(peer => peer.Id == id ? peer with { Paired = false } : peer));
    }

    internal void UpdateEndpoint(string id, IPAddress address, int port)
    {
        if (!KdeConnectDirectBackend.IsPrivateAddress(address) || port is < KdeConnectProtocol.FirstPort or > KdeConnectProtocol.LastPort)
            throw new InvalidDataException("Ungültiger KDE-Connect-Endpunkt.");
        lock (gate)
        {
            var peers = LoadPeers();
            if (!peers.Any(peer => peer.Id == id)) throw new InvalidDataException("KDE-Connect-Gerät ist nicht gespeichert.");
            WritePeers(peers.Select(peer => peer.Id == id ? peer with { LastAddress = address.ToString(), LastPort = port,
                LastSeenMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() } : peer));
        }
    }

    internal void Confirm(KdeConnectPeer peer, IEnumerable<string> connectedIds)
    {
        lock (gate)
        {
            var connected = connectedIds.ToHashSet(StringComparer.Ordinal);
            var peers = LoadPeers().Where(value => value.Id == peer.Id || connected.Contains(value.Id) ||
                !string.Equals(value.Name, peer.Name, StringComparison.Ordinal) ||
                string.Equals(value.CertificatePin, peer.CertificatePin, StringComparison.Ordinal));
            WritePeers(peers.Where(value => value.Id != peer.Id).Append(peer with { Paired = true }));
        }
    }

    internal void Replace(string oldId, KdeConnectPeer peer)
    {
        lock (gate) WritePeers(LoadPeers().Where(value => value.Id != oldId && value.Id != peer.Id)
            .Append(peer with { Paired = true }));
    }

    internal IReadOnlySet<string> RememberSms(IEnumerable<string> ids)
    {
        lock (gate)
        {
            LoadSeenSms();
            var added = new HashSet<string>(StringComparer.Ordinal);
            foreach (var id in ids)
            {
                if (id.Length is < 1 or > 512 || id.Any(char.IsControl))
                    throw new InvalidDataException("Ungültige KDE-Connect-SMS-Kennung.");
                if (!seenSms!.Add(id)) continue;
                seenSmsOrder!.Enqueue(id); added.Add(id);
            }
            while (seenSmsOrder!.Count > MaxRememberedSms) seenSms!.Remove(seenSmsOrder.Dequeue());
            if (added.Count != 0) WriteSeenSms();
            return added;
        }
    }

    private void LoadSeenSms()
    {
        if (seenSms is not null) return;
        seenSms = new HashSet<string>(StringComparer.Ordinal); seenSmsOrder = new Queue<string>();
        var path = Path.Combine(paths.KdeConnect, "sms-seen.dpapi");
        var encoded = files.Read(path, 8 * 1024 * 1024);
        if (encoded is null) return;
        byte[] plain;
        try { plain = protector.Unprotect(Convert.FromBase64String(encoded)); }
        catch (Exception error) when (error is FormatException or CryptographicException)
        { throw new InvalidDataException("Die geschützte KDE-Connect-SMS-Ablage ist beschädigt.", error); }
        try
        {
            var root = JsonNode.Parse(plain)?.AsObject()
                ?? throw new InvalidDataException("Die KDE-Connect-SMS-Ablage ist beschädigt.");
            if (root["storageVersion"]?.GetValue<int>() != 1 || root["ids"] is not JsonArray values ||
                values.Count > MaxRememberedSms)
                throw new InvalidDataException("Unbekannte oder zu große KDE-Connect-SMS-Ablage.");
            foreach (var value in values)
            {
                var id = value?.GetValue<string>() ?? "";
                if (id.Length is < 1 or > 512 || id.Any(char.IsControl) || !seenSms.Add(id))
                    throw new InvalidDataException("Die KDE-Connect-SMS-Ablage ist beschädigt.");
                seenSmsOrder.Enqueue(id);
            }
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException)
        { throw new InvalidDataException("Die KDE-Connect-SMS-Ablage ist beschädigt.", error); }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private void WriteSeenSms()
    {
        var plain = JsonSerializer.SerializeToUtf8Bytes(new { storageVersion = 1, ids = seenSmsOrder!.ToArray() });
        try { files.Write(Path.Combine(paths.KdeConnect, "sms-seen.dpapi"),
            Convert.ToBase64String(protector.Protect(plain)), 8 * 1024 * 1024); }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private void WritePeers(IEnumerable<KdeConnectPeer> peers) => files.Write(paths.KdeConnectPeers,
        new JsonObject { ["storageVersion"] = 1, ["peers"] = new JsonArray(peers.Select(value =>
        {
            var item = new JsonObject { ["deviceId"] = value.Id, ["deviceName"] = value.Name,
                ["certificatePin"] = value.CertificatePin, ["pairedAtMs"] = value.PairedAtMs, ["paired"] = value.Paired };
            if (value.LastAddress is not null)
            { item["lastAddress"] = value.LastAddress; item["lastPort"] = value.LastPort; item["lastSeenMs"] = value.LastSeenMs; }
            return (JsonNode)item;
        }).ToArray()) }.ToJsonString());
}
