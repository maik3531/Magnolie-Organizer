import Foundation
import XCTest
@testable import BetaCore

final class SystemSourceSnapshotTests: XCTestCase {
    private func source(_ kind: SystemSourcePolicy.Kind = .events, id: String = "one", type: String = "calendar:0", readOnly: Bool = false, permission: String = "authorized") throws -> SystemSourceSnapshot.Source {
        try .init(uid: SystemSourcePolicy.uid(kind, id), kind: kind, title: "Synthetic source", parentUID: "opaque-account", nativeType: type, permission: permission, readOnly: readOnly)
    }
    private func fields() -> [String: Any] {
        ["title": "One-off 🌼", "notes": "Keep original", "location": "Room", "start": 1_767_225_600.0, "end": 1_767_229_200.0,
         "allDay": false, "timeZone": "UTC", "recurring": false, "isDetached": false, "alarms": [[String: Any]](),
         "recurrenceRules": [[String: Any]](), "attendeeCount": 0, "hasOrganizer": false, "opaquePublic": ["retain": [true, NSNull()]]]
    }
    func testBoundedWindowCanNeverClaimCompleteOrDeletionAuthority() throws {
        let source = try source(), start = Date(timeIntervalSince1970: 0), end = Date(timeIntervalSince1970: 86400)
        let snapshot = try SystemSourceSnapshot(source: source, scope: .boundedWindow(start: start, end: end), records: [])
        XCTAssertFalse(snapshot.authorizesAbsenceDeletion)
        XCTAssertThrowsError(try SystemSourceSnapshot(source: source, scope: .fullSource, records: []))
        XCTAssertThrowsError(try SystemSourceSnapshot(source: source, scope: .boundedWindow(start: end, end: start), records: []))
        let reminders = try self.source(.reminders)
        XCTAssertFalse(try SystemSourceSnapshot(source: reminders, scope: .fullSource, records: []).authorizesAbsenceDeletion)
        XCTAssertThrowsError(try SystemSourceSnapshot(source: reminders, scope: .boundedWindow(start: start, end: end), records: []))
        XCTAssertThrowsError(try SystemSourceSnapshot(source: self.source(permission: "denied"), scope: .boundedWindow(start: start, end: end), records: []))
    }
    func testSourceQualifiedOccurrenceKeysAndUnsupportedNativeIdentity() throws {
        let source = try source(), other = try self.source(id: "other"), date = Date(timeIntervalSince1970: 100)
        let first = try SystemSourceSnapshot.Record(source: source, identifier: "same", occurrenceDate: date, fields: fields())
        let next = try SystemSourceSnapshot.Record(source: source, identifier: "same", occurrenceDate: date.addingTimeInterval(1), fields: fields())
        let window = SystemSourceSnapshot.Scope.boundedWindow(start: date, end: date.addingTimeInterval(86400))
        XCTAssertNoThrow(try SystemSourceSnapshot(source: source, scope: window, records: [first, next]))
        XCTAssertThrowsError(try SystemSourceSnapshot(source: source, scope: window, records: [first, first]))
        XCTAssertThrowsError(try SystemSourceSnapshot(source: other, scope: window, records: [first]))
        let unsaved = try SystemSourceSnapshot.Record(source: source, identifier: nil, fields: fields())
        guard case .unsupported(let retained, let reasons) = try SystemRecordNormalizer.project(unsaved, source: source, displayTimeZone: "UTC") else { return XCTFail("Never invent a native ID") }
        XCTAssertNil(retained.identifier); XCTAssertTrue(reasons.contains("native-identifier-unavailable"))
    }
    func testNarrowOneOffDraftPreservesNativeMetadataAndRejectsRichProjection() throws {
        let source = try source(readOnly: true), raw = fields()
        let record = try SystemSourceSnapshot.Record(source: source, identifier: "native-original", fields: raw)
        guard case .draft(let draft) = try SystemRecordNormalizer.project(record, source: source, displayTimeZone: "UTC") else { return XCTFail("Simple one-off should project") }
        XCTAssertEqual(draft["titel"] as? String, "One-off 🌼")
        XCTAssertEqual(draft["nativeSourceReadOnly"] as? Bool, true)
        let metadata = try XCTUnwrap(draft["nativeSystemRecord"] as? [String: Any])
        XCTAssertEqual(metadata["identifier"] as? String, "native-original")
        XCTAssertEqual(metadata["revisionCoverage"] as? String, "serialized-fields-only")
        XCTAssertEqual(try Document.encode(metadata["fields"]!), try Document.encode(raw))
        for patch in [["recurring": true], ["isDetached": true], ["alarms": [["relativeOffset": -900]]], ["attendeeCount": 1]] as [[String: Any]] {
            var rich = raw; rich.merge(patch) { _, incoming in incoming }
            let item = try SystemSourceSnapshot.Record(source: source, identifier: "native-original", fields: rich)
            guard case .unsupported(let retained, _) = try SystemRecordNormalizer.project(item, source: source, displayTimeZone: "UTC") else { return XCTFail("Do not flatten native metadata") }
            XCTAssertEqual(try Document.encode(retained.fields), try Document.encode(rich))
        }
    }
    func testSnapshotBudgetsRejectOversizeAndNonJSONBeforeFreezing() throws {
        let source = try source()
        XCTAssertThrowsError(try SystemSourceSnapshot.Record(source: source, identifier: "large", fields: ["notes": String(repeating: "a", count: 2 * 1024 * 1024 + 1)]))
        XCTAssertThrowsError(try SystemSourceSnapshot.Record(source: source, identifier: "nodes", fields: ["list": Array(repeating: NSNull(), count: 50_001)]))
        XCTAssertThrowsError(try SystemSourceSnapshot.Record(source: source, identifier: "invalid", fields: ["date": Date()]))
        XCTAssertThrowsError(try SystemSourceSnapshot.Record(source: source, identifier: "invalid", fields: ["number": Double.infinity]))
    }

    func testNativeSnapshotFreezesMutablePublicContainers() throws {
        let source = try source(), nested = NSMutableDictionary(dictionary: ["keep": "original"])
        var raw = fields(); raw["opaquePublic"] = nested
        let record = try SystemSourceSnapshot.Record(source: source, identifier: "stable", fields: raw)
        let revision = record.revision
        nested["keep"] = "changed elsewhere"
        XCTAssertEqual((record.fields["opaquePublic"] as? [String: Any])?["keep"] as? String, "original")
        XCTAssertEqual(record.revision, revision)
    }

    func testAllDayDSTBoundariesAndOccurrenceRemainExplicit() throws {
        let source = try source(), parser = ISO8601DateFormatter()
        var raw = fields()
        raw["allDay"] = true; raw["timeZone"] = "Europe/Berlin"
        raw["start"] = parser.date(from: "2026-03-28T23:00:00Z")!.timeIntervalSince1970
        raw["end"] = parser.date(from: "2026-03-29T22:00:00Z")!.timeIntervalSince1970
        let item = try SystemSourceSnapshot.Record(source: source, identifier: "all-day", fields: raw)
        guard case .draft(let draft) = try SystemRecordNormalizer.project(item, source: source, displayTimeZone: "America/New_York") else { return XCTFail("Explicit source-zone all-day should project") }
        XCTAssertEqual(draft["datum"] as? String, "2026-03-29")
        XCTAssertEqual(draft["endDatum"] as? String, "2026-03-29")
        XCTAssertEqual(draft["zeit"] as? String, "")
        raw["timeZone"] = NSNull()
        let floating = try SystemSourceSnapshot.Record(source: source, identifier: "all-day", fields: raw)
        guard case .unsupported = try SystemRecordNormalizer.project(floating, source: source, displayTimeZone: "UTC") else { return XCTFail("Do not guess a native all-day timezone") }
    }

    func testYearlessNonGregorianAndDateComponentAbsenceAreExact() throws {
        var birthday = DateComponents(); birthday.calendar = Calendar(identifier: .gregorian); birthday.month = 2; birthday.day = 29
        let raw = try XCTUnwrap(SystemDateComponents.fields(birthday))
        XCTAssertNil(raw["year"]); XCTAssertNil(raw["hour"]); XCTAssertNil(raw["timeZone"])
        XCTAssertEqual(raw["month"] as? Int, 2); XCTAssertEqual(raw["day"] as? Int, 29)
        var lunar = birthday; lunar.calendar = Calendar(identifier: .chinese); lunar.isLeapMonth = true
        let lunarRaw = try XCTUnwrap(SystemDateComponents.fields(lunar))
        XCTAssertEqual(lunarRaw["calendar"] as? String, "chinese"); XCTAssertEqual(lunarRaw["isLeapMonth"] as? Bool, true)
        var midnight = birthday; midnight.hour = 0; midnight.minute = 0; midnight.timeZone = TimeZone(identifier: "Europe/Berlin")
        XCTAssertNotEqual(try Document.encode(raw), try Document.encode(SystemDateComponents.fields(midnight)!))
        XCTAssertEqual(try source(.contacts, type: "container:1", readOnly: false).readOnly, true)
        XCTAssertEqual(try source(type: "birthday", readOnly: false).readOnly, true)
    }
}
