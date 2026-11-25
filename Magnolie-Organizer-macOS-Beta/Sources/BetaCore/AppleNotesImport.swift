import Foundation
import CryptoKit

/// Refs #772. A bounded proposal for explicit local text copies from Apple Notes.
/// This value-only layer does not access Notes, interpret HTML, grant permissions,
/// write to a source, synchronize records or authorize removal of local copies.
public enum AppleNotesImport {
    public static let maximumRecords = 32
    public static let maximumTextBytes = 1024 * 1024
    public static let maximumBytes = 8 * 1024 * 1024
    public static let maximumTitleBytes = 4096
    public static let maximumIdentifierBytes = 16_384

    public struct Source: Sendable {
        public let accountID: String, accountTitle: String, folderID: String, folderTitle: String
        public init(accountID: String, accountTitle: String, folderID: String, folderTitle: String) {
            self.accountID = accountID; self.accountTitle = accountTitle
            self.folderID = folderID; self.folderTitle = folderTitle
        }
    }

    /// Optional properties represent what the reader actually obtained. A failed
    /// read must not become false, zero, an empty body or an invented modification time.
    public struct Record: Sendable {
        public let identifier: String, title: String
        public let passwordProtected: Bool?, attachmentCount: Int?
        public let plaintext: String?, bodyHTML: String?, modified: Double?, failure: String?
        public init(identifier: String, title: String, passwordProtected: Bool?, attachmentCount: Int?,
                    plaintext: String?, bodyHTML: String?, modified: Double?, failure: String? = nil) {
            self.identifier = identifier; self.title = title; self.passwordProtected = passwordProtected
            self.attachmentCount = attachmentCount; self.plaintext = plaintext; self.bodyHTML = bodyHTML
            self.modified = modified; self.failure = failure
        }
    }

    public struct Snapshot: Sendable {
        public let source: Source, records: [Record]
        public init(source: Source, records: [Record]) { self.source = source; self.records = records }
    }

    public struct Plan {
        public let payload: [String: Any]
        public let snapshotRevision: String
        private let evidence: Data

        fileprivate init(source: [String: Any], notes: [[String: Any]], excluded: [[String: Any]], evidence: Data) throws {
            self.evidence = evidence
            snapshotRevision = AppleNotesImport.hash(evidence)
            payload = ["version": 1, "source": source, "notes": notes, "excluded": excluded,
                       "snapshotRevision": snapshotRevision]
            // Plaintext is also retained in nativeRecord. JSON escaping and that
            // duplication are covered by this independent final transport bound.
            guard try Document.encode(payload).utf8.count <= AppleNotesImport.maximumBytes else {
                throw AppleNotesImport.failure("proposal exceeds 8 MiB")
            }
        }

        /// Compare the complete byte evidence, not Swift String equality or only
        /// the importable subset. A reread is not an atomic native revision token.
        public func revalidate(_ snapshot: Snapshot) throws {
            guard try AppleNotesImport.checked(snapshot).evidence == evidence else {
                throw AppleNotesImport.failure("the selected notes or source changed; review a new proposal")
            }
        }
    }

    public static func prepare(_ snapshot: Snapshot) throws -> Plan {
        let read = try checked(snapshot)
        var notes: [[String: Any]] = [], excluded: [[String: Any]] = []
        for entry in read.records {
            let record = entry.record, reasons = exclusions(record)
            if !reasons.isEmpty {
                // Excluded bodies and failure details never enter the web payload.
                excluded.append(["identifier": record.identifier, "title": record.title, "reasons": reasons])
                continue
            }
            let identity = hash(OpaqueUTF8Identity(parts: [snapshot.source.accountID, record.identifier]).bytes)
            let revision = hash(try framed([Data("apple-notes-record-v1".utf8), read.sourceEvidence, entry.evidence]))
            notes.append(["identity": identity, "revision": revision, "identifier": record.identifier,
                          "title": record.title, "text": record.plaintext!, "nativeRecord": nativeRecord(record)])
        }
        return try Plan(source: sourcePayload(snapshot.source), notes: notes, excluded: excluded, evidence: read.evidence)
    }

    private struct CheckedRecord {
        let record: Record, evidence: Data
    }
    private struct CheckedSnapshot {
        let records: [CheckedRecord], sourceEvidence: Data, evidence: Data
    }

    private static func failure(_ message: String) -> BetaError { BetaError("Apple Notes copy: " + message + ".") }
    private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    private static func nullable<T>(_ value: T?) -> Any { value.map { $0 as Any } ?? NSNull() }

    private static func sourcePayload(_ source: Source) -> [String: Any] {
        ["accountID": source.accountID, "accountTitle": source.accountTitle,
         "folderID": source.folderID, "folderTitle": source.folderTitle]
    }
    private static func nativeRecord(_ record: Record) -> [String: Any] {
        ["identifier": record.identifier, "title": record.title,
         "passwordProtected": nullable(record.passwordProtected), "attachmentCount": nullable(record.attachmentCount),
         "plaintext": nullable(record.plaintext), "bodyHTML": nullable(record.bodyHTML),
         "modified": nullable(record.modified), "failure": nullable(record.failure)]
    }

    private static func safeText(_ value: String, multiline: Bool = false) -> Bool {
        value.unicodeScalars.allSatisfy {
            ($0.value >= 32 && !(0x7F...0x9F).contains($0.value)) ||
                (multiline && [9, 10, 13].contains($0.value))
        }
    }

    private static func exclusions(_ record: Record) -> [String] {
        var reasons: [String] = []
        if record.failure != nil { reasons.append("apple-note-read-failed") }
        switch record.passwordProtected {
        case nil: reasons.append("apple-note-protection-state-unavailable")
        case true?: reasons.append("apple-note-password-protected")
        case false?: break
        }
        if let count = record.attachmentCount, count >= 0 {
            if count > 0 { reasons.append("apple-note-has-attachments") }
        } else { reasons.append("apple-note-attachment-state-unavailable") }
        if record.plaintext == nil { reasons.append("apple-note-plaintext-unavailable") }
        if record.bodyHTML == nil { reasons.append("apple-note-html-unavailable") }
        if record.modified?.isFinite != true { reasons.append("apple-note-modification-state-unavailable") }
        if !safeText(record.identifier) || !safeText(record.title) ||
            record.plaintext.map({ !safeText($0, multiline: true) }) == true ||
            record.bodyHTML.map({ !safeText($0, multiline: true) }) == true ||
            record.failure.map({ !safeText($0) }) == true {
            reasons.append("apple-note-unsafe-control-characters")
        }
        return reasons.sorted()
    }

    private static func checked(_ snapshot: Snapshot) throws -> CheckedSnapshot {
        guard snapshot.records.count <= maximumRecords else { throw failure("select at most 32 notes") }
        let source = snapshot.source
        for identifier in [source.accountID, source.folderID] {
            guard !identifier.isEmpty, identifier.utf8.count <= maximumIdentifierBytes else {
                throw failure("invalid or oversized source identifier")
            }
        }
        guard [source.accountTitle, source.folderTitle].allSatisfy({ $0.utf8.count <= maximumTitleBytes }) else {
            throw failure("source title exceeds 4096 UTF-8 bytes")
        }
        guard [source.accountID, source.accountTitle, source.folderID, source.folderTitle].allSatisfy({ safeText($0) }) else {
            throw failure("unsafe source metadata")
        }
        let sourceEvidence = OpaqueUTF8Identity(parts: [source.accountID, source.accountTitle, source.folderID, source.folderTitle]).bytes
        var records: [CheckedRecord] = [], identifiers = Set<Data>(), total = sourceEvidence.count
        for record in snapshot.records {
            guard !record.identifier.isEmpty, record.identifier.utf8.count <= maximumIdentifierBytes else {
                throw failure("missing or oversized note identifier")
            }
            guard identifiers.insert(Data(record.identifier.utf8)).inserted else {
                throw failure("ambiguous note identifier")
            }
            guard record.title.utf8.count <= maximumTitleBytes else { throw failure("note title exceeds 4096 UTF-8 bytes") }
            guard (record.plaintext?.utf8.count ?? 0) <= maximumTextBytes,
                  (record.bodyHTML?.utf8.count ?? 0) <= maximumTextBytes else { throw failure("note text exceeds 1 MiB") }
            // The native reader must check protection before reading either body.
            // Reject a contract violation rather than retain protected text in proof.
            guard record.passwordProtected != true || (record.plaintext == nil && record.bodyHTML == nil) else {
                throw failure("protected notes must not contain text")
            }
            // Bound reader error details as part of the same proof before copying
            // any strings into the evidence buffer; errors cannot bypass the cap.
            var remaining = maximumBytes - total
            let retainedText: [String?] = [record.identifier, record.title, record.plaintext, record.bodyHTML, record.failure]
            for text in retainedText {
                let bytes = text?.utf8.count ?? 0
                guard bytes <= remaining else { throw failure("snapshot evidence exceeds 8 MiB") }
                remaining -= bytes
            }
            let proof = try recordEvidence(record)
            guard proof.count <= maximumBytes - total else { throw failure("snapshot evidence exceeds 8 MiB") }
            total += proof.count
            records.append(CheckedRecord(record: record, evidence: proof))
        }
        // Identifiers are opaque UTF-8: canonically equivalent Unicode strings
        // remain distinct and native enumeration order cannot change the proposal.
        records.sort { Data($0.record.identifier.utf8).lexicographicallyPrecedes(Data($1.record.identifier.utf8)) }
        let evidence = try framed([Data("apple-notes-snapshot-v1".utf8), sourceEvidence] + records.map(\.evidence))
        return CheckedSnapshot(records: records, sourceEvidence: sourceEvidence, evidence: evidence)
    }

    /// Count plus fixed-width lengths distinguish every component, including nil
    /// versus present-empty. Numeric bit patterns also bind rejected nonfinite
    /// values without forcing them into JSON or silently converting them to null.
    private static func framed(_ parts: [Data]) throws -> Data {
        var result = integerBytes(UInt64(parts.count))
        for part in parts {
            guard result.count <= maximumBytes - 8, part.count <= maximumBytes - result.count - 8 else {
                throw failure("snapshot evidence exceeds 8 MiB")
            }
            result.append(integerBytes(UInt64(part.count))); result.append(part)
        }
        return result
    }
    private static func integerBytes(_ value: UInt64) -> Data {
        var bigEndian = value.bigEndian
        return withUnsafeBytes(of: &bigEndian) { Data($0) }
    }
    private static func optionalText(_ value: String?) -> Data {
        guard let value else { return Data([0]) }
        var result = Data([1]); result.append(contentsOf: value.utf8); return result
    }
    private static func optionalBoolean(_ value: Bool?) -> Data {
        value.map { Data([1, $0 ? 1 : 0]) } ?? Data([0])
    }
    private static func optionalInteger(_ value: Int?) -> Data {
        guard let value else { return Data([0]) }
        var result = Data([1]); result.append(integerBytes(UInt64(bitPattern: Int64(value)))); return result
    }
    private static func optionalDouble(_ value: Double?) -> Data {
        guard let value else { return Data([0]) }
        var result = Data([1]); result.append(integerBytes(value.bitPattern)); return result
    }
    private static func recordEvidence(_ record: Record) throws -> Data {
        try framed([Data(record.identifier.utf8), Data(record.title.utf8),
                    optionalBoolean(record.passwordProtected), optionalInteger(record.attachmentCount),
                    optionalText(record.plaintext), optionalText(record.bodyHTML), optionalDouble(record.modified),
                    optionalText(record.failure)])
    }
}
