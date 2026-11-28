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
    func testRegionFallbackAppliesToEveryGroupedResponse() async throws {
        let transport = Transport { _ in
            BoundedHTTPResponse(status: 200, body: try self.body([
                ["startDate": "2026-10-01", "name": "Shared regional holiday", "nationwide": false]
            ]))
        }
        let query = try HolidayService.Query(country: "DE", regions: [.init(code: "DE-BE", name: "Berlin"),
            .init(code: "DE-BB", name: "Brandenburg")], years: [2026], includeSchool: false, language: "DE")
        let rows = try await HolidayService(transport: transport).fetch(query)
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].regions, ["DE-BB", "DE-BE"])
        XCTAssertEqual(rows[0].organizerValue["regionName"] as? String, "alle Bundesländer")
    }
    func testCountryScopeDoesNotPretendToSupplyRegionalSchoolHolidays() async throws {
        let transport = Transport { _ in BoundedHTTPResponse(status: 200, body: Data("[]".utf8)) }
        let query = try HolidayService.Query(country: "CH", years: [2026], includeSchool: true, regionRequired: true)
        XCTAssertFalse(query.includeSchool)
        let rows = try await HolidayService(transport: transport).fetch(query)
        XCTAssertTrue(rows.isEmpty); XCTAssertEqual(transport.requests.count, 1)
        XCTAssertEqual(transport.requests[0].url.path, "/PublicHolidays")
    }
    func testSuccessfulEmptyResponsesCertifyOnlyActualRequestedScopes() async throws {
        let transport = Transport { _ in BoundedHTTPResponse(status: 200, body: Data("[]".utf8)) }
        let query = try HolidayService.Query(country: "DE", regions: [.init(code: "DE-BE", name: "Berlin"),
            .init(code: "DE-BB", name: "Brandenburg")], years: [2028, 2027], includeSchool: true, regionRequired: true)
        let result = try await HolidayService(transport: transport).fetchResult(query)
        XCTAssertTrue(result.entries.isEmpty); XCTAssertEqual(result.coverage.count, 8)
        let expected = transport.requests.map { request -> [String] in
            let fields = Dictionary(uniqueKeysWithValues: URLComponents(url: request.url, resolvingAgainstBaseURL: false)!
                .queryItems!.map { ($0.name, $0.value ?? "") })
            return [fields["countryIsoCode"]!, fields["subdivisionCode"]!,
                    request.url.path == "/SchoolHolidays" ? "school-holiday" : "public-holiday",
                    fields["validFrom"]!, fields["validTo"]!]
        }
        XCTAssertEqual(result.coverage.map { [$0.country, $0.region, $0.kind, $0.start, $0.end] }, expected)
        XCTAssertEqual(result.coverage.map { value in
            ["country", "region", "art", "von", "bis"].map { value.organizerValue[$0] as! String }
        }, expected)
    }
    func testSchoolOptOutAndMissingRegionNeverCertifySchoolScopes() async throws {
        for query in [try HolidayService.Query(country: "DE", regions: [.init(code: "DE-BE", name: "Berlin")],
                         years: [2028], includeSchool: false),
                      try HolidayService.Query(country: "CH", years: [2028], includeSchool: true, regionRequired: true)] {
            let result = try await HolidayService(transport: Transport { _ in
                BoundedHTTPResponse(status: 200, body: Data("[]".utf8))
            }).fetchResult(query)
            XCTAssertEqual(result.coverage.count, 1)
            XCTAssertEqual(result.coverage[0].kind, "public-holiday")
            XCTAssertEqual(result.coverage[0].region, query.regions.first?.code ?? "")
        }
    }
    func testToleratedMalformedMetadataNeverCertifiesReplacement() async throws {
        let query = try HolidayService.Query(country: "DE", regions: [.init(code: "DE-BE", name: "Berlin")],
            years: [2028], includeSchool: false)
        let malformed: [[String: Any]] = [["nationwide": "true"], ["subdivisions": "DE-BE"],
                                          ["endDate": 123], ["endDate": NSNull()], ["nationwide": NSNull()],
                                          ["subdivisions": NSNull()], ["name": [["language": "EN", "text": "Fixture"], [:]]]]
        for extra in malformed {
            var row: [String: Any] = ["startDate": "2028-02-29", "endDate": "2028-02-29", "nationwide": false, "name": "Fixture"]
            row.merge(extra) { _, new in new }
            let result = try await HolidayService(transport: Transport { _ in
                BoundedHTTPResponse(status: 200, body: try self.body([row]))
            }).fetchResult(query)
            XCTAssertEqual(result.entries.count, 1)
            XCTAssertTrue(result.coverage.isEmpty)
        }
        for missing in ["endDate", "nationwide"] {
            var row: [String: Any] = ["startDate": "2028-02-29", "endDate": "2028-02-29", "nationwide": false, "name": "Fixture"]
            row.removeValue(forKey: missing)
            let result = try await HolidayService(transport: Transport { _ in
                BoundedHTTPResponse(status: 200, body: try self.body([row]))
            }).fetchResult(query)
            XCTAssertEqual(result.entries.count, 1); XCTAssertTrue(result.coverage.isEmpty)
        }
    }
    func testUnrelatedYearsOrRegionsCannotCertifyTheRequestedScope() async throws {
        let query = try HolidayService.Query(country: "DE", regions: [.init(code: "DE-BE", name: "Berlin")],
            years: [2028], includeSchool: false)
        let mismatches: [[String: Any]] = [["startDate": "2027-12-25", "endDate": "2027-12-25", "nationwide": false, "name": "Fixture"],
            ["startDate": "2028-02-29", "endDate": "2028-02-29", "nationwide": false, "name": "Fixture", "subdivisions": [["code": "AT-9"]]],
            ["startDate": "2028-02-29", "endDate": "2028-02-29", "nationwide": false, "name": "Fixture", "subdivisions": [["code": "DE-BY"]]]]
        for row in mismatches {
            let result = try await HolidayService(transport: Transport { _ in
                BoundedHTTPResponse(status: 200, body: try self.body([row]))
            }).fetchResult(query)
            XCTAssertEqual(result.entries.count, 1); XCTAssertTrue(result.coverage.isEmpty)
        }
        for code in ["DE-BE-TEST", "BE"] {
            let matching = try await HolidayService(transport: Transport { _ in
                BoundedHTTPResponse(status: 200, body: try self.body([
                    ["startDate": "2028-02-29", "endDate": "2028-02-29", "nationwide": false, "name": "Fixture", "subdivisions": [["code": code]]]
                ]))
            }).fetchResult(query)
            XCTAssertEqual(matching.coverage.map { $0.region }, ["DE-BE"])
        }
        let unknown = try await HolidayService(transport: Transport { _ in
            BoundedHTTPResponse(status: 200, body: try self.body([
                ["startDate": "2028-02-29", "endDate": "2028-02-29", "nationwide": false, "name": "Fixture"]
            ]))
        }).fetchResult(try HolidayService.Query(country: "DE", years: [2028], includeSchool: false))
        XCTAssertEqual(unknown.entries.count, 1); XCTAssertTrue(unknown.coverage.isEmpty)
    }
    func testLaterFailedRequestPublishesNoPartialCoverage() async throws {
        let query = try HolidayService.Query(country: "DE", years: [2028], includeSchool: true)
        let transport = Transport { request in
            BoundedHTTPResponse(status: request.url.path == "/SchoolHolidays" ? 503 : 200, body: Data("[]".utf8))
        }
        do {
            _ = try await HolidayService(transport: transport).fetchResult(query)
            XCTFail("A failed school request must not publish public-only cache authority")
        } catch { }
        let result = try await HolidayService(transport: Transport { _ in
            BoundedHTTPResponse(status: 200, body: Data("[]".utf8))
        }).fetchResult(try HolidayService.Query(country: "DE", years: [2029], includeSchool: false))
        XCTAssertEqual(result.coverage.count, 1)
        XCTAssertEqual(result.coverage[0].start, "2029-01-01")
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
    func testAustrianProviderIdentifiersRoundTripAllNineRegions() async throws {
        // Refs #856: pairs from the actual OpenHolidays AT Subdivisions response.
        let pairs = [("AT-1", "AT-BL"), ("AT-2", "AT-KÄ"), ("AT-3", "AT-NÖ"),
                     ("AT-4", "AT-OÖ"), ("AT-5", "AT-SB"), ("AT-6", "AT-SM"),
                     ("AT-7", "AT-TI"), ("AT-8", "AT-VA"), ("AT-9", "AT-WI")]
        let encoded = ["AT-KÄ": "AT-K%C3%84", "AT-NÖ": "AT-N%C3%96", "AT-OÖ": "AT-O%C3%96"]
        for (iso, provider) in pairs {
            let transport = Transport { request in
                let fields = URLComponents(url: request.url, resolvingAgainstBaseURL: false)!.queryItems!
                XCTAssertEqual(fields.first(where: { $0.name == "subdivisionCode" })?.value, provider, iso)
                if let escaped = encoded[provider] {
                    XCTAssertTrue(request.url.absoluteString.contains("subdivisionCode=" + escaped), iso)
                }
                return BoundedHTTPResponse(status: 200, body: try self.body([
                    ["startDate": "2026-02-02", "endDate": "2026-02-08", "name": "Regional period",
                     "nationwide": false, "subdivisions": [["code": provider]]]
                ]))
            }
            let query = try HolidayService.Query(country: "AT", regions: [.init(code: iso, name: iso)],
                years: [2026], includeSchool: true, regionRequired: true)
            do {
                let result = try await HolidayService(transport: transport).fetchResult(query)
                XCTAssertEqual(result.entries.count, 2, iso)
                XCTAssertEqual(result.coverage.count, 2, iso)
                XCTAssertEqual(Set(result.coverage.map { $0.kind }), ["public-holiday", "school-holiday"], iso)
                XCTAssertTrue(result.coverage.allSatisfy { $0.country == "AT" && $0.region == iso }, iso)
                XCTAssertTrue(result.entries.allSatisfy { $0.regions == [iso] && $0.selectedRegions == [iso] }, iso)
                XCTAssertTrue(result.entries.allSatisfy {
                    $0.organizerValue["regions"] as? [String] == [iso] && $0.organizerValue["region"] as? String == iso
                }, iso)
            } catch { XCTFail("\(iso) failed instead of normalizing its verified provider code: \(error)") }
            XCTAssertEqual(transport.requests.count, 2, iso)
        }
    }
    func testAustrianGroupedResponseUsesOnlyCanonicalISOScope() async throws {
        let transport = Transport { _ in
            BoundedHTTPResponse(status: 200, body: try self.body([
                ["startDate": "2026-07-04", "endDate": "2026-09-06", "name": "Shared period",
                 "nationwide": false, "subdivisions": [["code": "AT-KÄ"], ["code": "AT-NÖ"],
                    ["code": "AT-OÖ"], ["code": "AT-3"]]]
            ]))
        }
        let query = try HolidayService.Query(country: "AT", regions: [.init(code: "AT-2", name: "Kärnten"),
            .init(code: "AT-3", name: "Niederösterreich"), .init(code: "AT-4", name: "Oberösterreich")],
            years: [2026], includeSchool: false, language: "DE")
        let result = try await HolidayService(transport: transport).fetchResult(query)
        XCTAssertEqual(result.entries.count, 1)
        XCTAssertEqual(result.entries[0].regions, ["AT-2", "AT-3", "AT-4"])
        XCTAssertEqual(result.entries[0].selectedRegions, ["AT-2", "AT-3", "AT-4"])
        XCTAssertEqual(result.entries[0].organizerValue["region"] as? String, "AT-2,AT-3,AT-4")
        XCTAssertEqual(result.entries[0].regionLabel, "alle Bundesländer")
        XCTAssertEqual(result.coverage.map { $0.region }, ["AT-2", "AT-3", "AT-4"])
    }
    func testUnknownAustrianSelectionRejectsBeforeHTTP() throws {
        for code in ["AT-10", "AT-UNKNOWN", "AT-WI", "DE-BE"] {
            XCTAssertThrowsError(try HolidayService.Query(country: "AT", regions: [.init(code: code, name: code)],
                years: [2026], includeSchool: true), code)
        }
        XCTAssertNoThrow(try HolidayService.Query(country: "at", regions: [.init(code: " at-9 ", name: "Wien")],
            years: [2026], includeSchool: true))
    }
    func testUnknownAustrianAndForeignResponseCodesNeverCertifyCoverage() async throws {
        for selected in [[], [HolidayService.Region(code: "AT-9", name: "Wien")]] {
            for code in ["AT-UNKNOWN", "AT-10", "WI", "DE-BE"] {
                for nationwide in [false, true] {
                    let query = try HolidayService.Query(country: "AT", regions: selected,
                        years: [2026], includeSchool: false)
                    let result = try await HolidayService(transport: Transport { _ in
                        BoundedHTTPResponse(status: 200, body: try self.body([
                            ["startDate": "2026-02-02", "endDate": "2026-02-08", "name": "Unknown regional period",
                             "nationwide": nationwide, "subdivisions": [["code": code]]]
                        ]))
                    }).fetchResult(query)
                    XCTAssertEqual(result.entries.count, 1, code)
                    XCTAssertTrue(result.coverage.isEmpty, "\(code), nationwide=\(nationwide), selected=\(selected.count)")
                }
            }
        }
    }
    func testUnknownUnicodeRegionCodesKeepStrictParserFailure() async throws {
        for code in ["AT-ÜNBEKANNT", "AT-WI/../", "DE-Ä"] {
            let query = try HolidayService.Query(country: "AT", regions: [.init(code: "AT-9", name: "Wien")],
                years: [2026], includeSchool: false)
            do {
                _ = try await HolidayService(transport: Transport { _ in
                    BoundedHTTPResponse(status: 200, body: try self.body([
                        ["startDate": "2026-02-02", "endDate": "2026-02-08", "name": "Invalid scope",
                         "nationwide": false, "subdivisions": [["code": code]]]
                    ]))
                }).fetchResult(query)
                XCTFail("An unverified malformed code must still reject: \(code)")
            } catch { }
        }
    }
    func testGermanSwissAndCanonicalAustrianResponseScopesRemainValid() async throws {
        for (country, iso, provider) in [("DE", "DE-BE", "DE-BE"), ("CH", "CH-ZH", "CH-ZH"), ("AT", "AT-9", "AT-WI")] {
            let query = try HolidayService.Query(country: country, regions: [.init(code: iso, name: iso)],
                years: [2026], includeSchool: false)
            let result = try await HolidayService(transport: Transport { request in
                let fields = URLComponents(url: request.url, resolvingAgainstBaseURL: false)!.queryItems!
                XCTAssertEqual(fields.first(where: { $0.name == "subdivisionCode" })?.value, provider)
                return BoundedHTTPResponse(status: 200, body: try self.body([
                    ["startDate": "2026-02-02", "endDate": "2026-02-08", "name": "Canonical period",
                     "nationwide": false, "subdivisions": [["code": iso]]]
                ]))
            }).fetchResult(query)
            XCTAssertEqual(result.entries.first?.regions, [iso])
            XCTAssertEqual(result.coverage.map { $0.region }, [iso])
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
