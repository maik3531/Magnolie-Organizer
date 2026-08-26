package io.gitlab.maik3531.magnolienotes.baum

import java.io.File
import java.io.BufferedInputStream
import java.net.ServerSocket
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.concurrent.thread

class KlartextRichtlinieTest {
    @Test
    fun `Framework Klartext ist appweit gesperrt und Baum nutzt eigenen Socket`() {
        val regeln = File("app/src/main/res/xml/netzregeln.xml").readText()
        assertTrue(regeln.contains("cleartextTrafficPermitted=\"false\""))
        assertFalse(regeln.contains("cleartextTrafficPermitted=\"true\""))

        val transport = File(
            "app/src/main/java/io/gitlab/maik3531/magnolienotes/baum/Transport.kt"
        ).readText()
        assertTrue(transport.contains("return Socket().use"))
        assertFalse(transport.contains("HttpURLConnection"))
    }

    @Test
    fun `Baum HTTP funktioniert ohne Framework Klartextfreigabe`() {
        val server = ServerSocket(0)
        val antworten = thread(isDaemon = true) {
            server.accept().use { verbindung ->
                val herein = BufferedInputStream(verbindung.getInputStream())
                var ende = 0
                while (ende != 4) {
                    val zeichen = herein.read()
                    check(zeichen >= 0)
                    ende = when (zeichen) {
                        '\r'.code -> if (ende == 0 || ende == 2) ende + 1 else 0
                        '\n'.code -> if (ende == 1 || ende == 3) ende + 1 else 0
                        else -> 0
                    }
                }
                repeat(2) { check(herein.read() >= 0) }
                verbindung.getOutputStream().apply {
                    write(("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n" +
                        "Connection: close\r\n\r\n{}").toByteArray(Charsets.US_ASCII))
                    flush()
                }
            }
        }
        try {
            assertEquals(
                JsonObject(emptyMap()),
                WlanTransport("127.0.0.1", server.localPort)
                    .anfrage("/magnolie/v1/probe", JsonObject(emptyMap()), 2000)
            )
        } finally {
            server.close()
            antworten.join(2000)
        }
    }
}
