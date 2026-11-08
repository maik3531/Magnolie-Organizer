import Foundation
import CryptoKit
import Security

/// Password storage is bound to the complete validated provider/server/user tuple. Neither
/// profile exports nor the public WebKit bridge need to carry the account's application password.
public struct DAVCredentialIdentity: Equatable {
    public let server: URL
    public let username: String
    public let accountType: DAVAccountType
    public let storageKey: String

    public init(server: String, username: String, accountType: DAVAccountType = .nextcloud) throws {
        let account = try DAVClient(server: server, username: username, password: "", accountType: accountType)
        self.server = account.server; self.username = account.username; self.accountType = accountType
        var encoded = Data("Magnolie-DAV-credential-v1\0".utf8)
        for field in [accountType.rawValue, account.server.absoluteString, account.username] {
            let bytes = Data(field.utf8)
            var length = UInt32(bytes.count).bigEndian
            withUnsafeBytes(of: &length) { encoded.append(contentsOf: $0) }
            encoded.append(bytes)
        }
        storageKey = SHA256.hash(data: encoded).map { String(format: "%02x", $0) }.joined()
    }
}

public enum DAVCredentialError: Error, Equatable {
    case invalidSecret
    case invalidStoredCredential
    case keychain(OSStatus)
    case readbackMismatch
}

public protocol DAVCredentialStore {
    func read(for identity: DAVCredentialIdentity) throws -> String?
    func write(_ secret: String, for identity: DAVCredentialIdentity) throws
    @discardableResult func delete(for identity: DAVCredentialIdentity) throws -> Bool
}

internal protocol DAVKeychainOperations {
    func copy(_ query: [String: Any]) -> (OSStatus, Data?)
    func add(_ attributes: [String: Any]) -> OSStatus
    func update(_ query: [String: Any], attributes: [String: Any]) -> OSStatus
    func delete(_ query: [String: Any]) -> OSStatus
}

internal struct SystemDAVKeychainOperations: DAVKeychainOperations {
    /// A private keychain is injected only by native tests; production uses the user's login keychain.
    let keychain: SecKeychain?
    init(keychain: SecKeychain? = nil) { self.keychain = keychain }
    private func search(_ query: [String: Any]) -> [String: Any] {
        var query = query
        if let keychain { query[kSecMatchSearchList as String] = [keychain] }
        return query
    }
    func copy(_ query: [String: Any]) -> (OSStatus, Data?) {
        var value: CFTypeRef?
        let status = SecItemCopyMatching(search(query) as CFDictionary, &value)
        return (status, value as? Data)
    }
    func add(_ attributes: [String: Any]) -> OSStatus {
        var attributes = attributes
        if let keychain { attributes[kSecUseKeychain as String] = keychain }
        return SecItemAdd(attributes as CFDictionary, nil)
    }
    func update(_ query: [String: Any], attributes: [String: Any]) -> OSStatus {
        SecItemUpdate(search(query) as CFDictionary, attributes as CFDictionary)
    }
    func delete(_ query: [String: Any]) -> OSStatus { SecItemDelete(search(query) as CFDictionary) }
}

/// Generic passwords live in macOS Keychain, never in preferences, profile files or portable exports.
/// Background access fails explicitly if Keychain is locked or needs user interaction. An explicit
/// native account-settings flow may opt into the operating system's own Keychain consent dialog.
public final class KeychainDAVCredentialStore: DAVCredentialStore {
    private let operations: any DAVKeychainOperations
    private let service: String
    private let allowUserInteraction: Bool
    private let lock = NSRecursiveLock()
    public convenience init(allowUserInteraction: Bool = false) {
        self.init(operations: SystemDAVKeychainOperations(),
            service: "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta.dav-passwords.v1",
            allowUserInteraction: allowUserInteraction)
    }
    internal init(operations: any DAVKeychainOperations, service: String, allowUserInteraction: Bool = false) {
        self.operations = operations; self.service = service; self.allowUserInteraction = allowUserInteraction
    }
    private func query(_ identity: DAVCredentialIdentity) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: identity.storageKey,
         kSecAttrSynchronizable as String: false,
         kSecUseAuthenticationUI as String: allowUserInteraction ? kSecUseAuthenticationUIAllow : kSecUseAuthenticationUIFail]
    }
    public func read(for identity: DAVCredentialIdentity) throws -> String? {
        lock.lock(); defer { lock.unlock() }
        var query = query(identity)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        let (status, data) = operations.copy(query)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw DAVCredentialError.keychain(status) }
        guard let data, (1...16_384).contains(data.count), let secret = String(data: data, encoding: .utf8) else {
            throw DAVCredentialError.invalidStoredCredential
        }
        return secret
    }
    public func write(_ secret: String, for identity: DAVCredentialIdentity) throws {
        lock.lock(); defer { lock.unlock() }
        let bytes = Data(secret.utf8)
        guard (1...16_384).contains(bytes.count) else { throw DAVCredentialError.invalidSecret }
        let query = query(identity)
        let value = [kSecValueData as String: bytes]
        var status = operations.update(query, attributes: value)
        if status == errSecItemNotFound {
            var attributes = query
            attributes[kSecValueData as String] = bytes
            attributes[kSecAttrLabel as String] = "Magnolie Organizer DAV"
            status = operations.add(attributes)
            // Another native settings flow may have created the same account in the meantime.
            if status == errSecDuplicateItem { status = operations.update(query, attributes: value) }
        }
        guard status == errSecSuccess else { throw DAVCredentialError.keychain(status) }
        guard try read(for: identity) == secret else { throw DAVCredentialError.readbackMismatch }
    }
    @discardableResult public func delete(for identity: DAVCredentialIdentity) throws -> Bool {
        lock.lock(); defer { lock.unlock() }
        let status = operations.delete(query(identity))
        if status == errSecItemNotFound { return false }
        guard status == errSecSuccess else { throw DAVCredentialError.keychain(status) }
        guard try read(for: identity) == nil else { throw DAVCredentialError.readbackMismatch }
        return true
    }
}
