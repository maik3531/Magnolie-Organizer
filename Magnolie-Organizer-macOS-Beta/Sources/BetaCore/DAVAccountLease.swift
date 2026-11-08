import Foundation
import CryptoKit

public enum DAVAccountLeaseError: Error, Equatable {
    case invalidLease, expired, capacity, discoveryRequired, invalidSelection, signerUnavailable, bindingChanged
}

/// Opaque native handle. Not serializable and never a transport/auth credential.
public struct DAVSyncAccountLease: Equatable {
    internal let owner: UUID, id: UUID
}
/// Native-only stable fields remain internal to BetaCore; there is no bridge payload or Codable
/// conformance. Future journal/coordinator modules may consume them after independent book proof.
public struct DAVSyncAccountLeaseBinding {
    public let calendars: [DAVCollection]
    internal let accountIdentity: String, persistentAccountBinding: String
    internal let sessionRevision: String, discoveryFingerprint: String
}

/// Only an already-open verified journal constructs this opaque domain-separated signer.
/// It never exposes its subkey, journal encryption key or a public password-derived digest.
public final class DAVAccountBindingSigner {
    private let key: SymmetricKey
    private let namespace: String
    private let validateJournal: () async throws -> Void
    private let lock = NSLock()
    private var active = true
    internal init(namespace: String, key: SymmetricKey, validateJournal: @escaping () async throws -> Void) {
        self.namespace = namespace; self.key = key; self.validateJournal = validateJournal
    }
    internal func invalidate() { lock.lock(); active = false; lock.unlock() }
    private func checkActive() throws {
        lock.lock(); defer { lock.unlock() }
        guard active else { throw DAVAccountLeaseError.signerUnavailable }
    }
    internal func ensureCurrent() async throws {
        try checkActive()
        do { try await validateJournal() }
        catch { invalidate(); throw DAVAccountLeaseError.signerUnavailable }
        try checkActive()
    }
    internal func bind(configuration: DAVAccountConfiguration, secret: String, storeNamespace: String) throws -> String {
        lock.lock(); defer { lock.unlock() }
        guard active else { throw DAVAccountLeaseError.signerUnavailable }
        guard storeNamespace.utf8.count <= 16_384, secret.utf8.count <= 16_384 else { throw DAVAccountLeaseError.bindingChanged }
        let fields = ["Magnolie-DAV-stable-account-context-v1", namespace, storeNamespace,
            configuration.kontoArt.rawValue, configuration.server, configuration.benutzer,
            configuration.davAktiv ? "dav-on" : "dav-off", configuration.briefkastenAktiv ? "mailbox-on" : "mailbox-off",
            try configuration.identity.storageKey, "credential-present", secret]
        let material = OpaqueUTF8Identity(parts: fields).bytes
        return HMAC<SHA256>.authenticationCode(for: material, using: key).map { String(format: "%02x", $0) }.joined()
    }
}
