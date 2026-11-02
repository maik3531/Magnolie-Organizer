package io.gitlab.maik3531.magnolienotes.telefon

import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal data class NativeGalleryOfferOutput(val messageId: String, val transferId: String, val manifestSha256: String, val expires: Long)

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
    internal val acceptance = AtomicReference<DeviceFileRemoteAcceptance?>()
    val cancelRequested: Boolean get() = stopped.get()
    val offeredManifestSha256: String? get() = offered.get()
}
