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
let deadline = ProcessInfo.processInfo.systemUptime + 90
var owned: [NSRunningApplication] = []
func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw SmokeError(message) }
}
func waitUntil(_ condition: () throws -> Bool) throws {
    while try !condition() {
        try require(ProcessInfo.processInfo.systemUptime < deadline, "90-second bundle smoke deadline exceeded")
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }
}
func launch(_ bundle: URL) throws -> NSRunningApplication {
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
    try waitUntil { finished }
    if let failure { throw failure }
    guard let app else { throw SmokeError("LaunchServices returned no application") }
    owned.append(app)
    try require(app.bundleURL?.resolvingSymlinksInPath() == bundle.resolvingSymlinksInPath(), "Unexpected launched bundle")
    try require(app.bundleIdentifier == "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta", "Unexpected launched identity")
    try require(!app.isTerminated, "Application exited before its window was available")
    return app
}
func windowID(_ app: NSRunningApplication) throws -> CGWindowID {
    var found: CGWindowID?
    try waitUntil {
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
    try require(!app.isTerminated && app.terminate(), "Normal application termination was refused")
    try waitUntil { app.isTerminated }
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
    do { try waitUntil { !capture.isRunning } }
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
    let support = try fm.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
    let directory = support.appendingPathComponent("io.gitlab.maik3531.MagnolieOrganizer.macOSBeta")
    // The runner must be disposable. Never reuse, replace or delete user data.
    try require(!fm.fileExists(atPath: directory.path), "Existing Beta profile refused; use a fresh disposable runner")
    try require(NSRunningApplication.runningApplications(withBundleIdentifier: "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta").isEmpty,
                "Existing Beta process refused")
    try fm.createDirectory(at: output, withIntermediateDirectories: true)
    let proofFile = output.appendingPathComponent("bundle-smoke.json")
    let imageFile = output.appendingPathComponent("bundle-window.png")
    try require(!fm.fileExists(atPath: proofFile.path) && !fm.fileExists(atPath: imageFile.path), "Existing smoke evidence refused")
    let file = directory.appendingPathComponent("organizer.json")
    let first = try launch(bundle)
    let window = try windowID(first)
    // Let the normal local document render; final disk assertions, not this
    // short settling interval or the process/window, establish functional success.
    let settle = ProcessInfo.processInfo.systemUptime + 3
    try waitUntil { try require(!first.isTerminated, "Application exited while rendering"); return ProcessInfo.processInfo.systemUptime >= settle }
    let captured = try screenshot(window, to: imageFile)
    try quit(first)
    let (initialBytes, initial) = try profile(file)
    let initialFileNumber = (try fm.attributesOfItem(atPath: file.path)[.systemFileNumber] as? NSNumber)?.uint64Value
    try require(initialFileNumber != nil, "Cannot identify first saved profile file")
    let directoryAttributes = try fm.attributesOfItem(atPath: directory.path)
    try require((directoryAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o700, "Profile directory permissions are not 0700")
    let second = try launch(bundle)
    _ = try windowID(second)
    let reloadSettle = ProcessInfo.processInfo.systemUptime + 3
    try waitUntil { try require(!second.isTerminated, "Application exited while reloading"); return ProcessInfo.processInfo.systemUptime >= reloadSettle }
    try quit(second)
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
    print(String(decoding: encoded, as: UTF8.self))
} catch {
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
