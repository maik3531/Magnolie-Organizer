package io.gitlab.maik3531.magnolienotes

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import io.gitlab.maik3531.magnolienotes.aufgaben.Wecker
import io.gitlab.maik3531.magnolienotes.baum.BaumDienst
import io.gitlab.maik3531.magnolienotes.baum.Baumwerk
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.journal.AndroidJournal
import io.gitlab.maik3531.magnolienotes.journal.JournalIntervall
import io.gitlab.maik3531.magnolienotes.sicherung.AutoSicherungsWorker
import io.gitlab.maik3531.magnolienotes.telefon.*
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID
import java.util.concurrent.TimeUnit

/** Only ValidationTestRunner can select these phases; no telephony or user messages. */
class BackgroundServiceInstrumentationTest {
    private val runner get() = ValidationTestRunner.instance
    private val context get() = runner.targetContext
    private fun ready() {
        check(context.packageName == "io.gitlab.maik3531.magnolienotes.validation")
        check(android.os.Build.HARDWARE in setOf("ranchu", "goldfish"))
        check(runBlocking { withTimeout(30_000) { (context.applicationContext as MagnolieApp).awaitReady() } })
    }
    private fun await(condition: () -> Boolean) {
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
        while (!condition() && System.nanoTime() < until) Thread.sleep(50)
        assertTrue("Timed out", condition())
    }
    @Suppress("DEPRECATION")
    private fun running(type: Class<*>) = context.getSystemService(ActivityManager::class.java).getRunningServices(100)
        .any { it.service.packageName == context.packageName && it.service.className == type.name && it.foreground }

    @Test fun foregroundLifecycleIsIdempotentAndStopsInBackground() {
        ready()
        val storage = TelefonAblage.get(context)
        check(storage.peers().peer == null)
        val work = TelefonWerk.get(context)
        val generation = TelefonWerk::class.java.getDeclaredField("lifecycleGeneration").apply { isAccessible = true }
        runner.runOnMainSync { TelefonDienst.stop(context); BaumDienst.anhalten(context) }
        await { !running(TelefonDienst::class.java) && !running(BaumDienst::class.java) }
        assertFalse(Baumwerk.hole(context).bluetoothStarten())
        val before = generation.getLong(work)
        val activity = runner.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        try {
            runner.runOnMainSync { TelefonDienst.start(context); BaumDienst.starten(context) }
            await { running(TelefonDienst::class.java) && running(BaumDienst::class.java) && work.state.value.enabled }
            assertEquals(before + 1, generation.getLong(work))
            repeat(8) { runner.runOnMainSync { TelefonDienst.start(context); BaumDienst.starten(context) } }
            Thread.sleep(500)
            assertEquals(before + 1, generation.getLong(work))
            runner.runOnMainSync { activity.moveTaskToBack(true) }
            assertTrue(running(TelefonDienst::class.java))
            runner.runOnMainSync { TelefonDienst.stop(context); BaumDienst.anhalten(context) }
            await { !running(TelefonDienst::class.java) && !running(BaumDienst::class.java) && !work.state.value.enabled }
            assertFalse(storage.enabled())
        } finally {
            runner.runOnMainSync { TelefonDienst.stop(context); BaumDienst.anhalten(context); activity.finish() }
        }
    }

    @Test fun journalOffCancelsAndReenableSchedules() {
        ready()
        val journal = AndroidJournal.hole(context)
        val previous = journal.state.value.interval
        val work = WorkManager.getInstance(context)
        try {
            journal.intervalSetzen(JournalIntervall.AUS)
            await { work.getWorkInfosForUniqueWork("magnolie-journal-due").get(5, TimeUnit.SECONDS).all { it.state.isFinished } }
            journal.intervalSetzen(JournalIntervall.WOECHENTLICH)
            await { work.getWorkInfosForUniqueWork("magnolie-journal-due").get(5, TimeUnit.SECONDS).any { !it.state.isFinished } }
        } finally { journal.intervalSetzen(previous) }
    }

    @Test fun doneBroadcastPersistsThroughRealWorkManager() {
        ready()
        val data = Ablage.hole(context)
        val id = "background-fixture-${UUID.randomUUID()}"
        data.setzeAufgabe(Aufgabe(id = id, titel = "Synthetic reminder action"))
        try {
            context.sendBroadcast(Intent(context, Wecker::class.java).setAction(Wecker.ERLEDIGT).putExtra("aufgabe", id))
            await { data.aufgabe(id)?.erledigt == true }
            val work = WorkManager.getInstance(context)
            await { work.getWorkInfosForUniqueWork("magnolie-reminder-${Wecker.ERLEDIGT}-$id").get(5, TimeUnit.SECONDS)
                .any { it.state == WorkInfo.State.SUCCEEDED } }
        } finally {
            data.loescheAufgabe(id)
            data.bestand.value.papierkorb.filter { it.aufgabe?.id == id }.forEach { data.papierkorbEndgueltig(it.id) }
        }
    }

    @Test fun masterOffPurgesEncryptedNotificationQueueAndRejectsCapture() {
        ready()
        val storage = TelefonAblage.get(context)
        check(storage.peers().peer == null && !storage.enabled())
        storage.identity("Synthetic phone").second.fill(0)
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Synthetic desktop", TelefonKrypto.b64(ByteArray(32)))
        val work = TelefonWerk.get(context)
        val queue = TelefonQueue(context, storage)
        val body = JsonObject(mapOf("package" to JsonPrimitive("fixture.synthetic.messages")))
        try {
            storage.savePeer(peer)
            queue.queue(peer.device_id, "selected_notifications_readonly.event", body, 60_000)
            runner.runOnMainSync { TelefonDienst.stop(context) }
            assertFalse(queue.hasKind(peer.device_id, "selected_notifications_readonly.event"))
            work.publish("selected_notifications_readonly.event", body, 60_000)
            assertFalse(queue.hasKind(peer.device_id, "selected_notifications_readonly.event"))
        } finally { queue.deletePeer(peer.device_id); storage.savePeer(null) }
    }

    @Test fun backupWorkerMissingFolderAndGrantFailSafely() {
        ready()
        val prefs = context.getSharedPreferences("automatische_portable_sicherung", Context.MODE_PRIVATE)
        check(!prefs.contains("tree_uri"))
        val work = WorkManager.getInstance(context)
        try {
            for (uri in listOf(null, "content://fixture.invalid/tree/synthetic")) {
                prefs.edit().putBoolean("enabled", true).putString("tree_uri", uri).commit()
                val request = OneTimeWorkRequestBuilder<AutoSicherungsWorker>().build()
                work.enqueue(request).result.get(10, TimeUnit.SECONDS)
                await { work.getWorkInfoById(request.id).get(5, TimeUnit.SECONDS)?.state?.isFinished == true }
                assertEquals(WorkInfo.State.FAILED, work.getWorkInfoById(request.id).get()?.state)
                assertFalse(prefs.getBoolean("enabled", true))
                assertEquals(if (uri == null) "ORDNER_FEHLT" else "FREIGABE_FEHLT", prefs.getString("last_status", ""))
            }
        } finally { prefs.edit().remove("tree_uri").putBoolean("enabled", false).commit() }
    }

    @Test fun disabledServicesStayDisabledAfterProcessRestart() {
        ready()
        Thread.sleep(1000)
        assertFalse(TelefonAblage.get(context).enabled())
        assertFalse(running(TelefonDienst::class.java))
        assertFalse(running(BaumDienst::class.java))
    }
}
