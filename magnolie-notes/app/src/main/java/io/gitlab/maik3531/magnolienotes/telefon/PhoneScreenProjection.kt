package io.gitlab.maik3531.magnolienotes.telefon

import android.app.KeyguardManager
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.projection.MediaProjection
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.view.Surface
import androidx.core.content.ContextCompat

/** One Android capture surface, never an extra desktop monitor or input grant.
 * The original foreground service owns this object and the encoder Surface.
 * Only the Android MediaProjection result can open it. No secure display flag,
 * retry on the same consent, or alternate method of getting protected pixels.
 * All methods and callbacks run on the main looper; the service joins its own
 * media worker and releases the Surface after this object detaches the display.
 */
internal class PhoneScreenProjection(
    private val service: Service,
    private val request: PhoneScreenViewRequest,
    private val consent: PhoneScreenViewConsent,
    private val onEnded: (Exception?) -> Unit,
) : AutoCloseable {
    private val handler = Handler(Looper.getMainLooper())
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var started = false
    private var terminal = false
    private var watchingScreen = false
    var cleanupError: Exception? = null
        private set
    var notificationError: Exception? = null
        private set
    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() = finish(null)
    }
    private val displayCallback = object : VirtualDisplay.Callback() {
        override fun onStopped() = finish(null)
    }
    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == Intent.ACTION_SCREEN_OFF) finish(null)
        }
    }
    private val poll = object : Runnable {
        override fun run() {
            if (terminal) return
            try { requireCurrent() }
            catch (error: Exception) { finish(error); return }
            handler.postDelayed(this, 200)
        }
    }

    fun start(surface: Surface, width: Int, height: Int, densityDpi: Int) {
        mainThread()
        check(!started && !terminal) { "screen_projection_owner_already_used" }
        started = true
        try {
            require(width in 1..4096 && height in 1..4096 && width.toLong() * height <= 4096L * 2160 && densityDpi in 1..1000)
            check(surface.isValid) { "screen_original_surface_invalid" }
            requireCurrent()
            ContextCompat.registerReceiver(service, screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
            watchingScreen = true
            val originalProjection = consent.open(request, service, projectionCallback)
            projection = originalProjection
            requireCurrent()
            display = checkNotNull(originalProjection.createVirtualDisplay("Magnolie phone screen", width, height, densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, surface, displayCallback, handler)) { "screen_virtual_display_unavailable" }
            requireCurrent()
            handler.postDelayed(poll, 200)
        } catch (error: Exception) {
            finish(error)
            throw error
        }
    }

    private fun requireCurrent() {
        check(!terminal) { "screen_projection_retired" }
        request.requireCurrent()
        check(Build.VERSION.SDK_INT >= 29 && service.foregroundServiceType == ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION) {
            "screen_actual_projection_foreground_required"
        }
        val keyguard = checkNotNull(service.getSystemService(KeyguardManager::class.java))
        val power = checkNotNull(service.getSystemService(PowerManager::class.java))
        check(power.isInteractive && !keyguard.isDeviceLocked && !keyguard.isKeyguardLocked) { "screen_device_locked" }
    }

    override fun close() {
        mainThread()
        finish(null)
    }

    private fun finish(cause: Exception?) {
        if (terminal) return
        terminal = true
        request.close()
        handler.removeCallbacks(poll)
        var failure = cause
        fun cleanup(action: () -> Unit) {
            try { action() }
            catch (error: Exception) {
                if (cleanupError == null) cleanupError = error
                if (failure == null) failure = error
                else if (failure !== error) failure?.addSuppressed(error)
            }
        }
        if (watchingScreen) cleanup { service.unregisterReceiver(screenOff) }
        watchingScreen = false
        val originalDisplay = display.also { display = null }
        val originalProjection = projection.also { projection = null }
        cleanup { originalDisplay?.release() }
        cleanup { originalProjection?.unregisterCallback(projectionCallback) }
        cleanup { originalProjection?.stop() }
        cleanup { consent.close() }
        // Notify once after all owned native cleanup was attempted. A failure
        // is not a promise of successful release/worker drain.
        try { onEnded(failure) }
        catch (error: Exception) { notificationError = error }
    }

    private fun mainThread() = check(Looper.myLooper() == Looper.getMainLooper()) { "screen_main_thread_required" }
}
