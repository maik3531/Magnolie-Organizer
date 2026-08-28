package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File

class TelefonProtokollTest {
    @Test fun `feste Parameter und default off sind unabhaengig`() {
        assertEquals(8741, TelefonParameter.PORT)
        assertEquals("_magnolie-phone._tcp", TelefonParameter.NSD_TYP)
        assertEquals("7b1d9e2a-5c43-4f68-a172-9d30e6b4c851", TelefonParameter.RFCOMM_UUID)
        assertFalse(TelefonUiZustand().enabled)
        assertEquals(TelefonVerbindungsstatus.STOPPED, TelefonUiZustand().connection)
    }

    @Test fun `kanonisches JSON ist UTF8 sortiert und verbietet Bruchzahlen`() {
        val value = JsonObject(linkedMapOf("z" to JsonPrimitive("ä"), "a" to JsonPrimitive(2),
            "aktiv" to JsonPrimitive(true), "aus" to JsonPrimitive(false)))
        assertEquals("{\"a\":2,\"aktiv\":true,\"aus\":false,\"z\":\"ä\"}", TelefonKanonisch.text(value))
        org.junit.Assert.assertThrows(TelefonProtokollFehler::class.java) {
            TelefonKanonisch.text(JsonPrimitive(1.5))
        }
    }

    @Test fun `HKDF RFC5869 Testvektor`() {
        val ikm = ByteArray(22) { 0x0b }
        val result = TelefonKrypto.hkdf(ikm, hex("000102030405060708090a0b0c"),
            hex("f0f1f2f3f4f5f6f7f8f9"), 42)
        assertArrayEquals(hex("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"), result)
    }

    @Test fun `X25519 RFC7748 Testvektor`() {
        val shared = TelefonKrypto.austausch(
            hex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"),
            hex("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"))
        assertArrayEquals(hex("4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"), shared)
    }

    @Test fun `AES GCM NIST Testvektor und Nonce`() {
        val key = ByteArray(32)
        val encrypted = TelefonKrypto.verschluesseln(key, ByteArray(12), ByteArray(16), ByteArray(0))
        assertArrayEquals(hex("cea7403d4d606b6e074ec5d3baf39d18d0d1c8a799996bf0265b98b5d48ab919"), encrypted)
        assertArrayEquals(ByteArray(16), TelefonKrypto.entschluesseln(key, ByteArray(12), encrypted, ByteArray(0)))
        assertArrayEquals(hex("010203040000000000000007"), TelefonKrypto.nonce(hex("01020304"), 7))
    }

    @Test fun `Rahmen roundtrip und fail closed`() {
        val objectValue = buildJsonObject { put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive("x")) }
        val out = ByteArrayOutputStream()
        TelefonRahmen.schreiben(out, objectValue)
        assertEquals(objectValue, TelefonRahmen.lesen(ByteArrayInputStream(out.toByteArray())))
        val duplicate = "{\"a\":1,\"a\":2}".toByteArray()
        val framed = byteArrayOf(0, 0, 0, duplicate.size.toByte()) + duplicate
        org.junit.Assert.assertThrows(TelefonProtokollFehler::class.java) { TelefonRahmen.lesen(ByteArrayInputStream(framed)) }
        org.junit.Assert.assertThrows(TelefonProtokollFehler::class.java) {
            TelefonRahmen.lesen(ByteArrayInputStream(byteArrayOf(0, 1, 0, 1)), 65_536)
        }
    }

    @Test fun `Statusvertrag und Capabilities bleiben getrennt`() {
        val body = DeviceStatusCollector.body(DeviceStatus("123e4567-e89b-12d3-a456-426614174000", "Pixel", "Google",
            osVersion = "16", batteryPercent = 73, charging = "charging", capturedMs = 1_786_617_000_000))
        assertEquals(setOf("request_id", "model", "manufacturer", "os_name", "os_version", "battery_percent", "charging", "captured_ms"), body.keys)
        assertEquals("Android", (body["os_name"] as JsonPrimitive).content)
        val version2 = DeviceStatusCollector.body(DeviceStatus("123e4567-e89b-12d3-a456-426614174000", "Pixel", "Google",
            osVersion = "16", batteryPercent = 73, charging = "charging", capturedMs = 1_786_617_000_000,
            sdkInt = 36, batteryTemperatureDeciC = 287, powerSource = "usb", storageTotalBytes = 128_000_000_000,
            storageAvailableBytes = 41_000_000_000, memoryTotalBytes = 8_000_000_000,
            memoryAvailableBytes = 2_600_000_000, uptimeMs = 294_000_000, networkTransport = "wifi",
            networkValidated = true), 2)
        assertEquals(19, version2.keys.size)
        assertEquals("wifi", (version2["network_transport"] as JsonPrimitive).content)
        val version3 = DeviceStatusCollector.body(DeviceStatus("123e4567-e89b-12d3-a456-426614174000", "Pixel", "Google",
            osVersion = "16", batteryPercent = 73, charging = "charging", capturedMs = 1_786_617_000_000,
            appVersion = "1.0.8"), 3)
        assertEquals(version2.keys + "app_version", version3.keys)
        assertEquals("1.0.8", (version3["app_version"] as JsonPrimitive).content)
        val capabilities = TelefonCapabilities.phase1()
        assertTrue(capabilities.getValue("device_status").available)
        assertEquals(listOf(1, 2, 3), capabilities.getValue("device_status").versions)
        assertTrue(capabilities.getValue("transport.bluetooth_rfcomm").available)
        assertFalse(capabilities.getValue("dial_request").available)
        assertEquals("available", capabilities.getValue("transport.bluetooth_rfcomm").reason)
        assertEquals("permission_missing", TelefonCapabilities.phase1(dialRequest = true,
            dialResolvable = true, dialPermission = false).getValue("dial_request").reason)
        val direct = TelefonCapabilities.phase1(dialRequest = true, dialResolvable = true,
            dialPermission = true, incomingCalls = true, endCalls = true)
        assertTrue(direct.getValue("dial_request").available)
        assertTrue(direct.getValue("incoming_call_state").available)
        assertTrue(direct.getValue("end_call").available)
    }

    @Test fun `Waehlauftrag ist strikt und kurzlebig`() {
        val body = buildJsonObject {
            put("to", JsonPrimitive("+491701234567"))
            put("client_ref", JsonPrimitive("123e4567-e89b-42d3-a456-426614174000"))
        }
        TelefonNachrichten.validate(TelefonNachrichten.message("dial_request.command", body, 60_000, 1000,
            "123e4567-e89b-42d3-a456-426614174001"), 1000)
        org.junit.Assert.assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validate(TelefonNachrichten.message("dial_request.command",
                JsonObject(body + ("to" to JsonPrimitive("+49 1701234567"))), 60_000, 1000,
                "123e4567-e89b-42d3-a456-426614174002"), 1000)
        }
        org.junit.Assert.assertThrows(TelefonProtokollFehler::class.java) {
            TelefonNachrichten.validate(TelefonNachrichten.message("dial_request.command", body, 60_001, 1000,
                "123e4567-e89b-42d3-a456-426614174003"), 1000)
        }
    }

    @Test fun `gemeinsame Telefon Golden Vectors`() {
        val root = TelefonKanonisch.json.parseToJsonElement(javaClass.classLoader!!
            .getResource("telefon-protokoll-vektoren.json")!!.readText()).jsonObject
        val canonical = root.getValue("canonical_json").jsonObject
        assertEquals(canonical.text("expected"), TelefonKanonisch.text(canonical.getValue("input")))
        val pairing = root.getValue("pairing").jsonObject
        val init = pairing.getValue("pair_init").jsonObject
        val response = pairing.getValue("pair_response").jsonObject
        assertEquals(pairing.text("canonical_pair_init"), TelefonKanonisch.text(init))
        assertEquals(pairing.text("canonical_pair_response"), TelefonKanonisch.text(response))
        val material = TelefonKrypto.paarung(init, response,
            pairing.bytes("phone_ephemeral_private", 32), pairing.bytes("phone_static_private", 32))
        assertArrayEquals(pairing.bytes("transcript", 32), material.transcript)
        assertArrayEquals(pairing.bytes("pair_key", 32), material.schluessel)
        assertEquals(pairing.text("code"), material.code)
        for (phase in listOf("confirm", "finish")) for (side in listOf("phone", "desktop")) {
            assertArrayEquals(pairing.bytes("${side}_${phase}_proof", 32), TelefonKrypto.beweis(
                material, "magnolie-phone-pair-v1/$phase\u0000", side))
        }

        val session = root.getValue("session").jsonObject
        val ids = session.bytes("ids", 73)
        val staticRoot = TelefonKrypto.hkdf(pairing.bytes("static_shared", 32),
            TelefonKrypto.sha256("magnolie-phone-fs1/static-salt\u0000".toByteArray(), ids),
            "magnolie-phone-fs1/static-root\u0000".toByteArray() + ids, 32)
        assertArrayEquals(session.bytes("static_root", 32), staticRoot)
        val auth = TelefonKrypto.hkdf(staticRoot, null, "magnolie-phone-fs1/auth\u0000".toByteArray(), 32)
        assertArrayEquals(session.bytes("auth_key", 32), auth)
        val start0 = session.getValue("session_start_without_mac").jsonObject
        val start = session.getValue("session_start").jsonObject
        assertArrayEquals(TelefonKrypto.b64(start.text("mac"), 32), TelefonKrypto.hmac(auth,
            "magnolie-phone-fs1/start\u0000".toByteArray(), TelefonKanonisch.bytes(start0)))
        val response0 = session.getValue("session_response_without_mac").jsonObject
        val sessionResponse = session.getValue("session_response").jsonObject
        assertArrayEquals(TelefonKrypto.b64(sessionResponse.text("mac"), 32), TelefonKrypto.hmac(auth,
            "magnolie-phone-fs1/response\u0000".toByteArray(), TelefonKanonisch.bytes(start), TelefonKanonisch.bytes(response0)))
        val transcript = TelefonKrypto.sha256(TelefonKanonisch.bytes(start), TelefonKanonisch.bytes(sessionResponse))
        assertArrayEquals(session.bytes("transcript", 32), transcript)
        val salt = TelefonKrypto.hmac(staticRoot, "magnolie-phone-fs1/session-salt\u0000".toByteArray(), transcript)
        val sessionMaterial = TelefonKrypto.hkdf(pairing.bytes("ephemeral_shared", 32), salt,
            "magnolie-phone-fs1/session-keys\u0000".toByteArray() + transcript, 72)
        assertArrayEquals(session.bytes("session_material", 72), sessionMaterial)

        val encryption = root.getValue("encryption").jsonObject
        val envelope = encryption.getValue("envelope").jsonObject
        val aad = JsonObject(envelope.filterKeys { it != "ciphertext" })
        assertEquals(encryption.text("aad_canonical"), TelefonKanonisch.text(aad))
        val nonce = TelefonKrypto.nonce(sessionMaterial.copyOfRange(32, 36), 7)
        assertArrayEquals(encryption.bytes("nonce", 12), nonce)
        val cipher = TelefonKrypto.verschluesseln(sessionMaterial.copyOfRange(0, 32), nonce,
            TelefonKanonisch.bytes(encryption.getValue("plaintext")), TelefonKanonisch.bytes(aad))
        assertArrayEquals(encryption.bytes("ciphertext", cipher.size), cipher)
    }

    private fun JsonObject.text(name: String) = (getValue(name) as JsonPrimitive).content
    private fun JsonObject.bytes(name: String, length: Int) = TelefonKrypto.b64(text(name), length)

    private fun hex(value: String): ByteArray = value.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
}
