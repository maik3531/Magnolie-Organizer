#if os(macOS)
import AppKit
import CoreFoundation
import BetaCore

/// Refs #777. Explicit standalone task copies through public EventKit reminders.
/// The native source is read only; canonical JS owns the local transaction.
@MainActor
final class SystemReminderImportHost {
    private var busy = false
    private var cancelled = false
    private var progress: NSPanel?
    private var cancelActiveRead: (() -> Void)?

    func begin(accounts: SystemAccounts, context: CalendarTimeContext, displayTimeZone: String,
               isCurrent: @escaping () -> Bool, translate tr: @escaping (String) -> String,
               prepare: @escaping ([String: Any]) async throws -> [String: Any],
               commit: @escaping (String) async throws -> [String: Any],
               cancel: @escaping (String) async -> Void) async {
        guard isCurrent() else { return }
        guard !busy else {
            message("A reminder read is still finishing. Try again shortly.", tr: tr); return
        }
        busy = true; cancelled = false
        let current = { !self.cancelled && isCurrent() }
        var token: String?
        do {
            // Only this explicit action accesses Reminders and can request
            // system consent. No permission request or read at app launch.
            try await accounts.requestAccess(.reminders)
            guard current() else { throw CancellationError() }
            showProgress(tr)
            let sources = try await reading { try await accounts.reminderCopySources() }
            hideProgress()
            guard current() else { throw CancellationError() }
            guard !sources.isEmpty else { throw BetaError("No accessible macOS reminder lists were found.") }
            if let source = chooseSource(sources, tr: tr), current() {
                showProgress(tr)
                let summaries = try await reading { try await accounts.reminderCopySummaries(source: source) }
                hideProgress()
                guard current() else { throw CancellationError() }
                guard !summaries.isEmpty else { throw BetaError("The selected macOS reminder list is empty.") }
                if let identifiers = chooseReminders(summaries, source: source, tr: tr), current() {
                    showProgress(tr)
                    let snapshot = try await reading {
                        try await accounts.reminderCopySnapshot(source: source, identifiers: identifiers)
                    }
                    guard current() else { throw CancellationError() }
                    let plan = try await Task.detached(priority: .userInitiated) {
                        try SystemReminderImport.prepare(snapshot, context: context, displayTimeZone: displayTimeZone)
                    }.value
                    guard current() else { throw CancellationError() }
                    let proposal = try await prepare(plan.payload)
                    guard let proposalToken = proposal["token"] as? String,
                          !proposalToken.isEmpty, proposalToken.utf8.count <= 256 else {
                        throw BetaError("The reminder preview could not be prepared.")
                    }
                    token = proposalToken
                    guard proposal["ok"] as? Bool == true,
                          proposal["snapshotRevision"] as? String == plan.snapshotRevision,
                          proposal["displayTimeZone"] as? String == displayTimeZone,
                          let shownSource = proposal["source"] as? [String: Any],
                          let expectedSource = plan.payload["source"] as? [String: Any],
                          try Data(Document.encode(shownSource).utf8) == Data(Document.encode(expectedSource).utf8) else {
                        throw BetaError("The reminder preview could not be prepared.")
                    }
                    hideProgress()
                    guard current() else { throw CancellationError() }
                    if try confirm(proposal, expectedCount: identifiers.count, tr: tr), current() {
                        showProgress(tr)
                        // Re-resolve exactly the same native IDs after review.
                        // This binds the observed fields, not a server CAS token.
                        let fresh = try await reading {
                            try await accounts.reminderCopySnapshot(source: source, identifiers: identifiers)
                        }
                        try plan.revalidate(fresh)
                        hideProgress()
                        guard current() else { throw CancellationError() }
                        // There is no misleading cancellation button once the
                        // canonical local mutation/save transaction has started.
                        let receipt = try await commit(proposalToken)
                        guard isCurrent() else {
                            throw BetaError("The document or timezone changed. Check the saved task copies after reopening.")
                        }
                        guard receipt["ok"] as? Bool == true,
                              try count(receipt, "count") == count(proposal, "newCount") else {
                            throw BetaError("Reminder copying did not receive a durable save acknowledgement.")
                        }
                        message("Task copies saved", detail:
                            tr("New tasks") + ": \(try count(receipt, "count"))\n\n" +
                            tr("These are independent editable local tasks. Changes do not synchronize with Apple Reminders."), tr: tr)
                    }
                }
            }
        } catch {
            hideProgress()
            if current() {
                message("Reminder copying could not finish", detail: tr(error.localizedDescription), tr: tr)
            }
        }
        hideProgress()
        if let token { await cancel(token) }
        // The reader owns once-only completion and fetch cancellation. A running
        // native getter may still return; stale results never authorize a copy.
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
        panel.title = tr("Reading selected reminders…"); panel.isReleasedWhenClosed = false
        let spinner = NSProgressIndicator(frame: NSRect(x: 22, y: 78, width: 24, height: 24))
        spinner.style = .spinning; spinner.startAnimation(nil)
        let label = NSTextField(wrappingLabelWithString: tr("Reading the selected reminders. Cancel discards this read; a running system call may still return."))
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

    private func chooseSource(_ sources: [SystemReminderImport.Source], tr: (String) -> String) -> SystemReminderImport.Source? {
        let alert = NSAlert(); alert.messageText = tr("Copy macOS reminders")
        alert.informativeText = tr("Choose a reminder list. Selected entries become independent local tasks in Magnolie; subtask relationships are not available through this connection.")
        let next = alert.addButton(withTitle: tr("Next")); next.isEnabled = false
        alert.addButton(withTitle: tr("Cancel"))
        let table = SelectionTable(columns: [(tr("Account"), 160), (tr("Reminder list"), 220), (tr("Source identity"), 330)],
            rows: sources.map { [$0.parentTitle, $0.title, $0.sourceUID] }, multiple: false)
        table.changed = { next.isEnabled = table.table.selectedRow >= 0 }
        defer { table.changed = nil }
        alert.accessoryView = table.scroll
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let row = table.table.selectedRow
        guard sources.indices.contains(row) else { return nil }
        return sources[row]
    }

    private func chooseReminders(_ reminders: [SystemReminderReader.Summary], source: SystemReminderImport.Source,
                                 tr: (String) -> String) -> [String]? {
        let alert = NSAlert(); alert.messageText = tr("Select macOS reminders")
        alert.informativeText = display(source.parentTitle) + " / " + display(source.title) + "\n\n" +
            tr("Select up to 100 reminders. Open and completed entries are listed. Use Command-click or Shift-click for multiple selections. Recurring reminders and entries with alarms are excluded.")
        let next = alert.addButton(withTitle: tr("Review task copies")); next.isEnabled = false
        alert.addButton(withTitle: tr("Cancel"))
        let table = SelectionTable(columns: [(tr("Title"), 340), (tr("Status"), 100), (tr("Source identity"), 270)],
            rows: reminders.map { [$0.title, tr($0.completed ? "Completed" : "Open"), $0.identifier] }, multiple: true)
        table.changed = {
            let count = table.table.selectedRowIndexes.count
            next.isEnabled = (1...SystemReminderImport.maximumRecords).contains(count)
        }
        defer { table.changed = nil }
        alert.accessoryView = table.scroll
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let selected = table.table.selectedRowIndexes
        guard (1...SystemReminderImport.maximumRecords).contains(selected.count),
              selected.allSatisfy({ reminders.indices.contains($0) }) else { return nil }
        return selected.map { reminders[$0].identifier }
    }

    private func count(_ object: [String: Any], _ key: String) throws -> Int {
        guard let number = object[key] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              number.doubleValue >= 0, number.doubleValue <= Double(SystemReminderImport.maximumRecords) else { throw BetaError("The reminder preview is invalid.") }
        return number.intValue
    }
    private func confirm(_ proposal: [String: Any], expectedCount: Int, tr: (String) -> String) throws -> Bool {
        let added = try count(proposal, "newCount"), existing = try count(proposal, "existingCount"),
            changed = try count(proposal, "changedCount")
        guard let source = proposal["source"] as? [String: Any], let sourceTitle = source["title"] as? String,
              let parentTitle = source["parentTitle"] as? String,
              let destination = proposal["targetTitle"] as? String,
              let zone = proposal["displayTimeZone"] as? String,
              let preview = proposal["preview"] as? [[String: Any]], preview.count == added,
              let changes = proposal["changedPreview"] as? [[String: Any]], changes.count == changed,
              let excluded = proposal["excluded"] as? [[String: Any]],
              (1...SystemReminderImport.maximumRecords).contains(expectedCount),
              added + existing + changed + excluded.count == expectedCount else {
            throw BetaError("The reminder preview is invalid.")
        }
        var sections: [String] = []
        for task in preview {
            guard let title = task["title"] as? String, let text = task["text"] as? String,
                  let notices = task["notices"] as? [String] else { throw BetaError("The reminder preview is invalid.") }
            var section = tr("New task copy") + ": " + title + "\n\n" + text
            if !notices.isEmpty { section += "\n\n" + notices.map { reason($0, tr: tr) }.joined(separator: "\n") }
            sections.append(section)
        }
        for task in changes {
            guard let title = task["title"] as? String else { throw BetaError("The reminder preview is invalid.") }
            sections.append(tr("Changed in Apple Reminders; local copy preserved") + ": " + title)
        }
        for task in excluded {
            guard let title = task["title"] as? String, let reasons = task["reasons"] as? [String], !reasons.isEmpty else {
                throw BetaError("The reminder preview is invalid.")
            }
            sections.append(tr("Excluded") + ": " + title + "\n" + reasons.map { reason($0, tr: tr) }.joined(separator: "\n"))
        }
        let alert = NSAlert(); alert.messageText = tr("Review task copies")
        alert.informativeText = display(parentTitle) + " / " + display(sourceTitle) + "\n" +
            tr("Destination") + ": " + display(destination) + "\n" + tr("Display timezone") + ": " + display(zone) + "\n\n" +
            tr("New tasks") + ": \(added) · " + tr("Already copied") + ": \(existing) · " +
            tr("Changed at source") + ": \(changed) · " + tr("Excluded") + ": \(excluded.count)\n\n" +
            tr("Copy the displayed fields as independent local tasks. Subtasks, tags, flags, attachments and assignments are not copied. Recurring entries and alarms are excluded. Changes do not synchronize with Apple Reminders.")
        alert.addButton(withTitle: added > 0 ? tr("Copy displayed tasks") : tr("Close"))
        if added > 0 { alert.addButton(withTitle: tr("Cancel")) }
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 710, height: 360))
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
            "native-reminder-read-failed": "The reminder could not be read completely.",
            "native-reminder-field-unavailable": "A required public reminder field is unavailable or inconsistent.",
            "native-reminder-alarms-not-supported": "Reminders with alarms are not copied yet.",
            "native-reminder-recurrence-not-supported": "Recurring reminders are not copied yet.",
            "native-reminder-title-unavailable": "The reminder has no usable title.",
            "native-reminder-title-would-change": "The title would change in the task editor.",
            "native-reminder-text-not-representable": "The task editor cannot preserve this text exactly.",
            "native-reminder-note-state-unavailable": "The reminder note could not be read consistently.",
            "native-reminder-timestamp-state-unavailable": "A source timestamp is unavailable or invalid.",
            "native-reminder-completion-state-inconsistent": "The completion state and its timestamp are inconsistent.",
            "native-reminder-date-state-unavailable": "The reminder date fields are unavailable.",
            "native-reminder-date-components-not-representable": "The reminder date cannot be represented without changing its meaning.",
            "native-reminder-subminute-time-not-supported": "The task editor cannot preserve seconds or fractions of a second.",
            "native-reminder-time-zone-not-representable": "The reminder timezone or local clock time cannot be resolved unambiguously.",
            "native-reminder-date-window-not-editable": "This start and due date combination cannot be preserved by the task editor.",
            "native-reminder-mixed-time-semantics-not-supported": "Floating and timezone-bound start and due times cannot be combined in this copy.",
            "native-reminder-standalone-copy": "This is an independent task. No parent or subtask relationship is copied.",
            "native-reminder-public-fields-only": "Subtasks, tags, flags, attachments, assignments and rich text are unavailable through this connection. Their absence is not confirmed.",
            "native-reminder-priority-grouped": "Original priorities 1–3 become High, 4–6 become Normal and 7–9 become Low. No source priority (0) becomes Normal. The original value remains in the source data.",
            "native-reminder-source-timestamps": "Original creation, modification and completion times remain in the source data. The local copy has its own creation and modification times.",
            "native-reminder-extra-public-fields-in-source": "Location and URL remain in the source data. They are not activated as task fields or opened.",
            "local-reminder-copy-in-trash": "The local copy is in the trash. Restore it there if needed.",
            "canonical-reminder-content-would-change": "The task editor cannot preserve all selected fields."
        ]
        return labels[code].map(tr) ?? tr(code)
    }

    /// Rows are kept separately from labels: identical titles cannot silently
    /// select a different native reminder list or item.
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
