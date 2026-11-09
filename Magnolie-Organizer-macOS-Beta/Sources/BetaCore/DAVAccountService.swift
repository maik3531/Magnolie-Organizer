import Foundation
import CoreFoundation
import CryptoKit
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

public enum DAVAccountError: Error, Equatable {
    case invalidConfiguration, missingPassword, conflict, notActive, unsupportedFeature
    case verificationFailed, storageUnavailable, credentialUnavailable
}

/// The canonical native account configuration, shared by GUI and correlated bridge operations.
/// The organizer document, source bindings and records are never changed by this service.
public struct DAVAccountConfiguration: Equatable {
    public let kontoArt: DAVAccountType
    public let davAktiv: Bool
    public let briefkastenAktiv: Bool
    public let server: String
    public let benutzer: String
    public init(kontoArt: DAVAccountType = .nextcloud, davAktiv: Bool,
                briefkastenAktiv: Bool = false, server: String, benutzer: String) throws {
        guard !(kontoArt == .genericDAV && briefkastenAktiv), server.utf8.count <= 4096 else {
            throw DAVAccountError.invalidConfiguration
        }
        let identity = try DAVCredentialIdentity(server: server, username: benutzer, accountType: kontoArt)
        self.kontoArt = kontoArt; self.davAktiv = davAktiv; self.briefkastenAktiv = briefkastenAktiv
        self.server = identity.server.absoluteString; self.benutzer = identity.username
    }
    public var identity: DAVCredentialIdentity {
        // Construction above has already validated these immutable fields.
        get throws { try DAVCredentialIdentity(server: server, username: benutzer, accountType: kontoArt) }
    }
    public var dictionary: [String: Any] {
        ["kontoArt": kontoArt.rawValue, "davAktiv": davAktiv, "briefkastenAktiv": briefkastenAktiv,
         "server": server, "benutzer": benutzer]
    }
    public init(dictionary value: [String: Any]) throws {
        let keys = Set(value.keys)
        guard keys == ["aktiv", "server", "benutzer"] ||
                keys == ["davAktiv", "briefkastenAktiv", "server", "benutzer"] ||
                keys == ["kontoArt", "davAktiv", "briefkastenAktiv", "server", "benutzer"],
              let server = value["server"] as? String, let user = value["benutzer"] as? String,
              (!keys.contains("kontoArt") || value["kontoArt"] is String),
              let kind = DAVAccountType(rawValue: value["kontoArt"] as? String ?? "nextcloud") else {
            throw DAVAccountError.invalidConfiguration
        }
        func bool(_ key: String) throws -> Bool {
            guard let number = value[key] as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else {
                throw DAVAccountError.invalidConfiguration
            }
            return number.boolValue
        }
        let legacy = keys.contains("aktiv")
        try self.init(kontoArt: kind, davAktiv: bool(legacy ? "aktiv" : "davAktiv"),
            briefkastenAktiv: bool(legacy ? "aktiv" : "briefkastenAktiv"), server: server, benutzer: user)
    }
}

public protocol DAVAccountConfigurationStore {
    /// Stable store namespace prevents revisions from crossing profile/store contexts.
    var revisionNamespace: String { get }
    func read() throws -> DAVAccountConfiguration?
    /// nil is used solely to roll back a failed initial setup, not to erase organizer records.
    func replace(_ configuration: DAVAccountConfiguration?) throws
}

public final class DAVAccountFileStore: DAVAccountConfigurationStore {
    public let file: URL
    private let directory: URL
    public var revisionNamespace: String { file.path }
    public init(directory: URL) throws {
        self.directory = directory.standardizedFileURL
        self.file = self.directory.appendingPathComponent("nextcloud.json")
        try validateDirectory()
    }
    private func validateDirectory() throws {
        var info = stat()
        guard directory.path == directory.resolvingSymlinksInPath().path,
              lstat(directory.path, &info) == 0, info.st_uid == getuid(),
              info.st_mode & mode_t(S_IFMT) == mode_t(S_IFDIR), info.st_mode & 0o077 == 0 else {
            throw DAVAccountError.storageUnavailable
        }
    }
    public func read() throws -> DAVAccountConfiguration? {
        try validateDirectory()
        var info = stat()
        if lstat(file.path, &info) != 0 {
            if errno == ENOENT { return nil }
            throw DAVAccountError.storageUnavailable
        }
        guard info.st_size > 0, info.st_size <= 16_384 else { throw DAVAccountError.invalidConfiguration }
        guard let data = try AtomicStore.read(file, maximumBytes: 16_384), let text = String(data: data, encoding: .utf8) else {
            throw DAVAccountError.invalidConfiguration
        }
        do { return try DAVAccountConfiguration(dictionary: Document.object(text)) }
        catch { throw DAVAccountError.invalidConfiguration }
    }
    public func replace(_ configuration: DAVAccountConfiguration?) throws {
        try validateDirectory()
        if let configuration {
            let bytes = try JSONSerialization.data(withJSONObject: configuration.dictionary, options: [.sortedKeys])
            guard bytes.count <= 16_384 else { throw DAVAccountError.invalidConfiguration }
            try AtomicStore.write(bytes, to: file)
        } else {
            // Validate owner/type/link count before deleting a file created by this transaction.
            guard try AtomicStore.read(file) != nil else { return }
            guard unlink(file.path) == 0 else { throw DAVAccountError.storageUnavailable }
            let fd = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard fd >= 0 else { throw DAVAccountError.storageUnavailable }
            defer { close(fd) }
            guard fsync(fd) == 0 else { throw DAVAccountError.storageUnavailable }
        }
        guard try read() == configuration else { throw DAVAccountError.verificationFailed }
    }
}

public struct DAVAccountStatus {
    public let configuration: DAVAccountConfiguration?
    public let credentialPresent: Bool?
    public let revision: String?
    public let state: String
    public let errorCode: String
    public let calendars: [DAVCollection]
    public let addressBooks: [DAVCollection]
    public let connectivityChecked: Bool
    public func payload(requestID: String? = nil, persisted: Bool? = nil) -> [String: Any] {
        var value: [String: Any] = ["verfuegbar": true, "aktiv": configuration?.briefkastenAktiv ?? false,
            "kontoArt": configuration?.kontoArt.rawValue ?? "nextcloud", "davAktiv": configuration?.davAktiv ?? false,
            "briefkastenAktiv": configuration?.briefkastenAktiv ?? false,
            "server": configuration?.server ?? "", "url": configuration?.server ?? "", "benutzer": configuration?.benutzer ?? "",
            "kennwortVorhanden": credentialPresent ?? false, "revision": revision as Any? ?? NSNull(),
            "zustand": state, "fehlerCode": errorCode,
            "fehler": errorCode == "none" ? "" : Self.message(errorCode),
            "kalender": calendars.map(Self.collectionPayload), "adressbuecher": addressBooks.map(Self.collectionPayload),
            "connectivityChecked": connectivityChecked]
        if let requestID { value["requestId"] = requestID; value["ok"] = true }
        if let persisted { value["persisted"] = persisted; value["verified"] = persisted }
        return value
    }
    private static func collectionPayload(_ source: DAVCollection) -> [String: Any] {
        var value: [String: Any] = ["uid": source.uid, "name": source.name, "href": source.href.absoluteString, "art": source.kind.rawValue]
        if source.kind == .calendar { value["supportsVtodo"] = source.supportsVtodo }
        return value
    }
    private static func message(_ code: String) -> String {
        switch code {
        case "http_401": return "DAV authentication failed (HTTP 401)."
        case "http_403": return "DAV access was denied (HTTP 403)."
        case "conflict": return "The account changed. Read its current state before retrying."
        case "app_password_missing": return "The account application password is missing."
        case "secret_service_unavailable": return "The macOS Keychain credential is unavailable."
        case "unsupported_feature": return "The Nextcloud mailbox is not implemented on this platform."
        case "timeout": return "DAV discovery exceeded its time limit."
        case "verification_failed": return "The account change could not be verified. Reload before retrying."
        default: return "The DAV account operation failed."
        }
    }
}

public struct DAVAccountDiscovery {
    public let status: DAVAccountStatus
    public let reachable: Bool
    public let partial: Bool
    public func connectionTestPayload(requestID: String) -> [String: Any] {
        ["requestId": requestID, "ok": true, "revision": status.revision as Any? ?? NSNull(),
         "reachable": reachable, "partial": partial, "errorCode": status.errorCode,
         "calendars": status.calendars.count, "addressBooks": status.addressBooks.count]
    }
}

/// One actor owns all account mutations. A discovery suspension never grants permission to
/// publish results for credentials/configuration that changed while the request was running.
public actor DAVAccountService {
    private let configurationStore: any DAVAccountConfigurationStore
    private let credentials: any DAVCredentialStore
    private let transport: any BoundedHTTPTransport
    private let revisionKey = SymmetricKey(size: .bits256)
    private var epoch: UInt64 = 0
    private var poisoned = false
    private var cachedDiscovery: DAVAccountDiscovery?
    private let leaseOwner = UUID()
    nonisolated private let bookAdmission = DAVBookAdmission()
    private let leaseClock: () -> TimeInterval
    private let readClock: DAVReadClock?
    private var activeReads: [UUID: UUID] = [:]
    private var leaseGeneration: UInt64 = 0
    private var discoveryGeneration: UInt64 = 0
    private struct ActiveLease {
        let binding: DAVSyncAccountLeaseBinding, signer: DAVAccountBindingSigner
        let generation: UInt64, discoveryGeneration: UInt64, expires: TimeInterval
        let gate: DAVReadLeaseGate?
        let bookSession: DAVBookSessionTicket
    }
    private var leases: [UUID: ActiveLease] = [:]
    private struct Snapshot {
        let configuration: DAVAccountConfiguration?
        let secret: String?
        let revision: String
    }
    public init(configuration: any DAVAccountConfigurationStore,
                credentials: any DAVCredentialStore = KeychainDAVCredentialStore(),
                transport: any BoundedHTTPTransport = URLSessionBoundedTransport(),
                monotonicTime: (() -> TimeInterval)? = nil) {
        self.configurationStore = configuration; self.credentials = credentials; self.transport = transport
        if let monotonicTime { self.leaseClock = monotonicTime; self.readClock = nil }
        else { self.leaseClock = { DAVReadClock.system.now() }; self.readClock = .system }
    }
    internal init(configuration: any DAVAccountConfigurationStore, credentials: any DAVCredentialStore,
                  transport: any BoundedHTTPTransport, readClock: DAVReadClock) {
        self.configurationStore = configuration; self.credentials = credentials; self.transport = transport
        self.leaseClock = { readClock.now() }; self.readClock = readClock
    }
    deinit { for active in leases.values { active.gate?.revoke() } }
    private func snapshot() throws -> Snapshot {
        guard !poisoned else { throw DAVAccountError.verificationFailed }
        let configuration = try configurationStore.read()
        let secret = try configuration.map { try credentials.read(for: $0.identity) } ?? nil
        let material: [String: Any] = ["store": configurationStore.revisionNamespace,
            "settings": configuration?.dictionary as Any? ?? NSNull(),
            "credential": secret as Any? ?? NSNull(), "epoch": String(epoch)]
        let data = try JSONSerialization.data(withJSONObject: material, options: [.sortedKeys])
        let revision = HMAC<SHA256>.authenticationCode(for: data, using: revisionKey).map { String(format: "%02x", $0) }.joined()
        return Snapshot(configuration: configuration, secret: secret, revision: revision)
    }
    private func status(_ snapshot: Snapshot, calendars: [DAVCollection] = [], books: [DAVCollection] = [],
                        checked: Bool = false, error: String = "none") -> DAVAccountStatus {
        let config = snapshot.configuration
        let state: String
        if error != "none" { state = "fehler" }
        else if config == nil { state = "nicht_eingerichtet" }
        else if !(config!.davAktiv || config!.briefkastenAktiv) { state = "aus" }
        else if snapshot.secret?.isEmpty != false { state = "unvollstaendig" }
        else if config!.briefkastenAktiv { state = "fehler" }
        else { state = "bereit" }
        return DAVAccountStatus(configuration: config, credentialPresent: snapshot.secret?.isEmpty == false,
            revision: snapshot.revision, state: state,
            errorCode: error == "none" && config?.briefkastenAktiv == true ? "unsupported_feature" : error,
            calendars: calendars, addressBooks: books, connectivityChecked: checked)
    }
    /// Local metadata only: this does not contact a server or claim a completed synchronization.
    public func status() -> DAVAccountStatus {
        do {
            let current = try snapshot()
            if let cachedDiscovery, cachedDiscovery.status.revision == current.revision {
                return cachedDiscovery.status
            }
            cachedDiscovery = nil
            return status(current)
        }
        catch {
            cachedDiscovery = nil
            return DAVAccountStatus(configuration: try? configurationStore.read(), credentialPresent: nil,
                revision: nil, state: "fehler", errorCode: Self.code(error), calendars: [], addressBooks: [], connectivityChecked: false)
        }
    }
    public func save(expectedRevision: String, configuration wanted: DAVAccountConfiguration,
                     applicationPassword: String = "", clearPassword: Bool = false) throws -> DAVAccountStatus {
        let previous = try snapshot()
        guard previous.revision == expectedRevision else { throw DAVAccountError.conflict }
        guard !wanted.briefkastenAktiv else { throw DAVAccountError.unsupportedFeature }
        guard !(clearPassword && (!applicationPassword.isEmpty || wanted.davAktiv)),
              applicationPassword.utf8.count <= 16_384 else { throw DAVAccountError.invalidConfiguration }
        let target = try wanted.identity
        let oldIdentity = try previous.configuration?.identity
        let priorTarget = try credentials.read(for: target)
        guard try snapshot().revision == previous.revision, target != oldIdentity || priorTarget == previous.secret else {
            throw DAVAccountError.conflict
        }
        let replacement = !applicationPassword.isEmpty ? applicationPassword : clearPassword ? nil : priorTarget
        if wanted.davAktiv && (replacement?.isEmpty != false || (target != oldIdentity && applicationPassword.isEmpty)) {
            throw DAVAccountError.missingPassword
        }
        // Only a validated request reaching its first actual mutation revokes active leases.
        revokeLeases()
        do {
            if !applicationPassword.isEmpty { try credentials.write(applicationPassword, for: target) }
            else if clearPassword { try credentials.delete(for: target) }
            try configurationStore.replace(wanted)
            let readback = try snapshot()
            guard readback.configuration == wanted, readback.secret == replacement else { throw DAVAccountError.verificationFailed }
            if let oldIdentity, oldIdentity != target {
                try credentials.delete(for: oldIdentity)
                guard try credentials.read(for: oldIdentity) == nil else { throw DAVAccountError.verificationFailed }
            }
            let final = try snapshot()
            guard final.configuration == wanted, final.secret == replacement else { throw DAVAccountError.verificationFailed }
            epoch &+= 1
            cachedDiscovery = nil
            return status(try snapshot())
        } catch {
            // Both stores can fail after committing. Restore the complete old context and verify it;
            // an unknown third-party change is never overwritten during rollback.
            do {
                let actual = try configurationStore.read()
                guard actual == previous.configuration || actual == wanted else { throw DAVAccountError.verificationFailed }
                let currentTarget = try credentials.read(for: target)
                guard currentTarget == priorTarget || currentTarget == replacement else { throw DAVAccountError.verificationFailed }
                if let oldIdentity, oldIdentity != target {
                    let currentOld = try credentials.read(for: oldIdentity)
                    guard currentOld == nil || currentOld == previous.secret else { throw DAVAccountError.verificationFailed }
                    try restore(previous.secret, for: oldIdentity)
                }
                try restore(priorTarget, for: target)
                try configurationStore.replace(previous.configuration)
                let restored = try snapshot()
                guard restored.configuration == previous.configuration, restored.secret == previous.secret,
                      try credentials.read(for: target) == priorTarget else { throw DAVAccountError.verificationFailed }
            } catch {
                poisoned = true
                cachedDiscovery = nil
                throw DAVAccountError.verificationFailed
            }
            throw error
        }
    }
    private func restore(_ secret: String?, for identity: DAVCredentialIdentity) throws {
        if let secret { try credentials.write(secret, for: identity) }
        else { try credentials.delete(for: identity) }
    }
    public func discover(expectedRevision: String) async throws -> DAVAccountDiscovery {
        let before = try snapshot()
        guard before.revision == expectedRevision else { throw DAVAccountError.conflict }
        guard let configuration = before.configuration, configuration.davAktiv else { throw DAVAccountError.notActive }
        guard let secret = before.secret, !secret.isEmpty else { throw DAVAccountError.missingPassword }
        // A refresh cannot leave old capabilities authorized while its network work suspends.
        revokeLeases(); discoveryGeneration &+= 1; cachedDiscovery = nil
        let refreshGeneration = discoveryGeneration
        let client = try DAVClient(server: configuration.server, username: configuration.benutzer,
            password: secret, accountType: configuration.kontoArt,
            transport: DAVAccountDeadlineTransport(base: transport, deadline: ProcessInfo.processInfo.systemUptime + 60))
        var calendars: [DAVCollection] = [], books: [DAVCollection] = []
        var code = "none"
        do {
            calendars = try await client.collections(for: .calendar)
            // Check between service discovery calls as well as after the final await.
            guard refreshGeneration == discoveryGeneration, try snapshot().revision == before.revision else { throw DAVAccountError.conflict }
            books = try await client.collections(for: .addressbook)
        } catch is CancellationError { throw CancellationError() }
        catch { code = Self.code(error) }
        guard refreshGeneration == discoveryGeneration, try snapshot().revision == before.revision else { throw DAVAccountError.conflict }
        let partial = code != "none" && (!calendars.isEmpty || !books.isEmpty)
        let result = status(before, calendars: calendars, books: books, checked: true, error: code)
        let discovery = DAVAccountDiscovery(status: result, reachable: code == "none" || partial, partial: partial)
        cachedDiscovery = discovery
        return discovery
    }
    private func revokeLeases() {
        leaseGeneration &+= 1
        for active in leases.values { active.gate?.revoke() }
        leases.removeAll()
    }
    private func stableLeaseSnapshot() throws -> Snapshot {
        let first = try snapshot(), second = try snapshot()
        guard first.revision == second.revision else { throw DAVAccountLeaseError.bindingChanged }
        return second
    }
    private func selectedLeaseSources(_ requested: [String], snapshot: Snapshot) throws -> [DAVCollection] {
        guard let cached = cachedDiscovery, cached.status.revision == snapshot.revision,
              cached.status.connectivityChecked, cached.status.errorCode == "none", cached.reachable, !cached.partial else {
            throw DAVAccountLeaseError.discoveryRequired
        }
        guard (1...100).contains(requested.count) else { throw DAVAccountLeaseError.invalidSelection }
        var available: [OpaqueUTF8Identity: DAVCollection] = [:], selected = Set<OpaqueUTF8Identity>()
        guard let configuration = snapshot.configuration else { throw DAVAccountError.notActive }
        let validator = try DAVClient(server: configuration.server, username: configuration.benutzer, password: "", accountType: configuration.kontoArt)
        for source in cached.status.calendars {
            let path: Data, canonical: URL
            do {
                path = try DAVClient.recoveryPath(source.href.absoluteString)
                canonical = try validator.sameOriginURL(source.href.absoluteString)
            } catch { throw DAVAccountLeaseError.invalidSelection }
            guard source.uid.utf8.count <= 1024, source.kind == .calendar, path.last == 47,
                  OpaqueUTF8Identity(source.uid) == OpaqueUTF8Identity(DAVClient.sourceID(kind: source.kind, href: source.href, accountType: configuration.kontoArt)),
                  OpaqueUTF8Identity(canonical.absoluteString) == OpaqueUTF8Identity(source.href.absoluteString),
                  available.updateValue(source, forKey: OpaqueUTF8Identity(source.uid)) == nil else { throw DAVAccountLeaseError.invalidSelection }
        }
        return try requested.map { uid in
            guard uid.utf8.count <= 1024, selected.insert(OpaqueUTF8Identity(uid)).inserted, let source = available[OpaqueUTF8Identity(uid)] else { throw DAVAccountLeaseError.invalidSelection }
            return source
        }
    }
    private func fingerprint(_ sources: [DAVCollection]) -> String {
        let fields = sources.flatMap { [$0.uid, $0.href.absoluteString, $0.kind.rawValue, $0.supportsVtodo ? "vtodo-on" : "vtodo-off"] }
        return SHA256.hash(data: OpaqueUTF8Identity(parts: fields).bytes).map { String(format: "%02x", $0) }.joined()
    }
    private func leaseContext(_ snapshot: Snapshot) throws -> (DAVAccountConfiguration, String) {
        guard let configuration = snapshot.configuration, configuration.davAktiv else { throw DAVAccountError.notActive }
        guard !configuration.briefkastenAktiv else { throw DAVAccountError.unsupportedFeature }
        guard let secret = snapshot.secret, !secret.isEmpty, secret.utf8.count <= 16_384 else { throw DAVAccountError.missingPassword }
        return (configuration, secret)
    }
    /// Must be called synchronously BEFORE native work is enqueued. Initially closed; account
    /// setup/status/discovery remain available without granting any integrated book admission.
    public nonisolated func captureBookSession() throws -> DAVBookSessionTicket { try bookAdmission.capture() }
    /// Closes synchronously and revokes starts before any actor await. Caller then awaits the
    /// registry barrier before restore preparation/publication under its existing storage owner.
    public nonisolated func suspendBookAdmission() throws -> DAVBookTransitionTicket { try bookAdmission.suspend() }
    public func awaitBookSuspension(_ transition: DAVBookTransitionTicket) throws {
        try bookAdmission.validateSuspended(transition); revokeLeases()
    }
    /// Closed native restore proof only: the helper binds actual saved evidence and verified
    /// operation-specific UI handoff to this exact transition. Namespace never leaves the service.
    public func completeRestoredBookTransition(_ transition: DAVBookTransitionTicket, handoff: NativeBookRestore.Handoff) throws {
        guard handoff.committed.prepared.transition == transition else { throw DAVAccountLeaseError.bindingChanged }
        let confirmation = try DAVBookHandoffConfirmation(transition: transition, savedEvidence: handoff.committed.evidence,
            accountStoreNamespace: configurationStore.revisionNamespace)
        try completeBookTransition(transition, confirmation: confirmation)
    }
    /// No public proof constructor/decoder. NativeBookRestore's closed handoff is the only
    /// production issuer; actual saved bytes/epoch and successful UI apply are prerequisites.
    public func completeBookTransition(_ transition: DAVBookTransitionTicket, confirmation: DAVBookHandoffConfirmation) throws {
        try bookAdmission.validateSuspended(transition)
        guard OpaqueUTF8Identity(confirmation.accountStoreNamespace) == OpaqueUTF8Identity(configurationStore.revisionNamespace) else { throw DAVAccountLeaseError.bindingChanged }
        revokeLeases()
        try bookAdmission.reopen(transition, confirmation: confirmation)
    }
    /// Current WK/session loss must close synchronously BEFORE any actor work is queued.
    /// Terminal in every phase; a previously queued handoff cannot reopen this instance.
    public nonisolated func invalidateBookAdmission() { bookAdmission.invalidateAnyState() }
    /// Uncertain publication/UI outcome never reopens this instance, even with an old proof.
    public nonisolated func blockBookAdmission(_ transition: DAVBookTransitionTicket) throws { try bookAdmission.block(transition) }

    /// Native metadata/session pin. Captured book ticket is mandatory; no implicit recapture.
    public func pinForSync(expectedRevision: String, orderedCalendarUIDs: [String], signer: DAVAccountBindingSigner, bookSession: DAVBookSessionTicket) async throws -> DAVSyncAccountLease {
        try bookAdmission.validate(bookSession)
        // Reject stale/invalid UI input before an await can alter any lease registry state.
        let before = try stableLeaseSnapshot()
        guard before.revision == expectedRevision else { throw DAVAccountError.conflict }
        _ = try leaseContext(before)
        _ = try selectedLeaseSources(orderedCalendarUIDs, snapshot: before)
        let generation = leaseGeneration, discovery = discoveryGeneration
        try await signer.ensureCurrent()
        try bookAdmission.validate(bookSession)
        guard generation == leaseGeneration, discovery == discoveryGeneration else { throw DAVAccountLeaseError.bindingChanged }
        let current = try stableLeaseSnapshot()
        guard current.revision == expectedRevision else { throw DAVAccountError.conflict }
        let (configuration, secret) = try leaseContext(current)
        let sources = try selectedLeaseSources(orderedCalendarUIDs, snapshot: current)
        let now = leaseClock()
        guard now.isFinite, now >= 0, (now + 300).isFinite else { throw DAVAccountLeaseError.expired }
        for active in leases.values where active.expires <= now { active.gate?.revoke() }
        leases = leases.filter { $0.value.expires > now }
        guard leases.count < 16 else { throw DAVAccountLeaseError.capacity }
        let stable = try signer.bind(configuration: configuration, secret: secret, storeNamespace: configurationStore.revisionNamespace)
        let binding = DAVSyncAccountLeaseBinding(calendars: sources, accountIdentity: try configuration.identity.storageKey,
            persistentAccountBinding: stable, sessionRevision: current.revision, discoveryFingerprint: fingerprint(sources))
        let handle = DAVSyncAccountLease(owner: leaseOwner, id: UUID())
        let gate = readClock.map { DAVReadLeaseGate(signer: signer, expires: now + 300, clock: $0, admission: bookAdmission, bookSession: bookSession) }
        if let gate { try signer.registerReadGate(gate); try bookAdmission.register(gate, ticket: bookSession) }
        try bookAdmission.withCurrent(bookSession) {
            leases[handle.id] = ActiveLease(binding: binding, signer: signer, generation: generation, discoveryGeneration: discovery, expires: now + 300, gate: gate, bookSession: bookSession)
        }
        return handle
    }
    public func revalidate(_ handle: DAVSyncAccountLease) async throws {
        guard handle.owner == leaseOwner, let active = leases[handle.id] else { throw DAVAccountLeaseError.invalidLease }
        do {
            try bookAdmission.validate(active.bookSession)
            try await active.signer.ensureCurrent()
            try bookAdmission.validate(active.bookSession)
            guard let present = leases[handle.id], present.generation == active.generation,
                  present.discoveryGeneration == active.discoveryGeneration, leaseGeneration == active.generation,
                  discoveryGeneration == active.discoveryGeneration else { throw DAVAccountLeaseError.invalidLease }
            let now = leaseClock()
            guard now.isFinite, now >= 0, now < active.expires else { throw DAVAccountLeaseError.expired }
            try active.gate?.checkState()
            let current = try stableLeaseSnapshot(), (configuration, secret) = try leaseContext(current)
            guard current.revision == active.binding.sessionRevision else { throw DAVAccountLeaseError.bindingChanged }
            let sources = try selectedLeaseSources(active.binding.calendars.map(\.uid), snapshot: current)
            guard fingerprint(sources) == active.binding.discoveryFingerprint,
                  try active.signer.bind(configuration: configuration, secret: secret, storeNamespace: configurationStore.revisionNamespace) == active.binding.persistentAccountBinding else {
                throw DAVAccountLeaseError.bindingChanged
            }
            try bookAdmission.validate(active.bookSession)
        } catch { leases[handle.id]?.gate?.revoke(); leases.removeValue(forKey: handle.id); throw error }
    }
    public func binding(_ handle: DAVSyncAccountLease) async throws -> DAVSyncAccountLeaseBinding {
        try await revalidate(handle)
        guard let active = leases[handle.id] else { throw DAVAccountLeaseError.invalidLease }; return active.binding
    }
    public func release(_ handle: DAVSyncAccountLease) {
        guard handle.owner == leaseOwner else { return }
        leases[handle.id]?.gate?.revoke(); leases.removeValue(forKey: handle.id)
    }

    public struct LeaseReport {
        public let source: DAVCollection, resources: [DAVResource]
    }
    private func reserveRead(_ handle: DAVSyncAccountLease) throws -> (ActiveLease, UUID) {
        guard readClock != nil else { throw DAVAccountLeaseError.unsupportedClock }
        guard handle.owner == leaseOwner, let active = leases[handle.id], active.gate != nil else { throw DAVAccountLeaseError.invalidLease }
        guard transport is any DispatchFencedHTTPTransport else { throw DAVAccountLeaseError.unsupportedTransport }
        guard activeReads.count < 4, activeReads[handle.id] == nil else { throw DAVAccountLeaseError.capacity }
        let token = UUID(); activeReads[handle.id] = token; return (active, token)
    }
    private func readClient(_ handle: DAVSyncAccountLease, sourceUID: String, token: UUID, deadline: TimeInterval) throws -> (DAVClient, DAVCollection) {
        guard activeReads[handle.id] == token, let active = leases[handle.id], let base = transport as? any DispatchFencedHTTPTransport,
              let source = active.binding.calendars.first(where: { OpaqueUTF8Identity($0.uid) == OpaqueUTF8Identity(sourceUID) }) else { throw DAVAccountLeaseError.invalidSelection }
        let current = try stableLeaseSnapshot(), (configuration, secret) = try leaseContext(current)
        guard current.revision == active.binding.sessionRevision,
              try active.signer.bind(configuration: configuration, secret: secret, storeNamespace: configurationStore.revisionNamespace) == active.binding.persistentAccountBinding else { throw DAVAccountLeaseError.bindingChanged }
        let wrapper = DAVLeaseReadTransport(service: self, lease: handle, sourceUID: sourceUID, token: token, deadline: deadline, base: base)
        let client = try DAVClient(server: configuration.server, username: configuration.benutzer, password: secret,
            accountType: configuration.kontoArt, transport: wrapper)
        return (client, source)
    }
    /// Native read-only foundations; not a sync result, write permit or journal resolution.
    public func readReport(_ handle: DAVSyncAccountLease, sourceUID: String) async throws -> LeaseReport {
        guard !sourceUID.isEmpty, sourceUID.utf8.count <= 1024 else { throw DAVAccountLeaseError.invalidSelection }
        try Task.checkCancellation()
        guard let readClock else { throw DAVAccountLeaseError.unsupportedClock }
        let deadline = readClock.now() + 60
        try await revalidate(handle)
        let (_, token) = try reserveRead(handle)
        defer { activeReads.removeValue(forKey: handle.id) }
        let (client, source) = try readClient(handle, sourceUID: sourceUID, token: token, deadline: deadline)
        let resources = try await client.reportScoped(in: source)
        try Task.checkCancellation(); try await revalidate(handle)
        guard activeReads[handle.id] == token else { throw DAVAccountLeaseError.invalidLease }
        guard readClock.now() < deadline else { throw DAVError.timeout }
        return LeaseReport(source: source, resources: resources)
    }
    public func readResource(_ handle: DAVSyncAccountLease, sourceUID: String, href: URL, maximumBytes: Int = DAVClient.itemLimit) async throws -> DAVResourceRead {
        guard !sourceUID.isEmpty, sourceUID.utf8.count <= 1024 else { throw DAVAccountLeaseError.invalidSelection }
        try Task.checkCancellation()
        guard let readClock else { throw DAVAccountLeaseError.unsupportedClock }
        let deadline = readClock.now() + 60
        try await revalidate(handle)
        let (_, token) = try reserveRead(handle)
        defer { activeReads.removeValue(forKey: handle.id) }
        let (client, source) = try readClient(handle, sourceUID: sourceUID, token: token, deadline: deadline)
        let result = try await client.getResource(href: href, in: source, maximumBytes: maximumBytes)
        try Task.checkCancellation(); try await revalidate(handle)
        guard activeReads[handle.id] == token else { throw DAVAccountLeaseError.invalidLease }
        guard readClock.now() < deadline else { throw DAVError.timeout }
        return result
    }
    internal func authorizeRead(_ handle: DAVSyncAccountLease, sourceUID: String, token: UUID, deadline: TimeInterval, request: BoundedHTTPRequest) async throws -> (BoundedHTTPRequest, DAVReadDispatchAuthorization) {
        guard !sourceUID.isEmpty, sourceUID.utf8.count <= 1024 else { throw DAVAccountLeaseError.invalidSelection }
        try Task.checkCancellation(); try await revalidate(handle)
        guard activeReads[handle.id] == token, let active = leases[handle.id], let gate = active.gate,
              let source = active.binding.calendars.first(where: { OpaqueUTF8Identity($0.uid) == OpaqueUTF8Identity(sourceUID) }) else { throw DAVAccountLeaseError.invalidLease }
        let path = try DAVClient.recoveryPath(request.url.absoluteString), sourcePath = try DAVClient.recoveryPath(source.href.absoluteString)
        guard request.method == "REPORT" ? path == sourcePath : request.method == "GET" && path.count > sourcePath.count && path.starts(with: sourcePath) else { throw DAVAccountLeaseError.invalidSelection }
        let current = try stableLeaseSnapshot()
        guard current.revision == active.binding.sessionRevision else {
            gate.revoke(); leases.removeValue(forKey: handle.id); throw DAVAccountLeaseError.bindingChanged
        }
        let configuration = try leaseContext(current).0
        let validator = try DAVClient(server: configuration.server, username: configuration.benutzer, password: "", accountType: configuration.kontoArt)
        _ = try validator.sameOriginURL(request.url.absoluteString)
        let remaining = min(deadline, active.expires) - gate.clock.now()
        guard remaining > 0 else { throw DAVError.timeout }
        let bounded = BoundedHTTPRequest(url: request.url, method: request.method, headers: request.headers, body: request.body,
            timeout: min(request.timeout, remaining), maximumResponseBytes: request.maximumResponseBytes)
        return (bounded, try DAVReadDispatchAuthorization(gate: gate, deadline: deadline, request: bounded))
    }
    internal func finishReadResponse(_ handle: DAVSyncAccountLease, token: UUID) async throws {
        try Task.checkCancellation(); try await revalidate(handle)
        guard activeReads[handle.id] == token else { throw DAVAccountLeaseError.invalidLease }
    }

    public static func code(_ error: Error) -> String {
        if let error = error as? DAVAccountError {
            switch error {
            case .invalidConfiguration: return "invalid_config"
            case .missingPassword: return "app_password_missing"
            case .conflict: return "conflict"
            case .notActive: return "not_active"
            case .unsupportedFeature: return "unsupported_feature"
            case .verificationFailed: return "verification_failed"
            case .storageUnavailable: return "native_operation_failed"
            case .credentialUnavailable: return "secret_service_unavailable"
            }
        }
        if error is DAVCredentialError { return "secret_service_unavailable" }
        if let error = error as? DAVError {
            switch error {
            case .unauthorized: return "http_401"
            case .forbidden: return "http_403"
            case .conflict(let status), .httpStatus(let status): return "http_\(status)"
            case .timeout: return "timeout"
            case .invalidConfiguration: return "invalid_config"
            case .originRejected, .malformedXML, .partialMultistatus, .incompleteReport,
                 .reportOutsideCollection, .invalidResponse, .responseTooLarge: return "invalid_response"
            default: return "nextcloud_error"
            }
        }
        if let error = error as? URLError { return error.code == .timedOut ? "timeout" : "network_error" }
        return "native_operation_failed"
    }
}

/// A single discovery deadline covers redirects, principal/home fallbacks and both DAV kinds.
private struct DAVAccountDeadlineTransport: BoundedHTTPTransport {
    let base: any BoundedHTTPTransport
    let deadline: TimeInterval
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        try Task.checkCancellation()
        let remaining = deadline - ProcessInfo.processInfo.systemUptime
        guard remaining > 0 else { throw DAVError.timeout }
        let bounded = BoundedHTTPRequest(url: request.url, method: request.method, headers: request.headers,
            body: request.body, timeout: min(remaining, request.timeout), maximumResponseBytes: request.maximumResponseBytes)
        let response = try await base.send(bounded)
        try Task.checkCancellation()
        guard ProcessInfo.processInfo.systemUptime <= deadline else { throw DAVError.timeout }
        return response
    }
}

/// The wrapper never rewrites auth: every redirect uses the same local immutable DAVClient.
private struct DAVLeaseReadTransport: BoundedHTTPTransport {
    let service: DAVAccountService, lease: DAVSyncAccountLease, sourceUID: String, token: UUID, deadline: TimeInterval
    let base: any DispatchFencedHTTPTransport
    func send(_ request: BoundedHTTPRequest) async throws -> BoundedHTTPResponse {
        let (bounded, authorization) = try await service.authorizeRead(lease, sourceUID: sourceUID, token: token, deadline: deadline, request: request)
        let response = try await base.send(bounded, authorization: authorization)
        try authorization.checkResponseDeadline()
        try await service.finishReadResponse(lease, token: token)
        try authorization.checkResponseDeadline()
        return response
    }
}
