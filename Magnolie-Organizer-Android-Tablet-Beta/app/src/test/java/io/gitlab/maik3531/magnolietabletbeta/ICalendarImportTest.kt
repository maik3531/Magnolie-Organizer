package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CancellationException

class ICalendarImportTest {
    private fun bytes(body: String) = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + body + "END:VCALENDAR\r\n").toByteArray(Charsets.UTF_8)
    private val event = "BEGIN:VEVENT\r\nUID:public\r\nDTSTART:20260328T100000Z\r\nDTEND:20260328T110000Z\r\nSUMMARY:Public item\r\nEND:VEVENT\r\n"
    private fun decode(body: String) = ICalendarImport.decode(bytes(body), "UTC")
    private fun rejected(body: () -> Unit) {
        try { body(); fail("Expected an atomic import rejection") } catch (_: ICalendarImport.ImportException) { }
    }
    private fun semantic(value: Any?): Any? = when (value) {
        null, JSONObject.NULL -> null
        is JSONObject -> value.keys().asSequence().toList().sorted().associateWith { semantic(value.get(it)) }
        is JSONArray -> (0 until value.length()).map { semantic(value.get(it)) }
        is Number -> value.toDouble()
        else -> value
    }
    private val ignored = setOf("geaendert", "icsSequence", "icsAenderungszeitFehlt", "icsQuelleId", "icsQuelleName", "icsTimezones", "icsRoundtrip", "icsAnzeigeZeitzone")
    private fun stable(value: JSONObject): Any? = semantic(JSONObject(value.toString()).also { copy -> ignored.forEach { copy.remove(it) } })
    private fun strings(array: JSONArray) = (0 until array.length()).map { array.getString(it) }

    @Test fun publishedPythonOracleCasesHaveMatchingSemanticRecordsAndSourceProperties() {
        val path = System.getenv("ANDROID_BETA_CALENDAR_FIXTURES")
        val cases = if (path != null) JSONArray(File(path).readText(Charsets.UTF_8)) else {
            val resource = javaClass.classLoader!!.getResourceAsStream("calendar-import-v2.0.30.json")
                ?: throw AssertionError("Missing independently generated published Python calendar vectors")
            val golden = resource.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
            assertEquals("v2.0.30", golden.getString("canonicalTag"))
            assertEquals("067c38934b539943d8e1720abafd8a80b401d797", golden.getString("canonicalCommit"))
            golden.getJSONArray("cases")
        }
        assertEquals(8, cases.length())
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index); val source = case.getString("importSource"); val bytes = source.toByteArray(Charsets.UTF_8)
            val imported = ICalendarImport.decode(bytes, "UTC").document
            val expected = case.getJSONObject("importExpected")
            for (group in listOf("termine", "aufgaben", "jahrestage")) {
                val original = expected.getJSONArray(group); val actual = imported.getJSONArray(group)
                assertEquals(case.getString("name") + "/" + group, original.length(), actual.length())
                for (row in 0 until original.length()) {
                    val before = original.getJSONObject(row); val after = actual.getJSONObject(row)
                    assertEquals(case.getString("name") + "/" + group + "/" + row, stable(before), stable(after))
                    val retained = strings(after.getJSONArray("icsRoundtrip"))
                    for (line in strings(before.optJSONArray("icsRoundtrip") ?: JSONArray())) assertTrue("Lost source property: $line", line in retained)
                    assertEquals(semantic(before.opt("icsTimezones")), semantic(after.opt("icsTimezones")))
                }
            }
            val sha = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
            assertEquals(sha, imported.getJSONObject("icsImportMetadata").getString("sourceSHA256"))
        }
    }

    @Test fun unfoldingAndCalendarMetadataPreserveUnknownParametersAndNestedAlarms() {
        val body = "X-PROVIDER-CALENDAR;X-PARAM=opaque:keep\r\nBEGIN:VEVENT\r\nUID:folded\r\nDTSTART;VALUE=DATE:20260328\r\nSUMMARY:Long \\nlabel\r\nDESCRIPTION:First\\nSecond\\, item\r\nX-OPAQUE;X-TOKEN=alpha:part-\r\n two\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\n"
        val result = decode(body); val record = result.appointments.single()
        assertEquals("First\nSecond, item", record.getString("notiz"))
        assertTrue(strings(record.getJSONArray("icsRoundtrip")).containsAll(listOf("X-OPAQUE;X-TOKEN=alpha:part-two", "BEGIN:VALARM", "TRIGGER:-PT15M", "END:VALARM")))
        assertTrue("X-PROVIDER-CALENDAR;X-PARAM=opaque:keep" in result.calendarProperties)
        assertEquals(64, result.sourceSHA256.length)
    }
    @Test fun CRLFLFAndMixedTerminatorsAndBOMHaveIdenticalRecordsWithoutBareCRAcceptance() {
        val body = event.replace("SUMMARY:Public item\r\n", "SUMMARY:Public item\r\nDESCRIPTION:Folded \r\n\tsecond piece\r\nX-OPAQUE:part-\r\n\ttwo\r\n")
        val crlf = bytes(body).toString(Charsets.UTF_8)
        val variants = listOf(crlf, crlf.replace("\r\n", "\n"), crlf.replace("VERSION:2.0\r\n", "VERSION:2.0\n"), "\uFEFF$crlf")
        val original = semantic(ICalendarImport.decode(variants.first().toByteArray(), "UTC").appointments.single())
        for (source in variants) {
            val actual = ICalendarImport.decode(source.toByteArray(Charsets.UTF_8), "UTC").appointments.single()
            assertEquals(original, semantic(actual)); assertEquals("Folded second piece", actual.getString("notiz"))
        }
        rejected { ICalendarImport.decode(crlf.replace("SUMMARY:Public item", "SUMMARY:Public\ritem").toByteArray()) }
        rejected { ICalendarImport.decode(crlf.replace("END:VCALENDAR\r\n", "END:VCALENDAR\r").toByteArray()) }
    }
    @Test fun manySmallFoldsAccumulateWithoutLosingCharacters() {
        val folded = event.replace("SUMMARY:Public item\r\n", "SUMMARY:prefix\r\n" + " x\r\n".repeat(100_000))
        assertEquals("prefix" + "x".repeat(100_000), decode(folded).appointments.single().getString("titel"))
        rejected { decode(event.replace("SUMMARY:Public item", "SUMMARY:" + "x".repeat(1024 * 1024))) }
    }
    @Test fun aBadLaterComponentNeverReturnsAPrefixOrTreatsDuplicatesAsSuccess() {
        for (invalid in listOf(
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260230T100000Z\r\nSUMMARY:Bad date\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nUID:other\r\nDTSTART:20260328T100000Z\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260328T100000Z\r\nRRULE:FREQ=DAILY;COUNT=0\r\nEND:VEVENT\r\n",
            "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20260328T100000Z\r\nEND:VTODO\r\n",
            "BEGIN:VJOURNAL\r\nUID:unsupported\r\nEND:VJOURNAL\r\n")) rejected { decode(event + invalid) }
        rejected { decode(event + event) }
        rejected { ICalendarImport.decode(byteArrayOf(0xff.toByte(), 0xfe.toByte(), 0xff.toByte())) }
        rejected { ICalendarImport.decode(ByteArray(ICalendarImport.maximumBytes + 1) { 32 }) }
        // A byte-bounded file still must not allocate one substring per byte.
        rejected { ICalendarImport.decode(ByteArray(ICalendarImport.maximumBytes) { 10 }) }
        rejected { decode(event.replace("SUMMARY:Public item", "SUMMARY:bad\u0000")) }
        rejected { decode(event.replace("DTSTART:", "DTSTART;VALUE=DATE:")) }
        rejected { decode(event.replace("DTSTART:20260328T100000Z", "DTSTART;TZID=No/SuchZone:20260328T100000")) }
    }
    private fun fixedZone(offset: String = "+0530") = "BEGIN:VTIMEZONE\r\nTZID:Private/Test\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:$offset\r\nTZOFFSETTO:$offset\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
    private fun zonedEvent(clock: String = "20260328T100000") = "BEGIN:VEVENT\r\nUID:private-zone\r\nDTSTART;TZID=Private/Test:$clock\r\nDURATION:PT1H\r\nSUMMARY:Custom source zone\r\nEND:VEVENT\r\n"
    @Test fun customFixedZonesResolveRFCOffsetsIncludingBeyondJavaZoneOffsetLimit() {
        for ((offset, date, time) in listOf(Triple("+0530", "2026-03-28", "04:30"), Triple("+235959", "2026-03-27", "10:00"), Triple("-235959", "2026-03-29", "09:59"))) {
            val result = decode(fixedZone(offset) + zonedEvent()).appointments.single()
            assertEquals(date, result.getString("datum")); assertEquals(time, result.getString("zeit"))
            assertEquals("BEGIN:VTIMEZONE", result.getJSONArray("icsTimezones").getJSONArray(0).getString(0))
        }
        rejected { decode(fixedZone() + fixedZone("+0630") + zonedEvent()) }
        for (rule in listOf("FREQ=YEARLY;INTERVAL=2", "FREQ=YEARLY;BYDAY=-1SU")) {
            rejected { decode(event + fixedZone().replace("TZOFFSETTO:+0530\r\n", "TZOFFSETTO:+0530\r\nRRULE:$rule\r\n") + zonedEvent()) }
        }
    }
    private val seasonalZone = "BEGIN:VTIMEZONE\r\nTZID:Private/Test\r\nBEGIN:STANDARD\r\nDTSTART:19701025T030000\r\nTZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nRRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\r\nEND:STANDARD\r\nBEGIN:DAYLIGHT\r\nDTSTART:19700329T020000\r\nTZOFFSETFROM:+0100\r\nTZOFFSETTO:+0200\r\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
    @Test fun customSeasonalZoneRejectsGapsChoosesFirstFoldAndKeepsUnboundedFuture() {
        rejected { decode(seasonalZone + zonedEvent("20260329T023000")) }
        val overlap = decode(seasonalZone + zonedEvent("20261025T023000")).appointments.single()
        assertEquals("00:30", overlap.getString("zeit"))
        assertEquals("01:30", overlap.getString("endZeit"))
        val future = decode(seasonalZone + zonedEvent("80000701T100000")).appointments.single()
        assertEquals("08:00", future.getString("zeit"))
        val winter = decode(seasonalZone + zonedEvent("80000101T100000")).appointments.single()
        assertEquals("09:00", winter.getString("zeit"))
        // The final finite transition remains active after UNTIL, including
        // queries decades later, without enumerating intervening occurrences.
        val finite = seasonalZone.replace("BYMONTH=3;BYDAY=-1SU", "BYMONTH=3;BYDAY=-1SU;UNTIL=20260329T010000Z")
            .replace("BYMONTH=10;BYDAY=-1SU", "BYMONTH=10;BYDAY=-1SU;UNTIL=20251026T010000Z")
        assertEquals("08:00", decode(finite + zonedEvent("24000101T100000")).appointments.single().getString("zeit"))
    }
    @Test fun rangeExceptionsRetainSourceBodiesAndMasterExclusionsWithoutExpandingEvents() {
        val master = event.replace("UID:public", "UID:series").replace("SUMMARY:Public item", "RRULE:FREQ=DAILY;COUNT=5\r\nSUMMARY:Master")
        val exception = event.replace("UID:public", "UID:series\r\nRECURRENCE-ID;RANGE=THISANDFUTURE:20260330T100000Z").replace("20260328", "20260330").replace("SUMMARY:Public item", "SUMMARY:Moved\r\nX-OPAQUE:keep")
        val result = decode(master + exception)
        assertEquals(2, result.appointments.size)
        assertEquals("series", result.appointments[0].getString("icsSerienUid"))
        assertTrue(result.appointments[1].getString("uid").startsWith("series-magnolie-instanz-"))
        assertEquals(1, result.appointments[0].getJSONArray("icsRangeOverrides").length())
        assertTrue("EXDATE:20260330T100000Z" in strings(result.appointments[0].getJSONArray("icsRoundtrip")))
    }
    @Test fun qualifiedTaskParentsAndStrictIdentityStayBoundToTheirOriginalSource() {
        val identity = JSONObject().put("v", 1).put("source", "account-A").put("uid", "child").put("parent", "parent").put("parentSource", "account-B")
        val task = "BEGIN:VTODO\r\nUID:child\r\nSUMMARY:Child\r\nRELATED-TO;RELTYPE=PARENT:parent\r\nX-MAGNOLIE-TASK-IDENTITY:" + identity.toString().replace("\\", "\\\\").replace(",", "\\,") + "\r\nEND:VTODO\r\n"
        val result = ICalendarImport.decode(bytes(task), "UTC", sourceName = "imports\\public.ics", sourceId = "file-token").tasks.single()
        assertEquals("account-A", result.getString("icsQuelleId")); assertEquals("account-B", result.getString("icsElternQuelleId")); assertEquals("parent", result.getString("elternUid"))
        assertEquals("imports/public.ics", result.getString("icsQuelleName"))
        fun alias(value: String): String = "urn:magnolie:task:" + MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }
        val aliased = task.replace("UID:child", "UID:" + alias("account-A\u0000child") + "-2")
            .replace("RELTYPE=PARENT:parent", "RELTYPE=PARENT:" + alias("account-B\u0000parent"))
        val recovered = decode(aliased).tasks.single()
        assertEquals("child", recovered.getString("uid")); assertEquals("parent", recovered.getString("elternUid"))
        assertEquals("account-B", recovered.getString("icsElternQuelleId"))
        assertFalse(strings(result.getJSONArray("icsRoundtrip")).any { it.startsWith("X-MAGNOLIE-TASK-IDENTITY:") })
        rejected { decode(task.replace("UID:child", "UID:other")) }
        rejected { decode(task.replace("RELTYPE=PARENT:parent", "RELTYPE=PARENT:other")) }
        rejected { decode(task.replace("{", "{\"v\":1\\,")) }
        rejected { decode(task.replace("\"v\":1", "\"v\":true")) }
        rejected { decode(task.replace("\"source\"", "source")) }
    }
    @Test fun dealiasedTaskUIDsRemainDistinctAcrossSourcesAndRejectSameSourceDuplicates() {
        fun task(source: String): String {
            val alias = "urn:magnolie:task:" + MessageDigest.getInstance("SHA-256").digest((source + "\u0000shared").toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }
            val identity = JSONObject().put("v", 1).put("source", source).put("uid", "shared").put("parent", "").put("parentSource", "")
            val escaped = identity.toString().replace("\\", "\\\\").replace(",", "\\,")
            return "BEGIN:VTODO\r\nUID:$alias\r\nSUMMARY:Task $source\r\nX-MAGNOLIE-TASK-IDENTITY:$escaped\r\nEND:VTODO\r\n"
        }
        val result = decode(task("A") + task("B"))
        assertEquals(listOf("shared", "shared"), result.tasks.map { it.getString("uid") })
        assertEquals(listOf("A", "B"), result.tasks.map { it.getString("icsQuelleId") })
        rejected { decode(task("A") + task("A")) }
    }
    @Test fun durationUsesCalendarDaysAcrossDSTAndExactHoursSeparately() {
        val start = zonedEvent("20260328T100000")
        val day = decode(seasonalZone + start.replace("DURATION:PT1H", "DURATION:P1D")).appointments.single()
        val hours = decode(seasonalZone + start.replace("DURATION:PT1H", "DURATION:PT24H")).appointments.single()
        assertEquals("08:00", day.getString("endZeit")); assertEquals("09:00", hours.getString("endZeit"))
        val period = event.replace("SUMMARY:Public item", "RDATE;VALUE=PERIOD:20260401T100000Z/PT2H\r\nSUMMARY:Period")
        assertTrue(decode(period).appointments.single().getBoolean("icsKomplex"))
        assertTrue("RDATE;VALUE=PERIOD:20260401T100000Z/PT2H" in strings(decode(period).appointments.single().getJSONArray("icsRoundtrip")))
        rejected { decode(event.replace("DTEND:20260328T110000Z", "DTEND:20260328T110000Z\r\nDURATION:PT1H")) }
    }
    @Test fun projectedOutputLimitsComponentCountAndCancellationAreAtomic() {
        // Four physical lines per item keep this below the independent line
        // budget, so this specifically exercises the component-count limit.
        val many = buildString { repeat(50_000) { append("BEGIN:VTODO\r\nUID:item-$it\r\nSUMMARY:Task\r\nEND:VTODO\r\n") } }
        rejected { decode(many) }
        val paddedZone = fixedZone().replace("TZID:Private/Test", "TZID:Private/Test\r\nX-OPAQUE:" + "x".repeat(16_000))
        val projected = paddedZone + buildString { repeat(1100) { append(zonedEvent().replace("UID:private-zone", "UID:item-$it")) } }
        rejected { decode(projected) }
        var checks = 0; var returned = false
        try {
            ICalendarImport.decode(bytes(event + event.replace("UID:public", "UID:other")), "UTC", checkCancelled = {
                checks++; if (checks == 5) throw CancellationException("cancelled")
            }); returned = true
        } catch (_: CancellationException) { }
        assertFalse(returned); assertEquals(5, checks)
    }
}
