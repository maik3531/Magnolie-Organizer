import Foundation
import XCTest
@testable import BetaCore

final class ManualContentTests: XCTestCase {
    func testManualPathsAndCommandAreNarrow() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data("<html></html>".utf8).write(to: root.appendingPathComponent("index.html"))
        let manual = try ManualContent(root: root)
        XCTAssertTrue(manual.permits(try manual.entry(fragment: "calendar")))
        for value in ["../organizer.json", "%2e%2e", "javascript:alert(1)", "de?x=y"] { XCTAssertThrowsError(try manual.entry(fragment: value)) }
        XCTAssertFalse(manual.permits(root.appendingPathComponent("../organizer.json")))
        XCTAssertFalse(manual.permits(URL(string: "https://example.invalid/index.html")!))
        XCTAssertFalse(manual.permits(URL(string: try manual.entry().absoluteString + "?lang=../de")!))
        XCTAssertTrue(ManualContent.external(URL(string: "https://example.invalid/help")!, userInitiated: true))
        XCTAssertFalse(ManualContent.external(URL(string: "https://example.invalid/help")!, userInitiated: false))
        XCTAssertFalse(ManualContent.external(URL(string: "file:///etc/passwd")!, userInitiated: true))
        XCTAssertNoThrow(try Request(#"{"cmd":"handbuch_oeffnen"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"handbuch_oeffnen","pfad":"/etc/passwd"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"handbuch_oeffnen","sprache":"de;alert(1)"}"#))
    }
}

#if os(macOS)
import AppKit
import WebKit

@MainActor final class ManualWebKitTests: XCTestCase {
    func testBundledCanonicalManualLoadsSearchesAndHasNoNativeBridge() async throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_UI_PATH"] else { throw XCTSkip("Supply the generated bundled UI on a real Mac.") }
        _ = NSApplication.shared
        let content = try ManualContent(root: URL(fileURLWithPath: path).appendingPathComponent("manual"))
        var external: [URL] = []
        let browser = try ManualBrowser(content: content, language: "en", external: { external.append($0) })
        XCTAssertThrowsError(try ManualBrowser(content: content, language: "../de", external: { _ in }))
        let web = browser.webView
        defer { web.stopLoading() }
        XCTAssertFalse(web.configuration.websiteDataStore.isPersistent)
        try await browser.load()
        var loaded = false
        for _ in 0..<200 {
            if let ready = try? await web.evaluateJavaScript("!!document.getElementById('knopf-suche') && !!window.HANDBUCH_SEITEN && document.readyState === 'complete'"), ready as? Bool == true { loaded = true; break }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        XCTAssertTrue(loaded, "Actual bundled handbook scripts must initialize")
        guard loaded else { return }
        let language = try await web.evaluateJavaScript("document.documentElement.lang")
        XCTAssertEqual(language as? String, "en")
        let bridges = try await web.evaluateJavaScript("typeof window.MacBeta + ':' + typeof window.TabletNative + ':' + typeof window.webkit?.messageHandlers?.bruecke")
        XCTAssertEqual(bridges as? String, "undefined:undefined:undefined")
        let found = try await web.evaluateJavaScript("""
            document.getElementById('knopf-suche').click();
            const field = document.getElementById('handbuch-suchfeld');
            field.value = 'calendar'; field.dispatchEvent(new Event('input', {bubbles:true}));
            document.querySelectorAll('.handbuch-suchtreffer').length;
            """)
        XCTAssertGreaterThan(found as? Int ?? 0, 0)
        let selected = try await web.evaluateJavaScript("document.querySelector('.handbuch-suchtreffer').click(); document.getElementById('handbuch-suche').hidden")
        XCTAssertEqual(selected as? Bool, true)
        XCTAssertTrue(content.permits(try XCTUnwrap(web.url)))
        // Use the explicit completion overload, as in WebKitTests: some SDKs
        // otherwise select the default-handler Void method even with try/await.
        let blocked: Any = try await withCheckedThrowingContinuation { continuation in
            web.callAsyncJavaScript("""
                return await new Promise(resolve => {
                  const script = document.createElement('script');
                  script.src = 'https://example.invalid/forbidden-native-bridge.js';
                  script.onload = () => resolve(false); script.onerror = () => resolve(true);
                  document.head.append(script); setTimeout(() => resolve(false), 3000);
                });
                """, arguments: [:], in: nil, in: .page) { result in
                    continuation.resume(with: result)
                }
        }
        XCTAssertEqual(blocked as? Bool, true, "External script must be blocked")
        _ = try await web.evaluateJavaScript("const link = document.createElement('a'); link.href='https://example.invalid/programmatic'; document.body.append(link); link.click();")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertTrue(external.isEmpty, "No programmatic external browsing")
    }
}
#endif
