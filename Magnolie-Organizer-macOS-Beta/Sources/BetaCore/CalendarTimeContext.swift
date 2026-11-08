import Foundation

/// Immutable explicit authority for native calendar codecs. The platform supplies
/// only its selected identifier; every numeric rule comes from the pinned model.
public struct CalendarTimeContext: Sendable {
    public let database: NormativeTimeZoneDatabase
    public let systemIdentifier: String
    public init(database: NormativeTimeZoneDatabase, systemIdentifier: String) throws {
        _ = try database.named(systemIdentifier)
        self.database = database; self.systemIdentifier = systemIdentifier
    }
    public static func bundled(resources: URL, systemIdentifier: String) throws -> CalendarTimeContext {
        try CalendarTimeContext(database: bundledDatabase(resources: resources), systemIdentifier: systemIdentifier)
    }
    public static func bundledDatabase(resources: URL) throws -> NormativeTimeZoneDatabase {
        let directory = resources.appendingPathComponent("UI/web/timezones", isDirectory: true)
        func bytes(_ name: String, maximum: Int) throws -> Data {
            let handle = try FileHandle(forReadingFrom: directory.appendingPathComponent(name))
            defer { try? handle.close() }
            let value = try handle.read(upToCount: maximum + 1) ?? Data()
            guard value.count <= maximum else { throw BetaError("Bundled timezone resource exceeds its bound.") }
            return value
        }
        return try .load(payload: bytes("tzdb-2026egtz.json", maximum: 1_048_576), manifest: bytes("provenance.json", maximum: 65536))
    }
    func named(_ identifier: String) throws -> CalendarResolvedZone {
        let database = self.database
        let zone = try database.named(identifier)
        return CalendarResolvedZone(identifier: identifier, absoluteUTC: false,
            instant: { wall in
                guard let value = try database.resolve(ProlepticGregorian.civil(at: wall.milliseconds), in: zone, fold: .earlier, gap: .reject) else { throw BetaError("Unresolved calendar wall clock.") }
                return CalendarInstant(milliseconds: value)
            }, wall: { instant in
                let value = try database.wall(at: instant.milliseconds, in: zone)
                return CalendarInstant(milliseconds: value.epochMilliseconds)
            })
    }
    func display(_ name: String) throws -> CalendarResolvedZone {
        try named(name.isEmpty || name == "system" ? systemIdentifier : name)
    }
}

/// Protocol state is typed: no user-supplied TZID can impersonate an internal UTC
/// sentinel. Opaque values preserve the exact decoded UTF8 sequence (#453/#455).
enum CalendarTimeSource: Equatable {
    case absoluteUTC, floating, named(OpaqueUTF8Identity)
}

struct CalendarInstant: Hashable, Comparable {
    let milliseconds: Int64
    static func < (lhs: Self, rhs: Self) -> Bool { lhs.milliseconds < rhs.milliseconds }
    func adding(seconds: Int64) throws -> Self {
        let (delta, overflow1) = seconds.multipliedReportingOverflow(by: 1000)
        let (value, overflow2) = milliseconds.addingReportingOverflow(delta)
        guard !overflow1, !overflow2 else { throw BetaError("Calendar arithmetic exceeds its integer bound.") }
        return Self(milliseconds: value)
    }
    static func timestamp(_ date: Foundation.Date) throws -> Self {
        let value = date.timeIntervalSince1970 * 1000
        guard value.isFinite, value >= -62_135_596_801_000, value <= 253_402_300_801_000 else { throw BetaError("Calendar timestamp is outside years 1–9999.") }
        // Foundation stores seconds relative to 2001. Converting an intended
        // integer Unix millisecond accumulates bounded Double rounding from
        // the epoch conversion and multiplication. Correct only that noise, never round a
        // genuinely earlier timestamp forward across a whole-second boundary.
        let nearest = value.rounded()
        let tolerance = (date.timeIntervalSinceReferenceDate.ulp + date.timeIntervalSince1970.ulp) * 500 + value.ulp / 2
        let crossesSecond = nearest.truncatingRemainder(dividingBy: 1000) == 0 && value < nearest
        let milliseconds = abs(value - nearest) <= tolerance && !crossesSecond ? nearest : value.rounded(.down)
        guard milliseconds >= -62_135_596_800_000, milliseconds <= 253_402_300_799_999 else { throw BetaError("Calendar timestamp is outside years 1–9999.") }
        return Self(milliseconds: Int64(milliseconds))
    }
}

struct CalendarResolvedZone {
    let identifier: String, absoluteUTC: Bool
    let instant: (CalendarInstant) throws -> CalendarInstant
    let wall: (CalendarInstant) throws -> CalendarInstant
    static let utc = CalendarResolvedZone(identifier: "UTC", absoluteUTC: true, instant: { $0 }, wall: { $0 })
}

enum CalendarCivil {
    static func parse(_ value: String) throws -> CalendarInstant {
        let bytes = Array(value.utf8)
        guard [8, 13, 15].contains(bytes.count), bytes.enumerated().allSatisfy({ $0.offset == 8 ? $0.element == 84 : (48...57).contains($0.element) }) else { throw BetaError("Invalid calendar civil date/time.") }
        func number(_ start: Int, _ end: Int) -> Int { bytes[start..<end].reduce(0) { $0 * 10 + Int($1 - 48) } }
        let civil = try ProlepticGregorian.Civil(year: number(0, 4), month: number(4, 6), day: number(6, 8),
            hour: bytes.count > 8 ? number(9, 11) : 0, minute: bytes.count > 8 ? number(11, 13) : 0,
            second: bytes.count == 15 ? number(13, 15) : 0)
        return CalendarInstant(milliseconds: civil.epochMilliseconds)
    }
    static func format(_ value: CalendarInstant, _ pattern: String, _ zone: CalendarResolvedZone = .utc) throws -> String {
        let wall = try zone.wall(value), c = try ProlepticGregorian.civil(at: wall.milliseconds)
        switch pattern {
        case "yyyy-MM-dd": return String(format: "%04d-%02d-%02d", c.year, c.month, c.day)
        case "yyyyMMdd": return String(format: "%04d%02d%02d", c.year, c.month, c.day)
        case "HH:mm": return String(format: "%02d:%02d", c.hour, c.minute)
        case "HH:mm:ss": return String(format: "%02d:%02d:%02d", c.hour, c.minute, c.second)
        case "yyyyMMdd'T'HHmm": return String(format: "%04d%02d%02dT%02d%02d", c.year, c.month, c.day, c.hour, c.minute)
        case "yyyyMMdd'T'HHmmss": return String(format: "%04d%02d%02dT%02d%02d%02d", c.year, c.month, c.day, c.hour, c.minute, c.second)
        case "yyyyMMdd'T'HHmmss'Z'": return String(format: "%04d%02d%02dT%02d%02d%02dZ", c.year, c.month, c.day, c.hour, c.minute, c.second)
        default: throw BetaError("Unsupported deterministic calendar format.")
        }
    }
    static func day(_ value: String) throws -> CalendarInstant {
        guard value.utf8.count == 10, value.dropFirst(4).first == "-", value.dropFirst(7).first == "-" else { throw BetaError("Invalid calendar date.") }
        return try parse(value.replacingOccurrences(of: "-", with: ""))
    }
    static func wall(_ date: String, _ time: String, zone: CalendarResolvedZone) throws -> CalendarInstant {
        _ = try day(date)
        guard time.range(of: "^(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?$", options: .regularExpression) != nil else { throw BetaError("Invalid calendar clock.") }
        let digits = date.replacingOccurrences(of: "-", with: "") + "T" + time.replacingOccurrences(of: ":", with: "")
        return try zone.instant(parse(digits))
    }
    static func addingDays(_ value: CalendarInstant, _ days: Int, zone: CalendarResolvedZone = .utc) throws -> CalendarInstant {
        let wall = try zone.wall(value), civil = try ProlepticGregorian.civil(at: wall.milliseconds)
        return try zone.instant(CalendarInstant(milliseconds: civil.addingDays(days).epochMilliseconds))
    }
}

/// Foundation component enums/DateComponents are containers only. Every field
/// and operation below is computed by the integer proleptic Gregorian engine.
struct CalendarCivilCalendar {
    let zone: CalendarResolvedZone
    func dateComponents(_ fields: Set<Calendar.Component>, from value: CalendarInstant) throws -> DateComponents {
        let wall = try zone.wall(value), c = ProlepticGregorian.uncheckedParts(wall.milliseconds)
        var result = DateComponents()
        result.era = c.year >= 1 ? 1 : 0; result.year = c.year; result.month = c.month; result.day = c.day
        result.hour = c.hour; result.minute = c.minute; result.second = c.second
        let weekday = (ProlepticGregorian.floorDiv(wall.milliseconds, 86400000) + 4) % 7
        result.weekday = Int(weekday < 0 ? weekday + 7 : weekday) + 1
        return result
    }
    func component(_ field: Calendar.Component, from value: CalendarInstant) throws -> Int {
        let parts = try dateComponents([field], from: value)
        guard let number = parts.value(for: field) else { throw BetaError("Unsupported calendar component.") }
        return number
    }
    func date(from parts: DateComponents) -> CalendarInstant? {
        guard parts.era == nil || parts.era == 1, let year = parts.year, let month = parts.month, let day = parts.day,
              let civil = try? ProlepticGregorian.Civil(year: year, month: month, day: day, hour: parts.hour ?? 0, minute: parts.minute ?? 0, second: parts.second ?? 0) else { return nil }
        return try? zone.instant(CalendarInstant(milliseconds: civil.epochMilliseconds))
    }
    func date(byAdding field: Calendar.Component, value: Int, to date: CalendarInstant) -> CalendarInstant? {
        guard field == .day else { return nil }
        return try? CalendarCivil.addingDays(date, value, zone: zone)
    }
    func range(of small: Calendar.Component, in large: Calendar.Component, for date: CalendarInstant) -> Range<Int>? {
        guard small == .day, large == .month, let parts = try? dateComponents([.year, .month], from: date),
              let year = parts.year, let month = parts.month else { return nil }
        return 1..<(ProlepticGregorian.daysInMonth(year, month) + 1)
    }
}
