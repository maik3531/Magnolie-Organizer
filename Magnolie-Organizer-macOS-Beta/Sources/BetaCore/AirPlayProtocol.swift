import Foundation
import CoreFoundation

/// Refs #721. Private IPC from the bundled receiver, never raw UxPlay logs.
/// Media events acknowledge packets, not successful decoding or presentation.
public enum AirPlayEvent: Equatable {
    case ready
    case pin(String)
    case video
    case audio
    case disconnected
    case error(String)
}

public enum AirPlayProtocolError: Error, Equatable {
    case invalidMessage
    case lineTooLong
    case truncatedMessage
    case decoderFailed
}

/// Incremental and bounded even when a child writes without a newline. A broken
/// stream is poisoned until reset; callers must stop its owned helper process.
/// Errors deliberately contain no child output or authentication secrets.
public struct AirPlayEventDecoder {
    private let maximumLineBytes: Int
    private var buffered = Data()
    private var failed = false

    public init(maximumLineBytes: Int = 1_024) {
        self.maximumLineBytes = max(1, min(maximumLineBytes, 65_536))
    }

    public mutating func append(_ bytes: Data) throws -> [AirPlayEvent] {
        guard !failed else { throw AirPlayProtocolError.decoderFailed }
        var events: [AirPlayEvent] = []
        do {
            for byte in bytes {
                if byte == 10 {
                    events.append(try Self.decode(buffered))
                    buffered.removeAll(keepingCapacity: true)
                } else {
                    guard buffered.count < maximumLineBytes else {
                        throw AirPlayProtocolError.lineTooLong
                    }
                    buffered.append(byte)
                }
            }
            return events
        } catch {
            failed = true
            buffered.removeAll(keepingCapacity: false)
            throw error
        }
    }

    /// EOF is not readiness. It must be paired with the process-exit callback.
    public mutating func finish() throws {
        guard !failed else { throw AirPlayProtocolError.decoderFailed }
        guard buffered.isEmpty else {
            failed = true
            buffered.removeAll(keepingCapacity: false)
            throw AirPlayProtocolError.truncatedMessage
        }
    }

    public mutating func reset() {
        buffered.removeAll(keepingCapacity: false)
        failed = false
    }

    private static func decode(_ bytes: Data) throws -> AirPlayEvent {
        guard !bytes.isEmpty,
              let object = try? JSONSerialization.jsonObject(with: bytes),
              let fields = object as? [String: Any],
              let version = fields["protocol"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(), version == 1,
              let event = fields["event"] as? String else {
            throw AirPlayProtocolError.invalidMessage
        }
        let noCode: Set<String> = ["protocol", "event"]
        let withCode: Set<String> = ["protocol", "event", "code"]
        switch event {
        case "ready", "video", "audio", "disconnected":
            guard Set(fields.keys) == noCode else { throw AirPlayProtocolError.invalidMessage }
            switch event {
            case "ready": return .ready
            case "video": return .video
            case "audio": return .audio
            default: return .disconnected
            }
        case "pin":
            guard Set(fields.keys) == withCode, let code = fields["code"] as? String,
                  code.utf8.count == 4, code.utf8.allSatisfy({ (48...57).contains($0) }) else {
                throw AirPlayProtocolError.invalidMessage
            }
            return .pin(code)
        case "error":
            guard Set(fields.keys) == withCode, let code = fields["code"] as? String,
                  (1...48).contains(code.utf8.count),
                  let first = code.utf8.first, (97...122).contains(first),
                  code.utf8.allSatisfy({ (97...122).contains($0) || (48...57).contains($0) || $0 == 95 }) else {
                throw AirPlayProtocolError.invalidMessage
            }
            return .error(code)
        default: throw AirPlayProtocolError.invalidMessage
        }
    }
}
