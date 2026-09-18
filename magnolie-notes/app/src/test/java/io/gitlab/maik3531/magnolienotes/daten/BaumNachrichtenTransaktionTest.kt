package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.nio.file.Files
import java.util.UUID
import javax.crypto.KeyGenerator

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class BaumNachrichtenTransaktionTest {
    @Test fun ioFailureRequiresRecoveryBeforeAnyFurtherCommit() {
        for (restore in listOf(false, true)) for (step in PaarCommitSchritt.entries) {
            val dir = Files.createTempDirectory("commit-io-").toFile()
            try {
                val context = testContext(dir)
                val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
                Ablage.fuerTest(context) { key }.setzeBaum(Baumzustand(
                    partner = listOf(Partner("peer", bestaetigt = true))))
                val store = Ablage.fuerTest(context, { key }) { if (it == step) throw java.io.IOException("synthetic") }
                org.junit.Assert.assertThrows(java.io.IOException::class.java) {
                    if (restore) store.journalWiederherstellen(
                        Ablage.json.encodeToString(Bestand.serializer(), Bestand(notizen = listOf(Notiz(id = "restored", titel = "snapshot")))),
                        Ablage.json.encodeToString(Baumzustand.serializer(), store.baum.value), "io-restore")
                    else verarbeite(store, 7, null)
                }
                org.junit.Assert.assertThrows(StartFehler::class.java) { store.sichereNotiz(Notiz(id = "later", titel = "must not acknowledge")) }
                org.junit.Assert.assertThrows(StartFehler::class.java) { store.aendereBaum { it.copy(name = "later") } }
                org.junit.Assert.assertThrows(StartFehler::class.java) { verarbeite(store, 8, null) }
                org.junit.Assert.assertThrows(StartFehler::class.java) { store.portableWiederherstellen("{}", "later") }
                val restarted = Ablage.fuerTest(context) { key }
                val committed = step >= PaarCommitSchritt.ABSICHT_DAUERHAFT
                assertEquals(committed, if (restore) restarted.notiz("restored") != null else restarted.aufgaben().isNotEmpty())
                restarted.sichereNotiz(Notiz(id = "after-recovery", titel = "kept"))
                assertTrue(Ablage.fuerTest(context) { key }.notiz("after-recovery") != null)
            } finally { dir.deleteRecursively() }
        }
    }

    private class Prozessabbruch : Error()

    @Test fun `legacy mutation und zaehler bleiben an jeder crashgrenze gemeinsam`() {
        pruefeJedeGrenze(zaehler = 7L, transportId = null)
    }

    @Test fun `fs1 mutation und transport id bleiben an jeder crashgrenze gemeinsam`() {
        pruefeJedeGrenze(zaehler = null, transportId = "transport-7")
    }

    private fun pruefeJedeGrenze(zaehler: Long?, transportId: String?) {
        PaarCommitSchritt.entries.forEach { grenze ->
            val ordner = Files.createTempDirectory("baum-nachricht-").toFile()
            try {
                val context = testContext(ordner)
                val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
                Ablage.fuerTest(context) { key }.setzeBaum(Baumzustand(
                    partner = listOf(Partner("peer", bestaetigt = true, vertraut = true))))

                val mitAbbruch = Ablage.fuerTest(context, { key }) {
                    if (it == grenze) throw Prozessabbruch()
                }
                try {
                    verarbeite(mitAbbruch, zaehler, transportId)
                } catch (_: Prozessabbruch) {
                    // Simulierter Prozessabbruch: der nächste Ablage-Start muss allein reparieren.
                }

                val neuGestartet = Ablage.fuerTest(context) { key }
                val partner = neuGestartet.baum.value.partner.single()
                val markiert = if (zaehler != null) partner.zaehlerRein == zaehler
                    else transportId in partner.gesehen
                assertEquals("Gemischter Zustand nach $grenze", markiert,
                    neuGestartet.aufgaben().isNotEmpty())

                val erneutVerarbeitet = verarbeite(neuGestartet, zaehler, transportId)
                assertEquals(!markiert, erneutVerarbeitet)
                assertEquals(1, neuGestartet.aufgaben().size)
                val fertig = neuGestartet.baum.value.partner.single()
                if (zaehler != null) assertEquals(zaehler, fertig.zaehlerRein)
                else assertTrue(transportId in fertig.gesehen)
                assertFalse(verarbeite(neuGestartet, zaehler, transportId))
                assertEquals(1, neuGestartet.aufgaben().size)
            } finally {
                ordner.deleteRecursively()
            }
        }
    }

    private fun verarbeite(ablage: Ablage, zaehler: Long?, transportId: String?): Boolean =
        ablage.verarbeiteBaumNachricht("peer", zaehler, transportId) {
            ablage.setzeAufgabe(Aufgabe(id = UUID.randomUUID().toString(), titel = "genau einmal"))
        }

    private fun testContext(ordner: File): Context {
        val base: Context = ApplicationProvider.getApplicationContext()
        return object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = ordner
        }
    }
}
