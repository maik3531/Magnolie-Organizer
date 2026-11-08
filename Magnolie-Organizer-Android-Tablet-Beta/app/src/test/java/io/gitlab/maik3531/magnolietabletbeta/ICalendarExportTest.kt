package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.concurrent.CancellationException

class ICalendarExportTest {
    private val ignored = setOf("geaendert", "icsSequence", "icsAenderungszeitFehlt", "icsQuelleId", "icsQuelleName", "icsTimezones", "icsRoundtrip", "icsAnzeigeZeitzone")
    private fun semantic(value: Any?): Any? = when (value) {
        null, JSONObject.NULL -> null
        is JSONObject -> value.keys().asSequence().toList().sorted().associateWith { semantic(value.get(it)) }
        is JSONArray -> (0 until value.length()).map { semantic(value.get(it)) }
        is Number -> value.toDouble()
        else -> value
    }
    private fun stable(record: JSONObject) = semantic(JSONObject(record.toString()).also { copy -> ignored.forEach(copy::remove) })
    private fun records(array: JSONArray) = (0 until array.length()).map { array.getJSONObject(it) }
    private fun rejected(body: () -> Unit) { try { body(); fail("Expected an atomic export rejection") } catch (_: ICalendarExport.ExportException) { } }
    private fun event() = JSONObject().put("uid", "public").put("titel", "Appointment").put("datum", "2026-03-28").put("zeit", "10:00").put("endZeit", "11:00").put("icsAnzeigeZeitzone", "UTC")
    private fun cases(): JSONArray {
        System.getenv("ANDROID_BETA_CALENDAR_FIXTURES")?.let { return JSONArray(File(it).readText(Charsets.UTF_8)) }
        val resource = javaClass.classLoader!!.getResourceAsStream("calendar-export-v2.0.30.json") ?: throw AssertionError("Missing independently generated export vectors")
        val golden = resource.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
        assertEquals("v2.0.30", golden.getString("canonicalTag")); assertEquals("067c38934b539943d8e1720abafd8a80b401d797", golden.getString("canonicalCommit"))
        return golden.getJSONArray("cases")
    }
    @Test fun publishedCanonicalRecordsAndImportedSourceBodiesRetainSemantics() {
        val cases = cases(); assertEquals(8, cases.length())
        val output = System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let(::File)
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index); val name = case.getString("name"); val kind = case.getString("kind")
            val group = mapOf("ics-termine" to "termine", "ics-aufgaben" to "aufgaben", "ics-jahrestage" to "jahrestage").getValue(kind)
            val input = records(case.getJSONArray("records"))
            val original = input.map { it.toString() }
            val serialized = ICalendarExport.encode(input, kind, "UTC")
            assertEquals(original, input.map { it.toString() })
            assertTrue(serialized.startsWith("BEGIN:VCALENDAR\r\n")); assertTrue(serialized.endsWith("END:VCALENDAR\r\n"))
            for (line in serialized.split("\r\n")) assertTrue(line.toByteArray(Charsets.UTF_8).size <= 75)
            val decoded = ICalendarImport.decode(serialized.toByteArray(), "UTC").document.getJSONArray(group)
            assertEquals(name, records(case.getJSONArray("expected")).map(::stable), records(decoded).map(::stable))
            output?.resolve("$name.ics")?.writeText(serialized, Charsets.UTF_8)
            val imported = ICalendarImport.decode(case.getString("importSource").toByteArray(), "UTC")
            output?.resolve("$name-imported.json")?.writeText(imported.document.toString(), Charsets.UTF_8)
            for ((key, selected) in listOf("termine" to imported.appointments, "aufgaben" to imported.tasks, "jahrestage" to imported.anniversaries)) if (selected.isNotEmpty()) {
                val selectedKind = mapOf("termine" to "ics-termine", "aufgaben" to "ics-aufgaben", "jahrestage" to "ics-jahrestage").getValue(key)
                val sourceRoundtrip = ICalendarExport.encode(selected, selectedKind, "UTC")
                val sourceExpected = case.getJSONObject("importExpected").getJSONArray(key)
                assertEquals(name, records(sourceExpected).map(::stable), records(ICalendarImport.decode(sourceRoundtrip.toByteArray(), "UTC").document.getJSONArray(key)).map(::stable))
                output?.resolve("$name-reimport-$key.ics")?.writeText(sourceRoundtrip, Charsets.UTF_8)
            }
        }
    }
    @Test fun structuredRulesExcludedDaysAndYearlessAnniversariesKeepOneComponent() {
        val record = JSONObject().put("uid", "weekly").put("titel", "Weekly").put("datum", "2026-03-23").put("zeit", "")
            .put("wiederholung", JSONObject().put("art", "weekly").put("bis", "2026-04-30").put("intervall", 2)).put("icsAusnahmen", JSONArray().put("2026-04-06"))
        val text = ICalendarExport.encode(listOf(record), "ics-termine")
        assertTrue(text.contains("RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20260430\r\n")); assertTrue(text.contains("EXDATE;VALUE=DATE:20260406\r\n"))
        assertEquals(1, text.split("BEGIN:VEVENT").size - 1)
        val anniversary = JSONObject().put("uid", "leap").put("name", "Birthday").put("datum", "--02-29").put("typ", "birthday")
        val result = ICalendarExport.encode(listOf(anniversary), "ics-jahrestage")
        assertTrue(result.contains("DTSTART;VALUE=DATE:20000229\r\n")); assertTrue(result.contains("X-MAGNOLIE-DATE:--02-29\r\n"))
        assertEquals("--02-29", ICalendarImport.decode(result.toByteArray(), "UTC").anniversaries.single().getString("datum"))
    }
    @Test fun taskAliasesPreserveSourceQualifiedParentsWithCollidingExternalUIDs() {
        val a = JSONObject().put("uid", "same").put("titel", "Account A").put("icsQuelleId", "A")
        val b = JSONObject().put("uid", "same").put("titel", "Account B").put("icsQuelleId", "B")
        val child = JSONObject().put("uid", "child").put("titel", "Child").put("icsQuelleId", "A").put("elternUid", "same").put("icsElternUid", "same").put("icsElternQuelleId", "B")
        val encoded = ICalendarExport.encode(listOf(a, b, child), "ics-aufgaben")
        assertEquals(2, encoded.split("UID:urn:magnolie:task:").size - 1)
        val imported = ICalendarImport.decode(encoded.toByteArray(), "UTC").tasks
        assertEquals(listOf("same", "same", "child"), imported.map { it.getString("uid") })
        assertEquals(listOf("A", "B", "A"), imported.map { it.getString("icsQuelleId") })
        assertEquals("same", imported[2].getString("elternUid")); assertEquals("B", imported[2].getString("icsElternQuelleId"))
        assertTrue(encoded.contains("RELATED-TO;RELTYPE=PARENT:urn:magnolie:task:"))
        System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let { File(it, "task-qualified-aliases.ics").writeText(encoded, Charsets.UTF_8) }
        val reverse = ICalendarExport.encode(listOf(b, a, child), "ics-aufgaben")
        val sourceToUID = ICalendarImport.decode(reverse.toByteArray(), "UTC").tasks.associate { it.getString("icsQuelleId") + ":" + it.getString("uid") to it.getString("titel") }
        assertEquals("Account B", sourceToUID["B:same"])
    }
    @Test fun customEmbeddedTimeZoneBeatsSystemDatabaseAndUnknownDataStayExact() {
        val source = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTIMEZONE\r\nTZID:Private/Custom\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+235959\r\nTZOFFSETTO:+235959\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT\r\nUID:custom\r\nDTSTART;TZID=Private/Custom:20260328T100000\r\nDTEND;TZID=Private/Custom:20260328T110000\r\nRRULE:FREQ=DAILY;COUNT=4\r\nX-OPAQUE;X-PARAM=alpha:keep\r\nSUMMARY:Custom\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        val records = ICalendarImport.decode(source.toByteArray(), "UTC").appointments
        val exported = ICalendarExport.encode(records, "ics-termine", "UTC").replace("\r\n ", "")
        assertTrue(exported.contains("TZID:Private/Custom\r\n")); assertTrue(exported.contains("TZOFFSETTO:+235959\r\n"))
        assertTrue(exported.contains("DTSTART;TZID=Private/Custom:20260328T100000\r\n")); assertTrue(exported.contains("X-OPAQUE;X-PARAM=alpha:keep\r\n"))
        assertTrue(exported.contains("TRIGGER:-PT15M\r\n"))
        assertEquals(records.map(::stable), ICalendarImport.decode(exported.toByteArray(), "UTC").appointments.map(::stable))
        System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let { File(it, "custom-embedded-offset.ics").writeText(exported, Charsets.UTF_8) }
    }
    @Test fun contradictionsInvalidRulesAndDSTGapsNeverProduceAPartialFile() {
        rejected { ICalendarExport.encode(listOf(event(), event().put("uid", "bad").put("unrecognizedState", JSONObject().put("keep", true))), "ics-termine") }
        rejected { ICalendarExport.encode(listOf(event().put("ganztag", "true")), "ics-termine") }
        rejected { ICalendarExport.encode(listOf(event().put("datum", "2026-03-29").put("zeit", "02:30").put("icsAnzeigeZeitzone", "Europe/Berlin")), "ics-termine") }
        for (rule in listOf("FREQ=DAILY;COUNT=0", "FREQ=DAILY;FREQ=WEEKLY", "FREQ=DAILY;BYHOUR=25", "FREQ=DAILY;COUNT=4;UNTIL=20260430T100000Z", "FREQ=DAILY;BYDAY=0MO")) rejected {
            ICalendarExport.encode(listOf(event().put("icsRoundtrip", JSONArray().put("RRULE:$rule"))), "ics-termine")
        }
        rejected { ICalendarExport.encode(listOf(event().put("icsRoundtrip", JSONArray().put("DTSTART:20260328T120000Z"))), "ics-termine") }
        rejected { ICalendarExport.encode(listOf(event().put("icsRoundtrip", JSONArray().put("SUMMARY:Safe\r\nBEGIN:VEVENT"))), "ics-termine") }
        rejected { ICalendarExport.encode(listOf(event(), event()), "ics-termine") }
        rejected { ICalendarExport.encode(listOf(event().put("icsRangeOverrides", JSONArray().put(JSONArray().put("RECURRENCE-ID:20260330T100000Z")))), "ics-termine") }
    }
    @Test fun oversizedDurationAndTaskRecurrenceWithoutAStartCannotBecomeOneOffs() {
        val duration = event().put("endZeit", "").put("icsNullDauer", true)
            .put("icsRoundtrip", JSONArray().put("DTSTART:20260328T100000Z").put("DURATION:P99999999999999999999999999999999999D"))
        rejected { ICalendarExport.encode(listOf(duration), "ics-termine") }
        val task = JSONObject().put("uid", "task").put("titel", "Recurring").put("faellig", "2026-04-01")
            .put("wiederholung", JSONObject().put("art", "daily").put("bis", ""))
        rejected { ICalendarExport.encode(listOf(task), "ics-aufgaben") }
        task.put("wiederholung", JSONObject().put("art", "none").put("bis", ""))
        assertFalse(ICalendarExport.encode(listOf(task), "ics-aufgaben").contains("RRULE:"))
    }
    @Test fun UTF8FoldingIsBoundedAndCancellationNeverReturnsOutput() {
        val record = event().put("titel", "Ä💐".repeat(100))
        val encoded = ICalendarExport.encode(listOf(record), "ics-termine", "UTC")
        for (line in encoded.split("\r\n")) assertTrue(line.toByteArray(Charsets.UTF_8).size <= 75)
        assertEquals(record.getString("titel"), ICalendarImport.decode(encoded.toByteArray(), "UTC").appointments.single().getString("titel"))
        var checks = 0; var returned = false
        try { ICalendarExport.encode(listOf(event(), event().put("uid", "other")), "ics-termine", checkCancelled = { if (++checks == 5) throw CancellationException() }); returned = true } catch (_: CancellationException) { }
        assertFalse(returned)
        rejected { ICalendarExport.encode(listOf(event().put("titel", "x".repeat(1024 * 1024))), "ics-termine") }
    }
    private fun sharedUiFixture(): JSONObject {
        val resource=javaClass.classLoader!!.getResourceAsStream("calendar-export-normalized-ui.json")
            ?: throw AssertionError("Missing actual shared UI alarm projection fixture")
        return resource.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
    }
    @Test fun actualSharedImportedAndSavedAlarmProjectionExportsItsAuthoritativeValarms() {
        val fixture=sharedUiFixture()
        val nativeInput=ICalendarImport.decode(fixture.getString("source").toByteArray(),"UTC","gui-alarms.ics").document
        assertEquals(semantic(fixture.getJSONObject("importDocument")),semantic(nativeInput))
        val saved=fixture.getJSONObject("normalizedRecord")
        assertEquals(2,saved.getJSONArray("alarme").length())
        val before=saved.toString()
        val output=ICalendarExport.encode(listOf(saved),"ics-termine","UTC")
        assertEquals(before,saved.toString())
        assertEquals(2,output.split("BEGIN:VALARM").size-1)
        assertTrue(output.contains("TRIGGER:-PT15M\r\n"))
        assertTrue(output.contains("TRIGGER;VALUE=DATE-TIME:20261115T083000Z\r\n"))
        val decoded=ICalendarImport.decode(output.toByteArray(),"UTC").appointments.single()
        val beforeRaw=saved.getJSONArray("icsRoundtrip"); val afterRaw=decoded.getJSONArray("icsRoundtrip")
        fun blocks(raw: JSONArray): List<String> {
            var active=false; val result=mutableListOf<String>()
            for(index in 0 until raw.length()) {
                val line=raw.getString(index)
                if(line=="BEGIN:VALARM") active=true
                if(active) result.add(line)
                if(line=="END:VALARM") active=false
            }
            return result
        }
        assertEquals(blocks(beforeRaw),blocks(afterRaw))
        System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let { File(it,"ui-normalized-valarm.ics").writeText(output) }
    }
    @Test fun editedDisabledAdditionalOrMissingStructuredAlarmsCannotDisappearIntoOldRawData() {
        val original=sharedUiFixture().getJSONObject("normalizedRecord")
        fun copy()=JSONObject(original.toString())
        for(field in listOf("offsetMinuten","related","aktion","bearbeitbar","aktiviert")) {
            val changed=copy(); val alarm=changed.getJSONArray("alarme").getJSONObject(0)
            alarm.put(field,when(field) {
                "offsetMinuten" -> 30; "related" -> "END"; "aktion" -> "email"; "triggerRaw" -> "-PT30M";
                "triggerTzid" -> "Europe/Berlin"; else -> false
            })
            rejected { ICalendarExport.encode(listOf(changed),"ics-termine","UTC") }
        }
        val removed=copy().put("alarme",JSONArray())
        rejected { ICalendarExport.encode(listOf(removed),"ics-termine","UTC") }
        val extra=copy(); extra.getJSONArray("alarme").put(JSONObject(extra.getJSONArray("alarme").getJSONObject(0).toString()))
        rejected { ICalendarExport.encode(listOf(extra),"ics-termine","UTC") }
        val withoutRaw=copy().put("icsRoundtrip",JSONArray())
        rejected { ICalendarExport.encode(listOf(withoutRaw),"ics-termine","UTC") }
        val unknown=copy(); unknown.getJSONArray("alarme").getJSONObject(0).put("emailRecipients","must not silently disappear")
        rejected { ICalendarExport.encode(listOf(unknown),"ics-termine","UTC") }
    }
    @Test fun readonlyAlarmTriggerAndTimezoneRemainAuthoritative() {
        val original=sharedUiFixture().getJSONObject("normalizedRecord")
        for(field in listOf("triggerRaw","triggerTzid")) {
            val changed=JSONObject(original.toString())
            changed.getJSONArray("alarme").getJSONObject(1).put(field,if(field=="triggerRaw") "20261115T080000Z" else "Europe/Berlin")
            rejected { ICalendarExport.encode(listOf(changed),"ics-termine","UTC") }
        }
    }
    @Test fun actualAppointmentFormEditsAndRemovalMatchCurrentRawSemanticsDespiteStaleHints() {
        val resource=javaClass.classLoader!!.getResourceAsStream("calendar-export-edited-ui.json")!!
        val cases=resource.bufferedReader().use { JSONObject(it.readText()).getJSONArray("cases") }
        for(index in 0 until cases.length()) {
            val case=cases.getJSONObject(index);val record=case.getJSONObject("record");val mode=case.getString("mode")
            val output=ICalendarExport.encode(listOf(record),"ics-termine","UTC")
            assertTrue(output.contains("TRIGGER;VALUE=DATE-TIME:20261115T083000Z"))
            if(mode=="edit30") {
                assertEquals("-PT15M",record.getJSONArray("alarme").getJSONObject(0).getString("triggerRaw"))
                assertTrue(output.contains("TRIGGER;RELATED=START:-PT30M"))
            }
            assertEquals(if(mode=="removeEditable") 1 else 2,output.split("BEGIN:VALARM").size-1)
            System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let { File(it,"ui-$mode.ics").writeText(output) }
        }
    }
    @Test fun matchingLocallyEditedAlarmCanUseCurrentRawTriggerWithoutStaleDisplayHint() {
        val record=sharedUiFixture().getJSONObject("normalizedRecord")
        val alarm=record.getJSONArray("alarme").getJSONObject(0)
        alarm.remove("triggerRaw"); alarm.put("quelle","magnolie")
        assertTrue(ICalendarExport.encode(listOf(record),"ics-termine","UTC").contains("TRIGGER:-PT15M"))
    }
    @Test fun calendarSourceDisplayIsBoundedLocalMetadataAndCannotSmuggleCredentialsOrRebindSource() {
        val original=sharedUiFixture().getJSONObject("normalizedRecord")
        for((field,value) in listOf("password" to "must not export","id" to "different-source","farbe" to "invalid","name" to "x".repeat(201))) {
            val changed=JSONObject(original.toString());changed.getJSONObject("kalenderQuelle").put(field,value)
            rejected { ICalendarExport.encode(listOf(changed),"ics-termine","UTC") }
        }
        val valid=JSONObject(original.toString()); valid.getJSONObject("kalenderQuelle").put("name","Renamed local display").put("farbe","#12abEF")
        assertTrue(ICalendarExport.encode(listOf(valid),"ics-termine","UTC").contains("BEGIN:VEVENT"))
        val longSource=JSONObject(original.toString()).put("icsQuelleId","x".repeat(250))
        longSource.getJSONObject("kalenderQuelle").put("id","x".repeat(200)).put("name","Local\ncalendar")
        assertTrue(ICalendarExport.encode(listOf(longSource),"ics-termine","UTC").contains("BEGIN:VEVENT"))
    }

}
