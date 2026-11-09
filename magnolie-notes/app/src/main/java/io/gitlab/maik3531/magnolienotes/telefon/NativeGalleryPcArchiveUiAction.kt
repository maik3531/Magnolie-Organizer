package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicReference

/** Native UI composition; cancellation never releases an outstanding worker's
 * provider/store owners. No wire action, permission prompt or fresh transport. */
internal object NativeGalleryPcArchiveUiAction {
    internal suspend fun request(activity: ComponentActivity, connection: NativeGalleryFileConnection,
        kind: GalleryMediaType, book: NativeGalleryReceiveBookPermit,
        archiveBook: NativeGalleryTrashBookPermit): NativeGalleryArchiveEntry {
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        val selected = AtomicReference<NativeGalleryPcArchiveSelection?>()
        val run = AtomicReference<NativeGalleryPublishedReadRun?>()
        val pending = AtomicReference<AutoCloseable?>()
        val observer = object : DefaultLifecycleObserver {
            override fun onPause(owner: LifecycleOwner) { selected.get()?.close(); run.get()?.cancel() }
            override fun onDestroy(owner: LifecycleOwner) { selected.get()?.close(); run.get()?.cancel() }
        }
        activity.lifecycle.addObserver(observer)
        try {
            // Publish ownership before returning from IO, including coroutine cancellation races.
            val selection = withContext(Dispatchers.IO) {
                connection.preparePcArchiveSelection(kind, book, archiveBook).also { selected.set(it) }
            }
            val index = suspendCancellableCoroutine<Int> { continuation ->
                continuation.invokeOnCancellation { selected.get()?.close(); pending.getAndSet(null)?.close() }
                val handle = NativeGalleryPcArchivePrompt.request(activity, selection) { outcome ->
                    if (outcome.exceptionOrNull()?.message == "gallery_archive_local_confirmation_canceled") continuation.cancel()
                    else if (continuation.isActive) continuation.resumeWith(outcome)
                    else selection.close()
                }
                pending.set(handle)
                if (!continuation.isActive) pending.getAndSet(null)?.close()
            }
            val actual = withContext(Dispatchers.IO) { selection.confirm(index).also { run.set(it) } }
            return suspendCancellableCoroutine { continuation ->
                continuation.invokeOnCancellation { selection.close(); actual.cancel() }
                // Completion is published by the existing worker only after real IO drain.
                actual.notifyWhenIoDrained {
                    val outcome = runCatching {
                        actual.nativeFailure()?.let { throw it }
                        actual.actualArchiveOutput() ?: DeviceFileControl.fail("gallery_archive_original_action_required")
                    }
                    if (continuation.isActive) continuation.resumeWith(outcome)
                }
            }
        } finally {
            selected.get()?.close(); run.get()?.takeUnless { it.ioEnded }?.cancel(); pending.getAndSet(null)?.close()
            activity.lifecycle.removeObserver(observer)
            withContext(NonCancellable + Dispatchers.IO) {
                run.get()?.let { actual -> while (!actual.awaitIoEnded(1000)) { /* retain until actual IO ends */ } }
            }
        }
    }
}
