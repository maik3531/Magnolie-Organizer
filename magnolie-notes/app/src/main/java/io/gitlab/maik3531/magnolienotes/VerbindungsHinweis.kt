package io.gitlab.maik3531.magnolienotes

import android.app.Notification
import android.app.NotificationManager
import android.app.Service
import android.content.pm.ServiceInfo
import android.os.Build

/** Ein sichtbarer Hinweis, aber ein vollständiger Vordergrundnachweis je Dienst. */
internal object VerbindungsHinweis {
    enum class Quelle { BAUM, TELEFON }
    private data class Eintrag(val quelle: Quelle, val hinweis: Notification)
    private val dienste = linkedMapOf<Service, Eintrag>()
    private const val ID = 8741

    @Synchronized
    fun aktualisieren(dienst: Service, quelle: Quelle, hinweis: Notification) {
        dienste[dienst] = Eintrag(quelle, hinweis)
        anzeigen()
    }

    @Synchronized
    fun entfernen(dienst: Service) {
        if (dienste.remove(dienst) == null) return
        // REMOVE würde auch den gemeinsamen Hinweis des anderen Dienstes löschen.
        // Erst lösen, dann mit den verbliebenen aktiven Besitzern aktualisieren.
        dienst.stopForeground(Service.STOP_FOREGROUND_DETACH)
        if (dienste.isEmpty()) dienst.getSystemService(NotificationManager::class.java)?.cancel(ID)
        else anzeigen()
    }

    private fun anzeigen() {
        // Der konkrete Telefon-Verbindungsstatus ist aussagekräftiger als der
        // allgemeine Listenertext; dessen Takt darf ihn nicht überschreiben.
        val hinweis = dienste.values.maxByOrNull { it.quelle.ordinal }?.hinweis ?: return
        for (dienst in dienste.keys) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
                dienst.startForeground(ID, hinweis, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
            else dienst.startForeground(ID, hinweis)
        }
    }
}
