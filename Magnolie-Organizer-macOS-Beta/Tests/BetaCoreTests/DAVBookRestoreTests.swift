import Foundation
import XCTest
import Darwin
@testable import BetaCore

final class DAVBookRestoreTests: XCTestCase {
    private func fixture() throws -> [String: Any] {
        let path = Bundle.module.url(forResource: "dav-book-restore", withExtension: "json", subdirectory: "Fixtures")!
        return try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: Any]
    }
    private func transform(_ incoming: [String: Any]? = nil, live: [String: Any]? = nil) throws -> [String: Any] {
        let data = try fixture()
        return try DAVBookRestore.transform(incoming: incoming ?? data["incoming"] as! [String: Any], live: live ?? data["live"] as! [String: Any],
            newEpoch: UUID(uuidString: data["newEpoch"] as! String)!, restoredAt: ISO8601DateFormatter().date(from: data["restoredAt"] as! String)!)
    }
    private func root() throws -> URL {
        let path = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("dav-book-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        addTeardownBlock { try? FileManager.default.removeItem(at: path) }; return path
    }
    func testFrozenTransformMatchesSharedNormalizerFixtureExactly() throws {
        let expected = try fixture()["expected"] as! [String: Any]
        XCTAssertEqual(try DAVSyncBaseline.canonicalJSON(transform()), try DAVSyncBaseline.canonicalJSON(expected))
        XCTAssertEqual(try DAVBookRestore.persistedEpoch(expected), UUID(uuidString: expected["syncEpoch"] as! String))
    }
    func testActualNormalizerSavedBindingFixtureRetainsPresentFieldsAndAllowsMissingOptionalCopy() throws {
        let path = Bundle.module.url(forResource: "dav-book-normalized-epoch", withExtension: "json", subdirectory: "Fixtures")!
        let vector = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: Any]
        let saved = vector["savedBinding"] as! [String: Any], expected = try transform()
        XCTAssertEqual(try DAVBookRestore.persistedEpoch(saved), try DAVBookRestore.persistedEpoch(expected))
        let meta = saved["syncMetadaten"] as! [String: Any], expectedMeta = expected["syncMetadaten"] as! [String: Any]
        XCTAssertEqual(try DAVSyncBaseline.canonicalJSON(meta["quarantinedDeletes"]!), try DAVSyncBaseline.canonicalJSON(expectedMeta["quarantinedDeletes"]!))
        var absent = saved, settings = absent["einstellungen"] as! [String: Any], sync = settings["sync"] as! [String: Any]
        sync.removeValue(forKey: "syncEpoch"); settings["sync"] = sync; absent["einstellungen"] = settings
        XCTAssertEqual(try DAVBookRestore.persistedEpoch(absent), try DAVBookRestore.persistedEpoch(saved))
        sync["syncEpoch"] = UUID().uuidString; settings["sync"] = sync; absent["einstellungen"] = settings
        XCTAssertThrowsError(try DAVBookRestore.persistedEpoch(absent))
    }
    func testPriorLiveArchivedAndActiveQuarantineAreMergedWithoutLosingOpaqueContent() throws {
        let result = try transform(), meta = result["syncMetadaten"] as! [String: Any]
        let quarantine = meta["quarantinedDeletes"] as! [String: Any], removed = quarantine["geloescht"] as! [String: Any]
        let rows = removed["termine"] as! [[String: Any]]
        XCTAssertEqual(rows.compactMap { $0["uid"] as? String }, ["live-prior", "archive-prior", "archive-active"])
        XCTAssertEqual(rows.compactMap { $0["opaque"] as? String }, ["keep-live", "keep-archive", "keep-active"])
        XCTAssertEqual((result["futureRoot"] as! [String: Any])["opaque"] as? String, "keep-root")
        XCTAssertEqual(meta["futureMeta"] as? String, "keep")
        XCTAssertEqual((result["syncNachRestore"] as! [String: Any])["future"] as? String, "keep")
        var input = try fixture()["incoming"] as! [String: Any]
        input["smsPlanung"] = [["id": "one", "status": "planned"], ["id": "two", "status": "submitting"]]
        let restored = try transform(input), plans = restored["smsPlanung"] as! [[String: Any]]
        XCTAssertEqual(plans.compactMap { $0["status"] as? String }, ["paused", "uncertain"])
    }
    func testConflictingAndUnknownQuarantineShapesFailWithoutMutatingInput() throws {
        let input = try fixture()["incoming"] as! [String: Any]
        let invalidValues: [Any] = [["futureHistory": ["opaque"]], ["geloescht": ["futureDomain": []]], ["tombstones": "not-a-list"], ["geloescht": ["termine": ["not-a-record"]]]]
        for invalid in invalidValues {
            var candidate = input, meta = candidate["syncMetadaten"] as! [String: Any]
            meta["quarantinedDeletes"] = invalid; candidate["syncMetadaten"] = meta
            XCTAssertThrowsError(try transform(candidate))
        }
        XCTAssertEqual(try DAVSyncBaseline.canonicalJSON(input), try DAVSyncBaseline.canonicalJSON(fixture()["incoming"]!))
    }
    func testQuarantineLimitsAndReusedEpochRejectBeforePublishing() throws {
        var input = try fixture()["incoming"] as! [String: Any]
        input["tombstones"] = [["id": "large", "opaque": String(repeating: "x", count: DAVBookRestore.maximumQuarantineBytes / 6 + 1)]]
        XCTAssertThrowsError(try transform(input)) { XCTAssertEqual($0 as? DAVBookRestoreError, .limit) }
        let data = try fixture(), original = data["incoming"] as! [String: Any]
        XCTAssertThrowsError(try DAVBookRestore.transform(incoming: original, live: [:], newEpoch: UUID(uuidString: original["syncEpoch"] as! String)!, restoredAt: Date())) {
            XCTAssertEqual($0 as? DAVBookRestoreError, .invalidEpoch)
        }
    }
    func testDuplicateQuarantineContentIsDeduplicatedExactlyNotByUID() throws {
        var input = try fixture()["incoming"] as! [String: Any]
        input["tombstones"] = [["uid": "same", "payload": "first"], ["uid": "same", "payload": "first"], ["uid": "same", "payload": "different"]]
        let result = try transform(input), meta = result["syncMetadaten"] as! [String: Any]
        let quarantine = meta["quarantinedDeletes"] as! [String: Any]
        XCTAssertEqual((quarantine["tombstones"] as! [[String: Any]]).count, 2)
    }
    func testPersistedEpochRejectsMissingContradictoryAndVolatileNonUUIDValues() throws {
        let valid = try transform()
        let invalidValues: [Any] = ["volatile-host-generation", NSNull(), UUID().uuidString]
        for value in invalidValues {
            var changed = valid; changed["syncEpoch"] = value
            XCTAssertThrowsError(try DAVBookRestore.persistedEpoch(changed))
        }
        var missing = valid; missing.removeValue(forKey: "syncEpoch")
        XCTAssertThrowsError(try DAVBookRestore.persistedEpoch(missing))
    }
    func testPlainActualDiskSnapshotAndRestoreEpochPersistAcrossReopen() throws {
        let directory = try root(), book = try transform()
        let text = try Document.encode(book)
        var store: AtomicStore? = try AtomicStore(directory: directory)
        XCTAssertNil(try store!.load()); try store!.commit(text)
        let first = try DAVBookDiskSnapshot.read(store: store!)
        XCTAssertFalse(first.encrypted); XCTAssertEqual(first.epoch, try DAVBookRestore.persistedEpoch(book))
        XCTAssertEqual(first.rawSHA256, DAVSyncJournalStore.digest(Data(text.utf8)))
        store = nil; store = try AtomicStore(directory: directory); _ = try store!.load()
        let reopened = try DAVBookDiskSnapshot.read(store: store!)
        XCTAssertEqual(first.epoch, reopened.epoch); XCTAssertEqual(first.rawSHA256, reopened.rawSHA256)
    }
    func testEncryptedSnapshotAuthenticatesActualV2BytesWithUnlockedSessionOnly() throws {
        let store = try AtomicStore(directory: root()), book = try transform()
        _ = try store.load()
        let session = try Encryption.create(password: "synthetic-test-password")
        let sealed = try session.encrypt(Document.encode(book)); try store.commit(sealed)
        let evidence = try DAVBookDiskSnapshot.read(store: store, encryption: session)
        XCTAssertTrue(evidence.encrypted); XCTAssertEqual(evidence.epoch, try DAVBookRestore.persistedEpoch(book))
        XCTAssertEqual(evidence.rawSHA256, DAVSyncJournalStore.digest(Data(sealed.utf8)))
        XCTAssertThrowsError(try DAVBookDiskSnapshot.read(store: store))
        let wrong = try Encryption.create(password: "different-synthetic-password")
        XCTAssertThrowsError(try DAVBookDiskSnapshot.read(store: store, encryption: wrong))
    }
    func testSnapshotRejectsExternalBytesInsteadOfUsingPreviouslyLoadedPlaintext() throws {
        let store = try AtomicStore(directory: root()), book = try transform()
        _ = try store.load(); try store.commit(Document.encode(book))
        var changed = book; changed["futureRoot"] = ["opaque": "external-write"]
        try AtomicStore.write(Data(try Document.encode(changed).utf8), to: store.file)
        XCTAssertThrowsError(try DAVBookDiskSnapshot.read(store: store))
        XCTAssertThrowsError(try store.commit(Document.encode(book)))
    }
    func testActualFileAndDirectoryDurabilityFailureNeverIssuesSnapshotAndPoisonsWriter() throws {
        for point in ["snapshot-read", "snapshot-fsync", "snapshot-fullsync", "snapshot-dirsync"] {
            let store = try AtomicStore(directory: root()), book = try transform(), text = try Document.encode(book)
            _ = try store.load(); try store.commit(text)
            XCTAssertThrowsError(try store.durableSnapshotBytes { if $0 == point { throw DAVBookRestoreError.invalidInput } })
            XCTAssertEqual(try AtomicStore.read(store.file), Data(text.utf8))
            XCTAssertThrowsError(try store.commit(text))
        }
    }
    func testSnapshotFencesReplacedLeaseAndSameBytesNewFileInodeDuringRead() throws {
        let store = try AtomicStore(directory: root()), book = try transform(), text = try Document.encode(book)
        _ = try store.load(); try store.commit(text)
        XCTAssertThrowsError(try store.durableSnapshotBytes { point in
            if point == "snapshot-read" { try AtomicStore.write(Data(text.utf8), to: store.file) }
        })
        let other = try AtomicStore(directory: root()); _ = try other.load(); try other.commit(text)
        XCTAssertEqual(unlink(other.file.deletingLastPathComponent().appendingPathComponent("profile.lock").path), 0)
        XCTAssertThrowsError(try DAVBookDiskSnapshot.read(store: other))
    }
    func testSameInodeDurableCorruptionThenUnsyncedOriginalBytesCannotPassSnapshot() throws {
        let store = try AtomicStore(directory: root()), text = try Document.encode(transform())
        _ = try store.load(); try store.commit(text)
        let saved = Data(text.utf8)
        var fullSyncReached = false, replacementReached = false
        XCTAssertThrowsError(try store.durableSnapshotBytes { point in
            if point == "snapshot-fullsync" { fullSyncReached = true }
            if point == "snapshot-dirsync" {
                XCTAssertTrue(fullSyncReached); replacementReached = true
                let fd = open(store.file.path, O_WRONLY | O_NOFOLLOW | O_CLOEXEC)
                XCTAssertGreaterThanOrEqual(fd, 0); defer { close(fd) }
                var corrupt = saved; corrupt[0] ^= 1
                let badWritten = corrupt.withUnsafeBytes { pwrite(fd, $0.baseAddress!, $0.count, 0) }
                XCTAssertEqual(badWritten, corrupt.count); XCTAssertEqual(fsync(fd), 0); XCTAssertEqual(fcntl(fd, F_FULLFSYNC), 0)
                // Restore exactly equal bytes/inode after every snapshot durability barrier,
                // deliberately without a subsequent fsync/F_FULLFSYNC.
                let restored = saved.withUnsafeBytes { pwrite(fd, $0.baseAddress!, $0.count, 0) }
                XCTAssertEqual(restored, saved.count)
            }
        })
        XCTAssertTrue(replacementReached)
        XCTAssertEqual(try AtomicStore.read(store.file), saved)
        XCTAssertThrowsError(try store.commit(text))
    }
    func testPublicInputPreflightBoundsDepthBytesAndDoesNotPenalizeUTF8Sixfold() throws {
        let value = ["attachment": String(repeating: "Ä", count: 1000)]
        let actualSize = try JSONSerialization.data(withJSONObject: value).count
        XCTAssertNoThrow(try DAVBookRestore.preflightInput(value, maximumBytes: actualSize + 2))
        XCTAssertThrowsError(try DAVBookRestore.preflightInput(value, maximumBytes: actualSize - 1))
        XCTAssertThrowsError(try DAVBookRestore.preflightInput(value, maximumBytes: 0))
        var deep: [String: Any] = [:]
        for _ in 0..<65 { deep = ["nested": deep] }
        var incoming = try fixture()["incoming"] as! [String: Any]; incoming["futureRoot"] = deep
        XCTAssertThrowsError(try transform(incoming)) { XCTAssertEqual($0 as? DAVBookRestoreError, .limit) }
        let vector = try fixture(), original = vector["incoming"] as! [String: Any]
        var live = vector["live"] as! [String: Any], personal = live["personalSync"] as! [String: Any]
        personal["custom_entities"] = ["opaque": String(repeating: "x", count: 10_000)]; live["personalSync"] = personal
        XCTAssertNoThrow(try DAVBookRestore.preflightInput(original, maximumBytes: 11_500))
        XCTAssertNoThrow(try DAVBookRestore.preflightInput(live, maximumBytes: 11_500))
        XCTAssertThrowsError(try DAVBookRestore.transform(incoming: original, live: live,
            newEpoch: UUID(uuidString: vector["newEpoch"] as! String)!, restoredAt: ISO8601DateFormatter().date(from: vector["restoredAt"] as! String)!, maximumBytes: 11_500)) {
            XCTAssertEqual($0 as? DAVBookRestoreError, .limit)
        }
    }
    func testEncryptionSnapshotRejectsTamperedCipherWrappingAndLegacyVersion() throws {
        let session = try Encryption.create(password: "synthetic-test-password"), plain = try Document.encode(transform())
        let cipher = try session.encrypt(plain), envelope = try Document.object(cipher)
        for field in ["daten", "dekDaten", "dekKennung", "salz"] {
            var changed = envelope
            var bytes = Data(base64Encoded: changed[field] as! String)!; bytes[0] ^= 1; changed[field] = bytes.base64EncodedString()
            XCTAssertThrowsError(try session.openSnapshot(Document.encode(changed)))
        }
        var legacy = envelope; legacy["fassung"] = 1
        XCTAssertThrowsError(try session.openSnapshot(Document.encode(legacy)))
        XCTAssertEqual(try session.openSnapshot(cipher), plain)
    }
}
