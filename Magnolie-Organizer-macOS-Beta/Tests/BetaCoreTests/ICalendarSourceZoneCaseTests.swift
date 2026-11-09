import Foundation
import XCTest
@testable import BetaCore

final class ICalendarSourceZoneCaseTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent("port-adapters/tests/fixtures/source-vtimezone-case/" + name + ".ics"))
    }
    func testActualImportedSourceComponentCaseAndUnknownLinesRemainByteExact() throws {
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        for name in ["uppercase", "component-values", "property-names"] {
            let imported = try ICalendarImport.decode(fixture(name), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(imported.appointments.first?["zeit"] as? String, "09:00")
            let blocks = try XCTUnwrap(imported.appointments.first?["icsTimezones"] as? [[String]])
            let encoded = try ICalendarExport.encode(imported.appointments, context: context, kind: .appointments, defaultTimeZone: "UTC")
            for block in blocks { XCTAssertTrue(encoded.contains(block.joined(separator: "\r\n") + "\r\n"), name) }
            let again = try ICalendarImport.decode(Data(encoded.utf8), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(again.appointments.first?["zeit"] as? String, "09:00", name)
            XCTAssertEqual((again.appointments.first?["icsTimezones"] as? [[String]])?.map { OpaqueUTF8Identity(parts: $0) }, blocks.map { OpaqueUTF8Identity(parts: $0) })
        }
    }
    func testTZIDCaseIsOpaqueEvenWhenComponentTokensAreNot() throws {
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        func zone(_ name: String, _ offset: String) -> String {
            "begin:vtimezone\r\nTZID:" + name + "\r\nBEGIN:standard\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:" + offset + "\r\nTZOFFSETTO:" + offset + "\r\nend:STANDARD\r\nEND:VTimeZone\r\n"
        }
        func event(_ uid: String, _ zone: String) -> String {
            "BEGIN:VEVENT\r\nUID:" + uid + "\r\nDTSTART;TZID=" + zone + ":20260115T120000\r\nSUMMARY:Case\r\nEND:VEVENT\r\n"
        }
        let source = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + zone("Custom/Zone", "+0300") + zone("custom/zone", "+0200") + event("first", "Custom/Zone") + event("second", "custom/zone") + "END:VCALENDAR\r\n"
        let imported = try ICalendarImport.decode(Data(source.utf8), context: context, displayTimeZone: "UTC")
        XCTAssertEqual(imported.appointments.map { $0["zeit"] as? String }, ["09:00", "10:00"])
        let encoded = try ICalendarExport.encode(imported.appointments, context: context, kind: .appointments, defaultTimeZone: "UTC")
        XCTAssertTrue(encoded.contains("TZID:Custom/Zone\r\n"))
        XCTAssertTrue(encoded.contains("TZID:custom/zone\r\n"))
        let again = try ICalendarImport.decode(Data(encoded.utf8), context: context, displayTimeZone: "UTC")
        XCTAssertEqual(again.appointments.map { $0["zeit"] as? String }, ["09:00", "10:00"])
    }
    func testMalformedSourceNestingAndUnicodeTokenLookalikesStillReject() throws {
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        let imported = try ICalendarImport.decode(fixture("uppercase"), context: context, displayTimeZone: "UTC")
        let original = try XCTUnwrap(imported.appointments.first), blocks = try XCTUnwrap(original["icsTimezones"] as? [[String]])
        for (old, new) in [("BEGIN:STANDARD", "BEGIN:VEVENT"), ("END:STANDARD", "END:DAYLIGHT"), ("END:VTIMEZONE", "END:DAYLIGHT"), ("BEGIN:STANDARD", "BEGIN:ſtandard"),
                           ("BEGIN:VTIMEZONE", "BEGIN;X=P:VTIMEZONE"), ("END:VTIMEZONE", "END;X=P:VTIMEZONE")] {
            var changed = original
            changed["icsTimezones"] = blocks.map { $0.map { $0 == old ? new : $0 } }
            XCTAssertThrowsError(try ICalendarExport.encode([changed], context: context, kind: .appointments, defaultTimeZone: "UTC"), new)
        }
    }
}
