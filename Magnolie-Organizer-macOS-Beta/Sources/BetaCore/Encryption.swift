#if canImport(CryptoKit) && canImport(CommonCrypto)
import Foundation
import CoreFoundation
import CryptoKit
import CommonCrypto
import Security

// Desktop wire contract: EncryptionService.cs and magnolie-organizer's daten_* functions.
// Passwords and unwrapped keys are memory-only; no keychain, logs or JS storage.
public struct Encryption {
    private let key: SymmetricKey
    private var envelope: [String: Any]
    private static let marker = "magnolie-verschluesselt"
    private static let algorithm = "AES-256-GCM+DEK/PBKDF2-SHA256"

    private static func random(_ count: Int) throws -> Data {
        var bytes = Data(count: count)
        let result = bytes.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, count, $0.baseAddress!) }
        guard result == errSecSuccess else { throw BetaError("Secure random generation failed.") }
        return bytes
    }
    private static func derive(_ password: String, _ salt: Data, _ rounds: Int) throws -> SymmetricKey {
        let passwordBytes = Array(password.utf8)
        var derived = Data(count: 32)
        defer { derived.resetBytes(in: 0..<derived.count) }
        let result = derived.withUnsafeMutableBytes { output in
            salt.withUnsafeBytes { saltBytes in
                passwordBytes.withUnsafeBytes { input in
                    CCKeyDerivationPBKDF(CCPBKDFAlgorithm(kCCPBKDF2),
                        input.baseAddress?.assumingMemoryBound(to: Int8.self), passwordBytes.count,
                        saltBytes.baseAddress!.assumingMemoryBound(to: UInt8.self), salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256), UInt32(rounds),
                        output.baseAddress!.assumingMemoryBound(to: UInt8.self), 32)
                }
            }
        }
        guard result == kCCSuccess else { throw BetaError("Key derivation failed.") }
        return SymmetricKey(data: derived)
    }
    private static func aad(_ purpose: String, _ id: Data) -> Data {
        Data(("magnolie-daten-v2\0" + purpose + "\0").utf8) + id
    }
    private static func bytes(_ root: [String: Any], _ name: String, count: Int? = nil) throws -> Data {
        guard let string = root[name] as? String, let data = Data(base64Encoded: string),
              data.base64EncodedString() == string, count.map({ data.count == $0 }) ?? (data.count >= 16) else {
            throw BetaError("Damaged encrypted envelope.")
        }
        return data
    }
    private static func seal(_ plain: Data, _ key: SymmetricKey, _ nonce: Data, _ aad: Data) throws -> Data {
        let sealed = try AES.GCM.seal(plain, using: key, nonce: AES.GCM.Nonce(data: nonce), authenticating: aad)
        return sealed.ciphertext + sealed.tag
    }
    private static func open(_ cipher: Data, _ key: SymmetricKey, _ nonce: Data, _ aad: Data) throws -> Data {
        let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: nonce),
                                       ciphertext: cipher.dropLast(16), tag: cipher.suffix(16))
        return try AES.GCM.open(box, using: key, authenticating: aad)
    }

    public static func create(password: String) throws -> Encryption {
        guard password.count >= 4 else { throw BetaError("Use at least four password characters.") }
        var dek = try random(32)
        defer { dek.resetBytes(in: 0..<dek.count) }
        let id = try random(16), salt = try random(16), nonce = try random(12)
        let wrapped = try seal(dek, derive(password, salt, 240_000), nonce, aad("dek", id))
        return Encryption(key: SymmetricKey(data: dek), envelope: [
            "magnolie": marker, "fassung": 2, "verfahren": algorithm,
            "dekKennung": id.base64EncodedString(), "salz": salt.base64EncodedString(),
            "runden": 240_000, "dekNonce": nonce.base64EncodedString(), "dekDaten": wrapped.base64EncodedString()
        ])
    }

    public static func unlock(_ text: String, password: String) throws -> (String, Encryption) {
        let root = try Document.object(text)
        guard root["magnolie"] as? String == marker,
              let version = root["fassung"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              let rounds = root["runden"] as? NSNumber, CFGetTypeID(rounds) != CFBooleanGetTypeID(),
              rounds.doubleValue == Double(rounds.intValue), (50_000...1_000_000).contains(rounds.intValue) else {
            throw BetaError("Damaged encrypted envelope.")
        }
        let salt = try bytes(root, "salz", count: 16)
        let kek = try derive(password, salt, rounds.intValue)
        let plain: Data
        let session: Encryption
        if version.doubleValue == 1, root["verfahren"] as? String == "AES-256-GCM/PBKDF2-SHA256" {
            plain = try open(bytes(root, "daten"), kek, bytes(root, "nonce", count: 12), Data(marker.utf8))
            var next = try create(password: password)
            // Retain extensions when upgrading a shipped v1 envelope on the next explicit save.
            for (name, value) in root where next.envelope[name] == nil && !["daten", "nonce"].contains(name) {
                next.envelope[name] = value
            }
            session = next
        } else if version.doubleValue == 2, root["verfahren"] as? String == algorithm {
            let id = try bytes(root, "dekKennung", count: 16)
            var dek = try open(bytes(root, "dekDaten", count: 48), kek,
                               bytes(root, "dekNonce", count: 12), aad("dek", id))
            defer { dek.resetBytes(in: 0..<dek.count) }
            guard dek.count == 32 else { throw BetaError("Invalid data key.") }
            let key = SymmetricKey(data: dek)
            plain = try open(bytes(root, "daten"), key, bytes(root, "datenNonce", count: 12), aad("inhalt", id))
            session = Encryption(key: key, envelope: root)
        } else { throw BetaError("Unsupported encrypted envelope version.") }
        guard let result = String(data: plain, encoding: .utf8) else { throw BetaError("Invalid decrypted UTF-8.") }
        _ = try Document.plain(result)
        return (result, session)
    }

    public func encrypt(_ text: String) throws -> String {
        _ = try Document.plain(text)
        var root = envelope
        let nonce = try Self.random(12), id = try Self.bytes(root, "dekKennung", count: 16)
        root["datenNonce"] = nonce.base64EncodedString()
        root["daten"] = try Self.seal(Data(text.utf8), key, nonce, Self.aad("inhalt", id)).base64EncodedString()
        return try Document.encode(root)
    }
}
#endif
