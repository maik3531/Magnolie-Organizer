import Foundation
import CoreFoundation
import CryptoKit

/// #785: one framed input and one bounded response. Only native-selected bytes
/// are passed to the helper. Neither side receives an arbitrary source path.
public enum FileImportProtocol {
    public static let maximumInputBytes = 32 * 1024 * 1024
    public static let maximumHeaderBytes = 8192
    public static let maximumOutputBytes = 96 * 1024 * 1024
    public static let formats: Set<String> = ["ics", "lotus", "vcf", "claws", "ldif", "muell"]

    public struct Input {
        public let bytes: Data, header: Data
        public let format: String, name: String, sourceSHA256: String
        public init(bytes: Data, format: String, name: String, language: String, timeZone: String, homeCountry: String) throws {
            guard !bytes.isEmpty, bytes.count <= maximumInputBytes, formats.contains(format),
                  !name.isEmpty, name.utf8.count <= 1024, name != ".", name != "..",
                  !name.contains("/"), !name.contains("\\"),
                  name.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }),
                  language.range(of: "^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$", options: .regularExpression) != nil,
                  language.utf8.count <= 64, !timeZone.isEmpty, timeZone.utf8.count <= 128,
                  homeCountry.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil else {
                throw BetaError("Invalid file import request.")
            }
            self.bytes = bytes; self.format = format; self.name = name
            sourceSHA256 = Self.digest(bytes)
            let fields: [String: Any] = ["schema": 1, "format": format, "name": name, "language": language,
                "timeZone": timeZone, "homeCountry": homeCountry, "byteLength": bytes.count, "sha256": sourceSHA256]
            var encoded = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
            encoded.append(10)
            guard encoded.count <= maximumHeaderBytes else { throw BetaError("File import header is too large.") }
            header = encoded
        }
        private static func digest(_ data: Data) -> String { FileImportProtocol.digest(data) }
    }

    public static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    private static func integer(_ value: Any?, equals expected: Int) -> Bool {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return false }
        return number.doubleValue == Double(expected)
    }

    public static func response(_ bytes: Data, input: Input, manifestSHA256: String) throws -> [String: Any] {
        guard !bytes.isEmpty, bytes.count <= maximumOutputBytes, bytes.last == 10,
              let text = String(data: bytes, encoding: .utf8),
              manifestSHA256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            throw BetaError("The import helper returned an invalid response.")
        }
        let value = try Document.object(text)
        guard integer(value["schema"], equals: 1),
              let ok = value["ok"] as? NSNumber, CFGetTypeID(ok) == CFBooleanGetTypeID() else {
            throw BetaError("The import helper response schema is invalid.")
        }
        if !ok.boolValue {
            guard Set(value.keys) == Set(["schema", "ok", "sourceSHA256", "parserManifestSHA256", "error"]),
                  value["sourceSHA256"] is NSNull || value["sourceSHA256"] as? String == input.sourceSHA256,
                  value["parserManifestSHA256"] is NSNull || value["parserManifestSHA256"] as? String == manifestSHA256,
                  let error = value["error"] as? [String: Any], Set(error.keys) == Set(["code", "message"]),
                  let code = error["code"] as? String, !code.isEmpty, code.utf8.count <= 128,
                  let message = error["message"] as? String, !message.isEmpty, message.utf8.count <= 4096 else {
                throw BetaError("The import helper returned an invalid error.")
            }
            throw BetaError(message)
        }
        guard Set(value.keys) == Set(["schema", "ok", "format", "name", "sourceSHA256", "parserManifestSHA256", "result"]),
              value["sourceSHA256"] as? String == input.sourceSHA256,
              value["parserManifestSHA256"] as? String == manifestSHA256,
              value["format"] as? String == input.format,
              let name = value["name"] as? String, OpaqueUTF8Identity(name) == OpaqueUTF8Identity(input.name),
              let result = value["result"] as? [String: Any], result["fehler"] == nil else {
            throw BetaError("The import result does not belong to the selected file and parser.")
        }
        var records = 0
        for collection in ["termine", "aufgaben", "kontakte", "notizen", "jahrestage", "geburtstage"] {
            if let value = result[collection] {
                guard let list = value as? [[String: Any]] else { throw BetaError("Invalid import collection.") }
                records += list.count
            }
        }
        guard records <= 100_000 else { throw BetaError("The import exceeds the supported record limit.") }
        return result
    }
}
