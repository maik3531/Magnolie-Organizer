package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal class NativeGalleryIncomingRun internal constructor(private val workerOwner: Any,
    private val completedReadback: ((NativeGalleryIncomingRun) -> NativeGalleryPublishedReadRun)? = null,
    internal val automaticReadbackRequested: Boolean = false) {
    internal val cancellation = CancellationSignal()
    private val ended = AtomicBoolean(false)
    private val canceled = AtomicBoolean(false)
    private val state = AtomicReference("preparing")
    private val transfer = AtomicReference<NativeGalleryIncomingTransfer?>()
    private val error = AtomicReference<Throwable?>()
    private val output = AtomicReference<JsonObject?>()
    private val publications = AtomicReference<List<GalleryIncomingPublication>>(emptyList())
    private val readbackStarted = AtomicBoolean(false)
    private val drained = java.util.concurrent.CountDownLatch(1)
    private val automaticStarted = java.util.concurrent.CountDownLatch(1)
    private val automaticReadback = AtomicReference<NativeGalleryPublishedReadRun?>()
    private val automaticError = AtomicReference<Throwable?>()
    val ioEnded: Boolean get() = ended.get()
    val phase: String get() = state.get()
    val cancelRequested: Boolean get() = canceled.get()
    fun cancel() {
        canceled.set(true)
        try { transfer.get()?.close(); automaticReadback.get()?.cancel() } finally { cancellation.cancel() }
    }
    internal fun install(value: NativeGalleryIncomingTransfer) {
        if (!transfer.compareAndSet(null, value)) DeviceFileControl.fail("gallery_incoming_worker_foreign_transfer")
        if (canceled.get()) value.close()
        cancellation.throwIfCanceled(); state.set("receiving")
    }
    internal fun observe(channel: TelefonSecureChannel, message: JsonObject): Boolean = transfer.get()?.observeChunk(channel, message) ?: false
    internal fun retireIfChanged() {
        try { transfer.get()?.requireCurrent() } catch (_: Exception) { cancel() }
    }
    internal fun finish(message: JsonObject?, failure: Throwable?, published: List<GalleryIncomingPublication> = emptyList()) {
        publications.set(if (message != null && failure == null) published.toList() else emptyList())
        output.set(message); error.set(failure)
        state.set(if (canceled.get()) "canceled_held" else if (failure != null) "failed_held" else "saved_output")
    }
    internal fun belongsTo(owner: Any): Boolean = workerOwner === owner
    internal fun markIoEnded() { ended.set(true) }
    internal fun ioDrained() { drained.countDown() }
    /** Explicit bounded native drain, never a frontend wait or completion ACK. */
    internal fun awaitIoEnded(timeoutMillis: Long): Boolean = drained.await(timeoutMillis, java.util.concurrent.TimeUnit.MILLISECONDS)
    internal fun nativeFailure(): Throwable? {
        if (!ended.get()) DeviceFileControl.fail("gallery_incoming_worker_io_pending")
        return error.get()
    }
    internal fun actualSavedOutput(): JsonObject? {
        if (!ended.get()) DeviceFileControl.fail("gallery_incoming_worker_io_pending")
        return output.get().takeIf { phase == "saved_output" && !canceled.get() }
    }
    /** Native continuation only: no caller-supplied offer, publication, book or
     * channel. A Saved JSON object alone cannot construct this continuation. */
    internal fun beginPublishedReadback(): NativeGalleryPublishedReadRun = startReadback(automatic = false)
    private fun startReadback(automatic: Boolean): NativeGalleryPublishedReadRun {
        if (!ended.get() || (!automatic && drained.count != 0L) || automatic && !automaticReadbackRequested ||
            actualSavedOutput() == null || error.get() != null)
            DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        val start = completedReadback ?: DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        if (!readbackStarted.compareAndSet(false, true)) DeviceFileControl.fail("gallery_incoming_readback_already_attempted")
        return start(this)
    }
    internal fun actualPublishedOutput(): GalleryIncomingPublication {
        if (actualSavedOutput() == null || error.get() != null) DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        return publications.get().singleOrNull() ?: DeviceFileControl.fail("gallery_incoming_completed_owner_required")
    }
    internal fun startAutomaticReadback() {
        try {
            val readback = startReadback(automatic = true)
            automaticReadback.set(readback)
            if (canceled.get()) readback.cancel()
        } catch (error: Throwable) { automaticError.set(error) }
        finally { automaticStarted.countDown() }
    }
    internal fun awaitAutomaticReadbackStart(timeoutMillis: Long): Boolean =
        automaticStarted.await(timeoutMillis, java.util.concurrent.TimeUnit.MILLISECONDS)
    internal fun automaticReadbackRun(): NativeGalleryPublishedReadRun? {
        if (!automaticReadbackRequested || automaticStarted.count != 0L) DeviceFileControl.fail("gallery_incoming_readback_pending")
        automaticError.get()?.let { throw it }
        return automaticReadback.get()
    }
}

/** Native worker ownership drains actual provider/network IO before releasing
 * the process slot or allowing runtime index cleanup. Construction starts no
 * thread. The dispatcher can supply chunks without the runtime operation lock. */
internal class NativeGalleryIncomingWorker(private val onEnded: () -> Unit = {}) : AutoCloseable {
    private val gate = Any()
    private var active: NativeGalleryIncomingRun? = null
    private var closed = false
    val current: NativeGalleryIncomingRun? get() = synchronized(gate) { active }
    val isQuiescent: Boolean get() = synchronized(gate) { active == null }
    internal fun owns(run: NativeGalleryIncomingRun): Boolean = run.belongsTo(this)

    internal fun start(completedReadback: ((NativeGalleryIncomingRun) -> NativeGalleryPublishedReadRun)? = null,
        automaticReadback: Boolean = false,
        prepare: () -> NativeGalleryIncomingTransfer): NativeGalleryIncomingRun {
        val run = synchronized(gate) {
            if (closed) DeviceFileControl.fail("gallery_incoming_worker_closed")
            if (active != null) DeviceFileControl.fail("gallery_incoming_worker_busy")
            NativeGalleryIncomingRun(this, completedReadback, automaticReadback).also {
                if (!NativeGalleryMediaIoLane.acquire(it)) DeviceFileControl.fail("gallery_incoming_worker_busy")
                active = it
            }
        }
        fun finish(message: JsonObject?, error: Throwable?, published: List<GalleryIncomingPublication> = emptyList()) {
            run.finish(message, error, published)
            synchronized(gate) { if (active === run) active = null }
            NativeGalleryMediaIoLane.release(run); run.markIoEnded()
            // Reuse this native worker thread; never block the authenticated
            // receiver or create a second waiter/polling thread for Saved.
            try { if (automaticReadback) run.startAutomaticReadback() }
            finally { try { onEnded() } finally { run.ioDrained() } }
        }
        val thread = Thread({
            var transfer: NativeGalleryIncomingTransfer? = null
            var message: JsonObject? = null; var failure: Throwable? = null
            try {
                run.cancellation.throwIfCanceled(); transfer = prepare(); run.install(transfer)
                transfer.sendAcceptance(); message = transfer.receiveAndSendSaved(run.cancellation)
            } catch (error: Throwable) { failure = error }
            finally {
                try { transfer?.close() } catch (error: Throwable) {
                    val original = failure
                    if (original == null) failure = error else original.addSuppressed(error)
                }
                finish(message, failure, transfer?.actualPublishedOutput() ?: emptyList())
            }
        }, "magnolie-media-incoming").apply { isDaemon = true }
        try { thread.start() } catch (error: Throwable) { finish(null, error); throw error }
        return run
    }

    override fun close() {
        val running = synchronized(gate) { closed = true; active }
        running?.cancel() // Native cancellation never runs under our owner monitor.
    }
}
