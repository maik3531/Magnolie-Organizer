import Foundation
import CryptoKit

/// A native, profile-owner-serialized restore. No remote writes or sync baseline authority.
public enum NativeBookRestore {
    /// Closed authenticated result: cannot be constructed from caller-selected plaintext.
    public struct AuthenticatedOrigin {
        public let plain: String
        public let encryption: Encryption
        fileprivate let ciphertext: Data
        fileprivate let owner: AtomicStore
        fileprivate init(plain: String, encryption: Encryption, ciphertext: Data, owner: AtomicStore) {
            self.plain = plain; self.encryption = encryption; self.ciphertext = ciphertext; self.owner = owner
        }
    }
    public static func unlockActual(store: AtomicStore, password: String) throws -> AuthenticatedOrigin {
        guard let bytes = try store.restoreSnapshotBytes(), let text = String(data: bytes, encoding: .utf8) else {
            throw BetaError("No actual encrypted profile is available.")
        }
        let (plain, encryption) = try Encryption.unlock(text, password: password)
        guard try store.restoreSnapshotBytes() == bytes else { throw BetaError("Encrypted profile changed during authentication.") }
        return AuthenticatedOrigin(plain: plain, encryption: encryption, ciphertext: bytes, owner: store)
    }
    public final class Prepared {
        public let operationID: String, plain: String, epoch: UUID
        public let encryption: Encryption?
        internal let transition: DAVBookTransitionTicket
        fileprivate var expectedSnapshot: String?
        fileprivate var handoffIssued = false
        fileprivate let source: BackupSelection, sourcePath: String, original: Data?, output: String
        fileprivate let store: AtomicStore
        fileprivate var attempted = false
        public var publicationAttempted: Bool { attempted }
        fileprivate init(store: AtomicStore, plain: String, epoch: UUID, encryption: Encryption?, transition: DAVBookTransitionTicket, source: BackupSelection, sourcePath: String, original: Data?) throws {
            self.store = store; self.operationID = UUID().uuidString.lowercased(); self.plain = plain; self.epoch = epoch
            self.encryption = encryption; self.transition = transition; self.source = source; self.sourcePath = sourcePath; self.original = original
            output = try encryption?.encrypt(plain) ?? plain
        }
    }
    public final class Committed {
        public let prepared: Prepared
        public let evidence: DAVBookDiskSnapshot.Evidence
        public var envelope: String? { prepared.encryption == nil ? nil : prepared.output }
        fileprivate init(prepared: Prepared, evidence: DAVBookDiskSnapshot.Evidence) {
            self.prepared = prepared; self.evidence = evidence
        }
    }
    public static func prepare(store: AtomicStore, transition: DAVBookTransitionTicket, selection: BackupSelection, path: String, password: String,
                               currentEncryption: Encryption?, authenticatedOrigin: AuthenticatedOrigin?) throws -> Prepared {
        guard selection.url.standardizedFileURL.path != store.file.standardizedFileURL.path else {
            throw BetaError("Choose a backup or recovery file, not the live profile.")
        }
        let original = try store.restoreSnapshotBytes()
        var liveEncryption = currentEncryption
        let live: [String: Any]
        if let original {
            guard let text = String(data: original, encoding: .utf8) else { throw BetaError("Invalid actual profile encoding.") }
            if try Document.object(text)["magnolie"] as? String == "magnolie-verschluesselt" {
                let decoded: String
                if let authenticatedOrigin, authenticatedOrigin.owner === store, authenticatedOrigin.ciphertext == original {
                    decoded = authenticatedOrigin.plain
                    liveEncryption = authenticatedOrigin.encryption
                } else {
                    guard let currentEncryption else { throw BetaError("Actual encrypted profile is not authenticated.") }
                    decoded = try currentEncryption.openSnapshot(text)
                }
                live = try Document.plain(decoded)
            } else {
                guard currentEncryption == nil else { throw BetaError("The live encryption policy changed.") }
                live = try Document.plain(text)
            }
        } else {
            guard currentEncryption == nil else { throw BetaError("Absent profile unexpectedly has encryption.") }
            live = ["termine": [], "aufgaben": [], "kontakte": [], "notizen": []]
        }
        let sourceText = try selection.confirmed(path: path)
        let incoming: String, importedEncryption: Encryption?
        if selection.encrypted {
            let unlocked = try Encryption.unlock(sourceText, password: password)
            incoming = unlocked.0; importedEncryption = unlocked.1
        } else { incoming = sourceText; importedEncryption = nil }
        let epoch = UUID()
        let transformed = try DAVBookRestore.transform(incoming: Document.plain(incoming), live: live, newEpoch: epoch, restoredAt: Date())
        let plain = try Document.encode(transformed)
        _ = try Document.plain(plain)
        guard try store.restoreSnapshotBytes() == original else { throw BetaError("Live profile changed while preparing restore.") }
        _ = try selection.confirmed(path: path)
        return try Prepared(store: store, plain: plain, epoch: epoch, encryption: liveEncryption ?? importedEncryption, transition: transition,
                            source: selection, sourcePath: path, original: original)
    }
    /// Only once; any thrown error after entering this function must leave admission closed.
    /// publicationAttempted distinguishes source/precondition rejection from a started write.
    public static func commit(_ prepared: Prepared, store: AtomicStore) throws -> Committed {
        try commit(prepared, store: store, writeCheckpoint: { _ in })
    }
    internal static func commit(_ prepared: Prepared, store: AtomicStore, writeCheckpoint: (String) throws -> Void) throws -> Committed {
        guard prepared.store === store, !prepared.attempted, prepared.expectedSnapshot != nil else { throw BetaError("Restore publication was already attempted.") }
        guard try store.restoreSnapshotBytes() == prepared.original else { throw BetaError("The live restore source changed.") }
        _ = try prepared.source.confirmed(path: prepared.sourcePath)
        prepared.attempted = true
        try store.commit(prepared.output, preservingCurrent: prepared.original != nil, writeCheckpoint: writeCheckpoint)
        let evidence = try DAVBookDiskSnapshot.read(store: store, encryption: prepared.encryption)
        guard evidence.epoch == prepared.epoch,
              evidence.rawSHA256 == SHA256.hash(data: Data(prepared.output.utf8)).map({ String(format: "%02x", $0) }).joined() else {
            throw BetaError("Actual restored profile does not match its publication.")
        }
        return Committed(prepared: prepared, evidence: evidence)
    }
}

extension NativeBookRestore {
    /// Constructed only by validating the actual operation-bound WK callback result.
    /// It is not a generic Boolean confirmation or renderer-selected replacement book.
    public struct Handoff {
        internal let committed: Committed
        fileprivate init(committed: Committed) { self.committed = committed }
    }
    internal static func validatedExpectation(_ value: Any, for prepared: Prepared) throws -> String {
        guard let result = value as? [String: Any], result["operationID"] as? String == prepared.operationID,
              let snapshot = result["snapshot"] as? String,
              try DAVBookRestore.persistedEpoch(Document.plain(snapshot)) == prepared.epoch else {
            throw BetaError("Restore validation did not return the expected operation and epoch.")
        }
        guard !prepared.attempted, prepared.expectedSnapshot == nil else { throw BetaError("Restore validation was already consumed.") }
        prepared.expectedSnapshot = snapshot
        return snapshot
    }
    internal static func verifyApplied(_ value: Any, expectedSnapshot: String, committed: Committed) throws -> Handoff {
        let prepared = committed.prepared
        guard !prepared.handoffIssued, let validated = prepared.expectedSnapshot,
              Data(validated.utf8) == Data(expectedSnapshot.utf8),
              let result = value as? [String: Any], result["operationID"] as? String == prepared.operationID,
              let actual = result["snapshot"] as? String,
              try DAVBookRestore.persistedEpoch(Document.plain(actual)) == prepared.epoch,
              Data(actual.utf8) == Data(expectedSnapshot.utf8) else {
            throw BetaError("The actual restored UI model does not match its validated snapshot.")
        }
        let current = try DAVBookDiskSnapshot.read(store: prepared.store, encryption: prepared.encryption)
        guard current.rawSHA256 == committed.evidence.rawSHA256, current.epoch == prepared.epoch else {
            throw BetaError("The saved restore changed before its UI handoff completed.")
        }
        prepared.handoffIssued = true
        return Handoff(committed: committed)
    }
}

#if os(macOS)
import WebKit

extension NativeBookRestore {
    /// A closed receipt from the actual projected WK validator, bound to this view and candidate.
    public struct Validation {
        public let snapshot: String
        fileprivate let prepared: Prepared
        fileprivate let view: WKWebView
        fileprivate init(snapshot: String, prepared: Prepared, view: WKWebView) {
            self.snapshot = snapshot; self.prepared = prepared; self.view = view
        }
    }
    @MainActor private static func evaluate(_ body: String, arguments: [String: Any], web: WKWebView) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            var finished = false
            let timeout = DispatchWorkItem {
                guard !finished else { return }; finished = true
                continuation.resume(throwing: BetaError("Native restore WebKit transport exceeded 10 seconds."))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: timeout)
            web.callAsyncJavaScript(body, arguments: arguments, in: nil, in: .page) { (result: Result<Any, Error>) in
                guard !finished else { return }; finished = true; timeout.cancel(); continuation.resume(with: result)
            }
        }
    }
    /// Executes real WebKit; no caller-provided dictionary/Boolean can issue Validation.
    @MainActor public static func validateUI(_ prepared: Prepared, in web: WKWebView) async throws -> Validation {
        let value = try await evaluate("return window.MacBeta.prepareNativeRestore(text, operationID);",
            arguments: ["text": prepared.plain, "operationID": prepared.operationID], web: web)
        let snapshot = try validatedExpectation(value, for: prepared)
        return Validation(snapshot: snapshot, prepared: prepared, view: web)
    }
    /// Release editors only after Main's final native admission/generation checks.
    @MainActor public static func finishUI(_ validation: Validation, committed: Committed, in web: WKWebView) async throws {
        guard validation.prepared === committed.prepared, validation.view === web, committed.prepared.handoffIssued else {
            throw BetaError("Restore completion has no verified model handoff.")
        }
        let value = try await evaluate("return window.MacBeta.finishNativeRestore(operationID);",
            arguments: ["operationID": committed.prepared.operationID], web: web)
        guard let result = value as? [String: Any], result["operationID"] as? String == committed.prepared.operationID,
              result["released"] as? Bool == true else { throw BetaError("Restore editor release was not acknowledged.") }
    }
    /// Executes the actual App callback and verifies its full model and fresh actual disk.
    /// The matching native Host generation must remain current before and after this await.
    @MainActor public static func applyUI(_ validation: Validation, committed: Committed, in web: WKWebView) async throws -> Handoff {
        guard validation.prepared === committed.prepared, validation.view === web else {
            throw BetaError("The restore WebKit view or candidate changed.")
        }
        let value = try await evaluate("return window.MacBeta.applyNativeRestore(operationID, encrypted);",
            arguments: ["operationID": committed.prepared.operationID, "encrypted": committed.prepared.encryption != nil], web: web)
        return try verifyApplied(value, expectedSnapshot: validation.snapshot, committed: committed)
    }
}
#endif
