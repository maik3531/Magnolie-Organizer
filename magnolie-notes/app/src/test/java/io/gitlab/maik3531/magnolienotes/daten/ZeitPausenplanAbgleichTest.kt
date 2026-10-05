package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.telefon.TimeSyncProtokoll
import java.time.Instant
import java.util.UUID
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ZeitPausenplanAbgleichTest {
    private fun ms(time: String) = Instant.parse("2026-10-04T${time}Z").toEpochMilli()
    private fun started() = ZeiterfassungStand(enabled = true,
        fixedPauses = listOf(ZeitPausenfenster(720, 750)),
        wifi = ZeitWlanAutomatik(enabled = true, ssid = "Private WLAN selection"),
        endAlarm = ZeitFeierabendwecker(clockMinute = 960, autoStop = true))
        .start(Zeiteintrag(startMinute = ms("08:00:00") / 60000, zone = "UTC"))
        .prepareSharedPlans(ms("08:00:00"))

    private fun wire(state: ZeiterfassungStand) = buildJsonObject { put("entries", TimeSyncProtokoll.encodeRecords(state.entries)) }

    @Test fun receiverWithoutLocalAutomationCalculatesTheSameLivePauseWithoutChangingTheWireClock() {
        val source = started()
        val packet = wire(source)
        val incoming = TimeSyncProtokoll.decodeRecords(packet)
        val received = ZeiterfassungAbgleich.merge(ZeiterfassungStand(), incoming).state
        assertTrue(received.pauseRuns.isEmpty())
        val entry = received.entries.single()
        assertTrue(received.isPaused(entry, ms("12:10:00") / 60000))
        assertEquals(10L, received.projected(entry, ms("12:10:00") / 60000).pausedMinutes())
        assertEquals(30L, received.projected(entry, ms("12:40:00") / 60000).pausedMinutes())
        assertEquals(packet, wire(received))
        assertFalse(packet.toString().contains("Private WLAN selection"))
        assertFalse(packet.toString().contains("endAlarm"))
        assertEquals(source, source.prepareSharedPlans(ms("12:40:00")))
    }

    @Test fun replacementIsOneCausalChangeAndAFinishedRecordNeedsNoLivePlan() {
        var state = started()
        state = state.pause(state.entries.single(), ms("11:55:17")).prepareSharedPlans(ms("11:55:17"))
        val before = state.entries.single()
        state = state.evaluatePauses(ms("12:00:00") / 60000).prepareSharedPlans(ms("12:00:00"))
        val replacement = state.entries.single()
        assertTrue(replacement.clock.getValue(state.actor) > before.clock.getValue(state.actor))
        assertEquals(setOf(ms("12:00:00") / 60000), replacement.pausePlan!!.replaced)
        assertEquals(state, state.evaluatePauses(ms("12:01:00") / 60000).prepareSharedPlans(ms("12:01:00")))
        state = state.resume(replacement, ms("12:10:00")).prepareSharedPlans(ms("12:10:00"))
        val received = ZeiterfassungAbgleich.merge(ZeiterfassungStand(), TimeSyncProtokoll.decodeRecords(wire(state))).state
        assertEquals(15L, received.projected(received.entries.single(), ms("12:40:00") / 60000).pausedMinutes())
        val finished = state.finish(state.entries.single(), ms("17:00:00")).prepareSharedPlans(ms("17:00:00"))
        assertNull(finished.entries.single().pausePlan)
        assertEquals(15L, TimeSyncProtokoll.decodeRecords(wire(finished)).single().pauseMinutes)
    }

    @Test fun desktopTextEditsPreserveLocalPreciseAlarmAndCannotImportAlarmPermissions() {
        var state = started()
        state = state.pause(state.entries.single(), ms("11:55:17")).prepareSharedPlans(ms("11:55:17"))
        val original = state.entries.single()
        val edited = original.copy(note = "Desktop edit", clock = original.clock + (UUID.randomUUID().toString() to 1L))
        val merged = ZeiterfassungAbgleich.merge(state, listOf(edited)).state
        val local = merged.pauseRuns.getValue(original.id)
        assertEquals(ms("11:55:17"), local.alarm!!.startedMs)
        assertTrue(local.endAlarm.autoStop)
        assertEquals(state.wifi, merged.wifi)
        assertEquals(merged, merged.prepareSharedPlans(ms("12:00:00")))
        val plainReceiver = ZeiterfassungAbgleich.merge(ZeiterfassungStand(), listOf(edited)).state
        assertFalse(plainReceiver.endAlarm.autoStop)
        assertTrue(plainReceiver.pauseRuns.isEmpty())
    }

    @Test fun timingCorrectionPublishesTheEditedBaselineInsteadOfOldFixedWindows() {
        val state = started()
        val original = state.entries.single()
        val corrected = state.replace(original, original.copy(pauseMinutes = 42)).prepareSharedPlans(ms("16:00:00"))
        val received = TimeSyncProtokoll.decodeRecords(wire(corrected)).single()
        assertNull(received.pausePlan)
        assertEquals(42L, received.pauseMinutes)
        assertTrue(corrected.pauseRuns.getValue(original.id).endAlarm.autoStop)
    }

    @Test fun malformedOrPrivatePlanFieldsAreRejectedBeforeDeserialization() {
        val record = TimeSyncProtokoll.encodeRecords(started().entries).single().jsonObject
        val plan = record.getValue("pausePlan").jsonObject
        fun checkInvalid(value: JsonObject) {
            val body = buildJsonObject { put("entries", JsonArray(listOf(JsonObject(record + ("pausePlan" to value))))) }
            assertThrows(Exception::class.java) { TimeSyncProtokoll.decodeRecords(body) }
        }
        checkInvalid(JsonObject(plan + ("endAlarm" to JsonObject(emptyMap()))))
        checkInvalid(JsonObject(plan + ("fixed" to buildJsonArray { add(buildJsonObject {
            put("start", "720"); put("end", 750)
        }) })))
        checkInvalid(JsonObject(plan + ("replaced" to JsonArray(listOf(JsonPrimitive(20), JsonPrimitive(20))))))
        checkInvalid(JsonObject(plan + ("fixedEnds" to buildJsonObject { put("01", 2) })))
    }

    @Test fun authoritativeDesktopDeletionStopsTheLocalRunAndDesktopRestoreRemainsCausal() {
        val state = started()
        val entry = state.entries.single()
        val desktop = UUID.randomUUID().toString()
        val tombstone = Zeiteintrag(id = entry.id, startMinute = 0, endMinute = 0, zone = "UTC",
            deleted = true, clock = entry.clock + (desktop to 1L))
        assertThrows(IllegalArgumentException::class.java) { ZeiterfassungAbgleich.merge(state, listOf(tombstone)) }
        val removed = ZeiterfassungAbgleich.merge(state, listOf(tombstone), fromOrganizer = true, nowMs = ms("17:00:00")).state
        assertTrue(removed.entries.single().deleted)
        assertTrue(removed.pauseRuns.isEmpty())
        assertEquals("", removed.entries.single().note)
        assertEquals(ms("18:00:00"), removed.wifi.blockedUntilMs)
        assertEquals(removed, ZeiterfassungAbgleich.merge(removed, listOf(tombstone), fromOrganizer = true, nowMs = ms("17:30:00")).state)
        val restored = entry.copy(endMinute = ms("17:00:00") / 60000, pauseMinutes = 30, pausePlan = null,
            clock = tombstone.clock + (desktop to 2L))
        assertFalse(ZeiterfassungAbgleich.merge(removed, listOf(restored), fromOrganizer = true).state.entries.single().deleted)
    }
}
