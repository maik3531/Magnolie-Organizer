import Foundation
import XCTest
@testable import BetaCore

final class OrdinarySaveEpochPolicyTests: XCTestCase {
    static let epoch = "12345678-1234-4234-8234-123456789abc"
    static let other = "aaaaaaaa-1234-4234-8234-123456789abc"
    static let base: [String: Any] = ["termine": [], "aufgaben": [], "kontakte": [], "notizen": [], "futureRoot": ["keep": 7]]
    static func vectors() -> [[String: Any]] {
        var result = [base]
        for value in ["", NSNull(), "invalid", 7, true, ["invalid": true], epoch] as [Any] {
            var root = base; root["syncEpoch"] = value; result.append(root)
            var meta = base; meta["syncMetadaten"] = ["syncEpoch": value]; result.append(meta)
            var settings = base; settings["einstellungen"] = ["sync": ["syncEpoch": value]]; result.append(settings)
        }
        for settings in [[:], ["sync": ["syncEpoch": epoch]], ["sync": ["syncEpoch": other]], ["sync": ["syncEpoch": NSNull()]], ["sync": "invalid"], "invalid", NSNull(), ["sync": NSNull()]] as [Any] {
            var book = base; book["syncEpoch"] = epoch; book["syncMetadaten"] = ["syncEpoch": epoch]; book["einstellungen"] = settings; result.append(book)
        }
        for value in [NSNull(), "invalid", 7] as [Any] {
            var book = base; book["syncMetadaten"] = value; result.append(book)
        }
        var conflict = base; conflict["syncEpoch"] = epoch; conflict["syncMetadaten"] = ["syncEpoch": other]; result.append(conflict)
        return result
    }
    static func slotBytes(_ book: [String: Any]) throws -> [Data?] {
        try [["syncEpoch"], ["syncMetadaten", "syncEpoch"], ["einstellungen", "sync", "syncEpoch"]].map { path in
            var current: Any = book
            for key in path {
                guard let dictionary = current as? [String: Any], let value = dictionary[key] else { return nil }
                current = value
            }
            return try JSONSerialization.data(withJSONObject: current, options: [.fragmentsAllowed, .sortedKeys])
        }
    }
    func testMalformedOptionalContainersProtectExistingPairWithoutGrantingAdmission() throws {
        let expected = try XCTUnwrap(UUID(uuidString: Self.epoch))
        for settings in ["invalid", NSNull(), ["sync": "invalid"], ["sync": NSNull()]] as [Any] {
            var original = Self.base
            original["syncEpoch"] = Self.epoch; original["syncMetadaten"] = ["syncEpoch": Self.epoch]
            original["einstellungen"] = settings
            XCTAssertThrowsError(try DAVBookRestore.persistedEpoch(original), "Strict native disk predicate must remain unchanged")
            let policy = try OrdinarySaveEpochPolicy(loadedPlain: Document.encode(original))
            XCTAssertEqual(policy.classification, .protectedEpoch(expected))
            var repaired = original; repaired["einstellungen"] = ["sync": ["futureSync": 4]]
            let saved = try Document.plain(policy.prepare(candidate: Document.encode(repaired)))
            XCTAssertEqual(try Self.slotBytes(saved), try Self.slotBytes(original))
            XCTAssertEqual(try DAVBookRestore.persistedEpoch(saved), expected)
            // A well-shaped saved epoch is still not a NativeAdmission lease or verified baseline.
        }
    }
    func testEstablishedCannotChangeAuthorityAndLegacyCannotMintIt() throws {
        for original in Self.vectors() {
            let text = try Document.encode(original), policy = try OrdinarySaveEpochPolicy(loadedPlain: text)
            var edited = original; edited["syncEpoch"] = Self.other
            edited["syncMetadaten"] = ["syncEpoch": Self.other, "futureMeta": 3]
            edited["einstellungen"] = ["sync": ["syncEpoch": Self.other, "futureSync": 4]]
            if case .protectedEpoch = policy.classification { XCTAssertThrowsError(try policy.prepare(candidate: Document.encode(edited))) }
            else {
                let output = try Document.plain(policy.prepare(candidate: Document.encode(edited)))
                XCTAssertThrowsError(try DAVBookRestore.persistedEpoch(output))
                XCTAssertEqual(try Self.slotBytes(output), try Self.slotBytes(original))
                XCTAssertEqual((output["syncMetadaten"] as? [String: Any])?["futureMeta"] as? Int, 3)
                XCTAssertEqual(((output["einstellungen"] as? [String: Any])?["sync"] as? [String: Any])?["futureSync"] as? Int, 4)
                XCTAssertEqual(try policy.prepare(candidate: Document.encode(output)), try Document.encode(output))
            }
        }
    }
}
