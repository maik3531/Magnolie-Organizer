package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Partner
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.BufferedInputStream
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

class NetzwerkGrenzenTest {

    @Test
    fun `Server beantwortet Anfragen nach anhalten und erneutem starten`() {
        val server = Server(leereHandlung(), 0)
        try {
            check(server.starten())
            assertEquals("HTTP/1.1 503 Service Unavailable", anfragen(server.port))

            server.anhalten()

            check(server.starten())
            assertEquals("HTTP/1.1 503 Service Unavailable", anfragen(server.port))
        } finally {
            server.anhalten()
        }
    }

    @Test
    fun `Server schliesst Verbindung wenn Arbeiter und Queue belegt sind`() {
        val server = Server(leereHandlung(), 0)
        val verbindungen = mutableListOf<Socket>()
        try {
            check(server.starten())
            repeat(Server.ARBEITER_MAX + Server.WARTESCHLANGE_MAX + 1) {
                verbindungen += Socket("127.0.0.1", server.port)
            }

            val abgewiesen = verbindungen.last().apply { soTimeout = 2000 }
            assertEquals(-1, abgewiesen.getInputStream().read())
        } finally {
            verbindungen.forEach { runCatching { it.close() } }
            server.anhalten()
        }
    }

    @Test
    fun `WLAN Transport begrenzt normale und Fehlerantworten ohne Content Length`() {
        listOf(200, 500).forEach { nummer -> pruefeUebergrosseAntwort(nummer) }
    }

    private fun pruefeUebergrosseAntwort(nummer: Int) {
        val gegenstelle = ServerSocket(0)
        val senden = thread(isDaemon = true) {
            runCatching {
                gegenstelle.accept().use { verbindung ->
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
                    val hinaus = verbindung.getOutputStream()
                    val laenge = WlanTransport.ANTWORT_MAX + 1
                    hinaus.write(
                        ("HTTP/1.1 $nummer Antwort\r\nTransfer-Encoding: chunked\r\n" +
                            "Connection: close\r\n\r\n${laenge.toString(16)}\r\n")
                            .toByteArray(Charsets.US_ASCII)
                    )
                    hinaus.write(ByteArray(laenge) { 'x'.code.toByte() })
                    hinaus.write("\r\n0\r\n\r\n".toByteArray(Charsets.US_ASCII))
                    hinaus.flush()
                }
            }
        }

        try {
            val fehler = assertThrows(BaumFehler::class.java) {
                WlanTransport("127.0.0.1", gegenstelle.localPort)
                    .anfrage("/test", JsonObject(emptyMap()), 5000)
            }
            assertEquals("Die Antwort der Gegenstelle ist zu groß.", fehler.message)
        } finally {
            gegenstelle.close()
            senden.join(2000)
        }
    }

    private fun anfragen(port: Int): String = Socket("127.0.0.1", port).use { verbindung ->
        verbindung.soTimeout = 2000
        verbindung.getOutputStream().apply {
            write("POST /magnolie/v1/paarung HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}".toByteArray())
            flush()
        }
        BufferedReader(InputStreamReader(verbindung.getInputStream(), Charsets.US_ASCII)).readLine()
    }

    private fun leereHandlung() = object : Server.Handlung {
        override fun eigen(): EigeneIdentitaet? = null
        override fun istAn() = false
        override fun partner(kennung: String): Partner? = null
        override fun einladungen(): List<Einladung> = emptyList()
        override fun paarungFertig(zweig: JsonObject, adresse: String, einladung: Einladung) {}
        override fun codeAnfrage(
            name: String,
            kennung: String,
            oeffentlich: String,
            adresse: String,
            port: Int
        ) {}
        override fun nachricht(vonKennung: String, inhalt: JsonObject) {}
        override fun merkeZaehler(vonKennung: String, zaehler: Long) {}
        override fun schonGesehen(vonKennung: String, transportId: String) = false
        override fun merkeTransportId(vonKennung: String, transportId: String) {}
        override fun adresseGesehen(vonKennung: String, adresse: String) {}
    }
}
