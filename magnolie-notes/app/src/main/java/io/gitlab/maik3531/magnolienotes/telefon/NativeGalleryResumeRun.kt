package io.gitlab.maik3531.magnolienotes.telefon

import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Whole native resume ownership, distinct from the actual preparation I/O slot.
 * Not serializable and not a Byte/Saved/baseline/quota grant. */
internal class NativeGalleryResumeRun internal constructor(internal val selection: NativeGalleryAlbumSelection,
    internal val originalJob: PhotoSourceJob, internal val preparation: NativeGallerySourceRun) {
    val id: String = UUID.randomUUID().toString()
    private val stopped = AtomicBoolean(false)
    internal val attempt = AtomicReference<NativeGalleryResumeAttempt?>()
    internal val acceptance = AtomicReference<NativeResumeAcceptanceProjection?>()
    val cancelRequested: Boolean get() = stopped.get() || preparation.cancelRequested
    internal fun cancel() { stopped.set(true); attempt.get()?.cancel(); preparation.cancel() }
    internal fun source(): NativeGalleryRenewedSource {
        if (cancelRequested) DeviceFileControl.fail("gallery_resume_run_not_current")
        val value = preparation.renewedSource() ?: DeviceFileControl.fail("gallery_resume_source_unavailable")
        if (value.job != originalJob) DeviceFileControl.fail("gallery_resume_original_changed")
        return value
    }
}
