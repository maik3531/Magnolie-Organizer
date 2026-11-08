import Foundation
import XCTest
import Security
import CryptoKit
import Darwin
@testable import BetaCore

private final class JournalMemoryKeys: DAVSyncJournalKeyStore {
    var values: [String: DAVSyncJournalKey] = [:]
    var failure: DAVSyncJournalError?
    func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey {
        if let failure { throw failure }
        if let key = values[namespace] { return key }
        guard allowCreate else { throw DAVSyncJournalError.missingKey }
        let key = try DAVSyncJournalKey(id: Data(repeating: 4, count: 32), bytes: Data(repeating: 7, count: 32))
        values[namespace] = key
        return try DAVSyncJournalKey(id: key.id, bytes: key.bytes, newlyCreated: true)
    }
}
private final class JournalFault { var target: String?; func hit(_ point: String) throws { if point == target { throw DAVSyncJournalError.unsafeStorage } } }

final class DAVSyncJournalTests: XCTestCase {
    typealias Journal = DAVSyncJournalStore
    private func directory() throws -> URL {
        let path = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("dav-journal-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        addTeardownBlock { try? FileManager.default.removeItem(at: path) }; return path
    }
    private func frozen(_ suffix: String = "one", method: Journal.FrozenOperation.Method = .update,
                        href: String = "https://calendar.example.test/cal/item.ics", etag: String = "\"before\"", body: Data? = nil) -> Journal.PreparedRun {
        let input = Data("{\"synthetic\":\"input\"}".utf8)
        let binding = Journal.Binding(accountIdentity: String(repeating: "a", count: 64), accountRevision: String(repeating: "b", count: 64),
            server: URL(string: "https://calendar.example.test/")!, bookIdentity: "synthetic-book", bookGeneration: "persistent-restore-generation-1", syncEpoch: "epoch-1",
            inputDigest: Journal.digest(input), sources: [.init(uid: "calendar:fixture", href: URL(string: "https://calendar.example.test/cal/")!, supportsVtodo: true)])
        let op = Journal.FrozenOperation(id: Journal.digest(Data(("operation-" + suffix).utf8)), sourceUID: "calendar:fixture", method: method,
            href: URL(string: href)!, ifMatch: method == .create ? nil : etag,
            body: method == .delete ? nil : (body ?? Data("BEGIN:VCALENDAR\r\nX-SYNTHETIC:exact-body-ß\r\nEND:VCALENDAR\r\n".utf8)))
        return .init(id: Journal.digest(Data(suffix.utf8)), binding: binding, input: input, plan: Data("{\"frozen\":true}".utf8), operations: [op])
    }
    private func use<T>(_ directory: URL, keys: JournalMemoryKeys, fault: JournalFault = JournalFault(),
                        body: (Journal) async throws -> T) async throws -> T {
        let files = try DAVSyncJournalFiles(profileDirectory: directory, checkpoint: fault.hit)
        let journal = try Journal(files: files, keys: keys)
        return try await body(journal)
    }
    private func expect(_ expectedError: DAVSyncJournalError, _ body: () async throws -> Void, file: StaticString = #filePath, line: UInt = #line) async {
        do { try await body(); XCTFail("Expected journal rejection", file: file, line: line) }
        catch { XCTAssertEqual(error as? DAVSyncJournalError, expectedError, file: file, line: line) }
    }
    func testBootstrapCrashAfterKeyAddNeverResetsMissingJournal() throws {
        let root = try directory(), keys = JournalMemoryKeys(), files = try DAVSyncJournalFiles(profileDirectory: root)
        _ = try keys.load(namespace: files.namespace, allowCreate: true)
        XCTAssertThrowsError(try Journal(files: files, keys: keys)) { XCTAssertEqual($0 as? DAVSyncJournalError, .missingJournal) }
        XCTAssertNil(try files.read())
        XCTAssertEqual(keys.values.count, 1)
    }
    func testInitialCipherPublicationFailureDoesNotPermitSilentEmptyReset() throws {
        let root = try directory(), keys = JournalMemoryKeys(), fault = JournalFault(); fault.target = "before-rename"
        let files = try DAVSyncJournalFiles(profileDirectory: root, checkpoint: fault.hit)
        XCTAssertThrowsError(try Journal(files: files, keys: keys))
        fault.target = nil
        XCTAssertThrowsError(try Journal(files: files, keys: keys)) { XCTAssertEqual($0 as? DAVSyncJournalError, .missingJournal) }
        XCTAssertNil(try files.read())
    }
    func testPrepareEncryptsExactBodiesAndContainsNoCredentialSchema() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        try await use(root, keys: keys) { journal in
            let handle = try await journal.prepare(run)
            let repeated = try await journal.prepare(run)
            XCTAssertEqual(handle, repeated)
            let read = try await journal.frozenRun(handle)
            XCTAssertEqual(read, run)
            let permit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
            XCTAssertEqual(permit.operation.body, run.operations[0].body)
            XCTAssertEqual(permit.operation.ifMatch, "\"before\"")
            let path = root.appendingPathComponent("DAVSync-Journal/journal-v1.enc")
            let encrypted = try AtomicStore.read(path)!
            XCTAssertNil(encrypted.range(of: run.operations[0].body!))
            XCTAssertNil(encrypted.range(of: Data("synthetic-book".utf8)))
            XCTAssertEqual(encrypted.prefix(8), Data("MAGDAVJ1".utf8))
            let encoded = try JSONEncoder().encode(read)
            let schema = String(data: encoded, encoding: .utf8)!
            for forbidden in ["Authorization", "password", "credentials", "Cookie"] { XCTAssertFalse(schema.contains(forbidden)) }
        }
    }
    func testAcknowledgementAndStagingAreDurableAndIdempotent() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        let candidate = Data("{\"candidate\":\"final\"}".utf8), proof = Journal.digest(Data("proof-binding".utf8))
        try await use(root, keys: keys) { journal in
            let handle = try await journal.prepare(run)
            await expect(.invalidTransition) { _ = try await journal.stageResult(handle, candidate: candidate, proofBinding: proof) }
            let permit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
            try await journal.observe(permit, outcome: .acknowledgement(status: 204, etag: "\"after\""))
            try await journal.observe(permit, outcome: .acknowledgement(status: 204, etag: "\"after\""))
            await expect(.invalidTransition) { try await journal.observe(permit, outcome: .uncertain) }
            let staged = try await journal.stageResult(handle, candidate: candidate, proofBinding: proof)
            XCTAssertEqual(staged.digest, Journal.digest(candidate))
            _ = try await journal.stageResult(handle, candidate: candidate, proofBinding: proof)
            await expect(.collision) { _ = try await journal.stageResult(handle, candidate: Data("changed".utf8), proofBinding: proof) }
        }
        try await use(root, keys: keys) { journal in
            let status = try await journal.pending()
            XCTAssertEqual(status.count, 1); XCTAssertEqual(status[0].acknowledged, 1); XCTAssertTrue(status[0].staged)
            let handle = try await journal.resume(runID: run.id, currentBinding: run.binding)
            _ = try await journal.stageResult(handle, candidate: candidate, proofBinding: proof)
            let evidence = try await journal.evidence(handle)
            XCTAssertEqual(evidence.candidate, candidate); XCTAssertEqual(evidence.operations[0].status, .acknowledged)
            XCTAssertEqual(evidence.operations[0].outcome?.etag, "\"after\"")
            await expect(.invalidTransition) { _ = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding) }
        }
    }
    func testRestartedInFlightIsUncertainAndOldPermitsCannotAcknowledge() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        var oldPermit: Journal.WritePermit?
        try await use(root, keys: keys) { journal in
            let handle = try await journal.prepare(run)
            oldPermit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
        }
        try await use(root, keys: keys) { journal in
            let pending = try await journal.pending(); XCTAssertEqual(pending[0].uncertain, 1)
            let handle = try await journal.resume(runID: run.id, currentBinding: run.binding)
            await expect(.invalidTransition) { _ = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding) }
            await expect(.stalePermit) { try await journal.observe(oldPermit!, outcome: .acknowledgement(status: 204, etag: "\"after\"")) }
        }
    }
    func testExplicitUncertaintyAndConflictingOutcomesNeverBecomeSuccess() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        try await use(root, keys: keys) { journal in
            let handle = try await journal.prepare(run)
            let permit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
            try await journal.observe(permit, outcome: .uncertain)
            try await journal.observe(permit, outcome: .uncertain)
            await expect(.invalidTransition) { try await journal.observe(permit, outcome: .acknowledgement(status: 204, etag: "\"after\"")) }
            await expect(.invalidTransition) { _ = try await journal.stageResult(handle, candidate: Data("candidate".utf8), proofBinding: run.id) }
        }
    }
    func testAccountSourceEpochAndInputBindingsCannotBeReplaced() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        try await use(root, keys: keys) { journal in
            let handle = try await journal.prepare(run)
            let old = run.binding
            let changed = Journal.Binding(accountIdentity: old.accountIdentity, accountRevision: String(repeating: "c", count: 64), server: old.server,
                bookIdentity: old.bookIdentity, bookGeneration: old.bookGeneration, syncEpoch: old.syncEpoch, inputDigest: old.inputDigest, sources: old.sources)
            await expect(.bindingChanged) { _ = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: changed) }
            let replacement = Journal.PreparedRun(id: run.id, binding: changed, input: run.input, plan: run.plan, operations: run.operations)
            await expect(.collision) { _ = try await journal.prepare(replacement) }
            let capabilities = Journal.Binding(accountIdentity: old.accountIdentity, accountRevision: old.accountRevision, server: old.server,
                bookIdentity: old.bookIdentity, bookGeneration: old.bookGeneration, syncEpoch: old.syncEpoch, inputDigest: old.inputDigest,
                sources: old.sources.map { .init(uid: $0.uid, href: $0.href, supportsVtodo: false) })
            await expect(.bindingChanged) { _ = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: capabilities) }
        }
    }
    func testWildcardUnsafeScopesAndInvalidResponseStatusesRejectBeforeSuccess() async throws {
        let root = try directory(), keys = JournalMemoryKeys()
        try await use(root, keys: keys) { journal in
            for wildcard in ["*", " * ", "\t*\t", "", "\"ok\"\r\n"] {
                await expect(.invalidInput) { _ = try await journal.prepare(frozen(etag: wildcard)) }
            }
            for href in ["https://other.example.test/cal/item.ics", "https://calendar.example.test/other/item.ics", "https://name:secret@calendar.example.test/cal/item.ics", "https://calendar.example.test/cal/%2e%2e/item.ics", "https://calendar.example.test/cal/item.ics?token=secret"] {
                await expect(.invalidInput) { _ = try await journal.prepare(frozen(href: href)) }
            }
            let run = frozen(), handle = try await journal.prepare(run)
            let permit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
            for outcome in [Journal.Outcome.acknowledgement(status: 412, etag: "\"after\""), .acknowledgement(status: 204, etag: " * "), .acknowledgement(status: 204)] {
                await expect(.invalidTransition) { try await journal.observe(permit, outcome: outcome) }
            }
            try await journal.observe(permit, outcome: .acknowledgement(status: 204, etag: " W/\"legitimate\" "))
        }
    }
    func testDelete404AcknowledgesOnlyDeleteAndCreateFreezesIfNoneMatch() async throws {
        let root = try directory(), keys = JournalMemoryKeys()
        try await use(root, keys: keys) { journal in
            for method in [Journal.FrozenOperation.Method.create, .delete] {
                let run = frozen(method.rawValue, method: method), handle = try await journal.prepare(run)
                let permit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
                XCTAssertEqual(permit.operation.ifNoneMatch, method == .create ? "*" : nil)
                if method == .create { await expect(.invalidTransition) { try await journal.observe(permit, outcome: .acknowledgement(status: 404)) } }
                else { try await journal.observe(permit, outcome: .acknowledgement(status: 404)) }
            }
        }
    }
    func testEveryActualPOSIXPublicationCheckpointFailurePoisonsAndReopensOldOrNew() async throws {
        for point in ["temporary-created", "temporary-written", "file-fsync", "file-fullsync", "before-rename", "renamed", "directory-fsync", "readback"] {
            let root = try directory(), keys = JournalMemoryKeys(), run = frozen(), fault = JournalFault()
            try await use(root, keys: keys, fault: fault) { journal in
                let handle = try await journal.prepare(run); fault.target = point
                await expect(.unsafeStorage) { _ = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding) }
                await expect(.poisoned) { _ = try await journal.pending() }
            }
            try await use(root, keys: keys) { journal in
                let status = try await journal.pending()
                XCTAssertEqual(status.count, 1)
                XCTAssertEqual(status[0].prepared + status[0].uncertain, 1)
                XCTAssertEqual(status[0].acknowledged, 0); XCTAssertFalse(status[0].staged)
                let handle = try await journal.resume(runID: run.id, currentBinding: run.binding)
                if status[0].uncertain == 1 {
                    await expect(.invalidTransition) { _ = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding) }
                }
            }
        }
    }
    func testExternalReplacementPoisonsWithoutOverwriting() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        try await use(root, keys: keys) { journal in
            _ = try await journal.prepare(run)
            let path = root.appendingPathComponent("DAVSync-Journal/journal-v1.enc"), replacement = Data("external-change".utf8)
            try AtomicStore.write(replacement, to: path)
            await expect(.externalChange) { _ = try await journal.pending() }
            await expect(.poisoned) { _ = try await journal.prepare(run) }
            XCTAssertEqual(try AtomicStore.read(path), replacement)
        }
    }
    func testTamperingMissingAndLockedKeysRetainCiphertext() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        try await use(root, keys: keys) { _ = try await $0.prepare(run) }
        let files = try DAVSyncJournalFiles(profileDirectory: root)
        let original = try files.read()!
        keys.failure = .keychain(errSecInteractionNotAllowed)
        XCTAssertThrowsError(try Journal(files: files, keys: keys))
        keys.failure = nil; keys.values.removeAll()
        XCTAssertThrowsError(try Journal(files: files, keys: keys)) { XCTAssertEqual($0 as? DAVSyncJournalError, .missingKey) }
        XCTAssertEqual(try files.read(), original)
        _ = try keys.load(namespace: files.namespace, allowCreate: true)
        var changed = original; changed[changed.count - 1] ^= 1; try files.write(changed)
        XCTAssertThrowsError(try Journal(files: files, keys: keys)) { XCTAssertEqual($0 as? DAVSyncJournalError, .corrupt) }
        XCTAssertEqual(try files.read(), changed)
    }
    func testAuthenticatedUnknownSchemaAndImpossibleStateAreRetainedAndRejected() throws {
        let root = try directory(), keys = JournalMemoryKeys(), files = try DAVSyncJournalFiles(profileDirectory: root)
        let key = try keys.load(namespace: files.namespace, allowCreate: true)
        for text in ["{\"version\":1,\"runs\":[],\"futureUnknown\":true}", "{\"version\":2,\"runs\":[]}"] {
            let aad = Data("MAGDAVJ1".utf8) + key.id + Data(files.namespace.utf8)
            let sealed = try AES.GCM.seal(Data(text.utf8), using: SymmetricKey(data: key.bytes), authenticating: aad)
            let envelope = Data("MAGDAVJ1".utf8) + key.id + sealed.combined!
            try files.write(envelope)
            XCTAssertThrowsError(try Journal(files: files, keys: keys)) { XCTAssertEqual($0 as? DAVSyncJournalError, .corrupt) }
            XCTAssertEqual(try files.read(), envelope)
        }
    }
    func testLeaseAndPrivateModesAndSymlinkHardlinkGuardsAreRealPOSIX() throws {
        let root = try directory()
        var files: DAVSyncJournalFiles? = try DAVSyncJournalFiles(profileDirectory: root)
        XCTAssertThrowsError(try DAVSyncJournalFiles(profileDirectory: root)) { XCTAssertEqual($0 as? DAVSyncJournalError, .busy) }
        var info = stat(); XCTAssertEqual(lstat(files!.directory.path, &info), 0); XCTAssertEqual(info.st_mode & 0o777, 0o700)
        let file = files!.file
        try files!.write(Data("synthetic-cipher".utf8)); XCTAssertEqual(lstat(file.path, &info), 0); XCTAssertEqual(info.st_mode & 0o777, 0o600)
        let alias = root.appendingPathComponent("linked")
        XCTAssertEqual(link(file.path, alias.path), 0); XCTAssertThrowsError(try files!.read()); XCTAssertEqual(unlink(alias.path), 0)
        XCTAssertEqual(unlink(file.path), 0); XCTAssertEqual(symlink(alias.path, file.path), 0); XCTAssertThrowsError(try files!.read()); XCTAssertEqual(unlink(file.path), 0)
        files = nil
        XCTAssertEqual(chmod(root.appendingPathComponent("DAVSync-Journal").path, 0o755), 0)
        XCTAssertThrowsError(try DAVSyncJournalFiles(profileDirectory: root))
    }
    func testOneFilesAdapterCannotBeSharedByTwoActiveStoreActors() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), files = try DAVSyncJournalFiles(profileDirectory: root)
        let first = try Journal(files: files, keys: keys)
        XCTAssertThrowsError(try Journal(files: files, keys: keys)) { XCTAssertEqual($0 as? DAVSyncJournalError, .busy) }
        let run = frozen(), handle = try await first.prepare(run)
        let permit = try await first.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
        XCTAssertEqual(permit.operation.body, run.operations[0].body)
    }
    func testReplacingLeaseInodeFencesOldStoreBeforeAnotherCanDispatch() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), files = try DAVSyncJournalFiles(profileDirectory: root)
        let first = try Journal(files: files, keys: keys), run = frozen()
        let handle = try await first.prepare(run)
        XCTAssertEqual(unlink(files.directory.appendingPathComponent("journal.lock").path), 0)
        let replacement = try DAVSyncJournalFiles(profileDirectory: root)
        let second = try Journal(files: replacement, keys: keys)
        await expect(.externalChange) { _ = try await first.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding) }
        let resumed = try await second.resume(runID: run.id, currentBinding: run.binding)
        _ = try await second.beginAttempt(resumed, operationID: run.operations[0].id, currentBinding: run.binding)
    }
    func testReplacingWholeDirectoryWithCopiedCipherFencesOldStore() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), files = try DAVSyncJournalFiles(profileDirectory: root)
        let first = try Journal(files: files, keys: keys), run = frozen()
        let handle = try await first.prepare(run)
        let moved = root.appendingPathComponent("old-journal")
        XCTAssertEqual(rename(files.directory.path, moved.path), 0)
        XCTAssertEqual(mkdir(files.directory.path, mode_t(0o700)), 0)
        try AtomicStore.write(try AtomicStore.read(moved.appendingPathComponent("journal-v1.enc"))!, to: files.file)
        let replacement = try DAVSyncJournalFiles(profileDirectory: root), second = try Journal(files: replacement, keys: keys)
        await expect(.externalChange) { _ = try await first.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding) }
        let resumed = try await second.resume(runID: run.id, currentBinding: run.binding)
        _ = try await second.beginAttempt(resumed, operationID: run.operations[0].id, currentBinding: run.binding)
    }
    func testCapacityNeverPrunesUnrelatedPendingRuns() async throws {
        let root = try directory(), keys = JournalMemoryKeys()
        try await use(root, keys: keys) { journal in
            for index in 0..<Journal.maximumPendingRuns { _ = try await journal.prepare(frozen("run-\(index)")) }
            await expect(.capacity) { _ = try await journal.prepare(frozen("run-overflow")) }
            let pending = try await journal.pending(); XCTAssertEqual(pending.count, 16)
        }
    }
    func testAggregateCipherBudgetRejectsOversizedCandidateAndKeepsPendingEvidence() async throws {
        let root = try directory(), keys = JournalMemoryKeys(), run = frozen()
        try await use(root, keys: keys) { journal in
            let handle = try await journal.prepare(run)
            let permit = try await journal.beginAttempt(handle, operationID: run.operations[0].id, currentBinding: run.binding)
            try await journal.observe(permit, outcome: .acknowledgement(status: 204, etag: "\"after\""))
            // JSON Data base64 alone exceeds the encrypted64MiB budget; no disk publication occurs.
            let oversized = Data(repeating: 1, count: 48 * 1024 * 1024)
            await expect(.capacity) { _ = try await journal.stageResult(handle, candidate: oversized, proofBinding: run.id) }
            let pending = try await journal.pending()
            XCTAssertEqual(pending.count, 1); XCTAssertEqual(pending[0].acknowledged, 1); XCTAssertFalse(pending[0].staged)
        }
    }
    func testBoundedReadRejectsOversizedSparseFileBeforeMaterialization() throws {
        let root = try directory(), files = try DAVSyncJournalFiles(profileDirectory: root)
        let fd = open(files.file.path, O_WRONLY | O_CREAT | O_EXCL, mode_t(0o600)); XCTAssertGreaterThanOrEqual(fd, 0)
        defer { close(fd) }
        XCTAssertEqual(ftruncate(fd, off_t(Journal.maximumBytes + 1)), 0)
        XCTAssertThrowsError(try files.read())
        XCTAssertThrowsError(try AtomicStore.read(files.file, maximumBytes: 0))
    }
    func testRealJournalKeychainKeyIsSeparateAndStableInTemporaryDomain() throws {
        let root = try directory(), path = root.appendingPathComponent("isolated-journal.keychain-db").path
        let password = Array("temporary-journal-test-domain".utf8)
        var keychain: SecKeychain?
        let status = path.withCString { path in password.withUnsafeBytes { bytes in SecKeychainCreate(path, UInt32(bytes.count), bytes.baseAddress, false, nil, &keychain) } }
        XCTAssertEqual(status, errSecSuccess)
        guard status == errSecSuccess, let keychain else { throw DAVSyncJournalError.keychain(status) }
        defer { SecKeychainDelete(keychain) }
        let keys = KeychainDAVSyncJournalKeyStore(operations: SystemDAVKeychainOperations(keychain: keychain), service: "journal-test." + UUID().uuidString)
        let namespace = String(repeating: "a", count: 64)
        XCTAssertThrowsError(try keys.load(namespace: namespace, allowCreate: false))
        let first = try keys.load(namespace: namespace, allowCreate: true), second = try keys.load(namespace: namespace, allowCreate: false)
        XCTAssertEqual(first.id, second.id); XCTAssertEqual(first.bytes, second.bytes)
        XCTAssertTrue(first.newlyCreated); XCTAssertFalse(second.newlyCreated)
        let other = try keys.load(namespace: String(repeating: "b", count: 64), allowCreate: true)
        XCTAssertNotEqual(first.id, other.id); XCTAssertNotEqual(first.bytes, other.bytes)
    }
}
