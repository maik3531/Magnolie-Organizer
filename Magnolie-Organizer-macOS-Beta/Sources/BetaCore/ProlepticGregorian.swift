/// Integer civil arithmetic on the proleptic Gregorian calendar. No Foundation
/// calendar cutover, locale, two-digit-year window or timezone rule lookup.
public enum ProlepticGregorian {
    public struct Civil: Equatable, Sendable {
        public let year, month, day, hour, minute, second, millisecond: Int
        public init(year: Int, month: Int, day: Int, hour: Int = 0, minute: Int = 0, second: Int = 0, millisecond: Int = 0) throws {
            guard (1...9999).contains(year), (1...12).contains(month), (1...ProlepticGregorian.daysInMonth(year, month)).contains(day),
                  (0...23).contains(hour), (0...59).contains(minute), (0...59).contains(second), (0...999).contains(millisecond) else { throw BetaError("Invalid proleptic Gregorian civil time.") }
            self.year = year; self.month = month; self.day = day; self.hour = hour
            self.minute = minute; self.second = second; self.millisecond = millisecond
        }
        public var fields: [Int] { [year, month, day, hour, minute, second, millisecond] }
        public var epochMilliseconds: Int64 {
            ProlepticGregorian.days(year, month, day) * 86_400_000 + Int64(hour * 3_600_000 + minute * 60_000 + second * 1000 + millisecond)
        }
        public func addingDays(_ count: Int) throws -> Civil {
            let (resultDay, overflow) = ProlepticGregorian.days(year, month, day).addingReportingOverflow(Int64(count))
            guard !overflow, (-719162...2932896).contains(resultDay) else { throw BetaError("Gregorian date arithmetic out of range.") }
            let date = ProlepticGregorian.date(resultDay)
            return try Civil(year: date.0, month: date.1, day: date.2, hour: hour, minute: minute, second: second, millisecond: millisecond)
        }
    }
    public static func isLeapYear(_ year: Int) -> Bool { year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) }
    public static func daysInMonth(_ year: Int, _ month: Int) -> Int {
        guard (1...12).contains(month) else { return 0 }
        return month == 2 ? (isLeapYear(year) ? 29 : 28) : [4, 6, 9, 11].contains(month) ? 30 : 31
    }
    static func floorDiv(_ value: Int64, _ divisor: Int64) -> Int64 {
        let quotient = value / divisor
        return value % divisor < 0 ? quotient - 1 : quotient
    }
    /// Internal neighboring years0/10000 support timezone boundary calculations.
    static func days(_ year: Int, _ month: Int, _ day: Int) -> Int64 {
        let y = Int64(year - (month <= 2 ? 1 : 0)), era = floorDiv(y, 400), yoe = y - era * 400
        let shifted = Int64(month + (month > 2 ? -3 : 9))
        let doy = (153 * shifted + 2) / 5 + Int64(day) - 1
        return era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468
    }
    static func date(_ days: Int64) -> (Int, Int, Int) {
        let z = days + 719468, era = floorDiv(z, 146097), doe = z - era * 146097
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100), mp = (5 * doy + 2) / 153
        let d = doy - (153 * mp + 2) / 5 + 1, m = mp + (mp < 10 ? 3 : -9)
        let y = yoe + era * 400 + (m <= 2 ? 1 : 0)
        return (Int(y), Int(m), Int(d))
    }
    static func uncheckedParts(_ epochMilliseconds: Int64) -> (year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int, millisecond: Int) {
        let day = floorDiv(epochMilliseconds, 86_400_000), clock = epochMilliseconds - day * 86_400_000, value = date(day)
        return (value.0, value.1, value.2, Int(clock / 3_600_000), Int(clock / 60_000 % 60), Int(clock / 1000 % 60), Int(clock % 1000))
    }
    public static func civil(at epochMilliseconds: Int64) throws -> Civil {
        guard epochMilliseconds >= -62_135_596_800_000, epochMilliseconds <= 253_402_300_799_999 else { throw BetaError("Gregorian instant out of range.") }
        let c = uncheckedParts(epochMilliseconds)
        return try Civil(year: c.year, month: c.month, day: c.day, hour: c.hour, minute: c.minute, second: c.second, millisecond: c.millisecond)
    }
    /// Sunday=0. Floor modulo is essential before the Unix epoch.
    public static func weekday(_ civil: Civil) -> Int {
        let value = (days(civil.year, civil.month, civil.day) + 4) % 7
        return Int(value < 0 ? value + 7 : value)
    }
}
