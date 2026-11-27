package io.gitlab.maik3531.magnolienotes

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File
import java.util.Base64
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = MagnolieApp::class)
class AnhangOeffnenTest {
    private val app = ApplicationProvider.getApplicationContext<MagnolieApp>()
    private val cache = File(app.cacheDir, "anhaenge")
    private val bytes = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
    private val anhang = Anhang("open-test", "image.png", "image",
        "data:image/png;base64,${Base64.getEncoder().encodeToString(bytes)}")

    @Before fun providerEinrichten() {
        // Attach the real provider to each test's isolated cache before FileProvider resolves a path.
        val authority = app.packageName + ".dateien"
        checkNotNull(app.contentResolver.acquireContentProviderClient(authority)).close()
    }

    private class StartProbe(
        base: Context,
        private val providerFehlt: Boolean = false,
        private val activityFehlt: Boolean = false
    ) : ContextWrapper(base) {
        var cacheThread: Thread? = null
        val starts = mutableListOf<Intent>()

        override fun getCacheDir(): File {
            if (cacheThread == null) cacheThread = Thread.currentThread()
            return super.getCacheDir()
        }

        override fun getPackageName(): String =
            if (providerFehlt) "io.gitlab.maik3531.missing-provider" else super.getPackageName()

        override fun startActivity(intent: Intent) {
            assertSame(Looper.getMainLooper(), Looper.myLooper())
            starts += intent
            if (activityFehlt) throw ActivityNotFoundException()
        }
    }

    private fun oeffnen(context: Context): Boolean {
        val antwort = CompletableFuture<Boolean>()
        val auftrag = CoroutineScope(Dispatchers.Main.immediate).launch {
            try {
                antwort.complete(AnhangDatei.oeffnen(context, anhang))
            } catch (fehler: Throwable) {
                antwort.completeExceptionally(fehler)
            }
        }
        try {
            val ende = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
            while (!antwort.isDone && System.nanoTime() < ende) {
                shadowOf(Looper.getMainLooper()).idle()
                Thread.sleep(2)
            }
            return antwort.get(100, TimeUnit.MILLISECONDS)
        } finally {
            auftrag.cancel()
        }
    }

    @Test fun `Cache laeuft im Hintergrund und die Activity erhaelt nur Lesezugriff`() {
        val probe = StartProbe(app)
        assertTrue(oeffnen(probe))
        val intent = probe.starts.single()
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals("image/png", intent.type)
        assertEquals("content", intent.data?.scheme)
        assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK, intent.flags)
        app.startZustandFuerInstrumentation(StartZustand.Bereit)
        assertArrayEquals(bytes, app.contentResolver.openInputStream(intent.data!!)!!.use { it.readBytes() })
        assertNotNull(probe.cacheThread)
        assertTrue(probe.cacheThread !== Looper.getMainLooper().thread)
    }

    @Test fun `blockierter Cache liefert false und kann erneut geoeffnet werden`() {
        assertTrue(cache.createNewFile())
        val probe = StartProbe(app)
        assertFalse(oeffnen(probe))
        assertTrue(probe.starts.isEmpty())
        assertTrue(cache.isFile)
        assertTrue(cache.delete())
        assertTrue(oeffnen(probe))
        assertEquals(1, probe.starts.size)
    }

    @Test fun `Schreibfehler erzeugt weder Freigabe noch temporaere Datei`() {
        assertTrue(cache.mkdir())
        try {
            assumeTrue(cache.setWritable(false, true) && !cache.canWrite())
            val probe = StartProbe(app)
            assertFalse(oeffnen(probe))
            assertTrue(probe.starts.isEmpty())
            assertEquals(emptyList<String>(), cache.list()!!.toList())
        } finally {
            cache.setWritable(true, true)
        }
    }

    @Test fun `fehlgeschlagenes Umbenennen belaesst bestehende Daten und entfernt die eigene Tempdatei`() {
        val ziel = File(cache, "opentest.png")
        assertTrue(ziel.mkdirs())
        val bestand = File(ziel, "existing")
        bestand.writeText("Bestand")
        val probe = StartProbe(app)
        assertFalse(oeffnen(probe))
        assertTrue(probe.starts.isEmpty())
        assertEquals("Bestand", bestand.readText())
        assertEquals(listOf(ziel.name), cache.list()!!.toList())
    }

    @Test fun `Provider und Activity Fehler gehen als false zurueck`() {
        val ohneProvider = StartProbe(app, providerFehlt = true)
        assertFalse(oeffnen(ohneProvider))
        assertTrue(ohneProvider.starts.isEmpty())
        val ohneActivity = StartProbe(app, activityFehlt = true)
        assertFalse(oeffnen(ohneActivity))
        assertEquals(1, ohneActivity.starts.size)
        assertTrue(oeffnen(StartProbe(app)))
    }
}
