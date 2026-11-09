package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Looper
import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Exact live replacement acceptance -> encrypted staging only. There is no
 * insert, old-row writer, Saved output, resume-by-metadata or discovery hook. */
internal class NativeGalleryPcReplacementTransfer private constructor(private val owner: NativeGalleryIncomingOwner,
    private val channel: TelefonSecureChannel, private val stage: NativeGalleryPcStage, private val grant: NativeGalleryPcWriteGrant,
    private val lane: Any, private val issued: Long, private val ttl: Long) : AutoCloseable {
    private class Pending(val request: DeviceFileChunkRequest) {
        val ready = CountDownLatch(1)
        val sent = AtomicBoolean(false)
        val bytes = AtomicReference<ByteArray?>()
    }
    private val ended = AtomicBoolean(false)
    private val accepting = AtomicBoolean(false)
    private val accepted = AtomicBoolean(false)
    private val receiving = AtomicBoolean(false)
    private val finished = AtomicBoolean(false)
    private val writeTargetAttempted = AtomicBoolean(false)
    private val pending = AtomicReference<Pending?>()
    private val lifecycle = Any()
    private var inFlight = 0
    private var retired = false
    private var drainPublished = false
    private var writeTarget: NativeGalleryPcWriteTarget? = null
    private val drained = CountDownLatch(1)
    private var last = issued
    private val acceptance = stage.record.acceptance
    @Synchronized private fun clock() {
        val now = DeviceFileControl.monotonicMs(); val wall = System.currentTimeMillis()
        if (ended.get() || now < last || now - issued >= ttl || wall < acceptance.body.long("created_ms") || wall >= acceptance.expires)
            fail("gallery_pc_stage_offer_expired")
        last = now
    }
    private fun current() {
        try { clock(); stage.requireCurrent(); clock() } catch (error: Throwable) { close(); throw error }
    }
    private inline fun <T> io(action: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_worker_io_required")
        synchronized(lifecycle) { if (ended.get()) fail("gallery_pc_stage_closed"); inFlight++ }
        try { return action() }
        catch (error: Throwable) { close(); throw error }
        finally { endIo() }
    }
    private fun finishDrain() {
        if (ended.get() && retired && inFlight == 0 && !drainPublished) {
            writeTarget?.close(); writeTarget = null
            drainPublished = true; NativeGalleryMediaIoLane.release(lane); drained.countDown()
        }
    }
    private fun endIo() { synchronized(lifecycle) { inFlight--; finishDrain() } }
    internal fun awaitIoEnded(timeoutMillis: Long): Boolean = drained.await(timeoutMillis, TimeUnit.MILLISECONDS)
    internal fun sendAcceptance(): JsonObject = io {
        if (!accepting.compareAndSet(false, true)) fail("gallery_incoming_acceptance_already_attempted")
        try {
            current(); val now = System.currentTimeMillis()
            val message = TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                put("format", 1); put("offer_id", acceptance.body.string("offer_id")); put("manifest_sha256", owner.manifest.fingerprint)
                put("transfer_id", owner.manifest.transferId); put("acceptance_sha256", acceptance.id)
                put("permission_epoch", owner.binding.permissionEpoch); put("destination_token", owner.binding.destinationToken)
            }, acceptance.expires - now, now)
            DeviceFileAcceptanceEnvelope.parse(message, now)
            current(); channel.send(message); current(); accepted.set(true); message
        } catch (error: Throwable) { close(); throw error }
    }
    private fun readChunk(number: Int): ByteArray {
        current()
        if (!accepted.get() || finished.get()) fail("gallery_incoming_actual_acceptance_output_required")
        val file = owner.manifest.files.single(); val now = System.currentTimeMillis()
        val message = TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
            put("format", 1); put("transfer_id", owner.manifest.transferId); put("manifest_sha256", owner.manifest.fingerprint)
            put("acceptance_sha256", acceptance.id); put("permission_epoch", owner.binding.permissionEpoch)
            put("destination_token", owner.binding.destinationToken); put("file_id", file.id); put("chunk_index", number)
        }, acceptance.expires - now, now)
        val attempt = Pending(DeviceFileChunkEnvelope.parseRequest(message, now))
        if (!pending.compareAndSet(null, attempt)) fail("gallery_incoming_chunk_worker_busy")
        try {
            current(); channel.send(message); current(); attempt.sent.set(true)
            if (attempt.bytes.get() != null) attempt.ready.countDown()
            val remaining = minOf(minOf(attempt.request.expires, acceptance.expires) - System.currentTimeMillis(),
                ttl - (DeviceFileControl.monotonicMs() - issued), grant.request.admission.remainingMs())
            if (remaining <= 0 || !attempt.ready.await(remaining, TimeUnit.MILLISECONDS)) fail("gallery_incoming_chunk_timeout")
            current(); return attempt.bytes.getAndSet(null) ?: fail("gallery_incoming_chunk_not_received")
        } finally { pending.compareAndSet(attempt, null); attempt.bytes.getAndSet(null)?.fill(0) }
    }
    internal fun observeChunk(source: TelefonSecureChannel, message: JsonObject): Boolean {
        if (source !== channel || message["kind"] != JsonPrimitive(DeviceFileChunkEnvelope.RESULT)) return false
        val attempt = pending.get() ?: return false
        val body = message["body"] as? JsonObject ?: return false
        if (body["request_id"] != JsonPrimitive(attempt.request.requestId)) return false
        if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_worker_io_required")
        synchronized(lifecycle) { if (ended.get()) return false; inFlight++ }
        try {
            current(); val now = System.currentTimeMillis(); TelefonNachrichten.validateHeader(message, now)
            if (!accepted.get() || now >= message.long("expires_ms") || now >= attempt.request.expires || message.long("expires_ms") > attempt.request.expires ||
                message.long("expires_ms") - message.long("created_ms") > DeviceFileControl.MAX_TTL_MS || TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX ||
                body.keys != setOf("format", "request_id", "transfer_id", "manifest_sha256", "acceptance_sha256", "permission_epoch", "destination_token", "file_id", "chunk_index", "data_base64", "data_sha256") ||
                body["format"] != JsonPrimitive(1)) fail("gallery_incoming_chunk_invalid")
            val request = attempt.request
            val expected = mapOf("transfer_id" to JsonPrimitive(request.transferId), "manifest_sha256" to JsonPrimitive(request.manifestSha256),
                "acceptance_sha256" to JsonPrimitive(request.acceptanceSha256), "permission_epoch" to JsonPrimitive(request.permissionEpoch),
                "destination_token" to JsonPrimitive(request.destinationToken), "file_id" to JsonPrimitive(request.fileId), "chunk_index" to JsonPrimitive(request.chunkIndex))
            if (expected.any { body[it.key] != it.value }) fail("gallery_incoming_chunk_binding_changed")
            val file = owner.manifest.files.single()
            val wanted = minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), file.size - request.chunkIndex.toLong() * DeviceFileManifest.CHUNK_BYTES).toInt()
            val encoded = (body["data_base64"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail("gallery_incoming_chunk_invalid")
            if (wanted <= 0 || encoded.length != ((wanted + 2) / 3) * 4) fail("gallery_incoming_chunk_invalid")
            val bytes = Base64.getDecoder().decode(encoded)
            try {
                if (bytes.size != wanted || Base64.getEncoder().encodeToString(bytes) != encoded ||
                    body["data_sha256"] != JsonPrimitive(NativeHex.lower(MessageDigest.getInstance("SHA-256").digest(bytes)))) fail("gallery_incoming_chunk_hash_changed")
                current()
                if (pending.get() !== attempt) return false
                val held = bytes.copyOf()
                if (!attempt.bytes.compareAndSet(null, held)) {
                    held.fill(0)
                    if (attempt.bytes.get()?.contentEquals(bytes) != true) fail("gallery_incoming_chunk_equivocation")
                }
                if (ended.get() || pending.get() !== attempt) { attempt.bytes.getAndSet(null)?.fill(0); return false }
                if (attempt.sent.get()) attempt.ready.countDown()
                return true
            } finally { bytes.fill(0) }
        } catch (error: Throwable) { close(); throw error }
        finally { endIo() }
    }
    internal fun receiveAndStage(): NativeIncomingMediaObservation = io {
        if (!accepted.get() || !receiving.compareAndSet(false, true)) fail("gallery_incoming_actual_acceptance_output_required")
        try {
            current(); grant.requireUnused()
            val count = ((owner.manifest.totalBytes + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
            repeat(count) { number ->
                val bytes = readChunk(number)
                try { stage.append(number, bytes) } finally { bytes.fill(0) }
            }
            val observation = stage.finish(); current(); finished.set(true); observation
        } catch (error: Throwable) { close(); throw error }
    }
    internal fun sealedRecord(): GalleryPcStageRecord = io {
        current()
        if (!finished.get() || !stage.record.sealed) fail("gallery_pc_stage_not_complete")
        stage.record
    }
    internal fun readStagedAt(position: Long, target: ByteArray, offset: Int, length: Int): Int = io {
        current()
        if (!finished.get()) fail("gallery_pc_stage_not_complete")
        stage.readAt(position, target, offset, length).also { current() }
    }
    /** Still no writer: recheck the real original and independent recovery
     * archive under this exact live lane, then durably record the observation. */
    internal fun prepareBeforeWrite(rows: NativeGalleryIncomingRows, archive: NativeGalleryTrashArchive,
        cancellation: android.os.CancellationSignal = android.os.CancellationSignal()): GalleryPcPreWriteRecord = io {
        current()
        if (!finished.get()) fail("gallery_pc_stage_not_complete")
        grant.requireUnused(); stage.verifyRaw()
        rows.preparePcBeforeWrite(stage, grant, archive, lane, cancellation).also { current() }
    }
    /** Holds the actual rw FD until parent retirement AND all current IO drains.
     * It is deliberately not returned to callers and exposes no mutation API. */
    internal fun prepareWriteTarget(rows: NativeGalleryIncomingRows, archive: NativeGalleryTrashArchive,
        cancellation: android.os.CancellationSignal = android.os.CancellationSignal()): Unit = io {
        current()
        if (!finished.get() || !writeTargetAttempted.compareAndSet(false, true)) fail("gallery_pc_write_target_original_operation_required")
        val target = rows.preparePcWriteTarget(stage, grant, archive, lane, cancellation)
        try {
            current(); target.requireCurrent()
            synchronized(lifecycle) {
                if (ended.get() || writeTarget != null) fail("gallery_pc_write_target_original_operation_required")
                writeTarget = target
            }
        } catch (error: Throwable) { target.close(); throw error }
    }
    /** Durable fence only, still no first byte mutation or completion receipt. */
    internal fun markWriteStarted(): GalleryPcPreWriteRecord = io {
        current()
        val target = synchronized(lifecycle) { writeTarget } ?: fail("gallery_pc_before_write_native_proof_required")
        target.startWrite().also { current() }
    }
    /** Internal mutation only. The durable journal remains write_started until
     * separate actual provider readback and history CAS exist. Never Saved. */
    internal fun copyReplacementBytes(archive: NativeGalleryTrashArchive,
        boundary: (String) -> Unit = {}): NativeGalleryPcWrittenBytesObservation = io {
        current()
        val target = synchronized(lifecycle) { writeTarget } ?: fail("gallery_pc_before_write_native_proof_required")
        target.copyVerifiedBytes(archive, boundary).also { current() }
    }
    override fun close() {
        synchronized(lifecycle) { if (!ended.compareAndSet(false, true)) return }
        try { stage.close(); owner.close(); grant.request.close() }
        finally {
            pending.getAndSet(null)?.let { it.bytes.getAndSet(null)?.fill(0); it.ready.countDown() }
            synchronized(lifecycle) { retired = true; finishDrain() }
        }
    }
    companion object {
        internal fun prepare(context: Context, index: PhotoSourceJobIndex, plan: GalleryPcReplacementPlan,
            grant: NativeGalleryPcWriteGrant, channel: TelefonSecureChannel, boundary: (String) -> Unit = {}): NativeGalleryPcReplacementTransfer {
            if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_incoming_worker_io_required")
            val issued = DeviceFileControl.monotonicMs(); val now = System.currentTimeMillis()
            index.requirePcStageAdmission(grant, channel, plan)
            val media = MediaOfferEnvelope.validate(plan.body.getValue("offer").jsonObject,
                plan.body.getValue("binding").jsonObject.string("sender_id"), plan.body.getValue("binding").jsonObject.string("receiver_id"), now)
            if (media.kind != GalleryMediaType.IMAGES) fail("gallery_pc_stage_video_owner_required")
            val ttl = minOf(DeviceFileControl.MAX_TTL_MS, media.offer.long("expires_ms") - now)
            val lane = Any()
            if (!NativeGalleryMediaIoLane.acquire(lane)) fail("gallery_incoming_worker_busy")
            var owner: NativeGalleryIncomingOwner? = null; var stage: NativeGalleryPcStage? = null
            try {
                owner = grant.request.admission.incomingOwner(media)
                val initial = GalleryIncomingAcceptance.create(owner, media.offer, now)
                val acceptance = GalleryIncomingAcceptance.parse(JsonObject(initial.body + ("expires_ms" to JsonPrimitive(
                    minOf(initial.expires, System.currentTimeMillis() + grant.request.admission.remainingMs())))))
                stage = NativeGalleryPcStage.allocate(context, index, plan, acceptance, owner, grant, channel, lane, boundary)
                return NativeGalleryPcReplacementTransfer(owner, channel, stage, grant, lane, issued, ttl).also { it.current() }
            } catch (error: Throwable) { stage?.close(); owner?.close(); grant.request.close(); NativeGalleryMediaIoLane.release(lane); throw error }
        }
        private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
    }
}
