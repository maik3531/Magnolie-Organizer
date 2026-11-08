import Foundation
import CoreFoundation

/// Refs #121. Pure, bounded preparation only. The host must resolve the system
/// application and report its open completion; this never sends mail or a call.
public enum CommunicationLaunchPolicy {
    public enum Kind: String { case mail, map, website }
    public struct Target {
        public let url: URL
        public let kind: Kind
        public let service: String
    }
    public static func target(command: String, fields: [String: Any]) throws -> Target {
        guard JSONSerialization.isValidJSONObject(fields),
              try JSONSerialization.data(withJSONObject: fields).count <= 32_768 else {
            throw BetaError("Communication request is too large.")
        }
        if let supplied = fields["cmd"] {
            guard let supplied = supplied as? String, supplied == command else { throw BetaError("Mismatched communication command.") }
        }
        switch command {
        case "mail":
            try keys(fields, allowed: ["cmd", "email", "name"])
            let email = try text(fields, "email", limit: 254)
            _ = try text(fields, "name", limit: 256)
            // RFC 6068 addr-spec only. The display name is UI context, never
            // a header or a nonstandard "Name <address>" mailto path.
            let parts = email.split(separator: "@", omittingEmptySubsequences: false)
            guard parts.count == 2, !parts[0].isEmpty, parts[0].utf8.count <= 64,
                  !parts[0].hasPrefix("."), !parts[0].hasSuffix("."), !parts[0].contains(".."),
                  parts[0].unicodeScalars.allSatisfy({
                      CharacterSet.alphanumerics.contains($0) || "!#$&'*+-/=_^`{|}~.".unicodeScalars.contains($0)
                  }), validHost(String(parts[1]), requireDot: true) else {
                throw BetaError("Enter one email address without headers.")
            }
            return try make("mailto:" + encode(email, safe: "@._+-"), .mail, "mail")
        case "karte":
            try keys(fields, allowed: ["cmd", "kontakt", "land", "dienst", "route", "absender"])
            guard let contact = fields["kontakt"] as? [String: Any] else { throw BetaError("Invalid map contact.") }
            let service = try text(fields, "dienst", limit: 32, fallback: "auto")
            guard ["auto", "gnome-maps", "openstreetmap", "google"].contains(service) else { throw BetaError("Unsupported map service.") }
            let country = try text(fields, "land", limit: 128)
            let street = try text(contact, "strasse", limit: 512, fallback: "")
            let postcode = try text(contact, "plz", limit: 64, fallback: "")
            let city = try text(contact, "ort", limit: 256, fallback: "")
            var address = [street, [postcode, city].filter { !$0.isEmpty }.joined(separator: " ")].filter { !$0.isEmpty }.joined(separator: ", ")
            guard !address.isEmpty else { throw BetaError("This contact card has no postal address.") }
            address = appendCountry(address, country)
            let route: Bool
            if let value = fields["route"] {
                guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { throw BetaError("Invalid route flag.") }
                route = number.boolValue
            } else { route = false }
            let sender = try text(fields, "absender", limit: 2_048, fallback: "", multiline: true)
            let origin = appendCountry(sender.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty && $0.rangeOfCharacter(from: .decimalDigits) != nil }.joined(separator: ", "), country)
            if route && origin.isEmpty { throw BetaError("Your own address is required as the starting point for a route.") }
            let query: String
            let base: String
            switch service {
            case "google":
                base = "https://www.google.com/maps/" + (route ? "dir/?api=1&" : "search/?api=1&")
                query = route ? "destination=" + encode(address) + "&origin=" + encode(origin) : "query=" + encode(address)
            case "openstreetmap":
                base = "https://www.openstreetmap.org/" + (route ? "directions?" : "search?")
                query = route ? "from=" + encode(origin) + "&to=" + encode(address) : "query=" + encode(address)
            default:
                // Imported Linux GNOME preference is adapted, never executed.
                base = "https://maps.apple.com/?"
                query = route ? "saddr=" + encode(origin) + "&daddr=" + encode(address) : "q=" + encode(address)
            }
            return try make(base + query, .map, service == "auto" || service == "gnome-maps" ? "apple-maps" : service)
        case "sozial":
            try keys(fields, allowed: ["cmd", "dienst", "wert", "aktionArt", "aktionZiel", "land", "nummer"])
            let aliases = ["twitter": "x", "likedin": "linkedin", "telefon": "phone"]
            let rawService = try text(fields, "dienst", limit: 32).lowercased()
            let service = aliases[rawService] ?? rawService
            let allowed = ["whatsapp", "threema", "facebook", "instagram", "signal", "mastodon", "teams", "snapchat", "tiktok", "youtube", "telegram", "x", "linkedin", "reddit", "custom"]
            guard allowed.contains(service) else { throw BetaError("This communication method needs a separate native adapter.") }
            let value = try text(fields, "wert", limit: 500)
            guard !value.isEmpty else { throw BetaError("The communication method is incomplete.") }
            let action = try text(fields, "aktionArt", limit: 32, fallback: "").lowercased()
            guard ["", "url", "website", "webseite"].contains(action) else { throw BetaError("Custom application commands are unavailable on macOS.") }
            let template = try text(fields, "aktionZiel", limit: 500, fallback: "")
            _ = try text(fields, "land", limit: 128, fallback: "Deutschland")
            let suppliedNumber = try text(fields, "nummer", limit: 16, fallback: "")
            guard suppliedNumber.isEmpty || isE164(suppliedNumber) else { throw BetaError("Invalid canonical phone number.") }
            // The private projection supplies the result of the existing
            // telefonSchluessel helper, including its country/extension policy.
            let number = suppliedNumber.isEmpty ? internationalNumber(value) : suppliedNumber
            let user = encode(String(value.drop(while: { $0 == "@" })))
            var destination = value.lowercased().hasPrefix("https://") ? value : ""
            switch service {
            case "whatsapp", "signal":
                guard let number else { throw BetaError("Enter a complete phone number.") }
                destination = service == "whatsapp" ? "https://wa.me/" + String(number.dropFirst()) : "https://signal.me/#p/" + encode(number, safe: "+")
            case "threema": if destination.isEmpty { destination = "https://web.threema.ch/" }
            case "mastodon":
                if destination.isEmpty {
                    let parts = value.trimmingCharacters(in: CharacterSet(charactersIn: "@")).split(separator: "@", omittingEmptySubsequences: false)
                    guard parts.count == 2 else { throw BetaError("Enter the complete Mastodon address or an HTTPS address.") }
                    destination = "https://" + String(parts[1]) + "/@" + encode(String(parts[0]))
                }
            case "teams": if destination.isEmpty { destination = "https://teams.microsoft.com/l/chat/0/0?users=" + encode(value, safe: "@._+-") }
            case "custom": break
            default:
                let bases = ["facebook": "https://www.facebook.com/", "instagram": "https://www.instagram.com/", "snapchat": "https://www.snapchat.com/add/", "tiktok": "https://www.tiktok.com/@", "youtube": "https://www.youtube.com/@", "telegram": "https://t.me/", "x": "https://x.com/", "linkedin": "https://www.linkedin.com/in/", "reddit": "https://www.reddit.com/user/"]
                if destination.isEmpty, let base = bases[service] { destination = base + user }
            }
            if action == "website" || action == "webseite" {
                if template.contains("{nummer}"), number == nil { throw BetaError("Enter a complete phone number for the website template.") }
                destination = template.replacingOccurrences(of: "{wert}", with: encode(value, safe: "@._+-"))
                    .replacingOccurrences(of: "{nummer}", with: encode(number ?? "", safe: "+"))
                    .replacingOccurrences(of: "{ziel}", with: encode(destination))
                guard !destination.contains("{"), !destination.contains("}") else { throw BetaError("Unsupported website placeholder.") }
            }
            return try make(destination, .website, service)
        default: throw BetaError("Unsupported communication command.")
        }
    }
    private static func keys(_ fields: [String: Any], allowed: Set<String>) throws {
        guard Set(fields.keys).isSubset(of: allowed) else { throw BetaError("Invalid communication fields.") }
    }
    private static func text(_ fields: [String: Any], _ key: String, limit: Int, fallback: String? = nil, multiline: Bool = false) throws -> String {
        guard let raw = fields[key] else {
            if let fallback { return fallback }; throw BetaError("Missing communication field.")
        }
        guard let text = raw as? String, text.utf8.count <= limit,
              !text.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) && !(multiline && ($0.value == 10 || $0.value == 13)) }) else {
            throw BetaError("Invalid communication text.")
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    private static func appendCountry(_ address: String, _ country: String) -> String {
        guard !address.isEmpty, !country.isEmpty, address.range(of: country, options: [.caseInsensitive, .diacriticInsensitive]) == nil else { return address }
        return address + ", " + country
    }
    private static func encode(_ value: String, safe: String = "") -> String {
        let allowed = Set(("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" + safe).utf8)
        return value.utf8.map { allowed.contains($0) ? String(UnicodeScalar($0)) : String(format: "%%%02X", $0) }.joined()
    }
    private static func isE164(_ value: String) -> Bool {
        value.range(of: #"^\+[1-9][0-9]{5,14}$"#, options: .regularExpression) != nil
    }
    private static func internationalNumber(_ value: String) -> String? {
        // Compatibility for a direct typed native request with an already
        // international number. National normalization belongs to canonical JS.
        guard value.unicodeScalars.allSatisfy({ "0123456789+(). -".unicodeScalars.contains($0) }) else { return nil }
        var number = value.filter { "0123456789+".contains($0) }
        if number.hasPrefix("00") { number = "+" + number.dropFirst(2) }
        return isE164(number) ? number : nil
    }
    private static func validHost(_ host: String, requireDot: Bool = false) -> Bool {
        // URLComponents already parsed bracketed IP literals. Keep local
        // HTTPS servers and IDN names usable; this does not fetch their URLs.
        if !requireDot, host.contains(":"), host.utf8.count <= 64 {
            return host.unicodeScalars.allSatisfy { "0123456789abcdefABCDEF:.[]".unicodeScalars.contains($0) }
        }
        let labels = host.split(separator: ".", omittingEmptySubsequences: false)
        guard host.utf8.count <= 253, !requireDot || labels.count >= 2 else { return false }
        return labels.allSatisfy { label in
            !label.isEmpty && label.utf8.count <= 63 && !label.hasPrefix("-") && !label.hasSuffix("-") &&
            label.unicodeScalars.allSatisfy { CharacterSet.alphanumerics.contains($0) || $0 == "-" }
        }
    }
    private static func make(_ text: String, _ kind: Kind, _ service: String) throws -> Target {
        guard text.utf8.count <= 8_192, !text.isEmpty,
              !text.unicodeScalars.contains(where: { CharacterSet.whitespacesAndNewlines.contains($0) || CharacterSet.controlCharacters.contains($0) }),
              !text.contains("\\") else { throw BetaError("Invalid communication URL.") }
        var decoded = text
        for iteration in 0..<4 {
            guard let next = decoded.removingPercentEncoding else {
                if iteration == 0 { throw BetaError("Invalid URL escape.") }; break
            }
            guard !next.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { throw BetaError("Invalid URL control character.") }
            if next == decoded { break }; decoded = next
        }
        guard let url = URL(string: text), let parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { throw BetaError("Invalid communication URL.") }
        if kind == .mail {
            guard parts.scheme == "mailto", parts.query == nil, parts.fragment == nil, parts.host == nil else { throw BetaError("Invalid mail URL.") }
        } else {
            guard parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
                  parts.user == nil, parts.password == nil, (parts.port.map { (1...65535).contains($0) } ?? true),
                  validHost(host) else { throw BetaError("Enter a secure HTTPS address without credentials.") }
        }
        return Target(url: url, kind: kind, service: service)
    }
}
