import Foundation
import XCTest
@testable import BetaCore

final class TimeZoneExportTests: XCTestCase {
    private var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(secondsFromGMT: 0)!
        return c
    }
    private func date(_ year: Int, _ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute))!
    }
    private func signed(_ value: String) -> Int {
        let digits = Array(value.dropFirst())
        func number(_ start: Int) -> Int { Int(String(digits[start..<(start + 2)]))! }
        return (value.hasPrefix("-") ? -1 : 1) * (number(0) * 3600 + number(2) * 60 + (digits.count == 6 ? number(4) : 0))
    }
    private func wall(_ text: String) -> Date {
        let a = Array(text)
        func n(_ lower: Int, _ upper: Int) -> Int { Int(String(a[lower..<upper]))! }
        return calendar.date(from: DateComponents(year: n(0, 4), month: n(4, 6), day: n(6, 8),
                                                  hour: n(9, 11), minute: n(11, 13), second: n(13, 15)))!
    }
    // Independent VTIMEZONE consumer: enumerate finite RDATEs and only the nearby infinite
    // RRULE occurrences. Compare the resulting UTC offsets with Foundation's zone database.
    private func exportedOffset(_ lines: [String], at instant: Date) throws -> Int {
        var components: [[String: [String]]] = []
        var current: [String: [String]]?
        for line in lines {
            if line == "BEGIN:STANDARD" || line == "BEGIN:DAYLIGHT" { current = [:] }
            else if line == "END:STANDARD" || line == "END:DAYLIGHT" {
                components.append(current!); current = nil
            } else if current != nil, let colon = line.firstIndex(of: ":") {
                current![String(line[..<colon]), default: []].append(String(line[line.index(after: colon)...]))
            }
        }
        var latest: Date?
        var result: Int?
        for component in components {
            let start = wall(component["DTSTART"]!.first!)
            let before = signed(component["TZOFFSETFROM"]!.first!)
            let after = signed(component["TZOFFSETTO"]!.first!)
            var dates = [start]
            dates += component["RDATE", default: []].flatMap { $0.split(separator: ",").map { wall(String($0)) } }
            if let rule = component["RRULE"]?.first {
                let entries = Dictionary(uniqueKeysWithValues: rule.split(separator: ";").map { piece -> (String, String) in
                    let pair = piece.split(separator: "="); return (String(pair[0]), String(pair[1]))
                })
                XCTAssertEqual(entries["FREQ"], "YEARLY")
                let month = Int(entries["BYMONTH"]!)!
                let weekdayText = entries["BYDAY"]!
                let ordinal = Int(weekdayText.dropLast(2))!
                let weekday = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"].firstIndex(of: String(weekdayText.suffix(2)))!
                let year = calendar.component(.year, from: instant)
                for y in max(1, year - 1)...min(9999, year + 1) {
                    let days = calendar.range(of: .day, in: .month, for: date(y, month, 1))!
                    let matching = days.filter { calendar.component(.weekday, from: date(y, month, $0)) - 1 == weekday }
                    let day = ordinal == -1 ? matching.last! : matching[ordinal - 1]
                    let clock = calendar.dateComponents([.hour, .minute, .second], from: start)
                    let occurrence = date(y, month, day).addingTimeInterval(Double(clock.hour! * 3600 + clock.minute! * 60 + clock.second!))
                    if occurrence >= start { dates.append(occurrence) }
                }
            }
            for local in dates {
                let utc = local.addingTimeInterval(Double(-before))
                if utc <= instant, latest == nil || utc > latest! { latest = utc; result = after }
            }
        }
        return try XCTUnwrap(result)
    }

    func testFoundationZonesHistoryGapFoldAndUnboundedFuture() throws {
        for identifier in ["Europe/Berlin", "America/New_York", "Australia/Sydney", "Etc/UTC"] {
            let zone = try XCTUnwrap(TimeZone(identifier: identifier))
            let lines = try TimeZoneExport.definition(identifier)
            XCTAssertEqual(lines.first, "BEGIN:VTIMEZONE")
            XCTAssertEqual(lines.last, "END:VTIMEZONE")
            if identifier != "Etc/UTC" { XCTAssertTrue(lines.contains { $0.hasPrefix("RRULE:FREQ=YEARLY;") }, identifier) }
            for year in [1900, 1945, 1970, 2026, 2038, 2100, 2400, 8000] {
                for month in [1, 3, 4, 7, 10, 11, 12] {
                    let instant = date(year, month, 15, 12)
                    XCTAssertEqual(try exportedOffset(lines, at: instant), zone.secondsFromGMT(for: instant), "\(identifier) \(instant)")
                }
            }
        }
        for (identifier, instants) in [
            ("Europe/Berlin", [date(2026, 3, 29, 0, 59), date(2026, 3, 29, 1), date(2026, 10, 25, 0, 59), date(2026, 10, 25, 1)]),
            ("America/New_York", [date(2026, 3, 8, 6, 59), date(2026, 3, 8, 7), date(2026, 11, 1, 5, 59), date(2026, 11, 1, 6)])] {
            let zone = TimeZone(identifier: identifier)!
            let lines = try TimeZoneExport.definition(identifier)
            for instant in instants { XCTAssertEqual(try exportedOffset(lines, at: instant), zone.secondsFromGMT(for: instant)) }
        }
    }

    private func fixture(footer: String = "STD-1DST,M3.5.0,M10.5.0/3", standardOffset: Int = 3600, transitions: [(Int64, UInt8)] = [(0, 0), (10_000_000, 1), (20_000_000, 0), (25_000_000, 1), (30_000_000, 0)]) -> Data {
        func bytes(_ value: UInt64, size: Int) -> [UInt8] {
            (0..<size).reversed().map { UInt8(truncatingIfNeeded: value >> ($0 * 8)) }
        }
        func block(size: Int) -> [UInt8] {
            let names = Array("STD\0DST\0".utf8)
            var output = Array("TZif2".utf8) + Array(repeating: UInt8(0), count: 15)
            for count in [0, 0, 0, transitions.count, 2, names.count] { output += bytes(UInt64(count), size: 4) }
            for (second, _) in transitions { output += bytes(UInt64(bitPattern: second), size: size) }
            output += transitions.map { $0.1 }
            output += bytes(UInt64(bitPattern: Int64(standardOffset)), size: 4) + [0, 0]
            output += bytes(7200, size: 4) + [1, 4]
            return output + names
        }
        return Data(block(size: 4) + block(size: 8) + Array(("\n" + footer + "\n").utf8))
    }

    func testSyntheticHistoryOffsetsRdatesAndFuture() throws {
        let lines = try TimeZoneExport.definition("Test/Zone", data: fixture())
        XCTAssertTrue(lines.contains("DTSTART:00010101T000000"))
        XCTAssertTrue(lines.contains { $0.hasPrefix("RDATE:") })
        XCTAssertTrue(lines.contains("TZOFFSETFROM:+0100"))
        XCTAssertTrue(lines.contains("TZOFFSETTO:+0200"))
        XCTAssertTrue(lines.contains("RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU"))
        XCTAssertTrue(lines.contains("RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU"))
        XCTAssertEqual(try exportedOffset(lines, at: date(8000, 1, 1)), 3600)
        XCTAssertEqual(try exportedOffset(lines, at: date(8000, 7, 1)), 7200)
        let utc = try TimeZoneExport.definition("Fixed", data: fixture(footer: "STD-1", transitions: []))
        XCTAssertFalse(utc.contains { $0.hasPrefix("RRULE:") })
        XCTAssertEqual(try exportedOffset(utc, at: date(8000, 7, 1)), 3600)
        let seconds = try TimeZoneExport.definition("Seconds", data: fixture(footer: "STD-0:19:32", standardOffset: 1172, transitions: []))
        XCTAssertTrue(seconds.contains("TZOFFSETTO:+001932"))
        XCTAssertEqual(try exportedOffset(seconds, at: date(2026, 1, 1)), 1172)
        let southern = try TimeZoneExport.definition("Southern", data: fixture(footer: "STD-1DST,M10.1.0,M3.1.0", transitions: []))
        XCTAssertEqual(try exportedOffset(southern, at: date(2026, 1, 1)), 7200)
        XCTAssertEqual(try exportedOffset(southern, at: date(2026, 7, 1)), 3600)
    }

    func testRejectTruncatedMalformedAndUnrepresentableRules() throws {
        let valid = fixture()
        for length in [0, 3, 43, 44, valid.count - 1] {
            XCTAssertThrowsError(try TimeZoneExport.definition("Test", data: valid.prefix(length)))
        }
        for footer in ["bad", "STD-1DST,J60,J300", "STD-1DST,60,300", "STD-1DST,M3.5.0/-1,M10.5.0", "STD-1DST,M3.5.0/25,M10.5.0", "STD-1DST,M13.5.0,M10.5.0", "STD-1DST", "STD-2"] {
            XCTAssertThrowsError(try TimeZoneExport.definition("Test", data: fixture(footer: footer)), footer)
        }
        XCTAssertThrowsError(try TimeZoneExport.definition("Test", data: fixture(transitions: [(1, 2)])))
        XCTAssertThrowsError(try TimeZoneExport.definition("Test", data: fixture(transitions: [(1, 0), (1, 1)])))
        var excessive = valid
        excessive[32] = 0x7f // Untrusted transition count in the first TZif header.
        XCTAssertThrowsError(try TimeZoneExport.definition("Test", data: excessive))
        var leapSeconds = valid
        leapSeconds[31] = 1
        XCTAssertThrowsError(try TimeZoneExport.definition("Test", data: leapSeconds))
        XCTAssertThrowsError(try TimeZoneExport.definition("Injected\r\nTZID:X", data: valid))
        XCTAssertThrowsError(try TimeZoneExport.definition("Missing/NoSuchTimeZone"))
    }
}
