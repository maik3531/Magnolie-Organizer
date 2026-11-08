import Foundation
import XCTest
@testable import BetaCore

final class CalendarInterchangeTests: XCTestCase {
    func testStructuredSeriesAndExcludedDaysRemainARecurrence() throws {
        let record: [String: Any] = ["uid": "weekly", "titel": "Weekly", "datum": "2026-03-23", "zeit": "",
            "wiederholung": ["art": "weekly", "bis": "2026-04-30", "intervall": 2], "icsAusnahmen": ["2026-04-06"]]
        let text = try ICalendarExport.encode([record], kind: .appointments)
        XCTAssertTrue(text.contains("RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20260430\r\n"))
        XCTAssertTrue(text.contains("EXDATE;VALUE=DATE:20260406\r\n"))
        XCTAssertEqual(text.components(separatedBy: "BEGIN:VEVENT").count - 1, 1, "Do not flatten a series into occurrences")
        XCTAssertTrue(text.contains("DTEND;VALUE=DATE:20260324\r\n"))
    }

    func testDueOnlyTaskCannotSilentlyDiscardStructuredRecurrence() throws {
        let dueOnly: [String: Any] = ["uid": "due-task", "titel": "Task", "faellig": "2026-04-01", "wiederholung": ["art": "daily"]]
        XCTAssertThrowsError(try ICalendarExport.encode([dueOnly], kind: .tasks))
        var noRepeat = dueOnly
        noRepeat["wiederholung"] = ["art": "none"]
        let oneOff = try ICalendarExport.encode([noRepeat], kind: .tasks)
        XCTAssertTrue(oneOff.contains("DUE;VALUE=DATE:20260401"))
        XCTAssertFalse(oneOff.contains("RRULE:"))
        var recurring = dueOnly
        recurring["startDatum"] = "2026-03-31"
        let repeated = try ICalendarExport.encode([recurring], kind: .tasks)
        XCTAssertTrue(repeated.contains("DTSTART;VALUE=DATE:20260331"))
        XCTAssertTrue(repeated.contains("RRULE:FREQ=DAILY"))
        for malformed in ["daily", ["art": 7], ["art": "none", "unknown": "field"], ["art": "none", "intervall": 2]] as [Any] {
            var invalid = dueOnly
            invalid["wiederholung"] = malformed
            XCTAssertThrowsError(try ICalendarExport.encode([invalid], kind: .tasks))
        }
    }

    func testSubtaskExternalIdentityAndCompletionArePreserved() throws {
        let parent: [String: Any] = ["uid": "internal-parent", "icsImportUid": "external-parent", "titel": "Parent", "prio": 1]
        let child: [String: Any] = ["uid": "child", "titel": "Child", "elternUid": "internal-parent", "faellig": "2026-04-01",
                                    "prio": 3, "erledigt": true, "erinnern": true, "individuelleErinnerungTage": 3]
        let text = try ICalendarExport.encode([parent, child], kind: .tasks)
        XCTAssertTrue(text.contains("UID:external-parent\r\n"))
        XCTAssertTrue(text.contains("RELATED-TO;RELTYPE=PARENT:external-parent\r\n"))
        XCTAssertTrue(text.contains("BEGIN:VTODO\r\n"))
        XCTAssertTrue(text.contains("DUE;VALUE=DATE:20260401\r\n"))
        XCTAssertTrue(text.contains("STATUS:COMPLETED\r\nPERCENT-COMPLETE:100\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-ERINNERUNG-AM-TAG:1\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-TASK-IDENTITY:"))
    }

    func testYearlessLeapAnniversaryHasAnExplicitDateExtension() throws {
        let record: [String: Any] = ["uid": "yearless", "name": "Leap birthday", "datum": "--02-29", "typ": "birthday"]
        let text = try ICalendarExport.encode([record], kind: .anniversaries)
        XCTAssertTrue(text.contains("DTSTART;VALUE=DATE:20000229\r\n"))
        XCTAssertTrue(text.contains("RRULE:FREQ=YEARLY\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-DATE:--02-29\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-JAHRESTAG-TYP:birthday\r\n"))
        var invalid = record; invalid["datum"] = "--02-30"
        XCTAssertThrowsError(try ICalendarExport.encode([invalid], kind: .anniversaries))
    }

    func testRawClocksAndUnknownSourcePropertiesStayAuthoritative() throws {
        let record: [String: Any] = ["uid": "master", "icsSerienUid": "source-series", "titel": "Serie", "datum": "2026-03-28",
            "zeit": "09:00", "endZeit": "10:00", "icsAnzeigeZeitzone": "UTC", "wiederholung": ["art": "none", "bis": ""],
            "icsRoundtrip": ["DTSTART;TZID=Europe/Berlin:20260328T100000", "DTEND;TZID=Europe/Berlin:20260328T110000",
                             "RRULE:FREQ=DAILY;COUNT=4", "RDATE;TZID=Europe/Berlin:20260402T100000", "EXDATE;TZID=Europe/Berlin:20260330T100000",
                             "X-EXAMPLE-META;X-TOKEN=alpha:opaque-value", "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", "END:VALARM"]]
        let text = try ICalendarExport.encode([record], kind: .appointments)
        for line in record["icsRoundtrip"] as! [String] { XCTAssertTrue(text.contains(line + "\r\n"), line) }
        XCTAssertTrue(text.contains("UID:source-series\r\n"))
        XCTAssertTrue(text.contains("BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\n"))
        var stale = record; stale["zeit"] = "10:00"
        XCTAssertThrowsError(try ICalendarExport.encode([stale], kind: .appointments))
        var loss = record; loss["unrecognizedProviderState"] = ["keep": true]
        XCTAssertThrowsError(try ICalendarExport.encode([loss], kind: .appointments))
        var injection = record; injection["icsRoundtrip"] = ["SUMMARY:Safe\r\nBEGIN:VEVENT"]
        XCTAssertThrowsError(try ICalendarExport.encode([injection], kind: .appointments))
    }

    func testInvalidRulesAndDSTGapsAreRefused() throws {
        let record: [String: Any] = ["uid": "gap", "titel": "Gap", "datum": "2026-03-29", "zeit": "02:30", "endZeit": "03:30",
                                    "icsAnzeigeZeitzone": "Europe/Berlin", "wiederholung": ["art": "daily", "bis": ""]]
        XCTAssertThrowsError(try ICalendarExport.encode([record], kind: .appointments))
        var floating: [String: Any] = ["uid": "rule", "titel": "Rule", "datum": "2026-03-28", "zeit": "10:00", "endZeit": "11:00"]
        for rule in ["FREQ=DAILY;COUNT=4;UNTIL=20260430T100000", "FREQ=DAILY;BYHOUR=25", "FREQ=DAILY;COUNT=0", "FREQ=DAILY;BYDAY=0MO", "FREQ=DAILY;FREQ=WEEKLY"] {
            floating["icsRoundtrip"] = ["RRULE:" + rule]
            XCTAssertThrowsError(try ICalendarExport.encode([floating], kind: .appointments), rule)
        }
    }

    func testLiveCanonicalCalendarRecordsAndWriteIndependentOracleInputs() throws {
        guard let fixture = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_FIXTURES"],
              let output = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_OUTPUT"] else {
            throw XCTSkip("Run tools/check_calendar.py --swift for current desktop codec roundtrips.")
        }
        let bytes = try Data(contentsOf: URL(fileURLWithPath: fixture))
        let cases = try XCTUnwrap(try JSONSerialization.jsonObject(with: bytes) as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(cases.count, 8)
        for item in cases {
            let name = try XCTUnwrap(item["name"] as? String)
            let kind = try XCTUnwrap(ICalendarExport.Kind(rawValue: item["kind"] as? String ?? ""))
            let records = try XCTUnwrap(item["records"] as? [[String: Any]])
            let text = try ICalendarExport.encode(records, kind: kind)
            let file = URL(fileURLWithPath: output).appendingPathComponent(name + ".ics")
            try Data(text.utf8).write(to: file, options: [.atomic])
            XCTAssertTrue(text.hasPrefix("BEGIN:VCALENDAR\r\n"))
            XCTAssertTrue(text.hasSuffix("END:VCALENDAR\r\n"))
            for line in text.components(separatedBy: "\r\n") { XCTAssertLessThanOrEqual(line.utf8.count, 75) }
        }
    }
}
