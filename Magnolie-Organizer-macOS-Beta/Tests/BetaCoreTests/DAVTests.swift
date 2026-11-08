import XCTest
@testable import BetaCore

private final class DAVScriptTransport: BoundedHTTPTransport {
    var requests: [BoundedHTTPRequest] = []
    var replies: [BoundedHTTPResponse]
    init(_ replies: [BoundedHTTPResponse]) { self.replies = replies }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        requests.append(request)
        guard !replies.isEmpty else { throw DAVError.invalidResponse }
        return replies.removeFirst()
    }
}

final class DAVTests: XCTestCase {
    private let base = "https://cloud.example/nextcloud"
    private let calendarURL = URL(string: "https://cloud.example/calendars/person/personal/")!
    private let itemURL = URL(string: "https://cloud.example/calendars/person/personal/item.ics")!

    private func client(_ transport: DAVScriptTransport, type: DAVAccountType = .nextcloud) throws -> DAVClient {
        try DAVClient(server: base, username: "person", password: "fixture-only", accountType: type, transport: transport)
    }
    private func xml(_ content: String) -> BoundedHTTPResponse {
        BoundedHTTPResponse(status: 207, body: Data("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\" xmlns:a=\"urn:ietf:params:xml:ns:carddav\">\(content)</d:multistatus>".utf8))
    }
    private func row(_ href: String, _ properties: String, status: String = "200 OK") -> String {
        "<d:response><d:href>\(href)</d:href><d:propstat><d:prop>\(properties)</d:prop><d:status>HTTP/1.1 \(status)</d:status></d:propstat></d:response>"
    }
    private func expect(_ expected: DAVError, operation: () async throws -> Void, file: StaticString = #filePath, line: UInt = #line) async {
        do { try await operation(); XCTFail("Expected \(expected)", file: file, line: line) }
        catch let error as DAVError { XCTAssertEqual(error, expected, file: file, line: line) }
        catch { XCTFail("Unexpected error type: \(type(of: error))", file: file, line: line) }
    }

    func testInvalidConfigurationAndOriginReferencesNeverReachTransport() throws {
        let transport = DAVScriptTransport([])
        for server in ["http://cloud.example", "https://user:secret@cloud.example", "https://cloud.example/?", "https://cloud.example/#", "https://cloud.example:0", "https://cloud.example:70000", "https://cloud.example\\evil"] {
            XCTAssertThrowsError(try DAVClient(server: server, username: "person", password: "fixture", transport: transport))
        }
        for user in ["", "person:other", "person\nother", String(repeating: "x", count: 257)] {
            XCTAssertThrowsError(try DAVClient(server: base, username: user, password: "fixture", transport: transport))
        }
        let client = try client(transport)
        for href in ["https://evil.example/item", "http://cloud.example/item", "//evil.example/item", "https://cloud.example:8443/item", "https://person@cloud.example/item", "/item?", "/item#", "/item\\evil", "/item\n"] {
            XCTAssertThrowsError(try client.sameOriginURL(href))
        }
        XCTAssertEqual(try client.sameOriginURL("../personal/item.ics", relativeTo: calendarURL).absoluteString,
                       "https://cloud.example/calendars/person/personal/item.ics")
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testDiscoveryUsesPrincipalHomeAndCollectionProperties() async throws {
        let transport = DAVScriptTransport([
            xml(row("/.well-known/caldav", "<d:current-user-principal><d:href>/principals/person/</d:href></d:current-user-principal>")),
            xml(row("/principals/person/", "<c:calendar-home-set><d:href>/calendars/person/</d:href></c:calendar-home-set>")),
            xml(row("/calendars/person/", "<d:resourcetype><d:collection/></d:resourcetype>") +
                row("/calendars/person/personal/", "<d:displayname>Persönlich &amp; Familie</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:sync-token>token-1</d:sync-token><c:supported-calendar-component-set><c:comp name=\"VEVENT\"/><c:comp name=\"VTODO\"/></c:supported-calendar-component-set>") +
                row("/calendars/person/events/", "<d:displayname>Ereignisse</d:displayname><d:resourcetype><c:calendar/></d:resourcetype><c:supported-calendar-component-set><c:comp name=\"VEVENT\"/></c:supported-calendar-component-set>"))
        ])
        let collections = try await client(transport).collections(for: .calendar)
        XCTAssertEqual(collections.map(\.name), ["Ereignisse", "Persönlich & Familie"])
        XCTAssertEqual(collections.map(\.supportsVtodo), [false, true])
        XCTAssertEqual(collections[1].href, calendarURL)
        XCTAssertEqual(collections[1].syncToken, "token-1")
        XCTAssertEqual(collections[1].uid, "nextcloud-calendar:6541706891c0a0615cbaad7ae060941cecf7aec6e453a3ed28f8785050229ae4")
        XCTAssertEqual(transport.requests.map(\.method), ["PROPFIND", "PROPFIND", "PROPFIND"])
        XCTAssertEqual(transport.requests.map { $0.headers["Depth"] }, ["0", "0", "1"])
        XCTAssertEqual(transport.requests[0].url.absoluteString, "https://cloud.example/.well-known/caldav")
        XCTAssertEqual(transport.requests[1].url.absoluteString, "https://cloud.example/principals/person/")
        XCTAssertEqual(transport.requests[2].url.absoluteString, "https://cloud.example/calendars/person/")
        XCTAssertTrue(transport.requests.allSatisfy { $0.headers["Authorization"] == "Basic cGVyc29uOmZpeHR1cmUtb25seQ==" })
    }

    func testGenericCardDAVDiscoveryAndSourceIdentity() async throws {
        let home = "https://cloud.example/addressbooks/person/"
        let href = URL(string: home + "contacts/")!
        let transport = DAVScriptTransport([
            BoundedHTTPResponse(status: 404),
            xml(row("/nextcloud/", "<a:addressbook-home-set><d:href>\(home)</d:href></a:addressbook-home-set>")),
            xml(row(href.absoluteString, "<d:resourcetype><a:addressbook/></d:resourcetype><d:displayname>Kontakte</d:displayname>"))
        ])
        let collections = try await client(transport, type: .genericDAV).collections(for: .addressbook)
        XCTAssertEqual(collections.count, 1)
        XCTAssertEqual(collections[0].kind, .addressbook)
        XCTAssertFalse(collections[0].supportsVtodo)
        XCTAssertTrue(collections[0].uid.hasPrefix("generic-dav-addressbook:"))
        XCTAssertNotEqual(collections[0].uid, DAVClient.sourceID(kind: .addressbook, href: href))
        XCTAssertEqual(transport.requests[1].url.absoluteString, base + "/")
    }

    func testNextcloudFallbackUsesEncodedUsername() async throws {
        let transport = DAVScriptTransport([BoundedHTTPResponse(status: 404), BoundedHTTPResponse(status: 405)])
        let client = try DAVClient(server: base, username: "a/b ä", password: "fixture", transport: transport)
        let home = try await client.home(for: .calendar)
        XCTAssertTrue(home.absoluteString.hasSuffix("/remote.php/dav/calendars/a%2Fb%20%C3%A4/"))
        XCTAssertTrue(transport.requests[1].url.absoluteString.hasSuffix("/principals/users/a%2Fb%20%C3%A4/"))
    }

    func testCrossOriginRedirectCannotSendAuthorization() async throws {
        let transport = DAVScriptTransport([BoundedHTTPResponse(status: 307, headers: ["Location": "https://evil.example/dav/"])])
        await expect(.originRejected) { _ = try await self.client(transport).report(collection: self.calendarURL, kind: .calendar) }
        XCTAssertEqual(transport.requests.count, 1)
        XCTAssertEqual(transport.requests.first?.url.host, "cloud.example")
    }

    func testRejectedDiscoveryReferenceFallsBackOnlyToConfiguredOrigin() async throws {
        let transport = DAVScriptTransport([
            xml(row("/.well-known/caldav", "<d:current-user-principal><d:href>https://evil.example/principal/</d:href></d:current-user-principal>")),
            xml(row("/nextcloud/remote.php/dav/principals/users/person/", "<c:calendar-home-set><d:href>/calendars/person/</d:href></c:calendar-home-set>"))
        ])
        let home = try await client(transport).home(for: .calendar)
        XCTAssertEqual(home.absoluteString, "https://cloud.example/calendars/person/")
        XCTAssertEqual(transport.requests.count, 2)
        XCTAssertTrue(transport.requests.allSatisfy { $0.url.host == "cloud.example" })
        let malformed = DAVScriptTransport([BoundedHTTPResponse(status: 207, body: Data("<not-xml".utf8))])
        await expect(.malformedXML) { _ = try await self.client(malformed).home(for: .calendar) }
        XCTAssertEqual(malformed.requests.count, 1)
    }

    func testOverfullResourceListingFailsInsteadOfTruncating() async throws {
        let content = row(itemURL.absoluteString, "<c:calendar-data>BEGIN:VCALENDAR</c:calendar-data>")
        let transport = DAVScriptTransport([xml(String(repeating: content, count: DAVClient.listLimit + 1))])
        await expect(.responseTooLarge) { _ = try await self.client(transport).report(collection: self.calendarURL, kind: .calendar) }
    }

    func testSameOriginRedirectRetainsMethodBodyAndHasBoundedBudget() async throws {
        let transport = DAVScriptTransport([
            BoundedHTTPResponse(status: 301, headers: ["Location": "/calendars/person/personal/"]), xml("")
        ])
        let resources = try await client(transport).report(collection: calendarURL, kind: .calendar)
        XCTAssertTrue(resources.isEmpty)
        XCTAssertEqual(transport.requests.count, 2)
        XCTAssertEqual(transport.requests[0].body, transport.requests[1].body)
        XCTAssertEqual(transport.requests[1].method, "REPORT")
        XCTAssertLessThanOrEqual(transport.requests[1].timeout, transport.requests[0].timeout)
        let loop = DAVScriptTransport([BoundedHTTPResponse(status: 302, headers: ["location": "/again"]), BoundedHTTPResponse(status: 302, headers: ["location": "/again"])])
        await expect(.httpStatus(302)) { _ = try await self.client(loop).report(collection: self.calendarURL, kind: .calendar) }
        XCTAssertEqual(loop.requests.count, 2)
    }

    func testReportPreservesRawRecurrenceTasksAndUnknownProperties() async throws {
        let ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:stable-uid\nRRULE:FREQ=WEEKLY;COUNT=8\nEXDATE:20261115T090000Z\nX-MAGNOLIE-UNKNOWN:retain\nEND:VEVENT\nBEGIN:VEVENT\nUID:stable-uid\nRECURRENCE-ID:20261122T090000Z\nDTSTART:20261122T100000Z\nEND:VEVENT\nBEGIN:VTODO\nUID:task-1\nSTATUS:NEEDS-ACTION\nEND:VTODO\nEND:VCALENDAR\n"
        let transport = DAVScriptTransport([xml(row(itemURL.absoluteString, "<d:getetag>&quot;v1&quot;</d:getetag><c:calendar-data><![CDATA[\(ics)]]></c:calendar-data>"))])
        let resources = try await client(transport).report(collection: calendarURL, kind: .calendar)
        XCTAssertEqual(resources, [DAVResource(href: itemURL, etag: "\"v1\"", data: ics)])
        let requestBody = String(data: transport.requests[0].body, encoding: .utf8)!
        XCTAssertTrue(requestBody.contains("comp-filter name=\"VCALENDAR\""))
        XCTAssertEqual(transport.requests[0].maximumResponseBytes, DAVClient.itemLimit)
    }

    func testCardDAVReportPreservesVCardAndETag() async throws {
        let href = URL(string: "https://cloud.example/contacts/person/card.vcf")!
        let card = "BEGIN:VCARD\nVERSION:4.0\nUID:contact-1\nFN:Änne &amp; Team\nBDAY:20000102\nEND:VCARD"
        let transport = DAVScriptTransport([xml(row(href.absoluteString, "<d:getetag>W/&quot;revision&quot;</d:getetag><a:address-data><![CDATA[\(card)]]></a:address-data>"))])
        let resources = try await client(transport).report(collection: URL(string: "https://cloud.example/contacts/person/")!, kind: .addressbook)
        XCTAssertEqual(resources.first?.data, card)
        XCTAssertEqual(resources.first?.etag, "W/\"revision\"")
        XCTAssertTrue(String(data: transport.requests[0].body, encoding: .utf8)!.contains("addressbook-query"))
    }

    func testPartialReportsAndMissingDataAreRejected() async throws {
        for response in [
            xml(row(itemURL.absoluteString, "<c:calendar-data>BEGIN:VCALENDAR</c:calendar-data>", status: "404 Not Found")),
            xml("<d:response><d:href>\(itemURL.absoluteString)</d:href></d:response>"),
            BoundedHTTPResponse(status: 207, body: Data("<d:other xmlns:d=\"DAV:\"/>".utf8))
        ] {
            let transport = DAVScriptTransport([response])
            await expect(.partialMultistatus) { _ = try await self.client(transport).report(collection: self.calendarURL, kind: .calendar) }
        }
        let missing = DAVScriptTransport([xml(row(itemURL.absoluteString, "<d:getetag>v1</d:getetag>"))])
        await expect(.incompleteReport) { _ = try await self.client(missing).report(collection: self.calendarURL, kind: .calendar) }
    }

    func testReportRejectsOutsideCollectionTraversalAndDuplicates() async throws {
        let data = "<c:calendar-data>BEGIN:VCALENDAR</c:calendar-data>"
        for href in ["/calendars/person/other/item.ics", "/calendars/person/personal/../other/item.ics", "/calendars/person/personal/%2e%2e/other/item.ics", "/calendars/person/personalish/item.ics"] {
            let transport = DAVScriptTransport([xml(row(href, data))])
            await expect(.reportOutsideCollection) { _ = try await self.client(transport).report(collection: self.calendarURL, kind: .calendar) }
        }
        let duplicate = DAVScriptTransport([xml(row(itemURL.absoluteString, data) + row(itemURL.absoluteString, data))])
        await expect(.reportOutsideCollection) { _ = try await self.client(duplicate).report(collection: self.calendarURL, kind: .calendar) }
    }

    func testXMLRejectsEntitiesDTDsMalformedAndExcessiveDepth() async throws {
        let fixtures = [
            "<!DOCTYPE x [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<!DOCTYPE x [<!ENTITY x 'amplify'>]><d:multistatus xmlns:d='DAV:'>&x;</d:multistatus>",
            "<d:multistatus xmlns:d='DAV:'><d:response></d:multistatus>",
            "<d:multistatus xmlns:d='DAV:'>" + String(repeating: "<d:x>", count: 65) + String(repeating: "</d:x>", count: 65) + "</d:multistatus>",
            "\0<d:multistatus xmlns:d='DAV:'/>"
        ]
        for fixture in fixtures {
            let transport = DAVScriptTransport([BoundedHTTPResponse(status: 207, body: Data(fixture.utf8))])
            await expect(.malformedXML) { _ = try await self.client(transport).report(collection: self.calendarURL, kind: .calendar) }
        }
    }

    func testPutCreateAndDeleteSendConditionalHeadersAndPreserveBodies() async throws {
        let transport = DAVScriptTransport([
            BoundedHTTPResponse(status: 201, headers: ["ETag": "\"created\""]),
            BoundedHTTPResponse(status: 204, headers: ["etag": "\"changed\""]),
            BoundedHTTPResponse(status: 204), BoundedHTTPResponse(status: 404)
        ])
        let client = try client(transport)
        let ics = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:stable\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        let created = try await client.put(href: itemURL, data: ics, create: true)
        let changed = try await client.put(href: itemURL, data: ics, etag: created)
        let deleted = try await client.delete(href: itemURL, etag: changed)
        let missing = try await client.delete(href: itemURL, etag: changed)
        XCTAssertEqual(created, "\"created\""); XCTAssertEqual(changed, "\"changed\"")
        XCTAssertTrue(deleted); XCTAssertFalse(missing)
        XCTAssertEqual(transport.requests.map(\.method), ["PUT", "PUT", "DELETE", "DELETE"])
        XCTAssertEqual(transport.requests[0].headers["If-None-Match"], "*")
        XCTAssertNil(transport.requests[0].headers["If-Match"])
        XCTAssertEqual(transport.requests[1].headers["If-Match"], created)
        XCTAssertEqual(transport.requests[2].headers["If-Match"], changed)
        XCTAssertEqual(transport.requests[0].body, Data(ics.utf8))
        XCTAssertEqual(transport.requests[0].headers["Content-Type"], "text/calendar; charset=utf-8")
    }

    func testMissingETagsHeaderInjectionAndLocalAttachmentsFailBeforeNetwork() async throws {
        let transport = DAVScriptTransport([])
        let client = try client(transport)
        await expect(.missingETag) { _ = try await client.put(href: self.itemURL, data: "BEGIN:VCALENDAR") }
        await expect(.missingETag) { _ = try await client.delete(href: self.itemURL, etag: " ") }
        await expect(.missingETag) { _ = try await client.put(href: self.itemURL, data: "BEGIN:VCALENDAR", etag: "*") }
        await expect(.missingETag) { _ = try await client.delete(href: self.itemURL, etag: "v1\r\nInjected: header") }
        for attachment in ["ATTACH:file:///private/file", "ATTACH;FMTTYPE=\"image:png\":/private/file", "ATTACH;VALUE=URI:fi\r\n le:///private/file", "ATTACH:C:\\private\\file", "ATTACH:~/private/file"] {
            await expect(.localAttachment) { _ = try await client.put(href: self.itemURL, data: "BEGIN:VCALENDAR\r\n\(attachment)\r\nEND:VCALENDAR", create: true) }
        }
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testWildcardETagWhitespaceCannotWeakenPutOrDeletePreconditions() async throws {
        let transport = DAVScriptTransport([])
        let client = try client(transport)
        for etag in ["*", " * ", "* ", " *", "  *  ", "\t*\t", " \t* \t"] {
            await expect(.missingETag) { _ = try await client.put(href: self.itemURL, data: "BEGIN:VCALENDAR", etag: etag) }
            await expect(.missingETag) { _ = try await client.delete(href: self.itemURL, etag: etag) }
        }
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testNonWildcardETagsKeepOriginalBytesForPutAndDelete() async throws {
        let etags = ["\"fixture-v1\"", " \"fixture-v1\" ", "W/\"fixture-v1\""]
        let transport = DAVScriptTransport(Array(repeating: BoundedHTTPResponse(status: 204), count: etags.count * 2))
        let client = try client(transport)
        for etag in etags {
            _ = try await client.put(href: itemURL, data: "BEGIN:VCALENDAR", etag: etag)
            _ = try await client.delete(href: itemURL, etag: etag)
        }
        XCTAssertEqual(transport.requests.compactMap { $0.headers["If-Match"] }, etags.flatMap { [$0, $0] })
    }

    func testAuthenticationPermissionAndConflictErrorsNeverReturnSuccess() async throws {
        for (status, expected) in [(401, DAVError.unauthorized), (403, .forbidden), (409, .conflict(status: 409)), (412, .conflict(status: 412)), (500, .httpStatus(500))] {
            let transport = DAVScriptTransport([BoundedHTTPResponse(status: status)])
            await expect(expected) { _ = try await self.client(transport).put(href: self.itemURL, data: "BEGIN:VCALENDAR", etag: "\"old\"") }
            XCTAssertEqual(transport.requests.count, 1)
        }
        let deletion = DAVScriptTransport([BoundedHTTPResponse(status: 412)])
        await expect(.conflict(status: 412)) { _ = try await self.client(deletion).delete(href: self.itemURL, etag: "\"old\"") }
    }

    func testInjectedTransportCannotBypassResponseSizeBound() async throws {
        let transport = DAVScriptTransport([BoundedHTTPResponse(status: 201, body: Data(repeating: 0x20, count: DAVClient.xmlLimit + 1))])
        await expect(.responseTooLarge) { _ = try await self.client(transport).put(href: self.itemURL, data: "BEGIN:VCALENDAR", create: true) }
    }

    func testURLSessionTransportRejectsNonHTTPSBeforeAnyConnection() async {
        let transport = URLSessionBoundedTransport()
        for url in ["http://localhost", "file:///tmp/no-read", "https://person:password@localhost"] {
            await expect(.invalidConfiguration) { _ = try await transport.send(BoundedHTTPRequest(url: URL(string: url)!)) }
        }
        await expect(.invalidConfiguration) { _ = try await transport.send(BoundedHTTPRequest(url: self.itemURL, timeout: 0)) }
        await expect(.invalidConfiguration) { _ = try await transport.send(BoundedHTTPRequest(url: self.itemURL, maximumResponseBytes: 0)) }
    }
}
