import Foundation

public enum RegionalSettings {
    public static func validate(_ value: [String: Any]) throws -> [String: String] {
        let choices: [String: Set<String>] = [
            "language": ["system", "en", "de", "fr", "es", "it", "nl", "pt", "ru", "cs", "pl", "hsb", "da", "nb", "hi", "zh_CN", "ja", "ar", "uk", "be", "tr"],
            "hourCycle": ["system", "h23", "h12"], "firstDayOfWeek": ["locale", "monday", "sunday", "saturday"],
            "weekRule": ["iso"], "temperatureUnit": ["system", "celsius", "fahrenheit"]]
        guard let fields = value as? [String: String], Set(fields.keys) == Set(choices.keys).union(["formatLocale", "timeZone", "homeCountry"]),
              choices.allSatisfy({ $0.value.contains(fields[$0.key] ?? "") }),
              fields["formatLocale"] == "system" || fields["formatLocale"]!.range(of: "^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$", options: .regularExpression) != nil,
              fields["timeZone"] == "system" || TimeZone(identifier: fields["timeZone"]!) != nil,
              Locale.isoRegionCodes.contains(fields["homeCountry"]!) else {
            throw BetaError("The regional settings could not be saved.")
        }
        return fields
    }

    public static func merging(_ settings: [String: String], into text: String) throws -> String {
        var root = try Document.plain(text)
        guard root["einstellungen"] == nil || root["einstellungen"] is [String: Any] else {
            throw BetaError("The regional settings could not be saved.")
        }
        var preferences = root["einstellungen"] as? [String: Any] ?? [:]
        guard preferences["regional"] == nil || preferences["regional"] is [String: Any] else {
            throw BetaError("The regional settings could not be saved.")
        }
        var regional = preferences["regional"] as? [String: Any] ?? [:]
        regional.merge(settings) { _, new in new }
        preferences["regional"] = regional; root["einstellungen"] = preferences
        return try Document.encode(root)
    }
}
