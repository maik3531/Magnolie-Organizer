package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class DevicePublishedReadbackEnvelopeTest {
    private fun vector() = Json.parseToJsonElement(File("../contracts/file-published-readback-v1-vectors.json").readText()).jsonObject
    private fun binding(v: JsonObject): DeviceTransferBinding {
        val b = v.getValue("binding").jsonObject
        return DeviceTransferBinding(b.string("sender_id"), b.string("receiver_id"), b.string("sender_identity_sha256"),
            b.string("receiver_identity_sha256"), b.string("permission_epoch"), b.string("destination_token"))
    }
    private fun context(body: JsonObject) = JsonObject(body.filterKeys { it !in setOf("destination_token", "binding_sha256", "readback_sha256") })
    private fun parse(v: JsonObject, message: JsonObject = v.getValue("message").jsonObject, offer: JsonObject = v.getValue("offer").jsonObject,
        selected: DeviceTransferBinding = binding(v), kind: GalleryMediaType = GalleryMediaType.IMAGES) =
        DevicePublishedReadbackEnvelope.parse(message, offer, selected, kind, v.long("now_ms"))

    @Test fun sharedCanonicalVectorMatchesAllDigestDomainsAndReturnsNoReceiptOrAuthority() {
        val v = vector(); val body = v.getValue("message").jsonObject.getValue("body").jsonObject; val b = binding(v)
        assertEquals(b.destinationToken, DevicePublishedReadbackEnvelope.destinationToken(context(body)))
        assertArrayEquals(TelefonKanonisch.bytes(body), TelefonKanonisch.bytes(DevicePublishedReadbackEnvelope.encodeBody(context(body), b)))
        val parsed = parse(v)
        assertEquals(body, parsed.body); assertFalse(parsed.grantsWriteAuthority); assertFalse(parsed.isSavedReceipt); assertFalse(parsed.allowsChunkOutput)
    }
    @Test fun typedContextDoesNotAcceptTruthFlagsStringsOrUnrecognizedMediaClaims() {
        val v = vector(); val body = context(v.getValue("message").jsonObject.getValue("body").jsonObject)
        val invalid = listOf("size" to JsonPrimitive(true), "size" to JsonPrimitive("123"), "size" to JsonPrimitive(0),
            "size" to JsonPrimitive(-1), "size" to JsonNull, "format" to JsonPrimitive(true), "format" to JsonPrimitive("1"),
            "sha256" to JsonPrimitive("A".repeat(64)), "readback_nonce" to JsonPrimitive("1".repeat(63)), "mime_type" to JsonPrimitive("video/mp4"))
        for ((key, value) in invalid) assertThrows(Exception::class.java) {
            DevicePublishedReadbackEnvelope.encodeBody(JsonObject(body + (key to value)), binding(v))
        }
    }
    @Test fun selfConsistentBodyStillCannotChangeCurrentOfferManifestOrFile() {
        val v = vector(); val message = v.getValue("message").jsonObject; val body = context(message.getValue("body").jsonObject)
        val invalid = listOf("transfer_id" to JsonPrimitive("6".repeat(32)), "source_id" to JsonPrimitive("7".repeat(32)),
            "file_id" to JsonPrimitive("8".repeat(32)), "size" to JsonPrimitive(124), "sha256" to JsonPrimitive("9".repeat(64)),
            "manifest_sha256" to JsonPrimitive("a".repeat(64)), "offer_id" to JsonPrimitive("33333333-3333-4333-8333-333333333333"))
        for ((key, value) in invalid) {
            val changed = JsonObject(body + (key to value)); val b = binding(v).copy(destinationToken = DevicePublishedReadbackEnvelope.destinationToken(changed))
            val encoded = DevicePublishedReadbackEnvelope.encodeBody(changed, b)
            assertThrows(Exception::class.java) { parse(v, JsonObject(message + ("body" to encoded)), selected = b) }
        }
    }
    @Test fun wireLifetimeBindingKindAndDigestAreIndependentlyChecked() {
        val v = vector(); val message = v.getValue("message").jsonObject; val body = message.getValue("body").jsonObject; val offer = v.getValue("offer").jsonObject
        val invalid = listOf(JsonObject(message + ("kind" to JsonPrimitive("file_transfer.saved"))),
            JsonObject(message + ("body" to JsonObject(body + ("allows_write" to JsonPrimitive(true))))),
            JsonObject(message + ("body" to JsonObject(body + ("readback_sha256" to JsonPrimitive("a".repeat(64)))))),
            JsonObject(message + ("expires_ms" to JsonPrimitive(offer.long("expires_ms") + 1))))
        for (changed in invalid) assertThrows(Exception::class.java) { parse(v, changed) }
        assertThrows(Exception::class.java) { parse(v, selected = binding(v).copy(receiverIdentitySha256 = "a".repeat(64))) }
        assertThrows(Exception::class.java) { parse(v, kind = GalleryMediaType.VIDEO) }
        assertThrows(Exception::class.java) { parse(v, offer = JsonObject(offer + mapOf("created_ms" to JsonPrimitive(v.long("now_ms") - 60000), "expires_ms" to JsonPrimitive(v.long("now_ms"))))) }
        assertThrows(Exception::class.java) { parse(v, offer = JsonObject(offer + mapOf("created_ms" to JsonPrimitive(v.long("now_ms") + 1), "expires_ms" to JsonPrimitive(v.long("now_ms") + 60001)))) }
    }
    @Test fun freshNonceChangesAllDerivedIdentitiesButCannotGrantWriteOrSaved() {
        val v = vector(); val message = v.getValue("message").jsonObject; val old = message.getValue("body").jsonObject
        val changed = JsonObject(context(old) + ("readback_nonce" to JsonPrimitive("2".repeat(64))))
        val b = binding(v).copy(destinationToken = DevicePublishedReadbackEnvelope.destinationToken(changed))
        val body = DevicePublishedReadbackEnvelope.encodeBody(changed, b)
        for (key in listOf("destination_token", "binding_sha256", "readback_sha256")) assertNotEquals(old[key], body[key])
        val parsed = parse(v, JsonObject(message + ("body" to body)), selected = b)
        assertFalse(parsed.grantsWriteAuthority); assertFalse(parsed.isSavedReceipt)
    }
}
