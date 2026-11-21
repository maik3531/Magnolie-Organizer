package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/** Only an observation about shared settings on the original authenticated WLAN parent.
 * No queue, automatic registration, setting, or local media permission belongs here.
 * `current` must only read the native atomic/volatile session and control witnesses.
 */
internal class NativeMediaSupportAttempt(
    private val channel: TelefonSecureChannel,
    private val pipe: TelefonTcpRoehre,
    private val current: () -> Boolean,
    private val wall: () -> Long = System::currentTimeMillis,
    private val monotonicMs: () -> Long = { System.nanoTime() / 1_000_000 },
) : AutoCloseable {
    private val gate = Any()
    private val issued = monotonicMs()
    private val original = offer(wall())
    @Volatile private var retired = false
    @Volatile private var established = false
    private var sent = false
    private var written = false
    private var localAck = false
    private var remoteClaimed = false
    private var remoteAck = false

    init { channel.requireOriginalWlanPipe(pipe) }

    override fun close() { retired = true } // Never close the shared parent here.

    private fun live(from: TelefonSecureChannel): Boolean {
        if (from !== channel || retired) return false
        val now = monotonicMs()
        if (!current() || now < issued || !established && now - issued >= TTL) close()
        return !retired
    }

    fun supports(from: TelefonSecureChannel): Boolean = live(from) && established && !retired

    private fun write(frame: JsonObject): Boolean = try {
        channel.sendEphemeral(frame, pipe, {
            check(live(channel)) { "media_support_original_parent_retired" }
            channel.requireOriginalWlanPipe(pipe)
        })
        true
    } catch (error: InterruptedException) {
        close()
        Thread.currentThread().interrupt()
        false
    } catch (error: Exception) {
        close()
        false
    }

    private fun publish() {
        if (written && localAck && remoteAck && live(channel)) established = true
    }

    fun send(): Boolean {
        synchronized(gate) {
            if (sent || !live(channel)) return false
            sent = true
        }
        if (!write(original)) return false
        return synchronized(gate) {
            written = live(channel)
            publish()
            written
        }
    }

    fun receive(from: TelefonSecureChannel, frame: JsonObject): Boolean {
        synchronized(gate) {
            if (!live(from) || established) return false
            if (frame["type"] == JsonPrimitive("ack")) {
                if (!sent || localAck || frame["message_id"] != original["message_id"]) return false
                if (frame != ack(original)) { close(); return false }
                localAck = true
                publish()
                return true
            }
            if (remoteClaimed || !valid(frame, wall()) || frame["message_id"] == original["message_id"]) return false
            remoteClaimed = true
        }
        if (!write(ack(frame))) return false
        return synchronized(gate) {
            remoteAck = live(from)
            publish()
            remoteAck
        }
    }

    companion object {
        const val KIND = "media_support.hello"
        const val TTL = 10_000L
        private val fields = setOf("type", "v", "message_id", "kind", "created_ms", "expires_ms", "body")
        private val body = JsonObject(mapOf("format" to JsonPrimitive(1), "feature" to JsonPrimitive("shared_settings")))

        fun offer(at: Long): JsonObject = TelefonNachrichten.message(KIND, body, TTL, now = at)
        fun ack(frame: JsonObject): JsonObject = TelefonNachrichten.ack(frame.string("message_id"), "accepted", "none")

        fun valid(frame: JsonObject, now: Long): Boolean {
            if (frame.keys != fields || frame["type"] != JsonPrimitive("message") || frame["v"] != JsonPrimitive(1) ||
                frame["kind"] != JsonPrimitive(KIND) || frame["body"] != body) return false
            val id = frame["message_id"] as? JsonPrimitive ?: return false
            val created = (frame["created_ms"] as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull ?: return false
            val expires = (frame["expires_ms"] as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull ?: return false
            return id.isString && runCatching { TelefonNachrichten.uuid4(id.content) }.isSuccess &&
                created >= 0 && created <= now && now < expires && expires <= 253_402_300_799_999L && expires - created <= TTL
        }
    }
}
