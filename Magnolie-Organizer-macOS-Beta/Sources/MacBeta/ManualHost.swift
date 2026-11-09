#if os(macOS)
import AppKit
import BetaCore

@MainActor final class ManualHost {
    private var window: NSWindow?
    private var browser: ManualBrowser?
    func show(root: URL, language: String) async throws {
        if let window { window.makeKeyAndOrderFront(nil); return }
        let browser = try ManualBrowser(content: ManualContent(root: root), language: language, external: { NSWorkspace.shared.open($0) })
        try await browser.load()
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Magnolie Organizer — Handbook 2.0.30"
        window.isReleasedWhenClosed = false
        window.contentView = browser.webView
        self.browser = browser; self.window = window
        window.makeKeyAndOrderFront(nil)
    }
}
#endif
