import Foundation
import CoreFoundation

/// Typed native snapshots are not DAV resources or deletion acknowledgements.
public struct SystemSourceSnapshot {
    public enum Scope {
        case boundedWindow(start: Date, end: Date)
        case fullSource
    }
    public struct Source {
        public let uid: String, kind: SystemSourcePolicy.Kind, title: String
        public let parentUID: String?, parentTitle: String?, parentType: String?
        public let nativeType: String, permission: String, readOnly: Bool
        public init(uid: String, kind: SystemSourcePolicy.Kind, title: String, parentUID: String? = nil, parentTitle: String? = nil, parentType: String? = nil,
                    nativeType: String, permission: String, readOnly: Bool) throws {
            _ = try SystemSourcePolicy.identifier(uid, kind: kind)
            guard title.utf8.count <= 4096, (parentUID?.utf8.count ?? 0) <= 8192,
                  (parentTitle?.utf8.count ?? 0) <= 4096, (parentType?.utf8.count ?? 0) <= 256,
                  nativeType.utf8.count <= 256,
                  ["authorized", "not_determined", "denied", "restricted", "write_only"].contains(permission) else { throw BetaError("Unknown native source permission.") }
            self.uid = uid; self.kind = kind; self.title = title; self.parentUID = parentUID
            self.parentTitle = parentTitle; self.parentType = parentType
            self.nativeType = nativeType; self.permission = permission
            // Contacts container type/authorization does not prove writability.
            self.readOnly = kind == .contacts || nativeType == "birthday" || readOnly
        }
    }
    public struct Record {
        /// Digest of serialized fields only; never a full native-object revision,
        /// server ETag, or atomic compare-and-swap token.
        public let revisionCoverage = "serialized-fields-only"
        public let sourceUID: String, kind: SystemSourcePolicy.Kind, identifier: String?
        public let occurrenceDate: Date?, fields: [String: Any], unsupported: [String], revision: String
        public init(source: Source, identifier: String?, occurrenceDate: Date? = nil,
                    fields: [String: Any], unsupported: [String] = []) throws {
            guard identifier == nil || (!identifier!.isEmpty && identifier!.utf8.count <= 16_384),
                  unsupported.count <= 256, unsupported.allSatisfy({ $0.utf8.count <= 1024 }),
                  occurrenceDate == nil || occurrenceDate!.timeIntervalSince1970.isFinite else { throw BetaError("Invalid native record identity.") }
            var limitations = unsupported
            if identifier == nil { limitations.append("native-identifier-unavailable") }
            var nodes = 0, bytes = 0
            func validate(_ value: Any, depth: Int) throws {
                nodes += 1
                guard depth <= 32, nodes <= 50_000 else { throw BetaError("Native record structure limit.") }
                if let text = value as? String { bytes += text.utf8.count }
                else if let object = value as? [String: Any] {
                    guard object.count <= 10_000 else { throw BetaError("Native record field limit.") }
                    for (key, child) in object { bytes += key.utf8.count; try validate(child, depth: depth + 1) }
                } else if let array = value as? [Any] {
                    guard array.count <= 50_000 else { throw BetaError("Native record list limit.") }
                    for child in array { try validate(child, depth: depth + 1) }
                } else if let number = value as? NSNumber {
                    guard number.doubleValue.isFinite else { throw BetaError("Invalid native numeric value.") }; bytes += 32
                } else if !(value is NSNull) { throw BetaError("Native record contains a non-JSON field.") }
                guard bytes <= 2 * 1024 * 1024 else { throw BetaError("Native record byte limit.") }
            }
            try validate(fields, depth: 0)
            let frozenFields = try Document.object(Document.encode(fields))
            let content: [String: Any] = ["sourceUID": source.uid, "kind": source.kind.rawValue,
                "identifier": identifier.map { $0 as Any } ?? NSNull(), "occurrenceDate": occurrenceDate.map { $0.timeIntervalSince1970 } as Any? ?? NSNull(),
                "fields": frozenFields, "unsupported": limitations, "revisionCoverage": "serialized-fields-only"]
            let encoded = try Document.encode(content)
            guard encoded.utf8.count <= 2 * 1024 * 1024 else { throw BetaError("Native record exceeds snapshot byte limit.") }
            self.sourceUID = source.uid; self.kind = source.kind; self.identifier = identifier
            self.occurrenceDate = occurrenceDate; self.fields = frozenFields; self.unsupported = limitations
            revision = try SystemSourcePolicy.revision(content)
        }
    }
    public let source: Source, scope: Scope, records: [Record]
    /// Even full enumeration alone is not an epoch/baseline/intent-backed delete receipt.
    public var authorizesAbsenceDeletion: Bool { false }
    public init(source: Source, scope: Scope, records: [Record]) throws {
        try SystemSourcePolicy.requireAccess(source.permission, kind: source.kind)
        switch scope {
        case .boundedWindow(let start, let end):
            guard source.kind == .events else { throw BetaError("Only event snapshots accept window scope.") }
            try SystemSourcePolicy.requireWindow(start: start, end: end)
        case .fullSource:
            guard source.kind != .events else { throw BetaError("EventKit window reads cannot claim a full event source.") }
        }
        guard records.count <= 10_000 else { throw BetaError("Native snapshot item limit.") }
        var identities = Set<String>(), total = 0
        for record in records {
            guard record.sourceUID == source.uid, record.kind == source.kind else { throw BetaError("Native record belongs to another source.") }
            if let identifier = record.identifier {
                let identity = try Document.encode([identifier, record.occurrenceDate.map { String($0.timeIntervalSince1970) } ?? "master"])
                guard identities.insert(identity).inserted else { throw BetaError("Ambiguous native source record identity.") }
            }
            total += try Document.encode(record.fields).utf8.count
            guard total <= 16 * 1024 * 1024 else { throw BetaError("Native snapshot byte limit.") }
        }
        self.source = source; self.scope = scope; self.records = records
    }
}

/// Keep absence, calendar and timezone instead of inventing midnight or a year.
public enum SystemDateComponents {
    public static func fields(_ value: DateComponents?) -> [String: Any]? {
        guard let value else { return nil }
        var result: [String: Any] = [:]
        for (name, number) in [("era", value.era), ("year", value.year), ("month", value.month), ("day", value.day),
                               ("hour", value.hour), ("minute", value.minute), ("second", value.second), ("nanosecond", value.nanosecond),
                               ("weekday", value.weekday), ("weekdayOrdinal", value.weekdayOrdinal), ("quarter", value.quarter),
                               ("weekOfMonth", value.weekOfMonth), ("weekOfYear", value.weekOfYear), ("yearForWeekOfYear", value.yearForWeekOfYear)] {
            if let number { result[name] = number }
        }
        if let leap = value.isLeapMonth { result["isLeapMonth"] = leap }
        if let calendar = value.calendar {
            result["calendar"] = String(describing: calendar.identifier)
            result["calendarTimeZone"] = calendar.timeZone.identifier
            result["calendarFirstWeekday"] = calendar.firstWeekday
            result["calendarMinimumDaysInFirstWeek"] = calendar.minimumDaysInFirstWeek
            if let locale = calendar.locale { result["calendarLocale"] = locale.identifier }
        }
        if let zone = value.timeZone { result["timeZone"] = zone.identifier }
        return result
    }
}

public enum SystemRecordNormalizer {
    public enum Projection {
        case draft([String: Any])
        case unsupported(record: SystemSourceSnapshot.Record, reasons: [String])
    }
    public static func project(_ record: SystemSourceSnapshot.Record, source: SystemSourceSnapshot.Source,
                               displayTimeZone: String) throws -> Projection {
        guard record.sourceUID == source.uid, record.kind == source.kind else { throw BetaError("Native projection source mismatch.") }
        var reasons = record.unsupported
        if source.permission != "authorized" { reasons.append("source-not-authorized") }
        if source.nativeType == "birthday" { reasons.append("birthday-calendar-needs-contact-provenance") }
        if record.kind == .events, !(record.fields["recurring"] is Bool) || !(record.fields["isDetached"] is Bool) ||
            !(record.fields["alarms"] is [Any]) || !(record.fields["recurrenceRules"] is [Any]) ||
            !(record.fields["attendeeCount"] is Int) || !(record.fields["hasOrganizer"] is Bool) {
            reasons.append("native-event-feature-state-unavailable")
        }
        if record.fields["recurring"] as? Bool == true || record.fields["isDetached"] as? Bool == true ||
            !(record.fields["recurrenceRules"] as? [Any] ?? []).isEmpty { reasons.append("native-series-projection-not-lossless") }
        if !(record.fields["alarms"] as? [Any] ?? []).isEmpty { reasons.append("native-alarms-projection-not-lossless") }
        if (record.fields["attendeeCount"] as? Int ?? 0) > 0 || record.fields["hasOrganizer"] as? Bool == true { reasons.append("native-participants-projection-not-lossless") }
        // Contacts retain vCard/date components but await a tested complete mapping.
        if record.kind == .contacts { reasons.append("contact-mapping-not-implemented") }
        if record.kind == .reminders { reasons.append("reminder-component-and-hierarchy-mapping-not-implemented") }
        if !reasons.isEmpty { return .unsupported(record: record, reasons: reasons) }
        guard let identifier = record.identifier,
              let start = record.fields["start"] as? Double, let end = record.fields["end"] as? Double,
              start.isFinite, end.isFinite, end >= start,
              let title = record.fields["title"] as? String, !title.isEmpty,
              let boolean = record.fields["allDay"] as? NSNumber, CFGetTypeID(boolean) == CFBooleanGetTypeID() else { throw BetaError("Invalid one-off native event snapshot.") }
        let allDay = boolean.boolValue
        guard (-62_135_596_800...253_402_300_799).contains(start), (-62_135_596_800...253_402_300_799).contains(end) else {
            return .unsupported(record: record, reasons: ["native-event-date-outside-canonical-range"])
        }
        guard let zone = TimeZone(identifier: displayTimeZone) else { throw BetaError("Explicit display timezone required for native event projection.") }
        // All-day midnight depends on the native calendar zone, not viewer zone.
        let eventZone: TimeZone
        if allDay {
            guard let nativeZone = record.fields["timeZone"] as? String, let resolved = TimeZone(identifier: nativeZone) else {
                return .unsupported(record: record, reasons: ["all-day-native-zone-unavailable"])
            }
            eventZone = resolved
        } else { eventZone = zone }
        func format(_ date: Date, _ template: String) -> String {
            let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.calendar = Calendar(identifier: .gregorian); formatter.timeZone = eventZone; formatter.dateFormat = template
            return formatter.string(from: date)
        }
        let first = Date(timeIntervalSince1970: start), last = Date(timeIntervalSince1970: end)
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = eventZone
        if allDay {
            let firstClock = calendar.dateComponents([.hour, .minute, .second], from: first)
            let lastClock = calendar.dateComponents([.hour, .minute, .second], from: last)
            guard firstClock.hour == 0, firstClock.minute == 0, firstClock.second == 0,
                  lastClock.hour == 0, lastClock.minute == 0, lastClock.second == 0 else {
                return .unsupported(record: record, reasons: ["native-all-day-boundaries-not-midnight"])
            }
        }
        let inclusiveEnd = allDay && end > start ? calendar.date(byAdding: .day, value: -1, to: last)! : last
        let key = try SystemSourcePolicy.revision(["source": source.uid, "identifier": identifier,
            "occurrenceDate": record.occurrenceDate.map { $0.timeIntervalSince1970 as Any } ?? NSNull()])
        let draft: [String: Any] = ["uid": "mac-native:" + key, "titel": title, "notiz": record.fields["notes"] as? String ?? "",
            "ort": record.fields["location"] as? String ?? "", "datum": format(first, "yyyy-MM-dd"), "endDatum": format(inclusiveEnd, "yyyy-MM-dd"),
            "zeit": allDay ? "" : format(first, "HH:mm:ss"), "endZeit": allDay ? "" : format(last, "HH:mm:ss"), "ganztag": allDay,
            "icsAnzeigeZeitzone": eventZone.identifier, "wiederholung": ["art": "none"],
            "nativeSystemRecord": ["sourceUID": source.uid, "identifier": identifier, "revision": record.revision,
                                   "revisionCoverage": record.revisionCoverage, "fields": record.fields,
                                   "occurrenceDate": record.occurrenceDate.map { $0.timeIntervalSince1970 as Any } ?? NSNull()],
            "nativeSourceReadOnly": source.readOnly]
        return .draft(draft)
    }
}
