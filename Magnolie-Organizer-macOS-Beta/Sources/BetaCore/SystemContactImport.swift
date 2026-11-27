import Foundation
import CoreFoundation
import CryptoKit

/// Refs #775. Value-only proposals for explicitly selected local contact copies.
/// Only the enumerated public fields are projected. Neither private provider data,
/// the entitlement-protected note property nor a complete vCard is claimed.
public enum SystemContactImport {
    public static let maximumRecords = 100
    public static let maximumBytes = 16 * 1024 * 1024
    public static let maximumImageBytes = 2_600_000
    public static let maximumTitleBytes = 4096
    public static let maximumIdentifierBytes = 16_384
    public static let maximumTextBytes = 65_536
    public static let maximumValues = 1000

    public struct Source: Sendable {
        public let sourceUID: String, containerID: String, title: String, nativeType: String
        public init(sourceUID: String, containerID: String, title: String, nativeType: String) {
            self.sourceUID = sourceUID; self.containerID = containerID
            self.title = title; self.nativeType = nativeType
        }
    }
    public struct Record {
        public let identifier: String, title: String, fields: [String: Any], failure: String?
        public init(identifier: String, title: String, fields: [String: Any], failure: String? = nil) {
            self.identifier = identifier; self.title = title; self.fields = fields; self.failure = failure
        }
    }
    public struct Snapshot {
        public let source: Source, records: [Record]
        public init(source: Source, records: [Record]) { self.source = source; self.records = records }
    }
    public struct Plan {
        public let payload: [String: Any], snapshotRevision: String
        private let evidence: Data
        fileprivate init(source: [String: Any], contacts: [[String: Any]], excluded: [[String: Any]], evidence: Data) throws {
            self.evidence = evidence; snapshotRevision = SystemContactImport.hash(evidence)
            payload = ["version": 1, "source": source, "contacts": contacts,
                       "excluded": excluded, "snapshotRevision": snapshotRevision]
            guard try Document.encode(payload).utf8.count <= SystemContactImport.maximumBytes else {
                throw SystemContactImport.failure("proposal exceeds 16 MiB; select fewer contacts")
            }
        }
        /// Enumeration order is immaterial; source metadata and all selected raw
        /// records, including excluded records, must still match byte for byte.
        /// This is serialized-field evidence, not an atomic Contacts revision.
        public func revalidate(_ snapshot: Snapshot) throws {
            guard try SystemContactImport.checked(snapshot).evidence == evidence else {
                throw SystemContactImport.failure("the selected source changed; review a new proposal")
            }
        }
    }

    public static func prepare(_ snapshot: Snapshot) throws -> Plan {
        let read = try checked(snapshot)
        var contacts: [[String: Any]] = [], excluded: [[String: Any]] = []
        for entry in read.records {
            let record = entry.record
            do {
                let projected = try project(record)
                let identity = hash(OpaqueUTF8Identity(parts: [snapshot.source.sourceUID, record.identifier]).bytes)
                let revision = hash(try framed([Data("macos-contact-record-v1".utf8), read.sourceEvidence, entry.evidence]))
                contacts.append(["identity": identity, "revision": revision, "identifier": record.identifier,
                    "title": record.title, "contact": projected.contact, "nativeRecord": entry.raw,
                    "notices": projected.notices])
            } catch let error as Exclusion {
                excluded.append(["identifier": record.identifier, "title": record.title,
                                 "reasons": Array(Set(error.reasons)).sorted()])
            }
        }
        return try Plan(source: sourcePayload(snapshot.source), contacts: contacts, excluded: excluded, evidence: read.evidence)
    }

    private struct Exclusion: Error {
        let reasons: [String]
        init(_ reason: String) { reasons = [reason] }
        init(_ reasons: [String]) { self.reasons = reasons }
    }
    private struct CheckedRecord {
        let record: Record, raw: [String: Any], evidence: Data
    }
    private struct CheckedSnapshot {
        let records: [CheckedRecord], sourceEvidence: Data, evidence: Data
    }
    private static let nameFields = ["namePrefix", "givenName", "middleName", "familyName", "previousFamilyName", "nameSuffix",
        "nickname", "phoneticGivenName", "phoneticMiddleName", "phoneticFamilyName", "phoneticOrganizationName",
        "organizationName", "departmentName", "jobTitle"]
    private static let valueFields = ["phoneNumbers", "emailAddresses", "postalAddresses", "urlAddresses",
        "contactRelations", "socialProfiles", "instantMessageAddresses", "dates"]
    private static let postalFields = ["street", "city", "state", "postalCode", "country", "isoCountryCode", "subAdministrativeArea", "subLocality"]
    private static let fieldNames = Set(nameFields + valueFields + ["contactType", "unification", "unavailableKeys",
        "birthday", "nonGregorianBirthday", "imageDataAvailable", "imageData", "imageMIME"])
    private static let labelKinds: Set<String> = ["home", "work", "other", "mobile", "iphone", "main", "homeFax", "workFax",
        "otherFax", "pager", "homePage", "anniversary", "icloud", "custom", "none"]

    private static func failure(_ value: String) -> BetaError { BetaError("macOS contact copy: " + value + ".") }
    private static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func nullable(_ value: String?) -> Any { value.map { $0 as Any } ?? NSNull() }
    private static func sourcePayload(_ source: Source) -> [String: Any] {
        ["sourceUID": source.sourceUID, "containerID": source.containerID, "title": source.title, "nativeType": source.nativeType]
    }
    private static func safe(_ value: String, multiline: Bool = false) -> Bool {
        value.unicodeScalars.allSatisfy {
            ($0.value >= 32 && !(0x7F...0x9F).contains($0.value)) || (multiline && [9, 10, 13].contains($0.value))
        }
    }
    private static func text(_ value: Any?, maximum: Int = maximumTextBytes, multiline: Bool = false) throws -> String {
        guard let value = value as? String else { throw Exclusion("native-contact-field-unavailable") }
        guard value.utf8.count <= maximum, safe(value, multiline: multiline) else {
            throw Exclusion("native-contact-text-not-representable")
        }
        return value
    }
    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              abs(number.doubleValue) <= 9_007_199_254_740_991 else { return nil }
        return number.intValue
    }
    private static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    private static func checked(_ snapshot: Snapshot) throws -> CheckedSnapshot {
        guard snapshot.records.count <= maximumRecords else { throw failure("select at most 100 contacts") }
        let source = snapshot.source
        guard !source.containerID.isEmpty, source.containerID.utf8.count <= maximumIdentifierBytes,
              source.sourceUID.utf8.count <= 4096,
              Data(source.sourceUID.utf8) == Data(SystemSourcePolicy.uid(.contacts, source.containerID).utf8),
              source.title.utf8.count <= maximumTitleBytes, source.nativeType.utf8.count <= 64,
              source.nativeType.range(of: "^container:[0-9]+$", options: .regularExpression) != nil,
              [source.containerID, source.sourceUID, source.title, source.nativeType].allSatisfy({ safe($0) }) else {
            throw failure("invalid selected container identity or metadata")
        }
        let sourceEvidence = Data(try Document.encode(sourcePayload(source)).utf8)
        var records: [CheckedRecord] = [], seen = Set<Data>(), total = sourceEvidence.count
        for input in snapshot.records {
            guard !input.identifier.isEmpty, input.identifier.utf8.count <= maximumIdentifierBytes,
                  input.title.utf8.count <= maximumTitleBytes, (input.failure?.utf8.count ?? 0) <= maximumTitleBytes,
                  seen.insert(Data(input.identifier.utf8)).inserted else {
                throw failure("missing, oversized or ambiguous native contact identity/title")
            }
            guard Set(input.fields.keys).isSubset(of: fieldNames) else {
                throw failure("unexpected native field; private note data is not part of this copy")
            }
            var nodes = 0, bytes = 0
            func validate(_ value: Any, depth: Int) throws {
                nodes += 1
                guard depth <= 16, nodes <= 100_000 else { throw failure("native record structure limit") }
                if let string = value as? String { bytes += string.utf8.count }
                else if let object = value as? [String: Any] {
                    guard object.count <= maximumValues else { throw failure("native field limit") }
                    for (key, child) in object { bytes += key.utf8.count; try validate(child, depth: depth + 1) }
                } else if let array = value as? [Any] {
                    guard array.count <= maximumValues else { throw failure("native value count limit") }
                    for child in array { try validate(child, depth: depth + 1) }
                } else if let number = value as? NSNumber {
                    guard number.doubleValue.isFinite else { throw failure("invalid native numeric value") }; bytes += 32
                } else if !(value is NSNull) { throw failure("non-JSON native field") }
                guard bytes <= maximumBytes - total else { throw failure("snapshot evidence exceeds 16 MiB") }
            }
            try validate(input.fields, depth: 0)
            // Freeze dictionaries supplied by a native reader before retaining
            // either the proposal or the proof. Unknown absence stays explicit.
            let fields = try Document.object(Document.encode(input.fields))
            let record = Record(identifier: input.identifier, title: input.title, fields: fields, failure: input.failure)
            let raw: [String: Any] = ["identifier": record.identifier, "title": record.title,
                                     "fields": fields, "failure": nullable(record.failure)]
            let evidence = Data(try Document.encode(raw).utf8)
            guard evidence.count <= maximumBytes - total else { throw failure("snapshot evidence exceeds 16 MiB") }
            total += evidence.count; records.append(CheckedRecord(record: record, raw: raw, evidence: evidence))
        }
        records.sort { Data($0.record.identifier.utf8).lexicographicallyPrecedes(Data($1.record.identifier.utf8)) }
        let evidence = try framed([Data("macos-contact-snapshot-v1".utf8), sourceEvidence] + records.map(\.evidence))
        return CheckedSnapshot(records: records, sourceEvidence: sourceEvidence, evidence: evidence)
    }
    private static func framed(_ parts: [Data]) throws -> Data {
        var result = Data()
        func length(_ value: Int) {
            var number = UInt64(value).bigEndian
            withUnsafeBytes(of: &number) { result.append(contentsOf: $0) }
        }
        length(parts.count)
        for part in parts {
            guard result.count <= maximumBytes - 8, part.count <= maximumBytes - result.count - 8 else {
                throw failure("snapshot evidence exceeds 16 MiB")
            }
            length(part.count); result.append(part)
        }
        return result
    }

    private struct Labeled {
        let label: String?, kind: String, value: Any
    }
    private static func labeled(_ fields: [String: Any], _ key: String) throws -> [Labeled] {
        guard let rows = fields[key] as? [[String: Any]], rows.count <= maximumValues else {
            throw Exclusion("native-contact-field-unavailable")
        }
        var seen = Set<Data>()
        return try rows.map { row in
            guard Set(row.keys) == Set(["identifier", "label", "labelKind", "value"]),
                  let id = row["identifier"] as? String, !id.isEmpty, id.utf8.count <= maximumIdentifierBytes,
                  seen.insert(Data(id.utf8)).inserted,
                  let kind = row["labelKind"] as? String, labelKinds.contains(kind), let value = row["value"] else {
                throw Exclusion("native-contact-labeled-value-not-representable")
            }
            let label: String?
            if row["label"] is NSNull { label = nil }
            else { label = try text(row["label"], maximum: maximumTitleBytes) }
            if kind == "none" && label?.isEmpty == false || kind == "custom" && label == nil {
                throw Exclusion("native-contact-label-not-representable")
            }
            return Labeled(label: label, kind: kind, value: value)
        }
    }
    private static func label(_ entry: Labeled) throws -> String {
        if entry.kind == "custom" {
            let value = entry.label ?? ""
            guard value.utf16.count <= 80, value == value.trimmingCharacters(in: .whitespacesAndNewlines) else {
                throw Exclusion("native-contact-label-not-representable")
            }
            return value
        }
        return ["iphone": "iPhone", "main": "Main", "homeFax": "Home fax", "workFax": "Work fax",
                "otherFax": "Fax", "icloud": "iCloud"][entry.kind] ?? ""
    }
    private static func types(_ entry: Labeled, phone: Bool = false, email: Bool = false) -> [String] {
        let base: [String]
        switch entry.kind {
        case "home": base = ["HOME"]
        case "work": base = ["WORK"]
        case "other": base = ["OTHER"]
        case "mobile", "iphone": base = ["CELL"]
        case "main": base = ["PREF"]
        case "homeFax": base = ["HOME", "FAX"]
        case "workFax": base = ["WORK", "FAX"]
        case "otherFax": base = ["FAX"]
        case "pager": base = ["PAGER"]
        default: base = []
        }
        if email { return base + ["INTERNET"] }
        if phone && !base.contains(where: { ["CELL", "FAX", "PAGER"].contains($0) }) { return base + ["VOICE"] }
        return base
    }
    private static func escaped(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\r\n", with: "\\n")
            .replacingOccurrences(of: "\r", with: "\\n").replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: ",", with: "\\,").replacingOccurrences(of: ";", with: "\\;")
    }
    private static func birthday(_ fields: [String: Any]) throws -> String {
        guard fields["birthday"] != nil, fields["nonGregorianBirthday"] != nil else {
            throw Exclusion("native-contact-birthday-state-unavailable")
        }
        if !(fields["nonGregorianBirthday"] is NSNull) {
            throw Exclusion("native-contact-non-gregorian-birthday-not-supported")
        }
        guard try labeled(fields, "dates").isEmpty else { throw Exclusion("native-contact-additional-dates-not-supported") }
        if fields["birthday"] is NSNull { return "" }
        guard let value = fields["birthday"] as? [String: Any],
              let month = integer(value["month"]), let day = integer(value["day"]), (1...12).contains(month),
              value["calendar"] == nil || value["calendar"] is NSNull || value["calendar"] as? String == "gregorian",
              value["era"] == nil || integer(value["era"]) == 1,
              value["isLeapMonth"] == nil || boolean(value["isLeapMonth"]) == false else {
            throw Exclusion("native-contact-birthday-not-representable")
        }
        let metadata: Set<String> = ["era", "year", "month", "day", "calendar", "calendarTimeZone", "calendarFirstWeekday",
            "calendarMinimumDaysInFirstWeek", "calendarLocale", "isLeapMonth"]
        guard Set(value.keys).isSubset(of: metadata) else { throw Exclusion("native-contact-birthday-not-representable") }
        let year: Int?
        if value["year"] == nil || value["year"] is NSNull { year = nil }
        else {
            guard let raw = integer(value["year"]), (1000...9999).contains(raw) else {
                throw Exclusion("native-contact-birthday-not-representable")
            }
            year = raw
        }
        let leap = year.map { $0 % 4 == 0 && ($0 % 100 != 0 || $0 % 400 == 0) } ?? true
        let days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        guard day >= 1, day <= days[month - 1] else { throw Exclusion("native-contact-birthday-not-representable") }
        return (year.map { String(format: "%04d", $0) + "-" } ?? "--") + String(format: "%02d-%02d", month, day)
    }
    private static func photo(_ fields: [String: Any]) throws -> String {
        guard let available = boolean(fields["imageDataAvailable"]), fields["imageData"] != nil, fields["imageMIME"] != nil else {
            throw Exclusion("native-contact-photo-state-unavailable")
        }
        if !available {
            guard fields["imageData"] is NSNull, fields["imageMIME"] is NSNull else {
                throw Exclusion("native-contact-photo-state-unavailable")
            }
            return ""
        }
        guard let encoded = fields["imageData"] as? String, encoded.utf8.count <= 3_466_668,
              let data = Data(base64Encoded: encoded), !data.isEmpty, data.count <= maximumImageBytes,
              data.base64EncodedString() == encoded,
              let mime = fields["imageMIME"] as? String else { throw Exclusion("native-contact-photo-not-representable") }
        let head = Array(data.prefix(12)), valid: Bool
        switch mime {
        case "image/jpeg": valid = head.starts(with: [0xFF, 0xD8, 0xFF])
        case "image/png": valid = head.starts(with: [137, 80, 78, 71, 13, 10, 26, 10])
        case "image/gif": valid = head.starts(with: [71, 73, 70, 56]) && head.count >= 6 && [55, 57].contains(head[4]) && head[5] == 97
        case "image/webp": valid = head.starts(with: [82, 73, 70, 70]) && head.count >= 12 && Array(head[8..<12]) == [87, 69, 66, 80]
        default: valid = false
        }
        guard valid else { throw Exclusion("native-contact-photo-not-representable") }
        return "data:" + mime + ";base64," + encoded
    }

    private static func project(_ record: Record) throws -> (contact: [String: Any], notices: [String]) {
        let fields = record.fields
        if record.failure != nil { throw Exclusion("native-contact-read-failed") }
        guard safe(record.identifier), safe(record.title) else { throw Exclusion("native-contact-text-not-representable") }
        guard fields["unification"] as? String == "nonUnifiedContainer",
              let unavailable = fields["unavailableKeys"] as? [String],
              unavailable.allSatisfy({ $0 == "note" }),
              let kind = integer(fields["contactType"]), [0, 1].contains(kind) else {
            throw Exclusion("native-contact-field-unavailable")
        }
        var names: [String: String] = [:]
        for key in nameFields { names[key] = try text(fields[key]) }
        var notices: Set<String> = ["native-contact-public-fields-only"]
        if ["namePrefix", "middleName", "previousFamilyName", "nameSuffix", "nickname", "phoneticGivenName", "phoneticMiddleName", "phoneticFamilyName"]
            .contains(where: { names[$0]?.isEmpty == false }) { notices.insert("native-contact-name-details-in-source") }
        if ["departmentName", "jobTitle", "phoneticOrganizationName"].contains(where: { names[$0]?.isEmpty == false }) {
            notices.insert("native-contact-organization-details-in-source")
        }
        for key in ["contactRelations", "socialProfiles", "instantMessageAddresses"] {
            if !(try labeled(fields, key)).isEmpty { notices.insert("native-contact-extra-public-fields-in-source") }
        }
        let phones = try labeled(fields, "phoneNumbers").map { row -> [String: Any] in
            ["wert": try text(row.value), "typen": types(row, phone: true), "label": try label(row)]
        }
        // Existing Organizer intentionally lowercases email addresses. Preserve
        // original spelling here; only the actual JS normalizer may accept that
        // explicit transformation and must add its per-contact preview notice.
        let emails = try labeled(fields, "emailAddresses").map { row -> [String: Any] in
            ["wert": try text(row.value), "typen": types(row, email: true), "label": try label(row)]
        }
        let addresses = try labeled(fields, "postalAddresses").map { row -> [String: Any] in
            guard let value = row.value as? [String: Any], Set(value.keys) == Set(postalFields) else {
                throw Exclusion("native-contact-address-not-representable")
            }
            var parts: [String: String] = [:]
            for key in postalFields { parts[key] = try text(value[key], multiline: key == "street") }
            if ["subAdministrativeArea", "subLocality"].contains(where: { parts[$0]?.isEmpty == false }) {
                notices.insert("native-contact-address-details-in-source")
            }
            return ["postfach": "", "zusatz": "", "strasse": parts["street"]!, "ort": parts["city"]!,
                "region": parts["state"]!, "plz": parts["postalCode"]!, "land": parts["country"]!,
                "typen": types(row), "label": try label(row)]
        }
        var roundtrip = ["N:" + ["familyName", "givenName", "middleName", "namePrefix", "nameSuffix"].map { escaped(names[$0]!) }.joined(separator: ";"),
                         "FN:" + escaped(record.title)]
        if names["organizationName"]?.isEmpty == false || names["departmentName"]?.isEmpty == false {
            var org = [escaped(names["organizationName"]!)]
            if names["departmentName"]?.isEmpty == false { org.append(escaped(names["departmentName"]!)) }
            roundtrip.append("ORG:" + org.joined(separator: ";"))
        }
        let urls = try labeled(fields, "urlAddresses")
        for row in urls {
            let value = try text(row.value)
            // Match the canonical app's webLinkZiel text bounds before asking
            // Foundation to parse. The real JS URL parser is checked again by
            // projection; raw vCard retention alone does not make a usable URL.
            let plainURL = value.unicodeScalars.allSatisfy {
                !CharacterSet.whitespacesAndNewlines.contains($0) &&
                ![0x5C, 0xFEFF, 0x061C, 0x200E, 0x200F].contains($0.value) &&
                !(0x202A...0x202E).contains($0.value) && !(0x2066...0x2069).contains($0.value)
            }
            guard value.utf16.count <= 4096, plainURL,
                  value.range(of: "^https?://[^/]", options: [.regularExpression, .caseInsensitive]) != nil,
                  let url = URL(string: value), ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
                  url.host?.isEmpty == false, url.user == nil, url.password == nil else {
                throw Exclusion("native-contact-url-not-representable")
            }
            roundtrip.append("URL:" + escaped(value))
            if row.label?.isEmpty == false { notices.insert("native-contact-url-labels-in-source") }
        }
        let date = try birthday(fields), picture = try photo(fields)
        guard !record.title.isEmpty || ["givenName", "familyName", "organizationName"].contains(where: { names[$0]?.isEmpty == false }) ||
              !phones.isEmpty || !emails.isEmpty || !addresses.isEmpty || !urls.isEmpty || !date.isEmpty || !picture.isEmpty else {
            throw Exclusion("native-contact-no-supported-content")
        }
        let contact: [String: Any] = ["vorname": names["givenName"]!, "nachname": names["familyName"]!,
            "anzeigename": record.title, "firma": names["organizationName"]!, "telefone": phones, "emailEintraege": emails,
            "anschriften": addresses, "foto": picture, "geburtstag": date, "geburtstagJahrUnbekannt": date.hasPrefix("--"),
            "vcardRoundtrip": roundtrip]
        return (contact, notices.sorted())
    }
}
