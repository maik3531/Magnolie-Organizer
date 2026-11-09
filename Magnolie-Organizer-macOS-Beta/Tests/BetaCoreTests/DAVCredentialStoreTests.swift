import XCTest
import Security
@testable import BetaCore

private final class MemoryDAVKeychain: DAVKeychainOperations {
    var items: [String: Data] = [:]
    var queries: [[String: Any]] = []
    var failure: OSStatus?
    var corruptReadback = false
    private func key(_ query: [String: Any]) -> String {
        (query[kSecAttrService as String] as! String) + ":" + (query[kSecAttrAccount as String] as! String)
    }
    func copy(_ query: [String: Any]) -> (OSStatus, Data?) {
        queries.append(query)
        if let failure { return (failure, nil) }
        guard let bytes = items[key(query)] else { return (errSecItemNotFound, nil) }
        return (errSecSuccess, corruptReadback ? Data("different".utf8) : bytes)
    }
    func add(_ attributes: [String: Any]) -> OSStatus {
        queries.append(attributes)
        if let failure { return failure }
        let key = key(attributes)
        guard items[key] == nil else { return errSecDuplicateItem }
        items[key] = attributes[kSecValueData as String] as? Data
        return errSecSuccess
    }
    func update(_ query: [String: Any], attributes: [String: Any]) -> OSStatus {
        queries.append(query)
        if let failure { return failure }
        let key = key(query)
        guard items[key] != nil else { return errSecItemNotFound }
        items[key] = attributes[kSecValueData as String] as? Data
        return errSecSuccess
    }
    func delete(_ query: [String: Any]) -> OSStatus {
        queries.append(query)
        if let failure { return failure }
        return items.removeValue(forKey: key(query)) == nil ? errSecItemNotFound : errSecSuccess
    }
}

final class DAVCredentialStoreTests: XCTestCase {
    private func identity(_ server: String = "https://cloud.example/nextcloud", user: String = "person", type: DAVAccountType = .nextcloud) throws -> DAVCredentialIdentity {
        try DAVCredentialIdentity(server: server, username: user, accountType: type)
    }
    func testIdentityBindsCanonicalProviderServerAndUser() throws {
        let first = try identity()
        XCTAssertEqual(first, try identity("https://CLOUD.example:443/nextcloud/", user: " person "))
        XCTAssertNotEqual(first.storageKey, try identity("https://other.example/nextcloud").storageKey)
        XCTAssertNotEqual(first.storageKey, try identity(user: "other").storageKey)
        XCTAssertNotEqual(first.storageKey, try identity(type: .genericDAV).storageKey)
        XCTAssertEqual(first.storageKey, "1cb2ad28b900dac0410f024c8b15c71a219ebacd31c9a89320fa4023d28f3ef4")
        XCTAssertThrowsError(try identity("https://person:secret@cloud.example"))
    }
    func testKeychainRoundtripUpdateIsolationAndDeletion() throws {
        let operations = MemoryDAVKeychain()
        let store = KeychainDAVCredentialStore(operations: operations, service: "fixture-service")
        let first = try identity(), other = try identity(user: "other")
        XCTAssertNil(try store.read(for: first))
        try store.write("fixture-app-password", for: first)
        try store.write("different-account-password", for: other)
        XCTAssertEqual(try store.read(for: first), "fixture-app-password")
        try store.write("replacement-password", for: first)
        XCTAssertEqual(try store.read(for: first), "replacement-password")
        XCTAssertEqual(try store.read(for: other), "different-account-password")
        XCTAssertTrue(try store.delete(for: first)); XCTAssertFalse(try store.delete(for: first))
        XCTAssertEqual(try store.read(for: other), "different-account-password")
        for query in operations.queries {
            XCTAssertEqual(query[kSecAttrService as String] as? String, "fixture-service")
            XCTAssertEqual(query[kSecClass as String] as? String, kSecClassGenericPassword as String)
            XCTAssertEqual(query[kSecAttrSynchronizable as String] as? Bool, false)
            XCTAssertEqual(query[kSecUseAuthenticationUI as String] as? String, kSecUseAuthenticationUIFail as String)
            XCTAssertFalse((query[kSecAttrAccount as String] as! String).contains("password"))
        }
    }
    func testLockedKeychainCorruptionAndFailedReadbackNeverReportSuccess() throws {
        let operations = MemoryDAVKeychain()
        let store = KeychainDAVCredentialStore(operations: operations, service: "fixture-service")
        let account = try identity()
        operations.failure = errSecInteractionNotAllowed
        XCTAssertThrowsError(try store.read(for: account)) { XCTAssertEqual($0 as? DAVCredentialError, .keychain(errSecInteractionNotAllowed)) }
        XCTAssertThrowsError(try store.write("fixture-password", for: account))
        XCTAssertThrowsError(try store.delete(for: account))
        operations.failure = nil
        operations.corruptReadback = true
        XCTAssertThrowsError(try store.write("fixture-password", for: account)) { XCTAssertEqual($0 as? DAVCredentialError, .readbackMismatch) }
        operations.corruptReadback = false
        operations.items["fixture-service:" + account.storageKey] = Data([0xff])
        XCTAssertThrowsError(try store.read(for: account)) { XCTAssertEqual($0 as? DAVCredentialError, .invalidStoredCredential) }
        XCTAssertThrowsError(try store.write("", for: account))
        XCTAssertThrowsError(try store.write(String(repeating: "x", count: 16_385), for: account))
    }
    func testActualMacKeychainRoundtripInPrivateTemporaryKeychain() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let path = directory.appendingPathComponent("dav-test.keychain-db").path
        let password = Array("temporary-native-test-keychain".utf8)
        var keychain: SecKeychain?
        let status = path.withCString { path in
            password.withUnsafeBytes { bytes in
                SecKeychainCreate(path, UInt32(bytes.count), bytes.baseAddress, false, nil, &keychain)
            }
        }
        XCTAssertEqual(status, errSecSuccess)
        guard status == errSecSuccess, let keychain else { throw DAVCredentialError.keychain(status) }
        defer { SecKeychainDelete(keychain) }
        let store = KeychainDAVCredentialStore(operations: SystemDAVKeychainOperations(keychain: keychain), service: "test." + UUID().uuidString)
        let account = try identity()
        XCTAssertNil(try store.read(for: account))
        try store.write("fixture-native-keychain-secret", for: account)
        XCTAssertEqual(try store.read(for: account), "fixture-native-keychain-secret")
        try store.write("fixture-updated-keychain-secret", for: account)
        XCTAssertEqual(try store.read(for: account), "fixture-updated-keychain-secret")
        XCTAssertTrue(try store.delete(for: account)); XCTAssertNil(try store.read(for: account))
    }
}
