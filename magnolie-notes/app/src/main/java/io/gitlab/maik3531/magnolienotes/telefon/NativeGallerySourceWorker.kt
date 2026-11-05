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
    private val archived = AtomicReference<NativeGalleryArchiveEntry?>()
    private val writeRequest = AtomicReference<NativeGalleryWriteRequest?>()
    private val writeTarget = AtomicReference<NativeGalleryPhotoWorkflow.VerifiedWriteTarget?>()
    private val trashAction = AtomicReference<NativeGalleryTrashAction?>()
    private val failure = AtomicReference<Throwable?>()
    val ioEnded: Boolean get() = ended.get()
    val phase: String get() = state.get()
    val cancelRequested: Boolean get() = cancellation.isCanceled

    fun cancel() { cancellation.cancel() } // Never releases an I/O ownership slot.
    internal fun finish(prepared: PhotoSourceJob?, error: Throwable?, reopened: NativeGalleryRenewedSource? = null, recovery: NativeGalleryArchiveEntry? = null,
        write: NativeGalleryWriteRequest? = null, target: NativeGalleryPhotoWorkflow.VerifiedWriteTarget? = null,
        trash: NativeGalleryTrashAction? = null) {
        job.set(prepared); renewed.set(reopened); archived.set(recovery); writeRequest.set(write); failure.set(error)
        writeTarget.set(target)
        trashAction.set(trash)
        state.set(if (cancellation.isCanceled) "canceled_held" else if (error != null) "failed_held"
            else if (trash != null) if (trash.state == "restored") "local_restore_verified" else "local_trash_verified"
            else if (target != null) "write_target_verified"
            else if (write != null) "write_request_ready"
            else if (recovery != null) "archive_ready"
            else if (prepared == null) "empty_ready" else "snapshot_ready")
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
    internal fun completedNativeArchive(): NativeGalleryArchiveEntry? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return archived.get().takeIf { phase == "archive_ready" && !cancellation.isCanceled }
    }
    internal fun completedNativeWriteRequest(): NativeGalleryWriteRequest? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return writeRequest.get().takeIf { phase == "write_request_ready" && !cancellation.isCanceled }
    }
    internal fun completedNativeWriteTarget(): NativeGalleryPhotoWorkflow.VerifiedWriteTarget? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return writeTarget.get().takeIf { phase == "write_target_verified" && !cancellation.isCanceled }
    }
    internal fun completedNativeTrashAction(): NativeGalleryTrashAction? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return trashAction.get().takeIf { phase == "local_trash_verified" && !cancellation.isCanceled }
    }
    internal fun completedNativeRestoreAction(): NativeGalleryTrashAction? {
        if (!ended.get()) DeviceFileControl.fail("gallery_source_worker_io_pending")
        return trashAction.get().takeIf { phase == "local_restore_verified" && !cancellation.isCanceled }
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

    fun startSelected(selection: NativeGalleryAlbumSelection,
        copy: (CancellationSignal) -> PhotoSourceJob): NativeGallerySourceRun =
        startOwned(selection) { _, cancellation -> copy(cancellation) to null }

    fun startBatch(selection: NativeGalleryAlbumSelection,
        prepareBatch: (CancellationSignal) -> PhotoSourceJob?): NativeGallerySourceRun =
        startOwned(selection) { _, cancellation -> prepareBatch(cancellation) to null }

    fun startArchive(selection: NativeGalleryAlbumSelection,
        archive: (CancellationSignal) -> NativeGalleryArchiveEntry): NativeGallerySourceRun {
        val result = AtomicReference<NativeGalleryArchiveEntry?>()
        return startOwned(selection, result) { _, cancellation ->
            result.set(archive(cancellation)); null to null
        }
    }

    fun startWriteRequest(prepare: (CancellationSignal) -> NativeGalleryWriteRequest): NativeGallerySourceRun {
        val result = AtomicReference<NativeGalleryWriteRequest?>()
        return startNative(write = result) { cancellation -> result.set(prepare(cancellation)); null to null }
    }

    fun startWriteTarget(prepare: (CancellationSignal) -> NativeGalleryPhotoWorkflow.VerifiedWriteTarget): NativeGallerySourceRun {
        val result = AtomicReference<NativeGalleryPhotoWorkflow.VerifiedWriteTarget?>()
        return startNative(target = result) { cancellation -> result.set(prepare(cancellation)); null to null }
    }

    fun startTrash(action: (CancellationSignal) -> NativeGalleryTrashAction): NativeGallerySourceRun {
        val result = AtomicReference<NativeGalleryTrashAction?>()
        return startNative(trash = result) { cancellation -> result.set(action(cancellation)); null to null }
    }

    private fun startOwned(selection: NativeGalleryAlbumSelection,
        archived: AtomicReference<NativeGalleryArchiveEntry?>? = null,
        action: (NativeGalleryAlbumSelection, CancellationSignal) -> Pair<PhotoSourceJob?, NativeGalleryRenewedSource?>): NativeGallerySourceRun =
        startNative(archived) { cancellation -> action(selection, cancellation) }

    private fun startNative(archived: AtomicReference<NativeGalleryArchiveEntry?>? = null,
        write: AtomicReference<NativeGalleryWriteRequest?>? = null,
        target: AtomicReference<NativeGalleryPhotoWorkflow.VerifiedWriteTarget?>? = null,
        trash: AtomicReference<NativeGalleryTrashAction?>? = null,
        action: (CancellationSignal) -> Pair<PhotoSourceJob?, NativeGalleryRenewedSource?>): NativeGallerySourceRun {
        val run = synchronized(gate) {
            if (closed) DeviceFileControl.fail("gallery_source_worker_closed")
            if (active != null) DeviceFileControl.fail("gallery_source_worker_busy")
            NativeGallerySourceRun().also { active = it }
        }
        val thread = Thread({
            var prepared: Pair<PhotoSourceJob?, NativeGalleryRenewedSource?>? = null
            var error: Throwable? = null
            try {
                run.cancellation.throwIfCanceled()
                prepared = action(run.cancellation)
            } catch (failed: Throwable) { error = failed }
            finally { finish(run, prepared?.first, error, prepared?.second, archived?.get(), write?.get(), target?.get(), trash?.get()) }
        }, "magnolie-photo-source").apply { isDaemon = true }
        try { thread.start() }
        catch (error: Throwable) { finish(run, null, error); throw error }
        return run
    }

    private fun finish(run: NativeGallerySourceRun, job: PhotoSourceJob?, error: Throwable?, renewed: NativeGalleryRenewedSource? = null,
        recovery: NativeGalleryArchiveEntry? = null, write: NativeGalleryWriteRequest? = null,
        target: NativeGalleryPhotoWorkflow.VerifiedWriteTarget? = null, trash: NativeGalleryTrashAction? = null) {
        // prepare owns all descriptor cleanup before return. Only that actual
        // end, never cancel/close/progress totals, can release this slot.
        run.finish(job, error, renewed, recovery, write, target, trash)
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
