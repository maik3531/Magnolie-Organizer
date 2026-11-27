import Foundation
import CoreFoundation
import CryptoKit

/// Refs #770. A bounded proposal for explicitly copying individual native events.
/// No store, permission request, remote write, synchronization or deletion authority.
public enum SystemCalendarImport {
    public static let maximumBytes = 16 * 1024 * 1024
    public static let maximumRecords = 10_000
    public static let maximumWindowSeconds: TimeInterval = 366 * 86400

    public struct Plan {
        public let source: [String: Any], window: [String: Any]
        public let appointments: [[String: Any]], excluded: [[String: Any]]
        public let snapshotRevision: String
        private let evidence: Data

        fileprivate init(source: [String: Any], window: [String: Any], appointments: [[String: Any]],
                         excluded: [[String: Any]], evidence: Data) throws {
            self.source = source; self.window = window; self.appointments = appointments
            self.excluded = excluded; self.evidence = evidence
            self.snapshotRevision = SystemCalendarImport.hash(evidence)
            guard try Document.encode(payload).utf8.count <= maximumBytes else {
                throw BetaError("The native calendar proposal exceeds 16 MiB. Select a smaller date window.")
            }
        }

        public var payload: [String: Any] {
            ["version": 1, "source": source, "window": window, "appointments": appointments,
             "excluded": excluded, "snapshotRevision": snapshotRevision]
        }

        /// Bind confirmation to the same complete bounded read, including excluded
        /// records and source/account metadata. Enumeration order is immaterial.
        public func revalidate(_ snapshot: SystemSourceSnapshot) throws {
            guard try SystemCalendarImport.evidence(snapshot) == evidence else {
                throw BetaError("The selected macOS calendar changed. Review a new proposal before importing.")
            }
        }
    }

    public static func snapshotRevision(_ snapshot: SystemSourceSnapshot) throws -> String {
        hash(try evidence(snapshot))
    }

    public static func prepare(_ snapshot: SystemSourceSnapshot, context: CalendarTimeContext,
                               displayTimeZone: String) throws -> Plan {
        let proof = try evidence(snapshot)
        // Resolve once through the pinned model. Neither a current OS offset nor
        // an invalid display-zone fallback can determine the projected dates.
        guard !displayTimeZone.isEmpty, displayTimeZone != "system" else {
            throw BetaError("Choose an explicit display timezone for the native calendar copy.")
        }
        _ = try context.named(displayTimeZone)
        var counts: [OpaqueUTF8Identity: Int] = [:]
        for record in snapshot.records {
            if let identifier = record.identifier { counts[OpaqueUTF8Identity(identifier), default: 0] += 1 }
        }
        var appointments: [[String: Any]] = [], excluded: [[String: Any]] = []
        var projectedBytes = 0
        for record in try ordered(snapshot.records) {
            let title = record.fields["title"] as? String ?? ""
            let appointmentCount = appointments.count
            do {
                if let identifier = record.identifier, counts[OpaqueUTF8Identity(identifier), default: 0] != 1 {
                    throw Exclusion("native-event-identity-ambiguous")
                }
                guard ["recurring", "isDetached", "hasOrganizer"].allSatisfy({ key in
                    guard let value = record.fields[key] as? NSNumber else { return false }
                    return CFGetTypeID(value) == CFBooleanGetTypeID()
                }), integer(record.fields["attendeeCount"]).map({ $0 >= 0 }) == true else {
                    throw Exclusion("native-event-feature-state-unavailable")
                }
                // This shared policy is an eligibility gate only. Its Foundation
                // wall-clock draft is never the source of the imported dates.
                switch try SystemRecordNormalizer.project(record, source: snapshot.source, displayTimeZone: displayTimeZone) {
                case .unsupported(_, let reasons): throw Exclusion(reasons)
                case .draft: break
                }
                appointments.append(try appointment(record, source: snapshot.source, context: context,
                                                    displayTimeZone: displayTimeZone))
            } catch let exclusion as Exclusion {
                excluded.append(["title": title, "reasons": Array(Set(exclusion.reasons)).sorted()])
            } catch {
                // A malformed or unrepresentable individual record is visible in
                // the proposal; it cannot silently disappear or become a guess.
                excluded.append(["title": title, "reasons": ["native-event-calendar-projection-unavailable"]])
            }
            let entry = appointments.count > appointmentCount ? appointments.last! : excluded.last!
            projectedBytes += try Document.encode(entry).utf8.count
            guard projectedBytes <= maximumBytes else {
                throw BetaError("The native calendar proposal exceeds 16 MiB. Select a smaller date window.")
            }
        }
        return try Plan(source: sourcePayload(snapshot.source), window: windowPayload(snapshot),
                        appointments: appointments, excluded: excluded, evidence: proof)
    }

    private struct Exclusion: Error {
        let reasons: [String]
        init(_ reason: String) { reasons = [reason] }
        init(_ reasons: [String]) { self.reasons = reasons.isEmpty ? ["native-event-not-representable"] : reasons }
    }

    private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    private static func nullable(_ value: String?) -> Any { value.map { $0 as Any } ?? NSNull() }
    private static func sourcePayload(_ source: SystemSourceSnapshot.Source) -> [String: Any] {
        ["uid": source.uid, "title": source.title, "parentUID": nullable(source.parentUID),
         "parentTitle": nullable(source.parentTitle), "parentType": nullable(source.parentType), "nativeType": source.nativeType]
    }
    private static func windowPayload(_ snapshot: SystemSourceSnapshot) throws -> [String: Any] {
        guard snapshot.source.kind == .events, case .boundedWindow(let start, let end) = snapshot.scope else {
            throw BetaError("Native calendar copying requires a bounded event source.")
        }
        try SystemSourcePolicy.requireAccess(snapshot.source.permission, kind: .events)
        try SystemSourcePolicy.requireWindow(start: start, end: end)
        guard end.timeIntervalSince(start) <= maximumWindowSeconds else {
            throw BetaError("Select a calendar date range of at most 366 days.")
        }
        return ["start": start.timeIntervalSince1970, "end": end.timeIntervalSince1970]
    }
    private static func recordEvidence(_ record: SystemSourceSnapshot.Record) -> [String: Any] {
        ["sourceUID": record.sourceUID, "kind": record.kind.rawValue, "identifier": nullable(record.identifier),
         "occurrenceDate": record.occurrenceDate.map { $0.timeIntervalSince1970 as Any } ?? NSNull(),
         "revision": record.revision, "revisionCoverage": record.revisionCoverage]
    }
    private static func ordered(_ records: [SystemSourceSnapshot.Record]) throws -> [SystemSourceSnapshot.Record] {
        var entries: [(Data, SystemSourceSnapshot.Record)] = [], bytes = 0
        for record in records {
            let key = Data(try Document.encode(recordEvidence(record)).utf8)
            bytes += key.count
            guard bytes <= maximumBytes else { throw BetaError("The native calendar identity evidence exceeds 16 MiB.") }
            entries.append((key, record))
        }
        return entries.sorted { $0.0.lexicographicallyPrecedes($1.0) }.map { $0.1 }
    }
    private static func evidence(_ snapshot: SystemSourceSnapshot) throws -> Data {
        let window = try windowPayload(snapshot)
        guard snapshot.records.count <= maximumRecords else { throw BetaError("Too many native calendar records.") }
        var source = sourcePayload(snapshot.source)
        source["kind"] = snapshot.source.kind.rawValue
        source["permission"] = snapshot.source.permission; source["readOnly"] = snapshot.source.readOnly
        let records = try ordered(snapshot.records).map(recordEvidence)
        let result = Data(try Document.encode(["version": 1, "source": source, "window": window, "records": records]).utf8)
        guard result.count <= maximumBytes else { throw BetaError("The native calendar identity evidence exceeds 16 MiB.") }
        return result
    }

    private static func number(_ value: Any?) -> Double? {
        guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return nil }
        return value.doubleValue
    }
    private static func integer(_ value: Any?) -> Int? {
        guard let number = number(value), number.rounded(.towardZero) == number, (-1...1_000_000).contains(number) else { return nil }
        return Int(number)
    }
    private static func instant(_ value: Any?) throws -> CalendarInstant {
        guard let seconds = number(value), (-62_135_596_800...253_402_300_799).contains(seconds) else {
            throw Exclusion("native-event-date-outside-canonical-range")
        }
        guard seconds.rounded(.towardZero) == seconds else { throw Exclusion("native-event-subsecond-time-not-representable") }
        return CalendarInstant(milliseconds: Int64(seconds) * 1000)
    }
    private static func optionalText(_ fields: [String: Any], _ key: String) throws -> String {
        if fields[key] is NSNull { return "" }
        guard let value = fields[key] as? String else { throw Exclusion("native-event-text-state-unavailable") }
        return value
    }
    private static func validText(_ value: String) -> Bool {
        value.unicodeScalars.allSatisfy { ($0.value >= 32 && $0.value != 127) || $0.value == 9 || $0.value == 10 }
    }
    private static func isJSTrimSpace(_ value: Unicode.Scalar) -> Bool {
        switch value.value {
        case 9...13, 32, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF: return true
        default: return false
        }
    }
    private static func escaped(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: ",", with: "\\,").replacingOccurrences(of: ";", with: "\\;")
    }
    /// RFC 5545 octet folding, never splitting a UTF-8 scalar. Continuation space
    /// counts toward the 75-octet physical-line limit.
    static func folded(_ line: String) throws -> String {
        guard line.utf8.count <= 1024 * 1024 else { throw Exclusion("native-event-text-exceeds-calendar-limit") }
        var result = "", length = 0
        for scalar in line.unicodeScalars {
            let text = String(scalar), count = text.utf8.count
            if length + count > 75 { result += "\r\n "; length = 1 }
            result += text; length += count
        }
        return result
    }

    private static func appointment(_ record: SystemSourceSnapshot.Record, source: SystemSourceSnapshot.Source,
                                    context: CalendarTimeContext, displayTimeZone: String) throws -> [String: Any] {
        guard let identifier = record.identifier, let title = record.fields["title"] as? String,
              !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let boolean = record.fields["allDay"] as? NSNumber, CFGetTypeID(boolean) == CFBooleanGetTypeID() else {
            throw Exclusion("native-event-identity-or-title-unavailable")
        }
        let notes = try optionalText(record.fields, "notes"), location = try optionalText(record.fields, "location")
        guard title.utf8.count <= 65_536, notes.utf8.count <= 1_048_576,
              [title, notes, location].allSatisfy(validText) else { throw Exclusion("native-event-text-not-representable") }
        guard location.utf16.count <= 1000,
              !(location.unicodeScalars.first.map(isJSTrimSpace) ?? false),
              !(location.unicodeScalars.last.map(isJSTrimSpace) ?? false) else {
            throw Exclusion("native-event-location-would-change")
        }
        let first = try instant(record.fields["start"]), last = try instant(record.fields["end"])
        guard last >= first else { throw Exclusion("native-event-invalid-date-range") }
        let allDay = boolean.boolValue
        let identity = hash(OpaqueUTF8Identity(parts: [source.uid, identifier]).bytes)
        let uid = "mac-native-copy:" + identity
        var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Magnolie//Native Calendar Copy 1//EN",
                     "BEGIN:VEVENT", "UID:" + uid, "SUMMARY:" + escaped(title), "DESCRIPTION:" + escaped(notes)]
        let zone: String
        if allDay {
            guard last > first, let nativeZone = record.fields["timeZone"] as? String else {
                throw Exclusion("native-all-day-date-range-or-zone-unavailable")
            }
            guard let native = try? context.named(nativeZone) else { throw Exclusion("native-all-day-zone-not-in-calendar-model") }
            let begin = try ProlepticGregorian.civil(at: native.wall(first).milliseconds)
            let finish = try ProlepticGregorian.civil(at: native.wall(last).milliseconds)
            guard begin.hour == 0, begin.minute == 0, begin.second == 0,
                  finish.hour == 0, finish.minute == 0, finish.second == 0 else {
                throw Exclusion("native-all-day-boundaries-not-midnight-in-calendar-model")
            }
            lines += ["DTSTART;VALUE=DATE:" + (try CalendarCivil.format(first, "yyyyMMdd", native)),
                      "DTEND;VALUE=DATE:" + (try CalendarCivil.format(last, "yyyyMMdd", native))]
            zone = nativeZone
        } else {
            lines += ["DTSTART:" + (try CalendarCivil.format(first, "yyyyMMdd'T'HHmmss'Z'")),
                      "DTEND:" + (try CalendarCivil.format(last, "yyyyMMdd'T'HHmmss'Z'"))]
            zone = displayTimeZone
        }
        if !location.isEmpty { lines.append("LOCATION:" + escaped(location)) }
        let url = try optionalText(record.fields, "url")
        if !url.isEmpty {
            guard url.utf16.count <= 2048, url.unicodeScalars.allSatisfy({ $0.value > 32 && $0.value != 127 }),
                  let parsed = URL(string: url), parsed.scheme?.isEmpty == false,
                  Data(parsed.absoluteString.utf8) == Data(url.utf8) else { throw Exclusion("native-event-url-not-representable") }
            lines.append("URL:" + url)
        }
        // These are the public EventKit enum values recorded by the native reader.
        // Native tests additionally verify parity against the SDK enumerations.
        let statusLine: String?
        switch integer(record.fields["status"]) {
        case 0: statusLine = nil
        case 1: statusLine = "STATUS:CONFIRMED"
        case 2: statusLine = "STATUS:TENTATIVE"
        case 3: throw Exclusion("native-event-cancelled")
        default: throw Exclusion("native-event-status-unavailable")
        }
        if let statusLine { lines.append(statusLine) }
        switch integer(record.fields["availability"]) {
        case -1: break
        case 0: lines.append("TRANSP:OPAQUE")
        case 1: lines.append("TRANSP:TRANSPARENT")
        default: throw Exclusion("native-event-availability-not-representable")
        }
        lines += ["END:VEVENT", "END:VCALENDAR"]
        let bytes = Data((try lines.map(folded).joined(separator: "\r\n") + "\r\n").utf8)
        let decoded = try ICalendarImport.decode(bytes, context: context, displayTimeZone: zone)
        guard decoded.appointments.count == 1, decoded.tasks.isEmpty, decoded.anniversaries.isEmpty,
              var result = decoded.appointments.first,
              Data((result["titel"] as? String ?? "").utf8) == Data(title.utf8),
              Data((result["notiz"] as? String ?? "").utf8) == Data(notes.utf8) else {
            throw Exclusion("native-event-calendar-projection-would-change-text")
        }
        // Keep the codec's editable status projection. Restoring a raw STATUS
        // here would pin the old value after a local change of `vorlaeufig`.
        // The original public status remains exact in nativeSystemRecord.fields.
        result["ort"] = location; result["ganztag"] = allDay
        result["standardErinnerung"] = false; result["individuelleErinnerungTage"] = 0; result["alarme"] = [[String: Any]]()
        result["sync"] = false; result["syncKalenderUid"] = ""; result["syncQuellen"] = [String: Any]()
        result["icsQuelleId"] = ""; result["icsQuelleName"] = ""
        result["nativeSourceReadOnly"] = source.readOnly
        result["nativeSystemRecord"] = ["kind": record.kind.rawValue, "sourceUID": source.uid, "identifier": identifier,
            "revision": record.revision, "revisionCoverage": record.revisionCoverage, "fields": record.fields,
            "occurrenceDate": record.occurrenceDate.map { $0.timeIntervalSince1970 as Any } ?? NSNull()]
        result["nativeCalendarImport"] = ["version": 1, "identity": identity, "sourceUID": source.uid,
            "identifier": identifier, "sourceTitle": source.title, "parentUID": nullable(source.parentUID), "revision": record.revision]
        return result
    }
}
