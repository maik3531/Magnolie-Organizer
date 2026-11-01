package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.telefon.TimeSyncProtokoll
import kotlinx.serialization.json.*
import java.util.Locale
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class ZeitStartUebersichtTest {
    private val now = 1793505600000L
    private fun kind(state: ZeiterfassungStand): String {
        val encoded = Json.parseToJsonElement(Json.encodeToString(ZeiterfassungStand.serializer(), state)).jsonObject
        val id = state.entries.single().id
        return encoded["pauseRuns"]?.jsonObject?.get(id)?.jsonObject?.get("startKind")?.jsonPrimitive?.content.orEmpty()
    }

    @Test fun manualStartHasDurableLocalOriginWithoutChangingWireRecords() {
        val state = ZeiterfassungStand(enabled = true).start(Zeiteintrag(startMinute = now / 60000, zone = "UTC"))
        assertEquals("manual", kind(state))
        val restored = Json.decodeFromString(ZeiterfassungStand.serializer(), Json.encodeToString(ZeiterfassungStand.serializer(), state))
        assertEquals("manual", kind(restored))
        val wire = TimeSyncProtokoll.encodeRecords(state.entries).single().jsonObject
        assertFalse(wire.containsKey("startKind")); assertFalse(wire.containsKey("pauseRuns"))
    }

    @Test fun wifiStartIsNotMisrepresentedAsManual() {
        val state = ZeiterfassungStand(enabled = true, wifi = ZeitWlanAutomatik(true, "Synthetic WLAN"))
            .startFromWifi("Synthetic WLAN", now, now, "Synthetic")
        assertEquals("wifi", kind(state))
        assertEquals(state, state.startFromWifi("Synthetic WLAN", now + 1, now + 1, "Synthetic"))
    }

    @Test fun nativeComputerStartKeepsItsOwnOriginAndRetryIdentity() {
        val before = ZeiterfassungStand(enabled = true)
        val command = ZeitSteuerBefehl(UUID.randomUUID().toString(), "start", ZeitSteuerung.revision(before))
        val result = ZeitSteuerung.apply(before, command, "a".repeat(64), "owned-epoch", now, "UTC")
        assertEquals("computer", kind(result.state))
        val replay = ZeitSteuerung.apply(result.state, command, "a".repeat(64), "owned-epoch", now + 1, "UTC")
        assertTrue(replay.duplicate); assertEquals(result.state, replay.state)
    }

    @Test fun runningDurationAndStartTimeStayMinutePreciseWithoutStorageMutation() {
        val state = ZeiterfassungStand(enabled = true).start(Zeiteintrag(startMinute = now / 60000, zone = "UTC"))
        val before = Json.encodeToString(ZeiterfassungStand.serializer(), state)
        val entry = state.entries.single()
        assertEquals("1:05", Zeiteintrag.duration(entry.grossMinutes(entry.startMinute + 65), Locale.ROOT))
        assertTrue(entry.displayTime(entry.startMinute, Locale.ROOT, true).matches(Regex("[0-9]{2}:[0-9]{2}")))
        assertEquals(before, Json.encodeToString(ZeiterfassungStand.serializer(), state))
    }

    @Test fun localStartKindSurvivesPauseResumeCorrectionAndLocalTrashRestore() {
        var state = ZeiterfassungStand(enabled = true).start(Zeiteintrag(startMinute = now / 60000, zone = "UTC"))
        state = state.pause(state.entries.single(), now + 10 * 60000)
        assertEquals("manual", state.startKind(state.entries.single()))
        state = state.resume(state.entries.single(), now + 15 * 60000)
        state = state.replace(state.entries.single(), state.entries.single().copy(startMinute = now / 60000 - 1))
        assertEquals("manual", kind(state))
        state = state.removeLocal(state.entries, now + 20 * 60000)
        state = state.restoreLocal(state.trash.single().id, now + 21 * 60000)
        assertEquals("manual", state.startKind(state.entries.single()))
        val current = state.entries.single()
        assertEquals(26L, current.grossMinutes(now / 60000 + 25))
        assertEquals(21L, state.projected(current, now / 60000 + 25).totalMinutes(now / 60000 + 25))
    }

    @Test fun oldAndImportedEntriesDoNotAcquireAnInventedManualStart() {
        val started = ZeiterfassungStand(enabled = true).start(Zeiteintrag(startMinute = now / 60000, zone = "UTC"))
        val encoded = Json.parseToJsonElement(Json.encodeToString(ZeiterfassungStand.serializer(), started)).jsonObject
        val legacy = JsonObject(encoded + ("pauseRuns" to JsonObject(encoded.getValue("pauseRuns").jsonObject.mapValues { (_, run) ->
            JsonObject(run.jsonObject - "startKind") })))
        val restored = Json.decodeFromString(ZeiterfassungStand.serializer(), legacy.toString())
        assertEquals("", restored.startKind(restored.entries.single()))
        val imported = ZeiterfassungAbgleich.merge(ZeiterfassungStand(enabled = true), started.entries).state
        assertEquals("", imported.startKind(imported.entries.single()))
        assertEquals(started.entries.single(), imported.entries.single())
    }

    @Test fun anExistingNativeStartReceiptCanIdentifyAnOlderComputerStart() {
        val before = ZeiterfassungStand(enabled = true)
        val command = ZeitSteuerBefehl(UUID.randomUUID().toString(), "start", ZeitSteuerung.revision(before))
        val started = ZeitSteuerung.apply(before, command, "a".repeat(64), "owned-epoch", now, "UTC").state
        val legacy = started.copy(pauseRuns = started.pauseRuns.mapValues { (_, run) -> run.copy(startKind = "") })
        assertEquals("computer", legacy.startKind(legacy.entries.single()))
    }

    @Test fun unknownNewStartMethodsAreRejectedWithoutChangingTheBook() {
        val before = ZeiterfassungStand(enabled = true)
        assertTrue(runCatching { before.start(Zeiteintrag(startMinute = now / 60000), "invented") }.isFailure)
        assertTrue(before.entries.isEmpty()); assertTrue(before.pauseRuns.isEmpty())
    }
}
