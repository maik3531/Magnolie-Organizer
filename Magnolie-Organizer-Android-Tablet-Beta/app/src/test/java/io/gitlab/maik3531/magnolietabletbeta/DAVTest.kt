package io.gitlab.maik3531.magnolietabletbeta

import java.net.URI
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test

private class DavScriptTransport(vararg responses: BoundedHttpResponse) : BoundedHttpTransport {
    val requests = mutableListOf<BoundedHttpRequest>()
    private val responses = responses.toMutableList()
    override fun send(request: BoundedHttpRequest, cancellation: DavCancellation): BoundedHttpResponse {
        cancellation.check()
        requests.add(request)
        if (responses.isEmpty()) throw DavException("unexpected_request")
        return responses.removeAt(0)
    }
}

class DAVTest {
    private val base = "https://cloud.example/nextcloud"
    private val collection = URI("https://cloud.example/calendars/person/personal/")
    private val item = collection.resolve("item.ics")
    private fun client(transport: BoundedHttpTransport, accountType: DavAccountType = DavAccountType.NEXTCLOUD) =
        DavClient(base, "person", "fixture-only", accountType, transport)
    private fun xml(content: String) = BoundedHttpResponse(207, body = ("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\" xmlns:a=\"urn:ietf:params:xml:ns:carddav\">$content</d:multistatus>").toByteArray())
    private fun row(href: String, props: String, status: String = "200 OK") =
        "<d:response><d:href>$href</d:href><d:propstat><d:prop>$props</d:prop><d:status>HTTP/1.1 $status</d:status></d:propstat></d:response>"
    private fun expect(code: String, status: Int? = null, action: () -> Unit) {
        try { action(); fail("Expected $code") }
        catch (error: DavException) { assertEquals(code, error.code); if (status != null) assertEquals(status, error.status) }
    }

    @Test fun invalidConfigurationAndOriginNeverReachTransport() {
        val transport = DavScriptTransport()
        for (server in listOf("http://cloud.example", "https://user:secret@cloud.example", "https://cloud.example/?", "https://cloud.example/#", "https://cloud.example:0", "https://cloud.example:70000", "https://cloud.example\\evil")) {
            expect("invalid_configuration") { DavClient(server, "person", "fixture", transport = transport) }
        }
        for (user in listOf("", "person:other", "person\nother", "x".repeat(257))) {
            expect("invalid_configuration") { DavClient(base, user, "fixture", transport = transport) }
        }
        val client = client(transport)
        for (href in listOf("https://evil.example/item", "http://cloud.example/item", "//evil.example/item", "https://cloud.example:8443/item", "https://person@cloud.example/item", "/item?", "/item#", "/item\\evil", "/item\n")) {
            expect("dav_origin_rejected") { client.sameOrigin(href) }
        }
        assertEquals(item, client.sameOrigin("../personal/item.ics", collection))
        assertTrue(transport.requests.isEmpty())
    }

    @Test fun discoveryUsesPrincipalHomeCollectionsAndCanonicalSourceIdentity() {
        val transport = DavScriptTransport(
            xml(row("/.well-known/caldav", "<d:current-user-principal><d:href>/principals/person/</d:href></d:current-user-principal>")),
            xml(row("/principals/person/", "<c:calendar-home-set><d:href>/calendars/person/</d:href></c:calendar-home-set>")),
            xml(row("/calendars/person/", "<d:resourcetype><d:collection/></d:resourcetype>") +
                row(collection.toString(), "<d:displayname>Persönlich &amp; Familie</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:sync-token>token-1</d:sync-token><c:supported-calendar-component-set><c:comp name=\"VEVENT\"/><c:comp name=\"VTODO\"/></c:supported-calendar-component-set>") +
                row("/calendars/person/events/", "<d:displayname>Ereignisse</d:displayname><d:resourcetype><c:calendar/></d:resourcetype><c:supported-calendar-component-set><c:comp name=\"VEVENT\"/></c:supported-calendar-component-set>"))
        )
        val collections = client(transport).collections(DavKind.CALENDAR)
        assertEquals(listOf("Ereignisse", "Persönlich & Familie"), collections.map { it.name })
        assertEquals(listOf(false, true), collections.map { it.supportsVtodo })
        assertEquals(collection, collections[1].href)
        assertEquals("token-1", collections[1].syncToken)
        assertEquals("nextcloud-calendar:6541706891c0a0615cbaad7ae060941cecf7aec6e453a3ed28f8785050229ae4", collections[1].uid)
        assertEquals(listOf("PROPFIND", "PROPFIND", "PROPFIND"), transport.requests.map { it.method })
        assertEquals(listOf("0", "0", "1"), transport.requests.map { it.headers["Depth"] })
        assertEquals("https://cloud.example/.well-known/caldav", transport.requests[0].uri.toString())
        assertEquals("https://cloud.example/principals/person/", transport.requests[1].uri.toString())
        assertTrue(transport.requests.all { it.headers["Authorization"] == "Basic cGVyc29uOmZpeHR1cmUtb25seQ==" })
    }

    @Test fun genericCardDavAndNextcloudFallback() {
        val home = "https://cloud.example/addressbooks/person/"
        val href = URI(home + "contacts/")
        val transport = DavScriptTransport(BoundedHttpResponse(404),
            xml(row("/nextcloud/", "<a:addressbook-home-set><d:href>$home</d:href></a:addressbook-home-set>")),
            xml(row(href.toString(), "<d:resourcetype><a:addressbook/></d:resourcetype><d:displayname>Kontakte</d:displayname>")))
        val collections = client(transport, DavAccountType.GENERIC_DAV).collections(DavKind.ADDRESSBOOK)
        assertEquals(1, collections.size)
        assertFalse(collections[0].supportsVtodo)
        assertTrue(collections[0].uid.startsWith("generic-dav-addressbook:"))
        assertNotEquals(collections[0].uid, DavClient.sourceId(DavKind.ADDRESSBOOK, href))
        assertEquals(base + "/", transport.requests[1].uri.toString())
        val fallback = DavScriptTransport(BoundedHttpResponse(404), BoundedHttpResponse(405))
        val userClient = DavClient(base, "a/b ä", "fixture", transport = fallback)
        assertTrue(userClient.home(DavKind.CALENDAR).toString().endsWith("/remote.php/dav/calendars/a%2Fb%20%C3%A4/"))
        assertTrue(fallback.requests[1].uri.toString().endsWith("/principals/users/a%2Fb%20%C3%A4/"))
    }

    @Test fun crossOriginRedirectNeverSendsAuthorizationToTarget() {
        val transport = DavScriptTransport(BoundedHttpResponse(307, mapOf("Location" to "https://evil.example/dav/")))
        expect("dav_origin_rejected") { client(transport).report(collection, DavKind.CALENDAR) }
        assertEquals(1, transport.requests.size)
        assertEquals("cloud.example", transport.requests[0].uri.host)
    }

    @Test fun rejectedDiscoveryReferenceFallsBackOnlyToConfiguredOrigin() {
        val transport = DavScriptTransport(
            xml(row("/.well-known/caldav", "<d:current-user-principal><d:href>https://evil.example/principal/</d:href></d:current-user-principal>")),
            xml(row("/principal/", "<c:calendar-home-set><d:href>/calendars/person/</d:href></c:calendar-home-set>")))
        assertEquals(URI("https://cloud.example/calendars/person/"), client(transport).home(DavKind.CALENDAR))
        assertTrue(transport.requests.all { it.uri.host == "cloud.example" })
        val malformed = DavScriptTransport(BoundedHttpResponse(207, body = "<not-xml".toByteArray()))
        expect("malformed_xml") { client(malformed).home(DavKind.CALENDAR) }
        assertEquals(1, malformed.requests.size)
    }

    @Test fun sameOriginRedirectRetainsMethodBodyAndBudget() {
        val transport = DavScriptTransport(BoundedHttpResponse(301, mapOf("Location" to collection.path)), xml(""))
        assertTrue(client(transport).report(collection, DavKind.CALENDAR).isEmpty())
        assertEquals(2, transport.requests.size)
        assertArrayEquals(transport.requests[0].body, transport.requests[1].body)
        assertEquals("REPORT", transport.requests[1].method)
        assertTrue(transport.requests[1].timeoutMillis <= transport.requests[0].timeoutMillis)
        val loop = DavScriptTransport(BoundedHttpResponse(302, mapOf("location" to "/again")), BoundedHttpResponse(302, mapOf("location" to "/again")))
        expect("http_302", 302) { client(loop).report(collection, DavKind.CALENDAR) }
        assertEquals(2, loop.requests.size)
    }

    @Test fun reportsPreserveRawRecurrenceExceptionsTasksAndVcards() {
        val ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:stable-uid\nRRULE:FREQ=WEEKLY;COUNT=8\nEXDATE:20261115T090000Z\nX-MAGNOLIE-UNKNOWN:retain\nEND:VEVENT\nBEGIN:VEVENT\nUID:stable-uid\nRECURRENCE-ID:20261122T090000Z\nDTSTART:20261122T100000Z\nEND:VEVENT\nBEGIN:VTODO\nUID:task-1\nSTATUS:NEEDS-ACTION\nEND:VTODO\nEND:VCALENDAR\n"
        val transport = DavScriptTransport(xml(row(item.toString(), "<d:getetag>&quot;v1&quot;</d:getetag><c:calendar-data><![CDATA[$ics]]></c:calendar-data>")))
        assertEquals(listOf(DavResource(item, "\"v1\"", ics)), client(transport).report(collection, DavKind.CALENDAR))
        assertTrue(String(transport.requests[0].body).contains("comp-filter name=\"VCALENDAR\""))
        assertEquals(DavClient.ITEM_LIMIT, transport.requests[0].maxResponseBytes)
        val href = URI("https://cloud.example/contacts/person/card.vcf")
        val card = "BEGIN:VCARD\nVERSION:4.0\nUID:contact-1\nFN:Änne & Team\nBDAY:20000102\nEND:VCARD"
        val cards = DavScriptTransport(xml(row(href.toString(), "<d:getetag>W/&quot;revision&quot;</d:getetag><a:address-data><![CDATA[$card]]></a:address-data>")))
        assertEquals(listOf(DavResource(href, "W/\"revision\"", card)), client(cards).report(URI("https://cloud.example/contacts/person/"), DavKind.ADDRESSBOOK))
    }

    @Test fun partialMissingAndOutOfCollectionReportsFailClosed() {
        for (response in listOf(xml(row(item.toString(), "<c:calendar-data>BEGIN:VCALENDAR</c:calendar-data>", "404 Not Found")),
            xml("<d:response><d:href>$item</d:href></d:response>"),
            BoundedHttpResponse(207, body = "<d:other xmlns:d=\"DAV:\"/>".toByteArray()))) {
            expect("partial_multistatus") { client(DavScriptTransport(response)).report(collection, DavKind.CALENDAR) }
        }
        expect("incomplete_report") { client(DavScriptTransport(xml(row(item.toString(), "<d:getetag>v1</d:getetag>")))).report(collection, DavKind.CALENDAR) }
        for (href in listOf("/calendars/person/other/item.ics", "/calendars/person/personal/../other/item.ics", "/calendars/person/personal/%2e%2e/other/item.ics", "/calendars/person/personalish/item.ics")) {
            expect("report_outside_collection") { client(DavScriptTransport(xml(row(href, "<c:calendar-data>BEGIN:VCALENDAR</c:calendar-data>")))).report(collection, DavKind.CALENDAR) }
        }
        val duplicate = row(item.toString(), "<c:calendar-data>BEGIN:VCALENDAR</c:calendar-data>")
        expect("report_outside_collection") { client(DavScriptTransport(xml(duplicate + duplicate))).report(collection, DavKind.CALENDAR) }
        expect("response_too_large") { client(DavScriptTransport(xml(duplicate.repeat(DavClient.LIST_LIMIT + 1)))).report(collection, DavKind.CALENDAR) }
    }

    @Test fun xmlEntitiesDoctypesMalformedEncodingsAndExcessiveDepthFailClosed() {
        val fixtures = listOf(
            "<!DOCTYPE x [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<!DOCTYPE x [<!ENTITY x 'amplify'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<d:multistatus xmlns:d='DAV:'><d:response></d:multistatus>",
            "<d:multistatus xmlns:d='DAV:'>" + "<d:x>".repeat(65) + "</d:x>".repeat(65) + "</d:multistatus>",
            "\u0000<d:multistatus xmlns:d='DAV:'/>")
        for (fixture in fixtures) expect("malformed_xml") { client(DavScriptTransport(BoundedHttpResponse(207, body = fixture.toByteArray()))).report(collection, DavKind.CALENDAR) }
        expect("malformed_xml") { client(DavScriptTransport(BoundedHttpResponse(207, body = byteArrayOf(0xff.toByte(), 0xfe.toByte())))).report(collection, DavKind.CALENDAR) }
    }

    @Test fun putCreateDeleteUseConditionalHeadersAndPreserveBody() {
        val transport = DavScriptTransport(BoundedHttpResponse(201, mapOf("ETag" to "\"created\"")), BoundedHttpResponse(204, mapOf("etag" to "\"changed\"")), BoundedHttpResponse(204), BoundedHttpResponse(404))
        val client = client(transport)
        val ics = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:stable\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        val created = client.put(item, ics, create = true)
        val changed = client.put(item, ics, etag = created)
        assertTrue(client.delete(item, changed)); assertFalse(client.delete(item, changed))
        assertEquals("\"created\"", created); assertEquals("\"changed\"", changed)
        assertEquals(listOf("PUT", "PUT", "DELETE", "DELETE"), transport.requests.map { it.method })
        assertEquals("*", transport.requests[0].headers["If-None-Match"])
        assertNull(transport.requests[0].headers["If-Match"])
        assertEquals(created, transport.requests[1].headers["If-Match"])
        assertEquals(changed, transport.requests[2].headers["If-Match"])
        assertArrayEquals(ics.toByteArray(), transport.requests[0].body)
    }

    @Test fun missingEtagsWildcardAndLocalAttachmentsFailBeforeNetwork() {
        val transport = DavScriptTransport()
        val client = client(transport)
        expect("missing_etag") { client.put(item, "BEGIN:VCALENDAR") }
        for (etag in listOf(" ", "*", "v1\r\nInjected: header")) expect("missing_etag") { client.delete(item, etag) }
        for (attachment in listOf("ATTACH:file:///private/file", "ATTACH;FMTTYPE=\"image:png\":/private/file", "ATTACH;VALUE=URI:fi\r\n le:///private/file", "ATTACH:C:\\private\\file", "ATTACH:~/private/file")) {
            expect("local_attachment") { client.put(item, "BEGIN:VCALENDAR\r\n$attachment\r\nEND:VCALENDAR", create = true) }
        }
        assertTrue(transport.requests.isEmpty())
    }

    @Test fun authenticationPermissionAndConflictsNeverReturnSuccess() {
        for ((status, code) in listOf(401 to "unauthorized", 403 to "forbidden", 409 to "conflict", 412 to "conflict", 500 to "http_500")) {
            val transport = DavScriptTransport(BoundedHttpResponse(status))
            expect(code, status) { client(transport).put(item, "BEGIN:VCALENDAR", etag = "\"old\"") }
            assertEquals(1, transport.requests.size)
        }
        expect("conflict", 412) { client(DavScriptTransport(BoundedHttpResponse(412))).delete(item, "\"old\"") }
        expect("response_too_large") { client(DavScriptTransport(BoundedHttpResponse(201, body = ByteArray(DavClient.XML_LIMIT + 1)))).put(item, "BEGIN:VCALENDAR", create = true) }
    }

    @Test fun cancellationBeforeRequestNeverReachesTransport() {
        val transport = DavScriptTransport()
        val cancellation = DavCancellation().apply { cancel() }
        try { client(transport).report(collection, DavKind.CALENDAR, cancellation); fail("Expected cancellation") }
        catch (_: CancellationException) { }
        assertTrue(transport.requests.isEmpty())
    }

    private class TlsFixture : AutoCloseable {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").build()
        val serverCertificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientCertificates = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        val server = MockWebServer().apply { useHttps(serverCertificates.sslSocketFactory(), false); start() }
        fun transport(): OkHttpBoundedTransport {
            val client = OkHttpClient.Builder().sslSocketFactory(clientCertificates.sslSocketFactory(), clientCertificates.trustManager)
                .build()
            return OkHttpBoundedTransport(client)
        }
        fun uri(path: String = "/dav/") = server.url(path).toUri()
        override fun close() { server.close() }
    }

    @Test fun realTlsTransportSendsDavMethodsAndReturnsRedirectWithoutFollowing() {
        TlsFixture().use { tls ->
            tls.server.enqueue(MockResponse().setResponseCode(207).setBody("<multistatus/>"))
            val body = "<propfind/>".toByteArray()
            val response = tls.transport().send(BoundedHttpRequest(tls.uri(), "PROPFIND", mapOf("Depth" to "1"), body), DavCancellation())
            assertEquals(207, response.status)
            val request = tls.server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("PROPFIND", request.method); assertEquals("1", request.getHeader("Depth")); assertArrayEquals(body, request.body.readByteArray())
            tls.server.enqueue(MockResponse().setResponseCode(307).setHeader("Location", "https://evil.example/dav/"))
            val redirect = tls.transport().send(BoundedHttpRequest(tls.uri(), "REPORT", body = "<query/>".toByteArray()), DavCancellation())
            assertEquals(307, redirect.status)
            assertEquals(2, tls.server.requestCount)
            assertEquals("REPORT", tls.server.takeRequest(2, TimeUnit.SECONDS)!!.method)
        }
    }

    @Test fun realTlsTransportEnforcesStreamingLimitAndWallTimeout() {
        TlsFixture().use { tls ->
            tls.server.enqueue(MockResponse().setChunkedBody("123456789", 2))
            expect("response_too_large") { tls.transport().send(BoundedHttpRequest(tls.uri(), maxResponseBytes = 8), DavCancellation()) }
            tls.server.enqueue(MockResponse().setBody("123456789"))
            expect("response_too_large") { tls.transport().send(BoundedHttpRequest(tls.uri(), maxResponseBytes = 8), DavCancellation()) }
            tls.server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
            val started = System.nanoTime()
            expect("timeout") { tls.transport().send(BoundedHttpRequest(tls.uri(), timeoutMillis = 200), DavCancellation()) }
            assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 4000)
        }
    }

    @Test fun realTlsTransportRejectsUntrustedAndWrongHostnameCertificates() {
        TlsFixture().use { tls ->
            tls.server.enqueue(MockResponse().setBody("not accepted"))
            expect("transport_error") { OkHttpBoundedTransport().send(BoundedHttpRequest(tls.uri(), timeoutMillis = 2000), DavCancellation()) }
            tls.server.enqueue(MockResponse().setBody("not accepted"))
            val wrongHost = URI(tls.uri().toString().replace("localhost", "127.0.0.1"))
            expect("transport_error") { tls.transport().send(BoundedHttpRequest(wrongHost, timeoutMillis = 2000), DavCancellation()) }
            assertEquals(0, tls.server.requestCount)
        }
    }

    @Test fun realTlsCancellationAbortsBlockedRead() {
        TlsFixture().use { tls ->
            tls.server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
            val cancellation = DavCancellation()
            val executor = Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit<Boolean> {
                    try { tls.transport().send(BoundedHttpRequest(tls.uri(), timeoutMillis = 5000), cancellation); false }
                    catch (_: CancellationException) { true }
                }
                assertNotNull(tls.server.takeRequest(3, TimeUnit.SECONDS))
                cancellation.cancel()
                assertTrue(result.get(3, TimeUnit.SECONDS))
            } finally { cancellation.cancel(); executor.shutdownNow() }
        }
    }
}
