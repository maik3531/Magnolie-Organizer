import AppKit
import WebKit
import BetaCore

/// Exactly one system print panel, backed by a separate immutable renderer.
@MainActor final class PrintHost: NSObject {
    private var renderer: PrintRenderer?
    private var operation: NSPrintOperation?
    private var completion: (([String: Any]) -> Void)?
    func begin(html: String, parent: NSWindow, completed: @escaping ([String: Any]) -> Void) {
        guard renderer == nil else {
            completed(["ok": false, "code": "native_busy"]); return
        }
        let page = PrintRenderer()
        renderer = page; completion = completed
        Task {
            do {
                try await page.load(html)
                guard let info = NSPrintInfo.shared.copy() as? NSPrintInfo else {
                    throw BetaError("System print settings unavailable.")
                }
                let printOperation = page.webView.printOperation(with: info)
                printOperation.showsPrintPanel = true
                printOperation.showsProgressPanel = true
                operation = printOperation
                printOperation.runModal(for: parent, delegate: self,
                    didRun: #selector(didPrint(_:success:contextInfo:)), contextInfo: nil)
            } catch {
                finish(["ok": false, "code": "native_operation_failed"])
            }
        }
    }
    @objc private func didPrint(_ operation: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?) {
        // AppKit completion describes the dialog/operation only, never physical paper output.
        if success { finish(["ok": true, "stage": "dialog_returned", "dialogAction": "print"]) }
        else { finish(["ok": false, "code": "native_operation_failed"]) }
    }
    private func finish(_ result: [String: Any]) {
        let callback = completion
        completion = nil; operation = nil; renderer?.webView.stopLoading(); renderer = nil
        callback?(result)
    }
}
