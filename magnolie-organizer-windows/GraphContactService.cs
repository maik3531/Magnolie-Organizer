using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record DeviceCodeResponse(string DeviceCode, string UserCode, string VerificationUri, string Message, int ExpiresIn, int Interval);
internal sealed record OAuthTokenResponse(string AccessToken, string RefreshToken, int ExpiresIn);

internal static class OAuthResponseParser
{
    internal static DeviceCodeResponse DeviceCode(string json)
    {
        using var document = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 16 }); var root = document.RootElement;
        var result = new DeviceCodeResponse(Text(root, "device_code"), Text(root, "user_code"), Text(root, "verification_uri"),
            Text(root, "message"), Int(root, "expires_in"), Math.Max(1, Int(root, "interval")));
        if (result.DeviceCode.Length == 0 || result.UserCode.Length == 0 || !Uri.TryCreate(result.VerificationUri, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps)
            throw new InvalidDataException("Microsoft lieferte keine gültige Gerätecode-Antwort.");
        return result;
    }

    internal static OAuthTokenResponse Token(string json)
    {
        using var document = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 16 }); var root = document.RootElement;
        var result = new OAuthTokenResponse(Text(root, "access_token"), Text(root, "refresh_token"), Int(root, "expires_in"));
        if (result.AccessToken.Length == 0) throw new InvalidDataException("Microsoft lieferte kein Zugriffstoken.");
        return result;
    }
    internal static string Error(string json)
    {
        try { using var document = JsonDocument.Parse(json); return Text(document.RootElement, "error"); } catch (JsonException) { return "invalid_response"; }
    }
    private static string Text(JsonElement root, string name) => root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    private static int Int(JsonElement root, string name) => root.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : 0;
}

internal interface ISecretProtector
{
    byte[] Protect(byte[] plain);
    byte[] Unprotect(byte[] protectedData);
}

internal sealed class DpapiCurrentUserProtector : ISecretProtector
{
    public byte[] Protect(byte[] plain)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("DPAPI ist nur unter Windows verfügbar.");
        return System.Security.Cryptography.ProtectedData.Protect(plain, null, System.Security.Cryptography.DataProtectionScope.CurrentUser);
    }
    public byte[] Unprotect(byte[] protectedData)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("DPAPI ist nur unter Windows verfügbar.");
        return System.Security.Cryptography.ProtectedData.Unprotect(protectedData, null, System.Security.Cryptography.DataProtectionScope.CurrentUser);
    }
}

internal sealed class GraphTokenStore
{
    private readonly string path; private readonly ISecretProtector protector;
    internal GraphTokenStore(string path, ISecretProtector protector) { this.path = path; this.protector = protector; }
    internal void Save(string refreshToken)
    {
        if (string.IsNullOrWhiteSpace(refreshToken)) throw new ArgumentException("Das Aktualisierungstoken fehlt.");
        var plain = Encoding.UTF8.GetBytes(refreshToken); var bytes = protector.Protect(plain);
        try { new AtomicStore().Write(path, Convert.ToBase64String(bytes)); }
        finally { Array.Clear(plain); Array.Clear(bytes); }
    }
    internal string? Load()
    {
        var text = new AtomicStore().Read(path, 64 * 1024); if (text is null) return null;
        var protectedBytes = Convert.FromBase64String(text); var plain = protector.Unprotect(protectedBytes);
        try { return Encoding.UTF8.GetString(plain); } finally { Array.Clear(plain); Array.Clear(protectedBytes); }
    }
    internal void Delete() { if (File.Exists(path)) File.Delete(path); }
    internal bool Exists => File.Exists(path);
}

internal sealed class GraphConfiguration
{
    private readonly string userPath; private readonly string buildPath;
    internal GraphConfiguration(string userPath, string buildPath) { this.userPath = userPath; this.buildPath = buildPath; }
    internal string ClientId => Read(userPath, "clientId") is { Length: > 0 } user ? user : Read(buildPath, "graphClientId");
    internal void Save(string clientId)
    {
        clientId = clientId.Trim();
        if (clientId.Length > 0 && !Guid.TryParse(clientId, out _)) throw new ArgumentException("Die Microsoft OAuth Client-ID muss eine GUID sein.");
        if (clientId.Length == 0) { if (File.Exists(userPath)) File.Delete(userPath); return; }
        new AtomicStore().Write(userPath, new JsonObject { ["clientId"] = clientId }.ToJsonString());
    }
    private static string Read(string path, string property)
    {
        try
        {
            var text = new AtomicStore().Read(path, 4096); if (text is null) return "";
            using var document = JsonDocument.Parse(text); var value = document.RootElement.TryGetProperty(property, out var item) ? item.GetString() ?? "" : "";
            return Guid.TryParse(value, out _) ? value : "";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException) { return ""; }
    }
}

internal sealed class MicrosoftOAuthClient
{
    private const string Scope = "offline_access Contacts.ReadWrite";
    private readonly HttpClient http;
    internal MicrosoftOAuthClient(HttpClient http) => this.http = http;
    internal async Task<DeviceCodeResponse> RequestDeviceCodeAsync(string clientId, CancellationToken cancellationToken)
    {
        var json = await PostAsync("https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
            new Dictionary<string, string> { ["client_id"] = clientId, ["scope"] = Scope }, cancellationToken);
        return OAuthResponseParser.DeviceCode(json);
    }
    internal async Task<OAuthTokenResponse> PollTokenAsync(string clientId, DeviceCodeResponse device, CancellationToken cancellationToken)
    {
        var end = DateTimeOffset.UtcNow.AddSeconds(device.ExpiresIn);
        while (DateTimeOffset.UtcNow < end)
        {
            await Task.Delay(TimeSpan.FromSeconds(device.Interval), cancellationToken);
            var (status, json) = await PostResultAsync("https://login.microsoftonline.com/common/oauth2/v2.0/token", new Dictionary<string, string>
            {
                ["client_id"] = clientId, ["grant_type"] = "urn:ietf:params:oauth:grant-type:device_code", ["device_code"] = device.DeviceCode
            }, cancellationToken);
            if (status == HttpStatusCode.OK) return OAuthResponseParser.Token(json);
            var error = OAuthResponseParser.Error(json);
            if (error is "authorization_pending" or "slow_down") continue;
            throw new InvalidOperationException("Microsoft-Anmeldung fehlgeschlagen: " + error);
        }
        throw new TimeoutException("Der Microsoft-Gerätecode ist abgelaufen.");
    }
    internal async Task<OAuthTokenResponse> RefreshAsync(string clientId, string refreshToken, CancellationToken cancellationToken)
    {
        var json = await PostAsync("https://login.microsoftonline.com/common/oauth2/v2.0/token", new Dictionary<string, string>
        {
            ["client_id"] = clientId, ["grant_type"] = "refresh_token", ["refresh_token"] = refreshToken, ["scope"] = Scope
        }, cancellationToken);
        return OAuthResponseParser.Token(json);
    }
    private async Task<string> PostAsync(string url, Dictionary<string, string> fields, CancellationToken token)
    {
        var (status, json) = await PostResultAsync(url, fields, token); if ((int)status >= 400) throw new HttpRequestException("OAuth-HTTP-Fehler " + (int)status); return json;
    }
    private async Task<(HttpStatusCode, string)> PostResultAsync(string url, Dictionary<string, string> fields, CancellationToken token)
    {
        using var response = await http.PostAsync(url, new FormUrlEncodedContent(fields), token);
        return (response.StatusCode, await GraphApiClient.ReadLimitedAsync(response.Content, 1024 * 1024, token));
    }
}

internal sealed class GraphApiClient : IContactRemote
{
    private readonly HttpClient http; private readonly string accessToken;
    internal GraphApiClient(HttpClient http, string accessToken) { this.http = http; this.accessToken = accessToken; }

    public async Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken)
    {
        var result = new List<RemoteContact>();
        var next = "https://graph.microsoft.com/v1.0/me/contacts?$top=100&$select=id,givenName,surname,companyName,emailAddresses,businessPhones,mobilePhone,homePhones,homeAddress,businessAddress,otherAddress,birthday,personalNotes,lastModifiedDateTime";
        for (var page = 0; next.Length > 0 && page < 100; page++)
        {
            using var response = await SendAsync(HttpMethod.Get, next, null, "", cancellationToken); response.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await ReadLimitedAsync(response.Content, 8 * 1024 * 1024, cancellationToken), new JsonDocumentOptions { MaxDepth = 32 });
            foreach (var item in document.RootElement.GetProperty("value").EnumerateArray()) result.Add(ParseContact(item));
            next = document.RootElement.TryGetProperty("@odata.nextLink", out var link) ? link.GetString() ?? "" : "";
            if (next.Length > 0 && (!Uri.TryCreate(next, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps || uri.Host != "graph.microsoft.com")) throw new InvalidDataException("Graph lieferte einen ungültigen Seitenlink.");
        }
        if (next.Length > 0) throw new InvalidDataException("Der Graph-Kontaktbestand überschreitet die sichere Seitengrenze.");
        return result;
    }
    public async Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        using var response = await SendAsync(HttpMethod.Post, "https://graph.microsoft.com/v1.0/me/contacts", ToGraph(contact), "", cancellationToken); response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(await ReadLimitedAsync(response.Content, 1024 * 1024, cancellationToken)); return ParseContact(document.RootElement) with { Owned = true };
    }
    public async Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        using var response = await SendAsync(HttpMethod.Patch, ContactUrl(remote.Id), ToGraph(contact), remote.ETag, cancellationToken); response.EnsureSuccessStatusCode();
        var changed = contact.DeepClone().AsObject(); return new RemoteContact(remote.Id, response.Headers.ETag?.Tag ?? remote.ETag, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), changed, remote.Owned);
    }
    public async Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken)
    {
        using var response = await SendAsync(HttpMethod.Delete, ContactUrl(remote.Id), null, remote.ETag, cancellationToken); response.EnsureSuccessStatusCode();
    }
    private async Task<HttpResponseMessage> SendAsync(HttpMethod method, string url, JsonObject? body, string etag, CancellationToken token)
    {
        var request = new HttpRequestMessage(method, url); request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);
        if (etag.Length > 0) request.Headers.TryAddWithoutValidation("If-Match", etag);
        if (body is not null) request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        return await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
    }
    private static string ContactUrl(string id) => "https://graph.microsoft.com/v1.0/me/contacts/" + Uri.EscapeDataString(id);
    internal static async Task<string> ReadLimitedAsync(HttpContent content, int maximum, CancellationToken token)
    {
        if (content.Headers.ContentLength > maximum) throw new IOException("Die Serverantwort ist zu groß.");
        await using var stream = await content.ReadAsStreamAsync(token); using var memory = new MemoryStream();
        var buffer = new byte[16384]; int read; while ((read = await stream.ReadAsync(buffer, token)) > 0) { if (memory.Length + read > maximum) throw new IOException("Die Serverantwort ist zu groß."); await memory.WriteAsync(buffer.AsMemory(0, read), token); }
        return Encoding.UTF8.GetString(memory.ToArray());
    }
    internal static RemoteContact ParseContact(JsonElement item)
    {
        string Text(string name) => item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
        var emails = item.TryGetProperty("emailAddresses", out var emailValues) && emailValues.ValueKind == JsonValueKind.Array
            ? emailValues.EnumerateArray().Select(value => value.TryGetProperty("address", out var address) ? address.GetString() ?? "" : "").Where(value => value.Length > 0).ToArray() : Array.Empty<string>();
        var businessPhones = Strings(item, "businessPhones"); var homePhones = Strings(item, "homePhones");
        var addresses = new[] { "homeAddress", "businessAddress", "otherAddress" }.Select((name, index) =>
        {
            var address = item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object ? value : default;
            string Field(string field) => address.ValueKind == JsonValueKind.Object && address.TryGetProperty(field, out var node) ? node.GetString() ?? "" : "";
            return new JsonObject { ["strasse"] = Field("street"), ["ort"] = Field("city"), ["plz"] = Field("postalCode"), ["land"] = Field("countryOrRegion"),
                ["typen"] = new JsonArray(JsonValue.Create(index == 0 ? "HOME" : index == 1 ? "WORK" : "OTHER")) };
        }).Where(address => address.Any(pair => pair.Key != "typen" && (pair.Value?.GetValue<string>() ?? "").Length > 0)).ToArray();
        var firstAddress = addresses.FirstOrDefault() ?? new JsonObject();
        var phoneItems = businessPhones.Select(value => (JsonNode)new JsonObject { ["wert"] = value, ["typen"] = new JsonArray(JsonValue.Create("WORK"), JsonValue.Create("VOICE")) })
            .Concat(homePhones.Select(value => (JsonNode)new JsonObject { ["wert"] = value, ["typen"] = new JsonArray(JsonValue.Create("HOME"), JsonValue.Create("VOICE")) })).ToList();
        if (Text("mobilePhone").Length > 0) phoneItems.Add(new JsonObject { ["wert"] = Text("mobilePhone"), ["typen"] = new JsonArray(JsonValue.Create("CELL")) });
        var modified = DateTimeOffset.TryParse(Text("lastModifiedDateTime"), CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var date) ? date.ToUnixTimeMilliseconds() : 0;
        var data = new JsonObject { ["vorname"] = Text("givenName"), ["nachname"] = Text("surname"), ["firma"] = Text("companyName"),
            ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(value => JsonValue.Create(value)).ToArray()),
            ["telefon"] = businessPhones.Concat(homePhones).FirstOrDefault() ?? "", ["mobil"] = Text("mobilePhone"),
            ["telefone"] = new JsonArray(phoneItems.ToArray()), ["strasse"] = ContactFields.Text(firstAddress, "strasse"), ["ort"] = ContactFields.Text(firstAddress, "ort"),
            ["plz"] = ContactFields.Text(firstAddress, "plz"), ["land"] = ContactFields.Text(firstAddress, "land"), ["anschriften"] = new JsonArray(addresses.Select(address => (JsonNode)address).ToArray()),
            ["notiz"] = Text("personalNotes") };
        if (DateTimeOffset.TryParse(Text("birthday"), CultureInfo.InvariantCulture, DateTimeStyles.None, out var birthday))
            data["geburtstag"] = birthday.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        var etag = item.TryGetProperty("@odata.etag", out var etagNode) ? etagNode.GetString() ?? "" : "";
        return new RemoteContact(Text("id"), etag, modified, data, false);
    }
    internal static JsonObject ToGraph(JsonObject contact)
    {
        var emails = contact["emails"] is JsonArray values ? values.Select(value => value?.GetValue<string>() ?? "").Where(value => value.Length > 0) : new[] { ContactFields.Text(contact, "email") }.Where(value => value.Length > 0);
        var phoneValues = contact["telefone"] is JsonArray phoneArray ? phoneArray.OfType<JsonObject>().Select(phone => ContactFields.Text(phone, "wert"))
            .Where(value => value.Length > 0).ToList() : new List<string>();
        phoneValues.RemoveAll(value => value == ContactFields.Text(contact, "mobil"));
        if (ContactFields.Text(contact, "telefon").Length > 0 && !phoneValues.Contains(ContactFields.Text(contact, "telefon"))) phoneValues.Insert(0, ContactFields.Text(contact, "telefon"));
        var addresses = contact["anschriften"] is JsonArray addressArray ? addressArray.OfType<JsonObject>().Take(3).ToList() : new List<JsonObject>();
        if (addresses.Count == 0) addresses.Add(contact);
        JsonObject GraphAddress(int index) { var address = index < addresses.Count ? addresses[index] : new JsonObject(); return new JsonObject
            { ["street"] = ContactFields.Text(address, "strasse"), ["city"] = ContactFields.Text(address, "ort"), ["postalCode"] = ContactFields.Text(address, "plz"), ["countryOrRegion"] = ContactFields.Text(address, "land") }; }
        var body = new JsonObject { ["givenName"] = ContactFields.Text(contact, "vorname"), ["surname"] = ContactFields.Text(contact, "nachname"), ["companyName"] = ContactFields.Text(contact, "firma"),
            ["emailAddresses"] = new JsonArray(emails.Select(value => (JsonNode)new JsonObject { ["address"] = value, ["name"] = value }).ToArray()),
            ["businessPhones"] = new JsonArray(phoneValues.Select(value => JsonValue.Create(value)).ToArray()), ["mobilePhone"] = ContactFields.Text(contact, "mobil"),
            ["homeAddress"] = GraphAddress(0), ["businessAddress"] = GraphAddress(1), ["otherAddress"] = GraphAddress(2),
            ["personalNotes"] = ContactFields.Text(contact, "notiz") };
        if (ExchangeCodec.TryParseCanonicalDate(ContactFields.Text(contact, "geburtstag"), out var birthday, out _, out _) && birthday is not null)
            body["birthday"] = birthday.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + "T00:00:00Z";
        return body;
    }
    private static string[] Strings(JsonElement item, string name) => item.TryGetProperty(name, out var values) && values.ValueKind == JsonValueKind.Array ? values.EnumerateArray().Select(value => value.GetString() ?? "").Where(value => value.Length > 0).ToArray() : Array.Empty<string>();
}
