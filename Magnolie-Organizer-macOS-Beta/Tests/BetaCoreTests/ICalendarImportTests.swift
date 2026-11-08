import Foundation
import CryptoKit
import XCTest
@testable import BetaCore

final class ICalendarImportTests: XCTestCase {
    func testNativeImportCommandIsASelectedFileCapability() throws {
        XCTAssertNoThrow(try Request(#"{"cmd":"import","art":"ics"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"import","art":"ics","pfad":"/unselected.ics"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"import","art":"ics","daten":"arbitrary"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"import","art":true}"#))
    }
    private func data(_ body: String) -> Data { Data(("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + body + "END:VCALENDAR\r\n").utf8) }
    private let event = "BEGIN:VEVENT\r\nUID:public\r\nDTSTART:20260328T100000Z\r\nDTEND:20260328T110000Z\r\nSUMMARY:Public item\r\nEND:VEVENT\r\n"
    func testUnfoldingUnknownFieldsAndWrapperMetadataArePreserved() throws {
        let body = "X-PROVIDER-CALENDAR;X-PARAM=opaque:keep\r\nBEGIN:VEVENT\r\nUID:folded\r\nDTSTART;VALUE=DATE:20260328\r\nSUMMARY:Long \\nlabel\r\nDESCRIPTION:First\\nSecond\\, item\r\nX-OPAQUE;X-TOKEN=alpha:part-\r\n two\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\n"
        let result = try ICalendarImport.decode(data(body), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments.count, 1)
        XCTAssertEqual(result.appointments[0]["notiz"] as? String, "First\nSecond, item")
        let raw = try XCTUnwrap(result.appointments[0]["icsRoundtrip"] as? [String])
        XCTAssertTrue(raw.contains("X-OPAQUE;X-TOKEN=alpha:part-two"))
        XCTAssertTrue(raw.contains("BEGIN:VALARM")); XCTAssertTrue(raw.contains("TRIGGER:-PT15M"))
        XCTAssertTrue(result.calendarProperties.contains("X-PROVIDER-CALENDAR;X-PARAM=opaque:keep"))
        XCTAssertNotNil(result.document["icsImportMetadata"])
        XCTAssertEqual(result.sourceSHA256.count, 64)
    }
    func testDealiasedTaskUIDsRemainQualifiedByOriginalSource() throws {
        func task(_ wire: String, source: String, uid: String, parent: String = "") throws -> String {
            let identity = try Document.encode(["v": 1, "source": source, "uid": uid, "parent": parent, "parentSource": source])
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: ",", with: "\\,")
                .replacingOccurrences(of: ";", with: "\\;")
            let digest = SHA256.hash(data: Data((source + "\0" + uid).utf8)).map { String(format: "%02x", $0) }.joined()
            let wireUID = "urn:magnolie:task:" + digest + (wire == "other-wire-alias" ? "-1" : "")
            let relationship = parent.isEmpty ? "" : "RELATED-TO;RELTYPE=PARENT:" + parent + "\r\n"
            return "BEGIN:VTODO\r\nUID:\(wireUID)\r\nSUMMARY:Task\r\n\(relationship)X-MAGNOLIE-TASK-IDENTITY:\(identity)\r\nEND:VTODO\r\n"
        }
        let first = try task("alias-a", source: "source-a", uid: "same-parent")
        let second = try task("alias-b", source: "source-b", uid: "same-parent")
        let childA = try task("child-a", source: "source-a", uid: "same-child", parent: "same-parent")
        let childB = try task("child-b", source: "source-b", uid: "same-child", parent: "same-parent")
        let result = try ICalendarImport.decode(data(first + second + childA + childB), context: try CalendarTestContext.make(), displayTimeZone: "UTC", sourceID: "outer-import")
        XCTAssertEqual(result.tasks.count, 4)
        for source in ["source-a", "source-b"] {
            let tasks = result.tasks.filter { $0["icsQuelleId"] as? String == source }
            XCTAssertEqual(tasks.count, 2)
            let child = try XCTUnwrap(tasks.first { $0["uid"] as? String == "same-child" })
            XCTAssertEqual(child["icsElternUid"] as? String, "same-parent")
            XCTAssertEqual(child["icsElternQuelleId"] as? String, source)
            // Each source separately remains representable by the current exporter.
            let encoded = try ICalendarExport.encode(tasks, context: try CalendarTestContext.make(), kind: .tasks)
            let roundtrip = try ICalendarImport.decode(Data(encoded.utf8), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
            XCTAssertEqual(roundtrip.tasks.count, 2)
            XCTAssertTrue(roundtrip.tasks.allSatisfy { $0["icsQuelleId"] as? String == source })
        }
        let duplicate = try task("other-wire-alias", source: "source-a", uid: "same-parent")
        XCTAssertThrowsError(try ICalendarImport.decode(data(first + duplicate), context: try CalendarTestContext.make(), displayTimeZone: "UTC"))
        XCTAssertThrowsError(try ICalendarImport.decode(data(first + second + duplicate), context: try CalendarTestContext.make(), displayTimeZone: "UTC"))
    }
    func testPhysicalLineBudgetAndUnfoldedSizeAreRejectedBeforeExpansion() throws {
        let newlineFlood = Data(repeating: 10, count: 250_000)
        XCTAssertThrowsError(try ICalendarImport.decode(newlineFlood, context: try CalendarTestContext.make(), displayTimeZone: "UTC")) { error in
            XCTAssertTrue(error.localizedDescription.contains("too many lines"))
        }
        let tinyLines = String(repeating: "X:A\r\n", count: 250_000)
        XCTAssertThrowsError(try ICalendarImport.decode(data(tinyLines), context: try CalendarTestContext.make(), displayTimeZone: "UTC")) { error in
            XCTAssertTrue(error.localizedDescription.contains("too many lines"))
        }
        let hugeFold = "DESCRIPTION:" + String(repeating: "a", count: 512 * 1024) + "\r\n\t" +
            String(repeating: "b", count: 512 * 1024) + "\r\n"
        let oversizedEvent = event.replacingOccurrences(of: "END:VEVENT\r\n", with: hugeFold + "END:VEVENT\r\n")
        XCTAssertThrowsError(try ICalendarImport.decode(data(oversizedEvent), context: try CalendarTestContext.make(), displayTimeZone: "UTC")) { error in
            XCTAssertTrue(error.localizedDescription.contains("content line is too large"))
        }
        let validFold = "DESCRIPTION:first\r\n\tsecond\r\n"
        let validEvent = event.replacingOccurrences(of: "END:VEVENT\r\n", with: validFold + "END:VEVENT\r\n")
        let result = try ICalendarImport.decode(data(validEvent), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments.first?["notiz"] as? String, "firstsecond")
    }
    func testCRLFLFAndMixedTerminatorsUnfoldTabsWithoutAcceptingBareCR() throws {
        let body = event.replacingOccurrences(of: "SUMMARY:Public item\r\n", with:
            "SUMMARY:Public item\r\nDESCRIPTION:Folded \r\n\tsecond piece\r\nX-OPAQUE:part-\r\n\ttwo\r\n")
        let crlf = String(decoding: data(body), as: UTF8.self)
        let lf = crlf.replacingOccurrences(of: "\r\n", with: "\n")
        let mixed = crlf.replacingOccurrences(of: "VERSION:2.0\r\n", with: "VERSION:2.0\n")
        var first: [String: Any]?
        for source in [crlf, lf, mixed] {
            let result = try ICalendarImport.decode(Data(source.utf8), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
            XCTAssertEqual(result.appointments.count, 1)
            let record = result.appointments[0]
            XCTAssertEqual(record["notiz"] as? String, "Folded second piece")
            XCTAssertTrue((record["icsRoundtrip"] as? [String] ?? []).contains("X-OPAQUE:part-two"))
            if let expected = first { XCTAssertTrue(NSDictionary(dictionary: record).isEqual(NSDictionary(dictionary: expected))) }
            else { first = record }
        }
        let embeddedCR = crlf.replacingOccurrences(of: "SUMMARY:Public item", with: "SUMMARY:Public\ritem")
        XCTAssertThrowsError(try ICalendarImport.decode(Data(embeddedCR.utf8), context: try CalendarTestContext.make(), displayTimeZone: "UTC"))
        let trailingCR = crlf.replacingOccurrences(of: "END:VCALENDAR\r\n", with: "END:VCALENDAR\r")
        XCTAssertThrowsError(try ICalendarImport.decode(Data(trailingCR.utf8), context: try CalendarTestContext.make(), displayTimeZone: "UTC"))
    }
    func testInvalidComponentAfterAValidItemThrowsInsteadOfReturningAPrefix() throws {
        for invalid in [
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260230T100000Z\r\nSUMMARY:Bad date\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nUID:other\r\nDTSTART:20260328T100000Z\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260328T100000Z\r\nRRULE:FREQ=DAILY;COUNT=0\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260328T100000Z\r\nEND:VTODO\r\n",
            "BEGIN:VJOURNAL\r\nUID:unsupported\r\nEND:VJOURNAL\r\n"] {
            XCTAssertThrowsError(try ICalendarImport.decode(data(event + invalid), context: try CalendarTestContext.make(), displayTimeZone: "UTC"), invalid)
        }
        XCTAssertThrowsError(try ICalendarImport.decode(Data([0xff, 0xfe, 0xff]), context: try CalendarTestContext.make()))
        XCTAssertThrowsError(try ICalendarImport.decode(Data(repeating: 32, count: ICalendarImport.maximumBytes + 1), context: try CalendarTestContext.make()))
        XCTAssertThrowsError(try ICalendarImport.decode(data(event + event), context: try CalendarTestContext.make()))
    }
    func testCustomEmbeddedZoneProjectsCorrectlyWithoutTheOSKnowingItsTZID() throws {
        let zone = "BEGIN:VTIMEZONE\r\nTZID:Private/Test\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
        let body = "BEGIN:VEVENT\r\nUID:private-zone\r\nDTSTART;TZID=Private/Test:20260328T100000\r\nDTEND;TZID=Private/Test:20260328T110000\r\nSUMMARY:Custom source zone\r\nEND:VEVENT\r\n"
        let result = try ICalendarImport.decode(data(zone + body), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments[0]["zeit"] as? String, "04:30")
        XCTAssertEqual(result.appointments[0]["endZeit"] as? String, "05:30")
        XCTAssertEqual((result.appointments[0]["icsTimezones"] as? [[String]])?.first?.first, "BEGIN:VTIMEZONE")
        let conflict = zone.replacingOccurrences(of: "+0530", with: "+0630")
        XCTAssertThrowsError(try ICalendarImport.decode(data(zone + conflict + body), context: try CalendarTestContext.make(), displayTimeZone: "UTC"))
        for rule in ["FREQ=YEARLY;INTERVAL=2", "FREQ=YEARLY;BYDAY=-1SU"] {
            let unsupported = zone.replacingOccurrences(of: "TZOFFSETTO:+0530\r\n", with: "TZOFFSETTO:+0530\r\nRRULE:" + rule + "\r\n")
            XCTAssertThrowsError(try ICalendarImport.decode(data(event + unsupported + body), context: try CalendarTestContext.make(), displayTimeZone: "UTC"), "A valid first item must not escape a later unsupported zone: " + rule)
        }
    }
    func testMasterAndExceptionShareTheWireUIDAndKeepRangeSourceBodies() throws {
        let master = "BEGIN:VEVENT\r\nUID:series\r\nDTSTART:20260328T100000Z\r\nDTEND:20260328T110000Z\r\nRRULE:FREQ=DAILY;COUNT=5\r\nSUMMARY:Master\r\nEND:VEVENT\r\n"
        let exception = "BEGIN:VEVENT\r\nUID:series\r\nRECURRENCE-ID;RANGE=THISANDFUTURE:20260330T100000Z\r\nDTSTART:20260330T120000Z\r\nDTEND:20260330T130000Z\r\nSUMMARY:Moved\r\nX-OPAQUE:keep\r\nEND:VEVENT\r\n"
        let result = try ICalendarImport.decode(data(master + exception), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
        XCTAssertEqual(result.appointments.count, 2)
        XCTAssertEqual(result.appointments[0]["icsSerienUid"] as? String, "series")
        XCTAssertTrue((result.appointments[1]["uid"] as? String ?? "").hasPrefix("series-magnolie-instanz-"))
        XCTAssertEqual((result.appointments[0]["icsRangeOverrides"] as? [[String]])?.count, 1)
        XCTAssertTrue((result.appointments[0]["icsRoundtrip"] as? [String] ?? []).contains("EXDATE:20260330T100000Z"))
        let output = try ICalendarExport.encode(result.appointments, context: try CalendarTestContext.make(), kind: .appointments, defaultTimeZone: "UTC")
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
            let result = try ICalendarImport.decode(Data(source.utf8), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
            let target = URL(fileURLWithPath: output).appendingPathComponent(name + "-imported.json")
            try JSONSerialization.data(withJSONObject: result.document, options: [.sortedKeys]).write(to: target, options: [.atomic])
            let groups: [(String, [[String: Any]], ICalendarExport.Kind)] = [
                ("termine", result.appointments, .appointments), ("aufgaben", result.tasks, .tasks), ("jahrestage", result.anniversaries, .anniversaries)]
            for (group, records, kind) in groups where !records.isEmpty {
                let text = try ICalendarExport.encode(records, context: try CalendarTestContext.make(), kind: kind, defaultTimeZone: "UTC")
                let file = URL(fileURLWithPath: output).appendingPathComponent(name + "-reimport-" + group + ".ics")
                try Data(text.utf8).write(to: file, options: [.atomic])
            }
        }
    }
}
