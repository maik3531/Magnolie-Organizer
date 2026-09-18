package io.gitlab.maik3531.magnolienotes.baum

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.IBinder
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.journal.AndroidJournal
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job

/**
 * Hält den Empfangsdienst am Leben, solange er eingeschaltet ist, und stößt
 * alle 30 Sekunden das Postfach an – derselbe Takt wie die Outboxwartung des
 * Organizers. Ein sichtbarer Hinweis in der Leiste macht klar, dass das Handy
 * gerade zuhört.
 */
class BaumDienst : Service() {

    private val takt = Executors.newSingleThreadScheduledExecutor()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var taktGestartet = false
    private var startJob: Job? = null
    private var bluetoothAnfordern = false

    override fun onBind(absicht: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        kanalAnlegen()
    }

    override fun onStartCommand(absicht: Intent?, flaggen: Int, kennung: Int): Int {
        if (absicht?.action == ANHALTEN) {
            startJob?.cancel()
            beenden()
            return START_NOT_STICKY
        }
        vordergrund()
        bluetoothAnfordern = bluetoothAnfordern || absicht?.getBooleanExtra("bluetooth", false) == true
        if (taktGestartet) {
            val werk = Baumwerk.hole(this)
            if (!werk.zustand.value.dienstAn && !werk.dienstStarten(this)) {
                beenden(); return START_NOT_STICKY
            }
            if (bluetoothAnfordern) {
                bluetoothAnfordern = false
                scope.launch(Dispatchers.IO) { runCatching { Baumwerk.hole(this@BaumDienst).bluetoothStarten() } }
            }
            return START_STICKY
        }
        if (startJob?.isActive == true) return START_STICKY
        startJob = scope.launch {
            if (!(application as MagnolieApp).awaitReady()) {
                beenden()
                return@launch
            }
            val werk = Baumwerk.hole(this@BaumDienst)
            runCatching { AndroidJournal.hole(this@BaumDienst).faelligSichern() }
            if (!werk.dienstStarten(this@BaumDienst)) { beenden(); return@launch }
            if (bluetoothAnfordern) {
                bluetoothAnfordern = false
                runCatching { werk.bluetoothStarten() }
            }
            if (!taktGestartet) {
                taktGestartet = true
                takt.scheduleWithFixedDelay({
                    runCatching {
                        werk.postfachAbarbeiten()
                        werk.automatischSynchronisierenWennFaellig(istAktivesWlan())
                    }
                }, 2, 30, TimeUnit.SECONDS)
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        takt.shutdownNow()
        if ((application as MagnolieApp).startZustand.value == io.gitlab.maik3531.magnolienotes.StartZustand.Bereit) {
            Baumwerk.hole(this).dienstAnhalten()
        }
        super.onDestroy()
    }

    private fun beenden() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun vordergrund() {
        val oeffnen = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val hinweis = Notification.Builder(this, KANAL)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.baum_dienst_laeuft))
            .setSmallIcon(R.drawable.ic_baum)
            .setContentIntent(oeffnen)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(HINWEIS_ID, hinweis, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(HINWEIS_ID, hinweis)
        }
    }

    private fun kanalAnlegen() {
        val verwalter = getSystemService(NotificationManager::class.java) ?: return
        if (verwalter.getNotificationChannel(KANAL) != null) return
        verwalter.createNotificationChannel(
            NotificationChannel(
                KANAL, getString(R.string.baum_dienst_kanal), NotificationManager.IMPORTANCE_LOW
            ).apply { setShowBadge(false) }
        )
    }

    private fun istAktivesWlan(): Boolean {
        val verwalter = getSystemService(ConnectivityManager::class.java) ?: return false
        val netz = verwalter.activeNetwork ?: return false
        val eigenschaften = verwalter.getNetworkCapabilities(netz) ?: return false
        return eigenschaften.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }

    companion object {
        private const val KANAL = "magnolienbaum"
        private const val HINWEIS_ID = 8737
        const val ANHALTEN = "io.gitlab.maik3531.magnolienotes.ANHALTEN"

        fun starten(zusammenhang: Context, bluetooth: Boolean = false) {
            val absicht = Intent(zusammenhang, BaumDienst::class.java).putExtra("bluetooth", bluetooth)
            zusammenhang.startForegroundService(absicht)
        }

        fun anhalten(zusammenhang: Context) {
            val absicht = Intent(zusammenhang, BaumDienst::class.java).setAction(ANHALTEN)
            runCatching { zusammenhang.startService(absicht) }
            zusammenhang.stopService(Intent(zusammenhang, BaumDienst::class.java))
        }
    }
}
