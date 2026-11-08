import Foundation
import EventKit
import Contacts
import BetaCore

/// Async UI-facing facade. No EK/CN object crosses this boundary.
/// Store creation and every store access occur on one private serial queue.
final class SystemAccounts {
    private let queue = DispatchQueue(label: "io.gitlab.maik3531.magnolie.system-sources", qos: .utility)
    private var store: SystemAccountStore?

    private func worker() -> SystemAccountStore {
        dispatchPrecondition(condition: .onQueue(queue))
        if let store { return store }
        let created = SystemAccountStore(queue: queue); store = created; return created
    }
    private func perform<T>(_ action: @escaping (SystemAccountStore, SystemSourceReadControl) throws -> T) async throws -> T {
        let control = SystemSourceReadControl()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    do { try control.check(); continuation.resume(returning: try action(self.worker(), control)) }
                    catch { continuation.resume(throwing: error) }
                }
            }
        }, onCancel: { control.cancel() })
    }
    func authorization(_ kind: SystemSourcePolicy.Kind) async throws -> String {
        try await perform { store, _ in store.authorization(kind) }
    }
    func status(requestID: String? = nil) async throws -> [String: Any] {
        try await perform { store, control in
            let result = store.status(requestID: requestID); try control.check(); return result
        }
    }
    /// Called only from an explicit user action, never from status/automatic refresh.
    func requestAccess(_ kind: SystemSourcePolicy.Kind) async throws {
        try Task.checkCancellation()
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async { self.worker().requestAccess(kind) { continuation.resume(with: $0) } }
        }
        try Task.checkCancellation()
    }
    func readEvents(sourceUID: String, start: Date, end: Date) async throws -> [[String: Any]] {
        try await perform { try $0.readEvents(sourceUID: sourceUID, start: start, end: end, control: $1) }
    }
    func readContacts(sourceUID: String) async throws -> [[String: Any]] {
        try await perform { try $0.readContacts(sourceUID: sourceUID, control: $1) }
    }
    func readReminders(sourceUID: String) async throws -> [[String: Any]] {
        let control = SystemSourceReadControl()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    self.worker().readReminders(sourceUID: sourceUID, control: control) {
                        continuation.resume(with: $0)
                    }
                }
            }
        }, onCancel: { control.cancel() })
    }
    func updateEventText(sourceUID: String, identifier: String, expectedRevision: String,
                         title: String, notes: String, location: String) async throws -> [String: Any] {
        try await perform { store, control in
            try store.updateEventText(sourceUID: sourceUID, identifier: identifier,
                expectedRevision: expectedRevision, title: title, notes: notes, location: location, control: control)
        }
    }
    func updateReminderText(sourceUID: String, identifier: String, expectedRevision: String,
                            title: String, notes: String) async throws -> [String: Any] {
        try await perform { store, control in
            try store.updateReminderText(sourceUID: sourceUID, identifier: identifier,
                expectedRevision: expectedRevision, title: title, notes: notes, control: control)
        }
    }
}

/// Private queue-confined native objects; DTO conversion happens before returning.
private final class SystemAccountStore {
    private let queue: DispatchQueue
    private let events = EKEventStore()
    private let contacts = CNContactStore()
    private let maximumItems = 10_000
    init(queue: DispatchQueue) { self.queue = queue }

    func authorization(_ kind: SystemSourcePolicy.Kind) -> String {
        if kind == .contacts {
            switch CNContactStore.authorizationStatus(for: .contacts) {
            case .authorized: return "authorized"
            case .notDetermined: return "not_determined"
            case .denied: return "denied"
            case .restricted: return "restricted"
            @unknown default: return "restricted"
            }
        }
        let status = EKEventStore.authorizationStatus(for: kind == .events ? .event : .reminder)
        if #available(macOS 14.0, *) {
            if status == .fullAccess { return "authorized" }
            if status == .writeOnly { return "write_only" }
        }
        switch status {
        case .authorized: return "authorized"
        case .notDetermined: return "not_determined"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "restricted"
        }
    }

    func requestAccess(_ kind: SystemSourcePolicy.Kind, completion: @escaping (Result<Void, Error>) -> Void) {
        if authorization(kind) == "authorized" { completion(.success(())); return }
        let callback: (Bool, Error?) -> Void = { granted, error in
            self.queue.async {
                if let error { completion(.failure(error)); return }
                guard granted, self.authorization(kind) == "authorized" else {
                    completion(.failure(BetaError("macOS did not grant full access. Enable it in System Settings → Privacy & Security."))); return
                }
                completion(.success(()))
            }
        }
        if kind == .contacts { contacts.requestAccess(for: .contacts, completionHandler: callback) }
        else if #available(macOS 14.0, *) {
            if kind == .events { events.requestFullAccessToEvents(completion: callback) }
            else { events.requestFullAccessToReminders(completion: callback) }
        } else { events.requestAccess(to: kind == .events ? .event : .reminder, completion: callback) }
    }

    private func requireAccess(_ kind: SystemSourcePolicy.Kind) throws {
        try SystemSourcePolicy.requireAccess(authorization(kind), kind: kind)
    }

    /// Existing shared App.edsStatus contract, with honest per-service capabilities.
    func status(requestID: String? = nil) -> [String: Any] {
        var calendars: [[String: Any]] = []
        var books: [[String: Any]] = []
        var failures: [String] = []
        for kind in [SystemSourcePolicy.Kind.events, .reminders] where authorization(kind) == "authorized" {
            calendars += events.calendars(for: kind == .events ? .event : .reminder).map {
                ["uid": SystemSourcePolicy.uid(kind, $0.calendarIdentifier),
                 "name": $0.title + " (" + $0.source.title + ")", "quelle": "macos",
                 "art": kind.rawValue, "supportsVtodo": kind == .reminders,
                 "supportsVevent": kind == .events, "readOnly": !$0.allowsContentModifications]
            }
        }
        if authorization(.contacts) == "authorized" {
            do {
                books = try contacts.containers(matching: nil).map {
                    ["uid": SystemSourcePolicy.uid(.contacts, $0.identifier), "name": $0.name,
                     "quelle": "macos", "art": "contacts", "readOnly": true]
                }
            } catch { failures.append("macOS address books could not be read.") }
        }
        let permissions = Dictionary(uniqueKeysWithValues: SystemSourcePolicy.Kind.allCases.map { ($0.rawValue, authorization($0)) })
        for kind in SystemSourcePolicy.Kind.allCases where authorization(kind) != "authorized" {
            failures.append("macOS \(kind.rawValue): \(authorization(kind)).")
        }
        var result: [String: Any] = ["macos": true, "verfuegbar": !calendars.isEmpty || !books.isEmpty,
            "buchOk": authorization(.contacts) == "authorized", "kalender": calendars,
            "adressbuecher": books, "alleKalender": calendars, "alleAdressbuecher": books,
            "fehler": failures.joined(separator: " "), "permissions": permissions,
            "systemAccountSyncImplemented": false]
        if let requestID { result["requestId"] = requestID }
        return result
    }

    private func calendar(_ uid: String, kind: SystemSourcePolicy.Kind, writing: Bool = false) throws -> EKCalendar {
        try requireAccess(kind)
        let identifier = try SystemSourcePolicy.identifier(uid, kind: kind)
        guard let calendar = events.calendars(for: kind == .events ? .event : .reminder)
            .first(where: { $0.calendarIdentifier == identifier }) else {
            throw BetaError("The selected macOS calendar no longer exists.")
        }
        if writing && !calendar.allowsContentModifications { throw BetaError("The selected macOS calendar is read-only.") }
        return calendar
    }

    /// Native snapshot, not lossy conversion into Organizer recurrence fields.
    /// EventKit expands the selected date window; recurring snapshots are read-only.
    func readEvents(sourceUID: String, start: Date, end: Date, control: SystemSourceReadControl) throws -> [[String: Any]] {
        try SystemSourcePolicy.requireWindow(start: start, end: end)
        let source = try calendar(sourceUID, kind: .events)
        let found = events.events(matching: events.predicateForEvents(withStart: start, end: end, calendars: [source]))
        guard found.count <= maximumItems else { throw BetaError("Too many macOS events; select a smaller date window.") }
        try control.check()
        return try found.map { try control.check(); return try eventSnapshot($0, sourceUID: sourceUID) }
    }

    private func eventSnapshot(_ event: EKEvent, sourceUID: String) throws -> [String: Any] {
        var value: [String: Any] = ["sourceUid": sourceUID, "identifier": event.eventIdentifier ?? "",
            "title": event.title ?? "", "notes": event.notes ?? "", "location": event.location ?? "",
            "start": event.startDate.timeIntervalSince1970, "end": event.endDate.timeIntervalSince1970,
            "allDay": event.isAllDay, "timeZone": event.timeZone?.identifier ?? "",
            "recurring": event.hasRecurrenceRules || event.isDetached,
            "modified": event.lastModifiedDate?.timeIntervalSince1970 ?? 0]
        value["revision"] = try SystemSourcePolicy.revision(value)
        return value
    }

    /// Patch only supported text fields, preserving alarms, attendees and other native fields.
    /// Recurrence/occurrence edits wait for the complete series/exception codec.
    func updateEventText(sourceUID: String, identifier: String, expectedRevision: String,
                         title: String, notes: String, location: String, control: SystemSourceReadControl) throws -> [String: Any] {
        let source = try calendar(sourceUID, kind: .events, writing: true)
        guard let event = events.event(withIdentifier: identifier), event.calendar.calendarIdentifier == source.calendarIdentifier,
              !event.hasRecurrenceRules, !event.isDetached else {
            throw BetaError("The event is missing, belongs to another source, or requires recurrence-aware editing.")
        }
        let snapshot = try eventSnapshot(event, sourceUID: sourceUID)
        try SystemSourcePolicy.requireRevision(expectedRevision, actual: snapshot["revision"] as? String ?? "")
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              title.utf8.count <= 65536, notes.utf8.count <= 1_048_576, location.utf8.count <= 65536 else {
            throw BetaError("Invalid macOS event text.")
        }
        try control.check()
        event.title = title; event.notes = notes; event.location = location
        try events.save(event, span: .thisEvent, commit: true)
        return try eventSnapshot(event, sourceUID: sourceUID)
    }

    private func reminderSnapshot(_ reminder: EKReminder, sourceUID: String) throws -> [String: Any] {
        let dateText: (DateComponents?) -> String = { components in
            guard let components else { return "" }
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = components.timeZone ?? TimeZone.current
            return calendar.date(from: components).map { ISO8601DateFormatter().string(from: $0) } ?? ""
        }
        var value: [String: Any] = ["sourceUid": sourceUID,
            "identifier": reminder.calendarItemIdentifier, "title": reminder.title ?? "",
            "notes": reminder.notes ?? "", "completed": reminder.isCompleted,
            "priority": reminder.priority, "due": dateText(reminder.dueDateComponents),
            "start": dateText(reminder.startDateComponents), "recurring": reminder.hasRecurrenceRules,
            "modified": reminder.lastModifiedDate?.timeIntervalSince1970 ?? 0]
        value["revision"] = try SystemSourcePolicy.revision(value)
        return value
    }

    private final class ReminderRead {
        var completion: ((Result<[[String: Any]], Error>) -> Void)?
        init(_ completion: @escaping (Result<[[String: Any]], Error>) -> Void) { self.completion = completion }
        func finish(_ result: Result<[[String: Any]], Error>) {
            let pending = completion; completion = nil; pending?(result)
        }
    }

    func readReminders(sourceUID: String, control: SystemSourceReadControl,
                       completion: @escaping (Result<[[String: Any]], Error>) -> Void) {
        do {
            try control.check()
            let source = try calendar(sourceUID, kind: .reminders)
            let read = ReminderRead(completion)
            let token = events.fetchReminders(matching: events.predicateForReminders(in: [source])) { found in
                self.queue.async {
                    guard read.completion != nil else { return }
                    do {
                        try control.check(); try self.requireAccess(.reminders)
                        guard let found, found.count <= self.maximumItems else {
                            throw BetaError("macOS reminders could not be read within the item limit.")
                        }
                        let result = try found.map { reminder in
                            try control.check(); return try self.reminderSnapshot(reminder, sourceUID: sourceUID)
                        }
                        read.finish(.success(result))
                    } catch { read.finish(.failure(error)) }
                }
            }
            // Short polls make cancellation responsive without blocking the queue.
            func checkPending() {
                self.queue.asyncAfter(deadline: .now() + .milliseconds(100)) {
                    guard read.completion != nil else { return }
                    do { try control.check(); checkPending() }
                    catch { self.events.cancelFetchRequest(token); read.finish(.failure(error)) }
                }
            }
            checkPending()
        } catch { completion(.failure(error)) }
    }

    func updateReminderText(sourceUID: String, identifier: String, expectedRevision: String,
                            title: String, notes: String, control: SystemSourceReadControl) throws -> [String: Any] {
        let source = try calendar(sourceUID, kind: .reminders, writing: true)
        guard let reminder = events.calendarItem(withIdentifier: identifier) as? EKReminder,
              reminder.calendar.calendarIdentifier == source.calendarIdentifier,
              !reminder.hasRecurrenceRules else {
            throw BetaError("The reminder is missing, belongs to another source, or requires recurrence-aware editing.")
        }
        let snapshot = try reminderSnapshot(reminder, sourceUID: sourceUID)
        try SystemSourcePolicy.requireRevision(expectedRevision, actual: snapshot["revision"] as? String ?? "")
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              title.utf8.count <= 65536, notes.utf8.count <= 1_048_576 else {
            throw BetaError("Invalid macOS reminder text.")
        }
        try control.check()
        reminder.title = title; reminder.notes = notes
        try events.save(reminder, commit: true)
        return try reminderSnapshot(reminder, sourceUID: sourceUID)
    }

    /// Contact data remains a full standard vCard, including multi-valued fields.
    /// Containers expose no reliable public per-account write capability, so discovery
    /// conservatively reports contacts read-only until transaction integration exists.
    func readContacts(sourceUID: String, control: SystemSourceReadControl) throws -> [[String: Any]] {
        try requireAccess(.contacts)
        let identifier = try SystemSourcePolicy.identifier(sourceUID, kind: .contacts)
        guard try contacts.containers(matching: nil).contains(where: { $0.identifier == identifier }) else {
            throw BetaError("The selected macOS address book no longer exists.")
        }
        let request = CNContactFetchRequest(keysToFetch: [CNContactVCardSerialization.descriptorForRequiredKeys()])
        request.predicate = CNContact.predicateForContactsInContainer(withIdentifier: identifier)
        request.unifyResults = false
        var result: [[String: Any]] = []
        var overflow = false
        var totalBytes = 0
        var readError: Error?
        try contacts.enumerateContacts(with: request) { contact, stop in
            do { try control.check() } catch { readError = error; stop.pointee = true; return }
            if result.count >= self.maximumItems { overflow = true; stop.pointee = true; return }
            // Retain every field supported by Apple's vCard serializer instead of
            // flattening phones/emails/addresses into a single Organizer value.
            if let data = try? CNContactVCardSerialization.data(with: [contact]),
               data.count <= 1_048_576, totalBytes + data.count <= 16 * 1024 * 1024,
               let text = String(data: data, encoding: .utf8) {
                totalBytes += data.count
                result.append(["sourceUid": sourceUID, "identifier": contact.identifier, "vcard": text])
            } else { stop.pointee = true; overflow = true }
        }
        if let readError { throw readError }
        try control.check()
        guard !overflow else { throw BetaError("The macOS address book exceeds the read limit or contains an unreadable contact. Nothing was imported.") }
        return try result.map { value in
            try control.check()
            var snapshot = value; snapshot["revision"] = try SystemSourcePolicy.revision(value); return snapshot
        }
    }
}
