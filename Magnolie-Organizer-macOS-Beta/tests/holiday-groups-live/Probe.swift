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
func row(_ groups: [String], subdivisions: [String] = [], nationwide: Bool = false, name: String = "Winter", start: String = "2026-12-19", end: String = "2027-01-03", scope: String? = nil) -> [String: Any] {
    var value: [String: Any] = ["startDate": start, "endDate": end, "name": name, "nationwide": nationwide, "groups": groups.map { ["code": $0] }, "subdivisions": subdivisions.map { ["code": $0] }]
    if let scope { value["regionalScope"] = scope }; return value
}
func param(_ req: BoundedHTTPRequest, _ key: String) -> String? { URLComponents(url: req.url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == key }?.value }
final class RawTransport: BoundedHTTPTransport {
    var requests: [BoundedHTTPRequest] = []
    let directory: URL; let country: String
    init(_ directory: URL, _ country: String) { self.directory = directory; self.country = country }
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        requests.append(request)
        let endpoint = request.url.lastPathComponent
        let prefix = endpoint == "SchoolHolidays" ? param(request, "groupCode") ?? country : country
        return .init(status: 200, body: try Data(contentsOf: directory.appendingPathComponent("\(prefix)-\(endpoint).json")))
    }
}
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
        for (label, rows) in [("missing", [row([])]), ("foreign", [row(["DE-BE"])]), ("unknown", [row([country + "-XX"])]), ("wrong group", [row([codes[1]])]), ("explicit local", [row([codes[0]], subdivisions: [country + "-MUNICIPAL"], scope: "Local")]), ("contradictory nationwide", [row([codes[0]], nationwide: true)])] {
            let r = try await run(country, [codes[0]], Transport(rows))
            check("\(country) \(label) no school data or coverage", !r.entries.contains { $0.kind == "school-holiday" } && !r.coverage.contains { $0.kind == "school-holiday" })
        }
        for (label, rows) in [("empty", [[String:Any]]()), ("nationwide only", [row([], nationwide: true)])] {
            let r = try await run(country, [codes[0]], Transport(rows)); check("\(country) \(label) no coverage", !r.coverage.contains { $0.kind == "school-holiday" })
        }
        let municipal = try await run(country, [], Transport([row([codes[0]], subdivisions: [country + "-MUNICIPAL"], scope: "Local")]))
        check("\(country) country explicit local keeps subdivision only", municipal.entries.first?.regions == [country + "-MUNICIPAL"] && !municipal.coverage.contains { $0.kind == "school-holiday" })
        do { _ = try await run(country, [codes[0], country + "-MUNICIPAL"], Transport([])); check("\(country) mixed request rejected", false) } catch { check("\(country) mixed request rejected", true) }
        do { _ = try await run(country, [codes[0]], Transport([], status: 503)); check("\(country) failed response", false) } catch { check("\(country) failed response", true) }
    }
    let at = Transport([row([], subdivisions: ["AT-WI"])])
    let ar = try await run("AT", ["AT-9"], at)
    check("Austria subdivision mapping", param(at.requests[1], "subdivisionCode") == "AT-WI" && ar.entries.first?.regions == ["AT-9"])
    let de = Transport([row([], subdivisions: ["DE-BE"])])
    let dr = try await run("DE", ["DE-BE"], de)
    check("Germany subdivision unchanged", param(de.requests[1], "subdivisionCode") == "DE-BE" && dr.entries.first?.regions == ["DE-BE"])
    // Refs #857: replay the original provider bytes through the complete service.
    let fixtures = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    func identity(_ start: String, _ end: String, _ name: String) -> String { [start, end, name].joined(separator: "\u{1f}") }
    for country in all.keys.sorted() {
        let codes = all[country]!
        for selected in [""] + codes {
            let transport = RawTransport(fixtures, country)
            let query = try HolidayService.Query(country: country, regions: selected.isEmpty ? [] : [.init(code: selected, name: selected)], years: [2026], includeSchool: true)
            let result = try await HolidayService(transport: transport).fetchResult(query)
            let prefix = selected.isEmpty ? country : selected
            let rows = try JSONSerialization.jsonObject(with: Data(contentsOf: fixtures.appendingPathComponent("\(prefix)-SchoolHolidays.json"))) as! [[String:Any]]
            var expected: [String:Set<String>] = [:]
            for item in rows {
                let name = (item["name"] as! [[String:Any]])[0]["text"] as! String
                let key = identity(item["startDate"] as! String, item["endDate"] as! String, name)
                expected[key, default: []].formUnion((item["groups"] as! [[String:Any]]).map { $0["code"] as! String })
            }
            let observed = Dictionary(uniqueKeysWithValues: result.entries.filter { $0.kind == "school-holiday" }.map { (identity($0.start, $0.end, $0.name), Set($0.regions)) })
            check("\(prefix) captured groups and dates exact", observed == expected)
            check("\(prefix) captured group coverage", result.coverage.filter { $0.kind == "school-holiday" }.map { $0.region } == [selected])
            check("\(prefix) captured public scope", result.coverage.contains { $0.kind == "public-holiday" && $0.region == "" } && transport.requests.filter { $0.url.path == "/PublicHolidays" }.allSatisfy { param($0,"groupCode") == nil && param($0,"subdivisionCode") == nil })
        }
        let code = codes[0]
        func one(_ value: [String:Any], selected: Bool = true) async throws -> HolidayService.Result {
            try await run(country, selected ? [code] : [], Transport([value], publicRows: [row([], nationwide: true, name: "Public")]))
        }
        let expanded = try await one(row([code], subdivisions: [country + "-MUNICIPAL"]))
        check("\(country) expanded groups keep only group identity", expanded.entries.first { $0.kind == "school-holiday" }?.regions == [code] && expanded.coverage.contains { $0.kind == "school-holiday" && $0.region == code })
        var exceptionRow = row([code], subdivisions: [country + "-MUNICIPAL"]); exceptionRow["tags"] = ["Exception"]
        let exception = try await one(exceptionRow)
        check("\(country) Exception tag alone preserves group", exception.entries.first { $0.kind == "school-holiday" }?.regions == [code] && exception.coverage.contains { $0.kind == "school-holiday" })
        let national = try await one(row(codes, subdivisions: [country + "-MUNICIPAL"], nationwide: true))
        check("\(country) all groups nationwide expansion consistent", national.entries.first { $0.kind == "school-holiday" }?.regions == codes.sorted() && national.coverage.contains { $0.kind == "school-holiday" })
        let local = try await one(row([code], subdivisions: [country + "-MUNICIPAL"], scope: "Local"), selected: false)
        check("\(country) Local country retains only local scope", local.entries.first { $0.kind == "school-holiday" }?.regions == [country + "-MUNICIPAL"] && !local.coverage.contains { $0.kind == "school-holiday" })
        let subdivisionOnly = try await one(row([], subdivisions: [country + "-MUNICIPAL"]), selected: false)
        check("\(country) subdivision-only country retains local scope", subdivisionOnly.entries.first { $0.kind == "school-holiday" }?.regions == [country + "-MUNICIPAL"] && !subdivisionOnly.coverage.contains { $0.kind == "school-holiday" })
        for invalid: Any in ["Unknown", 42, NSNull()] {
            var value = row([code]); value["regionalScope"] = invalid
            let r = try await one(value)
            check("\(country) invalid regionalScope \(invalid) grants no coverage", r.entries.first { $0.kind == "school-holiday" }?.regions == [code] && !r.coverage.contains { $0.kind == "school-holiday" })
        }
        var malformed = row([code]); malformed["subdivisions"] = "invalid"
        for (label,bad) in [("foreign subdivision",row([code],subdivisions:["XX-FOREIGN"])),("prefixless subdivision",row([code],subdivisions:["MUNICIPAL"])),("malformed subdivisions",malformed),("local without local identity",row([code],scope:"Local"))] {
            do {
                let r = try await one(bad)
                check("\(country) \(label) rejected", !r.entries.contains { $0.kind == "school-holiday" } && !r.coverage.contains { $0.kind == "school-holiday" })
            } catch { check("\(country) \(label) rejected", true) }
        }
    }
    print("RESULT \(count-failed)/\(count)"); if failed != 0 { exit(1) }
 }
}
