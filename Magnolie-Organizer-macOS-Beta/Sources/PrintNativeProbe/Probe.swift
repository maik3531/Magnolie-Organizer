import Foundation
#if os(macOS)
import AppKit
import WebKit
import Network
import BetaCore

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

/// Test support only; not copied into the application bundle. XCTest owns the
/// exact child process and enforces a 30-second external deadline including cleanup.
@MainActor private final class Probe: NSObject, NSApplicationDelegate {
    private var renderer: PrintRenderer?
    private var operation: NSPrintOperation?
    private var parent: NSWindow?
    private var listener: NWListener?
    private let connections = PrintConnectionCount()
    private var proof: [String: Any] = [:]
    private var phase = "starting"
    private let fixture: URL
    private let directory: URL
    init(fixture: URL, directory: URL) { self.fixture = fixture; self.directory = directory }
    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { do { try await prepare() } catch { finish(false) } }
    }
    private func mark(_ value: String) {
        phase = value
        proof["ok"] = false; proof["phase"] = value; proof["paperOutputConfirmed"] = false
        if let data = try? JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys]) {
            try? data.write(to: directory.appendingPathComponent("proof.json"), options: .atomic)
        }
    }
    private func prepare() async throws {
        mark("fixture")
        let records = try Document.object(String(contentsOf: fixture, encoding: .utf8))
        guard let canonical = records["printHTML"] as? String else { throw BetaError("Missing canonical print fixture.") }
        let server = try NWListener(using: .tcp, on: .any)
        listener = server
        server.newConnectionHandler = { [connections] connection in connections.record(); connection.cancel() }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let ready = PrintListenerReady(continuation)
            server.stateUpdateHandler = { state in
                switch state {
                case .ready: ready.finish()
                case .failed(let error): ready.finish(error)
                default: break
                }
            }
            server.start(queue: DispatchQueue(label: "magnolie-print-probe-listener"))
            DispatchQueue.global().asyncAfter(deadline: .now() + 5) {
                if ready.finish(BetaError("Listener readiness deadline.")) { server.cancel() }
            }
        }
        guard let port = server.port?.rawValue else { throw BetaError("Listener unavailable.") }
        let local = directory.appendingPathComponent("private-test.html")
        try "LOCAL_FILE_MUST_NOT_RENDER".write(to: local, atomically: true, encoding: .utf8)
        let page = PrintRenderer()
        renderer = page
        proof["ephemeral"] = !page.webView.configuration.websiteDataStore.isPersistent
        proof["contentJavaScriptDisabled"] = !page.webView.configuration.defaultWebpagePreferences.allowsContentJavaScript
        proof["noInjectedScripts"] = page.webView.configuration.userContentController.userScripts.isEmpty
        let probes = """
        <script>document.body.append('SCRIPT_MUST_NOT_RUN'); window.printProbe = true;</script>
        <img id="inline" width="24" height="24" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6WQAAAAASUVORK5CYII=">
        <img id="remote" src="http://127.0.0.1:\(port)/must-not-request.png">
        <iframe src="\(local.absoluteString)"></iframe>
        """
        mark("loading")
        try await page.load(canonical.replacingOccurrences(of: "</body>", with: probes + "</body>"))
        mark("layout")
        proof["compatMode"] = try await page.webView.evaluateJavaScript("document.compatMode")
        proof["imageGeometry"] = try await page.webView.evaluateJavaScript("const image=document.getElementById('inline'); [image.naturalWidth,image.getBoundingClientRect().width,image.getBoundingClientRect().height]")
        proof["fontStatus"] = try await page.webView.evaluateJavaScript("document.fonts.status")
        proof["scriptAbsent"] = try await page.webView.evaluateJavaScript("typeof window.printProbe === 'undefined'")
        proof["bridgeAbsent"] = try await page.webView.evaluateJavaScript("typeof window.MacBeta === 'undefined' && typeof window.webkit?.messageHandlers?.bruecke === 'undefined'")
        try await Task.sleep(nanoseconds: 200_000_000)
        proof["networkRequests"] = connections.value()
        let info = NSPrintInfo.shared.copy() as! NSPrintInfo
        info.paperSize = NSSize(width: 595.2756, height: 841.8898)
        info.jobDisposition = .save
        info.dictionary()[NSPrintInfo.AttributeKey.jobSavingURL] = directory.appendingPathComponent("actual-appkit-output.pdf")
        let printOperation = page.webView.printOperation(with: info)
        printOperation.showsPrintPanel = false
        printOperation.showsProgressPanel = false
        operation = printOperation
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 794, height: 1123), styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = page.webView
        parent = window
        window.orderFront(nil)
        mark("appkit-print")
        printOperation.runModal(for: window, delegate: self,
            didRun: #selector(didPrint(_:success:contextInfo:)), contextInfo: nil)
    }
    @objc private func didPrint(_ operation: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?) {
        mark("appkit-returned"); finish(success)
    }
    private func finish(_ success: Bool) {
        listener?.cancel()
        proof["ok"] = success
        proof["phase"] = phase
        proof["paperOutputConfirmed"] = false
        do {
            let data = try JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys])
            try data.write(to: directory.appendingPathComponent("proof.json"), options: .atomic)
        } catch { exit(2) }
        exit(success ? 0 : 1)
    }
}

@main private struct Entry {
    @MainActor static func main() {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let probe = Probe(fixture: URL(fileURLWithPath: CommandLine.arguments[1]), directory: URL(fileURLWithPath: CommandLine.arguments[2]))
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        app.delegate = probe
        withExtendedLifetime(probe) { app.run() }
    }
}
#else
@main private struct Unsupported { static func main() { exit(2) } }
#endif
