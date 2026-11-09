#if os(macOS)
import AppKit
import BetaCore

/// Selected-file authority only; no directory watch, network or profile restore.
@MainActor final class NoteFileImportHost {
    private var busy = false
    func begin(parent: NSWindow, isCurrent: @escaping () -> Bool,
               deliver: @escaping ([String: Any], @escaping () -> Void) -> Void) {
        guard !busy, isCurrent() else { return }
        busy = true
        let panel = NSOpenPanel()
        panel.title = "Import note files"
        panel.message = "Select TXT/Markdown text, PDF or JPEG/PNG/GIF/WebP files. Unsupported content rejects the entire selection. Original Apple Notes ink is not converted."
        panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
        panel.allowedFileTypes = ["txt", "md", "markdown", "pdf", "jpg", "jpeg", "png", "gif", "webp"]
        guard panel.runModal() == .OK else { busy = false; return }
        let urls = panel.urls
        guard isCurrent(), !urls.isEmpty, urls.count <= NoteFileImport.maximumFiles else { busy = false; return }
        let scoped = urls.filter { $0.startAccessingSecurityScopedResource() }
        let stopScopes = { scoped.forEach { $0.stopAccessingSecurityScopedResource() } }
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try NoteFileImport.prepare(NoteFileImport.readSelected(urls)) }
            DispatchQueue.main.async {
                guard isCurrent() else { stopScopes(); self.busy = false; return }
                do {
                    let proposal = try result.get()
                    let preview = NSAlert()
                    preview.messageText = "Import \(proposal.items.count) new notes?"
                    preview.informativeText = "Existing notes are retained. TXT and Markdown become literal editable text. PDF/images remain original attachments; Apple Notes drawing strokes and metadata are not converted. No Apple synchronization is configured."
                    let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 520, height: 240))
                    let text = NSTextView(frame: scroll.bounds)
                    text.isEditable = false; text.isSelectable = true
                    text.string = proposal.items.map { item in
                        let sample = (item.noteFields["text"] as? String ?? "").prefix(240)
                        return item.sourceName + " (\(item.sourceBytes) bytes)\n" + item.warnings.joined(separator: "\n") + (sample.isEmpty ? "" : "\nPreview: " + String(sample))
                    }.joined(separator: "\n\n")
                    scroll.documentView = text; scroll.hasVerticalScroller = true; preview.accessoryView = scroll
                    preview.addButton(withTitle: "Import new notes"); preview.addButton(withTitle: "Cancel")
                    guard preview.runModal() == .alertFirstButtonReturn, isCurrent() else { stopScopes(); self.busy = false; return }
                    DispatchQueue.global(qos: .userInitiated).async {
                        let validation = Result { for (url, item) in zip(urls, proposal.items) { try NoteFileImport.revalidate(url, sourceSHA256: item.sourceSHA256) } }
                        DispatchQueue.main.async {
                            stopScopes()
                            guard isCurrent() else { self.busy = false; return }
                            do {
                                try validation.get()
                                let payload: [String: Any] = ["items": proposal.items.map { item in
                                    ["fields": item.noteFields, "sourceName": item.sourceName, "sourceSHA256": item.sourceSHA256,
                                     "sourceBytes": item.sourceBytes, "warnings": item.warnings] as [String: Any]
                                }]
                                deliver(payload) { self.busy = false }
                            } catch { self.fail(error); self.busy = false }
                        }
                    }
                } catch { stopScopes(); self.fail(error); self.busy = false }
            }
        }
    }
    private func fail(_ error: Error) {
        let alert = NSAlert(); alert.messageText = "Note file import failed"
        alert.informativeText = error.localizedDescription; alert.runModal()
    }
}
#endif
