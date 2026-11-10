package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import java.lang.ref.WeakReference

/** Visible Activity rendezvous only. Never launch an Activity, persist a remote
 * request or mint capture authority from an Intent/preference. The authenticated
 * controller must supply its one-use live original request explicitly. */
internal object PhoneWebcamForeground {
    private var host = WeakReference<PhoneWebcamPermissionHost>(null)

    fun register(original: PhoneWebcamPermissionHost) {
        uiThread()
        host = WeakReference(original)
    }

    fun unregister(original: PhoneWebcamPermissionHost) {
        uiThread()
        if (host.get() === original) host.clear()
    }

    fun request(original: PhoneWebcamCaptureRequest, result: (Result<PhoneWebcamCapturePermit>) -> Unit) {
        uiThread()
        val visible = host.get() ?: error("webcam_visible_activity_required")
        visible.request(original, result)
    }

    private fun uiThread() {
        check(Looper.myLooper() == Looper.getMainLooper()) { "webcam_ui_thread_required" }
    }
}
