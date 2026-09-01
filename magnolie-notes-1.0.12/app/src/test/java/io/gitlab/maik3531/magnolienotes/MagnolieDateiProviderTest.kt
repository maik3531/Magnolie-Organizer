package io.gitlab.maik3531.magnolienotes

import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.StartFehlerArt
import java.io.File
import java.io.FileNotFoundException
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
@Config(application = MagnolieApp::class)
class MagnolieDateiProviderTest {
    private lateinit var app: MagnolieApp
    private lateinit var bericht: File

    @Before
    fun vorbereiten() {
        app = ApplicationProvider.getApplicationContext()
        app.startZustandFuerInstrumentation(StartZustand.Fehler(StartFehlerArt.EINGABE_AUSGABE))
        bericht = File(app.filesDir, "diagnostics/${AbsturzHandler.DATEINAME}")
        bericht.parentFile?.mkdirs()
        bericht.writeText("recoverable crash report")
    }

    @After
    fun aufraeumen() {
        if (::bericht.isInitialized) bericht.parentFile?.deleteRecursively()
    }

    @Test
    fun `Crashbericht bleibt im Recovery Zustand nur lesbar`() {
        val uri = Uri.Builder().scheme("content").authority(app.packageName + ".dateien")
            .appendPath("diagnose").appendPath(AbsturzHandler.DATEINAME).build()
        assertTrue(app.startZustand.value is StartZustand.Fehler)
        assertTrue(MagnolieDateiProvider.diagnoseLesezugriff(
            uri, "r", app.packageName + ".dateien"))
        assertEquals("recoverable crash report", bericht.readText())

        erwarteNichtGefunden { MagnolieDateiProvider.diagnoseLesezugriff(
            uri, "w", app.packageName + ".dateien") }
        erwarteNichtGefunden { MagnolieDateiProvider.diagnoseLesezugriff(
            uri, "rw", app.packageName + ".dateien") }
    }

    @Test
    fun `Diagnosepfad erlaubt weder andere Dateien noch Traversal`() {
        val authority = app.packageName + ".dateien"
        val andere = Uri.Builder().scheme("content").authority(authority)
            .appendPath("diagnose").appendPath("other.txt").build()
        val traversal = Uri.parse("content://$authority/diagnose/%2E%2E/notizen.json")
        erwarteNichtGefunden { MagnolieDateiProvider.diagnoseLesezugriff(andere, "r", authority) }
        erwarteNichtGefunden { MagnolieDateiProvider.diagnoseLesezugriff(traversal, "r", authority) }
    }

    private fun erwarteNichtGefunden(aktion: () -> Unit) {
        try {
            aktion()
            fail("FileNotFoundException erwartet")
        } catch (_: FileNotFoundException) {
        }
    }
}
