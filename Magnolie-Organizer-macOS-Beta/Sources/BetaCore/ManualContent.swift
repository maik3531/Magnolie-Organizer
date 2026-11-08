import Foundation

public struct ManualContent {
    public let root: URL
    public static let languages = Set(["en", "de", "ar", "be", "cs", "da", "es", "fr", "hi", "hsb", "it", "ja", "nb", "nl", "pl", "pt", "ru", "tr", "uk", "zh-cn"])
    public init(root: URL) throws {
        guard root.isFileURL else { throw BetaError("Invalid bundled manual root.") }
        self.root = root.standardizedFileURL.resolvingSymlinksInPath()
        guard FileManager.default.fileExists(atPath: self.root.appendingPathComponent("index.html").path) else { throw BetaError("Bundled manual missing.") }
    }
    public func entry(fragment: String = "") throws -> URL {
        guard fragment.utf8.count <= 100, fragment.utf8.allSatisfy({ (97...122).contains($0) || (48...57).contains($0) || $0 == 45 }) else { throw BetaError("Invalid manual fragment.") }
        var url = URLComponents(url: root.appendingPathComponent("index.html"), resolvingAgainstBaseURL: false)!
        if !fragment.isEmpty { url.fragment = fragment }
        return url.url!
    }
    public func permits(_ url: URL) -> Bool {
        guard url.isFileURL, url.host == nil || url.host == "", url.query == nil,
              url.fragment?.utf8.allSatisfy({ (97...122).contains($0) || (48...57).contains($0) || $0 == 45 }) ?? true else { return false }
        guard let decoded = url.absoluteString.removingPercentEncoding,
              !decoded.components(separatedBy: "/").contains(".."), !decoded.components(separatedBy: "/").contains(".") else { return false }
        return url.standardizedFileURL.resolvingSymlinksInPath().path == root.appendingPathComponent("index.html").path
    }
    public static func external(_ url: URL, userInitiated: Bool) -> Bool {
        userInitiated && url.scheme?.lowercased() == "https" && url.host?.isEmpty == false && url.user == nil && url.password == nil
    }
}

#if os(macOS)
import AppKit
import WebKit

/// Separate local handbook origin and store. Deliberately installs NO message handlers.
@MainActor public final class ManualBrowser: NSObject, WKNavigationDelegate, WKUIDelegate {
    public let webView: WKWebView
    public let content: ManualContent
    private let external: (URL) -> Void
    public init(content: ManualContent, language: String = "system", external: @escaping (URL) -> Void) throws {
        guard language == "system" || ManualContent.languages.contains(language) else { throw BetaError("Invalid manual language.") }
        self.content = content; self.external = external
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.addUserScript(WKUserScript(source: """
            document.addEventListener('click', event => {
              const link = event.target.closest?.('a[href]');
              if (link && !event.isTrusted && new URL(link.href, document.baseURI).protocol !== 'file:') {
                event.preventDefault(); event.stopImmediatePropagation();
              }
            }, true);
            """, injectionTime: .atDocumentStart, forMainFrameOnly: false))
        if language != "system" {
            configuration.userContentController.addUserScript(WKUserScript(source: "window.__MAGNOLIE_SPRACHE__ = " + (try Document.encode(language)) + ";", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 1100, height: 800), configuration: configuration)
        super.init()
        webView.navigationDelegate = self; webView.uiDelegate = self
    }
    public func load() async throws {
        // Block network subresources, not just navigation. External HTTPS links
        // are handled explicitly by the delegate only after a user click.
        let networkRules = #"[{"trigger":{"url-filter":"^(https?|wss?|ftp)://"},"action":{"type":"block"}}]"#
        let list: WKContentRuleList = try await withCheckedThrowingContinuation { continuation in
            WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "magnolie-manual-local-only-v1", encodedContentRuleList: networkRules) { list, error in
                if let error { continuation.resume(throwing: error) }
                else if let list { continuation.resume(returning: list) }
                else { continuation.resume(throwing: BetaError("Manual network isolation unavailable.")) }
            }
        }
        webView.configuration.userContentController.add(list)
        webView.loadFileURL(try content.entry(), allowingReadAccessTo: content.root)
    }
    public func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if content.permits(url) { decisionHandler(.allow); return }
        if ManualContent.external(url, userInitiated: action.navigationType == .linkActivated) { external(url) }
        decisionHandler(.cancel)
    }
    public func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, ManualContent.external(url, userInitiated: action.navigationType == .linkActivated) { external(url) }
        return nil
    }
}
#endif
