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
        // Feed real canonical normalizer results into the production native policy,
        // then commit/reopen actual private files. No strict DAV snapshot is involved.
        var vectors = OrdinarySaveEpochPolicyTests.vectors().map { Optional($0) }
        vectors.append(nil) // Truly absent profile, distinct from a loaded legacy book.
        for original in vectors {
            let originalText = try original.map(Document.encode)
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: directory) }
            var store: AtomicStore? = try AtomicStore(directory: directory)
            XCTAssertNil(try store!.load())
            if let originalText { try store!.commit(originalText) }
            store = nil
            store = try AtomicStore(directory: directory)
            let actuallyLoaded = try store!.load()
            XCTAssertEqual(actuallyLoaded, originalText)
            let policy = try OrdinarySaveEpochPolicy(loadedPlain: actuallyLoaded)
            // The projected loss guard deliberately rejects object-valued epoch
            // leaves when the desktop normalizer would replace them with strings.
            // Exercise that rejection directly; never pre-normalize away the object.
            let meta = original?["syncMetadaten"] as? [String: Any]
            let epochLeaves = [original?["syncEpoch"], meta?["syncEpoch"]]
            let expectsDroppedObject = epochLeaves.contains { value in
                guard let value else { return false }
                return value is [String: Any] || value is [Any]
            }
            let normalizationBody = "const book=window.OrganizerTest.normalisiere(JSON.parse(text)); book.futureRoot={keep:7,edited:true}; return JSON.stringify(book);"
            if expectsDroppedObject {
                do {
                    _ = try await javascript(normalizationBody, arguments: ["text": originalText ?? "{}"])
                    XCTFail("Object-valued epoch fixture bypassed the projected dropped-object guard")
                } catch {
                    let error = error as NSError
                    XCTAssertEqual(error.domain, WKError.errorDomain)
                    XCTAssertEqual(error.userInfo["WKJavaScriptExceptionMessage"] as? String, "Error: macOS Beta refused a dropped object.")
                }
                let liveAfterRejection = try await javascript("return JSON.stringify(window.OrganizerTest.daten());")
                XCTAssertEqual(liveAfterRejection as? String, before)
                XCTAssertEqual(try String(contentsOf: store!.file, encoding: .utf8), originalText)
                store = nil
                continue
            }
            let normalizedValue = try await javascript(normalizationBody, arguments: ["text": originalText ?? "{}"])
            let normalized = try XCTUnwrap(normalizedValue as? String)
            let actual = try policy.prepare(candidate: normalized)
            try store!.commit(actual)
            store = nil
            var reopened: AtomicStore? = try AtomicStore(directory: directory)
            XCTAssertEqual(try reopened!.load(), actual)
            reopened = nil
            let saved = try Document.plain(actual)
            XCTAssertEqual(try OrdinarySaveEpochPolicyTests.slotBytes(saved), try OrdinarySaveEpochPolicyTests.slotBytes(original ?? [:]))
            XCTAssertEqual((saved["futureRoot"] as? [String: Any])?["edited"] as? Bool, true)
            XCTAssertEqual(try policy.prepare(candidate: actual), actual)
            if case .protectedEpoch(let epoch) = policy.classification { XCTAssertEqual(try DAVBookRestore.persistedEpoch(saved), epoch) }
            else { XCTAssertThrowsError(try DAVBookRestore.persistedEpoch(saved)) }
        }
        // V1 unlock returns a V2 encryption session. Saving must not attempt to
        // decrypt the old on-disk V1 bytes through that new session.
        let fixtureURL = try XCTUnwrap(Bundle.module.url(forResource: "desktop-envelopes", withExtension: "json", subdirectory: "Fixtures"))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as? [String: Any])
        let v1 = try XCTUnwrap(fixture["v1"] as? String)
        let password = try XCTUnwrap(fixture["password"] as? String)
        let encryptedDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: encryptedDirectory) }
        var encryptedStore: AtomicStore? = try AtomicStore(directory: encryptedDirectory)
        XCTAssertNil(try encryptedStore!.load()); try encryptedStore!.commit(v1); encryptedStore = nil
        encryptedStore = try AtomicStore(directory: encryptedDirectory)
        let actualV1 = try XCTUnwrap(encryptedStore!.load())
        let (decoded, encryption) = try Encryption.unlock(actualV1, password: password)
        let unlockedPolicy = try OrdinarySaveEpochPolicy(loadedPlain: decoded)
        let normalizedUnlockedValue = try await javascript("return JSON.stringify(window.OrganizerTest.normalisiere(JSON.parse(text)));", arguments: ["text": decoded])
        let normalizedUnlocked = try XCTUnwrap(normalizedUnlockedValue as? String)
        let savedUnlocked = try unlockedPolicy.prepare(candidate: normalizedUnlocked)
        try encryptedStore!.commit(encryption.encrypt(savedUnlocked)); encryptedStore = nil
        var reopenedEncrypted: AtomicStore? = try AtomicStore(directory: encryptedDirectory)
        let reopenedEnvelope = try XCTUnwrap(reopenedEncrypted!.load()); reopenedEncrypted = nil
        XCTAssertEqual(try Encryption.unlock(reopenedEnvelope, password: password).0, savedUnlocked)
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
