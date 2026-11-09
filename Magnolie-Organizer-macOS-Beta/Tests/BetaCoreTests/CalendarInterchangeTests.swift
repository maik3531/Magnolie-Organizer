import Foundation
import XCTest
@testable import BetaCore

final class CalendarInterchangeTests: XCTestCase {
    func testStructuredSeriesAndExcludedDaysRemainARecurrence() throws {
        let record: [String: Any] = ["uid": "weekly", "titel": "Weekly", "datum": "2026-03-23", "zeit": "",
            "wiederholung": ["art": "weekly", "bis": "2026-04-30", "intervall": 2], "icsAusnahmen": ["2026-04-06"]]
        let text = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments)
        XCTAssertTrue(text.contains("RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20260430\r\n"))
        XCTAssertTrue(text.contains("EXDATE;VALUE=DATE:20260406\r\n"))
        XCTAssertEqual(text.components(separatedBy: "BEGIN:VEVENT").count - 1, 1, "Do not flatten a series into occurrences")
        XCTAssertTrue(text.contains("DTEND;VALUE=DATE:20260324\r\n"))
    }

    func testPublishedNormalizedImportedAlarmPreservesRawAndRejectsEdits() throws {
        // Actual projected shared-JS normalizer output. Relevant functions are
        // byte-identical to published v2.0.30 (067c3893): normalisiereTermine,
        // icsProjektion, saubereAlarme, icsRelativeMinuten and terminHash.
        let record = try Document.object(#"{"id":"alarm-fixture","uid":"alarm-fixture","titel":"Imported alarm","datum":"2026-03-28","zeit":"10:00","endZeit":"11:00","icsAnzeigeZeitzone":"UTC","icsRoundtrip":["DTSTART:20260328T100000Z","DTEND:20260328T110000Z","BEGIN:VALARM","ACTION:DISPLAY","TRIGGER:-PT15M","DESCRIPTION:Original","END:VALARM"],"endDatum":"","notiz":"","kategorien":"","akzentFarbe":"","vertraulich":false,"vorlaeufig":false,"kostenstelle":"","kunde":"","ort":"","alarme":[{"id":"ics-alarm-0-15temj4","offsetMinuten":15,"aktion":"display","aktiviert":true,"quelle":"ics","triggerRaw":"-PT15M","related":"START","bearbeitbar":true}],"kalenderQuelle":{"id":"","name":"","gruppe":"","farbe":"","anbieter":""},"organisator":{"uri":"","name":"","email":""},"teilnehmer":[],"kalenderAnhaenge":[],"providerMetadaten":{},"individuelleErinnerungTage":0,"standardErinnerung":true,"wiederholung":{"art":"none","bis":""},"icsKomplex":false,"icsSerienUid":"","icsAusnahmen":[],"icsZusatzDaten":[],"icsZusatzTermine":[],"icsRangeOverrides":[],"icsAusnahmeTermine":[],"icsTimezones":[],"icsSequence":0,"icsAenderungszeitFehlt":false,"icsEndeFehlt":false,"icsNullDauer":false,"syncKonflikte":[],"icsReadOnly":false,"icsReadOnlyGrund":"","icsQuelleName":"","icsQuelleId":"","aufgaben":[],"kontaktId":"","syncKalenderUid":"","geaendert":0,"sync":false,"syncQuellen":{}}"#)
        let source = try XCTUnwrap(record["icsRoundtrip"] as? [String])
        XCTAssertNotNil(record["kalenderQuelle"] as? [String: Any])
        let exported = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments)
        for line in source { XCTAssertTrue(exported.contains(line + "\r\n"), line) }
        let alarms = try XCTUnwrap(record["alarme"] as? [[String: Any]])
        XCTAssertEqual(alarms.first?["offsetMinuten"] as? Int, 15)
        for mutation in ["offset", "disabled", "action", "missingRaw", "newAlarm", "malformed"] {
            var changed = record, edited = alarms
            switch mutation {
            case "offset": edited[0]["offsetMinuten"] = 30
            case "disabled": edited[0]["aktiviert"] = false
            case "action": edited[0]["aktion"] = "audio"
            case "missingRaw": changed["icsRoundtrip"] = Array(source.prefix(2))
            case "newAlarm": edited.append(edited[0])
            default: edited[0]["bearbeitbar"] = 1
            }
            changed["alarme"] = edited
            XCTAssertThrowsError(try ICalendarExport.encode([changed], context: try CalendarTestContext.make(), kind: .appointments), mutation)
        }
    }

    func testActualPublishedAlarmUIEditAndRemovalGoldens() throws {
        // Saved envelopes from the actual v2.0.30 editor (067c3893): untouched,
        // real .tb-alarm-zahl 15→30 edit, and actual Remove button + Save.
        let json = #"[{"web":"/workspace/scratch/port-release-validation/magnolie-organizer/web","mode":"untouched","record":{"datum":"2026-11-15","endDatum":"","icsAnzeigeZeitzone":"UTC","icsNullDauer":false,"notiz":"","icsSequence":0,"akzentFarbe":"","icsQuelleName":"Synthetic native calendar","icsKomplex":false,"icsQuelleId":"ics:960b687ab7ac82df4c2c933f2fa197d023346dd8f6d0c2b2dd9f37bc9d2d3873","uid":"normalized-valarm-event","titel":"Synthetic alarm fixture","kostenstelle":"","icsZusatzTermine":[],"kategorien":"","wiederholung":{"art":"none","bis":""},"icsAenderungszeitFehlt":true,"kunde":"","vertraulich":false,"icsRoundtrip":["DTSTART:20261115T090000Z","DTEND:20261115T100000Z","BEGIN:VALARM","ACTION:DISPLAY","TRIGGER:-PT15M","DESCRIPTION:Synthetic reminder","END:VALARM","BEGIN:VALARM","ACTION:AUDIO","TRIGGER;VALUE=DATE-TIME:20261115T083000Z","END:VALARM"],"individuelleErinnerungTage":0,"endZeit":"10:00","standardErinnerung":true,"icsSerienUid":"","zeit":"09:00","icsZusatzDaten":[],"vorlaeufig":false,"icsEndeFehlt":false,"ort":"","alarme":[{"id":"ics-alarm-0-c6mluk","offsetMinuten":15,"aktion":"display","aktiviert":true,"quelle":"ics","triggerRaw":"-PT15M","related":"START","bearbeitbar":true},{"id":"ics-alarm-1-108tzdj","offsetMinuten":0,"aktion":"audio","aktiviert":true,"quelle":"ics","triggerRaw":"20261115T083000Z","related":"START","bearbeitbar":false}],"kalenderQuelle":{"id":"ics:960b687ab7ac82df4c2c933f2fa197d023346dd8f6d0c2b2dd9f37bc9d2d3873","name":"Synthetic native calendar","gruppe":"","farbe":"","anbieter":"ICS"},"organisator":{"uri":"","name":"","email":""},"teilnehmer":[],"kalenderAnhaenge":[],"providerMetadaten":{},"icsAusnahmen":[],"icsRangeOverrides":[],"icsAusnahmeTermine":[],"icsTimezones":[],"syncKonflikte":[],"icsReadOnly":false,"icsReadOnlyGrund":"","aufgaben":[],"kontaktId":"","syncKalenderUid":"","sync":false,"syncQuellen":{},"id":"mw83at98f7hqji","geaendert":0},"errors":[]},{"web":"/workspace/scratch/port-release-validation/magnolie-organizer/web","mode":"edit30","record":{"datum":"2026-11-15","endDatum":"","icsAnzeigeZeitzone":"UTC","icsNullDauer":false,"notiz":"","icsSequence":0,"akzentFarbe":"","icsQuelleName":"Synthetic native calendar","icsKomplex":false,"icsQuelleId":"ics:960b687ab7ac82df4c2c933f2fa197d023346dd8f6d0c2b2dd9f37bc9d2d3873","uid":"normalized-valarm-event","titel":"Synthetic alarm fixture","kostenstelle":"","icsZusatzTermine":[],"kategorien":"","wiederholung":{"art":"none","bis":""},"icsAenderungszeitFehlt":true,"kunde":"","vertraulich":false,"icsRoundtrip":["DTSTART:20261115T090000Z","DTEND:20261115T100000Z","BEGIN:VALARM","ACTION:AUDIO","TRIGGER;VALUE=DATE-TIME:20261115T083000Z","END:VALARM","BEGIN:VALARM","TRIGGER;RELATED=START:-PT30M","ACTION:DISPLAY","DESCRIPTION:Synthetic alarm fixture","END:VALARM"],"individuelleErinnerungTage":0,"endZeit":"10:00","standardErinnerung":true,"icsSerienUid":"","zeit":"09:00","icsZusatzDaten":[],"vorlaeufig":false,"icsEndeFehlt":false,"ort":"","alarme":[{"id":"ics-alarm-0-c6mluk","offsetMinuten":30,"aktion":"display","aktiviert":true,"quelle":"ics","triggerRaw":"-PT15M","related":"START","bearbeitbar":true},{"id":"ics-alarm-1-108tzdj","offsetMinuten":0,"aktion":"audio","aktiviert":true,"quelle":"ics","triggerRaw":"20261115T083000Z","related":"START","bearbeitbar":false}],"kalenderQuelle":{"id":"ics:960b687ab7ac82df4c2c933f2fa197d023346dd8f6d0c2b2dd9f37bc9d2d3873","name":"Synthetic native calendar","gruppe":"","farbe":"","anbieter":"ICS"},"organisator":{"uri":"","name":"","email":""},"teilnehmer":[],"kalenderAnhaenge":[],"providerMetadaten":{},"icsAusnahmen":[],"icsRangeOverrides":[],"icsAusnahmeTermine":[],"icsTimezones":[],"syncKonflikte":[],"icsReadOnly":false,"icsReadOnlyGrund":"","aufgaben":[],"kontaktId":"","syncKalenderUid":"","sync":false,"syncQuellen":{},"id":"mw83atb68kt7ec","geaendert":1794157917696},"errors":[]},{"web":"/workspace/scratch/port-release-validation/magnolie-organizer/web","mode":"removeEditable","record":{"datum":"2026-11-15","endDatum":"","icsAnzeigeZeitzone":"UTC","icsNullDauer":false,"notiz":"","icsSequence":0,"akzentFarbe":"","icsQuelleName":"Synthetic native calendar","icsKomplex":false,"icsQuelleId":"ics:960b687ab7ac82df4c2c933f2fa197d023346dd8f6d0c2b2dd9f37bc9d2d3873","uid":"normalized-valarm-event","titel":"Synthetic alarm fixture","kostenstelle":"","icsZusatzTermine":[],"kategorien":"","wiederholung":{"art":"none","bis":""},"icsAenderungszeitFehlt":true,"kunde":"","vertraulich":false,"icsRoundtrip":["DTSTART:20261115T090000Z","DTEND:20261115T100000Z","BEGIN:VALARM","ACTION:AUDIO","TRIGGER;VALUE=DATE-TIME:20261115T083000Z","END:VALARM"],"individuelleErinnerungTage":0,"endZeit":"10:00","standardErinnerung":true,"icsSerienUid":"","zeit":"09:00","icsZusatzDaten":[],"vorlaeufig":false,"icsEndeFehlt":false,"ort":"","alarme":[{"id":"ics-alarm-1-108tzdj","offsetMinuten":0,"aktion":"audio","aktiviert":true,"quelle":"ics","triggerRaw":"20261115T083000Z","related":"START","bearbeitbar":false}],"kalenderQuelle":{"id":"ics:960b687ab7ac82df4c2c933f2fa197d023346dd8f6d0c2b2dd9f37bc9d2d3873","name":"Synthetic native calendar","gruppe":"","farbe":"","anbieter":"ICS"},"organisator":{"uri":"","name":"","email":""},"teilnehmer":[],"kalenderAnhaenge":[],"providerMetadaten":{},"icsAusnahmen":[],"icsRangeOverrides":[],"icsAusnahmeTermine":[],"icsTimezones":[],"syncKonflikte":[],"icsReadOnly":false,"icsReadOnlyGrund":"","aufgaben":[],"kontaktId":"","syncKalenderUid":"","sync":false,"syncQuellen":{},"id":"mw83atdgzml01y","geaendert":1794157917772},"errors":[]}]"#
        let cases = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [[String: Any]])
        XCTAssertEqual(cases.count, 3)
        for fixture in cases {
            let record = try XCTUnwrap(fixture["record"] as? [String: Any])
            let exported = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments)
            for line in try XCTUnwrap(record["icsRoundtrip"] as? [String]) {
                XCTAssertTrue(exported.contains(line + "\r\n"), line)
            }
            XCTAssertTrue(exported.contains("ACTION:AUDIO"))
            if fixture["mode"] as? String == "edit30" { XCTAssertTrue(exported.contains("TRIGGER;RELATED=START:-PT30M")) }
        }
    }

    func testActualNormalizerMultipleDuplicateEmojiAndOpaqueAlarmGoldens() throws {
        // Actual normalizer output using functions byte-identical to v2.0.30.
        let json = #"[{"name":"multiple-duplicate-emoji","record":{"id":"multiple-duplicate-emoji","uid":"multiple-duplicate-emoji","titel":"multiple-duplicate-emoji","datum":"2026-03-28","zeit":"10:00","endZeit":"11:00","icsAnzeigeZeitzone":"UTC","icsRoundtrip":["DTSTART:20260328T100000Z","DTEND:20260328T110000Z","BEGIN:VALARM","ACTION:DISPLAY","TRIGGER:-PT15M","DESCRIPTION:Emoji 🌼","END:VALARM","BEGIN:VALARM","ACTION:DISPLAY","TRIGGER:-PT15M","DESCRIPTION:Duplicate 🌼","END:VALARM","BEGIN:VALARM","ACTION:DISPLAY","TRIGGER;RELATED=END:-PT30M","END:VALARM"],"endDatum":"","notiz":"","kategorien":"","akzentFarbe":"","vertraulich":false,"vorlaeufig":false,"kostenstelle":"","kunde":"","ort":"","alarme":[{"id":"ics-alarm-0-xqapip","offsetMinuten":15,"aktion":"display","aktiviert":true,"quelle":"ics","triggerRaw":"-PT15M","related":"START","bearbeitbar":true},{"id":"ics-alarm-2-tou0hg","offsetMinuten":30,"aktion":"display","aktiviert":true,"quelle":"ics","triggerRaw":"-PT30M","related":"END","bearbeitbar":true}],"kalenderQuelle":{"id":"","name":"","gruppe":"","farbe":"","anbieter":""},"organisator":{"uri":"","name":"","email":""},"teilnehmer":[],"kalenderAnhaenge":[],"providerMetadaten":{},"individuelleErinnerungTage":0,"standardErinnerung":true,"wiederholung":{"art":"none","bis":""},"icsKomplex":false,"icsSerienUid":"","icsAusnahmen":[],"icsZusatzDaten":[],"icsZusatzTermine":[],"icsRangeOverrides":[],"icsAusnahmeTermine":[],"icsTimezones":[],"icsSequence":0,"icsAenderungszeitFehlt":false,"icsEndeFehlt":false,"icsNullDauer":false,"syncKonflikte":[],"icsReadOnly":false,"icsReadOnlyGrund":"","icsQuelleName":"","icsQuelleId":"","aufgaben":[],"kontaktId":"","syncKalenderUid":"","geaendert":0,"sync":false,"syncQuellen":{}}},{"name":"absolute-audio","record":{"id":"absolute-audio","uid":"absolute-audio","titel":"absolute-audio","datum":"2026-03-28","zeit":"10:00","endZeit":"11:00","icsAnzeigeZeitzone":"UTC","icsRoundtrip":["DTSTART:20260328T100000Z","DTEND:20260328T110000Z","BEGIN:VALARM","ACTION:AUDIO","TRIGGER;VALUE=DATE-TIME:20260328T090000Z","DESCRIPTION:Audio 🌼","END:VALARM"],"endDatum":"","notiz":"","kategorien":"","akzentFarbe":"","vertraulich":false,"vorlaeufig":false,"kostenstelle":"","kunde":"","ort":"","alarme":[{"id":"ics-alarm-0-1v6t6fe","offsetMinuten":0,"aktion":"audio","aktiviert":true,"quelle":"ics","triggerRaw":"20260328T090000Z","related":"START","bearbeitbar":false}],"kalenderQuelle":{"id":"","name":"","gruppe":"","farbe":"","anbieter":""},"organisator":{"uri":"","name":"","email":""},"teilnehmer":[],"kalenderAnhaenge":[],"providerMetadaten":{},"individuelleErinnerungTage":0,"standardErinnerung":true,"wiederholung":{"art":"none","bis":""},"icsKomplex":false,"icsSerienUid":"","icsAusnahmen":[],"icsZusatzDaten":[],"icsZusatzTermine":[],"icsRangeOverrides":[],"icsAusnahmeTermine":[],"icsTimezones":[],"icsSequence":0,"icsAenderungszeitFehlt":false,"icsEndeFehlt":false,"icsNullDauer":false,"syncKonflikte":[],"icsReadOnly":false,"icsReadOnlyGrund":"","icsQuelleName":"","icsQuelleId":"","aufgaben":[],"kontaktId":"","syncKalenderUid":"","geaendert":0,"sync":false,"syncQuellen":{}}}]"#
        let cases = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [[String: Any]])
        for fixture in cases {
            let record = try XCTUnwrap(fixture["record"] as? [String: Any])
            let exported = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments)
            let raw = try XCTUnwrap(record["icsRoundtrip"] as? [String])
            for line in raw { XCTAssertTrue(exported.contains(line + "\r\n"), line) }
            let alarms = try XCTUnwrap(record["alarme"] as? [[String: Any]])
            XCTAssertEqual(alarms.count, fixture["name"] as? String == "absolute-audio" ? 1 : 2)
            if fixture["name"] as? String == "absolute-audio" {
                var changed = record, edited = alarms
                edited[0]["triggerRaw"] = "20260328T080000Z"
                changed["alarme"] = edited
                XCTAssertThrowsError(try ICalendarExport.encode([changed], context: try CalendarTestContext.make(), kind: .appointments))
                // A negative mutation of the actual normalizer golden: retain
                // the raw read-only alarm but contradict only its opaque TZID.
                let nfc = "Custom/caf\u{e9}", nfd = "Custom/cafe\u{301}"
                var zoned = record, projected = alarms
                zoned["icsRoundtrip"] = raw.map { $0.hasPrefix("TRIGGER;") ? "TRIGGER;VALUE=DATE-TIME;TZID=" + nfc + ":20260328T090000" : $0 }
                zoned["icsTimezones"] = [(nfc, "+0000"), (nfd, "+0100")].map { name, offset in
                    ["BEGIN:VTIMEZONE", "TZID:" + name, "BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:" + offset, "TZOFFSETTO:" + offset, "END:STANDARD", "END:VTIMEZONE"]
                }
                projected[0]["triggerRaw"] = "20260328T090000"
                projected[0]["triggerTzid"] = nfc; zoned["alarme"] = projected
                XCTAssertTrue(try ICalendarExport.encode([zoned], context: try CalendarTestContext.make(), kind: .appointments).contains("TRIGGER;VALUE=DATE-TIME;TZID=" + nfc + ":20260328T090000\r\n"))
                projected[0]["triggerTzid"] = nfd; zoned["alarme"] = projected
                XCTAssertThrowsError(try ICalendarExport.encode([zoned], context: try CalendarTestContext.make(), kind: .appointments))
            }
        }
    }

    func testGeneratedSystemClockIsBoundButRawFloatingSourceStaysFloating() throws {
        // Actual new system-zone UI record has no icsAnzeigeZeitzone and an
        // empty icsRoundtrip; native export must bind its generated clocks.
        let record: [String: Any] = ["uid": "new-system", "titel": "New", "datum": "2026-01-15", "zeit": "10:00", "endZeit": "11:00", "icsRoundtrip": [String]()]
        let identifier = TimeZone.current.identifier
        let utc = ["UTC", "GMT", "Etc/UTC", "Etc/GMT"].contains(identifier)
        let generated = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments, defaultTimeZone: "system")
        let expected = utc ? "DTSTART:20260115T100000Z" : "DTSTART;TZID=" + identifier + ":20260115T100000"
        XCTAssertTrue(generated.contains(expected + "\r\n"))
        var floating = record
        floating["icsRoundtrip"] = ["DTSTART:20260115T100000", "DTEND:20260115T110000"]
        let preserved = try ICalendarExport.encode([floating], context: try CalendarTestContext.make(), kind: .appointments, defaultTimeZone: "system")
        XCTAssertTrue(preserved.contains("DTSTART:20260115T100000\r\n"))
        XCTAssertTrue(preserved.contains("DTEND:20260115T110000\r\n"))
        for (date, expectedUTC) in [("2026-01-15", "09:00"), ("2026-07-15", "08:00")] {
            var season = record
            season["datum"] = date
            let encoded = try ICalendarExport.encode([season], context: try CalendarTestContext.make(), kind: .appointments, defaultTimeZone: "Europe/Berlin")
            XCTAssertTrue(encoded.contains("DTSTART;TZID=Europe/Berlin:" + date.replacingOccurrences(of: "-", with: "") + "T100000"))
            let imported = try ICalendarImport.decode(Data(encoded.utf8), context: try CalendarTestContext.make(), displayTimeZone: "UTC")
            XCTAssertEqual(imported.appointments.first?["zeit"] as? String, expectedUTC)
        }
        var explicit = record
        explicit["icsAnzeigeZeitzone"] = "UTC"
        XCTAssertTrue(try ICalendarExport.encode([explicit], context: try CalendarTestContext.make(), kind: .appointments, defaultTimeZone: "Europe/Berlin").contains("DTSTART:20260115T100000Z"))
    }

    func testDueOnlyTaskCannotSilentlyDiscardStructuredRecurrence() throws {
        let dueOnly: [String: Any] = ["uid": "due-task", "titel": "Task", "faellig": "2026-04-01", "wiederholung": ["art": "daily"]]
        XCTAssertThrowsError(try ICalendarExport.encode([dueOnly], context: try CalendarTestContext.make(), kind: .tasks))
        var noRepeat = dueOnly
        noRepeat["wiederholung"] = ["art": "none"]
        let oneOff = try ICalendarExport.encode([noRepeat], context: try CalendarTestContext.make(), kind: .tasks)
        XCTAssertTrue(oneOff.contains("DUE;VALUE=DATE:20260401"))
        XCTAssertFalse(oneOff.contains("RRULE:"))
        var recurring = dueOnly
        recurring["startDatum"] = "2026-03-31"
        let repeated = try ICalendarExport.encode([recurring], context: try CalendarTestContext.make(), kind: .tasks)
        XCTAssertTrue(repeated.contains("DTSTART;VALUE=DATE:20260331"))
        XCTAssertTrue(repeated.contains("RRULE:FREQ=DAILY"))
        for malformed in ["daily", ["art": 7], ["art": "none", "unknown": "field"], ["art": "none", "intervall": 2]] as [Any] {
            var invalid = dueOnly
            invalid["wiederholung"] = malformed
            XCTAssertThrowsError(try ICalendarExport.encode([invalid], context: try CalendarTestContext.make(), kind: .tasks))
        }
    }

    func testSubtaskExternalIdentityAndCompletionArePreserved() throws {
        let parent: [String: Any] = ["uid": "internal-parent", "icsImportUid": "external-parent", "titel": "Parent", "prio": 1]
        let child: [String: Any] = ["uid": "child", "titel": "Child", "elternUid": "internal-parent", "faellig": "2026-04-01",
                                    "prio": 3, "erledigt": true, "erinnern": true, "individuelleErinnerungTage": 3]
        let text = try ICalendarExport.encode([parent, child], context: try CalendarTestContext.make(), kind: .tasks)
        XCTAssertTrue(text.contains("UID:external-parent\r\n"))
        XCTAssertTrue(text.contains("RELATED-TO;RELTYPE=PARENT:external-parent\r\n"))
        XCTAssertTrue(text.contains("BEGIN:VTODO\r\n"))
        XCTAssertTrue(text.contains("DUE;VALUE=DATE:20260401\r\n"))
        XCTAssertTrue(text.contains("STATUS:COMPLETED\r\nPERCENT-COMPLETE:100\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-ERINNERUNG-AM-TAG:1\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-TASK-IDENTITY:"))
    }

    func testYearlessLeapAnniversaryHasAnExplicitDateExtension() throws {
        let record: [String: Any] = ["uid": "yearless", "name": "Leap birthday", "datum": "--02-29", "typ": "birthday"]
        let text = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .anniversaries)
        XCTAssertTrue(text.contains("DTSTART;VALUE=DATE:20000229\r\n"))
        XCTAssertTrue(text.contains("RRULE:FREQ=YEARLY\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-DATE:--02-29\r\n"))
        XCTAssertTrue(text.contains("X-MAGNOLIE-JAHRESTAG-TYP:birthday\r\n"))
        var invalid = record; invalid["datum"] = "--02-30"
        XCTAssertThrowsError(try ICalendarExport.encode([invalid], context: try CalendarTestContext.make(), kind: .anniversaries))
    }

    func testRawClocksAndUnknownSourcePropertiesStayAuthoritative() throws {
        let record: [String: Any] = ["uid": "master", "icsSerienUid": "source-series", "titel": "Serie", "datum": "2026-03-28",
            "zeit": "09:00", "endZeit": "10:00", "icsAnzeigeZeitzone": "UTC", "wiederholung": ["art": "none", "bis": ""],
            "icsRoundtrip": ["DTSTART;TZID=Europe/Berlin:20260328T100000", "DTEND;TZID=Europe/Berlin:20260328T110000",
                             "RRULE:FREQ=DAILY;COUNT=4", "RDATE;TZID=Europe/Berlin:20260402T100000", "EXDATE;TZID=Europe/Berlin:20260330T100000",
                             "X-EXAMPLE-META;X-TOKEN=alpha:opaque-value", "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", "END:VALARM"]]
        let text = try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments)
        for line in record["icsRoundtrip"] as! [String] { XCTAssertTrue(text.contains(line + "\r\n"), line) }
        XCTAssertTrue(text.contains("UID:source-series\r\n"))
        XCTAssertTrue(text.contains("BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\n"))
        var stale = record; stale["zeit"] = "10:00"
        XCTAssertThrowsError(try ICalendarExport.encode([stale], context: try CalendarTestContext.make(), kind: .appointments))
        var loss = record; loss["unrecognizedProviderState"] = ["keep": true]
        XCTAssertThrowsError(try ICalendarExport.encode([loss], context: try CalendarTestContext.make(), kind: .appointments))
        var injection = record; injection["icsRoundtrip"] = ["SUMMARY:Safe\r\nBEGIN:VEVENT"]
        XCTAssertThrowsError(try ICalendarExport.encode([injection], context: try CalendarTestContext.make(), kind: .appointments))
    }

    func testInvalidRulesAndDSTGapsAreRefused() throws {
        let record: [String: Any] = ["uid": "gap", "titel": "Gap", "datum": "2026-03-29", "zeit": "02:30", "endZeit": "03:30",
                                    "icsAnzeigeZeitzone": "Europe/Berlin", "wiederholung": ["art": "daily", "bis": ""]]
        XCTAssertThrowsError(try ICalendarExport.encode([record], context: try CalendarTestContext.make(), kind: .appointments))
        var floating: [String: Any] = ["uid": "rule", "titel": "Rule", "datum": "2026-03-28", "zeit": "10:00", "endZeit": "11:00"]
        for rule in ["FREQ=DAILY;COUNT=4;UNTIL=20260430T100000", "FREQ=DAILY;BYHOUR=25", "FREQ=DAILY;COUNT=0", "FREQ=DAILY;BYDAY=0MO", "FREQ=DAILY;FREQ=WEEKLY"] {
            floating["icsRoundtrip"] = ["RRULE:" + rule]
            XCTAssertThrowsError(try ICalendarExport.encode([floating], context: try CalendarTestContext.make(), kind: .appointments), rule)
        }
    }

    func testLiveCanonicalCalendarRecordsAndWriteIndependentOracleInputs() throws {
        guard let fixture = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_FIXTURES"],
              let output = ProcessInfo.processInfo.environment["MACOS_BETA_CALENDAR_OUTPUT"] else {
            throw XCTSkip("Run tools/check_calendar.py --swift for current desktop codec roundtrips.")
        }
        let bytes = try Data(contentsOf: URL(fileURLWithPath: fixture))
        let cases = try XCTUnwrap(try JSONSerialization.jsonObject(with: bytes) as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(cases.count, 8)
        for item in cases {
            let name = try XCTUnwrap(item["name"] as? String)
            let kind = try XCTUnwrap(ICalendarExport.Kind(rawValue: item["kind"] as? String ?? ""))
            let records = try XCTUnwrap(item["records"] as? [[String: Any]])
            let text = try ICalendarExport.encode(records, context: try CalendarTestContext.make(), kind: kind)
            let file = URL(fileURLWithPath: output).appendingPathComponent(name + ".ics")
            try Data(text.utf8).write(to: file, options: [.atomic])
            XCTAssertTrue(text.hasPrefix("BEGIN:VCALENDAR\r\n"))
            XCTAssertTrue(text.hasSuffix("END:VCALENDAR\r\n"))
            for line in text.components(separatedBy: "\r\n") { XCTAssertLessThanOrEqual(line.utf8.count, 75) }
        }
    }
}
