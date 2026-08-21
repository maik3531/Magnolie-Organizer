package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PersonalRunAuthenticationTest {
    private val request = buildJsonObject {
        put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive("11111111-1111-4111-8111-111111111111"))
        put("trigger", JsonPrimitive("auto_wifi")); put("modules", JsonArray(listOf(JsonPrimitive("notes"))))
    }
    private val index = PersonalRunIndex("22222222-2222-4222-8222-222222222222",
        "11111111-1111-4111-8111-111111111111", "auto_wifi", "wifi_only", 10, 20)

    @Test fun `authenticated run envelope rejects every security index mutation`() {
        val envelope = PersonalRunAuthentication.envelope(index, request)
        assertEquals(request, PersonalRunAuthentication.authenticate(envelope, index))
        val mutations = listOf(
            index.copy(peerId = "33333333-3333-4333-8333-333333333333"),
            index.copy(runId = "44444444-4444-4444-8444-444444444444"),
            index.copy(trigger = "manual"), index.copy(transportPolicy = "any"),
            index.copy(createdMs = 11), index.copy(expiresMs = 21),
            index.copy(appliedRequest = true), index.copy(appliedReply = true),
            index.copy(responded = true), index.copy(reported = true)
        )
        mutations.forEach { altered -> assertThrows(TelefonProtokollFehler::class.java) {
            PersonalRunAuthentication.authenticate(envelope, altered)
        } }
        val alteredModules = JsonObject(envelope + ("modules" to JsonArray(listOf(JsonPrimitive("tasks")))))
        assertThrows(TelefonProtokollFehler::class.java) {
            PersonalRunAuthentication.authenticate(alteredModules, index)
        }
    }

    @Test fun `effective policy is derived from authenticated trigger and expiry fails closed`() {
        val wifiEnvelope = PersonalRunAuthentication.envelope(index, request)
        assertEquals("wifi_only", PersonalRunAuthentication.authenticate(wifiEnvelope,
            PersonalRunAuthentication.requireCurrent(index, 19)).let { index.transportPolicy })
        val manualRequest = JsonObject(request + ("trigger" to JsonPrimitive("manual")))
        val manual = index.copy(trigger = "manual", transportPolicy = "any")
        assertEquals("any", PersonalRunAuthentication.authenticate(
            PersonalRunAuthentication.envelope(manual, manualRequest), manual).let { manual.transportPolicy })
        assertThrows(TelefonProtokollFehler::class.java) {
            PersonalRunAuthentication.requireCurrent(index, 20)
        }
    }

    @Test fun `wire expiry stays exact cannot be extended and rejects expiry`() {
        val now = 1_000_000L
        val oneHour = now + 3_600_000L
        assertEquals(oneHour, PersonalRunAuthentication.effectiveExpiry(oneHour, now))
        assertEquals(oneHour, PersonalRunAuthentication.effectiveExpiry(now + 86_400_000L, now, oneHour))
        assertThrows(TelefonProtokollFehler::class.java) {
            PersonalRunAuthentication.effectiveExpiry(now, now)
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            PersonalRunAuthentication.effectiveExpiry(now + 3_600_000L, now, now)
        }
    }
}
