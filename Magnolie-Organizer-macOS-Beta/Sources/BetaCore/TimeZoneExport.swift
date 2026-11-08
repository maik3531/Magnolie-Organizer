import Foundation

/// Lossless TZif history plus an unbounded POSIX future, for RFC 5545 exports.
public enum TimeZoneExport {
    public enum ExportError: Error, LocalizedError {
        case invalidIdentifier, malformedData, unsupportedRule
        public var errorDescription: String? {
            switch self {
            case .invalidIdentifier: return "Unbekannte oder ungültige Kalenderzeitzone."
            case .malformedData: return "Die Zeitzonendaten sind beschädigt oder überschreiten die Exportgrenzen."
            case .unsupportedRule: return "Diese Zeitzonenregel lässt sich nicht verlustfrei als VTIMEZONE exportieren."
            }
        }
    }

    public static func definition(_ identifier: String) throws -> [String] {
        guard let zone = TimeZone(identifier: identifier) else { throw ExportError.invalidIdentifier }
        return try definition(identifier, data: (zone as NSTimeZone).data)
    }

    private struct ZoneType: Equatable {
        let offset: Int
        let daylight: Bool
        let name: String
    }
    private struct Transition { let second: Int64; let type: Int }
    private struct Zone { let types: [ZoneType]; let transitions: [Transition]; let footer: String }
    private struct Observance: Equatable {
        let daylight: Bool
        let before: Int
        let after: Int
        let name: String
    }
    private struct MonthRule {
        let month: Int; let week: Int; let weekday: Int; let second: Int
    }
    private struct Future {
        let standard: ZoneType; let daylight: ZoneType
        let start: MonthRule; let end: MonthRule
    }
    private static let dayNames = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
    private static var calendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }
    private static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: ";", with: "\\;")
            .replacingOccurrences(of: ",", with: "\\,")
    }

    // Internal data entry point also permits deterministic, platform-independent fixtures.
    static func definition(_ identifier: String, data: Data) throws -> [String] {
        guard !identifier.isEmpty, identifier.utf8.count <= 255,
              identifier.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }),
              !identifier.contains(":"), !identifier.contains(";") else { throw ExportError.invalidIdentifier }
        let zone = try parse(data)
        let finalType = zone.types[zone.transitions.last?.type ?? 0]
        let future = try parseFuture(zone.footer, finalType: finalType)
        let minimum = calendar.date(from: DateComponents(year: 1, month: 1, day: 1))!
        let maximum = calendar.date(from: DateComponents(year: 10000, month: 1, day: 1))!
        var previous = zone.types[0]
        if zone.transitions.isEmpty, let future = future {
            let starts = try ruleDate(future.start, year: 2000)
            let ends = try ruleDate(future.end, year: 2000)
            previous = starts > ends ? future.daylight : future.standard
        }
        var groups: [(Observance, [Date])] = []
        func add(_ current: ZoneType, before: Int, date: Date) {
            let key = Observance(daylight: current.daylight, before: before, after: current.offset, name: current.name)
            if let index = groups.firstIndex(where: { $0.0 == key }) { groups[index].1.append(date) }
            else { groups.append((key, [date])) }
        }
        // The initial observance makes dates preceding the first transition explicit.
        var seeded = false
        for transition in zone.transitions {
            let current = zone.types[transition.type]
            let instant = Date(timeIntervalSince1970: Double(transition.second))
            let wall = instant.addingTimeInterval(Double(previous.offset))
            if wall < minimum { previous = current; continue }
            guard wall < maximum else { throw ExportError.unsupportedRule }
            if !seeded { add(previous, before: previous.offset, date: minimum); seeded = true }
            if current != previous { add(current, before: previous.offset, date: wall) }
            previous = current
        }
        if !seeded { add(previous, before: previous.offset, date: minimum) }
        var lines = ["BEGIN:VTIMEZONE", "TZID:" + escape(identifier)]
        for (key, dates) in groups {
            lines += component(key, dates: dates, rule: nil)
        }
        if let future = future {
            let last = zone.transitions.last.map { Date(timeIntervalSince1970: Double($0.second)) }
                ?? minimum.addingTimeInterval(-1)
            // A malformed footer must not introduce an invisible discontinuity at the table boundary.
            if !zone.transitions.isEmpty {
                let boundaryYear = calendar.component(.year, from: last)
                guard (1...9999).contains(boundaryYear) else { throw ExportError.unsupportedRule }
                var preceding: (Date, ZoneType)?
                for year in max(1, boundaryYear - 1)...min(9999, boundaryYear + 1) {
                    for (kind, before, rule) in [(future.daylight, future.standard.offset, future.start),
                                                  (future.standard, future.daylight.offset, future.end)] {
                        let instant = try ruleDate(rule, year: year).addingTimeInterval(Double(-before))
                        if instant <= last, preceding == nil || instant > preceding!.0 { preceding = (instant, kind) }
                    }
                }
                guard let preceding = preceding, preceding.1.offset == finalType.offset,
                      preceding.1.daylight == finalType.daylight else { throw ExportError.unsupportedRule }
            }
            // Only extend after the explicit table. Never replace historical rules with today's rules.
            for (current, before, rule) in [(future.daylight, future.standard.offset, future.start),
                                             (future.standard, future.daylight.offset, future.end)] {
                let year = max(1, calendar.component(.year, from: last) - 1)
                var first: Date?
                for candidate in year...min(9999, year + 5) {
                    let wall = try ruleDate(rule, year: candidate)
                    if wall.addingTimeInterval(Double(-before)) > last { first = wall; break }
                }
                guard let first = first else { throw ExportError.unsupportedRule }
                let weekday = (rule.week == 5 ? -1 : rule.week)
                let rrule = "FREQ=YEARLY;BYMONTH=\(rule.month);BYDAY=\(weekday)\(dayNames[rule.weekday])"
                lines += component(Observance(daylight: current.daylight, before: before,
                                              after: current.offset, name: current.name), dates: [first], rule: rrule)
            }
        }
        lines.append("END:VTIMEZONE")
        return lines
    }

    private static func offset(_ value: Int) -> String {
        let n = abs(value)
        let base = String(format: "%@%02d%02d", value < 0 ? "-" : "+", n / 3600, (n % 3600) / 60)
        return n % 60 == 0 ? base : base + String(format: "%02d", n % 60)
    }
    private static func timestamp(_ date: Date) -> String {
        let c = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        return String(format: "%04d%02d%02dT%02d%02d%02d", c.year!, c.month!, c.day!, c.hour!, c.minute!, c.second!)
    }
    private static func component(_ key: Observance, dates: [Date], rule: String?) -> [String] {
        let kind = key.daylight ? "DAYLIGHT" : "STANDARD"
        var lines = ["BEGIN:" + kind, "DTSTART:" + timestamp(dates[0]),
                     "TZOFFSETFROM:" + offset(key.before), "TZOFFSETTO:" + offset(key.after),
                     "TZNAME:" + escape(key.name)]
        // Keep individual properties bounded; the enclosing writer performs RFC line folding.
        for index in stride(from: 1, to: dates.count, by: 100) {
            lines.append("RDATE:" + dates[index..<min(index + 100, dates.count)].map(timestamp).joined(separator: ","))
        }
        if let rule = rule { lines.append("RRULE:" + rule) }
        return lines + ["END:" + kind]
    }

    private static func parse(_ data: Data) throws -> Zone {
        guard data.count <= 4_000_000 else { throw ExportError.malformedData }
        let bytes = [UInt8](data)
        func integer(_ at: Int, _ size: Int) throws -> UInt64 {
            guard at >= 0, size <= bytes.count, at <= bytes.count - size else { throw ExportError.malformedData }
            return bytes[at..<(at + size)].reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
        }
        func header(_ at: Int, size: Int) throws -> ([Int], Int) {
            guard at >= 0, at <= bytes.count - 44,
                  Array(bytes[at..<(at + 4)]) == Array("TZif".utf8) else { throw ExportError.malformedData }
            let counts = try (0..<6).map { Int(try integer(at + 20 + $0 * 4, 4)) }
            let (gmt, standard, leap, times, types, chars) = (counts[0], counts[1], counts[2], counts[3], counts[4], counts[5])
            guard types > 0, types <= 256, times <= 100_000, chars > 0, chars <= 4096,
                  leap == 0, (gmt == 0 || gmt == types), (standard == 0 || standard == types) else { throw ExportError.unsupportedRule }
            let end = at + 44 + times * (size + 1) + types * 6 + chars + leap * (size + 4) + standard + gmt
            guard end <= bytes.count else { throw ExportError.malformedData }
            return (counts, end)
        }
        var (counts, end) = try header(0, size: 4)
        var at = 44
        var size = 4
        guard [0, 50, 51].contains(bytes[4]) else { throw ExportError.unsupportedRule }
        if bytes[4] != 0 {
            let secondHeader = end
            (counts, end) = try header(secondHeader, size: 8)
            guard bytes[secondHeader + 4] == bytes[4] else { throw ExportError.malformedData }
            at = secondHeader + 44; size = 8
        }
        var seconds: [Int64] = []
        for index in 0..<counts[3] {
            let raw = try integer(at + index * size, size)
            let second = size == 8 ? Int64(bitPattern: raw) : Int64(Int32(bitPattern: UInt32(raw)))
            guard seconds.last.map({ $0 < second }) ?? true else { throw ExportError.malformedData }
            seconds.append(second)
        }
        at += counts[3] * size
        let indices = Array(bytes[at..<(at + counts[3])]); at += counts[3]
        let namesAt = at + counts[4] * 6
        let names = Array(bytes[namesAt..<(namesAt + counts[5])])
        var types: [ZoneType] = []
        for index in 0..<counts[4] {
            let pos = at + index * 6
            let shift = Int(Int32(bitPattern: UInt32(try integer(pos, 4))))
            let nameIndex = Int(bytes[pos + 5])
            guard abs(shift) < 86400, bytes[pos + 4] <= 1, nameIndex < names.count,
                  let terminator = names[nameIndex...].firstIndex(of: 0), terminator > nameIndex,
                  let name = String(bytes: names[nameIndex..<terminator], encoding: .ascii),
                  name.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value < 127 }) else { throw ExportError.malformedData }
            types.append(ZoneType(offset: shift, daylight: bytes[pos + 4] == 1, name: name))
        }
        guard indices.allSatisfy({ Int($0) < types.count }) else { throw ExportError.malformedData }
        var footer = ""
        if size == 8 {
            guard end + 2 <= bytes.count, bytes[end] == 10, bytes.last == 10,
                  let text = String(bytes: bytes[(end + 1)..<(bytes.count - 1)], encoding: .ascii),
                  !text.contains("\n"), !text.contains("\r"), text.count <= 512 else { throw ExportError.malformedData }
            footer = text
        } else if end != bytes.count { throw ExportError.malformedData }
        return Zone(types: types, transitions: zip(seconds, indices).map { Transition(second: $0.0, type: Int($0.1)) }, footer: footer)
    }

    private static func parseFuture(_ text: String, finalType: ZoneType) throws -> Future? {
        if text.isEmpty { return nil }
        // Build identical offset/name groups from shared noncapturing fragments, so the
        // optional daylight offset cannot leave the enclosing group unbalanced.
        let name = #"(?:<[A-Za-z0-9+\-]+>|[A-Za-z]{3,})"#
        let number = #"[+\-]?[0-9]{1,3}(?::[0-9]{1,2}(?::[0-9]{1,2})?)?"#
        let pattern = "^(" + name + ")(" + number + ")(?:(" + name + ")(" + number + ")?)?(?:,([^,]+),([^,]+))?$"
        let regex = try NSRegularExpression(pattern: pattern)
        let ns = text as NSString
        guard let match = regex.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) else { throw ExportError.unsupportedRule }
        func field(_ index: Int) -> String? {
            let range = match.range(at: index)
            return range.location == NSNotFound ? nil : ns.substring(with: range)
        }
        func label(_ index: Int) -> String { field(index)!.trimmingCharacters(in: CharacterSet(charactersIn: "<>")) }
        let standard = ZoneType(offset: -(try clock(field(2)!)), daylight: false, name: label(1))
        guard abs(standard.offset) < 86400 else { throw ExportError.unsupportedRule }
        guard field(3) != nil else {
            guard field(5) == nil, standard.offset == finalType.offset, standard.name == finalType.name, !finalType.daylight else { throw ExportError.unsupportedRule }
            return nil
        }
        guard let start = field(5), let end = field(6) else { throw ExportError.unsupportedRule }
        let daylight = ZoneType(offset: try field(4).map { -(try clock($0)) } ?? standard.offset + 3600,
                                daylight: true, name: label(3))
        guard abs(daylight.offset) < 86400, daylight.offset != standard.offset else { throw ExportError.unsupportedRule }
        return Future(standard: standard, daylight: daylight, start: try monthRule(start), end: try monthRule(end))
    }
    private static func clock(_ text: String) throws -> Int {
        let sign = text.hasPrefix("-") ? -1 : 1
        let body = (text.hasPrefix("+") || text.hasPrefix("-")) ? String(text.dropFirst()) : text
        let parts = body.split(separator: ":", omittingEmptySubsequences: false)
        guard (1...3).contains(parts.count) else { throw ExportError.unsupportedRule }
        let numbers = try parts.map { part -> Int in
            guard !part.isEmpty, part.allSatisfy({ $0.isASCII && $0.isNumber }), let value = Int(part) else { throw ExportError.unsupportedRule }
            return value
        }
        guard numbers[0] <= 167, numbers.dropFirst().allSatisfy({ $0 < 60 }) else { throw ExportError.unsupportedRule }
        return sign * zip(numbers, [3600, 60, 1]).reduce(0) { $0 + $1.0 * $1.1 }
    }
    private static func monthRule(_ text: String) throws -> MonthRule {
        let halves = text.split(separator: "/", omittingEmptySubsequences: false)
        guard halves.count <= 2, halves[0].hasPrefix("M") else { throw ExportError.unsupportedRule }
        let parts = halves[0].dropFirst().split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3, let month = Int(parts[0]), let week = Int(parts[1]), let weekday = Int(parts[2]),
              (1...12).contains(month), (1...5).contains(week), (0...6).contains(weekday) else { throw ExportError.unsupportedRule }
        let second: Int
        if halves.count == 2 { second = try clock(String(halves[1])) } else { second = 7200 }
        // Out-of-day or Julian rules require different RRULEs. Refuse instead of truncating the future.
        guard (0..<86400).contains(second) else { throw ExportError.unsupportedRule }
        return MonthRule(month: month, week: week, weekday: weekday, second: second)
    }
    private static func ruleDate(_ rule: MonthRule, year: Int) throws -> Date {
        let first = calendar.date(from: DateComponents(year: year, month: rule.month, day: 1))!
        let weekday = calendar.component(.weekday, from: first) - 1
        var day = 1 + (rule.weekday - weekday + 7) % 7 + (rule.week - 1) * 7
        if day > calendar.range(of: .day, in: .month, for: first)!.count { day -= 7 }
        guard let date = calendar.date(from: DateComponents(year: year, month: rule.month, day: day)) else { throw ExportError.unsupportedRule }
        return date.addingTimeInterval(Double(rule.second))
    }
}
