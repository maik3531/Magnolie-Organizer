import Foundation
import XCTest
@testable import BetaCore

final class NormativeTimeZoneDefinitionTests: XCTestCase {
    private func database() throws -> NormativeTimeZoneDatabase {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("port-adapters/timezones")
        return try .load(payload: Data(contentsOf: root.appendingPathComponent("tzdb-2026egtz.json")), manifest: Data(contentsOf: root.appendingPathComponent("provenance.json")))
    }
    func testEveryNamedDefinitionHasUnlimitedProvenFutureWithoutOSRules() throws {
        let database = try database()
        for name in database.identifiers {
            let lines = try NormativeTimeZoneDefinition.definition(name, database: database)
            XCTAssertEqual(lines.first, "BEGIN:VTIMEZONE", name)
            XCTAssertEqual(lines.last, "END:VTIMEZONE", name)
            XCTAssertTrue(lines.contains("TZID:" + name), name)
            XCTAssertFalse(lines.contains { $0.hasPrefix("RRULE:") && ($0.contains("UNTIL=") || $0.contains("COUNT=") || $0.contains("INTERVAL=")) }, name)
            XCTAssertTrue(lines.contains { $0.hasPrefix("DTSTART:00010101") }, name)
        }
        XCTAssertThrowsError(try NormativeTimeZoneDefinition.definition("Factory", database: database))
    }
    func testShiftedCairoAndSignedGazaRulesRemainCompactUnlimitedPredicates() throws {
        let database = try database()
        for name in ["Africa/Cairo", "Asia/Gaza", "America/Nuuk", "Australia/Lord_Howe"] {
            let lines = try NormativeTimeZoneDefinition.definition(name, database: database)
            let rules = lines.filter { $0.hasPrefix("RRULE:") }
            XCTAssertFalse(rules.isEmpty, name)
            XCTAssertLessThanOrEqual(rules.count, 4, name)
            XCTAssertTrue(rules.allSatisfy { $0.hasPrefix("RRULE:FREQ=YEARLY;BYMONTH=") }, name)
        }
    }
}
