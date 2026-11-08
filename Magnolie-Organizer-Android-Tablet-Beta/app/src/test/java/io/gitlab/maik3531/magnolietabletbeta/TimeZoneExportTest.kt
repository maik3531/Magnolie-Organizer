package io.gitlab.maik3531.magnolietabletbeta

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import org.threeten.bp.LocalDateTime
import org.threeten.bp.ZoneId
import org.threeten.bp.ZoneOffset

class TimeZoneExportTest {
    private fun at(year: Int, month: Int, day: Int, hour: Int = 12, minute: Int = 0) = LocalDateTime.of(year, month, day, hour, minute)
    private fun offset(definition: List<String>, wall: LocalDateTime): Int {
        val value = wall.format(org.threeten.bp.format.DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss"))
        val lines = listOf("BEGIN:VCALENDAR", "VERSION:2.0") + definition + listOf("BEGIN:VEVENT", "UID:probe", "DTSTART:20000101T000000Z", "DTSTAMP;TZID=" + definition[1].removePrefix("TZID:") + ":$value", "SUMMARY:Timezone probe", "END:VEVENT", "END:VCALENDAR")
        val parsed = ICalendarImport.decode(lines.joinToString("\r\n", postfix = "\r\n").toByteArray(), "UTC").appointments.single()
        return (wall.toEpochSecond(ZoneOffset.UTC) - parsed.getLong("geaendert") / 1000).toInt()
    }
    @Test fun historyAndInfiniteFutureMatchSystemZoneRulesAcrossTheGregorianCycle() {
        val output = System.getenv("ANDROID_BETA_CALENDAR_OUTPUT")?.let(::File)
        val vectors = JSONArray()
        for (identifier in listOf("Europe/Berlin", "America/New_York", "Australia/Sydney", "Australia/Lord_Howe", "Pacific/Chatham", "Asia/Kathmandu", "Etc/UTC")) {
            val definition = TimeZoneExport.definition(identifier)
            assertEquals("BEGIN:VTIMEZONE", definition.first()); assertEquals("END:VTIMEZONE", definition.last())
            val future = ZoneId.of(identifier).rules.transitionRules
            assertEquals(future.size, definition.count { it.startsWith("RRULE:") })
            assertFalse(definition.any { it.startsWith("RRULE:") && ("UNTIL=" in it || "COUNT=" in it) })
            for (year in listOf(2, 1800, 1900, 1945, 2026, 2038, 2100, 2400, 8000)) for (month in listOf(1, 3, 4, 7, 10, 11, 12)) {
                val wall = at(year, month, 15); val valid = ZoneId.of(identifier).rules.getValidOffsets(wall)
                assertTrue(valid.isNotEmpty()); assertEquals(identifier + " " + wall, valid.first().totalSeconds, offset(definition, wall))
            }
            vectors.put(JSONObject().put("identifier", identifier).put("definition", JSONArray(definition)))
        }
        output?.resolve("timezone-definitions.json")?.writeText(vectors.toString(), Charsets.UTF_8)
    }
    @Test fun completeFixedOffsetRulesRemainLosslessWithoutSeasonalRules() {
        for ((identifier, expected) in listOf("UTC" to 0, "Etc/UTC" to 0, "Etc/GMT-1" to 3600)) {
            val definition = TimeZoneExport.definition(identifier)
            assertFalse(definition.any { it.startsWith("RRULE:") })
            assertEquals(1, definition.count { it == "BEGIN:STANDARD" })
            for (year in listOf(2, 2026, 8000)) assertEquals(expected, offset(definition, at(year, 7, 15)))
        }
    }
    @Test fun gapsFoldsAndInitialPositiveOffsetAnchorsKeepExactInstants() {
        for ((identifier, walls) in listOf(
            "Europe/Berlin" to listOf(at(2026, 3, 29, 1, 59), at(2026, 3, 29, 3), at(2026, 10, 25, 2, 30)),
            "America/New_York" to listOf(at(2026, 3, 8, 1, 59), at(2026, 3, 8, 3), at(2026, 11, 1, 1, 30)))) {
            val definition = TimeZoneExport.definition(identifier)
            for (wall in walls) assertEquals(ZoneId.of(identifier).rules.getValidOffsets(wall).first().totalSeconds, offset(definition, wall))
            val gap = if (identifier == "Europe/Berlin") at(2026, 3, 29, 2, 30) else at(2026, 3, 8, 2, 30)
            try { offset(definition, gap); fail("A nonexistent wall time must be rejected") } catch (_: ICalendarImport.ImportException) { }
        }
        val berlin = TimeZoneExport.definition("Europe/Berlin")
        assertTrue(berlin.contains("DTSTART:00010101T005328"))
        assertTrue(berlin.contains("TZOFFSETFROM:+005328"))
        try { TimeZoneExport.definition("No/SuchZone"); fail("Unknown zone must be rejected") } catch (_: TimeZoneExport.UnsupportedException) { }
    }
}
