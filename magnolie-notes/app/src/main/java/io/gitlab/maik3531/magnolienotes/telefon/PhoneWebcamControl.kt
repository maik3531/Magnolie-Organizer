package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.util.UUID

/** Small authenticated-parent controls ONLY; never AV data or capture/SEND
 * authority. A runtime must additionally bind the fresh probe/nonce, exact live
 * parent and phase, original Organizer opt-in, OS permit and receiver readiness.
 *
 * Discovery is desktop-only: adding this to Notes' already full 16-entry
 * device_status list would disconnect older peers. A desktop may reply only
 * after this phone's fresh v24 probe on that same authenticated parent.
 */
internal object PhoneWebcamControl {
    const val DISCOVERY_VERSION = 24
    const val REQUEST = "device_status.request"
    const val REPORT = "device_status.report"
    const val MAX_WIRE_BYTES = 4096
    const val MAX_TTL_MS = 60_000L
    val reasons = setOf("disabled", "unsupported", "foreground_required", "permission_denied", "capture_failed", "output_failed", "retired")
    private val base = setOf("version", "request_id", "nonce", "op")
    private val hex32 = Regex("[0-9a-f]{32}")
    private val hex64 = Regex("[0-9a-f]{64}")

    fun reserved(message: JsonObject): Boolean = message["kind"] in setOf(JsonPrimitive(REQUEST), JsonPrimitive(REPORT)) &&
        (message["body"] as? JsonObject)?.get("version") == JsonPrimitive(DISCOVERY_VERSION)

    fun validateMessage(message: JsonObject, now: Long = System.currentTimeMillis()): JsonObject {
        TelefonNachrichten.validateHeader(message, now)
        require(message.long("expires_ms") - message.long("created_ms") in 1..MAX_TTL_MS &&
            TelefonKanonisch.bytes(message).size <= MAX_WIRE_BYTES) { "webcam_control_envelope_invalid" }
        val body = message["body"] as? JsonObject ?: error("webcam_control_invalid")
        validateBody(body, message.string("kind"))
        return body
    }

    fun validateBody(body: JsonObject, kind: String) {
        fun invalid(): Nothing = throw IllegalArgumentException("webcam_control_invalid")
        fun text(key: String) = (body[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: invalid()
        if (body["version"] != JsonPrimitive(DISCOVERY_VERSION)) invalid()
        val id = text("request_id")
        val uuid = runCatching { UUID.fromString(id) }.getOrNull() ?: invalid()
        if (uuid.toString() != id || uuid.version() != 4 || uuid.variant() != 2 || !hex64.matches(text("nonce"))) invalid()
        val op = text("op")
        if (kind != REQUEST && kind != REPORT) invalid()
        val extra = when (op) {
            "probe" -> { if (kind != REQUEST) invalid(); emptySet() }
            "offer" -> { if (kind != REPORT) invalid(); setOf("session", "secret", "port", "muted", "front") }
            "unavailable" -> { if (kind != REPORT) invalid(); setOf("reason") }
            "prepared" -> { if (kind != REQUEST) invalid(); setOf("session") }
            "send" -> { if (kind != REPORT) invalid(); setOf("session") }
            "stop" -> setOf("session")
            "error" -> setOf("session", "reason")
            else -> invalid()
        }
        if (body.keys != base + extra) invalid()
        if ("session" in extra && !hex32.matches(text("session"))) invalid()
        if ("reason" in extra && text("reason") !in reasons) invalid()
        if (op == "offer") {
            if (!hex64.matches(text("secret"))) invalid()
            val port = (body["port"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toIntOrNull() ?: invalid()
            if (port !in 1024..65535) invalid()
            for (key in listOf("muted", "front")) if ((body[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull == null) invalid()
        }
    }
}
