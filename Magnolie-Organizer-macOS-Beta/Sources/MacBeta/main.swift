#if os(macOS)
import AppKit
import WebKit
import EventKit
import UserNotifications
import BetaCore

final class Host: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler,
                  WKNavigationDelegate, UNUserNotificationCenterDelegate {
    private let name = "Magnolie Organizer macOS Beta"
    private var window: NSWindow!
    private var web: WKWebView!
    private var store: AtomicStore!
    private var entry: URL!
    private var plain: String?
    private var envelope: String?
    private var encryption: Encryption?
    private var initialized = false
    private var closePending = false
    private var closeApproved = false
    private var failureCount = 0
    private var unlockAfter = Date.distantPast
    private var notificationConsent = false
    private var selection: BackupSelection?
    private var restoring = false
    private var catalog: [String: String] = [:]
    private let events = EKEventStore()

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            guard let resources = Bundle.main.resourceURL else { throw BetaError("Application resources missing.") }
            entry = resources.appendingPathComponent("UI/web/index.html")
            guard FileManager.default.fileExists(atPath: entry.path) else {
                throw BetaError("No frozen generated UI. Run the documented macOS Beta development build.")
            }
            let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                     appropriateFor: nil, create: true)
            store = try AtomicStore(directory: support.appendingPathComponent("io.gitlab.maik3531.MagnolieOrganizer.macOSBeta"))
            let configuration = WKWebViewConfiguration()
            configuration.websiteDataStore = .nonPersistent()
            let bridge = "macOSBeta" + UUID().uuidString.replacingOccurrences(of: "-", with: "")
            configuration.userContentController.add(self, name: bridge)
            configuration.userContentController.addUserScript(WKUserScript(
                source: "window.__MAGNOLIE_BRUECKE__ = '\(bridge)';",
                injectionTime: .atDocumentStart, forMainFrameOnly: true))
            web = WKWebView(frame: .zero, configuration: configuration)
            web.navigationDelegate = self
            window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 850),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window.title = name
            window.minSize = NSSize(width: 720, height: 550)
            window.contentView = web; window.delegate = self
            window.center(); window.makeKeyAndOrderFront(nil)
            menu()
            UNUserNotificationCenter.current().delegate = self
            web.loadFileURL(entry, allowingReadAccessTo: resources.appendingPathComponent("UI"))
            NSApp.activate(ignoringOtherApps: true)
        } catch { alert(error.localizedDescription); NSApp.terminate(nil) }
    }

    private func menu() {
        let root = NSMenu(), appItem = NSMenuItem(), appMenu = NSMenu()
        root.addItem(appItem); appItem.submenu = appMenu
        appMenu.addItem(withTitle: tr("About") + " " + name, action: #selector(about), keyEquivalent: "").target = self
        appMenu.addItem(withTitle: "Enable in-app notifications...", action: #selector(consent), keyEquivalent: "").target = self
        appMenu.addItem(withTitle: "List macOS calendars (read-only)...", action: #selector(calendars), keyEquivalent: "").target = self
        appMenu.addItem(withTitle: "List macOS reminder lists (read-only)...", action: #selector(reminders), keyEquivalent: "").target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: tr("Quit") + " " + name, action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(), edit = NSMenu(title: tr("Edit"))
        root.addItem(editItem); editItem.submenu = edit
        edit.addItem(withTitle: tr("Undo"), action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: tr("Redo"), action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(withTitle: tr("Cut"), action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: tr("Copy"), action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: tr("Paste"), action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: tr("Select all"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        NSApp.mainMenu = root
    }
    @objc private func about() {
        alert((Bundle.main.object(forInfoDictionaryKey: "MagnolieBetaVersion") as? String ?? "") + "\n" +
              "Development Beta. Native validation is still required. JSON backup/restore and recovery-backed local editing; " +
              "no sync, background wake, auto-update or system-account integration.")
    }
    private func tr(_ text: String) -> String { catalog[text] ?? text }
    private func regional(_ text: String?) -> [String: Any] {
        let root = text.flatMap { try? Document.plain($0) }
        return (root?["einstellungen"] as? [String: Any])?["regional"] as? [String: Any] ?? [:]
    }
    private func localize(_ preferences: [String: Any]) {
        var language = preferences["language"] as? String ?? "system"
        if language == "system" { language = Locale.preferredLanguages.first ?? "en" }
        language = language.replacingOccurrences(of: "_", with: "-").lowercased()
        if language.hasPrefix("zh") { language = "zh-cn" }
        let path = Bundle.main.resourceURL?.appendingPathComponent("UI/native-i18n.json")
        let all = path.flatMap { try? Data(contentsOf: $0) }.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: [String: String]]
        catalog = all?[language] ?? all?[String(language.split(separator: "-").first ?? "en")] ?? [:]
        menu()
    }
    private func alert(_ message: String) {
        let alert = NSAlert(); alert.messageText = name; alert.informativeText = tr(message)
        alert.runModal()
    }
    @objc private func consent() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
            DispatchQueue.main.async {
                self.notificationConsent = granted
                self.alert(granted ? "Notifications enabled for this session, while the app is open and unlocked. " +
                           "Notification text can appear on the macOS lock screen. No wake or closed-app scheduling."
                           : "Notification permission was not granted. No system notifications will be sent.")
            }
        }
    }
    @objc private func calendars() { list(.event) }
    @objc private func reminders() { list(.reminder) }
    private func list(_ type: EKEntityType) {
        let completion: (Bool, Error?) -> Void = { granted, error in
            DispatchQueue.main.async {
                guard granted, error == nil else { self.alert("Access denied or unavailable. Nothing was imported or changed."); return }
                let names = self.events.calendars(for: type).map { $0.title + " (" + $0.source.title + ")" }.sorted()
                self.alert("Read-only discovery, not synchronization:\n\n" +
                           (names.isEmpty ? "No lists returned by EventKit." : names.joined(separator: "\n")))
            }
        }
        if #available(macOS 14.0, *) {
            if type == .event { events.requestFullAccessToEvents(completion: completion) }
            else { events.requestFullAccessToReminders(completion: completion) }
        } else { events.requestAccess(to: type, completion: completion) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let allowed = navigationAction.targetFrame?.isMainFrame == true &&
            navigationAction.request.url?.standardizedFileURL == entry.standardizedFileURL &&
            navigationAction.navigationType == .other && !initialized
        decisionHandler(allowed ? .allow : .cancel)
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        plain = nil; encryption = nil
        alert("WebKit stopped. Unsaved changes may be lost. Disk data was not replaced with an empty document. Restart the Beta.")
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        alert("The generated UI could not load. No document was initialized.")
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.webView === web,
              message.frameInfo.request.url?.standardizedFileURL == entry.standardizedFileURL,
              web.url?.standardizedFileURL == entry.standardizedFileURL, let raw = message.body as? String else { return }
        do { try dispatch(Request(raw)) }
        catch {
            // Never interpolate or log raw payloads, passwords, keys or personal record values.
            let fields = (try? Document.object(raw)) ?? [:]
            let command = fields["cmd"] as? String ?? "invalid"
            let message = command == "entsperren" ? "Unlock failed: wrong password or damaged/unsupported data." : tr(error.localizedDescription)
            var result: [String: Any] = ["ok": false, "fehler": message, "cmd": command]
            if let id = fields["id"] as? NSNumber { result["id"] = id }
            if let token = fields["token"] as? String { result["token"] = token }
            if command == "entsperren" {
                failureCount += 1
                if failureCount >= 3 { unlockAfter = Date().addingTimeInterval(300); failureCount = 0 }
                result["wartet"] = max(0, Int(ceil(unlockAfter.timeIntervalSinceNow)))
            }
            send("failure", result)
        }
    }
    private func send(_ method: String, _ payload: Any = [:]) {
        web.callAsyncJavaScript("window.MacBeta.receive(method, payload)",
                                arguments: ["method": method, "payload": payload], in: nil, in: .page) { result in
            if case .failure = result {
                self.plain = nil; self.encryption = nil
                self.alert("UI response failed. Further saves are blocked; restart and inspect the retained file.")
            }
        }
    }
    private func initialize(_ text: String?, new: Bool = false, locked: Bool = false) throws {
        let data: Any = try text.map { try Document.plain($0) } ?? [:]
        let preferences = regional(text)
        localize(preferences)
        send("init", ["daten": data, "neu": new, "echterErststart": new, "gesperrt": locked,
                      "regional": preferences.isEmpty ? ["language": "system"] : preferences,
                      "kennwort": encryption != nil, "datenPfad": store.file.path,
                      "trayVerfuegbar": false, "handbuchInstalliert": false, "contributorAktiv": false])
    }
    private func savePanel(_ data: Data, suffix: String) throws -> String? {
        let panel = NSSavePanel()
        panel.title = name + " Export"
        panel.nameFieldStringValue = "Magnolie Organizer macOS Beta-" + UUID().uuidString + suffix
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        // A dialog never authorizes replacing the live profile or its lease.
        let profile = store.file.deletingLastPathComponent().path + "/"
        guard !url.standardizedFileURL.path.hasPrefix(profile) else { throw BetaError("Choose a destination outside the live Beta profile.") }
        try AtomicStore.write(data, to: url)
        return url.path
    }
    private func dispatch(_ request: Request) throws {
        guard !restoring else { throw BetaError("Please wait.") }
        switch request.command {
        case .bereit:
            guard !initialized else { throw BetaError("Duplicate initialization refused.") }
            initialized = true
            let text = try store.load()
            if let text {
                let root = try Document.object(text)
                if root["magnolie"] as? String == "magnolie-verschluesselt" {
                    envelope = text; try initialize(nil, locked: true)
                } else {
                    _ = try Document.plain(text); plain = text; try initialize(text)
                }
            } else {
                // Only ENOENT from the private store can create a new profile.
                plain = "{}"; try initialize(nil, new: true)
            }
        case .entsperren:
            guard Date() >= unlockAfter, plain == nil, let envelope else { throw BetaError("Unlock is not available yet.") }
            let (text, session) = try Encryption.unlock(envelope, password: request.text("kennwort"))
            plain = text; encryption = session; failureCount = 0
            try initialize(text)
        case .speichern:
            guard let plain else { throw BetaError("No successfully loaded, unlocked document. Save refused.") }
            let text = request.text("text"), next = try Document.plain(text)
            let needsRecovery = (try? Document.assertNoLoss(Document.object(plain), next)) == nil
            let output = try encryption?.encrypt(text) ?? text
            try store.commit(output, preservingCurrent: needsRecovery)
            self.plain = text; envelope = encryption == nil ? nil : output
            send("gespeichert", ["id": request.fields["id"]!, "ok": true])
        case .kennwort_setzen:
            guard let plain, encryption == nil, envelope == nil,
                  request.text("alt").isEmpty, request.fields["sicherungen"] as? Bool != true,
                  request.text("sicherungsordner").isEmpty else {
                throw BetaError("Beta supports enabling encryption for the current file only. Password changes and backup rekeying are not implemented.")
            }
            let confirmation = NSAlert()
            confirmation.messageText = "Encrypt current macOS Beta profile?"
            confirmation.informativeText = "Only this Beta profile will be encrypted. Other files and backups are not changed. " +
                "This is not secure erasure of previous plaintext filesystem blocks. Keep the password; password change/removal is unavailable in this Beta."
            confirmation.addButton(withTitle: "Encrypt current profile")
            confirmation.addButton(withTitle: "Cancel")
            guard confirmation.runModal() == .alertFirstButtonReturn else { throw BetaError("Encryption cancelled; original file retained.") }
            let candidate = try Encryption.create(password: request.text("neu"))
            let output = try candidate.encrypt(plain)
            try store.commit(output); encryption = candidate; envelope = output
            send("kennwortStand", ["ok": true, "an": true])
        case .beenden: NSApp.terminate(nil)
        case .beenden_bereit:
            guard closePending else { throw BetaError("Unexpected close acknowledgement.") }
            closeApproved = true; closePending = false; NSApp.reply(toApplicationShouldTerminate: true)
        case .beenden_abgebrochen:
            if closePending { closePending = false; NSApp.reply(toApplicationShouldTerminate: false) }
        case .ablage_kopieren:
            guard plain != nil else { throw BetaError("Unlock first.") }
            NSPasteboard.general.clearContents()
            guard NSPasteboard.general.setString(request.text("text"), forType: .string) else { throw BetaError("Clipboard write failed.") }
        case .ablage_holen:
            guard plain != nil else { throw BetaError("Unlock first.") }
            send("ablage", ["text": NSPasteboard.general.string(forType: .string) ?? ""])
        case .sicherung:
            guard let plain else { throw BetaError("Unlock first.") }
            guard request.text("pfad").isEmpty else { throw BetaError("Beta backups use a native Save dialog, not a stored path.") }
            let output: String
            if !request.text("kennwort").isEmpty {
                output = try Encryption.create(password: request.text("kennwort")).encrypt(plain)
            } else if let encryption { output = try encryption.encrypt(plain) }
            else {
                let prompt = NSAlert(); prompt.messageText = tr("Create encrypted backup")
                prompt.informativeText = tr("Enter at least four characters for the backup password.")
                let password = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
                password.setAccessibilityLabel(tr("New backup password")); prompt.accessoryView = password
                prompt.addButton(withTitle: tr("Create backup")); prompt.addButton(withTitle: tr("Cancel"))
                guard prompt.runModal() == .alertFirstButtonReturn else {
                    send("sicherungFertig", ["ok": false, "abgebrochen": true, "fehler": tr("Cancel")]); return
                }
                defer { password.stringValue = "" }
                output = try Encryption.create(password: password.stringValue).encrypt(plain)
            }
            let path = try savePanel(Data(output.utf8), suffix: ".json")
            send("sicherungFertig", ["ok": path != nil, "pfad": path ?? "", "fehler": path == nil ? "Export cancelled." : ""])
        case .mutations_snapshot:
            guard plain != nil else { throw BetaError("Unlock first.") }
            _ = try store.checkpoint()
            send("mutationsSnapshot", ["ok": true, "token": request.text("token")])
        case .sicherung_waehlen:
            guard plain != nil else { throw BetaError("Unlock first.") }
            selection = nil
            let panel = NSOpenPanel(); panel.title = tr("Restore backup")
            panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
            panel.allowedFileTypes = ["json"]
            let recovery = store.file.deletingLastPathComponent().appendingPathComponent("Recovery-macOS-Beta")
            if FileManager.default.fileExists(atPath: recovery.path) { panel.directoryURL = recovery }
            guard panel.runModal() == .OK, let url = panel.url else {
                send("sicherungAusgewaehlt", ["ok": false, "abgebrochen": true]); return
            }
            let candidate = try BackupSelection(url: url)
            selection = candidate
            send("sicherungAusgewaehlt", ["ok": true, "pfad": candidate.url.path, "verschluesselt": candidate.encrypted])
        case .sicherung_wiederherstellen:
            guard let current = plain, let selection else { throw BetaError("This backup cannot be used.") }
            let source = try selection.confirmed(path: request.text("pfad"))
            let incoming: String
            let importedEncryption: Encryption?
            if selection.encrypted {
                let unlocked = try Encryption.unlock(source, password: request.text("kennwort"))
                incoming = unlocked.0; importedEncryption = unlocked.1
            } else { incoming = source; importedEncryption = nil }
            _ = try Document.plain(incoming)
            // Keep the current profile's password; an encrypted import never becomes
            // plaintext merely because the current profile had no password yet.
            let targetEncryption = encryption ?? importedEncryption
            let output = try targetEncryption?.encrypt(incoming) ?? incoming
            restoring = true
            web.callAsyncJavaScript("window.MacBeta.validateRestore(text)", arguments: ["text": incoming], in: nil, in: .page) { result in
                defer { self.restoring = false }
                do {
                    guard case .success(let accepted) = result, accepted as? Bool == true, self.plain == current else {
                        throw BetaError("This backup cannot be used.")
                    }
                    _ = try selection.confirmed(path: request.text("pfad"))
                    try self.store.commit(output, preservingCurrent: true)
                    self.plain = incoming; self.encryption = targetEncryption
                    self.envelope = targetEncryption == nil ? nil : output; self.selection = nil
                    self.localize(self.regional(incoming))
                    self.send("sicherungWiederhergestellt", ["ok": true, "daten": try Document.plain(incoming), "kennwort": targetEncryption != nil])
                } catch {
                    self.send("failure", ["cmd": "sicherung_wiederherstellen", "ok": false, "fehler": self.tr(error.localizedDescription)])
                }
            }
        case .regional_einstellungen:
            guard let plain else { throw BetaError("Unlock first.") }
            let settings = try RegionalSettings.validate(request.fields["regional"] as! [String: Any])
            let next = try RegionalSettings.merging(settings, into: plain)
            let output = try encryption?.encrypt(next) ?? next
            try store.commit(output)
            self.plain = next; envelope = encryption == nil ? nil : output
            send("regionalErgebnis", ["ok": true, "regional": settings])
        case .export:
            guard plain != nil, request.text("art") == "ics-termine",
                  let records = request.fields["daten"] as? [[String: Any]] else {
                throw BetaError("Only simple appointment ICS export is implemented; use encrypted JSON backup for the whole document.")
            }
            let text = try CalendarExport.appointments(records)
            let path = try savePanel(Data(text.utf8), suffix: ".ics")
            send("exportErgebnis", ["ok": path != nil, "pfad": path ?? "", "abgebrochen": path == nil,
                                    "anzahl": records.count,
                                    "bericht": "macOS Beta: simple appointments only; application metadata and global reminder preferences are not ICS fields. Use JSON backup for a complete copy."])
        case .erinnerung_einrichten:
            send("erinnerungStand", ["fehler": "macOS Beta: reminders only while open and unlocked; no wake or background scheduler. Enable notifications in the application menu."])
        case .erinnerung_zeigen:
            guard plain != nil, notificationConsent else { throw BetaError("Native notifications require explicit permission in the Beta application menu.") }
            guard ["notification", "sound", "both"].contains(request.text("art")) else { throw BetaError("Unsupported notification mode.") }
            let content = UNMutableNotificationContent()
            if request.text("art") != "sound" {
                content.title = request.text("kopf"); content.body = request.text("rumpf")
            }
            if request.text("art") != "notification" { content.sound = .default }
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { error in
                if error != nil { DispatchQueue.main.async { self.send("failure", ["cmd": "erinnerung_zeigen", "ok": false, "fehler": "Notification delivery failed."]) } }
            }
        case .notiz_anhang_datei:
            guard plain != nil, request.text("aktion") == "speichern" else {
                throw BetaError("Beta supports attachment Save only, not automatic opening of files.")
            }
            let text = request.text("daten")
            let types = ["application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"]
            guard text.utf8.count <= 12_000_000, let separator = text.firstIndex(of: ",") else { throw BetaError("Invalid attachment.") }
            let prefix = String(text[..<separator])
            guard let type = types.first(where: { prefix == "data:" + $0.key + ";base64" }),
                  let bytes = Data(base64Encoded: String(text[text.index(after: separator)...])) else { throw BetaError("Invalid attachment encoding.") }
            let path = try savePanel(bytes, suffix: type.value)
            send("notizAnhangDateiErgebnis", ["id": request.fields["id"]!, "aktion": "speichern", "ok": path != nil, "abgebrochen": path == nil])
        }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if restoring { return .terminateCancel }
        if closeApproved || web == nil { return .terminateNow }
        if closePending { return .terminateCancel }
        closePending = true; send("vorBeenden")
        DispatchQueue.main.asyncAfter(deadline: .now() + 35) {
            if self.closePending {
                self.closePending = false; NSApp.reply(toApplicationShouldTerminate: false)
                self.alert("Close was not acknowledged. The app remains open to protect unsaved changes.")
            }
        }
        return .terminateLater
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

let application = NSApplication.shared
let host = Host()
application.setActivationPolicy(.regular)
application.delegate = host
application.run()
#else
import Foundation
fputs("Magnolie Organizer macOS Beta requires macOS and Apple's SDK. This is not an emulator.\n", stderr)
exit(78)
#endif
