import Foundation
import XCTest
@testable import BetaCore

final class ICalendarImportTests: XCTestCase {
    private func data(_ body: String) -> Data { Data(("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + body + "END:VCALENDAR\r\n").utf8) }
    private let event = "BEGIN:VEVENT\r\nUID:public\r\nDTSTART:20260328T100000Z\r\nDTEND:20260328T110000Z\r\nSUMMARY:Public item\r\nEND:VEVENT\r\n"
    func testUnfoldingUnknownFieldsAndWrapperMetadataArePreserved() throws {
        let body = "X-PROVIDER-CALENDAR;X-PARAM=opaque:keep\r\nBEGIN:VEVENT\r\nUID:folded\r\nDTSTART;VALUE=DATE:20260328\r\nSUMMARY:Long \\nlabel\r\nDESCRIPTION:First\\nSecond\\, item\r\nX-OPAQUE;X-TOKEN=alpha:part-\r\n two\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\n"
        let result = try ICalendarImport.decode(data(body), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments.count, 1)
        XCTAssertEqual(result.appointments[0]["notiz"] as? String, "First\nSecond, item")
        let raw = try XCTUnwrap(result.appointments[0]["icsRoundtrip"] as? [String])
        XCTAssertTrue(raw.contains("X-OPAQUE;X-TOKEN=alpha:part-two"))
        XCTAssertTrue(raw.contains("BEGIN:VALARM")); XCTAssertTrue(raw.contains("TRIGGER:-PT15M"))
        XCTAssertTrue(result.calendarProperties.contains("X-PROVIDER-CALENDAR;X-PARAM=opaque:keep"))
        XCTAssertNotNil(result.document["icsImportMetadata"])
        XCTAssertEqual(result.sourceSHA256.count, 64)
    }
    func testInvalidComponentAfterAValidItemThrowsInsteadOfReturningAPrefix() throws {
        for invalid in [
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260230T100000Z\r\nSUMMARY:Bad date\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nUID:other\r\nDTSTART:20260328T100000Z\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260328T100000Z\r\nRRULE:FREQ=DAILY;COUNT=0\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260328T100000Z\r\nEND:VTODO\r\n",
            "BEGIN:VJOURNAL\r\nUID:unsupported\r\nEND:VJOURNAL\r\n"] {
            XCTAssertThrowsError(try ICalendarImport.decode(data(event + invalid), displayTimeZone: "UTC"), invalid)
        }
        XCTAssertThrowsError(try ICalendarImport.decode(Data([0xff, 0xfe, 0xff])))
        XCTAssertThrowsError(try ICalendarImport.decode(Data(repeating: 32, count: ICalendarImport.maximumBytes + 1)))
        XCTAssertThrowsError(try ICalendarImport.decode(data(event + event)))
    }
    func testCustomEmbeddedZoneProjectsCorrectlyWithoutTheOSKnowingItsTZID() throws {
        let zone = "BEGIN:VTIMEZONE\r\nTZID:Private/Test\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
        let body = "BEGIN:VEVENT\r\nUID:private-zone\r\nDTSTART;TZID=Private/Test:20260328T100000\r\nDTEND;TZID=Private/Test:20260328T110000\r\nSUMMARY:Custom source zone\r\nEND:VEVENT\r\n"
        let result = try ICalendarImport.decode(data(zone + body), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments[0]["zeit"] as? String, "04:30")
        XCTAssertEqual(result.appointments[0]["endZeit"] as? String, "05:30")
        XCTAssertEqual((result.appointments[0]["icsTimezones"] as? [[String]])?.first?.first, "BEGIN:VTIMEZONE")
        let conflict = zone.replacingOccurrences(of: "+0530", with: "+0630")
        XCTAssertThrowsError(try ICalendarImport.decode(data(zone + conflict + body), displayTimeZone: "UTC"))
    }
    func testMasterAndExceptionShareTheWireUIDAndKeepRangeSourceBodies() throws {
        let master = "BEGIN:VEVENT\r\nUID:series\r\nDTSTART:20260328T100000Z\r\nDTEND:20260328T110000Z\r\nRRULE:FREQ=DAILY;COUNT=5\r\nSUMMARY:Master\r\nEND:VEVENT\r\n"
        let exception = "BEGIN:VEVENT\r\nUID:series\r\nRECURRENCE-ID;RANGE=THISANDFUTURE:20260330T100000Z\r\nDTSTART:20260330T120000Z\r\nDTEND:20260330T130000Z\r\nSUMMARY:Moved\r\nX-OPAQUE:keep\r\nEND:VEVENT\r\n"
        let result = try ICalendarImport.decode(data(master + exception), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments.count, 2)
        XCTAssertEqual(result.appointments[0]["icsSerienUid"] as? String, "series")
        XCTAssertTrue((result.appointments[1]["uid"] as? String ?? "").hasPrefix("series-magnolie-instanz-"))
        XCTAssertEqual((result.appointments[0]["icsRangeOverrides"] as? [[String]])?.count, 1)
        XCTAssertTrue((result.appointments[0]["icsRoundtrip"] as? [String] ?? []).contains("EXDATE:20260330T100000Z"))
        let output = try ICalendarExport.encode(result.appointments, kind: .appointments, defaultTimeZone: "UTC")
        XCTAssertEqual(output.components(separatedBy: "UID:series\r\n").count - 1, 2)
        XCTAssertTrue(output.contains("RECURRENCE-ID;RANGE=THISANDFUTURE:20260330T100000Z\r\n"))
    }
    func testLiveCanonicalImportAndReexportProduceIndependentOracleFiles() throws {
        guard let fixture = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_FIXTURES"],
              let output = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_OUTPUT"] else {
            throw XCTSkip("Run tools/check_calendar.py --swift to execute the actual canonical parser oracle.")
        }
        let cases = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: fixture))) as? [[String: Any]])
        for item in cases {
            let name = try XCTUnwrap(item["name"] as? String), source = try XCTUnwrap(item["importSource"] as? String)
            let result = try ICalendarImport.decode(Data(source.utf8), displayTimeZone: "UTC")
            let target = URL(fileURLWithPath: output).appendingPathComponent(name + "-imported.json")
            try JSONSerialization.data(withJSONObject: result.document, options: [.sortedKeys]).write(to: target, options: [.atomic])
            let groups: [(String, [[String: Any]], ICalendarExport.Kind)] = [
                ("termine", result.appointments, .appointments), ("aufgaben", result.tasks, .tasks), ("jahrestage", result.anniversaries, .anniversaries)]
            for (group, records, kind) in groups where !records.isEmpty {
                let text = try ICalendarExport.encode(records, kind: kind, defaultTimeZone: "UTC")
                let file = URL(fileURLWithPath: output).appendingPathComponent(name + "-reimport-" + group + ".ics")
                try Data(text.utf8).write(to: file, options: [.atomic])
            }
        }
    }
}
