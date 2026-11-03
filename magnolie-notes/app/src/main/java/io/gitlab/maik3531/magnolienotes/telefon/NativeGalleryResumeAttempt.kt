package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.ReentrantLock

/** Metadata projection only. A separate durable native attempt/run commit is
 * required before any Chunk output; the original acceptance stays immutable. */
internal class NativeResumeAcceptanceProjection internal constructor(val attemptId: String, val message: JsonObject,
    val accepted: DeviceFileRemoteAcceptance, val validUntil: Long) {
    val allowsChunkOutput: Boolean get() = false
}

/** Explicit native component, not a registered runtime/wire handler or run owner. */
internal class NativeGalleryResumeAttempt private constructor(private val source: NativeGalleryRenewedSource,
    private val offer: JsonObject, private val expected: DeviceFileRemoteAcceptance, issuedWall: Long,
    private val elapsed: () -> Long) {
    val id: String = java.util.UUID.randomUUID().toString()
    val offerId: String get() = offer.string("message_id")
    val offerExpires: Long get() = offer.long("expires_ms")
    private val gate = ReentrantLock()
    private val canceled = AtomicBoolean(false)
    private var invalid = false
    private var lastWall = issuedWall
    private var lastElapsed = elapsed()
    private val deadline: Long
    private var sent = false
    private var accepted: NativeResumeAcceptanceProjection? = null
    private var storage: NativeResumeAttemptStorage? = null
    init {
        if (lastElapsed < 0 || lastElapsed > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS)
            DeviceFileControl.fail("gallery_resume_attempt_not_current")
        val ttl = minOf(DeviceFileControl.MAX_TTL_MS, offer.long("expires_ms") - issuedWall)
        if (ttl <= 0) DeviceFileControl.fail("gallery_resume_attempt_not_current")
        deadline = lastElapsed + ttl
    }

    fun cancel() { canceled.set(true) } // Never waits behind an actual output.

    fun prepareStorage(index: PhotoSourceJobIndex, now: () -> Long = System::currentTimeMillis): Unit = owned {
        current(now())
        storage = index.prepareResumeAttempt(this, source.job, source.originalAcceptance(), offer) { current(now()) }
        current(now())
    }

    private fun current(wall: Long) {
        try {
            val tick = elapsed()
            if (invalid || canceled.get() || wall < lastWall || tick < lastElapsed || tick >= deadline || wall >= offer.long("expires_ms"))
                DeviceFileControl.fail("gallery_resume_attempt_not_current")
            lastWall = wall; lastElapsed = tick
            val manifest = source.manifest
            if (manifest.fingerprint != expected.manifestSha256 || manifest.transferId != expected.transferId)
                DeviceFileControl.fail("gallery_resume_original_changed")
        } catch (error: Exception) { invalid = true; throw error }
    }

    private inline fun <T> owned(action: () -> T): T {
        if (gate.isHeldByCurrentThread || !gate.tryLock()) DeviceFileControl.fail("gallery_resume_attempt_busy")
        try { return action() } finally { gate.unlock() }
    }

    fun sendOffer(send: (JsonObject) -> Unit, now: () -> Long = System::currentTimeMillis): Unit = owned {
        current(now())
        if (accepted != null) DeviceFileControl.fail("gallery_resume_acceptance_already_bound")
        val durable = storage ?: DeviceFileControl.fail("gallery_resume_attempt_storage_required")
        durable.requireOutput(this); current(now())
        try { send(offer) } catch (error: Exception) {
            // Keep the exact original envelope for retry, but an observed native
            // revocation/expiry remains sticky even if the transport also failed.
            try { current(now()) } catch (_: Exception) { }
            throw error
        }
        current(now()); durable.sent(this) { current(now()) }; current(now()); sent = true
    }

    fun observeAcceptance(message: JsonObject, now: () -> Long = System::currentTimeMillis): NativeResumeAcceptanceProjection = owned {
        val at = now(); current(at)
        if (!sent) DeviceFileControl.fail("gallery_resume_offer_not_sent")
        val durable = storage ?: DeviceFileControl.fail("gallery_resume_attempt_storage_required")
        durable.requireSent(this)
        val remote = DeviceFileAcceptanceEnvelope.parse(message, at)
        if (remote.offerId != offerId || remote.transferId != expected.transferId || remote.manifestSha256 != expected.manifestSha256 ||
            remote.acceptanceSha256 != expected.acceptanceSha256 || remote.permissionEpoch != expected.permissionEpoch ||
            remote.destinationToken != expected.destinationToken) DeviceFileControl.fail("gallery_resume_acceptance_changed")
        val checked = now(); current(checked)
        if (checked >= remote.expires) DeviceFileControl.fail("gallery_resume_attempt_not_current")
        val prior = accepted
        if (prior != null && prior.accepted != remote) DeviceFileControl.fail("gallery_resume_acceptance_already_bound")
        durable.accepted(this, message, checked) {
            val currentWall = now(); current(currentWall)
            if (currentWall >= remote.expires) DeviceFileControl.fail("gallery_resume_attempt_not_current")
        }
        current(now())
        prior ?: NativeResumeAcceptanceProjection(id, message, remote, minOf(remote.expires, offer.long("expires_ms"))).also { accepted = it }
    }

    companion object {
        fun begin(source: NativeGalleryRenewedSource, now: Long = System.currentTimeMillis(),
            elapsed: () -> Long = DeviceFileControl::monotonicMs, ttlMs: Long = DeviceFileControl.MAX_TTL_MS): NativeGalleryResumeAttempt {
            val original = source.originalAcceptance().historicalAcceptance()
            val manifest = source.manifest
            if (original.manifestSha256 != manifest.fingerprint || original.transferId != manifest.transferId)
                DeviceFileControl.fail("gallery_resume_original_changed")
            // This is a NEW bounded offer. No field in the old proof is renewed.
            val offer = DeviceFileOfferEnvelope.create(manifest, now, ttlMs = ttlMs)
            return NativeGalleryResumeAttempt(source, offer, original, now, elapsed).also { it.current(now) }
        }
    }
}
