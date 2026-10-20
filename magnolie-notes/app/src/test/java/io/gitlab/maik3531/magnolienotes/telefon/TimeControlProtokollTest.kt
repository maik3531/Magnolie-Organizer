package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class TimeControlProtokollTest {
    @Test fun sharedDesktopPhoneVectorsHaveTheSameStrictContract() {
        val root = generateSequence(java.io.File(System.getProperty("user.dir"))) { it.parentFile }
            .first { java.io.File(it, "contracts/time-control-v13.json").isFile }
        val vectors = TelefonKanonisch.json.parseToJsonElement(java.io.File(root, "contracts/time-control-v13.json").readText()).jsonObject
        vectors.getValue("requests").jsonArray.forEach { TimeControlProtokoll.validateRequest(it.jsonObject) }
        vectors.getValue("reports").jsonArray.forEach { TimeControlProtokoll.validateReport(it.jsonObject) }
    }
    @Test fun readAndCommandsAreDistinctStrictMessages() {
        val requestId = UUID.randomUUID().toString()
        val read = TimeControlProtokoll.request(requestId)
        TelefonNachrichten.validate(TelefonNachrichten.message(TimeControlProtokoll.REQUEST, read, 60000))
        val state = ZeiterfassungStand(enabled = true)
        val command = ZeitSteuerBefehl(UUID.randomUUID().toString(), "start", ZeitSteuerung.revision(state), activity = "Native work")
        val body = TimeControlProtokoll.request(requestId, "native-epoch", command)
        assertEquals(command, TimeControlProtokoll.command(body))
        assertThrows(TelefonProtokollFehler::class.java) { TimeControlProtokoll.validateRequest(JsonObject(body + ("at_ms" to JsonPrimitive(123)))) }
        assertThrows(IllegalArgumentException::class.java) { TimeControlProtokoll.validateRequest(JsonObject(read + ("entry_id" to JsonPrimitive(command.operationId)))) }
    }

    @Test fun nativeReportsSeparateCurrentStateFromActualCommandPersistence() {
        val state = ZeiterfassungStand(enabled = true)
        val read = TimeControlProtokoll.report(UUID.randomUUID().toString(), state, "", 1760000040000)
        assertEquals(JsonPrimitive(false), read["persisted"])
        val command = ZeitSteuerBefehl(UUID.randomUUID().toString(), "start", ZeitSteuerung.revision(state))
        val applied = ZeitSteuerung.apply(state, command, "a".repeat(64), "", 1760000040000, "UTC")
        val report = TimeControlProtokoll.report(UUID.randomUUID().toString(), applied.state, "", 1760000040000, applied, "requested")
        TelefonNachrichten.validate(TelefonNachrichten.message(TimeControlProtokoll.REPORT, report, 60000))
        assertEquals(JsonPrimitive(true), report["persisted"])
        assertEquals(JsonPrimitive(command.operationId), report["applied_entry_id"])
        assertThrows(IllegalArgumentException::class.java) { TimeControlProtokoll.validateReport(JsonObject(read + ("persisted" to JsonPrimitive(true)))) }
    }

    @Test fun rejectedReportsContainNoTimerDataOrSaveClaim() {
        val rejected = TimeControlProtokoll.rejected(UUID.randomUUID().toString(), UUID.randomUUID().toString(), "not_granted")
        assertEquals(JsonPrimitive(""), rejected["revision"])
        assertTrue(rejected.getValue("entries").jsonArray.isEmpty())
        assertThrows(IllegalArgumentException::class.java) { TimeControlProtokoll.validateReport(JsonObject(rejected + ("enabled" to JsonPrimitive(true)))) }
        assertThrows(IllegalArgumentException::class.java) { TimeControlProtokoll.validateReport(JsonObject(rejected + ("error" to JsonPrimitive("none")))) }
    }

    @Test fun frameLifetimeAndFullUtf8BudgetRemainBounded() {
        val read = TimeControlProtokoll.request(UUID.randomUUID().toString())
        assertThrows(TelefonProtokollFehler::class.java) { TelefonNachrichten.validate(TelefonNachrichten.message(TimeControlProtokoll.REQUEST, read, 60001)) }
        assertThrows(TelefonProtokollFehler::class.java) { TimeControlProtokoll.validateRequest(JsonObject(read + ("format" to JsonPrimitive("13")))) }
        assertThrows(IllegalArgumentException::class.java) { TimeControlProtokoll.validateRequest(JsonObject(read + ("action" to JsonPrimitive("execute")))) }
    }
}
