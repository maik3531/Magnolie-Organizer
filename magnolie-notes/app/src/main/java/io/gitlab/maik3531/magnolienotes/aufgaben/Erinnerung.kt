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
import io.gitlab.maik3531.magnolienotes.CustomNavigation
import io.gitlab.maik3531.magnolienotes.MagnolieApp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.PersonalCustom
import kotlinx.serialization.json.*
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters

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
    internal const val AKTION = "io.gitlab.maik3531.magnolienotes.ERINNERUNG"
    internal const val CUSTOM = "io.gitlab.maik3531.magnolienotes.CUSTOM_ERINNERUNG"
    private const val FELD_ID = "aufgabe"

    /** Stellt alle Wecker neu. Alte Wecker derselben Aufgabe werden ersetzt. */
    fun allesNeuStellen(zusammenhang: Context) {
        customNeuStellen(zusammenhang)
        val ablage = Ablage.hole(zusammenhang)
        val wecker = zusammenhang.getSystemService(AlarmManager::class.java) ?: return
        kanalAnlegen(zusammenhang)
        val jetzt = System.currentTimeMillis()
        for (aufgabe in ablage.aufgaben()) {
            val absicht = absichtFuer(zusammenhang, aufgabe.id, weckzeit(aufgabe))
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
        val absicht = absichtFuer(zusammenhang, aufgabe.id, weckzeit(aufgabe))
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

    private fun customAbsicht(context: Context, id: String, ms: Long = -1): PendingIntent =
        PendingIntent.getBroadcast(context, 0, Intent(context, Wecker::class.java).apply {
            action = CUSTOM; data = android.net.Uri.parse("magnolie://custom/$id")
            putExtra("aufgabe", id); putExtra("weckzeit", ms)
        }, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun customAbbestellen(context: Context, ids: Collection<String>) {
        val manager = context.getSystemService(AlarmManager::class.java)
        val notifications = context.getSystemService(NotificationManager::class.java)
        for (id in ids) {
            manager?.cancel(customAbsicht(context, id, -1))
            notifications?.cancel(id, 0)
        }
    }

    fun customNeuStellen(context: Context) = synchronized(Ablage.SCHREIBSPERRE) {
        val state = Ablage.hole(context).bestand.value.personalCustom
        val manager = context.getSystemService(AlarmManager::class.java) ?: return@synchronized
        val notifications = context.getSystemService(NotificationManager::class.java)
        for ((id, item) in state.items) {
            val next = PersonalCustom.nextAlarm(state, item, System.currentTimeMillis())
            val intent = customAbsicht(context, id, next ?: -1)
            if (next == null) {
                manager.cancel(intent)
                if (!PersonalCustom.remindersAllowed(state, item)) notifications?.cancel(id, 0)
            }
            else stellen(manager, next, intent)
        }
    }

    fun customMelden(context: Context, id: String, expected: Long) = synchronized(Ablage.SCHREIBSPERRE) {
        val ablage = Ablage.hole(context)
        val state = ablage.bestand.value.personalCustom
        val item = state.items[id] ?: return@synchronized
        if (expected < 0 || expected > System.currentTimeMillis() ||
            PersonalCustom.nextAlarm(state, item, expected - 1) != expected) return@synchronized
        ablage.personalCustomChange { it.copy(items = it.items + (id to item.copy(firedMs = expected))) }
        kanalAnlegen(context)
        val value = item.record.getValue("value").jsonObject
        val text = listOf("module_title", "date", "time", "note").map { value.getValue(it).jsonPrimitive.content }
            .filter { it.isNotEmpty() }.joinToString("\n")
        val open = PendingIntent.getActivity(context, 0, CustomNavigation.absicht(context, state, id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notice = Notification.Builder(context, KANAL).setSmallIcon(R.drawable.ic_aufgabe)
            .setSubText(context.getString(R.string.personal_custom_title))
            .setContentTitle(value.getValue("title").jsonPrimitive.content.ifBlank { context.getString(R.string.personal_custom_title) })
            .setContentText(text).setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open).setAutoCancel(true).setCategory(Notification.CATEGORY_REMINDER).build()
        context.getSystemService(NotificationManager::class.java)?.notify(id, 0, notice)
        customNeuStellen(context)
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

    private fun absichtFuer(zusammenhang: Context, aufgabeId: String, zeit: Long? = null): PendingIntent {
        val absicht = Intent(zusammenhang, Wecker::class.java).apply {
            action = AKTION
            // Ohne eigenes Datum hielte Android zwei Aufgaben für dieselbe.
            data = android.net.Uri.parse("magnolie://aufgabe/$aufgabeId")
            putExtra(FELD_ID, aufgabeId)
            zeit?.let { putExtra("weckzeit", it) }
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
        val tage = Kalendertage.bis(faellig) ?: return ""
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
        if (absicht.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED,
                Intent.ACTION_TIMEZONE_CHANGED, Intent.ACTION_TIME_CHANGED,
                 "android.app.action.SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED", ERLEDIGT, Erinnerung.AKTION, Erinnerung.CUSTOM)) return
        val ergebnis = goAsync()
        val handler = android.os.Handler(android.os.Looper.getMainLooper())
        val fertig = java.util.concurrent.atomic.AtomicBoolean()
        val beenden = Runnable { if (fertig.compareAndSet(false, true)) ergebnis.finish() }
        handler.postDelayed(beenden, 8_000)
        try {
            val daten = Data.Builder().putString("action", absicht.action)
                .putString("aufgabe", absicht.getStringExtra("aufgabe"))
                .putLong("weckzeit", absicht.getLongExtra("weckzeit", -1)).build()
            val work = OneTimeWorkRequestBuilder<WeckerWorker>().setInputData(daten).build()
            WorkManager.getInstance(zusammenhang).enqueueUniqueWork(
                "magnolie-reminder-${absicht.action}-${absicht.getStringExtra("aufgabe").orEmpty()}",
                ExistingWorkPolicy.APPEND_OR_REPLACE, work).result.addListener({
                    try { handler.removeCallbacks(beenden) } finally { beenden.run() }
                }, androidx.core.content.ContextCompat.getMainExecutor(zusammenhang))
        } catch (_: Exception) {
            try { handler.removeCallbacks(beenden) } finally { beenden.run() }
        }
    }

    internal fun verarbeite(zusammenhang: Context, absicht: Intent) {
        when (absicht.action) {
            Erinnerung.CUSTOM -> Erinnerung.customMelden(zusammenhang,
                absicht.getStringExtra("aufgabe") ?: return, absicht.getLongExtra("weckzeit", -1))
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_TIMEZONE_CHANGED,
            Intent.ACTION_TIME_CHANGED,
            "android.app.action.SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED",
            "android.intent.action.MY_PACKAGE_REPLACED" -> {
                // Nach einem Neustart sind alle Wecker fort.
                Erinnerung.allesNeuStellen(zusammenhang)
            }

            ERLEDIGT -> {
                val id = absicht.getStringExtra("aufgabe") ?: return
                io.gitlab.maik3531.magnolienotes.baum.Baumwerk.hole(zusammenhang)
                    .aufgabeAbhaken(id, true, sofortSenden = false)
                zusammenhang.getSystemService(NotificationManager::class.java)?.cancel(id.hashCode())
            }

            Erinnerung.AKTION -> {
                val id = absicht.getStringExtra("aufgabe") ?: return
                val aufgabe = Ablage.hole(zusammenhang).aufgabe(id) ?: return
                if (aufgabe.erledigt || !aufgabe.erinnern) return
                val aktuell = Erinnerung.weckzeit(aufgabe) ?: return
                if (aktuell > System.currentTimeMillis() ||
                    absicht.hasExtra("weckzeit") && absicht.getLongExtra("weckzeit", -1) != aktuell) return
                Erinnerung.melden(zusammenhang, aufgabe)
            }
        }
    }

    companion object {
        const val ERLEDIGT = "io.gitlab.maik3531.magnolienotes.AUFGABE_ERLEDIGT"
    }
}

class WeckerWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result = runCatching {
        if (!runBlocking { withTimeout(30_000) { (applicationContext as MagnolieApp).awaitReady() } })
            return Result.retry()
        if (isStopped) return Result.retry()
        val absicht = Intent().setAction(inputData.getString("action"))
            .putExtra("aufgabe", inputData.getString("aufgabe"))
        val zeit = inputData.getLong("weckzeit", -1)
        if (zeit >= 0) absicht.putExtra("weckzeit", zeit)
        Wecker().verarbeite(applicationContext, absicht)
        if (absicht.action == Wecker.ERLEDIGT && !isStopped)
            WorkManager.getInstance(applicationContext).enqueueUniqueWork("magnolie-reminder-outbox",
                ExistingWorkPolicy.KEEP, OneTimeWorkRequestBuilder<ErinnerungsVersandWorker>().build())
        Result.success()
    }.getOrElse { Result.retry() }
}

class ErinnerungsVersandWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result = runCatching {
        if (!runBlocking { withTimeout(30_000) { (applicationContext as MagnolieApp).awaitReady() } } || isStopped)
            return Result.retry()
        val werk = io.gitlab.maik3531.magnolienotes.baum.Baumwerk.hole(applicationContext)
        werk.postfachAbarbeiten(maxSendungen = 4)
        val blockiert = werk.zustand.value.postfach.filter { it.brauchtPruefung }.mapTo(mutableSetOf()) { it.an }
        if (werk.zustand.value.postfach.any { !it.aufgegeben && it.an !in blockiert }) Result.retry() else Result.success()
    }.getOrElse { Result.retry() }
}
