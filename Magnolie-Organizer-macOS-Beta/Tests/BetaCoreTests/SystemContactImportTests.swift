import Foundation
import XCTest
@testable import BetaCore

/// Refs #775. Pure read/plan tests. No Contacts permission or provider writes.
final class SystemContactImportTests: XCTestCase {
    private func source(id: String = "container-one", title: String = "Selected address book",
                        type: String = "container:2") -> SystemContactImport.Source {
        .init(sourceUID: SystemSourcePolicy.uid(.contacts, id), containerID: id, title: title, nativeType: type)
    }
    private func fields(_ changes: [String: Any] = [:]) -> [String: Any] {
        var value: [String: Any] = ["unification": "nonUnifiedContainer", "unavailableKeys": ["note"], "contactType": 0]
        for name in ["namePrefix", "givenName", "middleName", "familyName", "previousFamilyName", "nameSuffix", "nickname",
                     "phoneticGivenName", "phoneticMiddleName", "phoneticFamilyName", "phoneticOrganizationName",
                     "organizationName", "departmentName", "jobTitle"] { value[name] = "" }
        value["givenName"] = "Ada"; value["familyName"] = "Lovelace"
        for name in ["phoneNumbers", "emailAddresses", "postalAddresses", "urlAddresses", "contactRelations",
                     "socialProfiles", "instantMessageAddresses", "dates"] { value[name] = [[String: Any]]() }
        value["birthday"] = NSNull(); value["nonGregorianBirthday"] = NSNull()
        value["imageDataAvailable"] = false; value["imageData"] = NSNull(); value["imageMIME"] = NSNull()
        return value.merging(changes) { _, new in new }
    }
    private func record(id: String = "contact-one", title: String = "Ada Lovelace", changes: [String: Any] = [:],
                        failure: String? = nil) -> SystemContactImport.Record {
        .init(identifier: id, title: title, fields: fields(changes), failure: failure)
    }
    private func snapshot(_ records: [SystemContactImport.Record], source selected: SystemContactImport.Source? = nil) -> SystemContactImport.Snapshot {
        .init(source: selected ?? source(), records: records)
    }
    private func row(_ value: Any, id: String = "value-one", label: String? = nil, kind: String = "none") -> [String: Any] {
        ["identifier": id, "label": label.map { $0 as Any } ?? NSNull(), "labelKind": kind, "value": value]
    }
    private func contacts(_ plan: SystemContactImport.Plan) throws -> [[String: Any]] {
        try XCTUnwrap(plan.payload["contacts"] as? [[String: Any]])
    }
    private func excluded(_ plan: SystemContactImport.Plan) throws -> [[String: Any]] {
        try XCTUnwrap(plan.payload["excluded"] as? [[String: Any]])
    }
    private func first(_ plan: SystemContactImport.Plan) throws -> [String: Any] { try XCTUnwrap(contacts(plan).first) }
    private func contact(_ input: SystemContactImport.Record) throws -> [String: Any] {
        try XCTUnwrap(first(SystemContactImport.prepare(snapshot([input])))["contact"] as? [String: Any])
    }
    private func assertExcluded(_ input: SystemContactImport.Record, _ reason: String,
                                file: StaticString = #filePath, line: UInt = #line) throws {
        let plan = try SystemContactImport.prepare(snapshot([input]))
        XCTAssertTrue(try contacts(plan).isEmpty, file: file, line: line)
        let rejected = try XCTUnwrap(excluded(plan).first, file: file, line: line)
        XCTAssertEqual(Set(rejected.keys), Set(["identifier", "title", "reasons"]), file: file, line: line)
        XCTAssertEqual(rejected["identifier"] as? String, input.identifier, file: file, line: line)
        XCTAssertEqual(rejected["reasons"] as? [String], [reason], file: file, line: line)
        XCTAssertNoThrow(try plan.revalidate(snapshot([input])), file: file, line: line)
    }
    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "system-contact-copy", withExtension: "json", subdirectory: "Fixtures"))
        return try Document.object(String(contentsOf: url, encoding: .utf8))
    }
    private func fixtureRecord(_ fixture: [String: Any]) throws -> SystemContactImport.Record {
        let raw = try XCTUnwrap((fixture["records"] as? [[String: Any]])?.first)
        return .init(identifier: try XCTUnwrap(raw["identifier"] as? String), title: try XCTUnwrap(raw["title"] as? String),
                     fields: try XCTUnwrap(raw["fields"] as? [String: Any]), failure: raw["failure"] as? String)
    }
    private func bytes(_ value: Any) throws -> Data { Data(try Document.encode(value).utf8) }

    func testSharedReaderFixtureProjectsEveryAgreedFieldAndKeepsOriginalRaw() throws {
        let expected = try fixture(), input = try fixtureRecord(expected)
        let rawSource = try XCTUnwrap(expected["source"] as? [String: Any])
        let selected = SystemContactImport.Source(sourceUID: try XCTUnwrap(rawSource["sourceUID"] as? String),
            containerID: try XCTUnwrap(rawSource["containerID"] as? String), title: try XCTUnwrap(rawSource["title"] as? String),
            nativeType: try XCTUnwrap(rawSource["nativeType"] as? String))
        let plan = try SystemContactImport.prepare(snapshot([input], source: selected)), entry = try first(plan)
        XCTAssertEqual(Set(plan.payload.keys), Set(["version", "source", "contacts", "excluded", "snapshotRevision"]))
        XCTAssertEqual(plan.payload["version"] as? Int, 1)
        XCTAssertEqual(try bytes(XCTUnwrap(plan.payload["source"])), try bytes(rawSource))
        XCTAssertEqual(plan.payload["snapshotRevision"] as? String, plan.snapshotRevision)
        XCTAssertEqual(Set(entry.keys), Set(["identity", "revision", "identifier", "title", "contact", "nativeRecord", "notices"]))
        XCTAssertEqual(entry["identity"] as? String, expected["expectedIdentity"] as? String)
        XCTAssertEqual(try bytes(XCTUnwrap(entry["contact"])), try bytes(XCTUnwrap(expected["expectedContact"])))
        XCTAssertEqual(entry["notices"] as? [String], expected["expectedNotices"] as? [String])
        let raw = try XCTUnwrap((expected["records"] as? [[String: Any]])?.first)
        XCTAssertEqual(try bytes(XCTUnwrap(entry["nativeRecord"])), try bytes(raw))
        let draft = try XCTUnwrap(entry["contact"] as? [String: Any])
        XCTAssertEqual(Set(draft.keys), Set(["vorname", "nachname", "anzeigename", "firma", "telefone", "emailEintraege",
            "anschriften", "foto", "geburtstag", "geburtstagJahrUnbekannt", "vcardRoundtrip"]))
        XCTAssertEqual((draft["emailEintraege"] as? [[String: Any]])?.first?["wert"] as? String, "Ada@Example.Test")
        XCTAssertTrue(try excluded(plan).isEmpty)
        XCTAssertNoThrow(try plan.revalidate(snapshot([input], source: selected)))
    }

    func testControlledVCardLinesEscapeValuesWithoutActivatingForeignUIDOrCategories() throws {
        let draft = try contact(record(title: "Ada; Example, \\ Person", changes: ["familyName": "Example; Jr.",
            "givenName": "Ada, A.", "middleName": "Middle\\Name", "namePrefix": "Dr.", "nameSuffix": "Jr.",
            "organizationName": "Company; Division", "departmentName": "Team, West"]))
        let lines = try XCTUnwrap(draft["vcardRoundtrip"] as? [String])
        XCTAssertEqual(lines, ["N:Example\\; Jr.;Ada\\, A.;Middle\\\\Name;Dr.;Jr.",
            "FN:Ada\\; Example\\, \\\\ Person", "ORG:Company\\; Division;Team\\, West"])
        XCTAssertFalse(lines.contains { $0.hasPrefix("UID:") || $0.hasPrefix("REV:") || $0.hasPrefix("CATEGORIES:") })
        for key in ["id", "uid", "sync", "syncQuellen", "nativeContactImport", "vcard"] { XCTAssertNil(draft[key]) }
    }

    func testSupportedLabelsAndMultivaluesRetainOrder() throws {
        let kinds = ["home", "work", "other", "mobile", "iphone", "main", "homeFax", "workFax", "otherFax", "pager", "none", "custom"]
        let rows = kinds.enumerated().map { index, kind in
            row("+44 20 7946 \(1000 + index)", id: "p-\(index)", label: kind == "none" ? nil : "Studio", kind: kind)
        }
        let draft = try contact(record(changes: ["phoneNumbers": rows]))
        let phones = try XCTUnwrap(draft["telefone"] as? [[String: Any]])
        XCTAssertEqual(phones.count, rows.count)
        let expected = [["HOME", "VOICE"], ["WORK", "VOICE"], ["OTHER", "VOICE"], ["CELL"], ["CELL"],
                        ["PREF", "VOICE"], ["HOME", "FAX"], ["WORK", "FAX"], ["FAX"], ["PAGER"], ["VOICE"], ["VOICE"]]
        XCTAssertEqual(phones.compactMap { $0["typen"] as? [String] }, expected)
        XCTAssertEqual(phones[4]["label"] as? String, "iPhone")
        XCTAssertEqual(phones[11]["label"] as? String, "Studio")
        XCTAssertEqual(phones.compactMap { $0["wert"] as? String }, rows.compactMap { $0["value"] as? String })
    }

    func testOriginalEmailCaseAndDuplicateNativeValuesAreLeftForRealNormalizerReview() throws {
        let rows = [row("Ada@Example.Test", id: "mail-one", label: "First", kind: "custom"),
                    row("ada@example.test", id: "mail-two", label: "Second", kind: "custom")]
        let input = record(changes: ["emailAddresses": rows]), plan = try SystemContactImport.prepare(snapshot([input]))
        let draft = try XCTUnwrap(first(plan)["contact"] as? [String: Any])
        XCTAssertEqual((draft["emailEintraege"] as? [[String: Any]])?.count, 2)
        XCTAssertEqual((draft["emailEintraege"] as? [[String: Any]])?.first?["wert"] as? String, "Ada@Example.Test")
        XCTAssertFalse((try first(plan)["notices"] as? [String] ?? []).contains("native-contact-email-case-normalized"))
    }

    func testMissingRequiredFieldIsExcludedAndPrivateOrUnknownFieldsAreHardErrors() throws {
        var missing = fields(); missing.removeValue(forKey: "phoneNumbers")
        try assertExcluded(.init(identifier: "id", title: "Title", fields: missing), "native-contact-field-unavailable")
        let unknown: [[String: Any]] = [["note": "Private note"], ["vcard": "UID:foreign"], ["futureUnknownProperty": true]]
        for changes in unknown {
            XCTAssertThrowsError(try SystemContactImport.prepare(snapshot([record(changes: changes)])))
        }
        let missingStates: [[String: Any]] = [["unavailableKeys": ["note", "givenName"]], ["contactType": true],
            ["contactType": 2], ["unification": "unified"], ["givenName": NSNull()]]
        for changes in missingStates {
            try assertExcluded(record(changes: changes), "native-contact-field-unavailable")
        }
    }

    func testReadFailureIsVisibleAndNeverTreatsMissingDataAsEmpty() throws {
        for failure in ["contact-image-format-unsupported", "contact-original-image-unavailable", ""] {
            try assertExcluded(record(failure: failure), "native-contact-read-failed")
        }
        try assertExcluded(.init(identifier: "id", title: "Readable title", fields: [:], failure: "read failed"), "native-contact-read-failed")
    }

    func testUnsafeActiveControlsAndOversizedTextAreExcluded() throws {
        for value in ["Ada\u{0}", "Ada\nInjected", "Ada\u{7F}", "Ada\u{85}", String(repeating: "é", count: 32_769)] {
            try assertExcluded(record(changes: ["givenName": value]), "native-contact-text-not-representable")
        }
        try assertExcluded(record(title: "Name\u{0}"), "native-contact-text-not-representable")
        XCTAssertFalse(try contact(record(changes: ["givenName": String(repeating: "é", count: 32_768)])).isEmpty)
    }

    func testCustomLabelsAreNeverTrimmedOrTruncatedByCore() throws {
        for label in [" Studio", "Studio ", String(repeating: "🌼", count: 41)] {
            try assertExcluded(record(changes: ["phoneNumbers": [row("+44 123456789", label: label, kind: "custom")]]),
                               "native-contact-label-not-representable")
        }
        let boundary = String(repeating: "🌼", count: 40)
        let draft = try contact(record(changes: ["phoneNumbers": [row("+44 123456789", label: boundary, kind: "custom")]]))
        XCTAssertEqual((draft["telefone"] as? [[String: Any]])?.first?["label"] as? String, boundary)
        try assertExcluded(record(changes: ["phoneNumbers": [row("+44 123456789", kind: "custom")]]),
                           "native-contact-label-not-representable")
        try assertExcluded(record(changes: ["phoneNumbers": [row("+44 123456789", label: "Custom", kind: "none")]]),
                           "native-contact-label-not-representable")
    }

    func testAmbiguousLabeledIdentitiesAndUnexpectedActivePostalFieldsAreExcluded() throws {
        let duplicate = [row("+44 123456789"), row("+44 987654321")]
        try assertExcluded(record(changes: ["phoneNumbers": duplicate]), "native-contact-labeled-value-not-representable")
        try assertExcluded(record(changes: ["phoneNumbers": [row("+44 123456789", kind: "unknown")]]),
                           "native-contact-labeled-value-not-representable")
        try assertExcluded(record(changes: ["postalAddresses": [row(["street": "Street", "unsupported": "Detail"])]]),
                           "native-contact-address-not-representable")
    }

    func testOnlyUsableAbsoluteHTTPWebsitesBecomeControlledURLLines() throws {
        for url in ["https://example.test/path?x=a%20b&y=1", "HTTP://example.test:8080/path", "https://[::1]/"] {
            let draft = try contact(record(changes: ["urlAddresses": [row(url)]]))
            XCTAssertEqual((draft["vcardRoundtrip"] as? [String])?.last, "URL:" + url)
        }
        let bad = ["example.test", "http:example.test", "https:///example.test", "mailto:ada@example.test", "file:///tmp/a",
                   "javascript:alert(1)", "https://user:secret@example.test", " https://example.test", "https://example.test/a b",
                   "https://example.test/a\\b", "https://example.test/\u{FEFF}", "https://example.test/\u{061C}",
                   "https://example.test/\u{200E}", "https://example.test/\u{202E}", "https://example.test/\u{2066}",
                   "https://example.test/" + String(repeating: "x", count: 4096)]
        for url in bad {
            try assertExcluded(record(changes: ["urlAddresses": [row(url)]]), "native-contact-url-not-representable")
        }
    }

    func testGregorianBirthdaysKeepMissingYearAndValidateLeapDays() throws {
        let cases: [([String: Any], String)] = [(["month": 2, "day": 29], "--02-29"),
            (["year": 2000, "month": 2, "day": 29, "calendar": "gregorian"], "2000-02-29"),
            (["year": 1604, "month": 2, "day": 29, "calendar": "gregorian"], "1604-02-29"),
            (["year": 1984, "month": 12, "day": 10], "1984-12-10"),
            (["year": 1000, "month": 1, "day": 1, "era": 1, "isLeapMonth": false], "1000-01-01")]
        for (components, expected) in cases {
            let draft = try contact(record(changes: ["birthday": components]))
            XCTAssertEqual(draft["geburtstag"] as? String, expected)
            XCTAssertEqual(draft["geburtstagJahrUnbekannt"] as? Bool, expected.hasPrefix("--"))
        }
        let absent = try contact(record())
        XCTAssertEqual(absent["geburtstag"] as? String, "")
        XCTAssertEqual(absent["geburtstagJahrUnbekannt"] as? Bool, false)
    }

    func testAmbiguousAndUnsupportedDatesAreVisibleExclusions() throws {
        let unsupported: [[String: Any]] = [["month": 2, "day": 30], ["year": 1900, "month": 2, "day": 29],
            ["month": 13, "day": 1], ["month": 1, "day": 0], ["year": 999, "month": 1, "day": 1],
            ["month": 2, "day": true], ["month": 1, "day": 1, "calendar": "hebrew"],
            ["month": 1, "day": 1, "hour": 0], ["month": 1, "day": 1, "timeZone": "Europe/Berlin"],
            ["month": 1, "day": 1, "era": 0], ["month": 1, "day": 1, "isLeapMonth": true], [:]]
        for birthday in unsupported {
            try assertExcluded(record(changes: ["birthday": birthday]), "native-contact-birthday-not-representable")
        }
        try assertExcluded(record(changes: ["nonGregorianBirthday": ["calendar": "hebrew", "month": 1, "day": 1]]),
                           "native-contact-non-gregorian-birthday-not-supported")
        try assertExcluded(record(changes: ["dates": [row(["month": 5, "day": 4], label: "Anniversary", kind: "custom")]]),
                           "native-contact-additional-dates-not-supported")
        var missing = fields(); missing.removeValue(forKey: "birthday")
        try assertExcluded(.init(identifier: "id", title: "Name", fields: missing), "native-contact-birthday-state-unavailable")
    }

    func testNativeDateComponentsKeepCalendarMetadataAndYearAbsenceInRaw() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "Europe/Berlin"))
        calendar.locale = Locale(identifier: "de_DE")
        var components = DateComponents(); components.calendar = calendar; components.month = 3; components.day = 14
        let raw = try XCTUnwrap(SystemDateComponents.fields(components))
        XCTAssertNil(raw["year"])
        let entry = try first(SystemContactImport.prepare(snapshot([record(changes: ["birthday": raw])])) )
        XCTAssertEqual((entry["contact"] as? [String: Any])?["geburtstag"] as? String, "--03-14")
        let native = try XCTUnwrap((entry["nativeRecord"] as? [String: Any])?["fields"] as? [String: Any])
        XCTAssertEqual(try bytes(XCTUnwrap(native["birthday"])), try bytes(raw))
    }

    func testPhotoUsesOriginalBytesWithoutSubstitutionAndRequiresConsistentPresence() throws {
        let raw = try fixtureRecord(fixture()).fields
        let encoded = try XCTUnwrap(raw["imageData"] as? String)
        let draft = try contact(record(changes: ["imageDataAvailable": true, "imageData": encoded, "imageMIME": "image/png"]))
        XCTAssertEqual(draft["foto"] as? String, "data:image/png;base64," + encoded)
        let inconsistent: [[String: Any]] = [["imageDataAvailable": NSNull()], ["imageDataAvailable": 0],
            ["imageData": encoded], ["imageMIME": "image/png"]]
        for changes in inconsistent {
            try assertExcluded(record(changes: changes), "native-contact-photo-state-unavailable")
        }
        let invalid: [[String: Any]] = [["imageDataAvailable": true],
            ["imageDataAvailable": true, "imageData": encoded, "imageMIME": "image/jpeg"],
            ["imageDataAvailable": true, "imageData": "not base64", "imageMIME": "image/png"],
            ["imageDataAvailable": true, "imageData": encoded + "\n", "imageMIME": "image/png"],
            ["imageDataAvailable": true, "imageData": "", "imageMIME": "image/png"]]
        for changes in invalid {
            try assertExcluded(record(changes: changes), "native-contact-photo-not-representable")
        }
    }

    func testPhotoByteLimitIsCheckedBeforeCreatingADataURI() throws {
        var photo = Data([137, 80, 78, 71, 13, 10, 26, 10])
        photo.append(Data(repeating: 0, count: SystemContactImport.maximumImageBytes - photo.count + 1))
        try assertExcluded(record(changes: ["imageDataAvailable": true, "imageData": photo.base64EncodedString(), "imageMIME": "image/png"]),
                           "native-contact-photo-not-representable")
    }

    func testEmptyContactIsExcludedButSupportedPhoneOnlyContactHasNoInventedName() throws {
        try assertExcluded(record(title: "", changes: ["givenName": "", "familyName": ""]), "native-contact-no-supported-content")
        let draft = try contact(record(title: "", changes: ["givenName": "", "familyName": "", "phoneNumbers": [row("+44 123456789")]]))
        XCTAssertEqual(draft["vorname"] as? String, "")
        XCTAssertEqual(draft["nachname"] as? String, "")
        XCTAssertEqual(draft["anzeigename"] as? String, "")
        XCTAssertEqual((draft["telefone"] as? [[String: Any]])?.count, 1)
    }

    func testOpaqueIdentitiesAndTextRetainExactUTF8WithoutUnicodeNormalization() throws {
        let composed = "\u{E9}", decomposed = "e\u{301}"
        let one = record(id: composed, title: decomposed, changes: ["givenName": decomposed])
        let two = record(id: decomposed, title: composed, changes: ["givenName": composed])
        let plan = try SystemContactImport.prepare(snapshot([one, two])), entries = try contacts(plan)
        XCTAssertEqual(entries.count, 2)
        XCTAssertNotEqual(entries[0]["identity"] as? String, entries[1]["identity"] as? String)
        let byBytes = Dictionary(uniqueKeysWithValues: try entries.map { (Data(try XCTUnwrap($0["identifier"] as? String).utf8), $0) })
        let retained = try XCTUnwrap(byBytes[Data(composed.utf8)])
        XCTAssertEqual(Data(try XCTUnwrap(retained["title"] as? String).utf8), Data(decomposed.utf8))
        XCTAssertEqual(Data(try XCTUnwrap((retained["contact"] as? [String: Any])?["vorname"] as? String).utf8), Data(decomposed.utf8))
        XCTAssertThrowsError(try plan.revalidate(snapshot([record(id: composed, title: composed), two])))
    }

    func testIdentityBindsContainerAndNativeIDButNotEditableMetadata() throws {
        let original = try first(SystemContactImport.prepare(snapshot([record()])))
        let renamed = try first(SystemContactImport.prepare(snapshot([record(title: "Renamed")], source: source(title: "New title"))))
        XCTAssertEqual(original["identity"] as? String, renamed["identity"] as? String)
        XCTAssertNotEqual(original["revision"] as? String, renamed["revision"] as? String)
        let moved = try first(SystemContactImport.prepare(snapshot([record()], source: source(id: "other"))))
        XCTAssertNotEqual(original["identity"] as? String, moved["identity"] as? String)
        let composed = try first(SystemContactImport.prepare(snapshot([record()], source: source(id: "\u{E9}"))))
        let decomposed = try first(SystemContactImport.prepare(snapshot([record()], source: source(id: "e\u{301}"))))
        XCTAssertNotEqual(composed["identity"] as? String, decomposed["identity"] as? String)
    }

    func testSelectionOrderIsImmaterialAndActualNativeFieldChangesInvalidateReview() throws {
        let one = record(), two = record(id: "contact-two", title: "Second contact")
        let plan = try SystemContactImport.prepare(snapshot([one, two]))
        let reordered = try SystemContactImport.prepare(snapshot([two, one]))
        XCTAssertEqual(plan.snapshotRevision, reordered.snapshotRevision)
        XCTAssertEqual(try bytes(plan.payload), try bytes(reordered.payload))
        XCTAssertNoThrow(try plan.revalidate(snapshot([two, one])))
        for changed in [record(title: "Renamed"), record(changes: ["nickname": "Different"]),
                        record(changes: ["contactRelations": [row("Different relation")]]), record(failure: "unreadable")] {
            XCTAssertThrowsError(try plan.revalidate(snapshot([changed, two])))
            XCTAssertNotEqual(plan.snapshotRevision, try SystemContactImport.prepare(snapshot([changed, two])).snapshotRevision)
        }
        XCTAssertThrowsError(try plan.revalidate(snapshot([one])))
        XCTAssertThrowsError(try plan.revalidate(snapshot([one, two, record(id: "third")])))
        for selected in [source(title: "Changed"), source(type: "container:1"), source(id: "changed")] {
            XCTAssertThrowsError(try plan.revalidate(snapshot([one, two], source: selected)))
        }
    }

    func testExcludedRawAndReadFailureChangesAlsoInvalidateWholeReview() throws {
        let input = record(failure: "unreadable"), plan = try SystemContactImport.prepare(snapshot([input]))
        XCTAssertTrue(try contacts(plan).isEmpty)
        for changed in [record(failure: "different error"), record(changes: ["nickname": "Changed ignored field"], failure: "unreadable"),
                        record(title: "Changed excluded name", failure: "unreadable")] {
            XCTAssertThrowsError(try plan.revalidate(snapshot([changed])))
            XCTAssertNotEqual(plan.snapshotRevision, try SystemContactImport.prepare(snapshot([changed])).snapshotRevision)
        }
    }

    func testPlanFreezesCallerOwnedNestedObjects() throws {
        let mutable = NSMutableDictionary(dictionary: row("+44 123456789"))
        let input = record(changes: ["phoneNumbers": NSMutableArray(object: mutable)])
        let plan = try SystemContactImport.prepare(snapshot([input])), original = try bytes(plan.payload)
        mutable["value"] = "+44 987654321"
        XCTAssertEqual(try bytes(plan.payload), original)
        XCTAssertThrowsError(try plan.revalidate(snapshot([input])))
    }

    func testMissingDuplicateOversizedAndCrossContainerIdentitiesAreHardFailures() throws {
        for records in [[record(id: "")], [record(), record()], [record(id: String(repeating: "é", count: 8193))],
                        [record(title: String(repeating: "é", count: 2049))]] {
            XCTAssertThrowsError(try SystemContactImport.prepare(snapshot(records)))
        }
        let incorrect = SystemContactImport.Source(sourceUID: source().sourceUID, containerID: "different", title: "Title", nativeType: "container:2")
        XCTAssertThrowsError(try SystemContactImport.prepare(snapshot([record()], source: incorrect)))
        for selected in [source(id: ""), source(type: "birthday"), source(title: "Bad\u{0}title")] {
            XCTAssertThrowsError(try SystemContactImport.prepare(snapshot([record()], source: selected)))
        }
        XCTAssertEqual(try contacts(SystemContactImport.prepare(snapshot([record(id: String(repeating: "é", count: 8192))]))).count, 1)
    }

    func testSelectionAndLabeledArrayLimitsAbortWithoutReturningAPrefix() throws {
        XCTAssertEqual(try contacts(SystemContactImport.prepare(snapshot((0..<100).map { record(id: "id-\($0)") }))).count, 100)
        XCTAssertThrowsError(try SystemContactImport.prepare(snapshot((0..<101).map { record(id: "id-\($0)") })))
        let many = (0...1000).map { row("+44 12345", id: "p-\($0)") }
        XCTAssertThrowsError(try SystemContactImport.prepare(snapshot([record(changes: ["phoneNumbers": many])])) )
        XCTAssertThrowsError(try SystemContactImport.prepare(snapshot([record(changes: ["contactType": Double.nan])])) )
    }

    func testFinalTransportLimitIncludesRawAndProjectedPhotoDuplication() throws {
        // Core checks serialized evidence and transport; the Reader separately
        // proves actual image decoding. Signature-only bytes isolate this bound.
        var image = Data([137, 80, 78, 71, 13, 10, 26, 10])
        image.append(Data(repeating: 0, count: SystemContactImport.maximumImageBytes - image.count))
        let changes: [String: Any] = ["imageDataAvailable": true, "imageData": image.base64EncodedString(), "imageMIME": "image/png"]
        XCTAssertThrowsError(try SystemContactImport.prepare(snapshot((0..<3).map { record(id: "photo-\($0)", changes: changes) }))) { error in
            XCTAssertTrue(error.localizedDescription.contains("proposal exceeds 16 MiB"))
        }
        XCTAssertThrowsError(try SystemContactImport.prepare(snapshot((0..<5).map { record(id: "photo-\($0)", changes: changes) }))) { error in
            XCTAssertTrue(error.localizedDescription.contains("snapshot evidence exceeds 16 MiB"))
        }
    }

    func testNativeSelectionBridgeRejectsCallerSuppliedIdentifiersOrPayload() throws {
        XCTAssertEqual(try Request("{\"cmd\":\"macos_kontakte_importieren\"}").command, .macos_kontakte_importieren)
        let injections: [[String: Any]] = [["containerID": "container-one"], ["sourceUID": source().sourceUID], ["identifiers": ["contact-one"]],
            ["fields": ["givenName": "Injected"]], ["vcard": "UID:foreign"], ["script": "provider write"], ["sync": true]]
        for extra in injections {
            var input = extra; input["cmd"] = "macos_kontakte_importieren"
            XCTAssertThrowsError(try Request(Document.encode(input)))
        }
    }
}
