import Foundation

/// An immutable print snapshot. No profile paths or executable bridge are part of it.
public enum PrintDocument {
    public static let maximumBytes = 750_000
    public static func isolatedHTML(_ html: String) throws -> String {
        guard !html.isEmpty, html.utf8.count <= maximumBytes else {
            throw BetaError("Print page is empty or exceeds the UTF-8 limit.")
        }
        // An earlier CSP cannot be relaxed by a later policy in supplied markup.
        let policy = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'\">"
        // Preserve an existing standards doctype before inserting the first head
        // content. Snippets receive their own standards wrapper.
        let expression = try NSRegularExpression(pattern: "\\A[\\t\\n\\r\\f ]*<!doctype[\\t\\n\\r\\f ]+html[\\t\\n\\r\\f ]*>", options: .caseInsensitive)
        let range = NSRange(html.startIndex..<html.endIndex, in: html)
        if let match = expression.firstMatch(in: html, range: range), let prefix = Range(match.range, in: html) {
            return String(html[..<prefix.upperBound]) + policy + String(html[prefix.upperBound...])
        }
        return "<!DOCTYPE html><html><head>" + policy + "</head><body>" + html + "</body></html>"
    }
}

#if os(macOS)
import AppKit
import WebKit

/// Separate, ephemeral renderer. Never receives native message handlers or profile access.
@MainActor public final class PrintRenderer: NSObject, WKNavigationDelegate {
    public let webView: WKWebView
    private var completion: CheckedContinuation<Void, Error>?
    private var deadline: Task<Void, Never>?
    private var started = false
    public override init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 794, height: 1123), configuration: configuration)
        super.init()
        webView.navigationDelegate = self
    }
    public func load(_ html: String) async throws {
        guard !started else { throw BetaError("Print renderer already used.") }
        let page = try PrintDocument.isolatedHTML(html)
        started = true
        // Navigation is separately denied by the delegate. Subresources are
        // blocked regardless of a document's own CSP; only inline data images/fonts remain.
        let rules = #"[{"trigger":{"url-filter":".*","resource-type":["image","style-sheet","script","font","raw","svg-document","media"]},"action":{"type":"block"}},{"trigger":{"url-filter":"^data:","resource-type":["image","font"]},"action":{"type":"ignore-previous-rules"}}]"#
        let list: WKContentRuleList = try await withCheckedThrowingContinuation { continuation in
            WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "magnolie-print-isolated-v1", encodedContentRuleList: rules) { list, error in
                if let error { continuation.resume(throwing: error) }
                else if let list { continuation.resume(returning: list) }
                else { continuation.resume(throwing: BetaError("Print resource policy unavailable.")) }
            }
        }
        webView.configuration.userContentController.add(list)
        try await withCheckedThrowingContinuation { continuation in
            completion = continuation
            deadline = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: 15_000_000_000) } catch { return }
                self?.finish(BetaError("Print page did not finish loading."))
            }
            webView.loadHTMLString(page, baseURL: nil)
        }
    }
    private func finish(_ error: Error? = nil) {
        guard let pending = completion else { return }
        completion = nil; deadline?.cancel(); deadline = nil
        if let error { webView.stopLoading(); pending.resume(throwing: error) }
        else { pending.resume() }
    }
    public func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let initial = completion != nil && action.targetFrame?.isMainFrame == true &&
            action.navigationType == .other && action.request.url?.absoluteString == "about:blank"
        decisionHandler(initial ? .allow : .cancel)
    }
    public func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { finish() }
    public func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { finish(error) }
    public func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { finish(error) }
    public func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { finish(BetaError("Print renderer stopped.")) }
}
#endif
