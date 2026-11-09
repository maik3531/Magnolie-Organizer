import Foundation
import CoreFoundation
import CryptoKit

/// Versioned semantic fingerprints. Local IDs, transport ETags and wall-clock save times are not
/// domain content. The native format also covers exposed ICS fields absent from older Linux hashes.
public enum DAVSyncBaseline {
    public static let format = "native-calendar-1"
    private static let appointmentFields = ["datum", "endDatum", "zeit", "endZeit", "titel", "notiz", "kategorien",
        "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "individuelleErinnerungTage", "standardErinnerung", "wiederholung"]
    private static let taskFields = ["titel", "faellig", "startDatum", "startZeit", "faelligZeit", "prio", "erledigt", "notiz",
        "erinnern", "individuelleErinnerungTage", "elternUid", "reihenfolge", "icsRoundtrip"]
    private static let companionFields = ["icsRoundtrip", "icsKomplex", "icsSerienUid", "icsSequence", "icsTimezones", "icsRangeOverrides", "icsAusnahmeTermine", "icsStatus",
        "icsAusnahmen", "icsZusatzDaten", "icsZusatzTermine", "icsEndeFehlt", "icsNullDauer", "icsOriginalDatum", "icsOriginalZeit",
        "ort", "organisator", "teilnehmer", "alarme", "kalenderAnhaenge"]

    public static func hash(_ record: [String: Any], kind: DAVCalendarSnapshot.Kind) throws -> String {
        var fields: [String]
        switch kind {
        case .appointment: fields = appointmentFields
        case .task: fields = taskFields + ["kategorien", "personen", "wiederholung", "erinnerungsMinute", "icsElternQuelleId", "icsQuelleId"]
        case .anniversary: fields = ["name", "datum", "typ", "notiz", "kategorien"]
        }
        fields += companionFields + ["akzentFarbe", "icsAnzeigeZeitzone", "icsElternUid", "ganztag", "standardErinnerung", "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "individuelleErinnerungTage"]
        var projection: [String: Any] = [:]
        for key in Set(fields) { projection[key] = record[key] ?? NSNull() }
        for key in companionFields + ["akzentFarbe", "icsAnzeigeZeitzone", "icsElternUid", "ganztag"] where emptyDefault(projection[key]) { projection[key] = NSNull() }
        if kind == .task {
            for key in ["personen", "icsElternQuelleId", "icsQuelleId"] where emptyDefault(projection[key]) { projection[key] = NSNull() }
            projection["erinnerungsMinute"] = record["erinnerungsMinute"] ?? 480
            if (record["elternUid"] as? String ?? "").isEmpty { projection["icsElternQuelleId"] = NSNull() }
        }
        if fields.contains("wiederholung") {
            var rule = recurrence(record["wiederholung"])
            if rule["art"] as? String == "none", rule.keys.allSatisfy({ $0 == "art" || $0 == "bis" && (rule[$0] as? String ?? "").isEmpty }) { rule = [:] }
            projection["wiederholung"] = rule
        }
        return try digest(projection)
    }

    /// Exact shipped _sync_inhalt/_sync_inhalt_hash shape, for tested legacy-baseline migration.
    /// This does not label a native hash as a Linux hash or authorize deletes on unknown formats.
    public static func linuxCompatibilityHash(_ record: [String: Any], kind: DAVCalendarSnapshot.Kind) throws -> String {
        guard kind != .anniversary else { throw BetaError("Linux anniversary DAV baselines are not defined.") }
        var fields = kind == .appointment ? appointmentFields + ["icsRoundtrip", "icsKomplex", "icsSerienUid", "icsSequence"] : taskFields
        if kind == .appointment { fields += ["icsTimezones", "icsRangeOverrides", "icsAusnahmeTermine", "icsStatus"] }
        var projection: [String: Any] = [:]
        for key in fields { projection[key] = record[key] ?? NSNull() }
        if kind == .appointment {
            for key in ["icsTimezones", "icsRangeOverrides", "icsAusnahmeTermine", "icsStatus"] {
                if let list = projection[key] as? [Any], list.isEmpty { projection[key] = NSNull() }
                if let text = projection[key] as? String, text.isEmpty { projection[key] = NSNull() }
                if let dict = projection[key] as? [String: Any], dict.isEmpty { projection[key] = NSNull() }
                if let number = projection[key] as? NSNumber, number.doubleValue == 0 { projection[key] = NSNull() }
            }
            projection["wiederholung"] = recurrence(record["wiederholung"])
        }
        return try digest(projection)
    }
    private static func emptyDefault(_ value: Any?) -> Bool {
        guard let value, !(value is NSNull) else { return true }
        if let value = value as? String { return value.isEmpty }
        if let value = value as? [Any] { return value.isEmpty }
        if let value = value as? [String: Any] { return value.isEmpty }
        if let value = value as? NSNumber { return value.doubleValue == 0 }
        return false
    }
    private static func recurrence(_ value: Any?) -> [String: Any] {
        let input = value as? [String: Any] ?? [:]
        var result: [String: Any] = [:]
        for key in ["art", "bis", "intervall", "ordinal", "wochentag", "daten"] { if let value = input[key] { result[key] = value } }
        return result
    }
    public static func canonicalJSON(_ value: Any) throws -> Data { Data(try encode(value).utf8) }
    private static func digest(_ value: Any) throws -> String {
        SHA256.hash(data: try canonicalJSON(value)).map { String(format: "%02x", $0) }.joined()
    }
    private static func encode(_ value: Any) throws -> String {
        if value is NSNull { return "null" }
        if let value = value as? String {
            let data = try JSONSerialization.data(withJSONObject: [value], options: [.withoutEscapingSlashes])
            let text = String(data: data, encoding: .utf8)!
            return String(text.dropFirst().dropLast())
        }
        if let value = value as? NSNumber {
            if CFGetTypeID(value) == CFBooleanGetTypeID() { return value.boolValue ? "true" : "false" }
            guard value.doubleValue.isFinite else { throw BetaError("Non-finite sync baseline value.") }
            if CFNumberIsFloatType(unsafeBitCast(value, to: CFNumber.self)) { return String(value.doubleValue) }
            return value.stringValue
        }
        if let value = value as? [Any] { return "[" + (try value.map(encode)).joined(separator: ",") + "]" }
        if let value = value as? [String: Any] {
            let keys = value.keys.sorted { $0.utf8.lexicographicallyPrecedes($1.utf8) }
            return "{" + (try keys.map { try encode($0) + ":" + encode(value[$0]!) }).joined(separator: ",") + "}"
        }
        throw BetaError("Unrepresentable sync baseline value.")
    }
}
