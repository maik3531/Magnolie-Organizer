import Foundation
import XCTest
@testable import BetaCore

final class AirPlayBundleTests: XCTestCase {
    private let fm = FileManager.default
    private func temporary() throws -> URL {
        let root = fm.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("airplay-test-" + UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        return root
    }
    private func write(_ text: String, _ url: URL, mode: Int = 0o600) throws {
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(text.utf8).write(to: url)
        try fm.setAttributes([.posixPermissions: mode], ofItemAtPath: url.path)
    }
    private func manifest() -> [String: Any] {
        ["schemaVersion": 1, "protocolVersion": 1, "helper": "Helpers/magnolie-airplay-receiver",
         "uxplayVersion": "1.73.7", "uxplayCommit": "df67c212a433cf6dda3676dd40c097900d24e645",
         "architecture": "arm64", "minimumSystemVersion": "12.7", "dependencyClosureVerified": true,
         "runtime": ["pluginDirectory": "Frameworks/GStreamer.framework/Versions/Current/lib/gstreamer-1.0",
                     "pluginScanner": "Frameworks/GStreamer.framework/Versions/Current/libexec/gstreamer-1.0/gst-plugin-scanner",
                     "gioModules": "Frameworks/GStreamer.framework/Versions/Current/lib/gio/modules"]]
    }
    private func saveManifest(_ value: [String: Any], _ root: URL) throws {
        let file = root.appendingPathComponent("Resources/AirPlay/manifest.json")
        try fm.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONSerialization.data(withJSONObject: value).write(to: file)
    }
    private func fixture(_ root: URL) throws {
        let base = root.appendingPathComponent("Frameworks/GStreamer.framework/Versions")
        try fm.createDirectory(at: base.appendingPathComponent("1.0/lib/gstreamer-1.0"), withIntermediateDirectories: true)
        try fm.createDirectory(at: base.appendingPathComponent("1.0/lib/gio/modules"), withIntermediateDirectories: true)
        try write("fixture", base.appendingPathComponent("1.0/libexec/gstreamer-1.0/gst-plugin-scanner"), mode: 0o700)
        try fm.createSymbolicLink(atPath: base.appendingPathComponent("Current").path, withDestinationPath: "1.0")
        try write("fixture", root.appendingPathComponent("Helpers/magnolie-airplay-receiver"), mode: 0o700)
        try saveManifest(manifest(), root)
    }

    func testBundledFrameworkCurrentLinkAndEnvironment() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        try fixture(root)
        let bundle = try AirPlayBundle(contents: root, expectedArchitecture: "arm64")
        XCTAssertTrue(bundle.pluginDirectory.path.contains("/Versions/1.0/"))
        let environment = bundle.environment(sessionDirectory: root.appendingPathComponent("session"))
        XCTAssertEqual(environment["GST_PLUGIN_PATH_1_0"], "")
        XCTAssertNil(environment["DYLD_INSERT_LIBRARIES"])
        XCTAssertNil(environment["UXPLAYRC"])
        XCTAssertNil(environment["HOME"])
        XCTAssertEqual(environment["GST_PLUGIN_SCANNER_1_0"], bundle.pluginScanner.path)
        XCTAssertTrue(environment["GST_REGISTRY"]!.hasPrefix(root.path + "/session/"))
    }

    func testNoManifestMeansUnavailableWithoutCreatingFiles() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        XCTAssertThrowsError(try AirPlayBundle(contents: root)) { XCTAssertEqual($0 as? AirPlayBundle.Failure, .missing) }
        XCTAssertTrue(try fm.contentsOfDirectory(atPath: root.path).isEmpty)
    }

    func testIncompatibleUnverifiedManifestAndArchitectureAreRejected() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        try fixture(root)
        for (key, bad) in [("protocolVersion", 2 as Any), ("dependencyClosureVerified", false as Any),
                           ("uxplayCommit", "moving-main" as Any), ("minimumSystemVersion", "15.0" as Any)] {
            var value = manifest(); value[key] = bad; try saveManifest(value, root)
            XCTAssertThrowsError(try AirPlayBundle(contents: root, expectedArchitecture: "arm64"))
        }
        try saveManifest(manifest(), root)
        XCTAssertThrowsError(try AirPlayBundle(contents: root, expectedArchitecture: "x86_64"))
    }

    func testNoExternalOrTraversalRuntimePaths() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        try fixture(root)
        for path in ["/opt/homebrew/lib", "Frameworks/GStreamer.framework/../../../../tmp", "Frameworks/GStreamer.framework//lib"] {
            var value = manifest(); var runtime = value["runtime"] as! [String: String]
            runtime["pluginDirectory"] = path; value["runtime"] = runtime; try saveManifest(value, root)
            XCTAssertThrowsError(try AirPlayBundle(contents: root, expectedArchitecture: "arm64"))
        }
    }

    func testSymlinkEscapeAndNonExecutableHelperAreRejected() throws {
        let root = try temporary(), outside = try temporary()
        defer { try? fm.removeItem(at: root); try? fm.removeItem(at: outside) }
        try fixture(root)
        let helper = root.appendingPathComponent("Helpers/magnolie-airplay-receiver")
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: helper.path)
        XCTAssertThrowsError(try AirPlayBundle(contents: root, expectedArchitecture: "arm64"))
        try fm.removeItem(at: helper)
        let replacement = outside.appendingPathComponent("receiver")
        try write("fixture", replacement, mode: 0o700)
        try fm.createSymbolicLink(at: helper, withDestinationURL: replacement)
        XCTAssertThrowsError(try AirPlayBundle(contents: root, expectedArchitecture: "arm64"))
    }

    func testPrivateStateOwnsOnlySessionAndPreservesPairing() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        let state = try AirPlayPrivateState(profileDirectory: root)
        try write("private fixture", state.registration)
        try write("private fixture", state.key)
        XCTAssertEqual(try Data(contentsOf: state.configuration).count, 0)
        XCTAssertEqual((try fm.attributesOfItem(atPath: state.configuration.path)[.posixPermissions] as! NSNumber).intValue & 0o777, 0o600)
        let arguments = state.arguments(receiverName: "Magnolie Test")
        XCTAssertEqual(arguments, ["-rc", state.configuration.path, "-n", "Magnolie Test", "-nh", "-pin",
                                  "-reg", state.registration.path, "-key", state.key.path])
        state.removeSession()
        XCTAssertFalse(fm.fileExists(atPath: state.sessionDirectory.path))
        XCTAssertEqual(try String(contentsOf: state.registration, encoding: .utf8), "private fixture")
        XCTAssertTrue(fm.fileExists(atPath: state.key.path))
        let next = try AirPlayPrivateState(profileDirectory: root)
        XCTAssertNotEqual(state.sessionDirectory, next.sessionDirectory)
        next.removeSession()
    }

    func testSharedStateOrSymlinkedKeyNeverStarts() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        let state = try AirPlayPrivateState(profileDirectory: root); state.removeSession()
        try write("fixture", root.appendingPathComponent("unrelated-key"))
        try fm.createSymbolicLink(at: state.key, withDestinationURL: root.appendingPathComponent("unrelated-key"))
        XCTAssertThrowsError(try AirPlayPrivateState(profileDirectory: root))
        try fm.removeItem(at: state.key)
        try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: state.directory.path)
        XCTAssertThrowsError(try AirPlayPrivateState(profileDirectory: root))
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("unrelated-key"), encoding: .utf8), "fixture")
    }

    func testOversizedPairingStateIsRejectedWithoutNewSession() throws {
        let root = try temporary(); defer { try? fm.removeItem(at: root) }
        let state = try AirPlayPrivateState(profileDirectory: root); state.removeSession()
        try write(String(repeating: "a", count: 65_537), state.key)
        XCTAssertThrowsError(try AirPlayPrivateState(profileDirectory: root))
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: state.directory.path), ["receiver.pem"])
    }
}
