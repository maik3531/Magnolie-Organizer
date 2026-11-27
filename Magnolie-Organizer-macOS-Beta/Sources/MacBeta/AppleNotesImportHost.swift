#if os(macOS)
import AppKit
import CoreFoundation
import BetaCore

/// Refs #772. User-selected text copies from the existing Apple Notes app.
/// The native source is read only; canonical JS owns the local transaction.
@MainActor
final class AppleNotesImportHost {
    private let reader = AppleNotesReader()
    private var busy = false
    var active: Bool { busy }
    private var cancelled = false
    private var progress: NSPanel?
    private var cancelActiveRead: (() -> Void)?

    func begin(isCurrent: @escaping () -> Bool, translate tr: @escaping (String) -> String,
               prepare: @escaping ([String: Any]) async throws -> [String: Any],
               commit: @escaping (String) async throws -> [String: Any],
               cancel: @escaping (String) async -> Void) async {
        guard isCurrent() else { return }
        guard !busy else {
            message("An Apple Notes read is still finishing. Try again shortly.", tr: tr); return
        }
        busy = true; cancelled = false
        let current = { !self.cancelled && isCurrent() }
        var token: String?
        do {
            // Only this explicit action contacts Notes and can trigger macOS
            // Automation consent. No permission request or read at app launch.
            showProgress(tr)
            let sources = try await reading { try await self.reader.sources() }
            hideProgress()
            guard current() else { throw CancellationError() }
            guard !sources.isEmpty else { throw BetaError("No accessible Apple Notes folders were found.") }
            if let source = chooseSource(sources, tr: tr), current() {
                showProgress(tr)
                let summaries = try await reading { try await self.reader.notes(in: source) }
                hideProgress()
                guard current() else { throw CancellationError() }
                guard !summaries.isEmpty else { throw BetaError("The selected Apple Notes folder is empty.") }
                if let identifiers = chooseNotes(summaries, source: source, tr: tr), current() {
                    showProgress(tr)
                    let snapshot = try await reading {
                        try await self.reader.snapshot(source: source, identifiers: identifiers)
                    }
                    guard current() else { throw CancellationError() }
                    let plan = try await Task.detached(priority: .userInitiated) {
                        try AppleNotesImport.prepare(snapshot)
                    }.value
                    guard current() else { throw CancellationError() }
                    let proposal = try await prepare(plan.payload)
                    guard let proposalToken = proposal["token"] as? String,
                          !proposalToken.isEmpty, proposalToken.utf8.count <= 256 else {
                        throw BetaError("The Apple Notes preview could not be prepared.")
                    }
                    token = proposalToken
                    guard proposal["ok"] as? Bool == true,
                          proposal["snapshotRevision"] as? String == plan.snapshotRevision,
                          let shownSource = proposal["source"] as? [String: Any],
                          let expectedSource = plan.payload["source"] as? [String: Any],
                          try Data(Document.encode(shownSource).utf8) == Data(Document.encode(expectedSource).utf8) else {
                        throw BetaError("The Apple Notes preview could not be prepared.")
                    }
                    hideProgress()
                    guard current() else { throw CancellationError() }
                    if try confirm(proposal, expectedCount: identifiers.count, tr: tr), current() {
                        showProgress(tr)
                        // Re-resolve exactly the same native IDs after review.
                        // This binds the observed fields, not a server CAS token.
                        let fresh = try await reading {
                            try await self.reader.snapshot(source: source, identifiers: identifiers)
                        }
                        try plan.revalidate(fresh)
                        hideProgress()
                        guard current() else { throw CancellationError() }
                        // There is no misleading cancellation button once the
                        // canonical local mutation/save transaction has started.
                        let receipt = try await commit(proposalToken)
                        guard isCurrent() else {
                            throw BetaError("The document changed. Check the saved note copies after reopening.")
                        }
                        guard receipt["ok"] as? Bool == true,
                              try count(receipt, "count") == count(proposal, "newCount") else {
                            throw BetaError("Apple Notes import did not receive a durable save acknowledgement.")
                        }
                        message("Apple Notes text copies saved", detail:
                            tr("New notes") + ": \(try count(receipt, "count"))\n\n" +
                            tr("These are editable local text copies. Changes do not synchronize with Apple Notes."), tr: tr)
                    }
                }
            }
        } catch {
            hideProgress()
            if current() {
                message("Apple Notes import could not finish", detail: tr(error.localizedDescription), tr: tr)
            }
        }
        hideProgress()
        if let token { await cancel(token) }
        // A cancelled NSAppleScript call may still be awaiting Apple Events.
        // Keep this coordinator occupied until its serialized read returns.
        busy = false
    }

    private func reading<Value>(_ operation: @escaping () async throws -> Value) async throws -> Value {
        let task = Task { try await operation() }
        cancelActiveRead = { task.cancel() }
        defer { cancelActiveRead = nil }
        return try await task.value
    }
    @objc private func cancelRead() {
        cancelled = true; cancelActiveRead?(); hideProgress()
    }
    private func showProgress(_ tr: (String) -> String) {
        hideProgress()
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 430, height: 135),
                            styleMask: [.titled], backing: .buffered, defer: false)
        panel.title = tr("Reading Apple Notes…"); panel.isReleasedWhenClosed = false
        let spinner = NSProgressIndicator(frame: NSRect(x: 22, y: 78, width: 24, height: 24))
        spinner.style = .spinning; spinner.startAnimation(nil)
        let label = NSTextField(wrappingLabelWithString: tr("Waiting for Apple Notes. Cancel discards this read; the app may still be responding."))
        label.frame = NSRect(x: 62, y: 66, width: 345, height: 48)
        let button = NSButton(title: tr("Cancel"), target: self, action: #selector(cancelRead))
        button.frame = NSRect(x: 310, y: 18, width: 100, height: 30)
        panel.contentView?.addSubview(spinner); panel.contentView?.addSubview(label); panel.contentView?.addSubview(button)
        progress = panel; panel.center(); panel.makeKeyAndOrderFront(nil)
    }
    private func hideProgress() { progress?.orderOut(nil); progress = nil }
    private func message(_ title: String, detail: String = "", tr: (String) -> String) {
        let alert = NSAlert(); alert.messageText = tr(title); alert.informativeText = detail
        alert.addButton(withTitle: tr("OK")); alert.runModal()
    }
    private func display(_ value: String) -> String {
        String(value.replacingOccurrences(of: "\r", with: " ").replacingOccurrences(of: "\n", with: " ").prefix(160))
    }

    private func chooseSource(_ sources: [AppleNotesImport.Source], tr: (String) -> String) -> AppleNotesImport.Source? {
        let alert = NSAlert(); alert.messageText = tr("Text copies from Apple Notes")
        alert.informativeText = tr("Choose an account and folder. Only notes you select in the next step will be read as text copies.")
        let next = alert.addButton(withTitle: tr("Next")); next.isEnabled = false
        alert.addButton(withTitle: tr("Cancel"))
        let table = SelectionTable(columns: [(tr("Account"), 170), (tr("Folder"), 170), (tr("Source identity"), 370)],
            rows: sources.map { [$0.accountTitle, $0.folderTitle, $0.accountID + " / " + $0.folderID] }, multiple: false)
        table.changed = { next.isEnabled = table.table.selectedRow >= 0 }
        defer { table.changed = nil }
        alert.accessoryView = table.scroll
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let row = table.table.selectedRow
        guard sources.indices.contains(row) else { return nil }
        return sources[row]
    }

    private func chooseNotes(_ notes: [AppleNotesReader.Summary], source: AppleNotesImport.Source,
                             tr: (String) -> String) -> [String]? {
        let alert = NSAlert(); alert.messageText = tr("Select Apple Notes")
        alert.informativeText = display(source.accountTitle) + " / " + display(source.folderTitle) + "\n\n" +
            tr("Select up to 32 notes. Use Command-click or Shift-click for multiple selections. Protected notes and notes with attachments are excluded from text copying.")
        let next = alert.addButton(withTitle: tr("Review text copies")); next.isEnabled = false
        alert.addButton(withTitle: tr("Cancel"))
        let table = SelectionTable(columns: [(tr("Title"), 370), (tr("Protection"), 125), (tr("Source identity"), 215)],
            rows: notes.map { [$0.title, $0.passwordProtected.map { $0 ? tr("Protected") : tr("Not protected") } ?? tr("Unavailable"), $0.identifier] },
            multiple: true)
        table.changed = {
            let count = table.table.selectedRowIndexes.count
            next.isEnabled = (1...32).contains(count)
        }
        defer { table.changed = nil }
        alert.accessoryView = table.scroll
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let selected = table.table.selectedRowIndexes
        guard (1...32).contains(selected.count), selected.allSatisfy({ notes.indices.contains($0) }) else { return nil }
        return selected.map { notes[$0].identifier }
    }

    private func count(_ object: [String: Any], _ key: String) throws -> Int {
        guard let number = object[key] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              number.doubleValue >= 0, number.doubleValue <= 32 else { throw BetaError("The Apple Notes preview is invalid.") }
        return number.intValue
    }
    private func confirm(_ proposal: [String: Any], expectedCount: Int, tr: (String) -> String) throws -> Bool {
        let added = try count(proposal, "newCount"), existing = try count(proposal, "existingCount"),
            changed = try count(proposal, "changedCount")
        guard let source = proposal["source"] as? [String: Any],
              let account = source["accountTitle"] as? String, let folder = source["folderTitle"] as? String,
              let notebook = proposal["notebookTitle"] as? String,
              let preview = proposal["preview"] as? [[String: Any]], preview.count == added,
              let changes = proposal["changedPreview"] as? [[String: Any]], changes.count == changed,
              let excluded = proposal["excluded"] as? [[String: Any]],
              (1...32).contains(expectedCount),
              added + existing + changed + excluded.count == expectedCount else { throw BetaError("The Apple Notes preview is invalid.") }
        var sections: [String] = []
        for note in preview {
            guard let title = note["title"] as? String, let text = note["text"] as? String else {
                throw BetaError("The Apple Notes preview is invalid.")
            }
            // Plain NSTextView content only. Never render Notes HTML, URLs or
            // source titles as markup. The whole proposed text remains visible.
            sections.append(tr("New text copy") + ": " + title + "\n\n" + text)
        }
        for note in changes {
            guard let title = note["title"] as? String else { throw BetaError("The Apple Notes preview is invalid.") }
            sections.append(tr("Changed in Apple Notes; local copy preserved") + ": " + title)
        }
        for note in excluded {
            guard let title = note["title"] as? String, let reasons = note["reasons"] as? [String], !reasons.isEmpty else {
                throw BetaError("The Apple Notes preview is invalid.")
            }
            sections.append(tr("Excluded") + ": " + title + "\n" + reasons.map { reason($0, tr: tr) }.joined(separator: "\n"))
        }
        let alert = NSAlert(); alert.messageText = tr("Review Apple Notes text copies")
        alert.informativeText = display(account) + " / " + display(folder) + "\n" + tr("Destination notebook") + ": " + display(notebook) + "\n\n" +
            tr("New notes") + ": \(added) · " + tr("Already copied") + ": \(existing) · " +
            tr("Changed at source") + ": \(changed) · " + tr("Excluded") + ": \(excluded.count)\n\n" +
            tr("Only the displayed text becomes an editable local note. Formatting, checklists, tables and other Apple Notes features are not preserved as those features. The original stays in Apple Notes.")
        alert.addButton(withTitle: added > 0 ? tr("Copy displayed text") : tr("Close"))
        if added > 0 { alert.addButton(withTitle: tr("Cancel")) }
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 710, height: 340))
        scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
        let text = NSTextView(frame: NSRect(origin: .zero, size: scroll.contentSize))
        let maximum = CGFloat(Float.greatestFiniteMagnitude)
        text.minSize = NSSize(width: 0, height: scroll.contentSize.height)
        text.maxSize = NSSize(width: maximum, height: maximum)
        text.isEditable = false; text.isRichText = false; text.isSelectable = true
        text.isAutomaticLinkDetectionEnabled = false; text.isHorizontallyResizable = false
        text.isVerticallyResizable = true; text.autoresizingMask = [.width]
        text.textContainer?.containerSize = NSSize(width: scroll.contentSize.width, height: maximum)
        text.textContainer?.widthTracksTextView = true
        text.font = .systemFont(ofSize: NSFont.systemFontSize)
        text.string = sections.joined(separator: "\n\n────────────────────\n\n")
        scroll.documentView = text; alert.accessoryView = scroll
        return alert.runModal() == .alertFirstButtonReturn && added > 0
    }
    private func reason(_ code: String, tr: (String) -> String) -> String {
        let labels = [
            "apple-note-read-failed": "The note could not be read completely.",
            "apple-note-protection-state-unavailable": "The note protection status is unavailable.",
            "apple-note-password-protected": "Protected notes are not copied.",
            "apple-note-attachment-state-unavailable": "The note attachment status is unavailable.",
            "apple-note-has-attachments": "The note contains attachments; use the separate file import for exported files.",
            "apple-note-plaintext-unavailable": "The note plaintext is unavailable.",
            "apple-note-html-unavailable": "The source representation cannot be verified.",
            "apple-note-modification-state-unavailable": "The note modification information is unavailable.",
            "apple-note-unsafe-control-characters": "The note contains unsupported control characters.",
            "local-apple-note-copy-in-trash": "The local copy is in the trash. Restore it there if needed.",
            "canonical-note-content-would-change": "The text cannot be preserved by the note editor."
        ]
        return labels[code].map(tr) ?? code
    }

    /// Rows are kept separately from labels: identical titles cannot silently
    /// select a different native account, folder or note.
    private final class SelectionTable: NSObject, NSTableViewDataSource, NSTableViewDelegate {
        let table = NSTableView(), scroll: NSScrollView
        let rows: [[String]]
        var changed: (() -> Void)?
        init(columns: [(String, CGFloat)], rows: [[String]], multiple: Bool) {
            self.rows = rows
            scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 730, height: 290))
            super.init()
            table.frame = scroll.bounds
            for (index, definition) in columns.enumerated() {
                let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(String(index)))
                column.title = definition.0; column.width = definition.1; column.minWidth = 80
                table.addTableColumn(column)
            }
            table.allowsMultipleSelection = multiple; table.allowsEmptySelection = true
            table.usesAlternatingRowBackgroundColors = true; table.rowHeight = 24
            table.dataSource = self; table.delegate = self
            scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = true
            scroll.borderType = .bezelBorder; scroll.documentView = table
        }
        func numberOfRows(in tableView: NSTableView) -> Int { rows.count }
        func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
            guard rows.indices.contains(row), let value = tableColumn?.identifier.rawValue,
                  let column = Int(value), rows[row].indices.contains(column) else { return nil }
            let field = NSTextField(labelWithString: rows[row][column])
            field.lineBreakMode = .byTruncatingMiddle; field.toolTip = rows[row][column]
            return field
        }
        func tableViewSelectionDidChange(_ notification: Notification) { changed?() }
    }
}
#endif
