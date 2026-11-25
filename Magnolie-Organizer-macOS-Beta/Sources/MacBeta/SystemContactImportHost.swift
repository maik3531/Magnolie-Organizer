#if os(macOS)
import AppKit
import CoreFoundation
import BetaCore

/// Refs #775. Selected local contact copies through the public Contacts framework.
/// The native source is read only; canonical JS owns the local transaction.
@MainActor
final class SystemContactImportHost {
    private var busy = false
    private var cancelled = false
    private var progress: NSPanel?
    private var cancelActiveRead: (() -> Void)?

    func begin(accounts: SystemAccounts, isCurrent: @escaping () -> Bool, translate tr: @escaping (String) -> String,
               prepare: @escaping ([String: Any]) async throws -> [String: Any],
               commit: @escaping (String) async throws -> [String: Any],
               cancel: @escaping (String) async -> Void) async {
        guard isCurrent() else { return }
        guard !busy else {
            message("A contact read is still finishing. Try again shortly.", tr: tr); return
        }
        busy = true; cancelled = false
        let current = { !self.cancelled && isCurrent() }
        var token: String?
        do {
            // Only this explicit action accesses Contacts and can request
            // system consent. No permission request or read at app launch.
            try await accounts.requestAccess(.contacts)
            guard current() else { throw CancellationError() }
            showProgress(tr)
            let sources = try await reading { try await accounts.contactCopySources() }
            hideProgress()
            guard current() else { throw CancellationError() }
            guard !sources.isEmpty else { throw BetaError("No accessible macOS address books were found.") }
            if let source = chooseSource(sources, tr: tr), current() {
                showProgress(tr)
                let summaries = try await reading { try await accounts.contactCopySummaries(source: source) }
                hideProgress()
                guard current() else { throw CancellationError() }
                guard !summaries.isEmpty else { throw BetaError("The selected macOS address book is empty.") }
                if let identifiers = chooseContacts(summaries, source: source, tr: tr), current() {
                    showProgress(tr)
                    let snapshot = try await reading {
                        try await accounts.contactCopySnapshot(source: source, identifiers: identifiers)
                    }
                    guard current() else { throw CancellationError() }
                    let plan = try await Task.detached(priority: .userInitiated) {
                        try SystemContactImport.prepare(snapshot)
                    }.value
                    guard current() else { throw CancellationError() }
                    let proposal = try await prepare(plan.payload)
                    guard let proposalToken = proposal["token"] as? String,
                          !proposalToken.isEmpty, proposalToken.utf8.count <= 256 else {
                        throw BetaError("The contact preview could not be prepared.")
                    }
                    token = proposalToken
                    guard proposal["ok"] as? Bool == true,
                          proposal["snapshotRevision"] as? String == plan.snapshotRevision,
                          let shownSource = proposal["source"] as? [String: Any],
                          let expectedSource = plan.payload["source"] as? [String: Any],
                          try Data(Document.encode(shownSource).utf8) == Data(Document.encode(expectedSource).utf8) else {
                        throw BetaError("The contact preview could not be prepared.")
                    }
                    hideProgress()
                    guard current() else { throw CancellationError() }
                    if try confirm(proposal, expectedCount: identifiers.count, tr: tr), current() {
                        showProgress(tr)
                        // Re-resolve exactly the same native IDs after review.
                        // This binds the observed fields, not a server CAS token.
                        let fresh = try await reading {
                            try await accounts.contactCopySnapshot(source: source, identifiers: identifiers)
                        }
                        try plan.revalidate(fresh)
                        hideProgress()
                        guard current() else { throw CancellationError() }
                        // There is no misleading cancellation button once the
                        // canonical local mutation/save transaction has started.
                        let receipt = try await commit(proposalToken)
                        guard isCurrent() else {
                            throw BetaError("The document changed. Check the saved contact copies after reopening.")
                        }
                        guard receipt["ok"] as? Bool == true,
                              try count(receipt, "count") == count(proposal, "newCount") else {
                            throw BetaError("Contact copying did not receive a durable save acknowledgement.")
                        }
                        message("Contact copies saved", detail:
                            tr("New contacts") + ": \(try count(receipt, "count"))\n\n" +
                            tr("These are editable local copies. Changes do not synchronize with Apple Contacts."), tr: tr)
                    }
                }
            }
        } catch {
            hideProgress()
            if current() {
                message("Contact copying could not finish", detail: tr(error.localizedDescription), tr: tr)
            }
        }
        hideProgress()
        if let token { await cancel(token) }
        // Cancellation stops further enumeration at the next framework callback.
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
        panel.title = tr("Reading selected contacts…"); panel.isReleasedWhenClosed = false
        let spinner = NSProgressIndicator(frame: NSRect(x: 22, y: 78, width: 24, height: 24))
        spinner.style = .spinning; spinner.startAnimation(nil)
        let label = NSTextField(wrappingLabelWithString: tr("Reading the selected contacts. Cancel discards this read after the current system call returns."))
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

    private func chooseSource(_ sources: [SystemContactImport.Source], tr: (String) -> String) -> SystemContactImport.Source? {
        let alert = NSAlert(); alert.messageText = tr("Copy macOS contacts")
        alert.informativeText = tr("Choose an address book. Only contacts you select in the next step will be copied to Magnolie.")
        let next = alert.addButton(withTitle: tr("Next")); next.isEnabled = false
        alert.addButton(withTitle: tr("Cancel"))
        let table = SelectionTable(columns: [(tr("Address book"), 280), (tr("Source identity"), 430)],
            rows: sources.map { [$0.title, $0.sourceUID] }, multiple: false)
        table.changed = { next.isEnabled = table.table.selectedRow >= 0 }
        defer { table.changed = nil }
        alert.accessoryView = table.scroll
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let row = table.table.selectedRow
        guard sources.indices.contains(row) else { return nil }
        return sources[row]
    }

    private func chooseContacts(_ contacts: [SystemContactReader.Summary], source: SystemContactImport.Source,
                                tr: (String) -> String) -> [String]? {
        let alert = NSAlert(); alert.messageText = tr("Select macOS contacts")
        alert.informativeText = display(source.title) + "\n\n" +
            tr("Select up to 100 contacts. Use Command-click or Shift-click for multiple selections. Contact notes and provider-specific fields are not copied.")
        let next = alert.addButton(withTitle: tr("Review contact copies")); next.isEnabled = false
        alert.addButton(withTitle: tr("Cancel"))
        let table = SelectionTable(columns: [(tr("Name"), 370), (tr("Source identity"), 340)],
            rows: contacts.map { [$0.title, $0.identifier] }, multiple: true)
        table.changed = {
            let count = table.table.selectedRowIndexes.count
            next.isEnabled = (1...SystemContactImport.maximumRecords).contains(count)
        }
        defer { table.changed = nil }
        alert.accessoryView = table.scroll
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let selected = table.table.selectedRowIndexes
        guard (1...SystemContactImport.maximumRecords).contains(selected.count),
              selected.allSatisfy({ contacts.indices.contains($0) }) else { return nil }
        return selected.map { contacts[$0].identifier }
    }

    private func count(_ object: [String: Any], _ key: String) throws -> Int {
        guard let number = object[key] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              number.doubleValue >= 0, number.doubleValue <= Double(SystemContactImport.maximumRecords) else { throw BetaError("The contact preview is invalid.") }
        return number.intValue
    }
    private func confirm(_ proposal: [String: Any], expectedCount: Int, tr: (String) -> String) throws -> Bool {
        let added = try count(proposal, "newCount"), existing = try count(proposal, "existingCount"),
            changed = try count(proposal, "changedCount")
        guard let source = proposal["source"] as? [String: Any], let sourceTitle = source["title"] as? String,
              let destination = proposal["addressbookTitle"] as? String,
              let preview = proposal["preview"] as? [[String: Any]], preview.count == added,
              let changes = proposal["changedPreview"] as? [[String: Any]], changes.count == changed,
              let excluded = proposal["excluded"] as? [[String: Any]],
              (1...SystemContactImport.maximumRecords).contains(expectedCount),
              added + existing + changed + excluded.count == expectedCount else {
            throw BetaError("The contact preview is invalid.")
        }
        let content = NSMutableAttributedString(string: "")
        func append(_ text: String) {
            content.append(NSAttributedString(string: text, attributes: [.font: NSFont.systemFont(ofSize: NSFont.systemFontSize)]))
        }
        for contact in preview {
            guard let title = contact["title"] as? String, let text = contact["text"] as? String,
                  let notices = contact["notices"] as? [String] else { throw BetaError("The contact preview is invalid.") }
            append(tr("New contact copy") + ": " + title + "\n\n" + text)
            if !notices.isEmpty { append("\n\n" + notices.map { reason($0, tr: tr) }.joined(separator: "\n")) }
            if let photo = contact["photo"] as? String, !photo.isEmpty {
                // Only a locally supplied canonical data image; no URL fetch,
                // HTML parser or source vCard controls the native preview.
                guard let comma = photo.firstIndex(of: ","),
                      ["data:image/jpeg;base64", "data:image/png;base64", "data:image/gif;base64", "data:image/webp;base64"]
                        .contains(String(photo[..<comma])),
                      photo.utf8.count <= 3_600_000,
                      let data = Data(base64Encoded: String(photo[photo.index(after: comma)...])),
                      let image = NSImage(data: data), image.size.width > 0, image.size.height > 0,
                      image.size.width.isFinite, image.size.height.isFinite else {
                    throw BetaError("The contact photo could not be previewed. No contacts were copied.")
                }
                // This display size never changes the original image data in
                // the reviewed contact payload or its local stored copy.
                let scale = min(1, 160 / max(image.size.width, image.size.height))
                image.size = NSSize(width: image.size.width * scale, height: image.size.height * scale)
                let attachment = NSTextAttachment(); attachment.image = image
                append("\n\n" + tr("Contact photo") + "\n")
                content.append(NSAttributedString(attachment: attachment))
            }
            append("\n\n────────────────────\n\n")
        }
        for contact in changes {
            guard let title = contact["title"] as? String else { throw BetaError("The contact preview is invalid.") }
            append(tr("Changed in Apple Contacts; local copy preserved") + ": " + title + "\n\n")
        }
        for contact in excluded {
            guard let title = contact["title"] as? String, let reasons = contact["reasons"] as? [String], !reasons.isEmpty else {
                throw BetaError("The contact preview is invalid.")
            }
            append(tr("Excluded") + ": " + title + "\n" + reasons.map { reason($0, tr: tr) }.joined(separator: "\n") + "\n\n")
        }
        let alert = NSAlert(); alert.messageText = tr("Review contact copies")
        alert.informativeText = display(sourceTitle) + "\n" + tr("Destination") + ": " + display(destination) + "\n\n" +
            tr("New contacts") + ": \(added) · " + tr("Already copied") + ": \(existing) · " +
            tr("Changed at source") + ": \(changed) · " + tr("Excluded") + ": \(excluded.count)\n\n" +
            tr("Copy the displayed contact fields to Magnolie. Contact notes and provider-specific fields are not copied. Birthdays do not create anniversary entries. Changes do not synchronize with Apple Contacts.")
        alert.addButton(withTitle: added > 0 ? tr("Copy displayed contacts") : tr("Close"))
        if added > 0 { alert.addButton(withTitle: tr("Cancel")) }
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 710, height: 360))
        scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
        let text = NSTextView(frame: NSRect(origin: .zero, size: scroll.contentSize))
        let maximum = CGFloat(Float.greatestFiniteMagnitude)
        text.minSize = NSSize(width: 0, height: scroll.contentSize.height)
        text.maxSize = NSSize(width: maximum, height: maximum)
        text.isEditable = false; text.isRichText = true; text.isSelectable = true
        text.isAutomaticLinkDetectionEnabled = false; text.isHorizontallyResizable = false
        text.isVerticallyResizable = true; text.autoresizingMask = [.width]
        text.textContainer?.containerSize = NSSize(width: scroll.contentSize.width, height: maximum)
        text.textContainer?.widthTracksTextView = true
        text.textStorage?.setAttributedString(content)
        scroll.documentView = text; alert.accessoryView = scroll
        return alert.runModal() == .alertFirstButtonReturn && added > 0
    }
    private func reason(_ code: String, tr: (String) -> String) -> String {
        let labels = [
            "native-contact-read-failed": "The contact could not be read completely.",
            "local-contact-copy-in-trash": "The local copy is in the trash. Restore it there if needed.",
            "canonical-contact-content-would-change": "The contact editor cannot preserve all selected fields.",
            "native-contact-email-case-normalized": "Email addresses use lowercase in Magnolie; their original spelling is retained in the source record.",
            "native-contact-field-unavailable": "Required public contact fields are unavailable.",
            "native-contact-text-not-representable": "A contact text field cannot be preserved.",
            "native-contact-labeled-value-not-representable": "A labeled contact value is incomplete or ambiguous.",
            "native-contact-label-not-representable": "A contact label cannot be preserved.",
            "native-contact-birthday-state-unavailable": "The birthday information is unavailable.",
            "native-contact-non-gregorian-birthday-not-supported": "A non-Gregorian birthday cannot be copied to the contact model.",
            "native-contact-additional-dates-not-supported": "Additional contact dates are not supported by this copy.",
            "native-contact-birthday-not-representable": "The birthday cannot be represented without changing its meaning.",
            "native-contact-photo-state-unavailable": "The original contact photo information is incomplete.",
            "native-contact-photo-not-representable": "The original contact photo cannot be copied in its current format.",
            "native-contact-address-not-representable": "The postal address cannot be preserved.",
            "native-contact-url-not-representable": "A website address is not supported.",
            "native-contact-no-supported-content": "The contact has no supported visible fields to copy.",
            "native-contact-public-fields-only": "Only the displayed public contact fields become editable copies. Contact notes, provider-specific fields, groups and linked-card relationships are not copied as those features.",
            "native-contact-name-details-in-source": "Additional name details remain in the source record; they are not separate editable name fields.",
            "native-contact-organization-details-in-source": "Additional organization details remain in the source record; they are not separate editable company fields.",
            "native-contact-address-details-in-source": "Additional district and locality details remain in the source record.",
            "native-contact-extra-public-fields-in-source": "Relations, social profiles and messaging details remain in the source record; they are not activated as contact actions.",
            "native-contact-url-labels-in-source": "Website labels remain in the source record."
        ]
        return labels[code].map(tr) ?? tr(code)
    }

    /// Rows are kept separately from labels: identical titles cannot silently
    /// select a different native address book or contact.
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
