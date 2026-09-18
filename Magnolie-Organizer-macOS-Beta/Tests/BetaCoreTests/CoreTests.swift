import XCTest
@testable import BetaCore

final class CoreTests: XCTestCase {
    let plain = "{ \"termine\": [], \"aufgaben\": [], \"kontakte\": [], \"notizen\": [], \"future\":{\"keep\":[true,null,1]} }\n"

    func testAllowlistAndTypes() throws {
        XCTAssertEqual(try Request(#"{"cmd":"speichern","id":1,"text":"{}"}"#).command, .speichern)
        for text in [#"{"cmd":"speichern","id":true,"text":"{}"}"#,
                     #"{"cmd":"speichern","id":1.5,"text":"{}"}"#,
                     #"{"cmd":"speichern","id":9007199254740992,"text":"{}"}"#,
                     #"{"cmd":"speichern","id":0,"text":"{}"}"#,
                     #"{"cmd":"bereit","path":"/tmp"}"#,
                     #"{"cmd":"sicherung_wiederherstellen","pfad":"/tmp/anything"}"#,
                     #"{"cmd":"kennwort_entfernen","alt":"test"}"#,
                     #"{"cmd":"sync","daten":{}}"#,
                     #"{"cmd":"bereit","cmd":"beenden"}"#,
                     #"{"cmd":"bereit","\u0063md":"beenden"}"#,
                     #"{"cmd":"speichern","id":"1","text":"{}"}"#] {
            XCTAssertThrowsError(try Request(text), text)
        }
        XCTAssertThrowsError(try Document.object(#"{"nested":{"a":1,"a":2}}"#))
        XCTAssertThrowsError(try Document.object(#"{"trailing":1,}"#))
        XCTAssertThrowsError(try Document.object("[]"))
        XCTAssertThrowsError(try Document.plain("{}"))
        XCTAssertThrowsError(try Document.plain(#"{"verfahren":"broken"}"#))
    }

    func testOpaqueFieldsAndDestructiveGuard() throws {
        let old = try Document.object(#"{"termine":[{"id":"a","future":{"bytes":"AA=="}}],"unknown":null}"#)
        let safe = try Document.object(#"{"termine":[{"id":"b"},{"id":"a","title":"edited","future":{"bytes":"AA=="}}],"unknown":null}"#)
        XCTAssertNoThrow(try Document.assertNoLoss(old, safe))
        for text in [#"{"termine":[{"id":"a"}],"unknown":null}"#,
                     #"{"termine":[],"unknown":null}"#,
                     #"{"termine":[{"id":"b","future":{"bytes":"AA=="}}],"unknown":null}"#,
                     #"{"termine":[{"id":"a","future":{"bytes":"AA=="}}]}"#] {
            XCTAssertThrowsError(try Document.assertNoLoss(old, Document.object(text)))
        }
    }

    func testAtomicPersistenceAndLease() throws {
        let parent = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: parent) }
        let directory = parent.appendingPathComponent("profile")
        var store: AtomicStore? = try AtomicStore(directory: directory)
        XCTAssertThrowsError(try store!.commit(plain))
        XCTAssertNil(try store!.load())
        XCTAssertThrowsError(try AtomicStore(directory: directory))
        try store!.commit(plain)
        let file = store!.file
        XCTAssertEqual(try String(contentsOf: file, encoding: .utf8), plain)
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        XCTAssertEqual((attributes[.posixPermissions] as! NSNumber).intValue & 0o777, 0o600)
        store = nil
        store = try AtomicStore(directory: directory)
        XCTAssertEqual(try store!.load(), plain)
        try AtomicStore.write(Data((plain + " ").utf8), to: file)
        XCTAssertThrowsError(try store!.commit(plain))
        XCTAssertEqual(try String(contentsOf: file, encoding: .utf8), plain + " ")
        store = nil
        try FileManager.default.removeItem(at: file)
        try FileManager.default.createSymbolicLink(atPath: file.path, withDestinationPath: "/etc/passwd")
        store = try AtomicStore(directory: directory)
        XCTAssertThrowsError(try store!.load())
    }

    func testEmptyAndCorruptFilesAreNotNewProfiles() throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        var store: AtomicStore? = try AtomicStore(directory: directory)
        XCTAssertNil(try store!.load()); try store!.commit(plain)
        let file = store!.file; store = nil
        let handle = try FileHandle(forWritingTo: file)
        try handle.truncate(atOffset: 0); try handle.close()
        store = try AtomicStore(directory: directory)
        XCTAssertThrowsError(try store!.load())
        XCTAssertThrowsError(try store!.commit(plain))
    }

    func testRecoveryProtectsReplacementAndSurvivesRestart() throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        var store: AtomicStore? = try AtomicStore(directory: directory)
        XCTAssertNil(try store!.load())
        let original = #"{ "termine":[], "aufgaben":[{"id":"keep","opaque":{"attachment":"AA=="}}], "kontakte":[], "notizen":[], "future":true }"# + "\n"
        try store!.commit(original)
        let beforeMutation = try store!.checkpoint()
        try store!.commit(plain, preservingCurrent: true)
        let recovery = directory.appendingPathComponent("Recovery-macOS-Beta")
        let snapshots = try FileManager.default.contentsOfDirectory(at: recovery, includingPropertiesForKeys: nil)
        XCTAssertEqual(snapshots.count, 2)
        for url in snapshots { XCTAssertEqual(try AtomicStore.read(url), Data(original.utf8)) }
        store = nil
        store = try AtomicStore(directory: directory)
        XCTAssertEqual(try store!.load(), plain)
        let selected = try BackupSelection(url: beforeMutation)
        XCTAssertFalse(selected.encrypted)
        try store!.commit(selected.confirmed(path: beforeMutation.path), preservingCurrent: true)
        XCTAssertEqual(try AtomicStore.read(store!.file), Data(original.utf8))
        let all = try FileManager.default.contentsOfDirectory(at: recovery, includingPropertiesForKeys: nil)
        XCTAssertEqual(all.count, 3)
        XCTAssertTrue(try all.contains { try AtomicStore.read($0) == Data(plain.utf8) })
    }

    func testCheckpointFailureAndExternalEditBlockReplacement() throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try AtomicStore(directory: directory)
        XCTAssertNil(try store.load()); try store.commit(plain)
        let recovery = directory.appendingPathComponent("Recovery-macOS-Beta")
        // A pre-existing unexpected file is not overwritten or treated as a directory.
        try AtomicStore.write(Data("sentinel".utf8), to: recovery)
        XCTAssertThrowsError(try store.commit(plain + " ", preservingCurrent: true))
        XCTAssertEqual(try AtomicStore.read(store.file), Data(plain.utf8))
        XCTAssertEqual(try AtomicStore.read(recovery), Data("sentinel".utf8))
        try FileManager.default.removeItem(at: recovery)
        try FileManager.default.createSymbolicLink(atPath: recovery.path, withDestinationPath: directory.path)
        XCTAssertThrowsError(try store.checkpoint())
        XCTAssertEqual(try AtomicStore.read(store.file), Data(plain.utf8))
        try FileManager.default.removeItem(at: recovery)
        try AtomicStore.write(Data((plain + " ").utf8), to: store.file)
        XCTAssertThrowsError(try store.checkpoint())
        XCTAssertThrowsError(try store.commit(plain, preservingCurrent: true))
        XCTAssertFalse(FileManager.default.fileExists(atPath: recovery.path))
    }

    func testBackupSelectionPinsBytesAndPath() throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("desktop-backup.json")
        try AtomicStore.write(Data(plain.utf8), to: url)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: url.path)
        XCTAssertThrowsError(try AtomicStore.read(url))
        let selected = try BackupSelection(url: url)
        XCTAssertEqual(try selected.confirmed(path: url.path), plain)
        XCTAssertThrowsError(try selected.confirmed(path: directory.appendingPathComponent("other.json").path))
        try AtomicStore.write(Data((plain + " ").utf8), to: url)
        XCTAssertThrowsError(try selected.confirmed(path: url.path))
        for bad in ["{}", #"{"termine":[],"termine":[],"aufgaben":[],"kontakte":[],"notizen":[]}"#, #"{"verfahren":"damaged"}"#] {
            try AtomicStore.write(Data(bad.utf8), to: url)
            XCTAssertThrowsError(try BackupSelection(url: url))
        }
        try FileManager.default.removeItem(at: url)
        try FileManager.default.createSymbolicLink(atPath: url.path, withDestinationPath: "/etc/passwd")
        XCTAssertThrowsError(try BackupSelection(url: url))
    }

    func testRegionalValidationAndOpaquePreferencePreservation() throws {
        let input: [String: Any] = ["language": "ar", "formatLocale": "ar-EG", "timeZone": "Europe/Berlin",
            "hourCycle": "h12", "firstDayOfWeek": "saturday", "weekRule": "iso", "temperatureUnit": "celsius", "homeCountry": "DE"]
        let settings = try RegionalSettings.validate(input)
        var root = try Document.plain(plain)
        root["einstellungen"] = ["future": ["keep": true], "regional": ["extension": "keep"]]
        let output = try Document.plain(RegionalSettings.merging(settings, into: Document.encode(root)))
        XCTAssertNotNil(output["future"])
        let preferences = output["einstellungen"] as! [String: Any]
        XCTAssertNotNil(preferences["future"])
        XCTAssertEqual((preferences["regional"] as! [String: String])["extension"], "keep")
        for (key, value) in [("language", "../de"), ("timeZone", "Invalid/Zone"), ("homeCountry", "XXX"), ("hourCycle", "13"), ("formatLocale", "de<script>")] {
            var bad = input; bad[key] = value
            XCTAssertThrowsError(try RegionalSettings.validate(bad))
        }
        var bad = input; bad["homeCountry"] = true
        XCTAssertThrowsError(try RegionalSettings.validate(bad))
        bad = input; bad["extra"] = "anything"
        XCTAssertThrowsError(try RegionalSettings.validate(bad))
        root["einstellungen"] = ["regional": "opaque incompatible preferences"]
        XCTAssertThrowsError(try RegionalSettings.merging(settings, into: Document.encode(root)))
    }

    func testCalendarSubset() throws {
        let record: [String: Any] = ["id": "test", "titel": "a,b\nBEGIN:VTODO", "datum": "2026-09-13",
                                     "zeit": "10:00", "endZeit": "11:00", "wiederholung": ["art": "none", "bis": ""]]
        let text = try CalendarExport.appointments([record])
        XCTAssertTrue(text.contains("DTSTART:20260913T100000\r\n"))
        XCTAssertTrue(text.contains("SUMMARY:a\\,b\\nBEGIN:VTODO\r\n"))
        XCTAssertFalse(text.contains("\r\nBEGIN:VTODO\r\n"))
        var recurring = record; recurring["wiederholung"] = ["art": "daily"]
        XCTAssertThrowsError(try CalendarExport.appointments([recurring]))
        var rich = record; rich["icsRoundtrip"] = ["RRULE:FREQ=DAILY"]
        XCTAssertThrowsError(try CalendarExport.appointments([rich]))
        rich = record; rich["future"] = ["important": true]
        XCTAssertThrowsError(try CalendarExport.appointments([rich]))
    }

    func testCurrentEditorAppointments() throws {
        guard let path = ProcessInfo.processInfo.environment["MACOS_BETA_EDITOR_FIXTURES"] else {
            throw XCTSkip("Run tools/check_editor.py --swift with a JS runtime to test live canonical editor records.")
        }
        let fixture = try Document.object(String(contentsOfFile: path, encoding: .utf8))
        let cases = try XCTUnwrap(fixture["cases"] as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(cases.count, 9)
        for item in cases {
            let record = try XCTUnwrap(item["record"] as? [String: Any])
            let raw = try XCTUnwrap(record["icsRoundtrip"] as? [String])
            XCTAssertTrue(raw.contains(where: { $0.hasPrefix("LOCATION:") }))
            let text = try CalendarExport.appointments([record])
            let location = try XCTUnwrap(item["location"] as? String)
                .replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: ";", with: "\\;")
                .replacingOccurrences(of: ",", with: "\\,")
            XCTAssertTrue(text.contains("LOCATION:" + location + "\r\n"))
            XCTAssertTrue(text.contains((item["start"] as! String) + "\r\n"))
            XCTAssertTrue(text.contains((item["end"] as! String) + "\r\n"))
            XCTAssertEqual(text.components(separatedBy: "\r\nLOCATION:").count, 2, "No duplicate raw/structured LOCATION")
            for line in ["RRULE:FREQ=DAILY", "BEGIN:VALARM", "ATTENDEE:mailto:a@example.invalid",
                         "ATTACH:https://example.invalid/a", "X-IMPORTANT:retain", "LOCATION:Elsewhere",
                         "LOCATION;LANGUAGE=en:" + location, "DTSTART:19990101T100000",
                         "DTSTART;TZID=Invalid/Zone:20260510T120000", "SUMMARY:Contradiction"] {
                var negative = record; negative["icsRoundtrip"] = raw + [line]
                XCTAssertThrowsError(try CalendarExport.appointments([negative]), line)
            }
            var contradictory = record; contradictory["ort"] = "Changed without updating raw LOCATION"
            XCTAssertThrowsError(try CalendarExport.appointments([contradictory]))
            var rich = record; rich["providerMetadaten"] = ["mustPreserve": true]
            XCTAssertThrowsError(try CalendarExport.appointments([rich]))
            rich = record; rich["teilnehmer"] = [["email": "a@example.invalid"]]
            XCTAssertThrowsError(try CalendarExport.appointments([rich]))
            rich = record; rich["kalenderAnhaenge"] = [["uri": "https://example.invalid/a"]]
            XCTAssertThrowsError(try CalendarExport.appointments([rich]))
        }
    }

    func testRawCalendarTimeConsistency() throws {
        var record: [String: Any] = ["id": "test", "titel": "Synthetic", "datum": "2026-05-10",
            "zeit": "10:00", "endZeit": "11:00", "wiederholung": ["art": "none", "bis": ""]]
        record["icsRoundtrip"] = ["DTSTART:20260510T100000Z", "DTEND:20260510T110000Z"]
        XCTAssertTrue(try CalendarExport.appointments([record]).contains("DTSTART:20260510T100000Z\r\n"))
        for raw in [
            ["DTSTART;TZID=Europe/Berlin:20260510T100000", "DTEND;TZID=America/New_York:20260510T110000"],
            ["DTSTART:20260510T100000Z"],
            ["DTSTART;TZID=Europe/Berlin:20260510T100000", "DTEND:20260510T110000"],
            ["DTSTART;TZID=UTC:20260510T100000Z", "DTEND:20260510T110000Z"],
            ["DTSTART:20260510T100001", "DTEND:20260510T110000"],
            ["DTSTART:20260510T100000", "DTSTART:20260510T100000"], [""]
        ] {
            record["icsRoundtrip"] = raw
            XCTAssertThrowsError(try CalendarExport.appointments([record]), raw.description)
        }
        record["icsRoundtrip"] = "LOCATION:Office"
        XCTAssertThrowsError(try CalendarExport.appointments([record]))
        record["icsRoundtrip"] = [String]()
        record["wiederholung"] = "daily"
        XCTAssertThrowsError(try CalendarExport.appointments([record]))
        let allDay: [String: Any] = ["id": "date-only", "titel": "DST day", "datum": "2026-03-29", "zeit": "", "endZeit": "",
            "icsRoundtrip": ["DTSTART;VALUE=DATE:20260329", "DTEND;VALUE=DATE:20260330"]]
        XCTAssertTrue(try CalendarExport.appointments([allDay]).contains("DTEND;VALUE=DATE:20260330\r\n"))
    }

    #if canImport(CryptoKit) && canImport(CommonCrypto)
    func testDesktopEncryptionInteropAndTampering() throws {
        let url = Bundle.module.url(forResource: "desktop-envelopes", withExtension: "json", subdirectory: "Fixtures")!
        let fixture = try Document.object(String(contentsOf: url, encoding: .utf8))
        let password = fixture["password"] as! String, plain = fixture["plain"] as! String
        for version in ["v1", "v2"] {
            let input = fixture[version] as! String
            let (decoded, session) = try Encryption.unlock(input, password: password)
            XCTAssertEqual(decoded, plain)
            let output = try session.encrypt(decoded)
            XCTAssertEqual(try Encryption.unlock(output, password: password).0, plain)
            XCTAssertFalse(output.contains("opaque"))
            XCTAssertThrowsError(try Encryption.unlock(input, password: "incorrect"))
            var corrupt = try Document.object(input)
            var bytes = Data(base64Encoded: corrupt["daten"] as! String)!
            bytes[bytes.count - 1] ^= 1; corrupt["daten"] = bytes.base64EncodedString()
            XCTAssertThrowsError(try Encryption.unlock(Document.encode(corrupt), password: password))
            if version == "v2" {
                XCTAssertNotNil(try Document.object(output)["futureEnvelope"])
                XCTAssertEqual(try Document.object(input)["dekDaten"] as? String,
                               try Document.object(output)["dekDaten"] as? String)
            }
        }
        let session = try Encryption.create(password: password)
        XCTAssertNotEqual(try session.encrypt(plain), try session.encrypt(plain))
    }

    func testEncryptedRecoveryRetainsEnvelopeWithoutPlaintextShadow() throws {
        let directory = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = try AtomicStore(directory: directory)
        XCTAssertNil(try store.load())
        let password = "public synthetic password"
        let encrypted = try Encryption.create(password: password).encrypt(plain)
        try store.commit(encrypted)
        let checkpoint = try store.checkpoint()
        let selected = try BackupSelection(url: checkpoint)
        XCTAssertTrue(selected.encrypted)
        XCTAssertEqual(selected.text, encrypted)
        XCTAssertEqual(try Encryption.unlock(selected.confirmed(path: checkpoint.path), password: password).0, plain)
        XCTAssertThrowsError(try Encryption.unlock(selected.text, password: "wrong"))
    }
    #endif
}
