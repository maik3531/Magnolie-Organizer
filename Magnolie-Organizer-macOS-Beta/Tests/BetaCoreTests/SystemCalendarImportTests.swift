import Foundation
import XCTest
#if canImport(EventKit)
import EventKit
#endif
@testable import BetaCore

final class SystemCalendarImportTests: XCTestCase {
    private func source(id: String = "calendar-one", title: String = "Selected calendar", parent: String? = "native-account-one",
                        readOnly: Bool = false, type: String = "calendar:0") throws -> SystemSourceSnapshot.Source {
        try .init(uid: SystemSourcePolicy.uid(.events, id), kind: .events, title: title,
                  parentUID: parent, parentTitle: "Account", parentType: "source:2",
                  nativeType: type, permission: "authorized", readOnly: readOnly)
    }
    private func date(_ value: String) -> Date { ISO8601DateFormatter().date(from: value)! }
    private func fields(_ patch: [String: Any] = [:]) -> [String: Any] {
        var result: [String: Any] = ["title": "Native appointment 🌼", "notes": "Exact native text", "location": "Room",
            "start": date("2026-03-28T10:00:07Z").timeIntervalSince1970,
            "end": date("2026-03-28T11:00:29Z").timeIntervalSince1970,
            "allDay": false, "timeZone": "Europe/Berlin", "recurring": false, "isDetached": false,
            "alarms": [[String: Any]](), "recurrenceRules": [[String: Any]](), "attendeeCount": 0, "hasOrganizer": false,
            "status": 1, "availability": 0, "url": NSNull(), "metadataIncomplete": ["provider-opaque-fields"]]
        result.merge(patch) { _, next in next }; return result
    }
    private func record(_ source: SystemSourceSnapshot.Source, id: String? = "native-event-one", occurrence: Date? = nil,
                        patch: [String: Any] = [:], unsupported: [String] = []) throws -> SystemSourceSnapshot.Record {
        try .init(source: source, identifier: id, occurrenceDate: occurrence, fields: fields(patch), unsupported: unsupported)
    }
    private func snapshot(_ source: SystemSourceSnapshot.Source, _ records: [SystemSourceSnapshot.Record],
                          start: String = "2026-01-01T00:00:00Z", end: String = "2027-01-01T00:00:00Z") throws -> SystemSourceSnapshot {
        try .init(source: source, scope: .boundedWindow(start: date(start), end: date(end)), records: records)
    }
    private func prepare(_ snapshot: SystemSourceSnapshot, zone: String = "Europe/Berlin") throws -> SystemCalendarImport.Plan {
        try SystemCalendarImport.prepare(snapshot, context: CalendarTestContext.make(systemIdentifier: "UTC"), displayTimeZone: zone)
    }
    private func lines(_ plan: SystemCalendarImport.Plan, index: Int = 0) throws -> [String] {
        try XCTUnwrap(plan.appointments[index]["icsRoundtrip"] as? [String])
    }
    private func provenance(_ plan: SystemCalendarImport.Plan, index: Int = 0) throws -> [String: Any] {
        try XCTUnwrap(plan.appointments[index]["nativeCalendarImport"] as? [String: Any])
    }

    func testExplicitCommandHasNoFilePathOrImportedAuthorization() throws {
        XCTAssertNoThrow(try Request(#"{"cmd":"macos_kalender_importieren"}"#))
        for text in [#"{"cmd":"macos_kalender_importieren","sourceUID":"arbitrary"}"#,
                     #"{"cmd":"macos_kalender_importieren","pfad":"/unselected"}"#,
                     #"{"cmd":"macos_kalender_importieren","authorized":true}"#] {
            XCTAssertThrowsError(try Request(text))
        }
    }

    func testCopyUsesCanonicalCodecAndPreservesRawPublicFieldsWithoutSyncAuthority() throws {
        let source = try source(readOnly: true)
        let text = "Exact ;,\\ text\nBEGIN:VEVENT\nSUMMARY:still part of the note\n🌼 e\u{301}"
        let original = try record(source, patch: ["notes": text, "availability": 1, "url": "https://example.org/event?x=1&y=2",
                                                  "opaquePublicField": ["keep": [true, NSNull()]]])
        let read = try snapshot(source, [original]), plan = try prepare(read)
        XCTAssertEqual(plan.appointments.count, 1); XCTAssertTrue(plan.excluded.isEmpty)
        let item = plan.appointments[0], raw = try lines(plan), origin = try provenance(plan)
        XCTAssertEqual(item["titel"] as? String, "Native appointment 🌼")
        XCTAssertEqual(item["notiz"] as? String, text); XCTAssertEqual(item["ort"] as? String, "Room")
        XCTAssertEqual(item["zeit"] as? String, "11:00"); XCTAssertEqual(item["endZeit"] as? String, "12:00")
        XCTAssertTrue(raw.contains("DTSTART:20260328T100007Z")); XCTAssertTrue(raw.contains("DTEND:20260328T110029Z"))
        XCTAssertTrue(raw.contains("TRANSP:TRANSPARENT")); XCTAssertFalse(raw.contains { $0.hasPrefix("STATUS:") })
        XCTAssertEqual(item["vorlaeufig"] as? Bool, false)
        XCTAssertTrue(raw.contains("URL:https://example.org/event?x=1&y=2"))
        XCTAssertEqual(item["uid"] as? String, "mac-native-copy:" + (origin["identity"] as! String))
        XCTAssertNil(item["id"]); XCTAssertEqual(origin["parentUID"] as? String, source.parentUID)
        XCTAssertEqual(origin["sourceTitle"] as? String, source.title)
        XCTAssertEqual(item["nativeSourceReadOnly"] as? Bool, true)
        XCTAssertEqual(item["sync"] as? Bool, false); XCTAssertEqual(item["syncKalenderUid"] as? String, "")
        XCTAssertEqual(item["icsQuelleId"] as? String, ""); XCTAssertEqual(item["icsQuelleName"] as? String, "")
        XCTAssertTrue((item["syncQuellen"] as? [String: Any])?.isEmpty == true)
        XCTAssertEqual(item["standardErinnerung"] as? Bool, false)
        XCTAssertTrue((item["alarme"] as? [Any])?.isEmpty == true)
        let retained = try XCTUnwrap(item["nativeSystemRecord"] as? [String: Any])
        XCTAssertEqual(retained["kind"] as? String, "events")
        XCTAssertEqual(retained["revisionCoverage"] as? String, "serialized-fields-only")
        XCTAssertEqual((retained["fields"] as? [String: Any])?["status"] as? Int, 1)
        XCTAssertEqual(Data(try Document.encode(retained["fields"]!).utf8), Data(try Document.encode(original.fields).utf8))
        XCTAssertEqual(plan.snapshotRevision, try SystemCalendarImport.snapshotRevision(read))
        XCTAssertFalse(read.authorizesAbsenceDeletion)
        XCTAssertNoThrow(try plan.revalidate(read))
    }

    func testTentativeStatusUsesEditableCanonicalFlagAndRetainsOriginalMetadata() throws {
        let source = try source()
        let original = try record(source, patch: ["status": 2])
        let plan = try prepare(snapshot(source, [original]))
        XCTAssertEqual(plan.appointments.count, 1)
        XCTAssertEqual(plan.appointments[0]["vorlaeufig"] as? Bool, true)
        XCTAssertFalse(try lines(plan).contains { $0.hasPrefix("STATUS:") })
        let retained = try XCTUnwrap(plan.appointments[0]["nativeSystemRecord"] as? [String: Any])
        XCTAssertEqual((retained["fields"] as? [String: Any])?["status"] as? Int, 2)
        XCTAssertEqual(retained["revision"] as? String, original.revision)
    }

    func testDSTFoldKeepsBothAbsoluteInstantsDespiteEqualVisibleClock() throws {
        let source = try source()
        let first = try record(source, id: "early", patch: ["start": date("2026-10-25T00:30:07Z").timeIntervalSince1970,
                                                           "end": date("2026-10-25T00:40:09Z").timeIntervalSince1970])
        let second = try record(source, id: "late", patch: ["start": date("2026-10-25T01:30:07Z").timeIntervalSince1970,
                                                           "end": date("2026-10-25T01:40:09Z").timeIntervalSince1970])
        let plan = try prepare(snapshot(source, [first, second]))
        XCTAssertEqual(plan.appointments.count, 2)
        XCTAssertTrue(plan.appointments.allSatisfy { $0["zeit"] as? String == "02:30" })
        let starts = try plan.appointments.map { try XCTUnwrap(($0["icsRoundtrip"] as? [String])?.first { $0.hasPrefix("DTSTART:") }) }
        XCTAssertEqual(Set(starts), ["DTSTART:20261025T003007Z", "DTSTART:20261025T013007Z"])
        let crossing = try record(source, id: "crossing", patch: ["start": date("2026-10-25T00:50:00Z").timeIntervalSince1970,
                                                                "end": date("2026-10-25T01:10:00Z").timeIntervalSince1970])
        let crossed = try prepare(snapshot(source, [crossing]))
        XCTAssertEqual(crossed.appointments.first?["zeit"] as? String, "02:50")
        XCTAssertEqual(crossed.appointments.first?["endZeit"] as? String, "02:10")
        XCTAssertTrue(try lines(crossed).contains("DTEND:20261025T011000Z"))
    }

    func testNativeAllDayZoneAndExclusiveEndSurviveSpringClockChange() throws {
        let source = try source()
        let original = try record(source, patch: ["allDay": true,
            "start": date("2026-03-28T23:00:00Z").timeIntervalSince1970,
            "end": date("2026-03-29T22:00:00Z").timeIntervalSince1970])
        let plan = try prepare(snapshot(source, [original]), zone: "America/New_York")
        XCTAssertEqual(plan.appointments.count, 1)
        XCTAssertEqual(plan.appointments[0]["datum"] as? String, "2026-03-29")
        XCTAssertEqual(plan.appointments[0]["endDatum"] as? String, "")
        XCTAssertEqual(plan.appointments[0]["zeit"] as? String, "")
        XCTAssertEqual(plan.appointments[0]["icsAnzeigeZeitzone"] as? String, "Europe/Berlin")
        XCTAssertTrue(try lines(plan).contains("DTSTART;VALUE=DATE:20260329"))
        XCTAssertTrue(try lines(plan).contains("DTEND;VALUE=DATE:20260330"))
    }

    func testRichUnknownCancelledAndNonCanonicalRecordsRemainVisibleExclusions() throws {
        let source = try source()
        let patches: [[String: Any]] = [
            ["recurring": true], ["isDetached": true], ["alarms": [["relativeOffset": -900]]],
            ["recurrenceRules": [["frequency": 1]]], ["attendeeCount": 1], ["hasOrganizer": true],
            ["status": 3], ["status": 9], ["status": true], ["availability": 2], ["availability": 3],
            ["recurring": 0], ["attendeeCount": true], ["title": NSNull()]]
        let records = try patches.enumerated().map { try record(source, id: "excluded-\($0.offset)", patch: $0.element) }
        let plan = try prepare(snapshot(source, records + [record(source, id: "supported")]))
        XCTAssertEqual(plan.appointments.count, 1); XCTAssertEqual(plan.excluded.count, patches.count)
        let reasons = plan.excluded.flatMap { $0["reasons"] as? [String] ?? [] }
        XCTAssertTrue(reasons.contains("native-event-cancelled"))
        XCTAssertTrue(reasons.contains("native-series-projection-not-lossless"))
        XCTAssertTrue(reasons.contains("native-event-feature-state-unavailable"))
        XCTAssertTrue(reasons.contains("native-event-availability-not-representable"))
        let birthdays = try self.source(type: "birthday")
        XCTAssertEqual(try prepare(snapshot(birthdays, [record(birthdays)])).appointments.count, 0)
    }

    func testMissingIdentityAndDuplicateNativeIdentityCannotBecomeInventedCopies() throws {
        let source = try source()
        let missing = try record(source, id: nil)
        let first = try record(source, id: "ambiguous", occurrence: date("2026-03-28T10:00:00Z"))
        let second = try record(source, id: "ambiguous", occurrence: date("2026-03-29T10:00:00Z"))
        let plan = try prepare(snapshot(source, [missing, first, second]))
        XCTAssertTrue(plan.appointments.isEmpty); XCTAssertEqual(plan.excluded.count, 3)
        XCTAssertEqual(plan.excluded.filter { ($0["reasons"] as? [String])?.contains("native-event-identity-ambiguous") == true }.count, 2)
    }

    func testTextTruncationTrimmingControlsAndSubsecondsAreNeverSilentlyConverted() throws {
        let source = try source()
        let patches: [[String: Any]] = [
            ["location": String(repeating: "a", count: 1001)], ["location": String(repeating: "🌼", count: 501)],
            ["location": " leading"], ["location": "trailing\u{FEFF}"], ["location": "bad\u{7F}control"],
            ["notes": "original\r\nline ending"], ["title": "embedded\rreturn"],
            ["url": "https://example.org/\nSUMMARY:Injected"],
            ["start": date("2026-03-28T10:00:00Z").timeIntervalSince1970 + 0.25]]
        let records = try patches.enumerated().map { try record(source, id: "loss-\($0.offset)", patch: $0.element) }
        let plan = try prepare(snapshot(source, records))
        XCTAssertTrue(plan.appointments.isEmpty); XCTAssertEqual(plan.excluded.count, patches.count)
        let reasons = plan.excluded.flatMap { $0["reasons"] as? [String] ?? [] }
        XCTAssertTrue(reasons.contains("native-event-location-would-change"))
        XCTAssertTrue(reasons.contains("native-event-subsecond-time-not-representable"))
    }

    func testDateOnlyNeedsPositiveWholeDaysAndKnownNativeZone() throws {
        let source = try source(), midnight = date("2026-03-28T23:00:00Z").timeIntervalSince1970
        let patches: [[String: Any]] = [
            ["allDay": true, "start": midnight, "end": midnight],
            ["allDay": true, "start": midnight, "end": midnight + 3600],
            ["allDay": true, "start": midnight, "end": midnight + 23 * 3600, "timeZone": NSNull()],
            ["allDay": true, "start": midnight, "end": midnight + 23 * 3600, "timeZone": "Unavailable/Native"]]
        let records = try patches.enumerated().map { try record(source, id: "date-\($0.offset)", patch: $0.element) }
        let plan = try prepare(snapshot(source, records))
        XCTAssertTrue(plan.appointments.isEmpty); XCTAssertEqual(plan.excluded.count, patches.count)
        let zero = try record(source, id: "zero-duration", patch: ["start": midnight, "end": midnight])
        let zeroPlan = try prepare(snapshot(source, [zero]))
        XCTAssertEqual(zeroPlan.appointments.count, 1); XCTAssertEqual(zeroPlan.appointments[0]["icsNullDauer"] as? Bool, true)
    }

    func testStableCopyIdentityIsSourceBoundButUnaffectedByDateMove() throws {
        let source = try source()
        let old = try record(source, occurrence: date("2026-03-28T10:00:07Z"))
        let moved = try record(source, occurrence: date("2026-03-29T10:00:07Z"), patch: [
            "start": date("2026-03-29T10:00:07Z").timeIntervalSince1970,
            "end": date("2026-03-29T11:00:29Z").timeIntervalSince1970])
        let a = try prepare(snapshot(source, [old])), b = try prepare(snapshot(source, [moved]))
        XCTAssertEqual(a.appointments[0]["uid"] as? String, b.appointments[0]["uid"] as? String)
        XCTAssertNotEqual(a.snapshotRevision, b.snapshotRevision)
        let other = try self.source(id: "another-native-calendar")
        let c = try prepare(snapshot(other, [record(other)]))
        XCTAssertNotEqual(a.appointments[0]["uid"] as? String, c.appointments[0]["uid"] as? String)
        // Protocol identifiers preserve UTF-8, including canonically equivalent spellings.
        let composed = try prepare(snapshot(source, [record(source, id: "caf\u{E9}")]))
        let decomposed = try prepare(snapshot(source, [record(source, id: "cafe\u{301}")]))
        XCTAssertNotEqual(composed.appointments[0]["uid"] as? String, decomposed.appointments[0]["uid"] as? String)
    }

    func testRevalidationIgnoresEnumerationOrderButIncludesExcludedRecordsAndMetadata() throws {
        let source = try source()
        let a = try record(source, id: "a"), excluded = try record(source, id: "b", patch: ["recurring": true])
        let read = try snapshot(source, [a, excluded]), plan = try prepare(read)
        let reordered = try snapshot(source, [excluded, a])
        XCTAssertEqual(plan.snapshotRevision, try SystemCalendarImport.snapshotRevision(reordered))
        XCTAssertNoThrow(try plan.revalidate(reordered))
        XCTAssertThrowsError(try plan.revalidate(snapshot(source, [a])))
        XCTAssertThrowsError(try plan.revalidate(snapshot(source, [a, record(source, id: "b", patch: ["recurring": true, "notes": "changed hidden record"])])))
        XCTAssertThrowsError(try plan.revalidate(snapshot(source, [a, excluded], end: "2026-12-01T00:00:00Z")))
        let accountChanged = try self.source(parent: "other-native-account")
        XCTAssertThrowsError(try plan.revalidate(snapshot(accountChanged, [a, excluded])))
        let permissionChanged = try self.source(readOnly: true)
        XCTAssertThrowsError(try plan.revalidate(snapshot(permissionChanged, [a, excluded])))
        let composed = try self.source(title: "Caf\u{E9}"), decomposed = try self.source(title: "Cafe\u{301}")
        let unicodePlan = try prepare(snapshot(composed, [record(composed)]))
        XCTAssertThrowsError(try unicodePlan.revalidate(snapshot(decomposed, [record(decomposed)])))
    }

    func testEmptySourceAndInvalidContextDoNotAcquireSyncOrDeletionAuthority() throws {
        let source = try source(parent: nil), read = try snapshot(source, [])
        let plan = try prepare(read)
        XCTAssertTrue(plan.appointments.isEmpty); XCTAssertTrue(plan.excluded.isEmpty)
        XCTAssertTrue(plan.source["parentUID"] is NSNull)
        XCTAssertEqual(plan.payload["version"] as? Int, 1)
        XCTAssertFalse(read.authorizesAbsenceDeletion)
        for zone in ["", "system", "Unknown/Zone"] { XCTAssertThrowsError(try prepare(read, zone: zone)) }
        let reminders = try SystemSourceSnapshot.Source(uid: SystemSourcePolicy.uid(.reminders, "reminders"), kind: .reminders,
            title: "Reminders", nativeType: "calendar:0", permission: "authorized", readOnly: false)
        XCTAssertThrowsError(try prepare(SystemSourceSnapshot(source: reminders, scope: .fullSource, records: [])))
    }

    func testCalendarCopyWindowHasItsOwnConservative366DayLimit() throws {
        let source = try source()
        let allowed = try snapshot(source, [], end: "2027-01-02T00:00:00Z")
        XCTAssertNoThrow(try prepare(allowed))
        let tooWide = try snapshot(source, [], end: "2027-01-03T00:00:00Z")
        XCTAssertThrowsError(try prepare(tooWide)) { error in
            XCTAssertEqual(error.localizedDescription, "Select a calendar date range of at most 366 days.")
        }
        XCTAssertThrowsError(try SystemCalendarImport.snapshotRevision(tooWide))
    }

    func testUTF8FoldingPreservesTheExactLogicalLine() throws {
        let original = "DESCRIPTION:" + String(repeating: "🌼 e\u{301}\\n\\,\\;", count: 40)
        let physical = try SystemCalendarImport.folded(original).components(separatedBy: "\r\n")
        XCTAssertGreaterThan(physical.count, 1)
        XCTAssertTrue(physical.allSatisfy { $0.utf8.count <= 75 })
        let unfolded = physical.enumerated().map { $0.offset == 0 ? $0.element : String($0.element.dropFirst()) }.joined()
        XCTAssertEqual(Data(unfolded.utf8), Data(original.utf8))
        XCTAssertTrue(physical.dropFirst().allSatisfy { $0.hasPrefix(" ") })
    }

    func testProjectedPayloadLimitRejectsTheWholeProposalInsteadOfReturningAPrefix() throws {
        let source = try source(), notes = String(repeating: "a", count: 750_000)
        let records = try (0..<12).map { try record(source, id: "large-\($0)", patch: ["notes": notes]) }
        // The input snapshot is under 16 MiB, but preserving the original plus
        // the editable projected text crosses the proposal's independent bound.
        let read = try snapshot(source, records)
        XCTAssertThrowsError(try prepare(read)) { error in
            XCTAssertTrue(error.localizedDescription.contains("16 MiB"))
        }
    }

    #if canImport(EventKit)
    func testSnapshotEnumValuesMatchTheNativeSDK() {
        XCTAssertEqual(EKEventStatus.none.rawValue, 0); XCTAssertEqual(EKEventStatus.confirmed.rawValue, 1)
        XCTAssertEqual(EKEventStatus.tentative.rawValue, 2); XCTAssertEqual(EKEventStatus.canceled.rawValue, 3)
        XCTAssertEqual(EKEventAvailability.notSupported.rawValue, -1)
        XCTAssertEqual(EKEventAvailability.busy.rawValue, 0); XCTAssertEqual(EKEventAvailability.free.rawValue, 1)
        XCTAssertEqual(EKEventAvailability.tentative.rawValue, 2); XCTAssertEqual(EKEventAvailability.unavailable.rawValue, 3)
    }
    #endif
}
