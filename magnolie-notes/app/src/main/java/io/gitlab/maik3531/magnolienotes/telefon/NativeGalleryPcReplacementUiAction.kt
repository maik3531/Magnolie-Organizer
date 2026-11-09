package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import java.util.concurrent.atomic.AtomicReference

/** Original authenticated offer -> original native archive/request -> real OS
 * result -> exact worker -> original readback. The OS dialog's own pause is
 * intentional; every other foreground loss cancels without pretending IO ended. */
internal object NativeGalleryPcReplacementUiAction {
    internal suspend fun request(activity: ComponentActivity, host: NativeGalleryPcWriteConsentHost,
        connection: NativeGalleryFileConnection, message: JsonObject, book: NativeGalleryReceiveBookPermit,
        archiveBook: NativeGalleryTrashBookPermit) {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
            DeviceFileControl.fail("gallery_pc_write_foreground_required")
        val preparation = AtomicReference<NativeGalleryPublishedReadRun?>()
        val worker = AtomicReference<NativeGalleryPcReplacementRun?>()
        val readback = AtomicReference<NativeGalleryPublishedReadRun?>()
        var osDialog = false
        fun cancel() {
            preparation.get()?.let { connection.cancelPcReplacement(it); it.cancel() }
            worker.get()?.cancel(); readback.get()?.cancel()
        }
        val observer = object : DefaultLifecycleObserver {
            override fun onPause(owner: LifecycleOwner) { if (!osDialog) cancel() }
            override fun onDestroy(owner: LifecycleOwner) { cancel() }
        }
        activity.lifecycle.addObserver(observer)
        try {
            val original = withContext(Dispatchers.IO) {
                connection.preparePcReplacement(message, book, archiveBook).also { preparation.set(it) }
            }
            awaitPublished(original)
            val request = original.actualPcWriteRequest() ?: DeviceFileControl.fail("gallery_pc_worker_original_request_required")
            osDialog = true
            val grant = try {
                suspendCancellableCoroutine<NativeGalleryPcWriteGrant> { continuation ->
                    continuation.invokeOnCancellation { cancel() }
                    try { host.request(request) { outcome ->
                        if (continuation.isActive) continuation.resumeWith(outcome) else request.close()
                    } } catch (failed: Exception) { if (continuation.isActive) continuation.resumeWith(Result.failure(failed)) }
                }
            } finally { osDialog = false }
            awaitResumed(activity)
            val actual = withContext(Dispatchers.IO) {
                connection.beginPcReplacement(original, grant).also { worker.set(it) }
            }
            suspendCancellableCoroutine<Unit> { continuation ->
                continuation.invokeOnCancellation { actual.cancel() }
                actual.notifyWhenIoDrained {
                    val outcome = runCatching {
                        actual.nativeFailure()?.let { throw it }
                        actual.actualSavedOutput() ?: DeviceFileControl.fail("gallery_pc_worker_original_completion_required")
                        Unit
                    }
                    if (continuation.isActive) continuation.resumeWith(outcome)
                }
            }
            val proof = withContext(Dispatchers.IO) { connection.beginCompletedPcReadback(actual).also { readback.set(it) } }
            awaitPublished(proof)
            proof.actualReadbackOutput() ?: DeviceFileControl.fail("gallery_incoming_original_readback_required")
        } finally {
            cancel()
            activity.lifecycle.removeObserver(observer)
            withContext(NonCancellable + Dispatchers.IO) {
                preparation.get()?.let { while (!it.awaitIoEnded(1000)) { /* real archive IO end */ } }
                worker.get()?.let { while (!it.awaitIoEnded(1000)) { /* real observer/send/archive end */ } }
                readback.get()?.let { while (!it.awaitIoEnded(1000)) { /* real canonical read/send end */ } }
            }
        }
    }
    private suspend fun awaitPublished(run: NativeGalleryPublishedReadRun) = suspendCancellableCoroutine<Unit> { continuation ->
        continuation.invokeOnCancellation { run.cancel() }
        run.notifyWhenIoDrained {
            val outcome = runCatching { run.nativeFailure()?.let { throw it }; Unit }
            if (continuation.isActive) continuation.resumeWith(outcome)
        }
    }
    private suspend fun awaitResumed(activity: ComponentActivity) {
        if (activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        suspendCancellableCoroutine<Unit> { continuation ->
            val observer = object : DefaultLifecycleObserver {
                override fun onResume(owner: LifecycleOwner) {
                    activity.lifecycle.removeObserver(this)
                    if (continuation.isActive) continuation.resumeWith(Result.success(Unit))
                }
                override fun onDestroy(owner: LifecycleOwner) { continuation.cancel() }
            }
            continuation.invokeOnCancellation { android.os.Handler(Looper.getMainLooper()).post { activity.lifecycle.removeObserver(observer) } }
            activity.lifecycle.addObserver(observer)
        }
    }
}
