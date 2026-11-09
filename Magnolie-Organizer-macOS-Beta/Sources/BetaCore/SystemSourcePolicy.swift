import Foundation
import CryptoKit

/// Native identifiers are opaque. Never derive account credentials or filesystem paths.
public enum SystemSourcePolicy {
    public enum Kind: String, CaseIterable { case events, reminders, contacts }
    public static func uid(_ kind: Kind, _ identifier: String) -> String {
        "macos-\(kind.rawValue):" + Data(identifier.utf8).base64EncodedString()
    }
    public static func identifier(_ uid: String, kind: Kind) throws -> String {
        let prefix = "macos-\(kind.rawValue):"
        guard uid.hasPrefix(prefix), uid.utf8.count <= 4096,
              let data = Data(base64Encoded: String(uid.dropFirst(prefix.count))),
              let identifier = String(data: data, encoding: .utf8), !identifier.isEmpty,
              self.uid(kind, identifier) == uid else { throw BetaError("Invalid macOS source identifier.") }
        return identifier
    }
    public static func revision(_ value: [String: Any]) throws -> String {
        let bytes = Data(try Document.encode(value).utf8)
        return SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }
    public static func requireRevision(_ expected: String, actual: String) throws {
        guard expected.count == 64, expected == actual else {
            throw BetaError("The system item changed. Read it again before writing.")
        }
    }
    public static func requireAccess(_ state: String, kind: Kind) throws {
        guard state == "authorized" else {
            throw BetaError("macOS \(kind.rawValue) access is \(state). No system data was read or changed.")
        }
    }
    public static func requireWindow(start: Date, end: Date) throws {
        guard start.timeIntervalSince1970.isFinite, end.timeIntervalSince1970.isFinite,
              end > start, end.timeIntervalSince(start) <= 366 * 86400 * 4 else {
            throw BetaError("System calendar reads require a window of at most four years.")
        }
    }
}

/// Thread-safe cooperative cancellation, also checked between native records.
/// The monotonic deadline cannot be extended by changing the system clock.
public final class SystemSourceReadControl {
    private let lock = NSLock()
    private var cancelled = false
    private let deadline: TimeInterval
    public init(timeout: TimeInterval = 20) {
        deadline = ProcessInfo.processInfo.systemUptime + max(0, timeout)
    }
    public func cancel() { lock.lock(); cancelled = true; lock.unlock() }
    public func check() throws {
        lock.lock(); let stopped = cancelled; lock.unlock()
        if stopped { throw CancellationError() }
        if ProcessInfo.processInfo.systemUptime >= deadline {
            throw BetaError("The macOS source operation timed out. No read result was imported.")
        }
    }
}
