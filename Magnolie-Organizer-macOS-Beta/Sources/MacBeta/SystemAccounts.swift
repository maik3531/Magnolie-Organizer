import Foundation
import EventKit
import Contacts
import BetaCore

/// Async UI-facing facade. No EK/CN object crosses this boundary.
/// Store creation and every store access occur on one private serial queue.
final class SystemAccounts {
    private let queue = DispatchQueue(label: "io.gitlab.maik3531.magnolie.system-sources", qos: .utility)
    private var store: SystemAccountStore?
    private let syncWriteLock = NSLock()
    private var syncWrites = Set<String>()

    private final class SyncResult<Value> {
        private let lock = NSLock()
        private var continuation: CheckedContinuation<Value, Error>?
        init(_ value: CheckedContinuation<Value, Error>) { continuation = value }
        @discardableResult func finish(_ value: Result<Value, Error>) -> Bool {
            lock.lock(); let pending = continuation; continuation = nil; lock.unlock()
            pending?.resume(with: value); return pending != nil
        }
    }
    /// Unlike the legacy copy facade, the synchronization continuation has its
    /// own deadline queue. This bounds the caller, not a blocking Apple API.
    /// A late write remains protected by the native gate and the host journal.
    private func performSyncAsync<T>(onNativeFinish: @escaping () -> Void = {},
        _ action: @escaping (SystemAccountStore, SystemSourceReadControl, @escaping (Result<T, Error>) -> Void) -> Void) async throws -> T {
        let control = SystemSourceReadControl(timeout: 20)
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                let pending = SyncResult(continuation)
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 20) {
                    // A timeout says nothing about whether an entered save has
                    // committed. Only the native callback releases its gate.
                    if pending.finish(.failure(BetaError("The native synchronization operation exceeded 20 seconds. A started write may still finish; keep the recovery journal."))) {
                        control.cancel()
                    }
                }
                queue.async {
                    do {
                        try control.check()
                        action(self.worker(), control) { value in onNativeFinish(); pending.finish(value) }
                    } catch { onNativeFinish(); pending.finish(.failure(error)) }
                }
            }
        }, onCancel: { control.cancel() })
    }
    private func performSync<T>(onNativeFinish: @escaping () -> Void = {},
        _ action: @escaping (SystemAccountStore, SystemSourceReadControl) throws -> T) async throws -> T {
        try await performSyncAsync(onNativeFinish: onNativeFinish) { store, control, completion in
            do { completion(.success(try action(store, control))) } catch { completion(.failure(error)) }
        }
    }
    private func beginSyncWrite(_ fingerprint: String) -> Bool {
        syncWriteLock.lock(); defer { syncWriteLock.unlock() }; return syncWrites.insert(fingerprint).inserted
    }
    private func endSyncWrite(_ fingerprint: String) {
        syncWriteLock.lock(); syncWrites.remove(fingerprint); syncWriteLock.unlock()
    }

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
    /// Explicit selected-contact copy APIs. The older whole-source readers keep
    /// their original contracts; only value DTOs cross the private store queue.
    func contactCopySources() async throws -> [SystemContactImport.Source] {
        try Task.checkCancellation()
        let result = try await perform { try $0.contactCopySources(control: $1) }
        try Task.checkCancellation()
        return result
    }
    func contactCopySummaries(source: SystemContactImport.Source) async throws -> [SystemContactReader.Summary] {
        try Task.checkCancellation()
        let result = try await perform { try $0.contactCopySummaries(source: source, control: $1) }
        try Task.checkCancellation()
        return result
    }
    func contactCopySnapshot(source: SystemContactImport.Source, identifiers: [String]) async throws -> SystemContactImport.Snapshot {
        try Task.checkCancellation()
        let result = try await perform { try $0.contactCopySnapshot(source: source, identifiers: identifiers, control: $1) }
        try Task.checkCancellation()
        return result
    }
    /// Deliberate selected Reminder copies. No native object crosses this
    /// boundary, and the older whole-list readers retain their own semantics.
    func reminderCopySources() async throws -> [SystemReminderImport.Source] {
        try Task.checkCancellation()
        let result = try await perform { try $0.reminderCopySources(control: $1) }
        try Task.checkCancellation()
        return result
    }
    func reminderCopySummaries(source: SystemReminderImport.Source) async throws -> [SystemReminderReader.Summary] {
        try Task.checkCancellation()
        let control = SystemSourceReadControl()
        let result: [SystemReminderReader.Summary] = try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    self.worker().reminderCopySummaries(source: source, control: control) {
                        continuation.resume(with: $0)
                    }
                }
            }
        }, onCancel: { control.cancel() })
        try Task.checkCancellation()
        return result
    }
    func reminderCopySnapshot(source: SystemReminderImport.Source, identifiers: [String]) async throws -> SystemReminderImport.Snapshot {
        try Task.checkCancellation()
        let result = try await perform { try $0.reminderCopySnapshot(source: source, identifiers: identifiers, control: $1) }
        try Task.checkCancellation()
        return result
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
    func snapshotEvents(sourceUID: String, start: Date, end: Date) async throws -> SystemSourceSnapshot {
        try await perform { try $0.snapshotEvents(sourceUID: sourceUID, start: start, end: end, control: $1) }
    }
    func snapshotContacts(sourceUID: String) async throws -> SystemSourceSnapshot {
        try await perform { try $0.snapshotContacts(sourceUID: sourceUID, control: $1) }
    }
    func snapshotReminders(sourceUID: String) async throws -> SystemSourceSnapshot {
        let control = SystemSourceReadControl()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                queue.async { self.worker().snapshotReminders(sourceUID: sourceUID, control: control) { continuation.resume(with: $0) } }
            }
        }, onCancel: { control.cancel() })
    }

    /// Refs #786. One explicitly bound source at a time; no copy metadata grants
    /// write access. The caller owns durable authorization and the write journal.
    func syncSnapshot(sourceUID: String, start: Date, end: Date,
                      context: CalendarTimeContext, displayTimeZone: String) async throws -> SystemAccountSync.Snapshot {
        if sourceUID.hasPrefix("macos-events:") {
            return try await performSync { try $0.syncEventSnapshot(sourceUID: sourceUID, start: start, end: end,
                context: context, displayTimeZone: displayTimeZone, control: $1) }
        }
        if sourceUID.hasPrefix("macos-contacts:") {
            return try await performSync { store, control in
                let found = try store.contactCopySources(control: control).filter { $0.sourceUID.utf8.elementsEqual(sourceUID.utf8) }
                guard found.count == 1 else { throw BetaError("The selected Contacts source is missing or ambiguous.") }
                let source = found[0], summaries = try store.contactCopySummaries(source: source, control: control)
                guard summaries.count <= SystemAccountSync.maximumRecords else { throw BetaError("Select a source containing at most 100 contacts for this field synchronization.") }
                let snapshot = summaries.isEmpty ? SystemContactImport.Snapshot(source: source, records: []) :
                    try store.contactCopySnapshot(source: source, identifiers: summaries.map(\.identifier), control: control)
                return try SystemAccountSyncProjection.contacts(snapshot, displayTimeZone: displayTimeZone)
            }
        }
        guard sourceUID.hasPrefix("macos-reminders:") else { throw BetaError("Unsupported native synchronization source.") }
        return try await performSyncAsync { store, control, completion in
            do {
                let found = try store.reminderCopySources(control: control).filter { $0.sourceUID.utf8.elementsEqual(sourceUID.utf8) }
                guard found.count == 1 else { throw BetaError("The selected Reminders source is missing or ambiguous.") }
                let source = found[0]
                store.reminderCopySummaries(source: source, control: control) { value in
                    do {
                        let summaries = try value.get()
                        guard summaries.count <= SystemAccountSync.maximumRecords else { throw BetaError("Select a list containing at most 100 reminders for this field synchronization.") }
                        let snapshot = summaries.isEmpty ? SystemReminderImport.Snapshot(source: source, records: []) :
                            try store.reminderCopySnapshot(source: source, identifiers: summaries.map(\.identifier), control: control)
                        try control.check()
                        completion(.success(try SystemAccountSyncProjection.reminders(snapshot, context: context, displayTimeZone: displayTimeZone)))
                    } catch { completion(.failure(error)) }
                }
            } catch { completion(.failure(error)) }
        }
    }

    func applySync(operation: SystemAccountSync.Operation, source: SystemAccountSync.Source,
                   context: CalendarTimeContext) async throws -> SystemAccountSync.Record {
        guard beginSyncWrite(source.sourceUID) else { throw SystemAccountSync.RejectedBeforeWrite("A previous native write for this source is still running.") }
        return try await performSync(onNativeFinish: { self.endSyncWrite(source.sourceUID) }) { store, control in
            try store.applySync(operation: operation, source: source, context: context, control: control)
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
                 "supportsVevent": kind == .events, "readOnly": !$0.allowsContentModifications,
                 "systemSyncFields": $0.allowsContentModifications && $0.type != .birthday]
            }
        }
        if authorization(.contacts) == "authorized" {
            do {
                books = try contacts.containers(matching: nil).map {
                    ["uid": SystemSourcePolicy.uid(.contacts, $0.identifier), "name": $0.name,
                     "quelle": "macos", "art": "contacts", "readOnly": true,
                     "systemSyncFields": true, "systemSyncWritePolicy": "existing-nonunified-contact-fields"]
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
            "systemAccountSyncImplemented": true]
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

    private final class ReminderRead<Value> {
        var completion: ((Result<Value, Error>) -> Void)?
        init(_ completion: @escaping (Result<Value, Error>) -> Void) { self.completion = completion }
        func finish(_ result: Result<Value, Error>) {
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
    // #775: use the existing store, authorization policy and read control, without
    // changing the old full-source snapshot semantics or fetching vCard note keys.
    func contactCopySources(control: SystemSourceReadControl) throws -> [SystemContactImport.Source] {
        dispatchPrecondition(condition: .onQueue(queue))
        return try SystemContactReader.sources(store: contacts, control: control, requireAccess: { try self.requireContactCopyAccess() })
    }
    func contactCopySummaries(source: SystemContactImport.Source, control: SystemSourceReadControl) throws -> [SystemContactReader.Summary] {
        dispatchPrecondition(condition: .onQueue(queue))
        return try SystemContactReader.summaries(store: contacts, source: source, control: control, requireAccess: { try self.requireContactCopyAccess() })
    }
    func contactCopySnapshot(source: SystemContactImport.Source, identifiers: [String],
                             control: SystemSourceReadControl) throws -> SystemContactImport.Snapshot {
        dispatchPrecondition(condition: .onQueue(queue))
        return try SystemContactReader.snapshot(store: contacts, source: source, identifiers: identifiers,
            control: control, requireAccess: { try self.requireContactCopyAccess() })
    }
    private func requireContactCopyAccess() throws {
        do { try requireAccess(.contacts) }
        catch {
            // The same policy is checked again after reads. Do not claim that no
            // source data was ever read if access was revoked during that read.
            throw BetaError("macOS Contacts access is unavailable. No contacts were copied. Check Privacy & Security → Contacts before trying again.")
        }
    }
    func reminderCopySources(control: SystemSourceReadControl) throws -> [SystemReminderImport.Source] {
        dispatchPrecondition(condition: .onQueue(queue))
        return try SystemReminderReader.sources(store: events, queue: queue, control: control,
            requireAccess: { try self.requireReminderCopyAccess() })
    }
    func reminderCopySummaries(source: SystemReminderImport.Source, control: SystemSourceReadControl,
                               completion: @escaping (Result<[SystemReminderReader.Summary], Error>) -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        SystemReminderReader.summaries(store: events, queue: queue, source: source, control: control,
            requireAccess: { try self.requireReminderCopyAccess() }, completion: completion)
    }
    func reminderCopySnapshot(source: SystemReminderImport.Source, identifiers: [String],
                             control: SystemSourceReadControl) throws -> SystemReminderImport.Snapshot {
        dispatchPrecondition(condition: .onQueue(queue))
        return try SystemReminderReader.snapshot(store: events, queue: queue, source: source,
            identifiers: identifiers, control: control, requireAccess: { try self.requireReminderCopyAccess() })
    }
    private func requireReminderCopyAccess() throws {
        do { try requireAccess(.reminders) }
        catch {
            // Access may be revoked after an earlier read. Do not claim that
            // no system data was read; this path has made no local/source write.
            throw BetaError("macOS Reminders access is unavailable. No reminder copy was imported. Check Privacy & Security → Reminders before trying again.")
        }
    }
    private func typedSource(_ calendar: EKCalendar, kind: SystemSourcePolicy.Kind) throws -> SystemSourceSnapshot.Source {
        let parent = "macos-account:" + Data(calendar.source.sourceIdentifier.utf8).base64EncodedString()
        let type = calendar.type == .birthday ? "birthday" : "calendar:\(calendar.type.rawValue)"
        return try .init(uid: SystemSourcePolicy.uid(kind, calendar.calendarIdentifier), kind: kind, title: calendar.title,
                         parentUID: parent, parentTitle: calendar.source.title, parentType: "source:\(calendar.source.sourceType.rawValue)",
                         nativeType: type, permission: authorization(kind), readOnly: !calendar.allowsContentModifications)
    }
    private func appendTyped(_ record: SystemSourceSnapshot.Record, to records: inout [SystemSourceSnapshot.Record], bytes: inout Int) throws {
        bytes += try Document.encode(record.fields).utf8.count
        guard records.count < maximumItems, bytes <= 16 * 1024 * 1024 else { throw BetaError("Native source exceeds snapshot limits.") }
        records.append(record)
    }
    func snapshotEvents(sourceUID: String, start: Date, end: Date, control: SystemSourceReadControl) throws -> SystemSourceSnapshot {
        try control.check(); try SystemSourcePolicy.requireWindow(start: start, end: end)
        let calendar = try self.calendar(sourceUID, kind: .events)
        let source = try typedSource(calendar, kind: .events)
        let found = events.events(matching: events.predicateForEvents(withStart: start, end: end, calendars: [calendar]))
        guard found.count <= maximumItems else { throw BetaError("Event window exceeds snapshot limit.") }
        var records: [SystemSourceSnapshot.Record] = [], bytes = 0
        for event in found { try control.check(); try appendTyped(NativeSystemRecordReader.event(event, source: source), to: &records, bytes: &bytes) }
        try control.check(); try requireAccess(.events)
        return try .init(source: source, scope: .boundedWindow(start: start, end: end), records: records)
    }
    func snapshotReminders(sourceUID: String, control: SystemSourceReadControl,
                           completion: @escaping (Result<SystemSourceSnapshot, Error>) -> Void) {
        do {
            try control.check()
            let calendar = try self.calendar(sourceUID, kind: .reminders)
            let source = try typedSource(calendar, kind: .reminders)
            let read = ReminderRead<SystemSourceSnapshot>(completion)
            let token = events.fetchReminders(matching: events.predicateForReminders(in: [calendar])) { found in
                self.queue.async {
                    guard read.completion != nil else { return }
                    do {
                        try control.check(); try self.requireAccess(.reminders)
                        guard let found, found.count <= self.maximumItems else { throw BetaError("Incomplete native reminders snapshot.") }
                        var records: [SystemSourceSnapshot.Record] = [], bytes = 0
                        for reminder in found { try control.check(); try self.appendTyped(NativeSystemRecordReader.reminder(reminder, source: source), to: &records, bytes: &bytes) }
                        read.finish(.success(try .init(source: source, scope: .fullSource, records: records)))
                    } catch { read.finish(.failure(error)) }
                }
            }
            func poll() {
                self.queue.asyncAfter(deadline: .now() + .milliseconds(100)) {
                    guard read.completion != nil else { return }
                    do { try control.check(); poll() }
                    catch { self.events.cancelFetchRequest(token); read.finish(.failure(error)) }
                }
            }
            poll()
        } catch { completion(.failure(error)) }
    }
    func snapshotContacts(sourceUID: String, control: SystemSourceReadControl) throws -> SystemSourceSnapshot {
        try control.check(); try requireAccess(.contacts)
        let identifier = try SystemSourcePolicy.identifier(sourceUID, kind: .contacts)
        guard let container = try contacts.containers(matching: nil).first(where: { $0.identifier == identifier }) else { throw BetaError("Selected contacts container is unavailable.") }
        let source = try SystemSourceSnapshot.Source(uid: sourceUID, kind: .contacts, title: container.name,
            nativeType: "container:\(container.type.rawValue)", permission: authorization(.contacts), readOnly: true)
        let keys: [CNKeyDescriptor] = [CNContactVCardSerialization.descriptorForRequiredKeys(), CNContactBirthdayKey as CNKeyDescriptor,
                                      CNContactNonGregorianBirthdayKey as CNKeyDescriptor, CNContactDatesKey as CNKeyDescriptor]
        let request = CNContactFetchRequest(keysToFetch: keys)
        request.predicate = CNContact.predicateForContactsInContainer(withIdentifier: identifier); request.unifyResults = false
        var records: [SystemSourceSnapshot.Record] = [], bytes = 0, failure: Error?
        try contacts.enumerateContacts(with: request) { contact, stop in
            do {
                try control.check()
                try self.appendTyped(NativeSystemRecordReader.contact(contact, source: source, unification: .nonUnifiedContainer), to: &records, bytes: &bytes)
            } catch { failure = error; stop.pointee = true }
        }
        if let failure { throw failure }
        try control.check(); try requireAccess(.contacts)
        return try .init(source: source, scope: .fullSource, records: records)
    }

    private func syncCalendar(_ uid: String, kind: SystemSourcePolicy.Kind) throws -> EKCalendar {
        try requireAccess(kind)
        let identifier = try SystemSourcePolicy.identifier(uid, kind: kind)
        let calendars = events.calendars(for: kind == .events ? .event : .reminder)
        guard calendars.count <= 256 else { throw BetaError("Too many native calendars.") }
        var seen = Set<OpaqueUTF8Identity>(), found: [EKCalendar] = []
        for calendar in calendars {
            guard seen.insert(OpaqueUTF8Identity(calendar.calendarIdentifier)).inserted else { throw BetaError("Native calendar identities are ambiguous.") }
            if calendar.calendarIdentifier.utf8.elementsEqual(identifier.utf8) { found.append(calendar) }
        }
        guard found.count == 1, found[0].allowsContentModifications, found[0].type != .birthday,
              found[0].refresh(), found[0].source?.refresh() == true else { throw BetaError("The selected native source is unavailable or read-only.") }
        return found[0]
    }

    func syncEventSnapshot(sourceUID: String, start: Date, end: Date, context: CalendarTimeContext,
                           displayTimeZone: String, control: SystemSourceReadControl) throws -> SystemAccountSync.Snapshot {
        dispatchPrecondition(condition: .onQueue(queue))
        try control.check(); try SystemSourcePolicy.requireWindow(start: start, end: end)
        let calendar = try syncCalendar(sourceUID, kind: .events), source = try typedSource(calendar, kind: .events)
        let binding = try SystemAccountSyncProjection.eventSource(source, start: start, end: end, displayTimeZone: displayTimeZone)
        let found = events.events(matching: events.predicateForEvents(withStart: start, end: end, calendars: [calendar]))
        guard found.count <= SystemAccountSync.maximumRecords else { throw BetaError("Select a date window containing at most 100 events for this field synchronization.") }
        var records: [SystemSourceSnapshot.Record] = []
        for event in found {
            try control.check(); try syncMembership(event, source: source)
            records.append(try NativeSystemRecordReader.event(event, source: source))
        }
        let fresh = try typedSource(syncCalendar(sourceUID, kind: .events), kind: .events)
        let freshBinding = try SystemAccountSyncProjection.eventSource(fresh, start: start, end: end, displayTimeZone: displayTimeZone)
        guard binding.fingerprint == freshBinding.fingerprint else { throw BetaError("The selected calendar/account changed while reading.") }
        try control.check(); try requireAccess(.events)
        return try SystemAccountSyncProjection.events(.init(source: fresh, scope: .boundedWindow(start: start, end: end), records: records),
            context: context, displayTimeZone: displayTimeZone)
    }

    private func syncMembership(_ event: EKEvent, source: SystemSourceSnapshot.Source) throws {
        guard let calendar = event.calendar, let parent = calendar.source,
              SystemSourcePolicy.uid(.events, calendar.calendarIdentifier).utf8.elementsEqual(source.uid.utf8),
              ("macos-account:" + Data(parent.sourceIdentifier.utf8).base64EncodedString()).utf8.elementsEqual((source.parentUID ?? "").utf8) else {
            throw BetaError("The event moved or no longer belongs to the selected calendar/account.")
        }
    }

    private func syncEventRecord(_ event: EKEvent, source: SystemAccountSync.Source,
                                 context: CalendarTimeContext, control: SystemSourceReadControl) throws -> SystemAccountSync.Record {
        try control.check()
        let typed = try typedSource(syncCalendar(source.sourceUID, kind: .events), kind: .events)
        try syncMembership(event, source: typed)
        guard let start = source.scope["start"] as? Double, let end = source.scope["end"] as? Double else { throw BetaError("Missing synchronization window.") }
        let raw = try NativeSystemRecordReader.event(event, source: typed)
        let snapshot = try SystemAccountSyncProjection.events(.init(source: typed,
            scope: .boundedWindow(start: Date(timeIntervalSince1970: start), end: Date(timeIntervalSince1970: end)), records: [raw]),
            context: context, displayTimeZone: source.displayTimeZone)
        guard snapshot.source.fingerprint == source.fingerprint, snapshot.records.count == 1,
              snapshot.excluded.isEmpty, let record = snapshot.records.first else { throw BetaError("The event or source is no longer eligible for field synchronization.") }
        return record
    }

    func applySync(operation: SystemAccountSync.Operation, source: SystemAccountSync.Source,
                   context: CalendarTimeContext, control: SystemSourceReadControl) throws -> SystemAccountSync.Record {
        dispatchPrecondition(condition: .onQueue(queue))
        if source.kind == .contacts {
            return try SystemContactReader.applySync(store: contacts, operation: operation, source: source,
                context: context, control: control, requireAccess: { try self.requireAccess(.contacts) })
        }
        if source.kind == .reminders {
            return try SystemReminderReader.applySync(store: events, queue: queue, operation: operation, source: source,
                context: context, control: control, requireAccess: { try self.requireAccess(.reminders) })
        }
        var enteredSave = false
        do {
            try control.check(); try requireAccess(.events)
            guard source.kind == .events, let event = events.event(withIdentifier: operation.identifier),
                  event.eventIdentifier?.utf8.elementsEqual(operation.identifier.utf8) == true,
                  !event.isNew, !event.hasChanges, event.refresh() else { throw BetaError("The selected event is missing or changed identity.") }
            let current = try syncEventRecord(event, source: source, context: context, control: control)
            guard current.revision == operation.before.revision else { throw BetaError("The event changed after planning; read it again.") }
            let patch = try SystemAccountSyncProjection.nativePatch(record: current, desired: operation.desiredRecord,
                changedGroups: operation.changedGroups, source: source, context: context)
            guard try DAVSyncBaseline.canonicalJSON(patch) == DAVSyncBaseline.canonicalJSON(operation.nativePatch) else { throw BetaError("The journaled native field patch is inconsistent.") }
            try control.check(); try requireAccess(.events)
            if let title = patch["title"] as? String { event.title = title }
            if let notes = patch["notes"] as? String { event.notes = notes }
            if let location = patch["location"] as? String { event.location = location }
            if let start = patch["start"] as? Double, let end = patch["end"] as? Double, let allDay = patch["allDay"] as? Bool {
                event.isAllDay = allDay; event.timeZone = (patch["timeZone"] as? String).flatMap(TimeZone.init(identifier:))
                event.startDate = Date(timeIntervalSince1970: start); event.endDate = Date(timeIntervalSince1970: end)
            }
            // Apple does not provide a CAS token. A deletion racing this call can
            // recreate an event; even an API error is an uncertain write outcome.
            enteredSave = true
            try events.save(event, span: .thisEvent, commit: true)
            guard event.eventIdentifier?.utf8.elementsEqual(operation.identifier.utf8) == true,
                  let fresh = events.event(withIdentifier: operation.identifier), fresh.refresh() else { throw BetaError("Event identity changed or readback is unavailable after saving.") }
            let readback = try syncEventRecord(fresh, source: source, context: context, control: control)
            try operation.validateReadback(readback)
            return readback
        } catch {
            if enteredSave { events.reset(); throw BetaError("The native event write has an uncertain outcome. Keep the journal and review the source. " + error.localizedDescription) }
            throw SystemAccountSync.RejectedBeforeWrite(error.localizedDescription)
        }
    }

}
