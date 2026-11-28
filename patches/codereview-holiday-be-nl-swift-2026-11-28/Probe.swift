import Foundation
final class Transport: BoundedHTTPTransport {
    var requests: [BoundedHTTPRequest] = []
    let publicRows: [[String: Any]]; let schoolRows: [[String: Any]]; let status: Int
    init(_ rows: [[String: Any]], publicRows: [[String: Any]] = [], status: Int = 200) { self.schoolRows = rows; self.publicRows = publicRows; self.status = status }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        requests.append(request)
        return .init(status: request.url.path == "/SchoolHolidays" ? status : 200, body: try JSONSerialization.data(withJSONObject: request.url.path == "/SchoolHolidays" ? schoolRows : publicRows))
    }
}
func row(_ groups: [String], subdivisions: [String] = [], nationwide: Bool = false, name: String = "Winter", start: String = "2026-12-19", end: String = "2027-01-03") -> [String: Any] {
    ["startDate": start, "endDate": end, "name": name, "nationwide": nationwide, "groups": groups.map { ["code": $0] }, "subdivisions": subdivisions.map { ["code": $0] }]
}
func param(_ req: BoundedHTTPRequest, _ key: String) -> String? { URLComponents(url: req.url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == key }?.value }
@main struct Probe {
 static func main() async throws {
    var failed = 0; var count = 0
    func check(_ name: String, _ ok: Bool) { count += 1; if !ok { failed += 1 }; print("\(ok ? "PASS" : "FAIL") \(name)") }
    func run(_ country: String, _ codes: [String], _ t: Transport, school: Bool = true) async throws -> HolidayService.Result {
        let q = try HolidayService.Query(country: country, regions: codes.map { .init(code: $0, name: $0) }, years: [2026], includeSchool: school)
        return try await HolidayService(transport: t).fetchResult(q)
    }
    let all = ["BE": ["BE-DE", "BE-FR", "BE-NL"], "NL": ["NL-NO", "NL-MI", "NL-ZU"]]
    for country in all.keys.sorted() { let codes = all[country]!
        for code in codes {
            let t = Transport([row([code])], publicRows: [row([], nationwide: true, name: "Public")]); let r = try await run(country, [code], t)
            check("\(code) group param", t.requests.count == 2 && param(t.requests[1], "groupCode") == code && param(t.requests[1], "subdivisionCode") == nil)
            check("\(code) public scope", param(t.requests[0], "subdivisionCode") == nil && param(t.requests[0], "groupCode") == nil && r.coverage.contains { $0.kind == "public-holiday" && $0.region == "" })
            check("\(code) school scope + end", r.entries.contains { $0.kind == "school-holiday" && $0.regions == [code] && $0.end == "2027-01-03" } && r.coverage.contains { $0.kind == "school-holiday" && $0.region == code })
        }
        let multi = Transport([row(codes)]); let mr = try await run(country, codes, multi)
        check("\(country) multi groups", mr.entries.count == 1 && mr.entries[0].regions == codes.sorted() && mr.entries[0].regionLabel == codes.sorted().joined(separator: ", "))
        check("\(country) one public per year", multi.requests.filter { $0.url.path == "/PublicHolidays" }.count == 1)
        let national = try await run(country, [], Transport([row(codes)]))
        check("\(country) national groups", national.entries.first?.regions == codes.sorted() && national.coverage.contains { $0.kind == "school-holiday" && $0.region == "" })
        let partial = try await run(country, [], Transport([row([codes[0]])]))
        check("\(country) partial national no coverage", !partial.coverage.contains { $0.kind == "school-holiday" })
        for (label, rows) in [("missing", [row([])]), ("foreign", [row(["DE-BE"])]), ("unknown", [row([country + "-XX"])]), ("wrong group", [row([codes[1]])]), ("mixed", [row([codes[0]], subdivisions: [country + "-MUNICIPAL"])]), ("contradictory nationwide", [row([codes[0]], nationwide: true)])] {
            let r = try await run(country, [codes[0]], Transport(rows))
            check("\(country) \(label) no school data or coverage", !r.entries.contains { $0.kind == "school-holiday" } && !r.coverage.contains { $0.kind == "school-holiday" })
        }
        for (label, rows) in [("empty", [[String:Any]]()), ("nationwide only", [row([], nationwide: true)])] {
            let r = try await run(country, [codes[0]], Transport(rows)); check("\(country) \(label) no coverage", !r.coverage.contains { $0.kind == "school-holiday" })
        }
        let municipal = try await run(country, [], Transport([row([codes[0]], subdivisions: [country + "-MUNICIPAL"])]))
        check("\(country) country mixed keeps subdivision only", municipal.entries.first?.regions == [country + "-MUNICIPAL"] && !municipal.coverage.contains { $0.kind == "school-holiday" })
        do { _ = try await run(country, [codes[0], country + "-MUNICIPAL"], Transport([])); check("\(country) mixed request rejected", false) } catch { check("\(country) mixed request rejected", true) }
        do { _ = try await run(country, [codes[0]], Transport([], status: 503)); check("\(country) failed response", false) } catch { check("\(country) failed response", true) }
    }
    let at = Transport([row([], subdivisions: ["AT-WI"])])
    let ar = try await run("AT", ["AT-9"], at)
    check("Austria subdivision mapping", param(at.requests[1], "subdivisionCode") == "AT-WI" && ar.entries.first?.regions == ["AT-9"])
    let de = Transport([row([], subdivisions: ["DE-BE"])])
    let dr = try await run("DE", ["DE-BE"], de)
    check("Germany subdivision unchanged", param(de.requests[1], "subdivisionCode") == "DE-BE" && dr.entries.first?.regions == ["DE-BE"])
    print("RESULT \(count-failed)/\(count)"); if failed != 0 { exit(1) }
 }
}
