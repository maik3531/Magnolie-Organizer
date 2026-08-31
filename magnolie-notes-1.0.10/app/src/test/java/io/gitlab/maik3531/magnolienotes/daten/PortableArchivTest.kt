package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class PortableArchivTest {
    private val passwort = "correct horse battery staple".toCharArray()
    private val bestand = Bestand(
        notizen = listOf(Notiz("n1", "Geheimer Titel", "Sehr geheimer Inhalt",
            baumFreigabe = Freigabe("share", listOf("tree-device")), baumQuelle = "tree-device")),
        notizbuecher = listOf(Notizbuch("b1", "Privat")),
        aufgaben = listOf(Aufgabe("a1", "Wichtig", herkunft = "tree-device", fremdId = "remote")),
        papierkorb = listOf(PapierkorbEintrag("p1", "note", "Alt", 1,
            notiz = Notiz("n2", "Papierkorb", "Inhalt", baumQuelle = "tree-device"))),
        personalSync = PersonalSyncState(actor_id = "private-device-id"),
    )

    @Test fun `round trip enthaelt nur portablen Bestand`() {
        val geprueft = PortableArchiv.pruefen(PortableArchiv.erstellen(bestand, passwort), passwort)
        val restored = Ablage.json.decodeFromString<Bestand>(geprueft.bestandJson)
        assertEquals("Geheimer Titel", restored.notizen.single().titel)
        assertNull(restored.notizen.single().baumFreigabe)
        assertEquals("", restored.notizen.single().baumQuelle)
        assertEquals("", restored.aufgaben.single().herkunft)
        assertEquals(PersonalSyncState(), restored.personalSync)
        assertEquals(1, geprueft.vorschau.papierkorb)
    }

    @Test fun `falsches Passwort und manipulierte Nutzlast werden abgelehnt`() {
        val archiv = PortableArchiv.erstellen(bestand, passwort)
        assertThrows(AEADBadTagException::class.java) {
            PortableArchiv.pruefen(archiv, "wrong".toCharArray())
        }
        archiv[archiv.lastIndex] = (archiv.last().toInt() xor 1).toByte()
        assertThrows(AEADBadTagException::class.java) { PortableArchiv.pruefen(archiv, passwort) }
    }

    @Test fun `Header Manipulation Trunkierung und Parametergrenzen werden abgelehnt`() {
        val original = PortableArchiv.erstellen(bestand, passwort)
        listOf(16 to 2, 17 to 2, 18 to 2, 19 to 15, 24 to 13).forEach { (offset, value) ->
            val defekt = original.copyOf().also { it[offset] = value.toByte() }
            assertThrows(IllegalArgumentException::class.java) { PortableArchiv.pruefen(defekt, passwort) }
        }
        val iterationen = original.copyOf().also { it[23] = (it[23].toInt() xor 1).toByte() }
        assertThrows(IllegalArgumentException::class.java) { PortableArchiv.pruefen(iterationen, passwort) }
        listOf(33, 49).forEach { offset ->
            val authentifizierterKopf = original.copyOf().also {
                it[offset] = (it[offset].toInt() xor 1).toByte()
            }
            assertThrows(AEADBadTagException::class.java) {
                PortableArchiv.pruefen(authentifizierterKopf, passwort)
            }
        }
        assertThrows(IllegalArgumentException::class.java) {
            PortableArchiv.pruefen(original.copyOf(original.size - 1), passwort)
        }
        assertThrows(IllegalArgumentException::class.java) {
            PortableArchiv.pruefen(ByteArray((PortableArchiv.MAX_ARCHIV_BYTES + 1).toInt()), passwort)
        }
    }

    @Test fun `jedes Archiv hat frisches Salz und Nonce und verraet keinen Klartext`() {
        val eins = PortableArchiv.erstellen(bestand, passwort)
        val zwei = PortableArchiv.erstellen(bestand, passwort)
        assertFalse(eins.contentEquals(zwei))
        assertFalse(eins.copyOfRange(33, 61).contentEquals(zwei.copyOfRange(33, 61)))
        val roh = eins.toString(Charsets.ISO_8859_1)
        listOf("Geheimer Titel", "Sehr geheimer Inhalt", "private-device-id", "tree-device",
            "baumFreigabe", "geheim").forEach { assertFalse(it, roh.contains(it)) }
    }

    @Test fun `Restore behaelt Baumidentitaet und erzeugt neue Sync Epoch`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.filesDir.listFiles().orEmpty().forEach { it.deleteRecursively() }
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val ablage = Ablage.fuerTest(context) { key }
        val baum = Baumzustand(kennung = "dieses-geraet", geheim = "privater-baumschluessel",
            oeffentlich = "public", syncEpoch = "alte-epoch")
        ablage.setzeBaum(baum)
        val geprueft = PortableArchiv.pruefen(PortableArchiv.erstellen(bestand, passwort), passwort)
        assertTrue(ablage.portableWiederherstellen(geprueft.bestandJson, "portable-test"))
        assertEquals("dieses-geraet", ablage.baum.value.kennung)
        assertEquals("privater-baumschluessel", ablage.baum.value.geheim)
        assertNotEquals("alte-epoch", ablage.baum.value.syncEpoch)
        assertTrue(ablage.baum.value.additiveBaselineAusstehend)
        assertEquals("Geheimer Titel", ablage.bestand.value.notizen.single().titel)
    }
}
