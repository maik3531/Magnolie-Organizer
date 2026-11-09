package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Native handle only; a completed inspection is never a transfer receipt. */
internal class NativeGalleryPublishedReadRun internal constructor(private val workerOwner: Any) {
    internal val cancellation = CancellationSignal()
    private val canceled = AtomicBoolean(false)
    private val ended = AtomicBoolean(false)
    private val owner = AtomicReference<NativeGalleryPublishedInspection?>()
    private val readback = AtomicReference<NativeGalleryPublishedReadback?>()
    private val result = AtomicReference<NativeIncomingMediaObservation?>()
    private val output = AtomicReference<JsonObject?>()
    private val archive = AtomicReference<NativeGalleryArchiveEntry?>()
    private val failure = AtomicReference<Throwable?>()
    private val drained = CountDownLatch(1)
    private val completionGate = Any()
    private var completionRegistered = false
    private var completion: (() -> Unit)? = null
    val ioEnded: Boolean get() = ended.get()
    val cancelRequested: Boolean get() = canceled.get()
    fun cancel() {
        canceled.set(true)
        try { readback.get()?.close(); owner.get()?.close() } finally { cancellation.cancel() }
    }
    internal fun install(value: NativeGalleryPublishedInspection, recovery: NativeGalleryPublishedReadback? = null) {
        if (!owner.compareAndSet(null, value)) DeviceFileControl.fail("gallery_published_worker_foreign_owner")
        if (recovery != null && (recovery.owner !== value || !readback.compareAndSet(null, recovery)))
            DeviceFileControl.fail("gallery_published_worker_foreign_owner")
        if (canceled.get()) { recovery?.close(); value.close() }
        cancellation.throwIfCanceled()
    }
    internal fun retireIfChanged() {
        try { readback.get()?.requireCurrent() ?: owner.get()?.requireCurrent() } catch (_: Exception) { cancel() }
    }
    internal fun belongsTo(value: Any) = value === workerOwner
    internal fun finish(value: NativeIncomingMediaObservation?, error: Throwable?, message: JsonObject? = null,
        archived: NativeGalleryArchiveEntry? = null) {
        result.set(value); output.set(message); archive.set(archived); failure.set(error)
    }
    internal fun markIoEnded() { ended.set(true) }
    internal fun ioDrained() {
        val notify = synchronized(completionGate) {
            drained.countDown()
            completion.also { completion = null }
        }
        notify?.invoke()
    }
    /** A single native UI waiter, no polling thread or early END signal. */
    internal fun notifyWhenIoDrained(completed: () -> Unit) {
        val now = synchronized(completionGate) {
            if (completionRegistered) DeviceFileControl.fail("gallery_published_worker_foreign_owner")
            completionRegistered = true
            if (drained.count == 0L) true else { completion = completed; false }
        }
        if (now) completed()
    }
    internal fun awaitIoEnded(timeoutMillis: Long) = drained.await(timeoutMillis, TimeUnit.MILLISECONDS)
    internal fun observation(): NativeIncomingMediaObservation? {
        if (!ended.get()) DeviceFileControl.fail("gallery_published_worker_io_pending")
        return result.get().takeIf { !canceled.get() && failure.get() == null }
    }
    internal fun nativeFailure(): Throwable? {
        if (!ended.get()) DeviceFileControl.fail("gallery_published_worker_io_pending")
        return failure.get()
    }
    internal fun actualReadbackOutput(): JsonObject? {
        if (!ended.get()) DeviceFileControl.fail("gallery_published_worker_io_pending")
        return output.get().takeIf { !canceled.get() && failure.get() == null }
    }
    internal fun actualArchiveOutput(): NativeGalleryArchiveEntry? {
        if (!ended.get()) DeviceFileControl.fail("gallery_published_worker_io_pending")
        return archive.get().takeIf { !canceled.get() && failure.get() == null }
    }
}

/** One bounded native inspection thread. Provider lane acquisition and actual
 * descriptor drain belong to rows.inspectPublished; cancellation cannot free it.
 * The runtime retains index ownership until this worker becomes quiescent. */
internal class NativeGalleryPublishedReadWorker(private val rows: NativeGalleryIncomingRows,
    private val onEnded: () -> Unit) : AutoCloseable {
    private val gate = Any()
    private var active: NativeGalleryPublishedReadRun? = null
    private var closed = false
    val current: NativeGalleryPublishedReadRun? get() = synchronized(gate) { active }
    val isQuiescent: Boolean get() = synchronized(gate) { active == null }
    internal fun owns(run: NativeGalleryPublishedReadRun) = run.belongsTo(this)
    internal fun start(prepare: () -> NativeGalleryPublishedInspection): NativeGalleryPublishedReadRun =
        startNative { _ -> prepare() to null }
    internal fun startReadback(prepare: () -> NativeGalleryPublishedReadback): NativeGalleryPublishedReadRun =
        startNative { _ -> prepare().let { it.owner to it } }
    private class ArchiveCopy(val protection: DeviceTransferProtection, val book: NativeGalleryTrashBookPermit)
    internal fun startArchive(protection: DeviceTransferProtection, book: NativeGalleryTrashBookPermit,
        prepare: (CancellationSignal) -> NativeGalleryPublishedInspection): NativeGalleryPublishedReadRun =
        startNative(ArchiveCopy(protection, book)) { cancellation -> prepare(cancellation) to null }

    private fun startNative(archive: ArchiveCopy? = null,
        prepare: (CancellationSignal) -> Pair<NativeGalleryPublishedInspection, NativeGalleryPublishedReadback?>): NativeGalleryPublishedReadRun {
        val run = synchronized(gate) {
            if (closed) DeviceFileControl.fail("gallery_published_worker_closed")
            if (active != null) DeviceFileControl.fail("gallery_published_worker_busy")
            NativeGalleryPublishedReadRun(this).also { active = it }
        }
        fun finish(value: NativeIncomingMediaObservation?, error: Throwable?, message: JsonObject? = null, archived: NativeGalleryArchiveEntry? = null) {
            run.finish(value, error, message, archived)
            synchronized(gate) { if (active === run) active = null }
            run.markIoEnded()
            try { onEnded() } finally { run.ioDrained() }
        }
        val thread = Thread({
            var owner: NativeGalleryPublishedInspection? = null
            var recovery: NativeGalleryPublishedReadback? = null
            var observation: NativeIncomingMediaObservation? = null
            var message: JsonObject? = null
            var archived: NativeGalleryArchiveEntry? = null
            var failure: Throwable? = null
            try {
                run.cancellation.throwIfCanceled()
                val prepared = prepare(run.cancellation); owner = prepared.first; recovery = prepared.second; run.install(owner, recovery)
                if (archive != null) archived = rows.archivePublishedPcToApplication(owner, archive.protection, archive.book, run.cancellation)
                else if (recovery == null) observation = rows.inspectPublished(owner, run.cancellation)
                else message = recovery.perform(rows, run.cancellation)
            } catch (error: Throwable) { failure = error }
            finally { recovery?.close(); owner?.close(); finish(observation, failure, message, archived) }
        }, "magnolie-media-published-read").apply { isDaemon = true }
        try { thread.start() } catch (error: Throwable) { finish(null, error); throw error }
        return run
    }
    override fun close() {
        val running = synchronized(gate) { closed = true; active }
        running?.cancel()
    }
}
