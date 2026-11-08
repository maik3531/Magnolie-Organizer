import Foundation
import CoreFoundation
import CryptoKit

/// Pure, all-or-nothing iCalendar decoding. No disk, account or application state
/// is changed. Recurrences remain source properties; no occurrence list is made.
public enum ICalendarImport {
    public static let maximumBytes = 32 * 1024 * 1024
    public static let maximumRecords = 50_000
    public static let maximumProjectedBytes = 96 * 1024 * 1024
    public struct Result {
        public let appointments: [[String: Any]]
        public let tasks: [[String: Any]]
        public let anniversaries: [[String: Any]]
        public let calendarProperties: [String]
        public let sourceSHA256: String
        public var document: [String: Any] {
            ["termine": appointments, "aufgaben": tasks, "jahrestage": anniversaries,
             "icsImportMetadata": ["version": 1, "calendarProperties": calendarProperties, "sourceSHA256": sourceSHA256]]
        }
    }
    private struct Property {
        let line: String, name: String, value: String, header: String
        let parameters: [String: String]
        init(_ line: String) throws {
            guard !line.isEmpty, !line.contains("\0"), !line.contains("\r"), !line.contains("\n") else { throw BetaError("Invalid calendar content line.") }
            var quoted = false, separator: String.Index?
            for index in line.indices {
                if line[index] == "\"" { quoted.toggle() }
                else if line[index] == ":" && !quoted { separator = index; break }
            }
            guard let separator, !quoted else { throw BetaError("Invalid calendar property header.") }
            let header = String(line[..<separator])
            var fields: [String] = [], current = ""; quoted = false
            for character in header {
                if character == "\"" { quoted.toggle() }
                if character == ";" && !quoted { fields.append(current); current = "" }
                else { current.append(character) }
            }
            fields.append(current)
            guard let name = fields.first, ICalendarImport.matches(name, "^[A-Za-z0-9-]+$") else { throw BetaError("Invalid calendar property name.") }
            var parameters: [String: String] = [:]
            for field in fields.dropFirst() {
                let pair = field.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard pair.count == 2, ICalendarImport.matches(pair[0], "^[A-Za-z0-9-]+$"), parameters[pair[0].uppercased()] == nil else { throw BetaError("Invalid calendar parameter.") }
                var value = pair[1]
                if value.hasPrefix("\"") { guard value.hasSuffix("\""), value.count >= 2 else { throw BetaError("Invalid quoted calendar parameter.") }; value = String(value.dropFirst().dropLast()) }
                parameters[pair[0].uppercased()] = value
            }
            self.line = line; self.name = name.uppercased(); self.parameters = parameters; self.header = header
            self.value = String(line[line.index(after: separator)...])
        }
        func renamed(_ name: String, removing: Set<String> = []) -> String {
            let pairs = parameters.keys.sorted().filter { !removing.contains($0) }.map { key -> String in
                let value = parameters[key]!
                return ";" + key + "=" + (value.contains(":") || value.contains(";") || value.contains(",") ? "\"" + value + "\"" : value)
            }.joined()
            return name + pairs + ":" + value
        }
    }
    private final class Component {
        let name: String
        var properties: [Property] = []
        var children: [Component] = []
        var lines: [String] = []
        init(_ name: String, line: String) { self.name = name; lines = [line] }
        func property(_ name: String) -> Property? { properties.first(where: { $0.name == name }) }
        func value(_ name: String) -> String { property(name).map { ICalendarImport.unescape($0.value) } ?? "" }
    }
    private struct Clock { let instant: Date, wall: Date; let dateOnly: Bool; let source: String }
    private static let utc = TimeZone(secondsFromGMT: 0)!
    private static let absoluteUTC = "@magnolie-utc-instant"
    private static var utcCalendar: Calendar { ICalendarImport.calendar(ICalendarImport.utc) }
    private static func calendar(_ zone: TimeZone) -> Calendar { var c = Calendar(identifier: .gregorian); c.timeZone = zone; c.locale = Locale(identifier: "en_US_POSIX"); return c }
    private static func matches(_ text: String, _ pattern: String) -> Bool { text.range(of: pattern, options: .regularExpression) != nil }
    private static func hash(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
    private static func unescape(_ value: String) -> String {
        var result = "", escaped = false
        for c in value {
            if escaped { result.append(c == "n" || c == "N" ? "\n" : c); escaped = false }
            else if c == "\\" { escaped = true }
            else { result.append(c) }
        }
        if escaped { result.append("\\") }; return result
    }
    private static func format(_ date: Date, _ pattern: String, _ zone: TimeZone = ICalendarImport.utc) -> String {
        let f = DateFormatter(); f.calendar = ICalendarImport.calendar(zone); f.timeZone = zone; f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = pattern; return f.string(from: date)
    }
    private static func naive(_ text: String) throws -> Date {
        let value = text.uppercased()
        guard ICalendarImport.matches(value, "^[0-9]{8}(?:T[0-9]{4}(?:[0-9]{2})?)?$"), let year = Int(value.prefix(4)), (1...9999).contains(year) else { throw BetaError("Invalid calendar date/time.") }
        let pattern = value.count == 8 ? "yyyyMMdd" : value.count == 13 ? "yyyyMMdd'T'HHmm" : "yyyyMMdd'T'HHmmss"
        let f = DateFormatter(); f.calendar = ICalendarImport.utcCalendar; f.timeZone = ICalendarImport.utc; f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = pattern; f.isLenient = false
        guard let result = f.date(from: value), f.string(from: result) == value else { throw BetaError("Invalid calendar date/time.") }; return result
    }
    private static func knownZone(_ name: String) throws -> TimeZone {
        guard !name.isEmpty, name.utf8.count <= 255, let zone = TimeZone(identifier: name) else { throw BetaError("The calendar references an unresolved time zone.") }; return zone
    }
    private static func ordinaryWall(_ wall: Date, zone: TimeZone) throws -> Date {
        let components = ICalendarImport.utcCalendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: wall)
        guard let instant = ICalendarImport.calendar(zone).nextDate(after: wall.addingTimeInterval(-172800), matching: components,
                      matchingPolicy: .strict, repeatedTimePolicy: .first, direction: .forward),
              ICalendarImport.format(instant, "yyyyMMdd'T'HHmmss", zone) == ICalendarImport.format(wall, "yyyyMMdd'T'HHmmss") else {
            throw BetaError("A calendar wall time falls in a daylight-saving gap.")
        }; return instant
    }
    private static func integer(_ text: String, default fallback: Int = 0) throws -> Int {
        if text.isEmpty { return fallback }
        guard let n = Int(text), abs(Double(n)) <= 9_007_199_254_740_991 else { throw BetaError("Invalid integer calendar property.") }; return n
    }
    private static func foldedKey(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "en_US_POSIX"))
            .replacingOccurrences(of: "ß", with: "ss").split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }
    private static let anniversaryTypes = [
        "birthday": ["Birthday", "Geburtstag"], "death-anniversary": ["Death anniversary", "Todestag"],
        "wedding-anniversary": ["Wedding anniversary", "Hochzeitstag"], "partnership-anniversary": ["Partnership anniversary", "Partnerschaftstag"],
        "name-day": ["Name day", "Namenstag"], "baptism": ["Baptism", "Tauftag"], "first-communion": ["First Communion", "Kommunion"],
        "confirmation": ["Confirmation", "Konfirmation"], "catholic-confirmation": ["Catholic confirmation", "Firmung"],
        "anniversary": ["Anniversary", "Jubiläum"], "club-anniversary": ["Club anniversary", "Vereinsjubiläum"],
        "work-anniversary": ["Work anniversary", "Dienstjubiläum"], "founding-day": ["Founding day", "Gründungstag"],
        "memorial-day": ["Memorial day", "Gedenktag"], "other": ["Other", "Sonstiges"]]
    private static func anniversaryType(_ value: String) -> String {
        let key = foldedKey(value)
        return anniversaryTypes.first(where: { foldedKey($0.key) == key || $0.value.contains(where: { foldedKey($0) == key }) })?.key ?? ""
    }
    private static func unfold(_ text: String) throws -> [String] {
        guard !text.contains("\0") else { throw BetaError("Calendar files cannot contain NUL bytes.") }
        // Swift Character treats CRLF as one extended grapheme cluster, so
        // splitting directly on the LF Character would leave CRLF files whole.
        // Normalize the paired wire terminator first; reject every remaining CR.
        // Count before split: even a byte-bounded file may contain millions of
        // tiny lines. Include split's final (possibly empty) physical line.
        var physicalCount = 1
        for byte in text.utf8 where byte == 10 {
            physicalCount += 1
            guard physicalCount <= 250_000 else { throw BetaError("Calendar file has too many lines.") }
        }
        let physical = text.replacingOccurrences(of: "\r\n", with: "\n").split(separator: "\n", omittingEmptySubsequences: false)
        guard physical.count <= 250_000 else { throw BetaError("Calendar file has too many lines.") }
        var lines: [String] = []
        for raw in physical {
            let line = String(raw)
            guard !line.contains("\r"), line.unicodeScalars.allSatisfy({ $0.value >= 32 || $0 == "\t" }) else { throw BetaError("Invalid calendar line/control character.") }
            if line.first == " " || line.first == "\t" {
                guard !lines.isEmpty else { throw BetaError("Calendar continuation has no preceding property.") }
                guard lines[lines.count - 1].utf8.count + line.utf8.count - 1 <= 1024 * 1024 else { throw BetaError("Calendar content line is too large.") }
                lines[lines.count - 1] += line.dropFirst()
            } else if !line.isEmpty {
                guard line.utf8.count <= 1024 * 1024 else { throw BetaError("Calendar content line is too large.") }
                lines.append(line)
            }
        }
        return lines
    }
    private static func parse(_ lines: [String]) throws -> [Component] {
        var stack: [Component] = [], roots: [Component] = [], count = 0
        let singleton: Set<String> = ["UID", "DTSTART", "DTEND", "DUE", "DURATION", "SUMMARY", "DESCRIPTION", "DTSTAMP", "LAST-MODIFIED", "RECURRENCE-ID", "SEQUENCE", "STATUS", "CLASS", "PRIORITY", "PERCENT-COMPLETE", "X-MAGNOLIE-TASK-IDENTITY"]
        for line in lines {
            let property = try Property(line)
            if property.name == "BEGIN" {
                let type = property.value.uppercased(), parent = stack.last?.name
                let allowed = parent == nil ? ["VCALENDAR", "VEVENT", "VTODO"] : parent == "VCALENDAR" ? ["VEVENT", "VTODO", "VTIMEZONE"] :
                    parent == "VTIMEZONE" ? ["STANDARD", "DAYLIGHT"] : ["VEVENT", "VTODO"].contains(parent!) ? ["VALARM"] : []
                guard allowed.contains(type), stack.count < 8, count < maximumRecords else { throw BetaError("Unsupported or excessively nested calendar component; nothing was imported.") }
                for ancestor in stack { ancestor.lines.append(line) }
                let component = Component(type, line: line)
                if let parent = stack.last { parent.children.append(component) } else { roots.append(component) }
                stack.append(component); count += 1
            } else if property.name == "END" {
                guard let current = stack.last, current.name == property.value.uppercased() else { throw BetaError("The calendar file is incomplete or unbalanced.") }
                for ancestor in stack { ancestor.lines.append(line) }; stack.removeLast()
            } else {
                guard let current = stack.last else { throw BetaError("A calendar property appears outside a component.") }
                if singleton.contains(property.name), current.properties.contains(where: { $0.name == property.name }) { throw BetaError("Ambiguous duplicate calendar property.") }
                current.properties.append(property)
                for ancestor in stack { ancestor.lines.append(line) }
            }
        }
        guard stack.isEmpty, !roots.isEmpty, roots.filter({ $0.name == "VCALENDAR" }).count <= 1,
              roots.count == 1 || !roots.contains(where: { $0.name == "VCALENDAR" }) else { throw BetaError("Import one complete calendar per transaction.") }
        if let root = roots.first, root.name == "VCALENDAR" {
            guard root.properties.filter({ $0.name == "VERSION" }).count == 1, root.value("VERSION") == "2.0" else { throw BetaError("Only iCalendar VERSION 2.0 is supported.") }
        }
        return roots
    }
    /// A calendar-scoped VTIMEZONE resolver. It evaluates only observance rules
    /// adjacent to a queried clock; the event's RRULE is never expanded here.
    private final class EmbeddedZone {
        struct Observance {
            let start: Date, before: Int, after: Int, dates: [Date], rule: [String: String]
        }
        let observations: [Observance]
        private var cachedTransitions: [Int: [(Date, Int)]] = [:]
        static func offset(_ value: String) throws -> Int {
            guard ICalendarImport.matches(value, "^[+-][0-9]{4}(?:[0-9]{2})?$") else { throw BetaError("Invalid embedded time-zone offset.") }
            let chars = Array(value), hour = Int(String(chars[1...2]))!, minute = Int(String(chars[3...4]))!
            let second = chars.count == 7 ? Int(String(chars[5...6]))! : 0
            guard hour <= 23, minute < 60, second < 60 else { throw BetaError("Invalid embedded time-zone offset.") }
            return (value.first == "-" ? -1 : 1) * (hour * 3600 + minute * 60 + second)
        }
        init(_ component: Component) throws {
            guard !component.children.isEmpty, component.children.count <= 4096 else { throw BetaError("Invalid embedded time-zone observances.") }
            var result: [Observance] = []
            for child in component.children {
                guard ["STANDARD", "DAYLIGHT"].contains(child.name), let start = child.property("DTSTART"),
                      !start.value.uppercased().hasSuffix("Z"), child.properties.filter({ $0.name == "TZOFFSETFROM" }).count == 1,
                      child.properties.filter({ $0.name == "TZOFFSETTO" }).count == 1 else { throw BetaError("Incomplete embedded time-zone observance.") }
                let before = try Self.offset(child.value("TZOFFSETFROM")), after = try Self.offset(child.value("TZOFFSETTO"))
                let begin = try ICalendarImport.naive(start.value)
                var dates: [Date] = []
                for property in child.properties where property.name == "RDATE" {
                    guard property.parameters.isEmpty, dates.count <= 50_000 else { throw BetaError("Unsupported embedded transition dates.") }
                    dates += try property.value.split(separator: ",", omittingEmptySubsequences: false).map { try ICalendarImport.naive(String($0)) }
                }
                var rule: [String: String] = [:]
                let rules = child.properties.filter { $0.name == "RRULE" }
                guard rules.count <= 1 else { throw BetaError("Ambiguous embedded time-zone rule.") }
                if let source = rules.first {
                    rule = try ICalendarImport.ruleDictionary(source.value)
                    guard rule["FREQ"] == "YEARLY", rule["COUNT"] == nil,
                          rule["INTERVAL"] == nil || rule["INTERVAL"] == "1",
                          rule["BYMONTH"] != nil || ["BYMONTHDAY", "BYDAY", "BYSETPOS"].allSatisfy({ rule[$0] == nil }),
                          Set(rule.keys).isSubset(of: ["FREQ", "INTERVAL", "BYMONTH", "BYMONTHDAY", "BYDAY", "BYSETPOS", "UNTIL", "WKST"]) else {
                        throw BetaError("This embedded time-zone rule cannot be resolved safely.")
                    }
                }
                result.append(Observance(start: begin, before: before, after: after, dates: dates, rule: rule))
            }
            observations = result
        }
        private func ruleDates(_ observation: Observance, year: Int) throws -> [Date] {
            let rule = observation.rule
            if rule.isEmpty { return [] }
            let anchor = ICalendarImport.utcCalendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: observation.start)
            let interval = try ICalendarImport.integer(rule["INTERVAL"] ?? "1", default: 1)
            guard interval > 0 else { throw BetaError("Invalid embedded time-zone interval.") }
            if year < anchor.year! || (year - anchor.year!) % interval != 0 { return [] }
            let months = try rule["BYMONTH"].map { try $0.split(separator: ",").map { try ICalendarImport.integer(String($0)) } } ?? [anchor.month!]
            guard months.allSatisfy({ (1...12).contains($0) }) else { throw BetaError("Invalid embedded time-zone month.") }
            let dayRules = rule["BYDAY"]?.split(separator: ",").map(String.init) ?? []
            var dates: [Date] = []
            for month in months {
                guard let first = ICalendarImport.utcCalendar.date(from: DateComponents(year: year, month: month, day: 1)),
                      let range = ICalendarImport.utcCalendar.range(of: .day, in: .month, for: first) else { throw BetaError("Invalid embedded transition year.") }
                let monthDays = try rule["BYMONTHDAY"].map { try $0.split(separator: ",").map { try ICalendarImport.integer(String($0)) } }
                for day in range {
                    if let monthDays, !monthDays.contains(day), !monthDays.contains(day - range.count - 1) { continue }
                    if monthDays == nil && dayRules.isEmpty && day != anchor.day! { continue }
                    let date = ICalendarImport.utcCalendar.date(from: DateComponents(year: year, month: month, day: day, hour: anchor.hour, minute: anchor.minute, second: anchor.second))!
                    let weekday = ICalendarImport.utcCalendar.component(.weekday, from: date)
                    if !dayRules.isEmpty {
                        var accepted = false
                        for selector in dayRules {
                            guard selector.count >= 2, ["SU", "MO", "TU", "WE", "TH", "FR", "SA"].contains(String(selector.suffix(2))) else { throw BetaError("Invalid embedded transition weekday.") }
                            let wanted = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"].firstIndex(of: String(selector.suffix(2)))! + 1
                            if wanted != weekday { continue }
                            let prefix = String(selector.dropLast(2))
                            if prefix.isEmpty { accepted = true }
                            else {
                                let ordinal = try ICalendarImport.integer(prefix)
                                guard ordinal != 0, abs(ordinal) <= 53 else { throw BetaError("Invalid embedded transition ordinal.") }
                                if ordinal > 0 && (day - 1) / 7 + 1 == ordinal || ordinal < 0 && -((range.count - day) / 7 + 1) == ordinal { accepted = true }
                            }
                        }
                        if !accepted { continue }
                    }
                    if date >= observation.start { dates.append(date) }
                }
            }
            dates = Array(Set(dates)).sorted()
            if let positions = rule["BYSETPOS"] {
                var selected: [Date] = []
                for field in positions.split(separator: ",") {
                    let number = try ICalendarImport.integer(String(field)); guard number != 0, abs(number) <= 366 else { throw BetaError("Invalid embedded transition position.") }
                    let index = number > 0 ? number - 1 : dates.count + number
                    if dates.indices.contains(index) { selected.append(dates[index]) }
                }
                dates = Array(Set(selected)).sorted()
            }
            if let until = rule["UNTIL"] {
                let utcUntil = until.hasSuffix("Z")
                let last = try ICalendarImport.naive(utcUntil ? String(until.dropLast()) : until)
                dates = dates.filter { (utcUntil ? $0.addingTimeInterval(Double(-observation.before)) : $0) <= last }
            }
            return dates
        }
        private func activeOffset(at instant: Date) throws -> Int {
            let earliest = observations.min { $0.start.addingTimeInterval(Double(-$0.before)) < $1.start.addingTimeInterval(Double(-$1.before)) }!
            let year = ICalendarImport.utcCalendar.component(.year, from: instant)
            let transitions: [(Date, Int)]
            if let cached = cachedTransitions[year] { transitions = cached }
            else {
                var collected: [(Date, Int)] = []
                for observation in observations {
                    var walls = [observation.start] + observation.dates
                    if !observation.rule.isEmpty {
                        var years = Set(max(1, year - 1)...min(9999, year + 1))
                        // A finite observance's last transition remains in force
                        // after UNTIL. Evaluate its boundary, not all intervening years.
                        if let until = observation.rule["UNTIL"] {
                            let last = try ICalendarImport.naive(until.hasSuffix("Z") ? String(until.dropLast()) : until)
                            let endYear = ICalendarImport.utcCalendar.component(.year, from: last)
                            years.formUnion(max(1, endYear - 1)...min(9999, endYear + 1))
                        }
                        for candidate in years.sorted() { walls += try ruleDates(observation, year: candidate) }
                    }
                    collected += walls.map { ($0.addingTimeInterval(Double(-observation.before)), observation.after) }
                }
                collected.sort { $0.0 < $1.0 }
                for index in collected.indices.dropFirst() {
                    if collected[index].0 == collected[index - 1].0 && collected[index].1 != collected[index - 1].1 { throw BetaError("Conflicting embedded time-zone transitions.") }
                }
                if cachedTransitions.count >= 64 { cachedTransitions.removeAll(keepingCapacity: true) }
                cachedTransitions[year] = collected; transitions = collected
            }
            var low = 0, high = transitions.count
            while low < high { let mid = (low + high) / 2; if transitions[mid].0 <= instant { low = mid + 1 } else { high = mid } }
            return low == 0 ? earliest.before : transitions[low - 1].1
        }
        func instant(_ wall: Date) throws -> Date {
            var candidates: [Date] = []
            for offset in Set(observations.flatMap { [$0.before, $0.after] }) {
                let instant = wall.addingTimeInterval(Double(-offset))
                if try activeOffset(at: instant) == offset { candidates.append(instant) }
            }
            guard let first = candidates.min() else { throw BetaError("A source time falls in an embedded time-zone gap.") }; return first
        }
    }
    private struct Resolver {
        let display: TimeZone, displayName: String, zones: [String: EmbeddedZone]
        func instant(_ wall: Date, source: String) throws -> Date {
            if source == ICalendarImport.absoluteUTC { return wall }
            if let zone = zones[source] { return try zone.instant(wall) }
            return try ICalendarImport.ordinaryWall(wall, zone: source.isEmpty ? display : ICalendarImport.knownZone(source))
        }
        func clock(_ property: Property) throws -> Clock {
            let value = property.value.trimmingCharacters(in: .whitespaces).uppercased()
            let dateOnly = property.parameters["VALUE"]?.uppercased() == "DATE" || ICalendarImport.matches(value, "^[0-9]{8}$")
            if dateOnly {
                guard ICalendarImport.matches(value, "^[0-9]{8}$"), property.parameters["TZID"] == nil else { throw BetaError("Invalid date-only source property.") }
                let date = try ICalendarImport.naive(value); return Clock(instant: date, wall: date, dateOnly: true, source: ICalendarImport.absoluteUTC)
            }
            guard property.parameters["VALUE"] == nil || property.parameters["VALUE"]?.uppercased() == "DATE-TIME",
                  ICalendarImport.matches(value, "^[0-9]{8}T[0-9]{4}(?:[0-9]{2})?Z?$"), !value.hasSuffix("Z") || property.parameters["TZID"] == nil else { throw BetaError("Invalid source calendar date-time.") }
            let source = value.hasSuffix("Z") ? ICalendarImport.absoluteUTC : property.parameters["TZID"] ?? ""
            let wall = try ICalendarImport.naive(value.hasSuffix("Z") ? String(value.dropLast()) : value)
            let resolved = try instant(wall, source: source)
            let year = ICalendarImport.calendar(display).component(.year, from: resolved)
            guard ICalendarImport.calendar(display).component(.era, from: resolved) == 1, (1...9999).contains(year) else { throw BetaError("Calendar time is outside the supported display range.") }
            return Clock(instant: resolved, wall: wall, dateOnly: false, source: source)
        }
        func duration(_ specification: String, from start: Clock) throws -> Clock {
            let expression = try NSRegularExpression(pattern: "^\\+?P(?:(\\d+)W|(?:(\\d+)D)?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?)?)$")
            guard let match = expression.firstMatch(in: specification, range: NSRange(specification.startIndex..<specification.endIndex, in: specification)) else { throw BetaError("Invalid calendar duration.") }
            var values: [Int] = [], present = false
            for index in 1...5 {
                if let range = Range(match.range(at: index), in: specification) {
                    let value = try ICalendarImport.integer(String(specification[range])); guard (0...1_000_000).contains(value) else { throw BetaError("Calendar duration is too large.") }
                    values.append(value); present = true
                } else { values.append(0) }
            }
            guard present, !start.dateOnly || values[2...4].allSatisfy({ $0 == 0 }),
                  let wall = ICalendarImport.utcCalendar.date(byAdding: .day, value: values[0] * 7 + values[1], to: start.wall) else { throw BetaError("Invalid calendar duration.") }
            let exact = Double(values[2] * 3600 + values[3] * 60 + values[4])
            let instant = try self.instant(wall, source: start.source).addingTimeInterval(exact)
            return Clock(instant: instant, wall: wall.addingTimeInterval(exact), dateOnly: start.dateOnly, source: start.source)
        }
        func date(_ clock: Clock) -> String { ICalendarImport.format(clock.instant, "yyyy-MM-dd", clock.dateOnly ? ICalendarImport.utc : display) }
        func time(_ clock: Clock) -> String { clock.dateOnly ? "" : ICalendarImport.format(clock.instant, "HH:mm", display) }
    }
    private static func ruleDictionary(_ value: String) throws -> [String: String] {
        var result: [String: String] = [:]
        let allowed: Set<String> = ["FREQ", "INTERVAL", "COUNT", "UNTIL", "BYSECOND", "BYMINUTE", "BYHOUR", "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS", "WKST"]
        for field in value.uppercased().split(separator: ";", omittingEmptySubsequences: false) {
            let pair = field.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
            guard pair.count == 2, !pair[1].isEmpty, allowed.contains(pair[0]), result[pair[0]] == nil else { throw BetaError("Invalid or unsupported recurrence rule.") }
            result[pair[0]] = pair[1]
        }
        guard ["SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"].contains(result["FREQ"] ?? ""), result["COUNT"] == nil || result["UNTIL"] == nil else { throw BetaError("Invalid recurrence frequency/end.") }
        for key in ["INTERVAL", "COUNT"] { if let value = result[key] { guard try ICalendarImport.integer(value) > 0 else { throw BetaError("Invalid recurrence count/interval.") } } }
        for (key, lower, upper, zero) in [("BYSECOND", 0, 60, true), ("BYMINUTE", 0, 59, true), ("BYHOUR", 0, 23, true), ("BYMONTH", 1, 12, false), ("BYMONTHDAY", -31, 31, false), ("BYYEARDAY", -366, 366, false), ("BYWEEKNO", -53, 53, false), ("BYSETPOS", -366, 366, false)] {
            if let value = result[key] {
                for token in value.split(separator: ",", omittingEmptySubsequences: false) {
                    let number = try ICalendarImport.integer(String(token)); guard number >= lower, number <= upper, zero || number != 0 else { throw BetaError("Invalid recurrence selector.") }
                }
            }
        }
        if let value = result["BYDAY"] {
            guard value.split(separator: ",", omittingEmptySubsequences: false).allSatisfy({ ICalendarImport.matches(String($0), "^(?:[+-]?(?:[1-9]|[1-4][0-9]|5[0-3]))?(?:MO|TU|WE|TH|FR|SA|SU)$") }) else { throw BetaError("Invalid recurrence weekday.") }
        }
        if let value = result["WKST"], !["MO", "TU", "WE", "TH", "FR", "SA", "SU"].contains(value) { throw BetaError("Invalid recurrence week start.") }
        if let value = result["UNTIL"] { _ = try ICalendarImport.naive(value.hasSuffix("Z") ? String(value.dropLast()) : value) }
        return result
    }
    private static func simpleRule(_ fields: [String: String], start: Clock, resolver: Resolver) throws -> [String: Any]? {
        let frequencies = ["DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly", "YEARLY": "yearly"]
        guard let type = frequencies[fields["FREQ"] ?? ""], Set(fields.keys).isSubset(of: ["FREQ", "INTERVAL", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"]) else { return nil }
        let interval = try ICalendarImport.integer(fields["INTERVAL"] ?? "1", default: 1)
        guard (1...3660).contains(interval), ["daily", "weekly"].contains(type) || interval == 1 else { return nil }
        let date = try ICalendarImport.naive(resolver.date(start).replacingOccurrences(of: "-", with: ""))
        let components = ICalendarImport.utcCalendar.dateComponents([.weekday, .day, .month], from: date)
        var ordinal: Int?, weekday = ""
        if type == "daily" {
            if ["BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS"].contains(where: { fields[$0] != nil }) { return nil }
        } else if type == "weekly" {
            let expected = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"][components.weekday! - 1]
            if fields["BYDAY"] != nil && fields["BYDAY"] != expected || ["BYMONTHDAY", "BYMONTH", "BYSETPOS"].contains(where: { fields[$0] != nil }) { return nil }
        } else if type == "monthly" {
            if let byDay = fields["BYDAY"] {
                guard fields["BYMONTHDAY"] == nil, fields["BYMONTH"] == nil,
                      ICalendarImport.matches(byDay, "^(?:-1|[1-4])?(?:MO|TU|WE|TH|FR|SA|SU)$") else { return nil }
                weekday = String(byDay.suffix(2))
                let number = String(byDay.dropLast(2))
                if !number.isEmpty { guard fields["BYSETPOS"] == nil else { return nil }; ordinal = try ICalendarImport.integer(number) }
                else if let position = fields["BYSETPOS"], ["-1", "1", "2", "3", "4"].contains(position) { ordinal = try ICalendarImport.integer(position) }
                else { return nil }
            } else if fields["BYSETPOS"] != nil || fields["BYMONTH"] != nil || components.day! > 28 ||
                        fields["BYMONTHDAY"] != nil && fields["BYMONTHDAY"] != String(components.day!) { return nil }
        } else {
            if fields["BYDAY"] != nil || fields["BYSETPOS"] != nil || fields["BYMONTH"] != nil && fields["BYMONTH"] != String(components.month!) ||
                fields["BYMONTHDAY"] != nil && fields["BYMONTHDAY"] != String(components.day!) || components.month == 2 && components.day == 29 { return nil }
        }
        var until = ""
        if let value = fields["UNTIL"] {
            if value.contains("T") && !value.hasSuffix("00") && !value.hasSuffix("00Z") { return nil }
            let property = try Property("DTSTART" + (value.count == 8 ? ";VALUE=DATE" : "") + ":" + value)
            let ending = try resolver.clock(property)
            var last = ending.instant
            if !ending.dateOnly && !resolver.time(start).isEmpty && resolver.time(ending) < resolver.time(start) {
                last = ICalendarImport.calendar(resolver.display).date(byAdding: .day, value: -1, to: last)!
            }
            until = ICalendarImport.format(last, "yyyy-MM-dd", ending.dateOnly ? ICalendarImport.utc : resolver.display)
        }
        var result: [String: Any] = ["art": type, "bis": until]
        if interval > 1 { result["intervall"] = interval }
        if let ordinal { result["ordinal"] = ordinal; result["wochentag"] = weekday; if fields["BYSETPOS"] != nil { result["rruleForm"] = "bysetpos" } }
        return result
    }
    private static func rawProperties(_ component: Component, complex: Bool) throws -> [String] {
        var retained: Set<String> = ["RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID", "DURATION", "DTSTART", "DTEND", "DUE", "LOCATION", "URL", "ORGANIZER", "ATTENDEE", "ATTACH", "X-ALT-DESC", "TRANSP", "BEGIN", "END", "ACTION", "TRIGGER", "REPEAT"]
        let generated: Set<String> = ["UID", "DTSTAMP", "LAST-MODIFIED", "SEQUENCE", "DTSTART", "DTEND", "DUE", "SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "PRIORITY", "PERCENT-COMPLETE", "X-MAGNOLIE-ERINNERUNG-AM-TAG", "X-MAGNOLIE-KOSTENSTELLE", "X-MAGNOLIE-KUNDE", "X-MAGNOLIE-ERINNERUNG-TAGE", "X-MAGNOLIE-STANDARDERINNERUNG", "X-MAGNOLIE-DATE", "X-MAGNOLIE-REIHENFOLGE", "X-MAGNOLIE-TASK-IDENTITY", "X-MAGNOLIE-ACCENT-COLOR"]
        if component.property("RECURRENCE-ID") != nil { retained.formUnion(["SUMMARY", "DESCRIPTION", "CATEGORIES", "CLASS", "STATUS", "PRIORITY"]) }
        var depth = 0, result: [String] = []
        for line in component.lines.dropFirst().dropLast() {
            let property = try Property(line)
            if property.name == "BEGIN" { depth += 1 }
            let parentLink = property.name == "RELATED-TO" && property.parameters["RELTYPE"]?.uppercased() == "PARENT"
            if !parentLink && (depth > 0 || retained.contains(property.name) || !generated.contains(property.name) ||
                              property.name == "STATUS" && property.value.uppercased() == "CANCELLED" || !property.parameters.isEmpty) {
                result.append(line)
            }
            if property.name == "END" { depth -= 1 }
        }
        return result
    }
    private static func sourcePath(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "/").split(separator: "/").compactMap { piece -> String? in
            let safe = String(String.UnicodeScalarView(piece.unicodeScalars.filter { $0.value >= 32 && $0.value != 127 })).trimmingCharacters(in: .whitespaces)
            return safe.isEmpty || safe == "." || safe == ".." ? nil : safe.replacingOccurrences(of: ":", with: "_")
        }.joined(separator: "/")
    }
    private static func componentRecord(_ component: Component, complexUIDs: Set<String>, resolver: Resolver) throws -> (String, [String: Any]) {
        let wireUID = component.value("UID")
        guard !wireUID.isEmpty else { throw BetaError("Calendar items require a UID; nothing was imported.") }
        var baseUID = wireUID, taskIdentity: [String: Any]?
        if component.name == "VTODO", let property = component.property("X-MAGNOLIE-TASK-IDENTITY") {
            let identity = try Document.object(ICalendarImport.unescape(property.value))
            guard Set(identity.keys) == ["v", "source", "uid", "parent", "parentSource"],
                  let version = identity["v"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(), version.intValue == 1, version.doubleValue == 1,
                  ["source", "uid", "parent", "parentSource"].allSatisfy({ identity[$0] is String && !(identity[$0] as! String).contains("\0") }),
                  !(identity["uid"] as! String).isEmpty else { throw BetaError("Invalid source task identity.") }
            let sourceUID = identity["uid"] as! String, source = identity["source"] as! String
            let alias = "urn:magnolie:task:" + ICalendarImport.hash(Data((source + "\0" + sourceUID).utf8))
            guard wireUID == sourceUID || wireUID == alias || wireUID.hasPrefix(alias + "-") && ICalendarImport.matches(String(wireUID.dropFirst(alias.count + 1)), "^[1-9][0-9]*$") else {
                throw BetaError("Task identity does not match its calendar UID.")
            }
            baseUID = sourceUID; taskIdentity = identity
        }
        let seriesUID = baseUID
        let recurrence = component.property("RECURRENCE-ID")
        if let recurrence {
            let identity: [Any] = [recurrence.parameters, recurrence.value]
            let json = try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys, .withoutEscapingSlashes])
            baseUID += "-magnolie-instanz-" + ICalendarImport.hash(json).prefix(16)
        }
        var modified: Int64 = 0
        for name in ["LAST-MODIFIED", "DTSTAMP"] {
            if let property = component.property(name) {
                let clock = try resolver.clock(property)
                guard !clock.dateOnly else { throw BetaError("Invalid calendar modification timestamp.") }
                modified = Int64((clock.instant.timeIntervalSince1970 * 1000).rounded()); if modified != 0 { break }
            }
        }
        let sequence = try ICalendarImport.integer(component.value("SEQUENCE")); guard sequence >= 0 else { throw BetaError("Invalid calendar sequence.") }
        var rules: [String: [String: String]] = [:]
        for property in component.properties where ["RRULE", "EXRULE"].contains(property.name) {
            guard rules[property.name] == nil else { throw BetaError("Multiple source recurrence rules cannot be imported unambiguously.") }
            rules[property.name] = try ICalendarImport.ruleDictionary(property.value)
        }
        for alarm in component.children where alarm.name == "VALARM" {
            guard alarm.properties.filter({ $0.name == "ACTION" }).count == 1, alarm.properties.filter({ $0.name == "TRIGGER" }).count == 1 else { throw BetaError("An imported alarm is incomplete or ambiguous.") }
        }
        func reminder(_ name: String) throws -> Int { let n = try ICalendarImport.integer(component.value(name)); return (1...7).contains(n) ? n : 0 }
        func color() -> String { let text = component.value("X-MAGNOLIE-ACCENT-COLOR"); return ICalendarImport.matches(text, "^#[0-9a-fA-F]{6}$") ? text.lowercased() : "" }
        var raw = try rawProperties(component, complex: complexUIDs.contains(seriesUID))
        let title = component.value("SUMMARY")
        if component.name == "VTODO" {
            guard !title.isEmpty else { throw BetaError("An imported task has no title.") }
            let start = try component.property("DTSTART").map(resolver.clock)
            var end = try component.property("DUE").map(resolver.clock)
            if let specification = component.property("DURATION") {
                guard let start, end == nil else { throw BetaError("Ambiguous task duration.") }; end = try resolver.duration(specification.value, from: start)
            }
            if let start, let end { guard start.instant <= end.instant else { throw BetaError("Task end precedes start.") } }
            let priority = try ICalendarImport.integer(component.value("PRIORITY")); guard (0...9).contains(priority) else { throw BetaError("Invalid task priority.") }
            var parent = component.properties.first(where: { $0.name == "RELATED-TO" && $0.parameters["RELTYPE"]?.uppercased() == "PARENT" }).map { ICalendarImport.unescape($0.value) } ?? ""
            var parentSource = ""
            if let identity = taskIdentity {
                let originalParent = identity["parent"] as! String, originalSource = identity["parentSource"] as! String
                let alias = "urn:magnolie:task:" + ICalendarImport.hash(Data((originalSource + "\0" + originalParent).utf8))
                guard parent == originalParent || !originalParent.isEmpty && (parent == alias || parent.hasPrefix(alias + "-") && ICalendarImport.matches(String(parent.dropFirst(alias.count + 1)), "^[1-9][0-9]*$")) else { throw BetaError("Task parent identity does not match RELATED-TO.") }
                parent = originalParent; parentSource = originalSource
            }
            let order = try ICalendarImport.integer(component.value("X-MAGNOLIE-REIHENFOLGE")); guard order >= 0 else { throw BetaError("Invalid task ordering.") }
            raw.removeAll(where: { $0.hasPrefix("X-MAGNOLIE-TASK-IDENTITY:") })
            var result: [String: Any] = ["uid": baseUID, "titel": title, "faellig": end.map(resolver.date) ?? "", "faelligZeit": end.map(resolver.time) ?? "",
                "startDatum": start.map(resolver.date) ?? "", "startZeit": start.map(resolver.time) ?? "", "icsAnzeigeZeitzone": resolver.displayName,
                "prio": (1...3).contains(priority) ? 1 : priority >= 7 ? 3 : 2, "erledigt": component.value("STATUS").uppercased() == "COMPLETED" || component.value("PERCENT-COMPLETE") == "100",
                "notiz": component.value("DESCRIPTION"), "kategorien": component.value("CATEGORIES"), "akzentFarbe": color(),
                "erinnern": component.value("X-MAGNOLIE-ERINNERUNG-AM-TAG") == "1", "individuelleErinnerungTage": try reminder("X-MAGNOLIE-ERINNERUNG-TAGE"),
                "icsSerienUid": recurrence == nil ? "" : seriesUID, "elternUid": parent, "icsElternUid": parent, "icsElternQuelleId": parentSource,
                "reihenfolge": order, "geaendert": modified, "icsRoundtrip": raw]
            if let identity = taskIdentity { result["icsQuelleId"] = identity["source"] }
            return ("aufgaben", result)
        }
        guard component.name == "VEVENT" else { throw BetaError("Unsupported imported component.") }
        let startProperty = component.property("DTSTART") ?? (component.value("STATUS").uppercased() == "CANCELLED" ? recurrence : nil)
        guard let startProperty else { throw BetaError("An imported event has no start.") }
        let start = try resolver.clock(startProperty)
        var end = try component.property("DTEND").map(resolver.clock)
        if let specification = component.property("DURATION") {
            guard end == nil else { throw BetaError("An event has both DTEND and DURATION.") }; end = try resolver.duration(specification.value, from: start)
        }
        if let end { guard end.instant >= start.instant, end.dateOnly == start.dateOnly else { throw BetaError("Invalid event time range.") } }
        let date = resolver.date(start), time = resolver.time(start)
        var endDate = "", endTime = ""
        if let end {
            var exclusive = end.instant
            if start.dateOnly { exclusive = ICalendarImport.utcCalendar.date(byAdding: .day, value: -1, to: exclusive)! }
            let projected = ICalendarImport.format(exclusive, "yyyy-MM-dd", start.dateOnly ? ICalendarImport.utc : resolver.display)
            if projected > date { endDate = projected }
            if !start.dateOnly && (resolver.date(end) > date || resolver.time(end) != time) { endTime = resolver.time(end) }
        }
        let recurrenceNames = component.properties.filter { ["RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID"].contains($0.name) }.map { $0.name }
        var complex = complexUIDs.contains(seriesUID) || recurrenceNames.contains(where: { ["EXDATE", "EXRULE", "RECURRENCE-ID"].contains($0) })
        let sourceName = start.source == ICalendarImport.absoluteUTC ? "UTC" : start.source
        if rules["RRULE"] != nil && !time.isEmpty && !sourceName.isEmpty && sourceName != resolver.displayName { complex = true }
        if rules["RRULE"] != nil && component.property("DURATION") != nil { complex = true }
        if rules["RRULE"] != nil && !time.isEmpty && (endTime.isEmpty || ICalendarImport.utcCalendar.component(.second, from: start.wall) != 0 || end.map({ ICalendarImport.utcCalendar.component(.second, from: $0.wall) != 0 }) == true) { complex = true }
        var additions: [String] = [], additionRecords: [[String: String]] = []
        for property in component.properties where ["RDATE", "EXDATE", "RECURRENCE-ID"].contains(property.name) {
            for value in property.value.split(separator: ",", omittingEmptySubsequences: false) {
                if property.parameters["VALUE"]?.uppercased() == "PERIOD" {
                    guard property.name == "RDATE" else { throw BetaError("Only RDATE supports PERIOD values.") }
                    let pair = value.split(separator: "/", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                    guard pair.count == 2 else { throw BetaError("Invalid recurrence period.") }
                    let header = try Property(property.renamed("DTSTART", removing: ["VALUE"])).header
                    let first = try resolver.clock(Property(String(header) + ":" + pair[0]))
                    let finish: Clock
                    if pair[1].hasPrefix("P") || pair[1].hasPrefix("+P") { finish = try resolver.duration(pair[1], from: first) }
                    else { finish = try resolver.clock(Property(String(header) + ":" + pair[1])) }
                    guard finish.instant > first.instant else { throw BetaError("Recurrence period has no positive duration.") }; complex = true; continue
                }
                let header = property.header
                let clock = try resolver.clock(Property(header + ":" + value))
                guard clock.dateOnly == start.dateOnly else { throw BetaError("Recurrence dates do not match DTSTART's value type.") }
                if property.name == "RDATE" && !complex {
                    let rd = resolver.date(clock), rt = resolver.time(clock)
                    if rd < date || rd == date && rt < time { complex = true; additions = []; additionRecords = []; continue }
                    if rd == date && rt == time { continue }
                    additions.append(rd)
                    let projected = ["datum": rd, "zeit": rt]; if !additionRecords.contains(projected) { additionRecords.append(projected) }
                }
            }
        }
        var repetition: [String: Any]?
        if !complex, let rule = rules["RRULE"] { repetition = try simpleRule(rule, start: start, resolver: resolver) }
        if !complex && rules["RRULE"] == nil && !additions.isEmpty { repetition = ["art": "custom", "bis": "", "daten": Array(Set(additions)).sorted()] }
        let explicitType = anniversaryType(component.value("X-MAGNOLIE-TYPE-ID"))
        let legacy = component.value("X-MAGNOLIE-TYP").isEmpty ? component.value("X-MAGNOLIE-JAHRESTAG-TYP") : component.value("X-MAGNOLIE-TYP")
        let type = explicitType.isEmpty ? (anniversaryType(legacy).isEmpty ? legacy : anniversaryType(legacy)) : explicitType
        let yearly = rules["RRULE"] == nil || !complex && recurrenceNames == ["RRULE"] && (component.value("RRULE").uppercased() == "FREQ=YEARLY" || component.value("RRULE").uppercased() == "FREQ=YEARLY;INTERVAL=1") || repetition?["art"] as? String == "yearly" && repetition?["bis"] as? String == ""
        if !type.isEmpty && yearly && endDate.isEmpty && (time.isEmpty || time == "00:00" && endTime == "23:59") {
            var sourceDate = date
            let yearless = component.value("X-MAGNOLIE-DATE")
            if !yearless.isEmpty {
                guard ICalendarImport.matches(yearless, "^--[0-9]{2}-[0-9]{2}$"), String(date.suffix(5)) == String(yearless.suffix(5)) else { throw BetaError("Anniversary date extension contradicts DTSTART.") }
                _ = try ICalendarImport.naive("2000" + yearless.replacingOccurrences(of: "-", with: "")); sourceDate = yearless
            }
            return ("jahrestage", ["uid": baseUID, "name": title, "datum": sourceDate, "typ": type, "icsSerienUid": seriesUID,
                                    "notiz": component.value("DESCRIPTION"), "icsRoundtrip": raw, "geaendert": modified])
        }
        let isComplex = complex || rules["RRULE"] != nil && repetition == nil
        let record: [String: Any] = ["uid": baseUID, "titel": title.isEmpty ? "Untitled appointment" : title, "datum": date, "endDatum": endDate, "zeit": time, "endZeit": endTime,
            "icsAnzeigeZeitzone": resolver.displayName, "notiz": component.value("DESCRIPTION"), "kategorien": component.value("CATEGORIES"), "akzentFarbe": color(),
            "vertraulich": ["CONFIDENTIAL", "PRIVATE"].contains(component.value("CLASS").uppercased()), "vorlaeufig": component.value("STATUS").uppercased() == "TENTATIVE",
            "kostenstelle": component.value("X-MAGNOLIE-KOSTENSTELLE"), "kunde": component.value("X-MAGNOLIE-KUNDE"),
            "individuelleErinnerungTage": try reminder("X-MAGNOLIE-ERINNERUNG-TAGE"), "standardErinnerung": component.value("X-MAGNOLIE-STANDARDERINNERUNG") != "0",
            "wiederholung": repetition ?? ["art": "none", "bis": ""], "icsKomplex": isComplex, "icsSerienUid": isComplex ? seriesUID : "",
            "icsZusatzDaten": Array(Set(additions)).sorted(), "icsZusatzTermine": additionRecords, "icsEndeFehlt": end == nil,
            "icsNullDauer": end?.instant == start.instant, "icsRoundtrip": raw, "icsSequence": sequence,
            "icsAenderungszeitFehlt": component.property("LAST-MODIFIED") == nil, "geaendert": modified]
        return ("termine", record)
    }
    public static func decode(_ bytes: Data, displayTimeZone: String = "system", sourceName: String = "", sourceID: String = "") throws -> Result {
        guard !bytes.isEmpty, bytes.count <= maximumBytes, var input = String(data: bytes, encoding: .utf8) else { throw BetaError("Calendar import requires a UTF-8 file no larger than 32 MiB.") }
        if input.first == "\u{feff}" { input.removeFirst() }
        let roots = try parse(unfold(input))
        let wrapper = roots.count == 1 && roots[0].name == "VCALENDAR" ? roots[0] : nil
        let components = wrapper?.children ?? roots
        let items = components.filter { ["VEVENT", "VTODO"].contains($0.name) }
        guard !items.isEmpty, items.count <= maximumRecords else { throw BetaError("The calendar contains no supported items or too many items.") }
        let display: TimeZone
        if displayTimeZone.isEmpty || displayTimeZone == "system" { display = .current }
        else { display = try ICalendarImport.knownZone(displayTimeZone) }
        let displayName = displayTimeZone.isEmpty || displayTimeZone == "system" ? display.identifier : displayTimeZone
        var zoneBlocks: [[String]] = [], zoneSources: [String: [String]] = [:], zones: [String: EmbeddedZone] = [:]
        for component in components where component.name == "VTIMEZONE" {
            let names = component.properties.filter { $0.name == "TZID" }
            guard names.count == 1, !names[0].value.isEmpty else { throw BetaError("A source time zone has no unique TZID.") }
            let name = names[0].value
            if let previous = zoneSources[name] {
                guard previous == component.lines else { throw BetaError("Conflicting source definitions share a TZID.") }; continue
            }
            zones[name] = try EmbeddedZone(component); zoneSources[name] = component.lines; zoneBlocks.append(component.lines)
        }
        let resolver = Resolver(display: display, displayName: displayName, zones: zones)
        let complexUIDs = Set(items.filter { $0.name == "VEVENT" && $0.property("RECURRENCE-ID") != nil }.map { $0.value("UID") })
        let calendarName = wrapper?.value("X-WR-CALNAME").trimmingCharacters(in: .whitespaces) ?? ""
        let fallback = sourcePath(sourceName).isEmpty ? "Calendar" : sourcePath(sourceName)
        let label = calendarName.isEmpty ? fallback : calendarName
        let qualified = !sourceName.isEmpty || !sourceID.isEmpty || !calendarName.isEmpty
        let stableSource = sourceID.isEmpty ? (sourceName.isEmpty ? "calendar" : fallback) : sourceID
        let source = "ics:" + ICalendarImport.hash(Data((stableSource + "\n" + calendarName).utf8))
        var collections: [String: [[String: Any]]] = ["termine": [], "aufgaben": [], "jahrestage": []]
        var identities: Set<[String]> = [], projectedBytes = 0
        let zoneBytes = zoneBlocks.reduce(0) { $0 + $1.reduce(0) { $0 + $1.utf8.count + 2 } }
        for component in items {
            // Account for repeated source-zone payloads and worst-case JSON
            // escaping before materializing a potentially oversized result.
            let itemBytes = component.lines.reduce(0) { $0 + $1.utf8.count + 2 }
            projectedBytes += (itemBytes + zoneBytes) * 6 + 8192
            guard projectedBytes <= maximumProjectedBytes else { throw BetaError("The projected calendar data exceeds the bounded import size; nothing was imported.") }
            var (collection, record) = try componentRecord(component, complexUIDs: complexUIDs, resolver: resolver)
            if qualified { record["icsQuelleName"] = label; if record["icsQuelleId"] == nil { record["icsQuelleId"] = source } }
            guard let uid = record["uid"] as? String,
                  identities.insert([collection, record["icsQuelleId"] as? String ?? "", uid]).inserted else { throw BetaError("Duplicate calendar item identity; nothing was imported.") }
            if collection == "aufgaben", record["icsElternQuelleId"] as? String == "", component.property("X-MAGNOLIE-TASK-IDENTITY") == nil {
                record["icsElternQuelleId"] = record["icsQuelleId"] as? String ?? ""
            }
            if !zoneBlocks.isEmpty { record["icsTimezones"] = zoneBlocks }
            collections[collection, default: []].append(record)
        }
        // Preserve both masters and separate recurrence exceptions, including
        // source-qualified exclusions and THISANDFUTURE range bodies.
        for collection in ["termine", "aufgaben"] {
            let records = collections[collection]!
            var exclusions: [String: [String]] = [:], ranges: [String: [[String]]] = [:]
            for record in records {
                let raw = record["icsRoundtrip"] as? [String] ?? []
                if let line = raw.first(where: { (try? Property($0).name) == "RECURRENCE-ID" }) {
                    let property = try Property(line)
                    let uid = (record["icsSerienUid"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? record["uid"] as! String
                    let key = (record["icsQuelleId"] as? String ?? "") + "\0" + uid
                    exclusions[key, default: []].append(property.renamed("EXDATE", removing: ["RANGE"]))
                    if property.parameters["RANGE"]?.uppercased() == "THISANDFUTURE" { ranges[key, default: []].append(raw) }
                }
            }
            collections[collection] = records.map { value -> [String: Any] in
                var record = value
                var raw = record["icsRoundtrip"] as? [String] ?? []
                if !raw.contains(where: { (try? Property($0).name) == "RECURRENCE-ID" }) {
                    let uid = (record["icsSerienUid"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? record["uid"] as! String
                    let key = (record["icsQuelleId"] as? String ?? "") + "\0" + uid
                    if let additions = exclusions[key] {
                        for line in additions where !raw.contains(line) { raw.append(line) }
                        record["icsRoundtrip"] = raw; record["icsRangeOverrides"] = ranges[key] ?? []
                    }
                }
                return record
            }
        }
        let result = Result(appointments: collections["termine"]!, tasks: collections["aufgaben"]!, anniversaries: collections["jahrestage"]!,
                            calendarProperties: wrapper?.properties.map { $0.line } ?? [], sourceSHA256: ICalendarImport.hash(bytes))
        // This final bounded validation is still pure: callers receive either a
        // complete, JSON-representable transaction or an error, never a prefix.
        let encoded = try JSONSerialization.data(withJSONObject: result.document)
        guard encoded.count <= maximumProjectedBytes else { throw BetaError("Calendar projection exceeds the bounded import size.") }
        return result
    }
}
