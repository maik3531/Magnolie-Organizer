import Foundation

public enum DAVBookRestoreError: Error, Equatable { case invalidInput, unsupportedQuarantine, limit, invalidEpoch }

/// Canonical whole-book restore transform. Caller must atomically commit the returned whole book
/// with the epoch; no sidecar or volatile host generation supplies persisted restore authority.
public enum DAVBookRestore {
    public static let maximumQuarantineBytes = 16 * 1024 * 1024
    public static let maximumQuarantineEntries = 100_000
    private static let domains: Set<String> = ["termine", "aufgaben", "kontakte"]
    private static func dictionary(_ value: Any?) throws -> [String: Any] {
        guard let value else { return [:] }
        guard let value = value as? [String: Any] else { throw DAVBookRestoreError.invalidInput }; return value
    }
    private static func list(_ value: Any?) throws -> [[String: Any]] {
        guard let value else { return [] }
        guard let value = value as? [[String: Any]] else { throw DAVBookRestoreError.unsupportedQuarantine }; return value
    }
    /// Root/meta saved copies must agree. Legacy books may lack the optional settings copy;
    /// present copies survive canonical unknown-field preservation and must agree too.
    public static func persistedEpoch(_ book: [String: Any]) throws -> UUID {
        let meta = try dictionary(book["syncMetadaten"]), settings = try dictionary(book["einstellungen"])
        let sync = try dictionary(settings["sync"])
        guard let root = book["syncEpoch"] as? String, let epoch = UUID(uuidString: root),
              let metaEpoch = meta["syncEpoch"] as? String, UUID(uuidString: metaEpoch) == epoch else { throw DAVBookRestoreError.invalidEpoch }
        if let value = sync["syncEpoch"] {
            guard let settingsEpoch = value as? String, UUID(uuidString: settingsEpoch) == epoch else { throw DAVBookRestoreError.invalidEpoch }
        }
        return epoch
    }
    /// Bound public dictionary inputs before Foundation validity checks/serialization recurse.
    /// Strings count their encoded UTF8/escape sizes, so ordinary large attachments are not
    /// charged six times their size. Small structural overhead remains a conservative bound.
    internal static func preflightInput(_ value: Any, maximumBytes: Int = Document.maximumBytes) throws {
        guard maximumBytes > 0, maximumBytes <= Document.maximumBytes else { throw DAVBookRestoreError.limit }
        var remaining = maximumBytes, nodes = 0
        func reserve(_ count: Int) throws { guard count >= 0, count <= remaining else { throw DAVBookRestoreError.limit }; remaining -= count }
        func walk(_ value: Any, depth: Int) throws {
            nodes += 1
            guard depth < 64, nodes <= 2_000_000 else { throw DAVBookRestoreError.limit }
            if let text = value as? String {
                try reserve(2)
                for scalar in text.unicodeScalars {
                    let value = scalar.value
                    let count: Int
                    if value < 0x20 || value == 0x2028 || value == 0x2029 { count = 6 }
                    else if value == 0x22 || value == 0x5c || value == 0x2f { count = 2 }
                    else if value < 0x80 { count = 1 }
                    else if value < 0x800 { count = 2 }
                    else if value < 0x10000 { count = 3 }
                    else { count = 4 }
                    try reserve(count)
                }
            } else if value is NSNull { try reserve(4) }
            else if let number = value as? NSNumber {
                guard number.doubleValue.isFinite else { throw DAVBookRestoreError.invalidInput }
                try reserve(max(32, number.stringValue.utf8.count))
            } else if let values = value as? [Any] {
                try reserve(2)
                for item in values { try reserve(1); try walk(item, depth: depth + 1) }
            } else if let values = value as? [String: Any] {
                try reserve(2)
                for (key, item) in values { try walk(key, depth: depth + 1); try reserve(2); try walk(item, depth: depth + 1) }
            } else { throw DAVBookRestoreError.invalidInput }
        }
        try walk(value, depth: 0)
    }
    public static func transform(incoming: [String: Any], live: [String: Any], newEpoch: UUID, restoredAt: Date) throws -> [String: Any] {
        try transform(incoming: incoming, live: live, newEpoch: newEpoch, restoredAt: restoredAt, maximumBytes: Document.maximumBytes)
    }
    internal static func transform(incoming: [String: Any], live: [String: Any], newEpoch: UUID, restoredAt: Date, maximumBytes: Int) throws -> [String: Any] {
        guard restoredAt.timeIntervalSince1970.isFinite, restoredAt.timeIntervalSince1970 >= 0,
              restoredAt.timeIntervalSince1970 < Double(Int64.max) / 1000 else { throw DAVBookRestoreError.invalidInput }
        try preflightInput(incoming, maximumBytes: maximumBytes); try preflightInput(live, maximumBytes: maximumBytes)
        guard JSONSerialization.isValidJSONObject(incoming), JSONSerialization.isValidJSONObject(live) else { throw DAVBookRestoreError.invalidInput }
        let epoch = newEpoch.uuidString.lowercased()
        // A caller cannot accidentally reuse either saved book's authority for a restore.
        for book in [incoming, live] {
            let oldMeta = try dictionary(book["syncMetadaten"]), oldSettings = try dictionary(book["einstellungen"])
            let oldSync = try dictionary(oldSettings["sync"])
            for value in [book["syncEpoch"], oldMeta["syncEpoch"], oldSync["syncEpoch"]] {
                if let prior = value as? String, UUID(uuidString: prior) == newEpoch { throw DAVBookRestoreError.invalidEpoch }
            }
        }
        var result = incoming, meta = try dictionary(incoming["syncMetadaten"])
        let liveMeta = try dictionary(live["syncMetadaten"])
        var quarantines = [liveMeta["quarantinedDeletes"], meta["quarantinedDeletes"]].compactMap { $0 }
        quarantines.append(["geloescht": incoming["geloescht"] ?? [:], "tombstones": incoming["tombstones"] ?? [],
                            "baumKontaktGeloescht": incoming["baumKontaktGeloescht"] ?? []])
        var deletes: [String: [[String: Any]]] = Dictionary(uniqueKeysWithValues: domains.map { ($0, []) })
        var tombstones: [[String: Any]] = [], tree: [[String: Any]] = []
        var seen: [String: Set<Data>] = [:], count = 0, bytes = 0
        var nodes = 0
        func preflight(_ value: Any, remaining: inout Int, depth: Int = 0) throws {
            nodes += 1
            guard nodes <= 1_000_000, depth <= 64, remaining > 0 else { throw DAVBookRestoreError.limit }
            func reserve(_ count: Int) throws { guard count <= remaining else { throw DAVBookRestoreError.limit }; remaining -= count }
            if let string = value as? String {
                guard string.utf8.count <= remaining / 6 else { throw DAVBookRestoreError.limit }; try reserve(string.utf8.count * 6 + 2)
            } else if value is NSNull { try reserve(4) }
            else if let number = value as? NSNumber { guard number.doubleValue.isFinite else { throw DAVBookRestoreError.invalidInput }; try reserve(32) }
            else if let array = value as? [Any] { try reserve(2); for item in array { try reserve(1); try preflight(item, remaining: &remaining, depth: depth + 1) } }
            else if let dictionary = value as? [String: Any] {
                try reserve(2)
                for (key, item) in dictionary { try preflight(key, remaining: &remaining, depth: depth + 1); try reserve(2); try preflight(item, remaining: &remaining, depth: depth + 1) }
            } else { throw DAVBookRestoreError.invalidInput }
        }
        func append(_ values: [[String: Any]], container: String, to output: inout [[String: Any]]) throws {
            for value in values {
                var budget = maximumQuarantineBytes - bytes
                try preflight(value, remaining: &budget)
                let encoded = try DAVSyncBaseline.canonicalJSON(value)
                if seen[container, default: []].contains(encoded) { continue }
                guard count < maximumQuarantineEntries, encoded.count <= maximumQuarantineBytes - bytes else { throw DAVBookRestoreError.limit }
                seen[container, default: []].insert(encoded); output.append(value); count += 1; bytes += encoded.count
            }
        }
        for value in quarantines {
            guard let quarantine = value as? [String: Any], Set(quarantine.keys).isSubset(of: ["geloescht", "tombstones", "baumKontaktGeloescht"]) else { throw DAVBookRestoreError.unsupportedQuarantine }
            let removed: [String: Any]
            do { removed = try dictionary(quarantine["geloescht"]) }
            catch { throw DAVBookRestoreError.unsupportedQuarantine }
            guard Set(removed.keys).isSubset(of: domains) else { throw DAVBookRestoreError.unsupportedQuarantine }
            for domain in domains.sorted() {
                var values = deletes[domain]!
                try append(list(removed[domain]), container: domain, to: &values); deletes[domain] = values
            }
            try append(list(quarantine["tombstones"]), container: "tombstones", to: &tombstones)
            try append(list(quarantine["baumKontaktGeloescht"]), container: "baumKontaktGeloescht", to: &tree)
        }
        meta["quarantinedDeletes"] = ["geloescht": deletes, "tombstones": tombstones, "baumKontaktGeloescht": tree]
        meta["syncEpoch"] = epoch; meta["ersteSyncLoeschungsfrei"] = true
        if meta["nextcloud"] != nil {
            var cloud = try dictionary(meta["nextcloud"])
            cloud.removeValue(forKey: "pendingCommitId"); cloud.removeValue(forKey: "ausstehendeTransaktion"); cloud["transaktionen"] = [:] as [String: Any]
            meta["nextcloud"] = cloud
        }
        result["syncMetadaten"] = meta; result["syncEpoch"] = epoch
        result.removeValue(forKey: "syncAbgleichBasis"); result.removeValue(forKey: "syncAbgleichNachweis")
        result["geloescht"] = ["termine": [], "aufgaben": [], "kontakte": []] as [String: [[String: Any]]]
        result["tombstones"] = [] as [[String: Any]]; result["baumKontaktGeloescht"] = [] as [[String: Any]]
        var afterRestore = try dictionary(result["syncNachRestore"])
        afterRestore["additiv"] = true; afterRestore["loeschungsfrei"] = true
        afterRestore["erstelltUtc"] = ISO8601DateFormatter().string(from: restoredAt)
        result["syncNachRestore"] = afterRestore
        let changed = Int64(restoredAt.timeIntervalSince1970 * 1000)
        for domain in domains {
            if result[domain] != nil {
                guard var records = result[domain] as? [[String: Any]] else { throw DAVBookRestoreError.invalidInput }
                for index in records.indices where records[index]["sync"] as? Bool == true { records[index]["geaendert"] = changed }
                result[domain] = records
            }
        }
        var personal = try dictionary(result["personalSync"])
        let currentPersonal = try dictionary(live["personalSync"])
        personal["actor_id"] = currentPersonal["actor_id"] ?? ""
        personal["custom_revision"] = currentPersonal["custom_revision"] ?? 0
        personal["custom_entities"] = currentPersonal["custom_entities"] ?? [:]
        personal.removeValue(forKey: "custom_auto_hash"); result["personalSync"] = personal
        var settings = try dictionary(result["einstellungen"]), sync = try dictionary(settings["sync"])
        sync["syncEpoch"] = epoch; sync["ersteSyncLoeschungsfrei"] = true; settings["sync"] = sync
        let liveSettings = try dictionary(live["einstellungen"]), liveAddresses = try dictionary(liveSettings["adressen"])
        var addresses = try dictionary(settings["adressen"])
        addresses["smsSchedulingEnabled"] = liveAddresses["smsSchedulingEnabled"] as? Bool == true; settings["adressen"] = addresses
        result["einstellungen"] = settings
        if result["smsPlanung"] != nil {
            guard var plans = result["smsPlanung"] as? [[String: Any]] else { throw DAVBookRestoreError.invalidInput }
            for index in plans.indices {
                if plans[index]["status"] as? String == "planned" { plans[index]["status"] = "paused" }
                if plans[index]["status"] as? String == "submitting" { plans[index]["status"] = "uncertain" }
            }
            result["smsPlanung"] = plans
        }
        _ = try persistedEpoch(result)
        try preflightInput(result, maximumBytes: maximumBytes)
        return result
    }
}
