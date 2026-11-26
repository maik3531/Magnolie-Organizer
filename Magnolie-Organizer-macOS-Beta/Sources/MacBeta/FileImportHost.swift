#if os(macOS)
import AppKit
import BetaCore

/// #785: native selection -> frozen current parser -> shared merge -> Save ACK.
/// A parser response alone never counts as a saved import.
@MainActor final class FileImportHost {
    private var busy = false
    var active: Bool { busy }

    func begin(format: String, wasteToken: String?, bundle: URL,
               isCurrent: @escaping () -> Bool, settings: @escaping () throws -> [String: String],
               prepare: @escaping () async throws -> [String: Any],
               commit: @escaping ([String: Any], String) async throws -> [String: Any],
               cancel: @escaping (String) async -> Void,
               translate: @escaping (String) -> String) async {
        guard !busy, isCurrent(), FileImportProtocol.formats.contains(format) else { return }
        busy = true
        defer { busy = false }
        var token = ""
        do {
            let prepared = try await prepare()
            if prepared["cancelled"] as? Bool == true { return }
            guard isCurrent(), let selectedToken = prepared["token"] as? String, !selectedToken.isEmpty else {
                throw BetaError("The import document is no longer available.")
            }
            token = selectedToken
            let context = try settings()
            guard let language = context["language"], let timeZone = context["timeZone"],
                  let homeCountry = context["homeCountry"] else {
                throw BetaError("Invalid file import request.")
            }
            let types = ["ics": ["ics", "vcs", "lcs", "zip"], "lotus": ["or6", "csv", "zip"],
                         "vcf": ["vcf", "csv", "zip"], "claws": ["xml", "ldif", "ldi", "zip"],
                         "ldif": ["ldif", "ldi", "zip"], "muell": ["ics", "csv"]]
            let panel = NSOpenPanel()
            panel.title = translate("Import")
            panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
            panel.allowedFileTypes = types[format]
            guard panel.runModal() == .OK, let url = panel.url else { await cancel(token); return }
            guard isCurrent() else { throw BetaError("The document changed. Start the file import again.") }
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let response: [String: Any] = try await withCheckedThrowingContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    do {
                        let bytes = try FileImportProcess.readSelected(url)
                        let request = try FileImportProtocol.Input(bytes: bytes, format: format, name: url.lastPathComponent,
                            language: language, timeZone: timeZone, homeCountry: homeCountry)
                        var result = try FileImportProcess.run(request, bundle: bundle)
                        if format == "muell" {
                            guard let wasteToken, !wasteToken.isEmpty else { throw BetaError("Missing waste-import operation.") }
                            result["art"] = "muell"; result["muellToken"] = wasteToken
                        }
                        continuation.resume(returning: result)
                    } catch { continuation.resume(throwing: error) }
                }
            }
            guard isCurrent(), try settings() == context else {
                throw BetaError("The document or regional settings changed. Start the file import again.")
            }
            let receipt = try await commit(response, token)
            guard receipt["ok"] as? Bool == true else { throw BetaError("The import did not complete.") }
        } catch {
            if !token.isEmpty { await cancel(token) }
            let alert = NSAlert(); alert.messageText = translate("Import failed")
            alert.informativeText = translate(error.localizedDescription)
            alert.runModal()
        }
    }
}
#endif
