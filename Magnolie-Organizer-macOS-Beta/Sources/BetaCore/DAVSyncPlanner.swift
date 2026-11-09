import Foundation
import CryptoKit

public enum DAVSyncPlannerError: Error, Equatable {
    case invalidInput, duplicateIdentity, unsupportedRecord, deletionConflict, invalidAcknowledgement, limit
}

/// Pure calendar planning. No network, profile saves, journal deletion or durable-sync claim.
/// Only finalize() may attach newly acknowledged ETags; its result still requires a durable book save.
public enum DAVSyncPlanner {
    public typealias Domain = DAVCalendarSnapshot.Kind
    public typealias Key = ICalendarResourcePatch.Key
    /// One explicit source-scoped deletion intent. A future book adapter expands/rejoins
    /// multi-provider tombstones; payload is opaque and never used to infer other-source deletes.
    public struct Deletion {
        public let domain: Domain, sourceUID: String, key: Key, href: URL, etag: String, syncEpoch: String
        public let payload: [String: Any]
        public init(domain: Domain, sourceUID: String, key: Key, href: URL, etag: String, syncEpoch: String, payload: [String: Any] = [:]) {
            self.domain = domain; self.sourceUID = sourceUID; self.key = key; self.href = href; self.etag = etag
            self.syncEpoch = syncEpoch; self.payload = payload
        }
    }
    public struct LocalState {
        public let appointments: [[String: Any]], tasks: [[String: Any]], anniversaries: [[String: Any]]
        public let deletions: [Deletion]
        public let assignUnboundAppointments: Bool, assignUnboundTasks: Bool, assignUnboundAnniversaries: Bool
        public init(appointments: [[String: Any]], tasks: [[String: Any]], anniversaries: [[String: Any]], deletions: [Deletion] = [],
                    assignUnboundAppointments: Bool = false, assignUnboundTasks: Bool = false, assignUnboundAnniversaries: Bool = false) {
            self.appointments = appointments; self.tasks = tasks; self.anniversaries = anniversaries; self.deletions = deletions
            self.assignUnboundAppointments = assignUnboundAppointments; self.assignUnboundTasks = assignUnboundTasks
            self.assignUnboundAnniversaries = assignUnboundAnniversaries
        }
    }
    public struct Entry {
        public let domain: Domain, key: Key, localUID: String, href: URL, etag: String, format: String, localHash: String, remoteHash: String
        public init(domain: Domain, key: Key, localUID: String, href: URL, etag: String, format: String = DAVSyncBaseline.format,
                    localHash: String, remoteHash: String) {
            self.domain = domain; self.key = key; self.localUID = localUID; self.href = href; self.etag = etag
            self.format = format; self.localHash = localHash; self.remoteHash = remoteHash
        }
    }
    public struct Baseline {
        public let sourceUID: String, syncEpoch: String
        public let appointmentsInitialized: Bool, tasksInitialized: Bool, anniversariesInitialized: Bool
        public let entries: [Entry]
        public init(sourceUID: String, syncEpoch: String, appointmentsInitialized: Bool, tasksInitialized: Bool,
                    anniversariesInitialized: Bool, entries: [Entry]) {
            self.sourceUID = sourceUID; self.syncEpoch = syncEpoch; self.appointmentsInitialized = appointmentsInitialized
            self.tasksInitialized = tasksInitialized; self.anniversariesInitialized = anniversariesInitialized; self.entries = entries
        }
    }
    public struct Operation {
        public enum Kind: String { case create, update, delete }
        public let id: String, kind: Kind, href: URL, expectedETag: String?, bytes: Data?, componentKeys: [Key]
        public var ifNoneMatch: String? { kind == .create ? "*" : nil }
    }
    public struct Acknowledgement {
        public let operationID: String, href: URL, status: Int, etag: String?
        public init(operationID: String, href: URL, status: Int, etag: String? = nil) {
            self.operationID = operationID; self.href = href; self.status = status; self.etag = etag
        }
    }
    public struct Finalized {
        public let state: LocalState, baseline: Baseline
        /// This is a projected, remotely acknowledged candidate, NOT a disk-commit receipt.
    }
    fileprivate struct Assignment {
        let domain: Domain, key: Key, uid: String, href: URL, etag: String
    }
    public struct Plan {
        public let sourceUID: String, syncEpoch: String, createdAt: Date
        public let preview: LocalState, operations: [Operation], conflictCopies: Int, quarantinedDeletions: Int
        private let assignments: [Assignment]
        private let supportsTasks: Bool
        private let preservedTaskEntries: [Entry]
        private let priorTasksInitialized: Bool
        fileprivate init(sourceUID: String, syncEpoch: String, createdAt: Date, preview: LocalState, operations: [Operation],
                         conflictCopies: Int, quarantinedDeletions: Int, assignments: [Assignment], supportsTasks: Bool, preservedTaskEntries: [Entry], priorTasksInitialized: Bool) {
            self.sourceUID = sourceUID; self.syncEpoch = syncEpoch; self.createdAt = createdAt; self.preview = preview
            self.operations = operations; self.conflictCopies = conflictCopies; self.quarantinedDeletions = quarantinedDeletions
            self.assignments = assignments; self.supportsTasks = supportsTasks
            self.preservedTaskEntries = preservedTaskEntries; self.priorTasksInitialized = priorTasksInitialized
        }
        public func finalize(acknowledgements: [Acknowledgement]) throws -> Finalized {
            guard acknowledgements.count == operations.count else { throw DAVSyncPlannerError.invalidAcknowledgement }
            var responses: [String: Acknowledgement] = [:]
            for response in acknowledgements {
                guard responses.updateValue(response, forKey: response.operationID) == nil else { throw DAVSyncPlannerError.invalidAcknowledgement }
            }
            var resourceETags: [URL: String] = [:]
            for operation in operations {
                guard let response = responses[operation.id], response.href == operation.href else { throw DAVSyncPlannerError.invalidAcknowledgement }
                if operation.kind == .delete {
                    guard [200, 204, 404].contains(response.status) else { throw DAVSyncPlannerError.invalidAcknowledgement }
                } else {
                    guard [200, 201, 204].contains(response.status), let etag = response.etag, DAVSyncPlanner.validETag(etag) else {
                        throw DAVSyncPlannerError.invalidAcknowledgement
                    }
                    resourceETags[operation.href] = etag
                }
            }
            var values = ["appointment": preview.appointments, "task": preview.tasks, "anniversary": preview.anniversaries]
            var entries: [Entry] = preservedTaskEntries
            var lookup: [OpaqueUTF8Identity: Int] = [:]
            for domain in [Domain.appointment, .task, .anniversary] {
                for (index, value) in values[domain.rawValue]!.enumerated() where OpaqueUTF8Identity(DAVSyncPlanner.text(value, "syncKalenderUid")) == OpaqueUTF8Identity(sourceUID) {
                    let key = OpaqueUTF8Identity(parts: [domain.rawValue, DAVSyncPlanner.text(value, "uid")])
                    guard lookup.updateValue(index, forKey: key) == nil else { throw DAVSyncPlannerError.invalidAcknowledgement }
                }
            }
            for domain in [Domain.appointment, .task, .anniversary] {
              var records = values[domain.rawValue]!
              for assignment in assignments where assignment.domain == domain {
                guard let index = lookup[OpaqueUTF8Identity(parts: [assignment.domain.rawValue, assignment.uid])] else { throw DAVSyncPlannerError.invalidAcknowledgement }
                let etag = resourceETags[assignment.href] ?? assignment.etag
                guard DAVSyncPlanner.validETag(etag) else { throw DAVSyncPlannerError.invalidAcknowledgement }
                let hash = try DAVSyncBaseline.hash(records[index], kind: assignment.domain)
                var bindings = records[index]["syncQuellen"] as? [String: Any] ?? [:]
                bindings[sourceUID] = ["id": assignment.href.absoluteString, "etag": etag,
                    "geaendert": records[index]["geaendert"] ?? 0, "inhaltFormat": DAVSyncBaseline.format,
                    "inhaltSha256": hash, "eigen": true]
                records[index]["syncQuellen"] = bindings; records[index]["davHref"] = assignment.href.absoluteString
                records[index]["davEtag"] = etag; records[index]["sync"] = true
                entries.append(Entry(domain: assignment.domain, key: assignment.key, localUID: assignment.uid,
                    href: assignment.href, etag: etag, localHash: hash, remoteHash: hash))
              }
              values[domain.rawValue] = records
            }
            return Finalized(state: LocalState(appointments: values["appointment"]!, tasks: values["task"]!, anniversaries: values["anniversary"]!, deletions: preview.deletions),
                baseline: Baseline(sourceUID: sourceUID, syncEpoch: syncEpoch, appointmentsInitialized: true,
                    tasksInitialized: supportsTasks ? true : priorTasksInitialized, anniversariesInitialized: true, entries: entries))
        }
    }
    private struct Item { let domain: Domain, index: Int, key: Key, value: [String: Any] }
    private struct Desired { let domain: Domain, value: [String: Any] }
    private static func text(_ value: [String: Any], _ key: String) -> String { value[key] as? String ?? "" }
    private static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func group(_ key: Key) -> OpaqueUTF8Identity { OpaqueUTF8Identity(parts: [key.kind, key.uid]) }
    private static func ordered(_ key: Key) -> OpaqueUTF8Identity { OpaqueUTF8Identity(parts: [key.kind, key.uid, key.recurrenceID == nil ? "absent" : "present", key.recurrenceID ?? ""]) }
    private static func validETag(_ etag: String) -> Bool {
        let trimmed = etag.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != "*" && !etag.unicodeScalars.contains { $0.value < 32 || $0.value == 127 }
    }
    private static func compatible(_ entry: Entry) -> Bool {
        validETag(entry.etag) && !entry.localUID.isEmpty &&
        entry.localHash.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil &&
        entry.remoteHash.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil &&
        (entry.format == DAVSyncBaseline.format || entry.domain == .appointment && entry.format == "linux-calendar-2" || entry.domain == .task && entry.format == "linux-1")
    }
    private static func hash(_ value: [String: Any], _ domain: Domain, format: String) throws -> String {
        format == DAVSyncBaseline.format ? try DAVSyncBaseline.hash(value, kind: domain) : try DAVSyncBaseline.linuxCompatibilityHash(value, kind: domain)
    }
    private static func localKey(_ value: [String: Any], domain: Domain) throws -> Key {
        let uid = text(value, "icsSerienUid").isEmpty ? text(value, "uid") : text(value, "icsSerienUid")
        guard !uid.isEmpty else { throw DAVSyncPlannerError.invalidInput }
        let raw = value["icsRoundtrip"] as? [String] ?? []
        var depth = 0, rid: String?
        for line in raw {
            let name = line.prefix { $0 != ";" && $0 != ":" }.uppercased()
            if name == "BEGIN" { depth += 1 }
            if depth == 0 && name == "RECURRENCE-ID" { guard rid == nil else { throw DAVSyncPlannerError.invalidInput }; rid = line }
            if name == "END" { depth -= 1 }
        }
        let escaped = uid.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\n", with: "\\n").replacingOccurrences(of: ",", with: "\\,").replacingOccurrences(of: ";", with: "\\;")
        let kind = domain == .task ? "VTODO" : "VEVENT"
        let probe = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:\(kind)\r\nUID:\(escaped)\r\n" + (rid.map { $0 + "\r\n" } ?? "") + "END:\(kind)\r\nEND:VCALENDAR\r\n"
        guard let key = try ICalendarResourcePatch.keys(from: Data(probe.utf8)).first else { throw DAVSyncPlannerError.invalidInput }
        return key
    }

    public static func plan(context: CalendarTimeContext, snapshot: DAVCalendarSnapshot.Result, local: LocalState, baseline: Baseline?,
                            restoreAdditive: Bool, syncEpoch: String, createdAt: Date,
                            cancellation: () -> Bool = { false }) throws -> Plan {
        func check() throws { if cancellation() { throw CancellationError() }; try Task.checkCancellation() }
        try check()
        guard !syncEpoch.isEmpty, syncEpoch.utf8.count <= 1024, createdAt.timeIntervalSince1970.isFinite,
              local.appointments.count + local.tasks.count + local.anniversaries.count <= ICalendarImport.maximumRecords,
              local.deletions.count <= ICalendarImport.maximumRecords,
              (baseline?.entries.count ?? 0) <= ICalendarImport.maximumRecords else { throw DAVSyncPlannerError.limit }
        let source = snapshot.source, supportsTasks = snapshot.tasks != nil
        guard baseline == nil || OpaqueUTF8Identity(baseline!.sourceUID) == OpaqueUTF8Identity(source.uid) else { throw DAVSyncPlannerError.invalidInput }
        let arrays = ["appointment": local.appointments, "task": local.tasks, "anniversary": local.anniversaries]
        let deletionData: [[String: Any]] = local.deletions.map {
            ["domain": $0.domain.rawValue, "sourceUID": $0.sourceUID, "uid": $0.key.uid, "kind": $0.key.kind,
             "recurrenceID": $0.key.recurrenceID ?? "", "href": $0.href.absoluteString,
             "etag": $0.etag, "epoch": $0.syncEpoch, "payload": $0.payload]
        }
        guard try JSONSerialization.data(withJSONObject: ["records": arrays, "deletions": deletionData]).count <= ICalendarImport.maximumProjectedBytes else { throw DAVSyncPlannerError.limit }
        let baselineData: [[String: Any]] = (baseline?.entries ?? []).map {
            ["domain": $0.domain.rawValue, "uid": $0.key.uid, "kind": $0.key.kind, "rid": $0.key.recurrenceID ?? "",
             "localUID": $0.localUID, "href": $0.href.absoluteString, "etag": $0.etag, "format": $0.format,
             "localHash": $0.localHash, "remoteHash": $0.remoteHash]
        }
        guard try JSONSerialization.data(withJSONObject: baselineData).count <= ICalendarImport.maximumProjectedBytes else { throw DAVSyncPlannerError.limit }
        var output = arrays.mapValues { $0.map { Optional($0) } }
        var appended: [String: [[String: Any]]] = ["appointment": [], "task": [], "anniversary": []]
        let remoteRows = snapshot.resources.flatMap(\.records)
        var remote: [Key: DAVCalendarSnapshot.Record] = [:], base: [Key: Entry] = [:]
        var remoteByUID: [OpaqueUTF8Identity: DAVCalendarSnapshot.Record] = [:], baseByUID: [OpaqueUTF8Identity: Entry] = [:]
        var remoteByGroup: [OpaqueUTF8Identity: [DAVCalendarSnapshot.Record]] = [:]
        for row in remoteRows {
            guard remote.updateValue(row, forKey: row.wireKey) == nil,
                  remoteByUID.updateValue(row, forKey: OpaqueUTF8Identity(parts: [row.kind.rawValue, text(row.value, "uid")])) == nil else { throw DAVSyncPlannerError.duplicateIdentity }
            remoteByGroup[group(row.wireKey), default: []].append(row)
        }
        for entry in baseline?.entries ?? [] {
            guard entry.key.kind == (entry.domain == .task ? "VTODO" : "VEVENT"), !entry.key.uid.isEmpty, !entry.localUID.isEmpty else { throw DAVSyncPlannerError.invalidInput }
            let key = try localKey(["uid": entry.key.uid, "icsRoundtrip": entry.key.recurrenceID.map { [$0] } ?? []], domain: entry.domain)
            let normalized = Entry(domain: entry.domain, key: key, localUID: entry.localUID, href: entry.href, etag: entry.etag,
                format: entry.format, localHash: entry.localHash, remoteHash: entry.remoteHash)
            guard base.updateValue(normalized, forKey: key) == nil,
                  baseByUID.updateValue(normalized, forKey: OpaqueUTF8Identity(parts: [entry.domain.rawValue, entry.localUID])) == nil else { throw DAVSyncPlannerError.duplicateIdentity }
        }
        var additiveDomains: [String: Bool] = [:]
        for domain in [Domain.appointment, .task, .anniversary] {
            if restoreAdditive || baseline == nil || baseline!.syncEpoch != syncEpoch { additiveDomains[domain.rawValue] = true }
            else {
                let baseline = baseline!
                let initialized = domain == .appointment ? baseline.appointmentsInitialized : domain == .task ? baseline.tasksInitialized : baseline.anniversariesInitialized
                additiveDomains[domain.rawValue] = !initialized || baseline.entries.contains { $0.domain == domain && !compatible($0) }
            }
        }
        func additive(_ domain: Domain) -> Bool { additiveDomains[domain.rawValue]! }
        var items: [Item] = [], seenLocal = Set<OpaqueUTF8Identity>()
        for domain in [Domain.appointment, .task, .anniversary] {
            if domain == .task && !supportsTasks { continue }
            let unbound = domain == .appointment ? local.assignUnboundAppointments : domain == .task ? local.assignUnboundTasks : local.assignUnboundAnniversaries
            for (index, value) in arrays[domain.rawValue]!.enumerated() {
                try check()
                let owner = text(value, "syncKalenderUid"), bindings = value["syncQuellen"] as? [String: Any] ?? [:]
                guard OpaqueUTF8Identity(owner) == OpaqueUTF8Identity(source.uid) || bindings[source.uid] != nil || owner.isEmpty && bindings.isEmpty && unbound else { continue }
                let uid = text(value, "uid")
                guard !uid.isEmpty, seenLocal.insert(OpaqueUTF8Identity(parts: [domain.rawValue, uid])).inserted else { throw DAVSyncPlannerError.duplicateIdentity }
                let key = try baseByUID[OpaqueUTF8Identity(parts: [domain.rawValue, uid])]?.key ?? remoteByUID[OpaqueUTF8Identity(parts: [domain.rawValue, uid])]?.wireKey ?? localKey(value, domain: domain)
                items.append(Item(domain: domain, index: index, key: key, value: value))
            }
        }
        var localByKey: [Key: Item] = [:]
        let localByGroup = Dictionary(grouping: items, by: { group($0.key) })
        for item in items { guard localByKey.updateValue(item, forKey: item.key) == nil else { throw DAVSyncPlannerError.duplicateIdentity } }
        var conflictingGroups = Set<OpaqueUTF8Identity>()
        for item in items {
            guard let row = remote[item.key] else { continue }
            if row.kind != item.domain { conflictingGroups.insert(group(item.key)); continue }
            let localHash = try DAVSyncBaseline.hash(item.value, kind: item.domain), remoteHash = try DAVSyncBaseline.hash(row.value, kind: item.domain)
            guard localHash != remoteHash else { continue }
            if additive(item.domain) { conflictingGroups.insert(group(item.key)); continue }
            guard let entry = base[item.key] else { conflictingGroups.insert(group(item.key)); continue }
            let dirty = try hash(item.value, item.domain, format: entry.format) != entry.localHash
            let observedHash = try hash(row.value, item.domain, format: entry.format)
            let changed = entry.href != row.href || entry.etag != row.etag || observedHash != entry.remoteHash
            // Legacy hashes omit content fields now exposed by native codecs (for example color).
            // A legacy "clean" marker cannot establish which side owns an untracked difference.
            if dirty && changed || entry.format != DAVSyncBaseline.format {
                conflictingGroups.insert(group(item.key))
            }
        }
        var conflictCopies = 0, copiedRows: [(Domain, [String: Any])] = [], taskCopyUIDs: [OpaqueUTF8Identity: String] = [:]
        for identity in conflictingGroups.sorted() {
            let members = localByGroup[identity]!.sorted { ordered($0.key) < ordered($1.key) }
            // Preserve the existing v1 raw-UTF8 digest wire contract. Typed lookup/order
            // keys must not rewrite previously deterministic conflict/resource identifiers.
            let material = try members.map { item -> String in
                let hash = try DAVSyncBaseline.hash(item.value, kind: item.domain)
                return item.key.kind + "\0" + item.key.uid + "\0" + (item.key.recurrenceID ?? "") + "\0" + (base[item.key]?.etag ?? "") + "\0" + hash
            }.joined(separator: "\n")
            let newUID = "mag-" + digest(Data(("native-dav-conflict-v1\0" + source.uid + "\0" + material).utf8)).prefix(32) + "@magnolie-organizer"
            for item in members {
                var copy = item.value
                let uid = item.key.recurrenceID.map { newUID + "-magnolie-instanz-" + digest(Data($0.utf8)).prefix(16) } ?? newUID
                if item.domain == .task { taskCopyUIDs[OpaqueUTF8Identity(text(item.value, "uid"))] = uid }
                copy["uid"] = uid; copy["id"] = digest(Data((source.uid + "\0" + uid).utf8)).prefix(32).description
                copy["icsSerienUid"] = newUID; copy["icsImportUid"] = newUID; copy["syncKalenderUid"] = source.uid; copy["sync"] = false
                for field in ["syncQuellen", "davHref", "davEtag"] { copy.removeValue(forKey: field) }
                copiedRows.append((item.domain, copy)); conflictCopies += 1
                output[item.domain.rawValue]![item.index] = nil
            }
        }
        for (domain, value) in copiedRows {
            var copy = value
            if domain == .task, let parent = taskCopyUIDs[OpaqueUTF8Identity(text(copy, "elternUid"))] { copy["elternUid"] = parent; copy["icsElternUid"] = parent }
            appended[domain.rawValue]!.append(copy)
        }
        var desired: [Key: Desired] = [:], hrefs: [Key: URL] = [:], etags: [Key: String] = [:], seenRemote = Set<Key>()
        var updateKeys = Set<Key>(), insertKeys = Set<Key>(), deleteKeys = Set<Key>()
        var pendingDeletes: [Deletion] = [], quarantined = 0
        var selectedDeletes: [Key: Deletion] = [:]
        for deletion in local.deletions {
            guard OpaqueUTF8Identity(deletion.sourceUID) == OpaqueUTF8Identity(source.uid), deletion.domain != .task || supportsTasks else { pendingDeletes.append(deletion); continue }
            if additive(deletion.domain) || deletion.syncEpoch != syncEpoch { pendingDeletes.append(deletion); quarantined += 1; continue }
            guard deletion.key.kind == (deletion.domain == .task ? "VTODO" : "VEVENT") else { throw DAVSyncPlannerError.invalidInput }
            let key = try localKey(["uid": deletion.key.uid, "icsRoundtrip": deletion.key.recurrenceID.map { [$0] } ?? []], domain: deletion.domain)
            guard localByKey[key] == nil else { throw DAVSyncPlannerError.invalidInput }
            let normalized = Deletion(domain: deletion.domain, sourceUID: deletion.sourceUID, key: key, href: deletion.href,
                etag: deletion.etag, syncEpoch: deletion.syncEpoch, payload: deletion.payload)
            guard selectedDeletes.updateValue(normalized, forKey: key) == nil else { throw DAVSyncPlannerError.duplicateIdentity }
        }
        func bound(_ input: [String: Any]) -> [String: Any] {
            var value = input; value["syncKalenderUid"] = source.uid; value["sync"] = false; return value
        }
        func adopted(_ row: DAVCalendarSnapshot.Record, old: [String: Any]?) -> [String: Any] {
            var value = old ?? [:]
            for field in ["icsRoundtrip", "icsTimezones", "icsRangeOverrides", "icsAusnahmeTermine", "icsStatus", "icsAusnahmen", "icsZusatzDaten", "icsZusatzTermine", "icsReadOnly", "icsReadOnlyGrund"] { value.removeValue(forKey: field) }
            for (key, data) in row.value { value[key] = data }
            if let id = old?["id"] { value["id"] = id }
            return bound(value)
        }
        for item in items {
            try check()
            if conflictingGroups.contains(group(item.key)) { continue }
            guard selectedDeletes[item.key] == nil else { throw DAVSyncPlannerError.invalidInput }
            if let row = remote[item.key] {
                seenRemote.insert(item.key)
                var value: [String: Any]
                if !additive(item.domain), let entry = base[item.key], try hash(item.value, item.domain, format: entry.format) != entry.localHash,
                   try DAVSyncBaseline.hash(item.value, kind: item.domain) != DAVSyncBaseline.hash(row.value, kind: item.domain) {
                    value = bound(item.value)
                    if item.domain == .appointment {
                        let localSequence = (value["icsSequence"] as? NSNumber)?.int64Value ?? 0
                        let remoteSequence = (row.value["icsSequence"] as? NSNumber)?.int64Value ?? 0
                        guard max(localSequence, remoteSequence) < Int64.max else { throw DAVSyncPlannerError.invalidInput }
                        value["icsSequence"] = max(localSequence, remoteSequence) + 1
                        value["icsAenderungszeitFehlt"] = false
                    }
                    updateKeys.insert(item.key)
                } else { value = adopted(row, old: item.value) }
                output[item.domain.rawValue]![item.index] = value
                desired[item.key] = Desired(domain: item.domain, value: value); hrefs[item.key] = row.href; etags[item.key] = row.etag
            } else if !additive(item.domain), let entry = base[item.key], try hash(item.value, item.domain, format: entry.format) == entry.localHash {
                var value = item.value, bindings = value["syncQuellen"] as? [String: Any] ?? [:]
                bindings.removeValue(forKey: source.uid)
                if bindings.isEmpty { output[item.domain.rawValue]![item.index] = nil }
                else { value["syncQuellen"] = bindings; let owner = text(value, "syncKalenderUid"); value["syncKalenderUid"] = bindings[owner] != nil ? owner : bindings.keys.sorted().first!; value.removeValue(forKey: "davHref"); value.removeValue(forKey: "davEtag"); output[item.domain.rawValue]![item.index] = value }
            } else {
                let value = bound(item.value); output[item.domain.rawValue]![item.index] = value
                desired[item.key] = Desired(domain: item.domain, value: value); insertKeys.insert(item.key)
            }
        }
        for row in remoteRows where !seenRemote.contains(row.wireKey) {
            try check()
            if let deletion = selectedDeletes[row.wireKey] {
                guard let entry = base[row.wireKey], entry.href == deletion.href, deletion.href == row.href,
                      validETag(deletion.etag), deletion.etag == row.etag, entry.etag == deletion.etag else { throw DAVSyncPlannerError.deletionConflict }
                deleteKeys.insert(row.wireKey); hrefs[row.wireKey] = row.href; etags[row.wireKey] = row.etag
                selectedDeletes.removeValue(forKey: row.wireKey)
                continue
            }
            let prior = localByKey[row.wireKey]
            let old = prior?.domain == row.kind ? prior?.value : nil
            let value = adopted(row, old: old)
            appended[row.kind.rawValue]!.append(value); desired[row.wireKey] = Desired(domain: row.kind, value: value)
            hrefs[row.wireKey] = row.href; etags[row.wireKey] = row.etag
        }
        // A complete successful REPORT also confirms absence. Only current-epoch trusted
        // deletion intents are retired; unknown/restore intents remain explicitly quarantined.
        for (key, _) in selectedDeletes { guard remote[key] == nil else { throw DAVSyncPlannerError.deletionConflict } }
        var newGroups: [OpaqueUTF8Identity: [Key]] = [:]
        for key in insertKeys {
            if let sibling = remoteByGroup[group(key)]?.first { hrefs[key] = sibling.href; etags[key] = sibling.etag }
            else { newGroups[group(key), default: []].append(key) }
        }
        var operations: [Operation] = [], operationBytes = 0
        func operation(_ kind: Operation.Kind, _ href: URL, _ etag: String?, _ bytes: Data?, _ keys: [Key]) throws {
            let size = bytes?.count ?? 0
            guard size <= ICalendarImport.maximumBytes, operations.count < DAVClient.listLimit,
                  size <= DAVClient.itemLimit - operationBytes else { throw DAVSyncPlannerError.limit }
            operationBytes += size
            let material = "native-dav-operation-v1\0" + source.uid + "\0" + syncEpoch + "\0" + kind.rawValue + "\0" + href.absoluteString + "\0" + (etag ?? "") + "\0" + (bytes.map(digest) ?? "")
            operations.append(Operation(id: digest(Data(material.utf8)), kind: kind, href: href, expectedETag: etag, bytes: bytes, componentKeys: keys.sorted { ordered($0) < ordered($1) }))
        }
        for identity in newGroups.keys.sorted() {
            try check()
            let keys = newGroups[identity]!.sorted { ordered($0) < ordered($1) }
            let values = keys.map { desired[$0]! }
            let bytes = try encode(values, keys: keys, context: context, createdAt: createdAt)
            let href = source.href.appendingPathComponent(digest(Data((keys[0].kind + "\0" + keys[0].uid).utf8)) + ".ics")
            for key in keys { hrefs[key] = href; etags[key] = "" }
            try operation(.create, href, nil, bytes, keys)
        }
        let updatesByHref = Dictionary(grouping: Array(updateKeys), by: { hrefs[$0]! })
        let insertsByHref = Dictionary(grouping: Array(insertKeys.filter { hrefs[$0] != nil }), by: { hrefs[$0]! })
        let deletesByHref = Dictionary(grouping: Array(deleteKeys), by: { hrefs[$0]! })
        let desiredGroups = Dictionary(grouping: Array(desired.keys), by: { group($0) })
        for resource in snapshot.resources {
            try check()
            let updates = Set(updatesByHref[resource.href] ?? []), insertions = Set(insertsByHref[resource.href] ?? [])
            let deletions = Set(deletesByHref[resource.href] ?? [])
            guard !updates.isEmpty || !insertions.isEmpty || !deletions.isEmpty else { continue }
            var replacements: [ICalendarResourcePatch.Replacement] = [], additions: [ICalendarResourcePatch.Replacement] = []
            var extractedGroups: [OpaqueUTF8Identity: [Key: Data]] = [:], extractionBytes = 0
            for key in (updates.union(insertions)).sorted(by: { ordered($0) < ordered($1) }) {
                let identity = group(key)
                if extractedGroups[identity] == nil {
                    let members = desiredGroups[identity]!.sorted { ordered($0) < ordered($1) }
                    let encoded = try encode(members.map { desired[$0]! }, keys: members, context: context, createdAt: createdAt)
                    guard extractionBytes < ICalendarImport.maximumProjectedBytes else { throw DAVSyncPlannerError.limit }
                    let extracted = try ICalendarResourcePatch.extract(original: encoded, keys: members,
                        maximumOutputBytes: ICalendarImport.maximumProjectedBytes - extractionBytes)
                    extractionBytes += extracted.values.reduce(0) { $0 + $1.count }
                    extractedGroups[identity] = extracted
                }
                guard let single = extractedGroups[identity]![key] else { throw DAVSyncPlannerError.unsupportedRecord }
                let definitions = resource.records.first?.value["icsTimezones"] as? [[String]] ?? []
                let replacement = ICalendarResourcePatch.Replacement(key: key, calendar: stripExistingZones(single, definitions: definitions))
                if updates.contains(key) { replacements.append(replacement) } else { additions.append(replacement) }
            }
            let patched: ICalendarResourcePatch.Result
            do { patched = try ICalendarResourcePatch.apply(original: resource.bytes, replacements: replacements, insertions: additions, deletions: Array(deletions)) }
            catch { throw DAVSyncPlannerError.unsupportedRecord }
            try operation(patched.safeCanDeleteResource ? .delete : .update, resource.href, resource.etag,
                patched.safeCanDeleteResource ? nil : patched.data, Array(updates.union(insertions).union(deletions)))
        }
        guard operations.count <= DAVClient.listLimit, operations.reduce(0, { $0 + ($1.bytes?.count ?? 0) }) <= DAVClient.itemLimit else { throw DAVSyncPlannerError.limit }
        var assignments: [Assignment] = []
        for key in desired.keys.sorted(by: { ordered($0) < ordered($1) }) {
            guard let href = hrefs[key], let etag = etags[key] else { throw DAVSyncPlannerError.invalidInput }
            let value = desired[key]!
            assignments.append(Assignment(domain: value.domain, key: key, uid: text(value.value, "uid"), href: href, etag: etag))
        }
        func records(_ domain: Domain) -> [[String: Any]] { output[domain.rawValue]!.compactMap { $0 } + appended[domain.rawValue]! }
        let preview = LocalState(appointments: records(.appointment), tasks: records(.task), anniversaries: records(.anniversary), deletions: pendingDeletes)
        guard preview.appointments.count + preview.tasks.count + preview.anniversaries.count <= ICalendarImport.maximumRecords else { throw DAVSyncPlannerError.limit }
        try check()
        return Plan(sourceUID: source.uid, syncEpoch: syncEpoch, createdAt: createdAt, preview: preview,
            operations: operations.sorted { $0.href.absoluteString < $1.href.absoluteString }, conflictCopies: conflictCopies,
            quarantinedDeletions: quarantined, assignments: assignments, supportsTasks: supportsTasks,
            preservedTaskEntries: supportsTasks ? [] : (baseline?.entries.filter { $0.domain == .task } ?? []),
            priorTasksInitialized: !restoreAdditive && baseline?.syncEpoch == syncEpoch ? (baseline?.tasksInitialized ?? false) : false)
    }
    private static func encode(_ values: [Desired], keys: [Key], context: CalendarTimeContext, createdAt: Date) throws -> Data {
        guard !values.isEmpty, values.count == keys.count, let domain = values.first?.domain,
              values.allSatisfy({ $0.domain == domain }) else { throw DAVSyncPlannerError.unsupportedRecord }
        let kind: ICalendarExport.Kind = domain == .task ? .tasks : domain == .anniversary ? .anniversaries : .appointments
        let records = zip(values, keys).map { value, key -> [String: Any] in
            var record = value.value
            for field in ["sync", "syncQuellen", "davHref", "davEtag", "icsReadOnly", "icsReadOnlyGrund"] { record.removeValue(forKey: field) }
            if domain != .task {
                record["icsImportUid"] = key.uid
                if !text(record, "icsSerienUid").isEmpty { record["icsSerienUid"] = key.uid }
            }
            return record
        }
        do {
            let wireUIDs = Dictionary(uniqueKeysWithValues: zip(records, keys).map { (OpaqueUTF8Identity(text($0.0, "uid")), $0.1.uid) })
            let bytes = Data(try ICalendarExport.encode(records, context: context, kind: kind, timestamp: createdAt, wireUIDs: wireUIDs).utf8)
            guard Set(try ICalendarResourcePatch.keys(from: bytes)) == Set(keys) else { throw DAVSyncPlannerError.unsupportedRecord }
            return bytes
        } catch { throw DAVSyncPlannerError.unsupportedRecord }
    }
    /// Only generated, already validated exporter output is scanned here. Matching source-zone
    /// definitions remain byte-exact in the original resource instead of being rewritten as CRLF.
    internal static func stripExistingZones(_ generated: Data, definitions: [[String]]) -> Data {
        guard !definitions.isEmpty, let text = String(data: generated, encoding: .utf8) else { return generated }
        let lines = text.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var output: [String] = [], block: [String] = [], inZone = false
        for line in lines {
            if line.uppercased() == "BEGIN:VTIMEZONE" { inZone = true; block = [] }
            if inZone {
                block.append(line)
                if line.uppercased() == "END:VTIMEZONE" {
                    var unfolded: [String] = []
                    for part in block { if (part.hasPrefix(" ") || part.hasPrefix("\t")), !unfolded.isEmpty { unfolded[unfolded.count - 1] += part.dropFirst() } else { unfolded.append(part) } }
                    if !definitions.contains(where: { OpaqueUTF8Identity(parts: $0) == OpaqueUTF8Identity(parts: unfolded) }) { output.append(contentsOf: block) }
                    inZone = false
                }
            } else { output.append(line) }
        }
        return inZone ? generated : Data(output.joined(separator: "\r\n").utf8)
    }
}
