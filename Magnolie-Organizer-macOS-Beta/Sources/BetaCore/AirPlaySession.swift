import Foundation

public enum AirPlayFailure: Error, Equatable, CustomStringConvertible {
    case unavailable
    case alreadyRunning
    case launchFailed
    case startupTimeout
    case protocolViolation
    case receiverError(String)
    case unexpectedExit(Int32)

    public var description: String {
        switch self {
        case .unavailable: return "The AirPlay receiver is not included in this application."
        case .alreadyRunning: return "The AirPlay receiver is already running or stopping."
        case .launchFailed: return "The AirPlay receiver could not start."
        case .startupTimeout: return "The AirPlay receiver did not become ready in time."
        case .protocolViolation: return "The AirPlay receiver returned an invalid status."
        case .receiverError: return "The AirPlay receiver reported an error."
        case .unexpectedExit: return "The AirPlay receiver stopped unexpectedly."
        }
    }
}

/// Refs #721. A serial/main-actor host owns the process and uses the returned
/// token on every callback and timer. Reading this value never starts anything.
public struct AirPlaySession {
    public enum Phase: String, Equatable {
        case unavailable, idle, starting, ready, receiving, stopping, failed
    }

    public private(set) var available: Bool
    public private(set) var phase: Phase
    public private(set) var token: UUID?
    public private(set) var pin: String?
    public private(set) var receivingVideo = false
    public private(set) var receivingAudio = false
    public private(set) var failure: AirPlayFailure?

    /// A failed process remains owned until reaped; no overlapping receiver.
    public var isRunning: Bool { token != nil }
    public var canStart: Bool { available && token == nil }

    public init(available: Bool) {
        self.available = available
        self.phase = available ? .idle : .unavailable
    }

    /// Do not change a live session when a passive bundle check runs.
    @discardableResult
    public mutating func setAvailability(_ value: Bool) -> Bool {
        guard token == nil else { return false }
        guard available != value else { return false }
        available = value
        phase = value ? .idle : .unavailable
        failure = nil
        clearMedia()
        return true
    }

    /// Only an explicit user start may call this method.
    public mutating func beginStart() throws -> UUID {
        guard available else { throw AirPlayFailure.unavailable }
        guard token == nil else { throw AirPlayFailure.alreadyRunning }
        let next = UUID()
        token = next
        phase = .starting
        failure = nil
        clearMedia()
        return next
    }

    @discardableResult
    public mutating func receive(_ event: AirPlayEvent, token expected: UUID) -> Bool {
        guard token == expected, [.starting, .ready, .receiving].contains(phase) else { return false }
        switch event {
        case .ready:
            guard phase == .starting else { return false }
            phase = .ready
        case .pin(let code):
            // Typed events can also come from native tests; keep the invariant
            // here as well as at the JSON boundary.
            guard code.utf8.count == 4, code.utf8.allSatisfy({ (48...57).contains($0) }) else {
                return fail(.protocolViolation, token: expected)
            }
            pin = code
        case .video, .audio:
            guard phase == .ready || phase == .receiving else {
                return fail(.protocolViolation, token: expected)
            }
            phase = .receiving
            pin = nil
            if event == .video { receivingVideo = true } else { receivingAudio = true }
        case .disconnected:
            guard phase == .ready || phase == .receiving else {
                return fail(.protocolViolation, token: expected)
            }
            clearMedia()
            phase = .ready
        case .error(let code): return fail(.receiverError(code), token: expected)
        }
        return true
    }

    /// Marks an owned process for stopping. EOF/SIGTERM are the host's job.
    /// The token stays valid only for its eventual exit, not late ready/media.
    @discardableResult
    public mutating func requestStop() -> UUID? {
        guard let token else { return nil }
        phase = .stopping
        clearMedia()
        return token
    }

    @discardableResult
    public mutating func fail(_ reason: AirPlayFailure, token expected: UUID) -> Bool {
        guard token == expected, phase != .stopping else { return false }
        // Preserve the first useful failure across later callbacks/EOF errors.
        guard failure == nil else { return false }
        failure = reason
        phase = .failed
        clearMedia()
        return true
    }

    @discardableResult
    public mutating func startupTimedOut(token expected: UUID) -> Bool {
        guard token == expected, phase == .starting else { return false }
        return fail(.startupTimeout, token: expected)
    }

    /// Exit status zero is still a failure unless a stop was requested. Some
    /// upstream startup failures return zero, so it never proves readiness.
    @discardableResult
    public mutating func processExited(token expected: UUID, exitStatus: Int32) -> Bool {
        guard token == expected else { return false }
        if phase != .stopping && failure == nil { failure = .unexpectedExit(exitStatus) }
        token = nil
        clearMedia()
        phase = failure != nil ? .failed : (available ? .idle : .unavailable)
        return true
    }

    private mutating func clearMedia() {
        pin = nil
        receivingVideo = false
        receivingAudio = false
    }
}
