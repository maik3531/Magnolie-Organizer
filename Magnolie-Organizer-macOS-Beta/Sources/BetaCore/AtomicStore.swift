import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

public final class AtomicStore {
    public let file: URL
    private let directory: URL
    private var lease: Int32 = -1
    private var expected: Data?
    private var loaded = false
    private var poisoned = false

    public init(directory: URL) throws {
        self.directory = directory.standardizedFileURL
        file = self.directory.appendingPathComponent("organizer.json")
        let fm = FileManager.default
        if !fm.fileExists(atPath: directory.path) {
            try fm.createDirectory(at: directory, withIntermediateDirectories: false,
                                   attributes: [.posixPermissions: 0o700])
        }
        guard directory.standardizedFileURL.path == directory.resolvingSymlinksInPath().path else {
            throw BetaError("Symlinked profile directories are not permitted.")
        }
        var info = stat()
        guard lstat(directory.path, &info) == 0, info.st_uid == getuid(),
              (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFDIR), info.st_mode & 0o077 == 0 else {
            throw BetaError("Profile must be a private, owner-controlled directory (0700).")
        }
        let lock = directory.appendingPathComponent("profile.lock")
        lease = open(lock.path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard lease >= 0 else { throw BetaError("Cannot open profile lease.") }
        guard fstat(lease, &info) == 0, info.st_uid == getuid(), info.st_nlink == 1,
              (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG), info.st_mode & 0o077 == 0,
              flock(lease, LOCK_EX | LOCK_NB) == 0 else {
            close(lease); lease = -1
            throw BetaError("Profile is unsafe or already open in another macOS Beta process.")
        }
    }
    deinit { if lease >= 0 { close(lease) } }

    public func load() throws -> String? {
        guard !loaded else { throw BetaError("Profile already loaded.") }
        expected = try Self.read(file)
        loaded = true
        guard let data = expected else { return nil }
        guard let text = String(data: data, encoding: .utf8) else { poisoned = true; throw BetaError("Invalid UTF-8; file retained.") }
        return text
    }

    public func commit(_ text: String, preservingCurrent: Bool = false) throws {
        guard loaded, !poisoned else { throw BetaError("Storage is not writable. Restart and inspect the original file.") }
        let data = Data(text.utf8)
        _ = try Document.object(text)
        guard try Self.read(file) == expected else { throw BetaError("Profile changed externally; refusing overwrite.") }
        if preservingCurrent { _ = try checkpoint() }
        do {
            try Self.write(data, to: file)
            expected = data
        } catch {
            // An error after rename has an uncertain commit outcome. Do not acknowledge or retry in-session.
            poisoned = true
            throw error
        }
    }

    /// Exact on-disk bytes, including the encrypted envelope. Never a plaintext shadow
    /// of an encrypted profile. A failed checkpoint prevents the destructive commit.
    @discardableResult public func checkpoint() throws -> URL {
        guard loaded, !poisoned, let expected, try Self.read(file) == expected else {
            throw BetaError("The required recovery snapshot could not be created.")
        }
        let recovery = directory.appendingPathComponent("Recovery-macOS-Beta")
        let fm = FileManager.default
        if !fm.fileExists(atPath: recovery.path) {
            try fm.createDirectory(at: recovery, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            let fd = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard fd >= 0 else { throw BetaError("Cannot synchronize recovery directory.") }
            defer { close(fd) }
            guard fsync(fd) == 0 else { throw BetaError("Cannot synchronize recovery directory.") }
        }
        var info = stat()
        guard lstat(recovery.path, &info) == 0, info.st_uid == getuid(),
              info.st_mode & mode_t(S_IFMT) == mode_t(S_IFDIR), info.st_mode & 0o077 == 0 else {
            throw BetaError("Unsafe recovery directory.")
        }
        let path = recovery.appendingPathComponent("Magnolie Organizer macOS Beta-" + UUID().uuidString + ".json")
        try Self.write(expected, to: path)
        guard try Self.read(path) == expected, try Self.read(file) == expected else {
            throw BetaError("Recovery verification failed; profile was not replaced.")
        }
        return path
    }

    public static func read(_ url: URL, requirePrivate: Bool = true) throws -> Data? {
        let fd = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        if fd < 0 {
            if errno == ENOENT { return nil }
            throw BetaError("Cannot read file safely; no empty-document fallback.")
        }
        defer { close(fd) }
        var info = stat()
        guard fstat(fd, &info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              info.st_nlink == 1, (!requirePrivate || (info.st_uid == getuid() && info.st_mode & 0o077 == 0)),
              info.st_size > 0, info.st_size <= Document.maximumBytes else {
            throw BetaError("File is empty, oversized, linked or not private (0600). Original retained.")
        }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
        let data = try handle.read(upToCount: Int(info.st_size) + 1) ?? Data()
        var after = stat()
        guard data.count == info.st_size, fstat(fd, &after) == 0, after.st_size == info.st_size else {
            throw BetaError("File changed while reading.")
        }
        return data
    }

    public static func write(_ data: Data, to destination: URL) throws {
        guard !data.isEmpty, data.count <= Document.maximumBytes else { throw BetaError("Invalid output size.") }
        let parent = destination.deletingLastPathComponent()
        guard parent.standardizedFileURL.path == parent.resolvingSymlinksInPath().path else {
            throw BetaError("Symlinked output directory is not permitted.")
        }
        var info = stat()
        if lstat(destination.path, &info) == 0 {
            guard (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG), info.st_nlink == 1,
                  info.st_uid == getuid() else { throw BetaError("Unsafe output destination.") }
        } else if errno != ENOENT { throw BetaError("Cannot inspect output destination.") }
        let temp = parent.appendingPathComponent(".macOS-Beta-" + UUID().uuidString + ".tmp")
        let fd = open(temp.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard fd >= 0 else { throw BetaError("Cannot create private temporary file.") }
        defer { close(fd); unlink(temp.path) }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
        try handle.write(contentsOf: data)
        guard fsync(fd) == 0 else { throw BetaError("File synchronization failed.") }
        #if canImport(Darwin)
        guard fcntl(fd, F_FULLFSYNC) == 0 else { throw BetaError("Durable file synchronization failed.") }
        #endif
        let dirfd = open(parent.path, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW)
        guard dirfd >= 0 else { throw BetaError("Cannot synchronize output directory.") }
        defer { close(dirfd) }
        guard rename(temp.path, destination.path) == 0 else { throw BetaError("Atomic replacement failed.") }
        guard fsync(dirfd) == 0 else { throw BetaError("Directory synchronization failed; restart before further writes.") }
    }
}
