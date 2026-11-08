import Foundation
import CoreFoundation

/// Source-preserving calendar export. This does not expand a recurrence into
/// occurrences, import data, or turn on a native reminder scheduler.
public enum ICalendarExport {
    public enum Kind: String { case appointments = "ics-termine", tasks = "ics-aufgaben", anniversaries = "ics-jahrestage" }

    private struct Property {
        let line: String
        let name: String
        let parameters: [String: String]
        let value: String
        init(_ line: String) throws {
            guard !line.isEmpty, !line.contains("\r"), !line.contains("\n"), !line.contains("\0") else {
                throw BetaError("Invalid calendar content line; export was cancelled.")
            }
            var quoted = false, separator: String.Index?
            for index in line.indices {
                if line[index] == "\"" { quoted.toggle() }
                else if line[index] == ":" && !quoted { separator = index; break }
            }
            guard let separator, !quoted else { throw BetaError("Invalid calendar property header.") }
            let header = String(line[..<separator])
            var fields: [String] = [], field = ""; quoted = false
            for character in header {
                if character == "\"" { quoted.toggle() }
                if character == ";" && !quoted { fields.append(field); field = "" }
                else { field.append(character) }
            }
            fields.append(field)
            guard let name = fields.first, ICalendarExport.matches(name, "^[A-Za-z0-9-]+$") else {
                throw BetaError("Invalid calendar property name.")
            }
            var parameters: [String: String] = [:]
            for parameter in fields.dropFirst() {
                let pair = parameter.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
                guard pair.count == 2, ICalendarExport.matches(pair[0], "^[A-Za-z0-9-]+$"),
                      parameters[pair[0].uppercased()] == nil else { throw BetaError("Invalid calendar parameter.") }
                let text = pair[1]
                parameters[pair[0].uppercased()] = text.hasPrefix("\"") && text.hasSuffix("\"") ? String(text.dropFirst().dropLast()) : text
            }
            self.line = line; self.name = name.uppercased(); self.parameters = parameters
            self.value = String(line[line.index(after: separator)...])
        }
    }
    private struct Clock {
        let instant: Date
        let dateOnly: Bool
        let zone: TimeZone
        let floating: Bool
    }
    private static func matches(_ text: String, _ pattern: String) -> Bool { text.range(of: pattern, options: .regularExpression) != nil }
    private static func meaningful(_ value: Any) -> Bool {
        if value is NSNull { return false }
        if let value = value as? String { return !value.isEmpty }
        if let value = value as? [Any] { return !value.isEmpty }
        if let value = value as? [String: Any] { return value.values.contains(where: meaningful) }
        if let value = value as? NSNumber { return value.doubleValue != 0 }
        return true
    }
    private static func text(_ record: [String: Any], _ name: String) -> String { record[name] as? String ?? "" }
    private static func integer(_ value: Any?, default fallback: Int) throws -> Int {
        guard let value else { return fallback }
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite,
              number.doubleValue == number.doubleValue.rounded(), abs(number.doubleValue) <= 9_007_199_254_740_991 else {
            throw BetaError("Invalid integer calendar field.")
        }; return number.intValue
    }
    private static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n").replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: ",", with: "\\,").replacingOccurrences(of: ";", with: "\\;")
    }
    private static func unescape(_ value: String) -> String {
        var output = "", escaped = false
        for character in value {
            if escaped { output.append(character == "n" || character == "N" ? "\n" : character); escaped = false }
            else if character == "\\" { escaped = true }
            else { output.append(character) }
        }
        if escaped { output.append("\\") }; return output
    }
    private static func calendar(_ zone: TimeZone) -> Calendar {
        var value = Calendar(identifier: .gregorian); value.timeZone = zone; value.locale = Locale(identifier: "en_US_POSIX"); return value
    }
    private static let utc = TimeZone(secondsFromGMT: 0)!
    private static func format(_ date: Date, _ pattern: String, _ zone: TimeZone = utc) -> String {
        let formatter = DateFormatter(); formatter.calendar = calendar(zone); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = zone; formatter.dateFormat = pattern; return formatter.string(from: date)
    }
    private static func day(_ value: String) throws -> Date {
        guard matches(value, "^[0-9]{4}-[0-9]{2}-[0-9]{2}$") else { throw BetaError("Invalid calendar date.") }
        let formatter = DateFormatter(); formatter.calendar = calendar(utc); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = utc; formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        guard let result = formatter.date(from: value), formatter.string(from: result) == value else { throw BetaError("Invalid calendar date.") }
        return result
    }
    private static func zone(_ name: String) throws -> TimeZone {
        guard !name.isEmpty, matches(name, "^[A-Za-z0-9_+./-]+$"), !name.contains(".."), let zone = TimeZone(identifier: name) else {
            throw BetaError("This calendar time zone is unavailable; export was cancelled.")
        }; return zone
    }
    private static func displayZone(_ record: [String: Any]) throws -> TimeZone {
        let name = text(record, "icsAnzeigeZeitzone")
        if name.isEmpty || name == "system" { return .current }
        return try zone(name)
    }
    /// Strict wall-clock construction: DST gaps are rejected and folds select the
    /// first occurrence, matching the canonical desktop's source-time contract.
    private static func wall(_ date: String, _ time: String, _ zone: TimeZone) throws -> Date {
        _ = try day(date)
        guard matches(time, "^(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?$") else { throw BetaError("Invalid calendar clock.") }
        let values = date.split(separator: "-").compactMap { Int($0) } + time.split(separator: ":").compactMap { Int($0) }
        let components = DateComponents(year: values[0], month: values[1], day: values[2], hour: values[3], minute: values[4], second: values.count == 6 ? values[5] : 0)
        let cal = calendar(zone)
        let anchor = try day(date).addingTimeInterval(-172800)
        guard let result = cal.nextDate(after: anchor, matching: components, matchingPolicy: .strict, repeatedTimePolicy: .first, direction: .forward),
              format(result, "yyyy-MM-dd", zone) == date, format(result, time.count == 8 ? "HH:mm:ss" : "HH:mm", zone) == time else {
            throw BetaError("A calendar wall time falls in a daylight-saving gap; export was cancelled.")
        }; return result
    }
    private static func clock(_ property: Property, defaultZone: TimeZone) throws -> Clock {
        let value = property.value, allDay = property.parameters["VALUE"]?.uppercased() == "DATE" || matches(value, "^[0-9]{8}$")
        guard Set(property.parameters.keys).isSubset(of: ["TZID", "VALUE", "RANGE"]),
              property.parameters["RANGE"] == nil || property.name == "RECURRENCE-ID" && property.parameters["RANGE"]!.uppercased() == "THISANDFUTURE" else {
            throw BetaError("Unsupported calendar time parameters.")
        }
        if allDay {
            guard matches(value, "^[0-9]{8}$"), property.parameters["TZID"] == nil else { throw BetaError("Invalid date-only calendar property.") }
            let index = value.index(value.startIndex, offsetBy: 4), month = value.index(index, offsetBy: 2)
            let date = String(value[..<index]) + "-" + value[index..<month] + "-" + value[month...]
            return Clock(instant: try day(date), dateOnly: true, zone: utc, floating: true)
        }
        guard matches(value, "^[0-9]{8}T[0-9]{6}Z?$"), property.parameters["VALUE"] == nil || property.parameters["VALUE"]?.uppercased() == "DATE-TIME" else {
            throw BetaError("Invalid calendar date-time.")
        }
        let sourceZone: TimeZone
        if value.hasSuffix("Z") { sourceZone = utc }
        else { sourceZone = try property.parameters["TZID"].map(zone) ?? defaultZone }
        guard !value.hasSuffix("Z") || property.parameters["TZID"] == nil else { throw BetaError("UTC calendar times cannot also have TZID.") }
        let digits = Array(value.prefix(15))
        let date = String(digits[0..<4]) + "-" + String(digits[4..<6]) + "-" + String(digits[6..<8])
        let time = String(digits[9..<11]) + ":" + String(digits[11..<13]) + ":" + String(digits[13..<15])
        return Clock(instant: try wall(date, time, sourceZone), dateOnly: false, zone: sourceZone,
                     floating: !value.hasSuffix("Z") && property.parameters["TZID"] == nil)
    }
    private static func timeLine(_ name: String, date: String, time: String, zoneName: String) throws -> String {
        _ = try day(date)
        if time.isEmpty { return name + ";VALUE=DATE:" + date.replacingOccurrences(of: "-", with: "") }
        let zone: TimeZone
        if zoneName.isEmpty || zoneName == "system" { zone = .current }
        else { zone = try self.zone(zoneName) }
        _ = try wall(date, time, zone)
        let digits = time.replacingOccurrences(of: ":", with: "") + (time.count == 5 ? "00" : "")
        let header = zoneName.isEmpty || zoneName == "system" ? name : zoneName == "UTC" ? name : name + ";TZID=" + zoneName
        return header + ":" + date.replacingOccurrences(of: "-", with: "") + "T" + digits + (zoneName == "UTC" ? "Z" : "")
    }
    private static let localMetadata: Set<String> = ["id", "uid", "angelegt", "geaendert", "angelegtGeschaetzt", "ursprungApp", "personalGeaendert", "personalVersion", "kalenderQuelle", "syncKalenderUid", "icsQuelleId", "icsQuelleName", "icsImportUid", "icsSerienUid", "icsAnzeigeZeitzone", "icsKomplex", "icsAenderungszeitFehlt", "icsSequence", "icsStatus", "icsTimezones", "icsRoundtrip", "baumFreigabe", "baumGeaendert", "baumInhaltVersion", "baumVersion", "baumQuelle", "persoenlichVerknuepft", "geloescht"]
    private static func validateRecord(_ record: [String: Any], kind: Kind) throws {
        var allowed = localMetadata.union(["notiz", "kategorien", "akzentFarbe"])
        switch kind {
        case .appointments:
            allowed.formUnion(["titel", "datum", "zeit", "endDatum", "endZeit", "ganztag", "ort", "wiederholung", "icsAusnahmen", "icsZusatzDaten", "icsZusatzTermine", "icsRangeOverrides", "icsEndeFehlt", "icsNullDauer", "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "individuelleErinnerungTage", "standardErinnerung"])
        case .tasks:
            allowed.formUnion(["titel", "startDatum", "startZeit", "faellig", "faelligZeit", "prio", "erledigt", "erinnern", "individuelleErinnerungTage", "elternUid", "icsElternUid", "icsElternQuelleId", "reihenfolge", "personen", "wiederholung", "erinnerungsMinute"])
        case .anniversaries: allowed.formUnion(["name", "datum", "typ", "kontaktId", "quelle"])
        }
        for key in ["ganztag", "icsEndeFehlt", "icsNullDauer", "vertraulich", "vorlaeufig", "erledigt", "erinnern", "standardErinnerung"] {
            if let value = record[key] {
                guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { throw BetaError("Invalid boolean calendar field.") }
            }
        }
        guard !record.contains(where: { !allowed.contains($0.key) && meaningful($0.value) }) else {
            throw BetaError("This record contains fields the calendar exporter cannot preserve. Use a full JSON backup; nothing was exported.")
        }
    }
    private static func identifier(_ record: [String: Any]) -> String {
        for key in ["icsSerienUid", "icsImportUid", "uid", "id"] { let value = text(record, key); if !value.isEmpty { return value } }
        return UUID().uuidString + "@magnolie-macos-beta"
    }
    private static func raw(_ record: [String: Any]) throws -> [Property] {
        guard let lines = (record["icsRoundtrip"] ?? [String]()) as? [String] else { throw BetaError("Invalid source calendar properties.") }
        var depth = 0, singles: Set<String> = [], result: [Property] = []
        let unique: Set<String> = ["UID", "DTSTART", "DTEND", "DUE", "DURATION", "RRULE", "EXRULE", "RECURRENCE-ID", "SUMMARY", "DESCRIPTION", "STATUS", "CLASS", "SEQUENCE", "PRIORITY", "PERCENT-COMPLETE"]
        for line in lines {
            var property = try Property(line)
            if property.parameters["TZID"] == "", ["DTSTART", "DTEND", "DUE", "RECURRENCE-ID", "EXDATE", "RDATE"].contains(property.name) {
                // The ordinary editor uses empty TZID for a floating/system
                // clock. There is no named zone to preserve in that spelling.
                property = try Property(line.replacingOccurrences(of: ";TZID=(?:\"\")?(?=;|:)", with: "", options: [.regularExpression, .caseInsensitive]))
            }
            if property.name == "BEGIN" {
                guard depth == 0, property.value.uppercased() == "VALARM" else { throw BetaError("Invalid nested calendar component.") }
                depth = 1
            } else if property.name == "END" {
                guard depth == 1, property.value.uppercased() == "VALARM" else { throw BetaError("Unbalanced calendar component.") }
                depth = 0
            } else if depth == 0, unique.contains(property.name) {
                guard singles.insert(property.name).inserted else { throw BetaError("Duplicate source calendar property.") }
            }
            result.append(property)
        }
        guard depth == 0 else { throw BetaError("Unclosed calendar alarm.") }; return result
    }
    private static func topLevel(_ properties: [Property]) -> [Property] {
        var depth = 0
        return properties.filter { property in
            if property.name == "BEGIN" { depth += 1; return false }
            if property.name == "END" { depth -= 1; return false }
            return depth == 0
        }
    }
    private static func recurrence(_ record: [String: Any], start: Property) throws -> [String] {
        guard let value = record["wiederholung"] else { return [] }
        guard let repetition = value as? [String: Any] else { throw BetaError("Invalid structured recurrence.") }
        guard repetition["art"] == nil || repetition["art"] is String else { throw BetaError("Invalid recurrence frequency.") }
        let type = text(repetition, "art")
        guard Set(repetition.keys).isSubset(of: ["art", "bis", "intervall", "ordinal", "wochentag", "rruleForm", "daten"]) else { throw BetaError("Unsupported recurrence fields.") }
        if type.isEmpty || type == "none" {
            guard repetition.allSatisfy({ $0.key == "art" || !meaningful($0.value) }) else { throw BetaError("Contradictory recurrence.") }; return []
        }
        let frequency = ["daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"]
        let startClock = try clock(start, defaultZone: displayZone(record))
        func dated(_ date: String) throws -> String {
            _ = try day(date)
            // Keep the exact DATE/UTC/source-local representation of DTSTART.
            return date.replacingOccurrences(of: "-", with: "") + (startClock.dateOnly ? "" : String(start.value.dropFirst(8)))
        }
        if type == "custom" {
            guard let dates = repetition["daten"] as? [String], !dates.isEmpty else { throw BetaError("Custom recurrence dates are missing.") }
            let header = start.line.components(separatedBy: ":").first!.replacingOccurrences(of: "DTSTART", with: "RDATE")
            return [header + ":" + (try Array(Set(dates)).sorted().map(dated)).joined(separator: ",")]
        }
        guard let freq = frequency[type] else { throw BetaError("Unsupported recurrence frequency.") }
        var rule = "FREQ=" + freq
        if let interval = repetition["intervall"] {
            let number = try integer(interval, default: 1)
            guard (1...3660).contains(number) else { throw BetaError("Invalid recurrence interval.") }
            if number > 1 { rule += ";INTERVAL=" + String(number) }
        }
        if repetition["ordinal"] != nil || repetition["wochentag"] != nil {
            let ordinal = try integer(repetition["ordinal"], default: 0)
            guard type == "monthly", [-1, 1, 2, 3, 4].contains(ordinal),
                  ["MO", "TU", "WE", "TH", "FR", "SA", "SU"].contains(text(repetition, "wochentag")) else { throw BetaError("Invalid ordinal monthly recurrence.") }
            guard ["", "bysetpos"].contains(text(repetition, "rruleForm")) else { throw BetaError("Unsupported monthly recurrence form.") }
            let weekday = text(repetition, "wochentag")
            rule += text(repetition, "rruleForm") == "bysetpos" ? ";BYDAY=" + weekday + ";BYSETPOS=" + String(ordinal) : ";BYDAY=" + String(ordinal) + weekday
        }
        let until = text(repetition, "bis")
        if !until.isEmpty {
            _ = try day(until)
            let ending: String
            if startClock.dateOnly { ending = until.replacingOccurrences(of: "-", with: "") }
            else {
                let last = try wall(until, format(startClock.instant, "HH:mm:ss", startClock.zone), startClock.zone)
                ending = format(last, "yyyyMMdd'T'HHmmss", startClock.floating ? startClock.zone : utc) + (startClock.floating ? "" : "Z")
            }
            rule += ";UNTIL=" + ending
        }
        return ["RRULE:" + rule]
    }
    private static func ruleParts(_ value: String, start: Property) throws -> [String: String] {
        var parts: [String: String] = [:]
        for field in value.uppercased().split(separator: ";", omittingEmptySubsequences: false) {
            let pair = field.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
            guard pair.count == 2, !pair[1].isEmpty, parts[pair[0]] == nil else { throw BetaError("Invalid recurrence rule.") }
            parts[pair[0]] = pair[1]
        }
        let allowed: Set<String> = ["FREQ", "UNTIL", "COUNT", "INTERVAL", "BYSECOND", "BYMINUTE", "BYHOUR", "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS", "WKST"]
        guard Set(parts.keys).isSubset(of: allowed), ["SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"].contains(parts["FREQ"] ?? ""),
              parts["COUNT"] == nil || parts["UNTIL"] == nil else { throw BetaError("Unsupported or inconsistent recurrence rule.") }
        for key in ["INTERVAL", "COUNT"] {
            if let text = parts[key] { guard let value = Int(text), value > 0, value <= 9_007_199_254_740_991 else { throw BetaError("Invalid recurrence count/interval.") } }
        }
        for (key, lower, upper, nonzero) in [("BYSECOND", 0, 60, false), ("BYMINUTE", 0, 59, false), ("BYHOUR", 0, 23, false), ("BYMONTHDAY", -31, 31, true), ("BYYEARDAY", -366, 366, true), ("BYWEEKNO", -53, 53, true), ("BYMONTH", 1, 12, false), ("BYSETPOS", -366, 366, true)] {
            if let text = parts[key] {
                for item in text.split(separator: ",", omittingEmptySubsequences: false) {
                    guard let number = Int(item), number >= lower, number <= upper, !nonzero || number != 0 else { throw BetaError("Invalid recurrence selector.") }
                }
            }
        }
        if let text = parts["BYDAY"] {
            for item in text.split(separator: ",", omittingEmptySubsequences: false) {
                guard matches(String(item), "^(?:[+-]?(?:[1-9]|[1-4][0-9]|5[0-3]))?(?:MO|TU|WE|TH|FR|SA|SU)$") else { throw BetaError("Invalid recurrence weekday.") }
            }
        }
        if let week = parts["WKST"], !["MO", "TU", "WE", "TH", "FR", "SA", "SU"].contains(week) { throw BetaError("Invalid recurrence week start.") }
        if let until = parts["UNTIL"] {
            let ending = try clock(Property("DTSTART" + (until.count == 8 ? ";VALUE=DATE" : "") + ":" + until), defaultZone: clock(start, defaultZone: utc).zone)
            let initial = try clock(start, defaultZone: utc)
            guard ending.dateOnly == initial.dateOnly, ending.instant >= initial.instant else { throw BetaError("Recurrence end contradicts its start.") }
        }
        return parts
    }
    private static func duration(_ value: String, from start: Clock) throws -> Date {
        let pattern = "^\\+?P(?:(\\d+)W|(?:(\\d+)D)?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?)?)$"
        let expression = try NSRegularExpression(pattern: pattern)
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        guard let match = expression.firstMatch(in: value, range: range) else { throw BetaError("Invalid calendar duration.") }
        var values: [Int] = [], specified = false
        for index in 1...5 {
            if let range = Range(match.range(at: index), in: value) {
                guard let number = Int(value[range]), number <= 1_000_000 else { throw BetaError("Calendar duration exceeds the supported range.") }
                values.append(number); specified = true
            } else { values.append(0) }
        }
        guard specified, !start.dateOnly || values[2...4].allSatisfy({ $0 == 0 }),
              let days = calendar(start.zone).date(byAdding: .day, value: values[0] * 7 + values[1], to: start.instant) else { throw BetaError("Invalid calendar duration.") }
        return days.addingTimeInterval(TimeInterval(values[2] * 3600 + values[3] * 60 + values[4]))
    }
    private static func validateProjection(_ source: Clock, name: String, record: [String: Any], kind: Kind) throws {
        let dateField = kind == .tasks ? (name == "DTSTART" ? "startDatum" : "faellig") : (name == "DTSTART" ? "datum" : "endDatum")
        let clockField = kind == .tasks ? (name == "DTSTART" ? "startZeit" : "faelligZeit") : (name == "DTSTART" ? "zeit" : "endZeit")
        let storedDate = text(record, dateField).isEmpty && kind == .appointments ? text(record, "datum") : text(record, dateField)
        let storedTime = kind == .appointments && name == "DTEND" && text(record, clockField).isEmpty && record["icsNullDauer"] as? Bool == true
            ? text(record, "zeit") : text(record, clockField)
        var value = source.instant
        if source.dateOnly && kind == .appointments && name == "DTEND" { value = calendar(utc).date(byAdding: .day, value: -1, to: value)! }
        let projectionZone: TimeZone
        if source.dateOnly { projectionZone = utc }
        else { projectionZone = try displayZone(record) }
        guard !storedDate.isEmpty, format(value, "yyyy-MM-dd", projectionZone) == storedDate,
              source.dateOnly ? storedTime.isEmpty : format(value, storedTime.count == 8 ? "HH:mm:ss" : "HH:mm", projectionZone) == storedTime else {
            throw BetaError("Source calendar times contradict the visible record. Export was cancelled instead of replacing them.")
        }
    }
    private static func component(_ record: [String: Any], kind: Kind, taskParent: String? = nil) throws -> [String] {
        try validateRecord(record, kind: kind)
        let sources = try raw(record), top = topLevel(sources), display = try displayZone(record)
        var generated: [String] = ["UID:" + escape(identifier(record)), "DTSTAMP:" + format(Date(), "yyyyMMdd'T'HHmmss'Z'")]
        let title = text(record, kind == .anniversaries ? "name" : "titel")
        guard !title.isEmpty else { throw BetaError("Calendar records need a title.") }
        generated.append("SUMMARY:" + escape(title))
        let zoneName = text(record, "icsAnzeigeZeitzone")
        if kind == .appointments {
            let start = text(record, "datum"), startTime = text(record, "zeit")
            let endDate = text(record, "endDatum").isEmpty ? start : text(record, "endDatum")
            let endTime = text(record, "endZeit")
            _ = try day(start); _ = try day(endDate)
            if record["ganztag"] as? Bool == true && !startTime.isEmpty { throw BetaError("Ambiguous all-day calendar record.") }
            generated.append(try timeLine("DTSTART", date: start, time: startTime, zoneName: zoneName))
            if startTime.isEmpty {
                guard endTime.isEmpty, let exclusive = try calendar(utc).date(byAdding: .day, value: 1, to: day(endDate)) else { throw BetaError("Invalid all-day end.") }
                generated.append("DTEND;VALUE=DATE:" + format(exclusive, "yyyyMMdd"))
            } else if !endTime.isEmpty {
                generated.append(try timeLine("DTEND", date: endDate, time: endTime, zoneName: zoneName))
            } else if !top.contains(where: { $0.name == "DURATION" }) && record["icsEndeFehlt"] as? Bool != true {
                let startValue = try wall(start, startTime, display)
                let ending = startValue.addingTimeInterval(record["icsNullDauer"] as? Bool == true ? 0 : 1800)
                generated.append(try timeLine("DTEND", date: format(ending, "yyyy-MM-dd", display), time: format(ending, "HH:mm:ss", display), zoneName: zoneName))
            }
        } else if kind == .tasks {
            for (dateField, clockField, name) in [("startDatum", "startZeit", "DTSTART"), ("faellig", "faelligZeit", "DUE")] {
                if !text(record, dateField).isEmpty { generated.append(try timeLine(name, date: text(record, dateField), time: text(record, clockField), zoneName: zoneName)) }
                else if !text(record, clockField).isEmpty { throw BetaError("A task clock has no date.") }
            }
            let priority = try integer(record["prio"], default: 2)
            guard (1...3).contains(priority) else { throw BetaError("Invalid task priority.") }
            generated.append("PRIORITY:" + [1: "1", 2: "5", 3: "9"][priority]!)
            if record["erledigt"] as? Bool == true { generated += ["STATUS:COMPLETED", "PERCENT-COMPLETE:100"] }
            if record["erinnern"] as? Bool == true { generated.append("X-MAGNOLIE-ERINNERUNG-AM-TAG:1") }
            let parent = taskParent ?? (text(record, "icsElternUid").isEmpty ? text(record, "elternUid") : text(record, "icsElternUid"))
            if !parent.isEmpty { generated.append("RELATED-TO;RELTYPE=PARENT:" + escape(parent)) }
            let order = try integer(record["reihenfolge"], default: 0)
            guard order >= 0 else { throw BetaError("Invalid task order.") }; generated.append("X-MAGNOLIE-REIHENFOLGE:" + String(order))
            let identity: [String: Any] = ["v": 1, "source": text(record, "icsQuelleId"), "uid": identifier(record), "parent": parent,
                                         "parentSource": record["icsElternQuelleId"] as? String ?? text(record, "icsQuelleId")]
            generated.append("X-MAGNOLIE-TASK-IDENTITY:" + escape(try Document.encode(identity)))
        } else {
            let sourceDate = text(record, "datum")
            let date = sourceDate.hasPrefix("--") ? "2000-" + sourceDate.dropFirst(2) : sourceDate
            _ = try day(date)
            generated.append("DTSTART;VALUE=DATE:" + date.replacingOccurrences(of: "-", with: ""))
            generated.append("RRULE:FREQ=YEARLY")
            if sourceDate.hasPrefix("--") { generated.append("X-MAGNOLIE-DATE:" + sourceDate) }
            let names = ["birthday": "Geburtstag", "death-anniversary": "Todestag", "wedding-anniversary": "Hochzeitstag", "partnership-anniversary": "Partnerschaftstag", "name-day": "Namenstag", "baptism": "Tauftag", "first-communion": "Kommunion", "confirmation": "Konfirmation", "catholic-confirmation": "Firmung", "anniversary": "Jubiläum", "club-anniversary": "Vereinsjubiläum", "work-anniversary": "Dienstjubiläum", "founding-day": "Gründungstag", "memorial-day": "Gedenktag", "other": "Sonstiges"]
            let type = text(record, "typ").isEmpty ? "other" : text(record, "typ"), legacy = names[type] ?? type
            generated += ["CATEGORIES:" + escape(legacy), "X-MAGNOLIE-TYPE-ID:" + (names[type] == nil ? "custom" : type), "X-MAGNOLIE-TYP:" + escape(legacy), "X-MAGNOLIE-JAHRESTAG-TYP:" + escape(type)]
        }
        for (field, name) in [("notiz", "DESCRIPTION"), ("ort", "LOCATION"), ("kategorien", "CATEGORIES"), ("kostenstelle", "X-MAGNOLIE-KOSTENSTELLE"), ("kunde", "X-MAGNOLIE-KUNDE")] {
            if !text(record, field).isEmpty { generated.append(name + ":" + escape(text(record, field))) }
        }
        if record["vertraulich"] as? Bool == true { generated.append("CLASS:CONFIDENTIAL") }
        if record["vorlaeufig"] as? Bool == true { generated.append("STATUS:TENTATIVE") }
        if !text(record, "icsStatus").isEmpty { generated.removeAll(where: { $0.hasPrefix("STATUS:") }); generated.append("STATUS:" + text(record, "icsStatus")) }
        let accent = text(record, "akzentFarbe")
        if !accent.isEmpty { guard matches(accent, "^#[0-9a-fA-F]{6}$") else { throw BetaError("Invalid calendar accent color.") }; generated.append("X-MAGNOLIE-ACCENT-COLOR:" + accent.lowercased()) }
        let reminder = try integer(record["individuelleErinnerungTage"], default: 0)
        guard (0...7).contains(reminder) else { throw BetaError("Invalid custom calendar reminder.") }
        if reminder > 0 { generated.append("X-MAGNOLIE-ERINNERUNG-TAGE:" + String(reminder)) }
        if record["standardErinnerung"] as? Bool == false { generated.append("X-MAGNOLIE-STANDARDERINNERUNG:0") }
        if record["icsSequence"] != nil {
            let sequence = try integer(record["icsSequence"], default: 0)
            guard sequence >= 0 else { throw BetaError("Invalid calendar revision.") }
            generated.append("SEQUENCE:" + String(sequence))
        }
        var byName: [String: Property] = [:]
        for line in generated { let property = try Property(line); guard byName[property.name] == nil else { throw BetaError("Conflicting structured calendar fields.") }; byName[property.name] = property }
        let start = top.first(where: { $0.name == "DTSTART" }) ?? byName["DTSTART"]
        for property in top {
            if property.name == "RELATED-TO", property.parameters["RELTYPE"]?.uppercased() != "PARENT" { continue }
            if ["DTSTART", "DTEND", "DUE"].contains(property.name) {
                if kind != .anniversaries { try validateProjection(clock(property, defaultZone: display), name: property.name, record: record, kind: kind) }
                else if let own = byName[property.name] { guard property.line == own.line else { throw BetaError("Anniversary source date contradicts its visible date.") } }
            } else if property.name == "DURATION" {
                guard let start, !top.contains(where: { ["DTEND", "DUE"].contains($0.name) }) else { throw BetaError("Ambiguous source calendar duration.") }
                let source = try clock(start, defaultZone: display)
                let ending = Clock(instant: try duration(property.value, from: source), dateOnly: source.dateOnly, zone: source.zone, floating: source.floating)
                try validateProjection(ending, name: kind == .tasks ? "DUE" : "DTEND", record: record, kind: kind)
                byName.removeValue(forKey: kind == .tasks ? "DUE" : "DTEND")
            } else if let own = byName[property.name], !["RRULE", "X-MAGNOLIE-TASK-IDENTITY"].contains(property.name) {
                if kind == .tasks && property.name == "PRIORITY" {
                    guard let priority = Int(property.value), (0...9).contains(priority) else { throw BetaError("Invalid source task priority.") }
                    let bucket = (1...3).contains(priority) ? 1 : priority >= 7 ? 3 : 2
                    guard bucket == (try integer(record["prio"], default: 2)) else { throw BetaError("Source priority contradicts the visible task.") }
                } else if kind == .appointments && property.name == "CLASS" && record["vertraulich"] as? Bool == true {
                    guard ["PRIVATE", "CONFIDENTIAL"].contains(property.value.uppercased()) else { throw BetaError("Source confidentiality contradicts the visible appointment.") }
                } else {
                    guard unescape(property.value) == unescape(own.value) else { throw BetaError("Raw calendar data contradicts its visible fields.") }
                }
            }
            if ["RRULE", "EXRULE"].contains(property.name) {
                guard let start else { throw BetaError("A recurrence has no DTSTART.") }
                _ = try ruleParts(property.value, start: start)
            }
            if ["RDATE", "EXDATE", "RECURRENCE-ID"].contains(property.name) {
                guard let start else { throw BetaError("Recurrence dates have no DTSTART.") }
                let initial = try clock(start, defaultZone: display)
                for value in property.value.split(separator: ",", omittingEmptySubsequences: false) {
                    let header = property.line.prefix(while: { $0 != ":" })
                    let candidate = try clock(Property(String(header) + ":" + value), defaultZone: display)
                    guard candidate.dateOnly == initial.dateOnly else { throw BetaError("Recurrence value types do not match DTSTART.") }
                }
            }
            byName.removeValue(forKey: property.name)
        }
        if kind != .anniversaries, let start {
            let desired = try recurrence(record, start: start)
            let rawRule = top.first(where: { $0.name == "RRULE" })
            if let rawRule, let generatedRule = desired.first(where: { $0.hasPrefix("RRULE:") }) {
                let wanted = try ruleParts(String(generatedRule.dropFirst(6)), start: start), actual = try ruleParts(rawRule.value, start: start)
                guard wanted.allSatisfy({ actual[$0.key] == $0.value }), actual["COUNT"] == nil else { throw BetaError("Structured recurrence contradicts the source RRULE.") }
                let source = try clock(start, defaultZone: display)
                let components = calendar(source.zone).dateComponents([.weekday, .day, .month], from: source.instant)
                let weekday = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"][components.weekday! - 1]
                for (key, value) in actual where wanted[key] == nil {
                    let redundant = key == "INTERVAL" && value == "1" || key == "WKST" ||
                        key == "BYDAY" && wanted["FREQ"] == "WEEKLY" && value == weekday ||
                        key == "BYMONTHDAY" && ["MONTHLY", "YEARLY"].contains(wanted["FREQ"] ?? "") && value == String(components.day!) ||
                        key == "BYMONTH" && wanted["FREQ"] == "YEARLY" && value == String(components.month!)
                    guard redundant else { throw BetaError("The raw recurrence has selectors absent from the visible recurrence; export was cancelled.") }
                }
            } else if rawRule == nil {
                for line in desired { let property = try Property(line); if !top.contains(where: { $0.name == property.name }) { byName[property.name] = property } }
            }
            if let value = record["icsAusnahmen"] {
                guard let exceptions = value as? [String] else { throw BetaError("Invalid excluded calendar dates.") }
                let rawDates = try Set(top.filter { $0.name == "EXDATE" }.flatMap { property -> [String] in
                    try property.value.split(separator: ",").map { item in
                        let header = String(property.line.prefix(while: { $0 != ":" }))
                        let source = try clock(Property(header + ":" + item), defaultZone: display)
                        return format(source.instant, "yyyy-MM-dd", source.dateOnly ? utc : display)
                    }
                })
                let missing = Array(Set(exceptions)).sorted().filter { !rawDates.contains($0) }
                if !missing.isEmpty {
                    let source = try clock(start, defaultZone: display)
                    let additions = try missing.map { value -> Property in
                        let line = try timeLine("EXDATE", date: value, time: source.dateOnly ? "" : format(source.instant, "HH:mm:ss", display), zoneName: source.floating ? "" : text(record, "icsAnzeigeZeitzone"))
                        return try Property(line)
                    }
                    let header = String(additions[0].line.prefix(while: { $0 != ":" }))
                    byName["EXDATE"] = try Property(header + ":" + additions.map { $0.value }.joined(separator: ","))
                }
            }
        }
        let endName = kind == .tasks ? "DUE" : "DTEND"
        let effectiveStart = try start.map { try clock($0, defaultZone: display) }
        let effectiveEnd = try top.first(where: { $0.name == endName }).map { try clock($0, defaultZone: display) } ?? byName[endName].map { try clock($0, defaultZone: display) }
        if let lower = effectiveStart, let upper = effectiveEnd { guard upper.instant >= lower.instant else { throw BetaError("Calendar end precedes start.") } }
        let type = kind == .tasks ? "VTODO" : "VEVENT"
        return ["BEGIN:" + type] + generated.compactMap { line -> String? in
            guard let property = try? Property(line), let current = byName.removeValue(forKey: property.name) else { return nil }; return current.line
        } + byName.keys.sorted().compactMap { byName[$0]?.line } + sources.map { $0.line } + ["END:" + type]
    }

    public static func encode(_ input: [[String: Any]], kind: Kind, defaultTimeZone: String = "system") throws -> String {
        guard !input.isEmpty else { throw BetaError("There are no calendar records to export.") }
        let records = input.map { value -> [String: Any] in
            var copy = value
            if text(copy, "icsAnzeigeZeitzone").isEmpty { copy["icsAnzeigeZeitzone"] = defaultTimeZone }
            return copy
        }
        var definitions: [String: [String]] = [:], components: [[String]] = [], identities: Set<String> = [], owners: [String: String] = [:]
        let localTasks = Dictionary(grouping: records, by: { text($0, "uid") })
        for record in records {
            guard ["icsSerienUid", "icsImportUid", "uid", "id"].contains(where: { !text(record, $0).isEmpty }) else {
                throw BetaError("Calendar record has no stable identity; export was cancelled.")
            }
            let uid = identifier(record), source = text(record, "icsQuelleId")
            let properties = try topLevel(raw(record))
            let recurrenceID = properties.first(where: { $0.name == "RECURRENCE-ID" })?.line ?? "master"
            guard identities.insert(uid + "\u{0}" + recurrenceID).inserted,
                  owners[uid] == nil || owners[uid] == source else {
                throw BetaError("Colliding calendar source identities require source-aware alias export; nothing was exported.")
            }
            owners[uid] = source
            for field in ["icsZusatzDaten", "icsZusatzTermine"] {
                if let value = record[field], meaningful(value), !properties.contains(where: { $0.name == "RDATE" }) {
                    throw BetaError("Additional occurrence metadata has no authoritative RDATE; export was cancelled.")
                }
            }
            if let value = record["icsRangeOverrides"], meaningful(value) {
                guard let ranges = value as? [[String]], ranges.allSatisfy({ range in
                    records.contains(where: { identifier($0) == uid && ($0["icsRoundtrip"] as? [String]) == range })
                }) else { throw BetaError("Export the complete series including its range exceptions.") }
            }
            if kind == .tasks, record["erinnerungsMinute"] != nil {
                guard try integer(record["erinnerungsMinute"], default: 480) == 480 else { throw BetaError("The custom task reminder clock cannot be represented by this calendar export.") }
            }
            var parent: String?
            if kind == .tasks, !text(record, "elternUid").isEmpty {
                let matches = localTasks[text(record, "elternUid")] ?? []
                if matches.count == 1 { parent = identifier(matches[0]) }
                else if matches.count > 1 { throw BetaError("Ambiguous task parent identity.") }
            }
            let lines = try component(record, kind: kind, taskParent: parent)
            components.append(lines)
            if let value = record["icsTimezones"] {
                guard let blocks = value as? [[String]] else { throw BetaError("Invalid source time-zone definitions.") }
                for block in blocks {
                    guard block.first == "BEGIN:VTIMEZONE", block.last == "END:VTIMEZONE" else { throw BetaError("Invalid source time-zone component.") }
                    let properties = try block.map(Property.init)
                    let names = properties.filter { $0.name == "TZID" }
                    guard names.count == 1, !names[0].value.isEmpty else { throw BetaError("Missing or duplicate source TZID.") }
                    var stack: [String] = []
                    for property in properties {
                        if property.name == "BEGIN" {
                            guard stack.isEmpty ? property.value == "VTIMEZONE" : stack.count == 1 && ["STANDARD", "DAYLIGHT"].contains(property.value) else { throw BetaError("Invalid time-zone component nesting.") }
                            stack.append(property.value)
                        } else if property.name == "END" {
                            guard stack.popLast() == property.value else { throw BetaError("Unbalanced source time-zone definition.") }
                        }
                    }
                    guard stack.isEmpty else { throw BetaError("Unclosed source time-zone definition.") }
                    let name = names[0].value
                    if let previous = definitions[name], previous != block { throw BetaError("Conflicting source definitions share a TZID; export was cancelled.") }
                    definitions[name] = block
                }
            }
        }
        let referenced = try Set(components.flatMap { lines in try lines.compactMap { try Property($0).parameters["TZID"] } })
        for name in referenced.sorted() where definitions[name] == nil { definitions[name] = try TimeZoneExport.definition(name) }
        var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magnolie Organizer macOS Beta//EN", "CALSCALE:GREGORIAN"]
        for name in definitions.keys.sorted() { lines += definitions[name]! }
        lines += components.flatMap { $0 }; lines.append("END:VCALENDAR")
        return lines.map { line -> String in
            var result = "", width = 0
            for scalar in line.unicodeScalars {
                let text = String(scalar), size = text.utf8.count
                if width + size > 75 { result += "\r\n "; width = 1 }; result += text; width += size
            }; return result
        }.joined(separator: "\r\n") + "\r\n"
    }
}
