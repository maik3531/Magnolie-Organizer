package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.UUID

/** Codec only: a positive result requires the native owner to prove both
 * saved per-kind RECEIVE choices before calling. No offer or I/O lives here. */
internal object MediaMixedPreflight {
    const val REQUEST = "file_transfer.media_mixed_preflight"
    const val RESULT = "file_transfer.media_mixed_preflight.result"
    internal const val TTL_MS = 10_000L
    private const val MAX_WALL = 253_402_300_799_999L
    private val envelope = setOf("type", "v", "message_id", "kind", "created_ms", "expires_ms", "body")

    fun readRequest(request: JsonObject, settings: JsonObject, binding: DeviceTransferBinding, now: Long): String {
        val values = MediaSyncSettings.effective(settings)
        if (values.size != 8 || values["enabled"] != JsonPrimitive(true) || values["photos_enabled"] != JsonPrimitive(true) ||
            values["videos_enabled"] != JsonPrimitive(true) || values["direction"] != JsonPrimitive("pc_to_phone") ||
            values["collection_mode"] != JsonPrimitive("entire_collection") || binding.destinationToken != "0".repeat(64)) fail()
        if (request.keys != envelope || request["type"] != JsonPrimitive("message") || request["v"] != JsonPrimitive(1) ||
            request["kind"] != JsonPrimitive(REQUEST)) fail()
        val id = (request["message_id"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        TelefonNachrichten.uuid4(id)
        val created = strictTime(request, "created_ms")
        val expiry = strictTime(request, "expires_ms")
        if (now !in 0 until expiry || created !in 0..now || expiry > MAX_WALL || expiry - created > TTL_MS) fail()
        if (request["body"] != buildJsonObject {
                put("format", 1)
                put("settings_sha256", DeviceFileControl.digest("magnolie-mixed-settings-v1\u0000", settings))
                put("binding_sha256", DeviceFileControl.digest("magnolie-mixed-control-v1\u0000", binding.snapshot()))
            }) fail()
        return id
    }

    fun readyResult(request: JsonObject, settings: JsonObject, binding: DeviceTransferBinding, now: Long): JsonObject {
        val id = readRequest(request, settings, binding, now)
        return buildJsonObject {
            put("type", "message")
            put("v", 1)
            put("message_id", UUID.randomUUID().toString())
            put("kind", RESULT)
            put("created_ms", now)
            put("expires_ms", request.getValue("expires_ms"))
            put("body", JsonObject(request.getValue("body").jsonObject + ("request_id" to JsonPrimitive(id))))
        }
    }

    private fun strictTime(message: JsonObject, name: String): Long =
        (message[name] as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull ?: fail()

    private fun fail(): Nothing = DeviceFileControl.fail("media_mixed_preflight_invalid")
}
