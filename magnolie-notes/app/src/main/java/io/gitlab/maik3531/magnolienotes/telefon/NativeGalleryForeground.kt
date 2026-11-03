package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import android.content.Context
import java.lang.ref.WeakReference

internal class NativeGalleryForegroundOwner internal constructor(internal val runtime: NativeGalleryFileRuntime,
    internal val mediaType: GalleryMediaType = GalleryMediaType.IMAGES)

/** Passive native Activity route only. Registering the early host does not
 * construct TelefonWerk/stores, start a service, request permission or activate
 * a source. A native controller must explicitly attach an existing runtime.
 */
internal object NativeGalleryForeground {
    private class Binding(val owner: NativeGalleryForegroundOwner, val onResult: (Result<GalleryReadCoverage>) -> Unit)
    private class Route(val mediaType: GalleryMediaType) {
        var host = WeakReference<GalleryPhotoPermissionHost>(null)
        var binding: Binding? = null
        val actions = NativeGalleryPermissionActions({ binding?.let { current ->
            current.owner.runtime.currentRequest(mediaType)?.let { NativeGalleryPermissionActionScope(current.owner, it) }
        } })
    }
    private val routes = GalleryMediaType.entries.associateWith { Route(it) }

    fun registerHost(value: GalleryPhotoPermissionHost) {
        uiThread()
        val route = routes.getValue(value.mediaType)
        if (route.host.get() === value) return
        route.binding?.let { it.owner.runtime.attachPermissionHost(value, it.onResult) }
        route.host = WeakReference(value)
    }

    fun unregisterHost(value: GalleryPhotoPermissionHost) {
        uiThread()
        val route = routes.getValue(value.mediaType)
        if (route.host.get() === value) route.host.clear()
        value.close() // Exact Activity owner, never a different/new host.
    }

    internal fun attach(runtime: NativeGalleryFileRuntime, onResult: (Result<GalleryReadCoverage>) -> Unit,
        mediaType: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryForegroundOwner {
        uiThread()
        if (routes.values.any { it.binding?.owner?.runtime?.let { held -> held !== runtime } == true })
            DeviceFileControl.fail("gallery_foreground_runtime_busy")
        val route = routes.getValue(mediaType)
        route.binding?.let {
            if (it.owner.runtime !== runtime) DeviceFileControl.fail("gallery_foreground_runtime_busy")
            return it.owner
        }
        val owner = NativeGalleryForegroundOwner(runtime, mediaType)
        route.host.get()?.let { runtime.attachPermissionHost(it, onResult) }
        route.binding = Binding(owner, onResult)
        return owner
    }

    internal fun detach(runtime: NativeGalleryFileRuntime) {
        uiThread()
        routes.values.forEach { route ->
            route.binding?.takeIf { it.owner.runtime === runtime }?.let { route.actions.cancelOwner(it.owner); route.binding = null }
        }
    }

    fun isCurrent(owner: NativeGalleryForegroundOwner): Boolean {
        uiThread()
        return routes.getValue(owner.mediaType).binding?.owner === owner
    }

    fun permissionAction(owner: NativeGalleryForegroundOwner): NativeGalleryPermissionAction {
        uiThread()
        if (!isCurrent(owner)) DeviceFileControl.fail("gallery_permission_action_source_changed")
        return routes.getValue(owner.mediaType).actions.create()
    }

    fun acceptsPermissionAction(token: String): Boolean {
        uiThread()
        return routes.values.any { runCatching { it.actions.isCurrent(token) }.getOrDefault(false) }
    }

    fun performPermissionAction(token: String) {
        uiThread()
        val route = routes.values.singleOrNull { it.actions.isCurrent(token) }
            ?: DeviceFileControl.fail("gallery_permission_action_unknown")
        route.actions.perform(token) { owner ->
            val current = route.binding?.takeIf { it.owner === owner } ?: DeviceFileControl.fail("gallery_permission_action_source_changed")
            current.owner.runtime.requestReadPermission(route.mediaType)
        }
    }

    fun postPermissionAction(context: Context, action: NativeGalleryPermissionAction): Boolean {
        uiThread()
        if (!routes.getValue(action.mediaType).actions.isCurrent(action.token)) DeviceFileControl.fail("gallery_permission_action_source_changed")
        return GalleryPhotoPermissionIntent.post(context, action)
    }

    private fun uiThread() {
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
    }
}
