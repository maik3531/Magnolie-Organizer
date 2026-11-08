#if os(macOS)
import Foundation
import EventKit
import Contacts

/// Public-object conversion only. No store, permission request or account lookup.
public enum NativeSystemRecordReader {
    public enum ContactUnification: String { case unknown, nonUnifiedContainer }
    private static func validateText(_ title: String?, _ notes: String?) throws {
        guard (title?.utf8.count ?? 0) <= 65_536, (notes?.utf8.count ?? 0) <= 1_048_576 else { throw BetaError("Native text exceeds snapshot limits.") }
    }
    private static func string(_ value: String?) -> Any { value.map { $0 as Any } ?? NSNull() }
    private static func date(_ value: Date?) -> Any { value.map { $0.timeIntervalSince1970 as Any } ?? NSNull() }
    private static func weekday(_ value: Int) -> Int { value }
    private static func weekday(_ value: EKWeekday) -> Int { value.rawValue }
    private static func rules(_ values: [EKRecurrenceRule]?) -> [[String: Any]] {
        (values ?? []).map { rule in
            var result: [String: Any] = ["frequency": rule.frequency.rawValue, "interval": rule.interval,
                "firstDayOfWeek": weekday(rule.firstDayOfTheWeek),
                "daysOfWeek": (rule.daysOfTheWeek ?? []).map { ["weekday": $0.dayOfTheWeek.rawValue, "weekNumber": $0.weekNumber] },
                "daysOfMonth": rule.daysOfTheMonth ?? [], "monthsOfYear": rule.monthsOfTheYear ?? [],
                "weeksOfYear": rule.weeksOfTheYear ?? [], "daysOfYear": rule.daysOfTheYear ?? [], "setPositions": rule.setPositions ?? []]
            let identifier: String? = rule.calendarIdentifier
            if let identifier { result["calendarIdentifier"] = identifier }
            if let end = rule.recurrenceEnd { result["endDate"] = date(end.endDate); result["occurrenceCount"] = end.occurrenceCount }
            return result
        }
    }
    private static func alarms(_ values: [EKAlarm]?) -> [[String: Any]] {
        (values ?? []).map { alarm in
            var result: [String: Any] = ["absoluteDate": date(alarm.absoluteDate), "relativeOffset": alarm.relativeOffset,
                                       "type": alarm.type.rawValue, "proximity": alarm.proximity.rawValue]
            if let location = alarm.structuredLocation {
                var place: [String: Any] = ["title": location.title, "radius": location.radius]
                if let geo = location.geoLocation { place["latitude"] = geo.coordinate.latitude; place["longitude"] = geo.coordinate.longitude }
                result["structuredLocation"] = place
            }
            return result
        }
    }
    public static func eventFields(_ event: EKEvent) -> [String: Any] {
        var incomplete = ["provider-opaque-fields"]
        if !(event.attendees ?? []).isEmpty || event.organizer != nil { incomplete.append("participant-details-name-url-role-type-status-current-user") }
        if !(event.alarms ?? []).isEmpty { incomplete.append("alarm-action-sound-email-procedure-details") }
        return ["metadataIncomplete": incomplete, "title": string(event.title), "notes": string(event.notes), "location": string(event.location),
         "start": date(event.startDate), "end": date(event.endDate), "allDay": event.isAllDay,
         "externalIdentifier": string(event.calendarItemExternalIdentifier),
         "timeZone": string(event.timeZone?.identifier), "url": string(event.url?.absoluteString),
         "recurring": event.hasRecurrenceRules, "isDetached": event.isDetached,
         "occurrenceDate": date(event.occurrenceDate), "modified": date(event.lastModifiedDate),
         "created": date(event.creationDate), "status": event.status.rawValue, "availability": event.availability.rawValue,
         "recurrenceRules": rules(event.recurrenceRules), "alarms": alarms(event.alarms),
         "attendeeCount": event.attendees?.count ?? 0, "hasOrganizer": event.organizer != nil]
    }
    public static func event(_ event: EKEvent, source: SystemSourceSnapshot.Source) throws -> SystemSourceSnapshot.Record {
        guard source.kind == .events else { throw BetaError("Expected an event source.") }
        try validateText(event.title, event.notes)
        guard (event.recurrenceRules?.count ?? 0) <= 64, (event.alarms?.count ?? 0) <= 64 else { throw BetaError("Native event metadata exceeds limits.") }
        var unsupported: [String] = []
        if event.title?.isEmpty != false { unsupported.append("native-event-title-unavailable") }
        if event.startDate == nil || event.endDate == nil { unsupported.append("native-event-dates-unavailable") }
        if event.hasRecurrenceRules || event.isDetached { unsupported.append("native-series-projection-not-lossless") }
        if !(event.alarms ?? []).isEmpty { unsupported.append("native-alarms-projection-not-lossless") }
        if !(event.attendees ?? []).isEmpty || event.organizer != nil { unsupported.append("native-participants-projection-not-lossless") }
        return try .init(source: source, identifier: event.eventIdentifier, occurrenceDate: event.occurrenceDate,
                         fields: eventFields(event), unsupported: unsupported)
    }
    public static func reminderFields(_ reminder: EKReminder) -> [String: Any] {
        var incomplete = ["native-reminder-hierarchy", "provider-opaque-fields"]
        if !(reminder.alarms ?? []).isEmpty { incomplete.append("alarm-action-sound-email-procedure-details") }
        return ["metadataIncomplete": incomplete, "title": string(reminder.title), "notes": string(reminder.notes), "priority": reminder.priority,
         "completed": reminder.isCompleted, "completionDate": date(reminder.completionDate),
         "externalIdentifier": string(reminder.calendarItemExternalIdentifier),
         "startComponents": SystemDateComponents.fields(reminder.startDateComponents) as Any? ?? NSNull(),
         "dueComponents": SystemDateComponents.fields(reminder.dueDateComponents) as Any? ?? NSNull(),
         "url": string(reminder.url?.absoluteString), "created": date(reminder.creationDate), "modified": date(reminder.lastModifiedDate),
         "recurrenceRules": rules(reminder.recurrenceRules), "alarms": alarms(reminder.alarms),
         "hierarchyAvailable": false]
    }
    public static func reminder(_ reminder: EKReminder, source: SystemSourceSnapshot.Source) throws -> SystemSourceSnapshot.Record {
        guard source.kind == .reminders else { throw BetaError("Expected a reminders source.") }
        try validateText(reminder.title, reminder.notes)
        guard (reminder.recurrenceRules?.count ?? 0) <= 64, (reminder.alarms?.count ?? 0) <= 64 else { throw BetaError("Native reminder metadata exceeds limits.") }
        let identifier: String? = reminder.calendarItemIdentifier
        return try .init(source: source, identifier: identifier?.isEmpty == false ? identifier : nil, fields: reminderFields(reminder),
                         unsupported: ["native-reminder-hierarchy-not-exposed"])
    }
    public static func contact(_ contact: CNContact, source: SystemSourceSnapshot.Source, unification: ContactUnification = .unknown) throws -> SystemSourceSnapshot.Record {
        guard source.kind == .contacts else { throw BetaError("Expected a contacts source.") }
        var fields: [String: Any] = ["unification": unification.rawValue, "metadataIncomplete": ["provider-opaque-fields"]]
        var unsupported = ["native-contact-mapping-not-implemented", "provider-opaque-fields-not-exposed"]
        do {
            let data = try CNContactVCardSerialization.data(with: [contact])
            guard data.count <= 1_048_576, let vcard = String(data: data, encoding: .utf8) else { throw BetaError("Native vCard size/encoding limit.") }
            fields["vcard"] = vcard
        } catch let error as BetaError { throw error }
        catch { fields["vcard"] = NSNull(); unsupported.append("public-vcard-serialization-failed") }
        if unification == .unknown { unsupported.append("contact-unification-unknown") }
        if contact.isKeyAvailable(CNContactBirthdayKey) { fields["birthday"] = SystemDateComponents.fields(contact.birthday) as Any? ?? NSNull() }
        else { unsupported.append("birthday-key-unavailable") }
        if contact.isKeyAvailable(CNContactNonGregorianBirthdayKey) { fields["nonGregorianBirthday"] = SystemDateComponents.fields(contact.nonGregorianBirthday) as Any? ?? NSNull() }
        else { unsupported.append("non-gregorian-birthday-key-unavailable") }
        if contact.isKeyAvailable(CNContactDatesKey) {
            fields["dates"] = contact.dates.map { entry -> [String: Any] in
                ["identifier": entry.identifier, "label": string(entry.label),
                 "components": SystemDateComponents.fields(entry.value as DateComponents) as Any? ?? NSNull()]
            }
        } else { unsupported.append("contact-dates-key-unavailable") }
        return try .init(source: source, identifier: contact.identifier.isEmpty ? nil : contact.identifier,
                         fields: fields, unsupported: unsupported)
    }
}
#endif
