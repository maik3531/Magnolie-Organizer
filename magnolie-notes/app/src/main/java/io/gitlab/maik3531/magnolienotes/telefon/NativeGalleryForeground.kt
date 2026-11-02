package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import java.lang.ref.WeakReference

internal class NativeGalleryForegroundOwner internal constructor(internal val runtime: NativeGalleryFileRuntime)

/** Passive native Activity route only. Registering the early host does not
 * construct TelefonWerk/stores, start a service, request permission or activate
 * a source. A native controller must explicitly attach an existing runtime.
 */
internal object NativeGalleryForeground {
    private class Binding(val owner: NativeGalleryForegroundOwner, val onResult: (Result<GalleryReadCoverage>) -> Unit)
    private var host = WeakReference<GalleryPhotoPermissionHost>(null)
    private var binding: Binding? = null

    fun registerHost(value: GalleryPhotoPermissionHost) {
        uiThread()
        if (host.get() === value) return
        binding?.let { it.owner.runtime.attachPermissionHost(value, it.onResult) }
        host = WeakReference(value)
    }

    fun unregisterHost(value: GalleryPhotoPermissionHost) {
        uiThread()
        if (host.get() === value) host.clear()
        value.close() // Exact Activity owner, never a different/new host.
    }

    internal fun attach(runtime: NativeGalleryFileRuntime, onResult: (Result<GalleryReadCoverage>) -> Unit): NativeGalleryForegroundOwner {
        uiThread()
        binding?.let {
            if (it.owner.runtime !== runtime) DeviceFileControl.fail("gallery_foreground_runtime_busy")
            return it.owner
        }
        val owner = NativeGalleryForegroundOwner(runtime)
        host.get()?.let { runtime.attachPermissionHost(it, onResult) }
        binding = Binding(owner, onResult)
        return owner
    }

    internal fun detach(runtime: NativeGalleryFileRuntime) {
        uiThread()
        if (binding?.owner?.runtime === runtime) binding = null
    }

    fun isCurrent(owner: NativeGalleryForegroundOwner): Boolean {
        uiThread()
        return binding?.owner === owner
    }

    private fun uiThread() {
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
    }
}
