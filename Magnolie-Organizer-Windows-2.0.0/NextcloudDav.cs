using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml;
using System.Xml.Linq;

namespace MagnolieOrganizer.Windows;

internal static class NextcloudDavSelection
{
    internal static bool IsSupported(string addressBook, IReadOnlyList<string> calendarIds) =>
        (addressBook.Length == 0 || addressBook is "windows-contacts" or "microsoft-graph" ||
         addressBook.StartsWith("nextcloud-addressbook:", StringComparison.Ordinal)) &&
        calendarIds.All(value => value.StartsWith("nextcloud-calendar:", StringComparison.Ordinal));
}

internal sealed record NextcloudDavSource(string Uid, string Name, string Kind, Uri Href);
internal sealed record NextcloudDavSources(IReadOnlyList<NextcloudDavSource> Calendars,
    IReadOnlyList<NextcloudDavSource> AddressBooks, string Error = "");
internal sealed record NextcloudDavObject(Uri Href, string ETag, string Text);

internal sealed class NextcloudDavClient : IDisposable
{
    private const long MaximumXmlBytes = 16L * 1024 * 1024;
    private const long MaximumObjectBytes = 4L * 1024 * 1024;
    private static readonly HttpMethod PropFind = new("PROPFIND");
    private static readonly HttpMethod Report = new("REPORT");
    private readonly NextcloudMailboxSettingsStore settingsStore;
    private readonly HttpClient http;
    private readonly bool ownsHttp;

    internal NextcloudDavClient(NextcloudMailboxSettingsStore settingsStore, HttpClient? http = null)
    {
        this.settingsStore = settingsStore;
        if (http is not null) this.http = http;
        else
        {
            this.http = new HttpClient(NextcloudMailbox.CreateHandler()) { Timeout = TimeSpan.FromSeconds(12) };
            ownsHttp = true;
        }
    }

    internal async Task<NextcloudDavSources> ListSourcesAsync(CancellationToken cancellationToken)
    {
        var context = settingsStore.Context(false);
        var root = ServerUri(context, "/remote.php/dav/");
        var principal = await DiscoverPrincipalAsync(context, root, cancellationToken).ConfigureAwait(false);
        var homes = await DiscoverHomesAsync(context, principal, cancellationToken).ConfigureAwait(false);
        var calendarHome = homes.Calendar ?? ServerUri(context,
            "/remote.php/dav/calendars/" + Uri.EscapeDataString(context.Settings.User) + "/");
        var addressHome = homes.AddressBook ?? ServerUri(context,
            "/remote.php/dav/addressbooks/users/" + Uri.EscapeDataString(context.Settings.User) + "/");
        var calendars = await ListCollectionsAsync(context, calendarHome, "calendar", cancellationToken).ConfigureAwait(false);
        var addressBooks = await ListCollectionsAsync(context, addressHome, "addressbook", cancellationToken).ConfigureAwait(false);
        return new NextcloudDavSources(calendars, addressBooks);
    }

    internal async Task<IReadOnlyList<NextcloudDavObject>> ReadCalendarAsync(NextcloudDavSource source,
        CancellationToken cancellationToken) => await ReportAsync(source, "calendar-data", "urn:ietf:params:xml:ns:caldav",
        "<c:calendar-query xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name=\"VCALENDAR\"><c:comp-filter name=\"VEVENT\"/></c:comp-filter></c:filter></c:calendar-query>", cancellationToken).ConfigureAwait(false);

    internal async Task<IReadOnlyList<NextcloudDavObject>> ReadAddressBookAsync(NextcloudDavSource source,
        CancellationToken cancellationToken) => await ReportAsync(source, "address-data", "urn:ietf:params:xml:ns:carddav",
        "<card:addressbook-query xmlns:d=\"DAV:\" xmlns:card=\"urn:ietf:params:xml:ns:carddav\"><d:prop><d:getetag/><card:address-data/></d:prop><card:filter><card:prop-filter name=\"FN\"/></card:filter></card:addressbook-query>", cancellationToken).ConfigureAwait(false);

    internal async Task<NextcloudDavObject> CreateAsync(NextcloudDavSource source, string uid, string extension,
        string mediaType, string text, CancellationToken cancellationToken)
    {
        var name = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(uid))).ToLowerInvariant() + extension;
        var href = ResolveCollectionChild(source.Href, name);
        return await PutAsync(href, null, text, mediaType, cancellationToken).ConfigureAwait(false);
    }

    internal Task<NextcloudDavObject> UpdateAsync(Uri href, string etag, string mediaType, string text,
        CancellationToken cancellationToken) => PutAsync(href, etag, text, mediaType, cancellationToken);

    internal async Task DeleteAsync(Uri href, string etag, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context(false);
        EnsureAllowed(context, href);
        using var request = Request(HttpMethod.Delete, href, context);
        if (etag.Length > 0) request.Headers.TryAddWithoutValidation("If-Match", etag);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.PreconditionFailed)
            throw new InvalidOperationException("Das DAV-Objekt wurde gleichzeitig geändert.");
        if (response.StatusCode != HttpStatusCode.NotFound) EnsureSuccess(response);
    }

    internal static string StableSourceId(string kind, Uri href)
    {
        var canonical = href.GetComponents(UriComponents.SchemeAndServer | UriComponents.Path, UriFormat.UriEscaped);
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
        return $"nextcloud-{kind}:{hash}";
    }

    private async Task<Uri> DiscoverPrincipalAsync(NextcloudMailboxContext context, Uri fallback,
        CancellationToken cancellationToken)
    {
        foreach (var relative in new[] { "/.well-known/caldav", "/.well-known/carddav", "/remote.php/dav/" })
        {
            try
            {
                var endpoint = ServerUri(context, relative);
                var xml = await PropFindAsync(context, endpoint, "0",
                    "<d:propfind xmlns:d=\"DAV:\"><d:prop><d:current-user-principal/></d:prop></d:propfind>", cancellationToken).ConfigureAwait(false);
                var href = PropertyHref(xml, "current-user-principal");
                if (href is not null) return ResolveDavHref(context, endpoint, href);
            }
            catch (HttpRequestException error) when (error.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.MethodNotAllowed) { }
        }
        return fallback;
    }

    private async Task<(Uri? Calendar, Uri? AddressBook)> DiscoverHomesAsync(NextcloudMailboxContext context,
        Uri principal, CancellationToken cancellationToken)
    {
        try
        {
            var xml = await PropFindAsync(context, principal, "0",
                "<d:propfind xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\" xmlns:card=\"urn:ietf:params:xml:ns:carddav\"><d:prop><c:calendar-home-set/><card:addressbook-home-set/></d:prop></d:propfind>", cancellationToken).ConfigureAwait(false);
            var calendar = PropertyHref(xml, "calendar-home-set");
            var address = PropertyHref(xml, "addressbook-home-set");
            return (calendar is null ? null : ResolveDavHref(context, principal, calendar),
                address is null ? null : ResolveDavHref(context, principal, address));
        }
        catch (HttpRequestException error) when (error.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.MethodNotAllowed) { return (null, null); }
    }

    private async Task<IReadOnlyList<NextcloudDavSource>> ListCollectionsAsync(NextcloudMailboxContext context,
        Uri home, string kind, CancellationToken cancellationToken)
    {
        var typeNamespace = kind == "calendar" ? "urn:ietf:params:xml:ns:caldav" : "urn:ietf:params:xml:ns:carddav";
        var typeName = kind == "calendar" ? "calendar" : "addressbook";
        var xml = await PropFindAsync(context, home, "1",
            "<d:propfind xmlns:d=\"DAV:\"><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>", cancellationToken).ConfigureAwait(false);
        ValidateMultiStatus(xml);
        var result = new Dictionary<string, NextcloudDavSource>(StringComparer.Ordinal);
        foreach (var response in Responses(xml))
        {
            if (!Successful(response) || !response.Descendants().Any(element => element.Name.LocalName == typeName && element.Name.NamespaceName == typeNamespace)) continue;
            var rawHref = DirectHref(response); if (rawHref is null) continue;
            var href = ResolveDavHref(context, home, rawHref);
            var displayName = response.Descendants().FirstOrDefault(element => element.Name.LocalName == "displayname")?.Value.Trim();
            var uid = StableSourceId(kind, href);
            result[uid] = new NextcloudDavSource(uid, string.IsNullOrWhiteSpace(displayName) ? Uri.UnescapeDataString(href.Segments.Last().Trim('/')) : displayName, kind, href);
        }
        return result.Values.OrderBy(item => item.Name, StringComparer.CurrentCultureIgnoreCase).ThenBy(item => item.Uid, StringComparer.Ordinal).ToArray();
    }

    private async Task<IReadOnlyList<NextcloudDavObject>> ReportAsync(NextcloudDavSource source, string dataName,
        string dataNamespace, string body, CancellationToken cancellationToken)
    {
        var context = settingsStore.Context(false); EnsureAllowed(context, source.Href);
        using var request = Request(Report, source.Href, context);
        request.Headers.TryAddWithoutValidation("Depth", "1");
        request.Content = XmlContent(body);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        if (response.StatusCode != HttpStatusCode.MultiStatus) EnsureSuccess(response);
        var xml = ParseXml(await ReadLimitedAsync(response, MaximumXmlBytes, cancellationToken).ConfigureAwait(false));
        ValidateMultiStatus(xml);
        var result = new Dictionary<string, NextcloudDavObject>(StringComparer.Ordinal);
        foreach (var item in Responses(xml))
        {
            var rawHref = DirectHref(item) ?? throw new InvalidDataException("DAV-REPORT-Antwort ohne Href.");
            var href = ResolveDavHref(context, source.Href, rawHref);
            if (!IsCollectionChild(source.Href, href)) throw new InvalidDataException("DAV-REPORT lieferte ein Objekt außerhalb der Sammlung.");
            var data = item.Descendants().FirstOrDefault(element => element.Name.LocalName == dataName && element.Name.NamespaceName == dataNamespace)?.Value;
            if (data is null || string.IsNullOrWhiteSpace(data))
                throw new InvalidDataException("DAV-REPORT-Antwort ohne lesbare Objektdaten.");
            if (Encoding.UTF8.GetByteCount(data) > MaximumObjectBytes) throw new InvalidDataException("Ein DAV-Objekt ist zu groß.");
            var etag = item.Descendants().FirstOrDefault(element => element.Name.LocalName == "getetag")?.Value.Trim() ?? "";
            result[href.AbsoluteUri] = new NextcloudDavObject(href, etag, data);
        }
        return result.Values.OrderBy(item => item.Href.AbsoluteUri, StringComparer.Ordinal).ToArray();
    }

    private async Task<NextcloudDavObject> PutAsync(Uri href, string? etag, string text, string mediaType,
        CancellationToken cancellationToken)
    {
        if (Encoding.UTF8.GetByteCount(text) > MaximumObjectBytes) throw new InvalidDataException("Ein DAV-Objekt ist zu groß.");
        if (mediaType.Equals("text/calendar", StringComparison.OrdinalIgnoreCase))
            ExchangeCodec.RejectLocalIcsAttachments(text);
        var context = settingsStore.Context(false); EnsureAllowed(context, href);
        using var request = Request(HttpMethod.Put, href, context);
        request.Headers.TryAddWithoutValidation(etag is null ? "If-None-Match" : "If-Match", etag ?? "*");
        request.Content = new StringContent(text, new UTF8Encoding(false), mediaType);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.PreconditionFailed)
        {
            using var verifyRequest = Request(HttpMethod.Get, href, context);
            using var verify = await http.SendAsync(verifyRequest, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            if (verify.StatusCode == HttpStatusCode.OK)
            {
                var bytes = await ReadLimitedAsync(verify, MaximumObjectBytes, cancellationToken).ConfigureAwait(false);
                if (bytes.AsSpan().SequenceEqual(Encoding.UTF8.GetBytes(text)))
                    return new NextcloudDavObject(href, verify.Headers.ETag?.ToString() ?? etag ?? "", text);
            }
            throw new InvalidOperationException("Das DAV-Objekt wurde gleichzeitig geändert.");
        }
        EnsureSuccess(response);
        return new NextcloudDavObject(href, response.Headers.ETag?.ToString() ?? "", text);
    }

    private async Task<XDocument> PropFindAsync(NextcloudMailboxContext context, Uri uri, string depth, string body,
        CancellationToken cancellationToken)
    {
        for (var redirects = 0; ; redirects++)
        {
            EnsureAllowed(context, uri);
            using var request = Request(PropFind, uri, context);
            request.Headers.TryAddWithoutValidation("Depth", depth); request.Content = XmlContent(body);
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            if ((int)response.StatusCode is >= 300 and <= 399 && response.Headers.Location is { } location)
            {
                if (redirects != 0) throw new HttpRequestException("Zu viele DAV-Weiterleitungen.", null, response.StatusCode);
                uri = location.IsAbsoluteUri ? location : new Uri(uri, location); EnsureAllowed(context, uri); continue;
            }
            if (response.StatusCode != HttpStatusCode.MultiStatus) EnsureSuccess(response);
            var xml = ParseXml(await ReadLimitedAsync(response, MaximumXmlBytes, cancellationToken).ConfigureAwait(false));
            ValidateMultiStatus(xml);
            return xml;
        }
    }

    private static HttpRequestMessage Request(HttpMethod method, Uri uri, NextcloudMailboxContext context)
    {
        EnsureAllowed(context, uri);
        var request = new HttpRequestMessage(method, uri); request.Headers.Authorization = context.Authorization; return request;
    }

    private static ByteArrayContent XmlContent(string text)
    {
        var content = new ByteArrayContent(Encoding.UTF8.GetBytes(text));
        content.Headers.ContentType = new MediaTypeHeaderValue("application/xml") { CharSet = "utf-8" }; return content;
    }

    private static Uri ServerUri(NextcloudMailboxContext context, string relative)
    {
        var server = NextcloudMailbox.ValidateServer(context.Settings.ServerBase);
        var basePath = server.AbsolutePath.TrimEnd('/');
        return new UriBuilder(server) { Path = basePath + "/" + relative.TrimStart('/'), Query = "", Fragment = "" }.Uri;
    }

    private static Uri ResolveDavHref(NextcloudMailboxContext context, Uri requestUri, string href)
    {
        if (href.IndexOfAny(['\r', '\n']) >= 0) throw new InvalidDataException("Ungültiger DAV-Href.");
        var result = Uri.TryCreate(href, UriKind.Absolute, out var absolute) && absolute.Scheme == Uri.UriSchemeHttps
            ? absolute : new Uri(requestUri, href);
        EnsureAllowed(context, result); return result;
    }

    private static Uri ResolveCollectionChild(Uri collection, string name) => new(collection.AbsoluteUri.TrimEnd('/') + "/" + Uri.EscapeDataString(name));
    private static bool IsCollectionChild(Uri collection, Uri child) => child.AbsoluteUri.StartsWith(collection.AbsoluteUri.TrimEnd('/') + "/", StringComparison.Ordinal);

    private static void EnsureAllowed(NextcloudMailboxContext context, Uri uri)
    {
        var server = NextcloudMailbox.ValidateServer(context.Settings.ServerBase);
        if (uri.Scheme != Uri.UriSchemeHttps || !string.Equals(uri.IdnHost, server.IdnHost, StringComparison.OrdinalIgnoreCase) || uri.Port != server.Port ||
            !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new InvalidDataException("DAV-Ziel liegt außerhalb des konfigurierten HTTPS-Origin.");
    }

    private static string? PropertyHref(XDocument xml, string property) => xml.Descendants().FirstOrDefault(element => element.Name.LocalName == property)?
        .Descendants().FirstOrDefault(element => element.Name.LocalName == "href")?.Value;
    private static IEnumerable<XElement> Responses(XDocument xml) => xml.Descendants().Where(element => element.Name.LocalName == "response" && element.Name.NamespaceName == "DAV:");
    private static string? DirectHref(XElement response) => response.Elements().FirstOrDefault(element => element.Name.LocalName == "href" && element.Name.NamespaceName == "DAV:")?.Value;
    private static bool Successful(XElement response)
    {
        var statuses = response.Descendants().Where(element => element.Name.LocalName == "status").Select(element => element.Value).ToArray();
        return statuses.Length > 0 && statuses.All(IsSuccessfulStatus);
    }

    private static bool IsSuccessfulStatus(string status) =>
        status.StartsWith("HTTP/", StringComparison.Ordinal) && status.Length >= 12 &&
        int.TryParse(status.AsSpan(status.IndexOf(' ') + 1, 3), out var code) && code is >= 200 and <= 299;

    private static void ValidateMultiStatus(XDocument xml)
    {
        if (xml.Root?.Name != XName.Get("multistatus", "DAV:"))
            throw new InvalidDataException("Die DAV-Antwort ist kein Multi-Status-Dokument.");
        foreach (var response in Responses(xml))
        {
            if (DirectHref(response) is null) throw new InvalidDataException("DAV-Antwort ohne Href.");
            var direct = response.Elements(XName.Get("status", "DAV:")).ToArray();
            var propstats = response.Elements(XName.Get("propstat", "DAV:")).ToArray();
            if (direct.Length + propstats.Length == 0)
                throw new InvalidDataException("DAV-Antwort ohne Response-Status.");
            if (direct.Any(status => !IsSuccessfulStatus(status.Value)) || propstats.Any(propstat =>
                    propstat.Element(XName.Get("status", "DAV:")) is not { } status || !IsSuccessfulStatus(status.Value)))
                throw new InvalidDataException("Die DAV-Multi-Status-Antwort ist nur teilweise erfolgreich.");
        }
    }

    private static XDocument ParseXml(byte[] bytes)
    {
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaximumXmlBytes, MaxCharactersFromEntities = 0 };
        using var stream = new MemoryStream(bytes, false); using var reader = XmlReader.Create(stream, settings);
        return XDocument.Load(reader, LoadOptions.None);
    }

    private static async Task<byte[]> ReadLimitedAsync(HttpResponseMessage response, long limit, CancellationToken cancellationToken)
    {
        if (response.Content.Headers.ContentLength is > 0 && response.Content.Headers.ContentLength > limit) throw new InvalidDataException("Die DAV-Antwort ist zu groß.");
        await using var input = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false); using var output = new MemoryStream();
        var buffer = new byte[64 * 1024];
        while (true) { var read = await input.ReadAsync(buffer, cancellationToken).ConfigureAwait(false); if (read == 0) break; if (output.Length + read > limit) throw new InvalidDataException("Die DAV-Antwort ist zu groß."); output.Write(buffer, 0, read); }
        return output.ToArray();
    }

    private static void EnsureSuccess(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode) throw new HttpRequestException("Der Nextcloud-DAV-Aufruf ist fehlgeschlagen.", null, response.StatusCode);
    }

    public void Dispose() { if (ownsHttp) http.Dispose(); }
}

internal sealed class NextcloudCardDavRemote(NextcloudDavClient client, NextcloudDavSource source) : IContactRemote
{
    public async Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken)
    {
        var result = new List<RemoteContact>();
        var uids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in await client.ReadAddressBookAsync(source, cancellationToken).ConfigureAwait(false))
        {
            var parsed = ExchangeCodec.ParseVCard(item.Text);
            var contacts = parsed.Kontakte.OfType<JsonObject>().ToArray();
            if (parsed.Uebersprungen > 0 || contacts.Length != 1 || parsed.Kontakte.Count != 1)
                throw new InvalidDataException("Eine CardDAV-vCard wurde nicht vollständig gelesen.");
            var contact = contacts[0];
            var uid = ContactFields.Text(contact, "uid");
            if (uid.Length == 0 || !uids.Add(uid))
                throw new InvalidDataException("Das CardDAV-Adressbuch enthält fehlende oder doppelte UIDs.");
            result.Add(new RemoteContact(item.Href.AbsoluteUri, item.ETag, contact["geaendert"]?.GetValue<long>() ?? 0,
                contact.DeepClone().AsObject(), true));
        }
        return result;
    }

    public async Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        var text = Write(contact); var made = await client.CreateAsync(source, uid, ".vcf", "text/vcard", text, cancellationToken).ConfigureAwait(false);
        return new RemoteContact(made.Href.AbsoluteUri, made.ETag, contact["geaendert"]?.GetValue<long>() ?? 0, contact.DeepClone().AsObject(), true);
    }

    public async Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken)
    {
        if (remote.ETag.Length == 0) throw new InvalidOperationException("Der CardDAV-ETag fehlt; das Objekt wird nicht ungeschützt überschrieben.");
        var changed = await client.UpdateAsync(new Uri(remote.Id), remote.ETag, "text/vcard", Write(contact), cancellationToken).ConfigureAwait(false);
        return new RemoteContact(changed.Href.AbsoluteUri, changed.ETag, contact["geaendert"]?.GetValue<long>() ?? 0, contact.DeepClone().AsObject(), true);
    }

    public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) => remote.ETag.Length == 0
        ? Task.FromException(new InvalidOperationException("Der CardDAV-ETag fehlt; das Objekt wird nicht ungeschützt gelöscht."))
        : client.DeleteAsync(new Uri(remote.Id), remote.ETag, cancellationToken);

    private static string Write(JsonObject contact)
    {
        using var document = JsonDocument.Parse(new JsonArray(contact.DeepClone()).ToJsonString());
        var result = ExchangeCodec.WriteVCard(document.RootElement); if (result.Count != 1) throw new InvalidDataException("Kontakt kann nicht als vCard geschrieben werden."); return result.Text;
    }
}

internal sealed record NextcloudCalendarResult(JsonArray Termine, JsonArray Jahrestage, JsonArray Tombstones,
    int Imported, int Exported, int Updated, int Deleted, int Conflicts);

internal sealed class NextcloudCalendarSync(NextcloudDavClient client)
{
    internal async Task<NextcloudCalendarResult> SyncAsync(NextcloudDavSource source, JsonArray appointments,
        JsonArray anniversaries, JsonArray tombstones, long lastSync, bool additiveOnly, CancellationToken cancellationToken)
    {
        var localAppointments = new JsonArray(appointments.Select(value => value?.DeepClone()).ToArray());
        var localAnniversaries = new JsonArray(anniversaries.Select(value => value?.DeepClone()).ToArray());
        var dead = new JsonArray(tombstones.Select(value => value?.DeepClone()).ToArray());
        var remote = new Dictionary<string, (NextcloudDavObject Object, JsonObject Data, bool Anniversary)>(StringComparer.Ordinal);
        var uids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in await client.ReadCalendarAsync(source, cancellationToken).ConfigureAwait(false))
        {
            var parsed = ExchangeCodec.ParseIcs(item.Text);
            var values = parsed.Termine.OfType<JsonObject>().Select(value => (Value: value, Anniversary: false))
                .Concat(parsed.Jahrestage.OfType<JsonObject>().Select(value => (Value: value, Anniversary: true))).ToArray();
            if (parsed.Uebersprungen > 0 || values.Length == 0 || values.Length != parsed.Termine.Count + parsed.Jahrestage.Count)
                throw new InvalidDataException("Ein CalDAV-Objekt wurde nicht vollständig gelesen.");
            foreach (var value in values)
            {
                var uid = ContactFields.Text(value.Value, "uid");
                if (uid.Length == 0 || !uids.Add(uid))
                    throw new InvalidDataException("Der CalDAV-Kalender enthält fehlende oder doppelte UIDs.");
                remote.Add(RemoteKey(item.Href, value.Value), (item, value.Value, value.Anniversary));
            }
        }
        var imported = 0; var exported = 0; var updated = 0; var deleted = 0; var conflicts = 0;
        await MergeArray(localAppointments, false).ConfigureAwait(false);
        await MergeArray(localAnniversaries, true).ConfigureAwait(false);
        foreach (var tombstone in additiveOnly ? [] : dead.OfType<JsonObject>().ToArray())
        {
            var mapping = ContactFields.Source(tombstone, source.Uid); var id = mapping?["id"]?.GetValue<string>() ?? "";
            if (!remote.Remove(id, out var other)) continue;
            await client.DeleteAsync(other.Object.Href, other.Object.ETag, cancellationToken).ConfigureAwait(false); dead.Remove(tombstone); deleted++;
        }
        foreach (var other in remote.Values)
        {
            var value = other.Data.DeepClone().AsObject(); value["id"] = Guid.NewGuid().ToString("N"); value["geaendert"] = Math.Max(value["geaendert"]?.GetValue<long>() ?? 0, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            SetSource(value, source.Uid, RemoteKey(other.Object.Href, value), other.Object.ETag);
            (other.Anniversary ? localAnniversaries : localAppointments).Add(value); imported++;
        }
        return new NextcloudCalendarResult(localAppointments, localAnniversaries, dead, imported, exported, updated, deleted, conflicts);

        async Task MergeArray(JsonArray values, bool anniversary)
        {
            foreach (var value in values.OfType<JsonObject>().ToArray())
            {
                cancellationToken.ThrowIfCancellationRequested();
                var uid = ContactFields.Text(value, "uid"); if (uid.Length == 0) { uid = $"mag-{Guid.NewGuid():N}@magnolie-organizer"; value["uid"] = uid; }
                var mapping = ContactFields.Source(value, source.Uid); var id = mapping?["id"]?.GetValue<string>() ?? "";
                if (id.Length > 0 && remote.Remove(id, out var other))
                {
                    var localChanged = (value["geaendert"]?.GetValue<long>() ?? 0) > lastSync;
                    var remoteChanged = mapping?["etag"]?.GetValue<string>() != other.Object.ETag;
                    if (localChanged && remoteChanged) { var clone = other.Data.DeepClone().AsObject(); clone["id"] = Guid.NewGuid().ToString("N"); SetSource(clone, source.Uid, RemoteKey(other.Object.Href, clone), other.Object.ETag); values.Add(clone); conflicts++; continue; }
                    if (remoteChanged) { CopyCalendar(value, other.Data); SetSource(value, source.Uid, id, other.Object.ETag); updated++; }
                    else if (localChanged)
                    {
                        var changed = await WriteAsync(value, anniversary, other.Object, cancellationToken).ConfigureAwait(false);
                        foreach (var key in remote.Keys.ToArray())
                            if (remote[key].Object.Href == changed.Href)
                                remote[key] = (changed, remote[key].Data, remote[key].Anniversary);
                        SetSource(value, source.Uid, RemoteKey(changed.Href, value), changed.ETag); updated++;
                    }
                    continue;
                }
                if (id.Length > 0 && !additiveOnly && (value["geaendert"]?.GetValue<long>() ?? 0) <= lastSync) { values.Remove(value); deleted++; continue; }
                var made = await WriteAsync(value, anniversary, null, cancellationToken).ConfigureAwait(false); SetSource(value, source.Uid, RemoteKey(made.Href, value), made.ETag); exported++;
            }
        }

        async Task<NextcloudDavObject> WriteAsync(JsonObject value, bool anniversary, NextcloudDavObject? prior, CancellationToken token)
        {
            using var document = JsonDocument.Parse(new JsonArray(value.DeepClone()).ToJsonString());
            var text = ExchangeCodec.WriteIcs(anniversary ? "ics-jahrestage" : "ics-termine", document.RootElement).Text;
            if (prior is not null && !anniversary)
                text = ExchangeCodec.ReplaceCalendarEvent(prior.Text, value);
            return prior is null ? await client.CreateAsync(source, ContactFields.Text(value, "uid"), ".ics", "text/calendar", text, token).ConfigureAwait(false)
                : await client.UpdateAsync(prior.Href, prior.ETag, "text/calendar", text, token).ConfigureAwait(false);
        }
    }

    private static string RemoteKey(Uri href, JsonObject value) => href.AbsoluteUri + "#" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(ContactFields.Text(value, "uid")))).ToLowerInvariant();
    private static void SetSource(JsonObject value, string source, string id, string etag)
    {
        var all = value["syncQuellen"] as JsonObject ?? new JsonObject(); value["syncQuellen"] = all;
        all[source] = new JsonObject { ["id"] = id, ["etag"] = etag, ["geaendert"] = value["geaendert"]?.DeepClone(), ["eigen"] = true }; value["sync"] = true;
    }
    private static void CopyCalendar(JsonObject target, JsonObject source)
    {
        foreach (var item in source) if (item.Key is not ("id" or "syncQuellen" or "sync")) target[item.Key] = item.Value?.DeepClone();
    }
}
