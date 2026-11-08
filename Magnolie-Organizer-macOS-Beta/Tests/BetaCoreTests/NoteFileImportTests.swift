import Foundation
import XCTest
import CryptoKit
@testable import BetaCore

final class NoteFileImportTests: XCTestCase {
    typealias Import = NoteFileImport
    func testNativePickerCommandHasNoWebSuppliedPathsOrBodies() throws {
        XCTAssertNoThrow(try Request(#"{"cmd":"notiz_dateien_importieren"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"notiz_dateien_importieren","pfad":"/not-selected.txt"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"notiz_dateien_importieren","daten":[]}"#))
    }
    func testLiteralTextAndMarkdownRetainOriginalContentWithoutHTMLExecution() throws {
        let text = "<script>alert('not executed')</script>\nEmoji 🌼\tText\r\n"
        let markdown = "# Heading\n![drawing](https://example.invalid/remote.png)\n- [ ] task"
        let proposal = try Import.prepare([.init(name: "note.txt", data: Data(text.utf8), declaredMIME: "text/plain; charset=utf-8"),
                                           .init(name: "source.md", data: Data(markdown.utf8), declaredMIME: "text/markdown")])
        XCTAssertEqual(proposal.items[0].noteFields["text"] as? String, text)
        XCTAssertNil(proposal.items[0].noteFields["html"])
        XCTAssertEqual(proposal.items[1].noteFields["text"] as? String, markdown)
        XCTAssertFalse(proposal.items[1].warnings.isEmpty)
        XCTAssertEqual(proposal.items[0].sourceSHA256, SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined())
        XCTAssertEqual(Set(proposal.items[0].noteFields.keys), ["titel", "text", "anhaenge"])
    }
    func testAttachmentBytesUseExistingCanonicalModelExactly() throws {
        let png = Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRZkAAAAASUVORK5CYII=")!
        let pdf = Data("%PDF-1.4\n% Synthetic original document\n%%EOF\n".utf8)
        for (name, data, mime, kind) in [("drawing.png", png, "image/png", "image"), ("scan.pdf", pdf, "application/pdf", "pdf")] {
            let item = try Import.prepare([.init(name: name, data: data, declaredMIME: mime)]).items[0]
            let attachments = try XCTUnwrap(item.noteFields["anhaenge"] as? [[String: Any]])
            let attachment = try XCTUnwrap(attachments.first)
            XCTAssertEqual(Set(attachment.keys), ["id", "name", "art", "daten"])
            XCTAssertEqual(attachment["art"] as? String, kind)
            XCTAssertEqual(attachment["name"] as? String, name)
            XCTAssertEqual(attachment["daten"] as? String, "data:\(mime);base64," + data.base64EncodedString())
            XCTAssertFalse(item.warnings.isEmpty)
        }
    }
    func testUnsupportedMismatchedAndOversizedInputsFailAsWholeProposal() throws {
        let valid = Import.Input(name: "good.txt", data: Data("retained".utf8))
        for invalid in [Import.Input(name: "fake.pdf", data: Data("not PDF".utf8)),
                        .init(name: "disguised.txt", data: Data("%PDF-1.4".utf8)),
                        .init(name: "wrong.pdf", data: Data("%PDF-1.4".utf8), declaredMIME: "image/png"),
                        .init(name: "unsafe.txt", data: Data([0x61, 0, 0x62])),
                        .init(name: "invalid.txt", data: Data([0xff, 0xfe])),
                        .init(name: "../escape.txt", data: Data("text".utf8)),
                        .init(name: "file.html", data: Data("<p>not supported</p>".utf8)),
                        .init(name: "large.txt", data: Data(repeating: 65, count: Import.maximumTextBytes + 1))] {
            XCTAssertThrowsError(try Import.prepare([valid, invalid]), invalid.name)
        }
        XCTAssertThrowsError(try Import.prepare([]))
        XCTAssertThrowsError(try Import.prepare(Array(repeating: valid, count: Import.maximumFiles + 1)))
        let large = Import.Input(name: "large.pdf", data: Data("%PDF-".utf8) + Data(repeating: 65, count: Import.maximumBytes - 5))
        XCTAssertThrowsError(try Import.prepare([large, valid]))
        XCTAssertEqual(try Import.prepare([large]).items.count, 1)
    }
    func testSelectedFileRejectsSymlinkAndChangedSource() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("note.txt")
        try Data("original".utf8).write(to: source)
        let input = try Import.readSelected(source)
        let item = try Import.prepare([input]).items[0]
        XCTAssertNoThrow(try Import.revalidate(source, sourceSHA256: item.sourceSHA256))
        let link = root.appendingPathComponent("link.txt")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: source)
        XCTAssertThrowsError(try Import.readSelected(link))
        XCTAssertThrowsError(try Import.readSelected(root))
        try Data("changed".utf8).write(to: source)
        XCTAssertThrowsError(try Import.revalidate(source, sourceSHA256: item.sourceSHA256))
    }
}
