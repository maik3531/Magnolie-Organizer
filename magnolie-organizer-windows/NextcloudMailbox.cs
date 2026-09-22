using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal sealed record NextcloudMailboxSettings(bool DavActive, bool MailboxActive, string ServerBase, string User)
{
    internal NextcloudMailboxSettings(bool active, string serverBase, string user) :
        this(active, active, serverBase, user) { }
    internal bool Active => MailboxActive;
    internal string AccountType { get; init; } = "nextcloud";
}
internal sealed record NextcloudMailboxContext(NextcloudMailboxSettings Settings, AuthenticationHeaderValue? Authorization);

internal static class NextcloudStatusText
{
    internal static string For(Exception error) => NativeLocalization.Gettext(error switch
    {
        GoogleDavAuthenticationException => "Google requires browser sign-in. Use Thunderbird to manage this account.",
        ThunderbirdBridgeException => "Thunderbird could not complete the request. Check the account in Thunderbird.",
        HttpRequestException { StatusCode: HttpStatusCode.Unauthorized } => "Sign-in failed. Check the account and authentication method required by your provider.",
        HttpRequestException { StatusCode: HttpStatusCode.Forbidden } => "The server denied access. Check this account's permissions.",
        OperationCanceledException => "The Nextcloud request timed out.",
        ArgumentException => "The Nextcloud settings are invalid.",
        InvalidDataException => "The Nextcloud response was incomplete.",
        _ => "The Nextcloud operation failed."
    });
}

internal sealed class GoogleDavAuthenticationException : InvalidOperationException { }

internal sealed class NextcloudMailboxSettingsStore
{
    private readonly string settingsPath;
    private readonly string passwordPath;
    private readonly ISecretProtector protector;
    private readonly object gate = new();

    internal NextcloudMailboxSettingsStore(string settingsPath, string passwordPath, ISecretProtector protector)
    {
        this.settingsPath = settingsPath;
        this.passwordPath = passwordPath;
        this.protector = protector;
    }

    internal NextcloudMailboxSettingsStore(string settingsPath, string passwordPath) :
        this(settingsPath, passwordPath, new DpapiCurrentUserProtector()) { }

    internal void Save(NextcloudMailboxSettings settings)
    {
        lock (gate)
        {
            var server = NextcloudMailbox.ValidateServer(settings.ServerBase);
            var user = ValidateUser(settings.User);
            var accountType = ValidateAccountType(settings.AccountType);
            if (accountType == "generic-dav" && settings.MailboxActive)
                throw new ArgumentException("Der Magnolienbaum-Briefkasten benötigt ein Nextcloud-Konto.");
            new AtomicStore().Write(settingsPath, new JsonObject
            {
                ["kontoArt"] = accountType,
                ["davAktiv"] = settings.DavActive,
                ["briefkastenAktiv"] = settings.MailboxActive,
                ["server"] = server.AbsoluteUri.TrimEnd('/'),
                ["benutzer"] = user
            }.ToJsonString());
        }
    }

    internal NextcloudMailboxSettings? Load()
    {
        lock (gate)
        {
            var text = new AtomicStore().Read(settingsPath, 16 * 1024);
            if (text is null) return null;
            try
            {
                using var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 8 });
                var root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object || root.GetRawText().Length > 16 * 1024 ||
                    !root.TryGetProperty("server", out var server) || server.ValueKind != JsonValueKind.String ||
                    !root.TryGetProperty("benutzer", out var user) || user.ValueKind != JsonValueKind.String)
                    throw new InvalidDataException("Die Nextcloud-Briefkasten-Einstellungen sind ungültig.");
                var serverText = NextcloudMailbox.ValidateServer(server.GetString() ?? "").AbsoluteUri.TrimEnd('/');
                var oldActive = root.TryGetProperty("aktiv", out var active) && active.ValueKind is JsonValueKind.True or JsonValueKind.False
                    ? active.GetBoolean() : (bool?)null;
                var davActive = root.TryGetProperty("davAktiv", out var dav) && dav.ValueKind is JsonValueKind.True or JsonValueKind.False
                    ? dav.GetBoolean() : oldActive;
                var mailboxActive = root.TryGetProperty("briefkastenAktiv", out var mailbox) && mailbox.ValueKind is JsonValueKind.True or JsonValueKind.False
                    ? mailbox.GetBoolean() : oldActive;
                if (davActive is null || mailboxActive is null) throw new InvalidDataException("Die Nextcloud-Einstellungen sind ungültig.");
                var accountType = ValidateAccountType(root.TryGetProperty("kontoArt", out var account) && account.ValueKind == JsonValueKind.String
                    ? account.GetString() ?? "" : "nextcloud");
                if (accountType == "generic-dav" && mailboxActive.Value) throw new InvalidDataException("Generisches DAV unterstützt keinen Magnolienbaum-Briefkasten.");
                return new NextcloudMailboxSettings(davActive.Value, mailboxActive.Value, serverText, ValidateUser(user.GetString() ?? ""))
                    { AccountType = accountType };
            }
            catch (JsonException error) { throw new InvalidDataException("Die Nextcloud-Briefkasten-Einstellungen sind ungültig.", error); }
        }
    }

    internal void SetApplicationPassword(string applicationPassword)
    {
        lock (gate)
        {
        if (string.IsNullOrEmpty(applicationPassword) || applicationPassword.Length > 4096)
            throw new ArgumentException("Das Anwendungskennwort fehlt oder ist zu lang.", nameof(applicationPassword));
        var plain = Encoding.UTF8.GetBytes(applicationPassword);
        byte[]? protectedData = null;
        try
        {
            protectedData = protector.Protect(plain);
            if (protectedData.Length == 0 || protectedData.AsSpan().SequenceEqual(plain))
                throw new CryptographicException("Das Anwendungskennwort wurde nicht geschützt.");
            new AtomicStore().Write(passwordPath, Convert.ToBase64String(protectedData), 64 * 1024);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plain);
            if (protectedData is not null) CryptographicOperations.ZeroMemory(protectedData);
        }
        }
    }

    internal bool HasApplicationPassword { get { lock (gate) return File.Exists(passwordPath); } }

    internal void ClearApplicationPassword()
    {
        lock (gate) if (File.Exists(passwordPath)) File.Delete(passwordPath);
    }

    internal void SaveConfiguration(NextcloudMailboxSettings settings, string applicationPassword, bool deletePassword)
    {
        lock (gate)
        {
            var files = new AtomicStore();
            var previousSettings = files.Read(settingsPath, 16 * 1024);
            var previousPassword = files.Read(passwordPath, 64 * 1024);
            try
            {
                Save(settings with { DavActive = false, MailboxActive = false });
                if (deletePassword) ClearApplicationPassword();
                else if (applicationPassword.Length > 0) SetApplicationPassword(applicationPassword);
                if (settings.DavActive || settings.MailboxActive) Save(settings);
            }
            catch
            {
                Restore(settingsPath, previousSettings, 16 * 1024);
                Restore(passwordPath, previousPassword, 64 * 1024);
                throw;
            }
        }
    }

    private static void Restore(string path, string? content, long maximum)
    {
        if (content is null) { if (File.Exists(path)) File.Delete(path); }
        else new AtomicStore().Write(path, content, maximum);
    }

    internal void Authorize(HttpRequestMessage request, string user)
    {
        lock (gate)
        {
        var encoded = new AtomicStore().Read(passwordPath, 64 * 1024) ?? throw new InvalidOperationException("Das Nextcloud-Anwendungskennwort fehlt.");
        byte[] protectedData;
        try { protectedData = Convert.FromBase64String(encoded); }
        catch (FormatException error) { throw new InvalidDataException("Das geschützte Anwendungskennwort ist ungültig.", error); }
        byte[]? plain = null;
        byte[]? userBytes = null;
        byte[]? credential = null;
        try
        {
            plain = protector.Unprotect(protectedData);
            if (plain.Length is < 1 or > 16 * 1024) throw new CryptographicException("Das geschützte Anwendungskennwort ist ungültig.");
            userBytes = Encoding.UTF8.GetBytes(ValidateUser(user) + ":");
            credential = new byte[userBytes.Length + plain.Length];
            userBytes.CopyTo(credential, 0);
            plain.CopyTo(credential, userBytes.Length);
            request.Headers.Authorization = new AuthenticationHeaderValue("Basic", Convert.ToBase64String(credential));
        }
        finally
        {
            CryptographicOperations.ZeroMemory(protectedData);
            if (plain is not null) CryptographicOperations.ZeroMemory(plain);
            if (userBytes is not null) CryptographicOperations.ZeroMemory(userBytes);
            if (credential is not null) CryptographicOperations.ZeroMemory(credential);
        }
        }
    }

    internal NextcloudMailboxContext Context(bool mailbox = true)
    {
        lock (gate)
        {
            var settings = Load() ?? throw new InvalidOperationException("Der Nextcloud-Briefkasten ist nicht eingerichtet.");
            if (mailbox ? !settings.MailboxActive : !settings.DavActive)
                throw new InvalidOperationException(mailbox ? "Der Nextcloud-Briefkasten ist nicht aktiviert." : "Nextcloud ist nicht aktiviert.");
            using var request = new HttpRequestMessage(); Authorize(request, settings.User);
            var authorization = request.Headers.Authorization ?? throw new InvalidOperationException("Das Nextcloud-Anwendungskennwort fehlt.");
            return new NextcloudMailboxContext(settings,
                new AuthenticationHeaderValue(authorization.Scheme, authorization.Parameter));
        }
    }

    internal static string ValidateUser(string user)
    {
        user = user.Trim();
        if (user.Length is < 1 or > 256 || user.Contains(':') || user.Any(char.IsControl)) throw new ArgumentException("Der Nextcloud-Benutzer ist ungültig.", nameof(user));
        return user;
    }

    internal static string ValidateAccountType(string accountType)
    {
        accountType = string.IsNullOrWhiteSpace(accountType) ? "nextcloud" : accountType.Trim().ToLowerInvariant();
        if (accountType is not ("nextcloud" or "generic-dav")) throw new ArgumentException("Die DAV-Kontoart ist ungültig.", nameof(accountType));
        return accountType;
    }
}

internal static class NextcloudMailboxProtocol
{
    private static readonly byte[] MessageDomain = "magnolie-baum-1-webdav-message-v1\0"u8.ToArray();
    private static readonly byte[] ReceiptDomain = "magnolie-baum-1-webdav-receipt-v1\0"u8.ToArray();

    internal static byte[] CreateMessage(byte[] transportId, string sender, string recipient, JsonNode payload,
        byte[] authenticationKey)
    {
        ValidateInputs(transportId, authenticationKey);
        var core = new JsonObject
        {
            ["format"] = "baum-1-webdav",
            ["art"] = "nachricht",
            ["von"] = ValidateId(sender),
            ["an"] = ValidateId(recipient),
            ["transportId"] = MagnolienbaumCrypto.Base64Url(transportId),
            ["inhalt"] = payload.DeepClone()
        };
        return Signed(core, authenticationKey, MessageDomain);
    }

    internal static string ReadSender(byte[] document, byte[] expectedTransportId, string expectedRecipient)
    {
        var value = Parse(document);
        if (value["format"]?.GetValue<string>() != "baum-1-webdav" || value["art"]?.GetValue<string>() != "nachricht" ||
            value["transportId"]?.GetValue<string>() != MagnolienbaumCrypto.Base64Url(expectedTransportId) ||
            value["an"]?.GetValue<string>() != ValidateId(expectedRecipient))
            throw new InvalidDataException("Die WebDAV-Nachricht ist falsch adressiert.");
        return ValidateId(value["von"]?.GetValue<string>() ?? "");
    }

    internal static JsonNode ReadMessage(byte[] document, byte[] expectedTransportId, string expectedSender,
        string expectedRecipient, byte[] authenticationKey)
    {
        var value = ReadAndVerify(document, expectedTransportId, authenticationKey, MessageDomain, "nachricht", 7,
            expectedSender, expectedRecipient);
        return value["inhalt"]!.DeepClone();
    }

    internal static byte[] CreateReceipt(byte[] transportId, string sender, string recipient, byte[] authenticationKey)
    {
        ValidateInputs(transportId, authenticationKey);
        var core = new JsonObject
        {
            ["format"] = "baum-1-webdav",
            ["art"] = "quittung",
            ["von"] = ValidateId(sender),
            ["an"] = ValidateId(recipient),
            ["transportId"] = MagnolienbaumCrypto.Base64Url(transportId)
        };
        return Signed(core, authenticationKey, ReceiptDomain);
    }

    internal static void VerifyReceipt(byte[] document, byte[] expectedTransportId, string expectedSender,
        string expectedRecipient, byte[] authenticationKey) =>
        _ = ReadAndVerify(document, expectedTransportId, authenticationKey, ReceiptDomain, "quittung", 6,
            expectedSender, expectedRecipient);

    internal static string StableId(byte[] transportId)
    {
        if (transportId.Length != 16) throw new ArgumentException("Die Transport-ID muss 16 Byte lang sein.", nameof(transportId));
        return Convert.ToHexString(transportId).ToLowerInvariant();
    }

    internal static bool TryParseMessageFileName(string fileName, out byte[] transportId)
    {
        transportId = Array.Empty<byte>();
        if (fileName.Length != 37 || !fileName.EndsWith(".json", StringComparison.Ordinal) ||
            !fileName.AsSpan(0, 32).ToString().All(value => value is >= '0' and <= '9' or >= 'a' and <= 'f')) return false;
        transportId = Convert.FromHexString(fileName.AsSpan(0, 32));
        return true;
    }

    private static byte[] Signed(JsonObject core, byte[] key, byte[] domain)
    {
        core["mac"] = MagnolienbaumCrypto.Base64Url(MagnolienbaumCrypto.Hmac(key, domain, core));
        return MagnolienbaumCrypto.Canonical(core);
    }

    private static JsonObject ReadAndVerify(byte[] document, byte[] expectedId, byte[] key, byte[] domain, string kind,
        int count, string expectedSender, string expectedRecipient)
    {
        ValidateInputs(expectedId, key);
        var value = Parse(document);
        JsonValue macNode;
        try
        {
            if (value.Count != count || value["format"]?.GetValue<string>() != "baum-1-webdav" || value["art"]?.GetValue<string>() != kind ||
                value["von"]?.GetValue<string>() != ValidateId(expectedSender) ||
                value["an"]?.GetValue<string>() != ValidateId(expectedRecipient) ||
                value["transportId"]?.GetValue<string>() != MagnolienbaumCrypto.Base64Url(expectedId) || value["mac"] is not JsonValue parsedMac)
                throw new CryptographicException("Die WebDAV-Nachricht ist nicht authentisch.");
            macNode = parsedMac;
        }
        catch (InvalidOperationException error) { throw new CryptographicException("Die WebDAV-Nachricht ist nicht authentisch.", error); }
        byte[] actual;
        try { actual = MagnolienbaumCrypto.ReadBase64Url(macNode.GetValue<string>(), 32); }
        catch (Exception error) when (error is InvalidDataException or InvalidOperationException) { throw new CryptographicException("Die WebDAV-Nachricht ist nicht authentisch.", error); }
        var core = value.DeepClone().AsObject();
        core.Remove("mac");
        var expected = MagnolienbaumCrypto.Hmac(key, domain, core);
        if (!CryptographicOperations.FixedTimeEquals(actual, expected)) throw new CryptographicException("Die WebDAV-Nachricht ist nicht authentisch.");
        return value;
    }

    private static JsonObject Parse(byte[] document)
    {
        if (document.Length is < 1 or > 42 * 1024 * 1024) throw new InvalidDataException("Das WebDAV-Dokument ist zu groß.");
        try { return JsonNode.Parse(document, documentOptions: new JsonDocumentOptions { MaxDepth = 64 }) as JsonObject ??
            throw new InvalidDataException("Das WebDAV-Dokument ist ungültig."); }
        catch (JsonException error) { throw new InvalidDataException("Das WebDAV-Dokument ist ungültig.", error); }
    }

    private static string ValidateId(string value)
    {
        if (value.Length is < 1 or > 64 || value.Any(character =>
                !char.IsAsciiLetterOrDigit(character) && character is not ('_' or '-')))
            throw new ArgumentException("Die Magnolienbaum-Kennung ist ungültig.", nameof(value));
        return value;
    }

    private static void ValidateInputs(byte[] transportId, byte[] authenticationKey)
    {
        ArgumentNullException.ThrowIfNull(transportId);
        ArgumentNullException.ThrowIfNull(authenticationKey);
        if (transportId.Length != 16) throw new ArgumentException("Die Transport-ID muss 16 Byte lang sein.", nameof(transportId));
        if (authenticationKey.Length < 32) throw new ArgumentException("Der Authentisierungsschlüssel ist zu kurz.", nameof(authenticationKey));
    }
}

internal sealed class NextcloudMailbox : IDisposable
{
    private const long MaximumDocumentBytes = 42L * 1024 * 1024;
    private static readonly HttpMethod MkCol = new("MKCOL");
    private static readonly HttpMethod PropFind = new("PROPFIND");
    private readonly NextcloudMailboxSettingsStore settingsStore;
    private readonly HttpClient http;
    private readonly bool ownsHttp;

    internal NextcloudMailbox(NextcloudMailboxSettingsStore settingsStore, HttpClient? http = null)
    {
        this.settingsStore = settingsStore;
        if (http is not null) this.http = http;
        else
        {
            this.http = DeadlineHttp.Create(TimeSpan.FromSeconds(12), CreateHandler(), MaximumDocumentBytes);
            ownsHttp = true;
        }
    }

    internal static HttpClientHandler CreateHandler() => new() { AllowAutoRedirect = false };

    internal async Task EnsureHierarchyAsync(string ownId, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        foreach (var relative in new[] { "Magnolie/", "Magnolie/baum-1/", "Magnolie/baum-1/nachrichten/",
                     $"Magnolie/baum-1/nachrichten/{EscapeId(ownId)}/", "Magnolie/baum-1/quittungen/",
                     $"Magnolie/baum-1/quittungen/{EscapeId(ownId)}/" })
        {
            using var request = Request(MkCol, FilesRoot(context.Settings, relative), context);
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (response.StatusCode is not (HttpStatusCode.Created or HttpStatusCode.MethodNotAllowed))
                throw new HttpRequestException("Die WebDAV-Ordnerhierarchie konnte nicht angelegt werden.", null, response.StatusCode);
        }
    }

    internal async Task<bool> UploadAsync(byte[] transportId, string sender, string recipient, JsonNode payload,
        byte[] authenticationKey, CancellationToken cancellationToken)
    {
        var document = NextcloudMailboxProtocol.CreateMessage(transportId, sender, recipient, payload, authenticationKey);
        var context = settingsStore.Context();
        return await PutNewAsync(context, MessageUri(context.Settings, recipient, transportId), document, cancellationToken);
    }

    internal async Task<bool> ReceiptExistsAsync(byte[] transportId, string expectedSender, string expectedRecipient,
        byte[] authenticationKey, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        using var request = Request(HttpMethod.Get, ReceiptUri(context.Settings, expectedRecipient, transportId), context);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (response.StatusCode == HttpStatusCode.NotFound) return false;
        EnsureSuccess(response);
        var document = await ReadLimitedAsync(response, MaximumDocumentBytes, cancellationToken);
        NextcloudMailboxProtocol.VerifyReceipt(document, transportId, expectedSender, expectedRecipient, authenticationKey);
        return true;
    }

    internal async Task<IReadOnlyList<byte[]>> ListIncomingAsync(string ownId, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        using var request = Request(PropFind, FilesRoot(context.Settings,
            $"Magnolie/baum-1/nachrichten/{EscapeId(ownId)}/"), context);
        request.Headers.TryAddWithoutValidation("Depth", "1");
        request.Content = new StringContent("<?xml version=\"1.0\"?><d:propfind xmlns:d=\"DAV:\"><d:prop><d:resourcetype/></d:prop></d:propfind>", Encoding.UTF8, "application/xml");
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (response.StatusCode != HttpStatusCode.MultiStatus) EnsureSuccess(response);
        var xml = await ReadLimitedAsync(response, 2 * 1024 * 1024, cancellationToken);
        return ParseListing(xml);
    }

    internal Task<byte[]> GetIncomingDocumentAsync(string ownId, byte[] transportId, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        return GetDocumentAsync(context, MessageUri(context.Settings, ownId, transportId), cancellationToken);
    }

    internal async Task<bool> WriteReceiptAsync(byte[] transportId, string sender, string recipient,
        byte[] authenticationKey, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        return await PutNewAsync(context, ReceiptUri(context.Settings, recipient, transportId),
            NextcloudMailboxProtocol.CreateReceipt(transportId, sender, recipient, authenticationKey), cancellationToken);
    }

    internal async Task TestAccessAsync(string ownId, CancellationToken cancellationToken)
    {
        await EnsureHierarchyAsync(ownId, cancellationToken).ConfigureAwait(false);
        var context = settingsStore.Context();
        var id = RandomNumberGenerator.GetBytes(16);
        var uri = ReceiptUri(context.Settings, ownId, id);
        try
        {
            using var request = Request(HttpMethod.Put, uri, context);
            request.Headers.TryAddWithoutValidation("If-None-Match", "*");
            request.Content = new StringContent("{\"format\":\"magnolie-write-test\"}", Encoding.UTF8, "application/json");
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            EnsureSuccess(response);
        }
        finally
        {
            await DeleteAsync(context, uri, cancellationToken).ConfigureAwait(false);
        }
    }

    internal Task DeleteIncomingAsync(string ownId, byte[] transportId, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        return DeleteAsync(context, MessageUri(context.Settings, ownId, transportId), cancellationToken);
    }

    internal Task DeleteReceiptAsync(string ownId, byte[] transportId, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context();
        return DeleteAsync(context, ReceiptUri(context.Settings, ownId, transportId), cancellationToken);
    }

    private async Task DeleteAsync(NextcloudMailboxContext context, Uri uri, CancellationToken cancellationToken)
    {
        using var request = Request(HttpMethod.Delete, uri, context);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (response.StatusCode != HttpStatusCode.NotFound) EnsureSuccess(response);
    }

    internal static Uri ValidateServer(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps || string.IsNullOrEmpty(uri.Host) ||
            !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new ArgumentException("Die Nextcloud-Serverbasis muss eine absolute HTTPS-Adresse ohne Zugangsdaten, Query oder Fragment sein.", nameof(value));
        return uri;
    }

    private async Task<bool> PutNewAsync(NextcloudMailboxContext context, Uri uri, byte[] document, CancellationToken cancellationToken)
    {
        using var request = Request(HttpMethod.Put, uri, context);
        request.Headers.TryAddWithoutValidation("If-None-Match", "*");
        request.Content = new ByteArrayContent(document);
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json") { CharSet = "utf-8" };
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (response.StatusCode == HttpStatusCode.PreconditionFailed) return false;
        EnsureSuccess(response);
        return true;
    }

    private async Task<byte[]> GetDocumentAsync(NextcloudMailboxContext context, Uri uri, CancellationToken cancellationToken)
    {
        using var request = Request(HttpMethod.Get, uri, context);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        EnsureSuccess(response);
        return await ReadLimitedAsync(response, MaximumDocumentBytes, cancellationToken);
    }

    private static HttpRequestMessage Request(HttpMethod method, Uri uri, NextcloudMailboxContext context)
    {
        var request = new HttpRequestMessage(method, uri);
        request.Headers.Authorization = context.Authorization;
        return request;
    }

    private static Uri FilesRoot(NextcloudMailboxSettings settings, string relative)
    {
        var server = ValidateServer(settings.ServerBase).AbsoluteUri.TrimEnd('/');
        var user = Uri.EscapeDataString(settings.User);
        return new Uri($"{server}/remote.php/dav/files/{user}/{relative}", UriKind.Absolute);
    }

    private static Uri MessageUri(NextcloudMailboxSettings settings, string recipient, byte[] id) =>
        FilesRoot(settings, $"Magnolie/baum-1/nachrichten/{EscapeId(recipient)}/{NextcloudMailboxProtocol.StableId(id)}.json");

    private static Uri ReceiptUri(NextcloudMailboxSettings settings, string recipient, byte[] id) =>
        FilesRoot(settings, $"Magnolie/baum-1/quittungen/{EscapeId(recipient)}/{NextcloudMailboxProtocol.StableId(id)}.json");

    private static string EscapeId(string value)
    {
        if (value.Length is < 1 or > 64 || value.Any(character =>
                !char.IsAsciiLetterOrDigit(character) && character is not ('_' or '-')))
            throw new ArgumentException("Die Magnolienbaum-Kennung ist ungültig.", nameof(value));
        return Uri.EscapeDataString(value);
    }

    private static async Task<byte[]> ReadLimitedAsync(HttpResponseMessage response, long limit, CancellationToken cancellationToken)
    {
        if (response.Content.Headers.ContentLength is > 0 && response.Content.Headers.ContentLength > limit)
            throw new InvalidDataException("Die WebDAV-Antwort ist zu groß.");
        await using var input = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var output = new MemoryStream();
        var buffer = new byte[64 * 1024];
        while (true)
        {
            var read = await input.ReadAsync(buffer, cancellationToken);
            if (read == 0) break;
            if (output.Length + read > limit) throw new InvalidDataException("Die WebDAV-Antwort ist zu groß.");
            output.Write(buffer, 0, read);
        }
        return output.ToArray();
    }

    private static IReadOnlyList<byte[]> ParseListing(byte[] xml)
    {
        var result = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 2 * 1024 * 1024 };
        using var stream = new MemoryStream(xml, writable: false);
        using var reader = XmlReader.Create(stream, settings);
        var document = XDocument.Load(reader, LoadOptions.None);
        if (document.Root?.Name != XName.Get("multistatus", "DAV:"))
            throw new InvalidDataException("Die DAV-Antwort ist kein Multi-Status-Dokument.");
        foreach (var response in document.Descendants(XName.Get("response", "DAV:")))
        {
            var statuses = response.Descendants(XName.Get("status", "DAV:")).Select(element => element.Value).ToArray();
            if (statuses.Length == 0 || statuses.Any(status => !status.Contains(" 200 ", StringComparison.Ordinal)))
                throw new InvalidDataException("Die DAV-Multi-Status-Antwort ist nur teilweise erfolgreich.");
            var href = response.Elements(XName.Get("href", "DAV:")).FirstOrDefault()?.Value;
            if (string.IsNullOrEmpty(href)) throw new InvalidDataException("DAV-Antwort ohne Href.");
            string path;
            if (Uri.TryCreate(href, UriKind.Absolute, out var absolute)) path = absolute.AbsolutePath;
            else path = href.Split('?', '#')[0];
            var slash = path.TrimEnd('/').LastIndexOf('/');
            var fileName = Uri.UnescapeDataString(path[(slash + 1)..]);
            if (NextcloudMailboxProtocol.TryParseMessageFileName(fileName, out var id)) result[fileName] = id;
        }
        return result.OrderBy(item => item.Key, StringComparer.Ordinal).Select(item => item.Value).ToArray();
    }

    private static void EnsureSuccess(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode) throw new HttpRequestException("Der Nextcloud-WebDAV-Aufruf ist fehlgeschlagen.", null, response.StatusCode);
    }

    public void Dispose()
    {
        if (ownsHttp) http.Dispose();
    }
}
