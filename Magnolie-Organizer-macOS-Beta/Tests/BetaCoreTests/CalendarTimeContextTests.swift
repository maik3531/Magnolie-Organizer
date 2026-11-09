import Foundation
import XCTest
@testable import BetaCore

final class CalendarTimeContextTests: XCTestCase {
    private func event(_ date: String, uid: String = "civil") -> Data {
        Data(("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:" + uid + "\r\nDTSTART:" + date + "T120000Z\r\nSUMMARY:Civil\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").utf8)
    }
    func testProlepticYearsAnd1582HaveExactIntegerRoundtrips() throws {
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        for day in ["00010615", "00990615", "15821004", "15821005", "15821010", "15821011", "24000229", "99990615"] {
            let input = try ICalendarImport.decode(event(day), context: context, displayTimeZone: "UTC")
            let expected = String(day.prefix(4)) + "-" + day.dropFirst(4).prefix(2) + "-" + day.suffix(2)
            XCTAssertEqual(input.appointments.first?["datum"] as? String, expected)
            let output = try ICalendarExport.encode(input.appointments, context: context, kind: .appointments, defaultTimeZone: "UTC")
            XCTAssertTrue(output.contains("DTSTART:" + day + "T120000Z\r\n"), day)
        }
        for day in ["15000229", "19000229", "00000615"] {
            XCTAssertThrowsError(try ICalendarImport.decode(event(day), context: context))
        }
    }
    func testSourceDefinitionsTakePriorityOverNamedProviderAndFormerMarkers() throws {
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        for name in ["@utc", "@magnolie-utc-instant", "UTC", "Factory", "Custom/caf\u{e9}", "Custom/cafe\u{301}", "Asia/\u{212A}athmandu"] {
            let source = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTIMEZONE\r\nTZID:" + name + "\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0300\r\nTZOFFSETTO:+0300\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT\r\nUID:source\r\nDTSTART;TZID=" + name + ":20260115T120000\r\nSUMMARY:Source\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:absolute-utc\r\nDTSTART:20260115T120000Z\r\nSUMMARY:Absolute UTC\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            let input = try ICalendarImport.decode(Data(source.utf8), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(input.appointments.map { $0["zeit"] as? String }, ["09:00", "12:00"], name)
            let output = try ICalendarExport.encode(input.appointments, context: context, kind: .appointments, defaultTimeZone: "UTC")
            XCTAssertTrue(output.contains("DTSTART;TZID=" + name + ":20260115T120000\r\n"), name)
            XCTAssertTrue(output.contains("TZID:" + name + "\r\n"), name)
            XCTAssertTrue(output.contains("DTSTART:20260115T120000Z\r\n"), name)
        }
        XCTAssertThrowsError(try ICalendarImport.decode(Data("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART;TZID=Factory:20260115T120000\r\nSUMMARY:No rules\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n".utf8), context: context))
    }
    func testOpaqueUIDsAndDetachedExceptionAssociationsRemainDistinct() throws {
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("tests/fixtures/opaque-ics")
        for name in ["uid-two-events", "tzid-two-zones", "detached-exception"] {
            let input = try ICalendarImport.decode(Data(contentsOf: root.appendingPathComponent(name + ".ics")), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(input.appointments.count, 2, name)
            if name == "tzid-two-zones" {
                XCTAssertEqual(input.appointments.map { $0["zeit"] as? String }, ["12:00", "11:00"])
            } else if name == "detached-exception" {
                XCTAssertEqual(input.appointments[0]["icsKomplex"] as? Bool, false)
                XCTAssertFalse((input.appointments[0]["icsRoundtrip"] as? [String] ?? []).contains { $0.hasPrefix("EXDATE") })
            }
            let output = try ICalendarExport.encode(input.appointments, context: context, kind: .appointments, defaultTimeZone: "UTC")
            let again = try ICalendarImport.decode(Data(output.utf8), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(again.appointments.count, 2)
            XCTAssertEqual(again.appointments.map { OpaqueUTF8Identity($0["uid"] as! String) }, input.appointments.map { OpaqueUTF8Identity($0["uid"] as! String) })
        }
        let duplicate = String(decoding: event("20260115", uid: "same"), as: UTF8.self).replacingOccurrences(of: "END:VCALENDAR", with: "BEGIN:VEVENT\r\nUID:same\r\nDTSTART:20260116T120000Z\r\nSUMMARY:Duplicate\r\nEND:VEVENT\r\nEND:VCALENDAR")
        XCTAssertThrowsError(try ICalendarImport.decode(Data(duplicate.utf8), context: context))
    }
    func testNamedAndSynthesizedSourceZonesAgreeWithIndependentZicReferences() throws {
        // Values measured independently using zic/ZoneInfo from the approved
        // 2026egtz archive (SHA0f391ed7…), not computed by the Swift provider.
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        let cases = [("Africa/Cairo", "99990715", "09:00"), ("Asia/Gaza", "99990715", "09:00"),
                     ("America/Nuuk", "99990715", "13:00"), ("Australia/Lord_Howe", "99990715", "01:30"),
                     ("Europe/Berlin", "00010615", "11:06"), ("Europe/Berlin", "00990615", "11:06"), ("Europe/Berlin", "15821015", "11:06")]
        for (name, day, expected) in cases {
            let source = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:named\r\nDTSTART;TZID=" + name + ":" + day + "T120000\r\nSUMMARY:Independent zone\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            let named = try ICalendarImport.decode(Data(source.utf8), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(named.appointments.first?["zeit"] as? String, expected, name + day)
            let exported = try ICalendarExport.encode(named.appointments, context: context, kind: .appointments, defaultTimeZone: "UTC")
            XCTAssertTrue(exported.contains("BEGIN:VTIMEZONE\r\nTZID:" + name + "\r\n"))
            let embedded = try ICalendarImport.decode(Data(exported.utf8), context: context, displayTimeZone: "UTC")
            XCTAssertEqual(embedded.appointments.first?["zeit"] as? String, expected, name + day)
            XCTAssertEqual(embedded.appointments.first?["datum"] as? String, named.appointments.first?["datum"] as? String)
        }
    }
    func testOperationContextCapturesFreshSystemIdentityWithoutReloadingRules() throws {
        let first = try CalendarTestContext.make(systemIdentifier: "UTC")
        let changed = try CalendarTimeContext(database: first.database, systemIdentifier: "Europe/Berlin")
        let restarted = try CalendarTestContext.make(systemIdentifier: "Europe/Berlin")
        XCTAssertTrue(first.database === changed.database)
        let record: [String: Any] = ["uid": "regional", "titel": "Regional", "datum": "2026-07-15", "zeit": "10:00", "icsEndeFehlt": true]
        let before = try ICalendarExport.encode([record], context: first, kind: .appointments)
        let after = try ICalendarExport.encode([record], context: changed, kind: .appointments)
        let restart = try ICalendarExport.encode([record], context: restarted, kind: .appointments)
        XCTAssertTrue(before.contains("DTSTART:20260715T100000Z\r\n"))
        for output in [after, restart] { XCTAssertTrue(output.contains("DTSTART;TZID=Europe/Berlin:20260715T100000\r\n")) }
        var explicit = record; explicit["icsAnzeigeZeitzone"] = "UTC"
        XCTAssertTrue(try ICalendarExport.encode([explicit], context: changed, kind: .appointments).contains("DTSTART:20260715T100000Z\r\n"))
    }
    func testFoundationTimestampMillisecondNoiseNeverRoundsAcrossSecond() throws {
        for (seconds, expected) in [(0.001, Int64(1)), (-0.001, -1), (1.001, 1001), (-1.001, -1001),
                                    (0.0001, 0), (-0.0001, -1), (0.9999, 999), (-1.0001, -1001)] {
            XCTAssertEqual(try CalendarInstant.timestamp(Date(timeIntervalSince1970: seconds)).milliseconds, expected, String(seconds))
        }
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        let record: [String: Any] = ["uid": "timestamp", "titel": "Time", "datum": "2026-01-15", "zeit": "12:00", "icsEndeFehlt": true]
        let negative = try ICalendarExport.encode([record], context: context, kind: .appointments, timestamp: Date(timeIntervalSince1970: -0.0001))
        let positive = try ICalendarExport.encode([record], context: context, kind: .appointments, timestamp: Date(timeIntervalSince1970: 0.9999))
        XCTAssertTrue(negative.contains("DTSTAMP:19691231T235959Z\r\n"))
        XCTAssertTrue(positive.contains("DTSTAMP:19700101T000000Z\r\n"))
        XCTAssertThrowsError(try CalendarInstant.timestamp(Date(timeIntervalSince1970: .nan)))
    }
    func testExplicitBundleLoaderHasNoSourceOrEnvironmentFallback() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        XCTAssertThrowsError(try CalendarTimeContext.bundled(resources: directory, systemIdentifier: "UTC"))
        let target = directory.appendingPathComponent("UI/web/timezones")
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("port-adapters/timezones")
        for name in ["tzdb-2026egtz.json", "provenance.json"] { try FileManager.default.copyItem(at: source.appendingPathComponent(name), to: target.appendingPathComponent(name)) }
        let context = try CalendarTimeContext.bundled(resources: directory, systemIdentifier: "Europe/Berlin")
        XCTAssertEqual(context.database.identifiers.count, 597)
        XCTAssertEqual(context.systemIdentifier, "Europe/Berlin")
        XCTAssertThrowsError(try CalendarTimeContext.bundled(resources: directory, systemIdentifier: "Asia/\u{212A}athmandu"))
        try Data("{}".utf8).write(to: target.appendingPathComponent("provenance.json"))
        XCTAssertThrowsError(try CalendarTimeContext.bundled(resources: directory, systemIdentifier: "UTC"))
    }
}
