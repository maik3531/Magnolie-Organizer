package io.gitlab.maik3531.magnolietabletbeta

import java.io.ByteArrayOutputStream
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.CancellationException
import java.util.concurrent.TimeUnit
import javax.xml.parsers.SAXParserFactory
import org.xml.sax.Attributes
import org.xml.sax.InputSource
import org.xml.sax.SAXException
import org.xml.sax.XMLReader
import org.xml.sax.helpers.DefaultHandler
import okhttp3.RequestBody.Companion.toRequestBody

/** Safe error codes contain neither account secrets nor remote record contents. */
class DavException(val code: String, val status: Int? = null) : Exception(code)

/** Cancellation disconnects an active socket, including a blocked upload or read. */
class DavCancellation {
    private val lock = Any()
    private var cancelled = false
    private val callbacks = mutableSetOf<() -> Unit>()
    fun cancel() {
        val current = synchronized(lock) {
            if (cancelled) return
            cancelled = true
            callbacks.toList().also { callbacks.clear() }
        }
        current.forEach { it() }
    }
    fun check() {
        if (synchronized(lock) { cancelled } || Thread.currentThread().isInterrupted) throw CancellationException()
    }
    internal fun register(callback: () -> Unit): () -> Unit {
        val invoke = synchronized(lock) { if (cancelled) true else { callbacks.add(callback); false } }
        if (invoke) callback()
        return { synchronized(lock) { callbacks.remove(callback) }; Unit }
    }
}

class BoundedHttpRequest(
    val uri: URI,
    val method: String = "GET",
    val headers: Map<String, String> = emptyMap(),
    val body: ByteArray = byteArrayOf(),
    val timeoutMillis: Long = 30_000,
    val maxResponseBytes: Int = DavClient.XML_LIMIT
)
class BoundedHttpResponse(val status: Int, headers: Map<String, String> = emptyMap(), val body: ByteArray = byteArrayOf()) {
    val headers: Map<String, String> = headers.mapKeys { it.key.lowercase(Locale.ROOT) }
}
fun interface BoundedHttpTransport {
    /** Blocking operation. Invoke on a background executor, never Android's main thread. */
    fun send(request: BoundedHttpRequest, cancellation: DavCancellation): BoundedHttpResponse
}

/** OkHttp supports real PROPFIND/REPORT without reflection or method-override headers.
 * Its default TLS trust and hostname verification remain intact. Redirects, cookies and cache
 * are disabled; cancellation aborts the complete call, including DNS/connect/upload/read.
 */
class OkHttpBoundedTransport internal constructor(client: okhttp3.OkHttpClient) : BoundedHttpTransport {
    constructor() : this(okhttp3.OkHttpClient())
    private val client = client.newBuilder()
        .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .cookieJar(okhttp3.CookieJar.NO_COOKIES).cache(null)
        .connectTimeout(60, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS).callTimeout(60, TimeUnit.SECONDS)
        .build()

    override fun send(request: BoundedHttpRequest, cancellation: DavCancellation): BoundedHttpResponse {
        cancellation.check()
        requireHttps(request.uri, allowQuery = true)
        if (request.timeoutMillis !in 1..60_000 || request.maxResponseBytes !in 1..DavClient.ITEM_LIMIT ||
            request.body.size > DavClient.ITEM_LIMIT) throw DavException("invalid_configuration")
        val builder = okhttp3.Request.Builder().url(request.uri.toASCIIString())
        for ((name, value) in request.headers) {
            if (name.any { it <= ' ' || it == ':' || it == '\u007f' } || value.any { it == '\r' || it == '\n' }) throw DavException("invalid_header")
            builder.header(name, value)
        }
        // Avoid transparent compression: the byte limit applies to the actual returned payload.
        builder.header("Accept-Encoding", "identity")
        val needsBody = request.body.isNotEmpty() || request.method in setOf("POST", "PUT", "PATCH", "PROPPATCH", "REPORT", "PROPFIND")
        val body = if (needsBody) request.body.toRequestBody(null) else null
        val call = client.newCall(builder.method(request.method, body).build())
        call.timeout().timeout(request.timeoutMillis, TimeUnit.MILLISECONDS)
        val unregister = cancellation.register { call.cancel() }
        try {
            call.execute().use { response ->
                cancellation.check()
                val responseBody = response.body
                if ((responseBody?.contentLength() ?: -1) > request.maxResponseBytes) throw DavException("response_too_large")
                val output = ByteArrayOutputStream()
                responseBody?.byteStream()?.use { stream ->
                    val buffer = ByteArray(65_536)
                    while (true) {
                        cancellation.check()
                        val count = stream.read(buffer, 0, minOf(buffer.size, request.maxResponseBytes + 1 - output.size()))
                        if (count < 0) break
                        if (count == 0) continue
                        if (count > request.maxResponseBytes - output.size()) throw DavException("response_too_large")
                        output.write(buffer, 0, count)
                    }
                }
                cancellation.check()
                val headers = response.headers.names().associateWith { response.header(it).orEmpty() }
                return BoundedHttpResponse(response.code, headers, output.toByteArray())
            }
        } catch (error: Exception) {
            cancellation.check()
            if (error is DavException) throw error
            if (error is java.io.InterruptedIOException) throw DavException("timeout")
            // Platform exceptions can contain request details; expose a bounded safe code instead.
            throw DavException("transport_error")
        } finally { unregister() }
    }

}

enum class DavKind(val wireName: String) { CALENDAR("calendar"), ADDRESSBOOK("addressbook") }
enum class DavAccountType(val wireName: String) { NEXTCLOUD("nextcloud"), GENERIC_DAV("generic-dav") }
data class DavCollection(val uid: String, val name: String, val href: URI, val kind: DavKind, val supportsVtodo: Boolean, val syncToken: String?)
data class DavResource(val href: URI, val etag: String, val data: String)

/** Resource transfer is not a sync coordinator: local merge/deletion/save acknowledgement is separate. */
class DavClient(
    server: String, username: String, private val password: String,
    val accountType: DavAccountType = DavAccountType.NEXTCLOUD,
    private val transport: BoundedHttpTransport = OkHttpBoundedTransport(),
    timeoutMillis: Long = 60_000
) {
    val server: URI = canonicalServer(server)
    val username: String = username.trim().also { user ->
        if (user.isEmpty() || user.codePointCount(0, user.length) > 256 || user.contains(':') || user.any { it < ' ' || it == '\u007f' }) throw DavException("invalid_configuration")
    }
    private val timeoutMillis = timeoutMillis.coerceAtMost(60_000).also { if (it <= 0) throw DavException("invalid_configuration") }

    fun sameOrigin(value: String, relativeTo: URI = URI(server.toASCIIString() + "/")): URI {
        try {
            if (value.contains('\\') || value.any { it < ' ' }) throw DavException("dav_origin_rejected")
            val target = relativeTo.resolve(value)
            requireHttps(target, allowQuery = false)
            if (!target.host.equals(server.host, ignoreCase = true) || effectivePort(target) != effectivePort(server)) throw DavException("dav_origin_rejected")
            val authority = authority(server)
            val path = target.rawPath.orEmpty()
            return URI("https://$authority$path").normalize()
        } catch (error: DavException) {
            throw DavException("dav_origin_rejected")
        } catch (error: IllegalArgumentException) { throw DavException("dav_origin_rejected") }
    }

    private fun request(method: String, uri: URI, body: ByteArray = byteArrayOf(), headers: Map<String, String> = emptyMap(),
                        limit: Int = XML_LIMIT, expected: Set<Int>, cancellation: DavCancellation): Pair<BoundedHttpResponse, URI> {
        var target = sameOrigin(uri.toASCIIString())
        val authenticated = headers + mapOf("Authorization" to "Basic " + StandardBase64.encode("$username:$password".toByteArray(Charsets.UTF_8)), "User-Agent" to "Magnolie-Organizer-Tablet/2.0.30")
        val started = System.nanoTime()
        repeat(2) { attempt ->
            cancellation.check()
            val remaining = timeoutMillis - TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)
            if (remaining <= 0) throw DavException("timeout")
            val response = transport.send(BoundedHttpRequest(target, method, authenticated, body, remaining, limit), cancellation)
            cancellation.check()
            if (TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) >= timeoutMillis) throw DavException("timeout")
            if (response.body.size > limit) throw DavException("response_too_large")
            if (response.status in 300..399) {
                val location = response.headers["location"]
                if (attempt != 0 || location == null) throw DavException("http_${response.status}", response.status)
                target = sameOrigin(location, target)
            } else {
                when (response.status) {
                    401 -> throw DavException("unauthorized", 401)
                    403 -> throw DavException("forbidden", 403)
                    409, 412 -> throw DavException("conflict", response.status)
                }
                if (response.status !in expected) throw DavException("http_${response.status}", response.status)
                return response to target
            }
        }
        throw DavException("invalid_response")
    }

    private fun propfind(uri: URI, properties: String, depth: String = "0", cancellation: DavCancellation): Pair<List<DavRow>, URI> {
        val body = "<d:propfind xmlns:d=\"DAV:\" xmlns:c=\"$CAL\" xmlns:a=\"$CARD\"><d:prop>$properties</d:prop></d:propfind>"
        val (response, finalUri) = request("PROPFIND", uri, body.toByteArray(Charsets.UTF_8), mapOf("Depth" to depth, "Content-Type" to "application/xml; charset=utf-8"), expected = setOf(207), cancellation = cancellation)
        return DavXml.rows(response.body, strict = false) to finalUri
    }

    fun home(kind: DavKind, cancellation: DavCancellation = DavCancellation()): URI {
        val calendar = kind == DavKind.CALENDAR
        val tag = if (calendar) "c:calendar-home-set" else "a:addressbook-home-set"
        val homeKey = (if (calendar) CAL else CARD) + "|" + (if (calendar) "calendar-home-set" else "addressbook-home-set")
        val known = URI("https://${authority(server)}/.well-known/" + if (calendar) "caldav" else "carddav")
        val user = encodeSegment(username)
        val fallback = if (accountType == DavAccountType.NEXTCLOUD) sameOrigin(server.toASCIIString() + "/remote.php/dav/principals/users/$user/") else URI(server.toASCIIString() + "/")
        for (target in listOf(known, fallback)) {
            try {
                val (rows, finalUri) = propfind(target, "<d:current-user-principal/><$tag/>", cancellation = cancellation)
                val row = rows.firstOrNull() ?: throw DavException("partial_multistatus")
                row.properties[homeKey]?.child(DAV, "href")?.text?.takeIf { it.isNotEmpty() }?.let { return sameOrigin(it, finalUri) }
                row.properties["$DAV|current-user-principal"]?.child(DAV, "href")?.text?.takeIf { it.isNotEmpty() }?.let {
                    val principal = sameOrigin(it, finalUri)
                    val (principalRows, principalUri) = propfind(principal, "<$tag/>", cancellation = cancellation)
                    principalRows.firstOrNull()?.properties?.get(homeKey)?.child(DAV, "href")?.text?.takeIf { it.isNotEmpty() }?.let { home -> return sameOrigin(home, principalUri) }
                }
            } catch (error: DavException) {
                if (error.code != "dav_origin_rejected" && error.status !in setOf(301, 302, 303, 307, 308, 404, 405)) throw error
            }
        }
        if (accountType != DavAccountType.NEXTCLOUD) throw DavException("dav_home_missing")
        val suffix = if (calendar) "/remote.php/dav/calendars/" else "/remote.php/dav/addressbooks/users/"
        return sameOrigin(server.toASCIIString() + suffix + user + "/")
    }

    fun collections(kind: DavKind, cancellation: DavCancellation = DavCancellation()): List<DavCollection> {
        val home = home(kind, cancellation)
        val calendar = kind == DavKind.CALENDAR
        val extra = if (calendar) "<c:supported-calendar-component-set/>" else ""
        val (rows, finalUri) = propfind(home, "<d:displayname/><d:resourcetype/><d:sync-token/>$extra", "1", cancellation)
        return rows.mapNotNull { row ->
            if (row.properties["$DAV|resourcetype"]?.child(if (calendar) CAL else CARD, kind.wireName) == null) return@mapNotNull null
            val href = sameOrigin(row.href, finalUri)
            val name = row.properties["$DAV|displayname"]?.text?.trim().orEmpty().ifEmpty { href.path.trimEnd('/').substringAfterLast('/') }
            val supported = row.properties["$CAL|supported-calendar-component-set"]
            val vtodo = supported == null || supported.children.any { it.attributes["name"].equals("VTODO", ignoreCase = true) }
            DavCollection(sourceId(kind, href, accountType), name, href, kind, calendar && vtodo, row.properties["$DAV|sync-token"]?.text)
        }.sortedWith(compareBy<DavCollection> { it.name.lowercase(Locale.ROOT) }.thenBy { it.uid })
    }

    fun report(collection: URI, kind: DavKind, cancellation: DavCancellation = DavCancellation()): List<DavResource> {
        val calendar = kind == DavKind.CALENDAR
        val namespace = if (calendar) CAL else CARD
        val query = if (calendar) "calendar-query" else "addressbook-query"
        val dataTag = if (calendar) "calendar-data" else "address-data"
        val filter = if (calendar) "<x:filter><x:comp-filter name=\"VCALENDAR\"/></x:filter>" else "<x:filter/>"
        val body = "<x:$query xmlns:d=\"DAV:\" xmlns:x=\"$namespace\"><d:prop><d:getetag/><x:$dataTag/></d:prop>$filter</x:$query>"
        val (response, finalUri) = request("REPORT", sameOrigin(collection.toASCIIString()), body.toByteArray(Charsets.UTF_8), mapOf("Depth" to "1", "Content-Type" to "application/xml; charset=utf-8"), ITEM_LIMIT, setOf(207), cancellation)
        val prefix = decodedNormalizedPath(finalUri).trimEnd('/') + "/"
        val seen = mutableSetOf<String>()
        return DavXml.rows(response.body, strict = true).map { row ->
            val raw = row.properties["$namespace|$dataTag"]?.text?.takeIf { it.isNotBlank() } ?: throw DavException("incomplete_report")
            val href = sameOrigin(row.href, finalUri)
            val decoded = decodedNormalizedPath(href)
            if (!decoded.startsWith(prefix) || !seen.add(href.toASCIIString())) throw DavException("report_outside_collection")
            DavResource(href, row.properties["$DAV|getetag"]?.text.orEmpty(), raw)
        }
    }

    fun put(href: URI, data: String, etag: String? = null, create: Boolean = false, cancellation: DavCancellation = DavCancellation()): String {
        if (!create && !validEtag(etag)) throw DavException("missing_etag")
        val body = data.toByteArray(Charsets.UTF_8)
        if (body.size > ITEM_LIMIT) throw DavException("response_too_large")
        val calendar = data.trimStart().startsWith("BEGIN:VCALENDAR", ignoreCase = true)
        if (calendar) rejectLocalAttachments(data)
        val headers = mapOf("Content-Type" to if (calendar) "text/calendar; charset=utf-8" else "text/vcard; charset=utf-8",
            (if (create) "If-None-Match" else "If-Match") to if (create) "*" else etag!!)
        return request("PUT", href, body, headers, expected = setOf(200, 201, 204), cancellation = cancellation).first.headers["etag"].orEmpty()
    }

    fun delete(href: URI, etag: String, cancellation: DavCancellation = DavCancellation()): Boolean {
        if (!validEtag(etag)) throw DavException("missing_etag")
        return request("DELETE", href, headers = mapOf("If-Match" to etag), expected = setOf(200, 204, 404), cancellation = cancellation).first.status != 404
    }

    companion object {
        const val XML_LIMIT = 2 * 1024 * 1024
        const val ITEM_LIMIT = 42 * 1024 * 1024
        const val LIST_LIMIT = 10_000
        private const val DAV = "DAV:"
        private const val CAL = "urn:ietf:params:xml:ns:caldav"
        private const val CARD = "urn:ietf:params:xml:ns:carddav"
        fun sourceId(kind: DavKind, href: URI, accountType: DavAccountType = DavAccountType.NEXTCLOUD): String {
            val hash = MessageDigest.getInstance("SHA-256").digest(href.toASCIIString().toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 0xff) }
            return "${accountType.wireName}-${kind.wireName}:$hash"
        }
        private fun validEtag(etag: String?) = !etag.isNullOrBlank() && etag.trim() != "*" && etag.none { it < ' ' || it == '\u007f' }
        private fun canonicalServer(value: String): URI {
            try {
                val trimmed = value.trim()
                if (trimmed.contains('\\') || trimmed.any { it < ' ' }) throw DavException("invalid_configuration")
                val uri = URI(trimmed)
                requireHttps(uri, allowQuery = false)
                val path = uri.rawPath.orEmpty().trimEnd('/')
                return URI("https://${authority(uri)}$path")
            } catch (error: Exception) { throw DavException("invalid_configuration") }
        }
        private fun encodeSegment(value: String): String = value.toByteArray(Charsets.UTF_8).joinToString("") { byte ->
            val int = byte.toInt() and 0xff
            if (int in 65..90 || int in 97..122 || int in 48..57 || int in listOf(45, 46, 95, 126)) int.toChar().toString() else "%%%02X".format(int)
        }
        private fun decodedNormalizedPath(uri: URI): String {
            // Normalize AFTER percent-decoding too, so encoded separators/dot segments cannot escape a collection.
            val segments = mutableListOf<String>()
            for (segment in uri.path.split('/')) {
                when (segment) {
                    "", "." -> Unit
                    ".." -> if (segments.isNotEmpty()) { segments.removeAt(segments.lastIndex) }
                    else -> segments.add(segment)
                }
            }
            return "/" + segments.joinToString("/")
        }
        private fun rejectLocalAttachments(text: String) {
            val unfolded = mutableListOf<String>()
            for (line in text.replace("\r\n", "\n").replace('\r', '\n').split('\n')) {
                if ((line.startsWith(' ') || line.startsWith('\t')) && unfolded.isNotEmpty()) unfolded[unfolded.lastIndex] += line.drop(1) else unfolded.add(line)
            }
            for (line in unfolded) {
                if (!line.startsWith("ATTACH:", true) && !line.startsWith("ATTACH;", true)) continue
                var quoted = false
                for (index in line.indices) {
                    if (line[index] == '"') quoted = !quoted
                    if (line[index] == ':' && !quoted) {
                        val value = line.substring(index + 1).trim()
                        if (value.startsWith("file:", true) || value.startsWith('/') || value.startsWith("\\\\") || value.startsWith("~/") || value.startsWith("~\\") || Regex("^[A-Za-z]:[\\\\/]").containsMatchIn(value)) throw DavException("local_attachment")
                        break
                    }
                }
            }
        }
    }
}

private fun effectivePort(uri: URI): Int = if (uri.port == -1) 443 else uri.port
private fun authority(uri: URI): String {
    val host = uri.host.lowercase(Locale.ROOT)
    return host + if (effectivePort(uri) == 443) "" else ":${uri.port}"
}
private fun requireHttps(uri: URI, allowQuery: Boolean) {
    if (!uri.isAbsolute || !uri.scheme.equals("https", true) || uri.host.isNullOrEmpty() || uri.rawUserInfo != null ||
        (!allowQuery && uri.rawQuery != null) || uri.rawFragment != null || effectivePort(uri) !in 1..65535) throw DavException("invalid_configuration")
}
private class DavNode(val key: String, val attributes: Map<String, String>) {
    val children = mutableListOf<DavNode>()
    val content = StringBuilder()
    val text: String get() = content.toString()
    fun child(namespace: String, name: String): DavNode? = children.firstOrNull { it.key == "$namespace|$name" }
}
private class DavRow(val href: String, val properties: Map<String, DavNode>)
private object DavXml {
    fun rows(data: ByteArray, strict: Boolean): List<DavRow> {
        if (data.size > DavClient.ITEM_LIMIT) throw DavException("response_too_large")
        val text = try {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString()
        } catch (error: Exception) { throw DavException("malformed_xml") }
        if (text.contains('\u0000') || text.contains("<!DOCTYPE", true) || text.contains("<!ENTITY", true)) throw DavException("malformed_xml")
        val handler = TreeHandler()
        try {
            val factory = SAXParserFactory.newInstance()
            factory.isNamespaceAware = true
            factory.isValidating = false
            val reader = factory.newSAXParser().xmlReader
            // Android Expat and JVM Xerces have different optional feature sets. UTF-8/DTD rejection
            // above plus the mandatory rejecting EntityResolver are independent of these switches.
            disableOptional(reader, "http://xml.org/sax/features/external-general-entities")
            disableOptional(reader, "http://xml.org/sax/features/external-parameter-entities")
            disableOptional(reader, "http://apache.org/xml/features/nonvalidating/load-external-dtd")
            reader.entityResolver = org.xml.sax.EntityResolver { _, _ -> throw SAXException("external_entity_rejected") }
            reader.contentHandler = handler
            reader.errorHandler = handler
            // Parse the validated UTF-8 character stream: a conflicting XML encoding declaration
            // cannot reinterpret bytes and bypass the declaration rejection above.
            reader.parse(InputSource(java.io.StringReader(text)))
        } catch (error: Exception) { throw DavException("malformed_xml") }
        val root = handler.root ?: throw DavException("malformed_xml")
        if (root.key != "DAV:|multistatus") throw DavException("partial_multistatus")
        val responses = root.children.filter { it.key == "DAV:|response" }
        if (responses.size > DavClient.LIST_LIMIT) throw DavException("response_too_large")
        return responses.map { response ->
            val href = response.child("DAV:", "href")?.text.orEmpty()
            val status = response.child("DAV:", "status")?.text
            val propstats = response.children.filter { it.key == "DAV:|propstat" }
            if (strict && (href.isEmpty() || (status == null && propstats.isEmpty()) || (status != null && !success(status)))) throw DavException("partial_multistatus")
            val props = mutableMapOf<String, DavNode>()
            for (propstat in propstats) {
                if (!success(propstat.child("DAV:", "status")?.text.orEmpty())) {
                    if (strict) throw DavException("partial_multistatus")
                    continue
                }
                val prop = propstat.child("DAV:", "prop")
                if (prop == null) { if (strict) throw DavException("partial_multistatus"); continue }
                for (child in prop.children) props[child.key] = child
            }
            DavRow(href, props)
        }
    }
    private fun disableOptional(reader: XMLReader, name: String) {
        try { reader.setFeature(name, false) } catch (_: org.xml.sax.SAXNotRecognizedException) { } catch (_: org.xml.sax.SAXNotSupportedException) { }
    }
    private fun success(status: String): Boolean {
        val parts = status.trim().split(Regex("\\s+"))
        return parts.size >= 2 && parts[0].startsWith("HTTP/") && parts[1] == "200"
    }
    private class TreeHandler : DefaultHandler() {
        var root: DavNode? = null
        private val stack = mutableListOf<DavNode>()
        private var nodes = 0
        private var chars = 0
        override fun startElement(uri: String, localName: String, qName: String, attributes: Attributes) {
            if (++nodes > 100_000 || stack.size >= 64) throw SAXException("xml_limit")
            val attrs = (0 until attributes.length).associate { attributes.getLocalName(it) to attributes.getValue(it) }
            val node = DavNode("$uri|$localName", attrs)
            if (stack.isNotEmpty()) stack.last().children.add(node) else { if (root != null) throw SAXException("xml_root"); root = node }
            stack.add(node)
        }
        override fun characters(ch: CharArray, start: Int, length: Int) {
            chars += length
            if (chars > DavClient.ITEM_LIMIT) throw SAXException("xml_limit")
            stack.lastOrNull()?.content?.append(ch, start, length)
        }
        override fun endElement(uri: String, localName: String, qName: String) { if (stack.isNotEmpty()) stack.removeAt(stack.lastIndex) }
        override fun error(exception: org.xml.sax.SAXParseException) { throw exception }
        override fun fatalError(exception: org.xml.sax.SAXParseException) { throw exception }
    }
}
