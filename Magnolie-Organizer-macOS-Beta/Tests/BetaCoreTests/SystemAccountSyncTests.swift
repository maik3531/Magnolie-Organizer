import Foundation
import XCTest
@testable import BetaCore

/// Refs #786. Synthetic native DTOs only. These tests neither request TCC access
/// nor read or write a person's accounts. SDK/store acceptance is a separate gate.
final class SystemAccountSyncTests: XCTestCase {
    typealias Sync = SystemAccountSync
    private func context() throws -> CalendarTimeContext { try CalendarTestContext.make(systemIdentifier: "UTC") }
    private func book() -> [String: Any] {
        ["termine": [[String: Any]](), "aufgaben": [[String: Any]](), "kontakte": [[String: Any]](), "notizen": [[String: Any]](),
         "futureRoot": ["untouched": ["value": 42]], "einstellungen": ["allgemein": ["handbuchHinweisGezeigt": true]]]
    }
    private func fixture(_ name: String) throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
        return try Document.object(String(contentsOf: url, encoding: .utf8))
    }
    private func contacts() throws -> Sync.Snapshot {
        let value = try fixture("system-contact-copy"), source = try XCTUnwrap(value["source"] as? [String: Any])
        let native = SystemContactImport.Source(sourceUID: try XCTUnwrap(source["sourceUID"] as? String),
            containerID: try XCTUnwrap(source["containerID"] as? String), title: try XCTUnwrap(source["title"] as? String), nativeType: try XCTUnwrap(source["nativeType"] as? String))
        let rows = try XCTUnwrap(value["records"] as? [[String: Any]])
        let records = try rows.map { try SystemContactImport.Record(identifier: XCTUnwrap($0["identifier"] as? String), title: XCTUnwrap($0["title"] as? String),
            fields: XCTUnwrap($0["fields"] as? [String: Any]), failure: $0["failure"] as? String) }
        return try SystemAccountSyncProjection.contacts(.init(source: native, records: records), displayTimeZone: "Europe/Berlin")
    }
    private func reminders() throws -> Sync.Snapshot {
        let value = try fixture("system-reminder-copy"), source = try XCTUnwrap(value["source"] as? [String: Any])
        let native = SystemReminderImport.Source(sourceUID: try XCTUnwrap(source["sourceUID"] as? String), calendarID: try XCTUnwrap(source["calendarID"] as? String),
            title: try XCTUnwrap(source["title"] as? String), parentUID: try XCTUnwrap(source["parentUID"] as? String), parentTitle: try XCTUnwrap(source["parentTitle"] as? String),
            parentType: try XCTUnwrap(source["parentType"] as? String), nativeType: try XCTUnwrap(source["nativeType"] as? String), readOnly: false, permission: "authorized")
        let rows = try XCTUnwrap(value["records"] as? [[String: Any]])
        let records = try rows.map { try SystemReminderImport.Record(identifier: XCTUnwrap($0["identifier"] as? String), fields: XCTUnwrap($0["fields"] as? [String: Any]), failure: nil) }
        return try SystemAccountSyncProjection.reminders(.init(source: native, records: records), context: context(), displayTimeZone: "Europe/Berlin")
    }
    private func events(identifier: String = "event-one") throws -> Sync.Snapshot {
        let native = try SystemSourceSnapshot.Source(uid: SystemSourcePolicy.uid(.events, "calendar-one"), kind: .events, title: "Selected calendar",
            parentUID: "macos-account:" + Data("account-one".utf8).base64EncodedString(), parentTitle: "Selected account", parentType: "source:2",
            nativeType: "calendar:2", permission: "authorized", readOnly: false)
        let fields: [String: Any] = ["title": "Review native event", "notes": "Native note", "location": "Office",
            "start": 1_795_770_000.0, "end": 1_795_773_600.0, "allDay": false, "timeZone": "Europe/Berlin",
            "externalIdentifier": "provider-event-one", "url": NSNull(), "recurring": false, "isDetached": false,
            "occurrenceDate": NSNull(), "modified": 1_795_000_000.0, "created": 1_790_000_000.0,
            "status": 1, "availability": 0, "recurrenceRules": [[String: Any]](), "alarms": [[String: Any]](),
            "attendeeCount": 0, "hasOrganizer": false, "metadataIncomplete": ["provider-opaque-fields"]]
        return try SystemAccountSyncProjection.events(.init(source: native,
            scope: .boundedWindow(start: Date(timeIntervalSince1970: 1_767_225_600), end: Date(timeIntervalSince1970: 1_798_761_600)),
            records: [.init(source: native, identifier: identifier, fields: fields)]), context: context(), displayTimeZone: "Europe/Berlin")
    }
    private func adopted(_ snapshot: Sync.Snapshot) throws -> Sync.Finalized {
        try Sync.prepare(snapshot: snapshot, currentBook: book(), baseline: nil, context: context()).finalize(readbacks: [])
    }
    private func edit(_ book: [String: Any], source: Sync.Source, values: [String: Any]) throws -> [String: Any] {
        var value = book, rows = try XCTUnwrap(value[source.collection] as? [[String: Any]])
        rows[0].merge(values) { _, new in new }; value[source.collection] = rows; return value
    }
    private func remote(_ snapshot: Sync.Snapshot, values: [String: Any]) throws -> Sync.Snapshot {
        let record = try XCTUnwrap(snapshot.records.first)
        var fields = record.nativeFields; fields.merge(values) { _, new in new }
        return try Sync.Snapshot(source: snapshot.source, records: [SystemAccountSyncProjection.reproject(record: record, nativeFields: fields, source: snapshot.source, context: context())])
    }
    private func plan(_ snapshot: Sync.Snapshot, _ state: Sync.Finalized, changes: [String: Any] = [:]) throws -> Sync.Plan {
        try Sync.prepare(snapshot: snapshot, currentBook: edit(state.candidateBook, source: snapshot.source, values: changes), baseline: state.baseline, context: context())
    }
    private func row(_ book: [String: Any], source: Sync.Source) throws -> [String: Any] { try XCTUnwrap((book[source.collection] as? [[String: Any]])?.first) }
    private func equal(_ left: Any, _ right: Any, file: StaticString = #filePath, line: UInt = #line) throws {
        XCTAssertEqual(try DAVSyncBaseline.canonicalJSON(left), try DAVSyncBaseline.canonicalJSON(right), file: file, line: line)
    }
    private func acknowledgement(_ operation: Sync.Operation, source: Sync.Source) throws -> Sync.Record {
        var fields = operation.before.nativeFields; fields.merge(operation.nativePatch) { _, new in new }
        if source.kind != .contacts { fields["modified"] = 1_796_000_000.0 }
        if let notes = operation.nativePatch["notes"] as? String, source.kind == .reminders { fields["hasNotes"] = !notes.isEmpty }
        if let completed = operation.nativePatch["completed"] as? Bool { fields["completionDate"] = completed ? 1_796_000_000.0 as Any : NSNull() }
        return try SystemAccountSyncProjection.reproject(record: operation.before, nativeFields: fields, source: source, context: context())
    }

    func testAllThreeProjectionsAreStableAndInitialBindingOnlyCreatesLocalUUIDs() throws {
        for (first, second) in [(try events(), try events()), (try reminders(), try reminders()), (try contacts(), try contacts())] {
            try equal(first.payload, second.payload)
            let state = try adopted(first), item = try row(state.candidateBook, source: first.source)
            XCTAssertNotNil(UUID(uuidString: try XCTUnwrap(item["id"] as? String)))
            XCTAssertNotNil(UUID(uuidString: try XCTUnwrap(item["uid"] as? String)))
            XCTAssertNotEqual(item["id"] as? String, first.records[0].identifier)
            XCTAssertEqual(state.baseline.entries.count, 1)
            let unchanged = try plan(second, state)
            XCTAssertTrue(unchanged.operations.isEmpty); XCTAssertTrue(unchanged.conflicts.isEmpty)
            try equal(unchanged.candidateBook["futureRoot"]!, book()["futureRoot"]!)
        }
    }
    func testPassiveCopiesAndSameNamesNeverBecomeWriteAuthority() throws {
        let source = try contacts()
        var previous = book(), copy = source.records[0].canonicalRecord
        copy["id"] = "old-independent-copy"; copy["uid"] = "old-independent-uid"; copy["notiz"] = "Keep my note"
        previous["kontakte"] = [copy]
        let plan = try Sync.prepare(snapshot: source, currentBook: previous, baseline: nil, context: context())
        let rows = try XCTUnwrap(plan.candidateBook["kontakte"] as? [[String: Any]])
        XCTAssertEqual(rows.count, 2); try equal(rows[0], copy)
        XCTAssertTrue(plan.operations.isEmpty); XCTAssertNotEqual(plan.nextBaseline.entries[0].localID, "old-independent-copy")
    }
    func testEachProviderPullsAChangedSupportedField() throws {
        for (source, native, local) in [(try events(), "title", "titel"), (try reminders(), "title", "titel"), (try contacts(), "givenName", "vorname")] {
            let state = try adopted(source), changed = try remote(source, values: [native: "Changed remotely"])
            let result = try plan(changed, state)
            XCTAssertTrue(result.operations.isEmpty); XCTAssertTrue(result.conflicts.isEmpty)
            XCTAssertEqual(try row(result.candidateBook, source: source.source)[local] as? String, "Changed remotely")
        }
    }
    func testEachProviderPushesAChangedSupportedFieldAndNeedsReadback() throws {
        for (source, native, local) in [(try events(), "title", "titel"), (try reminders(), "title", "titel"), (try contacts(), "givenName", "vorname")] {
            let state = try adopted(source), changed = try plan(source, state, changes: [local: "Changed locally"])
            XCTAssertEqual(changed.operations.count, 1); XCTAssertTrue(changed.conflicts.isEmpty)
            let operation = try XCTUnwrap(changed.operations.first)
            XCTAssertEqual(operation.nativePatch[native] as? String, "Changed locally")
            XCTAssertThrowsError(try changed.finalize(readbacks: []))
            let readback = try acknowledgement(operation, source: source.source), final = try changed.finalize(readbacks: [readback])
            XCTAssertEqual(try row(final.candidateBook, source: source.source)[local] as? String, "Changed locally")
            let after = try Sync.prepare(snapshot: .init(source: source.source, records: [readback]), currentBook: final.candidateBook, baseline: final.baseline, context: context())
            XCTAssertTrue(after.operations.isEmpty); XCTAssertTrue(after.conflicts.isEmpty)
        }
    }
    func testDisjointChangesMergeButSameFieldConflictLeavesBothAndBaselineUntouched() throws {
        let source = try reminders(), state = try adopted(source)
        let changed = try remote(source, values: ["notes": "Remote note", "hasNotes": true])
        let merge = try plan(changed, state, changes: ["titel": "Local title"])
        XCTAssertEqual(merge.operations.count, 1); XCTAssertTrue(merge.conflicts.isEmpty)
        XCTAssertEqual(try row(merge.candidateBook, source: source.source)["notiz"] as? String, "Remote note")
        let conflict = try plan(try remote(source, values: ["title": "Remote title"]), state, changes: ["titel": "Local title"])
        XCTAssertTrue(conflict.operations.isEmpty); XCTAssertEqual(conflict.conflicts.count, 1)
        XCTAssertEqual(try row(conflict.candidateBook, source: source.source)["titel"] as? String, "Local title")
        try equal(conflict.nextBaseline.payload, state.baseline.payload)
    }
    func testEqualChangesConvergeWithoutWriting() throws {
        let source = try reminders(), state = try adopted(source), remote = try remote(source, values: ["title": "Same new title"])
        let result = try plan(remote, state, changes: ["titel": "Same new title"])
        XCTAssertTrue(result.operations.isEmpty); XCTAssertTrue(result.conflicts.isEmpty)
    }
    func testMissingNativeAndLocalRowsNeverDeleteOrRecreate() throws {
        let source = try events(), state = try adopted(source)
        let empty = try Sync.Snapshot(source: source.source, records: [])
        let missingRemote = try plan(empty, state)
        XCTAssertTrue(missingRemote.operations.isEmpty); XCTAssertEqual(missingRemote.conflicts.count, 1)
        try equal(missingRemote.candidateBook, state.candidateBook); try equal(missingRemote.nextBaseline.payload, state.baseline.payload)
        var missing = state.candidateBook; missing["termine"] = [[String: Any]]()
        let missingLocal = try Sync.prepare(snapshot: source, currentBook: missing, baseline: state.baseline, context: context())
        XCTAssertTrue(missingLocal.operations.isEmpty); XCTAssertEqual(missingLocal.conflicts.count, 1)
        XCTAssertTrue(try XCTUnwrap(missingLocal.candidateBook["termine"] as? [[String: Any]]).isEmpty)
    }
    func testSourceChangeAndAmbiguousLocalIdentityFailClosed() throws {
        let source = try contacts(), state = try adopted(source)
        let other = try Sync.Source(kind: .contacts, sourceUID: source.source.sourceUID, title: "Renamed container", metadata: source.source.metadata,
            scope: source.source.scope, displayTimeZone: source.source.displayTimeZone)
        XCTAssertThrowsError(try Sync.prepare(snapshot: .init(source: other, records: []), currentBook: state.candidateBook, baseline: state.baseline, context: context()))
        var duplicate = state.candidateBook; let original = try row(duplicate, source: source.source); duplicate["kontakte"] = [original, original]
        XCTAssertThrowsError(try Sync.prepare(snapshot: source, currentBook: duplicate, baseline: state.baseline, context: context()))
    }
    func testOpaqueNativeIdentifiersRemainByteDistinct() throws {
        let first = try events(identifier: "caf\u{e9}"), second = try events(identifier: "cafe\u{301}")
        let snapshot = try Sync.Snapshot(source: first.source, records: [first.records[0], second.records[0]])
        let initial = try Sync.prepare(snapshot: snapshot, currentBook: book(), baseline: nil, context: context())
        XCTAssertEqual(initial.nextBaseline.entries.count, 2)
        XCTAssertNotEqual(initial.nextBaseline.entries[0].localID, initial.nextBaseline.entries[1].localID)
    }
    func testEventWindowBoundCannotClaimAbsenceOrOverFourYearCompleteness() throws {
        let source = try events()
        XCTAssertThrowsError(try Sync.Source(kind: .events, sourceUID: source.source.sourceUID, title: source.source.title,
            metadata: source.source.metadata, scope: ["start": 1_767_225_600.0, "end": 1_767_225_600.0 + 367 * 86400], displayTimeZone: "Europe/Berlin"))
        let narrower = try Sync.Source(kind: .events, sourceUID: source.source.sourceUID, title: source.source.title,
            metadata: source.source.metadata, scope: ["start": 1_767_225_600.0, "end": 1_767_225_600.0 + 86400], displayTimeZone: "Europe/Berlin")
        XCTAssertEqual(narrower.fingerprint, source.source.fingerprint)
        let state = try adopted(source), result = try plan(.init(source: narrower, records: []), state)
        XCTAssertEqual(result.conflicts.count, 1); XCTAssertTrue(result.operations.isEmpty)
    }
    func testContactValuesPreserveLabelsIdentifiersAndHiddenAddressFields() throws {
        let source = try contacts(), record = source.records[0], state = try adopted(source)
        var phones = try XCTUnwrap(record.canonicalRecord["telefone"] as? [[String: Any]])
        phones[0]["wert"] = "+44 20 7946 0999"
        let result = try plan(source, state, changes: ["telefone": phones]), operation = try XCTUnwrap(result.operations.first)
        let changed = try XCTUnwrap(operation.nativePatch["phoneNumbers"] as? [[String: Any]]), original = try XCTUnwrap(record.nativeFields["phoneNumbers"] as? [[String: Any]])
        XCTAssertEqual(changed[0]["identifier"] as? String, original[0]["identifier"] as? String)
        XCTAssertEqual(changed[0]["label"] as? String, original[0]["label"] as? String)
        try equal(Array(changed.dropFirst()), Array(original.dropFirst()))
        var addresses = try XCTUnwrap(record.canonicalRecord["anschriften"] as? [[String: Any]])
        addresses[0]["strasse"] = "Changed street"
        let address = try XCTUnwrap(plan(source, state, changes: ["anschriften": addresses]).operations.first)
        let actual = try XCTUnwrap((address.nativePatch["postalAddresses"] as? [[String: Any]])?[0]["value"] as? [String: Any])
        XCTAssertEqual(actual["subLocality"] as? String, "St James"); XCTAssertEqual(actual["isoCountryCode"] as? String, "GB")
        phones.append(phones[0])
        let unsupported = try plan(source, state, changes: ["telefone": phones])
        XCTAssertTrue(unsupported.operations.isEmpty); XCTAssertEqual(unsupported.conflicts.count, 1)
    }
    func testContactCaseOnlyProjectionDoesNotWriteAndYear1604IsExplicit() throws {
        let source = try contacts(), state = try adopted(source)
        let emails = try XCTUnwrap(source.records[0].canonicalRecord["emailEintraege"] as? [[String: Any]])
        XCTAssertEqual(emails[0]["wert"] as? String, "ada@example.test")
        XCTAssertTrue(try plan(source, state).operations.isEmpty)
        let changed = try plan(source, state, changes: ["geburtstag": "1604-02-29", "geburtstagJahrUnbekannt": false])
        let birthday = try XCTUnwrap(changed.operations.first?.nativePatch["birthday"] as? [String: Any])
        XCTAssertEqual(birthday["year"] as? Int, 1604)
        let invalid = try plan(source, state, changes: ["geburtstag": "1604-02-29", "geburtstagJahrUnbekannt": true])
        XCTAssertTrue(invalid.operations.isEmpty); XCTAssertEqual(invalid.conflicts.count, 1)
    }
    func testReadbackAllowsOnlyHarmlessComponentDefaultsNeverTimezoneOrYearInvention() throws {
        let expected: [String: Any] = ["calendar": "gregorian", "month": 2, "day": 29]
        XCTAssertTrue(try Sync.matchesNativeField("birthday", expected: expected, actual: expected.merging(["calendarFirstWeekday": 1, "calendarMinimumDaysInFirstWeek": 1, "calendarTimeZone": "GMT"]) { _, new in new }))
        XCTAssertFalse(try Sync.matchesNativeField("birthday", expected: expected, actual: expected.merging(["year": 1604]) { _, new in new }))
        XCTAssertFalse(try Sync.matchesNativeField("dueComponents", expected: expected, actual: expected.merging(["timeZone": "UTC"]) { _, new in new }))
    }
    func testReminderCompletionAndPriorityAreActualFieldWrites() throws {
        let source = try reminders(), state = try adopted(source), result = try plan(source, state, changes: ["erledigt": true, "prio": 1])
        let operation = try XCTUnwrap(result.operations.first)
        XCTAssertEqual(operation.nativePatch["completed"] as? Bool, true); XCTAssertEqual(operation.nativePatch["priority"] as? Int, 1)
        XCTAssertNil(operation.nativePatch["dueComponents"])
        XCTAssertNoThrow(try result.finalize(readbacks: [acknowledgement(operation, source: source.source)]))
    }
    func testFloatingReminderDSTGapAndDateOnlyStayCivil() throws {
        let original = try reminders()
        let fields: [String: Any] = ["calendar": "gregorian", "calendarTimeZone": "Pacific/Auckland", "year": 2026, "month": 3, "day": 29, "hour": 2, "minute": 30, "second": 0]
        let source = try remote(original, values: ["startComponents": fields, "dueComponents": NSNull()]), state = try adopted(source)
        let result = try plan(source, state, changes: ["titel": "A floating gap is not a UTC instant"])
        XCTAssertEqual(result.operations.count, 1); XCTAssertNil(result.operations.first?.nativePatch["startComponents"])
        let dateOnly = try remote(original, values: ["startComponents": NSNull(), "dueComponents": ["calendar": "gregorian", "year": 2028, "month": 2, "day": 29]])
        let dateState = try adopted(dateOnly), changed = try plan(dateOnly, dateState, changes: ["notiz": "Leap date remains a date"])
        XCTAssertEqual(changed.operations.count, 1); XCTAssertNil(changed.operations.first?.nativePatch["dueComponents"])
    }
    func testCalendarEditorEquivalentRawOrderDoesNotInventADateWrite() throws {
        let source = try events(), state = try adopted(source)
        var lines = try XCTUnwrap(source.records[0].canonicalRecord["icsRoundtrip"] as? [String])
        let location = lines.filter { $0.hasPrefix("LOCATION:") }; lines.removeAll { $0.hasPrefix("LOCATION:") }; lines += location
        let result = try plan(source, state, changes: ["titel": "Changed by real editor shape", "icsRoundtrip": lines])
        XCTAssertEqual(result.operations.count, 1)
        XCTAssertEqual(result.operations.first?.changedGroups, ["title"])
    }
    func testIncomingSecondsChangeIsNotHiddenByMinutePrecision() throws {
        let source = try events(), state = try adopted(source)
        let changed = try remote(source, values: ["start": 1_795_770_017.0, "end": 1_795_773_619.0])
        let result = try plan(changed, state)
        XCTAssertTrue(result.operations.isEmpty); XCTAssertTrue(result.conflicts.isEmpty)
        let after = try row(result.candidateBook, source: source.source)
        XCTAssertEqual(after["zeit"] as? String, "10:00")
        XCTAssertTrue(try XCTUnwrap(after["icsRoundtrip"] as? [String]).contains("DTSTART:20261127T090017Z"))
        XCTAssertTrue(try XCTUnwrap(after["icsRoundtrip"] as? [String]).contains("DTEND:20261127T100019Z"))
    }
    func testPartialEventTimeEditPreservesUntouchedNativeSeconds() throws {
        let source = try remote(events(), values: ["start": 1_795_770_017.0, "end": 1_795_773_619.0]), state = try adopted(source)
        var lines = try XCTUnwrap(source.records[0].canonicalRecord["icsRoundtrip"] as? [String])
        lines = lines.map { $0.hasPrefix("DTEND:") ? "DTEND:20261127T110000Z" : $0 }
        let result = try plan(source, state, changes: ["endZeit": "12:00", "icsRoundtrip": lines])
        let operation = try XCTUnwrap(result.operations.first)
        XCTAssertEqual(operation.nativePatch["start"] as? Double, 1_795_770_017)
        XCTAssertEqual(operation.nativePatch["end"] as? Double, 1_795_777_200)
        XCTAssertNoThrow(try result.finalize(readbacks: [acknowledgement(operation, source: source.source)]))
    }
    func testReminderEditorUTCRewriteRetainsExplicitNativeComponentZone() throws {
        let base = try reminders()
        var start = try XCTUnwrap(base.records[0].nativeFields["startComponents"] as? [String: Any])
        var due = try XCTUnwrap(base.records[0].nativeFields["dueComponents"] as? [String: Any])
        start["timeZone"] = "Europe/Berlin"; due["timeZone"] = "Europe/Berlin"
        let source = try remote(base, values: ["startComponents": start, "dueComponents": due]), state = try adopted(source)
        var lines = try XCTUnwrap(source.records[0].canonicalRecord["icsRoundtrip"] as? [String])
        lines = lines.map { $0.hasPrefix("DTSTART") ? "DTSTART:20261127T090500Z" : $0 }
        let result = try plan(source, state, changes: ["startZeit": "10:05", "icsRoundtrip": lines])
        let component = try XCTUnwrap(result.operations.first?.nativePatch["startComponents"] as? [String: Any])
        XCTAssertEqual(component["hour"] as? Int, 10); XCTAssertEqual(component["timeZone"] as? String, "Europe/Berlin")
    }
    func testNewReminderRootsAppendAfterExistingRootsWithoutMovingChildren() throws {
        let source = try reminders(), first = source.records[0]
        let second = try Sync.Record(identifier: "second-reminder", source: source.source, canonicalRecord: first.canonicalRecord, nativeFields: first.nativeFields)
        var initial = book()
        let original: [[String: Any]] = [["id": "root-id", "uid": "root-uid", "titel": "Existing root", "elternUid": "", "reihenfolge": 0],
            ["id": "child-id", "uid": "child-uid", "titel": "Existing child", "elternUid": "root-uid", "reihenfolge": 0]]
        initial["aufgaben"] = original
        let result = try Sync.prepare(snapshot: .init(source: source.source, records: [first, second]), currentBook: initial, baseline: nil, context: context())
        let rows = try XCTUnwrap(result.candidateBook["aufgaben"] as? [[String: Any]])
        try equal(Array(rows.prefix(2)), original)
        XCTAssertEqual(rows[2]["reihenfolge"] as? Int, 1); XCTAssertEqual(rows[3]["reihenfolge"] as? Int, 2)
    }
    func testUnexpectedReadbackOrRecreatedEventCannotAdvanceBaseline() throws {
        let source = try events(), state = try adopted(source), result = try plan(source, state, changes: ["titel": "Local change"])
        let operation = try XCTUnwrap(result.operations.first), accepted = try acknowledgement(operation, source: source.source)
        var fields = accepted.nativeFields; fields["created"] = 1_796_000_000.0
        let recreated = try SystemAccountSyncProjection.reproject(record: accepted, nativeFields: fields, source: source.source, context: context())
        XCTAssertThrowsError(try result.finalize(readbacks: [recreated]))
        let newIdentity = try Sync.Record(identifier: "recreated-event", source: source.source, canonicalRecord: accepted.canonicalRecord, nativeFields: accepted.nativeFields)
        XCTAssertThrowsError(try operation.validateReadback(newIdentity))
        fields = accepted.nativeFields; fields["notes"] = "Concurrent external edit"
        let raced = try SystemAccountSyncProjection.reproject(record: accepted, nativeFields: fields, source: source.source, context: context())
        XCTAssertThrowsError(try result.finalize(readbacks: [raced]))
        XCTAssertThrowsError(try result.finalize(readbacks: [accepted, accepted]))
    }
    func testContactRaceOutcomeIsNotAnAcknowledgement() throws {
        let source = try contacts(), state = try adopted(source), result = try plan(source, state, changes: ["vorname": "Local name"])
        let operation = try XCTUnwrap(result.operations.first), accepted = try acknowledgement(operation, source: source.source)
        var fields = accepted.nativeFields; fields["jobTitle"] = "External simultaneous change"
        let raced = try SystemAccountSyncProjection.reproject(record: accepted, nativeFields: fields, source: source.source, context: context())
        XCTAssertThrowsError(try result.finalize(readbacks: [raced]))
    }
    func testAuthenticatedJournalCanRecoverFrozenPlanAndAllAcknowledgementsWithoutWrites() throws {
        let source = try reminders(), state = try adopted(source), result = try plan(source, state, changes: ["titel": "Journaled title"])
        let frozen = try Sync.Plan(payload: Document.object(Document.encode(result.payload)))
        let original = try XCTUnwrap(result.operations.first), read = try acknowledgement(original, source: source.source)
        let decoded = try Sync.Record(payload: Document.object(Document.encode(read.payload)))
        try equal(try frozen.finalize(readbacks: [decoded]).baseline.payload, try result.finalize(readbacks: [read]).baseline.payload)
        var broken = read.payload; broken["revision"] = String(repeating: "0", count: 64)
        XCTAssertThrowsError(try Sync.Record(payload: broken))
        var malformed = result.payload; malformed["delete"] = true
        XCTAssertThrowsError(try Sync.Plan(payload: malformed))
    }
    func testNormalizedObjectDefaultsBecomeLocalBaselineOnlyAfterExactSupersetProof() throws {
        let source = try reminders(), original = source.records[0]
        var canonical = original.canonicalRecord; canonical.removeValue(forKey: "erinnerungsMinute")
        let sparse = try Sync.Snapshot(source: source.source, records: [Sync.Record(identifier: original.identifier, source: source.source,
            canonicalRecord: canonical, nativeFields: original.nativeFields)])
        let result = try adopted(sparse)
        let normalized = try edit(result.candidateBook, source: source.source, values: ["erinnerungsMinute": 480])
        let baseline = try result.normalizedBaseline(in: normalized, source: source.source)
        XCTAssertEqual(baseline.entries[0].localFields["erinnerungsMinute"] as? Int, 480)
        let next = try Sync.prepare(snapshot: sparse, currentBook: normalized, baseline: baseline, context: context())
        XCTAssertTrue(next.operations.isEmpty); XCTAssertTrue(next.conflicts.isEmpty)
        let changed = try edit(normalized, source: source.source, values: ["titel": "Unexpected normalization change"])
        XCTAssertThrowsError(try result.normalizedBaseline(in: changed, source: source.source))
    }
    func testNormalizedCandidateCannotAdvanceAConflictBaseline() throws {
        let source = try reminders(), state = try adopted(source)
        let result = try plan(remote(source, values: ["title": "Remote edit"]), state, changes: ["titel": "Local edit"])
        let finalized = try result.finalize(readbacks: [])
        let normalized = try edit(finalized.candidateBook, source: source.source, values: ["ordinaryAddedDefault": ""])
        let baseline = try finalized.normalizedBaseline(in: normalized, source: source.source)
        try equal(baseline.payload, state.baseline.payload)
        let next = try Sync.prepare(snapshot: remote(source, values: ["title": "Remote edit"]), currentBook: normalized, baseline: baseline, context: context())
        XCTAssertEqual(next.conflicts.count, 1); XCTAssertTrue(next.operations.isEmpty)
    }
    func testOptionalFreshSwiftFixtureExport() throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_SYSTEM_SYNC_FIXTURE_OUTPUT"], !path.isEmpty else { return }
        let snapshots = try [events(), reminders(), contacts()]
        let result: [String: Any] = ["version": 1, "provenance": "fresh-swift-core-synthetic-inputs",
            "snapshots": snapshots.map(\.payload)]
        try Data(Document.encode(result).utf8).write(to: URL(fileURLWithPath: path), options: .atomic)
    }
}
