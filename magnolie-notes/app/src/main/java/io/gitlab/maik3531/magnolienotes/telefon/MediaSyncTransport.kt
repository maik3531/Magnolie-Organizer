package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** One authenticated channel, never a file permission or source-worker owner. */
internal class MediaSyncTransport(private val binding: MediaSettingsBinding,
    private val storage: MediaSyncStorage, private val queue: TelefonQueue,
    private val changed: () -> Unit = {}, private val ready: () -> Boolean) {
    private var generation = 0L
    private var sent: JsonObject? = null
    private var acknowledged: JsonObject? = null
    private var received: JsonObject? = null
    private val attempts = mutableMapOf<String, JsonObject>()
    private var previewPublished = false
    internal class IntentToken internal constructor(internal val body: JsonObject) {
        private val values = MediaSyncSettings.effective(body)
        internal fun requested(mediaType: GalleryMediaType): Boolean = values["enabled"] == JsonPrimitive(true) &&
            values[if (mediaType == GalleryMediaType.IMAGES) "photos_enabled" else "videos_enabled"] == JsonPrimitive(true)
        internal fun requestedIncoming(mediaType: GalleryMediaType): Boolean = requested(mediaType) &&
            values["direction"] == JsonPrimitive("two_way")
    }
    @Volatile private var currentIntent: IntentToken? = null
    private data class ManualRequest(val id: String, val intent: IntentToken, val started: Long)
    private var manualRequest: ManualRequest? = null
    private var manualState = ""

    @Synchronized fun manualStatus(): Pair<Boolean, String> {
        if (manualRequest?.let { android.os.SystemClock.elapsedRealtime() - it.started > 7_200_000L } == true) {
            manualRequest = null; manualState = "held"
        }
        return (manualRequest != null) to manualState
    }

    @Synchronized fun startManual(write: (JsonObject) -> Unit) {
        check(manualStatus().first.not()) { "media_manual_busy" }
        val intent = currentIntent ?: error("media_shared_not_matched")
        check(matched(intent.body) && (intent.requested(GalleryMediaType.IMAGES) || intent.requested(GalleryMediaType.VIDEO))) { "media_shared_not_matched" }
        val body = buildJsonObject { put("format", 1); put("settings", intent.body) }
        MediaSyncSettings.validateStart(body)
        val message = TelefonNachrichten.message(MediaSyncSettings.START_KIND, body, 60_000)
        manualRequest = ManualRequest(message.string("message_id"), intent, android.os.SystemClock.elapsedRealtime())
        manualState = ""; changed()
        try { write(message) }
        catch (error: Exception) { manualRequest = null; manualState = "held"; changed(); throw error }
        // Deliberately no outbox/replay: an explicit action belongs to this
        // current secure channel and exact in-process agreement owner only.
    }

    @Synchronized fun receiveManualResult(message: JsonObject, write: (JsonObject) -> Unit) {
        TelefonNachrichten.validate(message)
        val body = message.getValue("body").jsonObject
        MediaSyncSettings.validateResult(body)
        val request = manualRequest
        val current = request != null && request.id == body.string("request_id") && currentIntent === request.intent && matched(request.intent.body)
        write(TelefonNachrichten.ack(message.string("message_id"), if (current) "accepted" else "rejected", if (current) "none" else "not_granted"))
        if (current) { manualRequest = null; manualState = body.string("state"); changed() }
    }

    // Native source checks may hold their index lock. This projection MUST NOT
    // acquire transport/Werk/storage locks or manufacture any permission.
    internal fun intentFor(mediaType: GalleryMediaType): Any? = currentIntent?.takeIf { it.requested(mediaType) }

    // Incoming media needs the independently matched two-way direction. This
    // remains intent only: never Android consent or a file-control grant. Keep
    // it lock-free for receiver/index guards just like the outgoing projection.
    internal fun incomingIntentFor(mediaType: GalleryMediaType): Any? = currentIntent?.takeIf { it.requestedIncoming(mediaType) }

    private fun publish() {
        val body = try { if (ready()) storage.read(binding) else null }
            catch (error: Exception) { currentIntent = null; throw error }
        currentIntent = if (body != null && body == sent && body == acknowledged && body == received)
            currentIntent?.takeIf { it.body == body } ?: IntentToken(body) else null
        if (manualRequest?.let { it.intent !== currentIntent } == true) { manualRequest = null; manualState = "held" }
        changed()
    }

    @Synchronized fun invalidate() {
        if (manualRequest != null) { manualRequest = null; manualState = "held" }
        currentIntent = null
        generation++; sent = null; acknowledged = null; received = null; attempts.clear()
        previewPublished = false; changed()
    }

    @Synchronized fun matched(expected: JsonObject? = null): Boolean {
        if (!ready()) return false
        val body = storage.read(binding) ?: return false
        return (expected == null || expected == body) && body == sent && body == acknowledged && body == received
    }

    @Synchronized fun queueSettings() {
        val hadManualRequest = manualRequest != null
        manualStatus()
        if (hadManualRequest && manualRequest == null) changed()
        if (!ready()) {
            if (currentIntent != null || sent != null || acknowledged != null || received != null) invalidate()
            return
        }
        if (!previewPublished) { previewPublished = true; changed() }
        val body = storage.read(binding) ?: return
        if (body == sent || queue.hasKind(binding.peerActor, MediaSyncSettings.KIND)) return
        queue.queue(binding.peerActor, MediaSyncSettings.KIND, body, 86_400_000)
    }

    @Synchronized fun send(message: JsonObject, write: (JsonObject) -> Unit): Boolean {
        if (!ready()) { invalidate(); return false }
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
            publish()
            return true
        } catch (error: Exception) { invalidate(); throw error }
    }

    @Synchronized fun acknowledge(message: JsonObject) {
        TelefonNachrichten.validateAck(message)
        if (manualRequest?.id == message.string("message_id")) {
            if (message.string("status") == "rejected") { manualRequest = null; manualState = "held"; changed() }
            return
        }
        val attempted = attempts.remove(message.string("message_id")) ?: return
        if (!ready()) { invalidate(); return }
        acknowledged = attempted.takeIf { message.string("status") in setOf("accepted", "duplicate") && message.string("error") == "none" }
        publish()
    }

    @Synchronized fun receive(message: JsonObject, write: (JsonObject) -> Unit) {
        val captured = generation
        val result = runCatching {
            TelefonNachrichten.validate(message)
            check(ready()) { "not_granted" }
            val body = message.getValue("body").jsonObject
            MediaSyncSettings.validate(body)
            if (currentIntent?.body != body) currentIntent = null
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
                publish()
            } else invalidate()
        } catch (error: Exception) { invalidate(); throw error }
    }
}
