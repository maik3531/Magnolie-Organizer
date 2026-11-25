import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Refs #721. The runtime accepts only the receiver shipped inside this app.
/// Inspecting a bundle never launches a service or installs a dependency.
public struct AirPlayBundle {
    public enum Failure: Error, Equatable, LocalizedError {
        case missing, manifest, unsafePath, privateState
        public var errorDescription: String? {
            switch self {
            case .missing: return "This Magnolie build does not contain the iPhone receiver."
            case .manifest, .unsafePath: return "The bundled iPhone receiver is incomplete or incompatible."
            case .privateState: return "The private iPhone pairing storage could not be opened safely."
            }
        }
    }
    private struct Manifest: Decodable {
        struct Runtime: Decodable { let pluginDirectory: String; let pluginScanner: String; let gioModules: String }
        let schemaVersion: Int
        let protocolVersion: Int
        let helper: String
        let uxplayVersion: String
        let uxplayCommit: String
        let architecture: String
        let minimumSystemVersion: String
        let dependencyClosureVerified: Bool
        let runtime: Runtime
    }
    public let executable: URL
    public let pluginDirectory: URL
    public let pluginScanner: URL
    public let gioModules: URL

    public static var hostArchitecture: String {
        #if arch(arm64)
        return "arm64"
        #elseif arch(x86_64)
        return "x86_64"
        #else
        return "unsupported"
        #endif
    }

    public init(contents: URL, expectedArchitecture: String = AirPlayBundle.hostArchitecture) throws {
        let root = contents.standardizedFileURL.resolvingSymlinksInPath()
        let manifestFile = root.appendingPathComponent("Resources/AirPlay/manifest.json")
        guard FileManager.default.fileExists(atPath: manifestFile.path) else { throw Failure.missing }
        let checkedManifest = try Self.child("Resources/AirPlay/manifest.json", root: root, directory: false)
        let size = try checkedManifest.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
        guard size <= 32_768 else { throw Failure.manifest }
        let manifest: Manifest
        do { manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: checkedManifest)) }
        catch { throw Failure.manifest }
        guard manifest.schemaVersion == 1, manifest.protocolVersion == 1,
              manifest.helper == "Helpers/magnolie-airplay-receiver",
              manifest.uxplayVersion == "1.73.7",
              manifest.uxplayCommit == "df67c212a433cf6dda3676dd40c097900d24e645",
              ["arm64", "x86_64"].contains(expectedArchitecture), manifest.architecture == expectedArchitecture,
              manifest.minimumSystemVersion == "12.7", manifest.dependencyClosureVerified else { throw Failure.manifest }
        for path in [manifest.runtime.pluginDirectory, manifest.runtime.pluginScanner, manifest.runtime.gioModules] {
            guard path.hasPrefix("Frameworks/GStreamer.framework/") else { throw Failure.unsafePath }
        }
        executable = try Self.child(manifest.helper, root: root, directory: false, executable: true)
        pluginDirectory = try Self.child(manifest.runtime.pluginDirectory, root: root, directory: true)
        pluginScanner = try Self.child(manifest.runtime.pluginScanner, root: root, directory: false, executable: true)
        gioModules = try Self.child(manifest.runtime.gioModules, root: root, directory: true)
    }

    private static func child(_ path: String, root: URL, directory: Bool, executable: Bool = false) throws -> URL {
        let parts = path.split(separator: "/", omittingEmptySubsequences: false)
        guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
              !path.contains("\\"), !path.contains("\0") else { throw Failure.unsafePath }
        let url = root.appendingPathComponent(path).resolvingSymlinksInPath()
        guard url.path.hasPrefix(root.path + "/") else { throw Failure.unsafePath }
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isDirectoryKey])
        guard (directory ? values.isDirectory == true : values.isRegularFile == true) else { throw Failure.unsafePath }
        if executable && !FileManager.default.isExecutableFile(atPath: url.path) { throw Failure.unsafePath }
        return url
    }

    /// Build an environment from an allowlist, never inherit DYLD/GStreamer/user
    /// plugin or UxPlay configuration variables from a shell that started the app.
    public func environment(sessionDirectory: URL) -> [String: String] {
        let registry = sessionDirectory.appendingPathComponent("gstreamer-registry.bin").path
        return ["PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "LC_ALL": "C",
                "TMPDIR": sessionDirectory.path + "/", "XDG_CACHE_HOME": sessionDirectory.path,
                "XDG_CONFIG_HOME": sessionDirectory.path,
                "GST_PLUGIN_SYSTEM_PATH": pluginDirectory.path, "GST_PLUGIN_SYSTEM_PATH_1_0": pluginDirectory.path,
                "GST_PLUGIN_PATH": "", "GST_PLUGIN_PATH_1_0": "",
                "GST_PLUGIN_SCANNER": pluginScanner.path, "GST_PLUGIN_SCANNER_1_0": pluginScanner.path,
                "GST_REGISTRY": registry, "GST_REGISTRY_1_0": registry,
                "GIO_EXTRA_MODULES": gioModules.path, "GIO_MODULE_DIR": gioModules.path]
    }
}

/// Pairing survives explicit receiver restarts; PINs and raw logs are not stored.
/// The existing Organizer profile lease prevents a second app owning this state.
public struct AirPlayPrivateState {
    public let directory: URL
    public let configuration: URL
    public let registration: URL
    public let key: URL
    public let sessionDirectory: URL

    public init(profileDirectory: URL) throws {
        try Self.checkDirectory(profileDirectory)
        directory = profileDirectory.appendingPathComponent("AirPlay", isDirectory: true)
        if !FileManager.default.fileExists(atPath: directory.path) {
            guard mkdir(directory.path, mode_t(0o700)) == 0 else { throw AirPlayBundle.Failure.privateState }
        }
        try Self.checkDirectory(directory)
        registration = directory.appendingPathComponent("registered-iphones")
        key = directory.appendingPathComponent("receiver.pem")
        try Self.checkFileIfPresent(registration, maximumBytes: 1_048_576)
        try Self.checkFileIfPresent(key, maximumBytes: 65_536)
        sessionDirectory = directory.appendingPathComponent("session-" + UUID().uuidString, isDirectory: true)
        guard mkdir(sessionDirectory.path, mode_t(0o700)) == 0 else { throw AirPlayBundle.Failure.privateState }
        configuration = sessionDirectory.appendingPathComponent("receiver.conf")
        let descriptor = open(configuration.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else {
            try? FileManager.default.removeItem(at: sessionDirectory)
            throw AirPlayBundle.Failure.privateState
        }
        close(descriptor)
    }

    public func arguments(receiverName: String) -> [String] {
        // Native name is bounded and fixed by the host, never supplied by web/UI content.
        ["-rc", configuration.path, "-n", receiverName, "-nh", "-pin",
         "-reg", registration.path, "-key", key.path]
    }
    public func removeSession() {
        // Remove only the UUID directory made by this object, after its child exits.
        guard (try? Self.checkDirectory(sessionDirectory)) != nil else { return }
        try? FileManager.default.removeItem(at: sessionDirectory)
    }
    private static func checkDirectory(_ url: URL) throws {
        var info = stat()
        guard url.standardizedFileURL.path == url.resolvingSymlinksInPath().path,
              lstat(url.path, &info) == 0, info.st_uid == getuid(),
              info.st_mode & mode_t(S_IFMT) == mode_t(S_IFDIR), info.st_mode & 0o077 == 0 else {
            throw AirPlayBundle.Failure.privateState
        }
    }
    private static func checkFileIfPresent(_ url: URL, maximumBytes: Int64) throws {
        var info = stat()
        if lstat(url.path, &info) != 0 {
            guard errno == ENOENT else { throw AirPlayBundle.Failure.privateState }; return
        }
        guard info.st_uid == getuid(), info.st_nlink == 1, info.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),
              info.st_mode & 0o077 == 0, info.st_size <= maximumBytes else { throw AirPlayBundle.Failure.privateState }
    }
}
