import XCTest
@testable import BetaCore

final class PrintDocumentTests: XCTestCase {
    func testImmutableSnapshotPolicyAndUtf8Boundary() throws {
        let page = try PrintDocument.isolatedHTML("<h1>Report</h1><script>forbidden()</script>")
        XCTAssertTrue(page.hasPrefix("<!DOCTYPE html><html><head><meta http-equiv=\"Content-Security-Policy\""))
        let full = try PrintDocument.isolatedHTML("<!doctype html><html><head><title>Print</title></head><body>Record</body></html>")
        XCTAssertTrue(full.hasPrefix("<!doctype html><meta http-equiv="))
        XCTAssertLessThan(try XCTUnwrap(full.range(of: "script-src")).lowerBound, try XCTUnwrap(full.range(of: "<title>")).lowerBound)
        for directive in ["default-src 'none'", "script-src 'none'", "frame-src 'none'", "connect-src 'none'", "base-uri 'none'", "form-action 'none'"] {
            XCTAssertTrue(page.contains(directive))
        }
        XCTAssertThrowsError(try PrintDocument.isolatedHTML(""))
        XCTAssertNoThrow(try PrintDocument.isolatedHTML(String(repeating: "é", count: 375_000)))
        XCTAssertThrowsError(try PrintDocument.isolatedHTML(String(repeating: "é", count: 375_001)))
    }
    func testTypedPrintRequestOptionalCorrelationAndUnknownFields() throws {
        XCTAssertEqual(try Request(#"{"cmd":"drucken","html":"<p>Snapshot</p>","requestId":"print-1"}"#).command, .drucken)
        XCTAssertNoThrow(try Request(#"{"cmd":"drucken","html":"<p>Snapshot</p>"}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"drucken","html":42}"#))
        XCTAssertThrowsError(try Request(#"{"cmd":"drucken","html":"<p>Snapshot</p>","path":"/private/profile"}"#))
    }
}

#if os(macOS)
import AppKit
import PDFKit
import Darwin

private struct PrintProbeResult { let status: Int32; let timedOut: Bool; let cleanupFinished: Bool }

final class NativePrintTests: XCTestCase {
    func testIsolatedRendererAndRealAppKitPdfOutput() async throws {
        guard let fixture = ProcessInfo.processInfo.environment["MACOS_BETA_EDITOR_FIXTURES"] else {
            throw XCTSkip("Actual shared print fixture is supplied by tools/check_editor.py on the Mac runner.")
        }
        let helper = Bundle(for: NativePrintTests.self).bundleURL.deletingLastPathComponent().appendingPathComponent("PrintNativeProbe")
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: helper.path), "SPM must build the native print test-support executable")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let result: PrintProbeResult = try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let child = Process()
                child.executableURL = helper
                child.arguments = [fixture, directory.path]
                child.standardOutput = FileHandle.nullDevice
                child.standardError = FileHandle.nullDevice
                let terminated = DispatchSemaphore(value: 0)
                child.terminationHandler = { _ in terminated.signal() }
                do { try child.run() } catch { continuation.resume(throwing: error); return }
                let timeout = terminated.wait(timeout: .now() + 28) == .timedOut
                if timeout && child.isRunning {
                    child.terminate() // Exact direct child; never a global process lookup.
                    if terminated.wait(timeout: .now() + 1) == .timedOut && child.isRunning {
                        _ = Darwin.kill(child.processIdentifier, SIGKILL)
                        _ = terminated.wait(timeout: .now() + 1)
                    }
                }
                let cleaned = !child.isRunning
                if cleaned { child.waitUntilExit() }
                continuation.resume(returning: PrintProbeResult(status: cleaned ? child.terminationStatus : -1,
                    timedOut: timeout, cleanupFinished: cleaned))
            }
        }
        XCTAssertTrue(result.cleanupFinished, "Owned print probe must terminate and reap")
        XCTAssertFalse(result.timedOut, "Native print probe exceeded its 30-second deadline including cleanup")
        let proofURL = directory.appendingPathComponent("proof.json")
        if !FileManager.default.fileExists(atPath: proofURL.path) {
            XCTFail("Native print probe produced no completion proof; status=\(result.status)"); return
        }
        let data = try Data(contentsOf: proofURL)
        XCTAssertLessThan(data.count, 8192)
        let proof = try Document.object(String(decoding: data, as: UTF8.self))
        XCTAssertEqual(result.status, 0, "Native print phase: \(proof["phase"] as? String ?? "unknown")")
        XCTAssertEqual(proof["ok"] as? Bool, true)
        for key in ["ephemeral", "contentJavaScriptDisabled", "noInjectedScripts", "scriptAbsent", "bridgeAbsent"] {
            XCTAssertEqual(proof[key] as? Bool, true, key)
        }
        XCTAssertEqual(proof["compatMode"] as? String, "CSS1Compat")
        XCTAssertEqual(proof["imageGeometry"] as? [Int], [1,24,24])
        XCTAssertEqual(proof["fontStatus"] as? String, "loaded")
        XCTAssertEqual(proof["networkRequests"] as? Int, 0)
        XCTAssertEqual(proof["paperOutputConfirmed"] as? Bool, false)
        let bytes = try Data(contentsOf: directory.appendingPathComponent("actual-appkit-output.pdf"))
        XCTAssertTrue(bytes.starts(with: Data("%PDF-".utf8)))
        let pdf = try XCTUnwrap(PDFDocument(data: bytes))
        XCTAssertEqual(pdf.pageCount, 1)
        let bounds = try XCTUnwrap(pdf.page(at: 0)).bounds(for: .mediaBox)
        XCTAssertEqual(bounds.width, 595.2756, accuracy: 1)
        XCTAssertEqual(bounds.height, 841.8898, accuracy: 1)
        let text = pdf.string ?? ""
        XCTAssertTrue(text.contains("PrintProof"))
        XCTAssertTrue(text.contains("PDF evidence 2.0.30"))
        XCTAssertFalse(text.contains("SCRIPT_MUST_NOT_RUN"))
        XCTAssertFalse(text.contains("LOCAL_FILE_MUST_NOT_RENDER"))
        // Real AppKit PDF-engine evidence does not establish manual OS-panel/paper acceptance.
    }
}
#endif
