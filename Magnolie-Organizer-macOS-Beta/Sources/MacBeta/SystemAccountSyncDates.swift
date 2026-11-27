import Foundation
import BetaCore

/// Value container reconstruction only. No system timezone may stand in for an
/// absent DateComponents.timeZone; floating clocks remain floating clocks.
enum SystemAccountSyncDates {
    static func components(_ value: Any) throws -> DateComponents? {
        if value is NSNull { return nil }
        guard let fields = value as? [String: Any] else { throw BetaError("Invalid native date components.") }
        var result = DateComponents()
        let parts: [(String, Calendar.Component)] = [("era", .era), ("year", .year), ("month", .month), ("day", .day),
            ("hour", .hour), ("minute", .minute), ("second", .second), ("nanosecond", .nanosecond)]
        for (name, component) in parts where fields[name] != nil {
            guard let number = fields[name] as? Int else { throw BetaError("Invalid native date component.") }
            result.setValue(number, for: component)
        }
        if let leap = fields["isLeapMonth"] as? Bool { result.isLeapMonth = leap }
        if let name = fields["calendar"] as? String {
            guard name == "gregorian" else { throw BetaError("Unsupported native date calendar.") }
            var calendar = Calendar(identifier: .gregorian)
            calendar.locale = nil
            if let zone = fields["calendarTimeZone"] as? String {
                guard let resolved = TimeZone(identifier: zone) else { throw BetaError("Native date calendar timezone is unavailable.") }
                calendar.timeZone = resolved
            } else { calendar.timeZone = TimeZone(secondsFromGMT: 0)! }
            if let weekday = fields["calendarFirstWeekday"] as? Int { calendar.firstWeekday = weekday }
            if let minimum = fields["calendarMinimumDaysInFirstWeek"] as? Int { calendar.minimumDaysInFirstWeek = minimum }
            if let locale = fields["calendarLocale"] as? String { calendar.locale = Locale(identifier: locale) }
            result.calendar = calendar
        }
        if let zone = fields["timeZone"] as? String {
            guard let resolved = TimeZone(identifier: zone) else { throw BetaError("Native date timezone is unavailable.") }
            result.timeZone = resolved
        }
        return result
    }
}
