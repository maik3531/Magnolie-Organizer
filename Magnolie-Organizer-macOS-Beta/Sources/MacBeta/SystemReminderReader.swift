#if os(macOS)
import Foundation
import CoreFoundation
import EventKit
import BetaCore

/// Refs #777. Explicit selected Reminder copies, separate from full-source
/// snapshots. Store access and public-object conversion stay on the existing
/// SystemAccounts queue. This reader never assigns reminder fields or saves or
/// deletes a source object; refresh() only updates the fetched observations.
enum SystemReminderReader {
    struct Summary: Sendable {
        let identifier: String
        let title: String
        let completed: Bool
    }

    private static let maximumLists = 256
    private static let maximumMetadataRecords = 10_000
    private static let maximumScalarBytes = 65_536
    private static let maximumFeatures = 64
    private static let maximumRuleValues = 1000
    private static let incompleteMetadata = [
        "native-reminder-hierarchy", "native-reminder-attachments",
        "native-reminder-tags", "native-reminder-flags", "native-reminder-assignees",
        "native-reminder-rich-text", "provider-opaque-fields"
    ]

    static func sources(store: EKEventStore, queue: DispatchQueue,
                        control: SystemSourceReadControl,
                        requireAccess: () throws -> Void) throws -> [SystemReminderImport.Source] {
        dispatchPrecondition(condition: .onQueue(queue))
        try control.check(); try requireAccess()
        let calendars = store.calendars(for: .reminder)
        try control.check()
        guard calendars.count <= maximumLists else { throw failure("too many reminder lists") }
        var seen = Set<OpaqueUTF8Identity>(), budget = Budget()
        let result = try calendars.map { calendar in
            try control.check()
            let value = try source(calendar, control: control, budget: &budget)
            guard seen.insert(OpaqueUTF8Identity(value.calendarID)).inserted else {
                throw failure("reminder list identities are ambiguous")
            }
            return value
        }
        try control.check(); try requireAccess()
        return result
    }

    /// EventKit returns full EKReminder objects, with no keysToFetch equivalent.
    /// Only identity/list membership, title and completed metadata are inspected
    /// for this picker. The item limit is checked after the framework callback,
    /// not before its internal allocation.
    static func summaries(store: EKEventStore, queue: DispatchQueue,
                          source expected: SystemReminderImport.Source,
                          control: SystemSourceReadControl,
                          requireAccess: @escaping () throws -> Void,
                          completion: @escaping (Result<[Summary], Error>) -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        do {
            try control.check(); try requireAccess()
            let (calendar, current) = try currentSource(store, expected: expected, control: control)
            let pending = Pending<[Summary]>(completion)
            // The all-reminders predicate deliberately includes completed and
            // incomplete items in this one list, including items without dates.
            let token = store.fetchReminders(matching: store.predicateForReminders(in: [calendar])) { found in
                // The framework owns its callback queue. Do not inspect any EK
                // property there; convert to value DTOs only on the store queue.
                queue.async {
                    guard pending.completion != nil else { return }
                    do {
                        try control.check(); try requireAccess()
                        guard let found, found.count <= maximumMetadataRecords else {
                            throw failure("the reminder list could not be read within the metadata limit")
                        }
                        var rows: [Summary] = [], seen = Set<OpaqueUTF8Identity>(), budget = Budget()
                        for reminder in found {
                            try control.check()
                            guard reminder.refresh() else { throw failure("a listed reminder is no longer available") }
                            let identifier = try budget.identifier(reminder.calendarItemIdentifier)
                            guard seen.insert(OpaqueUTF8Identity(identifier)).inserted else {
                                throw failure("listed reminder identities are ambiguous")
                            }
                            try requireMembership(reminder, identifier: identifier, source: current, control: control)
                            // A missing title is shown as empty metadata; the
                            // selected raw record preserves nil for Core review.
                            let title = try budget.text(reminder.title ?? "", maximum: SystemReminderImport.maximumTitleBytes)
                            rows.append(Summary(identifier: identifier, title: title, completed: reminder.isCompleted))
                        }
                        _ = try currentSource(store, expected: current, control: control)
                        try control.check(); try requireAccess()
                        pending.finish(.success(rows))
                    } catch { pending.finish(.failure(error)) }
                }
            }
            func poll() {
                queue.asyncAfter(deadline: .now() + .milliseconds(100)) {
                    guard pending.completion != nil else { return }
                    do { try control.check(); poll() }
                    catch {
                        // Apple specifies that cancellation suppresses the
                        // original completion. Resolve our continuation once.
                        store.cancelFetchRequest(token)
                        pending.finish(.failure(error))
                    }
                }
            }
            poll()
        } catch { completion(.failure(error)) }
    }

    /// Resolve only the selected identifiers, then reread their memberships.
    /// The Host repeats this entire operation after review. These observations
    /// are not an atomic EventKit/server revision or a full-source snapshot.
    static func snapshot(store: EKEventStore, queue: DispatchQueue,
                         source expected: SystemReminderImport.Source, identifiers: [String],
                         control: SystemSourceReadControl,
                         requireAccess: () throws -> Void) throws -> SystemReminderImport.Snapshot {
        dispatchPrecondition(condition: .onQueue(queue))
        try control.check(); try requireAccess()
        let selected = try selectedIdentities(identifiers)
        let (_, current) = try currentSource(store, expected: expected, control: control)
        var records: [SystemReminderImport.Record] = [], seen = Set<OpaqueUTF8Identity>()
        var budget = Budget(), serializedBytes = 0
        for identifier in identifiers {
            try control.check(); try requireAccess()
            let reminder = try selectedReminder(store, identifier: identifier, source: current, control: control)
            let actual = try budget.identifier(reminder.calendarItemIdentifier), key = OpaqueUTF8Identity(actual)
            guard selected.contains(key), seen.insert(key).inserted else {
                throw failure("selected reminder identities are missing, duplicated or changed")
            }
            let record = try record(reminder, identifier: actual, control: control, budget: &budget)
            try requireMembership(reminder, identifier: actual, source: current, control: control)
            let bytes = try Document.encode(["identifier": actual, "fields": record.fields,
                                             "failure": record.failure.map { $0 as Any } ?? NSNull()]).utf8.count
            guard bytes <= SystemReminderImport.maximumBytes - serializedBytes else {
                throw failure("selected reminder data exceeds 16 MiB; select fewer reminders")
            }
            serializedBytes += bytes
            records.append(record)
        }
        guard seen == selected else { throw failure("a selected reminder is no longer available") }
        for identifier in identifiers {
            try control.check(); try requireAccess()
            _ = try selectedReminder(store, identifier: identifier, source: current, control: control)
        }
        let (_, finalSource) = try currentSource(store, expected: current, control: control)
        try control.check(); try requireAccess()
        return SystemReminderImport.Snapshot(source: finalSource, records: records)
    }

    /// Accessed only from the private queue, including polling and callbacks.
    private final class Pending<Value> {
        var completion: ((Result<Value, Error>) -> Void)?
        init(_ completion: @escaping (Result<Value, Error>) -> Void) { self.completion = completion }
        func finish(_ result: Result<Value, Error>) {
            let callback = completion; completion = nil; callback?(result)
        }
    }

    private static func selectedIdentities(_ identifiers: [String]) throws -> Set<OpaqueUTF8Identity> {
        guard !identifiers.isEmpty, identifiers.count <= SystemReminderImport.maximumRecords else {
            throw failure("select between 1 and 100 reminders")
        }
        var result = Set<OpaqueUTF8Identity>(), budget = Budget()
        for identifier in identifiers {
            _ = try budget.identifier(identifier)
            guard result.insert(OpaqueUTF8Identity(identifier)).inserted else { throw failure("duplicate selected reminder identity") }
        }
        return result
    }

    private static func source(_ calendar: EKCalendar, control: SystemSourceReadControl,
                               budget: inout Budget) throws -> SystemReminderImport.Source {
        try control.check()
        guard calendar.refresh(), calendar.allowedEntityTypes.contains(.reminder),
              let parent = calendar.source, parent.refresh() else {
            throw failure("a reminder list or its account is no longer available")
        }
        try control.check()
        let identifier = try budget.identifier(calendar.calendarIdentifier)
        let sourceUID = SystemSourcePolicy.uid(.reminders, identifier)
        guard same(try SystemSourcePolicy.identifier(sourceUID, kind: .reminders), identifier) else {
            throw failure("invalid reminder list identity")
        }
        let parentID = try budget.identifier(parent.sourceIdentifier)
        let parentUID = try budget.text("macos-account:" + Data(parentID.utf8).base64EncodedString(), maximum: 8192)
        return SystemReminderImport.Source(sourceUID: sourceUID, calendarID: identifier,
            title: try budget.text(calendar.title, maximum: SystemReminderImport.maximumTitleBytes),
            parentUID: parentUID, parentTitle: try budget.text(parent.title, maximum: SystemReminderImport.maximumTitleBytes),
            parentType: "source:\(parent.sourceType.rawValue)", nativeType: "calendar:\(calendar.type.rawValue)",
            readOnly: !calendar.allowsContentModifications, permission: "authorized")
    }

    private static func currentSource(_ store: EKEventStore, expected: SystemReminderImport.Source,
                                      control: SystemSourceReadControl) throws -> (EKCalendar, SystemReminderImport.Source) {
        try control.check()
        guard same(try SystemSourcePolicy.identifier(expected.sourceUID, kind: .reminders), expected.calendarID) else {
            throw failure("invalid selected reminder list identity")
        }
        let calendars = store.calendars(for: .reminder)
        guard calendars.count <= maximumLists else { throw failure("too many reminder lists") }
        var matches: [EKCalendar] = [], seen = Set<OpaqueUTF8Identity>(), budget = Budget()
        for calendar in calendars {
            try control.check()
            let identifier = try budget.identifier(calendar.calendarIdentifier)
            guard seen.insert(OpaqueUTF8Identity(identifier)).inserted else { throw failure("reminder list identities are ambiguous") }
            if same(identifier, expected.calendarID) { matches.append(calendar) }
        }
        guard matches.count == 1 else { throw failure("selected reminder list is missing or ambiguous") }
        let current = try source(matches[0], control: control, budget: &budget)
        guard same(current.sourceUID, expected.sourceUID), same(current.calendarID, expected.calendarID),
              same(current.title, expected.title), same(current.parentUID, expected.parentUID),
              same(current.parentTitle, expected.parentTitle), same(current.parentType, expected.parentType),
              same(current.nativeType, expected.nativeType), current.readOnly == expected.readOnly,
              same(current.permission, expected.permission) else {
            throw failure("the selected reminder list or account changed; select it again")
        }
        return (matches[0], current)
    }

    private static func selectedReminder(_ store: EKEventStore, identifier: String,
                                         source: SystemReminderImport.Source,
                                         control: SystemSourceReadControl) throws -> EKReminder {
        try control.check()
        guard let reminder = store.calendarItem(withIdentifier: identifier) as? EKReminder,
              reminder.refresh() else { throw failure("a selected reminder is no longer available") }
        try requireMembership(reminder, identifier: identifier, source: source, control: control)
        return reminder
    }

    private static func requireMembership(_ reminder: EKReminder, identifier: String,
                                          source: SystemReminderImport.Source,
                                          control: SystemSourceReadControl) throws {
        try control.check()
        guard same(reminder.calendarItemIdentifier, identifier), let calendar = reminder.calendar,
              same(calendar.calendarIdentifier, source.calendarID), let parent = calendar.source else {
            throw failure("a selected reminder moved or no longer belongs to this list and account")
        }
        let parentID = parent.sourceIdentifier
        guard !parentID.isEmpty, parentID.utf8.count <= SystemReminderImport.maximumIdentifierBytes,
              same("macos-account:" + Data(parentID.utf8).base64EncodedString(), source.parentUID) else {
            throw failure("a selected reminder moved or no longer belongs to this list and account")
        }
    }

    private static func record(_ reminder: EKReminder, identifier: String,
                               control: SystemSourceReadControl, budget: inout Budget) throws -> SystemReminderImport.Record {
        try control.check()
        let hasAlarms = reminder.hasAlarms, hasRules = reminder.hasRecurrenceRules
        let nativeAlarms = reminder.alarms, nativeRules = reminder.recurrenceRules
        let copiedAlarms = try alarms(nativeAlarms, control: control, budget: &budget)
        let copiedRules = try rules(nativeRules, control: control, budget: &budget)
        var incomplete = incompleteMetadata
        if !copiedAlarms.isEmpty { incomplete.append("alarm-procedure-url-not-exposed") }
        let fields: [String: Any] = [
            "metadataIncomplete": incomplete, "hierarchyAvailable": false,
            "title": try budget.optionalText(reminder.title, maximum: SystemReminderImport.maximumTitleBytes),
            "notes": try budget.optionalText(reminder.notes, maximum: SystemReminderImport.maximumNoteBytes),
            "hasNotes": reminder.hasNotes, "location": try budget.optionalText(reminder.location),
            "url": try budget.optionalText(reminder.url?.absoluteString),
            "externalIdentifier": try budget.optionalText(reminder.calendarItemExternalIdentifier, maximum: SystemReminderImport.maximumIdentifierBytes),
            "itemTimeZone": try budget.optionalText(reminder.timeZone?.identifier),
            "created": try budget.date(reminder.creationDate), "modified": try budget.date(reminder.lastModifiedDate),
            "completed": reminder.isCompleted, "completionDate": try budget.date(reminder.completionDate),
            "priority": reminder.priority,
            "startComponents": try components(reminder.startDateComponents, budget: &budget),
            "dueComponents": try components(reminder.dueDateComponents, budget: &budget),
            "hasAlarms": hasAlarms, "alarms": copiedAlarms,
            "hasRecurrenceRules": hasRules, "recurrenceRules": copiedRules
        ]
        try control.check()
        let inconsistent = hasAlarms != !copiedAlarms.isEmpty || hasRules != !copiedRules.isEmpty
        return SystemReminderImport.Record(identifier: identifier, fields: fields,
            failure: inconsistent ? "native-reminder-feature-state-inconsistent" : nil)
    }

    private static func components(_ value: DateComponents?, budget: inout Budget) throws -> Any {
        guard let fields = SystemDateComponents.fields(value) else { return NSNull() }
        // In particular, due.timeZone is independent of start/item.timeZone.
        // A missing zone is floating, and absent clock components stay absent.
        try budget.charge(Document.encode(fields).utf8.count)
        return fields
    }

    private static func alarms(_ values: [EKAlarm]?, control: SystemSourceReadControl,
                               budget: inout Budget) throws -> [[String: Any]] {
        guard (values?.count ?? 0) <= maximumFeatures else { throw failure("too many reminder alarms") }
        var result: [[String: Any]] = []
        for alarm in values ?? [] {
            try control.check()
            var row: [String: Any] = ["absoluteDate": try budget.date(alarm.absoluteDate),
                "relativeOffset": try budget.number(alarm.relativeOffset), "type": alarm.type.rawValue,
                "proximity": alarm.proximity.rawValue, "soundName": try budget.optionalText(alarm.soundName),
                "emailAddress": try budget.optionalText(alarm.emailAddress)]
            if let location = alarm.structuredLocation {
                var place: [String: Any] = ["title": try budget.optionalText(location.title),
                                           "radius": try budget.number(location.radius)]
                if let geo = location.geoLocation {
                    place["latitude"] = try budget.number(geo.coordinate.latitude)
                    place["longitude"] = try budget.number(geo.coordinate.longitude)
                }
                row["structuredLocation"] = place
            }
            // EKAlarm.url is unavailable on supported macOS versions. Do not
            // use KVC, invoke a procedure, or claim complete alarm action data.
            result.append(row)
        }
        return result
    }

    private static func rules(_ values: [EKRecurrenceRule]?, control: SystemSourceReadControl,
                              budget: inout Budget) throws -> [[String: Any]] {
        guard (values?.count ?? 0) <= maximumFeatures else { throw failure("too many reminder recurrence rules") }
        var result: [[String: Any]] = []
        for rule in values ?? [] {
            try control.check()
            let weekdays = rule.daysOfTheWeek ?? []
            guard weekdays.count <= maximumRuleValues else { throw failure("a recurrence rule exceeds the value limit") }
            let days: [[String: Any]] = try weekdays.map { day in
                try control.check(); try budget.charge(32)
                return ["weekday": day.dayOfTheWeek.rawValue, "weekNumber": day.weekNumber]
            }
            var row: [String: Any] = ["frequency": rule.frequency.rawValue, "interval": rule.interval,
                "firstDayOfWeek": weekday(rule.firstDayOfTheWeek), "daysOfWeek": days,
                "daysOfMonth": try numbers(rule.daysOfTheMonth, budget: &budget),
                "monthsOfYear": try numbers(rule.monthsOfTheYear, budget: &budget),
                "weeksOfYear": try numbers(rule.weeksOfTheYear, budget: &budget),
                "daysOfYear": try numbers(rule.daysOfTheYear, budget: &budget),
                "setPositions": try numbers(rule.setPositions, budget: &budget)]
            let calendarID: String? = rule.calendarIdentifier
            if let calendarID { row["calendarIdentifier"] = try budget.text(calendarID) }
            if let end = rule.recurrenceEnd {
                row["endDate"] = try budget.date(end.endDate)
                row["occurrenceCount"] = end.occurrenceCount
            }
            result.append(row)
        }
        return result
    }

    private static func weekday(_ value: Int) -> Int { value }
    private static func weekday(_ value: EKWeekday) -> Int { value.rawValue }
    private static func numbers(_ values: [NSNumber]?, budget: inout Budget) throws -> [Int] {
        guard (values?.count ?? 0) <= maximumRuleValues else { throw failure("a recurrence rule exceeds the value limit") }
        return try (values ?? []).map { value in
            let number = value.doubleValue
            guard CFGetTypeID(value) != CFBooleanGetTypeID(), number.isFinite,
                  number.rounded(.towardZero) == number, abs(number) <= 9_007_199_254_740_991 else {
                throw failure("a recurrence rule contains an invalid number")
            }
            try budget.charge(32)
            return value.intValue
        }
    }

    private struct Budget {
        var bytes = 0
        mutating func charge(_ count: Int) throws {
            guard count >= 0, count <= SystemReminderImport.maximumBytes - bytes else {
                throw SystemReminderReader.failure("selected reminder data exceeds 16 MiB; select fewer reminders")
            }
            bytes += count
        }
        mutating func text(_ value: String, maximum: Int = SystemReminderReader.maximumScalarBytes) throws -> String {
            let count = value.utf8.count
            guard count <= maximum else { throw SystemReminderReader.failure("a reminder field exceeds its read limit") }
            try charge(count)
            return value
        }
        mutating func optionalText(_ value: String?, maximum: Int = SystemReminderReader.maximumScalarBytes) throws -> Any {
            guard let value else { return NSNull() }
            return try text(value, maximum: maximum)
        }
        mutating func identifier(_ value: String) throws -> String {
            guard !value.isEmpty else { throw SystemReminderReader.failure("a native identity is unavailable") }
            return try text(value, maximum: SystemReminderImport.maximumIdentifierBytes)
        }
        mutating func number(_ value: Double) throws -> Double {
            guard value.isFinite else { throw SystemReminderReader.failure("a native numeric field is invalid") }
            try charge(32)
            return value
        }
        mutating func date(_ value: Date?) throws -> Any {
            guard let value else { return NSNull() }
            return try number(value.timeIntervalSince1970)
        }
    }
    private static func same(_ left: String, _ right: String) -> Bool { left.utf8.elementsEqual(right.utf8) }
    private static func failure(_ text: String) -> BetaError { BetaError("macOS reminder copy: " + text + ".") }
}
#endif
