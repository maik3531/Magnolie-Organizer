import Foundation
import CoreFoundation

/// Refs #786. Native account *field* synchronization. Authority and persistence
/// belong to the host ledger, never to fields imported from an Organizer book.
/// There are deliberately no native create/delete operations in this version.
public enum SystemAccountSync {
    public static let version = 1
    public static let maximumRecords = 100
    public static let maximumBytes = 32 * 1024 * 1024

    /// Only this error proves that the adapter has not entered a native save.
    /// Every other apply error has an uncertain outcome and must retain its journal.
    public struct RejectedBeforeWrite: Error, LocalizedError {
        public let reason: String
        public init(_ reason: String) { self.reason = reason }
        public var errorDescription: String? { reason }
    }

    public struct Source {
        public let kind: SystemSourcePolicy.Kind, sourceUID: String, title: String
        public let metadata: [String: Any], scope: [String: Any], displayTimeZone: String
        public let fingerprint: String
        public var collection: String {
            switch kind { case .events: return "termine"; case .reminders: return "aufgaben"; case .contacts: return "kontakte" }
        }
        public var payload: [String: Any] {
            ["version": version, "kind": kind.rawValue, "sourceUID": sourceUID, "title": title,
             "metadata": metadata, "scope": scope, "displayTimeZone": displayTimeZone, "fingerprint": fingerprint]
        }
        public init(kind: SystemSourcePolicy.Kind, sourceUID: String, title: String,
                    metadata: [String: Any], scope: [String: Any], displayTimeZone: String) throws {
            _ = try SystemSourcePolicy.identifier(sourceUID, kind: kind)
            guard title.utf8.count <= 4096, !displayTimeZone.isEmpty, displayTimeZone != "system",
                  displayTimeZone.utf8.count <= 1024 else { throw failure("invalid source identity or display timezone") }
            if kind == .events {
                guard Set(scope.keys) == ["start", "end"], let start = number(scope["start"]), let end = number(scope["end"]) else {
                    throw failure("event synchronization needs an explicit bounded window")
                }
                try SystemSourcePolicy.requireWindow(start: Date(timeIntervalSince1970: start), end: Date(timeIntervalSince1970: end))
            } else {
                guard scope["kind"] as? String == "full-source", scope.count == 1 else { throw failure("invalid source scope") }
            }
            self.kind = kind; self.sourceUID = sourceUID; self.title = title
            self.metadata = try frozen(metadata); self.scope = try frozen(scope); self.displayTimeZone = displayTimeZone
            // A moving event window is observation scope, not a new native source.
            // The host additionally binds the explicitly approved scope and zone.
            fingerprint = try SystemSourcePolicy.revision(["version": version, "kind": kind.rawValue,
                "sourceUID": sourceUID, "title": title, "metadata": self.metadata, "displayTimeZone": displayTimeZone])
        }
        public init(payload: [String: Any]) throws {
            try keys(payload, ["version", "kind", "sourceUID", "title", "metadata", "scope", "displayTimeZone", "fingerprint"])
            guard integer(payload["version"]) == version, let kind = SystemSourcePolicy.Kind(rawValue: try text(payload, "kind")),
                  let metadata = payload["metadata"] as? [String: Any], let scope = payload["scope"] as? [String: Any] else { throw failure("invalid persisted source") }
            try self.init(kind: kind, sourceUID: text(payload, "sourceUID"), title: text(payload, "title"),
                          metadata: metadata, scope: scope, displayTimeZone: text(payload, "displayTimeZone"))
            guard same(fingerprint, try text(payload, "fingerprint")) else { throw failure("source fingerprint mismatch") }
        }
    }

    public struct Record {
        public let identifier: String, sourceFingerprint: String, canonicalRecord: [String: Any]
        public let nativeFields: [String: Any], revision: String
        public var payload: [String: Any] {
            ["identifier": identifier, "sourceFingerprint": sourceFingerprint, "canonicalRecord": canonicalRecord,
             "nativeFields": nativeFields, "revision": revision]
        }
        public init(identifier: String, source: Source, canonicalRecord: [String: Any], nativeFields: [String: Any]) throws {
            guard !identifier.isEmpty, identifier.utf8.count <= 16_384 else { throw failure("invalid native record identity") }
            self.identifier = identifier; sourceFingerprint = source.fingerprint
            self.canonicalRecord = try frozen(canonicalRecord); self.nativeFields = try frozen(nativeFields)
            revision = try SystemSourcePolicy.revision(["sourceFingerprint": source.fingerprint,
                "identifier": identifier, "canonicalRecord": self.canonicalRecord, "nativeFields": self.nativeFields])
        }
        public init(payload: [String: Any]) throws {
            try keys(payload, ["identifier", "sourceFingerprint", "canonicalRecord", "nativeFields", "revision"])
            identifier = try text(payload, "identifier", empty: false, maximum: 16_384)
            sourceFingerprint = try digest(payload, "sourceFingerprint")
            guard let canonical = payload["canonicalRecord"] as? [String: Any], let native = payload["nativeFields"] as? [String: Any] else {
                throw failure("invalid persisted native record")
            }
            canonicalRecord = try frozen(canonical); nativeFields = try frozen(native); revision = try digest(payload, "revision")
            guard same(revision, try SystemSourcePolicy.revision(["sourceFingerprint": sourceFingerprint,
                "identifier": identifier, "canonicalRecord": canonicalRecord, "nativeFields": nativeFields])) else { throw failure("native record revision mismatch") }
        }
    }

    public struct Snapshot {
        public let source: Source, records: [Record], excluded: [[String: Any]]
        public var payload: [String: Any] { ["source": source.payload, "records": records.map(\.payload), "excluded": excluded] }
        public init(source: Source, records: [Record], excluded: [[String: Any]] = []) throws {
            guard records.count + excluded.count <= maximumRecords else { throw failure("select a source/window containing at most 100 entries") }
            var seen = Set<OpaqueUTF8Identity>()
            for record in records {
                guard same(record.sourceFingerprint, source.fingerprint), seen.insert(OpaqueUTF8Identity(record.identifier)).inserted else {
                    throw failure("ambiguous or mismatched native identity")
                }
            }
            self.source = source; self.records = records; self.excluded = try excluded.map(frozen)
            _ = try frozen(payload)
        }
    }

    public struct Baseline {
        public struct Entry {
            public let identifier: String, localID: String, localFields: [String: Any], nativeRecord: Record
            public var payload: [String: Any] {
                ["identifier": identifier, "localID": localID, "localFields": localFields, "nativeRecord": nativeRecord.payload]
            }
            public init(identifier: String, localID: String, localFields: [String: Any], nativeRecord: Record) throws {
                guard same(identifier, nativeRecord.identifier), !localID.isEmpty, localID.utf8.count <= 16_384 else { throw failure("invalid baseline binding") }
                self.identifier = identifier; self.localID = localID; self.localFields = try frozen(localFields); self.nativeRecord = nativeRecord
            }
            public init(payload: [String: Any]) throws {
                try keys(payload, ["identifier", "localID", "localFields", "nativeRecord"])
                guard let local = payload["localFields"] as? [String: Any], let record = payload["nativeRecord"] as? [String: Any] else { throw failure("invalid persisted baseline entry") }
                try self.init(identifier: text(payload, "identifier"), localID: text(payload, "localID"), localFields: local, nativeRecord: Record(payload: record))
            }
        }
        public let sourceFingerprint: String, entries: [Entry]
        public var payload: [String: Any] { ["version": version, "sourceFingerprint": sourceFingerprint, "entries": entries.map(\.payload)] }
        public init(sourceFingerprint: String, entries: [Entry] = []) throws {
            guard isDigest(sourceFingerprint), entries.count <= 10_000 else { throw failure("invalid baseline scope") }
            var native = Set<OpaqueUTF8Identity>(), local = Set<OpaqueUTF8Identity>()
            for entry in entries {
                guard same(entry.nativeRecord.sourceFingerprint, sourceFingerprint), native.insert(OpaqueUTF8Identity(entry.identifier)).inserted,
                      local.insert(OpaqueUTF8Identity(entry.localID)).inserted else { throw failure("ambiguous baseline identity") }
            }
            self.sourceFingerprint = sourceFingerprint; self.entries = entries
            _ = try frozen(payload)
        }
        public init(payload: [String: Any]) throws {
            try keys(payload, ["version", "sourceFingerprint", "entries"])
            guard integer(payload["version"]) == version, let entries = payload["entries"] as? [[String: Any]] else { throw failure("invalid persisted baseline") }
            try self.init(sourceFingerprint: digest(payload, "sourceFingerprint"), entries: entries.map { try Entry(payload: $0) })
        }
    }

    public struct Operation {
        public let id: String, localID: String, before: Record, nativePatch: [String: Any], desiredRecord: [String: Any]
        public let changedGroups: [String]
        public var identifier: String { before.identifier }
        public var payload: [String: Any] { ["id": id, "localID": localID, "before": before.payload,
            "nativePatch": nativePatch, "desiredRecord": desiredRecord, "changedGroups": changedGroups] }
        init(id: String = UUID().uuidString, localID: String, before: Record, nativePatch: [String: Any], desiredRecord: [String: Any], changedGroups: [String]) throws {
            guard UUID(uuidString: id) != nil, !localID.isEmpty, !nativePatch.isEmpty, !changedGroups.isEmpty,
                  Set(changedGroups).count == changedGroups.count else { throw failure("invalid field update operation") }
            self.id = id; self.localID = localID; self.before = before
            self.nativePatch = try frozen(nativePatch); self.desiredRecord = try frozen(desiredRecord); self.changedGroups = changedGroups
        }
        public init(payload: [String: Any]) throws {
            try keys(payload, ["id", "localID", "before", "nativePatch", "desiredRecord", "changedGroups"])
            guard let before = payload["before"] as? [String: Any], let patch = payload["nativePatch"] as? [String: Any],
                  let desired = payload["desiredRecord"] as? [String: Any], let groups = payload["changedGroups"] as? [String] else { throw failure("invalid persisted operation") }
            try self.init(id: text(payload, "id"), localID: text(payload, "localID"), before: Record(payload: before),
                          nativePatch: patch, desiredRecord: desired, changedGroups: groups)
        }
        /// A successful native API return alone is not an acknowledgement. The
        /// identity, requested values and all other observed fields must survive.
        public func validateReadback(_ record: Record) throws {
            guard same(record.identifier, before.identifier), same(record.sourceFingerprint, before.sourceFingerprint) else {
                throw failure("native identity changed after saving; retain the journal and review the source")
            }
            for (key, expected) in nativePatch {
                guard let actual = record.nativeFields[key], try matchesNativeField(key, expected: expected, actual: actual) else { throw failure("native readback did not retain the requested field: " + key) }
            }
            var allowed = Set(nativePatch.keys)
            allowed.insert("modified")
            if nativePatch["notes"] != nil { allowed.insert("hasNotes") }
            if nativePatch["completed"] != nil { allowed.insert("completionDate") }
            for key in Set(before.nativeFields.keys).union(record.nativeFields.keys) where !allowed.contains(key) {
                guard try equal(before.nativeFields[key] ?? NSNull(), record.nativeFields[key] ?? NSNull()) else {
                    throw failure("another native field changed during saving: " + key + "; retain the journal")
                }
            }
        }
    }

    public struct Finalized {
        public let candidateBook: [String: Any], baseline: Baseline
        fileprivate let normalizable: Set<OpaqueUTF8Identity>
        /// Defaults from the actual shared normalizer are bound only after an
        /// exact no-change/no-removal proof. Conflict/missing-record baselines
        /// never advance merely because the local editor has a different value.
        public func normalizedBaseline(in normalizedBook: [String: Any], source: Source) throws -> Baseline {
            guard same(source.fingerprint, baseline.sourceFingerprint) else { throw failure("normalized baseline source mismatch") }
            var nodes = 0
            func check(_ expected: Any, _ actual: Any, depth: Int) throws {
                nodes += 1
                guard depth < 64, nodes <= 2_000_000 else { throw failure("normalized candidate structure limit") }
                if let object = expected as? [String: Any] {
                    guard let other = actual as? [String: Any] else { throw failure("normalization changed a planned value") }
                    let indexed = Dictionary(uniqueKeysWithValues: other.map { (OpaqueUTF8Identity($0.key), $0.value) })
                    for (key, value) in object {
                        guard let next = indexed[OpaqueUTF8Identity(key)] else { throw failure("normalization removed a planned field") }
                        try check(value, next, depth: depth + 1)
                    }
                } else if let array = expected as? [Any] {
                    guard let other = actual as? [Any], array.count == other.count else { throw failure("normalization changed a planned collection") }
                    for (left, right) in zip(array, other) { try check(left, right, depth: depth + 1) }
                } else if try !equal(expected, actual) { throw failure("normalization changed a planned value") }
            }
            let book = try frozen(normalizedBook)
            try check(candidateBook, book, depth: 0)
            guard let rows = book[source.collection] as? [[String: Any]] else { throw failure("normalized collection is missing") }
            var indexed: [OpaqueUTF8Identity: [String: Any]] = [:]
            for row in rows {
                guard let id = row["id"] as? String, indexed.updateValue(row, forKey: OpaqueUTF8Identity(id)) == nil else { throw failure("ambiguous normalized local identity") }
            }
            let entries = try baseline.entries.map { entry -> Baseline.Entry in
                guard normalizable.contains(OpaqueUTF8Identity(entry.identifier)) else { return entry }
                guard let row = indexed[OpaqueUTF8Identity(entry.localID)] else { throw failure("normalized local binding is missing") }
                return try .init(identifier: entry.identifier, localID: entry.localID,
                    localFields: SystemAccountSyncProjection.fields(row, kind: source.kind), nativeRecord: entry.nativeRecord)
            }
            return try Baseline(sourceFingerprint: baseline.sourceFingerprint, entries: entries)
        }
    }

    public struct Plan {
        public let source: Source, candidateBook: [String: Any], operations: [Operation]
        public let conflicts: [[String: Any]], excluded: [[String: Any]], nextBaseline: Baseline
        public var payload: [String: Any] { ["version": version, "source": source.payload, "candidateBook": candidateBook,
            "operations": operations.map(\.payload), "conflicts": conflicts, "excluded": excluded, "nextBaseline": nextBaseline.payload] }
        init(source: Source, candidateBook: [String: Any], operations: [Operation], conflicts: [[String: Any]], excluded: [[String: Any]], nextBaseline: Baseline) throws {
            guard same(source.fingerprint, nextBaseline.sourceFingerprint), operations.count <= maximumRecords else { throw failure("plan source mismatch") }
            var identifiers = Set<OpaqueUTF8Identity>(), ids = Set<String>()
            for operation in operations {
                guard same(operation.before.sourceFingerprint, source.fingerprint), identifiers.insert(OpaqueUTF8Identity(operation.identifier)).inserted,
                      ids.insert(operation.id).inserted else { throw failure("ambiguous plan operation") }
            }
            self.source = source; self.candidateBook = try frozen(candidateBook); self.operations = operations
            self.conflicts = try conflicts.map(frozen); self.excluded = try excluded.map(frozen); self.nextBaseline = nextBaseline
            _ = try frozen(payload)
        }
        public init(payload: [String: Any]) throws {
            try keys(payload, ["version", "source", "candidateBook", "operations", "conflicts", "excluded", "nextBaseline"])
            guard integer(payload["version"]) == version, let source = payload["source"] as? [String: Any], let candidate = payload["candidateBook"] as? [String: Any],
                  let operations = payload["operations"] as? [[String: Any]], let conflicts = payload["conflicts"] as? [[String: Any]],
                  let excluded = payload["excluded"] as? [[String: Any]], let baseline = payload["nextBaseline"] as? [String: Any] else { throw failure("invalid persisted plan") }
            try self.init(source: Source(payload: source), candidateBook: candidate, operations: operations.map { try Operation(payload: $0) },
                          conflicts: conflicts, excluded: excluded, nextBaseline: Baseline(payload: baseline))
        }
        public func finalize(readbacks: [Record]) throws -> Finalized {
            guard readbacks.count == operations.count else { throw failure("not all native operations have verified readbacks") }
            var byIdentifier: [OpaqueUTF8Identity: Record] = [:]
            for readback in readbacks {
                guard byIdentifier.updateValue(readback, forKey: OpaqueUTF8Identity(readback.identifier)) == nil else { throw failure("duplicate native readback") }
            }
            var book = candidateBook
            guard var rows = book[source.collection] as? [[String: Any]] else { throw failure("candidate collection is unavailable") }
            var entries = nextBaseline.entries
            for operation in operations {
                guard let readback = byIdentifier[OpaqueUTF8Identity(operation.identifier)] else { throw failure("native readback is missing") }
                try operation.validateReadback(readback)
                guard let index = rows.firstIndex(where: { same($0["id"] as? String ?? "", operation.localID) }),
                      let entry = entries.firstIndex(where: { same($0.identifier, operation.identifier) }) else { throw failure("candidate identity changed") }
                // Reprojection is the authority for derived date/vCard/display
                // fields. Unrelated local/unknown fields are never replaced.
                for key in SystemAccountSyncProjection.managedKeys(source.kind) {
                    if let value = readback.canonicalRecord[key] { rows[index][key] = value }
                }
                SystemAccountSyncProjection.copyEvidence(from: readback.canonicalRecord, to: &rows[index])
                entries[entry] = try Baseline.Entry(identifier: readback.identifier, localID: operation.localID,
                    localFields: SystemAccountSyncProjection.fields(rows[index], kind: source.kind), nativeRecord: readback)
            }
            book[source.collection] = rows
            let disputed = Set(conflicts.compactMap { ($0["identifier"] as? String).map(OpaqueUTF8Identity.init) })
            let allowed = Set(entries.map { OpaqueUTF8Identity($0.identifier) }).subtracting(disputed)
            return Finalized(candidateBook: try frozen(book), baseline: try Baseline(sourceFingerprint: source.fingerprint, entries: entries), normalizable: allowed)
        }
    }

    public static func prepare(snapshot: Snapshot, currentBook: [String: Any], baseline: Baseline?, context: CalendarTimeContext) throws -> Plan {
        let source = snapshot.source
        guard baseline == nil || same(baseline!.sourceFingerprint, source.fingerprint) else { throw failure("source binding changed; explicit authorization is required") }
        var book = try frozen(currentBook)
        guard var rows = book[source.collection] as? [[String: Any]] else { throw failure("Organizer collection is unavailable") }
        var byID: [OpaqueUTF8Identity: Int] = [:]
        for (index, row) in rows.enumerated() {
            guard let id = row["id"] as? String, !id.isEmpty, byID.updateValue(index, forKey: OpaqueUTF8Identity(id)) == nil else { throw failure("ambiguous local identity") }
        }
        var entries = baseline?.entries ?? []
        let original = Dictionary(uniqueKeysWithValues: entries.enumerated().map { (OpaqueUTF8Identity($0.element.identifier), $0.offset) })
        let found = Set(snapshot.records.map { OpaqueUTF8Identity($0.identifier) })
        var conflicts: [[String: Any]] = [], operations: [Operation] = []
        func conflict(_ identifier: String, _ localID: String, _ reason: String, _ groups: [String] = []) {
            conflicts.append(["identifier": identifier, "localID": localID, "reason": reason, "groups": groups])
        }
        for entry in entries where !found.contains(OpaqueUTF8Identity(entry.identifier)) {
            conflict(entry.identifier, entry.localID, "native-record-unavailable-or-outside-window")
        }
        for record in snapshot.records {
            let identity = OpaqueUTF8Identity(record.identifier)
            guard let baselineIndex = original[identity] else {
                // A previous copy's passive metadata does not authorize adoption.
                var row = record.canonicalRecord
                var id = UUID().uuidString
                while byID[OpaqueUTF8Identity(id)] != nil { id = UUID().uuidString }
                row["id"] = id; row["uid"] = UUID().uuidString
                row["sync"] = false; row["syncQuellen"] = [String: Any]()
                row["syncKalenderUid"] = ""; row["geaendert"] = (Date().timeIntervalSince1970 * 1000).rounded(.down)
                if source.kind == .reminders {
                    row["elternUid"] = ""
                    row["reihenfolge"] = rows.filter { ($0["elternUid"] as? String ?? "").isEmpty }.count
                }
                byID[OpaqueUTF8Identity(id)] = rows.count; rows.append(row)
                entries.append(try .init(identifier: record.identifier, localID: id,
                    localFields: SystemAccountSyncProjection.fields(row, kind: source.kind), nativeRecord: record))
                continue
            }
            let previous = entries[baselineIndex]
            guard let index = byID[OpaqueUTF8Identity(previous.localID)] else {
                conflict(record.identifier, previous.localID, "local-record-missing-or-in-trash"); continue
            }
            let current = rows[index]
            do { try SystemAccountSyncProjection.validateLocal(current, record: previous.nativeRecord, source: source, context: context) }
            catch { conflict(record.identifier, previous.localID, "local-calendar-representation-conflict: " + error.localizedDescription); continue }
            var merged = current, outgoing: [String] = [], disputed: [String] = []
            for group in SystemAccountSyncProjection.groups(source.kind) {
                let local = SystemAccountSyncProjection.select(current, group.keys)
                let oldLocal = SystemAccountSyncProjection.select(previous.localFields, group.keys)
                let remote = SystemAccountSyncProjection.select(record.canonicalRecord, group.keys)
                let oldRemote = SystemAccountSyncProjection.select(previous.nativeRecord.canonicalRecord, group.keys)
                let localChanged = try !equal(local, oldLocal), remoteChanged = try !equal(remote, oldRemote)
                if localChanged && remoteChanged {
                    if try !equal(local, remote) { disputed.append(group.name); continue }
                }
                if localChanged && !remoteChanged {
                    if group.writable { outgoing.append(group.name) } else { disputed.append(group.name) }
                } else if remoteChanged {
                    for key in group.keys { if let value = record.canonicalRecord[key] { merged[key] = value } }
                }
            }
            guard disputed.isEmpty else { conflict(record.identifier, previous.localID, "field-conflict-or-unsupported-local-edit", disputed); continue }
            if !outgoing.isEmpty {
                do {
                    let patch = try SystemAccountSyncProjection.nativePatch(record: record, desired: merged, changedGroups: outgoing, source: source, context: context)
                    operations.append(try Operation(localID: previous.localID, before: record, nativePatch: patch, desiredRecord: merged, changedGroups: outgoing))
                } catch {
                    conflict(record.identifier, previous.localID, "local-edit-not-representable: " + error.localizedDescription, outgoing); continue
                }
            }
            SystemAccountSyncProjection.copyEvidence(from: record.canonicalRecord, to: &merged)
            rows[index] = merged
            entries[baselineIndex] = try .init(identifier: record.identifier, localID: previous.localID,
                localFields: SystemAccountSyncProjection.fields(merged, kind: source.kind), nativeRecord: record)
        }
        book[source.collection] = rows
        return try Plan(source: source, candidateBook: book, operations: operations, conflicts: conflicts, excluded: snapshot.excluded,
                        nextBaseline: Baseline(sourceFingerprint: source.fingerprint, entries: entries))
    }

    static func failure(_ value: String) -> BetaError { BetaError("macOS system account synchronization: " + value + ".") }
    static func matchesNativeField(_ key: String, expected: Any, actual: Any) throws -> Bool {
        if try equal(expected, actual) { return true }
        // EventKit can store a deliberately cleared optional text as nil.
        if ["notes", "location"].contains(key), expected as? String == "", actual is NSNull { return true }
        guard ["startComponents", "dueComponents", "birthday"].contains(key),
              let requested = expected as? [String: Any], let returned = actual as? [String: Any] else { return false }
        for (name, value) in requested {
            guard let found = returned[name], try equal(value, found) else { return false }
        }
        // Framework-added calendar metadata is not a newly invented clock, year
        // or DateComponents timezone. All requested metadata remains exact.
        // In particular yearless birthdays never accept the sentinel year 1604,
        // and floating times never accept a newly supplied timeZone.
        for (name, value) in returned where requested[name] == nil {
            switch name {
            case "calendar": guard value as? String == "gregorian" else { return false }
            case "calendarTimeZone", "calendarLocale": guard let text = value as? String, text.utf8.count <= 1024 else { return false }
            case "calendarFirstWeekday", "calendarMinimumDaysInFirstWeek": guard let number = integer(value), (1...7).contains(number) else { return false }
            case "era": guard integer(value) == 1 else { return false }
            case "isLeapMonth": guard boolean(value) == false else { return false }
            case "second", "nanosecond": guard requested["hour"] != nil, integer(value) == 0 else { return false }
            default: return false
            }
        }
        return true
    }
    static func same(_ left: String, _ right: String) -> Bool { left.utf8.elementsEqual(right.utf8) }
    static func equal(_ left: Any, _ right: Any) throws -> Bool { try DAVSyncBaseline.canonicalJSON(left) == DAVSyncBaseline.canonicalJSON(right) }
    static func frozen(_ value: [String: Any]) throws -> [String: Any] {
        let text = try Document.encode(value)
        guard text.utf8.count <= maximumBytes else { throw failure("payload exceeds 32 MiB") }
        return try Document.object(text)
    }
    static func number(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite else { return nil }
        return number.doubleValue
    }
    static func integer(_ value: Any?) -> Int? {
        guard let number = number(value), number.rounded(.towardZero) == number, abs(number) <= 9_007_199_254_740_991 else { return nil }
        return Int(number)
    }
    static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }; return number.boolValue
    }
    static func text(_ object: [String: Any], _ key: String, empty: Bool = true, maximum: Int = 65_536) throws -> String {
        guard let text = object[key] as? String, (empty || !text.isEmpty), text.utf8.count <= maximum else { throw failure("invalid text field: " + key) }
        return text
    }
    static func keys(_ object: [String: Any], _ expected: Set<String>) throws {
        guard Set(object.keys) == expected else { throw failure("unknown or missing serialized fields") }
    }
    static func isDigest(_ value: String) -> Bool { value.utf8.count == 64 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) } }
    static func digest(_ object: [String: Any], _ key: String) throws -> String {
        let value = try text(object, key); guard isDigest(value) else { throw failure("invalid digest") }; return value
    }
}
