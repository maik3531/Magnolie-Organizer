package io.gitlab.maik3531.magnolienotes.telefon

import java.util.concurrent.atomic.AtomicBoolean

/** Display metadata only. No URI, provider handle, preview or mutation grant. */
internal data class NativeGalleryPcArchiveChoice(val id: String, val fingerprint: String, val name: String, val bytes: Long)

/** A bounded original admission spanning list, native confirmation and worker.
 * Confirmation never restarts the action clock or captures replacement rights. */
internal class NativeGalleryPcArchiveSelection internal constructor(private val runtime: NativeGalleryFileRuntime,
    internal val action: NativeGalleryPcArchiveAction, internal val book: NativeGalleryReceiveBookPermit,
    internal val archiveBook: NativeGalleryTrashBookPermit, choices: List<NativeGalleryPcArchiveChoice>) : AutoCloseable {
    val choices: List<NativeGalleryPcArchiveChoice> = java.util.Collections.unmodifiableList(ArrayList(choices))
    private val consumed = AtomicBoolean(false)
    internal fun requireCurrent() = action.requireCurrent()
    internal fun confirm(index: Int): NativeGalleryPublishedReadRun {
        requireCurrent()
        val selected = choices.getOrNull(index) ?: DeviceFileControl.fail("gallery_archive_original_selection_required")
        if (!consumed.compareAndSet(false, true)) DeviceFileControl.fail("gallery_archive_original_selection_required")
        return try { runtime.beginSelectedPcArchive(this, selected) }
        catch (error: Throwable) { close(); throw error }
    }
    internal fun requireRuntime(actual: NativeGalleryFileRuntime, selected: NativeGalleryPcArchiveChoice) {
        requireCurrent()
        if (actual !== runtime || !consumed.get() || selected !in choices) DeviceFileControl.fail("gallery_archive_original_selection_required")
    }
    override fun close() { action.close() }
}
