#if os(macOS)
import Foundation
import Contacts
import ImageIO
import UniformTypeIdentifiers
import BetaCore

/// Refs #775/#786. Queue-confined contact reads and the separately authorized
/// exact-record field-write adapter. Copy operations continue to be read-only.
/// Call only through SystemAccountStore, with its existing CNContactStore and
/// cooperative read control. No CN object leaves these functions. This selected
/// scope is separate from the older full-source snapshots and vCard reader.
enum SystemContactReader {
    struct Summary: Sendable {
        let identifier: String
        let title: String
    }

    private static let maximumContainers = 256
    private static let maximumMetadataRecords = 10_000
    private static let maximumLabeledValues = 1000
    private static let maximumScalarBytes = 65_536

    // A name formatter descriptor has the documented name-only purpose. Neither
    // this list nor detailKeys requests contact notes, vCard keys, or thumbnails.
    private static let metadataKeys: [CNKeyDescriptor] = [
        CNContactIdentifierKey as CNKeyDescriptor,
        CNContactTypeKey as CNKeyDescriptor,
        CNContactFormatter.descriptorForRequiredKeys(for: .fullName)
    ]
    private static let detailKeys: [CNKeyDescriptor] = metadataKeys + [
        CNContactNamePrefixKey, CNContactGivenNameKey, CNContactMiddleNameKey,
        CNContactFamilyNameKey, CNContactPreviousFamilyNameKey, CNContactNameSuffixKey,
        CNContactNicknameKey, CNContactPhoneticGivenNameKey, CNContactPhoneticMiddleNameKey,
        CNContactPhoneticFamilyNameKey, CNContactPhoneticOrganizationNameKey,
        CNContactOrganizationNameKey, CNContactDepartmentNameKey, CNContactJobTitleKey,
        CNContactPhoneNumbersKey, CNContactEmailAddressesKey, CNContactPostalAddressesKey,
        CNContactUrlAddressesKey, CNContactRelationsKey, CNContactSocialProfilesKey,
        CNContactInstantMessageAddressesKey, CNContactBirthdayKey,
        CNContactNonGregorianBirthdayKey, CNContactDatesKey,
        CNContactImageDataAvailableKey, CNContactImageDataKey
    ].map { $0 as CNKeyDescriptor }

    static func sources(store: CNContactStore, control: SystemSourceReadControl,
                        requireAccess: () throws -> Void) throws -> [SystemContactImport.Source] {
        try control.check(); try requireAccess()
        let containers = try store.containers(matching: nil)
        try control.check(); try requireAccess()
        guard containers.count <= maximumContainers else { throw failure("too many address books") }
        var identities = Set<OpaqueUTF8Identity>(), budget = Budget()
        let result = try containers.map { container in
            try control.check()
            let source = try source(container, budget: &budget)
            guard identities.insert(OpaqueUTF8Identity(source.containerID)).inserted else {
                throw failure("address book identities are ambiguous")
            }
            return source
        }
        try control.check(); try requireAccess()
        return result
    }

    /// IDs and names only. No phone, email, postal address, photo, or note reads.
    static func summaries(store: CNContactStore, source expected: SystemContactImport.Source,
                          control: SystemSourceReadControl,
                          requireAccess: () throws -> Void) throws -> [Summary] {
        try control.check(); try requireAccess()
        _ = try currentSource(store, expected: expected, control: control)
        let request = makeRequest(keys: metadataKeys,
            predicate: CNContact.predicateForContactsInContainer(withIdentifier: expected.containerID))
        var rows: [Summary] = [], seen = Set<OpaqueUTF8Identity>(), budget = Budget(), problem: Error?
        try store.enumerateContacts(with: request) { contact, stop in
            do {
                try control.check()
                guard rows.count < maximumMetadataRecords, contact.areKeysAvailable(metadataKeys) else {
                    throw failure("the address book exceeds the metadata limit or required name fields were not fetched")
                }
                let identifier = try budget.identifier(contact.identifier)
                guard seen.insert(OpaqueUTF8Identity(identifier)).inserted else { throw failure("contact identities are ambiguous") }
                let name = try title(contact, budget: &budget)
                rows.append(Summary(identifier: identifier, title: name))
            } catch { problem = error; stop.pointee = true }
        }
        if let problem { throw problem }
        try control.check(); try requireAccess()
        _ = try currentSource(store, expected: expected, control: control)
        try control.check(); try requireAccess()
        return rows
    }

    /// Read only the selected, non-unified originals. Container membership is
    /// checked separately because CNContactFetchRequest rejects compound predicates.
    /// Repeating this complete operation after review gives the Core plan fresh
    /// serialized-field evidence; it is not an atomic Contacts revision token.
    static func snapshot(store: CNContactStore, source expected: SystemContactImport.Source,
                         identifiers: [String], control: SystemSourceReadControl,
                         requireAccess: () throws -> Void) throws -> SystemContactImport.Snapshot {
        try control.check(); try requireAccess()
        let selected = try selectedIdentities(identifiers)
        let current = try currentSource(store, expected: expected, control: control)
        try requireMembership(store, source: current, selected: selected, control: control)
        try control.check(); try requireAccess()
        let request = makeRequest(keys: detailKeys,
            predicate: CNContact.predicateForContacts(withIdentifiers: identifiers))
        var records: [SystemContactImport.Record] = []
        var found = Set<OpaqueUTF8Identity>(), budget = Budget(), serializedBytes = 0, problem: Error?
        try store.enumerateContacts(with: request) { contact, stop in
            do {
                try control.check()
                guard contact.areKeysAvailable(detailKeys) else {
                    // Reading an unfetched getter raises an Objective-C exception,
                    // so fail before touching any requested field, not after it.
                    throw failure("required contact fields were not fetched")
                }
                let identifier = try budget.identifier(contact.identifier), key = OpaqueUTF8Identity(identifier)
                guard selected.contains(key), found.insert(key).inserted,
                      found.count <= SystemContactImport.maximumRecords else {
                    throw failure("selected contact identities are missing, duplicated or changed")
                }
                let record = try record(contact, identifier: identifier, control: control, budget: &budget)
                let bytes = try Document.encode(record.fields).utf8.count
                guard bytes <= SystemContactImport.maximumBytes - serializedBytes else {
                    throw failure("selected contact data exceeds 16 MiB; select fewer contacts")
                }
                serializedBytes += bytes
                records.append(record)
            } catch { problem = error; stop.pointee = true }
        }
        if let problem { throw problem }
        try control.check(); try requireAccess()
        guard found == selected else { throw failure("a selected contact is no longer available") }
        try requireMembership(store, source: current, selected: selected, control: control)
        let finalSource = try currentSource(store, expected: current, control: control)
        try control.check(); try requireAccess()
        // Return caller selection order, without allowing Swift String's Unicode
        // equivalence to merge distinct opaque native identifiers.
        let byID = Dictionary(uniqueKeysWithValues: records.map { (OpaqueUTF8Identity($0.identifier), $0) })
        let ordered = try identifiers.map { identifier -> SystemContactImport.Record in
            guard let record = byID[OpaqueUTF8Identity(identifier)] else { throw failure("selected contact is missing") }
            return record
        }
        return SystemContactImport.Snapshot(source: finalSource, records: ordered)
    }

    private static func makeRequest(keys: [CNKeyDescriptor], predicate: NSPredicate) -> CNContactFetchRequest {
        let request = CNContactFetchRequest(keysToFetch: keys)
        request.predicate = predicate
        request.unifyResults = false
        request.mutableObjects = false
        return request
    }

    /// Refs #786. Update an exact non-unified record; do not construct a contact
    /// from its displayed name and do not replace unfetched/private properties.
    static func applySync(store: CNContactStore, operation: SystemAccountSync.Operation,
                          source binding: SystemAccountSync.Source, context: CalendarTimeContext,
                          control: SystemSourceReadControl, requireAccess: () throws -> Void) throws -> SystemAccountSync.Record {
        var enteredSave = false
        do {
            try control.check(); try requireAccess()
            let expected = try SystemAccountSyncProjection.contactSource(binding)
            let current = try currentSource(store, expected: expected, control: control)
            let selected = try selectedIdentities([operation.identifier])
            try requireMembership(store, source: current, selected: selected, control: control)
            let request = makeRequest(keys: detailKeys, predicate: CNContact.predicateForContacts(withIdentifiers: [operation.identifier]))
            var objects: [CNContact] = []
            try store.enumerateContacts(with: request) { contact, stop in
                objects.append(contact); if objects.count > 1 { stop.pointee = true }
            }
            guard objects.count == 1, let contact = objects.first, contact.areKeysAvailable(detailKeys),
                  same(contact.identifier, operation.identifier) else { throw failure("the selected contact is missing or ambiguous") }
            var budget = Budget()
            let raw = try record(contact, identifier: operation.identifier, control: control, budget: &budget)
            let observed = try SystemAccountSyncProjection.contacts(.init(source: current, records: [raw]), displayTimeZone: binding.displayTimeZone)
            guard observed.source.fingerprint == binding.fingerprint, observed.records.count == 1,
                  observed.excluded.isEmpty, let before = observed.records.first, before.revision == operation.before.revision else {
                throw failure("the selected contact or source changed after planning")
            }
            let patch = try SystemAccountSyncProjection.nativePatch(record: before, desired: operation.desiredRecord,
                changedGroups: operation.changedGroups, source: binding, context: context)
            guard try DAVSyncBaseline.canonicalJSON(patch) == DAVSyncBaseline.canonicalJSON(operation.nativePatch),
                  let mutable = contact.mutableCopy() as? CNMutableContact else { throw failure("invalid contact field operation") }
            if let value = patch["givenName"] as? String { mutable.givenName = value }
            if let value = patch["familyName"] as? String { mutable.familyName = value }
            if let value = patch["organizationName"] as? String { mutable.organizationName = value }
            if let values = patch["phoneNumbers"] as? [[String: Any]] {
                guard values.count == mutable.phoneNumbers.count else { throw failure("phone value identity changed") }
                mutable.phoneNumbers = try mutable.phoneNumbers.enumerated().map { index, old in
                    guard same(old.identifier, values[index]["identifier"] as? String ?? ""), let value = values[index]["value"] as? String else { throw failure("phone value identity changed") }
                    return old.settingValue(CNPhoneNumber(stringValue: value))
                }
            }
            if let values = patch["emailAddresses"] as? [[String: Any]] {
                guard values.count == mutable.emailAddresses.count else { throw failure("email value identity changed") }
                mutable.emailAddresses = try mutable.emailAddresses.enumerated().map { index, old in
                    guard same(old.identifier, values[index]["identifier"] as? String ?? ""), let value = values[index]["value"] as? String else { throw failure("email value identity changed") }
                    return old.settingValue(value as NSString)
                }
            }
            if let values = patch["postalAddresses"] as? [[String: Any]] {
                guard values.count == mutable.postalAddresses.count else { throw failure("postal value identity changed") }
                mutable.postalAddresses = try mutable.postalAddresses.enumerated().map { index, old in
                    guard same(old.identifier, values[index]["identifier"] as? String ?? ""), let fields = values[index]["value"] as? [String: Any],
                          let address = old.value.mutableCopy() as? CNMutablePostalAddress,
                          let street = fields["street"] as? String, let city = fields["city"] as? String,
                          let state = fields["state"] as? String, let postal = fields["postalCode"] as? String else { throw failure("postal value identity changed") }
                    address.street = street; address.city = city; address.state = state; address.postalCode = postal
                    return old.settingValue(address)
                }
            }
            if let value = patch["birthday"] { mutable.birthday = try SystemAccountSyncDates.components(value) }
            try requireMembership(store, source: current, selected: selected, control: control)
            _ = try currentSource(store, expected: current, control: control)
            try control.check(); try requireAccess()
            let save = CNSaveRequest(); save.update(mutable)
            // CNSaveRequest has no compare-and-swap condition. No caller may
            // clear its journal just because execute returned or threw.
            enteredSave = true
            try store.execute(save)
            guard same(mutable.identifier, operation.identifier) else { throw failure("contact identity changed after saving") }
            let fresh = try snapshot(store: store, source: current, identifiers: [operation.identifier], control: control, requireAccess: requireAccess)
            let read = try SystemAccountSyncProjection.contacts(fresh, displayTimeZone: binding.displayTimeZone)
            guard read.source.fingerprint == binding.fingerprint, read.records.count == 1, read.excluded.isEmpty,
                  let readback = read.records.first else { throw failure("contact readback is unavailable after saving") }
            try operation.validateReadback(readback)
            return readback
        } catch {
            if enteredSave { throw BetaError("The native contact write has an uncertain outcome. Keep the journal and review the source. " + error.localizedDescription) }
            throw SystemAccountSync.RejectedBeforeWrite(error.localizedDescription)
        }
    }

    private static func selectedIdentities(_ identifiers: [String]) throws -> Set<OpaqueUTF8Identity> {
        guard !identifiers.isEmpty, identifiers.count <= SystemContactImport.maximumRecords else {
            throw failure("select between 1 and 100 contacts")
        }
        var budget = Budget(), result = Set<OpaqueUTF8Identity>()
        for identifier in identifiers {
            _ = try budget.identifier(identifier)
            guard result.insert(OpaqueUTF8Identity(identifier)).inserted else { throw failure("duplicate selected contact identity") }
        }
        return result
    }

    private static func source(_ container: CNContainer, budget: inout Budget) throws -> SystemContactImport.Source {
        let identifier = try budget.identifier(container.identifier)
        let uid = SystemSourcePolicy.uid(.contacts, identifier)
        guard same(try SystemSourcePolicy.identifier(uid, kind: .contacts), identifier) else { throw failure("invalid address book identity") }
        return SystemContactImport.Source(sourceUID: uid, containerID: identifier,
            title: try budget.text(container.name, maximum: SystemContactImport.maximumTitleBytes),
            nativeType: "container:\(container.type.rawValue)")
    }

    private static func currentSource(_ store: CNContactStore, expected: SystemContactImport.Source,
                                      control: SystemSourceReadControl) throws -> SystemContactImport.Source {
        try control.check()
        guard same(try SystemSourcePolicy.identifier(expected.sourceUID, kind: .contacts), expected.containerID) else {
            throw failure("invalid selected address book identity")
        }
        let containers = try store.containers(matching: CNContainer.predicateForContainers(withIdentifiers: [expected.containerID]))
        try control.check()
        guard containers.count == 1 else { throw failure("selected address book is missing or ambiguous") }
        var budget = Budget()
        let current = try source(containers[0], budget: &budget)
        guard same(current.sourceUID, expected.sourceUID), same(current.containerID, expected.containerID),
              same(current.title, expected.title), same(current.nativeType, expected.nativeType) else {
            throw failure("the selected address book changed; select it again")
        }
        return current
    }

    private static func requireMembership(_ store: CNContactStore, source: SystemContactImport.Source,
                                          selected: Set<OpaqueUTF8Identity>, control: SystemSourceReadControl) throws {
        try control.check()
        let keys: [CNKeyDescriptor] = [CNContactIdentifierKey as CNKeyDescriptor]
        let request = makeRequest(keys: keys,
            predicate: CNContact.predicateForContactsInContainer(withIdentifier: source.containerID))
        var all = Set<OpaqueUTF8Identity>(), members = Set<OpaqueUTF8Identity>(), budget = Budget(), problem: Error?
        try store.enumerateContacts(with: request) { contact, stop in
            do {
                try control.check()
                guard contact.areKeysAvailable(keys), all.count < maximumMetadataRecords else {
                    throw failure("address book membership could not be read within its limit")
                }
                let key = OpaqueUTF8Identity(try budget.identifier(contact.identifier))
                guard all.insert(key).inserted else { throw failure("address book membership is ambiguous") }
                if selected.contains(key) { members.insert(key) }
            } catch { problem = error; stop.pointee = true }
        }
        if let problem { throw problem }
        try control.check()
        guard members == selected else { throw failure("a selected contact moved or is no longer in this address book") }
    }

    private static func title(_ contact: CNContact, budget: inout Budget) throws -> String {
        // nil means the fetched naming fields have no formatted display name;
        // it is not a fallback for an unavailable key (checked before this call).
        try budget.text(CNContactFormatter.string(from: contact, style: .fullName) ?? "",
                        maximum: SystemContactImport.maximumTitleBytes)
    }

    private enum LabelScope: Equatable { case phone, email, url, postal, other }
    private static func labelKind(_ label: String?, scope: LabelScope) -> String {
        guard let label else { return "none" }
        if scope == .other { return "custom" }
        var known: [(String, String)] = [(CNLabelHome, "home"), (CNLabelWork, "work"), (CNLabelOther, "other")]
        switch scope {
        case .phone: known += [(CNLabelPhoneNumberMobile, "mobile"), (CNLabelPhoneNumberiPhone, "iphone"),
            (CNLabelPhoneNumberMain, "main"), (CNLabelPhoneNumberHomeFax, "homeFax"),
            (CNLabelPhoneNumberWorkFax, "workFax"), (CNLabelPhoneNumberOtherFax, "otherFax"), (CNLabelPhoneNumberPager, "pager")]
        case .email: known += [(CNLabelEmailiCloud, "icloud")]
        case .url: known += [(CNLabelURLAddressHomePage, "homePage")]
        case .postal, .other: break
        }
        return known.first(where: { same($0.0, label) })?.1 ?? "custom"
    }

    private static func labeled<Value>(_ values: [CNLabeledValue<Value>], scope: LabelScope = .other,
                                       control: SystemSourceReadControl, budget: inout Budget,
                                       convert: (Value, inout Budget) throws -> Any) throws -> [[String: Any]]
        where Value: NSCopying, Value: NSSecureCoding {
        guard values.count <= maximumLabeledValues else { throw failure("a contact has too many labeled values") }
        var result: [[String: Any]] = [], identifiers = Set<OpaqueUTF8Identity>()
        for entry in values {
            try control.check()
            let identifier = try budget.identifier(entry.identifier)
            guard identifiers.insert(OpaqueUTF8Identity(identifier)).inserted else { throw failure("labeled contact values have ambiguous identities") }
            let label: Any
            if let raw = entry.label { label = try budget.text(raw, maximum: 4096) }
            else { label = NSNull() }
            result.append(["identifier": identifier, "label": label, "labelKind": labelKind(entry.label, scope: scope),
                           "value": try convert(entry.value, &budget)])
        }
        return result
    }

    private static func components(_ value: DateComponents?, budget: inout Budget) throws -> Any {
        guard let fields = SystemDateComponents.fields(value) else { return NSNull() }
        // Preserve year absence, calendar identity and leap-month state. Never
        // manufacture a midnight Date or the current year for a contact date.
        try budget.charge(Document.encode(fields).utf8.count)
        return fields
    }

    private static func record(_ contact: CNContact, identifier: String, control: SystemSourceReadControl,
                               budget: inout Budget) throws -> SystemContactImport.Record {
        let name = try title(contact, budget: &budget)
        var fields: [String: Any] = [
            "unification": "nonUnifiedContainer", "unavailableKeys": ["note"],
            "contactType": contact.contactType.rawValue,
            "namePrefix": try budget.text(contact.namePrefix), "givenName": try budget.text(contact.givenName),
            "middleName": try budget.text(contact.middleName), "familyName": try budget.text(contact.familyName),
            "previousFamilyName": try budget.text(contact.previousFamilyName), "nameSuffix": try budget.text(contact.nameSuffix),
            "nickname": try budget.text(contact.nickname), "phoneticGivenName": try budget.text(contact.phoneticGivenName),
            "phoneticMiddleName": try budget.text(contact.phoneticMiddleName), "phoneticFamilyName": try budget.text(contact.phoneticFamilyName),
            "phoneticOrganizationName": try budget.text(contact.phoneticOrganizationName),
            "organizationName": try budget.text(contact.organizationName), "departmentName": try budget.text(contact.departmentName),
            "jobTitle": try budget.text(contact.jobTitle),
            "birthday": try components(contact.birthday, budget: &budget),
            "nonGregorianBirthday": try components(contact.nonGregorianBirthday, budget: &budget)
        ]
        fields["phoneNumbers"] = try labeled(contact.phoneNumbers, scope: .phone, control: control, budget: &budget) {
            value, budget in try budget.text(value.stringValue)
        }
        fields["emailAddresses"] = try labeled(contact.emailAddresses, scope: .email, control: control, budget: &budget) {
            value, budget in try budget.text(value as String)
        }
        fields["urlAddresses"] = try labeled(contact.urlAddresses, scope: .url, control: control, budget: &budget) {
            value, budget in try budget.text(value as String)
        }
        fields["postalAddresses"] = try labeled(contact.postalAddresses, scope: .postal, control: control, budget: &budget) { value, budget in
            ["street": try budget.text(value.street), "city": try budget.text(value.city),
             "state": try budget.text(value.state), "postalCode": try budget.text(value.postalCode),
             "country": try budget.text(value.country), "isoCountryCode": try budget.text(value.isoCountryCode),
             "subAdministrativeArea": try budget.text(value.subAdministrativeArea), "subLocality": try budget.text(value.subLocality)]
        }
        fields["contactRelations"] = try labeled(contact.contactRelations, control: control, budget: &budget) {
            value, budget in try budget.text(value.name)
        }
        fields["socialProfiles"] = try labeled(contact.socialProfiles, control: control, budget: &budget) { value, budget in
            ["username": try budget.text(value.username), "service": try budget.text(value.service),
             "urlString": try budget.text(value.urlString), "userIdentifier": try budget.text(value.userIdentifier)]
        }
        fields["instantMessageAddresses"] = try labeled(contact.instantMessageAddresses, control: control, budget: &budget) { value, budget in
            ["username": try budget.text(value.username), "service": try budget.text(value.service)]
        }
        fields["dates"] = try labeled(contact.dates, control: control, budget: &budget) { value, budget in
            try components(value as DateComponents, budget: &budget)
        }
        try control.check()
        fields["imageDataAvailable"] = contact.imageDataAvailable
        var readFailure: String?
        if let image = contact.imageData {
            guard !image.isEmpty, image.count <= SystemContactImport.maximumImageBytes else {
                throw failure("a contact photo exceeds the original-image size limit")
            }
            // Bound before Base64 allocation; preserve exact original imageData.
            let encodedSize = ((image.count + 2) / 3) * 4
            try budget.charge(encodedSize)
            fields["imageData"] = image.base64EncodedString()
            let mime = try imageMIME(image, control: control)
            fields["imageMIME"] = mime.map { $0 as Any } ?? NSNull()
            if mime == nil { readFailure = "contact-image-format-unsupported" }
            if !contact.imageDataAvailable { readFailure = "contact-image-state-inconsistent" }
        } else {
            fields["imageData"] = NSNull(); fields["imageMIME"] = NSNull()
            if contact.imageDataAvailable { readFailure = "contact-original-image-unavailable" }
        }
        try control.check()
        return SystemContactImport.Record(identifier: identifier, title: name, fields: fields, failure: readFailure)
    }

    private static func imageMIME(_ data: Data, control: SystemSourceReadControl) throws -> String? {
        // Inspect and decode the original bytes; never substitute a thumbnail or
        // transcode an unsupported image. Decoded pixels are only a validity check.
        let prefix = Array(data.prefix(12)), signature: String
        if prefix.starts(with: [0xff, 0xd8, 0xff]) { signature = "image/jpeg" }
        else if prefix.starts(with: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) { signature = "image/png" }
        else if prefix.starts(with: Array("GIF87a".utf8)) || prefix.starts(with: Array("GIF89a".utf8)) { signature = "image/gif" }
        else if prefix.count == 12, prefix[0..<4].elementsEqual("RIFF".utf8), prefix[8..<12].elementsEqual("WEBP".utf8) {
            signature = "image/webp"
        } else { return nil }
        let options = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, options),
              CGImageSourceGetStatus(source) == .statusComplete,
              let type = CGImageSourceGetType(source) else { return nil }
        let imageCount = CGImageSourceGetCount(source)
        guard (1...64).contains(imageCount) else { return nil }
        let decodedMIME: String
        switch type as String {
        case UTType.jpeg.identifier: decodedMIME = "image/jpeg"
        case UTType.png.identifier: decodedMIME = "image/png"
        case UTType.gif.identifier: decodedMIME = "image/gif"
        case UTType.webP.identifier: decodedMIME = "image/webp"
        default: return nil
        }
        // Force decoding only after the dimension/pixel checks. The default is
        // deferred decoding, which would move the cost/failure into the UI later.
        let decodeOptions = [kCGImageSourceShouldCache: true, kCGImageSourceShouldCacheImmediately: true] as CFDictionary
        guard decodedMIME == signature else { return nil }
        var pixels: Int64 = 0
        for index in 0..<imageCount {
            try control.check()
            guard let properties = CGImageSourceCopyPropertiesAtIndex(source, index, options) as? [CFString: Any],
                  let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.int64Value,
                  let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.int64Value,
                  width > 0, height > 0, width <= 8192, height <= 8192,
                  width * height <= 16_777_216 - pixels else { return nil }
            pixels += width * height
            guard let decoded = CGImageSourceCreateImageAtIndex(source, index, decodeOptions),
                  decoded.width == Int(width), decoded.height == Int(height) else { return nil }
        }
        try control.check()
        return decodedMIME
    }

    private struct Budget {
        var bytes = 0
        mutating func charge(_ count: Int) throws {
            guard count >= 0, count <= SystemContactImport.maximumBytes - bytes else {
                throw SystemContactReader.failure("selected contact data exceeds 16 MiB; select fewer contacts")
            }
            bytes += count
        }
        mutating func text(_ value: String, maximum: Int = SystemContactReader.maximumScalarBytes) throws -> String {
            let count = value.utf8.count
            guard count <= maximum else { throw SystemContactReader.failure("a contact field exceeds its read limit") }
            try charge(count)
            return value
        }
        mutating func identifier(_ value: String) throws -> String {
            guard !value.isEmpty else { throw SystemContactReader.failure("a native identity is unavailable") }
            return try text(value, maximum: SystemContactImport.maximumIdentifierBytes)
        }
    }
    private static func same(_ left: String, _ right: String) -> Bool { left.utf8.elementsEqual(right.utf8) }
    private static func failure(_ message: String) -> BetaError { BetaError("macOS contact copy: " + message + ".") }
}
#endif
