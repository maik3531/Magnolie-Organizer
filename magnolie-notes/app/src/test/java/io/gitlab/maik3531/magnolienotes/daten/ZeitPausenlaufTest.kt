package io.gitlab.maik3531.magnolienotes.daten

import java.time.Instant
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ZeitPausenlaufTest {
    private fun ms(time: String) = Instant.parse("2026-10-04T${time}Z").toEpochMilli()
    private fun restart(state: ZeiterfassungStand) = Json.decodeFromString(ZeiterfassungStand.serializer(),
        Json.encodeToString(ZeiterfassungStand.serializer(), state)).validate()
    private fun started() = ZeiterfassungStand(enabled = true,
        fixedPauses = listOf(ZeitPausenfenster(720, 750))).start(
        Zeiteintrag(startMinute = ms("08:00:00") / 60000, zone = "UTC", modifiedMs = ms("08:00:00")))

    @Test fun fixedAndManualPausesReachTheStoredFinishedTotalAfterRestart() {
        var state = started()
        state = state.pause(state.entries.single(), ms("15:00:00"))
        state = restart(state)
        state = state.resume(state.entries.single(), ms("15:15:00"))
        state = restart(state).finish(state.entries.single(), ms("17:00:00"))
        assertEquals(45L, state.entries.single().pauseMinutes)
        assertEquals(495L, state.entries.single().totalMinutes())
        assertTrue(state.pauseRuns.isEmpty())
    }

    @Test fun replacementSurvivesRestartAndUsesThePreciseOriginalManualStart() {
        var state = started()
        state = state.pause(state.entries.single(), ms("11:55:17"))
        state = restart(state).evaluatePauses(ms("12:00:00") / 60000)
        val run = state.pauseRuns.values.single()
        assertEquals(ms("12:24:17"), run.alarm!!.warningMs())
        assertEquals(setOf(ms("12:00:00") / 60000), run.pendingNotices)
        assertEquals(state, restart(state).evaluatePauses(ms("12:05:00") / 60000))
        state = state.resume(state.entries.single(), ms("12:10:00"))
        state = restart(state).finish(state.entries.single(), ms("17:00:00"))
        assertEquals(15L, state.entries.single().pauseMinutes)
        assertNull(state.entries.single().pauseMinute)
    }

    @Test fun fixedPauseCannotBeStackedAndEndingItEarlyCountsOnlyItsActualPortion() {
        var state = started()
        val entry = state.entries.single()
        assertTrue(state.isPaused(entry, ms("12:10:00") / 60000))
        assertEquals(state, state.pause(entry, ms("12:10:00")))
        state = state.resume(entry, ms("12:10:00"))
        state = restart(state)
        assertFalse(state.isPaused(state.entries.single(), ms("12:11:00") / 60000))
        state = state.pause(state.entries.single(), ms("12:15:00"))
        state = state.resume(state.entries.single(), ms("12:20:00"))
        state = state.finish(state.entries.single(), ms("17:00:00"))
        assertEquals(15L, state.entries.single().pauseMinutes)
    }

    @Test fun settingsChangesDoNotRewriteTheActiveSnapshotOrFinishedRecords() {
        var state = started().copy(fixedPauses = listOf(ZeitPausenfenster(720, 780)))
        state = restart(state).finish(state.entries.single(), ms("17:00:00"))
        assertEquals(30L, state.entries.single().pauseMinutes)
        state = state.copy(fixedPauses = emptyList()).evaluatePauses(ms("18:00:00") / 60000)
        assertEquals(30L, state.entries.single().pauseMinutes)
    }

    @Test fun stoppingDuringAFixedWindowClipsAtTheRecordingEnd() {
        val state = started()
        assertEquals(10L, state.finish(state.entries.single(), ms("12:10:00")).entries.single().pauseMinutes)
    }

    @Test fun startingInsideAFixedWindowIsImmediatelyPausedWithoutChargingEarlierMinutes() {
        var state = ZeiterfassungStand(enabled = true, fixedPauses = listOf(ZeitPausenfenster(720, 750)))
            .start(Zeiteintrag(startMinute = ms("12:20:00") / 60000, zone = "UTC"))
        val entry = state.entries.single()
        assertTrue(state.isPaused(entry, entry.startMinute))
        assertEquals(0L, state.projected(entry, entry.startMinute).pausedMinutes(entry.startMinute))
        assertEquals(state, state.pause(entry, ms("12:20:00")))
        state = state.finish(entry, ms("17:00:00"))
        assertEquals(10L, state.entries.single().pauseMinutes)
    }

    @Test fun localTrashRoundTripRetainsTheEncryptedAutomationSnapshot() {
        val state = started()
        val removed = restart(state.removeLocal(state.entries, ms("10:00:00")))
        assertTrue(removed.pauseRuns.isEmpty())
        assertEquals(state.pauseRuns, removed.trash.single().pauseRuns)
        val restored = restart(removed.restoreLocal(removed.trash.single().id, ms("10:01:00")))
        assertEquals(state.pauseRuns, restored.pauseRuns)
        assertEquals(30L, restored.finish(restored.entries.single(), ms("17:00:00")).entries.single().pauseMinutes)
        assertTrue(removed.permanentlyRemoveLocal(removed.trash.single().id).trash.isEmpty())
    }

    @Test fun explicitCorrectionOverridesAutomaticPauseTotals() {
        val state = started()
        val entry = state.entries.single()
        val edited = state.replace(entry, entry.corrected(entry.startMinute, ms("17:00:00") / 60000, 42, "early", ""))
        assertEquals(42L, restart(edited).entries.single().pauseMinutes)
        assertTrue(edited.pauseRuns.isEmpty())
    }

    @Test fun editorShowsScheduledMinutesButTextOnlyEditsKeepThePrecisePauseAnchor() {
        val state = started().let { it.pause(it.entries.single(), ms("15:00:17")) }
        val original = state.entries.single()
        val draft = ZeitEntwurf(original, pauseRun = state.pauseRuns[original.id], note = "changed")
        assertEquals(40L, draft.pauseMinutes(ms("15:10:00") / 60000))
        val updated = state.replace(original, draft.record(ms("15:10:00") / 60000, ms("15:10:00")))
        assertEquals(ms("15:00:17"), updated.pauseRuns[original.id]!!.alarm!!.startedMs)
        assertEquals(original.pauseMinute, updated.entries.single().pauseMinute)
        val closed = draft.copy(end = ms("15:15:00") / 60000).record(ms("15:15:00") / 60000)
        assertEquals(45L, closed.pauseMinutes)
    }
}
