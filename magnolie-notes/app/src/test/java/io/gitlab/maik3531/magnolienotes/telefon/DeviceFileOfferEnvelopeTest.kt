package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class DeviceFileOfferEnvelopeTest {
    private val now = 1_800_000_000_000L
    private val messageId = "00000000-0000-4000-8000-000000000001"
    private fun fixture() = Json.parseToJsonElement(File("../contracts/file-transfer-manifest-v1-vectors.json").readText())
        .jsonObject["vectors"]!!.jsonArray.first().jsonObject["manifest"]!!.jsonObject
    private fun raw(manifest: DeviceFileManifest): JsonObject = TelefonNachrichten.message(DeviceFileOfferEnvelope.KIND,
        JsonObject(mapOf("version" to JsonPrimitive(1), "manifest" to manifest.wire(), "manifest_sha256" to JsonPrimitive(manifest.fingerprint))),
        60_000, now, messageId)
    private fun validate(message: JsonObject, manifest: DeviceFileManifest) = DeviceFileOfferEnvelope.validate(message, manifest.senderId, manifest.receiverId, now)
    private fun bodyChanged(message: JsonObject, field: String, value: kotlinx.serialization.json.JsonElement): JsonObject =
        JsonObject(message + ("body" to JsonObject(message["body"]!!.jsonObject + (field to value))))

    private fun largeManifest(totalCharacters: Int, asciiPadding: Int = 0): DeviceFileManifest {
        val original = fixture()
        val files = (0 until 128).map { index ->
            val length = totalCharacters / 128 + if (index < totalCharacters % 128) 1 else 0
            val path = "界".repeat(length).chunked(200).joinToString("/") + "/file-$index" +
                (if (index == 0) "x".repeat(asciiPadding) else "") + ".jpg"
            JsonObject(mapOf("id" to JsonPrimitive("%032x".format(index + 1)), "path" to JsonPrimitive(path),
                "size" to JsonPrimitive(0), "sha256" to JsonPrimitive("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")))
        }
        return DeviceFileManifest.parse(JsonObject(original + mapOf("files" to JsonArray(files), "total_bytes" to JsonPrimitive(0))))
    }

    private fun manifestForEnvelopeBytes(target: Int): DeviceFileManifest {
        var low = 128 * 580; var high = 128 * 700
        while (low < high) {
            val middle = (low + high + 1) / 2
            if (TelefonKanonisch.bytes(raw(largeManifest(middle))).size <= target) low = middle else high = middle - 1
        }
        val unpadded = largeManifest(low)
        val difference = target - TelefonKanonisch.bytes(raw(unpadded)).size
        assertTrue(difference in 0..4)
        return largeManifest(low, difference).also { assertEquals(target, TelefonKanonisch.bytes(raw(it)).size) }
    }

    @Test fun exactCompleteUtf8ApplicationLimitIsAcceptedButOneExtraByteIsNotSplitOrOffered() {
        val manifest = manifestForEnvelopeBytes(TelefonParameter.ANWENDUNG_MAX)
        val message = DeviceFileOfferEnvelope.create(manifest, now, messageId)
        assertEquals(262144, TelefonKanonisch.bytes(message).size)
        assertEquals(128, validate(message, manifest).files.size)
        assertTrue(TelefonKanonisch.bytes(manifest.wire()).size < TelefonParameter.ANWENDUNG_MAX)
        val excess = manifestForEnvelopeBytes(TelefonParameter.ANWENDUNG_MAX + 1)
        assertTrue(TelefonKanonisch.bytes(excess.wire()).size < TelefonParameter.ANWENDUNG_MAX)
        assertEquals("file_offer_envelope_too_large", assertThrows(PhotoFolderScopeError::class.java) {
            DeviceFileOfferEnvelope.create(excess, now, messageId) }.code)
        assertEquals("file_offer_envelope_too_large", assertThrows(PhotoFolderScopeError::class.java) { validate(raw(excess), excess) }.code)
        assertEquals(128, excess.files.size)
    }

    @Test fun fullManifestFingerprintAndActualAuthenticatedPeersMustMatchWithoutUnknownBodyFields() {
        val manifest = DeviceFileManifest.parse(fixture()); val message = DeviceFileOfferEnvelope.create(manifest, now, messageId)
        assertEquals(manifest.fingerprint, validate(message, manifest).fingerprint)
        for ((field, value) in listOf("manifest_sha256" to JsonPrimitive("0".repeat(64)), "extra" to JsonPrimitive(true),
            "version" to JsonPrimitive("1"), "version" to JsonPrimitive(true)))
            assertThrows(PhotoFolderScopeError::class.java) { validate(bodyChanged(message, field, value), manifest) }
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileOfferEnvelope.validate(message, "other_sender_0001", manifest.receiverId, now) }
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileOfferEnvelope.validate(message, manifest.senderId, "other_receiver_01", now) }
        val changed = DeviceFileManifest.parse(JsonObject(manifest.wire() + ("source_id" to JsonPrimitive("f".repeat(32)))))
        assertThrows(PhotoFolderScopeError::class.java) { validate(bodyChanged(message, "manifest", changed.wire()), manifest) }
    }

    @Test fun onlyTheActualHeaderKindShortTtlAndValidMessageIdentityAreAccepted() {
        val manifest = DeviceFileManifest.parse(fixture()); val message = raw(manifest)
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileOfferEnvelope.create(manifest, now, messageId, 60_001) }
        assertThrows(PhotoFolderScopeError::class.java) { validate(JsonObject(message + ("kind" to JsonPrimitive("personal_sync.attachment_request"))), manifest) }
        assertThrows(PhotoFolderScopeError::class.java) { validate(JsonObject(message + ("expires_ms" to JsonPrimitive(now + 60_001))), manifest) }
        assertThrows(TelefonProtokollFehler::class.java) { validate(JsonObject(message + ("message_id" to JsonPrimitive("invalid"))), manifest) }
        assertThrows(TelefonProtokollFehler::class.java) { validate(JsonObject(message + ("extra" to JsonPrimitive(true))), manifest) }
        // Still unregistered until real consent/handlers exist: syntax support
        // is not accidental transport activation or capability advertisement.
        assertThrows(TelefonProtokollFehler::class.java) { TelefonNachrichten.validate(message, now) }
    }
}
