package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicReference

/** Explicit foreground UI action only. It uses the already owned connection;
 * neither creating a transport nor turning a source READ grant into reception. */
internal object NativeGalleryReceiveAction {
    internal suspend fun request(activity: ComponentActivity, connection: NativeGalleryFileConnection,
        nativePeerLabel: String, kind: GalleryMediaType, book: NativeGalleryReceiveBookPermit,
        requireAgreement: () -> Unit): GalleryPhotoPolicySnapshot {
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        val runtime = connection.runtime
        val ticket = AtomicReference<NativeFileReceiveConfigurer?>()
        val chosen = AtomicReference<NativeGalleryReceiveConsent?>()
        val pending = AtomicReference<AutoCloseable?>()
        fun current() {
            book.requireCurrent()
            if (connection.isEnded || connection.runtime !== runtime) DeviceFileControl.fail("gallery_incoming_foreign_connection")
        }
        try {
            val (snapshot, intent) = withContext(Dispatchers.IO) {
                current()
                requireAgreement()
                val intent = runtime.receiveConsentIntent(kind)
                ticket.set(runtime.beginReceiveConfiguration())
                runtime.savedPolicy() to intent
            }
            val selection = withContext(Dispatchers.Main.immediate) {
                current()
                suspendCancellableCoroutine<NativeGalleryReceiveConsent> { continuation ->
                    continuation.invokeOnCancellation { pending.getAndSet(null)?.close() }
                    val handle = NativeGalleryReceiveConsent.request(activity, nativePeerLabel, kind,
                        ticket.get() ?: DeviceFileControl.fail("file_control_configuration_not_ready"), book) { result ->
                        result.getOrNull()?.let { chosen.set(it) }
                        if (result.exceptionOrNull()?.message == "gallery_receive_local_consent_canceled") continuation.cancel()
                        else if (continuation.isActive) continuation.resumeWith(result)
                        else result.getOrNull()?.close()
                    }
                    pending.set(handle)
                    if (!continuation.isActive && chosen.get() == null) pending.getAndSet(null)?.close()
                }
            }
            return withContext(Dispatchers.IO) {
                current()
                // Fresh transport/settings IO stays off Main and OUTSIDE the
                // protected index guards. Their intent callback stays lock-free.
                requireAgreement()
                if (runtime.receiveConsentIntent(kind) !== intent) DeviceFileControl.fail("gallery_incoming_offer_intent_changed")
                runtime.grantReceiving(snapshot, selection).also { runtime.sendControls() }
            }
        } finally {
            pending.getAndSet(null)?.close()
            chosen.getAndSet(null)?.close()
            withContext(NonCancellable + Dispatchers.IO) {
                ticket.getAndSet(null)?.let { runCatching { runtime.finishReceiveConfiguration(it) } }
            }
        }
    }
}
