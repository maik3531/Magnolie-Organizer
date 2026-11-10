package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Service
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Looper
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicBoolean

/** Original native desktop request, not a saved Boolean or Android grant.
 * The authenticated provider must supply its exact live peer/channel/opt-in guard.
 * No default guard, persisted request, restart or cross-app permission transfer.
 */
internal class PhoneWebcamCaptureRequest(val session: String, val muted: Boolean, val frontCamera: Boolean,
    private val current: () -> Unit, private val clock: () -> Long = SystemClock::elapsedRealtime) : AutoCloseable {
    private val issued = clock()
    private val retired = AtomicBoolean(false)
    private val prompted = AtomicBoolean(false)
    private val permissionResult = AtomicBoolean(false)
    private val foreground = AtomicBoolean(false)
    @Volatile var terminalFailure: Throwable? = null
        private set
    init { require(Regex("[0-9a-f]{32}").matches(session) && issued >= 0); requireOriginal() }
    internal val permissions: Array<String> get() = if (muted) arrayOf(Manifest.permission.CAMERA)
        else arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
    internal fun requireOriginal() {
        try {
            check(!retired.get()) { "webcam_original_request_retired" }
            current()
            val now = clock()
            check(!retired.get() && now >= issued && (foreground.get() || now - issued < 60_000)) { "webcam_original_request_retired" }
        } catch (error: Throwable) { retire(error); throw error }
    }
    internal fun claimPrompt() {
        requireOriginal()
        check(prompted.compareAndSet(false, true)) { "webcam_permission_request_already_used" }
    }
    internal fun requirePermissions(context: Context) {
        requireOriginal()
        check(permissions.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }) {
            "webcam_actual_android_permission_required"
        }
        requireOriginal()
    }
    internal fun claimPermissionResult() {
        requireOriginal()
        check(prompted.get() && permissionResult.compareAndSet(false, true)) { "webcam_original_permission_result_required" }
    }
    internal fun claimForeground() {
        requireOriginal()
        check(foreground.compareAndSet(false, true)) { "webcam_foreground_owner_already_used" }
    }
    override fun close() { retired.set(true) }
    internal fun retire(error: Throwable) { if (terminalFailure == null) terminalFailure = error; close() }
}

/** Minted only from this Activity's genuine permission-result/lifecycle path. */
internal class PhoneWebcamCapturePermit private constructor(private val request: PhoneWebcamCaptureRequest,
    activity: ComponentActivity) : AutoCloseable {
    private val originalActivity = WeakReference(activity)
    @Volatile private var service: Service? = null
    val session get() = request.session
    val muted get() = request.muted
    val frontCamera get() = request.frontCamera

    internal fun requireVisibleStart() {
        check(service == null) { "webcam_foreground_owner_already_used" }
        val activity = checkNotNull(originalActivity.get()) { "webcam_original_activity_required" }
        check(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && !activity.isFinishing) { "webcam_visible_activity_required" }
        request.requirePermissions(activity)
    }

    @Synchronized fun enterForeground(actual: Service) {
        try {
            check(service == null) { "webcam_foreground_owner_already_used" }
            requireVisibleStart()
            request.requirePermissions(actual)
            checkForeground(actual)
            request.claimForeground()
            service = actual
            originalActivity.clear()
        } catch (error: Throwable) { close(); throw error }
    }
    fun requireActive(actual: Service) {
        try {
            check(service === actual) { "webcam_original_foreground_service_required" }
            request.requirePermissions(actual)
            checkForeground(actual)
        } catch (error: Throwable) { close(); throw error }
    }
    private fun checkForeground(actual: Service) {
        // Optional feature requirement only; Notes itself keeps its older minSdk.
        if (Build.VERSION.SDK_INT < 30) error("webcam_android_version_unsupported")
        val mask = ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        val expected = ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or if (muted) 0 else ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        check(actual.foregroundServiceType and mask == expected) { "webcam_actual_foreground_capture_required" }
    }
    override fun close() { request.close() }
    companion object {
        internal fun fromOriginalPermissionResult(activity: ComponentActivity, request: PhoneWebcamCaptureRequest): PhoneWebcamCapturePermit {
            check(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) { "webcam_visible_activity_required" }
            request.requirePermissions(activity)
            request.claimPermissionResult()
            return PhoneWebcamCapturePermit(request, activity)
        }
    }
}

/** Early Activity registration only, with NO startup probe/prompt/capture.
 * Attach the future authenticated desktop route explicitly. Background requests
 * must remain pending for a real foreground Activity, never launch it silently.
 */
internal class PhoneWebcamPermissionHost(private val activity: ComponentActivity,
    private val otherPermissionPending: () -> Boolean) : DefaultLifecycleObserver, AutoCloseable {
    private class Pending(val request: PhoneWebcamCaptureRequest, val result: (Result<PhoneWebcamCapturePermit>) -> Unit) {
        var returned: Map<String, Boolean>? = null
        var failed = false
    }
    private var pending: Pending? = null
    private var closed = false
    val requestPending get() = pending != null
    private val launcher = activity.registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { returned ->
        pending?.let { it.returned = returned; completeIfResumed() }
    }
    init { activity.lifecycle.addObserver(this) }

    fun request(original: PhoneWebcamCaptureRequest, result: (Result<PhoneWebcamCapturePermit>) -> Unit) {
        uiThread()
        check(!closed && !requestPending && !otherPermissionPending()) { "webcam_permission_slot_unavailable" }
        check(Build.VERSION.SDK_INT >= 30) { "webcam_android_version_unsupported" }
        check(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) { "webcam_visible_activity_required" }
        original.claimPrompt()
        pending = Pending(original, result)
        try { launcher.launch(original.permissions) }
        catch (error: Throwable) { pending = null; original.close(); throw error }
    }
    private fun completeIfResumed() {
        uiThread()
        val original = pending ?: return
        val returned = original.returned ?: return
        if (!activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        pending = null
        if (original.failed) return
        val outcome = runCatching {
            check(!closed && !otherPermissionPending() && original.request.permissions.all { returned[it] == true }) { "webcam_android_permission_denied" }
            PhoneWebcamCapturePermit.fromOriginalPermissionResult(activity, original.request)
        }
        deliver(original, outcome)
    }
    private fun deliver(original: Pending, outcome: Result<PhoneWebcamCapturePermit>) {
        outcome.exceptionOrNull()?.let { original.request.retire(it) }
        try { original.result(outcome) }
        catch (error: Exception) {
            // An optional adapter startup failure must not crash the Activity's
            // OS-result/lifecycle callback or create another permission result.
            outcome.getOrNull()?.close(); original.request.retire(error)
        }
    }
    override fun onResume(owner: LifecycleOwner) { completeIfResumed() }
    override fun onStop(owner: LifecycleOwner) {
        val original = pending ?: return
        if (original.failed) return
        // Keep the original OS-result slot occupied until that result returns;
        // a late old callback must never consume a new request's ticket.
        original.failed = true; original.request.close()
        deliver(original, Result.failure(IllegalStateException("webcam_original_activity_stopped")))
    }
    override fun onDestroy(owner: LifecycleOwner) { close() }
    override fun close() {
        uiThread()
        if (closed) return
        closed = true
        val original = pending; pending = null
        original?.request?.close()
        launcher.unregister(); activity.lifecycle.removeObserver(this)
        if (original != null && !original.failed) deliver(original, Result.failure(IllegalStateException("webcam_permission_host_closed")))
    }
    private fun uiThread() { check(Looper.myLooper() == Looper.getMainLooper()) { "webcam_ui_thread_required" } }
}
