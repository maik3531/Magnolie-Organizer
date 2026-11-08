#if os(macOS)
import Foundation
import XCTest
import Darwin
@testable import BetaCore

private struct DomainProbeResult { let status: Int32; let timedOut: Bool; let cleanupFinished: Bool }

/// The actual domain checks run under NSApplication.run() in an owned child,
/// rather than injecting native input into XCTest's nonrunning NSApplication.
final class NativeDomainAcceptanceTests: XCTestCase {
    func testActualHealthCustomDrawingDurableSaveAndReopen() async throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_UI_PATH"] else { throw XCTSkip("Supply generated UI on a real Mac.") }
        let helper = Bundle(for: NativeDomainAcceptanceTests.self).bundleURL.deletingLastPathComponent().appendingPathComponent("DomainsNativeProbe")
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: helper.path))
        let package = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let harness = package.deletingLastPathComponent().appendingPathComponent("port-adapters/tests/domain-scenarios.js")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let logURL = directory.appendingPathComponent("probe.log")
        XCTAssertTrue(FileManager.default.createFile(atPath: logURL.path, contents: nil))
        let log = try FileHandle(forWritingTo: logURL)
        defer { try? log.close() }
        let result: DomainProbeResult = try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let child = Process(); child.executableURL = helper
                child.arguments = [path, harness.path, directory.path]
                child.standardOutput = log; child.standardError = log
                let terminated = DispatchSemaphore(value: 0)
                child.terminationHandler = { _ in terminated.signal() }
                do { try child.run() } catch { continuation.resume(throwing: error); return }
                let timeout = terminated.wait(timeout: .now() + 58) == .timedOut
                if timeout && child.isRunning {
                    child.terminate()
                    if terminated.wait(timeout: .now() + 1) == .timedOut && child.isRunning {
                        _ = Darwin.kill(child.processIdentifier, SIGKILL)
                        _ = terminated.wait(timeout: .now() + 1)
                    }
                }
                let cleaned = !child.isRunning
                if cleaned { child.waitUntilExit() }
                continuation.resume(returning: DomainProbeResult(status: cleaned ? child.terminationStatus : -1,
                    timedOut: timeout, cleanupFinished: cleaned))
            }
        }
        let logReader = try FileHandle(forReadingFrom: logURL)
        defer { try? logReader.close() }
        let logBytes = try logReader.read(upToCount: 131072) ?? Data()
        print("Mac domain owned-probe output: " + String(decoding: logBytes.prefix(131072), as: UTF8.self))
        XCTAssertTrue(result.cleanupFinished, "Owned domain probe must terminate and reap")
        XCTAssertFalse(result.timedOut, "Domain probe exceeded its60-second total deadline including cleanup")
        let proofURL = directory.appendingPathComponent("proof.json")
        guard FileManager.default.fileExists(atPath: proofURL.path) else { return XCTFail("Domain probe produced no proof; exit=\(result.status)") }
        let proofReader = try FileHandle(forReadingFrom: proofURL)
        defer { try? proofReader.close() }
        let data = try proofReader.read(upToCount: 131073) ?? Data()
        XCTAssertLessThanOrEqual(data.count, 131072)
        guard data.count <= 131072 else { return }
        let proof = try Document.object(String(decoding: data, as: UTF8.self))
        print("Mac domain owned-probe proof: " + (try Document.encode(proof)))
        XCTAssertEqual(result.status, 0, "Native domain phase: \(proof["phase"] as? String ?? "unknown"); \(proof["error"] as? String ?? "")")
        XCTAssertEqual(proof["ok"] as? Bool, true)
        for key in ["healthForms", "customDesignerForms", "strictReopen"] { XCTAssertEqual(proof[key] as? Bool, true, key) }
        XCTAssertEqual(proof["productionHostDialogsTested"] as? Bool, false)
        let lifecycle = try XCTUnwrap(proof["applicationLifecycle"] as? [String: Any])
        for key in ["running", "active", "keyWindow", "visible"] { XCTAssertEqual(lifecycle[key] as? Bool, true, key) }
        XCTAssertGreaterThan(proof["nativeDurableSaves"] as? Int ?? 0, 0)
        let drawing = try XCTUnwrap(proof["drawing"] as? [String: Any])
        XCTAssertEqual(drawing["strokeCount"] as? Int, 1)
        XCTAssertEqual(drawing["pixelChange"] as? Bool, true)
        XCTAssertEqual(drawing["undoRedo"] as? Bool, true)
        let pointer = try XCTUnwrap(drawing["pointer"] as? [String: Any])
        for key in ["down", "move", "up"] { XCTAssertGreaterThan(pointer[key] as? Int ?? 0, 0, key) }
        XCTAssertEqual(pointer["untrusted"] as? Int, 0)
    }
}
#endif
