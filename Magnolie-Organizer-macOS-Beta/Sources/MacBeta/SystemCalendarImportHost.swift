#if os(macOS)
import AppKit
import CoreFoundation
import BetaCore

/// Explicit one-way copying through EventKit. Neither the renderer nor this
/// coordinator can choose a write target in a system account.
@MainActor
final class SystemCalendarImportHost {
    private var busy = false
    private var cancelled = false
    private var progress: NSPanel?
    private var activeRead: Task<SystemSourceSnapshot, Error>?
    private struct Selection {
        let sourceUID: String, start: Date, end: Date, firstDay: String, lastDay: String
    }

    func begin(accounts: SystemAccounts, context: CalendarTimeContext, displayTimeZone: String,
               isCurrent: @escaping () -> Bool, translate tr: @escaping (String) -> String,
               prepare: @escaping ([String: Any]) async throws -> [String: Any],
               commit: @escaping (String) async throws -> [String: Any],
               cancel: @escaping (String) async -> Void) async {
        guard !busy, isCurrent() else { return }
        busy = true; cancelled = false
        let current = { !self.cancelled && isCurrent() }
        var token: String?
        do {
            // This method is entered only by the user's Import action, after
            // the canonical editor/save guard. Listing accounts never prompts.
            try await accounts.requestAccess(.events)
            guard current() else { throw BetaError("The document or timezone changed. Start the calendar import again.") }
            let status = try await accounts.status()
            guard current() else { throw BetaError("The document or timezone changed. Start the calendar import again.") }
            let sources = (status["kalender"] as? [[String: Any]] ?? []).filter {
                $0["art"] as? String == "events" && $0["quelle"] as? String == "macos"
            }
            guard !sources.isEmpty else { throw BetaError("No accessible macOS calendars were found.") }
            if let selection = try choose(sources, context: context, displayTimeZone: displayTimeZone, tr: tr), current() {
                showProgress(tr)
                let snapshot = try await read(accounts, selection)
                guard current() else { throw BetaError("The document or timezone changed. Start the calendar import again.") }
                // Calendar parsing uses the same pinned timezone database as
                // ordinary ICS import, off the AppKit/WebKit event thread.
                let plan = try await build(snapshot, context: context, displayTimeZone: displayTimeZone)
                guard current() else { throw BetaError("The document or timezone changed. Start the calendar import again.") }
                let proposal = try await prepare(plan.payload)
                guard proposal["ok"] as? Bool == true, let proposalToken = proposal["token"] as? String,
                      !proposalToken.isEmpty, proposalToken.utf8.count <= 256,
                      proposal["snapshotRevision"] as? String == plan.snapshotRevision else {
                    throw BetaError("The calendar preview could not be prepared.")
                }
                token = proposalToken
                hideProgress()
                guard current() else { throw BetaError("The document or timezone changed. Start the calendar import again.") }
                if try confirm(proposal, source: snapshot.source, selection: selection, tr: tr), current() {
                    // Re-fetch public objects after the preview. The fingerprint
                    // binds source/account metadata and every serialized record,
                    // including excluded entries; it is not a server CAS token.
                    showProgress(tr)
                    let fresh = try await read(accounts, selection)
                    try plan.revalidate(fresh)
                    hideProgress()
                    guard current() else { throw BetaError("The document or timezone changed. Start the calendar import again.") }
                    let receipt = try await commit(proposalToken)
                    guard isCurrent() else { throw BetaError("The document or timezone changed. Check the saved calendar copies after reopening.") }
                    guard receipt["ok"] as? Bool == true, try count(receipt, "count") == count(proposal, "newCount") else {
                        throw BetaError("Calendar import did not receive a durable save acknowledgement.")
                    }
                    let result = NSAlert()
                    result.messageText = tr("Calendar copies saved")
                    result.informativeText = tr("New appointments") + ": \(try count(receipt, "count"))\n\n" +
                        tr("These are editable local copies. Changes do not synchronize with Apple Calendar.")
                    result.addButton(withTitle: tr("OK")); result.runModal()
                }
            }
        } catch {
            hideProgress()
            if current() {
                let alert = NSAlert(); alert.messageText = tr("Calendar import could not finish")
                alert.informativeText = tr(error.localizedDescription)
                alert.addButton(withTitle: tr("OK")); alert.runModal()
            }
        }
        hideProgress()
        if let token { await cancel(token) }
        busy = false
    }

    private func read(_ accounts: SystemAccounts, _ selection: Selection) async throws -> SystemSourceSnapshot {
        let task = Task { try await accounts.snapshotEvents(sourceUID: selection.sourceUID, start: selection.start, end: selection.end) }
        activeRead = task
        defer { activeRead = nil }
        return try await task.value
    }
    @objc private func cancelRead() {
        cancelled = true; activeRead?.cancel(); hideProgress()
    }
    private func showProgress(_ tr: (String) -> String) {
        hideProgress()
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 380, height: 110),
                            styleMask: [.titled], backing: .buffered, defer: false)
        panel.title = tr("Reading selected calendar…"); panel.isReleasedWhenClosed = false
        let spinner = NSProgressIndicator(frame: NSRect(x: 24, y: 45, width: 24, height: 24))
        spinner.style = .spinning; spinner.startAnimation(nil)
        let label = NSTextField(labelWithString: tr("Preparing calendar preview…"))
        label.frame = NSRect(x: 60, y: 45, width: 296, height: 24)
        let button = NSButton(title: tr("Cancel"), target: self, action: #selector(cancelRead))
        button.frame = NSRect(x: 260, y: 10, width: 96, height: 28)
        panel.contentView?.addSubview(spinner); panel.contentView?.addSubview(label); panel.contentView?.addSubview(button)
        panel.center(); panel.makeKeyAndOrderFront(nil); progress = panel
    }
    private func hideProgress() { progress?.close(); progress = nil }

    private func build(_ snapshot: SystemSourceSnapshot, context: CalendarTimeContext,
                       displayTimeZone: String) async throws -> SystemCalendarImport.Plan {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do { continuation.resume(returning: try SystemCalendarImport.prepare(snapshot, context: context, displayTimeZone: displayTimeZone)) }
                catch { continuation.resume(throwing: error) }
            }
        }
    }

    private func choose(_ sources: [[String: Any]], context: CalendarTimeContext, displayTimeZone: String,
                        tr: (String) -> String) throws -> Selection? {
        let zoneName = displayTimeZone.isEmpty || displayTimeZone == "system" ? context.systemIdentifier : displayTimeZone
        let zone = try context.database.named(zoneName)
        let today = try context.database.wall(at: Int64(Date().timeIntervalSince1970 * 1000), in: zone)
        let midnight = try ProlepticGregorian.Civil(year: today.year, month: today.month, day: today.day)
        let first = try midnight.addingDays(-30), last = try midnight.addingDays(90)
        let alert = NSAlert(); alert.messageText = tr("Import macOS calendar appointments")
        alert.informativeText = tr("Choose a calendar and date range. Review the local copies before saving them in Magnolie.") +
            "\n" + tr("Display timezone") + ": " + zoneName
        let popup = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 480, height: 28), pullsDown: false)
        popup.menu = NSMenu(); popup.menu?.autoenablesItems = false
        for source in sources {
            guard let uid = source["uid"] as? String, let name = source["name"] as? String else { continue }
            _ = try SystemSourcePolicy.identifier(uid, kind: .events)
            // Add actual menu items: NSPopUpButton.addItem(withTitle:) can
            // merge equal names, while native source identities must not merge.
            let item = NSMenuItem(title: displayName(name), action: nil, keyEquivalent: "")
            item.representedObject = uid; item.isEnabled = true
            popup.menu?.addItem(item)
        }
        guard popup.numberOfItems > 0 else { throw BetaError("No accessible macOS calendars were found.") }
        popup.selectItem(at: 0)
        popup.setAccessibilityLabel(tr("Calendar"))
        let from = picker(first), until = picker(last)
        from.setAccessibilityLabel(tr("From date")); until.setAccessibilityLabel(tr("Through date"))
        let stack = NSStackView(views: [NSTextField(labelWithString: tr("Calendar")), popup,
            NSTextField(labelWithString: tr("From date")), from,
            NSTextField(labelWithString: tr("Through date")), until])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 8
        stack.frame = NSRect(x: 0, y: 0, width: 480, height: 190)
        alert.accessoryView = stack
        alert.addButton(withTitle: tr("Preview appointments")); alert.addButton(withTitle: tr("Cancel"))
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        guard alert.window.makeFirstResponder(nil) else { throw BetaError("Finish entering a valid calendar date.") }
        guard let sourceUID = popup.selectedItem?.representedObject as? String else { throw BetaError("Select a macOS calendar.") }
        let startDay = try day(from.dateValue), endDay = try day(until.dateValue)
        let exclusiveDay = try endDay.addingDays(1)
        guard let start = try context.database.resolve(startDay, in: zone, fold: .earlier, gap: .reject),
              let end = try context.database.resolve(exclusiveDay, in: zone, fold: .earlier, gap: .reject) else {
            throw BetaError("The selected date range cannot be represented in this timezone.")
        }
        let startDate = Date(timeIntervalSince1970: Double(start) / 1000), endDate = Date(timeIntervalSince1970: Double(end) / 1000)
        try SystemSourcePolicy.requireWindow(start: startDate, end: endDate)
        guard endDate.timeIntervalSince(startDate) <= SystemCalendarImport.maximumWindowSeconds else {
            throw BetaError("Select a calendar date range of at most 366 days.")
        }
        return Selection(sourceUID: sourceUID, start: startDate, end: endDate, firstDay: dateText(startDay), lastDay: dateText(endDay))
    }

    private func picker(_ day: ProlepticGregorian.Civil) -> NSDatePicker {
        let field = NSDatePicker(frame: NSRect(x: 0, y: 0, width: 220, height: 26))
        field.datePickerStyle = .textFieldAndStepper; field.datePickerMode = .single
        field.datePickerElements = [.yearMonthDay]
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        field.calendar = calendar; field.timeZone = calendar.timeZone
        field.dateValue = Date(timeIntervalSince1970: Double(day.epochMilliseconds) / 1000)
        return field
    }
    private func day(_ date: Date) throws -> ProlepticGregorian.Civil {
        let value = date.timeIntervalSince1970 * 1000
        guard value.isFinite, value >= -62_135_596_800_000, value <= 253_402_300_799_999 else { throw BetaError("Invalid calendar date.") }
        let civil = try ProlepticGregorian.civil(at: Int64(value))
        return try ProlepticGregorian.Civil(year: civil.year, month: civil.month, day: civil.day)
    }
    private func dateText(_ day: ProlepticGregorian.Civil) -> String {
        String(format: "%04d-%02d-%02d", day.year, day.month, day.day)
    }
    private func displayName(_ value: String) -> String {
        String(value.components(separatedBy: .controlCharacters).joined(separator: " ").prefix(180))
    }
    private func count(_ proposal: [String: Any], _ key: String) throws -> Int {
        guard let value = proposal[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.rounded() == value.doubleValue, (0...10_000).contains(value.doubleValue) else {
            throw BetaError("The calendar preview is invalid.")
        }
        return value.intValue
    }
    private func confirm(_ proposal: [String: Any], source: SystemSourceSnapshot.Source,
                         selection: Selection, tr: (String) -> String) throws -> Bool {
        let newCount = try count(proposal, "newCount"), existing = try count(proposal, "existingCount"), changed = try count(proposal, "changedCount")
        guard let preview = proposal["preview"] as? [[String: Any]], preview.count == newCount,
              let changedPreview = proposal["changedPreview"] as? [[String: Any]], changedPreview.count == changed,
              let excluded = proposal["excluded"] as? [[String: Any]], excluded.count <= 10_000,
              newCount + existing + changed + excluded.count <= 10_000 else { throw BetaError("The calendar preview is invalid.") }
        let alert = NSAlert(); alert.messageText = tr("Review calendar copies")
        alert.informativeText = displayName(source.title) + (source.parentTitle.map { " (" + displayName($0) + ")" } ?? "") +
            "\n\(selection.firstDay) – \(selection.lastDay)\n\n" +
            tr("New appointments") + ": \(newCount)\n" + tr("Already copied") + ": \(existing)\n" +
            tr("Changed in the source; existing copies are kept") + ": \(changed)\n" +
            tr("Not copied") + ": \(excluded.count)\n\n" +
            tr("These are editable local copies. Changes do not synchronize with Apple Calendar.")
        var lines: [String] = []
        for event in preview {
            let title = String((event["title"] as? String ?? "").prefix(400))
            let date = event["date"] as? String ?? "", time = event["time"] as? String ?? ""
            let end = event["endDate"] as? String ?? "", endTime = event["endTime"] as? String ?? ""
            let clock = event["allDay"] as? Bool == true ? tr("All day") : time
            let location = String((event["location"] as? String ?? "").prefix(1000))
            lines.append("\(date) \(clock) – \(end.isEmpty ? date : end) \(endTime)\n\(title)" + (location.isEmpty ? "" : "\n\(location)"))
        }
        if !changedPreview.isEmpty { lines.append("\n" + tr("Changed in the source; existing copies are kept")) }
        for event in changedPreview {
            let date = event["date"] as? String ?? "", time = event["time"] as? String ?? ""
            lines.append("\(date) \(time)\n" + String((event["title"] as? String ?? "").prefix(400)))
        }
        if !excluded.isEmpty { lines.append("\n" + tr("Not copied")) }
        for event in excluded {
            let reasons = event["reasons"] as? [String] ?? []
            let explanations = reasons.map { reason($0, tr: tr) }
            let title = event["title"] as? String ?? ""
            lines.append((title.isEmpty ? tr("Untitled appointment") : String(title.prefix(400))) + "\n" +
                Array(Set(explanations)).sorted().joined(separator: "; "))
        }
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 560, height: 300))
        let text = NSTextView(frame: scroll.bounds); text.isEditable = false; text.isSelectable = true
        text.isRichText = false; text.string = lines.joined(separator: "\n\n")
        scroll.documentView = text; scroll.hasVerticalScroller = true; alert.accessoryView = scroll
        if newCount > 0 {
            alert.addButton(withTitle: tr("Import local copies")); alert.addButton(withTitle: tr("Cancel"))
        } else { alert.addButton(withTitle: tr("Close")) }
        return alert.runModal() == .alertFirstButtonReturn && newCount > 0
    }

    private func reason(_ value: String, tr: (String) -> String) -> String {
        if value == "local-calendar-copy-in-trash" { return tr("This calendar copy is in the trash. Restore it there if needed.") }
        if value.contains("series") || value.contains("recurrence") { return tr("Repeating appointments are not supported by this import yet.") }
        if value.contains("alarm") { return tr("Appointments with alarms are not supported by this import yet.") }
        if value.contains("participant") { return tr("Appointments with participants are not supported by this import yet.") }
        if value.contains("birthday") { return tr("Birthday calendars need contact provenance and are not copied here.") }
        if value.contains("cancelled") { return tr("Cancelled appointments are not copied.") }
        if value.contains("all-day") || value.contains("timezone") || value.contains("zone") { return tr("The date or timezone cannot be preserved exactly.") }
        if value.contains("subsecond") || value.contains("fractional") { return tr("Subsecond appointment times are not supported.") }
        if value.contains("normaliz") || value.contains("text") || value.contains("location") { return tr("The appointment text cannot be preserved exactly.") }
        if value.contains("identity") || value.contains("conflict") { return tr("The appointment identity is ambiguous.") }
        return tr("This appointment contains unsupported or incomplete data.")
    }
}
#endif
