import Foundation
import CoreFoundation
import CryptoKit

/// Refs #777. Selected public EventKit fields become deliberate standalone task
/// copies. Unavailable native hierarchy/attachments/tags remain unavailable;
/// neither this proposal nor its serialized revision authorizes source writes.
public enum SystemReminderImport {
    public static let maximumRecords = 100
    public static let maximumBytes = 16 * 1024 * 1024
    public static let maximumTitleBytes = 4096
    public static let maximumIdentifierBytes = 16_384
    public static let maximumNoteBytes = 1_048_576
    public static let maximumScalarBytes = 65_536

    public struct Source: Sendable {
        public let sourceUID: String, calendarID: String, title: String
        public let parentUID: String, parentTitle: String, parentType: String
        public let nativeType: String, readOnly: Bool, permission: String
        public init(sourceUID: String, calendarID: String, title: String, parentUID: String,
                    parentTitle: String, parentType: String, nativeType: String, readOnly: Bool, permission: String) {
            self.sourceUID = sourceUID; self.calendarID = calendarID; self.title = title
            self.parentUID = parentUID; self.parentTitle = parentTitle; self.parentType = parentType
            self.nativeType = nativeType; self.readOnly = readOnly; self.permission = permission
        }
    }
    public struct Record {
        public let identifier: String, fields: [String: Any], failure: String?
        public init(identifier: String, fields: [String: Any], failure: String? = nil) {
            self.identifier = identifier; self.fields = fields; self.failure = failure
        }
    }
    public struct Snapshot {
        public let source: Source, records: [Record]
        public init(source: Source, records: [Record]) { self.source = source; self.records = records }
    }
    public struct Plan {
        public let payload: [String: Any], snapshotRevision: String
        private let evidence: Data
        fileprivate init(source: [String: Any], displayTimeZone: String, tasks: [[String: Any]],
                         excluded: [[String: Any]], evidence: Data) throws {
            self.evidence = evidence; snapshotRevision = SystemReminderImport.hash(evidence)
            payload = ["version": 1, "source": source, "displayTimeZone": displayTimeZone,
                       "tasks": tasks, "excluded": excluded, "snapshotRevision": snapshotRevision]
            guard try Document.encode(payload).utf8.count <= SystemReminderImport.maximumBytes else {
                throw SystemReminderImport.failure("proposal exceeds 16 MiB; select fewer reminders")
            }
        }
        /// Source/account metadata and all selected records, including exclusions,
        /// are compared as exact bytes. Enumeration order does not matter. This
        /// is serialized-field evidence, not an EventKit/server CAS token.
        public func revalidate(_ snapshot: Snapshot) throws {
            guard try SystemReminderImport.checked(snapshot).evidence == evidence else {
                throw SystemReminderImport.failure("the selected source changed; review a new proposal")
            }
        }
    }

    public static func prepare(_ snapshot: Snapshot, context: CalendarTimeContext,
                               displayTimeZone: String) throws -> Plan {
        // The host pins the document's chosen display zone through its whole
        // preview/commit transaction. It is never a substitute for a nil native
        // DateComponents.timeZone, which continues to mean floating time.
        _ = try context.database.named(displayTimeZone)
        let read = try checked(snapshot)
        var tasks: [[String: Any]] = [], excluded: [[String: Any]] = []
        for entry in read.records {
            let record = entry.record, title = record.fields["title"] as? String ?? ""
            do {
                let value = try project(record, context: context, displayTimeZone: displayTimeZone)
                let identity = hash(OpaqueUTF8Identity(parts: [snapshot.source.sourceUID, record.identifier]).bytes)
                let revision = hash(try framed([Data("macos-reminder-record-v1".utf8), read.sourceEvidence, entry.evidence]))
                tasks.append(["identity": identity, "revision": revision, "identifier": record.identifier, "title": title,
                              "task": value.task, "nativeRecord": entry.raw, "notices": value.notices])
            } catch let error as Exclusion {
                excluded.append(["identifier": record.identifier, "title": title, "reasons": [error.reason]])
            }
        }
        return try Plan(source: sourcePayload(snapshot.source), displayTimeZone: displayTimeZone,
                        tasks: tasks, excluded: excluded, evidence: read.evidence)
    }

    private struct Exclusion: Error { let reason: String; init(_ reason: String) { self.reason = reason } }
    private struct CheckedRecord { let record: Record, raw: [String: Any], evidence: Data }
    private struct CheckedSnapshot { let records: [CheckedRecord], sourceEvidence: Data, evidence: Data }
    private static let fieldNames: Set<String> = ["metadataIncomplete", "title", "notes", "location", "url", "externalIdentifier",
        "itemTimeZone", "created", "modified", "completed", "completionDate", "priority", "startComponents", "dueComponents",
        "hasNotes", "hasAlarms", "alarms", "hasRecurrenceRules", "recurrenceRules", "hierarchyAvailable"]
    private static let coverage: Set<String> = ["native-reminder-hierarchy", "native-reminder-attachments", "native-reminder-tags",
        "native-reminder-flags", "native-reminder-assignees", "native-reminder-rich-text", "provider-opaque-fields"]
    private static let componentFields: Set<String> = ["era", "year", "month", "day", "hour", "minute", "second", "nanosecond",
        "isLeapMonth", "calendar", "calendarTimeZone", "calendarFirstWeekday", "calendarMinimumDaysInFirstWeek", "calendarLocale", "timeZone"]
    private static func failure(_ text: String) -> BetaError { BetaError("macOS reminder copy: " + text + ".") }
    private static func hash(_ value: Data) -> String { SHA256.hash(data: value).map { String(format: "%02x", $0) }.joined() }
    private static func nullable(_ value: String?) -> Any { value.map { $0 as Any } ?? NSNull() }
    private static func sourcePayload(_ source: Source) -> [String: Any] {
        ["sourceUID": source.sourceUID, "calendarID": source.calendarID, "title": source.title,
         "parentUID": source.parentUID, "parentTitle": source.parentTitle, "parentType": source.parentType,
         "nativeType": source.nativeType, "readOnly": source.readOnly, "permission": source.permission]
    }
    private static func safe(_ value: String, note: Bool = false) -> Bool {
        value.unicodeScalars.allSatisfy {
            ($0.value >= 32 && !(0x7F...0x9F).contains($0.value)) || (note && [9, 10].contains($0.value))
        }
    }
    private static func trimSpace(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 9...13, 32, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF: return true
        default: return false
        }
    }
    private static func number(_ value: Any?) -> Double? {
        guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return nil }
        return value.doubleValue
    }
    private static func integer(_ value: Any?) -> Int? {
        guard let value = number(value), value.rounded() == value, abs(value) <= 9_007_199_254_740_991 else { return nil }
        return Int(value)
    }
    private static func boolean(_ value: Any?) -> Bool? {
        guard let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }
    private static func optionalText(_ fields: [String: Any], _ key: String, maximum: Int = maximumScalarBytes,
                                     note: Bool = false) throws -> String? {
        guard let value = fields[key] else { throw Exclusion("native-reminder-field-unavailable") }
        if value is NSNull { return nil }
        guard let text = value as? String else { throw Exclusion("native-reminder-field-unavailable") }
        guard text.utf8.count <= maximum, safe(text, note: note) else { throw Exclusion("native-reminder-text-not-representable") }
        return text
    }
    private static func timestamp(_ fields: [String: Any], _ key: String) throws -> Double? {
        guard let value = fields[key] else { throw Exclusion("native-reminder-timestamp-state-unavailable") }
        if value is NSNull { return nil }
        guard let value = number(value), (-62_135_596_800...253_402_300_799.999).contains(value) else {
            throw Exclusion("native-reminder-timestamp-state-unavailable")
        }
        return value
    }

    private static func checked(_ snapshot: Snapshot) throws -> CheckedSnapshot {
        guard snapshot.records.count <= maximumRecords else { throw failure("select at most 100 reminders") }
        let source = snapshot.source
        let parentPrefix = "macos-account:"
        guard !source.calendarID.isEmpty, source.calendarID.utf8.count <= maximumIdentifierBytes,
              source.sourceUID.utf8.count <= 4096,
              Data(source.sourceUID.utf8) == Data(SystemSourcePolicy.uid(.reminders, source.calendarID).utf8),
              source.parentUID.hasPrefix(parentPrefix), source.parentUID.utf8.count <= 8192,
              let parentBytes = Data(base64Encoded: String(source.parentUID.dropFirst(parentPrefix.count))),
              let parent = String(data: parentBytes, encoding: .utf8), !parent.isEmpty,
              source.parentUID == parentPrefix + parentBytes.base64EncodedString(),
              source.title.utf8.count <= maximumTitleBytes, source.parentTitle.utf8.count <= maximumTitleBytes,
              source.nativeType.utf8.count <= 64, source.parentType.utf8.count <= 64,
              source.nativeType.range(of: "\\Acalendar:[0-9]+\\z", options: .regularExpression) != nil,
              source.parentType.range(of: "\\Asource:[0-9]+\\z", options: .regularExpression) != nil,
              source.permission == "authorized",
              [source.calendarID, source.sourceUID, parent, source.title, source.parentTitle].allSatisfy({ safe($0) }) else {
            throw failure("invalid selected list/account identity or permission")
        }
        let sourceEvidence = Data(try Document.encode(sourcePayload(source)).utf8)
        var seen = Set<Data>(), records: [CheckedRecord] = [], total = sourceEvidence.count
        for input in snapshot.records {
            guard !input.identifier.isEmpty, input.identifier.utf8.count <= maximumIdentifierBytes,
                  (input.failure?.utf8.count ?? 0) <= maximumTitleBytes, seen.insert(Data(input.identifier.utf8)).inserted else {
                throw failure("missing, oversized or ambiguous native reminder identity")
            }
            guard Set(input.fields.keys).isSubset(of: fieldNames),
                  ((input.fields["title"] as? String)?.utf8.count ?? 0) <= maximumTitleBytes else {
                throw failure("unexpected native field or oversized title")
            }
            var nodes = 0, bytes = 0
            func freeze(_ value: Any, depth: Int) throws -> Any {
                nodes += 1
                guard depth <= 16, nodes <= 100_000 else { throw failure("native record structure limit") }
                let frozen: Any
                if let text = value as? String {
                    bytes += text.utf8.count
                    guard bytes <= maximumBytes - total else { throw failure("snapshot evidence exceeds 16 MiB") }
                    frozen = String(decoding: text.utf8, as: UTF8.self)
                } else if let object = value as? [String: Any] {
                    guard object.count <= 1000 else { throw failure("native field limit") }
                    var copy: [String: Any] = [:]
                    for (key, child) in object {
                        bytes += key.utf8.count
                        guard bytes <= maximumBytes - total else { throw failure("snapshot evidence exceeds 16 MiB") }
                        copy[key] = try freeze(child, depth: depth + 1)
                    }
                    frozen = copy
                } else if let array = value as? [Any] {
                    guard array.count <= 1000 else { throw failure("native value count limit") }
                    frozen = try array.map { try freeze($0, depth: depth + 1) }
                } else if let value = value as? NSNumber {
                    guard value.doubleValue.isFinite else { throw failure("invalid native numeric value") }
                    bytes += 32; frozen = value
                } else if value is NSNull { frozen = NSNull() }
                else { throw failure("non-JSON native field") }
                guard bytes <= maximumBytes - total else { throw failure("snapshot evidence exceeds 16 MiB") }
                return frozen
            }
            // Refs #797: JSONSerialization may consume a leading U+FEFF inside a string on
            // Darwin. Copy native values without that parse round-trip so editor
            // exclusions inspect the original text, including mutable NSStrings.
            guard let fields = try freeze(input.fields, depth: 0) as? [String: Any] else {
                throw failure("invalid native fields")
            }
            let record = Record(identifier: input.identifier, fields: fields, failure: input.failure)
            let raw: [String: Any] = ["identifier": record.identifier, "fields": fields, "failure": nullable(record.failure)]
            let evidence = Data(try Document.encode(raw).utf8)
            guard evidence.count <= maximumBytes - total else { throw failure("snapshot evidence exceeds 16 MiB") }
            total += evidence.count; records.append(CheckedRecord(record: record, raw: raw, evidence: evidence))
        }
        records.sort { Data($0.record.identifier.utf8).lexicographicallyPrecedes(Data($1.record.identifier.utf8)) }
        return CheckedSnapshot(records: records, sourceEvidence: sourceEvidence,
            evidence: try framed([Data("macos-reminder-snapshot-v1".utf8), sourceEvidence] + records.map(\.evidence)))
    }
    private static func framed(_ parts: [Data]) throws -> Data {
        var result = Data()
        func length(_ value: Int) {
            var number = UInt64(value).bigEndian
            withUnsafeBytes(of: &number) { result.append(contentsOf: $0) }
        }
        length(parts.count)
        for part in parts {
            guard result.count <= maximumBytes - 8, part.count <= maximumBytes - result.count - 8 else {
                throw failure("snapshot evidence exceeds 16 MiB")
            }
            length(part.count); result.append(part)
        }
        return result
    }

    private struct ControlledDate {
        let line: String, dateOnly: Bool, civil: ProlepticGregorian.Civil, instant: Int64?
        var floating: Bool { !dateOnly && instant == nil }
    }
    private static func component(_ fields: [String: Any], _ key: String, name: String,
                                  context: CalendarTimeContext) throws -> ControlledDate? {
        guard let raw = fields[key] else { throw Exclusion("native-reminder-date-state-unavailable") }
        if raw is NSNull { return nil }
        guard let value = raw as? [String: Any], Set(value.keys).isSubset(of: componentFields),
              value["calendar"] as? String == "gregorian",
              let year = integer(value["year"]), (1000...9999).contains(year),
              let month = integer(value["month"]), let day = integer(value["day"]),
              value["era"] == nil || integer(value["era"]) == 1,
              value["isLeapMonth"] == nil || boolean(value["isLeapMonth"]) == false else {
            throw Exclusion("native-reminder-date-components-not-representable")
        }
        let clockKeys = ["hour", "minute", "second"]
        let dateOnly = clockKeys.allSatisfy { value[$0] == nil }
        let hour: Int, minute: Int
        if dateOnly { hour = 0; minute = 0 }
        else {
            guard let h = integer(value["hour"]), let m = integer(value["minute"]),
                  (0...23).contains(h), (0...59).contains(m) else {
                throw Exclusion("native-reminder-date-components-not-representable")
            }
            hour = h; minute = m
        }
        guard value["second"] == nil || integer(value["second"]) == 0,
              value["nanosecond"] == nil || integer(value["nanosecond"]) == 0 else {
            throw Exclusion("native-reminder-subminute-time-not-supported")
        }
        for key in ["calendarTimeZone", "calendarLocale"] where value[key] != nil {
            guard let text = value[key] as? String, text.utf8.count <= 1024, safe(text) else {
                throw Exclusion("native-reminder-date-components-not-representable")
            }
        }
        for key in ["calendarFirstWeekday", "calendarMinimumDaysInFirstWeek"] where value[key] != nil {
            guard let n = integer(value[key]), (1...7).contains(n) else { throw Exclusion("native-reminder-date-components-not-representable") }
        }
        guard let civil = try? ProlepticGregorian.Civil(year: year, month: month, day: day, hour: hour, minute: minute, second: 0) else {
            throw Exclusion("native-reminder-date-components-not-representable")
        }
        let digits = String(format: "%04d%02d%02d", year, month, day)
        let zone: String?
        if value["timeZone"] == nil { zone = nil }
        else {
            guard let text = value["timeZone"] as? String, !text.isEmpty, text.utf8.count <= 1024, safe(text) else {
                throw Exclusion("native-reminder-date-components-not-representable")
            }
            zone = text
        }
        if dateOnly {
            // A DATE stays a calendar date. A retained native zone is evidence,
            // not a request to shift the date or manufacture midnight.
            return ControlledDate(line: name + ";VALUE=DATE:" + digits, dateOnly: true, civil: civil, instant: nil)
        }
        let clock = digits + String(format: "T%02d%02d00", hour, minute)
        guard let zone else {
            return ControlledDate(line: name + ":" + clock, dateOnly: false, civil: civil, instant: nil)
        }
        do {
            let named = try context.database.named(zone)
            guard let instant = try context.database.resolve(civil, in: named, fold: .reject, gap: .reject) else {
                throw Exclusion("native-reminder-time-zone-not-representable")
            }
            return ControlledDate(line: name + ";TZID=" + zone + ":" + clock, dateOnly: false, civil: civil, instant: instant)
        } catch { throw Exclusion("native-reminder-time-zone-not-representable") }
    }

    private static func display(_ value: ControlledDate?, context: CalendarTimeContext,
                                zone: String) throws -> (date: String, time: String) {
        guard let value else { return ("", "") }
        let wall: ProlepticGregorian.Civil
        if let instant = value.instant {
            do { wall = try context.database.wall(at: instant, in: context.database.named(zone)) }
            catch { throw Exclusion("native-reminder-time-zone-not-representable") }
        } else {
            // DATE and floating wall clocks have no absolute instant. Reusing a
            // decoder that resolves floating time in a display zone would reject
            // or choose DST gaps/folds that the native source never specified.
            wall = value.civil
        }
        guard (1000...9999).contains(wall.year) else { throw Exclusion("native-reminder-date-components-not-representable") }
        // Historical second-based offsets can turn a native minute into a
        // subminute displayed time, beyond the task editor/scheduler's scope.
        guard wall.second == 0, wall.millisecond == 0 else { throw Exclusion("native-reminder-subminute-time-not-supported") }
        return (String(format: "%04d-%02d-%02d", wall.year, wall.month, wall.day),
                value.dateOnly ? "" : String(format: "%02d:%02d", wall.hour, wall.minute))
    }

    private static func project(_ record: Record, context: CalendarTimeContext,
                                displayTimeZone: String) throws -> (task: [String: Any], notices: [String]) {
        if record.failure != nil { throw Exclusion("native-reminder-read-failed") }
        let fields = record.fields
        guard safe(record.identifier), Set(fields.keys) == fieldNames,
              let incomplete = fields["metadataIncomplete"] as? [String],
              coverage.isSubset(of: Set(incomplete)),
              Set(incomplete).isSubset(of: coverage.union(["alarm-procedure-url-not-exposed"])),
              boolean(fields["hierarchyAvailable"]) == false,
              let hasNotes = boolean(fields["hasNotes"]), let completed = boolean(fields["completed"]),
              let priority = integer(fields["priority"]), (0...9).contains(priority),
              let hasAlarms = boolean(fields["hasAlarms"]), let alarms = fields["alarms"] as? [[String: Any]], alarms.count <= 64,
              let hasRules = boolean(fields["hasRecurrenceRules"]), let rules = fields["recurrenceRules"] as? [[String: Any]], rules.count <= 64 else {
            throw Exclusion("native-reminder-field-unavailable")
        }
        guard !hasAlarms && alarms.isEmpty else { throw Exclusion("native-reminder-alarms-not-supported") }
        guard !hasRules && rules.isEmpty else { throw Exclusion("native-reminder-recurrence-not-supported") }
        guard let title = try optionalText(fields, "title", maximum: maximumTitleBytes), !title.isEmpty else {
            throw Exclusion("native-reminder-title-unavailable")
        }
        guard !(title.unicodeScalars.first.map(trimSpace) ?? false), !(title.unicodeScalars.last.map(trimSpace) ?? false) else {
            throw Exclusion("native-reminder-title-would-change")
        }
        let notes = try optionalText(fields, "notes", maximum: maximumNoteBytes, note: true)
        guard !(hasNotes && notes == nil), hasNotes || notes?.isEmpty != false else {
            throw Exclusion("native-reminder-note-state-unavailable")
        }
        let location = try optionalText(fields, "location"), url = try optionalText(fields, "url")
        _ = try optionalText(fields, "externalIdentifier", maximum: maximumIdentifierBytes)
        _ = try optionalText(fields, "itemTimeZone", maximum: 1024)
        let created = try timestamp(fields, "created"), modified = try timestamp(fields, "modified")
        let completedAt = try timestamp(fields, "completionDate")
        // Apple explicitly permits completed=true with no completionDate when
        // another client completed it. No completion instant is manufactured.
        guard completed || completedAt == nil else { throw Exclusion("native-reminder-completion-state-inconsistent") }
        let start = try component(fields, "startComponents", name: "DTSTART", context: context)
        let due = try component(fields, "dueComponents", name: "DUE", context: context)
        if let start, let due {
            guard start.dateOnly || !due.dateOnly else { throw Exclusion("native-reminder-date-window-not-editable") }
            if !start.dateOnly && !due.dateOnly {
                guard start.floating == due.floating else { throw Exclusion("native-reminder-mixed-time-semantics-not-supported") }
                let first = start.instant ?? start.civil.epochMilliseconds, last = due.instant ?? due.civil.epochMilliseconds
                guard last > first else { throw Exclusion("native-reminder-date-window-not-editable") }
            } else if start.dateOnly && due.dateOnly && due.civil.epochMilliseconds < start.civil.epochMilliseconds {
                throw Exclusion("native-reminder-date-window-not-editable")
            }
        }
        let timeLines = [start?.line, due?.line].compactMap { $0 }
        let projectedStart = try display(start, context: context, zone: displayTimeZone)
        let projectedDue = try display(due, context: context, zone: displayTimeZone)
        let startDay = projectedStart.date, startTime = projectedStart.time, dueDay = projectedDue.date, dueTime = projectedDue.time
        if !startDay.isEmpty && !dueDay.isEmpty {
            guard dueDay >= startDay, startTime.isEmpty || (!dueTime.isEmpty && dueDay + "T" + dueTime > startDay + "T" + startTime) else {
                throw Exclusion("native-reminder-date-window-not-editable")
            }
        }
        // Original priority and creation/modification/completion instants are
        // explicitly source evidence. A new local copy gets its own timestamps
        // in JS and its displayed three-level priority is an announced mapping.
        let task: [String: Any] = ["titel": title, "notiz": notes ?? "", "prio": (1...3).contains(priority) ? 1 : priority >= 7 ? 3 : 2,
            "erledigt": completed, "startDatum": startDay, "startZeit": startTime, "faellig": dueDay, "faelligZeit": dueTime,
            "icsRoundtrip": timeLines, "icsAnzeigeZeitzone": displayTimeZone, "erinnern": false,
            "individuelleErinnerungTage": 0, "vorlaufTage": 0, "erinnerungsMinute": 480]
        var notices = ["native-reminder-standalone-copy", "native-reminder-public-fields-only", "native-reminder-priority-grouped"]
        if created != nil || modified != nil || completedAt != nil { notices.append("native-reminder-source-timestamps") }
        if location?.isEmpty == false || url?.isEmpty == false { notices.append("native-reminder-extra-public-fields-in-source") }
        return (task, notices.sorted())
    }
}
