#if os(macOS)
import AppKit
import BetaCore

/// Native user authorization + durable intent/readback/candidate/disk transaction.
/// A source's observed revision is not an atomic Apple API compare-and-swap.
@MainActor
final class SystemAccountSyncHost {
    private let ledger: SystemAccountSyncLedger
    init(profileDirectory: URL) throws { ledger = try SystemAccountSyncLedger(profileDirectory: profileDirectory) }

    private func requireCurrent(_ current: () -> Bool) throws {
        guard current() else { throw BetaError("The current book changed; the synchronization journal was retained.") }
    }
    private func date(_ text: String) throws -> Date {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian); formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        guard text.count == 10, let value = formatter.date(from: text), formatter.string(from: value) == text else {
            throw BetaError("Please enter a valid date.")
        }
        return value
    }
    private func authorize(_ source: SystemAccountSync.Source, binding: SystemAccountSyncLedger.Binding,
                           count: Int, excluded: Int, tr: (String) -> String) throws {
        if try ledger.grant(for: binding) != nil { return }
        let alert = NSAlert(); alert.messageText = tr("Enable macOS field synchronization?")
        var sourceDescription = source.title + "\n" + source.sourceUID + "\n" + source.displayTimeZone
        if source.kind == .events, let start = source.scope["start"] as? NSNumber, let end = source.scope["end"] as? NSNumber {
            let formatter = ISO8601DateFormatter(); formatter.timeZone = TimeZone(secondsFromGMT: 0)
            sourceDescription += "\n" + tr("Window start (UTC)") + ": " + formatter.string(from: Date(timeIntervalSince1970: start.doubleValue)) +
                "\n" + tr("Window end, exclusive (UTC)") + ": " + formatter.string(from: Date(timeIntervalSince1970: end.doubleValue))
        }
        alert.informativeText = sourceDescription + "\n\n" +
            tr("This permission applies to this Organizer book and the selected source and calendar window. The first run adds supported native entries. Later runs exchange supported field changes only for those linked entries.") + "\n\n" +
            tr("Existing copies and unrelated local entries are not exported. No native entries are created or deleted. Recurring events and unsupported fields are excluded. Removing the permission stops future synchronization.") + "\n\n" +
            tr("Apple APIs do not provide atomic comparison-and-save protection. Another app can change an item between the comparison and save. Uncertain results retain the journal and are never automatically repeated.") + "\n\n" +
            tr("Supported entries") + ": \(count)\n" + tr("Excluded entries") + ": \(excluded)"
        alert.addButton(withTitle: tr("Enable field synchronization")); alert.addButton(withTitle: tr("Cancel"))
        guard alert.runModal() == .alertFirstButtonReturn else { throw BetaError("System synchronization permission was not granted.") }
        try ledger.authorize(binding)
    }

    func begin(request: Request, accounts: SystemAccounts, context: CalendarTimeContext,
               isCurrent: @escaping () -> Bool, disk: @escaping () throws -> DAVBookDiskSnapshot.Evidence,
               candidateWrite: @escaping (String?) -> Void,
               ui: @escaping (String, [String: Any]) async throws -> [String: Any],
               translate tr: @escaping (String) -> String) async -> [String: Any] {
        let requestID = request.text("requestId")
        var activeRunID: String?
        do {
            try requireCurrent(isCurrent)
            let initialDisk = try disk(), initial = try SystemAccountSyncLedger.encoded(initialDisk.book)
            let admission = try await ui("return window.App.macOSBetaAdmitSystemSync(requestId, input);",
                                         ["requestId": requestID, "input": String(decoding: initial, as: UTF8.self)])
            try requireCurrent(isCurrent)
            guard admission["ok"] as? Bool == true, admission["requestId"] as? String == requestID else {
                throw BetaError("The saved book does not match the current synchronization request.")
            }
            if request.text("action") == "revoke" {
                try ledger.revokeSource(epoch: initialDisk.epoch, sourceUID: request.text("sourceUID"))
                return ["ok": true, "revoked": true, "requestId": requestID]
            }
            guard let kind = SystemSourcePolicy.Kind(rawValue: request.text("kind")) else { throw BetaError("Invalid macOS source kind.") }
            let start: Date, end: Date
            if kind == .events { start = try date(request.text("start")); end = try date(request.text("end")); try SystemSourcePolicy.requireWindow(start: start, end: end) }
            else { start = Date(timeIntervalSince1970: 0); end = Date(timeIntervalSince1970: 1) }
            try await accounts.requestAccess(kind)
            try requireCurrent(isCurrent)
            let snapshot = try await accounts.syncSnapshot(sourceUID: request.text("sourceUID"), start: start, end: end,
                                                           context: context, displayTimeZone: request.text("timeZone"))
            try requireCurrent(isCurrent)
            let scope = try Document.encode(["scope": snapshot.source.scope, "displayTimeZone": snapshot.source.displayTimeZone,
                                             "contract": "system-account-fields-v1"])
            let binding = try SystemAccountSyncLedger.Binding(epoch: initialDisk.epoch, sourceUID: snapshot.source.sourceUID,
                                                              sourceFingerprint: snapshot.source.fingerprint, scope: scope)
            if let prior = try ledger.pendingSource(epoch: initialDisk.epoch, sourceUID: snapshot.source.sourceUID) {
                if prior.withoutEffects { try ledger.discardWithoutEffects(runID: prior.id) }
                else if prior.binding != binding { throw BetaError("A pending synchronization belongs to an earlier source binding. Its evidence was retained.") }
            }
            try authorize(snapshot.source, binding: binding, count: snapshot.records.count, excluded: snapshot.excluded.count, tr: tr)
            try requireCurrent(isCurrent)
            guard try SystemAccountSyncLedger.equal(initial, SystemAccountSyncLedger.encoded(disk().book)) else {
                throw BetaError("The saved book changed before synchronization; no new write was started.")
            }
            var run: SystemAccountSyncLedger.Run
            let plan: SystemAccountSync.Plan
            if let prior = try ledger.pending(binding) {
                run = prior; plan = try SystemAccountSync.Plan(payload: SystemAccountSyncLedger.decoded(prior.plan))
                if let candidate = prior.candidate, try SystemAccountSyncLedger.equal(candidate, initial) {
                    try ledger.complete(runID: prior.id, evidence: disk())
                    return ["ok": true, "requestId": requestID, "bericht": tr("The previously saved transaction was verified without repeating native writes.")]
                }
                guard try SystemAccountSyncLedger.equal(prior.input, initial), !prior.uncertain, prior.rejected.isEmpty else {
                    throw BetaError("A previous synchronization has uncertain writes or a changed book. Its journal was retained; writes were not repeated.")
                }
            } else {
                let baseline: SystemAccountSync.Baseline?
                if let data = try ledger.grant(for: binding)?.baseline {
                    baseline = try SystemAccountSync.Baseline(payload: SystemAccountSyncLedger.decoded(data))
                } else { baseline = nil }
                plan = try SystemAccountSync.prepare(snapshot: snapshot, currentBook: initialDisk.book, baseline: baseline, context: context)
                let operations = try plan.operations.map { try SystemAccountSyncLedger.Operation(id: $0.id, payload: SystemAccountSyncLedger.encoded($0.payload)) }
                run = try ledger.begin(binding: binding, input: initial, plan: SystemAccountSyncLedger.encoded(plan.payload), operations: operations)
            }
            activeRunID = run.id
            if run.candidate == nil {
                // Prove current shared-UI representability before touching any
                // provider. Final readbacks are probed again before staging.
                let required = try SystemAccountSyncLedger.encoded(plan.candidateBook)
                let preflight = try await ui("return window.App.macOSBetaPrepareSystemSync(requestId, runID, candidate);",
                    ["requestId": requestID, "runID": run.id, "candidate": String(decoding: required, as: UTF8.self)])
                try requireCurrent(isCurrent)
                guard preflight["ok"] as? Bool == true, preflight["requestId"] as? String == requestID,
                      preflight["runID"] as? String == run.id, let text = preflight["text"] as? String else {
                    throw BetaError("The synchronization candidate could not be prepared.")
                }
                try SystemAccountSyncLedger.verifyNormalizedCandidate(required: required, proposed: Data(text.utf8))
                if run.candidateBudget == nil {
                    var readbackBudgets: [String: Int] = [:]
                    for operation in plan.operations {
                        // Actual readbacks are admitted only inside these bounds.
                        // The before/desired/native patch plus growth allowance
                        // covers stable full-field copies and provider timestamps.
                        let budget = try SystemAccountSyncLedger.encoded(operation.before.payload).count +
                            SystemAccountSyncLedger.encoded(operation.desiredRecord).count +
                            4 * SystemAccountSyncLedger.encoded(operation.nativePatch).count + 65_536
                        readbackBudgets[operation.id] = budget
                    }
                    let growth = readbackBudgets.values.reduce(0, +) * 2 + 65_536
                    try ledger.reserve(runID: run.id, readbacks: readbackBudgets,
                                       candidate: Data(text.utf8).count + growth,
                                       baseline: SystemAccountSyncLedger.encoded(plan.nextBaseline.payload).count + growth)
                    guard let reserved = try ledger.pending(binding) else { throw BetaError("System synchronization evidence is missing.") }
                    run = reserved
                }
            }
            // Re-entering a prepared run is safe only for operations with no
            // recorded attempt. In-flight/unknown outcomes never become retries.
            for operation in plan.operations where run.readbacks[operation.id] == nil {
                try requireCurrent(isCurrent)
                guard try SystemAccountSyncLedger.equal(initial, SystemAccountSyncLedger.encoded(disk().book)) else {
                    throw BetaError("The saved book changed before synchronization; no new write was started.")
                }
                try ledger.willApply(runID: run.id, operationID: operation.id)
                do {
                    let readback = try await accounts.applySync(operation: operation, source: plan.source, context: context)
                    try operation.validateReadback(readback)
                    // Persist the real outcome even if the WebView disappeared
                    // meanwhile. That does not authorize another operation.
                    try ledger.acknowledge(runID: run.id, operationID: operation.id,
                                           readback: SystemAccountSyncLedger.encoded(readback.payload))
                } catch let rejection as SystemAccountSync.RejectedBeforeWrite {
                    try ledger.rejectBeforeWrite(runID: run.id, operationID: operation.id)
                    throw rejection
                }
                try requireCurrent(isCurrent)
                guard let updated = try ledger.pending(binding) else { throw BetaError("System synchronization evidence is missing.") }
                run = updated
            }
            try requireCurrent(isCurrent)
            let candidate: Data
            if let staged = run.candidate { candidate = staged }
            else {
                let readbacks = try plan.operations.map { operation -> SystemAccountSync.Record in
                    guard let value = run.readbacks[operation.id] else { throw BetaError("A native synchronization write has no verified readback.") }
                    return try SystemAccountSync.Record(payload: SystemAccountSyncLedger.decoded(value))
                }
                let finalized = try plan.finalize(readbacks: readbacks)
                let required = try SystemAccountSyncLedger.encoded(finalized.candidateBook)
                let prepared = try await ui("return window.App.macOSBetaPrepareSystemSync(requestId, runID, candidate);",
                    ["requestId": requestID, "runID": run.id, "candidate": String(decoding: required, as: UTF8.self)])
                try requireCurrent(isCurrent)
                guard prepared["ok"] as? Bool == true, prepared["requestId"] as? String == requestID,
                      prepared["runID"] as? String == run.id, let text = prepared["text"] as? String else {
                    throw BetaError("The synchronization candidate could not be prepared.")
                }
                candidate = Data(text.utf8)
                try SystemAccountSyncLedger.verifyNormalizedCandidate(required: required, proposed: candidate)
                let baseline = try finalized.normalizedBaseline(in: SystemAccountSyncLedger.decoded(candidate), source: plan.source)
                try ledger.stage(runID: run.id, candidate: candidate, baseline: SystemAccountSyncLedger.encoded(baseline.payload))
            }
            // Recovery also prepares the exact previously staged candidate, then
            // verifies that the current normalizer has not changed that evidence.
            if run.candidate != nil {
                let prepared = try await ui("return window.App.macOSBetaPrepareSystemSync(requestId, runID, candidate);",
                    ["requestId": requestID, "runID": run.id, "candidate": String(decoding: candidate, as: UTF8.self)])
                guard prepared["ok"] as? Bool == true, let text = prepared["text"] as? String,
                      try SystemAccountSyncLedger.equal(candidate, Data(text.utf8)) else { throw BetaError("The staged synchronization candidate changed during recovery.") }
            }
            try requireCurrent(isCurrent)
            let candidateText = String(decoding: candidate, as: UTF8.self)
            candidateWrite(candidateText); defer { candidateWrite(nil) }
            let committed = try await ui("return await window.App.macOSBetaCommitSystemSync(requestId, runID, candidate);",
                ["requestId": requestID, "runID": run.id, "candidate": candidateText])
            try requireCurrent(isCurrent)
            guard committed["ok"] as? Bool == true, committed["requestId"] as? String == requestID,
                  committed["runID"] as? String == run.id, let text = committed["text"] as? String,
                  try SystemAccountSyncLedger.equal(candidate, Data(text.utf8)) else {
                throw BetaError("System synchronization did not receive a matching save acknowledgement.")
            }
            try ledger.complete(runID: run.id, evidence: disk())
            var summary = tr("Conflicts retained") + ": \(plan.conflicts.count); " + tr("Excluded entries") + ": \(plan.excluded.count)."
            if committed["renderingFailed"] as? Bool == true { summary += " " + tr("The data was saved, but the view could not be refreshed. Reopen the Organizer.") }
            return ["ok": true, "requestId": requestID, "bericht": summary]
        } catch {
            candidateWrite(nil)
            if let activeRunID { try? ledger.discardWithoutEffects(runID: activeRunID) }
            return ["ok": false, "requestId": requestID, "fehler": tr(error.localizedDescription)]
        }
    }
}
#endif
