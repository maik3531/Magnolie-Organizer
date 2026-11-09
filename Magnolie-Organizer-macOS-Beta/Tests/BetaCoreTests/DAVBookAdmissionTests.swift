import Foundation
import CryptoKit
import XCTest
@testable import BetaCore

// Explicit TEST-ONLY UI handoff model. Evidence itself is obtained independently from an
// actual private durable file. No production issuer exists until the native handoff is wired.
func fixtureBookHandoff(_ transition: DAVBookTransitionTicket, namespace: String) throws -> DAVBookHandoffConfirmation {
    let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent("dav-admission-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    defer { try? FileManager.default.removeItem(at: directory) }
    let epoch = UUID().uuidString
    let book: [String: Any] = ["termine": [], "aufgaben": [], "kontakte": [], "notizen": [],
        "syncEpoch": epoch, "syncMetadaten": ["syncEpoch": epoch], "einstellungen": ["sync": ["syncEpoch": epoch]]]
    let store = try AtomicStore(directory: directory)
    _ = try store.load(); try store.commit(Document.encode(book))
    return try DAVBookHandoffConfirmation(transition: transition, savedEvidence: DAVBookDiskSnapshot.read(store: store), accountStoreNamespace: namespace)
}
func fixtureAdmitBook(_ service: DAVAccountService, namespace: String) async throws {
    let transition = try service.suspendBookAdmission()
    try await service.awaitBookSuspension(transition)
    try await service.completeBookTransition(transition, confirmation: fixtureBookHandoff(transition, namespace: namespace))
}

private final class AdmissionCancellation: DAVReadOperationCancellation {
    let callback: () -> Void
    init(_ callback: @escaping () -> Void) { self.callback = callback }
    func cancel() { callback() }
}
final class DAVBookAdmissionTests: XCTestCase {
    private func open(_ admission: DAVBookAdmission) throws -> DAVBookSessionTicket {
        let transition = try admission.suspend()
        try admission.reopen(transition, confirmation: fixtureBookHandoff(transition, namespace: "fixture"))
        return try admission.capture()
    }
    private func signer() -> DAVAccountBindingSigner {
        DAVAccountBindingSigner(namespace: "test", key: SymmetricKey(data: Data(repeating: 4, count: 32)), validateJournal: {})
    }
    private func request() -> BoundedHTTPRequest {
        BoundedHTTPRequest(url: URL(string: "https://example.test/cal/a.ics")!, method: "GET", headers: [:], body: Data(), timeout: 30, maximumResponseBytes: 1024)
    }
    func testInitialAdmissionIsClosedWithoutProductionIssuer() throws {
        let admission = DAVBookAdmission()
        XCTAssertThrowsError(try admission.capture())
        let ticket = try open(admission)
        try admission.validate(ticket)
    }
    func testSuspendImmediatelyInvalidatesCapturedTicketAndNeverResurrectsIt() throws {
        let admission = DAVBookAdmission(), old = try open(admission)
        let transition = try admission.suspend()
        XCTAssertThrowsError(try admission.capture()); XCTAssertThrowsError(try admission.validate(old))
        try admission.reopen(transition, confirmation: fixtureBookHandoff(transition, namespace: "fixture"))
        XCTAssertNotEqual(old, try admission.capture()); XCTAssertThrowsError(try admission.validate(old))
    }
    func testUncertainOutcomeCannotReopenOrStartAnotherTransition() throws {
        let admission = DAVBookAdmission(); _ = try open(admission)
        let transition = try admission.suspend(), proof = try fixtureBookHandoff(transition, namespace: "fixture")
        try admission.block(transition)
        XCTAssertThrowsError(try admission.reopen(transition, confirmation: proof))
        XCTAssertThrowsError(try admission.suspend()); XCTAssertThrowsError(try admission.capture())
    }
    func testForeignAndConsumedTransitionProofsCannotOpen() throws {
        let first = DAVBookAdmission(), second = DAVBookAdmission()
        let one = try first.suspend(), two = try second.suspend(), proof = try fixtureBookHandoff(one, namespace: "fixture")
        XCTAssertThrowsError(try second.reopen(two, confirmation: proof))
        try first.reopen(one, confirmation: proof)
        XCTAssertThrowsError(try first.reopen(one, confirmation: proof))
        XCTAssertThrowsError(try first.block(one))
    }
    func testSuspensionCancelsOutsideAllAdmissionAndLeaseLocks() throws {
        let admission = DAVBookAdmission(), ticket = try open(admission), signer = signer()
        let gate = DAVReadLeaseGate(signer: signer, expires: 400, clock: .testing(100), admission: admission, bookSession: ticket)
        try admission.register(gate, ticket: ticket)
        let cancelled = expectation(description: "callback reacquires admission and signer")
        let operation = AdmissionCancellation {
            do { _ = try admission.capture(); XCTFail("Suspended admission reopened") } catch {}
            do { try signer.withReadStartGate {} } catch { XCTFail("Unexpected signer failure") }
            cancelled.fulfill()
        }
        _ = try gate.register(operation)
        DispatchQueue.global().async { do { _ = try admission.suspend() } catch { XCTFail("Suspend failed") } }
        wait(for: [cancelled], timeout: 3)
        withExtendedLifetime(operation) {}
    }
    func testOldActualStartAuthorizationDeniedEvenAfterNewHandoff() throws {
        let admission = DAVBookAdmission(), ticket = try open(admission), signer = signer(), req = request()
        let gate = DAVReadLeaseGate(signer: signer, expires: 400, clock: .testing(100), admission: admission, bookSession: ticket)
        try admission.register(gate, ticket: ticket)
        let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 300, request: req)
        let transition = try admission.suspend()
        try admission.reopen(transition, confirmation: fixtureBookHandoff(transition, namespace: "fixture"))
        XCTAssertThrowsError(try auth.start(req) { XCTFail("Old queued task resumed") })
        XCTAssertThrowsError(try gate.checkState())
    }
    func testActualStartBeforeSuspensionLinearizesThenIsRevoked() throws {
        let admission = DAVBookAdmission(), ticket = try open(admission), signer = signer(), req = request()
        let gate = DAVReadLeaseGate(signer: signer, expires: 400, clock: .testing(100), admission: admission, bookSession: ticket)
        try admission.register(gate, ticket: ticket)
        let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 300, request: req)
        var starts = 0
        try auth.start(req) { starts += 1 }
        XCTAssertEqual(starts, 1)
        _ = try admission.suspend()
        XCTAssertThrowsError(try gate.checkState())
    }
    func testFreshSessionGateStartsButForeignSessionCannotRegister() throws {
        let admission = DAVBookAdmission(), other = DAVBookAdmission(), ticket = try open(admission), foreign = try open(other), signer = signer(), req = request()
        let gate = DAVReadLeaseGate(signer: signer, expires: 400, clock: .testing(100), admission: admission, bookSession: ticket)
        XCTAssertThrowsError(try admission.register(gate, ticket: foreign))
        try admission.register(gate, ticket: ticket)
        let auth = try DAVReadDispatchAuthorization(gate: gate, deadline: 300, request: req)
        var started = false; try auth.start(req) { started = true }; XCTAssertTrue(started)
    }
    func testBarrierTimeoutIsTerminalAndCannotReleasePinSuccessfully() async throws {
        let barrier = AdmissionTestBarrier(timeoutNanoseconds: 1_000_000)
        do { try await barrier.wait(); XCTFail("Timeout opened barrier") } catch { XCTAssertEqual(error as? DAVError, .timeout) }
        do { try await barrier.started(); XCTFail("Expired barrier accepted started") } catch { XCTAssertEqual(error as? DAVError, .timeout) }
        await barrier.open()
        do { try await barrier.wait(); XCTFail("Explicit open resurrected expired barrier") } catch { XCTAssertEqual(error as? DAVError, .timeout) }
        let entryOnly = AdmissionTestBarrier(timeoutNanoseconds: 1_000_000)
        do { try await entryOnly.started(); XCTFail("Missing arrival accepted") } catch { XCTAssertEqual(error as? DAVError, .timeout) }
        await entryOnly.open()
        do { try await entryOnly.wait(); XCTFail("Expired entry resurrected") } catch { XCTAssertEqual(error as? DAVError, .timeout) }
    }

}

internal actor AdmissionTestBarrier {
    private var entered = false, opened = false, failed = false
    private var entries: [UUID: CheckedContinuation<Void, Error>] = [:]
    private var releases: [UUID: CheckedContinuation<Void, Error>] = [:]
    private var timers: [UUID: Task<Void, Never>] = [:]
    private let timeoutNanoseconds: UInt64
    init(timeoutNanoseconds: UInt64 = 3_000_000_000) { self.timeoutNanoseconds = timeoutNanoseconds }
    private func arm(_ id: UUID) {
        let timeout = timeoutNanoseconds
        timers[id] = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: timeout) } catch { return }
            await self?.expire(id)
        }
    }
    private func expire(_ id: UUID) {
        guard entries[id] != nil || releases[id] != nil else { return }
        failed = true
        let pending = Array(entries.values) + Array(releases.values)
        entries.removeAll(); releases.removeAll()
        for timer in timers.values { timer.cancel() }; timers.removeAll()
        for continuation in pending { continuation.resume(throwing: DAVError.timeout) }
    }
    func wait() async throws {
        guard !failed else { throw DAVError.timeout }
        entered = true
        let waiting = entries; entries.removeAll()
        for (id, continuation) in waiting { timers.removeValue(forKey: id)?.cancel(); continuation.resume() }
        if !opened {
            let id = UUID()
            try await withCheckedThrowingContinuation { releases[id] = $0; arm(id) }
        }
    }
    func started() async throws {
        guard !failed else { throw DAVError.timeout }
        if !entered {
            let id = UUID()
            try await withCheckedThrowingContinuation { entries[id] = $0; arm(id) }
        }
    }
    func open() {
        guard !failed else { return }
        opened = true
        let waiting = releases; releases.removeAll()
        for (id, continuation) in waiting { timers.removeValue(forKey: id)?.cancel(); continuation.resume() }
    }
}
