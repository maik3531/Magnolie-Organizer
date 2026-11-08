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
        guard let data = try AtomicStore.read(file), let text = String(data: data, encoding: .utf8) else {
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
    private struct Snapshot {
        let configuration: DAVAccountConfiguration?
        let secret: String?
        let revision: String
    }
    public init(configuration: any DAVAccountConfigurationStore,
                credentials: any DAVCredentialStore = KeychainDAVCredentialStore(),
                transport: any BoundedHTTPTransport = URLSessionBoundedTransport()) {
        self.configurationStore = configuration; self.credentials = credentials; self.transport = transport
    }
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
        let client = try DAVClient(server: configuration.server, username: configuration.benutzer,
            password: secret, accountType: configuration.kontoArt,
            transport: DAVAccountDeadlineTransport(base: transport, deadline: ProcessInfo.processInfo.systemUptime + 60))
        var calendars: [DAVCollection] = [], books: [DAVCollection] = []
        var code = "none"
        do {
            calendars = try await client.collections(for: .calendar)
            // Check between service discovery calls as well as after the final await.
            guard try snapshot().revision == before.revision else { throw DAVAccountError.conflict }
            books = try await client.collections(for: .addressbook)
        } catch is CancellationError { throw CancellationError() }
        catch { code = Self.code(error) }
        guard try snapshot().revision == before.revision else { throw DAVAccountError.conflict }
        let partial = code != "none" && (!calendars.isEmpty || !books.isEmpty)
        let result = status(before, calendars: calendars, books: books, checked: true, error: code)
        let discovery = DAVAccountDiscovery(status: result, reachable: code == "none" || partial, partial: partial)
        cachedDiscovery = discovery
        return discovery
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
