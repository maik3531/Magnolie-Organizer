package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import android.os.CancellationSignal
import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** One actual authenticated incoming offer, owned by a serialized native media
 * worker. No listener, scheduler, durable replay, capability or factory starts
 * here. observeChunk is called only by that exact channel's native dispatcher.
 * The worker never holds index locks while sending/waiting for network IO. */
internal class NativeGalleryIncomingTransfer private constructor(private val owner: NativeGalleryIncomingOwner,
    private val channel: TelefonSecureChannel, private val index: PhotoSourceJobIndex,
    private val rows: NativeGalleryIncomingRows, private val mimeTypes: Map<String, String>,
    internal val acceptance: GalleryIncomingAcceptance, private val wall: () -> Long) : AutoCloseable {
    private class Pending(val request: DeviceFileChunkRequest) {
        val ready = CountDownLatch(1)
        val sent = AtomicBoolean(false)
        val bytes = AtomicReference<ByteArray?>()
    }
    private val ended = AtomicBoolean(false)
    private val acceptanceStarted = AtomicBoolean(false)
    private val acceptanceSent = AtomicBoolean(false)
    private val runStarted = AtomicBoolean(false)
    private val savedSent = AtomicBoolean(false)
    private val pending = AtomicReference<Pending?>()
    internal val actualSavedOutput: Boolean get() = savedSent.get()
    private var publishedOutput: List<GalleryIncomingPublication> = emptyList()
    internal fun actualPublishedOutput(): List<GalleryIncomingPublication> =
        if (savedSent.get()) publishedOutput.toList() else emptyList()

    private fun current() {
        if (ended.get() || wall() >= acceptance.expires || wall() < acceptance.body.long("created_ms")) fail("gallery_incoming_transfer_expired")
        owner.requireChannel(channel)
        if (index.incomingAcceptance(acceptance.id)?.body != acceptance.body) fail("gallery_incoming_acceptance_changed")
    }
    private fun ioRequired() { if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_worker_io_required") }

    internal fun sendAcceptance(): JsonObject {
        ioRequired()
        if (!acceptanceStarted.compareAndSet(false, true)) fail("gallery_incoming_acceptance_already_attempted")
        try {
            current(); val now = wall()
            val message = TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                put("format", 1); put("offer_id", acceptance.body.string("offer_id")); put("manifest_sha256", owner.manifest.fingerprint)
                put("transfer_id", owner.manifest.transferId); put("acceptance_sha256", acceptance.id)
                put("permission_epoch", owner.binding.permissionEpoch); put("destination_token", owner.binding.destinationToken)
            }, acceptance.expires - now, now)
            DeviceFileAcceptanceEnvelope.parse(message, now)
            current(); channel.send(message); current(); acceptanceSent.set(true)
            return message
        } catch (error: Exception) { close(); throw error }
    }

    /** At most one pending request and one bounded owned chunk. A response that
     * races the actual send is retained but cannot wake the worker until the
     * encrypted request write has really returned successfully. */
    private fun readChunk(fileId: String, chunk: Int): ByteArray {
        current()
        if (!acceptanceSent.get()) fail("gallery_incoming_actual_acceptance_output_required")
        val now = wall()
        val message = TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
            put("format", 1); put("transfer_id", owner.manifest.transferId); put("manifest_sha256", owner.manifest.fingerprint)
            put("acceptance_sha256", acceptance.id); put("permission_epoch", owner.binding.permissionEpoch)
            put("destination_token", owner.binding.destinationToken); put("file_id", fileId); put("chunk_index", chunk)
        }, acceptance.expires - now, now)
        val attempt = Pending(DeviceFileChunkEnvelope.parseRequest(message, now))
        if (!pending.compareAndSet(null, attempt)) fail("gallery_incoming_chunk_worker_busy")
        try {
            current(); channel.send(message); current(); attempt.sent.set(true)
            if (attempt.bytes.get() != null) attempt.ready.countDown()
            val remaining = minOf(attempt.request.expires, acceptance.expires) - wall()
            if (remaining <= 0 || !attempt.ready.await(remaining, TimeUnit.MILLISECONDS)) fail("gallery_incoming_chunk_timeout")
            current()
            return attempt.bytes.getAndSet(null) ?: fail("gallery_incoming_chunk_not_received")
        } catch (error: Exception) { close(); throw error }
        finally { pending.compareAndSet(attempt, null); attempt.bytes.getAndSet(null)?.fill(0) }
    }

    internal fun observeChunk(source: TelefonSecureChannel, message: JsonObject): Boolean {
        if (source !== channel || message["kind"] != JsonPrimitive(DeviceFileChunkEnvelope.RESULT)) return false
        val attempt = pending.get() ?: return false
        val body = message["body"] as? JsonObject ?: return false
        if (body["request_id"] != JsonPrimitive(attempt.request.requestId)) return false
        try {
            current()
            val now = wall(); TelefonNachrichten.validateHeader(message, now)
            if (!acceptanceSent.get() || now >= message.long("expires_ms") || now >= attempt.request.expires ||
                message.long("expires_ms") > attempt.request.expires ||
                message.long("expires_ms") - message.long("created_ms") > DeviceFileControl.MAX_TTL_MS ||
                TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX ||
                body.keys != setOf("format", "request_id", "transfer_id", "manifest_sha256", "acceptance_sha256", "permission_epoch",
                    "destination_token", "file_id", "chunk_index", "data_base64", "data_sha256") || body["format"] != JsonPrimitive(1))
                fail("gallery_incoming_chunk_invalid")
            val request = attempt.request
            val expected = mapOf("transfer_id" to JsonPrimitive(request.transferId), "manifest_sha256" to JsonPrimitive(request.manifestSha256),
                "acceptance_sha256" to JsonPrimitive(request.acceptanceSha256), "permission_epoch" to JsonPrimitive(request.permissionEpoch),
                "destination_token" to JsonPrimitive(request.destinationToken), "file_id" to JsonPrimitive(request.fileId), "chunk_index" to JsonPrimitive(request.chunkIndex))
            if (expected.any { body[it.key] != it.value }) fail("gallery_incoming_chunk_binding_changed")
            val file = owner.manifest.files.singleOrNull { it.id == request.fileId } ?: fail("gallery_incoming_chunk_invalid")
            val wanted = minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), file.size - request.chunkIndex.toLong() * DeviceFileManifest.CHUNK_BYTES).toInt()
            val encoded = (body["data_base64"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail("gallery_incoming_chunk_invalid")
            if (wanted <= 0 || encoded.length != ((wanted + 2) / 3) * 4) fail("gallery_incoming_chunk_invalid")
            val bytes = Base64.getDecoder().decode(encoded)
            try {
                if (bytes.size != wanted || Base64.getEncoder().encodeToString(bytes) != encoded ||
                    body["data_sha256"] != JsonPrimitive(MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }))
                    fail("gallery_incoming_chunk_hash_changed")
                current()
                if (pending.get() !== attempt) return false
                val held = bytes.copyOf()
                if (!attempt.bytes.compareAndSet(null, held)) {
                    held.fill(0)
                    if (attempt.bytes.get()?.contentEquals(bytes) != true) fail("gallery_incoming_chunk_equivocation")
                }
                if (pending.get() !== attempt || ended.get()) {
                    attempt.bytes.getAndSet(null)?.fill(0); return false
                }
                if (attempt.sent.get()) attempt.ready.countDown()
                return true
            } finally { bytes.fill(0) }
        } catch (error: Exception) { close(); throw error }
    }

    internal fun requireCurrent() { current() }

    internal fun receiveAndSendSaved(cancellation: CancellationSignal = CancellationSignal()): JsonObject {
        ioRequired()
        if (!acceptanceSent.get() || !runStarted.compareAndSet(false, true)) fail("gallery_incoming_actual_acceptance_output_required")
        try {
            cancellation.throwIfCanceled(); current(); val published = mutableListOf<GalleryIncomingPublication>()
            for (file in owner.manifest.files) {
                current(); val mime = mimeTypes.getValue(file.id)
                val plan = GalleryIncomingPublication.plan(owner.binding, owner.manifest, file.id, owner.pairingEpoch, owner.kind, mime, owner.scope)
                var selected = index.incomingPublication(plan.id) ?: fail("gallery_incoming_original_changed")
                if (selected.state == "planned") selected = rows.prepare(owner, file.id, mime)
                if (selected.state in setOf("inserted", "copying", "copy_verified"))
                    selected = rows.copyAndVerify(owner, selected, { readChunk(file.id, it) }, cancellation)
                published += rows.publish(owner, selected, cancellation)
            }
            current(); val now = wall()
            val message = TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                put("format", 1); put("transfer_id", owner.manifest.transferId); put("manifest_sha256", owner.manifest.fingerprint)
                put("acceptance_sha256", acceptance.id); put("permission_epoch", owner.binding.permissionEpoch)
                put("destination_token", owner.binding.destinationToken)
                put("receipts", JsonArray(owner.manifest.files.zip(published).map { (file, saved) ->
                    if (saved.state != "published" || index.incomingPublication(saved.id)?.body != saved.body) fail("gallery_incoming_original_changed")
                    buildJsonObject { put("file_id", file.id); put("size", file.size); put("sha256", file.sha256); put("receipt_sha256", saved.fingerprint) }
                }))
            }, acceptance.expires - now, now)
            DeviceFileSavedEnvelope.parse(message, owner.manifest, now)
            current(); channel.send(message); current(); publishedOutput = published.toList(); savedSent.set(true)
            return message // Actual output only, never peer ACK, quota retirement or bilateral completion.
        } catch (error: Exception) { close(); throw error }
    }

    override fun close() {
        if (!ended.compareAndSet(false, true)) return
        pending.getAndSet(null)?.let { it.bytes.getAndSet(null)?.fill(0); it.ready.countDown() }
        owner.close() // Not the shared secure transport socket.
    }

    companion object {
        internal fun prepare(owner: NativeGalleryIncomingOwner, channel: TelefonSecureChannel, index: PhotoSourceJobIndex,
            rows: NativeGalleryIncomingRows, offer: JsonObject, mimeTypes: Map<String, String>,
            wall: () -> Long = System::currentTimeMillis): NativeGalleryIncomingTransfer {
            if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_worker_io_required")
            owner.requireChannel(channel)
            if (mimeTypes.keys != owner.manifest.files.map { it.id }.toSet()) fail("gallery_incoming_media_metadata_required")
            val value = GalleryIncomingAcceptance.create(owner, offer, wall())
            for (file in owner.manifest.files) {
                owner.requireChannel(channel)
                index.reserveIncomingPublication(GalleryIncomingPublication.plan(owner.binding, owner.manifest, file.id,
                    owner.pairingEpoch, owner.kind, mimeTypes.getValue(file.id), owner.scope), owner::requireLocal)
            }
            owner.requireChannel(channel)
            val saved = index.reserveIncomingAcceptance(value, owner::requireLocal)
            owner.requireChannel(channel)
            return NativeGalleryIncomingTransfer(owner, channel, index, rows, mimeTypes.toMap(), saved, wall)
        }
        private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
    }
}
