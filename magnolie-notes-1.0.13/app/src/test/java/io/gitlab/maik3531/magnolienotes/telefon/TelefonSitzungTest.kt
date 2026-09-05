package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TelefonSitzungTest {
    @Test fun `Organizerbindung vergleicht nur kryptografische device id`() {
        val peer = TelefonPeer("22222222-2222-4222-8222-222222222222", "Gleicher Name", "pin")
        assertTrue(organizerPairingAllowed(null, "33333333-3333-4333-8333-333333333333"))
        assertTrue(organizerPairingAllowed(peer, peer.device_id))
        assertFalse(organizerPairingAllowed(peer, "33333333-3333-4333-8333-333333333333"))
        assertFalse(organizerPairingAllowed(peer.copy(display_name = "Anderer Name",
            bluetooth_address = "AA:BB:CC:DD:EE:FF"), "33333333-3333-4333-8333-333333333333"))
    }

    @Test fun `session start entspricht gemeinsamem Golden Vector`() {
        val root = TelefonKanonisch.json.parseToJsonElement(javaClass.classLoader!!
            .getResource("telefon-protokoll-vektoren.json")!!.readText()).jsonObject
        val pairing = root.getValue("pairing").jsonObject
        val session = root.getValue("session").jsonObject
        val identity = TelefonIdentitaet(device_id = "11111111-1111-4111-8111-111111111111", display_name = "Telefon",
            static_public = pairing.text("phone_static_public"), wrapped_private = "")
        val peer = TelefonPeer("22222222-2222-4222-8222-222222222222", "Arbeitsplatz", pairing.text("desktop_static_public"))
        val start0 = session.getValue("session_start_without_mac").jsonObject
        val fixed = TelefonSession.start(identity, peer, pairing.bytes("phone_static_private", 32),
            TelefonKrypto.b64(start0.text("sid"), 16),
            pairing.bytes("phone_ephemeral_private", 32) to pairing.bytes("phone_ephemeral_public", 32),
            TelefonKrypto.b64(start0.text("nonce"), 32))
        assertEquals(session.getValue("session_start").jsonObject, fixed.start)
        assertArrayEquals(session.bytes("static_root", 32), fixed.staticRoot)
        assertArrayEquals(session.bytes("auth_key", 32), fixed.authKey)
    }

    @Test fun `session ready ist exakt und versionsgebunden`() {
        val ready = buildJsonObject {
            put("type", JsonPrimitive("session_ready")); put("connection_id", JsonPrimitive("33333333-3333-4333-8333-333333333333"))
            put("capabilities_revision", JsonPrimitive(1)); put("last_received_seq", JsonPrimitive(-1))
        }
        TelefonNachrichten.validateReady(ready)
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validateReady(JsonObject(ready + ("extra" to JsonPrimitive(true))))
        }
    }

    @Test fun `Queue Nachricht behaelt ID und Retryfolge`() {
        val id = "33333333-3333-4333-8333-333333333333"
        val message = TelefonNachrichten.message("device_status.request", buildJsonObject {
            put("request_id", JsonPrimitive("44444444-4444-4444-8444-444444444444"))
        }, 60_000, 1_000, id)
        assertEquals(id, message.string("message_id"))
        TelefonNachrichten.validate(message, 1_000)
        assertThrows(TelefonProtokollFehler::class.java) { TelefonNachrichten.validate(message, -300_001) }
        assertEquals(listOf(2_000L, 3_000L, 6_000L, 11_000L, 31_000L, 61_000L),
            (0..5).map { TelefonWiederholung.naechsterVersuch(1_000, it) })
        assert(TelefonWiederholung.naechsterVersuch(1_000, 6) in 241_000L..361_000L)
    }

    @Test fun `Dedupe wiederholt Wirkung nicht und reproduziert terminales Ack`() {
        assertEquals("duplicate" to "none", TelefonNachrichten.duplicateAck("accepted", "none"))
        assertEquals("rejected" to "invalid_schema", TelefonNachrichten.duplicateAck("rejected", "invalid_schema"))
    }

    @Test fun `Capabilities und Grants enthalten keine Telefonrechte`() {
        val capabilities = TelefonNachrichten.capabilities()
        val grants = TelefonNachrichten.grants()
        assertEquals(setOf("revision", "items"), capabilities.keys)
        assertEquals(setOf("device_status", "selected_notifications_readonly", "dial_request",
            "incoming_call_state", "incoming_call_number", "answer_call", "end_call",
            "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync", "transport.bluetooth_rfcomm"),
            (capabilities["items"] as JsonObject).keys)
        assertEquals(setOf("device_status", "selected_notifications_readonly", "dial_request",
            "incoming_call_state", "incoming_call_number", "answer_call", "end_call",
            "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync"),
            (grants["grants"] as JsonObject).keys)
        assertEquals(listOf("1", "2", "3"), (((capabilities["items"] as JsonObject)["device_status"] as JsonObject)
            ["versions"] as kotlinx.serialization.json.JsonArray).map { (it as JsonPrimitive).content })
        assertEquals(listOf("1", "2", "3"), (((capabilities["items"] as JsonObject)["personal_tasks_sync"] as JsonObject)
            ["versions"] as kotlinx.serialization.json.JsonArray).map { (it as JsonPrimitive).content })
        assertEquals(false, ((grants["grants"] as JsonObject)["dial_request"] as JsonPrimitive).content.toBoolean())
    }

    @Test fun `Control Vertrag entspricht gemeinsamem Golden`() {
        val golden = TelefonKanonisch.json.parseToJsonElement(
            File("app/src/test/resources/telefon-control-contract.json").readText()).jsonObject
        assertEquals(golden.getValue("android_capabilities"), TelefonNachrichten.capabilities()["items"])
        assertEquals(golden.getValue("android_grants"), TelefonNachrichten.grants()["grants"])
        TelefonNachrichten.validate(TelefonNachrichten.message("incoming_call_state.event",
            golden.getValue("incoming_call_state_v2").jsonObject, 60_000, 1_000), 1_000)
        TelefonNachrichten.validate(TelefonNachrichten.message("capabilities.update", buildJsonObject {
            put("revision", JsonPrimitive(1)); put("items", golden.getValue("desktop_capabilities"))
        }, 86_400_000))
        TelefonNachrichten.validate(TelefonNachrichten.message("grants.update", buildJsonObject {
            put("revision", JsonPrimitive(1)); put("grants", golden.getValue("desktop_grants"))
        }, 86_400_000))
    }

    @Test fun `unbekannte Capability wird abgewiesen und Pong ist protokollkonform`() {
        val capabilities = TelefonNachrichten.capabilities().let { body ->
            val items = body["items"] as JsonObject
            JsonObject(body + ("items" to JsonObject(items + ("future.module" to buildJsonObject {
                put("available", JsonPrimitive(false)); put("reason", JsonPrimitive("not_implemented"))
                put("versions", buildJsonArray { add(JsonPrimitive(1)); add(JsonPrimitive(2)) })
            }))))
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validate(TelefonNachrichten.message("capabilities.update", capabilities, 86_400_000))
        }
        TelefonNachrichten.validateHeartbeat(buildJsonObject {
            put("type", JsonPrimitive("pong")); put("ping_id", JsonPrimitive("33333333-3333-4333-8333-333333333333")); put("sent_ms", JsonPrimitive(1))
        })
    }

    private fun JsonObject.text(name: String) = (getValue(name) as JsonPrimitive).content
    private fun JsonObject.bytes(name: String, length: Int) = TelefonKrypto.b64(text(name), length)
}
