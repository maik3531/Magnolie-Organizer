import Foundation

/// Native ordinary-save policy, captured before renderer normalization. This does not
/// establish sync authority or implement restore/migration; only a native transition may do that.
public struct OrdinarySaveEpochPolicy {
    public enum Classification: Equatable { case absent, legacy, protectedEpoch(UUID) }
    public let classification: Classification
    private let slots: [Data?]
    private static let paths = [["syncEpoch"], ["syncMetadaten", "syncEpoch"], ["einstellungen", "sync", "syncEpoch"]]

    public init(loadedPlain: String?) throws {
        let book = try loadedPlain.map(Document.plain) ?? [:]
        if loadedPlain == nil { classification = .absent }
        else if let epoch = Self.protectedEpoch(book) { classification = .protectedEpoch(epoch) }
        else { classification = .legacy }
        slots = try Self.paths.map { path in
            var current: Any = book
            for key in path {
                guard let dictionary = current as? [String: Any], let value = dictionary[key] else { return nil }
                current = value
            }
            return try JSONSerialization.data(withJSONObject: current, options: [.fragmentsAllowed, .sortedKeys])
        }
    }

    // Local-save consistency only: malformed optional containers may be repaired.
    // This is NOT the stricter persistedEpoch/disk-snapshot admission predicate.
    private static func protectedEpoch(_ book: [String: Any]) -> UUID? {
        guard let root = book["syncEpoch"] as? String, let epoch = UUID(uuidString: root),
              let meta = book["syncMetadaten"] as? [String: Any],
              let value = meta["syncEpoch"] as? String, UUID(uuidString: value) == epoch else { return nil }
        if let settings = book["einstellungen"] as? [String: Any],
           let sync = settings["sync"] as? [String: Any], let leaf = sync["syncEpoch"] {
            guard let value = leaf as? String, UUID(uuidString: value) == epoch else { return nil }
        }
        return epoch
    }

    /// Returns the actual plaintext to commit and retain as native Main.plain.
    /// Legacy slot values (including invalid values) cannot be promoted by normalization.
    public func prepare(candidate: String) throws -> String {
        var book = try Document.plain(candidate)
        if case .protectedEpoch(let epoch) = classification {
            guard Self.protectedEpoch(book) == epoch else {
                throw BetaError("Ordinary save cannot replace the persisted sync epoch.")
            }
        }
        func restore(_ dictionary: inout [String: Any], path: ArraySlice<String>, value: Any?) throws {
            let key = path.first!
            if path.count == 1 { dictionary[key] = value; return }
            if dictionary[key] == nil && value == nil { return }
            guard var child = dictionary[key] as? [String: Any] else {
                // Never replace a malformed parent and discard unrelated user data.
                if value == nil { return }
                throw BetaError("Cannot preserve the native sync epoch slot in a malformed container.")
            }
            try restore(&child, path: path.dropFirst(), value: value)
            dictionary[key] = child
        }
        for (path, saved) in zip(Self.paths, slots) {
            let value = try saved.map { try JSONSerialization.jsonObject(with: $0, options: .fragmentsAllowed) }
            try restore(&book, path: path[...], value: value)
        }
        if case .protectedEpoch(let epoch) = classification {
            guard Self.protectedEpoch(book) == epoch else { throw BetaError("Native sync epoch preservation failed.") }
        } else if (try? DAVBookRestore.persistedEpoch(book)) != nil {
            throw BetaError("Ordinary save cannot establish sync authority.")
        }
        let data = try JSONSerialization.data(withJSONObject: book, options: [.sortedKeys])
        guard let text = String(data: data, encoding: .utf8) else { throw BetaError("Invalid saved document encoding.") }
        _ = try Document.plain(text)
        return text
    }
}
