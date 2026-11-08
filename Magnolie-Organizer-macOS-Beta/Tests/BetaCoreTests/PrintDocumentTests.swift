import XCTest
@testable import BetaCore

final class PrintDocumentTests: XCTestCase {
    func testImmutableSnapshotPolicyAndUtf8Boundary() throws {
        let page = try PrintDocument.isolatedHTML("<h1>Report</h1><script>forbidden()</script>")
        XCTAssertTrue(page.hasPrefix("<!DOCTYPE html><html><head><meta http-equiv=\"Content-Security-Policy\""))
        let full = try PrintDocument.isolatedHTML("<!doctype html><html><head><title>Print</title></head><body>Record</body></html>")
        XCTAssertTrue(full.hasPrefix("<!doctype html><meta http-equiv="))
        XCTAssertLessThan(try XCTUnwrap(full.range(of: "script-src")).lowerBound, try XCTUnwrap(full.range(of: "<title>")).lowerBound)
        for directive in ["default-src 'none'", "script-src 'none'", "frame-src 'none'", "connect-src 'none'", "base-uri 'none'", "form-action 'none'"] {
            XCTAssertTrue(page.contains(directive))
        }
        XCTAssertThrowsError(try PrintDocument.isolatedHTML(""))
        XCTAssertNoThrow(try PrintDocument.isolatedHTML(String(repeating: "é", count: 375_000)))
        XCTAssertThrowsError(try PrintDocument.isolatedHTML(String(repeating: "é", count: 375_001)))
    }
    func testTypedPrintRequestOptionalCorrelationAndUnknownFields() throws {
        XCTAssertEqual(try Request(#"{"cmd":"drucken","html":"<p>Snapshot</p>","requestId":"print-1"}"#).command, .drucken)
        XCTAssertNoThrow(try Request(#"{"cmd":"drucken","html":"<p>Snapshot</p>"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"drucken","html":42}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"drucken","html":"<p>Snapshot</p>","path":"/private/profile"}"#))
    }
}

#if os(macOS)
import AppKit
import WebKit
import PDFKit
import Network

private final class PrintConnectionCount: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    func record() { lock.lock(); defer { lock.unlock() }; count += 1 }
    func value() -> Int { lock.lock(); defer { lock.unlock() }; return count }
}

private final class PrintListenerReady: @unchecked Sendable {
    private let lock = NSLock()
    private var pending: CheckedContinuation<Void, Error>?
    init(_ continuation: CheckedContinuation<Void, Error>) { pending = continuation }
    @discardableResult func finish(_ error: Error? = nil) -> Bool {
        lock.lock(); let continuation = pending; pending = nil; lock.unlock()
        guard let continuation else { return false }
        if let error { continuation.resume(throwing: error) } else { continuation.resume() }
        return true
    }
}

final class NativePrintTests: XCTestCase {
    @MainActor func testIsolatedRendererAndRealAppKitPdfOutput() async throws {
        guard let fixture = ProcessInfo.processInfo.environment["MACOS_BETA_EDITOR_FIXTURES"] else {
            throw XCTSkip("Actual shared print fixture is supplied by tools/check_editor.py on the Mac runner.")
        }
        let records = try Document.object(String(contentsOfFile: fixture, encoding: .utf8))
        let canonical = try XCTUnwrap(records["printHTML"] as? String)
        _ = NSApplication.shared
        let listener = try NWListener(using: .tcp, on: .any)
        let connections = PrintConnectionCount()
        listener.newConnectionHandler = { connection in
            connections.record(); connection.cancel()
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let ready = PrintListenerReady(continuation)
            listener.stateUpdateHandler = { state in
                switch state {
                case .ready: ready.finish()
                case .failed(let error): ready.finish(error)
                default: break
                }
            }
            listener.start(queue: DispatchQueue(label: "magnolie-print-test-listener"))
            DispatchQueue.global().asyncAfter(deadline: .now() + 5) {
                if ready.finish(BetaError("Native print test listener did not become ready.")) { listener.cancel() }
            }
        }
        defer { listener.cancel() }
        let port = try XCTUnwrap(listener.port).rawValue
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let local = directory.appendingPathComponent("private-test.html")
        try "LOCAL_FILE_MUST_NOT_RENDER".write(to: local, atomically: true, encoding: .utf8)
        let renderer = PrintRenderer()
        XCTAssertFalse(renderer.webView.configuration.websiteDataStore.isPersistent)
        XCTAssertFalse(renderer.webView.configuration.defaultWebpagePreferences.allowsContentJavaScript)
        XCTAssertTrue(renderer.webView.configuration.userContentController.userScripts.isEmpty)
        let probes = """
        <script>document.body.append('SCRIPT_MUST_NOT_RUN'); window.printProbe = true;</script>
        <img id="inline" width="24" height="24" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6WQAAAAASUVORK5CYII=">
        <img id="remote" src="http://127.0.0.1:\(port)/must-not-request.png">
        <iframe src="\(local.absoluteString)"></iframe>
        """
        let html = canonical.replacingOccurrences(of: "</body>", with: probes + "</body>")
        try await renderer.load(html)
        let mode = try await renderer.webView.evaluateJavaScript("document.compatMode")
        XCTAssertEqual(mode as? String, "CSS1Compat", "The actual canonical print page must retain standards layout")
        let image = try await renderer.webView.evaluateJavaScript("const image=document.getElementById('inline'); [image.naturalWidth,image.getBoundingClientRect().width,image.getBoundingClientRect().height]")
        XCTAssertEqual(image as? [Int], [1,24,24], "Embedded image and its print geometry must survive isolation")
        try await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(connections.value(), 0, "Printing must not fetch even a reachable loopback image")
        let destination = directory.appendingPathComponent("actual-appkit-output.pdf")
        let info = try XCTUnwrap(NSPrintInfo.shared.copy() as? NSPrintInfo)
        info.paperSize = NSSize(width: 595.2756, height: 841.8898)
        info.jobDisposition = .save
        info.dictionary()[NSPrintInfo.AttributeKey.jobSavingURL] = destination
        let operation = renderer.webView.printOperation(with: info)
        operation.showsPrintPanel = false
        operation.showsProgressPanel = false
        XCTAssertTrue(operation.run(), "Exercise the actual AppKit print-to-PDF engine")
        let bytes = try Data(contentsOf: destination)
        XCTAssertTrue(bytes.starts(with: Data("%PDF-".utf8)))
        let pdf = try XCTUnwrap(PDFDocument(data: bytes))
        XCTAssertEqual(pdf.pageCount, 1)
        let bounds = try XCTUnwrap(pdf.page(at: 0)).bounds(for: .mediaBox)
        XCTAssertEqual(bounds.width, 595.2756, accuracy: 1)
        XCTAssertEqual(bounds.height, 841.8898, accuracy: 1)
        let text = pdf.string ?? ""
        XCTAssertTrue(text.contains("PrintProof"))
        XCTAssertTrue(text.contains("PDF evidence 2.0.30"))
        XCTAssertFalse(text.contains("SCRIPT_MUST_NOT_RUN"))
        XCTAssertFalse(text.contains("LOCAL_FILE_MUST_NOT_RENDER"))
        // Saving a PDF verifies the renderer/print engine, not manual OS print-panel acceptance.
    }
}
#endif
