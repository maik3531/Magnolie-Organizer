package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonElement
import android.os.SystemClock
import java.util.UUID

/** Validation only. Marker, probe, envelope and ACK confer no capture or SEND permission. */
internal object PhoneScreenControl {
    const val VERSION = 26
    const val REQUEST = "device_status.request"
    const val REPORT = "device_status.report"
    private const val MAX_TTL_MS = 60_000L
    private const val MAX_WIRE_BYTES = 4096
    private val base = setOf("version", "request_id", "nonce", "op")
    private val reasons = setOf("not_granted", "unsupported", "foreground_required", "permission_denied", "capture_failed", "output_failed", "retired")
    private val hex32 = Regex("[a-f0-9]{32}")
    private val hex64 = Regex("[a-f0-9]{64}")
    private val intValue = Regex("0|[1-9][0-9]*")

    fun reserved(message: JsonObject): Boolean = message["kind"] in setOf(JsonPrimitive(REQUEST), JsonPrimitive(REPORT)) &&
        ((message["body"] as? JsonObject)?.get("version") as? JsonPrimitive)?.content?.toDoubleOrNull() == VERSION.toDouble()

    fun validateMessage(message: JsonObject, now: Long = System.currentTimeMillis()): JsonObject {
        TelefonNachrichten.validateHeader(message, now)
        require(message.long("expires_ms") - message.long("created_ms") in 1..MAX_TTL_MS &&
            TelefonKanonisch.bytes(message).size <= MAX_WIRE_BYTES) { "screen_control_envelope_invalid" }
        val body = message["body"] as? JsonObject ?: throw IllegalArgumentException("screen_control_invalid")
        validateBody(body, message.string("kind"))
        return body
    }

    fun validateBody(body: JsonObject, kind: String) {
        fun invalid(): Nothing = throw IllegalArgumentException("screen_control_invalid")
        fun text(key: String) = (body[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: invalid()
        fun integer(key: String) = (body[key] as? JsonPrimitive)?.takeIf { !it.isString && intValue.matches(it.content) }
            ?.content?.toIntOrNull() ?: invalid()
        if (kind != REQUEST && kind != REPORT || integer("version") != VERSION) invalid()
        val id = text("request_id")
        if (id.length != 36) invalid()
        val uuid = runCatching { UUID.fromString(id) }.getOrNull() ?: invalid()
        if (uuid.toString() != id || uuid.version() != 4 || uuid.variant() != 2 || !hex64.matches(text("nonce"))) invalid()
        val operation = text("op")
        val extra = when (operation) {
            "probe" -> { if (kind != REQUEST) invalid(); emptySet() }
            "offer" -> { if (kind != REPORT) invalid(); setOf("session", "secret", "port", "width", "height", "density") }
            "prepared" -> { if (kind != REQUEST) invalid(); setOf("session") }
            "send" -> { if (kind != REPORT) invalid(); setOf("session") }
            "stop" -> setOf("session")
            "error" -> setOf("session", "reason")
            else -> invalid()
        }
        if (body.keys != base + extra || "session" in extra && !hex32.matches(text("session"))) invalid()
        if (operation == "error" && text("reason") !in reasons) invalid()
        if (operation == "offer") {
            val width = integer("width")
            val height = integer("height")
            if (!hex64.matches(text("secret")) || integer("port") !in 1024..65535 || width !in 2..1920 ||
                height !in 2..1920 || width * height > 1920 * 1080 || integer("density") !in 1..1000) invalid()
        }
    }
}

/** Uses the original bounded native writer; does not consume, start, or substitute a parent. */
internal class PhoneScreenNotesChannel(private val channel: TelefonSecureChannel, private val pipe: TelefonTcpRoehre,
    private val requireCurrent: () -> Unit, private val track: (String) -> Unit = {}) {
    fun bodyFrom(actual: TelefonSecureChannel, message: JsonObject): JsonObject {
        check(actual === channel && message.string("kind") == PhoneScreenControl.REPORT) { "screen_control_original_channel_required" }
        requireCurrent()
        return PhoneScreenControl.validateMessage(message)
    }

    fun write(body: JsonObject, guard: () -> Unit = {}) {
        PhoneScreenControl.validateBody(body, PhoneScreenControl.REQUEST)
        val message = TelefonNachrichten.message(PhoneScreenControl.REQUEST, body, 60_000)
        requireCurrent()
        guard()
        track(message.string("message_id"))
        channel.sendEphemeral(message, pipe, { requireCurrent(); guard() })
    }
}

/** One original probe, optional capture, and SEND decision. No socket or Android consent is created here. */
internal class PhoneScreenNotesControl(private val parent: Any, probe: JsonObject, private val requireParent: () -> Unit,
    private val clock: () -> Long = SystemClock::elapsedRealtime) : AutoCloseable {
    private val gate = Any()
    private val issued = clock()
    private val base: Map<String, JsonElement>
    private var phase = Phase.Probe
    private var session: JsonPrimitive? = null
    private enum class Phase { Probe, Offered, Publishing, Prepared, Sending, Closed }

    init {
        PhoneScreenControl.validateBody(probe, PhoneScreenControl.REQUEST)
        require(probe.string("op") == "probe")
        base = probe.filterKeys { it == "version" || it == "request_id" || it == "nonce" }
    }

    private fun current() {
        try {
            requireParent()
            synchronized(gate) {
                val age = clock() - issued
                check(phase != Phase.Closed && age >= 0 && (phase == Phase.Sending || age < 60_000)) { "screen_control_retired" }
            }
        } catch (error: Exception) { close(); throw error }
    }

    private fun original(actual: Any, body: JsonObject): Boolean {
        PhoneScreenControl.validateBody(body, PhoneScreenControl.REPORT)
        return actual === parent && base.all { (key, value) -> body[key] == value }
    }

    fun acceptOffer(actual: Any, body: JsonObject): Boolean {
        if (!original(actual, body) || body.string("op") != "offer") return false
        current()
        synchronized(gate) {
            if (phase != Phase.Probe) return false
            session = JsonPrimitive(body.string("session"))
            phase = Phase.Offered
            return true
        }
    }

    /** Writer must invoke the supplied guard on the original protected connection.
     * Start the data-socket proof only after this call returns successfully. */
    fun prepared(requireCapture: () -> Unit, writeOriginal: (JsonObject, () -> Unit) -> Unit) {
        current()
        val packet = synchronized(gate) {
            check(phase == Phase.Offered) { "screen_control_original_offer_required" }
            phase = Phase.Publishing
            JsonObject(base + ("op" to JsonPrimitive("prepared")) + ("session" to checkNotNull(session)))
        }
        val guard: () -> Unit = {
            current()
            requireCapture()
            synchronized(gate) { check(phase == Phase.Publishing) { "screen_control_retired" } }
        }
        try {
            guard()
            writeOriginal(packet, guard)
            guard()
            synchronized(gate) {
                check(phase == Phase.Publishing) { "screen_control_retired" }
                phase = Phase.Prepared
            }
        } catch (error: Exception) { close(); throw error }
    }

    fun receive(actual: Any, body: JsonObject): Boolean {
        if (!original(actual, body)) return false
        current()
        synchronized(gate) {
            if (session == null || body["session"] != session || phase == Phase.Closed) return false
            when (body.string("op")) {
                "stop", "error" -> phase = Phase.Closed
                "send" -> {
                    if (phase != Phase.Prepared) return false
                    phase = Phase.Sending
                }
                else -> return false
            }
            return true
        }
    }

    fun hasOriginalSend(): Boolean {
        current()
        return synchronized(gate) { phase == Phase.Sending }
    }

    override fun close() { synchronized(gate) { phase = Phase.Closed } }
}
