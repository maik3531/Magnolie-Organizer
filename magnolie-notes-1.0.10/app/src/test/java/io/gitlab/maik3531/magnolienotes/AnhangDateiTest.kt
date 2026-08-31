package io.gitlab.maik3531.magnolienotes

import io.gitlab.maik3531.magnolienotes.daten.Anhang
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Base64

class AnhangDateiTest {
    private val formate = listOf(
        Triple("image/jpeg", byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 1), "jpg"),
        Triple("image/png", byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a), "png"),
        Triple("image/webp", "RIFF1234WEBP".toByteArray(), "webp"),
        Triple("image/gif", "GIF89a".toByteArray(), "gif"),
        Triple("application/pdf", "%PDF-1.7".toByteArray(), "pdf")
    )

    private fun anhang(mime: String, bytes: ByteArray, name: String = "datei") = Anhang(
        "id", name, if (mime == "application/pdf") "pdf" else "image",
        "data:$mime;base64,${Base64.getEncoder().encodeToString(bytes)}"
    )

    @Test fun `alle Formate werden strikt dekodiert`() {
        formate.forEach { (mime, bytes, endung) ->
            val inhalt = AnhangDatei.dekodieren(anhang(mime, bytes))!!
            assertEquals(mime, inhalt.mime)
            assertEquals(endung, inhalt.endung)
            assertArrayEquals(bytes, inhalt.bytes)
        }
    }

    @Test fun `Manipulationen werden abgelehnt`() {
        val png = formate[1].second
        listOf(
            Anhang("id", "x", daten = ""),
            Anhang("id", "x", daten = "data:image/svg+xml;base64,PHN2Zz4="),
            Anhang("id", "x", daten = "data:image/png;base64,%%%"),
            Anhang("id", "x", daten = "data:image/png;base64, ${Base64.getEncoder().encodeToString(png)}"),
            Anhang("id", "x", daten = "data:image/png;base64,"),
            anhang("application/pdf", png),
            Anhang("id", "x", daten = "data:image/png;BASE64,AAAA")
        ).forEach { assertNull(AnhangDatei.dekodieren(it)) }
    }

    @Test fun `URL und Rohdatengrenzen werden erzwungen`() {
        assertNull(AnhangDatei.dekodieren(Anhang(
            "id", "x", daten = "data:image/png;base64," + "A".repeat(AnhangDatei.DATA_URL_MAX)
        )))
        val zuGross = ByteArray(AnhangDatei.ROH_MAX + 1)
        zuGross[0] = 0x89.toByte(); zuGross[1] = 0x50; zuGross[2] = 0x4e; zuGross[3] = 0x47
        zuGross[4] = 0x0d; zuGross[5] = 0x0a; zuGross[6] = 0x1a; zuGross[7] = 0x0a
        assertNull(AnhangDatei.dekodieren(anhang("image/png", zuGross)))
    }

    @Test fun `Vorschlagsnamen sind sicher und haben die validierte Endung`() {
        val pdf = AnhangDatei.dekodieren(anhang("application/pdf", "%PDF-1.7".toByteArray()))!!
        assertEquals("bericht.pdf", AnhangDatei.sichererName(anhang("application/pdf", pdf.bytes, "../bericht.exe"), pdf))
        assertEquals("document.pdf", AnhangDatei.sichererName(anhang("application/pdf", pdf.bytes, "\u0000/"), pdf))
        val lang = "a".repeat(300)
        assertEquals(174, AnhangDatei.sichererName(anhang("application/pdf", pdf.bytes, lang), pdf).length)
    }
}
