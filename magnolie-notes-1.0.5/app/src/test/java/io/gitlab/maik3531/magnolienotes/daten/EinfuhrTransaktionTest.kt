package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import kotlinx.serialization.decodeFromString
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class EinfuhrTransaktionTest {
    @Test fun `Import normalisiert einmalig und alle Leser sehen denselben Stand`() {
        val ordner = Files.createTempDirectory("einfuhr-transaktion-").toFile()
        try {
            val context = object : ContextWrapper(ApplicationProvider.getApplicationContext()) {
                override fun getFilesDir(): File = ordner
                override fun getApplicationContext(): Context = this
            }
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val ablage = Ablage.fuerTest(context) { key }
            val gleich = Ablage.einfuhrSchluessel("Titel", "Text")

            assertEquals(2 to 1, ablage.uebernehmenMitNotizbuechern(listOf(
                Notiz("eins", "Titel", "Text", einfuhrSchluessel = gleich) to "  Projekt  ",
                Notiz("doppelt", "Titel", "Text", einfuhrSchluessel = gleich) to "Projekt",
                Notiz("zwei", "Andere", "Mehr") to "Projekt"
            )))

            val live = ablage.bestand.value
            assertEquals(1, live.notizbuecher.count { it.name == "Projekt" })
            assertEquals(2, live.notizen.size)
            assertEquals(live, Ablage.json.decodeFromString<Bestand>(ablage.journalNutzlast().first))
            assertEquals(live, Ablage.fuerTest(context) { key }.bestand.value)
        } finally {
            ordner.deleteRecursively()
        }
    }
}
