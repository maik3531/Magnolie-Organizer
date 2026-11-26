import Foundation
import XCTest
@testable import BetaCore

/// Refs #777. Pure proposals/codec checks; no permission request or store write.
final class SystemReminderImportTests: XCTestCase {
    private func source(id: String = "reminder-list-one", title: String = "Selected reminder list",
                        parent: String = "reminder-account-one", parentTitle: String = "Selected account",
                        parentType: String = "source:2", type: String = "calendar:2", readOnly: Bool = false,
                        permission: String = "authorized") -> SystemReminderImport.Source {
        .init(sourceUID: SystemSourcePolicy.uid(.reminders, id), calendarID: id, title: title,
              parentUID: "macos-account:" + Data(parent.utf8).base64EncodedString(), parentTitle: parentTitle,
              parentType: parentType, nativeType: type, readOnly: readOnly, permission: permission)
    }
    private func fields(_ changes: [String: Any] = [:]) -> [String: Any] {
        let value: [String: Any] = ["metadataIncomplete": ["native-reminder-hierarchy", "native-reminder-attachments",
            "native-reminder-tags", "native-reminder-flags", "native-reminder-assignees", "native-reminder-rich-text", "provider-opaque-fields"],
            "hierarchyAvailable": false, "title": "Native reminder 🌼", "notes": "Exact native text", "hasNotes": true,
            "location": NSNull(), "url": NSNull(), "externalIdentifier": "provider-id", "itemTimeZone": NSNull(),
            "created": 1_780_000_000.125, "modified": 1_780_000_600.5,
            "completed": false, "completionDate": NSNull(), "priority": 0,
            "startComponents": NSNull(), "dueComponents": NSNull(),
            "hasAlarms": false, "alarms": [[String: Any]](), "hasRecurrenceRules": false, "recurrenceRules": [[String: Any]]()]
        return value.merging(changes) { _, new in new }
    }
    private func record(id: String = "reminder-one", changes: [String: Any] = [:], failure: String? = nil) -> SystemReminderImport.Record {
        .init(identifier: id, fields: fields(changes), failure: failure)
    }
    private func snapshot(_ records: [SystemReminderImport.Record], source selected: SystemReminderImport.Source? = nil) -> SystemReminderImport.Snapshot {
        .init(source: selected ?? source(), records: records)
    }
    private func prepare(_ snapshot: SystemReminderImport.Snapshot, zone: String = "Europe/Berlin") throws -> SystemReminderImport.Plan {
        try SystemReminderImport.prepare(snapshot, context: CalendarTestContext.make(systemIdentifier: "UTC"), displayTimeZone: zone)
    }
    private func tasks(_ plan: SystemReminderImport.Plan) throws -> [[String: Any]] { try XCTUnwrap(plan.payload["tasks"] as? [[String: Any]]) }
    private func excluded(_ plan: SystemReminderImport.Plan) throws -> [[String: Any]] { try XCTUnwrap(plan.payload["excluded"] as? [[String: Any]]) }
    private func first(_ plan: SystemReminderImport.Plan) throws -> [String: Any] { try XCTUnwrap(tasks(plan).first) }
    private func task(_ record: SystemReminderImport.Record, zone: String = "Europe/Berlin") throws -> [String: Any] {
        try XCTUnwrap(first(prepare(snapshot([record]), zone: zone))["task"] as? [String: Any])
    }
    private func date(_ changes: [String: Any] = [:]) -> [String: Any] {
        ["calendar": "gregorian", "year": 2026, "month": 11, "day": 27].merging(changes) { _, new in new }
    }
    private func clock(_ changes: [String: Any] = [:]) -> [String: Any] {
        date(["hour": 9, "minute": 5, "second": 0]).merging(changes) { _, new in new }
    }
    private func bytes(_ value: Any) throws -> Data { Data(try Document.encode(value).utf8) }
    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "system-reminder-copy", withExtension: "json", subdirectory: "Fixtures"))
        return try Document.object(String(contentsOf: url, encoding: .utf8))
    }
    private func assertExcluded(_ record: SystemReminderImport.Record, _ reason: String, zone: String = "Europe/Berlin",
                                file: StaticString = #filePath, line: UInt = #line) throws {
        let plan = try prepare(snapshot([record]), zone: zone)
        XCTAssertTrue(try tasks(plan).isEmpty, "\(record.identifier): \(reason)", file: file, line: line)
        let rejected = try XCTUnwrap(excluded(plan).first, "\(record.identifier): \(reason)", file: file, line: line)
        XCTAssertEqual(Set(rejected.keys), Set(["identifier", "title", "reasons"]), file: file, line: line)
        XCTAssertEqual(rejected["identifier"] as? String, record.identifier, file: file, line: line)
        XCTAssertEqual(rejected["reasons"] as? [String], [reason], file: file, line: line)
        XCTAssertNoThrow(try plan.revalidate(snapshot([record])), file: file, line: line)
    }

    func testSharedFixtureRetainsRawAndProjectsFloatingTimeWithoutCalendarZoneFallback() throws {
        let expected = try fixture(), raw = try XCTUnwrap((expected["records"] as? [[String: Any]])?.first)
        let input = SystemReminderImport.Record(identifier: try XCTUnwrap(raw["identifier"] as? String),
            fields: try XCTUnwrap(raw["fields"] as? [String: Any]), failure: raw["failure"] as? String)
        let plan = try prepare(snapshot([input])), entry = try first(plan)
        XCTAssertEqual(Set(plan.payload.keys), Set(["version", "source", "displayTimeZone", "tasks", "excluded", "snapshotRevision"]))
        XCTAssertEqual(plan.payload["version"] as? Int, 1)
        XCTAssertEqual(plan.payload["snapshotRevision"] as? String, plan.snapshotRevision)
        XCTAssertEqual(plan.payload["displayTimeZone"] as? String, expected["displayTimeZone"] as? String)
        XCTAssertEqual(try bytes(XCTUnwrap(plan.payload["source"])), try bytes(XCTUnwrap(expected["source"])))
        XCTAssertEqual(Set(entry.keys), Set(["identity", "revision", "identifier", "title", "task", "nativeRecord", "notices"]))
        XCTAssertEqual(entry["identity"] as? String, expected["expectedIdentity"] as? String)
        XCTAssertEqual(try bytes(XCTUnwrap(entry["task"])), try bytes(XCTUnwrap(expected["expectedTask"])))
        XCTAssertEqual(try bytes(XCTUnwrap(entry["nativeRecord"])), try bytes(raw))
        XCTAssertEqual(entry["notices"] as? [String], expected["expectedNotices"] as? [String])
        XCTAssertTrue(try excluded(plan).isEmpty)
        XCTAssertNoThrow(try plan.revalidate(snapshot([input])))
    }

    func testNoNativeIdentityTimeOrHierarchyBecomesLocalSyncAuthority() throws {
        let draft = try task(record())
        XCTAssertEqual(Set(draft.keys), Set(["titel", "notiz", "prio", "erledigt", "startDatum", "startZeit", "faellig", "faelligZeit",
            "icsRoundtrip", "icsAnzeigeZeitzone", "erinnern", "individuelleErinnerungTage", "vorlaufTage", "erinnerungsMinute"]))
        for key in ["id", "uid", "angelegt", "geaendert", "personalGeaendert", "sync", "syncQuellen", "icsQuelleId", "elternUid", "icsElternUid"] {
            XCTAssertNil(draft[key], key)
        }
        XCTAssertEqual(draft["erinnern"] as? Bool, false)
        XCTAssertEqual(draft["individuelleErinnerungTage"] as? Int, 0)
        XCTAssertEqual(draft["vorlaufTage"] as? Int, 0)
        XCTAssertEqual(draft["erinnerungsMinute"] as? Int, 480)
        XCTAssertEqual(draft["icsRoundtrip"] as? [String], [])
        let entry = try first(prepare(snapshot([record()])))
        let raw = try XCTUnwrap((entry["nativeRecord"] as? [String: Any])?["fields"] as? [String: Any])
        XCTAssertEqual(raw["hierarchyAvailable"] as? Bool, false)
        XCTAssertTrue((entry["notices"] as? [String] ?? []).contains("native-reminder-standalone-copy"))
        XCTAssertTrue((raw["metadataIncomplete"] as? [String] ?? []).contains("native-reminder-attachments"))
    }

    func testAllNativePriorityValuesUseAnnouncedLocalBucketsWithoutLiveRawPriority() throws {
        let expected = [2, 1, 1, 1, 2, 2, 2, 3, 3, 3]
        for priority in 0...9 {
            let entry = try first(prepare(snapshot([record(changes: ["priority": priority])])) )
            let draft = try XCTUnwrap(entry["task"] as? [String: Any])
            XCTAssertEqual(draft["prio"] as? Int, expected[priority])
            XCTAssertFalse((draft["icsRoundtrip"] as? [String] ?? []).contains { $0.hasPrefix("PRIORITY:") })
            XCTAssertEqual(((entry["nativeRecord"] as? [String: Any])?["fields"] as? [String: Any])?["priority"] as? Int, priority)
            XCTAssertTrue((entry["notices"] as? [String] ?? []).contains("native-reminder-priority-grouped"))
        }
        let invalid: [Any] = [-1, 10, true, 2.5]
        for priority in invalid {
            try assertExcluded(record(changes: ["priority": priority]), "native-reminder-field-unavailable")
        }
    }

    func testNativeTimestampsRemainExactRawAndDoNotBecomeCopyTimestamps() throws {
        let input = record(changes: ["created": -1.125, "modified": 0, "completed": true, "completionDate": 1_780_000_500.25])
        let entry = try first(prepare(snapshot([input]))), draft = try XCTUnwrap(entry["task"] as? [String: Any])
        let raw = try XCTUnwrap((entry["nativeRecord"] as? [String: Any])?["fields"] as? [String: Any])
        for key in ["created", "modified", "completionDate"] { XCTAssertEqual(try bytes(XCTUnwrap(raw[key])), try bytes(XCTUnwrap(input.fields[key]))) }
        for key in ["angelegt", "geaendert", "personalGeaendert", "completionDate"] { XCTAssertNil(draft[key]) }
        XCTAssertFalse((draft["icsRoundtrip"] as? [String] ?? []).contains { $0.hasPrefix("CREATED:") || $0.hasPrefix("COMPLETED:") || $0.hasPrefix("LAST-MODIFIED:") })
        XCTAssertTrue((entry["notices"] as? [String] ?? []).contains("native-reminder-source-timestamps"))
    }

    func testCompletedReminderWithNoCompletionDateIsValidWithoutInventingOne() throws {
        let input = record(changes: ["completed": true, "completionDate": NSNull(), "created": NSNull(), "modified": NSNull()])
        let entry = try first(prepare(snapshot([input]))), draft = try XCTUnwrap(entry["task"] as? [String: Any])
        XCTAssertEqual(draft["erledigt"] as? Bool, true)
        XCTAssertTrue(((entry["nativeRecord"] as? [String: Any])?["fields"] as? [String: Any])?["completionDate"] is NSNull)
        XCTAssertFalse((entry["notices"] as? [String] ?? []).contains("native-reminder-source-timestamps"))
        try assertExcluded(record(changes: ["completed": false, "completionDate": 1_780_000_500]), "native-reminder-completion-state-inconsistent")
    }

    func testUndatedAndDateOnlyTasksKeepAbsenceInsteadOfMidnight() throws {
        let absent = try task(record())
        for key in ["startDatum", "startZeit", "faellig", "faelligZeit"] { XCTAssertEqual(absent[key] as? String, "") }
        let due = record(changes: ["dueComponents": date(["timeZone": "Pacific/Auckland"])])
        for zone in ["UTC", "America/New_York", "Pacific/Auckland"] {
            let draft = try task(due, zone: zone)
            XCTAssertEqual(draft["faellig"] as? String, "2026-11-27")
            XCTAssertEqual(draft["faelligZeit"] as? String, "")
            XCTAssertEqual(draft["startDatum"] as? String, "")
            XCTAssertEqual(draft["icsRoundtrip"] as? [String], ["DUE;VALUE=DATE:20261127"])
        }
        let startOnly = try task(record(changes: ["startComponents": date()]))
        XCTAssertEqual(startOnly["startDatum"] as? String, "2026-11-27")
        XCTAssertEqual(startOnly["startZeit"] as? String, "")
        XCTAssertEqual(startOnly["faellig"] as? String, "")
    }

    func testFloatingDueIgnoresCalendarAndItemTimeZonesAndPreservesClockAcrossDisplayZones() throws {
        let due = clock(["calendarTimeZone": "Pacific/Auckland"])
        let input = record(changes: ["dueComponents": due, "itemTimeZone": "America/New_York"])
        for zone in ["UTC", "Europe/Berlin", "America/New_York"] {
            let draft = try task(input, zone: zone)
            XCTAssertEqual(draft["faellig"] as? String, "2026-11-27")
            XCTAssertEqual(draft["faelligZeit"] as? String, "09:05")
            XCTAssertEqual(draft["icsRoundtrip"] as? [String], ["DUE:20261127T090500"])
        }
    }

    func testExplicitSourceZonesAreIndependentAndUsePinnedDisplayProjection() throws {
        let start = clock(["timeZone": "Europe/Berlin", "hour": 10, "minute": 0])
        let due = clock(["timeZone": "America/New_York", "hour": 10, "minute": 0])
        let draft = try task(record(changes: ["startComponents": start, "dueComponents": due]), zone: "America/New_York")
        XCTAssertEqual(draft["startDatum"] as? String, "2026-11-27")
        XCTAssertEqual(draft["startZeit"] as? String, "04:00")
        XCTAssertEqual(draft["faelligZeit"] as? String, "10:00")
        XCTAssertEqual(draft["icsRoundtrip"] as? [String], ["DTSTART;TZID=Europe/Berlin:20261127T100000", "DUE;TZID=America/New_York:20261127T100000"])
        let shifted = try task(record(changes: ["dueComponents": clock(["timeZone": "America/New_York", "hour": 23, "minute": 30])]), zone: "UTC")
        XCTAssertEqual(shifted["faellig"] as? String, "2026-11-28")
        XCTAssertEqual(shifted["faelligZeit"] as? String, "04:30")
    }

    func testExplicitSourceZoneGapFoldAndUnknownZoneAreExcludedWithoutGuessing() throws {
        for due in [clock(["year": 2026, "month": 3, "day": 29, "hour": 2, "minute": 30, "timeZone": "Europe/Berlin"]),
                    clock(["year": 2026, "month": 10, "day": 25, "hour": 2, "minute": 30, "timeZone": "Europe/Berlin"]),
                    clock(["timeZone": "Unknown/Place"])] {
            try assertExcluded(record(changes: ["dueComponents": due]), "native-reminder-time-zone-not-representable")
        }
    }

    func testFloatingDSTGapAndFoldRemainUnanchoredCivilTimes() throws {
        for (components, expected) in [(clock(["month": 3, "day": 29, "hour": 2, "minute": 30]), "2026-03-29"),
                                       (clock(["month": 10, "day": 25, "hour": 2, "minute": 30]), "2026-10-25")] {
            let draft = try task(record(changes: ["dueComponents": components]), zone: "Europe/Berlin")
            XCTAssertEqual(draft["faellig"] as? String, expected)
            XCTAssertEqual(draft["faelligZeit"] as? String, "02:30")
            XCTAssertEqual(draft["icsRoundtrip"] as? [String], ["DUE:" + expected.replacingOccurrences(of: "-", with: "") + "T023000"])
        }
    }

    func testSubminuteNativeTimesAndHistoricalSecondOffsetProjectionAreExcluded() throws {
        for due in [clock(["second": 37]), clock(["nanosecond": 1]), clock(["second": false])] {
            try assertExcluded(record(changes: ["dueComponents": due]), "native-reminder-subminute-time-not-supported")
        }
        // The pinned historical Paris offset includes seconds. A minute in its
        // source wall clock would be truncated by the UTC task display.
        let historical = clock(["year": 1890, "month": 1, "day": 1, "timeZone": "Europe/Paris"])
        try assertExcluded(record(changes: ["dueComponents": historical]), "native-reminder-subminute-time-not-supported", zone: "UTC")
        var minutePrecision = clock(); minutePrecision.removeValue(forKey: "second")
        XCTAssertEqual(try task(record(changes: ["dueComponents": minutePrecision]))["faelligZeit"] as? String, "09:05")
    }

    func testPartialInvalidOrNonGregorianDateComponentsAreExcluded() throws {
        var noYear = date(); noYear.removeValue(forKey: "year")
        var noCalendar = date(); noCalendar.removeValue(forKey: "calendar")
        let invalid = [noYear, noCalendar, date(["calendar": "hebrew"]), date(["month": 2, "day": 30]),
                       date(["year": 999]), date(["era": 0]), date(["isLeapMonth": true]), date(["weekday": 2]),
                       date(["hour": 9]), date(["minute": 30]), date(["second": 0]), date(["timeZone": NSNull()]),
                       date(["calendarFirstWeekday": 0]), date(["calendarLocale": true])]
        for due in invalid { try assertExcluded(record(changes: ["dueComponents": due]), "native-reminder-date-components-not-representable") }
        var absent = fields(); absent.removeValue(forKey: "dueComponents")
        try assertExcluded(.init(identifier: "missing-due", fields: absent), "native-reminder-field-unavailable")
    }

    func testLeapDatesAndMinimumSupportedYearRemainCivilDates() throws {
        for (components, expected) in [(date(["year": 1604, "month": 2, "day": 29]), "1604-02-29"),
                                       (date(["year": 2000, "month": 2, "day": 29]), "2000-02-29"),
                                       (date(["year": 1000, "month": 1, "day": 1]), "1000-01-01")] {
            XCTAssertEqual(try task(record(changes: ["dueComponents": components]))["faellig"] as? String, expected)
        }
        try assertExcluded(record(changes: ["dueComponents": date(["year": 1900, "month": 2, "day": 29])]),
                           "native-reminder-date-components-not-representable")
    }

    func testNoneditableIntervalsAreExcludedButDateStartAndTimedDueAreKept() throws {
        let inputs: [[String: Any]] = [["startComponents": clock(), "dueComponents": date()],
            ["startComponents": clock(), "dueComponents": clock()],
            ["startComponents": clock(), "dueComponents": clock(["hour": 8])],
            ["startComponents": date(), "dueComponents": date(["day": 26])]]
        for changes in inputs { try assertExcluded(record(changes: changes), "native-reminder-date-window-not-editable") }
        let mixed = record(changes: ["startComponents": clock(), "dueComponents": clock(["timeZone": "UTC", "hour": 11])])
        try assertExcluded(mixed, "native-reminder-mixed-time-semantics-not-supported")
        let valid = try task(record(changes: ["startComponents": date(), "dueComponents": clock(["hour": 11])]))
        XCTAssertEqual(valid["startDatum"] as? String, "2026-11-27")
        XCTAssertEqual(valid["startZeit"] as? String, "")
        XCTAssertEqual(valid["faelligZeit"] as? String, "11:05")
        let sameDay = try task(record(changes: ["startComponents": date(), "dueComponents": date()]))
        XCTAssertEqual(sameDay["startDatum"] as? String, sameDay["faellig"] as? String)
        let overnight = try task(record(changes: ["startComponents": clock(), "dueComponents": clock(["day": 28])]))
        XCTAssertEqual(overnight["startZeit"] as? String, "09:05")
        XCTAssertEqual(overnight["faelligZeit"] as? String, "09:05")
        XCTAssertEqual(overnight["faellig"] as? String, "2026-11-28")
    }

    func testControlledTimePropertiesRoundtripThroughCanonicalTaskCodecWithoutAlarmsOrForeignUID() throws {
        let draft = try task(record(changes: ["startComponents": clock(["timeZone": "UTC"]),
            "dueComponents": clock(["timeZone": "UTC", "hour": 10]), "priority": 4]))
        var local = draft
        local["id"] = "local-id"; local["uid"] = "independent-local-uid"
        let context = try CalendarTestContext.make(systemIdentifier: "UTC")
        let text = try ICalendarExport.encode([local], context: context, kind: .tasks,
                                             timestamp: Date(timeIntervalSince1970: 1_780_000_000))
        XCTAssertTrue(text.contains("UID:independent-local-uid"))
        XCTAssertFalse(text.contains("magnolie-reminder-projection"))
        XCTAssertFalse(text.contains("reminder-one"))
        XCTAssertFalse(text.contains("BEGIN:VALARM"))
        XCTAssertFalse(text.contains("RELATED-TO"))
        XCTAssertFalse(text.contains("PRIORITY:4"))
        let decoded = try ICalendarImport.decode(Data(text.utf8), context: context, displayTimeZone: "Europe/Berlin")
        let reread = try XCTUnwrap(decoded.tasks.first)
        for key in ["startDatum", "startZeit", "faellig", "faelligZeit", "titel", "notiz"] {
            XCTAssertEqual(reread[key] as? String, draft[key] as? String, key)
        }
        XCTAssertEqual(reread["erinnern"] as? Bool, false)
    }

    func testAlarmsAndRecurrencesAreExcludedEvenWithAnInconsistentFalseFlag() throws {
        let alarm: [String: Any] = ["relativeOffset": -900, "absoluteDate": NSNull(), "type": 0, "proximity": 0,
                                    "soundName": NSNull(), "emailAddress": NSNull()]
        let alarms: [[String: Any]] = [["hasAlarms": true], ["hasAlarms": false, "alarms": [alarm]]]
        for changes in alarms {
            try assertExcluded(record(changes: changes), "native-reminder-alarms-not-supported")
        }
        let rule: [String: Any] = ["frequency": 1, "interval": 1]
        let rules: [[String: Any]] = [["hasRecurrenceRules": true], ["hasRecurrenceRules": false, "recurrenceRules": [rule]]]
        for changes in rules {
            try assertExcluded(record(changes: changes), "native-reminder-recurrence-not-supported")
        }
        try assertExcluded(record(failure: "native-reminder-feature-state-inconsistent"), "native-reminder-read-failed")
    }

    func testCoverageAbsenceAndMissingBooleanStateCannotTurnIntoAnEmptyFeature() throws {
        let unavailable: [[String: Any]] = [["metadataIncomplete": []], ["metadataIncomplete": ["unknown-provider-guarantee"]],
            ["hierarchyAvailable": true], ["hierarchyAvailable": 0], ["hasNotes": NSNull()], ["hasAlarms": 0],
            ["hasRecurrenceRules": NSNull()], ["completed": 1], ["alarms": NSNull()], ["recurrenceRules": NSNull()]]
        for changes in unavailable { try assertExcluded(record(changes: changes), "native-reminder-field-unavailable") }
        var missing = fields(); missing.removeValue(forKey: "hasAlarms")
        try assertExcluded(.init(identifier: "missing-alarm-state", fields: missing), "native-reminder-field-unavailable")
    }

    func testUnavailableNotesAreNotSilentlyReplacedWithEmptyText() throws {
        try assertExcluded(record(changes: ["hasNotes": true, "notes": NSNull()]), "native-reminder-note-state-unavailable")
        try assertExcluded(record(changes: ["hasNotes": false, "notes": "Content"]), "native-reminder-note-state-unavailable")
        XCTAssertEqual(try task(record(changes: ["hasNotes": false, "notes": NSNull()]))["notiz"] as? String, "")
        XCTAssertEqual(try task(record(changes: ["hasNotes": false, "notes": ""]))["notiz"] as? String, "")
        try assertExcluded(record(changes: ["title": NSNull()]), "native-reminder-title-unavailable")
        try assertExcluded(record(changes: ["title": ""]), "native-reminder-title-unavailable")
    }

    func testTextMustSurviveRealEditorWhitespaceAndLineEndingRules() throws {
        for (id, title) in [("leading-space", " Leading"), ("trailing-space", "Trailing "),
                            ("trailing-no-break-space", "Trailing\u{A0}"), ("trailing-bom", "Trailing\u{FEFF}")] {
            try assertExcluded(record(id: id, changes: ["title": title]), "native-reminder-title-would-change")
        }
        for (id, note) in [("crlf", "Line1\r\nLine2"), ("cr", "Line1\rLine2"),
                           ("nul", "Unsafe\u{0}"), ("del", "Unsafe\u{7F}")] {
            try assertExcluded(record(id: id, changes: ["notes": note]), "native-reminder-text-not-representable")
        }
        let literal = "\t First line\nSecond e\u{301} 🌼 <script>literal</script> "
        XCTAssertEqual(Data(try XCTUnwrap(task(record(changes: ["notes": literal]))["notiz"] as? String).utf8), Data(literal.utf8))
        try assertExcluded(record(changes: ["title": "Bad\nTitle"]), "native-reminder-text-not-representable")
    }

    func testLeadingBOMTitleRemainsExcludedAndRevisionBound() throws {
        let title = "\u{FEFF}Leading"
        let input = record(id: "leading-bom", changes: ["title": title])
        XCTAssertEqual(title.unicodeScalars.first?.value, 0xFEFF)
        try assertExcluded(input, "native-reminder-title-would-change")
        let plan = try prepare(snapshot([input])), rejected = try XCTUnwrap(excluded(plan).first)
        XCTAssertEqual(Data(try XCTUnwrap(rejected["title"] as? String).utf8), Data(title.utf8))
        let stripped = snapshot([record(id: "leading-bom", changes: ["title": "Leading"])])
        XCTAssertThrowsError(try plan.revalidate(stripped))
        XCTAssertNotEqual(plan.snapshotRevision, try prepare(stripped).snapshotRevision)
    }

    func testTextLimitsCountUTF8AndNeverTruncateSourceNotes() throws {
        let boundary = String(repeating: "é", count: SystemReminderImport.maximumNoteBytes / 2)
        XCTAssertEqual(Data(try XCTUnwrap(task(record(changes: ["notes": boundary]))["notiz"] as? String).utf8).count, SystemReminderImport.maximumNoteBytes)
        try assertExcluded(record(changes: ["notes": boundary + "x"]), "native-reminder-text-not-representable")
        XCTAssertThrowsError(try prepare(snapshot([record(changes: ["title": String(repeating: "é", count: 2049)])])))
    }

    func testLocationURLAndExternalIdentifiersRemainInertSourceEvidence() throws {
        let changes: [String: Any] = ["location": "Meeting room", "url": "javascript:literal-source-url", "externalIdentifier": "foreign-sync-id"]
        let entry = try first(prepare(snapshot([record(changes: changes)]))), draft = try XCTUnwrap(entry["task"] as? [String: Any])
        XCTAssertEqual(draft["icsRoundtrip"] as? [String], [])
        for key in ["ort", "url", "uid", "icsImportUid"] { XCTAssertNil(draft[key]) }
        let raw = try XCTUnwrap((entry["nativeRecord"] as? [String: Any])?["fields"] as? [String: Any])
        for key in changes.keys { XCTAssertEqual(raw[key] as? String, changes[key] as? String) }
        XCTAssertTrue((entry["notices"] as? [String] ?? []).contains("native-reminder-extra-public-fields-in-source"))
    }

    func testInvalidTimestampsAndUnavailableReadAreVisible() throws {
        let invalid: [[String: Any]] = [["created": true], ["modified": 1e15], ["completionDate": "yesterday"]]
        for changes in invalid {
            try assertExcluded(record(changes: changes), "native-reminder-timestamp-state-unavailable")
        }
        try assertExcluded(.init(identifier: "unreadable", fields: [:], failure: "read-failed"), "native-reminder-read-failed")
        try assertExcluded(record(failure: ""), "native-reminder-read-failed")
    }

    func testOpaqueUnicodeIDsAndOriginalTextAreNeverCanonicallyMerged() throws {
        let composed = "\u{E9}", decomposed = "e\u{301}"
        let one = record(id: composed, changes: ["title": decomposed, "notes": decomposed])
        let two = record(id: decomposed, changes: ["title": composed, "notes": composed])
        let plan = try prepare(snapshot([one, two])), entries = try tasks(plan)
        XCTAssertEqual(entries.count, 2)
        XCTAssertNotEqual(entries[0]["identity"] as? String, entries[1]["identity"] as? String)
        let byID = Dictionary(uniqueKeysWithValues: try entries.map { (Data(try XCTUnwrap($0["identifier"] as? String).utf8), $0) })
        let retained = try XCTUnwrap(byID[Data(composed.utf8)])
        XCTAssertEqual(Data(try XCTUnwrap(retained["title"] as? String).utf8), Data(decomposed.utf8))
        XCTAssertEqual(Data(try XCTUnwrap((retained["task"] as? [String: Any])?["notiz"] as? String).utf8), Data(decomposed.utf8))
        XCTAssertThrowsError(try plan.revalidate(snapshot([record(id: composed, changes: ["title": composed]), two])))
    }

    func testIdentityUsesListAndNativeIDWhileAccountMetadataChangesRevision() throws {
        let original = try first(prepare(snapshot([record()])))
        let renamed = try first(prepare(snapshot([record(changes: ["title": "Renamed task"])], source: source(title: "Renamed list"))))
        XCTAssertEqual(original["identity"] as? String, renamed["identity"] as? String)
        XCTAssertNotEqual(original["revision"] as? String, renamed["revision"] as? String)
        let moved = try first(prepare(snapshot([record()], source: source(id: "different-list"))))
        XCTAssertNotEqual(original["identity"] as? String, moved["identity"] as? String)
        let account = try first(prepare(snapshot([record()], source: source(parent: "different-account"))))
        XCTAssertEqual(original["identity"] as? String, account["identity"] as? String)
        XCTAssertNotEqual(original["revision"] as? String, account["revision"] as? String)
        let left = try first(prepare(snapshot([record()], source: source(id: "\u{E9}"))))
        let right = try first(prepare(snapshot([record()], source: source(id: "e\u{301}"))))
        XCTAssertNotEqual(left["identity"] as? String, right["identity"] as? String)
    }

    func testOrderDoesNotAffectProofButEveryNativeFieldAndSourceChangeDoes() throws {
        let one = record(), two = record(id: "reminder-two"), plan = try prepare(snapshot([one, two]))
        XCTAssertEqual(try bytes(plan.payload), try bytes(prepare(snapshot([two, one])).payload))
        XCTAssertNoThrow(try plan.revalidate(snapshot([two, one])))
        let changes: [[String: Any]] = [["title": "Changed"], ["notes": "Changed"], ["location": "Only raw changed"],
            ["externalIdentifier": "Different provider id"], ["modified": 1_780_000_600.75], ["priority": 3],
            ["completed": true], ["dueComponents": date()], ["metadataIncomplete": []]]
        for change in changes {
            let changed = snapshot([record(changes: change), two])
            XCTAssertThrowsError(try plan.revalidate(changed))
            XCTAssertNotEqual(plan.snapshotRevision, try prepare(changed).snapshotRevision)
        }
        for selected in [source(title: "Changed"), source(parentTitle: "Changed"), source(parentType: "source:1"),
                         source(type: "calendar:1"), source(readOnly: true), source(parent: "changed")] {
            XCTAssertThrowsError(try plan.revalidate(snapshot([one, two], source: selected)))
        }
        XCTAssertThrowsError(try plan.revalidate(snapshot([one])))
        XCTAssertThrowsError(try plan.revalidate(snapshot([one, two, record(id: "third")])))
        XCTAssertThrowsError(try plan.revalidate(snapshot([one, two], source: source(permission: "denied"))))
    }

    func testExcludedRecordsAndReadFailuresRemainPartOfRevalidation() throws {
        let original = record(failure: "failed"), plan = try prepare(snapshot([original]))
        XCTAssertTrue(try tasks(plan).isEmpty)
        for changed in [record(failure: "changed failure"), record(changes: ["notes": "Changed excluded note"], failure: "failed"),
                        record(changes: ["priority": 9], failure: "failed")] {
            XCTAssertThrowsError(try plan.revalidate(snapshot([changed])))
            XCTAssertNotEqual(plan.snapshotRevision, try prepare(snapshot([changed])).snapshotRevision)
        }
    }

    func testCallerOwnedMutableComponentsCannotRewriteAnExistingPlan() throws {
        let due = NSMutableDictionary(dictionary: date()), input = record(changes: ["dueComponents": due])
        let plan = try prepare(snapshot([input])), original = try bytes(plan.payload)
        due["day"] = 28
        XCTAssertEqual(try bytes(plan.payload), original)
        XCTAssertThrowsError(try plan.revalidate(snapshot([input])))
    }

    func testCallerOwnedMutableTextAndArraysCannotRewriteAnExistingPlan() throws {
        let title = NSMutableString(string: "Original title"), notes = NSMutableString(string: "Original note e\u{301} 🌼")
        let coverage = NSMutableArray(array: try XCTUnwrap(fields()["metadataIncomplete"] as? [String]))
        let input = record(changes: ["title": title, "notes": notes, "metadataIncomplete": coverage])
        let plan = try prepare(snapshot([input])), original = try bytes(plan.payload)
        title.append(" changed"); notes.setString("Changed note"); coverage.removeAllObjects()
        XCTAssertEqual(try bytes(plan.payload), original)
        let draft = try XCTUnwrap(first(plan)["task"] as? [String: Any])
        XCTAssertEqual(draft["titel"] as? String, "Original title")
        XCTAssertEqual(Data(try XCTUnwrap(draft["notiz"] as? String).utf8), Data("Original note e\u{301} 🌼".utf8))
        XCTAssertThrowsError(try plan.revalidate(snapshot([input])))
    }

    func testIdentitySelectionSourceAndUnknownFieldFailuresAbortWithoutPartialPlan() throws {
        for inputs in [[record(id: "")], [record(), record()], [record(id: String(repeating: "é", count: 8193))]] {
            XCTAssertThrowsError(try prepare(snapshot(inputs)))
        }
        for selected in [source(id: ""), source(parent: ""), source(permission: "write_only"), source(type: "birthday"),
                         source(parentType: "not-a-source"), source(title: "Unsafe\u{0}")] {
            XCTAssertThrowsError(try prepare(snapshot([record()], source: selected)))
        }
        let wrong = SystemReminderImport.Source(sourceUID: source().sourceUID, calendarID: "wrong-list", title: "Title",
            parentUID: source().parentUID, parentTitle: "Parent", parentType: "source:2", nativeType: "calendar:2", readOnly: false, permission: "authorized")
        XCTAssertThrowsError(try prepare(snapshot([record()], source: wrong)))
        XCTAssertThrowsError(try prepare(snapshot([record(changes: ["privateSubtasks": []])])) )
        XCTAssertThrowsError(try prepare(snapshot([record(changes: ["modified": Double.nan])])) )
    }

    func testSelectionAndRecursiveMetadataLimitsAbortWithoutReturningPrefix() throws {
        XCTAssertEqual(try tasks(prepare(snapshot((0..<100).map { record(id: "id-\($0)") }))).count, 100)
        XCTAssertThrowsError(try prepare(snapshot((0..<101).map { record(id: "id-\($0)") })))
        XCTAssertThrowsError(try prepare(snapshot([record(changes: ["metadataIncomplete": Array(repeating: "native-reminder-hierarchy", count: 1001)])])) )
    }

    func testFinalTransportLimitCountsRawAndProjectedTextAndJSONEscaping() throws {
        let text = String(repeating: "\\", count: SystemReminderImport.maximumNoteBytes)
        XCTAssertThrowsError(try prepare(snapshot((0..<5).map { record(id: "item-\($0)", changes: ["notes": text]) }))) { error in
            XCTAssertTrue(error.localizedDescription.contains("proposal exceeds 16 MiB"))
        }
        XCTAssertThrowsError(try prepare(snapshot((0..<9).map { record(id: "item-\($0)", changes: ["notes": text]) }))) { error in
            XCTAssertTrue(error.localizedDescription.contains("snapshot evidence exceeds 16 MiB"))
        }
    }

    func testNativeSelectionCommandIsParameterlessAndCannotInjectSourceOrAuthorization() throws {
        XCTAssertEqual(try Request("{\"cmd\":\"macos_erinnerungen_importieren\"}").command, .macos_erinnerungen_importieren)
        let extras: [[String: Any]] = [["sourceUID": source().sourceUID], ["calendarID": "injected"], ["identifiers": ["reminder-one"]],
            ["authorized": true], ["fields": ["completed": true]], ["script": "write-source"], ["sync": true], ["parent": "invented"]]
        for extra in extras {
            var input = extra; input["cmd"] = "macos_erinnerungen_importieren"
            XCTAssertThrowsError(try Request(Document.encode(input)))
        }
    }
}
