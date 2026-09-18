import Foundation

/// A native file-picker capability: the web page cannot turn a supplied path into
/// filesystem authority. The bytes selected are pinned until confirmation.
public struct BackupSelection {
    public let url: URL
    public let text: String
    public let encrypted: Bool
    private let bytes: Data

    public init(url: URL) throws {
        guard let bytes = try AtomicStore.read(url, requirePrivate: false),
              let text = String(data: bytes, encoding: .utf8) else { throw BetaError("This backup cannot be used.") }
        let root = try Document.object(text)
        encrypted = root["magnolie"] as? String == "magnolie-verschluesselt"
        if !encrypted { _ = try Document.plain(text) }
        self.url = url.standardizedFileURL; self.bytes = bytes; self.text = text
    }

    public func confirmed(path: String) throws -> String {
        guard path == url.path, try AtomicStore.read(url, requirePrivate: false) == bytes else {
            throw BetaError("This backup cannot be used.")
        }
        return text
    }
}
