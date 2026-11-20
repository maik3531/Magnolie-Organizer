package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Activity
import android.app.KeyguardManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResult
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import java.lang.ref.WeakReference
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/** A one-shot view request owned by the original authenticated desktop session. */
internal class PhoneScreenViewRequest(private val originalCurrent: () -> Unit,
    private val clock: () -> Long = SystemClock::elapsedRealtime) : AutoCloseable {
    private val issued = clock()
    private val retired = AtomicBoolean(false)
    private val prompted = AtomicBoolean(false)
    private val started = AtomicBoolean(false)

    internal fun requireCurrent() {
        try {
            check(!retired.get()) { "screen_request_retired" }
            originalCurrent()
            val now = clock()
            check(!retired.get() && issued >= 0 && now >= issued && (started.get() || now - issued < 60_000)) { "screen_request_expired" }
        } catch (error: Exception) { close(); throw error }
    }

    internal fun claimPrompt() {
        requireCurrent()
        check(prompted.compareAndSet(false, true)) { "screen_request_already_prompted" }
    }

    internal fun markProjectionStarted() {
        requireCurrent()
        check(prompted.get() && started.compareAndSet(false, true)) { "screen_projection_already_started" }
    }

    override fun close() { retired.set(true) }
}

/** No grant is exposed to the network, persisted, or shared with the webcam path. */
internal interface PhoneScreenViewConsent : AutoCloseable {
    /** Must be called from the original projection foreground service after promotion.
     * The caller owns projection stop, virtual-display release and worker drain.
     */
    fun open(original: PhoneScreenViewRequest, service: Service, callback: MediaProjection.Callback): MediaProjection
}

/** Observe the original Activity. Only request() can launch
 * Android's own share dialog, and only while the Activity is visible and unlocked.
 * This adapter has no startup action or phone settings.
 */
internal class PhoneScreenConsentHost(private val activity: ComponentActivity,
    private val otherPermissionPending: () -> Boolean) : DefaultLifecycleObserver, AutoCloseable {
    private class Pending(val request: PhoneScreenViewRequest, val deliver: (Result<PhoneScreenViewConsent>) -> Unit) {
        var returned: ActivityResult? = null
        var launcher: ActivityResultLauncher<Intent>? = null
    }
    private var pending: Pending? = null
    private var closed = false
    val requestPending get() = pending != null

    init { activity.lifecycle.addObserver(this) }

    fun request(original: PhoneScreenViewRequest, deliver: (Result<PhoneScreenViewConsent>) -> Unit) {
        requireMainThread()
        check(!closed && !requestPending && !otherPermissionPending()) { "screen_consent_slot_unavailable" }
        // API 29 has a dedicated mediaProjection foreground-service type.
        check(Build.VERSION.SDK_INT >= 29) { "screen_projection_version_unsupported" }
        requireVisible(activity)
        original.claimPrompt()
        val operation = Pending(original, deliver)
        pending = operation
        try {
            val manager = checkNotNull(activity.getSystemService(MediaProjectionManager::class.java))
            // Unique even across requests on the same Activity; a stale OS
            // result cannot satisfy any subsequent mirror request.
            val launcher = activity.activityResultRegistry.register("magnolie.screen.${UUID.randomUUID()}",
                ActivityResultContracts.StartActivityForResult()) { returned ->
                if (pending === operation && operation.returned == null) {
                    operation.returned = returned
                    completeIfResumed()
                }
            }
            operation.launcher = launcher
            original.requireCurrent()
            launcher.launch(manager.createScreenCaptureIntent())
        } catch (error: Exception) {
            if (pending === operation) pending = null
            operation.launcher?.unregister()
            original.close()
            throw error
        }
    }

    private fun completeIfResumed() {
        requireMainThread()
        val operation = pending ?: return
        val returned = operation.returned ?: return
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        pending = null
        // Unregister after the registry finishes dispatching the original result.
        Handler(Looper.getMainLooper()).post { operation.launcher?.unregister(); operation.launcher = null }
        val outcome = runCatching {
            requireVisible(activity)
            operation.request.requireCurrent()
            check(!closed && !otherPermissionPending() && returned.resultCode == Activity.RESULT_OK) { "screen_consent_denied" }
            val data = checkNotNull(returned.data) { "screen_os_result_required" }
            Permit(operation.request, activity, data)
        }
        deliver(operation, outcome)
    }

    private fun deliver(operation: Pending, outcome: Result<PhoneScreenViewConsent>) {
        if (outcome.isFailure) operation.request.close()
        try { operation.deliver(outcome) }
        catch (error: Exception) { outcome.getOrNull()?.close(); operation.request.close() }
    }

    override fun onResume(owner: LifecycleOwner) { completeIfResumed() }
    override fun onDestroy(owner: LifecycleOwner) { close() }

    override fun close() {
        requireMainThread()
        if (closed) return
        closed = true
        val operation = pending
        pending = null
        operation?.launcher?.unregister()
        activity.lifecycle.removeObserver(this)
        if (operation != null) deliver(operation, Result.failure(IllegalStateException("screen_consent_host_closed")))
    }

    private class Permit(private val request: PhoneScreenViewRequest, activity: ComponentActivity, data: Intent) : PhoneScreenViewConsent {
        private val originalActivity = WeakReference(activity)
        private var data: Intent? = data

        override fun open(original: PhoneScreenViewRequest, service: Service, callback: MediaProjection.Callback): MediaProjection {
            requireMainThread()
            check(request === original) { "screen_original_request_required" }
            val result = checkNotNull(data) { "screen_os_result_already_consumed" }
            data = null // Even native failure consumes this OS result.
            var projection: MediaProjection? = null
            try {
                request.requireCurrent()
                requireVisible(checkNotNull(originalActivity.get()))
                check(Build.VERSION.SDK_INT >= 29 && service.foregroundServiceType == ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION) {
                    "screen_actual_projection_foreground_required"
                }
                val manager = checkNotNull(service.getSystemService(MediaProjectionManager::class.java))
                projection = checkNotNull(manager.getMediaProjection(Activity.RESULT_OK, result))
                // Android 14+ requires callback registration before virtual display creation.
                projection.registerCallback(callback, Handler(Looper.getMainLooper()))
                requireUnlocked(service)
                request.markProjectionStarted()
                return projection
            } catch (error: Exception) {
                request.close()
                try { projection?.stop() } catch (cleanup: Exception) { error.addSuppressed(cleanup) }
                throw error
            }
        }

        override fun close() {
            requireMainThread()
            data = null
            request.close()
        }
    }

    companion object {
        private fun requireMainThread() = check(Looper.myLooper() == Looper.getMainLooper()) { "screen_main_thread_required" }
        private fun requireUnlocked(context: Context) {
            val lock = checkNotNull(context.getSystemService(KeyguardManager::class.java))
            check(!lock.isDeviceLocked && !lock.isKeyguardLocked) { "screen_device_locked" }
        }
        private fun requireVisible(activity: ComponentActivity) {
            check(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && !activity.isFinishing && !activity.isDestroyed) {
                "screen_visible_activity_required"
            }
            requireUnlocked(activity)
        }
    }
}
