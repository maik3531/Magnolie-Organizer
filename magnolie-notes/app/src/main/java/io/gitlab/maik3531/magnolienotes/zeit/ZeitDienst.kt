package io.gitlab.maik3531.magnolienotes.zeit

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.location.LocationManager
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
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.merge
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException

/** Visible user-initiated tracking, without treating it as a connected-device service. */
class ZeitDienst : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var job: Job? = null
    private var foregroundType: Int? = null
    private val scanEvents = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    private val scanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action in setOf(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION,
                    WifiManager.WIFI_STATE_CHANGED_ACTION, LocationManager.MODE_CHANGED_ACTION)) scanEvents.tryEmit(Unit)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        androidx.core.content.ContextCompat.registerReceiver(this, scanReceiver,
            IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION).apply {
                addAction(WifiManager.WIFI_STATE_CHANGED_ACTION); addAction(LocationManager.MODE_CHANGED_ACTION)
            }, androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) manager.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.zeit_titel), NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false); setSound(null, null)
            })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (job?.isActive == true) { scanEvents.tryEmit(Unit); return START_STICKY }
        val initialMonitor = intent?.getBooleanExtra(MONITOR, false) == true && ZeitWlanScan.ready(this)
        foreground(notification(this, null, Zeiteintrag.currentMinute(), waitingForWifi = initialMonitor), initialMonitor)
        job = scope.launch {
            if (!(application as MagnolieApp).awaitReady()) { finish(); return@launch }
            val data = Ablage.hole(this@ZeitDienst).bestand.map { it.zeiterfassung }.distinctUntilChanged()
            val ticks = flow {
                while (true) { emit(Zeiteintrag.currentMinute()); delay(60000 - System.currentTimeMillis() % 60000) }
            }
            val clock = merge(ticks, scanEvents.map { Zeiteintrag.currentMinute() })
            combine(data, clock) { state, now -> state to now }.collect { (state, now) ->
                val active = state.entries.filter { !it.deleted && it.endMinute == null }.maxByOrNull { it.startMinute }
                val requested = state.enabled && state.wifi.enabled
                val monitor = requested && ZeitWlanScan.permissionGranted(this@ZeitDienst) &&
                    (ZeitWlanScan.locationEnabled(this@ZeitDienst) ||
                        ((foregroundType ?: 0) and ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION) != 0)
                if (active == null && !requested) {
                    withContext(Dispatchers.IO) { ZeitWecker.neuStellen(this@ZeitDienst) }
                    finish()
                } else {
                    val scanningAllowed = foreground(notification(this@ZeitDienst, active?.let { state.projected(it, now) }, now,
                        active?.let { state.isPaused(it, now) } == true, waitingForWifi = active == null), monitor)
                    withContext(Dispatchers.IO) {
                        try {
                            ZeitWecker.neuStellen(this@ZeitDienst)
                            if (scanningAllowed && active == null) observeWifi()
                        } catch (error: IOException) {
                            android.util.Log.w("ZeitDienst", "Pause state could not be saved; retry on next tick", error)
                        }
                    }
                }
            }
        }
        return START_STICKY
    }

    private fun foreground(notification: Notification, monitor: Boolean = false): Boolean {
        val base = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        val type = base or (if (monitor) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0)
        try {
            if (foregroundType == type) getSystemService(NotificationManager::class.java).notify(ID, notification)
            else if (Build.VERSION.SDK_INT >= 29) startForeground(ID, notification, type)
            else startForeground(ID, notification)
            foregroundType = type
            return monitor
        } catch (error: SecurityException) {
            if (!monitor) throw error
            // A while-in-use permission may have been revoked between the check and start.
            if (Build.VERSION.SDK_INT >= 29) startForeground(ID, notification, base)
            else startForeground(ID, notification)
            foregroundType = base
            return false
        }
    }

    private fun observeWifi() {
        val storage = Ablage.hole(this)
        val state = storage.bestand.value.zeiterfassung
        val now = System.currentTimeMillis()
        if (!state.enabled || !state.wifi.enabled || now < state.wifi.blockedUntilMs) return
        val observation = ZeitWlanScan.observations(this, now).firstOrNull { it.ssid == state.wifi.ssid }
        if (observation != null) {
            val hour = java.time.Instant.ofEpochMilli(now).atZone(java.time.ZoneId.systemDefault()).hour
            val activity = getString(when (Zeiteintrag.suggestedType(hour)) {
                "early" -> R.string.zeit_frueh
                "late" -> R.string.zeit_spaet
                else -> R.string.zeit_nacht
            })
            storage.aendereZeiterfassung { it.startFromWifi(observation.ssid, observation.observedMs, now, activity) }
        }
        if (storage.bestand.value.zeiterfassung.entries.none { !it.deleted && it.endMinute == null }) ZeitWlanScan.request(this)
    }

    private fun finish() { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf() }

    override fun onDestroy() { unregisterReceiver(scanReceiver); scope.cancel(); super.onDestroy() }

    companion object {
        const val CHANNEL = "magnolie_time_tracking"
        const val ID = 8742
        private const val MONITOR = "wifi_monitor"

        fun refresh(context: Context, state: ZeiterfassungStand) {
            val requested = state.enabled && state.wifi.enabled
            val intent = Intent(context, ZeitDienst::class.java).putExtra(MONITOR, requested && ZeitWlanScan.ready(context))
            if (state.entries.any { !it.deleted && it.endMinute == null } || requested) context.startForegroundService(intent)
            else context.stopService(intent)
        }

        internal fun notification(context: Context, entry: Zeiteintrag?, nowMinute: Long,
                                  paused: Boolean = entry?.pauseMinute != null, waitingForWifi: Boolean = false): Notification {
            val open = PendingIntent.getActivity(context, ID, Intent(context, MainActivity::class.java)
                .putExtra(MainActivity.ZEIGE_ZEITERFASSUNG, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val state = context.getString(if (waitingForWifi) R.string.zeit_wlan_warten
                else if (paused) R.string.zeit_pause_aktiv else R.string.zeit_laufend)
            val text = listOf(entry?.type.orEmpty(), state, entry?.let {
                Zeiteintrag.duration(it.totalMinutes(nowMinute), context.resources.configuration.locales[0])
            }.orEmpty()).filter { it.isNotEmpty() }.joinToString(" · ")
            return Notification.Builder(context, CHANNEL).setSmallIcon(if (waitingForWifi) R.drawable.ic_zeit_wlan else R.drawable.ic_zeiterfassung)
                .apply { if (Build.VERSION.SDK_INT >= 31) setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE) }
                .setContentTitle(context.getString(R.string.zeit_titel)).setContentText(text)
                .setContentIntent(open).setOnlyAlertOnce(true).setOngoing(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE).setCategory(Notification.CATEGORY_SERVICE).build()
        }
    }
}
