package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.IOException
import java.security.MessageDigest

class MediaOfferEnvelopeTest {
    private val a = "11111111-1111-4111-8111-111111111111"
    private val b = "22222222-2222-4222-8222-222222222222"
    private val fileId = "1".repeat(32)
    private fun vector() = Json.parseToJsonElement(File("../contracts/media-offer-v1-vectors.json").readText()).jsonObject
    private fun body(message: JsonObject, field: String, value: JsonElement) = JsonObject(message + ("body" to JsonObject(message.getValue("body").jsonObject + (field to value))))
    private fun reject(operation: () -> Unit) {
        try { operation(); fail("Invalid media metadata admitted before actual native ownership") }
        catch (_: IllegalArgumentException) { }
        catch (_: IOException) { }
        catch (_: TelefonProtokollFehler) { }
    }
    @Test fun sharedBytesAndStandardOfferCorrelationStayExactWithoutNativeRights() {
        val vector = vector(); val message = vector.getValue("message").jsonObject; val now = vector.long("now")
        val parsed = MediaOfferEnvelope.validate(message, a, b, now); val raw = TelefonKanonisch.bytes(message)
        assertEquals(vector.long("canonical_bytes"), raw.size.toLong())
        assertEquals(vector.string("canonical_sha256"), MessageDigest.getInstance("SHA-256").digest(raw).joinToString("") { "%02x".format(it) })
        assertEquals(parsed.manifest.fingerprint, DeviceFileOfferEnvelope.validate(parsed.offer, a, b, now).fingerprint)
        assertEquals(message["message_id"], parsed.offer["message_id"])
        assertEquals(123L, parsed.originals.getValue(fileId).body.long("original_size"))
        reject { DeviceFileOfferEnvelope.validate(message, a, b, now) }
    }
    @Test fun malformedMissingForeignUnrequestedAndExpiredMetadataNeverStartNativeIo() {
        val vector = vector(); val message = vector.getValue("message").jsonObject; val now = vector.long("now")
        val raw = message.getValue("body").jsonObject; val mime = raw.getValue("mime_types").jsonObject; val originals = raw.getValue("originals").jsonObject
        val invalid = mutableListOf(
            JsonObject(message + ("extra" to JsonPrimitive(true))), JsonObject(message + ("expires_ms" to JsonPrimitive(now))),
            body(message, "confirmed", JsonPrimitive(true)), body(message, "mime_types", buildJsonObject {}),
            body(message, "mime_types", JsonObject(mime + (fileId to JsonPrimitive("video/mp4")))),
            body(message, "mime_types", JsonObject(mime + (fileId to JsonPrimitive("image/png; charset=utf-8")))),
            body(message, "mime_types", JsonObject(mime + ("f".repeat(32) to JsonPrimitive("image/png")))),
            body(message, "originals", buildJsonObject {}), body(message, "originals", JsonObject(originals + ("f".repeat(32) to originals.getValue(fileId)))),
            body(message, "settings", JsonObject(raw.getValue("settings").jsonObject + ("settings" to JsonObject(raw.getValue("settings").jsonObject.getValue("settings").jsonObject.filterKeys { it != "photos_only" }))))
        )
        for (value in listOf(JsonPrimitive(true), JsonPrimitive(123.0))) {
            val original = originals.getValue(fileId).jsonObject
            invalid += body(message, "originals", JsonObject(mapOf(fileId to JsonObject(original + ("original_size" to value)))))
        }
        for ((field, value) in listOf("enabled" to JsonPrimitive(false), "direction" to JsonPrimitive("phone_to_pc"), "collection_mode" to JsonPrimitive("import_only")))
            invalid += body(message, "settings", MediaSyncSettings.change(raw.getValue("settings").jsonObject, a, b, field, value))
        invalid.forEach { reject { MediaOfferEnvelope.validate(it, a, b, now) } }
        reject { MediaOfferEnvelope.validate(message, b, b, now) }
    }
    @Test fun entireCollectionCanContainNewMembersWithoutPretendingTheyCameFromThePhone() {
        val vector = vector(); val message = vector.getValue("message").jsonObject
        val settings = MediaSyncSettings.change(message.getValue("body").jsonObject.getValue("settings").jsonObject, a, b, "collection_mode", JsonPrimitive("entire_collection"))
        val selected = body(body(message, "settings", settings), "originals", buildJsonObject {})
        assertTrue(MediaOfferEnvelope.validate(selected, a, b, vector.long("now")).originals.isEmpty())
    }
    @Test fun opaquePcOriginVersionTwoHasSharedBytesWithoutPhoneProofOrNativePaths() {
        val v = vector(); val base = v.getValue("message").jsonObject
        val pc = Json.parseToJsonElement(File("../contracts/media-pc-origin-v1-vectors.json").readText()).jsonObject
        val settings = MediaSyncSettings.change(base.getValue("body").jsonObject.getValue("settings").jsonObject, a, b, "collection_mode", JsonPrimitive("entire_collection"))
        val selected = body(body(body(body(base, "settings", settings), "originals", buildJsonObject {}), "format", JsonPrimitive(2)), "pc_origins", pc.getValue("pc_origins"))
        val decoded = MediaOfferEnvelope.validate(selected, a, b, v.long("now")); val bytes = TelefonKanonisch.bytes(selected)
        assertTrue(decoded.originals.isEmpty()); assertEquals(1, decoded.pcOrigins.size)
        assertEquals(pc.long("canonical_bytes"), bytes.size.toLong())
        assertEquals(pc.string("canonical_sha256"), MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) })
        val token = pc.getValue("pc_origins").jsonObject.getValue(fileId).jsonObject
        fun tokenChanged(value: JsonObject) = body(selected, "pc_origins", JsonObject(mapOf(fileId to value)))
        val invalid = mutableListOf(body(selected, "format", JsonPrimitive(1)), body(selected, "pc_origins", buildJsonObject {}),
            body(selected, "settings", base.getValue("body").jsonObject.getValue("settings")),
            body(selected, "originals", base.getValue("body").jsonObject.getValue("originals")),
            body(selected, "pc_origins", JsonObject(pc.getValue("pc_origins").jsonObject + ("f".repeat(32) to token))),
            tokenChanged(JsonObject(token.filterKeys { it != "previous_publication_sha256" })))
        for ((key,value) in listOf("format" to JsonPrimitive(true), "origin_sha256" to JsonPrimitive("A".repeat(64)),
            "previous_publication_sha256" to JsonPrimitive(true), "native_path" to JsonPrimitive("private")))
            invalid += tokenChanged(JsonObject(token + (key to value)))
        invalid.forEach { reject { MediaOfferEnvelope.validate(it, a, b, v.long("now")) } }
        val next = tokenChanged(JsonObject(token + ("previous_publication_sha256" to JsonPrimitive("b".repeat(64)))))
        assertEquals("b".repeat(64), MediaOfferEnvelope.validate(next, a, b, v.long("now")).pcOrigins.getValue(fileId).previousPublication)
    }
}
