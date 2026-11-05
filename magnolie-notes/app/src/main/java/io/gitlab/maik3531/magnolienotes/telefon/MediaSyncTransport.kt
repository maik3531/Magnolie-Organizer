package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** One authenticated channel, never a file permission or source-worker owner. */
internal class MediaSyncTransport(private val binding: MediaSettingsBinding,
    private val storage: MediaSyncStorage, private val queue: TelefonQueue, private val ready: () -> Boolean) {
    private var generation = 0L
    private var sent: JsonObject? = null
    private var acknowledged: JsonObject? = null
    private var received: JsonObject? = null
    private val attempts = mutableMapOf<String, JsonObject>()

    @Synchronized fun invalidate() { generation++; sent = null; acknowledged = null; received = null; attempts.clear() }

    @Synchronized fun matched(): Boolean {
        if (!ready()) return false
        val body = storage.read(binding) ?: return false
        return body == sent && body == acknowledged && body == received
    }

    @Synchronized fun queueSettings() {
        if (!ready()) return
        val body = storage.read(binding) ?: return
        if (body == sent || queue.hasKind(binding.peerActor, MediaSyncSettings.KIND)) return
        queue.queue(binding.peerActor, MediaSyncSettings.KIND, body, 86_400_000)
    }

    @Synchronized fun send(message: JsonObject, write: (JsonObject) -> Unit): Boolean {
        if (!ready()) return false
        val id = message.string("message_id")
        val body = message.getValue("body").jsonObject
        if (body != storage.read(binding)) { queue.acknowledge(binding.peerActor, id); return false }
        MediaSyncSettings.validate(body)
        val captured = generation
        attempts.clear(); attempts[id] = body
        try {
            write(message)
            if (!ready()) { invalidate(); return false }
            if (captured == generation) sent = body
            queue.sent(id, queue.attempts(id))
            return true
        } catch (error: Exception) { invalidate(); throw error }
    }

    @Synchronized fun acknowledge(message: JsonObject) {
        TelefonNachrichten.validateAck(message)
        val attempted = attempts.remove(message.string("message_id")) ?: return
        if (!ready()) { invalidate(); return }
        acknowledged = attempted.takeIf { message.string("status") in setOf("accepted", "duplicate") && message.string("error") == "none" }
    }

    @Synchronized fun receive(message: JsonObject, write: (JsonObject) -> Unit) {
        val captured = generation
        val result = runCatching {
            TelefonNachrichten.validate(message)
            check(ready()) { "not_granted" }
            val body = message.getValue("body").jsonObject
            MediaSyncSettings.validate(body)
            if (queue.duplicateResult(binding.peerActor, message.string("message_id")) != null)
                require(queue.receivedMatches(binding.peerActor, message))
            storage.merge(binding, body) // Commit and exact readback before ACK/echo.
            check(ready()) { "not_granted" }
            queue.receive(binding.peerActor, message)
        }.getOrElse { "rejected" to when (it) {
            is java.io.IOException, is android.database.sqlite.SQLiteException, is java.security.GeneralSecurityException -> "temporary_failure"
            is IllegalArgumentException, is TelefonProtokollFehler -> "invalid_schema"
            else -> "not_granted"
        } }
        try {
            write(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second))
            if (result.first in setOf("accepted", "duplicate") && ready()) {
                if (captured == generation) received = message.getValue("body").jsonObject
                if (storage.read(binding) != sent) queue.removeKind(binding.peerActor, MediaSyncSettings.KIND)
                queueSettings()
            } else invalidate()
        } catch (error: Exception) { invalidate(); throw error }
    }
}
