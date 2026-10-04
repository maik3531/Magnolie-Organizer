package io.gitlab.maik3531.magnolienotes.zeit

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException

/** Visible user-initiated tracking, without treating it as a connected-device service. */
class ZeitDienst : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) manager.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.zeit_titel), NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false); setSound(null, null)
            })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (job?.isActive == true) return START_STICKY
        foreground(notification(this, null, Zeiteintrag.currentMinute()))
        job = scope.launch {
            if (!(application as MagnolieApp).awaitReady()) { finish(); return@launch }
            val data = Ablage.hole(this@ZeitDienst).bestand.map { it.zeiterfassung }.distinctUntilChanged()
            val clock = flow {
                while (true) { emit(Zeiteintrag.currentMinute()); delay(60000 - System.currentTimeMillis() % 60000) }
            }
            combine(data, clock) { state, now -> state to now }.collect { (state, now) ->
                val active = state.entries.filter { !it.deleted && it.endMinute == null }.maxByOrNull { it.startMinute }
                if (active == null) {
                    withContext(Dispatchers.IO) { ZeitWecker.neuStellen(this@ZeitDienst) }
                    finish()
                } else {
                    foreground(notification(this@ZeitDienst, state.projected(active, now), now, state.isPaused(active, now)))
                    withContext(Dispatchers.IO) {
                        try {
                            ZeitWecker.neuStellen(this@ZeitDienst)
                        } catch (error: IOException) {
                            android.util.Log.w("ZeitDienst", "Pause state could not be saved; retry on next tick", error)
                        }
                    }
                }
            }
        }
        return START_STICKY
    }

    private fun foreground(notification: Notification) {
        if (Build.VERSION.SDK_INT >= 34) startForeground(ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(ID, notification)
    }

    private fun finish() { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf() }

    override fun onDestroy() { scope.cancel(); super.onDestroy() }

    companion object {
        const val CHANNEL = "magnolie_time_tracking"
        const val ID = 8742

        fun refresh(context: Context, state: ZeiterfassungStand) {
            val intent = Intent(context, ZeitDienst::class.java)
            if (state.entries.any { !it.deleted && it.endMinute == null }) context.startForegroundService(intent)
            else context.stopService(intent)
        }

        internal fun notification(context: Context, entry: Zeiteintrag?, nowMinute: Long,
                                  paused: Boolean = entry?.pauseMinute != null): Notification {
            val open = PendingIntent.getActivity(context, ID, Intent(context, MainActivity::class.java)
                .putExtra(MainActivity.ZEIGE_ZEITERFASSUNG, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val state = context.getString(if (paused) R.string.zeit_pause_aktiv else R.string.zeit_laufend)
            val text = listOf(entry?.type.orEmpty(), state, entry?.let {
                Zeiteintrag.duration(it.totalMinutes(nowMinute), context.resources.configuration.locales[0])
            }.orEmpty()).filter { it.isNotEmpty() }.joinToString(" · ")
            return Notification.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_zeiterfassung)
                .apply { if (Build.VERSION.SDK_INT >= 31) setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE) }
                .setContentTitle(context.getString(R.string.zeit_titel)).setContentText(text)
                .setContentIntent(open).setOnlyAlertOnce(true).setOngoing(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE).setCategory(Notification.CATEGORY_SERVICE).build()
        }
    }
}
