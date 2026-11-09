package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Handler
import android.os.Looper
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.atomic.AtomicBoolean

/** Native transport ownership, retained until actual UI cleanup. No worker-END
 * or quota receipt is implied by closing the control plane.
 */
internal class NativeGalleryFileConnection internal constructor(internal val channel: TelefonSecureChannel,
    private val requireIncomingAgreement: () -> Unit = {},
    private val released: (NativeGalleryFileConnection) -> Unit) : AutoCloseable {
    private val ended = AtomicBoolean(false)
    private val permissionQueued = AtomicBoolean(false)
    private val cleanupReported = AtomicBoolean(false)
    private val permissionIoEnd = java.util.concurrent.atomic.AtomicReference(java.util.concurrent.CountDownLatch(0))
    @Volatile private var bound: NativeGalleryFileRuntime? = null
    val runtime: NativeGalleryFileRuntime get() = bound?.takeUnless { ended.get() }
        ?: DeviceFileControl.fail("gallery_file_connection_ended")
    internal val isEnded get() = ended.get()

    internal fun bind(value: NativeGalleryFileRuntime) {
        check(Looper.myLooper() == Looper.getMainLooper())
        check(bound == null)
        bound = value
        if (ended.get()) { close(); DeviceFileControl.fail("gallery_file_connection_ended") }
    }

    /** Only the existing authenticated native connection can receive these
     * reserved frames. This never constructs a runtime, intent or consent from
     * a packet. Chunk delivery must not queue behind the worker waiting for it. */
    internal fun receiveIncomingMedia(authenticatedChannel: TelefonSecureChannel, message: JsonObject,
        book: () -> NativeGalleryReceiveBookPermit): NativeGalleryIncomingRun? {
        if (authenticatedChannel !== channel || ended.get()) DeviceFileControl.fail("gallery_incoming_foreign_connection")
        return when (message.string("kind")) {
            MediaOfferEnvelope.KIND -> runtime.beginIncomingMediaOffer(message, book(), automaticReadback = true,
                requireReadbackAgreement = requireIncomingAgreement)
            DeviceFileChunkEnvelope.RESULT -> {
                if (!runtime.observeIncomingChunk(authenticatedChannel, message)) DeviceFileControl.fail("gallery_incoming_unsolicited_chunk")
                null
            }
            else -> DeviceFileControl.fail("gallery_incoming_unexpected_message")
        }
    }

    /** Explicit native selection only; the frame dispatcher above cannot create
     * these actual saved-book permits or authorize a local archive action. */
    internal fun archivePublishedPc(kind: GalleryMediaType, id: String, fingerprint: String,
        book: NativeGalleryReceiveBookPermit, archiveBook: NativeGalleryTrashBookPermit): NativeGalleryPublishedReadRun {
        if (Looper.myLooper() == Looper.getMainLooper()) DeviceFileControl.fail("gallery_incoming_worker_io_required")
        val selected = runtime
        requireIncomingAgreement()
        if (ended.get() || bound !== selected) DeviceFileControl.fail("gallery_file_connection_ended")
        return selected.beginPublishedPcArchive(kind, id, fingerprint, book, archiveBook)
    }

    /** Called after native I/O actually ends, outside the TelefonWerk monitor. */
    internal fun transportEnded() {
        ended.set(true)
        bound?.revokeControl()
        if (Looper.myLooper() == Looper.getMainLooper()) close()
        else Handler(Looper.getMainLooper()).post { close() }
    }

    internal fun enqueuePermissionCommand(operation: (NativeGalleryFileRuntime) -> Unit) {
        enqueuePermissionCommand(operation, null)
    }

    internal fun enqueuePermissionCommand(prepare: (NativeGalleryFileRuntime) -> Unit,
        background: ((NativeGalleryFileRuntime) -> Unit)?) {
        if (ended.get() || !permissionQueued.compareAndSet(false, true)) DeviceFileControl.fail("gallery_permission_command_busy")
        val completed = java.util.concurrent.CountDownLatch(1)
        permissionIoEnd.set(completed)
        fun finish(failed: Boolean) {
            if (failed) { ended.set(true); bound?.revokeControl() }
            permissionQueued.set(false)
            try {
                if (ended.get()) Handler(Looper.getMainLooper()).post { close() }
            } finally { completed.countDown() }
        }
        val posted = Handler(Looper.getMainLooper()).post {
            try {
                prepare(runtime)
                if (background == null) finish(false)
                else Thread({
                    var failed = false
                    try { background(runtime) } catch (_: Exception) { failed = true }
                    finally { finish(failed) }
                }, "magnolie-permission-response").apply { isDaemon = true }.start()
            } catch (_: Exception) { finish(true) }
        }
        if (!posted) { permissionQueued.set(false); completed.countDown(); DeviceFileControl.fail("gallery_permission_foreground_required") }
    }

    override fun close() {
        ended.set(true)
        bound?.revokeControl()
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        if (permissionQueued.get()) return // Includes actual background response/control I/O.
        if (bound?.closeWhenQuiescent { close() } == false) return
        bound = null
        if (cleanupReported.compareAndSet(false, true)) released(this)
    }
}
