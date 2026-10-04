package io.gitlab.maik3531.magnolienotes.daten

import android.app.AlarmManager
import android.app.Application
import android.app.NotificationManager
import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.MainActivity
import io.gitlab.maik3531.magnolienotes.zeit.ZeitWecker
import java.io.File
import java.nio.file.Files
import java.time.Instant
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28])
class ZeitWeckerTest {
    private val started = Instant.parse("2026-10-04T11:55:17Z").toEpochMilli()

    private fun fixture(test: (Context, Ablage, () -> Ablage) -> Unit) {
        val directory = Files.createTempDirectory("magnolie-time-alarm-").toFile()
        try {
            val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
                override fun getApplicationContext(): Context = this
                override fun getFilesDir(): File = directory
            }
            val key = SecretKeySpec(ByteArray(32) { 37 }, "AES")
            fun reopen() = Ablage.fuerTest(context) { key }
            val storage = reopen()
            storage.aendereZeiterfassung { it.copy(enabled = true).start(
                Zeiteintrag(startMinute = started / 60000 - 120, zone = "UTC")) }
            storage.aendereZeiterfassung { it.pause(it.entries.single(), started) }
            test(context, storage, ::reopen)
        } finally { directory.deleteRecursively() }
    }

    private fun select(storage: Ablage, minutes: Int?) = storage.aendereZeiterfassung { state ->
        val (id, run) = state.pauseRuns.entries.single()
        state.copy(pauseRuns = mapOf(id to run.copy(alarm = run.alarm!!.select(minutes))))
    }

    @Test fun preciseAlarmSurvivesReopeningAndCannotNotifyTwiceAfterReplay() = fixture { context, storage, reopen ->
        select(storage, 15)
        val target = started + 14 * 60000
        val manager = shadowOf(context.getSystemService(AlarmManager::class.java))
        val notifications = shadowOf(context.getSystemService(NotificationManager::class.java))
        ZeitWecker.neuStellen(context, started + 1000, storage)
        assertEquals(target, manager.scheduledAlarms.single().triggerAtMs)
        val pending = shadowOf(manager.scheduledAlarms.single().operation).savedIntent
        assertEquals(ZeitWecker.AKTION, pending.action)
        assertEquals(target, pending.getLongExtra("weckzeit", -1))
        val id = storage.bestand.value.zeiterfassung.entries.single().id
        val restarted = reopen()
        ZeitWecker.melden(context, id, target, target - 1, restarted)
        assertTrue(notifications.allNotifications.isEmpty())
        ZeitWecker.melden(context, id, target, target, restarted)
        assertEquals(1, notifications.allNotifications.size)
        val open = shadowOf(notifications.allNotifications.single().contentIntent).savedIntent
        assertTrue(open.getBooleanExtra(MainActivity.ZEIGE_ZEITERFASSUNG, false))
        // Remove the delivered notification: replay must not recreate it.
        context.getSystemService(NotificationManager::class.java).cancelAll()
        ZeitWecker.melden(context, id, target, target + 1000, reopen())
        ZeitWecker.neuStellen(context, target + 1000, reopen())
        assertTrue(notifications.allNotifications.isEmpty())
        assertTrue(manager.scheduledAlarms.isEmpty())
    }

    @Test fun lateEnablingKeepsOriginalTargetAndResumeCancelsPendingAlarm() = fixture { context, storage, reopen ->
        select(storage, 5)
        val late = started + 6 * 60000
        ZeitWecker.neuStellen(context, late, storage)
        val manager = shadowOf(context.getSystemService(AlarmManager::class.java))
        val alarm = manager.scheduledAlarms.single()
        assertEquals(late, alarm.triggerAtMs)
        assertEquals(started + 4 * 60000, shadowOf(alarm.operation).savedIntent.getLongExtra("weckzeit", -1))
        val id = storage.bestand.value.zeiterfassung.entries.single().id
        storage.aendereZeiterfassung { it.resume(it.entries.single(), late) }
        ZeitWecker.neuStellen(context, late, reopen())
        assertTrue(manager.scheduledAlarms.isEmpty())
        ZeitWecker.melden(context, id, started + 4 * 60000, late, reopen())
        assertTrue(shadowOf(context.getSystemService(NotificationManager::class.java)).allNotifications.isEmpty())
    }

    @Test fun changingTheTargetRejectsStaleDeliveryAndDisablingCancelsIt() = fixture { context, storage, _ ->
        select(storage, 5)
        ZeitWecker.neuStellen(context, started, storage)
        select(storage, 30)
        ZeitWecker.neuStellen(context, started, storage)
        val id = storage.bestand.value.zeiterfassung.entries.single().id
        ZeitWecker.melden(context, id, started + 4 * 60000, started + 5 * 60000, storage)
        assertTrue(shadowOf(context.getSystemService(NotificationManager::class.java)).allNotifications.isEmpty())
        val manager = shadowOf(context.getSystemService(AlarmManager::class.java))
        assertEquals(started + 29 * 60000, manager.scheduledAlarms.single().triggerAtMs)
        select(storage, null)
        ZeitWecker.neuStellen(context, started, storage)
        assertTrue(manager.scheduledAlarms.isEmpty())
    }

    @Test @Config(sdk = [35]) fun deniedExactAlarmPermissionUsesTheExistingAndroidFallback() = fixture { context, storage, _ ->
        select(storage, 15)
        val manager = shadowOf(context.getSystemService(AlarmManager::class.java))
        org.robolectric.shadows.ShadowAlarmManager.setCanScheduleExactAlarms(false)
        ZeitWecker.neuStellen(context, started, storage)
        assertEquals(started + 14 * 60000, manager.scheduledAlarms.single().triggerAtMs)
        assertNotEquals(org.robolectric.shadows.ShadowAlarmManager.WINDOW_EXACT, manager.scheduledAlarms.single().windowLengthMs)
        select(storage, null)
        ZeitWecker.neuStellen(context, started, storage)
        assertTrue(manager.scheduledAlarms.isEmpty())
    }

    @Test fun endOfWorkAlarmUsesTheSameDurableDeliveryPathAndAutomaticStopCancelsAllTargets() = fixture { context, storage, reopen ->
        storage.aendereZeiterfassung { state -> state.copy(pauseRuns = state.pauseRuns.mapValues { (_, run) ->
            run.copy(endAlarm = ZeitFeierabendwecker(workedMinutes = 150, includePauses = true, autoStop = true))
        }) }
        val entry = storage.bestand.value.zeiterfassung.entries.single()
        val target = (entry.startMinute + 150) * 60000
        ZeitWecker.neuStellen(context, started, storage)
        val alarms = shadowOf(context.getSystemService(AlarmManager::class.java))
        assertEquals(ZeitWecker.FEIERABEND, shadowOf(alarms.scheduledAlarms.single().operation).savedIntent.action)
        assertEquals(target, alarms.scheduledAlarms.single().triggerAtMs)
        ZeitWecker.meldenFeierabend(context, entry.id, target, target, storage)
        assertEquals(target / 60000, reopen().bestand.value.zeiterfassung.entries.single().endMinute)
        assertEquals(target + 60 * 60000, reopen().bestand.value.zeiterfassung.wifi.blockedUntilMs)
        val notifications = context.getSystemService(NotificationManager::class.java)
        assertEquals(1, shadowOf(notifications).allNotifications.size)
        notifications.cancelAll()
        ZeitWecker.meldenFeierabend(context, entry.id, target, target + 1000, reopen())
        assertTrue(shadowOf(notifications).allNotifications.isEmpty())
        assertTrue(alarms.scheduledAlarms.isEmpty())
    }
}
