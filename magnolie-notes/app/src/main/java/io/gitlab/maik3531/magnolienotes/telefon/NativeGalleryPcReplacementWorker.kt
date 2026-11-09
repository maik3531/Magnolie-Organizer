package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Original grant/run ownership, never reconstructed from a stored plan. */
internal class NativeGalleryPcReplacementRun internal constructor(private val worker: Any,
    internal val grant: NativeGalleryPcWriteGrant) {
    private val canceled = AtomicBoolean(false)
    private val ended = AtomicBoolean(false)
    private val transfer = AtomicReference<NativeGalleryPcReplacementTransfer?>()
    private val failure = AtomicReference<Throwable?>()
    private val saved = AtomicReference<JsonObject?>()
    private val publication = AtomicReference<GalleryIncomingPublication?>()
    private val drained = CountDownLatch(1)
    private val completionGate = Any()
    private var completion: (() -> Unit)? = null
    private var registered = false
    val ioEnded: Boolean get() = ended.get()
    fun cancel() { canceled.set(true); grant.request.close(); transfer.get()?.close() }
    internal fun install(value: NativeGalleryPcReplacementTransfer) {
        if (!value.belongsTo(this, grant) || !transfer.compareAndSet(null, value)) DeviceFileControl.fail("gallery_pc_worker_foreign_transfer")
        if (canceled.get()) value.close()
        if (canceled.get()) DeviceFileControl.fail("gallery_pc_worker_canceled")
    }
    internal fun belongsTo(owner: Any) = worker === owner
    internal fun observe(channel: TelefonSecureChannel, message: JsonObject): Boolean = transfer.get()?.observeChunk(channel, message) ?: false
    internal fun retireIfChanged() {
        try { grant.requireCurrent(); transfer.get()?.requireControlCurrent() } catch (_: Exception) { cancel() }
    }
    internal fun finish(output: JsonObject?, error: Throwable?, published: GalleryIncomingPublication?) {
        saved.set(output); failure.set(error); publication.set(published); ended.set(true)
    }
    internal fun publishDrain() {
        val notify = synchronized(completionGate) { drained.countDown(); completion.also { completion = null } }
        notify?.invoke()
    }
    internal fun notifyWhenIoDrained(notify: () -> Unit) {
        val now = synchronized(completionGate) {
            if (registered) DeviceFileControl.fail("gallery_pc_worker_foreign_waiter")
            registered = true
            if (drained.count == 0L) true else { completion = notify; false }
        }
        if (now) notify()
    }
    internal fun awaitIoEnded(timeout: Long): Boolean = drained.await(timeout, TimeUnit.MILLISECONDS)
    internal fun nativeFailure(): Throwable? {
        if (!ended.get()) DeviceFileControl.fail("gallery_pc_worker_io_pending")
        return failure.get()
    }
    internal fun actualSavedOutput(): JsonObject? {
        if (!ended.get()) DeviceFileControl.fail("gallery_pc_worker_io_pending")
        return saved.get().takeIf { !canceled.get() && failure.get() == null }
    }
    internal fun actualPublishedOutput(): GalleryIncomingPublication? = publication.get().takeIf { actualSavedOutput() != null }
}

/** Owns the exact process lane from before proposal/staging through observer,
 * encrypted output and archive-store close. Construction starts no work. */
internal class NativeGalleryPcReplacementWorker(private val context: Context, private val index: PhotoSourceJobIndex,
    private val rows: NativeGalleryIncomingRows, private val protection: DeviceTransferProtection,
    private val channel: TelefonSecureChannel, private val onEnded: (NativeGalleryPcReplacementRun) -> Unit) : AutoCloseable {
    private val gate = Any()
    private var active: NativeGalleryPcReplacementRun? = null
    private var closed = false
    val current: NativeGalleryPcReplacementRun? get() = synchronized(gate) { active }
    val isQuiescent: Boolean get() = synchronized(gate) { active == null }
    internal fun owns(run: NativeGalleryPcReplacementRun) = run.belongsTo(this)
    internal fun start(offer: JsonObject, grant: NativeGalleryPcWriteGrant): NativeGalleryPcReplacementRun {
        grant.requireUnused(); grant.request.admission.requireIndex(index)
        val run = synchronized(gate) {
            if (closed || active != null) DeviceFileControl.fail("gallery_pc_worker_busy")
            NativeGalleryPcReplacementRun(this, grant).also {
                if (!NativeGalleryMediaIoLane.acquire(it)) DeviceFileControl.fail("gallery_incoming_worker_busy")
                active = it
            }
        }
        fun finish(output: JsonObject?, error: Throwable?, published: GalleryIncomingPublication?) {
            NativeGalleryMediaIoLane.release(run)
            run.finish(output, error, published)
            synchronized(gate) { if (active === run) active = null }
            try { onEnded(run) } finally { run.publishDrain() }
        }
        val thread = Thread({
            var transfer: NativeGalleryPcReplacementTransfer? = null
            var archive: NativeGalleryTrashArchive? = null
            var output: JsonObject? = null; var error: Throwable? = null
            try {
                grant.requireUnused()
                archive = NativeGalleryTrashArchive.openExistingForApplication(context, protection)
                val origin = archive.verifiedOrigin(grant.request.entry, grant.request.admission.archiveBook)
                if (origin["publication"] != grant.request.admission.publication.body) DeviceFileControl.fail("gallery_pc_write_original_admission_required")
                val preview = grant.request.admission.proposeSuccessor(grant, channel, offer)
                index.requirePcStageCapacity(preview); index.requirePcHistoryCapacity(preview.predecessor)
                val plan = index.proposePcReplacement(grant, channel, offer)
                transfer = NativeGalleryPcReplacementTransfer.prepareOwned(context, index, plan, grant, channel, run)
                run.install(transfer)
                transfer.sendAcceptance(); transfer.receiveAndStage()
                transfer.prepareBeforeWrite(rows, archive); transfer.prepareWriteTarget(rows, archive); transfer.markWriteStarted()
                val written = transfer.copyReplacementBytes(archive)
                transfer.inspectWrittenReplacement(rows, written); output = transfer.sendSaved()
            } catch (failed: Throwable) { error = failed }
            finally {
                fun retainFailure(failed: Throwable) { if (error == null) error = failed else error!!.addSuppressed(failed) }
                try { transfer?.close() } catch (failed: Throwable) { retainFailure(failed) }
                var interrupted = false
                transfer?.let {
                    var actualEnd = false
                    while (!actualEnd) {
                        try { actualEnd = it.awaitIoEnded(1000) }
                        catch (failed: InterruptedException) { interrupted = true; retainFailure(failed) }
                    }
                }
                try { archive?.close() } catch (failed: Throwable) { retainFailure(failed) }
                grant.request.close()
                finish(output, error, transfer?.actualPublishedOutput())
                if (interrupted) Thread.currentThread().interrupt()
            }
        }, "magnolie-pc-replacement").apply { isDaemon = true }
        try { thread.start() } catch (failed: Throwable) { grant.request.close(); finish(null, failed, null); throw failed }
        return run
    }
    override fun close() { synchronized(gate) { closed = true; active }?.cancel() }
}
