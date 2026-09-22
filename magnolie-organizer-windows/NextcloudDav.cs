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
    internal static bool IsCalendar(string value) => value.StartsWith("nextcloud-calendar:", StringComparison.Ordinal) ||
        value.StartsWith("generic-dav-calendar:", StringComparison.Ordinal);
    internal static bool IsAddressBook(string value) => value.StartsWith("nextcloud-addressbook:", StringComparison.Ordinal) ||
        value.StartsWith("generic-dav-addressbook:", StringComparison.Ordinal);

    internal static bool IsSupported(string addressBook, IReadOnlyList<string> calendarIds) =>
        (addressBook.Length == 0 || addressBook is "windows-contacts" or "microsoft-graph" ||
         IsAddressBook(addressBook)) && calendarIds.All(IsCalendar);

    internal static (JsonArray Selected, JsonArray Remaining) SplitCalendarItems(
        JsonArray items, string calendarUid, bool isDefaultCalendar)
    {
        var selected = new JsonArray(); var remaining = new JsonArray();
        foreach (var item in items.OfType<JsonObject>())
        {
            var owner = item["syncKalenderUid"]?.GetValue<string>() ?? "";
            var clone = item.DeepClone().AsObject();
            if (owner == calendarUid || (owner.Length == 0 && isDefaultCalendar))
            {
                if (owner.Length == 0) clone["syncKalenderUid"] = calendarUid;
                selected.Add(clone);
            }
            else remaining.Add(clone);
        }
        return (selected, remaining);
    }

    internal static (JsonArray Selected, JsonArray Remaining) SplitCalendarTombstones(
        JsonArray items, string calendarUid, bool isDefaultCalendar)
    {
        var selected = new JsonArray(); var remaining = new JsonArray();
        foreach (var item in items.OfType<JsonObject>())
        {
            var owner = item["syncKalenderUid"]?.GetValue<string>() ?? "";
            var hasCalendarMappings = item["syncQuellen"] is JsonObject sources &&
                sources.Any(source => IsCalendar(source.Key));
            var clone = item.DeepClone().AsObject();
            if (owner == calendarUid || ContactFields.Source(item, calendarUid) is not null ||
                (owner.Length == 0 && !hasCalendarMappings && isDefaultCalendar))
            {
                clone["syncKalenderUid"] = calendarUid;
                selected.Add(clone);
            }
            else remaining.Add(clone);
        }
        return (selected, remaining);
    }
}

internal sealed record NextcloudDavSource(string Uid, string Name, string Kind, Uri Href, bool SupportsVTodo = true);
internal sealed record NextcloudDavSources(IReadOnlyList<NextcloudDavSource> Calendars,
    IReadOnlyList<NextcloudDavSource> AddressBooks, string Error = "");
internal sealed record NextcloudDavObject(Uri Href, string ETag, string Text);
internal sealed class DavServiceUnavailableException : IOException { }

internal sealed class NextcloudDavClient : IDisposable
{
    private const long MaximumXmlBytes = 16L * 1024 * 1024;
    private const long MaximumObjectBytes = 4L * 1024 * 1024;
    private static readonly HttpMethod PropFind = new("PROPFIND");
    private static readonly HttpMethod Report = new("REPORT");
    private readonly NextcloudMailboxSettingsStore settingsStore;
    private readonly HttpClient http;
    private readonly bool ownsHttp;
    private readonly NextcloudSyncJournal? journal;
    private readonly string transactionId;
    private Uri? lastPropFindUri;

    internal NextcloudDavClient(NextcloudMailboxSettingsStore settingsStore, HttpClient? http = null,
        NextcloudSyncJournal? journal = null, string transactionId = "")
    {
        this.settingsStore = settingsStore;
        this.journal = journal;
        this.transactionId = transactionId;
        if (http is not null) this.http = http;
        else
        {
            this.http = DeadlineHttp.Create(TimeSpan.FromSeconds(12), NextcloudMailbox.CreateHandler(), MaximumXmlBytes);
            ownsHttp = true;
        }
    }

    internal async Task<NextcloudDavSources> ListSourcesAsync(CancellationToken cancellationToken,
        bool calendars = true, bool addressBooks = true)
    {
        var settings = settingsStore.Load();
        if (settings is not null && NextcloudMailbox.ValidateServer(settings.ServerBase).IdnHost
            is "www.googleapis.com" or "apidata.googleusercontent.com" or "calendar.google.com")
            throw new GoogleDavAuthenticationException();
        var context = settingsStore.Context(false);
        IReadOnlyList<NextcloudDavSource> calendarSources = [], addressSources = [];
        Exception? firstError = null;
        async Task<IReadOnlyList<NextcloudDavSource>> Discover(string kind)
        {
            try
            {
                var home = await DiscoverHomeAsync(context, kind, cancellationToken).ConfigureAwait(false);
                return await ListCollectionsAsync(context, home, kind, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception error) when (error is DavServiceUnavailableException ||
                error is HttpRequestException { StatusCode: HttpStatusCode.NotFound or HttpStatusCode.MethodNotAllowed })
            {
                firstError ??= error;
                return [];
            }
        }
        if (calendars) calendarSources = await Discover("calendar").ConfigureAwait(false);
        if (addressBooks) addressSources = await Discover("addressbook").ConfigureAwait(false);
        // CardDAV-only and CalDAV-only providers are valid. Keep the available
        // sources even when discovery of the other service fails.
        if (firstError is not null && calendarSources.Count + addressSources.Count == 0)
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(firstError).Throw();
        return new NextcloudDavSources(calendarSources, addressSources,
            firstError is null ? "" : NextcloudStatusText.For(firstError));
    }

    internal async Task<IReadOnlyList<NextcloudDavObject>> ReadCalendarAsync(NextcloudDavSource source,
        CancellationToken cancellationToken) => await ReportAsync(source, "calendar-data", "urn:ietf:params:xml:ns:caldav",
        "<c:calendar-query xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name=\"VCALENDAR\"/></c:filter></c:calendar-query>", cancellationToken).ConfigureAwait(false);

    internal async Task<IReadOnlyList<NextcloudDavObject>> ReadAddressBookAsync(NextcloudDavSource source,
        CancellationToken cancellationToken) => await ReportAsync(source, "address-data", "urn:ietf:params:xml:ns:carddav",
        "<card:addressbook-query xmlns:d=\"DAV:\" xmlns:card=\"urn:ietf:params:xml:ns:carddav\"><d:prop><d:getetag/><card:address-data/></d:prop><card:filter/></card:addressbook-query>", cancellationToken).ConfigureAwait(false);

    internal async Task<NextcloudDavObject> CreateAsync(NextcloudDavSource source, string uid, string extension,
        string mediaType, string text, CancellationToken cancellationToken)
    {
        var name = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(uid))).ToLowerInvariant() + extension;
        var href = ResolveCollectionChild(source.Href, name);
        if (journal is not null) text = journal.PrepareCreate(transactionId, href, mediaType, text);
        return await PutAsync(href, null, text, mediaType, cancellationToken).ConfigureAwait(false);
    }

    internal bool HasPendingCreate(Uri href) => journal?.HasPendingCreate(transactionId, href) == true;

    internal Task<NextcloudDavObject> UpdateAsync(Uri href, string etag, string mediaType, string text,
        CancellationToken cancellationToken) => PutAsync(href, etag, text, mediaType, cancellationToken);

    internal async Task DeleteAsync(Uri href, string etag, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(etag)) throw new InvalidOperationException("Der DAV-ETag fehlt; das Objekt wird nicht ungeschützt gelöscht.");
        var context = settingsStore.Context(false);
        EnsureAllowed(context, href);
        using var request = Request(HttpMethod.Delete, href, context);
        if (etag.Length > 0) request.Headers.TryAddWithoutValidation("If-Match", etag);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.PreconditionFailed)
            throw new InvalidOperationException("Das DAV-Objekt wurde gleichzeitig geändert.");
        if (response.StatusCode != HttpStatusCode.NotFound) EnsureSuccess(response);
    }

    internal static string StableSourceId(string kind, Uri href, string accountType = "nextcloud")
    {
        var canonical = href.GetComponents(UriComponents.SchemeAndServer | UriComponents.Path, UriFormat.UriEscaped);
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
        var provider = NextcloudMailboxSettingsStore.ValidateAccountType(accountType) == "generic-dav" ? "generic-dav" : "nextcloud";
        return $"{provider}-{kind}:{hash}";
    }

    private async Task<Uri> DiscoverHomeAsync(NextcloudMailboxContext context, string kind,
        CancellationToken cancellationToken)
    {
        var isCalendar = kind == "calendar";
        var endpoint = OriginUri(context, isCalendar ? "/.well-known/caldav" : "/.well-known/carddav");
        var homeName = isCalendar ? "calendar-home-set" : "addressbook-home-set";
        var homeNamespace = isCalendar ? "urn:ietf:params:xml:ns:caldav" : "urn:ietf:params:xml:ns:carddav";
        var endpoints = context.Settings.AccountType == "generic-dav"
            ? new[] { endpoint, new Uri(NextcloudMailbox.ValidateServer(context.Settings.ServerBase).AbsoluteUri.TrimEnd('/') + "/"),
                NextcloudMailbox.ValidateServer(context.Settings.ServerBase) }.Distinct().ToArray()
            : new[] { endpoint };
        foreach (var candidate in endpoints)
        {
            try
            {
                var xml = await PropFindAsync(context, candidate, "0",
                    $"<d:propfind xmlns:d=\"DAV:\" xmlns:x=\"{homeNamespace}\"><d:prop><d:resourcetype/><d:current-user-principal/><x:{homeName}/></d:prop></d:propfind>", cancellationToken).ConfigureAwait(false);
                var direct = PropertyHref(xml, homeName, homeNamespace);
                var responseBase = lastPropFindUri ?? candidate;
                // A user may supply the address book/calendar URL itself.
                // Such a resource need not expose a home-set or principal.
                foreach (var response in Responses(xml).Where(Successful))
                {
                    var rawHref = DirectHref(response);
                    if (rawHref is null) continue;
                    var href = ResolveDavHref(context, responseBase, rawHref);
                    if (href.AbsoluteUri.TrimEnd('/') == responseBase.AbsoluteUri.TrimEnd('/') &&
                        SuccessfulProperties(response).Where(p => p.Name == XName.Get("resourcetype", "DAV:"))
                            .Any(p => p.Elements(XName.Get(kind, homeNamespace)).Any())) return href;
                }
                if (direct is not null) return ResolveDavHref(context, responseBase, direct);
                var principalHref = PropertyHref(xml, "current-user-principal", "DAV:");
                if (principalHref is not null)
                {
                    var principal = ResolveDavHref(context, responseBase, principalHref);
                    var homes = await PropFindAsync(context, principal, "0",
                        $"<d:propfind xmlns:d=\"DAV:\" xmlns:x=\"{homeNamespace}\"><d:prop><x:{homeName}/></d:prop></d:propfind>", cancellationToken).ConfigureAwait(false);
                    var home = PropertyHref(homes, homeName, homeNamespace);
                    if (home is not null) return ResolveDavHref(context, lastPropFindUri ?? principal, home);
                }
            }
            catch (HttpRequestException error) when (error.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.MethodNotAllowed) { }
        }
        if (context.Settings.AccountType == "nextcloud")
            return ServerUri(context, isCalendar
                ? "/remote.php/dav/calendars/" + Uri.EscapeDataString(context.Settings.User) + "/"
                : "/remote.php/dav/addressbooks/users/" + Uri.EscapeDataString(context.Settings.User) + "/");
        throw new DavServiceUnavailableException();
    }

    private async Task<IReadOnlyList<NextcloudDavSource>> ListCollectionsAsync(NextcloudMailboxContext context,
        Uri home, string kind, CancellationToken cancellationToken)
    {
        var typeNamespace = kind == "calendar" ? "urn:ietf:params:xml:ns:caldav" : "urn:ietf:params:xml:ns:carddav";
        var typeName = kind == "calendar" ? "calendar" : "addressbook";
        var componentProperty = kind == "calendar" ? "<c:supported-calendar-component-set/>" : "";
        var xml = await PropFindAsync(context, home, "1",
            $"<d:propfind xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:prop><d:displayname/><d:resourcetype/>{componentProperty}</d:prop></d:propfind>", cancellationToken).ConfigureAwait(false);
        ValidateMultiStatus(xml, false);
        var responseBase = lastPropFindUri ?? home;
        var result = new Dictionary<string, NextcloudDavSource>(StringComparer.Ordinal);
        foreach (var response in Responses(xml))
        {
            var properties = SuccessfulProperties(response).ToArray();
            if (!Successful(response) || !properties.SelectMany(element => element.DescendantsAndSelf()).Any(element => element.Name.LocalName == typeName && element.Name.NamespaceName == typeNamespace)) continue;
            var rawHref = DirectHref(response); if (rawHref is null) continue;
            var href = ResolveDavHref(context, responseBase, rawHref);
            var displayName = properties.SelectMany(element => element.DescendantsAndSelf()).FirstOrDefault(element => element.Name.LocalName == "displayname")?.Value.Trim();
            var uid = StableSourceId(kind, href, context.Settings.AccountType);
            var components = properties.SelectMany(element => element.DescendantsAndSelf()).FirstOrDefault(element => element.Name.LocalName == "supported-calendar-component-set" && element.Name.NamespaceName == "urn:ietf:params:xml:ns:caldav");
            var supportsVTodo = components is null || components.Descendants().Any(element => element.Name.LocalName == "comp" &&
                string.Equals(element.Attribute("name")?.Value, "VTODO", StringComparison.OrdinalIgnoreCase));
            result[uid] = new NextcloudDavSource(uid, string.IsNullOrWhiteSpace(displayName) ? Uri.UnescapeDataString(href.Segments.Last().Trim('/')) : displayName, kind, href, supportsVTodo);
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
        if (etag is not null && string.IsNullOrWhiteSpace(etag))
            throw new InvalidOperationException("Der DAV-ETag fehlt; das Objekt wird nicht ungeschützt überschrieben.");
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
            ValidateMultiStatus(xml, false);
            lastPropFindUri = uri;
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

    private static Uri OriginUri(NextcloudMailboxContext context, string path)
    {
        var server = NextcloudMailbox.ValidateServer(context.Settings.ServerBase);
        return new UriBuilder(server) { Path = path, Query = "", Fragment = "" }.Uri;
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

    private static string? PropertyHref(XDocument xml, string property, string? propertyNamespace = null) => Responses(xml)
        .SelectMany(SuccessfulProperties).SelectMany(element => element.DescendantsAndSelf()).FirstOrDefault(element => element.Name.LocalName == property &&
        (propertyNamespace is null || element.Name.NamespaceName == propertyNamespace))?
        .Descendants().FirstOrDefault(element => element.Name.LocalName == "href")?.Value;
    private static IEnumerable<XElement> Responses(XDocument xml) => xml.Descendants().Where(element => element.Name.LocalName == "response" && element.Name.NamespaceName == "DAV:");
    private static string? DirectHref(XElement response) => response.Elements().FirstOrDefault(element => element.Name.LocalName == "href" && element.Name.NamespaceName == "DAV:")?.Value;
    private static bool Successful(XElement response)
    {
        var direct = response.Elements(XName.Get("status", "DAV:")).Select(element => element.Value).ToArray();
        if (direct.Length > 0) return direct.All(IsSuccessfulStatus);
        return response.Elements(XName.Get("propstat", "DAV:")).Any(propstat =>
            propstat.Element(XName.Get("status", "DAV:")) is { } status && IsSuccessfulStatus(status.Value));
    }

    private static IEnumerable<XElement> SuccessfulProperties(XElement response) => response.Elements(XName.Get("propstat", "DAV:"))
        .Where(propstat => propstat.Element(XName.Get("status", "DAV:")) is { } status && IsSuccessfulStatus(status.Value))
        .SelectMany(propstat => propstat.Element(XName.Get("prop", "DAV:"))?.Elements() ?? []);

    private static bool IsSuccessfulStatus(string status) =>
        status.StartsWith("HTTP/", StringComparison.Ordinal) && status.Length >= 12 &&
        int.TryParse(status.AsSpan(status.IndexOf(' ') + 1, 3), out var code) && code is >= 200 and <= 299;

    private static void ValidateMultiStatus(XDocument xml, bool requireAllSuccess = true)
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
            if (requireAllSuccess && (direct.Any(status => !IsSuccessfulStatus(status.Value)) || propstats.Any(propstat =>
                    propstat.Element(XName.Get("status", "DAV:")) is not { } status || !IsSuccessfulStatus(status.Value)))
                )
                throw new InvalidDataException("Die DAV-Multi-Status-Antwort ist nur teilweise erfolgreich.");
            if (!requireAllSuccess && propstats.Any(propstat => propstat.Element(XName.Get("status", "DAV:")) is null))
                throw new InvalidDataException("DAV-Antwort ohne Property-Status.");
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
    private static readonly string[] Fields = ["uid", "datum", "endDatum", "zeit", "endZeit", "titel", "notiz", "kategorien",
        "ort", "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "standardErinnerung", "individuelleErinnerungTage",
        "wiederholung", "erinnern", "vorlaufTage", "name", "typ", "icsRoundtrip", "icsKomplex", "icsSerienUid", "icsSequence",
        "icsAusnahmen", "icsAusnahmeTermine", "icsZusatzDaten", "icsZusatzTermine", "icsStatus", "icsEndeFehlt", "icsNullDauer"];
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
            if (parsed.FehlerhafteTermine > 0 ||
                values.Length != parsed.Termine.Count + parsed.Jahrestage.Count)
                throw new InvalidDataException("Ein CalDAV-Objekt wurde nicht vollständig gelesen.");
            if (values.Length == 0) continue;
            foreach (var value in values)
            {
                var uid = ContactFields.Text(value.Value, "uid");
                if (uid.Length == 0 || !uids.Add(uid))
                    throw new InvalidDataException("Der CalDAV-Kalender enthält fehlende oder doppelte UIDs.");
                remote.Add(RemoteKey(item.Href, value.Value), (item, value.Value, value.Anniversary));
            }
        }
        var observedEtags = remote.Values.GroupBy(item => item.Object.Href)
            .ToDictionary(group => group.Key, group => group.First().Object.ETag);
        if (!additiveOnly) foreach (var tombstone in dead.OfType<JsonObject>())
        {
            var mapping = ContactFields.Source(tombstone, source.Uid);
            if (mapping?["id"]?.GetValue<string>() is string id && remote.TryGetValue(id, out var other))
                SyncBaseline.RequireDeletionRevision(mapping, other.Object.ETag);
        }
        var imported = 0; var exported = 0; var updated = 0; var deleted = 0; var conflicts = 0;
        await MergeArray(localAppointments, false).ConfigureAwait(false);
        await MergeArray(localAnniversaries, true).ConfigureAwait(false);
        foreach (var tombstone in additiveOnly ? [] : dead.OfType<JsonObject>().ToArray())
        {
            var mapping = ContactFields.Source(tombstone, source.Uid); var id = mapping?["id"]?.GetValue<string>() ?? "";
            if (id.Length == 0) continue;
            if (remote.Remove(id, out var other))
            {
                var remaining = ExchangeCodec.RemoveCalendarEvent(other.Object.Text, ContactFields.Text(tombstone, "uid"));
                if (remaining is null) await client.DeleteAsync(other.Object.Href, other.Object.ETag, cancellationToken).ConfigureAwait(false);
                else
                {
                    var changed = await client.UpdateAsync(other.Object.Href, other.Object.ETag, "text/calendar", remaining, cancellationToken).ConfigureAwait(false);
                    foreach (var key in remote.Keys.ToArray())
                        if (remote[key].Object.Href == changed.Href)
                            remote[key] = (changed with { Text = remaining }, remote[key].Data, remote[key].Anniversary);
                }
                deleted++;
            }
            var sources = tombstone["syncQuellen"] as JsonObject;
            sources?.Remove(source.Uid);
            if (sources is null || sources.Count == 0) dead.Remove(tombstone);
            else if (tombstone["syncKalenderUid"]?.GetValue<string>() is not string owner || owner.Length == 0 || owner == source.Uid)
                tombstone["syncKalenderUid"] = sources.FirstOrDefault(item =>
                    NextcloudDavSelection.IsCalendar(item.Key)).Key ?? "";
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
                if (additiveOnly && id.Length == 0)
                {
                    var match = remote.FirstOrDefault(pair => pair.Value.Anniversary == anniversary &&
                        ContactFields.Text(pair.Value.Data, "uid") == uid);
                    if (!string.IsNullOrEmpty(match.Key))
                    {
                        remote.Remove(match.Key);
                        if ((match.Value.Data["geaendert"]?.GetValue<long>() ?? 0) > (value["geaendert"]?.GetValue<long>() ?? 0))
                            CopyCalendar(value, match.Value.Data);
                        SetSource(value, source.Uid, match.Key, match.Value.Object.ETag, match.Value.Data);
                    }
                    continue;
                }
                if (id.Length > 0 && remote.Remove(id, out var other))
                {
                    var remoteChanged = mapping?["etag"]?.GetValue<string>() != observedEtags[other.Object.Href];
                    var localChanged = SyncBaseline.Dirty(value, mapping, Fields, remoteChanged ? null : other.Data);
                    if (additiveOnly)
                    {
                        if ((other.Data["geaendert"]?.GetValue<long>() ?? 0) > (value["geaendert"]?.GetValue<long>() ?? 0))
                            CopyCalendar(value, other.Data);
                        SetSource(value, source.Uid, id, other.Object.ETag, other.Data);
                        continue;
                    }
                    if (localChanged && remoteChanged)
                    {
                        var clone = value.DeepClone().AsObject(); clone["id"] = Guid.NewGuid().ToString("N");
                        clone["uid"] = $"mag-{Guid.NewGuid():N}@magnolie-organizer";
                        clone.Remove("syncQuellen"); clone.Remove("icsSerienUid");
                        clone["sync"] = false; clone["syncKalenderUid"] = source.Uid;
                        values.Add(clone);
                        CopyCalendar(value, other.Data); SetSource(value, source.Uid, id, other.Object.ETag);
                        conflicts++; continue;
                    }
                    if (remoteChanged) { CopyCalendar(value, other.Data); SetSource(value, source.Uid, id, other.Object.ETag); updated++; }
                    else if (localChanged)
                    {
                        var changed = await WriteAsync(value, anniversary, other.Object, cancellationToken).ConfigureAwait(false);
                        foreach (var key in remote.Keys.ToArray())
                            if (remote[key].Object.Href == changed.Href)
                                remote[key] = (changed, remote[key].Data, remote[key].Anniversary);
                        SetSource(value, source.Uid, RemoteKey(changed.Href, value), changed.ETag); updated++;
                    }
                    else SetSource(value, source.Uid, id, other.Object.ETag);
                    continue;
                }
                if (additiveOnly) { (value["syncQuellen"] as JsonObject)?.Remove(source.Uid); continue; }
                if (id.Length > 0 && !anniversary && !additiveOnly && !SyncBaseline.Dirty(value, mapping, Fields)) { values.Remove(value); deleted++; continue; }
                if (!additiveOnly)
                {
                    var made = await WriteAsync(value, anniversary, null, cancellationToken).ConfigureAwait(false); SetSource(value, source.Uid, RemoteKey(made.Href, value), made.ETag); remote.Remove(RemoteKey(made.Href, value)); exported++;
                }
            }
        }

        async Task<NextcloudDavObject> WriteAsync(JsonObject value, bool anniversary, NextcloudDavObject? prior, CancellationToken token)
        {
            using var document = JsonDocument.Parse(new JsonArray(value.DeepClone()).ToJsonString());
            var text = ExchangeCodec.WriteIcs(anniversary ? "ics-jahrestage" : "ics-termine", document.RootElement).Text;
            if (prior is not null)
                text = anniversary ? ExchangeCodec.ReplaceCalendarAnniversary(prior.Text, value)
                    : ExchangeCodec.ReplaceCalendarEvent(prior.Text, value);
            return prior is null ? await client.CreateAsync(source, ContactFields.Text(value, "uid"), ".ics", "text/calendar", text, token).ConfigureAwait(false)
                : await client.UpdateAsync(prior.Href, prior.ETag, "text/calendar", text, token).ConfigureAwait(false);
        }
    }

    private static string RemoteKey(Uri href, JsonObject value) => href.AbsoluteUri + "#" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(ContactFields.Text(value, "uid")))).ToLowerInvariant();
    private static void SetSource(JsonObject value, string source, string id, string etag, JsonObject? baseline = null)
    {
        var all = value["syncQuellen"] as JsonObject ?? new JsonObject(); value["syncQuellen"] = all;
        all[source] = new JsonObject { ["id"] = id, ["etag"] = etag, ["geaendert"] = value["geaendert"]?.DeepClone(), ["eigen"] = true,
            ["inhaltFormat"] = "windows-1", ["inhaltSha256"] = SyncBaseline.Hash(baseline ?? value, Fields) };
        value["syncKalenderUid"] = source; value["sync"] = true;
    }
    private static void CopyCalendar(JsonObject target, JsonObject source)
    {
        foreach (var key in target.Select(item => item.Key).Where(key => key.StartsWith("ics", StringComparison.Ordinal) && !source.ContainsKey(key)).ToArray()) target.Remove(key);
        foreach (var item in source) if (item.Key is not ("id" or "syncQuellen" or "sync")) target[item.Key] = item.Value?.DeepClone();
    }
}

internal sealed record NextcloudTaskResult(JsonArray Tasks, JsonArray Tombstones,
    int Imported, int Exported, int Updated, int Deleted, int Conflicts);

internal sealed class NextcloudTaskSync(NextcloudDavClient client)
{
    private static readonly string[] Fields = ["uid", "titel", "faellig", "startDatum", "startZeit", "faelligZeit", "prio", "erledigt",
        "notiz", "erinnern", "vorlaufTage", "individuelleErinnerungTage", "erinnerungsMinute", "elternUid", "reihenfolge", "icsRoundtrip"];
    internal async Task<NextcloudTaskResult> SyncAsync(NextcloudDavSource source, JsonArray tasks,
        JsonArray tombstones, long lastSync, bool additiveOnly, CancellationToken cancellationToken)
    {
        var local = new JsonArray(tasks.Select(value => value?.DeepClone()).ToArray());
        var dead = new JsonArray(tombstones.Select(value => value?.DeepClone()).ToArray());
        GesamtarchivService.NormalizeTaskGraph(local);
        var remote = new Dictionary<string, (NextcloudDavObject Object, JsonObject Data)>(StringComparer.Ordinal);
        foreach (var resource in await client.ReadCalendarAsync(source, cancellationToken).ConfigureAwait(false))
        {
            var parsed = ExchangeCodec.ParseIcs(resource.Text);
            if (parsed.FehlerhafteAufgaben > 0) throw new InvalidDataException("Ein CalDAV-Objekt wurde nicht vollständig gelesen.");
            foreach (var task in parsed.Aufgaben.OfType<JsonObject>())
            {
                var uid = ContactFields.Text(task, "uid");
                if (uid.Length == 0 || !remote.TryAdd(uid, (resource, task.DeepClone().AsObject())))
                    throw new InvalidDataException("Die CalDAV-Aufgabensammlung enthält fehlende oder doppelte UIDs.");
            }
        }
        GesamtarchivService.NormalizeTaskGraph(new JsonArray(remote.Values
            .Select(value => (JsonNode?)value.Data).ToArray()));
        var observedEtags = remote.Values.GroupBy(item => item.Object.Href)
            .ToDictionary(group => group.Key, group => group.First().Object.ETag);
        if (!additiveOnly) foreach (var tombstone in dead.OfType<JsonObject>())
            if (remote.TryGetValue(ContactFields.Text(tombstone, "uid"), out var other))
                SyncBaseline.RequireDeletionRevision(ContactFields.Source(tombstone, source.Uid), other.Object.ETag);
        var imported = 0; var exported = 0; var updated = 0; var deleted = 0; var conflicts = 0;
        foreach (var value in local.OfType<JsonObject>().ToArray())
        {
            var uid = ContactFields.Text(value, "uid");
            if (remote.Remove(uid, out var other))
            {
                var mapping = ContactFields.Source(value, source.Uid);
                if (!additiveOnly && mapping is null && client.HasPendingCreate(other.Object.Href))
                {
                    using var document = JsonDocument.Parse(new JsonArray(value.DeepClone()).ToJsonString());
                    var made = await client.CreateAsync(source, uid, ".ics", "text/calendar",
                        ExchangeCodec.WriteIcs("ics-aufgaben", document.RootElement).Text, cancellationToken).ConfigureAwait(false);
                    SetSource(value, source.Uid, made.Href.AbsoluteUri, made.ETag);
                    exported++; continue;
                }
                var remoteChanged = mapping?["etag"]?.GetValue<string>() != observedEtags[other.Object.Href];
                var localChanged = SyncBaseline.Dirty(value, mapping, Fields, remoteChanged ? null : other.Data);
                if (additiveOnly)
                {
                    if ((other.Data["geaendert"]?.GetValue<long>() ?? 0) > (value["geaendert"]?.GetValue<long>() ?? 0)) CopyTask(value, other.Data);
                    SetSource(value, source.Uid, other.Object.Href.AbsoluteUri, other.Object.ETag, other.Data);
                    continue;
                }
                if (!additiveOnly && localChanged && remoteChanged)
                {
                    var clone = value.DeepClone().AsObject(); clone["id"] = Guid.NewGuid().ToString("N");
                    clone["uid"] = $"mag-task-{Guid.NewGuid():N}@magnolie-organizer";
                    clone.Remove("syncQuellen"); clone["sync"] = false; clone["syncKalenderUid"] = source.Uid;
                    local.Add(clone);
                    CopyTask(value, other.Data); SetSource(value, source.Uid, other.Object.Href.AbsoluteUri, other.Object.ETag);
                    conflicts++;
                }
                else if (remoteChanged || additiveOnly)
                {
                    CopyTask(value, other.Data); SetSource(value, source.Uid, other.Object.Href.AbsoluteUri, other.Object.ETag); updated++;
                }
                else if (localChanged)
                {
                    var text = ExchangeCodec.ReplaceCalendarTask(other.Object.Text, value);
                    var changed = await client.UpdateAsync(other.Object.Href, other.Object.ETag, "text/calendar", text, cancellationToken).ConfigureAwait(false);
                    RefreshResource(remote, changed, text);
                    SetSource(value, source.Uid, changed.Href.AbsoluteUri, changed.ETag); updated++;
                }
                else SetSource(value, source.Uid, other.Object.Href.AbsoluteUri, other.Object.ETag);
                continue;
            }
            if (additiveOnly) { (value["syncQuellen"] as JsonObject)?.Remove(source.Uid); continue; }
            if (!additiveOnly && ContactFields.Source(value, source.Uid) is { } missingMapping &&
                !SyncBaseline.Dirty(value, missingMapping, Fields))
            {
                local.Remove(value); deleted++; continue;
            }
            if (!additiveOnly)
            {
                using var document = JsonDocument.Parse(new JsonArray(value.DeepClone()).ToJsonString());
                var text = ExchangeCodec.WriteIcs("ics-aufgaben", document.RootElement).Text;
                var made = await client.CreateAsync(source, uid, ".ics", "text/calendar", text, cancellationToken).ConfigureAwait(false);
                SetSource(value, source.Uid, made.Href.AbsoluteUri, made.ETag); exported++;
            }
        }
        if (!additiveOnly) foreach (var tombstone in dead.OfType<JsonObject>().ToArray())
        {
            var uid = ContactFields.Text(tombstone, "uid");
            if (remote.Remove(uid, out var other))
            {
                var remaining = ExchangeCodec.RemoveCalendarTask(other.Object.Text, uid);
                if (remaining is null) await client.DeleteAsync(other.Object.Href, other.Object.ETag, cancellationToken).ConfigureAwait(false);
                else
                {
                    var changed = await client.UpdateAsync(other.Object.Href, other.Object.ETag, "text/calendar", remaining, cancellationToken).ConfigureAwait(false);
                    RefreshResource(remote, changed, remaining);
                }
                deleted++;
            }
            var sources = tombstone["syncQuellen"] as JsonObject;
            sources?.Remove(source.Uid);
            if (sources is null || sources.Count == 0) dead.Remove(tombstone);
            else if (tombstone["syncKalenderUid"]?.GetValue<string>() is not string owner || owner.Length == 0 || owner == source.Uid)
                tombstone["syncKalenderUid"] = sources.FirstOrDefault(item =>
                    NextcloudDavSelection.IsCalendar(item.Key)).Key ?? "";
        }
        foreach (var other in remote.Values)
        {
            var value = other.Data.DeepClone().AsObject(); value["id"] = Guid.NewGuid().ToString("N");
            value["geaendert"] = Math.Max(value["geaendert"]?.GetValue<long>() ?? 0, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            SetSource(value, source.Uid, other.Object.Href.AbsoluteUri, other.Object.ETag); local.Add(value); imported++;
        }
        var clean = local.OfType<JsonObject>().Where(value =>
            ContactFields.Source(value, source.Uid) is { } mapping && !SyncBaseline.Dirty(value, mapping, Fields)).ToArray();
        GesamtarchivService.NormalizeTaskGraph(local);
        // Internal sibling renumbering is not a new user edit; retain already-dirty baselines.
        foreach (var value in clean) ContactFields.Source(value, source.Uid)!["inhaltSha256"] = SyncBaseline.Hash(value, Fields);
        return new NextcloudTaskResult(local, dead, imported, exported, updated, deleted, conflicts);
    }

    private static void SetSource(JsonObject value, string source, string id, string etag, JsonObject? baseline = null)
    {
        var all = value["syncQuellen"] as JsonObject ?? new JsonObject(); value["syncQuellen"] = all;
        all[source] = new JsonObject { ["id"] = id, ["etag"] = etag, ["geaendert"] = value["geaendert"]?.DeepClone(), ["eigen"] = true,
            ["inhaltFormat"] = "windows-1", ["inhaltSha256"] = SyncBaseline.Hash(baseline ?? value, Fields) };
        value["syncKalenderUid"] = source; value["sync"] = true;
    }

    private static void CopyTask(JsonObject target, JsonObject source)
    {
        foreach (var key in target.Select(item => item.Key).Where(key => key.StartsWith("ics", StringComparison.Ordinal) && !source.ContainsKey(key)).ToArray()) target.Remove(key);
        foreach (var item in source) if (item.Key is not ("id" or "syncQuellen" or "sync")) target[item.Key] = item.Value?.DeepClone();
    }

    private static void RefreshResource(Dictionary<string, (NextcloudDavObject Object, JsonObject Data)> remote,
        NextcloudDavObject changed, string text)
    {
        foreach (var pair in remote.Where(pair => pair.Value.Object.Href == changed.Href).ToArray())
            remote[pair.Key] = (changed with { Text = text }, pair.Value.Data);
    }
}
