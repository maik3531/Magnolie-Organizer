import Foundation
import CryptoKit
import XCTest
@testable import BetaCore

final class LegacyAndroidAliasEvidenceTests: XCTestCase {
    private var repository: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }
    private func sha(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    private func source() throws -> String {
        let url = repository.appendingPathComponent("Magnolie-Organizer-Android-Tablet-Beta/app/src/test/resources/calendar-import-v2.0.30.json")
        let fixture = try Document.object(String(contentsOf: url, encoding: .utf8))
        let cases = try XCTUnwrap(fixture["cases"] as? [[String: Any]])
        return try XCTUnwrap(cases.first { $0["name"] as? String == "caldav-series-resource" }?["importSource"] as? String)
    }
    func testOldQuoteAndCompleteIdentitiesMatchActualAOSPReference() throws {
        let url = repository.appendingPathComponent("port-adapters/tests/fixtures/legacy-android-alias-evidence.json")
        let fixture = try Document.object(String(contentsOf: url, encoding: .utf8))
        XCTAssertEqual(fixture["aospJSONStringerSHA256"] as? String, "8772ac80610cd62e906330152b09864c471a0921f199f4b9d670d98050e3d86c")
        for row in try XCTUnwrap(fixture["quotes"] as? [[String: String]]) {
            XCTAssertEqual(Data(ICalendarImport.legacyAndroidQuote(try XCTUnwrap(row["value"])).utf8),
                           Data(try XCTUnwrap(row["legacyAndroid"]).utf8))
        }
        for row in try XCTUnwrap(fixture["recurrences"] as? [[String: Any]]) {
            let parameters = try XCTUnwrap(row["parameters"] as? [String: String])
            let text = try ICalendarImport.legacyAndroidRecurrenceKey(parameters, XCTUnwrap(row["value"] as? String))
            XCTAssertEqual(Data(text.utf8), Data(try XCTUnwrap(row["legacyAndroid"] as? String).utf8))
            XCTAssertEqual(sha(text), row["legacySHA256"] as? String)
            XCTAssertEqual("public-wire-magnolie-instanz-" + sha(text).prefix(16), row["legacyUID"] as? String)
        }
        XCTAssertThrowsError(try ICalendarImport.legacyAndroidRecurrenceKey(["BAD.KEY": "x"], "20261102T100000"))
    }
    func testEvidenceBindsActualSourceIndexAndRawIdentityWithoutChangingDocument() throws {
        let text = try source()
        let result = try ICalendarImport.decode(Data(text.utf8), context: CalendarTestContext.make(), displayTimeZone: "UTC")
        let proof = try XCTUnwrap(result.legacyAndroidAliases)
        XCTAssertEqual(proof.sourceSHA256, sha(text)); XCTAssertEqual(proof.sourceSHA256, result.sourceSHA256)
        XCTAssertEqual(proof.appointmentCount, result.appointments.count); XCTAssertEqual(proof.entries.count, 1)
        let entry = try XCTUnwrap(proof.entries.first)
        XCTAssertEqual(entry.appointmentIndex, 1)
        XCTAssertEqual(entry.canonicalUID, "caldav-series-1-magnolie-instanz-1201680171431eb3")
        XCTAssertEqual(entry.legacyUID, "caldav-series-1-magnolie-instanz-7f5e24178d89f683")
        let row = result.appointments[entry.appointmentIndex]
        XCTAssertEqual(entry.sourceID, row["icsQuelleId"] as? String)
        XCTAssertEqual(entry.wireUID, row["icsSerienUid"] as? String)
        XCTAssertEqual(entry.recurrenceLine, "RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000")
        XCTAssertTrue((row["icsRoundtrip"] as? [String] ?? []).contains(entry.recurrenceLine))
        XCTAssertEqual(Set(result.document.keys), Set(["termine", "aufgaben", "jahrestage", "icsImportMetadata"]))
        let metadata = try XCTUnwrap(result.document["icsImportMetadata"] as? [String: Any])
        XCTAssertEqual(Set(metadata.keys), Set(["version", "calendarProperties", "sourceSHA256"]))
        XCTAssertFalse(result.appointments.contains { $0.keys.contains { $0.hasPrefix("legacy") } })
        let renamed = try ICalendarImport.decode(Data(text.utf8), context: CalendarTestContext.make(), displayTimeZone: "UTC", sourceName: "other-name.ics")
        XCTAssertEqual(renamed.legacyAndroidAliases?.sourceSHA256, proof.sourceSHA256)
        XCTAssertNotEqual(renamed.legacyAndroidAliases?.entries.first?.sourceID, entry.sourceID)
    }
    func testEvidenceExcludesUnqualifiedAndEqualIdentitiesAndCountsItsBytes() throws {
        let context = try CalendarTestContext.make()
        func calendar(_ rid: String) -> Data {
            Data(("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:public\r\n" + rid +
                  "DTSTART:20261102T113000Z\r\nSUMMARY:Public\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").utf8)
        }
        XCTAssertNil(try ICalendarImport.decode(calendar("RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000\r\n"), context: context, displayTimeZone: "UTC").legacyAndroidAliases)
        XCTAssertNil(try ICalendarImport.decode(calendar("RECURRENCE-ID:20261102T090000Z\r\n"), context: context, displayTimeZone: "UTC", sourceName: "utc.ics").legacyAndroidAliases)
        XCTAssertNil(try ICalendarImport.decode(calendar(""), context: context, displayTimeZone: "UTC", sourceName: "master.ics").legacyAndroidAliases)
        let result = try ICalendarImport.decode(Data(source().utf8), context: context, displayTimeZone: "UTC")
        let proof = try XCTUnwrap(result.legacyAndroidAliases)
        let documentBytes = try JSONSerialization.data(withJSONObject: result.document).count
        let sidecarBytes = try JSONSerialization.data(withJSONObject: proof.payload).count
        XCTAssertNoThrow(try ICalendarImport.validateProjection(result.document, aliases: nil, maximum: documentBytes))
        XCTAssertThrowsError(try ICalendarImport.validateProjection(result.document, aliases: proof, maximum: documentBytes))
        XCTAssertNoThrow(try ICalendarImport.validateProjection(result.document, aliases: proof, maximum: documentBytes + sidecarBytes + 64))
        XCTAssertThrowsError(try ICalendarImport.validateProjection(result.document, aliases: proof, maximum: documentBytes + sidecarBytes + 63))
        XCTAssertEqual(ICalendarImport.maximumProjectedBytes, 96 * 1024 * 1024)
    }
}
