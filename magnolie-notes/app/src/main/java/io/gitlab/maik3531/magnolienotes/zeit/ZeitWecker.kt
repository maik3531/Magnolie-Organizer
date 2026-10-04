package io.gitlab.maik3531.magnolienotes.zeit

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.aufgaben.Wecker
import io.gitlab.maik3531.magnolienotes.daten.Ablage

/** Reuses the existing alarm receiver/worker and exact-alarm permission fallback. */
object ZeitWecker {
    const val AKTION = "io.gitlab.maik3531.magnolienotes.ZEIT_PAUSE"
    const val CHANNEL = "magnolie_time_alarms"

    private fun absicht(context: Context, id: String = "", expected: Long = -1): PendingIntent =
        PendingIntent.getBroadcast(context, 0, Intent(context, Wecker::class.java).apply {
            action = AKTION
            data = Uri.parse("magnolie://time/pause-alarm")
            putExtra("aufgabe", id)
            putExtra("weckzeit", expected)
        }, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun neuStellen(context: Context, now: Long = System.currentTimeMillis(), storage: Ablage = Ablage.hole(context)) = synchronized(Ablage.SCHREIBSPERRE) {
        val manager = context.getSystemService(AlarmManager::class.java) ?: return@synchronized
        val before = storage.bestand.value.zeiterfassung
        val state = if (before.evaluatePauses(now / 60000) == before) before
            else storage.aendereZeiterfassung { it.evaluatePauses(now / 60000) }
        val next = state.pauseRuns.mapNotNull { (id, run) -> run.alarm?.warningMs()?.let { id to it } }
            .minByOrNull { it.second }
        if (next == null) manager.cancel(absicht(context))
        else Erinnerung.stellen(manager, maxOf(now, next.second), absicht(context, next.first, next.second))
    }

    fun melden(context: Context, id: String, expected: Long, now: Long = System.currentTimeMillis(),
               storage: Ablage = Ablage.hole(context)) =
        synchronized(Ablage.SCHREIBSPERRE) {
            if (expected < 0 || expected > now) return@synchronized
            var claimed = false
            storage.aendereZeiterfassung { old ->
                val state = old.evaluatePauses(now / 60000)
                val run = state.pauseRuns[id] ?: return@aendereZeiterfassung state
                val alarm = run.alarm ?: return@aendereZeiterfassung state
                if (alarm.warningMs() != expected) return@aendereZeiterfassung state
                val fired = alarm.markSignaled(alarm.minutes!!, now)
                if (fired == alarm) return@aendereZeiterfassung state
                claimed = true
                state.copy(pauseRuns = state.pauseRuns + (id to run.copy(alarm = fired)))
            }
            // The atomic encrypted save above must succeed before any audible notification.
            if (claimed) {
                val manager = context.getSystemService(NotificationManager::class.java)
                if (manager.getNotificationChannel(CHANNEL) == null) manager.createNotificationChannel(
                    NotificationChannel(CHANNEL, context.getString(R.string.zeit_titel), NotificationManager.IMPORTANCE_HIGH))
                val open = PendingIntent.getActivity(context, ZeitDienst.ID,
                    Intent(context, MainActivity::class.java).putExtra(MainActivity.ZEIGE_ZEITERFASSUNG, true)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
                manager.notify("time-pause-$id", 0, Notification.Builder(context, CHANNEL)
                    .setSmallIcon(R.drawable.ic_zeiterfassung)
                    .setContentTitle(context.getString(R.string.zeit_titel))
                    .setContentText(context.getString(R.string.zeit_pause_wecksignal))
                    .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true)
                    .setVisibility(Notification.VISIBILITY_PRIVATE).setCategory(Notification.CATEGORY_ALARM).build())
            }
            neuStellen(context, now, storage)
        }
}
