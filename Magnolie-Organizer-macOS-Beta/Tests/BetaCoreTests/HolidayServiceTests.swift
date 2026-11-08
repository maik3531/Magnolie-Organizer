import Foundation
import XCTest
@testable import BetaCore

final class HolidayServiceTests: XCTestCase {
    private final class Transport: BoundedHTTPTransport {
        var requests: [BoundedHTTPRequest] = []
        let handler: (BoundedHTTPRequest) throws -> BoundedHTTPResponse
        init(_ handler: @escaping (BoundedHTTPRequest) throws -> BoundedHTTPResponse) { self.handler = handler }
        func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
            requests.append(request); return try handler(request)
        }
    }
    private func body(_ objects: [[String: Any]]) throws -> Data { try JSONSerialization.data(withJSONObject: objects) }
    func testNativeHolidayCommandContract() throws {
        XCTAssertNoThrow(try Request(#"{"cmd":"feiertage","land":"DE","region":"DE-BE","regionen":[],"jahre":[2026,2027],"ferien":true,"regionErforderlich":true}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"feiertage","land":"DE","jahre":[true]}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"feiertage","land":"DE","jahre":[2026.5]}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"feiertage","land":"DE","jahre":[2026],"url":"https://example.invalid"}"#))
    }
    func testPublicAndSchoolScopeLanguageAndInclusiveDates() async throws {
        let transport = Transport { request in
            let school = request.url.path == "/SchoolHolidays"
            let row: [String: Any] = ["startDate": "2028-02-29", "endDate": school ? "2028-03-04" : "2028-02-29",
                "name": [["language": "EN", "text": "Spring"], ["language": "DE", "text": "Frühling"]],
                "nationwide": !school, "subdivisions": school ? [["code": "DE-BE"]] : []]
            return BoundedHTTPResponse(status: 200, body: try self.body([row]))
        }
        let query = try HolidayService.Query(country: "de", regions: [.init(code: "DE-BE", name: "Berlin")],
            years: [2028], includeSchool: true, regionRequired: true, language: "de-DE")
        let rows = try await HolidayService(transport: transport).fetch(query)
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows.first(where: { $0.kind == "school-holiday" })?.end, "2028-03-04")
        XCTAssertTrue(rows.allSatisfy { $0.name == "Frühling" && $0.country == "DE" })
        XCTAssertEqual(rows.first(where: { $0.kind == "school-holiday" })?.regions, ["DE-BE"])
        for request in transport.requests {
            XCTAssertEqual(request.url.scheme, "https"); XCTAssertEqual(request.url.host, "openholidaysapi.org")
            XCTAssertNil(request.headers["Authorization"])
            XCTAssertLessThanOrEqual(request.timeout, 20)
            let fields = URLComponents(url: request.url, resolvingAgainstBaseURL: false)!.queryItems!
            XCTAssertEqual(fields.first(where: { $0.name == "validFrom" })?.value, "2028-01-01")
            XCTAssertEqual(fields.first(where: { $0.name == "subdivisionCode" })?.value, "DE-BE")
        }
    }
    func testAllRegionDuplicatesMergeWithoutLosingScopes() async throws {
        let transport = Transport { request in
            let code = URLComponents(url: request.url, resolvingAgainstBaseURL: false)!.queryItems!
                .first(where: { $0.name == "subdivisionCode" })!.value!
            return BoundedHTTPResponse(status: 200, body: try self.body([
                ["startDate": "2026-12-25", "name": [["language": "EN", "text": "Christmas"]],
                 "nationwide": false, "subdivisions": [["code": code]]]
            ]))
        }
        let query = try HolidayService.Query(country: "DE", regions: [.init(code: "DE-BE", name: "Berlin"),
            .init(code: "DE-BB", name: "Brandenburg")], years: [2026], includeSchool: false)
        let rows = try await HolidayService(transport: transport).fetch(query)
        XCTAssertEqual(rows.count, 1); XCTAssertEqual(rows[0].regions, ["DE-BB", "DE-BE"])
        XCTAssertEqual(rows[0].regionNames, ["Berlin", "Brandenburg"])
    }
    func testCountryScopeDoesNotPretendToSupplyRegionalSchoolHolidays() async throws {
        let transport = Transport { _ in BoundedHTTPResponse(status: 200, body: Data("[]".utf8)) }
        let query = try HolidayService.Query(country: "CH", years: [2026], includeSchool: true, regionRequired: true)
        XCTAssertFalse(query.includeSchool)
        let rows = try await HolidayService(transport: transport).fetch(query)
        XCTAssertTrue(rows.isEmpty); XCTAssertEqual(transport.requests.count, 1)
        XCTAssertEqual(transport.requests[0].url.path, "/PublicHolidays")
    }
    func testInvalidSelectionAndMalformedResponsesReject() async throws {
        XCTAssertThrowsError(try HolidayService.Query(country: "DE/../", years: [2026], includeSchool: false))
        XCTAssertThrowsError(try HolidayService.Query(country: "DE", years: [2025, 2026, 2027, 2028], includeSchool: false))
        XCTAssertThrowsError(try HolidayService.Query(country: "DE", years: [0], includeSchool: false))
        let query = try HolidayService.Query(country: "DE", years: [2026], includeSchool: false)
        for response in [BoundedHTTPResponse(status: 302, headers: ["Location": "https://example.invalid"]),
                         BoundedHTTPResponse(status: 503),
                         BoundedHTTPResponse(status: 200, body: Data("not-json".utf8)),
                         BoundedHTTPResponse(status: 200, body: try body([["startDate": "2026-02-30", "name": "invalid"]]))] {
            do { _ = try await HolidayService(transport: Transport { _ in response }).fetch(query)
                XCTFail("Invalid provider data must not replace the existing holiday cache")
            } catch { /* Native caller reports failure; no partial Entry array exists. */ }
        }
    }
    func testLivePublicHolidayServiceWhenRequested() async throws {
        guard ProcessInfo.processInfo.environment["MACOS_BETA_LIVE_HOLIDAYS"] == "1" else {
            throw XCTSkip("Enable the explicit read-only public holiday integration check on a network-enabled Mac runner.")
        }
        let query = try HolidayService.Query(country: "DE", years: [2026], includeSchool: false, language: "EN")
        let rows = try await HolidayService().fetch(query)
        XCTAssertFalse(rows.isEmpty)
        XCTAssertTrue(rows.allSatisfy { $0.country == "DE" && $0.kind == "public-holiday" && $0.start.hasPrefix("2026-") })
    }
}
