import Foundation
import XCTest
@testable import BetaCore

/// #785. Prepared for the real macOS Swift test job. These are protocol tests,
/// not claims about an Apple picker, a signed Python runtime or account access.
final class FileImportProtocolTests: XCTestCase {
    let manifest = String(repeating: "a", count: 64)
    func input(name: String = "original.or6") throws -> FileImportProtocol.Input {
        try .init(bytes: Data("original bytes\u{0}retained".utf8), format: "lotus", name: name,
                  language: "de-de", timeZone: "Europe/Berlin", homeCountry: "DE")
    }
    func envelope(_ source: FileImportProtocol.Input, result: [String: Any] = ["notizen": [["titel": "Original", "text": "Literal <text>"]]]) -> [String: Any] {
        ["schema": 1, "ok": true, "format": source.format, "name": source.name,
         "sourceSHA256": source.sourceSHA256, "parserManifestSHA256": manifest, "result": result]
    }
    func wire(_ object: [String: Any]) throws -> Data {
        var data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        data.append(10); return data
    }
    func testHeaderDescribesExactSelectedBytesAndConcreteRegionalContext() throws {
        let source = try input()
        XCTAssertEqual(source.header.last, 10)
        let header = try XCTUnwrap(JSONSerialization.jsonObject(with: source.header) as? [String: Any])
        XCTAssertEqual(Set(header.keys), Set(["schema", "format", "name", "language", "timeZone", "homeCountry", "byteLength", "sha256"]))
        XCTAssertEqual(header["byteLength"] as? Int, source.bytes.count)
        XCTAssertEqual(header["sha256"] as? String, FileImportProtocol.digest(source.bytes))
        XCTAssertEqual(header["language"] as? String, "de-de")
        XCTAssertEqual(header["timeZone"] as? String, "Europe/Berlin")
        XCTAssertEqual(header["homeCountry"] as? String, "DE")
        XCTAssertEqual(source.bytes, Data("original bytes\u{0}retained".utf8))
    }
    func testNativeCommandAdmitsFormatsWithoutWebSelectedPaths() throws {
        for format in FileImportProtocol.formats {
            var fields: [String: Any] = ["cmd": "import", "art": format]
            if format == "muell" { fields["muellToken"] = "waste-operation" }
            XCTAssertNoThrow(try Request(String(decoding: wire(fields), as: UTF8.self)))
            fields["path"] = "/unselected.or6"
            XCTAssertThrowsError(try Request(String(decoding: wire(fields), as: UTF8.self)))
        }
        for request in [#"{"cmd":"import","art":"magnolie"}"#,
                        #"{"cmd":"import","art":"muell"}"#,
                        #"{"cmd":"import","art":"lotus","muellToken":"wrong-purpose"}"#] {
            XCTAssertThrowsError(try Request(request))
        }
    }
    func testUnsafeNamesEmptyAndOversizedInputsAreRejected() throws {
        for name in ["", ".", "..", "../input.or6", "folder\\input.or6", "line\n.or6", String(repeating: "a", count: 1025)] {
            XCTAssertThrowsError(try input(name: name), name)
        }
        for bytes in [Data(), Data(repeating: 0, count: FileImportProtocol.maximumInputBytes + 1)] {
            XCTAssertThrowsError(try FileImportProtocol.Input(bytes: bytes, format: "lotus", name: "file.or6",
                language: "en", timeZone: "UTC", homeCountry: "DE"))
        }
    }
    func testSuccessfulResultIsBoundToSourceAndParserManifest() throws {
        let source = try input(), value = envelope(try input())
        let result = try FileImportProtocol.response(wire(value), input: source, manifestSHA256: manifest)
        XCTAssertEqual((result["notizen"] as? [[String: String]])?.first?["text"], "Literal <text>")
        for (field, replacement) in [("sourceSHA256", String(repeating: "b", count: 64)),
                                      ("parserManifestSHA256", String(repeating: "b", count: 64)),
                                      ("format", "ics"), ("name", "another.or6")] {
            var changed = value; changed[field] = replacement
            XCTAssertThrowsError(try FileImportProtocol.response(wire(changed), input: source, manifestSHA256: manifest), field)
        }
    }
    func testSourceNameUsesExactUTF8Identity() throws {
        let source = try input(name: "caf\u{00e9}.or6")
        var changed = envelope(source); changed["name"] = "cafe\u{0301}.or6"
        XCTAssertThrowsError(try FileImportProtocol.response(wire(changed), input: source, manifestSHA256: manifest))
    }
    func testBooleansAndNumbersCannotMasqueradeAsSchemaOrSuccess() throws {
        let source = try input()
        for (field, invalid) in [("schema", true as Any), ("schema", 1.5 as Any), ("ok", 1 as Any), ("ok", "true" as Any)] {
            var value = envelope(source); value[field] = invalid
            XCTAssertThrowsError(try FileImportProtocol.response(wire(value), input: source, manifestSHA256: manifest))
        }
    }
    func testCollectionsAndRecordBudgetAreCheckedBeforeApplication() throws {
        let source = try input()
        let invalidResults: [[String: Any]] = [["termine": "wrong"], ["notizen": [1]], ["fehler": "partial-result"],
            ["notizen": Array(repeating: ["titel": "over limit"], count: 100_001)]]
        for result in invalidResults {
            XCTAssertThrowsError(try FileImportProtocol.response(wire(envelope(source, result: result)), input: source, manifestSHA256: manifest))
        }
    }
    func testFramingDuplicateKeysAndExtraSuccessFieldsAreRejected() throws {
        let source = try input()
        var valid = try wire(envelope(source)); valid.removeLast()
        XCTAssertThrowsError(try FileImportProtocol.response(valid, input: source, manifestSHA256: manifest))
        XCTAssertThrowsError(try FileImportProtocol.response(Data("{\"schema\":1,\"schema\":1,\"ok\":true}\n".utf8), input: source, manifestSHA256: manifest))
        var extra = envelope(source); extra["unexpected"] = true
        XCTAssertThrowsError(try FileImportProtocol.response(wire(extra), input: source, manifestSHA256: manifest))
    }
    func testWellFormedHelperFailureNeverProvidesAPartialResult() throws {
        let source = try input()
        var failure: [String: Any] = ["schema": 1, "ok": false, "sourceSHA256": source.sourceSHA256,
            "parserManifestSHA256": manifest, "error": ["code": "unsupported", "message": "Synthetic invalid source"]]
        XCTAssertThrowsError(try FileImportProtocol.response(wire(failure), input: source, manifestSHA256: manifest)) { error in
            XCTAssertEqual(error.localizedDescription, "Synthetic invalid source")
        }
        failure["result"] = ["notizen": [["titel": "must not apply"]]]
        XCTAssertThrowsError(try FileImportProtocol.response(wire(failure), input: source, manifestSHA256: manifest)) { error in
            XCTAssertNotEqual(error.localizedDescription, "Synthetic invalid source")
        }
    }
    func testForeignOrMalformedFailureIsNotTrusted() throws {
        let source = try input()
        let base: [String: Any] = ["schema": 1, "ok": false, "sourceSHA256": NSNull(),
            "parserManifestSHA256": NSNull(), "error": ["code": "invalid-header", "message": "Safe helper failure"]]
        for (field, bad) in [("sourceSHA256", "foreign" as Any), ("error", ["message": "No code"] as Any),
                            ("error", ["code": "invalid", "message": String(repeating: "x", count: 4097)] as Any)] {
            var value = base; value[field] = bad
            XCTAssertThrowsError(try FileImportProtocol.response(wire(value), input: source, manifestSHA256: manifest)) { error in
                XCTAssertNotEqual(error.localizedDescription, "Safe helper failure")
            }
        }
    }
}
