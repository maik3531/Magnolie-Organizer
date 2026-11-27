import Foundation
import CryptoKit

/// Native authority and transaction evidence for the bounded system-account field sync.
/// This store is separate from the book, imports, DAV credentials and the DAV journal.
/// The host serializes all access. No method accepts a WebView "saved"/"verified" flag.
public final class SystemAccountSyncLedger {
    public static let maximumBytes = 64 * 1024 * 1024
    public struct Binding: Codable, Equatable {
        public let epoch: String, sourceUID: String, sourceFingerprint: String, scope: String
        public init(epoch: UUID, sourceUID: String, sourceFingerprint: String, scope: String) throws {
            self.epoch = epoch.uuidString.lowercased(); self.sourceUID = sourceUID
            self.sourceFingerprint = sourceFingerprint; self.scope = scope
            try validate()
        }
        fileprivate func validate() throws {
            guard UUID(uuidString: epoch) != nil, !sourceUID.isEmpty, sourceUID.utf8.count <= 4096,
                  ["macos-events:", "macos-reminders:", "macos-contacts:"].contains(where: { sourceUID.hasPrefix($0) }),
                  sourceFingerprint.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
                  !scope.isEmpty, scope.utf8.count <= 4096 else { throw BetaError("Invalid system synchronization binding.") }
        }
        public static func == (a: Self, b: Self) -> Bool {
            OpaqueUTF8Identity(parts: [a.epoch, a.sourceUID, a.sourceFingerprint, a.scope]) ==
            OpaqueUTF8Identity(parts: [b.epoch, b.sourceUID, b.sourceFingerprint, b.scope])
        }
    }
    public struct Grant: Codable {
        public let id: String, binding: Binding
        public fileprivate(set) var enabled: Bool
        public fileprivate(set) var baseline: Data?
    }
    public struct Operation: Codable {
        public let id: String, payload: Data
        public init(id: String, payload: Data) throws {
            guard !id.isEmpty, id.utf8.count <= 1024 else { throw BetaError("Invalid system synchronization operation.") }
            _ = try Self.object(payload)
            self.id = id; self.payload = payload
        }
        private static func object(_ data: Data) throws -> [String: Any] { try SystemAccountSyncLedger.object(data) }
    }
    public struct Run: Codable {
        public let id: String, grantID: String, binding: Binding, input: Data, plan: Data, operations: [Operation]
        public fileprivate(set) var started: [String], readbacks: [String: Data], rejected: [String]
        public fileprivate(set) var candidate: Data?, nextBaseline: Data?
        public fileprivate(set) var readbackBudgets: [String: Int]
        public fileprivate(set) var candidateBudget: Int?, baselineBudget: Int?
        public var uncertain: Bool { started.contains { readbacks[$0] == nil && !rejected.contains($0) } }
        public var allAcknowledged: Bool { operations.allSatisfy { readbacks[$0.id] != nil } }
        public var withoutEffects: Bool { candidate == nil && readbacks.isEmpty && started.allSatisfy { rejected.contains($0) } }
    }
    private struct State: Codable { let version: Int; var grants: [Grant]; var runs: [Run] }
    private let store: AtomicStore, keys: any DAVSyncJournalKeyStore, key: DAVSyncJournalKey, namespace: String
    private var state: State
    private var poisoned = false

    public convenience init(profileDirectory: URL) throws {
        try self.init(profileDirectory: profileDirectory, keys: KeychainDAVSyncJournalKeyStore(
            operations: SystemDAVKeychainOperations(), service: "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta.system-account-sync-key.v1"))
    }
    internal init(profileDirectory: URL, keys: any DAVSyncJournalKeyStore) throws {
        let directory = profileDirectory.appendingPathComponent("SystemAccounts-Sync", isDirectory: true)
        store = try AtomicStore(directory: directory)
        namespace = Self.digest(Data(("Magnolie-SystemAccountSync-v1\0" + directory.standardizedFileURL.path).utf8))
        self.keys = keys
        let saved = try store.load()
        key = try keys.load(namespace: namespace, allowCreate: saved == nil)
        if let saved {
            let envelope = try Document.object(saved)
            guard envelope["format"] as? String == "magnolie-system-sync-v1",
                  envelope["keyID"] as? String == key.id.base64EncodedString(),
                  let text = envelope["ciphertext"] as? String, let ciphertext = Data(base64Encoded: text),
                  ciphertext.count <= Self.maximumBytes else { throw BetaError("The system synchronization journal is damaged; evidence was retained.") }
            let clear = try AES.GCM.open(AES.GCM.SealedBox(combined: ciphertext), using: SymmetricKey(data: key.bytes),
                                         authenticating: Data(namespace.utf8))
            state = try JSONDecoder().decode(State.self, from: clear)
            try Self.validate(state)
            guard try store.durableSnapshotBytes() == Data(saved.utf8) else { throw BetaError("System synchronization journal durability could not be verified.") }
        } else {
            guard key.newlyCreated else { throw BetaError("A system synchronization journal is missing; existing authority was not reset.") }
            state = State(version: 1, grants: [], runs: [])
            try persist(state)
        }
    }
    private static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func object(_ data: Data) throws -> [String: Any] {
        guard !data.isEmpty, data.count <= maximumBytes, let text = String(data: data, encoding: .utf8) else {
            throw BetaError("System synchronization data exceeds its limit.")
        }
        return try Document.object(text)
    }
    public static func encoded(_ object: [String: Any]) throws -> Data {
        let data = Data(try Document.encode(object).utf8); _ = try self.object(data); return data
    }
    public static func decoded(_ data: Data) throws -> [String: Any] { try object(data) }
    public static func equal(_ a: Data, _ b: Data) throws -> Bool {
        try Data(Document.encode(object(a)).utf8) == Data(Document.encode(object(b)).utf8)
    }
    /// Normalization may add ordinary defaults, but may not change or remove any
    /// native-planned value, record, identity, array entry or pre-existing book field.
    public static func verifyNormalizedCandidate(required: Data, proposed: Data) throws {
        var nodes = 0
        func check(_ expected: Any, _ actual: Any, depth: Int) throws {
            nodes += 1
            guard depth < 64, nodes <= 2_000_000 else { throw BetaError("System synchronization candidate structure is too large.") }
            if let a = expected as? [String: Any] {
                guard let b = actual as? [String: Any] else { throw BetaError("System synchronization normalization changed a planned value.") }
                let indexed = Dictionary(uniqueKeysWithValues: b.map { (OpaqueUTF8Identity($0.key), $0.value) })
                for (key, value) in a {
                    guard let next = indexed[OpaqueUTF8Identity(key)] else { throw BetaError("System synchronization normalization dropped a planned field.") }
                    try check(value, next, depth: depth + 1)
                }
            } else if let a = expected as? [Any] {
                guard let b = actual as? [Any], a.count == b.count else { throw BetaError("System synchronization normalization changed a planned collection.") }
                for (left, right) in zip(a, b) { try check(left, right, depth: depth + 1) }
            } else {
                guard try Data(Document.encode(expected).utf8) == Data(Document.encode(actual).utf8) else { throw BetaError("System synchronization normalization changed a planned value.") }
            }
        }
        try check(object(required), object(proposed), depth: 0)
    }
    private static func validate(_ state: State) throws {
        guard state.version == 1, state.grants.count <= 128, state.runs.count <= 16,
              Set(state.grants.map(\.id)).count == state.grants.count,
              Set(state.runs.map(\.id)).count == state.runs.count else { throw BetaError("Invalid system synchronization journal state.") }
        for grant in state.grants {
            guard UUID(uuidString: grant.id) != nil else { throw BetaError("Invalid system synchronization grant.") }
            try grant.binding.validate(); if let baseline = grant.baseline { _ = try object(baseline) }
        }
        for run in state.runs {
            try run.binding.validate(); _ = try object(run.input); _ = try object(run.plan)
            guard UUID(uuidString: run.id) != nil, state.grants.contains(where: { $0.enabled && $0.id == run.grantID && $0.binding == run.binding }),
                  run.operations.count <= 1000, Set(run.operations.map(\.id)).count == run.operations.count,
                  Set(run.started).count == run.started.count, Set(run.rejected).count == run.rejected.count else {
                throw BetaError("Invalid system synchronization run.")
            }
            let ids = Set(run.operations.map(\.id))
            guard Set(run.started).isSubset(of: ids), Set(run.readbacks.keys).isSubset(of: Set(run.started)),
                  Set(run.rejected).isSubset(of: Set(run.started)), Set(run.rejected).isDisjoint(with: Set(run.readbacks.keys)),
                  (run.candidate == nil) == (run.nextBaseline == nil) else { throw BetaError("Invalid system synchronization operation evidence.") }
            for operation in run.operations { _ = try Operation(id: operation.id, payload: operation.payload) }
            for readback in run.readbacks.values { _ = try object(readback) }
            if let candidate = run.candidate, let baseline = run.nextBaseline {
                guard run.allAcknowledged else { throw BetaError("Unacknowledged system synchronization result.") }
                _ = try object(candidate); _ = try object(baseline)
            }
            if let candidateBudget = run.candidateBudget, let baselineBudget = run.baselineBudget {
                guard (1...maximumBytes).contains(candidateBudget), (1...maximumBytes).contains(baselineBudget),
                      Set(run.readbackBudgets.keys) == ids,
                      run.readbackBudgets.values.allSatisfy({ (1...maximumBytes).contains($0) }),
                      run.readbacks.allSatisfy({ $0.value.count <= (run.readbackBudgets[$0.key] ?? 0) }),
                      (run.candidate?.count ?? 0) <= candidateBudget, (run.nextBaseline?.count ?? 0) <= baselineBudget else {
                    throw BetaError("Invalid system synchronization capacity reservation.")
                }
            } else {
                guard run.candidateBudget == nil, run.baselineBudget == nil, run.readbackBudgets.isEmpty,
                      run.started.isEmpty, run.candidate == nil else { throw BetaError("Missing system synchronization capacity reservation.") }
            }
        }
    }
    private func current() throws {
        guard !poisoned else { throw BetaError("System synchronization storage is blocked; restart and inspect retained evidence.") }
        let present = try keys.load(namespace: namespace, allowCreate: false)
        guard present.id == key.id, present.bytes == key.bytes else { throw BetaError("System synchronization authority changed.") }
    }
    private func persist(_ next: State) throws {
        try current(); try Self.validate(next)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let clear = try encoder.encode(next)
        // Data is Base64 without optional slash escapes, so encodedBytes below
        // is an upper bound for every reserved payload. Reserve slots before a
        // provider write, including retained runs, so an ordinary acknowledged
        // result cannot first discover an unfillable journal at stage().
        func encodedBytes(_ count: Int) -> Int { 4 * ((count + 2) / 3) }
        var reserved = clear.count
        for run in next.runs where run.candidateBudget != nil {
            reserved += 8192 + run.operations.count * 2048
            for (id, budget) in run.readbackBudgets { reserved += encodedBytes(budget) - encodedBytes(run.readbacks[id]?.count ?? 0) }
            reserved += encodedBytes(run.candidateBudget!) - encodedBytes(run.candidate?.count ?? 0)
            reserved += encodedBytes(run.baselineBudget!) - encodedBytes(run.nextBaseline?.count ?? 0)
        }
        guard reserved <= Self.maximumBytes - 4096 else { throw BetaError("System synchronization journal capacity reached; no further native write was started.") }
        let sealed = try AES.GCM.seal(clear, using: SymmetricKey(data: key.bytes), authenticating: Data(namespace.utf8))
        guard let bytes = sealed.combined else { throw BetaError("System synchronization encryption failed.") }
        let text = try Document.encode(["format": "magnolie-system-sync-v1", "keyID": key.id.base64EncodedString(), "ciphertext": bytes.base64EncodedString()])
        do { try store.commit(text); state = next }
        catch { poisoned = true; throw error }
    }
    public func grant(for binding: Binding) throws -> Grant? {
        try current(); try binding.validate()
        return state.grants.first { $0.enabled && $0.binding == binding }
    }
    /// The native host calls this only after its own explicit source/book confirmation.
    @discardableResult public func authorize(_ binding: Binding) throws -> Grant {
        if let existing = try grant(for: binding) { return existing }
        guard !state.grants.contains(where: { $0.enabled && $0.binding.epoch == binding.epoch &&
            OpaqueUTF8Identity($0.binding.sourceUID) == OpaqueUTF8Identity(binding.sourceUID) }) else {
            throw BetaError("The approved source or calendar window changed. Remove its previous synchronization permission before authorizing a new binding.")
        }
        // Revocation removes authority, not the private proven correspondence.
        // An explicitly re-approved observation window of the same source/zone
        // can reuse its baseline without cloning already-linked local entries.
        let prior = state.grants.last { !$0.enabled && $0.binding.epoch == binding.epoch &&
            OpaqueUTF8Identity($0.binding.sourceUID) == OpaqueUTF8Identity(binding.sourceUID) && $0.binding.sourceFingerprint == binding.sourceFingerprint }
        if let index = state.grants.firstIndex(where: { $0.binding == binding }) {
            var next = state, restored = next.grants.remove(at: index)
            restored.enabled = true; restored.baseline = prior?.baseline ?? restored.baseline
            next.grants.append(restored); try persist(next); return restored
        }
        guard state.grants.count < 128 else { throw BetaError("System synchronization grant capacity reached.") }
        let grant = Grant(id: UUID().uuidString, binding: binding, enabled: true, baseline: prior?.baseline)
        var next = state; next.grants.append(grant); try persist(next); return grant
    }
    public func revoke(_ binding: Binding) throws {
        try current()
        guard !state.runs.contains(where: { $0.binding == binding }) else { throw BetaError("A pending system synchronization must be inspected before its authority can be removed.") }
        var next = state
        for index in next.grants.indices where next.grants[index].binding == binding { next.grants[index].enabled = false }
        try persist(next)
    }
    public func revokeSource(epoch: UUID, sourceUID: String) throws {
        try current()
        let matches: (Binding) -> Bool = { UUID(uuidString: $0.epoch) == epoch && OpaqueUTF8Identity($0.sourceUID) == OpaqueUTF8Identity(sourceUID) }
        guard !state.runs.contains(where: { matches($0.binding) && !$0.withoutEffects }) else { throw BetaError("A pending system synchronization must be inspected before its authority can be removed.") }
        var next = state; next.runs.removeAll { matches($0.binding) && $0.withoutEffects }
        for index in next.grants.indices where matches(next.grants[index].binding) { next.grants[index].enabled = false }
        try persist(next)
    }
    public func pendingSource(epoch: UUID, sourceUID: String) throws -> Run? {
        try current()
        return state.runs.first { UUID(uuidString: $0.binding.epoch) == epoch && OpaqueUTF8Identity($0.binding.sourceUID) == OpaqueUTF8Identity(sourceUID) }
    }
    public func pending(_ binding: Binding) throws -> Run? {
        try current(); return state.runs.first { $0.binding == binding }
    }
    public func begin(binding: Binding, input: Data, plan: Data, operations: [Operation]) throws -> Run {
        guard let grant = try grant(for: binding), try pending(binding) == nil else { throw BetaError("System synchronization is not authorized or a transaction is still pending.") }
        let run = Run(id: UUID().uuidString, grantID: grant.id, binding: binding, input: input, plan: plan,
                      operations: operations, started: [], readbacks: [:], rejected: [], candidate: nil, nextBaseline: nil,
                      readbackBudgets: [:], candidateBudget: nil, baselineBudget: nil)
        var next = state; next.runs.append(run); try persist(next); return run
    }
    private func index(_ runID: String) throws -> Int {
        try current()
        guard let index = state.runs.firstIndex(where: { $0.id == runID }) else { throw BetaError("Unknown system synchronization transaction.") }
        return index
    }
    public func reserve(runID: String, readbacks: [String: Int], candidate: Int, baseline: Int) throws {
        let index = try index(runID), run = state.runs[index]
        if let oldCandidate = run.candidateBudget {
            guard oldCandidate == candidate, run.baselineBudget == baseline, run.readbackBudgets == readbacks else {
                throw BetaError("A frozen system synchronization capacity reservation changed.")
            }
            return
        }
        guard run.started.isEmpty else { throw BetaError("System synchronization capacity must be reserved before writing.") }
        var next = state; next.runs[index].readbackBudgets = readbacks
        next.runs[index].candidateBudget = candidate; next.runs[index].baselineBudget = baseline; try persist(next)
    }
    /// No staged local result, no acknowledged remote write and no uncertain
    /// attempt: these exact recorded states prove there is no effect to recover.
    public func discardWithoutEffects(runID: String) throws {
        let index = try index(runID)
        guard state.runs[index].withoutEffects else { throw BetaError("System synchronization evidence with possible effects cannot be discarded.") }
        var next = state; next.runs.remove(at: index); try persist(next)
    }
    public func willApply(runID: String, operationID: String) throws {
        let index = try index(runID), run = state.runs[index]
        guard run.candidate == nil, run.candidateBudget != nil, run.baselineBudget != nil, run.readbackBudgets[operationID] != nil,
              !run.started.contains(operationID), run.operations.contains(where: { $0.id == operationID }),
              !run.uncertain, run.rejected.isEmpty else { throw BetaError("Uncertain system synchronization writes cannot be repeated.") }
        var next = state; next.runs[index].started.append(operationID); try persist(next)
    }
    public func acknowledge(runID: String, operationID: String, readback: Data) throws {
        let index = try index(runID), run = state.runs[index]; _ = try Self.object(readback)
        guard run.started.contains(operationID), !run.rejected.contains(operationID), run.readbacks[operationID] == nil,
              let budget = run.readbackBudgets[operationID], readback.count <= budget else {
            throw BetaError("Stale system synchronization write receipt.")
        }
        var next = state; next.runs[index].readbacks[operationID] = readback; try persist(next)
    }
    public func rejectBeforeWrite(runID: String, operationID: String) throws {
        let index = try index(runID), run = state.runs[index]
        guard run.started.contains(operationID), run.readbacks[operationID] == nil, !run.rejected.contains(operationID) else {
            throw BetaError("Stale system synchronization rejection.")
        }
        var next = state; next.runs[index].rejected.append(operationID); try persist(next)
    }
    public func stage(runID: String, candidate: Data, baseline: Data) throws {
        let index = try index(runID), run = state.runs[index]
        _ = try Self.object(candidate); _ = try Self.object(baseline)
        guard run.allAcknowledged, let candidateBudget = run.candidateBudget, let baselineBudget = run.baselineBudget,
              candidate.count <= candidateBudget, baseline.count <= baselineBudget else { throw BetaError("System synchronization still has unconfirmed writes or exceeds its reserved result size.") }
        if let existing = run.candidate {
            guard try Self.equal(existing, candidate), run.nextBaseline == baseline else { throw BetaError("Conflicting system synchronization candidate.") }
            return
        }
        var next = state; next.runs[index].candidate = candidate; next.runs[index].nextBaseline = baseline; try persist(next)
    }
    /// Actual private-store fsync/read/decryption evidence is the only completion input.
    /// A lost frontend ACK is harmless: the exact staged on-disk candidate can finish later.
    public func complete(runID: String, evidence: DAVBookDiskSnapshot.Evidence) throws {
        let index = try index(runID), run = state.runs[index]
        guard run.allAcknowledged, let candidate = run.candidate, let baseline = run.nextBaseline,
              UUID(uuidString: run.binding.epoch) == evidence.epoch,
              try Self.equal(candidate, Self.encoded(evidence.book)),
              let grantIndex = state.grants.firstIndex(where: { $0.enabled && $0.id == run.grantID && $0.binding == run.binding }) else {
            throw BetaError("The saved book does not confirm this system synchronization; its journal was retained.")
        }
        var next = state; next.grants[grantIndex].baseline = baseline; next.runs.remove(at: index); try persist(next)
    }
}
