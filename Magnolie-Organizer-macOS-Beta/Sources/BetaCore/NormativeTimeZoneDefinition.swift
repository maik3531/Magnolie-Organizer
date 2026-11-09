import Foundation

/// RFC5545 observances from the pinned complete model, without OS rule lookup.
/// Future predicates are proven over the complete Gregorian cycle, then emitted
/// as unlimited annual rules; sampled dates are never runtime future data.
public enum NormativeTimeZoneDefinition {
    private struct Key: Equatable { let daylight: Bool; let before, after: Int; let name: String }
    private struct Pattern {
        let text: String, months: Set<Int>, days: Set<Int>?, weekday: Int?, ordinal: Int?
    }
    private static let names = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
    private static func require(_ value: Bool) throws { if !value { throw TimeZoneExport.ExportError.unsupportedRule } }
    private static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: ";", with: "\\;").replacingOccurrences(of: ",", with: "\\,")
    }
    private static func stamp(_ seconds: Int64) throws -> String {
        let c = try ProlepticGregorian.civil(at: seconds * 1000)
        return String(format: "%04d%02d%02dT%02d%02d%02d", c.year, c.month, c.day, c.hour, c.minute, c.second)
    }
    private static func offset(_ value: Int) throws -> String {
        try require(value > -86400 && value < 86400)
        let n = abs(value)
        return String(format: "%@%02d%02d", value < 0 ? "-" : "+", n / 3600, n % 3600 / 60) + (n % 60 == 0 ? "" : String(format: "%02d", n % 60))
    }
    private static func component(_ key: Key, _ dates: [Int64], rule: String? = nil) throws -> [String] {
        try require(!dates.isEmpty)
        let kind = key.daylight ? "DAYLIGHT" : "STANDARD"
        var lines = ["BEGIN:" + kind, "DTSTART:" + (try stamp(dates[0])),
                     "TZOFFSETFROM:" + (try offset(key.before)), "TZOFFSETTO:" + (try offset(key.after)), "TZNAME:" + escape(key.name)]
        for start in stride(from: 1, to: dates.count, by: 100) {
            lines.append("RDATE:" + (try dates[start..<min(start + 100, dates.count)].map(stamp)).joined(separator: ","))
        }
        if let rule { lines.append("RRULE:" + rule) }
        return lines + ["END:" + kind]
    }
    private static func candidates(_ pattern: Pattern, year: Int, clock: Int64) -> [Int64] {
        var result: [Int64] = []
        for month in pattern.months.sorted() {
            let length = ProlepticGregorian.daysInMonth(year, month)
            for day in 1...length {
                if let days = pattern.days, !days.contains(day), !days.contains(day - length - 1) { continue }
                let date = ProlepticGregorian.days(year, month, day)
                let weekday = Int((date + 4) % 7 + 7) % 7
                if let wanted = pattern.weekday, weekday != wanted { continue }
                if let ordinal = pattern.ordinal,
                   ordinal > 0 ? (day - 1) / 7 + 1 != ordinal : -((length - day) / 7 + 1) != ordinal { continue }
                result.append(date * 86400 + clock)
            }
        }
        return result
    }
    private static func patterns(_ rule: NormativeTimeZoneDatabase.Rule) throws -> [Pattern] {
        var byYear: [Int: [Int64]] = [:]
        for year in 1999...2400 {
            let wall = rule.wallSecond(year: year), c = ProlepticGregorian.uncheckedParts(wall * 1000)
            if (2000...2399).contains(c.year) { byYear[c.year, default: []].append(wall) }
        }
        try require(byYear.count == 400 && byYear.values.allSatisfy { $0.count == 1 })
        let dates = (2000...2399).map { ProlepticGregorian.uncheckedParts(byYear[$0]![0] * 1000) }
        let clocks = Set(dates.map { Int64($0.hour * 3600 + $0.minute * 60 + $0.second) })
        try require(clocks.count == 1)
        let clock = clocks.first!, months = Set(dates.map { $0.month }), days = Set(dates.map { $0.day })
        let weekdays = Set((2000...2399).map { Int((ProlepticGregorian.floorDiv(byYear[$0]![0], 86400) + 4) % 7 + 7) % 7 })
        let positive = Set(dates.map { ($0.day - 1) / 7 + 1 })
        let negative = Set(dates.map { -((ProlepticGregorian.daysInMonth($0.year, $0.month) - $0.day) / 7 + 1) })
        func list(_ values: Set<Int>) -> String { values.sorted().map(String.init).joined(separator: ",") }
        let base = "FREQ=YEARLY;BYMONTH=" + list(months)
        var options: [Pattern] = []
        if months.count == 1 && days.count == 1 { options.append(Pattern(text: base + ";BYMONTHDAY=" + list(days), months: months, days: days, weekday: nil, ordinal: nil)) }
        if months.count == 1 && weekdays.count == 1 {
            let weekday = weekdays.first!
            for ordinal in [negative.count == 1 ? negative.first : nil, positive.count == 1 ? positive.first : nil].compactMap({ $0 }) {
                options.append(Pattern(text: base + ";BYDAY=\(ordinal)" + names[weekday], months: months, days: nil, weekday: weekday, ordinal: ordinal))
            }
        }
        if weekdays.count == 1 {
            let weekday = weekdays.first!
            options.append(Pattern(text: base + ";BYDAY=" + names[weekday] + ";BYMONTHDAY=" + list(days), months: months, days: days, weekday: weekday, ordinal: nil))
        }
        for option in options {
            if (2000...2399).allSatisfy({ candidates(option, year: $0, clock: clock) == byYear[$0]! }) { return [option] }
        }
        // Shifted annual rules can cross a month boundary. Disjoint month
        // predicates prevent a Cartesian product of unrelated month/day sets.
        let split: [Pattern] = months.sorted().map { month in
            let selected = dates.filter { $0.month == month }
            let positiveDays = Set(selected.map { $0.day })
            let negativeDays = Set(selected.map { $0.day - ProlepticGregorian.daysInMonth($0.year, month) - 1 })
            let accepted = negativeDays.count == 1 ? negativeDays : positiveDays
            let weekday = weekdays.count == 1 ? weekdays.first : nil
            return Pattern(text: "FREQ=YEARLY;BYMONTH=\(month);BYMONTHDAY=" + list(accepted) + (weekday.map { ";BYDAY=" + names[$0] } ?? ""),
                           months: [month], days: accepted, weekday: weekday, ordinal: nil)
        }
        try require((2000...2399).allSatisfy { year in
            Array(Set(split.flatMap { candidates($0, year: year, clock: clock) })).sorted() == byYear[year]!
        })
        return split
    }
    public static func definition(_ identifier: String, database: NormativeTimeZoneDatabase) throws -> [String] {
        let zone = try database.named(identifier)
        let minimum = ProlepticGregorian.days(1, 1, 1) * 86400
        guard let model = try database.completeModel(for: zone) else {
            return ["BEGIN:VTIMEZONE", "TZID:" + escape(identifier)] + (try component(Key(daylight: false, before: 0, after: 0, name: "UTC"), [minimum])) + ["END:VTIMEZONE"]
        }
        var previous = model.types[model.initial].state
        if model.history.isEmpty { previous = try database.offset(at: minimum * 1000, in: zone) }
        let initial = Key(daylight: previous.daylight, before: previous.offsetSeconds, after: previous.offsetSeconds, name: previous.abbreviation)
        var groups: [(Key, [Int64])] = [(initial, [minimum + Int64(max(0, initial.before))])]
        for transition in model.history {
            let current = model.types[transition.type].state
            let key = Key(daylight: current.daylight, before: previous.offsetSeconds, after: current.offsetSeconds, name: current.abbreviation)
            let wall = transition.second + Int64(previous.offsetSeconds)
            _ = try stamp(wall)
            if let index = groups.firstIndex(where: { $0.0 == key }) { groups[index].1.append(wall) }
            else { groups.append((key, [wall])) }
            previous = current
        }
        var lines = ["BEGIN:VTIMEZONE", "TZID:" + escape(identifier)]
        for (key, dates) in groups { lines += try component(key, dates) }
        let boundary = model.history.last?.second ?? minimum - 1
        if let daylight = model.tail.daylight, let start = model.tail.start, let end = model.tail.end {
            for (rule, before, current) in [(start, model.tail.standard.offsetSeconds, daylight), (end, daylight.offsetSeconds, model.tail.standard)] {
                let predicates = try patterns(rule)
                let year = ProlepticGregorian.uncheckedParts(boundary * 1000).year
                try require((0...9598).contains(year))
                for predicate in predicates {
                    var first: Int64?
                    for candidate in max(1, year - 1)...(year + 401) {
                        let wall = rule.wallSecond(year: candidate), c = ProlepticGregorian.uncheckedParts(wall * 1000)
                        guard wall - Int64(before) > boundary, (1...9999).contains(c.year) else { continue }
                        let clock = Int64(c.hour * 3600 + c.minute * 60 + c.second)
                        if candidates(predicate, year: c.year, clock: clock).contains(wall), first == nil || wall < first! { first = wall }
                    }
                    guard let first else { throw TimeZoneExport.ExportError.unsupportedRule }
                    lines += try component(Key(daylight: current.daylight, before: before, after: current.offsetSeconds, name: current.abbreviation), [first], rule: predicate.text)
                }
            }
        }
        lines.append("END:VTIMEZONE")
        try require(lines.count <= 250_000 && lines.reduce(0, { $0 + $1.utf8.count }) <= 8 * 1024 * 1024)
        return lines
    }
}
