package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import java.util.concurrent.atomic.AtomicBoolean

/** Original native archive admission, never a packet, OS mutation grant or a
 * replacement source lease. Its clock starts before the worker is scheduled. */
internal class NativeGalleryPcArchiveAction private constructor(private val session: NativeFileControlSession,
    internal val kind: GalleryMediaType, private val book: NativeGalleryReceiveBookPermit,
    private val archiveBook: NativeGalleryTrashBookPermit, private val incomingIntent: () -> Any?,
    private val ready: () -> Boolean) : AutoCloseable {
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private val closed = AtomicBoolean(false)
    private val token = incomingIntent() as? MediaSyncTransport.IntentToken ?: fail()
    private val original = session.operationBinding("0".repeat(64)) ?: fail()
    private var cancellation: CancellationSignal? = null

    init { requireCurrent() }
    /** Local IO guard only; no control-session or protected-index callback. */
    @Synchronized internal fun requireLocal() {
        try {
            cancellation?.throwIfCanceled()
            val now = DeviceFileControl.monotonicMs()
            if (closed.get() || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS || !ready() ||
                incomingIntent() !== token || !token.requestedIncoming(kind)) fail()
            book.requireArchiveBook(archiveBook); archiveBook.requireTrashEnabled(); last = now
        } catch (error: Exception) { closed.set(true); throw error }
    }
    @Synchronized internal fun requireCurrent() {
        try {
            requireLocal()
            if (session.operationBinding("0".repeat(64)) != original) fail()
        } catch (error: Exception) { closed.set(true); throw error }
    }
    @Synchronized internal fun bindCancellation(actual: CancellationSignal) {
        if (cancellation != null) { close(); fail() }
        cancellation = actual; requireCurrent()
    }
    internal fun currentIntent(): Any? { requireCurrent(); return token }
    @Synchronized internal fun remainingMs(): Long {
        requireCurrent()
        return maxOf(0L, DeviceFileControl.MAX_TTL_MS - (DeviceFileControl.monotonicMs() - issued))
    }
    internal fun expectedControl(destination: String): NativeFileOperationBinding {
        requireCurrent()
        val actual = session.operationBinding(destination) ?: fail()
        if (actual.session != original.session || actual.binding.snapshot().filterKeys { it != "destination_token" } !=
            original.binding.snapshot().filterKeys { it != "destination_token" }) { close(); fail() }
        requireCurrent(); return actual
    }
    override fun close() { closed.set(true) }

    companion object {
        internal fun capture(session: NativeFileControlSession, kind: GalleryMediaType, book: NativeGalleryReceiveBookPermit,
            archiveBook: NativeGalleryTrashBookPermit, incomingIntent: () -> Any?, ready: () -> Boolean): NativeGalleryPcArchiveAction =
            NativeGalleryPcArchiveAction(session, kind, book, archiveBook, incomingIntent, ready)
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_archive_original_action_required")
    }
}
