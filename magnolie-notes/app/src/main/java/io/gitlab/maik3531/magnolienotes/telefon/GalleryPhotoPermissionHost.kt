package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import java.util.concurrent.atomic.AtomicReference

/** Activity-owned early registration, with late native workflow attachment.
 * Construct before STARTED; attaching an explicitly activated source while the
 * Activity is already resumed never registers another launcher or recreates it.
 * No store/key access, settings screen or permission prompt on construction.
 */
internal class GalleryPhotoPermissionHost(private val activity: ComponentActivity,
    internal val mediaType: GalleryMediaType = GalleryMediaType.IMAGES,
    private val writeConsent: NativeGalleryWriteConsentHost? = null) : DefaultLifecycleObserver, AutoCloseable {
    private class Attachment(val workflow: NativeGalleryPhotoWorkflow, val onResult: (Result<GalleryReadCoverage>) -> Unit)
    private val attachment = AtomicReference<Attachment?>()
    private val pendingResult = AtomicReference<Attachment?>()
    private var closed = false
    internal val applicationContext get() = activity.applicationContext
    private val launcher = GalleryPhotoPermissionLauncher(activity, { attachment.get()?.workflow?.currentRequest(mediaType) }, mediaType) { result ->
        val original = pendingResult.getAndSet(null)
        if (original != null && attachment.get() === original) {
            original.workflow.nativeReadAccessChanged(); original.onResult(result)
        }
    }
    internal val requestPending: Boolean get() = launcher.requestPending
    init { activity.lifecycle.addObserver(this) }

    internal fun attach(workflow: NativeGalleryPhotoWorkflow, onResult: (Result<GalleryReadCoverage>) -> Unit): GalleryPhotoPermissionLauncher {
        uiThread()
        if (closed) fail("gallery_permission_host_closed")
        if (attachment.get()?.workflow === workflow) return launcher
        if (launcher.requestPending || writeConsent?.requestPending == true) fail("gallery_permission_request_pending")
        val next = Attachment(workflow, onResult)
        val previous = attachment.getAndSet(next)
        previous?.workflow?.detachPermissionHost(this)
        pendingResult.set(null)
        launcher.access.onAccessChanged()
        return launcher
    }

    internal fun request(workflow: NativeGalleryPhotoWorkflow) {
        uiThread()
        if (closed) fail("gallery_permission_host_closed")
        val original = attachment.get()?.takeIf { it.workflow === workflow } ?: fail("gallery_permission_host_owner_changed")
        if (launcher.requestPending || writeConsent?.requestPending == true || !pendingResult.compareAndSet(null, original)) fail("gallery_permission_request_pending")
        try { launcher.request() }
        catch (error: Exception) { pendingResult.compareAndSet(original, null); throw error }
    }

    internal fun detach(workflow: NativeGalleryPhotoWorkflow) {
        val original = attachment.get()?.takeIf { it.workflow === workflow } ?: return
        if (attachment.compareAndSet(original, null)) {
            writeConsent?.retirePending()
            pendingResult.compareAndSet(original, null)
            launcher.access.onAccessChanged()
        }
        // A launched Android request is still held until its old callback or
        // Activity destruction. Do not let that callback consume a new ticket.
    }

    internal fun requestOriginalAccess(workflow: NativeGalleryPhotoWorkflow, request: NativeGalleryOriginalAccessRequest,
        result: (Result<Unit>) -> Unit) {
        uiThread()
        val original = attachment.get()?.takeIf { it.workflow === workflow } ?: fail("gallery_permission_host_owner_changed")
        if (closed || launcher.requestPending) fail("gallery_write_foreground_required")
        val writer = writeConsent ?: fail("gallery_write_foreground_required")
        writer.requestOriginal(request) { outcome ->
            if (attachment.get() === original && !closed) result(outcome) else request.revoke()
        }
    }

    internal fun requestWrite(workflow: NativeGalleryPhotoWorkflow, request: NativeGalleryWriteRequest,
        result: (Result<NativeGalleryWriteGrant>) -> Unit) {
        uiThread()
        val original = attachment.get()?.takeIf { it.workflow === workflow } ?: fail("gallery_permission_host_owner_changed")
        if (closed || launcher.requestPending || mediaType != request.mediaType) fail("gallery_write_foreground_required")
        val writer = writeConsent ?: fail("gallery_write_foreground_required")
        writer.request(request) { outcome ->
            if (attachment.get() === original && !closed) result(outcome) else request.revoke()
        }
    }

    override fun onDestroy(owner: LifecycleOwner) { close() }
    override fun close() {
        uiThread()
        if (closed) return
        closed = true
        writeConsent?.retirePending()
        attachment.getAndSet(null)?.workflow?.detachPermissionHost(this)
        pendingResult.set(null)
        launcher.close()
        activity.lifecycle.removeObserver(this)
    }
    private fun uiThread() { if (Looper.myLooper() != Looper.getMainLooper()) fail("gallery_permission_ui_thread_required") }
    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
