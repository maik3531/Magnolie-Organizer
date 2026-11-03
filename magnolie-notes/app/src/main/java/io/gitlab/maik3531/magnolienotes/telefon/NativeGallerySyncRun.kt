package io.gitlab.maik3531.magnolienotes.telefon

import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlinx.serialization.json.JsonObject

internal data class NativeGalleryOfferOutput(val messageId: String, val transferId: String, val manifestSha256: String, val expires: Long)
internal class NativeGalleryWireOfferAttempt(val requestId: String, val commandSha256: String, val message: JsonObject,
    initialWall: Long, issuedElapsed: Long = DeviceFileControl.monotonicMs()) {
    private var lastWall = initialWall
    private var lastElapsed = issuedElapsed
    private val expiresElapsed: Long
    private var invalidated = false
    init {
        if (issuedElapsed < 0 || issuedElapsed > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS)
            DeviceFileControl.fail("gallery_sync_offer_attempt_not_current")
        val expiresWall = message.long("expires_ms")
        if (initialWall < 0 || expiresWall <= initialWall) DeviceFileControl.fail("gallery_sync_offer_attempt_not_current")
        expiresElapsed = issuedElapsed + minOf(DeviceFileControl.MAX_TTL_MS, expiresWall - initialWall)
    }
    /** The run monitor serializes this bounded attempt. Even fresh configuration
     * tickets cannot revive an expired offer after an observed clock rollback. */
    fun checkCurrent(wall: Long, elapsed: Long = DeviceFileControl.monotonicMs()) {
        if (invalidated || wall < lastWall || elapsed < lastElapsed || elapsed >= expiresElapsed || wall >= message.long("expires_ms")) {
            invalidated = true
            DeviceFileControl.fail("gallery_sync_offer_attempt_not_current")
        }
        lastWall = wall; lastElapsed = elapsed
    }
}

/** Whole native run ownership, distinct from its source-preparation I/O slot.
 * Snapshot readiness or offer output cannot produce a synchronization success.
 * No remotely supplied run object, receipt, path or cleanup claim is accepted.
 */
internal class NativeGallerySyncRun internal constructor(internal val selection: NativeGalleryAlbumSelection,
    internal val preparation: NativeGallerySourceRun) {
    val id: String = UUID.randomUUID().toString()
    internal val stopped = AtomicBoolean(false)
    internal val offered = AtomicReference<String?>()
    internal val offerOutput = AtomicReference<NativeGalleryOfferOutput?>()
    internal val wireOfferAttempt = AtomicReference<NativeGalleryWireOfferAttempt?>()
    internal val mediaAttempts = NativeGalleryMediaAttempts()
    internal val acceptance = AtomicReference<DeviceFileRemoteAcceptance?>()
    internal val remoteSaved = AtomicReference<RemoteSavedConfirmation?>()
    val cancelRequested: Boolean get() = stopped.get()
    val offeredManifestSha256: String? get() = offered.get()
}
