import Foundation
import XCTest
@testable import BetaCore

final class NormativeTimeZoneTests: XCTestCase {
    private func inputs() throws -> (Data, Data) {
        // Test-only explicit source fixture. Production loader has no path fallback.
        let package = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let root = package.deletingLastPathComponent().appendingPathComponent("port-adapters/timezones")
        return (try Data(contentsOf: root.appendingPathComponent("tzdb-2026egtz.json")), try Data(contentsOf: root.appendingPathComponent("provenance.json")))
    }
    func testApprovedDatabaseSHARegistryAndNoOSFallback() throws {
        let (payload, manifest) = try inputs(), database = try NormativeTimeZoneDatabase.load(payload: payload, manifest: manifest)
        XCTAssertEqual(database.identifiers.count, 597)
        XCTAssertEqual(database.payloadSHA256, NormativeTimeZoneDatabase.approvedPayloadSHA256)
        for name in database.identifiers {
            let zone = try database.named(name)
            let instant = try ProlepticGregorian.Civil(year: 2400, month: 7, day: 15, hour: 12).epochMilliseconds
            XCTAssertFalse(try database.wall(at: instant, in: zone).fields.isEmpty)
        }
        XCTAssertThrowsError(try database.named("Factory"))
        XCTAssertThrowsError(try database.named("Not/AZone"))
        var changed = payload; changed[changed.startIndex] ^= 1
        XCTAssertThrowsError(try NormativeTimeZoneDatabase.load(payload: changed, manifest: manifest))
        XCTAssertThrowsError(try NormativeTimeZoneDatabase.load(payload: payload, manifest: Data("{}".utf8)))
        for year in [1, 99, 1582, 2400, 9999] {
            let instant = try ProlepticGregorian.Civil(year: year, month: 7, day: 15, hour: 12).epochMilliseconds
            for alias in ["UTC", "GMT", "UT", "Z", "Etc/UTC"] {
                XCTAssertEqual(try database.offset(at: instant, in: database.named(alias)).offsetSeconds, 0)
            }
        }
    }
    func testHistoricalSecondsFarFutureGapsFoldsAndAliases() throws {
        let (payload, manifest) = try inputs(), db = try NormativeTimeZoneDatabase.load(payload: payload, manifest: manifest)
        let berlin = try db.named("Europe/Berlin")
        XCTAssertEqual(try db.offset(at: ProlepticGregorian.Civil(year: 1800, month: 1, day: 1).epochMilliseconds, in: berlin).offsetSeconds, 3208)
        for year in [2400, 9999] {
            XCTAssertEqual(try db.offset(at: ProlepticGregorian.Civil(year: year, month: 1, day: 15).epochMilliseconds, in: berlin).offsetSeconds, 3600)
            XCTAssertEqual(try db.offset(at: ProlepticGregorian.Civil(year: year, month: 7, day: 15).epochMilliseconds, in: berlin).offsetSeconds, 7200)
        }
        let gap = try ProlepticGregorian.Civil(year: 2026, month: 3, day: 29, hour: 2, minute: 30)
        XCTAssertThrowsError(try db.resolve(gap, in: berlin))
        XCTAssertNil(try db.resolve(gap, in: berlin, gap: .omit))
        let shifted = try XCTUnwrap(db.resolve(gap, in: berlin, gap: .forward))
        XCTAssertEqual(try db.wall(at: shifted, in: berlin).hour, 3)
        let fold = try ProlepticGregorian.Civil(year: 2026, month: 10, day: 25, hour: 2, minute: 30)
        let early = try XCTUnwrap(db.resolve(fold, in: berlin, fold: .earlier)), late = try XCTUnwrap(db.resolve(fold, in: berlin, fold: .later))
        XCTAssertEqual(late - early, 3_600_000)
        XCTAssertThrowsError(try db.resolve(fold, in: berlin, fold: .reject))
        for date in [try ProlepticGregorian.Civil(year: 1900, month: 2, day: 15), try ProlepticGregorian.Civil(year: 9999, month: 6, day: 15)] {
            XCTAssertEqual(try db.offset(at: date.epochMilliseconds, in: db.named("America/Nuuk")), try db.offset(at: date.epochMilliseconds, in: db.named("America/Godthab")))
        }
    }
    func testMalformedModelRejectedBeforeUseAndRawPOSIXMustAgree() throws {
        let (payload, _) = try inputs()
        var root = try Document.object(String(decoding: payload, as: UTF8.self))
        root["zones"] = ["Bad/Zone": 999999]
        XCTAssertThrowsError(try NormativeTimeZoneDatabase.decode(Data(Document.encode(root).utf8)))
        root = try Document.object(String(decoding: payload, as: UTF8.self))
        var rules = root["rules"] as! [[Any]], first = rules[0], tail = first[3] as! [Any]
        tail[6] = "BAD0DST,M3.5.0/99,M10.5.0"; first[3] = tail; rules[0] = first; root["rules"] = rules
        XCTAssertThrowsError(try NormativeTimeZoneDatabase.decode(Data(Document.encode(root).utf8)))
    }
    func testSignedMonthAndJulianRulesUseProlepticCivilDates() throws {
        let month = NormativeTimeZoneDatabase.Rule(kind: "M", a: 3, b: 5, c: 0, clock: -3600)
        let value = try ProlepticGregorian.civil(at: month.wallSecond(year: 2026) * 1000)
        XCTAssertEqual(value.fields, [2026, 3, 28, 23, 0, 0, 0])
        let julian = NormativeTimeZoneDatabase.Rule(kind: "J", a: 60, b: 0, c: 0, clock: 0)
        for year in [1900, 2000, 2400] {
            XCTAssertEqual(try ProlepticGregorian.civil(at: julian.wallSecond(year: year) * 1000).fields, [year, 3, 1, 0, 0, 0, 0])
        }
        let numeric = NormativeTimeZoneDatabase.Rule(kind: "N", a: 59, b: 0, c: 0, clock: 180000)
        XCTAssertEqual(try ProlepticGregorian.civil(at: numeric.wallSecond(year: 2400) * 1000).fields, [2400, 3, 2, 2, 0, 0, 0])
    }
}

final class ProlepticGregorianTests: XCTestCase {
    func testEntireGregorianCycleRoundtripsWithout1582Cutover() throws {
        let first = try ProlepticGregorian.Civil(year: 1400, month: 1, day: 1)
        for day in 0..<146097 {
            let value = try first.addingDays(day)
            XCTAssertEqual(try ProlepticGregorian.civil(at: value.epochMilliseconds), value)
        }
        XCTAssertEqual(try ProlepticGregorian.Civil(year: 1582, month: 10, day: 4).addingDays(1).fields, [1582, 10, 5, 0, 0, 0, 0])
        XCTAssertEqual(try ProlepticGregorian.Civil(year: 1582, month: 10, day: 10).addingDays(1).day, 11)
    }
    func testBoundariesNegativeMillisecondsAndStrictLeapDates() throws {
        XCTAssertEqual(try ProlepticGregorian.Civil(year: 1, month: 1, day: 1).epochMilliseconds, -62_135_596_800_000)
        XCTAssertEqual(try ProlepticGregorian.Civil(year: 9999, month: 12, day: 31, hour: 23, minute: 59, second: 59, millisecond: 999).epochMilliseconds, 253_402_300_799_999)
        XCTAssertEqual(try ProlepticGregorian.civil(at: -1).fields, [1969, 12, 31, 23, 59, 59, 999])
        for year in [1, 99, 100, 1582, 1900, 9999] { XCTAssertThrowsError(try ProlepticGregorian.Civil(year: year, month: 2, day: 29)) }
        for year in [400, 1600, 2000, 2400] { XCTAssertEqual(try ProlepticGregorian.Civil(year: year, month: 2, day: 29).addingDays(1).month, 3) }
        XCTAssertThrowsError(try ProlepticGregorian.Civil(year: 1, month: 1, day: 1).addingDays(-1))
        XCTAssertThrowsError(try ProlepticGregorian.Civil(year: 9999, month: 12, day: 31).addingDays(1))
        XCTAssertThrowsError(try ProlepticGregorian.Civil(year: 2026, month: 1, day: 1, second: 60))
    }
}
