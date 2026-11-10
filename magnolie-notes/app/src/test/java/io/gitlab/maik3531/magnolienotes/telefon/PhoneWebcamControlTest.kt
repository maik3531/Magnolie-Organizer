package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PhoneWebcamControlTest {
    private fun packet(op: String = "probe") = buildJsonObject {
        put("version", 24); put("request_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        put("nonce", "b".repeat(64)); put("op", op)
        if (op in setOf("offer", "prepared", "send", "stop", "error")) put("session", "c".repeat(32))
        if (op == "offer") { put("secret", "d".repeat(64)); put("port", 24401); put("muted", false); put("front", false) }
        if (op in setOf("unavailable", "error")) put("reason", "disabled")
    }
    private fun changed(body: JsonObject, key: String, value: JsonElement) = JsonObject(body + (key to value))

    @Test fun exactDirectionSpecificPacketsMatchThePcControlContractWithoutAuthorityFields() {
        for ((op, kind) in listOf("probe" to PhoneWebcamControl.REQUEST, "offer" to PhoneWebcamControl.REPORT,
            "unavailable" to PhoneWebcamControl.REPORT, "prepared" to PhoneWebcamControl.REQUEST,
            "send" to PhoneWebcamControl.REPORT, "stop" to PhoneWebcamControl.REQUEST,
            "stop" to PhoneWebcamControl.REPORT, "error" to PhoneWebcamControl.REQUEST, "error" to PhoneWebcamControl.REPORT)) {
            PhoneWebcamControl.validateBody(packet(op), kind)
        }
    }

    @Test fun oppositeRolesCannotIssueOffersOrAuthorizeWireSend() {
        for ((op, kind) in listOf("probe" to PhoneWebcamControl.REPORT, "offer" to PhoneWebcamControl.REQUEST,
            "unavailable" to PhoneWebcamControl.REQUEST, "prepared" to PhoneWebcamControl.REPORT, "send" to PhoneWebcamControl.REQUEST)) {
            assertThrows(IllegalArgumentException::class.java) { PhoneWebcamControl.validateBody(packet(op), kind) }
        }
    }

    @Test fun malformedOfferCannotSubstituteStringsBooleansOtherVersionsOrWeakIdentities() {
        val original = packet("offer")
        val bad = listOf("version" to JsonPrimitive(true), "version" to JsonPrimitive("24"),
            "version" to JsonPrimitive(21), "version" to JsonPrimitive(22), "version" to JsonPrimitive(23),
            "request_id" to JsonPrimitive("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            "request_id" to JsonPrimitive("aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa"),
            "nonce" to JsonPrimitive("b".repeat(63)), "nonce" to JsonPrimitive("B".repeat(64)), "nonce" to JsonNull,
            "session" to JsonPrimitive("c".repeat(31)), "session" to JsonPrimitive("C".repeat(32)),
            "secret" to JsonPrimitive("d".repeat(63)), "port" to JsonPrimitive(1023), "port" to JsonPrimitive(65536),
            "port" to JsonPrimitive(true), "port" to JsonPrimitive("24401"), "muted" to JsonPrimitive("false"),
            "muted" to JsonPrimitive(0), "front" to JsonNull, "op" to JsonArray(listOf(JsonPrimitive("offer"))))
        for ((key, value) in bad) assertThrows(IllegalArgumentException::class.java) {
            PhoneWebcamControl.validateBody(changed(original, key, value), PhoneWebcamControl.REPORT)
        }
    }

    @Test fun noMissingExtraFrameUrlOrPermissionFieldsInSmallControlOffer() {
        val original = packet("offer")
        for (key in original.keys) assertThrows(IllegalArgumentException::class.java) {
            PhoneWebcamControl.validateBody(JsonObject(original - key), PhoneWebcamControl.REPORT)
        }
        for (key in listOf("url", "video", "audio", "permission", "ready")) assertThrows(IllegalArgumentException::class.java) {
            PhoneWebcamControl.validateBody(changed(original, key, JsonPrimitive(true)), PhoneWebcamControl.REPORT)
        }
        assertEquals(JsonPrimitive(false), original["muted"])
    }

    @Test fun messageEnvelopeHasBoundedLifetimeAndSizeAndDoesNotGrantAnything() {
        val body = packet("offer")
        val message = TelefonNachrichten.message(PhoneWebcamControl.REPORT, body, 60_000, now = 10_000)
        assertTrue(PhoneWebcamControl.reserved(message))
        assertEquals(body, PhoneWebcamControl.validateMessage(message, 10_000))
        assertThrows(IllegalArgumentException::class.java) {
            PhoneWebcamControl.validateMessage(TelefonNachrichten.message(PhoneWebcamControl.REPORT, body, 60_001, now = 10_000), 10_000)
        }
        assertThrows(IllegalArgumentException::class.java) {
            PhoneWebcamControl.validateMessage(changed(message, "body", changed(body, "padding", JsonPrimitive("x".repeat(4096)))), 10_000)
        }
    }

    @Test fun defaultAndFullNotesCapabilitiesDoNotGainAnUnknownKeyOrASeventeenthVersion() {
        val standard = TelefonCapabilities.phase1()
        val full = TelefonCapabilities.phase1(identifiers = true, contactRead = true, contactGroupsWrite = true,
            contactValuesWrite = true, contactGroupTitlesWrite = true, fileHandlersReady = true, videoHandlersReady = true)
        assertEquals(standard.keys, full.keys)
        assertEquals(16, full.getValue("device_status").versions.size)
        assertFalse(full.getValue("device_status").versions.contains(PhoneWebcamControl.DISCOVERY_VERSION))
        TelefonNachrichten.validate(TelefonNachrichten.message("capabilities.update", TelefonNachrichten.capabilities(itemsValue = full), 60_000))
    }
}
