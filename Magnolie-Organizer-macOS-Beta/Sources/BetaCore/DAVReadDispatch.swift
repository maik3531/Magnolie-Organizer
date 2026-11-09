import Foundation
import CryptoKit

/// Closed leaf clock: no application callback can execute while dispatch gates are held.
internal final class DAVReadClock {
    private let lock = NSLock()
    private var testValue: TimeInterval?
    private init(_ value: TimeInterval?) { testValue = value }
    static let system = DAVReadClock(nil)
    static func testing(_ value: TimeInterval) -> DAVReadClock { DAVReadClock(value) }
    func now() -> TimeInterval {
        lock.lock(); defer { lock.unlock() }
        return testValue ?? ProcessInfo.processInfo.systemUptime
    }
    func setForTesting(_ value: TimeInterval) {
        lock.lock(); defer { lock.unlock() }
        precondition(testValue != nil); testValue = value
    }
}
internal protocol DAVReadOperationCancellation: AnyObject { func cancel() }
internal final class WeakDAVReadLeaseGate {
    weak var value: DAVReadLeaseGate?
    init(_ value: DAVReadLeaseGate) { self.value = value }
}
private final class WeakDAVReadOperation {
    weak var value: (any DAVReadOperationCancellation)?
    init(_ value: any DAVReadOperationCancellation) { self.value = value }
}

/// Nested order: admission -> signer -> lease -> operation. Revocation invokes cancellations AFTER unlock.
internal final class DAVReadLeaseGate {
    let signer: DAVAccountBindingSigner
    let expires: TimeInterval
    let clock: DAVReadClock
    private let lock = NSLock()
    private let admission: DAVBookAdmission?
    private let bookSession: DAVBookSessionTicket?
    private var active = true
    private var operations: [UUID: WeakDAVReadOperation] = [:]
    init(signer: DAVAccountBindingSigner, expires: TimeInterval, clock: DAVReadClock,
         admission: DAVBookAdmission? = nil, bookSession: DAVBookSessionTicket? = nil) {
        self.signer = signer; self.expires = expires; self.clock = clock
        self.admission = admission; self.bookSession = bookSession
    }
    private func validateAdmission() throws {
        if let admission {
            guard let bookSession else { throw DAVAccountLeaseError.bookAdmissionClosed }
            try admission.validate(bookSession)
        }
    }
    func revoke() {
        lock.lock(); active = false
        let pending = operations.values.compactMap(\.value); operations.removeAll(); lock.unlock()
        for operation in pending { operation.cancel() }
    }
    func register(_ operation: any DAVReadOperationCancellation) throws -> UUID {
        try validateAdmission() // Before lease lock; never acquire admission while holding it.
        lock.lock(); defer { lock.unlock() }
        guard active else { throw DAVAccountLeaseError.invalidLease }
        operations = operations.filter { $0.value.value != nil }
        guard operations.count < 1 else { throw DAVAccountLeaseError.capacity }
        let id = UUID(); operations[id] = WeakDAVReadOperation(operation); return id
    }
    func unregister(_ id: UUID) { lock.lock(); operations.removeValue(forKey: id); lock.unlock() }
    func withStart(_ authorization: DAVReadDispatchAuthorization, request: BoundedHTTPRequest, start: () throws -> Void) throws {
        func signedStart() throws {
            try signer.withReadStartGate {
                lock.lock(); defer { lock.unlock() }
                guard active else { throw DAVAccountLeaseError.invalidLease }
                do { try authorization.checkDeadlineAtResume(); try authorization.consumeLocked(); try start(); authorization.markStartedLocked() }
                catch {
                    authorization.discardLocked()
                    if error as? DAVAccountLeaseError == .expired { active = false }
                    throw error
                }
            }
        }
        if let admission {
            guard let bookSession else { throw DAVAccountLeaseError.bookAdmissionClosed }
            try admission.withCurrent(bookSession, start: signedStart)
        } else { try signedStart() } // Unbound gate exists only in internal primitive fixtures.
    }
    func discard(_ authorization: DAVReadDispatchAuthorization) { lock.lock(); authorization.discardLocked(); lock.unlock() }
    func confirmStarted(_ authorization: DAVReadDispatchAuthorization) throws {
        lock.lock(); defer { lock.unlock() }
        guard authorization.startedLocked else { throw DAVAccountLeaseError.invalidLease }
    }
    func checkState() throws {
        try validateAdmission() // Check admission before acquiring lease lock.
        lock.lock(); defer { lock.unlock() }
        guard active else { throw DAVAccountLeaseError.invalidLease }
        let now = clock.now()
        guard now.isFinite, now >= 0, now < expires else { active = false; throw DAVAccountLeaseError.expired }
    }
}

/// Memory-only exact request binding. No public initializer/serialization or write methods.
internal final class DAVReadDispatchAuthorization {
    let gate: DAVReadLeaseGate
    let deadline: TimeInterval
    private let requestDigest: Data
    // Accessed only under gate's lease lock; an authorization authorizes at most one start.
    private var consumed = false
    private var dispatched = false
    var startedLocked: Bool { dispatched }
    func consumeLocked() throws {
        guard !consumed else { throw DAVAccountLeaseError.invalidLease }
        consumed = true
    }
    func markStartedLocked() { dispatched = true }
    func discardLocked() { consumed = true }
    init(gate: DAVReadLeaseGate, deadline: TimeInterval, request: BoundedHTTPRequest) throws {
        guard request.method == "GET" || request.method == "REPORT" else { throw DAVAccountLeaseError.invalidSelection }
        self.gate = gate; self.deadline = deadline; requestDigest = Self.digest(request)
    }
    private static func digest(_ request: BoundedHTTPRequest) -> Data {
        var hash = SHA256()
        let fields = [request.method, request.url.absoluteString, String(request.timeout), String(request.maximumResponseBytes)] +
            request.headers.keys.sorted().flatMap { [$0, request.headers[$0]!] }
        hash.update(data: OpaqueUTF8Identity(parts: fields).bytes); hash.update(data: request.body)
        return Data(hash.finalize())
    }
    func matches(_ request: BoundedHTTPRequest) -> Bool { requestDigest == Self.digest(request) }
    func checkDeadlineAtResume() throws {
        let now = gate.clock.now()
        guard now.isFinite, now >= 0, now < gate.expires else { throw DAVAccountLeaseError.expired }
        guard now < deadline else { throw DAVError.timeout }
    }
    func checkResponseDeadline() throws {
        try gate.confirmStarted(self)
        do { try checkDeadlineAtResume() }
        catch { if error as? DAVAccountLeaseError == .expired { gate.revoke() }; throw error }
    }
    func start(_ request: BoundedHTTPRequest, _ resume: () throws -> Void) throws {
        // Immutable request hashing can process a large REPORT body; never hold gates for it.
        guard matches(request) else { gate.discard(self); throw DAVAccountLeaseError.bindingChanged }
        try gate.withStart(self, request: request, start: resume)
    }
}

/// Closed native transport capability; arbitrary public transports cannot accidentally skip fences.
internal protocol DispatchFencedHTTPTransport: BoundedHTTPTransport {
    func send(_ request: BoundedHTTPRequest, authorization: DAVReadDispatchAuthorization) async throws -> BoundedHTTPResponse
}

/// Deterministic native start seam only; waits occur outside all production gates.
internal final class DAVHTTPStartProbe {
    private let lock = NSLock()
    private let ready = DispatchSemaphore(value: 0), release = DispatchSemaphore(value: 0), resumed = DispatchSemaphore(value: 0)
    private let hold: Bool
    private var count = 0
    init(holdBeforeStart: Bool) { hold = holdBeforeStart }
    func beforeAuthorization() -> Bool { ready.signal(); return !hold || release.wait(timeout: .now() + 5) == .success }
    func waitUntilSuspended() -> Bool { ready.wait(timeout: .now() + 5) == .success }
    func allowStart() { release.signal() }
    func recordResume() { lock.lock(); count += 1; lock.unlock(); resumed.signal() }
    func waitUntilResumed() -> Bool { resumed.wait(timeout: .now() + 5) == .success }
    var resumes: Int { lock.lock(); defer { lock.unlock() }; return count }
}
