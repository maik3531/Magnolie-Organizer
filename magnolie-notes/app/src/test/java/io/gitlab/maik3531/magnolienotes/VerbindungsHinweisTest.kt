package io.gitlab.maik3531.magnolienotes

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class VerbindungsHinweisTest {
    class ProbeDienst : Service() { override fun onBind(intent: Intent?): IBinder? = null }

    @Test fun twoForegroundOwnersKeepOneAccurateNotificationThroughEitherStopOrder() {
        val baum = Robolectric.buildService(ProbeDienst::class.java).create()
        val telefon = Robolectric.buildService(ProbeDienst::class.java).create()
        val b = baum.get(); val t = telefon.get()
        val manager = b.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("tree", "Tree", NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel("phone", "Phone", NotificationManager.IMPORTANCE_LOW))
        fun notification(service: Service, channel: String, text: String) = Notification.Builder(service, channel)
            .setSmallIcon(android.R.drawable.stat_notify_sync).setContentText(text)
            .setOngoing(true).setOnlyAlertOnce(true).build()
        fun shown(text: String) {
            val active = manager.activeNotifications.filter { it.id == 8741 }
            assertEquals(1, active.size)
            assertEquals(text, active.single().notification.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
            assertTrue(active.single().notification.flags and Notification.FLAG_FOREGROUND_SERVICE != 0)
        }
        try {
            manager.notify(44, notification(b, "tree", "Unrelated reminder"))
            VerbindungsHinweis.aktualisieren(b, VerbindungsHinweis.Quelle.BAUM, notification(b, "tree", "Listening"))
            shown("Listening")
            VerbindungsHinweis.aktualisieren(t, VerbindungsHinweis.Quelle.TELEFON, notification(t, "phone", "Connected to desktop"))
            shown("Connected to desktop")
            for (service in listOf(b, t)) {
                assertEquals(8741, Shadows.shadowOf(service).lastForegroundNotificationId)
                assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE, service.foregroundServiceType)
                assertFalse(Shadows.shadowOf(service).isForegroundStopped)
            }
            VerbindungsHinweis.aktualisieren(b, VerbindungsHinweis.Quelle.BAUM, notification(b, "tree", "Still listening"))
            shown("Connected to desktop")
            VerbindungsHinweis.aktualisieren(t, VerbindungsHinweis.Quelle.TELEFON, notification(t, "phone", "Waiting for desktop"))
            shown("Waiting for desktop")
            VerbindungsHinweis.entfernen(t)
            shown("Still listening")
            assertTrue(Shadows.shadowOf(t).isForegroundStopped)
            assertFalse(Shadows.shadowOf(b).isForegroundStopped)
            telefon.destroy()
            shown("Still listening")
            VerbindungsHinweis.entfernen(t) // repeated stop cannot remove the other owner
            shown("Still listening")
            val restarted = Robolectric.buildService(ProbeDienst::class.java).create()
            try {
                val r = restarted.get()
                VerbindungsHinweis.aktualisieren(r, VerbindungsHinweis.Quelle.TELEFON, notification(r, "phone", "Reconnected via Bluetooth"))
                shown("Reconnected via Bluetooth")
                VerbindungsHinweis.entfernen(b)
                baum.destroy()
                shown("Reconnected via Bluetooth")
                assertFalse(Shadows.shadowOf(r).isForegroundStopped)
                VerbindungsHinweis.entfernen(r)
                assertFalse(manager.activeNotifications.any { it.id == 8741 })
                assertTrue(manager.activeNotifications.any { it.id == 44 })
            } finally { VerbindungsHinweis.entfernen(restarted.get()); restarted.destroy() }
        } finally {
            VerbindungsHinweis.entfernen(b); VerbindungsHinweis.entfernen(t)
            baum.destroy(); telefon.destroy()
        }
    }
}
