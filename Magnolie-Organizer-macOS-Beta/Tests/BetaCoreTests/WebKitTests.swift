#if os(macOS)
import AppKit
import WebKit
import XCTest

/// Real WKWebView, synthetic transport/profile. This is NOT the production Host's
/// dialogs, permissions, APFS lifecycle or a complete native acceptance test.
@MainActor final class WebKitTests: XCTestCase, WKScriptMessageHandler {
    private var ready: XCTestExpectation?

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let raw = message.body as? String,
              let bytes = raw.data(using: .utf8),
              let request = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { return }
        if request["cmd"] as? String == "bereit" { ready?.fulfill(); ready = nil }
    }

    func testCurrentProjectionInRealWebKit() async throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_UI_PATH"] else {
            throw XCTSkip("Supply MACOS_BETA_UI_PATH with the current generated projection on a real Mac.")
        }
        _ = NSApplication.shared
        let root = URL(fileURLWithPath: path)
        let entry = root.appendingPathComponent("web/index.html")
        XCTAssertTrue(FileManager.default.fileExists(atPath: entry.path))
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(self, name: "nativeBetaTest")
        configuration.userContentController.addUserScript(WKUserScript(
            source: "window.__MAGNOLIE_BRUECKE__ = 'nativeBetaTest';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 850), configuration: configuration)
        let loaded = expectation(description: "Current local entry reaches the actual WK bridge")
        ready = loaded
        defer { web.stopLoading(); configuration.userContentController.removeScriptMessageHandler(forName: "nativeBetaTest") }
        web.loadFileURL(entry, allowingReadAccessTo: root)
        await fulfillment(of: [loaded], timeout: 20)
        let title = try await web.evaluateJavaScript("document.title")
        XCTAssertEqual(title as? String, "Magnolie Organizer macOS Beta")
        _ = try await web.evaluateJavaScript("""
            window.MacBeta.receive('init', {daten: {termine: [], aufgaben: [], kontakte: [], notizen: [],
              einstellungen: {allgemein: {handbuchHinweisGezeigt: true}}}, neu: false,
              regional: {language: 'de', timeZone: 'Europe/Berlin'}});
            window.OrganizerTest.baueEinstellungen();
            document.getElementById('einst-tab-sicherheit').click();
            """)
        let buttons = try await web.evaluateJavaScript("Array.from(document.querySelectorAll('#einst-seite-sicherheit button')).map(b => b.textContent)")
        XCTAssertTrue((buttons as? [String] ?? []).contains("Sicherung wiederherstellen …"))
        let fonts = try await web.callAsyncJavaScript("await document.fonts.ready; return document.fonts.status;", arguments: [:], in: nil, in: .page)
        XCTAssertEqual(fonts as? String, "loaded")
    }
}
#endif
