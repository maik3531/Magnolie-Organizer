import Foundation
import XCTest
@testable import BetaCore

final class ICalendarResourcePatchTests: XCTestCase {
    typealias Patch = ICalendarResourcePatch
    private func calendar(_ body: String) -> Data {
        Data(("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-OPAQUE;TOKEN=one:two\r\n" + body + "END:VCALENDAR\r\n").utf8)
    }
    private func event(_ uid: String, _ extra: String = "", kind: String = "VEVENT") -> String {
        "BEGIN:\(kind)\r\nUID:\(uid)\r\nDTSTART:20260328T100000Z\r\nSUMMARY:Original\r\n\(extra)END:\(kind)\r\n"
    }
    private let zone = "BEGIN:VTIMEZONE\r\nTZID:Example/Zone\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0100\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
    func testSurgicalUpdatePreservesAllOtherBytesAndCanonicalRecords() throws {
        let sibling = event("two", "X-RAW:folded-\r\n\tvalue\r\n"), task = event("task", kind: "VTODO")
        let opaque = "BEGIN:X-PRIVATE\r\nX-FIELD:opaque\r\nEND:X-PRIVATE\r\n"
        let first = event("one", "RRULE:FREQ=DAILY;COUNT=3\r\nEXDATE:20260329T100000Z\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n")
        let original = calendar(zone + first + sibling + task + opaque)
        let changed = first.replacingOccurrences(of: "SUMMARY:Original", with: "SUMMARY:Changed")
        let result = try Patch.apply(original: original, replacements: [.init(key: .init(kind: "VEVENT", uid: "one"), calendar: calendar(changed))])
        XCTAssertEqual(result.data, calendar(zone + changed + sibling + task + opaque))
        XCTAssertFalse(result.safeCanDeleteResource)
        let before = try ICalendarImport.decode(calendar(first + sibling + task), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        let after = try ICalendarImport.decode(calendar(changed + sibling + task), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        XCTAssertEqual(before.appointments.count, after.appointments.count)
        XCTAssertEqual(before.tasks.count, after.tasks.count)
        XCTAssertEqual(after.appointments.first?["titel"] as? String, "Changed")
    }
    func testExactOverrideDeletionAndExplicitInsertion() throws {
        let master = event("series", "RRULE:FREQ=DAILY\r\nRDATE:20260401T100000Z\r\n")
        let override = event("series", "RECURRENCE-ID;RANGE=THISANDFUTURE;VALUE=DATE-TIME:20260329T100000Z\r\n")
        let original = calendar(master + override)
        let deleted = try Patch.apply(original: original, replacements: [], deletions: [.init(kind: "VEVENT", uid: "series", recurrenceID: "RECURRENCE-ID:20260329T100000Z")])
        XCTAssertEqual(deleted.data, calendar(master)); XCTAssertFalse(deleted.safeCanDeleteResource)
        let new = event("new")
        let inserted = try Patch.apply(original: deleted.data, replacements: [], insertions: [.init(key: .init(kind: "VEVENT", uid: "new"), calendar: calendar(new))])
        XCTAssertEqual(inserted.data, calendar(master + new))
        XCTAssertThrowsError(try Patch.apply(original: original, replacements: [.init(key: .init(kind: "VEVENT", uid: "new"), calendar: calendar(new))]))
        XCTAssertThrowsError(try Patch.apply(original: original, replacements: [], insertions: [.init(key: .init(kind: "VEVENT", uid: "series"), calendar: calendar(master))]))
    }
    func testDeletionSafetyNeverDeletesOpaqueSibling() throws {
        let key = Patch.Key(kind: "VEVENT", uid: "one")
        let empty = try Patch.apply(original: calendar(zone + event("one")), replacements: [], deletions: [key])
        XCTAssertTrue(empty.safeCanDeleteResource); XCTAssertEqual(empty.data, calendar(zone))
        let opaque = "BEGIN:VJOURNAL\r\nUID:unselected\r\nEND:VJOURNAL\r\n"
        XCTAssertFalse(try Patch.apply(original: calendar(event("one") + opaque), replacements: [], deletions: [key]).safeCanDeleteResource)
        XCTAssertThrowsError(try Patch.apply(original: calendar(""), replacements: [], deletions: [key]))
    }
    func testAmbiguityMismatchAndMalformedInputFailAtomically() throws {
        let key = Patch.Key(kind: "VEVENT", uid: "one")
        XCTAssertThrowsError(try Patch.keys(from: calendar(event("one") + event("one"))))
        let a = event("series", "RECURRENCE-ID;TZID=\"Europe/Berlin\";VALUE=DATE-TIME:20260329T120000\r\n")
        let b = event("series", "RECURRENCE-ID;RANGE=THISANDFUTURE;tzid=Europe/Berlin:20260329T120000\r\n")
        XCTAssertThrowsError(try Patch.keys(from: calendar(a + b)))
        XCTAssertEqual(try Patch.keys(from: calendar(a)), try Patch.keys(from: calendar(b)))
        let utc = event("series", "RECURRENCE-ID:20260329T100000Z\r\n")
        XCTAssertEqual(try Patch.keys(from: calendar(a + utc)).count, 2)
        XCTAssertThrowsError(try Patch.apply(original: calendar(event("one")), replacements: [.init(key: key, calendar: calendar(event("wrong")))]))
        XCTAssertThrowsError(try Patch.apply(original: calendar(event("one")), replacements: [], deletions: [key, key]))
        let malformed = Data("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VCALENDAR\r\n".utf8)
        XCTAssertThrowsError(try Patch.apply(original: malformed, replacements: []))
        XCTAssertThrowsError(try Patch.keys(from: Data("BEGIN:VCALENDAR\rEND:VCALENDAR\r".utf8)))
    }
    func testBatchExtractionPreservesWrapperZonesAndExactSelectedComponentBytes() throws {
        let one=event("one", "X-OPAQUE:folded-\r\n\tvalue\r\n"), two=event("two"), todo=event("task",kind:"VTODO")
        let original=calendar(zone+one+two+todo)
        let selected=[Patch.Key(kind:"VEVENT",uid:"one"),Patch.Key(kind:"VTODO",uid:"task")]
        let extracted=try Patch.extract(original:original,keys:selected)
        XCTAssertEqual(extracted.count,2)
        XCTAssertEqual(extracted[selected[0]],calendar(zone+one))
        XCTAssertEqual(extracted[selected[1]],calendar(zone+todo))
        XCTAssertEqual(original,calendar(zone+one+two+todo))
        XCTAssertEqual(try Patch.keys(from:extracted[selected[0]]!),[selected[0]])
    }
    func testBatchExtractionDuplicateUnknownMalformedAndAggregateLimitsRejectAtomically() throws {
        let key=Patch.Key(kind:"VEVENT",uid:"one"), original=calendar(zone+event("one")+event("two"))
        XCTAssertThrowsError(try Patch.extract(original:original,keys:[key,key]))
        XCTAssertThrowsError(try Patch.extract(original:original,keys:[key,.init(kind:"VEVENT",uid:"missing")]))
        XCTAssertThrowsError(try Patch.extract(original:original,keys:[key],maximumOutputBytes:1))
        XCTAssertThrowsError(try Patch.extract(original:original,keys:[key],maximumOutputBytes:0))
        XCTAssertThrowsError(try Patch.extract(original:Data("broken".utf8),keys:[key]))
        XCTAssertTrue(try Patch.extract(original:original,keys:[]).isEmpty)
        let rid="RECURRENCE-ID;TZID=Europe/Berlin:20260329T120000"
        let recurring=calendar(event("series",rid+"\r\n"))
        XCTAssertThrowsError(try Patch.extract(original:recurring,keys:[.init(kind:"VEVENT",uid:"series",recurrenceID:rid),
            .init(kind:"VEVENT",uid:"series",recurrenceID:"RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=\"Europe/Berlin\";VALUE=DATE-TIME:20260329T120000")]))
    }
    func testTimezoneAdditionAndConflictAreAtomic() throws {
        let original = calendar(zone + event("one"))
        let key = Patch.Key(kind: "VEVENT", uid: "one")
        XCTAssertEqual(try Patch.apply(original: original, replacements: [.init(key: key, calendar: calendar(zone + event("one")))]).data, original)
        let changedZone = zone.replacingOccurrences(of: "+0100", with: "+0200")
        XCTAssertThrowsError(try Patch.apply(original: original, replacements: [.init(key: key, calendar: calendar(changedZone + event("one")))]))
        let newZone = zone.replacingOccurrences(of: "Example/Zone", with: "Example/New")
        let result = try Patch.apply(original: original, replacements: [.init(key: key, calendar: calendar(newZone + event("one")))])
        XCTAssertEqual(result.data, calendar(zone + event("one") + newZone))
    }
    func testPublishedParserPatchOracleArtifacts() throws {
        guard let output = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_OUTPUT"] else {
            throw XCTSkip("Published parser oracle runs through tools/check_calendar.py --swift")
        }
        let first = event("one", "RRULE:FREQ=DAILY;COUNT=3\r\nEXDATE:20260329T100000Z\r\n")
        let second = event("two"), task = event("task", kind: "VTODO")
        let before = calendar(first + second + task)
        let replacement = first.replacingOccurrences(of: "SUMMARY:Original", with: "SUMMARY:Changed")
        let after = try Patch.apply(original: before, replacements: [.init(key: .init(kind: "VEVENT", uid: "one"), calendar: calendar(replacement))])
        let expected = calendar(replacement + second + task)
        for (name, data) in [("patch-before", before), ("patch-after", after.data), ("patch-expected", expected)] {
            try data.write(to: URL(fileURLWithPath: output).appendingPathComponent(name + ".ics"), options: [.atomic])
        }
    }

    func testAdversarialPhysicalLogicalAndUnfoldedLineBounds() throws {
        // All inputs remain well below the whole-resource limit. Scanner must
        // reject them before creating an unbounded array or unfolded String.
        let newlines = Data(repeating: 10, count: 250_001)
        XCTAssertThrowsError(try Patch.keys(from: newlines))
        let tinyProperties = String(repeating: "X:A\n", count: 250_001)
        XCTAssertThrowsError(try Patch.keys(from: calendar(tinyProperties)))
        let oversized = "X:" + String(repeating: "a", count: 1024 * 1024) + "\r\n"
        XCTAssertThrowsError(try Patch.keys(from: calendar(oversized)))
        let folded = "X:" + String(repeating: "a", count: 512 * 1024) + "\r\n " +
            String(repeating: "b", count: 512 * 1024) + "\r\n"
        XCTAssertThrowsError(try Patch.keys(from: calendar(folded)))
        let boundedFold = "X:" + String(repeating: "a", count: 1024) + "\r\n\t" + String(repeating: "b", count: 1024) + "\r\n"
        let valid = calendar(boundedFold + event("one"))
        XCTAssertEqual(try Patch.apply(original: valid, replacements: []).data, valid)
    }

}
