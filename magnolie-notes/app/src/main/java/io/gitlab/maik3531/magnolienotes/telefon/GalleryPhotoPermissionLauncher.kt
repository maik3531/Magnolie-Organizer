package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner

/** Real Android activity-result/lifecycle adapter. Construct before STARTED.
 * No layout/settings screen or startup permission request is added. A future
 * authenticated desktop command must call request on the native foreground UI
 * thread, or report foreground/notification-tap pending instead of bypassing
 * Android's background-start restrictions.
 */
internal class GalleryPhotoPermissionLauncher private constructor(private val activity: ComponentActivity,
    current: () -> NativeGalleryRequest?, private val onResult: (Result<GalleryReadCoverage>) -> Unit,
    mediaType: GalleryMediaType) : DefaultLifecycleObserver, AutoCloseable {
    constructor(activity: ComponentActivity, current: () -> NativeGalleryRequest?, onResult: (Result<GalleryReadCoverage>) -> Unit) :
        this(activity, current, onResult, GalleryMediaType.IMAGES)
    constructor(activity: ComponentActivity, current: () -> NativeGalleryRequest?, mediaType: GalleryMediaType,
        onResult: (Result<GalleryReadCoverage>) -> Unit) : this(activity, current, onResult, mediaType)
    val access = GalleryPhotoAccessController(activity, current, mediaType = mediaType)
    private var ticket: GalleryPhotoPermissionTicket? = null
    private var closed = false
    internal val requestPending: Boolean get() = ticket != null
    private val launcher = activity.registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        // Lost/recreated native owner: an old OS callback cannot select a new
        // source or recreate a ticket from saved strings/Boolean grant claims.
        val original = ticket ?: return@registerForActivityResult
        ticket = null
        onResult(runCatching { access.complete(original) })
    }

    init { activity.lifecycle.addObserver(this) }

    fun request() {
        if (Looper.myLooper() != Looper.getMainLooper()) throw PhotoFolderScopeError("gallery_permission_ui_thread_required")
        if (closed) throw PhotoFolderScopeError("gallery_access_controller_closed")
        val original = access.preparePermissionRequest()
        ticket = original
        try { access.launch(original) { launcher.launch(it) } }
        catch (error: Exception) { ticket = null; throw error }
    }

    override fun onResume(owner: LifecycleOwner) { access.onResume() }
    override fun onPause(owner: LifecycleOwner) { access.onPause() }
    override fun onDestroy(owner: LifecycleOwner) { close() }

    override fun close() {
        if (closed) return
        closed = true
        ticket = null
        access.close()
        launcher.unregister()
        activity.lifecycle.removeObserver(this)
    }
}
