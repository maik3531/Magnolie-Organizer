import Foundation
import CryptoKit

/// Encrypted intent/response evidence only. No network and no public retirement API.
/// Expected-byte fencing detects in-session replacement; older valid ciphertext rollback across
/// process launches is NOT prevented. Restores must change the independent book generation/epoch.
public actor DAVSyncJournalStore {
    public static let maximumBytes = 64 * 1024 * 1024
    public static let maximumPendingRuns = 16
    private static let magic = Data("MAGDAVJ1".utf8)
    public struct Source: Codable, Equatable {
        public let uid: String, href: URL, supportsVtodo: Bool
        public init(uid: String, href: URL, supportsVtodo: Bool) { self.uid = uid; self.href = href; self.supportsVtodo = supportsVtodo }
    }
    public struct Binding: Codable, Equatable {
        public let accountIdentity: String, accountRevision: String, server: URL
        /// Caller must supply a persistent native book/restore binding verified against disk.
        /// Today's volatile host documentGeneration is NOT this contract; no host verifier exists yet.
        public let bookIdentity: String, bookGeneration: String, syncEpoch: String, inputDigest: String
        public let sources: [Source]
        public init(accountIdentity: String, accountRevision: String, server: URL, bookIdentity: String,
                    bookGeneration: String, syncEpoch: String, inputDigest: String, sources: [Source]) {
            self.accountIdentity = accountIdentity; self.accountRevision = accountRevision; self.server = server
            self.bookIdentity = bookIdentity; self.bookGeneration = bookGeneration; self.syncEpoch = syncEpoch
            self.inputDigest = inputDigest; self.sources = sources
        }
    }
    public struct FrozenOperation: Codable, Equatable {
        public enum Method: String, Codable { case create, update, delete }
        public let id: String, sourceUID: String, method: Method, href: URL, ifMatch: String?, body: Data?
        public var ifNoneMatch: String? { method == .create ? "*" : nil }
        public init(id: String, sourceUID: String, method: Method, href: URL, ifMatch: String? = nil, body: Data? = nil) {
            self.id = id; self.sourceUID = sourceUID; self.method = method; self.href = href; self.ifMatch = ifMatch; self.body = body
        }
    }
    public struct PreparedRun: Codable, Equatable {
        public let id: String, binding: Binding, input: Data, plan: Data, operations: [FrozenOperation]
        public init(id: String, binding: Binding, input: Data, plan: Data, operations: [FrozenOperation]) {
            self.id = id; self.binding = binding; self.input = input; self.plan = plan; self.operations = operations
        }
    }
    public struct RunHandle: Equatable { public let id: String; fileprivate let instance: UUID }
    public struct WritePermit {
        public let operation: FrozenOperation
        fileprivate let runID: String, attempt: UUID, instance: UUID
    }
    public struct Outcome: Codable, Equatable {
        public enum Kind: String, Codable { case acknowledged, uncertain }
        public let kind: Kind, status: Int?, etag: String?
        public static func acknowledgement(status: Int, etag: String? = nil) -> Outcome { Outcome(kind: .acknowledged, status: status, etag: etag) }
        public static var uncertain: Outcome { Outcome(kind: .uncertain, status: nil, etag: nil) }
    }
    public struct PendingSummary {
        public let id: String, prepared: Int, acknowledged: Int, uncertain: Int, staged: Bool
    }
    public struct StagedResult {
        public let runID: String, candidate: Data, digest: String
    }
    public struct OperationEvidence {
        public enum Status: Equatable { case prepared, acknowledged, uncertain }
        public let operation: FrozenOperation, status: Status, outcome: Outcome?
    }
    public struct RunEvidence {
        public let frozen: PreparedRun, operations: [OperationEvidence], candidate: Data?, proofBinding: String?
    }
    private enum Phase: String, Codable { case prepared, inFlight, acknowledged, uncertain }
    private struct OperationState: Codable {
        var phase: Phase = .prepared
        var attempt: UUID?
        var outcome: Outcome?
    }
    private struct Run: Codable {
        let frozen: PreparedRun
        var states: [OperationState]
        var candidate: Data?
        var proofBinding: String?
    }
    private struct State: Codable { let version: Int; var runs: [Run] }
    private let files: DAVSyncJournalFiles
    private let key: DAVSyncJournalKey
    private let owner: UUID
    private let instance = UUID()
    private var state: State
    private var expected: Data?
    private var poisoned = false

    public init(files: DAVSyncJournalFiles, keys: any DAVSyncJournalKeyStore = KeychainDAVSyncJournalKeyStore()) throws {
        self.files = files
        let token = try files.claimOwner()
        owner = token
        var opened = false
        defer { if !opened { files.releaseOwner(token) } }
        let bytes = try files.read(owner: owner)
        key = try keys.load(namespace: files.namespace, allowCreate: bytes == nil)
        if let bytes {
            state = try Self.decrypt(bytes, key: key, namespace: files.namespace)
            try Self.validateState(state)
            try files.reopenBarrier(expected: bytes, owner: owner)
            expected = bytes
        } else {
            guard key.newlyCreated else { throw DAVSyncJournalError.missingJournal }
            state = State(version: 1, runs: [])
            let initial = try Self.encrypt(state, key: key, namespace: files.namespace)
            try files.write(initial, owner: owner)
            expected = initial
        }
        opened = true
    }
    deinit { files.releaseOwner(owner) }
    private static func encoder() -> JSONEncoder { let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]; return encoder }
    public static func digest(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
    private static func validDigest(_ value: String) -> Bool { value.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil }
    private static func validETag(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != "*" && value.utf8.count <= 8192 && !value.unicodeScalars.contains { $0.value < 32 || $0.value == 127 }
    }
    private static func url(_ value: URL) throws -> URLComponents {
        guard let parts = URLComponents(url: value, resolvingAgainstBaseURL: false), parts.scheme?.lowercased() == "https",
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil, parts.query == nil,
              parts.fragment == nil, parts.port == nil || (1...65535).contains(parts.port!), value.absoluteString.utf8.count <= 16_384 else { throw DAVSyncJournalError.invalidInput }
        let path = parts.percentEncodedPath
        for piece in path.split(separator: "/", omittingEmptySubsequences: false) {
            guard let decoded = String(piece).removingPercentEncoding, decoded != ".", decoded != "..",
                  !decoded.contains("/"), !decoded.contains("\\"), !decoded.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else { throw DAVSyncJournalError.invalidInput }
        }
        return parts
    }
    private static func canonicalPath(_ value: URLComponents) -> String {
        value.percentEncodedPath.split(separator: "/", omittingEmptySubsequences: false).map { String($0).removingPercentEncoding! }.joined(separator: "/")
    }
    private static func sameOrigin(_ lhs: URLComponents, _ rhs: URLComponents) -> Bool {
        lhs.host?.lowercased() == rhs.host?.lowercased() && (lhs.port ?? 443) == (rhs.port ?? 443)
    }
    private static func validate(_ frozen: PreparedRun) throws {
        let binding = frozen.binding
        guard validDigest(frozen.id), validDigest(binding.accountIdentity), validDigest(binding.accountRevision), validDigest(binding.inputDigest),
              !binding.bookIdentity.isEmpty, !binding.bookGeneration.isEmpty, !binding.syncEpoch.isEmpty,
              [binding.bookIdentity, binding.bookGeneration, binding.syncEpoch].allSatisfy({ $0.utf8.count <= 1024 && !$0.contains("\0") }),
              digest(frozen.input) == binding.inputDigest, !frozen.input.isEmpty, !frozen.plan.isEmpty,
              frozen.input.count <= maximumBytes, frozen.plan.count <= maximumBytes,
              (1...100).contains(binding.sources.count), frozen.operations.count <= DAVClient.listLimit else { throw DAVSyncJournalError.invalidInput }
        let origin = try url(binding.server)
        var sources: [String: URLComponents] = [:], hrefs = Set<String>(), sourceHrefs = Set<String>()
        for source in binding.sources {
            let href = try url(source.href)
            guard !source.uid.isEmpty, source.uid.utf8.count <= 1024, sameOrigin(origin, href), href.percentEncodedPath.hasSuffix("/"),
                  sourceHrefs.insert((href.host!.lowercased()) + ":" + String(href.port ?? 443) + canonicalPath(href)).inserted,
                  sources.updateValue(href, forKey: source.uid) == nil else { throw DAVSyncJournalError.invalidInput }
        }
        var ids = Set<String>(), total = 0
        for operation in frozen.operations {
            let href = try url(operation.href)
            guard validDigest(operation.id), ids.insert(operation.id).inserted, hrefs.insert((href.host!.lowercased()) + ":" + String(href.port ?? 443) + canonicalPath(href)).inserted,
                  let source = sources[operation.sourceUID], sameOrigin(source, href), canonicalPath(href).hasPrefix(canonicalPath(source)),
                  canonicalPath(href) != canonicalPath(source) else { throw DAVSyncJournalError.invalidInput }
            switch operation.method {
            case .create: guard operation.ifMatch == nil, let body = operation.body, !body.isEmpty else { throw DAVSyncJournalError.invalidInput }
            case .update: guard let etag = operation.ifMatch, validETag(etag), let body = operation.body, !body.isEmpty else { throw DAVSyncJournalError.invalidInput }
            case .delete: guard let etag = operation.ifMatch, validETag(etag), operation.body == nil else { throw DAVSyncJournalError.invalidInput }
            }
            let count = operation.body?.count ?? 0
            guard count <= ICalendarImport.maximumBytes, count <= DAVClient.itemLimit - total else { throw DAVSyncJournalError.capacity }; total += count
        }
    }
    private static func validateOutcome(_ outcome: Outcome, operation: FrozenOperation) throws {
        if outcome.kind == .uncertain {
            guard outcome.status == nil, outcome.etag == nil else { throw DAVSyncJournalError.invalidTransition }; return
        }
        if operation.method == .delete {
            guard let status = outcome.status, [200, 204, 404].contains(status), outcome.etag == nil else { throw DAVSyncJournalError.invalidTransition }
        } else {
            guard let status = outcome.status, [200, 201, 204].contains(status), let etag = outcome.etag, validETag(etag) else { throw DAVSyncJournalError.invalidTransition }
        }
    }
    private static func validateState(_ state: State) throws {
        guard state.version == 1, state.runs.count <= maximumPendingRuns else { throw DAVSyncJournalError.corrupt }
        var ids = Set<String>()
        for run in state.runs {
            try validate(run.frozen)
            guard ids.insert(run.frozen.id).inserted, run.states.count == run.frozen.operations.count else { throw DAVSyncJournalError.corrupt }
            for (operation, value) in zip(run.frozen.operations, run.states) {
                switch value.phase {
                case .prepared: guard value.attempt == nil, value.outcome == nil else { throw DAVSyncJournalError.corrupt }
                case .inFlight: guard value.attempt != nil, value.outcome == nil else { throw DAVSyncJournalError.corrupt }
                case .acknowledged, .uncertain:
                    guard value.attempt != nil, let outcome = value.outcome, outcome.kind == (value.phase == .acknowledged ? .acknowledged : .uncertain) else { throw DAVSyncJournalError.corrupt }
                    try validateOutcome(outcome, operation: operation)
                }
            }
            if let candidate = run.candidate {
                guard !candidate.isEmpty, candidate.count <= maximumBytes, let proof = run.proofBinding, validDigest(proof),
                      run.states.allSatisfy({ $0.phase == .acknowledged }) else { throw DAVSyncJournalError.corrupt }
            } else if run.proofBinding != nil { throw DAVSyncJournalError.corrupt }
        }
    }
    private static func aad(_ key: DAVSyncJournalKey, namespace: String) -> Data { magic + key.id + Data(namespace.utf8) }
    /// Conservative serialized upper bound, checked without materializing Data's Base64 or JSON.
    /// Every metadata object reserves512 bytes for fixed keys/punctuation/UUIDs; escaped strings
    /// reserve6 bytes per UTF8 byte, an upper bound even for escaped UTF16 surrogate pairs.
    private static func preflight(_ state: State) throws {
        var remaining = maximumBytes - 68
        func reserve(_ count: Int) throws {
            guard count >= 0, count <= remaining else { throw DAVSyncJournalError.capacity }; remaining -= count
        }
        func string(_ value: String) throws {
            let count = value.utf8.count
            guard count <= remaining / 6 else { throw DAVSyncJournalError.capacity }
            try reserve(count * 6)
        }
        func bytes(_ value: Data?) throws {
            guard let value else { return }
            guard value.count <= maximumBytes else { throw DAVSyncJournalError.capacity }
            let groups = value.count / 3 + (value.count % 3 == 0 ? 0 : 1)
            guard groups <= remaining / 4 else { throw DAVSyncJournalError.capacity }; try reserve(groups * 4)
        }
        try reserve(512)
        for run in state.runs {
            try reserve(512)
            let frozen = run.frozen, binding = frozen.binding
            for value in [frozen.id, binding.accountIdentity, binding.accountRevision, binding.server.absoluteString,
                binding.bookIdentity, binding.bookGeneration, binding.syncEpoch, binding.inputDigest] { try string(value) }
            try bytes(frozen.input); try bytes(frozen.plan); try bytes(run.candidate)
            if let proof = run.proofBinding { try string(proof) }
            for source in binding.sources { try reserve(512); try string(source.uid); try string(source.href.absoluteString) }
            for operation in frozen.operations {
                try reserve(512)
                for value in [operation.id, operation.sourceUID, operation.href.absoluteString, operation.ifMatch ?? ""] { try string(value) }
                try bytes(operation.body)
            }
            for state in run.states { try reserve(512); if let etag = state.outcome?.etag { try string(etag) } }
        }
    }
    private static func encrypt(_ state: State, key: DAVSyncJournalKey, namespace: String) throws -> Data {
        try preflight(state)
        let plain = try encoder().encode(state)
        guard plain.count <= maximumBytes - 68 else { throw DAVSyncJournalError.capacity }
        let sealed = try AES.GCM.seal(plain, using: SymmetricKey(data: key.bytes), authenticating: aad(key, namespace: namespace))
        guard let combined = sealed.combined else { throw DAVSyncJournalError.corrupt }
        return magic + key.id + combined
    }
    private static func validateSchema(_ plain: Data) throws {
        func object(_ value: Any, _ allowed: Set<String>) throws -> [String: Any] {
            guard let result = value as? [String: Any], Set(result.keys).isSubset(of: allowed) else { throw DAVSyncJournalError.corrupt }
            return result
        }
        let root = try object(JSONSerialization.jsonObject(with: plain), ["version", "runs"])
        guard let runs = root["runs"] as? [Any], runs.count <= maximumPendingRuns else { throw DAVSyncJournalError.corrupt }
        for value in runs {
            let run = try object(value, ["frozen", "states", "candidate", "proofBinding"])
            let frozen = try object(run["frozen"] ?? NSNull(), ["id", "binding", "input", "plan", "operations"])
            let binding = try object(frozen["binding"] ?? NSNull(), ["accountIdentity", "accountRevision", "server", "bookIdentity", "bookGeneration", "syncEpoch", "inputDigest", "sources"])
            guard let sources = binding["sources"] as? [Any], sources.count <= 100,
                  let operations = frozen["operations"] as? [Any], operations.count <= DAVClient.listLimit,
                  let states = run["states"] as? [Any], states.count == operations.count else { throw DAVSyncJournalError.corrupt }
            for source in sources { _ = try object(source, ["uid", "href", "supportsVtodo"]) }
            for operation in operations { _ = try object(operation, ["id", "sourceUID", "method", "href", "ifMatch", "body"]) }
            for value in states {
                let state = try object(value, ["phase", "attempt", "outcome"])
                if let outcome = state["outcome"] { _ = try object(outcome, ["kind", "status", "etag"]) }
            }
        }
    }
    private static func decrypt(_ bytes: Data, key: DAVSyncJournalKey, namespace: String) throws -> State {
        guard bytes.count > 68, bytes.count <= maximumBytes, bytes.prefix(8) == magic, bytes.subdata(in: 8..<40) == key.id else { throw DAVSyncJournalError.corrupt }
        do {
            let box = try AES.GCM.SealedBox(combined: bytes.dropFirst(40))
            let plain = try AES.GCM.open(box, using: SymmetricKey(data: key.bytes), authenticating: aad(key, namespace: namespace))
            try validateSchema(plain)
            return try JSONDecoder().decode(State.self, from: plain)
        } catch { throw DAVSyncJournalError.corrupt }
    }
    private func current() throws {
        guard !poisoned else { throw DAVSyncJournalError.poisoned }
        guard try files.read(owner: owner) == expected else { poisoned = true; throw DAVSyncJournalError.externalChange }
    }
    private func persist(_ next: State) throws {
        try current(); try Self.validateState(next)
        let encrypted = try Self.encrypt(next, key: key, namespace: files.namespace)
        do { try files.write(encrypted, owner: owner); expected = encrypted; state = next }
        catch { poisoned = true; throw error }
    }
    private func index(_ handle: RunHandle) throws -> Int {
        try current()
        guard handle.instance == instance else { throw DAVSyncJournalError.stalePermit }
        guard let index = state.runs.firstIndex(where: { $0.frozen.id == handle.id }) else { throw DAVSyncJournalError.missingRun }; return index
    }
    public func pending() throws -> [PendingSummary] {
        try current()
        return state.runs.map { run in PendingSummary(id: run.frozen.id,
            prepared: run.states.filter { $0.phase == .prepared }.count, acknowledged: run.states.filter { $0.phase == .acknowledged }.count,
            uncertain: run.states.filter { $0.phase == .inFlight || $0.phase == .uncertain }.count, staged: run.candidate != nil) }
    }
    public func prepare(_ frozen: PreparedRun) throws -> RunHandle {
        try current(); try Self.validate(frozen)
        if let run = state.runs.first(where: { $0.frozen.id == frozen.id }) {
            guard run.frozen == frozen else { throw DAVSyncJournalError.collision }
        } else {
            guard state.runs.count < Self.maximumPendingRuns else { throw DAVSyncJournalError.capacity }
            var next = state; next.runs.append(Run(frozen: frozen, states: frozen.operations.map { _ in OperationState() }))
            try persist(next)
        }
        return RunHandle(id: frozen.id, instance: instance)
    }
    public func resume(runID: String, currentBinding: Binding) throws -> RunHandle {
        try current()
        guard let run = state.runs.first(where: { $0.frozen.id == runID }) else { throw DAVSyncJournalError.missingRun }
        guard run.frozen.binding == currentBinding else { throw DAVSyncJournalError.bindingChanged }
        return RunHandle(id: runID, instance: instance)
    }
    public func beginAttempt(_ run: RunHandle, operationID: String, currentBinding: Binding) throws -> WritePermit {
        let index = try index(run)
        guard state.runs[index].frozen.binding == currentBinding else { throw DAVSyncJournalError.bindingChanged }
        guard state.runs[index].candidate == nil, let op = state.runs[index].frozen.operations.firstIndex(where: { $0.id == operationID }),
              state.runs[index].states[op].phase == .prepared else { throw DAVSyncJournalError.invalidTransition }
        let attempt = UUID()
        var next = state; next.runs[index].states[op].phase = .inFlight; next.runs[index].states[op].attempt = attempt
        try persist(next)
        return WritePermit(operation: state.runs[index].frozen.operations[op], runID: run.id, attempt: attempt, instance: instance)
    }
    public func observe(_ permit: WritePermit, outcome: Outcome) throws {
        try current()
        guard permit.instance == instance, let index = state.runs.firstIndex(where: { $0.frozen.id == permit.runID }),
              let op = state.runs[index].frozen.operations.firstIndex(where: { $0.id == permit.operation.id }),
              state.runs[index].frozen.operations[op] == permit.operation,
              state.runs[index].states[op].attempt == permit.attempt else { throw DAVSyncJournalError.stalePermit }
        try Self.validateOutcome(outcome, operation: permit.operation)
        let prior = state.runs[index].states[op]
        if prior.outcome == outcome { return }
        guard prior.phase == .inFlight, prior.outcome == nil else { throw DAVSyncJournalError.invalidTransition }
        var next = state; next.runs[index].states[op].phase = outcome.kind == .acknowledged ? .acknowledged : .uncertain
        next.runs[index].states[op].outcome = outcome
        try persist(next)
    }
    public func stageResult(_ run: RunHandle, candidate: Data, proofBinding: String) throws -> StagedResult {
        let index = try index(run)
        guard !candidate.isEmpty, candidate.count <= Self.maximumBytes, Self.validDigest(proofBinding),
              state.runs[index].states.allSatisfy({ $0.phase == .acknowledged }) else { throw DAVSyncJournalError.invalidTransition }
        if let prior = state.runs[index].candidate {
            guard prior == candidate, state.runs[index].proofBinding == proofBinding else { throw DAVSyncJournalError.collision }
        } else {
            var next = state; next.runs[index].candidate = candidate; next.runs[index].proofBinding = proofBinding; try persist(next)
        }
        return StagedResult(runID: run.id, candidate: candidate, digest: Self.digest(candidate))
    }
    /// Native-only recovery evidence, never an automatic WebView status payload.
    public func evidence(_ handle: RunHandle) throws -> RunEvidence {
        let run = state.runs[try index(handle)]
        let operations = zip(run.frozen.operations, run.states).map { operation, value in
            OperationEvidence(operation: operation, status: value.phase == .prepared ? .prepared : value.phase == .acknowledged ? .acknowledged : .uncertain, outcome: value.outcome)
        }
        return RunEvidence(frozen: run.frozen, operations: operations, candidate: run.candidate, proofBinding: run.proofBinding)
    }
    /// Trusted native recovery can inspect exact frozen evidence; uncertainty is not a retry permit.
    public func frozenRun(_ run: RunHandle) throws -> PreparedRun { state.runs[try index(run)].frozen }
    // Deliberately no production retire/resolveUncertain method until independent disk/GET proof
    // verifiers exist. Retaining bounded evidence is safer than a caller-supplied "verified" flag.
}
