package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** In-process source preparation only. Snapshot-ready is not sent, accepted,
 * published, retired or a synchronization receipt. Construction starts nothing.
 */
internal class NativeGallerySourceRun internal constructor() {
    val id: String = UUID.randomUUID().toString()
    internal val cancellation = CancellationSignal()
    private val ended = AtomicBoolean(false)
    private val state = AtomicReference("preparing")
    private val job = AtomicReference<PhotoSourceJob?>()
    private val renewed = AtomicReference<NativeGalleryRenewedSource?>()
    private val failure = AtomicReference<Throwable?>()
    val ioEnded: Boolean get() = ended.get()
    val phase: String get() = state.get()
    val cancelRequested: Boolean get() = cancellation.isCanceled

    fun cancel() { cancellation.cancel() } // Never releases an I/O ownership slot.
    internal fun finish(prepared: PhotoSourceJob?, error: Throwable?, reopened: NativeGalleryRenewedSource? = null) {
        job.set(prepared); renewed.set(reopened); failure.set(error)
        state.set(if (cancellation.isCanceled) "canceled_held" else if (error != null) "failed_held" else "snapshot_ready")
        ended.set(true)
    }
    internal fun snapshotJob(): PhotoSourceJob? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return job.get().takeIf { phase == "snapshot_ready" && !cancellation.isCanceled }
    }
    internal fun nativeFailure(): Throwable? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return failure.get() // Native handle only, never serialized to a peer.
    }
    internal fun completedNativeJob(): PhotoSourceJob? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return job.get() // Exact completed native owner; never a remote ID lookup.
    }
    internal fun renewedSource(): NativeGalleryRenewedSource? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return renewed.get().takeIf { phase == "snapshot_ready" && !cancellation.isCanceled }
    }
}

/** Explicit bounded single-worker owner. A stop/close request only cancels; a
 * blocked provider remains owned until prepare returns with all its I/O closed.
 * The native owner must not close its source index before isQuiescent becomes
 * true. No retries, timers, scans or automatic cleanup are started here.
 */
internal class NativeGallerySourceWorker(private val prepare: (NativeGalleryAlbumSelection, CancellationSignal) -> PhotoSourceJob,
    private val onEnded: (NativeGallerySourceRun) -> Unit = {}) : AutoCloseable {
    private val gate = Any()
    private var active: NativeGallerySourceRun? = null
    private var closed = false
    val current: NativeGallerySourceRun? get() = synchronized(gate) { active }
    val isQuiescent: Boolean get() = synchronized(gate) { active == null }

    fun start(selection: NativeGalleryAlbumSelection): NativeGallerySourceRun = startOwned(selection) { selected, cancellation ->
        prepare(selected, cancellation) to null
    }

    fun startRenewed(selection: NativeGalleryAlbumSelection,
        renew: (NativeGalleryAlbumSelection, CancellationSignal) -> NativeGalleryRenewedSource): NativeGallerySourceRun =
        startOwned(selection) { selected, cancellation -> renew(selected, cancellation).let { it.job to it } }

    private fun startOwned(selection: NativeGalleryAlbumSelection,
        action: (NativeGalleryAlbumSelection, CancellationSignal) -> Pair<PhotoSourceJob, NativeGalleryRenewedSource?>): NativeGallerySourceRun {
        val run = synchronized(gate) {
            if (closed) DeviceFileControl.fail("gallery_source_worker_closed")
            if (active != null) DeviceFileControl.fail("gallery_source_worker_busy")
            NativeGallerySourceRun().also { active = it }
        }
        val thread = Thread({
            var prepared: Pair<PhotoSourceJob, NativeGalleryRenewedSource?>? = null
            var error: Throwable? = null
            try {
                run.cancellation.throwIfCanceled()
                prepared = action(selection, run.cancellation)
            } catch (failed: Throwable) { error = failed }
            finally { finish(run, prepared?.first, error, prepared?.second) }
        }, "magnolie-photo-source").apply { isDaemon = true }
        try { thread.start() }
        catch (error: Throwable) { finish(run, null, error); throw error }
        return run
    }

    private fun finish(run: NativeGallerySourceRun, job: PhotoSourceJob?, error: Throwable?, renewed: NativeGalleryRenewedSource? = null) {
        // prepare owns all descriptor cleanup before return. Only that actual
        // end, never cancel/close/progress totals, can release this slot.
        run.finish(job, error, renewed)
        synchronized(gate) { if (active === run) active = null }
        onEnded(run) // Outside the owner monitor; callbacks are not source I/O.
    }

    fun cancel(run: NativeGallerySourceRun) {
        synchronized(gate) {
            if (active !== run) DeviceFileControl.fail("gallery_source_worker_foreign_run")
        }
        run.cancel() // Cancellation can call native code; never hold our owner monitor.
    }

    override fun close() {
        val running = synchronized(gate) { closed = true; active }
        running?.cancel()
    }
}
