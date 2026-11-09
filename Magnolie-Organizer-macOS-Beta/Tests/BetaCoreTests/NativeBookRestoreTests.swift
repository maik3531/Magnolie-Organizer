#if os(macOS)
import Foundation
import XCTest
@testable import BetaCore

final class NativeBookRestoreTests: XCTestCase {
    private let transition = DAVBookTransitionTicket(owner: UUID(), transition: UUID())
    private let base: [String: Any] = ["termine": [], "aufgaben": [], "kontakte": [], "notizen": [], "futureRoot": ["keep": 7]]
    private func temporary() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }; return url
    }
    func testAbsentAndSavedRestorePublishNewEpochAndRetainRecoverySource() throws {
        for saved in [false, true] {
            let directory = try temporary(), profile = directory.appendingPathComponent("profile")
            let store = try AtomicStore(directory: profile); XCTAssertNil(try store.load())
            let old = try Document.encode(base)
            if saved { try store.commit(old) }
            var incoming = base
            incoming["syncEpoch"] = OrdinarySaveEpochPolicyTests.epoch
            incoming["syncMetadaten"] = ["syncEpoch": OrdinarySaveEpochPolicyTests.epoch]
            incoming["geloescht"] = ["termine": [["uid": "deleted"]], "aufgaben": [], "kontakte": []]
            let source = directory.appendingPathComponent("recovery.json")
            try AtomicStore.write(Data(Document.encode(incoming).utf8), to: source)
            let selection = try BackupSelection(url: source)
            let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: selection, path: source.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
            XCTAssertNotEqual(prepared.epoch, UUID(uuidString: OrdinarySaveEpochPolicyTests.epoch))
            let expected = prepared.plain
            _ = try NativeBookRestore.validatedExpectation(["operationID": prepared.operationID, "snapshot": expected], for: prepared)
            let committed = try NativeBookRestore.commit(prepared, store: store)
            XCTAssertEqual(committed.evidence.epoch, prepared.epoch)
            XCTAssertEqual(try String(contentsOf: store.file, encoding: .utf8), prepared.plain)
            XCTAssertEqual(try selection.confirmed(path: source.path), try Document.encode(incoming))
            let book = committed.evidence.book
            XCTAssertEqual((book["syncNachRestore"] as? [String: Any])?["additiv"] as? Bool, true)
            XCTAssertNil(book["syncAbgleichBasis"])
            XCTAssertThrowsError(try NativeBookRestore.commit(prepared, store: store))
            let recovery = profile.appendingPathComponent("Recovery-macOS-Beta")
            if saved {
                let files = try FileManager.default.contentsOfDirectory(at: recovery, includingPropertiesForKeys: nil)
                XCTAssertEqual(files.count, 1)
                XCTAssertEqual(try String(contentsOf: XCTUnwrap(files.first), encoding: .utf8), old)
                // A retained recovery file is itself a valid pinned restore source.
                let recoverySelection = try BackupSelection(url: XCTUnwrap(files.first))
                let another = try NativeBookRestore.prepare(store: store, transition: transition, selection: recoverySelection, path: recoverySelection.url.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
                XCTAssertNotEqual(another.epoch, prepared.epoch)
            } else { XCTAssertFalse(FileManager.default.fileExists(atPath: recovery.path)) }
            let receipt: [String: Any] = ["operationID": prepared.operationID, "snapshot": expected]
            XCTAssertThrowsError(try NativeBookRestore.verifyApplied(["operationID": "stale", "snapshot": expected], expectedSnapshot: expected, committed: committed))
            XCTAssertThrowsError(try NativeBookRestore.verifyApplied(receipt, expectedSnapshot: expected + " ", committed: committed))
            _ = try NativeBookRestore.verifyApplied(receipt, expectedSnapshot: expected, committed: committed)
            XCTAssertThrowsError(try NativeBookRestore.verifyApplied(receipt, expectedSnapshot: expected, committed: committed))
        }
    }
    func testChangedSelectionAndLiveDiskNeverPublish() throws {
        for changeLive in [false, true] {
            let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
            XCTAssertNil(try store.load()); let old = try Document.encode(base); try store.commit(old)
            let source = directory.appendingPathComponent("backup.json"); try AtomicStore.write(Data(old.utf8), to: source)
            let selection = try BackupSelection(url: source)
            let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: selection, path: source.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
            _ = try NativeBookRestore.validatedExpectation(["operationID": prepared.operationID, "snapshot": prepared.plain], for: prepared)
            let changed = old + " "
            try AtomicStore.write(Data(changed.utf8), to: changeLive ? store.file : source)
            XCTAssertThrowsError(try NativeBookRestore.commit(prepared, store: store))
            XCTAssertFalse(prepared.publicationAttempted)
            XCTAssertEqual(try String(contentsOf: store.file, encoding: .utf8), changeLive ? changed : old)
        }
    }
    func testAuthenticatedV1OriginAndCurrentPasswordPolicy() throws {
        let fixture = try Document.object(String(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "desktop-envelopes", withExtension: "json", subdirectory: "Fixtures")), encoding: .utf8))
        let password = try XCTUnwrap(fixture["password"] as? String)
        for version in ["v1", "v2"] {
            let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
            XCTAssertNil(try store.load()); let original = try XCTUnwrap(fixture[version] as? String); try store.commit(original)
            let origin = try NativeBookRestore.unlockActual(store: store, password: password)
            if version == "v1" { XCTAssertThrowsError(try origin.encryption.openSnapshot(original)) }
            let source = directory.appendingPathComponent("plain.json")
            try AtomicStore.write(Data(Document.encode(base).utf8), to: source)
            let selection = try BackupSelection(url: source)
            let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: selection, path: source.path, password: "", currentEncryption: origin.encryption, authenticatedOrigin: origin)
            let expected = prepared.plain
            _ = try NativeBookRestore.validatedExpectation(["operationID": prepared.operationID, "snapshot": expected], for: prepared)
            let committed = try NativeBookRestore.commit(prepared, store: store)
            XCTAssertTrue(committed.evidence.encrypted)
            let envelope = try XCTUnwrap(committed.envelope)
            XCTAssertEqual(try Encryption.unlock(envelope, password: password).0, prepared.plain)
            XCTAssertThrowsError(try Encryption.unlock(envelope, password: "wrong-password"))
        }
    }
    func testWriteFailuresRemainUnacknowledgedAndPoisonSession() throws {
        for phase in ["before-rename", "renamed"] {
            let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
            XCTAssertNil(try store.load()); let old = try Document.encode(base); try store.commit(old)
            let source = directory.appendingPathComponent("backup.json"); try AtomicStore.write(Data(old.utf8), to: source)
            let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: BackupSelection(url: source), path: source.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
            _ = try NativeBookRestore.validatedExpectation(["operationID": prepared.operationID, "snapshot": prepared.plain], for: prepared)
            XCTAssertThrowsError(try NativeBookRestore.commit(prepared, store: store, writeCheckpoint: { if $0 == phase { throw BetaError("Injected owned write failure") } }))
            XCTAssertTrue(prepared.publicationAttempted)
            XCTAssertEqual(try String(contentsOf: store.file, encoding: .utf8), phase == "renamed" ? prepared.plain : old)
            XCTAssertThrowsError(try store.commit(old))
            XCTAssertThrowsError(try store.restoreSnapshotBytes())
            XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
        }
    }
    func testClosedHandoffCannotAdmitAnotherOrConsumedTransition() async throws {
        let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
        XCTAssertNil(try store.load())
        let configuration = try DAVAccountFileStore(directory: store.file.deletingLastPathComponent())
        let first = DAVAccountService(configuration: configuration), second = DAVAccountService(configuration: configuration)
        let one = try first.suspendBookAdmission(), two = try second.suspendBookAdmission()
        try await first.awaitBookSuspension(one); try await second.awaitBookSuspension(two)
        let source = directory.appendingPathComponent("backup.json"); try AtomicStore.write(Data(Document.encode(base).utf8), to: source)
        let prepared = try NativeBookRestore.prepare(store: store, transition: one, selection: BackupSelection(url: source), path: source.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
        let receipt: [String: Any] = ["operationID": prepared.operationID, "snapshot": prepared.plain]
        let expected = try NativeBookRestore.validatedExpectation(receipt, for: prepared)
        let saved = try NativeBookRestore.commit(prepared, store: store)
        // Synthetic handoff fixture only; actual WK callback is exercised separately.
        let handoff = try NativeBookRestore.verifyApplied(receipt, expectedSnapshot: expected, committed: saved)
        do { try await second.completeRestoredBookTransition(two, handoff: handoff); XCTFail("Foreign transition admitted") } catch {}
        XCTAssertThrowsError(try second.captureBookSession())
        try await first.completeRestoredBookTransition(one, handoff: handoff)
        _ = try first.captureBookSession()
        do { try await first.completeRestoredBookTransition(one, handoff: handoff); XCTFail("Consumed transition admitted") } catch {}
        let next = try first.suspendBookAdmission()
        do { try await first.completeRestoredBookTransition(next, handoff: handoff); XCTFail("Old handoff admitted a later transition") } catch {}
        XCTAssertThrowsError(try first.captureBookSession())
    }

    func testLegacyOneSidedAndConflictingEpochsRemainRestorable() throws {
        for slots in [
            ["syncEpoch": OrdinarySaveEpochPolicyTests.epoch],
            ["syncMetadaten": ["syncEpoch": OrdinarySaveEpochPolicyTests.epoch]],
            ["syncEpoch": OrdinarySaveEpochPolicyTests.epoch, "syncMetadaten": ["syncEpoch": OrdinarySaveEpochPolicyTests.other]]
        ] as [[String: Any]] {
            let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
            XCTAssertNil(try store.load())
            var legacy = base; for (key, value) in slots { legacy[key] = value }
            let old = try Document.encode(legacy); try store.commit(old)
            let source = directory.appendingPathComponent("legacy.json"); try AtomicStore.write(Data(old.utf8), to: source)
            let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: BackupSelection(url: source), path: source.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
            _ = try NativeBookRestore.validatedExpectation(["operationID": prepared.operationID, "snapshot": prepared.plain], for: prepared)
            let saved = try NativeBookRestore.commit(prepared, store: store)
            XCTAssertEqual(try DAVBookRestore.persistedEpoch(saved.evidence.book), prepared.epoch)
            XCTAssertNotEqual(prepared.epoch, UUID(uuidString: OrdinarySaveEpochPolicyTests.epoch))
            XCTAssertNotEqual(prepared.epoch, UUID(uuidString: OrdinarySaveEpochPolicyTests.other))
        }
    }

    func testEncryptedImportIntoAbsentProfileRetainsPasswordAndRejectsBadPasswordWithoutWrite() throws {
        let fixture = try Document.object(String(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "desktop-envelopes", withExtension: "json", subdirectory: "Fixtures")), encoding: .utf8))
        let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
        XCTAssertNil(try store.load())
        let source = directory.appendingPathComponent("encrypted-backup.json")
        try AtomicStore.write(Data(try XCTUnwrap(fixture["v1"] as? String).utf8), to: source)
        let selection = try BackupSelection(url: source), password = try XCTUnwrap(fixture["password"] as? String)
        XCTAssertThrowsError(try NativeBookRestore.prepare(store: store, transition: transition, selection: selection, path: source.path, password: "wrong-password", currentEncryption: nil, authenticatedOrigin: nil))
        XCTAssertNil(try store.restoreSnapshotBytes())
        let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: selection, path: source.path, password: password, currentEncryption: nil, authenticatedOrigin: nil)
        _ = try NativeBookRestore.validatedExpectation(["operationID": prepared.operationID, "snapshot": prepared.plain], for: prepared)
        let saved = try NativeBookRestore.commit(prepared, store: store)
        XCTAssertTrue(saved.evidence.encrypted)
        XCTAssertEqual(try Encryption.unlock(XCTUnwrap(saved.envelope), password: password).0, prepared.plain)
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
    }

    func testPostAuthenticationCipherChangeCannotReuseV1Origin() throws {
        let fixture = try Document.object(String(contentsOf: XCTUnwrap(Bundle.module.url(forResource: "desktop-envelopes", withExtension: "json", subdirectory: "Fixtures")), encoding: .utf8))
        let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
        XCTAssertNil(try store.load())
        let original = try XCTUnwrap(fixture["v1"] as? String); try store.commit(original)
        let origin = try NativeBookRestore.unlockActual(store: store, password: XCTUnwrap(fixture["password"] as? String))
        let source = directory.appendingPathComponent("backup.json"); try AtomicStore.write(Data(Document.encode(base).utf8), to: source)
        let changedCipher = original + " "
        try AtomicStore.write(Data(changedCipher.utf8), to: store.file)
        XCTAssertThrowsError(try NativeBookRestore.prepare(store: store, transition: transition, selection: BackupSelection(url: source), path: source.path, password: "", currentEncryption: origin.encryption, authenticatedOrigin: origin))
        XCTAssertEqual(try String(contentsOf: store.file, encoding: .utf8), changedCipher)
    }
    func testCurrentUIInvalidationWinsBeforeOrAfterQueuedHandoff() async throws {
        for invalidateBefore in [true, false] {
            let directory = try temporary(), store = try AtomicStore(directory: directory.appendingPathComponent("profile"))
            XCTAssertNil(try store.load())
            let service = DAVAccountService(configuration: try DAVAccountFileStore(directory: store.file.deletingLastPathComponent()))
            let transition = try service.suspendBookAdmission(); try await service.awaitBookSuspension(transition)
            let source = directory.appendingPathComponent("backup.json"); try AtomicStore.write(Data(Document.encode(base).utf8), to: source)
            let prepared = try NativeBookRestore.prepare(store: store, transition: transition, selection: BackupSelection(url: source), path: source.path, password: "", currentEncryption: nil, authenticatedOrigin: nil)
            let receipt: [String: Any] = ["operationID": prepared.operationID, "snapshot": prepared.plain]
            let expected = try NativeBookRestore.validatedExpectation(receipt, for: prepared)
            let committed = try NativeBookRestore.commit(prepared, store: store)
            let handoff = try NativeBookRestore.verifyApplied(receipt, expectedSnapshot: expected, committed: committed) // Explicit synthetic UI fixture.
            if invalidateBefore {
                service.invalidateBookAdmission()
                do { try await service.completeRestoredBookTransition(transition, handoff: handoff); XCTFail("Invalidated UI reopened queued admission") } catch {}
            } else {
                try await service.completeRestoredBookTransition(transition, handoff: handoff)
                _ = try service.captureBookSession()
                service.invalidateBookAdmission()
            }
            XCTAssertThrowsError(try service.captureBookSession())
            XCTAssertThrowsError(try service.suspendBookAdmission())
            XCTAssertEqual(try String(contentsOf: store.file, encoding: .utf8), prepared.plain)
        }
    }

}
#endif
