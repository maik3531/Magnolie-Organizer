package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.ByteArrayInputStream

class AnhangLeserTest {
    private val formate = listOf(
        Triple("image/jpeg", byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 1), "image/jpg"),
        Triple("image/png", byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a), "image/png"),
        Triple("image/webp", "RIFF1234WEBP".toByteArray(), "application/octet-stream"),
        Triple("image/gif", "GIF89a".toByteArray(), ""),
        Triple("application/pdf", "%PDF-1.7".toByteArray(), "application/pdf")
    )

    @Test fun `alle fuenf Formate werden an Signatur erkannt und kanonisiert`() {
        formate.forEachIndexed { index, (mime, bytes, gemeldet) ->
            assertEquals(mime, AnhangLeser.mimeAusSignatur(bytes))
            val ergebnis = AnhangLeser.lies(ByteArrayInputStream(bytes), gemeldet, "pfad/datei-$index")
            assertNotNull(ergebnis.anhang)
            assertEquals(mime, ergebnis.anhang!!.daten.substringAfter("data:").substringBefore(';'))
        }
        assertEquals("image/gif", AnhangLeser.mimeAusSignatur("GIF87a".toByteArray()))
    }

    @Test fun `falscher MIME oder falscher Inhalt wird abgelehnt`() {
        assertNull(AnhangLeser.lies(ByteArrayInputStream("kein bild".toByteArray()), "image/png", "x.png").anhang)
        assertNull(AnhangLeser.lies(ByteArrayInputStream("%PDF-1.7".toByteArray()), "image/png", "x.png").anhang)
    }

    @Test fun `Lesen bricht genau oberhalb der Grenze ab`() {
        assertEquals(4, AnhangLeser.begrenztLesen(ByteArrayInputStream(byteArrayOf(1, 2, 3, 4)), 4)!!.size)
        assertNull(AnhangLeser.begrenztLesen(ByteArrayInputStream(byteArrayOf(1, 2, 3, 4, 5)), 4))
    }
}
