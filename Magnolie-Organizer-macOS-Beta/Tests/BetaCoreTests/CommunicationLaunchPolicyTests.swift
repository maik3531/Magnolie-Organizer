import XCTest
@testable import BetaCore

/// No NSWorkspace calls: tests prepare destinations, never launch external apps.
final class CommunicationLaunchPolicyTests: XCTestCase {
    private func prepare(_ command: String, _ fields: [String: Any]) throws -> CommunicationLaunchPolicy.Target {
        try CommunicationLaunchPolicy.target(command: command, fields: fields)
    }
    private func social(_ service: String, _ value: String, _ extra: [String: Any] = [:]) throws -> CommunicationLaunchPolicy.Target {
        try prepare("sozial", ["dienst": service, "wert": value, "aktionArt": "", "aktionZiel": "", "land": "Deutschland"].merging(extra) { _, new in new })
    }
    func testPublishedUiGoldenRequests() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "communication-ui-payloads", withExtension: "json", subdirectory: "Fixtures"))
        let rows = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [[String: Any]])
        XCTAssertEqual(rows.count, 15)
        for row in rows {
            let request = try Request(String(decoding: JSONSerialization.data(withJSONObject: row), as: UTF8.self))
            if row["aktionArt"] as? String == "program" {
                XCTAssertThrowsError(try prepare(request.command.rawValue, request.fields))
            } else { XCTAssertNoThrow(try prepare(request.command.rawValue, request.fields)) }
        }
        for raw in [#"{"cmd":"mail","email":"a@example.org","name":"","headers":"Bcc"}"#,
                    #"{"cmd":"karte","kontakt":{},"land":"DE","route":1}"#,
                    #"{"cmd":"sozial","dienst":"custom","wert":"https://example.org","file":"/bin/sh"}"#] {
            XCTAssertThrowsError(try Request(raw))
        }
    }
    func testActualPublishedMailPayload() throws {
        let target = try prepare("mail", ["cmd": "mail", "email": "ada@example.org", "name": "Ada Example"])
        XCTAssertEqual(target.kind, .mail)
        XCTAssertEqual(target.url.absoluteString, "mailto:ada@example.org")
        XCTAssertNoThrow(try prepare("mail", ["email": "ada+tag@example.org", "name": "Änne 100% Example"]))
        XCTAssertEqual(try prepare("mail", ["email": "ada@example.org", "name": ""]).url.absoluteString, "mailto:ada@example.org")
    }
    func testActualPublishedMapPayloadsAndPlatformAdaptation() throws {
        // Exact contact shape captured from zeigeKarte in both tagged/current UI.
        let contact: [String: Any] = ["vorname": "", "nachname": "Example, Ada", "firma": "", "strasse": "Musterweg 12", "plz": "10115", "ort": "Berlin", "region": "", "land": "", "typen": ["HOME"], "anschriften": [["strasse": "Musterweg 12", "plz": "10115", "ort": "Berlin", "region": "", "land": "", "typen": ["HOME"]]]]
        for service in ["auto", "gnome-maps", "openstreetmap", "google"] {
            for route in [false, true] {
                let target = try prepare("karte", ["cmd": "karte", "kontakt": contact, "land": "Deutschland", "dienst": service, "route": route, "absender": route ? "Alex Example\nStartweg 5\n10117 Berlin" : ""])
                XCTAssertEqual(target.kind, .map)
                let components = try XCTUnwrap(URLComponents(url: target.url, resolvingAgainstBaseURL: false))
                let query = Dictionary(uniqueKeysWithValues: (components.queryItems ?? []).map { ($0.name, $0.value ?? "") })
                let destination = "Musterweg 12, 10115 Berlin, Deutschland", origin = "Startweg 5, 10117 Berlin, Deutschland"
                switch service {
                case "google":
                    XCTAssertEqual(components.host, "www.google.com")
                    XCTAssertEqual(query[route ? "destination" : "query"], destination)
                    if route { XCTAssertEqual(query["origin"], origin) }
                case "openstreetmap":
                    XCTAssertEqual(components.host, "www.openstreetmap.org")
                    XCTAssertEqual(query[route ? "to" : "query"], destination)
                    if route { XCTAssertEqual(query["from"], origin) }
                default:
                    XCTAssertEqual(components.host, "maps.apple.com")
                    XCTAssertEqual(query[route ? "daddr" : "q"], destination)
                    if route { XCTAssertEqual(query["saddr"], origin) }
                }
                XCTAssertFalse(target.url.absoluteString.contains("Alex"))
            }
        }
    }
    func testActualPublishedWebsiteTemplateAndCalendarAttachment() throws {
        XCTAssertEqual(try social("custom", "https://example.org/calendar/item", ["aktionArt": "url", "aktionZiel": "https://example.org/calendar/item"]).url.absoluteString, "https://example.org/calendar/item")
        let target = try social("custom", "Ada & Bob", ["aktionArt": "website", "aktionZiel": "https://example.org/search?q={wert}"])
        XCTAssertEqual(URLComponents(url: target.url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "Ada & Bob")
        XCTAssertEqual(try social("telegram", "@example").url.absoluteString, "https://t.me/example")
        let nested = try social("telegram", "Ada & Bob", ["aktionArt": "website", "aktionZiel": "https://example.org/?target={ziel}"])
        XCTAssertEqual(URLComponents(url: nested.url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "https://t.me/Ada%20%26%20Bob")
        XCTAssertEqual(try social("custom", "+49 123456789", ["aktionArt": "website", "aktionZiel": "https://example.org/?number={nummer}"]).url.absoluteString, "https://example.org/?number=+49123456789")
    }
    func testActualProjectedCanonicalNationalAndExtensionPayloads() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "communication-phone-payloads", withExtension: "json", subdirectory: "Fixtures"))
        let rows = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [[String: Any]])
        XCTAssertEqual(rows.count, 9)
        for row in rows {
            let fields = try XCTUnwrap(row["request"] as? [String: Any])
            let number = try XCTUnwrap(row["expectedE164"] as? String)
            let request = try Request(String(decoding: JSONSerialization.data(withJSONObject: fields), as: UTF8.self))
            let target = try prepare(request.command.rawValue, request.fields)
            switch fields["dienst"] as? String {
            case "whatsapp": XCTAssertEqual(target.url.absoluteString, "https://wa.me/" + number.dropFirst())
            case "signal": XCTAssertEqual(target.url.absoluteString, "https://signal.me/#p/" + number)
            default: XCTAssertEqual(URLComponents(url: target.url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, number)
            }
        }
        for number in ["0049123456789", "49123456789", "+01234567", "+49123456789x12", "+49%0a123456", "+1234567890123456"] {
            XCTAssertThrowsError(try social("whatsapp", "030 12345678", ["nummer": number]))
        }
        XCTAssertThrowsError(try social("whatsapp", "030 12345678"), "No guessed native national prefix")
        XCTAssertThrowsError(try social("whatsapp", "+493012345678", ["nummer": 123]))
    }
    func testInternationalDomainAndUserSelectedHttpsPort() throws {
        let mail = try prepare("mail", ["email": "ada@bücher.example", "name": "Ada Example"])
        XCTAssertEqual(mail.url.absoluteString, "mailto:ada@b%C3%BCcher.example")
        let international = try social("custom", "https://bücher.example:8443/calendar")
        let components = try XCTUnwrap(URLComponents(url: international.url, resolvingAgainstBaseURL: false))
        XCTAssertEqual(components.port, 8443)
        // Foundation may expose the Unicode hostname or its IDNA A-label,
        // depending on SDK. Neither changes the selected host or port.
        XCTAssertTrue(["bücher.example", "xn--bcher-kva.example"].contains(components.host ?? ""))
        XCTAssertNoThrow(try social("custom", "HTTPS://example.org/calendar"))
        XCTAssertNoThrow(try social("custom", "Ada", ["aktionArt": "website", "aktionZiel": "HTTPS://example.org/{wert}"]))
        XCTAssertNoThrow(try social("custom", "https://localhost:8443/calendar"))
        XCTAssertNoThrow(try social("custom", "https://[::1]:8443/calendar"))
        for port in [1, 443, 8443, 65535] {
            XCTAssertEqual(URLComponents(url: try social("custom", "https://example.org:\(port)/").url, resolvingAgainstBaseURL: false)?.port, port)
        }
    }
    func testEverySupportedWebServiceHasBoundedHttpsDestination() throws {
        for service in ["whatsapp", "threema", "facebook", "instagram", "signal", "mastodon", "teams", "snapchat", "tiktok", "youtube", "telegram", "x", "twitter", "linkedin", "likedin", "reddit", "custom"] {
            let value: String
            switch service {
            case "whatsapp", "signal": value = "+49 123456789"
            case "mastodon": value = "@example@example.org"
            case "custom": value = "https://example.org/path"
            default: value = "example"
            }
            let target = try social(service, value)
            XCTAssertEqual(target.kind, .website); XCTAssertEqual(target.url.scheme, "https")
        }
        XCTAssertEqual(try social("whatsapp", "+1 (202) 555-0100").url.absoluteString, "https://wa.me/12025550100")
        XCTAssertEqual(try social("signal", "0049 123456789").url.absoluteString, "https://signal.me/#p/+49123456789")
    }
    func testRejectsMailListsHeadersAndInvalidTypes() {
        for email in ["a@example.org,b@example.org", "a@example.org?subject=hidden", "a@example.org\r\nBcc:b@example.org", "a%0ab@example.org", "mailto:a@example.org", "a@example.org#fragment", ".a@example.org", "a..b@example.org", "a@-example.org", "a@localhost"] {
            XCTAssertThrowsError(try prepare("mail", ["email": email, "name": "Name"]), email)
        }
        for name in ["Name\nBcc:other"] { XCTAssertThrowsError(try prepare("mail", ["email": "a@example.org", "name": name])) }
        let malformed: [[String: Any]] = [["email": 1, "name": ""], ["email": "a@example.org", "name": "", "subject": "Hidden"], ["cmd": "karte", "email": "a@example.org", "name": ""]]
        for fields in malformed { XCTAssertThrowsError(try prepare("mail", fields)) }
    }
    func testRejectsOpaqueSchemesCredentialsAndMalformedUrls() {
        for value in ["http://example.org/", "file:///tmp/test", "javascript:alert(1)", "mailto:a@example.org", "https://user@example.org/", "https://user:password@example.org/", "https://example.org:0/", "https://example.org:65536/", "https://example.org\\@evil.org/", "https://example.org/\npath", "https://example.org/%0Apath", "https://example.org/%250dpath", "https://example.org/%GG", "https://-example.org/", "https://example..org/", "https:///path"] {
            XCTAssertThrowsError(try social("custom", value), value)
        }
        for service in ["sms", "phone", "telefon", "unknown"] { XCTAssertThrowsError(try social(service, "+49123456789")) }
        for action in ["program", "programm", "exec", "file"] { XCTAssertThrowsError(try social("custom", "Ada", ["aktionArt": action, "aktionZiel": "/bin/sh"])) }
        XCTAssertThrowsError(try social("custom", "Ada", ["aktionArt": "website", "aktionZiel": "https://example.org/{unknown}"]))
        XCTAssertThrowsError(try social("custom", "Ada", ["aktionArt": "website", "aktionZiel": "file:///{wert}"]))
        XCTAssertThrowsError(try social("custom", "Ada", ["aktionArt": "website", "aktionZiel": "https://{wert}@example.org/"]))
        XCTAssertThrowsError(try social("custom", "Ada", ["aktionArt": "website", "aktionZiel": "https://example.org/{nummer}"]))
    }
    func testRequestBoundsRouteTypesAndNoExternalSideEffects() {
        XCTAssertThrowsError(try prepare("mail", ["email": "a@example.org", "name": String(repeating: "é", count: 129)]))
        XCTAssertThrowsError(try social("custom", String(repeating: "a", count: 501)))
        XCTAssertThrowsError(try social("custom", "https://example.org", ["path": "/bin/sh"]))
        let malformedRoutes: [Any] = [1, "true", NSNull()]
        for route in malformedRoutes { XCTAssertThrowsError(try prepare("karte", ["kontakt": ["strasse": "Road 1"], "land": "DE", "route": route])) }
        XCTAssertThrowsError(try prepare("karte", ["kontakt": ["strasse": "Road 1"], "land": "DE", "route": true, "absender": "Only Name"]))
        XCTAssertThrowsError(try prepare("karte", ["kontakt": ["strasse": ""], "land": "DE"]))
        XCTAssertThrowsError(try prepare("karte", ["kontakt": ["strasse": "Road 1"], "land": "DE", "dienst": "/bin/sh"]))
        XCTAssertThrowsError(try prepare("karte", ["kontakt": ["strasse": "Road 1", "opaque": String(repeating: "a", count: 33_000)], "land": "DE"]))
        XCTAssertThrowsError(try prepare("https", ["url": "https://example.org"]))
    }
}
