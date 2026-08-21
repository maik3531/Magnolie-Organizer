package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.content.ContextWrapper
import android.content.res.Resources
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Partner
import java.io.File
import java.nio.file.Files
import javax.crypto.KeyGenerator
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class TerminCapabilityTest {
    @Test fun `vertrauter Termin bleibt im Eingang und wird negativ beantwortet`() = mitWerk(vertraut = true) { werk, ablage ->
        val fehler = assertThrows(BaumFehler::class.java) {
            werk.verarbeiteNachricht("peer", termin(), transportId = "termin-vertraut")
        }

        assertTrue(fehler.message.orEmpty().contains("noch nicht unterstützt"))
        assertEquals("termin", ablage.baum.value.eingang.single().art)
        assertTrue("termin-vertraut" in ablage.baum.value.partner.single().gesehen)
    }

    @Test fun `manuell angenommener Termin bleibt mit lokalisiertem Status im Eingang`() = mitWerk(vertraut = false) { werk, ablage ->
        assertThrows(BaumFehler::class.java) {
            werk.verarbeiteNachricht("peer", termin(), transportId = "termin-manuell")
        }
        val id = ablage.baum.value.eingang.single().id

        werk.eingangAnnehmen(id)

        assertEquals(id, ablage.baum.value.eingang.single().id)
        assertTrue(werk.meldungen.value.last().contains("noch nicht unterstützt"))
    }

    private fun termin() = buildJsonObject {
        put("art", JsonPrimitive("termin"))
        put("id", JsonPrimitive("t1"))
        put("titel", JsonPrimitive("Nicht verlieren"))
    }

    private fun mitWerk(vertraut: Boolean, pruefung: (Baumwerk, Ablage) -> Unit) {
        val ordner = Files.createTempDirectory("termin-capability-").toFile()
        try {
            val context = testContext(ordner)
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val ablage = Ablage.fuerTest(context) { key }
            ablage.setzeBaum(Baumzustand(partner = listOf(
                Partner("peer", name = "Desktop", bestaetigt = true, vertraut = vertraut)
            )))
            pruefung(Baumwerk.fuerTest(ablage, context), ablage)
        } finally {
            ordner.deleteRecursively()
        }
    }

    private fun testContext(ordner: File): Context {
        val base: Context = ApplicationProvider.getApplicationContext()
        val resources = object : Resources(base.assets, base.resources.displayMetrics, base.resources.configuration) {
            override fun getText(id: Int): CharSequence = when (id) {
                R.string.baum_meldung_angebot -> "Ein Angebot wartet im Eingang."
                R.string.baum_termin_nicht_unterstuetzt ->
                    "Termine aus dem Magnolienbaum werden auf diesem Gerät noch nicht unterstützt."
                else -> super.getText(id)
            }
        }
        return object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = ordner
            override fun getResources(): Resources = resources
        }
    }
}
