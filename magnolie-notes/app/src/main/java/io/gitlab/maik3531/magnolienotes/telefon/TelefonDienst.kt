package io.gitlab.maik3531.magnolienotes.telefon

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
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import io.gitlab.maik3531.magnolienotes.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext

class TelefonDienst : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var connectivity: ConnectivityManager? = null
    private var werk: TelefonWerk? = null
    private var startJob: Job? = null
    private val wifiListener = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) { TelefonWerk.get(this@TelefonDienst).wifiChanged(true) }
        override fun onLost(network: Network) { TelefonWerk.get(this@TelefonDienst).wifiChanged(hasWifi()) }
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onCreate() {
        super.onCreate(); channel()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            startJob?.cancel()
            TelefonAblage.get(this).setEnabled(false)
            TelefonWerk.get(this).serviceStopped()
            stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return START_NOT_STICKY
        }
        foreground()
        if (startJob?.isActive == true) return START_STICKY
        startJob = scope.launch {
            if (!(application as MagnolieApp).awaitReady()) {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
                return@launch
            }
            TelefonAblage.get(this@TelefonDienst).setEnabled(true)
            val current = TelefonWerk.get(this@TelefonDienst)
            werk = current
            val started = runCatching { withContext(Dispatchers.IO) { current.serviceStarted() } }
            if (started.isFailure) {
                stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return@launch
            }
            listenForWifi()
            launch(Dispatchers.IO) {
                while (isActive) {
                    delay(60_000)
                    runCatching { current.maintenance() }
                }
            }
            current.state.collectLatest { foreground(it) }
        }
        return START_STICKY
    }
    override fun onDestroy() {
        scope.cancel()
        connectivity?.let { runCatching { it.unregisterNetworkCallback(wifiListener) } }
        connectivity = null
        werk?.serviceStopped()
        werk = null
        super.onDestroy()
    }

    private fun listenForWifi() {
        if (connectivity != null) return
        connectivity = getSystemService(ConnectivityManager::class.java)?.also { manager ->
            manager.registerNetworkCallback(NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), wifiListener)
            TelefonWerk.get(this).wifiChanged(hasWifi())
        }
    }

    private fun hasWifi(): Boolean = connectivity?.allNetworks?.any { network ->
        connectivity?.getNetworkCapabilities(network)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
    } == true

    private fun foreground(state: TelefonUiZustand? = null) {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(this, 1, Intent(this, TelefonDienst::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val peer = state?.peer?.display_name.orEmpty()
        val text = when (state?.connection) {
            TelefonVerbindungsstatus.DISCOVERING -> getString(R.string.telefon_dienst_sucht)
            TelefonVerbindungsstatus.HANDSHAKING, TelefonVerbindungsstatus.AUTHENTICATING,
            TelefonVerbindungsstatus.CODE_PENDING -> getString(R.string.telefon_dienst_verbindet,
                state?.pairingName.orEmpty().ifBlank { peer.ifBlank { getString(R.string.telefon_status_gepaart) } })
            TelefonVerbindungsstatus.ONLINE_WIFI -> getString(R.string.telefon_dienst_wlan, peer)
            TelefonVerbindungsstatus.ONLINE_BLUETOOTH -> getString(R.string.telefon_dienst_bluetooth, peer)
            TelefonVerbindungsstatus.ERROR -> getString(R.string.telefon_dienst_fehler)
            else -> getString(R.string.telefon_dienst_laeuft)
        }
        val notification = Notification.Builder(this, CHANNEL).setContentTitle(getString(R.string.telefon_titel))
            .setContentText(text).setSmallIcon(R.drawable.ic_baum).setContentIntent(open)
            .addAction(0, getString(R.string.telefon_trennen), stop).setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        else startForeground(ID, notification)
    }
    private fun channel() {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) == null) manager.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.telefon_dienst_kanal), NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) })
    }
    companion object {
        const val STOP = "io.gitlab.maik3531.magnolienotes.telefon.STOP"
        private const val CHANNEL = "magnolie_phone"
        private const val ID = 8741
        fun start(context: Context) { TelefonAblage.get(context).setEnabled(true); context.startForegroundService(Intent(context, TelefonDienst::class.java)) }
        fun stop(context: Context) {
            TelefonAblage.get(context).setEnabled(false)
            TelefonWerk.get(context).serviceStopped()
            context.stopService(Intent(context, TelefonDienst::class.java))
        }
    }
}
