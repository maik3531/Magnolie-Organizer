package io.gitlab.maik3531.magnolienotes

import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.time.Instant
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AbsturzberichteTest {
    private val metadaten = {
        AbsturzMetadaten(
            zeitUtc = "2026-08-28T12:34:56Z",
            appVersion = "1.0.9",
            androidVersion = "15",
            api = 35,
            hersteller = "ExampleMaker",
            modell = "ExampleModel",
        )
    }

    @Test
    fun `Bericht enthaelt nur Crashdaten mit Stack und Ursachenkette`() {
        val ordner = kotlin.io.path.createTempDirectory("magnolie-crash").toFile()
        try {
            val ursache = IllegalArgumentException("root failure")
            val fehler = IllegalStateException("outer failure", ursache)
            AbsturzHandler(ordner, metadaten, null).uncaughtException(Thread("worker-7"), fehler)

            val text = File(ordner, AbsturzHandler.DATEINAME).readText()
            assertTrue(text.contains("UTC timestamp: 2026-08-28T12:34:56Z"))
            assertTrue(text.contains("App version: 1.0.9"))
            assertTrue(text.contains("Android: 15 (API 35)"))
            assertTrue(text.contains("Device: ExampleMaker ExampleModel"))
            assertTrue(text.contains("Thread: worker-7"))
            assertTrue(text.contains("Exception type: java.lang.IllegalStateException"))
            assertTrue(text.contains("Exception message: outer failure"))
            assertTrue(text.contains("Caused by: java.lang.IllegalArgumentException: root failure"))
            assertTrue(text.contains("AbsturzberichteTest"))
            listOf(
                "private note sentinel", "contact sentinel", "sms sentinel",
                "notification sentinel", "settings sentinel", "token sentinel",
                "key sentinel", "payload sentinel", "intent sentinel",
            ).forEach { assertFalse(text.contains(it)) }
        } finally {
            ordner.deleteRecursively()
        }
    }

    @Test
    fun `Berichte sind begrenzt und genau einmal rotiert`() {
        val ordner = kotlin.io.path.createTempDirectory("magnolie-rotation").toFile()
        try {
            val handler = AbsturzHandler(ordner, metadaten, null)
            handler.uncaughtException(Thread("first"), IllegalStateException("first crash"))
            handler.uncaughtException(
                Thread("second"), IllegalStateException("second crash " + "x".repeat(2 * 1024 * 1024)))

            val aktuell = File(ordner, AbsturzHandler.DATEINAME)
            val alt = File(ordner, "${AbsturzHandler.DATEINAME}.old")
            assertEquals(AbsturzHandler.MAXIMALE_BYTES, aktuell.length())
            assertTrue(aktuell.readText().contains("second crash"))
            assertTrue(alt.readText().contains("first crash"))
            assertEquals(setOf(aktuell.name, alt.name), ordner.listFiles().orEmpty().map(File::getName).toSet())
        } finally {
            ordner.deleteRecursively()
        }
    }

    @Test
    fun `Schreibfehler maskiert Crash nicht und delegiert immer`() {
        val basis = kotlin.io.path.createTempDirectory("magnolie-write-failure").toFile()
        val unbrauchbarerOrdner = File(basis, "not-a-directory").apply { writeText("occupied") }
        val aufrufe = AtomicInteger()
        val fehler = IllegalStateException("original")
        val vorher = Thread.UncaughtExceptionHandler { faden, weitergereicht ->
            assertEquals("crashing-thread", faden.name)
            assertSame(fehler, weitergereicht)
            aufrufe.incrementAndGet()
        }
        try {
            AbsturzHandler(unbrauchbarerOrdner, metadaten, vorher)
                .uncaughtException(Thread("crashing-thread"), fehler)
            assertEquals(1, aufrufe.get())
        } finally {
            basis.deleteRecursively()
        }
    }

    @Test
    fun `Installation ist frueh und nicht doppelt`() {
        val quelle = File(
            System.getProperty("user.dir"),
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/MagnolieApp.kt",
        ).readText()
        val attach = quelle.indexOf("override fun attachBaseContext(base: Context)")
        val superAufruf = quelle.indexOf("super.attachBaseContext(base)", attach)
        val installation = quelle.indexOf("Absturzberichte.installieren(this)")
        val onCreate = quelle.indexOf("override fun onCreate()")
        assertTrue(attach >= 0 && superAufruf > attach)
        assertTrue(installation > superAufruf && installation < onCreate)
        assertFalse(quelle.substring(onCreate).contains("Absturzberichte.installieren"))

        val vorher = Thread.getDefaultUncaughtExceptionHandler()
        try {
            Absturzberichte.installieren(ApplicationProvider.getApplicationContext())
            val einmal = Thread.getDefaultUncaughtExceptionHandler()
            Absturzberichte.installieren(ApplicationProvider.getApplicationContext())
            assertTrue(einmal is AbsturzHandler)
            assertSame(einmal, Thread.getDefaultUncaughtExceptionHandler())
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(vorher)
        }
    }

    @Test
    fun `Zeitformat ist UTC`() {
        assertEquals("Z", Instant.parse(metadaten().zeitUtc).toString().takeLast(1))
    }
}
