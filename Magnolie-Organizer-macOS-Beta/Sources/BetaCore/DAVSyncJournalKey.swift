import Foundation
import Security

public enum DAVSyncJournalError: Error, Equatable {
    case invalidInput, unsafeStorage, busy, missingKey, missingJournal, corrupt, capacity, poisoned, externalChange
    case missingRun, collision, invalidTransition, bindingChanged, stalePermit, unsupportedDiskProof
    case keychain(OSStatus)
}

public struct DAVSyncJournalKey {
    public let id: Data
    internal let bytes: Data
    internal let newlyCreated: Bool
    public init(id: Data, bytes: Data, newlyCreated: Bool = false) throws {
        guard id.count == 32, bytes.count == 32 else { throw DAVSyncJournalError.invalidInput }
        self.id = id; self.bytes = bytes; self.newlyCreated = newlyCreated
    }
}
public protocol DAVSyncJournalKeyStore {
    /// Existing ciphertext always passes allowCreate=false. Missing keys never reset evidence.
    func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey
}

/// Independent native journal key; account-password removal does not access this Keychain service.
/// Background calls never request a system consent prompt. Tests inject an isolated temporary keychain.
public final class KeychainDAVSyncJournalKeyStore: DAVSyncJournalKeyStore {
    private let operations: any DAVKeychainOperations
    private let service: String
    private let lock = NSLock()
    public convenience init() {
        self.init(operations: SystemDAVKeychainOperations(), service: "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta.dav-journal-key.v1")
    }
    internal init(operations: any DAVKeychainOperations, service: String) { self.operations = operations; self.service = service }
    public func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey {
        lock.lock(); defer { lock.unlock() }
        guard namespace.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { throw DAVSyncJournalError.invalidInput }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: namespace,
            kSecAttrSynchronizable as String: false, kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail]
        func read() throws -> Data? {
            var lookup = query; lookup[kSecReturnData as String] = true; lookup[kSecMatchLimit as String] = kSecMatchLimitOne
            let (status, data) = operations.copy(lookup)
            if status == errSecItemNotFound { return nil }
            guard status == errSecSuccess else { throw DAVSyncJournalError.keychain(status) }
            guard let data, data.count == 64 else { throw DAVSyncJournalError.corrupt }
            return data
        }
        if let data = try read() { return try DAVSyncJournalKey(id: data.prefix(32), bytes: data.suffix(32)) }
        guard allowCreate else { throw DAVSyncJournalError.missingKey }
        var random = Data(count: 64)
        let status = random.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, 64, $0.baseAddress!) }
        guard status == errSecSuccess else { throw DAVSyncJournalError.keychain(status) }
        var attributes = query; attributes[kSecValueData as String] = random
        attributes[kSecAttrLabel as String] = "Magnolie Organizer DAV synchronization journal"
        let added = operations.add(attributes)
        guard added == errSecSuccess || added == errSecDuplicateItem else { throw DAVSyncJournalError.keychain(added) }
        guard let persisted = try read(), added == errSecDuplicateItem || persisted == random else { throw DAVSyncJournalError.corrupt }
        return try DAVSyncJournalKey(id: persisted.prefix(32), bytes: persisted.suffix(32), newlyCreated: added == errSecSuccess)
    }
}
