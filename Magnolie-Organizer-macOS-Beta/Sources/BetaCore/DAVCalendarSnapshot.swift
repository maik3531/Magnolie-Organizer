import Foundation
import CryptoKit

public enum DAVCalendarSnapshotError: Error, Equatable {
    case invalidLimits, invalidSource, resourceOutsideCollection, missingETag
    case duplicateResource, ambiguousWireUID, duplicateProjection, incompleteProjection
    case unsupportedTasks, unsupportedOrMalformedResource, byteLimit, resourceLimit, recordLimit, projectionLimit
}

/// Pure projection of an already completed DAVClient.report result for ONE discovered calendar.
/// The caller must supply the complete successful REPORT list; this module cannot manufacture or
/// verify transport completeness from an arbitrary array, nor does it establish a sync baseline.
public enum DAVCalendarSnapshot {
    public struct Limits {
        public let maximumBytes: Int
        public let maximumResources: Int
        public let maximumRecords: Int
        public let maximumProjectedBytes: Int
        public init(maximumBytes: Int = DAVClient.itemLimit, maximumResources: Int = DAVClient.listLimit,
                    maximumRecords: Int = ICalendarImport.maximumRecords,
                    maximumProjectedBytes: Int = ICalendarImport.maximumProjectedBytes) {
            self.maximumBytes = maximumBytes; self.maximumResources = maximumResources
            self.maximumRecords = maximumRecords; self.maximumProjectedBytes = maximumProjectedBytes
        }
    }
    public enum Kind: String { case appointment, task, anniversary }
    public struct Record {
        public let kind: Kind
        public let sourceUID: String
        public let href: URL
        public let etag: String
        /// Original server identity; never replace this with the local UI/task id.
        public let wireKey: ICalendarResourcePatch.Key
        /// The parser's domain projection, including opaque ICS fields. Only tasks receive an
        /// additional stable local `id`; their projected `uid` and original wire UID remain intact.
        public let value: [String: Any]
    }
    public struct Resource {
        public let href: URL
        public let etag: String
        /// Exact UTF-8 bytes of the supplied REPORT text. XML has already decoded calendar-data;
        /// these are not a claim about byte identity with an independent HTTP GET response.
        public let bytes: Data
        public let wireKeys: [ICalendarResourcePatch.Key]
        public let calendarProperties: [String]
        public let sourceSHA256: String
        public let records: [Record]
    }
    public struct Result {
        public let source: DAVCollection
        public let resources: [Resource]
        public let appointments: [Record]
        /// nil explicitly means the discovery capability does not support tasks. An empty array
        /// means supported and actually empty; a future merger must not confuse these states.
        public let tasks: [Record]?
        public let anniversaries: [Record]
        public let byteCount: Int
        public let projectedByteCount: Int
    }

    public static func decode(source: DAVCollection, resources: [DAVResource], displayTimeZone: String = "system",
                              limits: Limits = Limits(), cancellation: () -> Bool = { false }) throws -> Result {
        func checkCancellation() throws {
            if cancellation() { throw CancellationError() }
            try Task.checkCancellation()
        }
        try checkCancellation()
        guard limits.maximumBytes > 0, limits.maximumBytes <= DAVClient.itemLimit,
              limits.maximumResources > 0, limits.maximumResources <= DAVClient.listLimit,
              limits.maximumRecords > 0, limits.maximumRecords <= ICalendarImport.maximumRecords,
              limits.maximumProjectedBytes > 0, limits.maximumProjectedBytes <= ICalendarImport.maximumProjectedBytes else {
            throw DAVCalendarSnapshotError.invalidLimits
        }
        guard resources.count <= limits.maximumResources else { throw DAVCalendarSnapshotError.resourceLimit }
        guard source.kind == .calendar else { throw DAVCalendarSnapshotError.invalidSource }
        let accountType: DAVAccountType
        if source.uid.hasPrefix("nextcloud-calendar:") { accountType = .nextcloud }
        else if source.uid.hasPrefix("generic-dav-calendar:") { accountType = .genericDAV }
        else { throw DAVCalendarSnapshotError.invalidSource }
        guard source.uid == DAVClient.sourceID(kind: .calendar, href: source.href, accountType: accountType) else {
            throw DAVCalendarSnapshotError.invalidSource
        }
        let validator: DAVClient
        do { validator = try DAVClient(server: source.href.absoluteString, username: "snapshot-validation", password: "") }
        catch { throw DAVCalendarSnapshotError.invalidSource }
        let collectionPath = try scopedPath(source.href)
        let collectionPrefix = collectionPath == "/" ? "/" : collectionPath + "/"
        var seenHrefs = Set<String>(), wireOwners: [String: URL] = [:], projectedIdentities = Set<String>()
        var byteCount = 0, projectedByteCount = 0, recordCount = 0
        var output: [Resource] = [], appointments: [Record] = [], tasks: [Record] = [], anniversaries: [Record] = []
        func consumeProjection(_ value: Any) throws {
            let size = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).count
            guard size <= limits.maximumProjectedBytes - projectedByteCount else { throw DAVCalendarSnapshotError.projectionLimit }
            projectedByteCount += size
        }
        for resource in resources {
            try checkCancellation()
            let href: URL
            do { href = try validator.sameOriginURL(resource.href.absoluteString) }
            catch { throw DAVCalendarSnapshotError.resourceOutsideCollection }
            let path = try scopedPath(href)
            guard path.hasPrefix(collectionPrefix), path.count > collectionPrefix.count else {
                throw DAVCalendarSnapshotError.resourceOutsideCollection
            }
            // Percent-encoded aliases and dot-normalized paths cannot masquerade as two resources.
            guard seenHrefs.insert(path).inserted else { throw DAVCalendarSnapshotError.duplicateResource }
            let trimmedETag = resource.etag.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmedETag.isEmpty, trimmedETag != "*",
                  !resource.etag.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else {
                throw DAVCalendarSnapshotError.missingETag
            }
            let size = resource.data.utf8.count
            guard size <= limits.maximumBytes - byteCount else { throw DAVCalendarSnapshotError.byteLimit }
            let bytes = Data(resource.data.utf8)
            byteCount += size
            try checkCancellation()
            let keys: [ICalendarResourcePatch.Key]
            let parsed: ICalendarImport.Result
            do {
                keys = try ICalendarResourcePatch.keys(from: bytes)
                guard keys.count <= limits.maximumRecords - recordCount else { throw DAVCalendarSnapshotError.recordLimit }
                if !source.supportsVtodo && keys.contains(where: { $0.kind == "VTODO" }) { throw DAVCalendarSnapshotError.unsupportedTasks }
                for key in keys {
                    let identity = key.kind + "\0" + key.uid
                    if let owner = wireOwners[identity], owner != href { throw DAVCalendarSnapshotError.ambiguousWireUID }
                    wireOwners[identity] = href
                }
                try checkCancellation()
                parsed = try ICalendarImport.decode(bytes, displayTimeZone: displayTimeZone, sourceName: source.name, sourceID: source.uid)
            } catch let error as DAVCalendarSnapshotError { throw error }
            catch is CancellationError { throw CancellationError() }
            catch { throw DAVCalendarSnapshotError.unsupportedOrMalformedResource }
            guard keys.count == parsed.appointments.count + parsed.tasks.count + parsed.anniversaries.count else {
                throw DAVCalendarSnapshotError.incompleteProjection
            }
            recordCount += keys.count
            try consumeProjection(parsed.calendarProperties)
            let eventKeys = Set(keys.filter { $0.kind == "VEVENT" }), taskKeys = keys.filter { $0.kind == "VTODO" }
            guard taskKeys.count == parsed.tasks.count else { throw DAVCalendarSnapshotError.incompleteProjection }
            var matched = Set<ICalendarResourcePatch.Key>(), records: [Record] = []
            func append(_ input: [String: Any], kind: Kind, key: ICalendarResourcePatch.Key) throws {
                try checkCancellation()
                guard let uid = input["uid"] as? String, !uid.isEmpty,
                      matched.insert(key).inserted else { throw DAVCalendarSnapshotError.incompleteProjection }
                let domain = kind == .task ? "VTODO" : "VEVENT"
                guard projectedIdentities.insert(domain + "\0" + uid).inserted else { throw DAVCalendarSnapshotError.duplicateProjection }
                var value = input
                if kind == .appointment && value["icsKomplex"] as? Bool == true {
                    value["icsReadOnly"] = true; value["icsReadOnlyGrund"] = "Nextcloud"
                }
                if kind == .task {
                    let hash = SHA256.hash(data: Data((source.uid + "\n" + uid).utf8)).map { String(format: "%02x", $0) }.joined()
                    value["id"] = "dav-task:" + hash.prefix(32)
                }
                try consumeProjection(value)
                let record = Record(kind: kind, sourceUID: source.uid, href: href, etag: resource.etag, wireKey: key, value: value)
                records.append(record)
                switch kind { case .appointment: appointments.append(record); case .task: tasks.append(record); case .anniversary: anniversaries.append(record) }
            }
            for value in parsed.appointments {
                let key = try eventKey(value)
                guard eventKeys.contains(key) else { throw DAVCalendarSnapshotError.incompleteProjection }
                try append(value, kind: .appointment, key: key)
            }
            for value in parsed.anniversaries {
                let key = try eventKey(value)
                guard eventKeys.contains(key) else { throw DAVCalendarSnapshotError.incompleteProjection }
                try append(value, kind: .anniversary, key: key)
            }
            // Both the resource scanner and parser preserve VTODO component order. This binds
            // aliased X-MAGNOLIE-TASK-IDENTITY projections without guessing their original wire UID.
            for (key, value) in zip(taskKeys, parsed.tasks) { try append(value, kind: .task, key: key) }
            guard matched == Set(keys) else { throw DAVCalendarSnapshotError.incompleteProjection }
            output.append(Resource(href: href, etag: resource.etag, bytes: bytes, wireKeys: keys,
                calendarProperties: parsed.calendarProperties, sourceSHA256: parsed.sourceSHA256, records: records))
        }
        try checkCancellation()
        return Result(source: source, resources: output, appointments: appointments,
            tasks: source.supportsVtodo ? tasks : nil, anniversaries: anniversaries,
            byteCount: byteCount, projectedByteCount: projectedByteCount)
    }

    private static func scopedPath(_ url: URL) throws -> String {
        guard let encoded = URLComponents(url: url, resolvingAgainstBaseURL: false)?.percentEncodedPath,
              let decoded = encoded.removingPercentEncoding, !decoded.contains("\\"),
              !decoded.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else {
            throw DAVCalendarSnapshotError.resourceOutsideCollection
        }
        var segments: [String] = []
        for segment in decoded.split(separator: "/") {
            switch segment {
            case ".": continue
            case "..": if !segments.isEmpty { segments.removeLast() }
            default: segments.append(String(segment))
            }
        }
        return "/" + segments.joined(separator: "/")
    }
    private static func eventKey(_ value: [String: Any]) throws -> ICalendarResourcePatch.Key {
        guard let projectedUID = value["uid"] as? String, !projectedUID.isEmpty,
              let raw = value["icsRoundtrip"] as? [String] else { throw DAVCalendarSnapshotError.incompleteProjection }
        let series = value["icsSerienUid"] as? String ?? ""
        let uid = series.isEmpty ? projectedUID : series
        var depth = 0, recurrenceID: String?
        for line in raw {
            let name = line.prefix { $0 != ";" && $0 != ":" }.uppercased()
            if name == "BEGIN" { depth += 1 }
            if depth == 0 && name == "RECURRENCE-ID" {
                guard recurrenceID == nil else { throw DAVCalendarSnapshotError.incompleteProjection }
                recurrenceID = line
            }
            if name == "END" { depth -= 1 }
        }
        func escape(_ text: String) -> String {
            text.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\n", with: "\\n")
                .replacingOccurrences(of: ",", with: "\\,").replacingOccurrences(of: ";", with: "\\;")
        }
        // Reuse the resource patcher's canonical RECURRENCE-ID semantics (parameter order,
        // implicit DATE-TIME, RANGE) rather than introducing a second normalizer.
        let probe = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:\(escape(uid))\r\n" +
            (recurrenceID.map { $0 + "\r\n" } ?? "") + "END:VEVENT\r\nEND:VCALENDAR\r\n"
        do {
            let keys = try ICalendarResourcePatch.keys(from: Data(probe.utf8))
            guard keys.count == 1 else { throw DAVCalendarSnapshotError.incompleteProjection }
            return keys[0]
        } catch { throw DAVCalendarSnapshotError.incompleteProjection }
    }
}
