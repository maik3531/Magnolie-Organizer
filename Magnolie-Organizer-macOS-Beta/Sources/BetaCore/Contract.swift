import Foundation
import CoreFoundation

public struct BetaError: LocalizedError {
    public let errorDescription: String?
    public init(_ message: String) { errorDescription = message }
}

public enum Command: String, CaseIterable {
    case bereit, entsperren, speichern, kennwort_setzen
    case beenden, beenden_bereit, beenden_abgebrochen
    case ablage_kopieren, ablage_holen, sicherung, export
    case erinnerung_zeigen, erinnerung_einrichten, notiz_anhang_datei
    case mutations_snapshot, sicherung_waehlen, sicherung_wiederherstellen, regional_einstellungen
}

public struct Request {
    public let command: Command
    public let fields: [String: Any]

    public init(_ text: String) throws {
        fields = try Document.object(text)
        guard let name = fields["cmd"] as? String, let command = Command(rawValue: name) else {
            throw BetaError("Not implemented in macOS Beta. Nothing was changed.")
        }
        self.command = command
        var schema: [String: String] = ["cmd": "string"]
        var optional: Set<String> = []
        switch command {
        case .entsperren: schema["kennwort"] = "string"
        case .speichern: schema.merge(["id": "integer", "text": "string"]) { _, b in b }
        case .kennwort_setzen:
            schema.merge(["alt": "string", "neu": "string", "sicherungen": "bool",
                          "sicherungsordner": "string"]) { _, b in b }
            optional = ["sicherungen", "sicherungsordner"]
        case .ablage_kopieren: schema["text"] = "string"
        case .sicherung: schema.merge(["pfad": "string", "kennwort": "string"]) { _, b in b }
        case .mutations_snapshot: schema.merge(["token": "string", "reason": "string"]) { _, b in b }
        case .sicherung_wiederherstellen:
            schema.merge(["pfad": "string", "kennwort": "string", "sicherungsordner": "string"]) { _, b in b }
            optional = ["sicherungsordner"]
        case .regional_einstellungen: schema["regional"] = "object"
        case .export: schema.merge(["art": "string", "daten": "array"]) { _, b in b }
        case .erinnerung_zeigen:
            for key in ["kopf", "rumpf", "art", "stil"] { schema[key] = "string" }
        case .erinnerung_einrichten:
            schema.merge(["an": "bool", "wecken": "bool", "vorlauf": "minutes", "termine": "array"]) { _, b in b }
            optional = ["vorlauf", "termine"]
        case .notiz_anhang_datei:
            schema.merge(["id": "integer", "daten": "string", "name": "string", "aktion": "string"]) { _, b in b }
        default: break
        }
        guard Set(fields.keys).isSubset(of: Set(schema.keys)),
              Set(schema.keys).subtracting(optional).isSubset(of: Set(fields.keys)) else {
            throw BetaError("Invalid bridge fields.")
        }
        for (key, value) in fields {
            let number = value as? NSNumber
            let boolean = number.map { CFGetTypeID($0) == CFBooleanGetTypeID() } ?? false
            let integer = number.map { !boolean && $0.doubleValue.isFinite &&
                $0.doubleValue.rounded() == $0.doubleValue && abs($0.doubleValue) <= 9_007_199_254_740_991 } ?? false
            let valid: Bool
            switch schema[key] {
            case "string": valid = value is String
            case "array": valid = value is [Any]
            case "object": valid = value is [String: Any]
            case "bool": valid = boolean
            case "integer": valid = integer
            case "minutes": valid = value is String || integer
            default: valid = false
            }
            guard valid else { throw BetaError("Invalid bridge field type.") }
        }
        if command == .speichern, ((fields["id"] as? NSNumber)?.int64Value ?? 0) < 1 {
            throw BetaError("Invalid save identifier.")
        }
    }
    public func text(_ name: String) -> String { fields[name] as? String ?? "" }
}

public enum Document {
    public static let maximumBytes = 384 * 1024 * 1024

    public static func object(_ text: String) throws -> [String: Any] {
        let data = Data(text.utf8)
        guard !data.isEmpty, data.count <= maximumBytes else { throw BetaError("Invalid document size.") }
        // JSONSerialization accepts duplicate keys. Scan decoded key tokens first,
        // including escaped spellings, to reject ambiguous envelopes and documents.
        var scanner = JSONKeys(bytes: Array(data))
        try scanner.scan()
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BetaError("Expected a JSON object; original file was not changed.")
        }
        return value
    }

    public static func encode(_ value: Any) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .fragmentsAllowed])
        guard let text = String(data: data, encoding: .utf8) else { throw BetaError("Invalid UTF-8.") }
        return text
    }

    public static func plain(_ text: String) throws -> [String: Any] {
        let value = try object(text)
        guard !["magnolie", "verfahren", "salz", "dekDaten", "datenNonce", "nonce"].contains(where: { value[$0] != nil }) else {
            throw BetaError("Encrypted or unrecognized document; refusing plaintext fallback.")
        }
        // A new profile is initialized explicitly as {}. Existing files must be organizer documents.
        guard ["termine", "aufgaben", "kontakte", "notizen"].allSatisfy({ value[$0] is [Any] }) else {
            throw BetaError("Unrecognized organizer document; original file was not changed.")
        }
        return value
    }

    public static func assertNoLoss(_ old: Any, _ new: Any, depth: Int = 0) throws {
        guard depth < 64 else { throw BetaError("Document nesting limit exceeded.") }
        if let a = old as? [String: Any] {
            guard let b = new as? [String: Any], Set(a.keys).isSubset(of: Set(b.keys)) else {
                throw BetaError("Save would drop existing fields; a recovery checkpoint is required.")
            }
            for (key, value) in a { try assertNoLoss(value, b[key]!, depth: depth + 1) }
        } else if let a = old as? [Any] {
            guard let b = new as? [Any], b.count >= a.count else {
                throw BetaError("Save would shorten an existing array; a recovery checkpoint is required.")
            }
            let keyed = !a.isEmpty && a.allSatisfy { ($0 as? [String: Any])?["id"] is String }
            if keyed {
                var byID: [String: Any] = [:]
                for value in b {
                    guard let id = (value as? [String: Any])?["id"] as? String, byID[id] == nil else {
                        throw BetaError("Ambiguous record identifiers.")
                    }
                    byID[id] = value
                }
                for value in a {
                    let id = (value as! [String: Any])["id"] as! String
                    guard let next = byID[id] else { throw BetaError("Save would delete a record; a recovery checkpoint is required.") }
                    try assertNoLoss(value, next, depth: depth + 1)
                }
            } else {
                for (index, value) in a.enumerated() { try assertNoLoss(value, b[index], depth: depth + 1) }
            }
        }
    }
}

private struct JSONKeys {
    let bytes: [UInt8]
    var index = 0
    mutating func whitespace() { while index < bytes.count && [9, 10, 13, 32].contains(bytes[index]) { index += 1 } }
    mutating func scan() throws {
        try value(0); whitespace()
        guard index == bytes.count else { throw BetaError("Invalid JSON suffix.") }
    }
    mutating func string() throws -> String {
        let start = index
        guard index < bytes.count, bytes[index] == 34 else { throw BetaError("Invalid JSON string.") }
        index += 1
        while index < bytes.count {
            let char = bytes[index]; index += 1
            if char == 92 { index += 1 }
            else if char == 34 {
                let token = Data(bytes[start..<index])
                guard let result = try JSONSerialization.jsonObject(with: token, options: [.fragmentsAllowed]) as? String else {
                    throw BetaError("Invalid JSON string.")
                }
                return result
            }
        }
        throw BetaError("Unterminated JSON string.")
    }
    mutating func value(_ depth: Int) throws {
        whitespace()
        guard depth < 64, index < bytes.count else { throw BetaError("Invalid JSON depth or value.") }
        let first = bytes[index]
        if first == 34 { _ = try string(); return }
        if first == 123 || first == 91 {
            index += 1; whitespace()
            let end: UInt8 = first == 123 ? 125 : 93
            if index < bytes.count, bytes[index] == end { index += 1; return }
            var keys: Set<String> = []
            while true {
                if first == 123 {
                    whitespace(); let key = try string()
                    guard keys.insert(key).inserted else { throw BetaError("Duplicate JSON key.") }
                    whitespace()
                    guard index < bytes.count, bytes[index] == 58 else { throw BetaError("Invalid JSON object.") }
                    index += 1
                }
                try value(depth + 1); whitespace()
                guard index < bytes.count else { throw BetaError("Truncated JSON.") }
                let separator = bytes[index]; index += 1
                if separator == end { return }
                guard separator == 44 else { throw BetaError("Invalid JSON separator.") }
            }
        }
        let start = index
        while index < bytes.count && ![9, 10, 13, 32, 44, 93, 125].contains(bytes[index]) { index += 1 }
        guard index > start else { throw BetaError("Invalid JSON token.") }
    }
}
