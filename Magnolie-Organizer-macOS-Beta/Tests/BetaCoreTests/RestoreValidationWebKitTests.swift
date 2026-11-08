#if os(macOS)
import AppKit
import WebKit
import XCTest
@testable import BetaCore

/// Real projected validator/WK return transport, with synthetic initialization.
/// This does not exercise native selection, epoch transformation or full restore.
@MainActor final class RestoreValidationWebKitTests: XCTestCase, WKScriptMessageHandler {
    private var web: WKWebView!
    private var ready: XCTestExpectation?
    private var transportError: Error?

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        do {
            guard message.frameInfo.isMainFrame, let raw = message.body as? String else { return }
            let request = try Request(raw)
            if request.command == .bereit {
                web.callAsyncJavaScript("window.MacBeta.receive('init', {daten:{termine:[],aufgaben:[],kontakte:[],notizen:[],futureRoot:{keep:'live'},einstellungen:{allgemein:{handbuchHinweisGezeigt:true}}},neu:false,regional:{language:'en',timeZone:'UTC'}}); return true;",
                                        arguments: [:], in: nil, in: .page) { (result: Result<Any, Error>) in
                    if case .failure(let error) = result { self.transportError = error }
                    self.ready?.fulfill(); self.ready = nil
                }
            } else if request.command == .speichern {
                web.callAsyncJavaScript("window.MacBeta.receive('gespeichert', {ok:true,id:id}); return true;",
                                        arguments: ["id": request.fields["id"]!], in: nil, in: .page) { (_: Result<Any, Error>) in }
            }
        } catch { transportError = error; ready?.fulfill(); ready = nil }
    }
    private func javascript(_ source: String, arguments: [String: Any] = [:]) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            var completed = false
            let timeout = DispatchWorkItem {
                guard !completed else { return }; completed = true
                continuation.resume(throwing: BetaError("Restore validation JavaScript exceeded 10 seconds."))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: timeout)
            web.callAsyncJavaScript(source, arguments: arguments, in: nil, in: .page) { (result: Result<Any, Error>) in
                guard !completed else { return }; completed = true; timeout.cancel()
                continuation.resume(with: result)
            }
        }
    }
    private func productionValidationBody() throws -> String {
        let package = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let source = try String(contentsOf: package.appendingPathComponent("Sources/MacBeta/main.swift"), encoding: .utf8)
        let sites = source.components(separatedBy: "web.callAsyncJavaScript(\"").dropFirst().filter { $0.prefix(200).contains("window.MacBeta.validateRestore(text)") }
        XCTAssertEqual(sites.count, 1, "Bind this regression to the one production restore validation call")
        let site = try XCTUnwrap(sites.first)
        let body = String(site.prefix(while: { $0 != "\"" }))
        XCTAssertEqual(body, "return window.MacBeta.validateRestore(text);")
        XCTAssertTrue(site.prefix(400).contains("{ (result: Result<Any, Error>) in"), "Production must select the Any-result completion overload")
        return body // Execute the actual production literal, not a test-only equivalent.
    }
    func testProductionBodyReturnsValidatorResultWithoutReplacingBook() async throws {
        let body = try productionValidationBody()
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_UI_PATH"] else { throw XCTSkip("Supply generated UI on a real Mac.") }
        _ = NSApplication.shared
        let configuration = WKWebViewConfiguration(); configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(self, name: "restoreValidationTest")
        configuration.userContentController.addUserScript(WKUserScript(source: "window.__MAGNOLIE_BRUECKE__='restoreValidationTest';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 850), configuration: configuration)
        defer { web.stopLoading(); configuration.userContentController.removeScriptMessageHandler(forName: "restoreValidationTest"); web = nil }
        let initialized = expectation(description: "Actual projection initialized")
        ready = initialized
        let root = URL(fileURLWithPath: path)
        web.loadFileURL(root.appendingPathComponent("web/index.html"), allowingReadAccessTo: root)
        await fulfillment(of: [initialized], timeout: 20)
        if let error = transportError { throw error }
        let beforeValue = try await javascript("return JSON.stringify(window.OrganizerTest.daten());")
        let before = try XCTUnwrap(beforeValue as? String)
        let candidateValue = try await javascript("const candidate=JSON.parse(JSON.stringify(window.OrganizerTest.daten())); candidate.futureRoot.keep='candidate'; return JSON.stringify(candidate);")
        let candidate = try XCTUnwrap(candidateValue as? String)
        let accepted = try await javascript(body, arguments: ["text": candidate])
        XCTAssertEqual(accepted as? Bool, true)
        let afterValidation = try await javascript("return JSON.stringify(window.OrganizerTest.daten());")
        XCTAssertEqual(afterValidation as? String, before)
        // Validation fences further attempts until the real native failure route
        // resets restorePending. Neither route installs the candidate document.
        do { _ = try await javascript(body, arguments: ["text": candidate]); XCTFail("A pending validation accepted another restore") }
        catch { XCTAssertEqual((error as NSError).domain, WKError.errorDomain) }
        _ = try await javascript("window.MacBeta.receive('failure',{cmd:'sicherung_wiederherstellen',ok:false,fehler:'Synthetic validation cancellation'}); return true;")
        do { _ = try await javascript(body, arguments: ["text": "{"]); XCTFail("Malformed JSON was accepted") }
        catch { XCTAssertEqual((error as NSError).domain, WKError.errorDomain) }
        let afterInvalid = try await javascript("return JSON.stringify(window.OrganizerTest.daten());")
        XCTAssertEqual(afterInvalid as? String, before)
        let retried = try await javascript(body, arguments: ["text": candidate])
        XCTAssertEqual(retried as? Bool, true, "Rejected invalid JSON must not leave restorePending set")
        _ = try await javascript("window.MacBeta.receive('failure',{cmd:'sicherung_wiederherstellen',ok:false,fehler:'Synthetic validation cancellation'}); return true;")
        let afterReset = try await javascript("return JSON.stringify(window.OrganizerTest.daten());")
        XCTAssertEqual(afterReset as? String, before)
    }
}
#endif
