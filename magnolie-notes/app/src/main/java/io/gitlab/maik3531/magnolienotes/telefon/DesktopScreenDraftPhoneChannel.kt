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
    private enum class Phase { NEW, WRITING, WRITTEN, TAKEN, PREPARING, PREPARED, ACTIVE, CLOSED }
    private val gate = Any()
    private var phase = Phase.NEW
    private var edge = false
    private var session: JsonPrimitive? = null
    private var pending: JsonObject? = null
    private var proof: JsonPrimitive? = null
    private var preparedEdge = false
    private var receivedSend = false
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
        if (phase == Phase.CLOSED || phase != Phase.ACTIVE && clock() - setupDeadlineNanos >= 0) {
            retireLocked()
            error("desktop_screen_original_request_retired")
        }
    }

    fun requireCurrent() {
        try {
            wire.current()
            synchronized(gate) { currentLocked() }
        } catch (failure: Exception) { close(); throw failure }
    }

    fun writeRequest() {
        requireCurrent()
        synchronized(gate) {
            currentLocked()
            check(phase == Phase.NEW)
            phase = Phase.WRITING
        }
        try {
            wire.write(JsonObject(base + ("op" to JsonPrimitive("request")))) {
                synchronized(gate) { currentLocked(); check(phase == Phase.WRITING); edge = true }
            }
            requireCurrent()
            synchronized(gate) { currentLocked(); check(edge); phase = Phase.WRITTEN }
        } catch (failure: Exception) { close(); throw failure }
    }

    fun receive(actual: TelefonSecureChannel, frame: JsonObject): Boolean {
        val body = wire.readFrom(actual, frame) ?: return false
        if (base.any { (k, v) -> body[k] != v }) return false
        synchronized(gate) {
            if (phase == Phase.CLOSED) return false
            val incoming = body.getValue("session") as JsonPrimitive
            if (body["op"] == JsonPrimitive("stop")) {
                if (session != incoming) return false
                retireLocked()
                return true
            }
            currentLocked()
            return when (body["op"]) {
                JsonPrimitive("offer") -> {
                    if (!edge || session != null || phase !in setOf(Phase.WRITING, Phase.WRITTEN)) return false
                    session = incoming
                    pending = JsonObject(body.toMap())
                    true
                }
                JsonPrimitive("send") -> {
                    if (session != incoming || !preparedEdge || receivedSend || proof != body["transcript"] ||
                        phase !in setOf(Phase.PREPARING, Phase.PREPARED)) return false
                    receivedSend = true
                    true
                }
                else -> false
            }
        }
    }

    fun takeOffer(): JsonObject? {
        requireCurrent()
        return synchronized(gate) {
            currentLocked()
            if (phase != Phase.WRITTEN) null else pending?.also { pending = null; phase = Phase.TAKEN }
        }
    }

    /** Only the original visible receiver after its own successful data proof. */
    fun writePrepared(transcript: ByteArray, requireViewerAndProof: () -> Unit) {
        require(transcript.size == 32)
        requireCurrent()
        requireViewerAndProof()
        val value = JsonPrimitive(transcript.joinToString("") { "%02x".format(it) })
        val message = synchronized(gate) {
            currentLocked()
            check(phase == Phase.TAKEN)
            phase = Phase.PREPARING
            proof = value
            JsonObject(base + mapOf("op" to JsonPrimitive("prepared"), "session" to checkNotNull(session), "transcript" to value))
        }
        try {
            wire.write(message) {
                requireViewerAndProof()
                synchronized(gate) { currentLocked(); check(phase == Phase.PREPARING); preparedEdge = true }
            }
            requireViewerAndProof()
            requireCurrent()
            synchronized(gate) { currentLocked(); check(preparedEdge); phase = Phase.PREPARED }
        } catch (failure: Exception) { close(); throw failure }
    }

    /** Delivers one receipt to the native receiver, never before PREPARED returns. */
    fun takeSend(): ByteArray? {
        requireCurrent()
        return synchronized(gate) {
            currentLocked()
            if (phase != Phase.PREPARED || !receivedSend) return null
            val digest = checkNotNull(proof).content.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
            proof = null
            phase = Phase.ACTIVE
            digest
        }
    }

    private fun retireLocked() {
        phase = Phase.CLOSED
        pending = null
        proof = null
    }

    override fun close() {
        synchronized(gate) { retireLocked() }
    }
}
