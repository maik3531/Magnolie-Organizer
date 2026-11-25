#if os(macOS)
import AppKit
import CoreGraphics
import Darwin
import BetaCore

/// Refs #721. Native controls own exactly one bundled receiver. The web bridge
/// cannot pass executable paths, pipeline strings, network destinations or PINs.
@MainActor final class AirPlayHost: NSObject, NSWindowDelegate {
    private let profileDirectory: URL
    private let mayStart: () -> Bool
    private let translate: (String) -> String
    private var session = AirPlaySession(available: false)
    private var bundle: AirPlayBundle?
    private var privateState: AirPlayPrivateState?
    private var process: Process?
    private var input: Pipe?
    private var output: Pipe?
    private var notificationTokens: [(NotificationCenter, NSObjectProtocol)] = []
    private var lockToken: NSObjectProtocol?
    private var window: NSWindow?
    private let status = NSTextField(wrappingLabelWithString: "")
    private let pin = NSTextField(labelWithString: "")
    private var startButton: NSButton!
    private var stopButton: NSButton!
    private var errorText: String?
    private var suspended = false
    private let receiverName: String = {
        let host = ProcessInfo.processInfo.hostName.split(separator: ".").first.map(String.init) ?? "Mac"
        // Leave room for RAOP's MAC-prefix inside the 63-byte DNS-SD label.
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
        let scalars = host.unicodeScalars.filter { allowed.contains($0) }.prefix(32)
        let safe = String(String.UnicodeScalarView(scalars))
        return "Magnolie " + (safe.isEmpty ? "Mac" : safe)
    }()

    init(profileDirectory: URL, mayStart: @escaping () -> Bool, translate: @escaping (String) -> String) {
        self.profileDirectory = profileDirectory
        self.mayStart = mayStart
        self.translate = translate
        super.init()
        let workspace = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.willSleepNotification, NSWorkspace.screensDidSleepNotification,
                     NSWorkspace.sessionDidResignActiveNotification] {
            let observer = workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.suspend() }
            }
            notificationTokens.append((workspace, observer))
        }
        // The public session/sleep notifications above also cover switching users
        // and display sleep. This notification stops promptly on an explicit lock.
        lockToken = DistributedNotificationCenter.default().addObserver(
            forName: NSNotification.Name("com.apple.screenIsLocked"), object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.suspend() }
            }
    }

    deinit {
        for (center, token) in notificationTokens { center.removeObserver(token) }
        if let lockToken { DistributedNotificationCenter.default().removeObserver(lockToken) }
        try? input?.fileHandleForWriting.close()
        // EOF is also watched by the native helper, including when this app crashes.
        if process?.isRunning == true { process?.terminate() }
    }

    func show() {
        if window == nil { makeWindow() }
        if !session.isRunning {
            do {
                bundle = try AirPlayBundle(contents: Bundle.main.bundleURL.appendingPathComponent("Contents"))
                session.setAvailability(true); errorText = nil
            } catch {
                bundle = nil; session.setAvailability(false)
                errorText = (error as? AirPlayBundle.Failure)?.errorDescription ?? "The bundled iPhone receiver is incomplete or incompatible."
            }
        }
        update()
        window?.makeKeyAndOrderFront(nil)
    }

    private func makeWindow() {
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 430),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        panel.minSize = NSSize(width: 520, height: 420)
        panel.title = translate("iPhone screen mirroring")
        panel.isReleasedWhenClosed = false; panel.delegate = self
        let heading = NSTextField(labelWithString: receiverName)
        heading.font = .boldSystemFont(ofSize: 19)
        let instructions = NSTextField(wrappingLabelWithString: translate(
            "Connect the iPhone and Mac to the same network. Start the receiver, then select this name in Control Center → Screen Mirroring on the iPhone."))
        let scope = NSTextField(wrappingLabelWithString: translate(
            "Shows the iPhone screen and plays its sound. Control the iPhone on the iPhone. Notes, calendars and contacts use their separate import or account connections."))
        scope.textColor = .secondaryLabelColor
        pin.font = .monospacedDigitSystemFont(ofSize: 28, weight: .semibold)
        pin.setAccessibilityLabel(translate("iPhone pairing PIN"))
        startButton = NSButton(title: translate("Start receiver"), target: self, action: #selector(start))
        stopButton = NSButton(title: translate("Stop receiver"), target: self, action: #selector(stopPressed))
        let buttons = NSStackView(views: [startButton, stopButton]); buttons.spacing = 12
        let stack = NSStackView(views: [heading, instructions, status, pin, buttons, scope])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = NSView(); content.addSubview(stack); panel.contentView = content
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 22),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -22),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 22),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: content.bottomAnchor, constant: -22),
            instructions.widthAnchor.constraint(equalTo: stack.widthAnchor),
            status.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scope.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
        panel.center(); window = panel
    }

    private func update() {
        let message: String
        if let errorText { message = errorText }
        else {
            switch session.phase {
            case .unavailable: message = "This Magnolie build does not contain the iPhone receiver."
            case .idle: message = suspended ? "Receiver stopped. Start it again when you want to share the iPhone screen." : "Receiver is off."
            case .starting: message = "Starting the iPhone receiver…"
            case .ready: message = session.pin == nil ? "Ready. Select this Mac on the iPhone." : "Enter this PIN on the iPhone."
            case .receiving:
                message = session.receivingVideo ? "Receiving iPhone screen data. The picture opens in its own window." : "Receiving iPhone audio data."
            case .stopping: message = "Stopping the iPhone receiver…"
            case .failed: message = "The iPhone receiver stopped unexpectedly. Start it again to retry."
            }
        }
        status.stringValue = translate(message)
        pin.stringValue = session.pin ?? ""
        pin.isHidden = session.pin == nil
        startButton?.isEnabled = session.canStart && mayStart()
        stopButton?.isEnabled = session.isRunning && session.phase != .stopping
    }

    private func foregroundConsoleSession() -> Bool {
        guard NSApp.isActive, let dictionary = CGSessionCopyCurrentDictionary() as? [String: Any],
              dictionary[kCGSessionOnConsoleKey as String] as? Bool == true,
              dictionary[kCGSessionLoginDoneKey as String] as? Bool == true else { return false }
        return true
    }

    @objc private func start() {
        guard session.canStart, mayStart(), foregroundConsoleSession(), let bundle else { return }
        let token: UUID
        do { token = try session.beginStart() } catch { return }
        errorText = nil; suspended = false; update()
        let child = Process(), events = Pipe(), lifetime = Pipe()
        do {
            let state = try AirPlayPrivateState(profileDirectory: profileDirectory)
            privateState = state
            child.executableURL = bundle.executable
            child.arguments = state.arguments(receiverName: receiverName)
            child.environment = bundle.environment(sessionDirectory: state.sessionDirectory)
            child.currentDirectoryURL = state.sessionDirectory
            child.standardInput = lifetime; child.standardOutput = events; child.standardError = FileHandle.nullDevice
            process = child; input = lifetime; output = events
            child.terminationHandler = { [weak self, weak child] terminated in
                let exitStatus = terminated.terminationStatus
                Task { @MainActor in
                    guard let self, let child, self.process === child else { return }
                    self.didExit(token: token, status: exitStatus)
                }
            }
            try child.run()
            // Only the child owns these ends. Their closure makes EOF reliable.
            try? lifetime.fileHandleForReading.close()
            try? events.fileHandleForWriting.close()
            readEvents(events.fileHandleForReading, token: token)
            // A cold bundled plugin scan can be slower on older Intel Macs.
            DispatchQueue.main.asyncAfter(deadline: .now() + 45) { [weak self] in
                guard let self, self.session.startupTimedOut(token: token) else { return }
                self.errorText = "The iPhone receiver did not become ready in time."
                self.endChild(); self.update()
            }
        } catch {
            _ = session.fail(.launchFailed, token: token)
            errorText = (error as? AirPlayBundle.Failure)?.errorDescription ?? "The iPhone receiver could not start."
            if child.isRunning { endChild() }
            else { didExit(token: token, status: 1) }
            update()
        }
    }

    private func readEvents(_ handle: FileHandle, token: UUID) {
        // Bounded reads and decoder; no raw diagnostics, device names or PIN log.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var decoder = AirPlayEventDecoder()
            do {
                while let bytes = try handle.read(upToCount: 4096), !bytes.isEmpty {
                    let events = try decoder.append(bytes)
                    DispatchQueue.main.async { [weak self] in
                        guard let self else { return }
                        for event in events {
                            guard self.session.receive(event, token: token) else { continue }
                            if self.session.phase == .failed {
                                self.errorText = "The iPhone receiver reported an error. Stop and start it again."
                                self.endChild()
                            }
                        }
                        self.update()
                    }
                }
                try decoder.finish()
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.process?.isRunning == true, self.session.phase != .stopping,
                          self.session.fail(.protocolViolation, token: token) else { return }
                    self.errorText = "The iPhone receiver returned an invalid status."
                    self.endChild(); self.update()
                }
            } catch {
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.session.phase != .stopping,
                          self.session.fail(.protocolViolation, token: token) else { return }
                    self.errorText = "The iPhone receiver returned an invalid status."
                    self.endChild(); self.update()
                }
            }
        }
    }

    @objc private func stopPressed() { stop() }
    func stop() {
        guard session.requestStop() != nil else { return }
        endChild(); update()
    }
    func suspend() {
        suspended = true; stop()
        // A locked/switched session must not leave a pairing PIN on screen.
        window?.orderOut(nil)
    }
    private func endChild() {
        try? input?.fileHandleForWriting.close()
        // Its stdin monitor also handles parent death and has its own hard timeout.
        if let process, process.isRunning { process.terminate() }
    }
    private func didExit(token: UUID, status: Int32) {
        guard session.processExited(token: token, exitStatus: status) else { return }
        process?.terminationHandler = nil
        process = nil
        try? input?.fileHandleForWriting.close(); input = nil
        // Reader owns its handle until EOF. Do not close it concurrently with read.
        output = nil
        privateState?.removeSession(); privateState = nil
        update()
    }
    func windowWillClose(_ notification: Notification) { stop() }
}
#endif
