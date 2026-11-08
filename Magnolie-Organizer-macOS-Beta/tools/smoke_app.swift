// Run on macOS: swift tools/smoke_app.swift /path/to/Beta.app /path/to/proof-directory
// Exercises the shipped Host/resources; no JS injection, alternate profile or test bridge.
#if os(macOS)
import AppKit
import CoreGraphics
import CryptoKit
import Foundation

struct SmokeError: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}
let started = ProcessInfo.processInfo.systemUptime
let deadline = started + 90
var owned: [NSRunningApplication] = []
var phase = "preflight"
var launchNumber = 0
var evidence: URL?
var profileURL: URL?
var progressFile: FileHandle?
var consoleFile: FileHandle?
var consoleProcess: Process?
func progress(_ message: String) {
    let elapsed = ProcessInfo.processInfo.systemUptime - started
    let line = String(format: "[bundle-smoke +%.1fs] %@: %@\n", elapsed, phase, message)
    let bytes = Data(line.utf8)
    FileHandle.standardError.write(bytes) // Unbuffered progress, including runner failures.
    progressFile?.write(bytes)
}
func begin(_ next: String) { phase = next; progress("begin") }
func observations() -> [String: Any] {
    let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta")
    let pids = Set(apps.map { $0.processIdentifier })
    let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    var result: [String: Any] = [
        "phase": phase, "elapsedSeconds": ProcessInfo.processInfo.systemUptime - started,
        "screenCaptureAccess": CGPreflightScreenCaptureAccess(),
        "applications": apps.map { app -> [String: Any] in
            ["pid": app.processIdentifier, "terminated": app.isTerminated,
             "finishedLaunching": app.isFinishedLaunching, "active": app.isActive,
             "bundle": app.bundleURL?.path ?? "unavailable"]
        },
        "windows": windows.compactMap { window -> [String: Any]? in
            guard let pid = window[kCGWindowOwnerPID as String] as? NSNumber,
                  pids.contains(pid.int32Value) else { return nil }
            return ["pid": pid, "number": window[kCGWindowNumber as String] ?? -1,
                    "layer": window[kCGWindowLayer as String] ?? -1,
                    "onscreen": window[kCGWindowIsOnscreen as String] ?? false,
                    "bounds": window[kCGWindowBounds as String] ?? [:],
                    "title": window[kCGWindowName as String] ?? "redacted/unavailable"]
        }
    ]
    if let file = profileURL {
        let attributes = try? FileManager.default.attributesOfItem(atPath: file.path)
        result["profile"] = ["exists": FileManager.default.fileExists(atPath: file.path),
                             "bytes": attributes?[.size] as? NSNumber ?? -1,
                             "mode": attributes?[.posixPermissions] as? NSNumber ?? -1]
    }
    return result
}
func saveObservations(_ filename: String, extra: [String: Any] = [:]) {
    guard let evidence else { return }
    let value = observations().merging(extra) { _, new in new }
    do {
        let bytes = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        try bytes.write(to: evidence.appendingPathComponent(filename), options: .atomic)
    } catch { progress("Could not save diagnostic metadata: \(error)") }
}
func startConsole(_ directory: URL) throws {
    let file = directory.appendingPathComponent("bundle-console.log")
    try Data().write(to: file, options: .withoutOverwriting)
    consoleFile = try FileHandle(forWritingTo: file)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/log")
    process.arguments = ["stream", "--style", "compact", "--level", "debug", "--predicate",
                         "process == 'Magnolie Organizer macOS Beta'"]
    process.standardOutput = consoleFile
    process.standardError = consoleFile
    try process.run()
    consoleProcess = process
}
func stopConsole() {
    if let process = consoleProcess, process.isRunning { process.terminate() }
    try? consoleFile?.close()
    consoleFile = nil
}
func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw SmokeError(message) }
}
func waitUntil(_ label: String, _ condition: () throws -> Bool) throws {
    var heartbeat = ProcessInfo.processInfo.systemUptime + 5
    while try !condition() {
        let now = ProcessInfo.processInfo.systemUptime
        try require(now < deadline, "90-second bundle smoke deadline exceeded while " + label)
        if now >= heartbeat {
            progress("waiting for " + label)
            saveObservations("bundle-smoke-observations.json")
            heartbeat = now + 5
        }
        // NSWorkspace/NSRunningApplication are AppKit APIs. A CLI helper must
        // initialize NSApplication and service its events as well as CFRunLoop.
        while let event = NSApp.nextEvent(matching: .any, until: Date(), inMode: .default, dequeue: true) {
            NSApp.sendEvent(event)
        }
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }
    progress("completed " + label)
}
func launch(_ bundle: URL) throws -> NSRunningApplication {
    launchNumber += 1
    begin("launch-" + String(launchNumber))
    var finished = false
    var app: NSRunningApplication?
    var failure: Error?
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.createsNewApplicationInstance = true
    configuration.activates = true
    configuration.addsToRecentItems = false
    NSWorkspace.shared.openApplication(at: bundle, configuration: configuration) { result, error in
        app = result; failure = error; finished = true
    }
    try waitUntil("LaunchServices completion") { finished }
    if let failure { throw failure }
    guard let app else { throw SmokeError("LaunchServices returned no application") }
    owned.append(app)
    progress("LaunchServices returned PID " + String(app.processIdentifier))
    saveObservations("bundle-smoke-observations.json")
    try require(app.bundleURL?.resolvingSymlinksInPath() == bundle.resolvingSymlinksInPath(), "Unexpected launched bundle")
    try require(app.bundleIdentifier == "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta", "Unexpected launched identity")
    try require(!app.isTerminated, "Application exited before its window was available")
    return app
}
func windowID(_ app: NSRunningApplication) throws -> CGWindowID {
    begin("visible-window-" + String(launchNumber))
    var found: CGWindowID?
    try waitUntil("PID-bound visible application window") {
        try require(!app.isTerminated, "Application exited before a visible window appeared")
        let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        for window in windows {
            guard (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == app.processIdentifier,
                  (window[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
                  let bounds = window[kCGWindowBounds as String] as? [String: Any],
                  let rectangle = CGRect(dictionaryRepresentation: bounds as CFDictionary),
                  rectangle.width >= 700, rectangle.height >= 500,
                  let identifier = window[kCGWindowNumber as String] as? NSNumber else { continue }
            found = identifier.uint32Value; return true
        }
        return false
    }
    return found!
}
func quit(_ app: NSRunningApplication) throws {
    // Normal Cocoa quit invokes Host.applicationShouldTerminate, which waits
    // for the real page's save/close acknowledgement. No signal is a success path.
    begin("normal-quit-" + String(launchNumber))
    try require(!app.isTerminated && app.terminate(), "Normal application termination was refused")
    try waitUntil("normal Cocoa termination of PID " + String(app.processIdentifier)) { app.isTerminated }
}
func profile(_ file: URL) throws -> (Data, [String: Any]) {
    let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
    try require((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600, "Profile file permissions are not 0600")
    let bytes = try Data(contentsOf: file)
    guard let root = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
          let notes = root["notizen"] as? [[String: Any]], notes.count == 1,
          let noteID = notes[0]["id"] as? String, !noteID.isEmpty,
          let text = notes[0]["text"] as? String, !text.isEmpty,
          root["einstellungen"] is [String: Any],
          ["termine", "aufgaben", "kontakte"].allSatisfy({ root[$0] is [Any] }) else {
        throw SmokeError("Real startup/save did not produce the normalized fresh profile and welcome note")
    }
    return (bytes, root)
}
func hash(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
func screenshot(_ identifier: CGWindowID, to file: URL) throws -> Bool {
    let capture = Process()
    capture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    capture.arguments = ["-x", "-l", String(identifier), file.path]
    capture.standardOutput = FileHandle.nullDevice
    capture.standardError = FileHandle.nullDevice
    try capture.run()
    do { try waitUntil("window screenshot process") { !capture.isRunning } }
    catch { if capture.isRunning { capture.terminate() }; throw error }
    // Screen-recording permission is independent of LaunchServices/native storage.
    // If capture succeeds, the evidence must be a decodable, nonempty PNG.
    if capture.terminationStatus != 0 { return false }
    let bytes = try Data(contentsOf: file)
    try require(bytes.starts(with: [137, 80, 78, 71, 13, 10, 26, 10]), "Screenshot is not a PNG")
    guard let image = NSBitmapImageRep(data: bytes), image.pixelsWide >= 700, image.pixelsHigh >= 500 else {
        throw SmokeError("Screenshot is not a valid application-window image")
    }
    return true
}

do {
    try require(CommandLine.arguments.count == 3, "Usage: smoke_app.swift BUNDLE.app PROOF_DIRECTORY")
    let bundle = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
    let output = URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL
    let fm = FileManager.default
    try fm.createDirectory(at: output, withIntermediateDirectories: true)
    let proofFile = output.appendingPathComponent("bundle-smoke.json")
    let imageFile = output.appendingPathComponent("bundle-window.png")
    try require(!fm.fileExists(atPath: proofFile.path) && !fm.fileExists(atPath: imageFile.path), "Existing smoke evidence refused")
    evidence = output
    let progressURL = output.appendingPathComponent("bundle-smoke-progress.log")
    try Data().write(to: progressURL, options: .withoutOverwriting)
    progressFile = try FileHandle(forWritingTo: progressURL)
    progress("initializing AppKit for the LaunchServices client")
    // Initialize the event machinery required by AppKit's LaunchServices client.
    _ = NSApplication.shared
    NSApp.setActivationPolicy(.prohibited)
    NSApp.finishLaunching()
    progress("AppKit initialized; starting real bundle check")
    let support = try fm.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
    let directory = support.appendingPathComponent("io.gitlab.maik3531.MagnolieOrganizer.macOSBeta")
    // The runner must be disposable. Never reuse, replace or delete user data.
    try require(!fm.fileExists(atPath: directory.path), "Existing Beta profile refused; use a fresh disposable runner")
    try require(NSRunningApplication.runningApplications(withBundleIdentifier: "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta").isEmpty,
                "Existing Beta process refused")
    try startConsole(output)
    let file = directory.appendingPathComponent("organizer.json")
    profileURL = file
    saveObservations("bundle-smoke-observations.json")
    let first = try launch(bundle)
    let window = try windowID(first)
    // Let the normal local document render; final disk assertions, not this
    // short settling interval or the process/window, establish functional success.
    begin("render-settle")
    let settle = ProcessInfo.processInfo.systemUptime + 3
    try waitUntil("initial rendering interval") { try require(!first.isTerminated, "Application exited while rendering"); return ProcessInfo.processInfo.systemUptime >= settle }
    begin("window-capture")
    let captured = try screenshot(window, to: imageFile)
    saveObservations("bundle-smoke-first-window.json", extra: ["screenshotCaptured": captured])
    try quit(first)
    begin("first-profile-validation")
    let (initialBytes, initial) = try profile(file)
    let initialFileNumber = (try fm.attributesOfItem(atPath: file.path)[.systemFileNumber] as? NSNumber)?.uint64Value
    try require(initialFileNumber != nil, "Cannot identify first saved profile file")
    let directoryAttributes = try fm.attributesOfItem(atPath: directory.path)
    try require((directoryAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o700, "Profile directory permissions are not 0700")
    let second = try launch(bundle)
    _ = try windowID(second)
    begin("reload-settle")
    let reloadSettle = ProcessInfo.processInfo.systemUptime + 3
    try waitUntil("reloaded rendering interval") { try require(!second.isTerminated, "Application exited while reloading"); return ProcessInfo.processInfo.systemUptime >= reloadSettle }
    try quit(second)
    begin("reloaded-profile-validation")
    let (reloadedBytes, reloaded) = try profile(file)
    let reloadedFileNumber = (try fm.attributesOfItem(atPath: file.path)[.systemFileNumber] as? NSNumber)?.uint64Value
    // The page begins each launch without a saved-text acknowledgement. Its
    // normal quit must therefore cause AtomicStore's real rename-based commit.
    // An unchanged file could otherwise hide quitting before reload completed.
    try require(reloadedFileNumber != nil && reloadedFileNumber != initialFileNumber, "Reopened Host did not atomically save the profile")
    try require(NSDictionary(dictionary: initial).isEqual(NSDictionary(dictionary: reloaded)), "Profile data changed during reopen/normal quit")
    let proof: [String: Any] = [
        "bundleLaunch": true, "pidBoundVisibleWindow": true, "normalQuit": true,
        "freshNormalizedProfileSaved": true, "reopen": true, "reopenedProfileAtomicallySaved": true, "profileDataPreserved": true,
        "firstProfileSHA256": hash(initialBytes), "reopenedProfileSHA256": hash(reloadedBytes),
        "screenshotCaptured": captured, "screenshot": captured ? imageFile.lastPathComponent : "unavailable",
        "nativeAcceptance": false, "productionRelease": false,
        "scope": "Real bundled Host/resources, fresh local init, normal save-before-quit, reopen; no editor, permissions, accessibility or full feature acceptance."
    ]
    let encoded = try JSONSerialization.data(withJSONObject: proof, options: [.prettyPrinted, .sortedKeys])
    try encoded.write(to: proofFile, options: .atomic)
    begin("complete")
    saveObservations("bundle-smoke-observations.json")
    stopConsole()
    print(String(decoding: encoded, as: UTF8.self))
} catch {
    progress("FAILED: \(error)")
    saveObservations("bundle-smoke-failure.json", extra: ["success": false, "error": String(describing: error)])
    stopConsole()
    // Cleanup requests are never counted as successful graceful-quit evidence.
    for app in owned where !app.isTerminated { _ = app.terminate() }
    fputs("Bundle smoke failed: \(error)\n", stderr)
    exit(1)
}
#else
import Foundation
fputs("Bundle smoke requires a real macOS GUI runner.\n", stderr)
exit(78)
#endif
