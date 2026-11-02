package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.UUID

/** Complete offer encoding groundwork. Not registered/advertised until actual
 * handlers, dedicated grants and destination acceptance exist on both peers.
 */
internal object DeviceFileOfferEnvelope {
    const val KIND = "file_transfer.offer"
    const val MAX_TTL_MS = 60_000L

    fun create(manifest: DeviceFileManifest, now: Long = System.currentTimeMillis(),
        messageId: String = UUID.randomUUID().toString(), ttlMs: Long = MAX_TTL_MS): JsonObject {
        if (ttlMs !in 1..MAX_TTL_MS) fail("file_offer_invalid_ttl")
        val body = JsonObject(mapOf("version" to JsonPrimitive(1), "manifest" to manifest.wire(),
            "manifest_sha256" to JsonPrimitive(manifest.fingerprint)))
        val message = TelefonNachrichten.message(KIND, body, ttlMs, now, messageId)
        validate(message, manifest.senderId, manifest.receiverId, now)
        return message
    }

    /** Native authenticated peer IDs are supplied by the coordinator, never
     * inferred from fields inside the received offer. Budget the WHOLE encoded
     * application message (including header/body/fingerprint/UTF-8 escaping).
     * Transport ciphertext/base64 has its own existing outer frame bound.
     */
    fun validate(message: JsonObject, senderId: String, receiverId: String,
        now: Long = System.currentTimeMillis()): DeviceFileManifest {
        if (TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX) fail("file_offer_envelope_too_large")
        TelefonNachrichten.validateHeader(message, now)
        if (message.string("kind") != KIND || message.long("expires_ms") - message.long("created_ms") > MAX_TTL_MS)
            fail("file_offer_invalid_envelope")
        val body = message["body"] as? JsonObject ?: fail("file_offer_invalid_envelope")
        if (body.keys != setOf("version", "manifest", "manifest_sha256") || body["version"] != JsonPrimitive(1))
            fail("file_offer_invalid_envelope")
        val manifest = DeviceFileManifest.parse(body["manifest"] as? JsonObject ?: fail("file_offer_invalid_envelope"))
        if (manifest.senderId != senderId || manifest.receiverId != receiverId ||
            body["manifest_sha256"] != JsonPrimitive(manifest.fingerprint)) fail("file_offer_manifest_binding_changed")
        return manifest
    }

    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
