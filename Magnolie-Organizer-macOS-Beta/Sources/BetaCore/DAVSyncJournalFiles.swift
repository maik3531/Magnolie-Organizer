import Foundation
import CryptoKit
import Darwin

/// Private, exclusively leased journal directory. Profile-store lifetime and permissions are separate.
public final class DAVSyncJournalFiles {
    public let directory: URL
    public let namespace: String
    internal let file: URL
    private var lease: Int32 = -1
    private var directoryIdentity = stat()
    private var leaseIdentity = stat()
    private let guardLock = NSRecursiveLock()
    private var activeOwner: UUID?
    private var invalidated = false
    private let checkpoint: (String) throws -> Void
    public convenience init(profileDirectory: URL) throws { try self.init(profileDirectory: profileDirectory, checkpoint: { _ in }) }
    internal init(profileDirectory: URL, checkpoint: @escaping (String) throws -> Void) throws {
        self.checkpoint = checkpoint
        let parent = profileDirectory.standardizedFileURL
        try Self.validateDirectory(parent)
        directory = parent.appendingPathComponent("DAVSync-Journal", isDirectory: true)
        var info = stat()
        if lstat(directory.path, &info) != 0 {
            guard errno == ENOENT, mkdir(directory.path, mode_t(0o700)) == 0 else { throw DAVSyncJournalError.unsafeStorage }
            try Self.synchronizeDirectory(parent)
        }
        try Self.validateDirectory(directory)
        file = directory.appendingPathComponent("journal-v1.enc")
        namespace = SHA256.hash(data: Data(("Magnolie-DAV-journal-store-v1\0" + directory.path).utf8)).map { String(format: "%02x", $0) }.joined()
        let lockFile = directory.appendingPathComponent("journal.lock")
        let descriptor = open(lockFile.path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, mode_t(0o600))
        guard descriptor >= 0 else { throw DAVSyncJournalError.unsafeStorage }
        guard fstat(descriptor, &info) == 0, Self.privateRegular(info) else { close(descriptor); throw DAVSyncJournalError.unsafeStorage }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else { close(descriptor); throw DAVSyncJournalError.busy }
        lease = descriptor
        leaseIdentity = info
        guard lstat(directory.path, &directoryIdentity) == 0 else { close(lease); lease = -1; throw DAVSyncJournalError.unsafeStorage }
        do { try Self.synchronizeDirectory(directory) }
        catch { close(lease); lease = -1; throw error }
    }
    deinit { if lease >= 0 { close(lease) } }
    private static func privateRegular(_ info: stat) -> Bool {
        info.st_uid == getuid() && info.st_nlink == 1 && info.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG) && info.st_mode & 0o077 == 0
    }
    private static func validateDirectory(_ directory: URL) throws {
        var info = stat()
        guard directory.path == directory.resolvingSymlinksInPath().path,
              lstat(directory.path, &info) == 0, info.st_uid == getuid(),
              info.st_mode & mode_t(S_IFMT) == mode_t(S_IFDIR), info.st_mode & 0o077 == 0 else { throw DAVSyncJournalError.unsafeStorage }
    }
    private static func synchronizeDirectory(_ directory: URL) throws {
        try validateDirectory(directory)
        let descriptor = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw DAVSyncJournalError.unsafeStorage }
        defer { close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_uid == getuid(), info.st_mode & mode_t(S_IFMT) == mode_t(S_IFDIR),
              info.st_mode & 0o077 == 0, fsync(descriptor) == 0 else { throw DAVSyncJournalError.unsafeStorage }
    }
    private func validateLease() throws {
        guard !invalidated, lease >= 0 else { throw DAVSyncJournalError.poisoned }
        var directoryNow = stat(), lockNow = stat(), descriptorNow = stat()
        let lockFile = directory.appendingPathComponent("journal.lock")
        guard lstat(directory.path, &directoryNow) == 0, directoryNow.st_dev == directoryIdentity.st_dev,
              directoryNow.st_ino == directoryIdentity.st_ino,
              lstat(lockFile.path, &lockNow) == 0, Self.privateRegular(lockNow),
              lockNow.st_dev == leaseIdentity.st_dev, lockNow.st_ino == leaseIdentity.st_ino,
              fstat(lease, &descriptorNow) == 0, Self.privateRegular(descriptorNow),
              descriptorNow.st_dev == leaseIdentity.st_dev, descriptorNow.st_ino == leaseIdentity.st_ino else {
            invalidated = true; throw DAVSyncJournalError.externalChange
        }
        do { try Self.validateDirectory(directory) }
        catch { invalidated = true; throw error }
    }
    internal func claimOwner() throws -> UUID {
        guardLock.lock(); defer { guardLock.unlock() }
        try validateLease()
        guard activeOwner == nil else { throw DAVSyncJournalError.busy }
        let token = UUID(); activeOwner = token; return token
    }
    internal func releaseOwner(_ token: UUID) {
        guardLock.lock(); defer { guardLock.unlock() }
        if activeOwner == token { activeOwner = nil }
    }
    private func guarded<T>(_ owner: UUID?, _ body: () throws -> T) throws -> T {
        guardLock.lock(); defer { guardLock.unlock() }
        guard activeOwner == owner else { throw DAVSyncJournalError.busy }
        try validateLease()
        let result = try body()
        try validateLease()
        return result
    }
    internal func read(owner: UUID? = nil) throws -> Data? {
        try guarded(owner) { try AtomicStore.read(file, maximumBytes: DAVSyncJournalStore.maximumBytes) }
    }
    internal func write(_ data: Data, owner: UUID? = nil) throws {
        try guarded(owner) {
            guard data.count <= DAVSyncJournalStore.maximumBytes else { throw DAVSyncJournalError.capacity }
            try AtomicStore.write(data, to: file) { point in
                try self.validateLease()
                try self.checkpoint(point)
                try self.validateLease()
            }
            guard try read(owner: owner) == data else { throw DAVSyncJournalError.externalChange }
            try checkpoint("readback")
        }
    }
    /// Reestablish a complete readable file's durability after an uncertain previous publication.
    internal func reopenBarrier(expected: Data?, owner: UUID? = nil) throws {
        try guarded(owner) {
            guard let expected else { try Self.synchronizeDirectory(directory); return }
            let descriptor = open(file.path, O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
            guard descriptor >= 0 else { throw DAVSyncJournalError.unsafeStorage }
            defer { close(descriptor) }
            var info = stat()
            guard fstat(descriptor, &info) == 0, Self.privateRegular(info), info.st_size == expected.count,
                  try read(owner: owner) == expected, fsync(descriptor) == 0, fcntl(descriptor, F_FULLFSYNC) == 0 else { throw DAVSyncJournalError.unsafeStorage }
            try Self.synchronizeDirectory(directory)
            guard try read(owner: owner) == expected else { throw DAVSyncJournalError.externalChange }
        }
    }
}
