package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class KontaktSyncTest {
    private val kontakt = KontaktDaten(
        vorname = "Ada", nachname = "Lovelace", firma = "Analytical Engines",
        notiz = "Mathematikerin", geburtstag = "1815-12-10",
        telefone = listOf(KontaktWert("mobil", "+44 123")),
        emailEintraege = listOf(KontaktWert("arbeit", "ADA@example.org")),
        anschriften = listOf(KontaktAnschrift("arbeit", "1 Engine Rd", "12345", "London", "", "UK"))
    )

    @Test fun `Nutzlast entspricht exakt dem Vertrag und enthaelt keine technischen IDs`() {
        val json = KontaktSync.inhalt(KontaktNachricht("f1", 2, "handy", 123, kontakt))
        assertEquals(setOf("art", "fassung", "freigabeId", "version", "quelle", "geaendert", "kontakt"), json.keys)
        assertFalse(json.toString().contains("rawContact"))
        assertFalse(json.toString().contains("lookup"))
        assertFalse(json.toString().contains("foto"))
        assertFalse(json.toString().contains("delete", ignoreCase = true))
        assertEquals(kontakt.copy(emailEintraege = listOf(KontaktWert("arbeit", "ADA@example.org"))),
            KontaktSync.lies(json)!!.kontakt.copy(emailEintraege = kontakt.emailEintraege))
    }

    @Test fun `unbekannte Fassung und ungueltige Revision werden abgelehnt`() {
        val basis = KontaktSync.inhalt(KontaktNachricht("f1", 1, "q", 1, kontakt))
        assertNull(KontaktSync.lies(buildJsonObject { basis.forEach { (k, v) -> put(k, v) }; put("fassung", JsonPrimitive(2)) }))
        assertNull(KontaktSync.lies(buildJsonObject { basis.forEach { (k, v) -> put(k, v) }; put("version", JsonPrimitive(0)) }))
        assertNull(KontaktSync.lies(buildJsonObject { basis.forEach { (k, v) -> put(k, v) }; put("freigabeId", JsonPrimitive("x".repeat(129))) }))
    }

    @Test fun `leere Remote-Werte loeschen nichts und Listen mergen normalisiert additiv`() {
        val lokal = kontakt.copy(telefone = listOf(KontaktWert("mobil", "+49 123")), notiz = "bleibt")
        val fern = KontaktDaten(telefone = listOf(KontaktWert("home", "0049-123"), KontaktWert("work", "+49 999")),
            emailEintraege = listOf(KontaktWert("work", "ada@example.org")))
        val gemischt = KontaktSync.mische(lokal, fern)
        assertEquals("Ada", gemischt.vorname)
        assertEquals("bleibt", gemischt.notiz)
        assertEquals(3, gemischt.telefone.size)
        assertEquals(1, gemischt.emailEintraege.size)
    }

    @Test fun `Revision ist idempotent und Quelle bricht Gleichstand`() {
        assertTrue(KontaktSync.istNeu(KontaktNachricht("f", 3, "a", 0, kontakt), 2, "z"))
        assertTrue(KontaktSync.istNeu(KontaktNachricht("f", 2, "z", 0, kontakt), 2, "a"))
        assertFalse(KontaktSync.istNeu(KontaktNachricht("f", 2, "a", 0, kontakt), 2, "a"))
        assertFalse(KontaktSync.istNeu(KontaktNachricht("f", 1, "z", 0, kontakt), 2, "a"))
        assertNotNull(KontaktSync.hash(kontakt))
    }

    @Test fun `JPEG PNG und WebP werden ohne Neukompression als Data URL transportiert`() {
        val bilder = listOf(
            "image/jpeg" to byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 1, 2),
            "image/png" to byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1),
            "image/webp" to ("RIFF".toByteArray() + byteArrayOf(1, 2, 3, 4) + "WEBP".toByteArray())
        )
        bilder.forEach { (mime, bytes) ->
            val foto = KontaktSync.fotoDataUrl(bytes)
            assertTrue(foto.startsWith("data:$mime;base64,"))
            assertTrue(bytes.contentEquals(KontaktSync.fotoBytes(foto)))
            val gelesen = KontaktSync.lies(KontaktSync.inhalt(
                KontaktNachricht("f", 1, "q", 1, kontakt.copy(foto = foto))))
            assertEquals(foto, gelesen!!.kontakt.foto)
        }
    }

    @Test fun `falsche Foto Data URLs Whitespace und zu grosse Fotos werden abgelehnt`() {
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
        val b64 = Base64.getEncoder().encodeToString(png)
        listOf(
            "data:image/gif;base64,$b64",
            "data:image/jpeg;base64,$b64",
            "data:image/png;base64, $b64",
            "data:image/png;base64,${b64}\n",
            "data:text/plain;base64,$b64"
        ).forEach { foto ->
            val payload = KontaktSync.inhalt(KontaktNachricht("f", 1, "q", 1, kontakt.copy(foto = foto)))
            assertNull(KontaktSync.lies(payload))
        }
        assertNull(KontaktSync.fotoBytes("data:image/png;base64," + "A".repeat(KontaktSync.FOTO_TEXT_MAX)))
    }

    @Test fun `leeres oder konkurrierendes Remote Foto ersetzt kein lokales Foto`() {
        val lokalFoto = KontaktSync.fotoDataUrl(byteArrayOf(
            0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 1))
        val fernFoto = KontaktSync.fotoDataUrl(byteArrayOf(
            0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 2))
        assertEquals(lokalFoto, KontaktSync.mische(kontakt.copy(foto = lokalFoto),
            KontaktDaten(foto = fernFoto)).foto)
        assertEquals(lokalFoto, KontaktSync.mische(kontakt.copy(foto = lokalFoto),
            KontaktDaten()).foto)
        assertEquals(fernFoto, KontaktSync.mische(kontakt, KontaktDaten(foto = fernFoto)).foto)
    }
}
