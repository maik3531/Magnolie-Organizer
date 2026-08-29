package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class KontaktPruefungTest {
    @Test fun `Loeschvertrag ist exakt und streng validiert`() {
        val l = KontaktLoeschung("f1", 2, "handy", 123)
        val json = KontaktPruefung.loeschInhalt(l)
        assertEquals(setOf("art", "fassung", "freigabeId", "version", "quelle", "geaendert"), json.keys)
        assertEquals(l, KontaktPruefung.liesLoeschung(json))
        assertNull(KontaktPruefung.liesLoeschung(buildJsonObject {
            json.forEach { (k, v) -> put(k, v) }; put("version", JsonPrimitive(0))
        }))
        assertNull(KontaktPruefung.liesLoeschung(buildJsonObject {
            json.forEach { (k, v) -> put(k, v) }; put("extra", JsonPrimitive(true))
        }))
    }

    @Test fun `leerer halber oder fehlerhafter Snapshot erzeugt keine Loeschung`() {
        val spuren = (1L..20L).map { KontaktSpur(rawContactId = it, freigabeId = "f$it", partner = "p") }
        assertTrue(KontaktPruefung.fehlendeSpuren(spuren, emptySet(), true).isEmpty())
        assertTrue(KontaktPruefung.fehlendeSpuren(spuren, (1L..20L).toSet(), false).isEmpty())
        assertTrue(KontaktPruefung.fehlendeSpuren(spuren, (1L..9L).toSet(), true).isEmpty())
    }

    @Test fun `Loeschvorschlaege sind auf zehn und zehn Prozent begrenzt`() {
        val hundert = (1L..100L).map { KontaktSpur(rawContactId = it, freigabeId = "f$it", partner = "p") }
        assertEquals(10, KontaktPruefung.fehlendeSpuren(hundert, (11L..100L).toSet(), true).size)
        val fuenfzehn = hundert.take(15)
        assertEquals(1, KontaktPruefung.fehlendeSpuren(fuenfzehn, (2L..15L).toSet(), true).size)
    }

    @Test fun `Dubletten brauchen eindeutiges starkes Merkmal`() {
        fun k(id: Long, mail: String = "", telefon: String = "", vor: String = "", firma: String = "") =
            AndroidKontakt("l$id", id, KontaktDaten(vorname = vor, firma = firma,
                telefone = if (telefon.isBlank()) emptyList() else listOf(KontaktWert("", telefon)),
                emailEintraege = if (mail.isBlank()) emptyList() else listOf(KontaktWert("", mail))))
        val kontakte = listOf(k(1, mail = "A@x.de"), k(2, mail = "a@x.de"),
            k(3, telefon = "+49 123"), k(4, telefon = "0049-123"),
            k(5, vor = "Ada", firma = "Engine"), k(6, vor = "Ada", firma = "Engine"),
            k(7, vor = "Ada"))
        val paare = KontaktPruefung.dubletten(kontakte).map { setOf(it.erste.rawContactId, it.zweite.rawContactId) }
        assertTrue(setOf(1L, 2L) in paare)
        assertTrue(setOf(3L, 4L) in paare)
        assertTrue(setOf(5L, 6L) in paare)
        assertFalse(paare.any { 7L in it })
    }

    @Test fun `Revision einer Loeschung ist idempotent`() {
        val n = KontaktNachricht("f", 2, "q", 1, KontaktDaten())
        assertFalse(KontaktSync.istNeu(n, 2, "q"))
        assertTrue(KontaktSync.istNeu(n.copy(version = 3), 2, "q"))
    }
}
