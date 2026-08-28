package io.gitlab.maik3531.magnolienotes.baum

import android.content.ContentProviderOperation
import android.content.ContentValues
import android.provider.ContactsContract.CommonDataKinds.Note
import android.provider.ContactsContract.CommonDataKinds.Photo
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import io.gitlab.maik3531.magnolienotes.journal.KontaktRohstand
import io.gitlab.maik3531.magnolienotes.journal.KontaktZeile
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AndroidKontakteRestoreTest {
    private val alt = KontaktDaten(vorname = "Alt")
    private val aktuell = AndroidKontakt("lookup", 42, alt)

    private fun stand(rows: List<KontaktZeile> = listOf(KontaktZeile(Note.CONTENT_ITEM_TYPE,
        data = listOf("Notiz")))) = KontaktRohstand(rawContactId = 42, rows = rows,
        beforeHash = KontaktSync.hash(alt))

    private fun restore(
        snapshot: KontaktRohstand = stand(),
        lesen: () -> AndroidKontakt? = { aktuell },
        anwenden: (ArrayList<ContentProviderOperation>) -> Unit
    ) = AndroidKontakte.wiederherstellenMitGrenzen(snapshot, false, lesen, anwenden)

    private fun wert(op: ContentProviderOperation, feld: String, name: String): Any? {
        val inhalt = operationsfeld(op, feld)
        return when (inhalt) {
            is ContentValues -> inhalt.get(name)
            is Map<*, *> -> inhalt[name]
            else -> error("Unbekannter Operationsinhalt")
        }
    }

    private fun operationsfeld(op: ContentProviderOperation, feld: String): Any? =
        ContentProviderOperation::class.java.getDeclaredField(feld).run {
            isAccessible = true
            get(op)
        }

    @Test fun `vorhandener Kontakt wird in genau einem Batch ersetzt`() {
        var aufrufe = 0
        restore { ops ->
            aufrufe++
            assertEquals(2, ops.size)
            assertEquals(Data.CONTENT_URI, ops[0].uri)
            assertEquals(42L, (wert(ops[1], "mValues", Data.RAW_CONTACT_ID) as Number).toLong())
        }
        assertEquals(1, aufrufe)
    }

    @Test fun `fehlender Kontakt und seine Daten entstehen in demselben Batch`() {
        lateinit var batch: ArrayList<ContentProviderOperation>
        val ergebnis = restore(lesen = { null }) { batch = it }
        assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT, ergebnis)
        assertEquals(2, batch.size)
        assertEquals(RawContacts.CONTENT_URI, batch[0].uri)
        assertEquals(Data.CONTENT_URI, batch[1].uri)
    }

    @Test fun `Foto wird vor dem Batch validiert und als Blob geschrieben`() {
        val foto = byteArrayOf(1, 2, 3, 4)
        val snapshot = stand(listOf(KontaktZeile(Photo.CONTENT_ITEM_TYPE,
            data = List(14) { null } + android.util.Base64.encodeToString(foto, android.util.Base64.NO_WRAP))))
        restore(snapshot) { ops -> assertArrayEquals(foto, wert(ops[1], "mValues", "data15") as ByteArray) }
    }

    @Test fun `Lesefehler mutiert nichts`() {
        var batch = false
        val ergebnis = restore(lesen = { error("Lesefehler") }) { batch = true }
        assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, ergebnis)
        assertFalse(batch)
    }

    @Test fun `Hashkonflikt mutiert nichts`() {
        var batch = false
        val geaendert = aktuell.copy(daten = KontaktDaten(vorname = "Geaendert"))
        val ergebnis = restore(lesen = { geaendert }) { batch = true }
        assertEquals(AndroidKontakte.RestoreErgebnis.KONFLIKT, ergebnis)
        assertFalse(batch)
    }

    @Test fun `Batchfehler wird als nicht schreibbar gemeldet`() {
        val ergebnis = restore { throw IllegalStateException("Providerfehler") }
        assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, ergebnis)
    }

    @Test fun `Fehler an jeder bestehenden Batchoperation lassen den alten Zustand stehen`() {
        val snapshot = stand((1..3).map { KontaktZeile(Note.CONTENT_ITEM_TYPE, data = listOf("N$it")) })
        repeat(4) { fehlerIndex ->
            val speicher = mutableListOf("alt-a", "alt-b")
            val vorher = speicher.toList()
            val ergebnis = restore(snapshot) { ops ->
                val transaktion = speicher.toMutableList()
                ops.forEachIndexed { index, _ ->
                    if (index == fehlerIndex) error("Operation $index")
                    if (index == 0) transaktion.clear() else transaktion += "neu-$index"
                }
                speicher.clear(); speicher += transaktion
            }
            assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, ergebnis)
            assertEquals(vorher, speicher)
        }
    }

    @Test fun `Fehler an jeder neuen Batchoperation hinterlassen keinen Teilkontakt`() {
        val snapshot = stand((1..2).map { KontaktZeile(Note.CONTENT_ITEM_TYPE, data = listOf("N$it")) })
        repeat(3) { fehlerIndex ->
            var kontaktVorhanden = false
            val ergebnis = restore(snapshot, lesen = { null }) { ops ->
                var transaktion = kontaktVorhanden
                ops.forEachIndexed { index, _ ->
                    if (index == fehlerIndex) error("Operation $index")
                    if (index == 0) transaktion = true
                }
                kontaktVorhanden = transaktion
            }
            assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, ergebnis)
            assertFalse(kontaktVorhanden)
        }
    }

    @Test fun `zu viele Operationen werden vor dem Provider abgewiesen`() {
        val rows = List(AndroidKontakte.MAX_RESTORE_OPERATIONEN) { KontaktZeile(Note.CONTENT_ITEM_TYPE) }
        var batch = false
        val ergebnis = restore(stand(rows)) { batch = true }
        assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, ergebnis)
        assertFalse(batch)
    }

    @Test fun `zu grosse Nutzlast wird vor dem Provider abgewiesen`() {
        val riesig = "x".repeat(AndroidKontakte.MAX_RESTORE_NUTZLAST)
        var batch = false
        val ergebnis = restore(stand(listOf(KontaktZeile(Note.CONTENT_ITEM_TYPE, data = listOf(riesig))))) {
            batch = true
        }
        assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, ergebnis)
        assertFalse(batch)
    }

    @Test fun `ungueltige Zeilen werden vor dem Provider abgewiesen`() {
        val invalid = listOf(
            KontaktZeile(""),
            KontaktZeile(Note.CONTENT_ITEM_TYPE, data = List(16) { "x" }),
            KontaktZeile(Note.CONTENT_ITEM_TYPE, sync = List(5) { "x" }),
            KontaktZeile(Photo.CONTENT_ITEM_TYPE, data = List(14) { null } + "kein base64!")
        )
        invalid.forEach { row ->
            var batch = false
            assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR,
                restore(stand(listOf(row))) { batch = true })
            assertFalse(batch)
        }
    }
}
