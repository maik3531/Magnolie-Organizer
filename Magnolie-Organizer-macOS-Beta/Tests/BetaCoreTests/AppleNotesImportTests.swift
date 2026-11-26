import Foundation
import XCTest
@testable import BetaCore

final class AppleNotesImportTests: XCTestCase {
    private func source(accountID: String = "account-one", accountTitle: String = "Selected account",
                        folderID: String = "folder-one", folderTitle: String = "Selected folder") -> AppleNotesImport.Source {
        .init(accountID: accountID, accountTitle: accountTitle, folderID: folderID, folderTitle: folderTitle)
    }
    private func record(id: String = "note-one", title: String = "Native note 🌼", protected: Bool? = false,
                        attachments: Int? = 0, text: String? = "Exact native text", html: String? = "<div>Exact native text</div>",
                        modified: Double? = 1_780_000_000.25, failure: String? = nil) -> AppleNotesImport.Record {
        .init(identifier: id, title: title, passwordProtected: protected, attachmentCount: attachments,
              plaintext: text, bodyHTML: html, modified: modified, failure: failure)
    }
    private func snapshot(_ records: [AppleNotesImport.Record], source selected: AppleNotesImport.Source? = nil) -> AppleNotesImport.Snapshot {
        .init(source: selected ?? source(), records: records)
    }
    private func notes(_ plan: AppleNotesImport.Plan) throws -> [[String: Any]] {
        try XCTUnwrap(plan.payload["notes"] as? [[String: Any]])
    }
    private func excluded(_ plan: AppleNotesImport.Plan) throws -> [[String: Any]] {
        try XCTUnwrap(plan.payload["excluded"] as? [[String: Any]])
    }
    private func firstNote(_ plan: AppleNotesImport.Plan) throws -> [String: Any] { try XCTUnwrap(notes(plan).first) }

    func testExactPayloadContainsLiteralTextAndOriginalNativeFields() throws {
        let plain = "  Zeile e\u{301} 🌼\r\n\t<script>literal text</script>  "
        let html = "<div data-x=\"quoted\"><script>notExecutable()</script>&amp; e\u{301}</div>"
        let original = record(title: "  Original title  ", text: plain, html: html)
        let plan = try AppleNotesImport.prepare(snapshot([original]))
        XCTAssertEqual(Set(plan.payload.keys), Set(["version", "source", "notes", "excluded", "snapshotRevision"]))
        XCTAssertEqual(plan.payload["version"] as? Int, 1)
        XCTAssertEqual(plan.payload["snapshotRevision"] as? String, plan.snapshotRevision)
        let selected = try XCTUnwrap(plan.payload["source"] as? [String: Any])
        XCTAssertEqual(Set(selected.keys), Set(["accountID", "accountTitle", "folderID", "folderTitle"]))
        XCTAssertEqual(selected["accountID"] as? String, "account-one")
        let note = try firstNote(plan)
        XCTAssertEqual(Set(note.keys), Set(["identity", "revision", "identifier", "title", "text", "nativeRecord"]))
        XCTAssertEqual(note["title"] as? String, "  Original title  ")
        XCTAssertEqual(Data(try XCTUnwrap(note["text"] as? String).utf8), Data(plain.utf8))
        let raw = try XCTUnwrap(note["nativeRecord"] as? [String: Any])
        XCTAssertEqual(Set(raw.keys), Set(["identifier", "title", "passwordProtected", "attachmentCount", "plaintext", "bodyHTML", "modified", "failure"]))
        XCTAssertEqual(raw["passwordProtected"] as? Bool, false)
        XCTAssertEqual(raw["attachmentCount"] as? Int, 0)
        XCTAssertEqual(Data(try XCTUnwrap(raw["plaintext"] as? String).utf8), Data(plain.utf8))
        XCTAssertEqual(Data(try XCTUnwrap(raw["bodyHTML"] as? String).utf8), Data(html.utf8))
        XCTAssertEqual(raw["modified"] as? Double, 1_780_000_000.25)
        XCTAssertTrue(raw["failure"] is NSNull)
        XCTAssertTrue(try excluded(plan).isEmpty)
        XCTAssertNoThrow(try plan.revalidate(snapshot([original])))
        // Independent SHA-256 vector: two UInt64-BE length-framed UTF-8 values,
        // prefixed by the UInt64-BE component count (account-one, note-one).
        XCTAssertEqual(note["identity"] as? String, "b2445ad5193ee243176c5ce803f403f404d51cbe36029a7416de84417c58eac8")
    }

    func testEmptyNoteAndEmptyTitleAreRetainedWithoutInventingContent() throws {
        let plan = try AppleNotesImport.prepare(snapshot([record(title: "", text: "", html: "")]))
        let note = try firstNote(plan)
        XCTAssertEqual(note["title"] as? String, "")
        XCTAssertEqual(note["text"] as? String, "")
        XCTAssertEqual((note["nativeRecord"] as? [String: Any])?["bodyHTML"] as? String, "")
        XCTAssertTrue(try excluded(plan).isEmpty)
    }

    func testMissingAndUnsupportedStatesAreVisibleExclusions() throws {
        let examples: [(AppleNotesImport.Record, String)] = [
            (record(failure: "apple-notes-property-error:-1728"), "apple-note-read-failed"),
            (record(failure: ""), "apple-note-read-failed"),
            (record(protected: nil), "apple-note-protection-state-unavailable"),
            (record(protected: true, text: nil, html: nil), "apple-note-password-protected"),
            (record(attachments: nil), "apple-note-attachment-state-unavailable"),
            (record(attachments: -1), "apple-note-attachment-state-unavailable"),
            (record(attachments: 1), "apple-note-has-attachments"),
            (record(text: nil), "apple-note-plaintext-unavailable"),
            (record(html: nil), "apple-note-html-unavailable"),
            (record(modified: nil), "apple-note-modification-state-unavailable")
        ]
        for (input, reason) in examples {
            let plan = try AppleNotesImport.prepare(snapshot([input]))
            XCTAssertTrue(try notes(plan).isEmpty, reason)
            let rejected = try XCTUnwrap(excluded(plan).first)
            XCTAssertEqual(Set(rejected.keys), Set(["identifier", "title", "reasons"]))
            XCTAssertEqual(rejected["identifier"] as? String, input.identifier)
            XCTAssertEqual(rejected["title"] as? String, input.title)
            XCTAssertTrue((rejected["reasons"] as? [String] ?? []).contains(reason), reason)
            XCTAssertNoThrow(try plan.revalidate(snapshot([input])))
        }
    }

    func testProtectedBodiesAreAContractErrorAndNeverBecomeAProposal() throws {
        for input in [record(protected: true, text: "private locked body", html: nil),
                      record(protected: true, text: nil, html: "<p>private locked body</p>"),
                      record(protected: true, text: "", html: "")] {
            XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([input]))) { error in
                XCTAssertTrue(error.localizedDescription.contains("protected notes"))
                XCTAssertFalse(error.localizedDescription.contains("private locked body"))
            }
        }
        let input = record(protected: true, text: nil, html: nil)
        let plan = try AppleNotesImport.prepare(snapshot([input]))
        XCTAssertTrue(try notes(plan).isEmpty)
        let payload = try Document.object(Document.encode(plan.payload))
        XCTAssertEqual(Set(payload.keys), Set(["version", "source", "notes", "excluded", "snapshotRevision"]))
        let exclusions = try XCTUnwrap(payload["excluded"] as? [[String: Any]])
        XCTAssertEqual(exclusions.count, 1)
        let rejected = try XCTUnwrap(exclusions.first)
        // A reason may contain "plaintext"; it must never be mistaken for a body field.
        XCTAssertEqual(Set(rejected.keys), Set(["identifier", "title", "reasons"]))
        XCTAssertEqual(rejected["identifier"] as? String, input.identifier)
        XCTAssertEqual(rejected["title"] as? String, input.title)
        XCTAssertEqual(rejected["reasons"] as? [String],
                       ["apple-note-html-unavailable", "apple-note-password-protected", "apple-note-plaintext-unavailable"])
        XCTAssertTrue(try XCTUnwrap(payload["notes"] as? [[String: Any]]).isEmpty)
    }

    func testReadFailureBodiesAndErrorDetailsStayOutOfWebPayload() throws {
        let input = record(text: "unreadable secret", html: "<div>unreadable secret</div>", failure: "private reader detail")
        let plan = try AppleNotesImport.prepare(snapshot([input]))
        let encoded = try Document.encode(plan.payload)
        XCTAssertFalse(encoded.contains("unreadable secret"))
        XCTAssertFalse(encoded.contains("private reader detail"))
        XCTAssertTrue(encoded.contains("apple-note-read-failed"))
    }

    func testNonfiniteModificationTimesAreExcludedAndStillRevisionBound() throws {
        for value in [Double.nan, Double.infinity, -Double.infinity] {
            let input = record(modified: value)
            let plan = try AppleNotesImport.prepare(snapshot([input]))
            XCTAssertTrue(try notes(plan).isEmpty)
            XCTAssertTrue((try excluded(plan).first?["reasons"] as? [String] ?? []).contains("apple-note-modification-state-unavailable"))
            XCTAssertNoThrow(try Document.encode(plan.payload))
            XCTAssertNoThrow(try plan.revalidate(snapshot([input])))
            XCTAssertThrowsError(try plan.revalidate(snapshot([record(modified: nil)])))
        }
    }

    func testUnsafeControlsAreVisibleAndLineBreaksTabsRemainExact() throws {
        let inputs = [record(id: "unsafe\u{0}id"), record(title: "Title\u{7}"), record(text: "Text\u{0}"),
                      record(html: "<div>\u{1B}</div>"), record(text: "Text\u{7F}"), record(text: "Text\u{85}"),
                      record(failure: "error\u{9F}")]
        for input in inputs {
            let plan = try AppleNotesImport.prepare(snapshot([input]))
            XCTAssertTrue(try notes(plan).isEmpty)
            XCTAssertTrue((try excluded(plan).first?["reasons"] as? [String] ?? []).contains("apple-note-unsafe-control-characters"))
        }
        let text = "\tfirst\r\nsecond\n"
        let plan = try AppleNotesImport.prepare(snapshot([record(text: text)]))
        XCTAssertEqual(Data(try XCTUnwrap(firstNote(plan)["text"] as? String).utf8), Data(text.utf8))
    }

    func testMissingOrDuplicateIdentityRejectsTheWholeSelection() throws {
        for records in [[record(), record(id: "")], [record(), record()],
                        [record(), record(protected: true, text: nil, html: nil)]] {
            XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot(records)))
        }
    }

    func testOpaqueUnicodeIdentitiesDoNotCollapseAndTextIsNotNormalized() throws {
        let composed = "\u{E9}", decomposed = "e\u{301}"
        let first = record(id: composed, title: decomposed, text: composed, html: "<div>" + decomposed + "</div>")
        let second = record(id: decomposed, title: composed, text: decomposed)
        let plan = try AppleNotesImport.prepare(snapshot([first, second]))
        let entries = try notes(plan)
        XCTAssertEqual(entries.count, 2)
        XCTAssertNotEqual(entries[0]["identity"] as? String, entries[1]["identity"] as? String)
        let byBytes = Dictionary(uniqueKeysWithValues: try entries.map { note in
            (Data(try XCTUnwrap(note["identifier"] as? String).utf8), note)
        })
        let retained = try XCTUnwrap(byBytes[Data(composed.utf8)])
        XCTAssertEqual(Data(try XCTUnwrap(retained["title"] as? String).utf8), Data(decomposed.utf8))
        XCTAssertEqual(Data(try XCTUnwrap(retained["text"] as? String).utf8), Data(composed.utf8))
        let renamed = record(id: composed, title: composed, text: composed, html: "<div>" + decomposed + "</div>")
        XCTAssertThrowsError(try plan.revalidate(snapshot([renamed, second])))
    }

    func testIdentityIncludesAccountAndLengthFramesButNotFolder() throws {
        let original = try AppleNotesImport.prepare(snapshot([record()]))
        let moved = try AppleNotesImport.prepare(snapshot([record()], source: source(folderID: "folder-two")))
        XCTAssertEqual(try firstNote(original)["identity"] as? String, try firstNote(moved)["identity"] as? String)
        XCTAssertNotEqual(try firstNote(original)["revision"] as? String, try firstNote(moved)["revision"] as? String)
        let anotherAccount = try AppleNotesImport.prepare(snapshot([record()], source: source(accountID: "account-two")))
        XCTAssertNotEqual(try firstNote(original)["identity"] as? String, try firstNote(anotherAccount)["identity"] as? String)
        let left = try AppleNotesImport.prepare(snapshot([record(id: "c")], source: source(accountID: "ab")))
        let right = try AppleNotesImport.prepare(snapshot([record(id: "bc")], source: source(accountID: "a")))
        XCTAssertNotEqual(try firstNote(left)["identity"] as? String, try firstNote(right)["identity"] as? String)
        let composed = try AppleNotesImport.prepare(snapshot([record()], source: source(accountID: "\u{E9}")))
        let decomposed = try AppleNotesImport.prepare(snapshot([record()], source: source(accountID: "e\u{301}")))
        XCTAssertNotEqual(try firstNote(composed)["identity"] as? String, try firstNote(decomposed)["identity"] as? String)
    }

    func testEverySourceFieldAndNativeRecordFieldInvalidatesReview() throws {
        let plan = try AppleNotesImport.prepare(snapshot([record()]))
        for selected in [source(accountID: "other"), source(accountTitle: "Renamed account"),
                         source(folderID: "other"), source(folderTitle: "Renamed folder")] {
            let changed = snapshot([record()], source: selected)
            XCTAssertThrowsError(try plan.revalidate(changed))
            XCTAssertNotEqual(plan.snapshotRevision, try AppleNotesImport.prepare(changed).snapshotRevision)
        }
        for input in [record(id: "other"), record(title: "Changed title"), record(protected: nil),
                      record(protected: true, text: nil, html: nil), record(attachments: 1),
                      record(text: "Changed text"), record(html: "<b>Changed HTML only</b>"),
                      record(modified: 1_780_000_000.5), record(failure: "reader failed")] {
            let changed = snapshot([input])
            XCTAssertThrowsError(try plan.revalidate(changed))
            XCTAssertNotEqual(plan.snapshotRevision, try AppleNotesImport.prepare(changed).snapshotRevision)
        }
        XCTAssertThrowsError(try plan.revalidate(snapshot([])))
        XCTAssertThrowsError(try plan.revalidate(snapshot([record(), record(id: "added")])))
    }

    func testExcludedRecordsAndMissingVersusEmptyFieldsAreRevisionBound() throws {
        let first = record(id: "excluded", attachments: 1, text: nil, html: nil, failure: "first failure")
        let plan = try AppleNotesImport.prepare(snapshot([record(), first]))
        for changed in [record(id: "excluded", attachments: 2, text: nil, html: nil, failure: "first failure"),
                        record(id: "excluded", attachments: 1, text: "", html: nil, failure: "first failure"),
                        record(id: "excluded", attachments: 1, text: nil, html: "", failure: "first failure"),
                        record(id: "excluded", attachments: 1, text: nil, html: nil, failure: "second failure"),
                        record(id: "excluded", attachments: 1, text: nil, html: nil, modified: nil, failure: "first failure")] {
            let next = snapshot([record(), changed])
            XCTAssertThrowsError(try plan.revalidate(next))
            XCTAssertNotEqual(plan.snapshotRevision, try AppleNotesImport.prepare(next).snapshotRevision)
        }
        let nilFailure = try AppleNotesImport.prepare(snapshot([record(protected: nil, failure: nil)]))
        let emptyFailure = try AppleNotesImport.prepare(snapshot([record(protected: nil, failure: "")]))
        XCTAssertNotEqual(nilFailure.snapshotRevision, emptyFailure.snapshotRevision)
    }

    func testEnumerationOrderDoesNotChangeEvidenceOrPayload() throws {
        let records = [record(id: "z"), record(id: "a", attachments: 2), record(id: "b")]
        let first = try AppleNotesImport.prepare(snapshot(records))
        let second = try AppleNotesImport.prepare(snapshot(Array(records.reversed())))
        XCTAssertEqual(first.snapshotRevision, second.snapshotRevision)
        XCTAssertEqual(Data(try Document.encode(first.payload).utf8), Data(try Document.encode(second.payload).utf8))
        XCTAssertNoThrow(try first.revalidate(snapshot([records[1], records[2], records[0]])))
    }

    func testSelectedNoteCountAndUTF8MetadataBounds() throws {
        XCTAssertNoThrow(try AppleNotesImport.prepare(snapshot((0..<32).map { record(id: "note-\($0)") })))
        XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot((0..<33).map { record(id: "note-\($0)") })))
        let longID = String(repeating: "a", count: AppleNotesImport.maximumIdentifierBytes)
        let title = String(repeating: "🌼", count: AppleNotesImport.maximumTitleBytes / 4)
        XCTAssertNoThrow(try AppleNotesImport.prepare(snapshot([record(id: longID, title: title)],
            source: source(accountID: longID, accountTitle: title, folderID: longID, folderTitle: title))))
        XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([record(id: longID + "a")])))
        XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([record(title: title + "a")])))
        for selected in [source(accountID: ""), source(folderID: ""), source(accountID: longID + "a"),
                         source(folderID: longID + "a"), source(accountTitle: title + "a"),
                         source(folderTitle: title + "a"), source(accountID: "unsafe\u{0}"),
                         source(folderTitle: "unsafe\u{7F}")] {
            XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([record()], source: selected)))
        }
    }

    func testEachBodyHasAnIndependentOneMiBUTF8Limit() throws {
        let text = String(repeating: "🌼", count: AppleNotesImport.maximumTextBytes / 4)
        XCTAssertEqual(text.utf8.count, AppleNotesImport.maximumTextBytes)
        XCTAssertNoThrow(try AppleNotesImport.prepare(snapshot([record(text: text, html: "")])))
        XCTAssertNoThrow(try AppleNotesImport.prepare(snapshot([record(text: "", html: text)])))
        let ascii = String(repeating: "a", count: AppleNotesImport.maximumTextBytes)
        XCTAssertNoThrow(try AppleNotesImport.prepare(snapshot([record(text: ascii, html: ascii)])))
        for input in [record(text: text + "a"), record(html: text + "a"),
                      record(attachments: 1, text: text + "a"), record(html: text + "a", failure: "unreadable")] {
            XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([input]))) { error in
                XCTAssertTrue(error.localizedDescription.contains("1 MiB"))
            }
        }
    }

    func testAggregateEvidenceLimitIncludesExcludedBodiesAndFailureDetails() throws {
        let text = String(repeating: "a", count: AppleNotesImport.maximumTextBytes)
        let records = (0..<5).map { record(id: "excluded-\($0)", attachments: 1, text: text, html: text) }
        XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot(records))) { error in
            XCTAssertTrue(error.localizedDescription.contains("evidence exceeds 8 MiB"))
        }
        let oversizedFailure = record(failure: String(repeating: "a", count: AppleNotesImport.maximumBytes))
        XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([oversizedFailure])))
    }

    func testFinalPayloadLimitIncludesDuplicatedTextAndJSONEscaping() throws {
        let text = String(repeating: "\\", count: AppleNotesImport.maximumTextBytes)
        // Two records retain roughly 4 MiB of evidence. JSON escaping plus the
        // copied text makes the full proposal exceed 8 MiB; return no prefix.
        XCTAssertThrowsError(try AppleNotesImport.prepare(snapshot([
            record(id: "first", text: text, html: text), record(id: "second", text: text, html: text)
        ]))) { error in
            XCTAssertTrue(error.localizedDescription.contains("proposal exceeds 8 MiB"))
        }
    }

    func testBridgeCommandIsParameterlessAndCannotInjectSelectionOrScript() throws {
        let request = try Request("{\"cmd\":\"macos_apple_notizen_importieren\"}")
        XCTAssertEqual(request.command, .macos_apple_notizen_importieren)
        let extraFields: [[String: Any]] = [["accountID": "account-one"], ["folderID": "folder-one"],
            ["identifier": "note-one"], ["identifiers": ["note-one"]],
            ["script": "Application('Notes').notes()"], ["body": "injected"],
            ["bodyHTML": "<div>injected</div>"], ["plaintext": "injected"]]
        for extra in extraFields {
            var fields = extra; fields["cmd"] = "macos_apple_notizen_importieren"
            XCTAssertThrowsError(try Request(Document.encode(fields)))
        }
    }
}
