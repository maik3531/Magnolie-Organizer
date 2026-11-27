import Foundation
import XCTest
@testable import BetaCore

/// Refs #511. The guarded dictionary bridge is still intentionally limited.
/// These tests do not claim that two equivalent-looking keys in one object load.
final class DocumentOpaqueIdentityTests: XCTestCase {
    private let nfc = "caf\u{e9}"
    private let nfd = "cafe\u{301}"
    private let bridgeLimitation = "This macOS version cannot safely preserve distinct Unicode JSON keys. The original file was not changed."

    private func book(_ fields: String) -> String {
        "{\"termine\":[],\"aufgaben\":[],\"kontakte\":[],\"notizen\":[]," + fields + "}"
    }
    private func noLoss(_ before: String, _ after: String) throws {
        try Document.assertNoLoss(Document.object(before), Document.object(after))
    }

    func testFixtureHasDifferentUTF8DespiteSwiftCanonicalEquality() {
        XCTAssertEqual(nfc, nfd, "Documents must not inherit this UI-text equivalence")
        XCTAssertNotEqual(Data(nfc.utf8), Data(nfd.utf8))
        XCTAssertNotEqual(OpaqueUTF8Identity(nfc), OpaqueUTF8Identity(nfd))
    }

    func testTrueDecodedDuplicateKeysRemainInvalid() {
        for text in [#"{"a":1,"\u0061":2}"#,
                     #"{"caf\u00e9":1,"café":2}"#,
                     #"{"outer":[{"cafe\u0301":1,"cafe\u0301":2}]}"#] {
            XCTAssertThrowsError(try Document.object(text)) {
                XCTAssertEqual($0.localizedDescription, "Duplicate JSON key.")
            }
        }
    }

    func testDistinctEquivalentKeysRemainBlockedBeforeTheLossyBridge() {
        let pair = "{\"" + nfc + "\":1,\"" + nfd + "\":2}"
        for text in [pair, "{\"outer\":" + pair + "}", "{\"outer\":[" + pair + "]}",
                     #"{"caf\u00e9":1,"cafe\u0301":2}"#] {
            XCTAssertThrowsError(try Document.object(text)) {
                XCTAssertEqual($0.localizedDescription, self.bridgeLimitation)
            }
        }
    }

    func testNoncollidingUnicodeKeysRoundtripWithOriginalUTF8() throws {
        // Different objects can retain these keys without a dictionary collision.
        let source = "{\"left\":{\"" + nfc + "\":1},\"right\":{\"" + nfd + "\":2}}"
        let output = try Document.object(Document.encode(Document.object(source)))
        for (name, expected) in [("left", nfc), ("right", nfd)] {
            let object = try XCTUnwrap(output[name] as? [String: Any])
            XCTAssertEqual(object.count, 1)
            XCTAssertEqual(Data(try XCTUnwrap(object.keys.first).utf8), Data(expected.utf8))
        }
    }

    func testNoLossDistinguishesFieldReplacementAtEveryDepth() throws {
        let left = "{\"" + nfc + "\":{\"keep\":true}}"
        let right = "{\"" + nfd + "\":{\"keep\":true}}"
        XCTAssertThrowsError(try noLoss(left, right))
        XCTAssertThrowsError(try noLoss(right, left))
        XCTAssertThrowsError(try noLoss("{\"future\":[" + left + "]}", "{\"future\":[" + right + "]}"))
        XCTAssertNoThrow(try noLoss(left, left))
        XCTAssertNoThrow(try noLoss(right, right))
        // Escaping does not change the decoded JSON key's identity.
        XCTAssertNoThrow(try noLoss(#"{"caf\u00e9":{"keep":true}}"#, left))
    }

    func testNoLossDistinguishesRecordReplacement() throws {
        let left = "{\"records\":[{\"id\":\"" + nfc + "\",\"unknown\":true}]}"
        let right = "{\"records\":[{\"id\":\"" + nfd + "\",\"unknown\":true}]}"
        XCTAssertThrowsError(try noLoss(left, right))
        XCTAssertThrowsError(try noLoss(right, left))
        XCTAssertNoThrow(try noLoss(left, left))
        XCTAssertNoThrow(try noLoss(right, right))
    }

    func testDifferentOpaqueRecordIDsCanCoexistAndReorderWithoutFalseRecovery() throws {
        let first = "{\"id\":\"" + nfc + "\",\"nfcOnly\":{\"keep\":1}}"
        let second = "{\"id\":\"" + nfd + "\",\"nfdOnly\":{\"keep\":2}}"
        let before = "{\"records\":[" + first + "," + second + "]}"
        let after = "{\"records\":[" + second + "," + first + "]}"
        XCTAssertNoThrow(try noLoss(before, after))
        XCTAssertNoThrow(try noLoss("{\"records\":[" + first + "]}", after))
        XCTAssertThrowsError(try noLoss(before, "{\"records\":[" + first + "," + first + "]}"))
        let crossed = "{\"records\":[{\"id\":\"" + nfc + "\",\"nfdOnly\":{\"keep\":2}}," +
            "{\"id\":\"" + nfd + "\",\"nfcOnly\":{\"keep\":1}}]}"
        XCTAssertThrowsError(try noLoss(before, crossed), "Unknown fields must follow the exact original ID")
    }

    func testLexicalReplacementCreatesExactRecoveryBeforeDiskCommitAndReopen() throws {
        for fieldChange in [true, false] {
            let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: directory) }
            var store: AtomicStore? = try AtomicStore(directory: directory)
            XCTAssertNil(try store!.load())
            func fields(_ key: String) -> String {
                fieldChange ? "\"future\":{\"" + key + "\":{\"preserved\":true}}" :
                    "\"records\":[{\"id\":\"" + key + "\",\"preserved\":true}]"
            }
            let original = book(fields(nfc)) + "\n"
            try store!.commit(original)
            let policy = try OrdinarySaveEpochPolicy(loadedPlain: original)
            let candidate = try policy.prepare(candidate: book(fields(nfd)))
            // This is the production Host's exact recovery decision, not a stubbed ACK.
            let needsRecovery = (try? Document.assertNoLoss(Document.object(original), Document.plain(candidate))) == nil
            XCTAssertTrue(needsRecovery)
            try store!.commit(candidate, preservingCurrent: needsRecovery)
            let snapshots = try FileManager.default.contentsOfDirectory(
                at: directory.appendingPathComponent("Recovery-macOS-Beta"), includingPropertiesForKeys: nil)
            XCTAssertEqual(snapshots.count, 1)
            XCTAssertEqual(try AtomicStore.read(try XCTUnwrap(snapshots.first)), Data(original.utf8))
            let file = store!.file
            XCTAssertEqual(try AtomicStore.read(file), Data(candidate.utf8))
            store = nil
            store = try AtomicStore(directory: directory)
            XCTAssertEqual(Data(try XCTUnwrap(store!.load()).utf8), Data(candidate.utf8))
            store = nil
        }
    }

    func testUnsupportedUnicodePairCannotChangeAnExistingProfile() throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try AtomicStore(directory: directory)
        XCTAssertNil(try store.load())
        let original = book("\"future\":{\"unchanged\":true}") + "\n"
        try store.commit(original)
        let rejected = book("\"future\":{\"" + nfc + "\":1,\"" + nfd + "\":2}")
        let policy = try OrdinarySaveEpochPolicy(loadedPlain: original)
        XCTAssertThrowsError(try policy.prepare(candidate: rejected)) {
            XCTAssertEqual($0.localizedDescription, self.bridgeLimitation)
        }
        XCTAssertThrowsError(try store.commit(rejected))
        XCTAssertEqual(try AtomicStore.read(store.file), Data(original.utf8))
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent("Recovery-macOS-Beta").path))
    }

    func testActualProjectedSaveRemainsGuardedAtNativeBoundary() throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_OPAQUE_JSON_FIXTURE"] else {
            throw XCTSkip("Run tools/check_opaque_json.py --js-runtime node --swift /path/to/swift for actual projected inputs.")
        }
        let fixture = try Document.object(String(contentsOfFile: path, encoding: .utf8))
        XCTAssertEqual(fixture["schema"] as? Int, 1)
        let save = try XCTUnwrap(fixture["saveRequest"] as? [String: Any])
        let request = try Request(Document.encode(save))
        XCTAssertEqual(request.command, .speichern)
        let candidate = request.text("text")
        XCTAssertThrowsError(try Document.plain(candidate)) {
            XCTAssertEqual($0.localizedDescription, self.bridgeLimitation)
        }
        let restore = try XCTUnwrap(fixture["restoreSnapshot"] as? String)
        XCTAssertThrowsError(try Document.plain(restore)) {
            XCTAssertEqual($0.localizedDescription, self.bridgeLimitation)
        }
    }
}
