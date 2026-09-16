package io.gitlab.maik3531.magnolienotes

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.CancellationException

class AnhangIoRegressionTest {
    @Test fun readFailureIsReportedAndStreamCloses() {
        var closed = false
        val stream = object : InputStream() {
            override fun read(): Int = throw IOException("synthetic failure")
            override fun close() { closed = true }
        }
        assertEquals(AnhangLeser.Fehler.LESEN, AnhangLeser.liesUndSchliesse(stream, null, "x").fehler)
        assertTrue(closed)
    }

    @Test fun closeFailureIsReported() {
        val stream = object : ByteArrayInputStream("%PDF-1.7".toByteArray()) {
            override fun close() { throw IOException("synthetic close failure") }
        }
        assertEquals(AnhangLeser.Fehler.LESEN, AnhangLeser.liesUndSchliesse(stream, null, "x.pdf").fehler)
    }

    @Test fun cancellationIsNeverConvertedToReadFailure() {
        val stream = object : InputStream() {
            override fun read(): Int = throw CancellationException()
        }
        assertThrows(CancellationException::class.java) { AnhangLeser.liesUndSchliesse(stream, null, "x") }
    }
}
