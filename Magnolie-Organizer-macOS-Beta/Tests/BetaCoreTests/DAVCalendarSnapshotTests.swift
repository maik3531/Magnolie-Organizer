import Foundation
import CryptoKit
import XCTest
@testable import BetaCore

final class DAVCalendarSnapshotTests: XCTestCase {
    typealias Snapshot = DAVCalendarSnapshot
    private let base = URL(string: "https://cloud.example/calendars/person/personal/")!
    private func source(_ href: URL? = nil, tasks: Bool = true) -> DAVCollection {
        let href = href ?? base
        return DAVCollection(uid: DAVClient.sourceID(kind: .calendar, href: href), name: "Fixture calendar", href: href,
            kind: .calendar, supportsVtodo: tasks, syncToken: "fixture-sync-token")
    }
    private func calendar(_ body: String, newline: String = "\r\n") -> String {
        ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Synthetic fixture//EN\nX-OPAQUE;TOKEN=one:two\n" + body + "END:VCALENDAR\n").replacingOccurrences(of: "\n", with: newline)
    }
    private func event(_ uid: String = "event-one", _ extra: String = "") -> String {
        "BEGIN:VEVENT\nUID:\(uid)\nDTSTART:20260328T100000Z\nSUMMARY:Fixture event\n\(extra)END:VEVENT\n"
    }
    private func task(_ uid: String = "task-one", _ extra: String = "") -> String {
        "BEGIN:VTODO\nUID:\(uid)\nDTSTART:20260328T100000Z\nDUE:20260329T120000Z\nSUMMARY:Fixture task\n\(extra)END:VTODO\n"
    }
    private func resource(_ body: String, path: String = "resource.ics", etag: String = "\"fixture-v1\"", collection: URL? = nil) -> DAVResource {
        DAVResource(href: (collection ?? base).appendingPathComponent(path), etag: etag, data: calendar(body))
    }
    private func expect(_ expected: DAVCalendarSnapshotError, action: () throws -> Void, file: StaticString = #filePath, line: UInt = #line) {
        do { try action(); XCTFail("Expected snapshot rejection", file: file, line: line) }
        catch let error as DAVCalendarSnapshotError { XCTAssertEqual(error, expected, file: file, line: line) }
        catch { XCTFail("Unexpected error type: \(type(of: error))", file: file, line: line) }
    }
    private func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func testMixedResourceKeepsExactBytesOpaqueMetadataAndDistinctWireBindings() throws {
        let input = resource(event("event-one", "LOCATION:Room 2\nX-OPAQUE:folded-\n\tvalue\n") + task("task-one", "RELATED-TO;RELTYPE=PARENT:parent-task\n"))
        let snapshot = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [input], displayTimeZone: "UTC")
        XCTAssertEqual(snapshot.resources.count, 1); XCTAssertEqual(snapshot.appointments.count, 1)
        XCTAssertEqual(snapshot.tasks?.count, 1); XCTAssertTrue(snapshot.anniversaries.isEmpty)
        let stored = snapshot.resources[0]
        XCTAssertEqual(stored.bytes, Data(input.data.utf8)); XCTAssertEqual(stored.sourceSHA256, hash(input.data))
        XCTAssertTrue(stored.calendarProperties.contains("X-OPAQUE;TOKEN=one:two"))
        XCTAssertEqual(stored.wireKeys, [.init(kind: "VEVENT", uid: "event-one"), .init(kind: "VTODO", uid: "task-one")])
        let row = snapshot.tasks![0]
        XCTAssertEqual(row.sourceUID, source().uid); XCTAssertEqual(row.href, input.href); XCTAssertEqual(row.etag, input.etag)
        XCTAssertEqual(row.wireKey.uid, "task-one"); XCTAssertEqual(row.value["uid"] as? String, "task-one")
        XCTAssertEqual(row.value["id"] as? String, "dav-task:" + hash(source().uid + "\n" + "task-one").prefix(32))
        XCTAssertEqual(row.value["elternUid"] as? String, "parent-task")
        XCTAssertTrue((snapshot.appointments[0].value["icsRoundtrip"] as! [String]).contains("X-OPAQUE:folded-value"))
        XCTAssertNil(row.value["sync"]); XCTAssertNil(row.value["syncQuellen"])
        XCTAssertEqual(snapshot.byteCount, input.data.utf8.count)
    }
    func testMasterAndExceptionShareOneWireUIDWithoutOccurrenceExpansion() throws {
        let master = "BEGIN:VEVENT\nUID:series\nDTSTART;TZID=Europe/Berlin:20260328T120000\nRRULE:FREQ=DAILY;COUNT=1000000\nSUMMARY:Master\nEND:VEVENT\n"
        let exception = "BEGIN:VEVENT\nUID:series\nRECURRENCE-ID;RANGE=THISANDFUTURE;TZID=Europe/Berlin;VALUE=DATE-TIME:20260329T120000\nDTSTART;TZID=Europe/Berlin:20260329T130000\nSUMMARY:Exception\nEND:VEVENT\n"
        let input = resource(master + exception)
        let snapshot = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [input], displayTimeZone: "UTC")
        XCTAssertEqual(snapshot.appointments.count, 2)
        XCTAssertEqual(Set(snapshot.resources[0].wireKeys.map(\.uid)), ["series"])
        XCTAssertEqual(snapshot.appointments.filter { $0.wireKey.recurrenceID == nil }.count, 1)
        XCTAssertEqual(snapshot.appointments.first { $0.wireKey.recurrenceID != nil }?.wireKey.recurrenceID,
                       "RECURRENCE-ID;TZID=Europe/Berlin:20260329T120000")
        XCTAssertTrue(snapshot.appointments.allSatisfy { $0.value["icsReadOnly"] as? Bool == true })
        XCTAssertEqual(snapshot.resources[0].bytes, Data(input.data.utf8))
    }
    func testExplicitAnniversaryIsRetainedSeparatelyFromOrdinaryYearlyAppointment() throws {
        let ordinary = event("ordinary-yearly", "RRULE:FREQ=YEARLY\n")
        let marked = "BEGIN:VEVENT\nUID:anniversary\nDTSTART;VALUE=DATE:20000203\nRRULE:FREQ=YEARLY\nSUMMARY:Fixture anniversary\nX-MAGNOLIE-JAHRESTAG-TYP:birthday\nEND:VEVENT\n"
        let snapshot = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(ordinary + marked)], displayTimeZone: "UTC")
        XCTAssertEqual(snapshot.appointments.count, 1); XCTAssertEqual(snapshot.anniversaries.count, 1)
        XCTAssertEqual(snapshot.anniversaries[0].wireKey.uid, "anniversary")
        XCTAssertEqual(snapshot.anniversaries[0].value["name"] as? String, "Fixture anniversary")
        XCTAssertEqual(snapshot.resources[0].records.count, 2)
    }
    func testTaskWireAliasAndSourceQualifiedLocalIdentityStaySeparate() throws {
        let originalUID = "original-task", originalSource = "legacy-source"
        let alias = "urn:magnolie:task:" + hash(originalSource + "\0" + originalUID)
        let identity: [String: Any] = ["v": 1, "source": originalSource, "uid": originalUID, "parent": "", "parentSource": ""]
        let json = String(data: try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys]), encoding: .utf8)!
            .replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: ",", with: "\\,")
        let input = resource(task(alias, "X-MAGNOLIE-TASK-IDENTITY:\(json)\n"))
        let snapshot = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [input], displayTimeZone: "UTC")
        let row = snapshot.tasks![0]
        XCTAssertEqual(row.wireKey.uid, alias); XCTAssertEqual(row.value["uid"] as? String, originalUID)
        XCTAssertEqual(row.value["icsQuelleId"] as? String, originalSource)
        XCTAssertEqual(row.value["id"] as? String, "dav-task:" + hash(source().uid + "\n" + originalUID).prefix(32))
        XCTAssertEqual(snapshot.resources[0].bytes, Data(input.data.utf8))
    }
    func testSourceNamespacesDoNotGloballyDeduplicateSameTaskUID() throws {
        let other = URL(string: "https://cloud.example/calendars/person/other/")!
        let one = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(task())], displayTimeZone: "UTC")
        let two = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(other), resources: [resource(task(), collection: other)], displayTimeZone: "UTC")
        XCTAssertEqual(one.tasks![0].value["uid"] as? String, two.tasks![0].value["uid"] as? String)
        XCTAssertNotEqual(one.tasks![0].value["id"] as? String, two.tasks![0].value["id"] as? String)
    }
    func testSameWireUIDInDifferentComponentKindsIsNotGloballyDeduplicated() throws {
        let result = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event("shared-uid"), path: "event.ics"), resource(task("shared-uid"), path: "task.ics")], displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments.count, 1); XCTAssertEqual(result.tasks?.count, 1)
        XCTAssertEqual(result.appointments[0].wireKey.uid, result.tasks![0].wireKey.uid)
        XCTAssertNotEqual(result.appointments[0].wireKey.kind, result.tasks![0].wireKey.kind)
        XCTAssertNotEqual(result.appointments[0].href, result.tasks![0].href)
    }
    func testMissingETagsAndDuplicateHrefAliasesFailBeforePublishingSnapshot() {
        for etag in ["", " ", "*", " * ", "\"v1\"\r\nInjected: header"] {
            expect(.missingETag) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event(), etag: etag)]) }
        }
        let one = resource(event(), path: "a.ics")
        let alias = DAVResource(href: URL(string: base.absoluteString + "%61.ics")!, etag: "\"v2\"", data: calendar(task()))
        expect(.duplicateResource) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [one, one]) }
        expect(.duplicateResource) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [one, alias]) }
    }
    func testResourceOriginCredentialsQueryAndCollectionTraversalAreRejected() {
        for url in ["https://evil.example/item.ics", "http://cloud.example/calendars/person/personal/item.ics",
                    "https://person@cloud.example/calendars/person/personal/item.ics", base.absoluteString + "item.ics?token=x",
                    base.absoluteString + "item.ics#fragment", "https://cloud.example/calendars/person/other/item.ics",
                    base.absoluteString + "../other/item.ics", base.absoluteString + "%2e%2e/other/item.ics",
                    base.absoluteString + "%2F..%2Fother/item.ics", base.absoluteString] {
            let input = DAVResource(href: URL(string: url)!, etag: "\"v1\"", data: calendar(event()))
            expect(.resourceOutsideCollection) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [input]) }
        }
    }
    func testInvalidSourceKindOrUIDCannotRebindAResourceList() {
        let valid = source()
        let wrongUID = DAVCollection(uid: "nextcloud-calendar:wrong", name: valid.name, href: valid.href, kind: .calendar, supportsVtodo: true, syncToken: nil)
        let wrongKind = DAVCollection(uid: valid.uid, name: valid.name, href: valid.href, kind: .addressbook, supportsVtodo: true, syncToken: nil)
        expect(.invalidSource) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: wrongUID, resources: [resource(event())]) }
        expect(.invalidSource) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: wrongKind, resources: [resource(event())]) }
    }
    func testSharedWireUIDAcrossResourcesAndDuplicateProjectedTaskAliasesAreAmbiguous() throws {
        expect(.ambiguousWireUID) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event("series"), path: "one.ics"), resource(event("series", "RECURRENCE-ID:20260329T100000Z\n"), path: "two.ics")]) }
        expect(.unsupportedOrMalformedResource) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event() + event())]) }
        let originalUID = "original-task", originalSource = "legacy-source"
        let alias = "urn:magnolie:task:" + hash(originalSource + "\0" + originalUID)
        let identity: [String: Any] = ["v": 1, "source": originalSource, "uid": originalUID, "parent": "", "parentSource": ""]
        let json = String(data: try JSONSerialization.data(withJSONObject: identity), encoding: .utf8)!.replacingOccurrences(of: ",", with: "\\,")
        expect(.duplicateProjection) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(task(originalUID), path: "one.ics"), resource(task(alias, "X-MAGNOLIE-TASK-IDENTITY:\(json)\n"), path: "two.ics")]) }
    }
    func testUnsupportedTasksAreExplicitAndSupportedEmptyTaskScopeIsDistinct() throws {
        let unsupported = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(tasks: false), resources: [resource(event())])
        XCTAssertNil(unsupported.tasks)
        let supported = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event())])
        XCTAssertEqual(supported.tasks?.count, 0)
        expect(.unsupportedTasks) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(tasks: false), resources: [resource(event() + task())]) }
    }
    func testMalformedMissingUIDAndUnsupportedOpaqueComponentsRejectWholeList() {
        for body in [event().replacingOccurrences(of: "UID:event-one\n", with: ""),
                     event().replacingOccurrences(of: "DTSTART:20260328T100000Z", with: "DTSTART:invalid"),
                     event() + "BEGIN:VJOURNAL\nUID:opaque\nEND:VJOURNAL\n",
                     event().replacingOccurrences(of: "END:VEVENT\n", with: "")] {
            expect(.unsupportedOrMalformedResource) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event("valid"), path: "valid.ics"), resource(body, path: "invalid.ics")]) }
        }
    }
    func testAggregateByteResourceRecordAndProjectionBoundsAreAllOrNothing() {
        let one = resource(event()), two = resource(event("second"), path: "second.ics")
        expect(.byteLimit) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [one, two], limits: .init(maximumBytes: one.data.utf8.count)) }
        expect(.resourceLimit) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [one, two], limits: .init(maximumResources: 1)) }
        expect(.recordLimit) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event() + task())], limits: .init(maximumRecords: 1)) }
        expect(.projectionLimit) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [one], limits: .init(maximumProjectedBytes: 1)) }
        expect(.invalidLimits) { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [one], limits: .init(maximumBytes: 0)) }
    }
    func testCancellationBeforeParsingAndBetweenProjectedRecordsReturnsNoPrefix() {
        do { _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event())], cancellation: { true }); XCTFail("Expected cancellation") }
        catch is CancellationError { } catch { XCTFail("Unexpected cancellation error") }
        var calls = 0
        do {
            _ = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [resource(event() + task())], cancellation: { calls += 1; return calls >= 6 })
            XCTFail("Expected cancellation during record projection")
        } catch is CancellationError { } catch { XCTFail("Unexpected cancellation error") }
        XCTAssertGreaterThanOrEqual(calls, 6)
    }
    func testEmptyCompletedReportProducesNoInitializationOrSyncSuccessMarker() throws {
        let result = try Snapshot.decode(context: try CalendarTestContext.make(), source: source(), resources: [])
        XCTAssertTrue(result.resources.isEmpty); XCTAssertTrue(result.appointments.isEmpty)
        XCTAssertEqual(result.tasks?.count, 0); XCTAssertTrue(result.anniversaries.isEmpty)
        XCTAssertEqual(result.byteCount, 0); XCTAssertEqual(result.projectedByteCount, 0)
        // Result intentionally has no cursor, initialized flag, sync marker or remote-mutation API.
    }
}
