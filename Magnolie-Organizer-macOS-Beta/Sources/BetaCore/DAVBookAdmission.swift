import Foundation

/// Capture synchronously at the native request boundary BEFORE creating/queuing a Task.
/// Runtime admission only: neither a persisted restore epoch nor remote-write authority.
public struct DAVBookSessionTicket: Equatable, Sendable {
    internal let owner: UUID, session: UUID
}
public struct DAVBookTransitionTicket: Equatable, Sendable {
    internal let owner: UUID, transition: UUID
}

/// No public initializer/decoder and no production issuer in this slice. A future reviewed
/// native restore helper may construct this ONLY after actual saved-disk verification AND
/// successful native UI apply handoff. Starting an asynchronous send is not that handoff.
/// Tests explicitly model the nonpublic handoff; this is not journal-retirement proof.
public struct DAVBookHandoffConfirmation {
    internal let transition: DAVBookTransitionTicket, epoch: UUID, rawSHA256: String, accountStoreNamespace: String
    internal init(transition: DAVBookTransitionTicket, savedEvidence: DAVBookDiskSnapshot.Evidence, accountStoreNamespace: String) throws {
        guard savedEvidence.rawSHA256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              !accountStoreNamespace.isEmpty, accountStoreNamespace.utf8.count <= 16_384,
              try DAVBookRestore.persistedEpoch(savedEvidence.book) == savedEvidence.epoch else { throw DAVAccountLeaseError.bindingChanged }
        self.transition = transition; epoch = savedEvidence.epoch; rawSHA256 = savedEvidence.rawSHA256
        self.accountStoreNamespace = accountStoreNamespace
    }
}

/// One closed native latch, owned by the account service. Nested start order is
/// Admission -> Signer -> Lease -> HTTP. No IO/await/cancellation callback under this lock.
internal final class DAVBookAdmission: @unchecked Sendable {
    private enum State { case initial, open(UUID), suspended(UUID), blocked }
    private let owner = UUID(), lock = NSLock()
    private var state: State = .initial
    private var gates: [WeakDAVReadLeaseGate] = []
    func capture() throws -> DAVBookSessionTicket {
        lock.lock(); defer { lock.unlock() }
        guard case .open(let session) = state else { throw DAVAccountLeaseError.bookAdmissionClosed }
        return DAVBookSessionTicket(owner: owner, session: session)
    }
    private func validLocked(_ ticket: DAVBookSessionTicket) -> Bool {
        guard ticket.owner == owner, case .open(let session) = state else { return false }
        return session == ticket.session
    }
    func validate(_ ticket: DAVBookSessionTicket) throws {
        lock.lock(); defer { lock.unlock() }
        guard validLocked(ticket) else { throw DAVAccountLeaseError.bookAdmissionClosed }
    }
    func withCurrent(_ ticket: DAVBookSessionTicket, start: () throws -> Void) throws {
        lock.lock(); defer { lock.unlock() }
        guard validLocked(ticket) else { throw DAVAccountLeaseError.bookAdmissionClosed }
        try start()
    }
    func register(_ gate: DAVReadLeaseGate, ticket: DAVBookSessionTicket) throws {
        lock.lock(); defer { lock.unlock() }
        guard validLocked(ticket) else { throw DAVAccountLeaseError.bookAdmissionClosed }
        gates = gates.filter { $0.value != nil }
        guard gates.count < 64 else { throw DAVAccountLeaseError.capacity }
        gates.append(WeakDAVReadLeaseGate(gate))
    }
    func suspend() throws -> DAVBookTransitionTicket {
        lock.lock()
        switch state {
        case .initial, .open: break
        case .suspended, .blocked: lock.unlock(); throw DAVAccountLeaseError.bookAdmissionClosed
        }
        let transition = UUID(); state = .suspended(transition)
        let pending = gates.compactMap(\.value); gates.removeAll(); lock.unlock()
        // Existing starts are ordered before suspension, or denied by the now-closed latch.
        for gate in pending { gate.revoke() }
        return DAVBookTransitionTicket(owner: owner, transition: transition)
    }
    func validateSuspended(_ ticket: DAVBookTransitionTicket) throws {
        lock.lock(); defer { lock.unlock() }
        guard ticket.owner == owner, case .suspended(let transition) = state, transition == ticket.transition else { throw DAVAccountLeaseError.bookAdmissionClosed }
    }
    func block(_ ticket: DAVBookTransitionTicket) throws {
        lock.lock()
        guard ticket.owner == owner, case .suspended(let transition) = state, transition == ticket.transition else {
            lock.unlock(); throw DAVAccountLeaseError.bookAdmissionClosed
        }
        state = .blocked
        let pending = gates.compactMap(\.value); gates.removeAll(); lock.unlock()
        for gate in pending { gate.revoke() }
    }
    func reopen(_ ticket: DAVBookTransitionTicket, confirmation: DAVBookHandoffConfirmation) throws {
        lock.lock(); defer { lock.unlock() }
        guard ticket.owner == owner, confirmation.transition == ticket,
              case .suspended(let transition) = state, transition == ticket.transition else { throw DAVAccountLeaseError.bookAdmissionClosed }
        state = .open(UUID()) // Never revive the pretransition session, even for unchanged-old book.
    }
}
