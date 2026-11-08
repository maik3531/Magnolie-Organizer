import Foundation
@testable import BetaCore

/// Explicit test fixture initialization only. Production never consults source
/// paths, environment overrides or a mutable global provider installation.
enum CalendarTestContext {
    private static let fixture: Result<NormativeTimeZoneDatabase, Error> = Result {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("port-adapters/timezones")
        return try .load(payload: Data(contentsOf: root.appendingPathComponent("tzdb-2026egtz.json")), manifest: Data(contentsOf: root.appendingPathComponent("provenance.json")))
    }
    static func make(systemIdentifier: String = TimeZone.current.identifier) throws -> CalendarTimeContext {
        try CalendarTimeContext(database: fixture.get(), systemIdentifier: systemIdentifier)
    }
}
