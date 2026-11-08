#if os(macOS)
import AppKit
import WebKit
import XCTest
@testable import BetaCore

/// Actual canonical UI and real temporary native persistence, not production
/// NSOpenPanel automation or a user-device transfer acceptance test.
@MainActor final class NoteFileImportWebKitTests: XCTestCase, WKScriptMessageHandler {
    private var store: AtomicStore!
    private var web: WKWebView!
    private var firstSave: XCTestExpectation?
    private var checkpoints = 0
    private let seed = #"{"termine":[],"aufgaben":[],"kontakte":[],"notizen":[],"futureRoot":{"keep":"opaque"},"einstellungen":{"allgemein":{"handbuchHinweisGezeigt":true}}}"#
    private func send(_ method: String, _ payload: [String: Any]) {
        web.callAsyncJavaScript("window.MacBeta.receive(method,payload)", arguments: ["method": method, "payload": payload], in: nil, in: .page) { (_: Result<Any, Error>) in }
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        do {
            guard let raw = message.body as? String else { return }
            let request = try Request(raw)
            switch request.command {
            case .bereit:
                let text = try store.load() ?? seed
                send("init", ["daten": try Document.object(text), "neu": false, "regional": ["language": "en", "timeZone": "UTC"]])
            case .speichern:
                try store.commit(request.text("text"))
                send("gespeichert", ["id": request.fields["id"]!, "ok": true])
                firstSave?.fulfill(); firstSave = nil
            case .mutations_snapshot:
                _ = try store.checkpoint(); checkpoints += 1
                send("mutationsSnapshot", ["token": request.text("token"), "ok": true])
            default: break
            }
        } catch { XCTFail("Native note-import transport: \(error)") }
    }
    private func javascript(_ source: String, arguments: [String: Any] = [:]) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            var finished = false
            let timeout = DispatchWorkItem {
                guard !finished else { return }; finished = true
                continuation.resume(throwing: BetaError("Canonical note import/save JavaScript exceeded 45 seconds."))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: timeout)
            web.callAsyncJavaScript(source, arguments: arguments, in: nil, in: .page) { (result: Result<Any, Error>) in
                guard !finished else { return }; finished = true; timeout.cancel()
                continuation.resume(with: result)
            }
        }
    }
    func testPreparedFilesThroughCanonicalRecoverySaveAndReopen() async throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_UI_PATH"] else { throw XCTSkip("Supply generated UI on a Mac.") }
        _ = NSApplication.shared
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        store = try AtomicStore(directory: directory)
        let configuration = WKWebViewConfiguration(); configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(self, name: "noteImportTest")
        configuration.userContentController.addUserScript(WKUserScript(source: "window.__MAGNOLIE_BRUECKE__='noteImportTest';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 850), configuration: configuration)
        defer {
            web.stopLoading(); configuration.userContentController.removeScriptMessageHandler(forName: "noteImportTest")
            web = nil; store = nil; try? FileManager.default.removeItem(at: directory)
        }
        let ready = expectation(description: "Canonical initialization durably saved")
        firstSave = ready
        let root = URL(fileURLWithPath: path)
        web.loadFileURL(root.appendingPathComponent("web/index.html"), allowingReadAccessTo: root)
        await fulfillment(of: [ready], timeout: 30)
        let text = " \n# Literal <script>not code</script> 🌼\n "
        let pdf = Data("%PDF-1.4\n% Synthetic original\n%%EOF".utf8)
        let proposal = try NoteFileImport.prepare([.init(name: "source.md", data: Data(text.utf8)), .init(name: "drawing.pdf", data: pdf)])
        let items: [[String: Any]] = proposal.items.map { ["fields": $0.noteFields, "sourceSHA256": $0.sourceSHA256, "sourceName": $0.sourceName, "sourceBytes": $0.sourceBytes, "warnings": $0.warnings] }
        let value = try await javascript("return await window.App.macOSBetaImportNoteFiles(payload);", arguments: ["payload": ["items": items]])
        let response = try XCTUnwrap(value as? [String: Any])
        XCTAssertEqual(response["ok"] as? Bool, true); XCTAssertEqual(response["count"] as? Int, 2)
        XCTAssertEqual(checkpoints, 1)
        let saved = try XCTUnwrap(store.load())
        let document = try Document.object(saved)
        let notes = try XCTUnwrap(document["notizen"] as? [[String: Any]])
        XCTAssertEqual(notes.count, 2); XCTAssertEqual(notes[0]["text"] as? String, text)
        let attachment = try XCTUnwrap((notes[1]["anhaenge"] as? [[String: Any]])?.first)
        XCTAssertEqual(attachment["daten"] as? String, "data:application/pdf;base64," + pdf.base64EncodedString())
        XCTAssertEqual((document["futureRoot"] as? [String: Any])?["keep"] as? String, "opaque")
        _ = try await javascript("window.MacBeta.receive('init', {daten: document, neu:false, regional:{language:'en',timeZone:'UTC'}}); return window.OrganizerTest.daten().notizen.length;", arguments: ["document": document])
        let reopened = try await javascript("return JSON.stringify(window.OrganizerTest.daten().notizen);")
        XCTAssertEqual(try Document.encode(JSONSerialization.jsonObject(with: Data((reopened as! String).utf8))), try Document.encode(notes))
    }
}
#endif
