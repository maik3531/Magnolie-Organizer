import Foundation

/// Pinned complete history plus verified unlimited future rules for RFC5545.
public enum TimeZoneExport {
    public enum ExportError: Error, LocalizedError {
        case invalidIdentifier, malformedData, unsupportedRule
        public var errorDescription: String? {
            switch self {
            case .invalidIdentifier: return "Unbekannte oder ungültige Kalenderzeitzone."
            case .malformedData: return "Die Zeitzonendaten sind beschädigt oder überschreiten die Exportgrenzen."
            case .unsupportedRule: return "Diese Zeitzonenregel lässt sich nicht verlustfrei als VTIMEZONE exportieren."
            }
        }
    }

    public static func definition(_ identifier: String, context: CalendarTimeContext) throws -> [String] {
        try NormativeTimeZoneDefinition.definition(identifier, database: context.database)
    }
}
