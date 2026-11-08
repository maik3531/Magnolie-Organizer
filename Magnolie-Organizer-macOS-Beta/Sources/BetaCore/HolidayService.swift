import Foundation
import CoreFoundation

/// Public holiday data only. The server and endpoints are fixed; no account
/// credentials or user-provided URLs are sent to this service.
public struct HolidayService {
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
                guard HolidayService.matches(code, "^[A-Z0-9-]{1,64}$"), region.name.count <= 256 else {
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
        public var organizerValue: [String: Any] {
            ["von": start, "bis": end, "name": name, "art": kind, "country": country,
             "nationwide": nationwide, "regions": regions,
             "region": selectedRegions.joined(separator: ","), "regionName": regionNames.joined(separator: ", ")]
        }
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
        let selections: [Region?] = query.regions.isEmpty ? [nil] : query.regions.map { Optional($0) }
        let kinds = query.includeSchool ? [("PublicHolidays", "public-holiday"), ("SchoolHolidays", "school-holiday")]
                                       : [("PublicHolidays", "public-holiday")]
        var groups: [GroupKey: Group] = [:]
        var receivedBytes = 0
        let deadline = ProcessInfo.processInfo.systemUptime + 90
        for year in query.years {
            for (endpoint, kind) in kinds {
                for region in selections {
                    try Task.checkCancellation()
                    let remaining = deadline - ProcessInfo.processInfo.systemUptime
                    guard remaining > 0 else { throw BetaError("Holiday retrieval timed out; no partial result was applied.") }
                    var url = URLComponents(string: "https://openholidaysapi.org/" + endpoint)!
                    url.queryItems = [URLQueryItem(name: "countryIsoCode", value: query.country),
                        URLQueryItem(name: "languageIsoCode", value: query.language),
                        URLQueryItem(name: "validFrom", value: String(format: "%04d-01-01", year)),
                        URLQueryItem(name: "validTo", value: String(format: "%04d-12-31", year))]
                    if let region { url.queryItems!.append(URLQueryItem(name: "subdivisionCode", value: region.code)) }
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
                    for row in rows {
                        try Task.checkCancellation()
                        guard ProcessInfo.processInfo.systemUptime < deadline else { throw BetaError("Holiday retrieval timed out; no partial result was applied.") }
                        let start = String((row["startDate"] as? String ?? "").prefix(10))
                        let rawEnd = String((row["endDate"] as? String ?? start).prefix(10))
                        guard Self.validDate(start), Self.validDate(rawEnd), rawEnd >= start,
                              let title = Self.name(row["name"], language: query.language), !title.isEmpty, title.count <= 1024 else {
                            throw BetaError("The holiday service returned an invalid entry; no partial result was applied.")
                        }
                        let key = GroupKey(start: start, end: rawEnd,
                            name: title.precomposedStringWithCompatibilityMapping.lowercased(), kind: kind)
                        var group = groups[key] ?? Group(start: start, end: rawEnd, name: title, kind: kind)
                        if let nationwide = row["nationwide"] as? NSNumber,
                           CFGetTypeID(nationwide) == CFBooleanGetTypeID(), nationwide.boolValue { group.nationwide = true }
                        if let subdivisions = row["subdivisions"] as? [[String: Any]] {
                            for subdivision in subdivisions {
                                guard let code = subdivision["code"] as? String, Self.matches(code, "^[A-Z0-9-]{1,64}$") else {
                                    throw BetaError("The holiday service returned invalid regional scope.")
                                }
                                group.regions.insert(code)
                            }
                        }
                        if let region {
                            group.selected.insert(region.code)
                            if !region.name.isEmpty { group.names.insert(region.name) }
                            if !group.nationwide && group.regions.isEmpty { group.regions.insert(region.code) }
                        }
                        groups[key] = group
                        guard groups.count <= 20_000 else { throw BetaError("The holiday service returned too many entries.") }
                    }
                }
            }
        }
        return groups.values.map { value in
            let names = value.names.sorted()
            var title = value.name
            if query.regions.count > 1 && !names.isEmpty {
                let allNames = Set(query.regions.map { $0.name })
                let label: String
                if value.names == allNames {
                    label = query.language == "DE" ? (query.country == "CH" ? "alle Kantone" : "alle Bundesländer")
                        : (query.country == "CH" ? "all cantons" : "all states")
                } else if names.count > allNames.count / 2 {
                    label = (query.language == "DE" ? "alle außer " : "all except ") + allNames.subtracting(value.names).sorted().joined(separator: ", ")
                } else { label = names.joined(separator: ", ") }
                title += " (" + label + ")"
            }
            return Entry(start: value.start, end: value.end, name: title, kind: value.kind,
                  country: query.country, nationwide: value.nationwide, regions: value.regions.sorted(),
                  selectedRegions: value.selected.sorted(), regionNames: value.names.sorted())
        }.sorted { ($0.start, $0.name, $0.kind) < ($1.start, $1.name, $1.kind) }
    }
}
