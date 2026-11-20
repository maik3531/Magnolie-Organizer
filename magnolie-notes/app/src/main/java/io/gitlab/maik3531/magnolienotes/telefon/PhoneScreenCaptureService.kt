package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.view.Surface
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import io.gitlab.maik3531.magnolienotes.R
import java.util.UUID

/** Encoder adapter of this exact viewing request. Stop is a nonblocking signal;
 * drained becomes true only after the worker and its Surface are released. */
internal interface PhoneScreenOutput {
    val surface: Surface
    fun requestStop()
    fun isDrained(): Boolean
    val failure: Exception? get() = null
}

/** An output setup attempt failed and could not confirm native teardown. */
internal class PhoneScreenOutputCleanupException(cause: Exception) : IllegalStateException("screen_output_cleanup_unconfirmed", cause)

/** Process-local control handle. Only the exact attached projection can prove capture current. */
internal interface PhoneScreenCaptureHandle : AutoCloseable {
    fun requireActive()
    fun isDrained(): Boolean
}

/** Process-local one-shot handoff, never an Android grant in an Intent or on disk.
 * The caller supplies the original decoder/transport counterpart and must own
 * the opt-in guard. There is deliberately no boot, retry or browser entry point. */
@RequiresApi(29)
internal object PhoneScreenServiceStarts {
    internal class Entry(val request: PhoneScreenViewRequest, private val consent: PhoneScreenViewConsent,
        private val width: Int, private val height: Int, private val density: Int,
        private val openOutput: () -> PhoneScreenOutput) {
        val token: String = UUID.randomUUID().toString()
        val issued = SystemClock.elapsedRealtime()
        var service: PhoneScreenCaptureService? = null
            private set
        var stoppingAt: Long? = null
            private set
        private var projection: PhoneScreenProjection? = null
        private var output: PhoneScreenOutput? = null
        private var openingOutput = false
        var failure: Exception? = null
            private set
        private var cleanupFailed = false
        @Volatile private var active = false

        fun requireStart() {
            val now = SystemClock.elapsedRealtime()
            check(stoppingAt == null && now >= issued && now - issued < START_BUDGET) { "screen_service_start_expired" }
            request.requireCurrent()
            consent.requireVisibleStart(request)
        }

        fun claim(service: PhoneScreenCaptureService) {
            check(this.service == null)
            requireStart()
            this.service = service
        }

        fun capture(service: PhoneScreenCaptureService) {
            check(this.service === service && projection == null && output == null)
            requireStart()
            check(service.foregroundServiceType == ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
            openingOutput = true
            val target = try { openOutput().also { output = it } }
            catch (error: PhoneScreenOutputCleanupException) { cleanupFailed = true; throw error }
            finally { openingOutput = false }
            // If the adapter reentered stop during construction, retire its late output.
            if (stoppingAt != null) {
                cleanup { target.requestStop() }
                error("screen_service_stopping")
            }
            val run = PhoneScreenProjection(service, request, consent, ::stop)
            projection = run
            run.start(target.surface, width, height, density)
            check(stoppingAt == null) { "screen_service_stopping" }
            active = true
        }

        fun requireActive() {
            check(active) { "screen_service_projection_inactive" }
            request.requireCurrent()
            check(active) { "screen_service_projection_inactive" }
        }

        fun stop(cause: Exception? = null) {
            if (cause != null && failure == null) failure = cause
            if (stoppingAt != null) return
            active = false
            stoppingAt = SystemClock.elapsedRealtime()
            request.close() // Close admission before any native close or worker callback.
            val run = projection
            if (run == null) cleanup { consent.close() }
            else cleanup { run.close() }
            cleanup { output?.requestStop() }
        }

        private fun cleanup(action: () -> Unit) {
            try { action() }
            catch (error: Exception) { cleanupFailed = true; if (failure == null) failure = error }
        }

        fun drained(): Boolean {
            if (stoppingAt == null || openingOutput || cleanupFailed || projection?.cleanupError != null) return false
            return try { output?.isDrained() ?: true }
            catch (error: Exception) { cleanupFailed = true; if (failure == null) failure = error; false }
        }

        fun checkOutput() { output?.failure?.let { stop(it) } }

        fun detach(service: PhoneScreenCaptureService) {
            if (this.service === service) this.service = null
        }
    }

    private const val START_BUDGET = 8_000L
    private val handler by lazy { Handler(Looper.getMainLooper()) }
    private var slot: Entry? = null

    fun startJpeg(context: Context, request: PhoneScreenViewRequest, consent: PhoneScreenViewConsent,
        width: Int, height: Int, density: Int, pending: PhoneScreenFrameSlot): PhoneScreenCaptureHandle {
        require(width in 2..1920 && height in 2..1920 && width * height <= 1920 * 1080)
        require(pending.matchesSize(width, height)) { "screen_original_frame_slot_shape" }
        return start(context, request, consent, width, height, density) {
            val output = PhoneScreenJpegOutput.open(width, height, request::requireCurrent, pending::offer)
            object : PhoneScreenOutput by output {
                override fun requestStop() {
                    pending.close()
                    output.requestStop()
                }
            }
        }
    }

    fun start(context: Context, request: PhoneScreenViewRequest, consent: PhoneScreenViewConsent,
        width: Int, height: Int, density: Int, output: () -> PhoneScreenOutput): PhoneScreenCaptureHandle {
        mainThread()
        check(Build.VERSION.SDK_INT >= 29) { "screen_projection_version_unsupported" }
        require(width in 1..4096 && height in 1..4096 && width.toLong() * height <= 4096L * 2160 && density in 1..1000)
        reap()
        check(slot == null) { "screen_service_original_owner_busy" }
        val entry = Entry(request, consent, width, height, density, output)
        entry.requireStart()
        slot = entry
        try {
            checkNotNull(ContextCompat.startForegroundService(context, PhoneScreenCaptureService.startIntent(context, entry.token)))
            handler.postDelayed({ if (slot === entry && entry.service == null && entry.stoppingAt == null) {
                entry.stop(IllegalStateException("screen_service_start_expired")); reap()
            } }, START_BUDGET)
        } catch (error: Exception) {
            entry.stop(error)
            reap()
            throw error
        }
        return object : PhoneScreenCaptureHandle {
            override fun requireActive() = entry.requireActive()
            override fun isDrained(): Boolean {
                mainThread()
                return entry.service == null && entry.drained()
            }
            override fun close() {
                mainThread()
                if (slot === entry) { entry.stop(); reap() }
            }
        }
    }

    fun claim(service: PhoneScreenCaptureService, token: String?): Entry? {
        mainThread()
        val entry = slot?.takeIf { it.service == null && it.token == token && it.stoppingAt == null } ?: return null
        try { entry.claim(service) }
        catch (error: Exception) { entry.stop(error); reap(); throw error }
        return entry
    }

    fun stop(token: String?) {
        mainThread()
        slot?.takeIf { it.token == token }?.stop()
        reap()
    }

    fun detach(entry: Entry, service: PhoneScreenCaptureService) {
        mainThread()
        if (slot === entry && entry.service === service) {
            entry.stop()
            entry.detach(service)
            reap()
        }
    }

    private fun reap() {
        val previous = slot ?: return
        if (previous.service == null && previous.drained() && slot === previous) slot = null
    }

    private fun mainThread() = check(Looper.myLooper() == Looper.getMainLooper()) { "screen_service_main_thread_required" }
}

/** Projection-only service. The Start Intent is insufficient without its live,
 * unclaimed process-local owner; no sticky restart or permission replay. */
class PhoneScreenCaptureService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var entry: PhoneScreenServiceStarts.Entry? = null
    private val poll = object : Runnable {
        override fun run() {
            if (Build.VERSION.SDK_INT < 29) return
            val owner = entry ?: return
            owner.checkOutput()
            val stopping = owner.stoppingAt
            if (stopping != null && (owner.drained() || SystemClock.elapsedRealtime() - stopping >= 12_000)) {
                // A failed/late drain does not allow a replacement owner.
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            } else handler.postDelayed(this, 100)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (Build.VERSION.SDK_INT < 29) { stopSelf(startId); return START_NOT_STICKY }
        if (intent?.action == STOP) {
            PhoneScreenServiceStarts.stop(intent.getStringExtra(TOKEN))
            if (entry == null) stopSelf(startId)
            return START_NOT_STICKY
        }
        if (intent?.action != START || entry != null) {
            if (entry == null) stopSelf(startId)
            return START_NOT_STICKY
        }
        try {
            val owner = PhoneScreenServiceStarts.claim(this, intent.getStringExtra(TOKEN))
            if (owner == null) { stopSelf(startId); return START_NOT_STICKY }
            entry = owner
            startForeground(NOTIFICATION, notification(owner.token), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
            owner.capture(this)
        } catch (error: Exception) {
            val owner = entry
            if (owner == null) { stopSelf(startId); return START_NOT_STICKY }
            owner.stop(error)
            if (foregroundServiceType == ServiceInfo.FOREGROUND_SERVICE_TYPE_NONE) {
                stopSelf(startId)
                return START_NOT_STICKY
            }
        }
        handler.post(poll)
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(poll)
        if (Build.VERSION.SDK_INT >= 29) entry?.let { PhoneScreenServiceStarts.detach(it, this) }
        entry = null
        super.onDestroy()
    }

    private fun notification(token: String): Notification {
        val title = getString(R.string.phone_screen_notification)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, title, NotificationManager.IMPORTANCE_LOW))
        val stop = Intent(this, PhoneScreenCaptureService::class.java).setAction(STOP)
            .setData(Uri.fromParts("magnolie-screen-stop", token, null)).putExtra(TOKEN, token)
        val action = Notification.Action.Builder(null, getString(R.string.phone_screen_stop),
            PendingIntent.getService(this, 0, stop, PendingIntent.FLAG_IMMUTABLE)).build()
        return Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle(title).setOngoing(true).addAction(action).build()
    }

    companion object {
        private const val CHANNEL = "magnolie-phone-screen"
        private const val NOTIFICATION = 24501
        private const val START = "magnolie.screen.START"
        private const val STOP = "magnolie.screen.STOP"
        private const val TOKEN = "screen_original_owner"

        internal fun startIntent(context: Context, token: String): Intent =
            Intent(context, PhoneScreenCaptureService::class.java).setAction(START).putExtra(TOKEN, token)
    }
}
