package io.gitlab.maik3531.magnolienotes.einfuhr

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant
import java.util.TimeZone

/** Refs #819: source timestamps keep their instant, including fractional seconds. */
class LeserZeitTest {
    @Test fun `ISO Bruchteile behalten ihren Sekundenanteil`() {
        val base = Instant.parse("2026-11-27T10:00:00Z").toEpochMilli()
        val cases = mapOf("" to 0L, ".1" to 100L, ".12" to 120L, ".123" to 123L,
            ".1234" to 123L, ".12345" to 123L, ".123456" to 123L, ".1234567" to 123L,
            ".12345678" to 123L, ".123456789" to 123L, ".000001" to 0L, ".999999999" to 999L)
        for ((fraction, millis) in cases) {
            assertEquals(fraction, base + millis, Leser.isoZeit("2026-11-27T10:00:00${fraction}Z"))
            assertEquals("positive offset $fraction", base + millis,
                Leser.isoZeit("2026-11-27T11:00:00${fraction}+01:00"))
            assertEquals("negative offset $fraction", base + millis,
                Leser.isoZeit("2026-11-27T04:30:00${fraction}-05:30"))
        }
    }

    @Test fun `falsche Tage und Resttext werden nicht normalisiert`() {
        for (value in listOf("2026-02-30T10:00:00.000Z", "2026-02-29T10:00:00Z",
            "2026-13-01T10:00:00Z", "2026-11-27T25:00:00Z", "2026-11-27T10:60:00Z",
            "2026-11-27T10:00:00.Z", "2026-11-27T10:00:00.1234567890Z", "2026-11-27T10:00:00Zrest",
            "2026-11-27T10:00:00.000Zrest", "2026-02-30 10:00:00", "2026-11-27 10:00:00rest",
            "2026-02-30", "2026-11-27rest", "not a date", "", " "))
            assertEquals(value, 0L, Leser.isoZeit(value))
        assertEquals(Instant.parse("2024-02-29T10:00:00Z").toEpochMilli(), Leser.isoZeit("2024-02-29T10:00:00Z"))
    }

    @Test fun `beide Exportleser erhalten Erstellungs und Aenderungszeit`() {
        val created = "2026-11-27T10:00:00.123456Z"
        val changed = "2026-11-27T10:01:00.1Z"
        val standard = """{"items":[{"content_type":"Note",
            "created_at":"$created","updated_at":"$changed",
            "content":{"title":"Synthetic","text":"Content"}}]}"""
        val simple = """{"activeNotes":[{"content":"Synthetic",
            "creationDate":"$created","lastModified":"$changed"}]}"""
        for ((name, export) in listOf("standardnotes.json" to standard, "simplenote.json" to simple)) {
            val note = Einfuhr.ausInhalt(export.toByteArray(), name, 0).single()
            assertEquals(Instant.parse(created).toEpochMilli(), note.angelegt)
            assertEquals(Instant.parse(changed).toEpochMilli(), note.geaendert)
        }
    }

    @Test fun `lokale und numerische Altformate bleiben erhalten`() {
        val original = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Europe/Berlin"))
            assertEquals(Instant.parse("2026-11-27T09:00:00Z").toEpochMilli(), Leser.isoZeit("2026-11-27 10:00:00"))
            assertEquals(Instant.parse("2026-11-26T23:00:00Z").toEpochMilli(), Leser.isoZeit("2026-11-27"))
            assertEquals(Instant.parse("2026-11-27T10:00:00Z").toEpochMilli(), Leser.isoZeit("2026-11-27T10:00:00Z"))
            assertEquals(1_700_000_000_000L, Leser.isoZeit("1700000000"))
            assertEquals(1_700_000_000_000L, Leser.isoZeit("1700000000000"))
            assertEquals(0L, Leser.isoZeit((Long.MIN_VALUE + 1).toString()))
        } finally { TimeZone.setDefault(original) }
    }

    @Test fun `lokale doppelte Uhrzeit bleibt kompatibel und eine Luecke wird nicht erfunden`() {
        val original = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Europe/Berlin"))
            assertEquals(Instant.parse("2026-10-25T01:30:00Z").toEpochMilli(),
                Leser.isoZeit("2026-10-25 02:30:00"))
            assertEquals(0L, Leser.isoZeit("2026-03-29 02:30:00"))
            TimeZone.setDefault(TimeZone.getTimeZone("Pacific/Apia"))
            assertEquals(0L, Leser.isoZeit("2011-12-30"))
        } finally { TimeZone.setDefault(original) }
    }
}
