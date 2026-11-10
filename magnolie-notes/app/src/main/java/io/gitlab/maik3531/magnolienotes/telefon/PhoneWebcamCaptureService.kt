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
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import io.gitlab.maik3531.magnolienotes.R
import java.security.SecureRandom
import java.util.Locale

/** Original one-use in-memory native service handoff. No persisted start record,
 * restored Boolean/Intent grant or second simultaneous Notes capture owner. */
@RequiresApi(30)
internal object PhoneWebcamServiceStarts {
    internal class Entry(val token: String, val run: PhoneWebcamForegroundRun) {
        var service: PhoneWebcamCaptureService? = null
    }
    private val gate = Any()
    private var slot: Entry? = null

    fun start(context: Context, run: PhoneWebcamForegroundRun) {
        check(Looper.myLooper() == Looper.getMainLooper()) { "webcam_foreground_start_thread_required" }
        var entry: Entry? = null
        try {
            run.requireVisibleStart()
            val token = ByteArray(32).also { SecureRandom().nextBytes(it) }
                .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
            val created = Entry(token, run)
            synchronized(gate) {
                val previous = slot
                check(previous == null || previous.service == null && previous.run.isCompletelyStopped()) { "webcam_native_capture_owner_busy" }
                slot = created; entry = created
            }
            ContextCompat.startForegroundService(context, Intent(context, PhoneWebcamCaptureService::class.java)
                .setAction(PhoneWebcamCaptureService.START).putExtra(PhoneWebcamCaptureService.TOKEN, token))
        } catch (error: Throwable) {
            run.abort(error)
            synchronized(gate) { if (entry != null && slot === entry && run.isCompletelyStopped()) slot = null }
            throw error
        }
    }

    fun claim(service: PhoneWebcamCaptureService, token: String?): Entry? {
        val original = synchronized(gate) { slot?.takeIf { it.token == token && it.service == null } } ?: return null
        try { original.run.requireVisibleStart() }
        catch (error: Throwable) {
            original.run.abort(error)
            synchronized(gate) { if (slot === original && original.run.isCompletelyStopped()) slot = null }
            throw error
        }
        synchronized(gate) {
            if (slot !== original || original.service != null) return null
            original.service = service
            return original
        }
    }
    fun stop(token: String?) {
        val original = synchronized(gate) { slot?.takeIf { it.token == token } } ?: return
        original.run.close()
    }
    fun finish(original: Entry, service: PhoneWebcamCaptureService) {
        synchronized(gate) {
            if (slot === original && original.service === service) {
                original.service = null
                if (original.run.isCompletelyStopped()) slot = null
            }
        }
    }
}

/** No automatic boot/start/restart. This component still needs the explicit
 * manifest/control/Activity wiring before it can be used on a phone. */
class PhoneWebcamCaptureService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var original: PhoneWebcamServiceStarts.Entry? = null
    private var stoppingAt: Long? = null
    private var previousText: Int? = null
    private val poll = object : Runnable {
        override fun run() {
            if (Build.VERSION.SDK_INT < 30) return
            val entry = original ?: return
            if (entry.run.isCompletelyStopped()) {
                stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return
            }
            try {
                val text = when {
                    entry.run.isStopping -> R.string.webcam_stoppt
                    entry.run.isCapturePrepared() -> if (entry.run.muted) R.string.webcam_stumm else R.string.webcam_aktiv
                    else -> R.string.webcam_startet
                }
                if (text != previousText) {
                    getSystemService(NotificationManager::class.java).notify(NOTIFICATION, notification(entry, text))
                    previousText = text
                }
            } catch (error: Exception) { entry.run.abort(error) }
            if (entry.run.isStopping) {
                if (stoppingAt == null) stoppingAt = SystemClock.elapsedRealtime()
                if (SystemClock.elapsedRealtime() - stoppingAt!! >= 12_000) {
                    // No unchecked service/poller survives an uncertain SDK
                    // shutdown. The native registry remains held until actual
                    // resources drain; no callback flag releases it by itself.
                    stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return
                }
            }
            handler.postDelayed(this, 100)
        }
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (Build.VERSION.SDK_INT < 30) { stopSelf(startId); return START_NOT_STICKY }
        if (intent?.action == STOP) {
            PhoneWebcamServiceStarts.stop(intent.getStringExtra(TOKEN))
            handler.removeCallbacks(poll); handler.post(poll)
            if (original == null) stopSelf(startId)
            return START_NOT_STICKY
        }
        if (intent?.action != START || original != null) {
            if (original == null) stopSelf(startId)
            return START_NOT_STICKY
        }
        var entry: PhoneWebcamServiceStarts.Entry? = null
        try {
            entry = PhoneWebcamServiceStarts.claim(this, intent.getStringExtra(TOKEN))
            if (entry == null) { stopSelf(startId); return START_NOT_STICKY }
            original = entry
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.webcam_kanal), NotificationManager.IMPORTANCE_LOW))
            val type = ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or if (entry.run.muted) 0 else ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            startForeground(NOTIFICATION, notification(entry, R.string.webcam_startet), type)
            previousText = R.string.webcam_startet
            entry.run.start(this)
        } catch (error: Exception) {
            entry?.run?.abort(error)
            if (original == null) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(startId) }
        }
        handler.removeCallbacks(poll); handler.post(poll)
        return START_NOT_STICKY
    }

    @RequiresApi(30)
    private fun notification(entry: PhoneWebcamServiceStarts.Entry, text: Int): Notification {
        val stop = Intent(this, PhoneWebcamCaptureService::class.java).setAction(STOP)
            .setData(Uri.parse("magnolie-internal://webcam-stop/" + entry.token)).putExtra(TOKEN, entry.token)
        val action = PendingIntent.getService(this, 0, stop, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle(getString(R.string.webcam_kanal)).setContentText(getString(text))
            .setCategory(Notification.CATEGORY_SERVICE).setOngoing(true).setOnlyAlertOnce(true)
            .addAction(Notification.Action.Builder(null, getString(R.string.webcam_beenden), action).build()).build()
    }
    override fun onDestroy() {
        handler.removeCallbacks(poll)
        if (Build.VERSION.SDK_INT >= 30) original?.let {
            it.run.close(); PhoneWebcamServiceStarts.finish(it, this)
        }
        original = null
        super.onDestroy()
    }
    companion object {
        internal const val START = "io.gitlab.maik3531.magnolienotes.webcam.START"
        internal const val STOP = "io.gitlab.maik3531.magnolienotes.webcam.STOP"
        internal const val TOKEN = "webcam_original_native_token"
        private const val CHANNEL = "magnolie-webcam"
        private const val NOTIFICATION = 24401
    }
}
