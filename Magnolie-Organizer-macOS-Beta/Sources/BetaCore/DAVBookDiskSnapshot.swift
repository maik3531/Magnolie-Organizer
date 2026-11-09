import Foundation
import CryptoKit

/// Independent actual disk evidence, not a sync-commit or retirement capability. The host must
/// serialize profile access and supply the existing unlocked encryption session, never plaintext.
public enum DAVBookDiskSnapshot {
    public struct Evidence {
        public let book: [String: Any]
        public let rawSHA256: String, epoch: UUID, encrypted: Bool
    }
    public static func read(store: AtomicStore, encryption: Encryption? = nil) throws -> Evidence {
        let bytes = try store.durableSnapshotBytes()
        guard let actual = String(data: bytes, encoding: .utf8) else { throw BetaError("Invalid actual profile UTF-8.") }
        let root = try Document.object(actual)
        let encrypted = root["magnolie"] as? String == "magnolie-verschluesselt"
        let text: String
        if encrypted {
            guard let encryption else { throw BetaError("Unlock the actual encrypted profile before verification.") }
            text = try encryption.openSnapshot(actual)
        } else {
            guard encryption == nil else { throw BetaError("The actual disk profile unexpectedly lacks encryption.") }
            text = actual
        }
        let book = try Document.plain(text), epoch = try DAVBookRestore.persistedEpoch(book)
        return Evidence(book: book, rawSHA256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), epoch: epoch, encrypted: encrypted)
    }
}
