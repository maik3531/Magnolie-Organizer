package io.gitlab.maik3531.magnolienotes.aufgaben

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import kotlinx.coroutines.runBlocking

/**
 * Die Erinnerungen an fällige Aufgaben.
 *
 * Für jede Aufgabe mit Fälligkeit und gesetztem Haken wird ein Wecker
 * gestellt – am Fälligkeitstag zur eingestellten Uhrzeit, gegebenenfalls um
 * den Vorlauf nach vorn gezogen. Die Wecker werden nach jeder Änderung, nach
 * einem Neustart des Geräts und beim Öffnen der App neu gestellt; Android
 * behält sie über den Prozesstod hinaus, aber nicht über einen Neustart.
 */
object Erinnerung {

    const val KANAL = "aufgaben"
    private const val AKTION = "io.gitlab.maik3531.magnolienotes.ERINNERUNG"
    private const val FELD_ID = "aufgabe"

    /** Stellt alle Wecker neu. Alte Wecker derselben Aufgabe werden ersetzt. */
    fun allesNeuStellen(zusammenhang: Context) {
        val ablage = Ablage.hole(zusammenhang)
        val wecker = zusammenhang.getSystemService(AlarmManager::class.java) ?: return
        kanalAnlegen(zusammenhang)
        val jetzt = System.currentTimeMillis()
        for (aufgabe in ablage.aufgaben()) {
            val absicht = absichtFuer(zusammenhang, aufgabe.id)
            val zeitpunkt = weckzeit(aufgabe)
            if (zeitpunkt == null || zeitpunkt <= jetzt) {
                // Nichts (mehr) zu wecken: einen etwaigen alten Wecker abbestellen.
                wecker.cancel(absicht)
                continue
            }
            stellen(wecker, zeitpunkt, absicht)
        }
    }

    /** Stellt oder löscht den Wecker einer einzelnen Aufgabe. */
    fun stellen(zusammenhang: Context, aufgabe: Aufgabe) {
        val wecker = zusammenhang.getSystemService(AlarmManager::class.java) ?: return
        kanalAnlegen(zusammenhang)
        val absicht = absichtFuer(zusammenhang, aufgabe.id)
        val zeitpunkt = weckzeit(aufgabe)
        if (zeitpunkt == null || zeitpunkt <= System.currentTimeMillis()) {
            wecker.cancel(absicht)
            return
        }
        stellen(wecker, zeitpunkt, absicht)
    }

    fun abbestellen(zusammenhang: Context, aufgabeId: String) {
        val wecker = zusammenhang.getSystemService(AlarmManager::class.java) ?: return
        wecker.cancel(absichtFuer(zusammenhang, aufgabeId))
    }

    private fun stellen(wecker: AlarmManager, zeitpunkt: Long, absicht: PendingIntent) {
        // Genau wecken, wo es erlaubt ist; sonst lieber ungenau als gar nicht.
        val genauErlaubt = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            wecker.canScheduleExactAlarms()
        try {
            if (genauErlaubt) {
                wecker.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, zeitpunkt, absicht)
            } else {
                wecker.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, zeitpunkt, absicht)
            }
        } catch (fehler: SecurityException) {
            wecker.set(AlarmManager.RTC_WAKEUP, zeitpunkt, absicht)
        }
    }

    /** Wann geweckt wird, oder null, wenn diese Aufgabe keine Erinnerung will. */
    fun weckzeit(aufgabe: Aufgabe): Long? {
        if (!aufgabe.erinnern || aufgabe.erledigt || aufgabe.faellig.isBlank()) return null
        val tag = try {
            SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).parse(aufgabe.faellig) ?: return null
        } catch (fehler: Exception) {
            return null
        }
        val kalender = Calendar.getInstance().apply {
            time = tag
            add(Calendar.DAY_OF_YEAR, -aufgabe.vorlaufTage.coerceIn(0, 30))
            set(Calendar.HOUR_OF_DAY, aufgabe.erinnerungsMinute / 60)
            set(Calendar.MINUTE, aufgabe.erinnerungsMinute % 60)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        return kalender.timeInMillis
    }

    private fun absichtFuer(zusammenhang: Context, aufgabeId: String): PendingIntent {
        val absicht = Intent(zusammenhang, Wecker::class.java).apply {
            action = AKTION
            // Ohne eigenes Datum hielte Android zwei Aufgaben für dieselbe.
            data = android.net.Uri.parse("magnolie://aufgabe/$aufgabeId")
            putExtra(FELD_ID, aufgabeId)
        }
        return PendingIntent.getBroadcast(
            zusammenhang, aufgabeId.hashCode(), absicht,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
    }

    fun kanalAnlegen(zusammenhang: Context) {
        val verwalter = zusammenhang.getSystemService(NotificationManager::class.java) ?: return
        if (verwalter.getNotificationChannel(KANAL) != null) return
        verwalter.createNotificationChannel(
            NotificationChannel(
                KANAL,
                zusammenhang.getString(R.string.aufgabe_kanal),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = zusammenhang.getString(R.string.aufgabe_kanal_hinweis)
                enableVibration(true)
            }
        )
    }

    /**
     * Zeigt die Erinnerung. Der Grund steht in der Notiz – „Blumen kaufen“
     * allein sagt weniger als „weil Max Mustermann morgen Geburtstag hat“.
     */
    fun melden(zusammenhang: Context, aufgabe: Aufgabe) {
        kanalAnlegen(zusammenhang)
        val verwalter = zusammenhang.getSystemService(NotificationManager::class.java) ?: return
        val oeffnen = PendingIntent.getActivity(
            zusammenhang, aufgabe.id.hashCode(),
            Intent(zusammenhang, MainActivity::class.java).apply {
                putExtra(MainActivity.ZEIGE_AUFGABE, aufgabe.id)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val erledigt = PendingIntent.getBroadcast(
            zusammenhang, ("erledigt-" + aufgabe.id).hashCode(),
            Intent(zusammenhang, Wecker::class.java).apply {
                action = Wecker.ERLEDIGT
                data = android.net.Uri.parse("magnolie://erledigt/${aufgabe.id}")
                putExtra(FELD_ID, aufgabe.id)
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val zeile = beschreibung(zusammenhang, aufgabe)
        val hinweis = Notification.Builder(zusammenhang, KANAL)
            .setSmallIcon(R.drawable.ic_aufgabe)
            .setContentTitle(aufgabe.anzeigeTitel)
            .setContentText(zeile)
            .setStyle(Notification.BigTextStyle().bigText(zeile))
            .setContentIntent(oeffnen)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_REMINDER)
            .addAction(
                Notification.Action.Builder(
                    null, zusammenhang.getString(R.string.aufgabe_erledigt), erledigt
                ).build()
            )
            .build()
        verwalter.notify(aufgabe.id.hashCode(), hinweis)
    }

    /**
     * Meldet, dass ein anderer Zweig eine Aufgabe herübergereicht hat. Ohne
     * diesen Hinweis bliebe eine Aufgabe vom Rechner unbemerkt, bis man die
     * App das nächste Mal öffnet.
     */
    fun neueAufgabeMelden(zusammenhang: Context, aufgabe: Aufgabe, vonZweig: String) {
        if (aufgabe.erledigt) return
        kanalAnlegen(zusammenhang)
        val verwalter = zusammenhang.getSystemService(NotificationManager::class.java) ?: return
        val oeffnen = PendingIntent.getActivity(
            zusammenhang, ("neu-" + aufgabe.id).hashCode(),
            Intent(zusammenhang, MainActivity::class.java).apply {
                putExtra(MainActivity.ZEIGE_AUFGABE, aufgabe.id)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val zeile = beschreibung(zusammenhang, aufgabe)
        val hinweis = Notification.Builder(zusammenhang, KANAL)
            .setSmallIcon(R.drawable.ic_aufgabe)
            .setContentTitle(zusammenhang.getString(R.string.aufgabe_angekommen, vonZweig))
            .setContentText(
                aufgabe.anzeigeTitel + (if (zeile.isBlank()) "" else " · " + zeile)
            )
            .setStyle(
                Notification.BigTextStyle().bigText(
                    aufgabe.anzeigeTitel + (if (zeile.isBlank()) "" else "\n" + zeile)
                )
            )
            .setContentIntent(oeffnen)
            .setAutoCancel(true)
            .build()
        verwalter.notify(("neu-" + aufgabe.id).hashCode(), hinweis)
    }

    /** Die zweite Zeile der Erinnerung: der Grund und wann es soweit ist. */
    fun beschreibung(zusammenhang: Context, aufgabe: Aufgabe): String {
        val teile = mutableListOf<String>()
        if (aufgabe.notiz.isNotBlank()) {
            teile += aufgabe.notiz.lineSequence().filter { it.isNotBlank() }.joinToString(" ")
        }
        val wann = faelligkeitInWorten(zusammenhang, aufgabe.faellig)
        if (wann.isNotBlank()) teile += wann
        return teile.joinToString(" · ")
    }

    /** „heute fällig“, „morgen fällig“ oder das Datum. */
    fun faelligkeitInWorten(zusammenhang: Context, faellig: String): String {
        if (faellig.isBlank()) return ""
        val tag = try {
            SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).parse(faellig) ?: return ""
        } catch (fehler: Exception) {
            return ""
        }
        val ziel = Calendar.getInstance().apply {
            time = tag
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }
        val heute = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }
        val tage = ((ziel.timeInMillis - heute.timeInMillis) / 86_400_000L).toInt()
        return when {
            tage == 0 -> zusammenhang.getString(R.string.aufgabe_heute_faellig)
            tage == 1 -> zusammenhang.getString(R.string.aufgabe_morgen_faellig)
            tage < 0 -> zusammenhang.resources.getQuantityString(
                R.plurals.aufgabe_ueberfaellig, -tage, -tage
            )
            tage <= 7 -> zusammenhang.resources.getQuantityString(
                R.plurals.aufgabe_in_tagen, tage, tage
            )
            else -> zusammenhang.getString(
                R.string.aufgabe_faellig_am,
                java.text.DateFormat.getDateInstance(java.text.DateFormat.MEDIUM).format(tag)
            )
        }
    }
}

/**
 * Nimmt die gestellten Wecker entgegen, meldet die Aufgabe und stellt nach
 * einem Neustart des Geräts alle Wecker wieder her.
 */
class Wecker : BroadcastReceiver() {

    override fun onReceive(zusammenhang: Context, absicht: Intent) {
        val ergebnis = goAsync()
        Thread {
            try {
                if (!runBlocking { (zusammenhang.applicationContext as MagnolieApp).awaitReady() }) return@Thread
                verarbeite(zusammenhang, absicht)
            } finally {
                ergebnis.finish()
            }
        }.start()
    }

    private fun verarbeite(zusammenhang: Context, absicht: Intent) {
        when (absicht.action) {
            Intent.ACTION_BOOT_COMPLETED,
            "android.intent.action.MY_PACKAGE_REPLACED" -> {
                // Nach einem Neustart sind alle Wecker fort.
                Erinnerung.allesNeuStellen(zusammenhang)
            }

            ERLEDIGT -> {
                val id = absicht.getStringExtra("aufgabe") ?: return
                io.gitlab.maik3531.magnolienotes.baum.Baumwerk.hole(zusammenhang)
                    .aufgabeAbhaken(id, true)
                zusammenhang.getSystemService(NotificationManager::class.java)?.cancel(id.hashCode())
            }

            else -> {
                val id = absicht.getStringExtra("aufgabe") ?: return
                val aufgabe = Ablage.hole(zusammenhang).aufgabe(id) ?: return
                if (aufgabe.erledigt) return
                Erinnerung.melden(zusammenhang, aufgabe)
            }
        }
    }

    companion object {
        const val ERLEDIGT = "io.gitlab.maik3531.magnolienotes.AUFGABE_ERLEDIGT"
    }
}
