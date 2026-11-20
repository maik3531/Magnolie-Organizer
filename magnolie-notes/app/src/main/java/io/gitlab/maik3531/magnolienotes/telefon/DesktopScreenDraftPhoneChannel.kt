package io.gitlab.maik3531.magnolienotes.telefon

import java.security.SecureRandom
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Private adapter for an explicit native draft caller. Never register this as a
 * product message or feed it to the ordinary queue. Incoming payloads must come
 * from the sole, original authenticated reader. The guard is nonblocking. */
internal class DesktopScreenDraftPhoneChannel(private val channel: TelefonSecureChannel,
    private val pipe: TelefonTcpRoehre, private val requireParent: () -> Unit) {
    fun current() {
        requireParent()
        channel.requireOriginalWlanPipe(pipe)
        requireParent()
    }

    fun write(body: JsonObject, atWrite: () -> Unit) {
        DesktopScreenDraftControl.validate(body, DesktopScreenDraftControl.Role.PHONE)
        val frame = JsonObject(mapOf("type" to JsonPrimitive(TYPE), "body" to body))
        current()
        channel.sendEphemeral(frame, pipe, { current(); atWrite() })
        current()
    }

    fun readFrom(actual: TelefonSecureChannel, frame: JsonObject): JsonObject? {
        if (actual !== channel) return null
        current()
        require(frame.keys == setOf("type", "body") && frame["type"] == JsonPrimitive(TYPE))
        val body = requireNotNull(frame["body"] as? JsonObject)
        return DesktopScreenDraftControl.validate(body, DesktopScreenDraftControl.Role.DESKTOP)
    }

    companion object {
        const val TYPE = "desktop_screen_draft"
    }
}

/** Owns one native phone action and one deadline for accepting an exact offer.
 * The caller must retain the slot through retirement and separately obtain the
 * visible viewer's approval. Taking an offer is not consent or media authority. */
internal class DesktopScreenDraftPhoneRequest(private val wire: DesktopScreenDraftPhoneChannel, mode: Int,
    budgetMs: Long, private val clock: () -> Long = System::nanoTime, wallMs: () -> Long = System::currentTimeMillis) : AutoCloseable {
    private enum class Phase { NEW, WRITING, WRITTEN, CLOSED }
    private val gate = Any()
    private var phase = Phase.NEW
    private var edge = false
    private var offered = false
    private var pending: JsonObject? = null
    val setupDeadlineNanos: Long
    private val base: Map<String, JsonPrimitive>

    init {
        require(mode in 1..2 && budgetMs in 1..30_000)
        setupDeadlineNanos = clock() + TimeUnit.MILLISECONDS.toNanos(budgetMs)
        val id = ByteArray(16).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) }
        base = mapOf("draft" to JsonPrimitive(DesktopScreenDraftControl.DRAFT), "request" to JsonPrimitive(id),
            "mode" to JsonPrimitive(mode), "setup_until_ms" to JsonPrimitive(Math.addExact(wallMs(), budgetMs)))
    }

    private fun currentLocked() {
        if (phase == Phase.CLOSED || clock() - setupDeadlineNanos >= 0) {
            phase = Phase.CLOSED
            pending = null
            error("desktop_screen_original_request_retired")
        }
    }

    private fun current() {
        try {
            wire.current()
            synchronized(gate) { currentLocked() }
        } catch (failure: Exception) { close(); throw failure }
    }

    fun writeRequest() {
        current()
        synchronized(gate) {
            currentLocked()
            check(phase == Phase.NEW)
            phase = Phase.WRITING
        }
        try {
            wire.write(JsonObject(base + ("op" to JsonPrimitive("request")))) {
                synchronized(gate) { currentLocked(); check(phase == Phase.WRITING); edge = true }
            }
            current()
            synchronized(gate) { currentLocked(); check(edge); phase = Phase.WRITTEN }
        } catch (failure: Exception) { close(); throw failure }
    }

    fun receiveOffer(actual: TelefonSecureChannel, frame: JsonObject): Boolean {
        val body = wire.readFrom(actual, frame) ?: return false
        if (body["op"] != JsonPrimitive("offer") || base.any { (k, v) -> body[k] != v }) return false
        current()
        synchronized(gate) {
            currentLocked()
            if (!edge || offered) return false
            offered = true
            pending = body
            return true
        }
    }

    fun takeOffer(): JsonObject? {
        current()
        return synchronized(gate) {
            currentLocked()
            if (phase != Phase.WRITTEN) null else pending.also { pending = null }
        }
    }

    override fun close() {
        synchronized(gate) { phase = Phase.CLOSED; pending = null }
    }
}
