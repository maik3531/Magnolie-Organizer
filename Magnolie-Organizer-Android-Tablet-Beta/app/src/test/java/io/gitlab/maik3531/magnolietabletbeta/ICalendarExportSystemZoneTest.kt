package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.TimeZone

/** Real new-record outputs of the common appointment form and save envelope,
 * not hand-crafted simplified calendar DTOs. No source fields are removed. */
class ICalendarExportSystemZoneTest {
    private fun records(): List<JSONObject> {
        val resource = javaClass.classLoader!!.getResourceAsStream("calendar-export-system-zone-ui.json") ?: throw AssertionError("Missing actual saved UI system-zone vectors")
        val fixture = resource.bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
        assertEquals("system", fixture.getString("profileTimeZone")); assertEquals("Europe/Berlin", fixture.getString("uiTimeZone"))
        val array = fixture.getJSONArray("records")
        return (0 until array.length()).map { array.getJSONObject(it) }
    }
    private fun inBerlin(action: () -> Unit) {
        val previous = TimeZone.getDefault()
        try { TimeZone.setDefault(TimeZone.getTimeZone("Europe/Berlin")); action() } finally { TimeZone.setDefault(previous) }
    }
    @Test fun newSavedUIRecordsUseResolvedSystemZoneAndPreserveWinterSummerInstants() = inBerlin {
        val input = records()
        for ((index, record) in input.withIndex()) {
            assertFalse(record.has("icsAnzeigeZeitzone")); assertEquals(0, record.getJSONArray("icsRoundtrip").length())
            val before = record.toString()
            val encoded = ICalendarExport.encode(listOf(record), "ics-termine", "system")
            assertEquals(before, record.toString())
            assertTrue("System zone must be explicit for new times", encoded.contains("DTSTART;TZID=Europe/Berlin:"))
            assertTrue(encoded.contains("TZID:Europe/Berlin\r\n"))
            val imported = ICalendarImport.decode(encoded.toByteArray(Charsets.UTF_8), "UTC").appointments.single()
            assertEquals(if (index == 0) "09:00" else "08:00", imported.getString("zeit"))
            System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let { File(it, "system-zone-ui-$index.ics").writeText(encoded, Charsets.UTF_8) }
        }
    }
    @Test fun explicitProfileAndRecordZonesRemainAuthoritative() = inBerlin {
        val input = records().first()
        val before = input.toString()
        val profile = ICalendarExport.encode(listOf(input), "ics-termine", "America/New_York")
        assertTrue(profile.contains("DTSTART;TZID=America/New_York:"))
        assertEquals("15:00", ICalendarImport.decode(profile.toByteArray(), "UTC").appointments.single().getString("zeit"))
        assertEquals(before, input.toString())
        val explicit = JSONObject(input.toString()).put("icsAnzeigeZeitzone", "UTC")
        val explicitBefore = explicit.toString()
        val output = ICalendarExport.encode(listOf(explicit), "ics-termine", "Europe/Berlin")
        assertTrue(output.contains("DTSTART:20300115T100000Z\r\n")); assertEquals(explicitBefore, explicit.toString())
        val sentinel = JSONObject(input.toString()).put("icsAnzeigeZeitzone", "system")
        assertTrue(ICalendarExport.encode(listOf(sentinel), "ics-termine", "America/New_York").contains("DTSTART;TZID=Europe/Berlin:"))
    }
    @Test fun originalFloatingDTSTARTAndRuleStayFloatingAfterResolvingDisplayDefault() = inBerlin {
        val input = records().first()
        val source = listOf("DTSTART:20300115T100000", "DTEND:20300115T110000", "RRULE:FREQ=DAILY;COUNT=2")
        input.put("icsRoundtrip", JSONArray(source))
        val before = input.toString()
        val output = ICalendarExport.encode(listOf(input), "ics-termine", "system")
        for (line in source) assertTrue(output.contains(line + "\r\n"))
        assertFalse(output.contains("DTSTART;TZID=")); assertFalse(output.contains("BEGIN:VTIMEZONE"))
        assertEquals(before, input.toString())
        System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let { File(it, "original-floating-source.ics").writeText(output, Charsets.UTF_8) }
    }
}
