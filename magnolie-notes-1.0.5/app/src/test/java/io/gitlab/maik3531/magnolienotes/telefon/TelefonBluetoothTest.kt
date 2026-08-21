package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.baum.BluetoothTransport
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.UUID

class TelefonBluetoothTest {
    @Test fun `WLAN hat vor RFCOMM Prioritaet`() {
        val calls = mutableListOf<String>()
        val result = TelefonTransportwahl.oeffnen(true, "AA:BB", true,
            wifi = { calls += "wifi"; "w" }, bluetooth = { calls += "bluetooth"; "b" })
        assertEquals(TelefonTransportArt.WIFI to "w", result)
        assertEquals(listOf("wifi"), calls)
    }

    @Test fun `RFCOMM ist nur erlaubter Rueckfall`() {
        val result = TelefonTransportwahl.oeffnen(true, "AA:BB", true,
            wifi = { throw java.io.IOException("offline") }, bluetooth = { "b:$it" })
        assertEquals(TelefonTransportArt.BLUETOOTH to "b:AA:BB", result)
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonTransportwahl.oeffnen(false, "AA:BB", false, wifi = { "w" }, bluetooth = { "b" })
        }
    }

    @Test fun `Telefon UUID ist strikt von Baum UUID getrennt`() {
        assertEquals(UUID.fromString("7b1d9e2a-5c43-4f68-a172-9d30e6b4c851"),
            UUID.fromString(TelefonParameter.RFCOMM_UUID))
        assertNotEquals(BluetoothTransport.DIENST_UUID.toString(), TelefonParameter.RFCOMM_UUID)
    }

    @Test fun `falscher Peer wird im FS Handshake vor Persistierung abgewiesen`() {
        val (phonePrivate, phonePublic) = TelefonKrypto.schluesselpaar()
        val (_, desktopPublic) = TelefonKrypto.schluesselpaar()
        val identity = TelefonIdentitaet(device_id = "11111111-1111-4111-8111-111111111111",
            display_name = "Phone", static_public = TelefonKrypto.b64(phonePublic), wrapped_private = "")
        val peer = TelefonPeer("22222222-2222-4222-8222-222222222222", "Desktop", TelefonKrypto.b64(desktopPublic))
        val secrets = TelefonSession.start(identity, peer, phonePrivate)
        val wrong = buildJsonObject {
            put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive("session_response"))
            put("sid", JsonPrimitive(TelefonKrypto.b64(secrets.sid)))
            put("from", JsonPrimitive("33333333-3333-4333-8333-333333333333")); put("to", JsonPrimitive(identity.device_id))
            put("ephemeral_public", JsonPrimitive(TelefonKrypto.b64(TelefonKrypto.schluesselpaar().second)))
            put("nonce", JsonPrimitive(TelefonKrypto.b64(TelefonKrypto.zufall(32))))
            put("version", JsonPrimitive(1)); put("mac", JsonPrimitive(TelefonKrypto.b64(ByteArray(32))))
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            TelefonSession.finish(secrets, wrong, identity, peer, ByteArrayInputStream(byteArrayOf()), ByteArrayOutputStream())
        }
    }

    @Test fun `RFCOMM nutzt unveraenderte laengenpraefigierte Telefonrahmen`() {
        val value = buildJsonObject {
            put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive("session_start"))
            put("versions", JsonArray(listOf(JsonPrimitive(1))))
        }
        val bytes = ByteArrayOutputStream().also { TelefonRahmen.schreiben(it, value) }.toByteArray()
        assertEquals(bytes.size - 4, java.nio.ByteBuffer.wrap(bytes, 0, 4).int)
        assertEquals(value, TelefonRahmen.lesen(ByteArrayInputStream(bytes)))
    }
}
