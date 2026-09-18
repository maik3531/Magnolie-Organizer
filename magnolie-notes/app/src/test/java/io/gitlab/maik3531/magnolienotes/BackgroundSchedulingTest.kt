package io.gitlab.maik3531.magnolienotes

import android.app.AlarmManager
import android.app.Service
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.aufgaben.Wecker
import io.gitlab.maik3531.magnolienotes.daten.*
import io.gitlab.maik3531.magnolienotes.telefon.TelefonDienst
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.time.LocalDate
import java.util.TimeZone
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class BackgroundSchedulingTest {
    private fun fixture(action: (Context, Ablage) -> Unit) {
        val directory = kotlin.io.path.createTempDirectory("background-scheduling-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        try {
            val data = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32), "AES") }
            Ablage::class.java.getDeclaredField("einzig").apply { isAccessible = true }.set(null, data)
            action(context, data)
        } finally { Ablage.singletonFuerTestZuruecksetzen(); directory.deleteRecursively() }
    }

    @Test fun timezoneRescheduleKeepsCivilTimeAndReplacesOldPendingIntent() = fixture { context, data ->
        val before = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("UTC"))
            val task = Aufgabe(id = "civil", faellig = LocalDate.now().plusDays(3).toString(), erinnern = true, erinnerungsMinute = 600)
            data.setzeAufgabe(task)
            Erinnerung.allesNeuStellen(context)
            val alarms = Shadows.shadowOf(context.getSystemService(AlarmManager::class.java))
            val original = alarms.scheduledAlarms.single().triggerAtMs
            TimeZone.setDefault(TimeZone.getTimeZone("GMT+01:00"))
            Wecker().verarbeite(context, Intent(Intent.ACTION_TIMEZONE_CHANGED))
            val rescheduled = alarms.scheduledAlarms.single()
            assertEquals(original - 3_600_000, rescheduled.triggerAtMs)
            assertEquals(Erinnerung.weckzeit(task), rescheduled.triggerAtMs)
            assertEquals(rescheduled.triggerAtMs, Shadows.shadowOf(rescheduled.operation).savedIntent.getLongExtra("weckzeit", -1))
        } finally { TimeZone.setDefault(before) }
    }

    @Test fun doneActionPersistsLocallyWithoutNetworkInsideReceiver() = fixture { context, data ->
        ServerSocket(0).use { server ->
            server.soTimeout = 200
            data.setzeBaum(Baumzustand(kennung = "local", geheim = "fixture", oeffentlich = "fixture",
                partner = listOf(Partner("origin", bestaetigt = true, adresse = "127.0.0.1", port = server.localPort))))
            data.setzeAufgabe(Aufgabe(id = "done", herkunft = "origin", fremdId = "remote"))
            Wecker().verarbeite(context, Intent(Wecker.ERLEDIGT).putExtra("aufgabe", "done"))
            assertTrue(data.aufgabe("done")!!.erledigt)
            assertEquals("stand", data.baum.value.postfach.single().art)
            assertThrows(SocketTimeoutException::class.java) { server.accept() }
        }
    }

    @Test fun repeatedServiceStartsOwnOneStartupJobAndDestroyCancelsIt() {
        val controller = Robolectric.buildService(TelefonDienst::class.java).create()
        val service = controller.get()
        // Keep the real service at its startup barrier, without invoking Keystore or radio.
        Service::class.java.getDeclaredField("mApplication").apply { isAccessible = true }.set(service, MagnolieApp())
        repeat(8) { service.onStartCommand(Intent(), 0, it + 1) }
        val scope = TelefonDienst::class.java.getDeclaredField("scope").apply { isAccessible = true }.get(service) as CoroutineScope
        assertEquals(1, scope.coroutineContext[Job]!!.children.count())
        controller.destroy()
        assertTrue(scope.coroutineContext[Job]!!.isCancelled)
    }
}
