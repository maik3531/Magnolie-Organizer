package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/** Settings only, after separate support on the original reader. No file
 * owner, worker, Android permissions or personal outbox belong to this lane. */
internal class NativeMediaSettingsLane(
    private val binding: MediaSettingsBinding,
    private val storage: MediaSyncStorage,
    private val ready: () -> Boolean,
    private val originalLive: () -> Boolean,
    private val write: (JsonObject) -> Unit,
) : NativeGalleryMediaAgreement {
    private val incoming = mutableMapOf<String, JsonObject>()
    private val outgoing = mutableSetOf<String>()
    private var sent: JsonObject? = null
    private var received: JsonObject? = null
    private var acknowledged: JsonObject? = null
    private var pending: String? = null
    private var failed = false
    @Volatile private var intent: MediaSyncTransport.IntentToken? = null

    private fun requireCurrent() = check(!failed && ready()) { "media_shared_original_reader_retired" }

    @Synchronized fun change(field: String, value: JsonElement, expectedVersion: String) {
        requireCurrent()
        require(field != "skip_deletions")
        intent = null
        storage.change(binding, field, value, expectedVersion)
        sendSettings()
        publish()
    }

    private fun sendSettings() {
        requireCurrent()
        val body = storage.read(binding) ?: return
        if (body == sent) return
        intent = null
        check(outgoing.size < MAX_MESSAGES) { "media_shared_session_capacity" }
        val message = TelefonNachrichten.message(MediaSyncSettings.KIND, body, 86_400_000)
        val id = message.string("message_id")
        check(outgoing.add(id))
        write(message)
        requireCurrent()
        pending = id
        sent = body
        acknowledged = null
    }

    @Synchronized fun receive(message: JsonObject) {
        TelefonNachrichten.validate(message)
        check(message["kind"] == JsonPrimitive(MediaSyncSettings.KIND))
        val body = message.getValue("body").jsonObject
        val id = message.string("message_id")
        if (failed || !ready()) return
        var writing = false
        try {
            val previous = incoming[id]
            if (previous != null && previous != message) {
                intent = null
                writing = true
                write(TelefonNachrichten.ack(id, "rejected", "invalid_schema"))
                failed = true
                return
            }
            check(previous != null || incoming.size < MAX_MESSAGES) { "media_shared_session_capacity" }
            if (intent?.body != body) intent = null
            storage.merge(binding, body)
            requireCurrent()
            writing = true
            write(TelefonNachrichten.ack(id, if (previous == null) "accepted" else "duplicate", "none"))
            requireCurrent()
            incoming[id] = message
            received = body
            sendSettings()
            publish()
        } catch (error: Exception) {
            intent = null
            failed = true
            // A stopped private settings operation is not a request to close
            // the Notes parent. Never send a second ACK once output was attempted.
            if (error is InterruptedException) Thread.currentThread().interrupt()
            else if (!writing && ready()) {
                val code = when (error) {
                    is IllegalArgumentException, is TelefonProtokollFehler -> "invalid_schema"
                    is java.io.IOException, is android.database.sqlite.SQLiteException,
                    is java.security.GeneralSecurityException -> "temporary_failure"
                    else -> "not_granted"
                }
                write(TelefonNachrichten.ack(id, "rejected", code))
            }
        }
    }

    @Synchronized fun receiveAck(message: JsonObject): Boolean {
        if (message["type"] != JsonPrimitive("ack")) return false
        val id = (message["message_id"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return false
        if (id !in outgoing) return false
        TelefonNachrichten.validateAck(message)
        if (pending == id && !failed && ready()) {
            pending = null
            acknowledged = sent.takeIf { message["error"] == JsonPrimitive("none") &&
                message["status"] in setOf(JsonPrimitive("accepted"), JsonPrimitive("duplicate")) }
            publish()
        }
        return true // Also consume an old receipt without restoring agreement.
    }

    private fun publish() {
        val snapshot = sent
        intent = if (snapshot != null && matched(snapshot))
            intent?.takeIf { it.body == snapshot } ?: MediaSyncTransport.IntentToken(snapshot) else null
    }

    @Synchronized override fun matched(expected: JsonObject?): Boolean {
        if (failed || !ready()) return false
        val local = storage.read(binding) ?: return false
        return (expected == null || local == expected) && local == sent && local == received && local == acknowledged
    }

    // Source/index guards call these while holding their own locks. Do not
    // acquire the lane, Werk, storage or the secure writer from these methods.
    override fun intentFor(mediaType: GalleryMediaType): MediaSyncTransport.IntentToken? =
        intent?.takeIf { originalLive() && it.requestedOutgoing(mediaType) }

    override fun incomingIntentFor(mediaType: GalleryMediaType): MediaSyncTransport.IntentToken? =
        intent?.takeIf { originalLive() && it.requestedIncoming(mediaType) }

    private companion object { const val MAX_MESSAGES = 128 }
}
