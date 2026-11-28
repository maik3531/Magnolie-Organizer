import Foundation
import CoreFoundation

/// Public holiday data only. The server and endpoints are fixed; no account
/// credentials or user-provided URLs are sent to this service.
public struct HolidayService {
    // Refs #856: OpenHolidays uses its own AT subdivision codes, not ISO 3166-2.
    // Keep the selected/cache identity in ISO form; translate only at this boundary.
    private static let austrianProviderRegions = [
        "AT-1": "AT-BL", "AT-2": "AT-KÄ", "AT-3": "AT-NÖ", "AT-4": "AT-OÖ",
        "AT-5": "AT-SB", "AT-6": "AT-SM", "AT-7": "AT-TI", "AT-8": "AT-VA", "AT-9": "AT-WI"
    ]
    private static let austrianISORegions = Dictionary(uniqueKeysWithValues:
        austrianProviderRegions.map { ($0.value, $0.key) })
    // Refs #854: school groups are not administrative subdivisions.
    private static func schoolGroups(_ country: String) -> Set<String> {
        switch country {
        case "BE": return ["BE-DE", "BE-FR", "BE-NL"]
        case "NL": return ["NL-NO", "NL-MI", "NL-ZU"]
        default: return []
        }
    }
    public struct Region: Hashable, Sendable {
        public let code: String
        public let name: String
        public init(code: String, name: String) { self.code = code; self.name = name }
    }
    public struct Query: Sendable {
        public let country: String
        public let regions: [Region]
        public let years: [Int]
        public let includeSchool: Bool
        public let regionRequired: Bool
        public let language: String
        public init(country: String, regions: [Region] = [], years: [Int], includeSchool: Bool,
                    regionRequired: Bool = false, language: String = "EN") throws {
            guard country.utf8.count <= 32 else { throw BetaError("Invalid holiday country.") }
            let country = country.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
            guard HolidayService.matches(country, "^[A-Z]{2}$"), !years.isEmpty,
                  Set(years).count <= 3, years.allSatisfy({ (1...9999).contains($0) }),
                  regions.count <= 26 else { throw BetaError("Select a country, valid regions and at most three years.") }
            var seen = Set<String>()
            var selected: [Region] = []
            for region in regions {
                guard region.code.utf8.count <= 128 else { throw BetaError("Invalid holiday region.") }
                let code = region.code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
                guard HolidayService.matches(code, "^[A-Z0-9-]{1,64}$"), region.name.count <= 256,
                      country != "AT" || HolidayService.austrianProviderRegions[code] != nil else {
                    throw BetaError("The selected holiday region is invalid.")
                }
                if seen.insert(code).inserted { selected.append(Region(code: code, name: region.name)) }
            }
            self.country = country; self.regions = selected
            self.years = Set(years).sorted(); self.regionRequired = regionRequired
            self.includeSchool = includeSchool && (!regionRequired || !selected.isEmpty)
            self.language = language.lowercased().hasPrefix("de") || language == "system" ? "DE" : "EN"
        }
    }
    public struct Entry: Equatable, Sendable {
        public let start: String
        public let end: String
        public let name: String
        public let kind: String
        public let country: String
        public let nationwide: Bool
        public let regions: [String]
        public let selectedRegions: [String]
        public let regionNames: [String]
        public let regionLabel: String
        public var organizerValue: [String: Any] {
            ["von": start, "bis": end, "name": name, "art": kind, "country": country,
             "nationwide": nationwide, "regions": regions,
             "region": selectedRegions.joined(separator: ","), "regionName": regionLabel]
        }
    }
    public struct Coverage: Equatable, Sendable {
        public let country: String
        public let region: String
        public let kind: String
        public let start: String
        public let end: String
        public var organizerValue: [String: Any] {
            ["country": country, "region": region, "art": kind, "von": start, "bis": end]
        }
    }
    public struct Result: Sendable {
        public let entries: [Entry]
        public let coverage: [Coverage]
    }
    private struct GroupKey: Hashable { let start: String; let end: String; let name: String; let kind: String }
    private struct Group {
        var start: String; var end: String; var name: String; var kind: String
        var nationwide = false; var regions = Set<String>()
        var selected = Set<String>(); var names = Set<String>()
    }
    private let transport: BoundedHTTPTransport
    public init(transport: BoundedHTTPTransport = URLSessionBoundedTransport()) { self.transport = transport }
    private static func matches(_ text: String, _ pattern: String) -> Bool {
        text.range(of: pattern, options: .regularExpression) != nil
    }
    private static func validDate(_ text: String) -> Bool {
        guard matches(text, "^[0-9]{4}-[0-9]{2}-[0-9]{2}$") else { return false }
        let pieces = text.split(separator: "-").compactMap { Int($0) }
        guard pieces.count == 3, (1...9999).contains(pieces[0]) else { return false }
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let components = DateComponents(year: pieces[0], month: pieces[1], day: pieces[2])
        guard let date = calendar.date(from: components) else { return false }
        let readback = calendar.dateComponents([.year, .month, .day], from: date)
        return readback.year == components.year && readback.month == components.month && readback.day == components.day
    }
    private static func name(_ value: Any?, language: String) -> String? {
        if let text = value as? String { return text.trimmingCharacters(in: .whitespacesAndNewlines) }
        guard let values = value as? [[String: Any]] else { return nil }
        let matching = values.first { ($0["language"] as? String)?.uppercased() == language }
        let text = (matching?["text"] as? String) ?? values.compactMap { $0["text"] as? String }.first
        return text?.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    public func fetch(_ query: Query) async throws -> [Entry] {
        (try await fetchResult(query)).entries
    }
    public func fetchResult(_ query: Query) async throws -> Result {
        let selections: [Region?] = query.regions.isEmpty ? [nil] : query.regions.map { Optional($0) }
        let schoolGroups = Self.schoolGroups(query.country)
        let groupSelection = query.regions.contains { schoolGroups.contains($0.code) }
        if groupSelection && !query.regions.allSatisfy({ schoolGroups.contains($0.code) }) {
            throw BetaError("The selected holiday region is invalid.")
        }
        let kinds = query.includeSchool ? [("PublicHolidays", "public-holiday"), ("SchoolHolidays", "school-holiday")]
                                       : [("PublicHolidays", "public-holiday")]
        var groups: [GroupKey: Group] = [:]
        var coverage: [Coverage] = []
        var receivedBytes = 0
        let deadline = ProcessInfo.processInfo.systemUptime + 90
        for year in query.years {
            for (endpoint, kind) in kinds {
                // Public holidays have no school-group filter.
                let targets: [Region?] = groupSelection && kind == "public-holiday" ? [nil] : selections
                for region in targets {
                    let groupScope = kind == "school-holiday" && !schoolGroups.isEmpty && (groupSelection || region == nil)
                    try Task.checkCancellation()
                    let remaining = deadline - ProcessInfo.processInfo.systemUptime
                    guard remaining > 0 else { throw BetaError("Holiday retrieval timed out; no partial result was applied.") }
                    var url = URLComponents(string: "https://openholidaysapi.org/" + endpoint)!
                    url.queryItems = [URLQueryItem(name: "countryIsoCode", value: query.country),
                        URLQueryItem(name: "languageIsoCode", value: query.language),
                        URLQueryItem(name: "validFrom", value: String(format: "%04d-01-01", year)),
                        URLQueryItem(name: "validTo", value: String(format: "%04d-12-31", year))]
                    if let region {
                        let providerCode = query.country == "AT" ? Self.austrianProviderRegions[region.code] : region.code
                        guard let providerCode else { throw BetaError("The selected holiday region is invalid.") }
                        url.queryItems!.append(URLQueryItem(name: groupScope ? "groupCode" : "subdivisionCode", value: providerCode))
                    }
                    let response = try await transport.send(BoundedHTTPRequest(url: url.url!,
                        headers: ["Accept": "application/json", "User-Agent": "Magnolie-Organizer-macOS/2.0.30"],
                        timeout: min(20, remaining), maximumResponseBytes: 2 * 1024 * 1024))
                    // No redirects are followed, including to a different public-data server.
                    guard response.status == 200 else { throw BetaError("Holiday retrieval failed (HTTP \(response.status)); the existing calendar was retained.") }
                    receivedBytes += response.body.count
                    guard response.body.count <= 2 * 1024 * 1024, receivedBytes <= 16 * 1024 * 1024 else {
                        throw BetaError("The holiday service returned too much data.")
                    }
                    let document = try JSONSerialization.jsonObject(with: response.body)
                    let rows = (document as? [[String: Any]]) ?? ((document as? [String: Any])?["data"] as? [[String: Any]])
                    guard let rows, rows.count <= 10_000 else { throw BetaError("The holiday service returned an unreadable response.") }
                    var complete = true
                    var observedGroups = Set<String>()
                    for row in rows {
                        try Task.checkCancellation()
                        guard ProcessInfo.processInfo.systemUptime < deadline else { throw BetaError("Holiday retrieval timed out; no partial result was applied.") }
                        let start = String((row["startDate"] as? String ?? "").prefix(10))
                        let rawEnd = String((row["endDate"] as? String ?? start).prefix(10))
                        guard Self.validDate(start), Self.validDate(rawEnd), rawEnd >= start,
                              let title = Self.name(row["name"], language: query.language), !title.isEmpty, title.count <= 1024 else {
                            throw BetaError("The holiday service returned an invalid entry; no partial result was applied.")
                        }
                        // Refs #855: retain tolerant rows, but never certify malformed scope metadata.
                        if !(row["endDate"] is String) { complete = false }
                        if let raw = row["nationwide"] {
                            if let number = raw as? NSNumber {
                                if CFGetTypeID(number) != CFBooleanGetTypeID() { complete = false }
                            } else { complete = false }
                        } else { complete = false }
                        if let raw = row["subdivisions"], !(raw is [[String: Any]]) { complete = false }
                        if rawEnd < String(format: "%04d-01-01", year) || start > String(format: "%04d-12-31", year) { complete = false }
                        if let names = row["name"] as? [[String: Any]], names.contains(where: {
                            !($0["text"] is String) || ($0["language"] != nil && !($0["language"] is String))
                        }) { complete = false }
                        let key = GroupKey(start: start, end: rawEnd,
                            name: title.precomposedStringWithCompatibilityMapping.lowercased(), kind: kind)
                        var group = groups[key] ?? Group(start: start, end: rawEnd, name: title, kind: kind)
                        var rowNationwide = false
                        if let nationwide = row["nationwide"] as? NSNumber,
                           CFGetTypeID(nationwide) == CFBooleanGetTypeID(), nationwide.boolValue { rowNationwide = true; group.nationwide = true }
                        var rowRegions = Set<String>()
                        if let subdivisions = row["subdivisions"] as? [[String: Any]] {
                            for subdivision in subdivisions {
                                guard let rawCode = subdivision["code"] as? String else {
                                    throw BetaError("The holiday service returned invalid regional scope.")
                                }
                                let code = query.country == "AT" ? (Self.austrianISORegions[rawCode] ?? rawCode) : rawCode
                                guard Self.matches(code, "^[A-Z0-9-]{1,64}$") else {
                                    throw BetaError("The holiday service returned invalid regional scope.")
                                }
                                if query.country == "AT" && Self.austrianProviderRegions[code] == nil { complete = false }
                                rowRegions.insert(code)
                            }
                        }
                        if groupScope {
                            // Refs #857: explicit groups are expanded into administrative
                            // subdivisions by the provider. Both arrays are normal.
                            if row["regionalScope"] != nil && !["National", "Regional", "Local"].contains(row["regionalScope"] as? String ?? "") {
                                complete = false
                            }
                            let rawGroups = row["groups"] ?? []
                            guard let refs = rawGroups as? [[String: Any]] else { complete = false; continue }
                            let codes = Set(refs.compactMap { $0["code"] as? String })
                            guard refs.allSatisfy({ ($0["code"] as? String).map { schoolGroups.contains($0) } == true }) else {
                                complete = false; continue
                            }
                            let hasSubdivisions = !rowRegions.isEmpty
                            if (row["subdivisions"] != nil && !(row["subdivisions"] is [[String: Any]])) ||
                                rowRegions.contains(where: { !$0.hasPrefix(query.country + "-") }) { complete = false; continue }
                            // Local/subdivision-only rows may survive a country query,
                            // without authorizing replacement of a school group.
                            if row["regionalScope"] as? String == "Local" || (codes.isEmpty && hasSubdivisions) {
                                complete = false
                                if region != nil || rowNationwide || !hasSubdivisions { continue }
                            } else {
                                if rowNationwide {
                                    if !codes.isEmpty && codes != schoolGroups { complete = false; continue }
                                } else if codes.isEmpty || (region.map { !codes.contains($0.code) } ?? false) {
                                    complete = false; continue
                                }
                                rowRegions = codes
                                observedGroups.formUnion(codes)
                            }
                        }
                        if rowRegions.contains(where: { $0.contains("-") && !$0.hasPrefix(query.country + "-") }) { complete = false }
                        if !rowNationwide && region == nil && rowRegions.isEmpty { complete = false }
                        if !rowNationwide, let region, !rowRegions.isEmpty, !rowRegions.contains(where: {
                            let code = $0.contains("-") || $0 == query.country ? $0 : query.country + "-" + $0
                            return code == region.code || code.hasPrefix(region.code + "-") || region.code.hasPrefix(code + "-")
                        }) { complete = false }
                        if let region {
                            group.selected.insert(region.code)
                            if !region.name.isEmpty { group.names.insert(region.name) }
                            if !groupScope && !rowNationwide && rowRegions.isEmpty { rowRegions.insert(region.code) }
                        }
                        group.regions.formUnion(rowRegions)
                        groups[key] = group
                        guard groups.count <= 20_000 else { throw BetaError("The holiday service returned too many entries.") }
                    }
                    // A successful HTTP response alone is not evidence that all
                    // requested school calendars were supplied.
                    if groupScope {
                        let required = region.map { Set([$0.code]) } ?? schoolGroups
                        if !required.isSubset(of: observedGroups) { complete = false }
                    }
                    if complete {
                        coverage.append(Coverage(country: query.country, region: region?.code ?? "", kind: kind,
                            start: String(format: "%04d-01-01", year), end: String(format: "%04d-12-31", year)))
                    }
                }
            }
        }
        let entries = groups.values.map { value in
            let names = value.names.sorted()
            var title = value.name
            var regionLabel = names.first ?? ""
            if query.regions.count > 1 && !names.isEmpty {
                let allNames = Set(query.regions.map { $0.name })
                let label: String
                if groupSelection {
                    label = names.joined(separator: ", ")
                } else if value.names == allNames {
                    label = query.language == "DE" ? (query.country == "CH" ? "alle Kantone" : "alle Bundesländer")
                        : (query.country == "CH" ? "all cantons" : "all states")
                } else if names.count > allNames.count / 2 {
                    label = (query.language == "DE" ? "alle außer " : "all except ") + allNames.subtracting(value.names).sorted().joined(separator: ", ")
                } else { label = names.joined(separator: ", ") }
                title += " (" + label + ")"
                regionLabel = label
            }
            return Entry(start: value.start, end: value.end, name: title, kind: value.kind,
                  country: query.country, nationwide: value.nationwide, regions: value.regions.sorted(),
                  selectedRegions: value.selected.sorted(), regionNames: value.names.sorted(), regionLabel: regionLabel)
        }.sorted { ($0.start, $0.name, $0.kind) < ($1.start, $1.name, $1.kind) }
        try Task.checkCancellation()
        guard ProcessInfo.processInfo.systemUptime < deadline else { throw BetaError("Holiday retrieval timed out; no partial result was applied.") }
        return Result(entries: entries, coverage: coverage)
    }
}
