package io.gitlab.maik3531.magnolienotes.daten

import java.time.Instant
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ZeitPausenTest {
    private fun minute(time: String) = Instant.parse(time).epochSecond / 60
    private val midday = listOf(ZeitPausenfenster(12 * 60, 12 * 60 + 30))

    @Test fun fixedThirtyAndLaterManualFifteenProduceExactlyFortyFive() {
        val from = minute("2026-10-04T08:00:00Z")
        val until = minute("2026-10-04T17:00:00Z")
        val manual = listOf(minute("2026-10-04T15:00:00Z") to minute("2026-10-04T15:15:00Z"))
        assertEquals(45L, ZeitPausen.minutes(from, until, "UTC", midday, manual))
        assertEquals(495L, until - from - ZeitPausen.minutes(from, until, "UTC", midday, manual))
    }

    @Test fun anotherManualPauseCannotStartDuringAFixedPauseAndOnlyRecordedPortionsCount() {
        val from = minute("2026-10-04T08:00:00Z")
        val until = minute("2026-10-04T17:00:00Z")
        val overlap = listOf(minute("2026-10-04T12:15:00Z") to minute("2026-10-04T12:45:00Z"))
        assertThrows(IllegalArgumentException::class.java) { ZeitPausen.minutes(from, until, "UTC", midday, overlap) }
        assertEquals(10L, ZeitPausen.minutes(from, minute("2026-10-04T12:10:00Z"), "UTC", midday))
        assertEquals(10L, ZeitPausen.minutes(minute("2026-10-04T12:20:00Z"), until, "UTC", midday))
        assertEquals(0L, ZeitPausen.minutes(from, minute("2026-10-04T11:59:00Z"), "UTC", midday))
    }

    @Test fun earlierManualPauseReplacesTheWholeFixedOccurrenceIncludingItsUnusedRemainder() {
        val from = minute("2026-10-04T08:00:00Z")
        val until = minute("2026-10-04T17:00:00Z")
        val manualStart = minute("2026-10-04T11:55:00Z")
        val result = ZeitPausen.calculate(from, until, "UTC", midday,
            listOf(manualStart to minute("2026-10-04T12:10:00Z")))
        assertEquals(15L, result.minutes)
        assertEquals(30L, result.replacements.single().durationMinutes)
        assertEquals(manualStart, result.replacements.single().manualStart)
        val preciseStart = manualStart * 60000 + 17000
        val alarm = ZeitPausenwecker(preciseStart).adoptFixed(result.replacements.single().durationMinutes.toInt())
        assertEquals(preciseStart + 29 * 60000L, alarm.warningMs())
        val repeated = ZeitPausen.calculate(from, until, "UTC", midday,
            listOf(manualStart to minute("2026-10-04T12:10:00Z")),
            replacedFixedStarts = setOf(result.replacements.single().fixedStart))
        assertEquals(15L, repeated.minutes)
        assertTrue(repeated.replacements.isEmpty())
    }

    @Test fun scheduledStartDuringOngoingManualPauseProvidesTheReplacementNoticeAndDuration() {
        val start = minute("2026-10-04T11:55:00Z")
        val result = ZeitPausen.calculate(minute("2026-10-04T08:00:00Z"), minute("2026-10-04T12:00:00Z"),
            "UTC", midday, activeManualStart = start)
        assertEquals(5L, result.minutes)
        assertEquals(30L, result.replacements.single().durationMinutes)
    }

    @Test fun overnightFixedBreakKeepsItsDateBoundary() {
        val from = minute("2026-10-04T23:40:00Z")
        val until = minute("2026-10-05T00:10:00Z")
        assertEquals(20L, ZeitPausen.minutes(from, until, "UTC", listOf(ZeitPausenfenster(23 * 60 + 50, 20))))
    }

    @Test fun alarmUsesOriginalPauseStartAndLateActivationDoesNotResetIt() {
        val started = 1000045L
        val clock = ZeitPausenwecker(started).select(15)
        assertEquals(started + 14 * 60000L, clock.nextMs(started + 10 * 60000L))
        val late = clock.nextMs(started + 16 * 60000L)
        assertEquals(started + 16 * 60000L, late)
        val fired = clock.markSignaled(15, late!!)
        assertNull(fired.nextMs(late))
        val restarted = Json.decodeFromString(ZeitPausenwecker.serializer(), Json.encodeToString(ZeitPausenwecker.serializer(), fired))
        assertNull(restarted.select(15).nextMs(late))
        assertEquals(started + 29 * 60000L, restarted.select(30).nextMs(late))
        assertNull(restarted.select(null).nextMs(late))
    }
}
