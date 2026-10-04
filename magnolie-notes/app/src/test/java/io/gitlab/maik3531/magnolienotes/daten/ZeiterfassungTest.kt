package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.util.Locale

class ZeiterfassungTest {
    private fun minute(value: String) = Instant.parse(value).epochSecond / 60

    @Test fun pauseAndRestartKeepOneIntervalAcrossMonthBoundary() {
        val start = minute("2026-01-31T21:00:00Z")
        val initial = Zeiteintrag(startMinute = start, zone = "Europe/Berlin", type = "night").validate()
        val paused = initial.pause(start + 120)
        val restored = Json.decodeFromString<Zeiteintrag>(Json.encodeToString(Zeiteintrag.serializer(), paused))
        assertEquals(initial.id, restored.id)
        assertEquals(120L, restored.totalMinutes(start + 150))
        val ended = restored.resume(start + 150).finish(start + 480)
        assertEquals(480L, ended.grossMinutes())
        assertEquals(30L, ended.pausedMinutes())
        assertEquals(450L, ended.totalMinutes())
        assertEquals("2026-01-31", ended.localStart().toLocalDate().toString())
        assertEquals("2026-02-01", ended.localEnd()!!.toLocalDate().toString())
        assertEquals(ended, ended.finish(start + 500))
    }

    @Test fun clockConventionDoesNotWrapDurationsOrShowSeconds() {
        val start = minute("2026-10-03T14:30:00Z")
        val entry = Zeiteintrag(startMinute = start, zone = "UTC")
        assertEquals("2:30 PM", entry.displayTime(start, Locale.US, false))
        assertEquals("14:30", entry.displayTime(start, Locale.GERMANY, true))
        assertEquals("12:00 AM", entry.displayTime(minute("2026-10-03T00:00:00Z"), Locale.US, false))
        assertEquals("12:00 PM", entry.displayTime(minute("2026-10-03T12:00:00Z"), Locale.US, false))
        assertEquals("168:30", Zeiteintrag.duration(168 * 60 + 30L))
    }

    @Test fun correctionCannotCreateNegativeNetTime() {
        val entry = Zeiteintrag(startMinute = 100, zone = "UTC")
        assertTrue(runCatching { entry.corrected(100, 160, 61, "Learning", "") }.isFailure)
        assertTrue(runCatching { entry.corrected(160, 100, 0, "Learning", "") }.isFailure)
        val fixed = entry.corrected(100, 220, 15, "Learning", "Corrected afterwards")
        assertEquals(105L, fixed.totalMinutes())
        assertEquals("Learning", fixed.type)
        assertEquals(entry.id, fixed.id)
    }

    @Test fun daylightSavingChangesMeasureElapsedTimeRatherThanWallClockDifference() {
        val spring = Zeiteintrag(startMinute = minute("2026-03-08T06:30:00Z"),
            zone = "America/New_York").finish(minute("2026-03-08T07:30:00Z"))
        assertEquals("01:30", spring.displayTime(spring.startMinute, Locale.US, true))
        assertEquals("03:30", spring.displayTime(spring.endMinute!!, Locale.US, true))
        assertEquals(60L, spring.totalMinutes())
        val autumn = Zeiteintrag(startMinute = minute("2026-11-01T05:30:00Z"),
            zone = "America/New_York").finish(minute("2026-11-01T06:30:00Z"))
        assertEquals(autumn.localStart(), autumn.localEnd())
        assertEquals(60L, autumn.totalMinutes())
    }

    @Test fun impossibleRunningPausesAndOutOfRangeClockChangesAreRejected() {
        assertTrue(runCatching { Zeiteintrag(startMinute = 100, pauseMinutes = Long.MAX_VALUE).validate() }.isFailure)
        assertTrue(runCatching { Zeiteintrag(startMinute = 100, pauseMinute = 110, pauseMinutes = 11).validate() }.isFailure)
        assertTrue(runCatching { Zeiteintrag(startMinute = 100).pause(Zeiteintrag.MAX_MINUTE + 1) }.isFailure)
        assertTrue(runCatching { Zeiteintrag(startMinute = 100).pause(110).resume(Zeiteintrag.MAX_MINUTE + 1) }.isFailure)
    }

    @Test fun serializationAlwaysPinsZoneAndIdentityInsteadOfUsingFutureDeviceDefaults() {
        val record = Zeiteintrag(startMinute = 100)
        val encoded = Json.encodeToString(Zeiteintrag.serializer(), record)
        val objectValue = Json.parseToJsonElement(encoded).jsonObject
        assertTrue(objectValue.keys.containsAll(listOf("zone", "id", "modifiedMs")))
        assertEquals(record, Json.decodeFromString(Zeiteintrag.serializer(), encoded))
    }

    @Test fun draftPauseContinuesUntilSaveAndLocalizedDurationRemainsMinuteBased() {
        val original = Zeiteintrag(startMinute = 1000).pause(1010)
        val draft = ZeitEntwurf(original, pause = "10")
        val saved = draft.record(now = 1030)
        assertEquals(20L, saved.pauseMinutes)
        assertEquals(1030L, saved.pauseMinute)
        assertEquals(10L, saved.totalMinutes(1040))
        val closed = draft.copy(end = 1025).record(now = 1030)
        assertEquals(15L, closed.pauseMinutes)
        assertEquals(10L, closed.totalMinutes())
        val manual = draft.copy(pause = "٣٠", pauseEdited = true, duration = "١:١٥").record(now = 1030)
        assertEquals(1105L, manual.endMinute)
        assertEquals(75L, manual.totalMinutes())
    }
}
