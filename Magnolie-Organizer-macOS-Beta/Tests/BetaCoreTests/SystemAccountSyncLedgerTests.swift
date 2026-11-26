import Foundation
import XCTest
@testable import BetaCore

private final class SystemSyncMemoryKeys: DAVSyncJournalKeyStore {
    var values: [String: DAVSyncJournalKey] = [:]
    func load(namespace: String, allowCreate: Bool) throws -> DAVSyncJournalKey {
        if let key = values[namespace] { return key }
        guard allowCreate else { throw DAVSyncJournalError.missingKey }
        let key = try DAVSyncJournalKey(id: Data(repeating: 13, count: 32), bytes: Data(repeating: 29, count: 32))
        values[namespace] = key
        return try DAVSyncJournalKey(id: key.id, bytes: key.bytes, newlyCreated: true)
    }
}

final class SystemAccountSyncLedgerTests: XCTestCase {
    typealias Ledger = SystemAccountSyncLedger
    private func directory() throws -> URL {
        let path = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("system-sync-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        addTeardownBlock { try? FileManager.default.removeItem(at: path) }; return path
    }
    private func binding(_ epoch: UUID, source: String = "synthetic-source", scope: String = "window-v1") throws -> Ledger.Binding {
        try Ledger.Binding(epoch: epoch, sourceUID: SystemSourcePolicy.uid(.events, source),
                           sourceFingerprint: String(repeating: "a", count: 64), scope: scope)
    }
    private func book(_ epoch: UUID, title: String = "Original synthetic title") -> [String: Any] {
        ["termine": [["id": "synthetic-local-id", "titel": title, "future": ["keep": true]]],
         "aufgaben": [], "kontakte": [], "notizen": [], "futureRoot": ["keep": true],
         "syncEpoch": epoch.uuidString, "syncMetadaten": ["syncEpoch": epoch.uuidString]]
    }
    private func staged(_ ledger: Ledger, binding: Ledger.Binding, before: [String: Any], candidate: [String: Any]) throws -> Ledger.Run {
        try ledger.authorize(binding)
        let operation = try Ledger.Operation(id: "synthetic-op", payload: Ledger.encoded(["desired": "Private synthetic contact value"]))
        let run = try ledger.begin(binding: binding, input: Ledger.encoded(before), plan: Ledger.encoded(["syntheticPlan": true]), operations: [operation])
        try ledger.reserve(runID: run.id, readbacks: [operation.id: 4096], candidate: 65536, baseline: 4096)
        try ledger.willApply(runID: run.id, operationID: operation.id)
        try ledger.acknowledge(runID: run.id, operationID: operation.id, readback: Ledger.encoded(["actualReadback": true]))
        try ledger.stage(runID: run.id, candidate: Ledger.encoded(candidate), baseline: Ledger.encoded(["syntheticBaseline": "after-readback"]))
        return run
    }

    func testImportedMetadataCannotAuthorizeAProviderWrite() throws {
        let root = try directory(), ledger = try Ledger(profileDirectory: root, keys: SystemSyncMemoryKeys())
        let epoch = UUID(), bound = try binding(epoch)
        var imported = book(epoch)
        imported["nativeContactImport"] = ["version": 1, "sourceUID": bound.sourceUID, "syncAllowed": true]
        XCTAssertNil(try ledger.grant(for: bound))
        XCTAssertThrowsError(try ledger.begin(binding: bound, input: Ledger.encoded(imported), plan: Ledger.encoded([:]), operations: []))
        XCTAssertNil(try ledger.pending(bound))
    }

    func testNativeGrantIsSourceScopeEpochBoundAndPersistedEncrypted() throws {
        let root = try directory(), keys = SystemSyncMemoryKeys(), epoch = UUID(), bound = try binding(epoch)
        var ledger: Ledger? = try Ledger(profileDirectory: root, keys: keys)
        let grant = try ledger!.authorize(bound)
        _ = try staged(ledger!, binding: bound, before: book(epoch), candidate: book(epoch, title: "Changed"))
        let encrypted = try AtomicStore.read(root.appendingPathComponent("SystemAccounts-Sync/organizer.json"))!
        XCTAssertNil(encrypted.range(of: Data("Private synthetic contact value".utf8)))
        XCTAssertNil(encrypted.range(of: Data("synthetic-local-id".utf8)))
        ledger = nil
        ledger = try Ledger(profileDirectory: root, keys: keys)
        XCTAssertEqual(try ledger!.grant(for: bound)?.id, grant.id)
        XCTAssertNil(try ledger!.grant(for: binding(UUID())))
        XCTAssertNil(try ledger!.grant(for: binding(epoch, source: "other-source")))
        XCTAssertNil(try ledger!.grant(for: binding(epoch, scope: "changed-window")))
        XCTAssertThrowsError(try ledger!.authorize(binding(epoch, scope: "changed-window")))
    }

    func testAttemptIsDurableBeforeProviderAndUncertainRestartNeverRetries() throws {
        let root = try directory(), keys = SystemSyncMemoryKeys(), epoch = UUID(), bound = try binding(epoch)
        var ledger: Ledger? = try Ledger(profileDirectory: root, keys: keys)
        try ledger!.authorize(bound)
        let operation = try Ledger.Operation(id: "uncertain-operation", payload: Ledger.encoded(["write": "value"]))
        let run = try ledger!.begin(binding: bound, input: Ledger.encoded(book(epoch)), plan: Ledger.encoded([:]), operations: [operation])
        try ledger!.reserve(runID: run.id, readbacks: [operation.id: 4096], candidate: 65536, baseline: 4096)
        try ledger!.willApply(runID: run.id, operationID: operation.id)
        ledger = nil
        ledger = try Ledger(profileDirectory: root, keys: keys)
        XCTAssertTrue(try XCTUnwrap(ledger!.pending(bound)).uncertain)
        XCTAssertThrowsError(try ledger!.willApply(runID: run.id, operationID: operation.id))
        XCTAssertThrowsError(try ledger!.stage(runID: run.id, candidate: Ledger.encoded(book(epoch)), baseline: Ledger.encoded([:])))
        XCTAssertThrowsError(try ledger!.revokeSource(epoch: epoch, sourceUID: bound.sourceUID))
        XCTAssertNil(try ledger!.grant(for: bound)?.baseline)
    }

    func testOnlyIndependentActualDiskCandidateAdvancesBaseline() throws {
        for encrypted in [false, true] {
            let root = try directory(), store = try AtomicStore(directory: root)
            _ = try store.load()
            let epoch = UUID(), before = book(epoch), candidate = book(epoch, title: "Acknowledged native result"), bound = try binding(epoch)
            let encryption: Encryption? = try (encrypted ? Encryption.create(password: "synthetic-test-only-password") : nil)
            func save(_ book: [String: Any]) throws {
                let plain = try Document.encode(book); try store.commit(encryption?.encrypt(plain) ?? plain)
            }
            try save(before)
            let ledger = try Ledger(profileDirectory: root, keys: SystemSyncMemoryKeys())
            let run = try staged(ledger, binding: bound, before: before, candidate: candidate)
            // Neither a completed provider call nor staging is a local save receipt.
            XCTAssertNil(try ledger.grant(for: bound)?.baseline)
            XCTAssertThrowsError(try ledger.complete(runID: run.id, evidence: DAVBookDiskSnapshot.read(store: store, encryption: encryption)))
            XCTAssertNotNil(try ledger.pending(bound))
            try save(candidate) // Simulate lost WebView ACK: only the actual file exists.
            try ledger.complete(runID: run.id, evidence: DAVBookDiskSnapshot.read(store: store, encryption: encryption))
            XCTAssertNil(try ledger.pending(bound))
            XCTAssertTrue(try Ledger.equal(XCTUnwrap(ledger.grant(for: bound)?.baseline), Ledger.encoded(["syntheticBaseline": "after-readback"])))
            try ledger.revokeSource(epoch: epoch, sourceUID: bound.sourceUID)
            XCTAssertNil(try ledger.grant(for: bound))
            let renewed = try ledger.authorize(bound)
            XCTAssertTrue(try Ledger.equal(XCTUnwrap(renewed.baseline), Ledger.encoded(["syntheticBaseline": "after-readback"])))
        }
    }

    func testWrongEpochAndCandidateRetainStagedEvidence() throws {
        let root = try directory(), store = try AtomicStore(directory: root); _ = try store.load()
        let epoch = UUID(), bound = try binding(epoch), ledger = try Ledger(profileDirectory: root, keys: SystemSyncMemoryKeys())
        let candidate = book(epoch, title: "Planned result")
        let run = try staged(ledger, binding: bound, before: book(epoch), candidate: candidate)
        try store.commit(Document.encode(book(epoch, title: "Concurrent different value")))
        XCTAssertThrowsError(try ledger.complete(runID: run.id, evidence: DAVBookDiskSnapshot.read(store: store)))
        try store.commit(Document.encode(book(UUID(), title: "Planned result")))
        XCTAssertThrowsError(try ledger.complete(runID: run.id, evidence: DAVBookDiskSnapshot.read(store: store)))
        XCTAssertNotNil(try ledger.pending(bound)); XCTAssertNil(try ledger.grant(for: bound)?.baseline)
    }

    func testNativePrewriteRejectionIsDistinctFromUncertainWrite() throws {
        let root = try directory(), epoch = UUID(), bound = try binding(epoch), ledger = try Ledger(profileDirectory: root, keys: SystemSyncMemoryKeys())
        try ledger.authorize(bound)
        let operation = try Ledger.Operation(id: "rejected", payload: Ledger.encoded(["write": true]))
        let run = try ledger.begin(binding: bound, input: Ledger.encoded(book(epoch)), plan: Ledger.encoded([:]), operations: [operation])
        try ledger.reserve(runID: run.id, readbacks: [operation.id: 4096], candidate: 65536, baseline: 4096)
        try ledger.willApply(runID: run.id, operationID: operation.id)
        try ledger.rejectBeforeWrite(runID: run.id, operationID: operation.id)
        let pending = try XCTUnwrap(ledger.pending(bound))
        XCTAssertFalse(pending.uncertain); XCTAssertEqual(pending.rejected, [operation.id])
        XCTAssertThrowsError(try ledger.acknowledge(runID: run.id, operationID: operation.id, readback: Ledger.encoded([:])))
        XCTAssertThrowsError(try ledger.willApply(runID: run.id, operationID: operation.id))
        XCTAssertNil(try ledger.grant(for: bound)?.baseline)
        try ledger.discardWithoutEffects(runID: run.id)
        XCTAssertNil(try ledger.pending(bound))
        XCTAssertNotNil(try ledger.grant(for: bound))
    }

    func testCapacityIsReservedBeforeAnyNativeWrite() throws {
        let root = try directory(), epoch = UUID(), bound = try binding(epoch), ledger = try Ledger(profileDirectory: root, keys: SystemSyncMemoryKeys())
        try ledger.authorize(bound)
        let operation = try Ledger.Operation(id: "capacity", payload: Ledger.encoded(["write": true]))
        let run = try ledger.begin(binding: bound, input: Ledger.encoded(book(epoch)), plan: Ledger.encoded([:]), operations: [operation])
        XCTAssertThrowsError(try ledger.willApply(runID: run.id, operationID: operation.id))
        XCTAssertThrowsError(try ledger.reserve(runID: run.id, readbacks: [operation.id: Ledger.maximumBytes], candidate: Ledger.maximumBytes, baseline: Ledger.maximumBytes))
        XCTAssertTrue(try XCTUnwrap(ledger.pending(bound)).withoutEffects)
        try ledger.discardWithoutEffects(runID: run.id)
        XCTAssertNil(try ledger.pending(bound))
    }

    func testOversizedReadbackRemainsUncertainAndDoesNotConsumeUnreservedSpace() throws {
        let root = try directory(), epoch = UUID(), bound = try binding(epoch), ledger = try Ledger(profileDirectory: root, keys: SystemSyncMemoryKeys())
        try ledger.authorize(bound)
        let operation = try Ledger.Operation(id: "bounded-readback", payload: Ledger.encoded(["write": true]))
        let run = try ledger.begin(binding: bound, input: Ledger.encoded(book(epoch)), plan: Ledger.encoded([:]), operations: [operation])
        try ledger.reserve(runID: run.id, readbacks: [operation.id: 128], candidate: 65536, baseline: 4096)
        try ledger.willApply(runID: run.id, operationID: operation.id)
        XCTAssertThrowsError(try ledger.acknowledge(runID: run.id, operationID: operation.id, readback: Ledger.encoded(["unexpected": String(repeating: "x", count: 1024)])))
        XCTAssertTrue(try XCTUnwrap(ledger.pending(bound)).uncertain)
        XCTAssertThrowsError(try ledger.discardWithoutEffects(runID: run.id))
        XCTAssertNil(try ledger.grant(for: bound)?.baseline)
    }

    func testCandidateProbeAllowsDefaultsButRejectsLossOrValueChanges() throws {
        let required: [String: Any] = ["rows": [["id": "one", "title": "Native result", "privateFuture": ["keep": true]]]]
        let defaults: [String: Any] = ["rows": [["id": "one", "title": "Native result", "privateFuture": ["keep": true], "ordinaryDefault": ""]]]
        XCTAssertNoThrow(try Ledger.verifyNormalizedCandidate(required: Ledger.encoded(required), proposed: Ledger.encoded(defaults)))
        let alterations: [[String: Any]] = [["rows": [["id": "one", "title": "Different"]]], ["rows": []], ["rows": [["id": "renamed", "title": "Native result"]]]]
        for altered in alterations {
            XCTAssertThrowsError(try Ledger.verifyNormalizedCandidate(required: Ledger.encoded(required), proposed: Ledger.encoded(altered)))
        }
        let nfd = try Ledger.encoded(["opaque": "cafe\u{301}"]), nfc = try Ledger.encoded(["opaque": "caf\u{e9}"])
        XCTAssertFalse(try Ledger.equal(nfd, nfc))
        XCTAssertThrowsError(try Ledger.verifyNormalizedCandidate(required: nfd, proposed: nfc))
    }

    func testRevocationRemovesNativeAuthorityAndMissingJournalDoesNotRecreateIt() throws {
        let root = try directory(), keys = SystemSyncMemoryKeys(), epoch = UUID(), bound = try binding(epoch)
        var ledger: Ledger? = try Ledger(profileDirectory: root, keys: keys)
        try ledger!.authorize(bound); try ledger!.revokeSource(epoch: epoch, sourceUID: bound.sourceUID)
        XCTAssertNil(try ledger!.grant(for: bound))
        ledger = nil
        try FileManager.default.removeItem(at: root.appendingPathComponent("SystemAccounts-Sync/organizer.json"))
        XCTAssertThrowsError(try Ledger(profileDirectory: root, keys: keys))
    }
}
