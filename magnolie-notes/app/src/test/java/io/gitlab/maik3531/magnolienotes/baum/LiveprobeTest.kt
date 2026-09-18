package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Partner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assume.assumeTrue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.io.Writer
import java.util.concurrent.TimeUnit

/**
 * Der Livetest: ein wirklich laufender Magnolienbaum-Dienst des Organizers auf
 * der einen Seite, der Code dieser App auf der anderen – über echtes HTTP.
 *
 * Geprüft werden beide Richtungen: die Paarung mit der Datei, eine Notiz vom
 * Handy zum Organizer und eine Notiz vom Organizer zum Handy.
 *
 * Fehlen Python oder `python3-cryptography`, wird der Test übersprungen statt
 * fehlzuschlagen – auf einem Rechner ohne Organizer wäre er sinnlos.
 */
class LiveprobeTest {

    private val organizerQuelle = File(
        System.getenv("MAGNOLIE_ORGANIZER_QUELLE")
            ?: "../magnolie-organizer/bin/magnolie-organizer"
    ).absoluteFile.normalize()
    private val treiber = File("werkzeuge/organizer_dienst.py")

    private class Gegenstelle(
        val prozess: Process,
        val lesen: BufferedReader,
        val schreiben: Writer
    ) {
        fun sag(befehl: String) {
            schreiben.write(befehl + "\n")
            schreiben.flush()
        }

        fun warteAuf(anfang: String, sekunden: Long = 20): String? {
            val ende = System.currentTimeMillis() + sekunden * 1000
            while (System.currentTimeMillis() < ende) {
                val zeile = lesen.readLine() ?: return null
                gesammelt += zeile
                if (zeile.startsWith(anfang)) return zeile
            }
            return null
        }

        val gesammelt = mutableListOf<String>()

        fun beenden() {
            runCatching { sag("ENDE") }
            if (!prozess.waitFor(5, TimeUnit.SECONDS)) prozess.destroyForcibly()
        }
    }

    private fun starteOrganizer(port: Int): Gegenstelle? {
        if (!organizerQuelle.isFile || !treiber.isFile) return null
        val bau = ProcessBuilder(
            "python3", treiber.absolutePath, organizerQuelle.absolutePath, port.toString()
        )
        bau.redirectErrorStream(false)
        val prozess = try {
            bau.start()
        } catch (fehler: Exception) {
            return null
        }
        val gegen = Gegenstelle(
            prozess,
            BufferedReader(InputStreamReader(prozess.inputStream, Charsets.UTF_8)),
            java.io.OutputStreamWriter(prozess.outputStream, Charsets.UTF_8)
        )
        if (gegen.warteAuf("BEREIT") == null) {
            gegen.beenden()
            return null
        }
        return gegen
    }

    private fun eigeneIdentitaet(port: Int): EigeneIdentitaet {
        val (geheim, oeffentlich) = Krypto.neuesSchluesselpaar()
        return EigeneIdentitaet(
            kennung = "handylivetest0001",
            name = "Magnolie Notes",
            oeffentlich = Krypto.b64(oeffentlich),
            geheim = Krypto.b64(geheim),
            port = port
        )
    }

    @Test
    fun `Paarung und Notizversand laufen gegen den echten Organizer`() {
        val organizerPort = 18841
        val eigenerPort = 18842
        val gegen = starteOrganizer(organizerPort)
        assumeTrue("Kein lauffähiger Organizer gefunden – Livetest übersprungen", gegen != null)
        gegen!!

        val eigen = eigeneIdentitaet(eigenerPort)
        var empfangen: JsonObject? = null
        val partnerListe = mutableListOf<Partner>()

        // Unser eigener Empfangsdienst, damit der Organizer zurückschreiben kann.
        val handlung = object : Server.Handlung {
            override fun eigen() = eigen
            override fun istAn() = true
            override fun partner(kennung: String) =
                partnerListe.firstOrNull { it.kennung == kennung }
            override fun einladungen(): List<Einladung> = emptyList()
            override fun dateiPaarungAnnehmen(eigen: EigeneIdentitaet, anfrage: JsonObject, adresse: String): JsonObject = error("Unused test route")
            override fun codeAnfrage(
                name: String, kennung: String, oeffentlich: String, adresse: String, port: Int
            ) {}
            override fun nachricht(vonKennung: String, inhalt: JsonObject) {
                empfangen = inhalt
            }
            override fun merkeZaehler(vonKennung: String, zaehler: Long) {}
            override fun schonGesehen(vonKennung: String, transportId: String) = false
            override fun merkeTransportId(vonKennung: String, transportId: String) {}
            override fun adresseGesehen(vonKennung: String, adresse: String) {}
        }
        val server = Server(handlung, eigenerPort)
        assertTrue("Der eigene Empfangsdienst startete nicht", server.starten())

        try {
            // ---------------------------------------------- Schritt 1: Paarung
            val zeile = gegen.gesammelt.first { it.startsWith("PAARUNGSDATEI ") }
            val dokument = Kanonisch.json
                .parseToJsonElement(zeile.removePrefix("PAARUNGSDATEI ")).jsonObject
            val geprueft = Paarung.pruefeDatei(
                Kanonisch.json.encodeToString(JsonObject.serializer(), dokument)
            )
            val partner = Versand.paareMitDatei(geprueft, eigen)
            partnerListe += partner
            assertTrue("Der Organizer gilt nach der Paarung als bestätigt", partner.bestaetigt)
            assertEquals("baum-fs1", partner.protokoll)

            // Der Organizer muss uns nun ebenfalls als bestätigt führen.
            gegen.sag("PARTNER")
            val partnerZeile = gegen.warteAuf("PARTNER ")
            assertNotNull("Der Organizer meldete keinen Partner", partnerZeile)
            assertTrue(
                "Der Organizer hat uns nicht bestätigt: $partnerZeile",
                partnerZeile!!.contains(eigen.kennung) && partnerZeile.contains("True")
            )
            gegen.warteAuf("PARTNERENDE")

            // ------------------------------- Schritt 2: Notiz vom Handy hinüber
            val inhalt = buildJsonObject {
                put("freigabeId", JsonPrimitive("live-1"))
                put("titel", JsonPrimitive("Einkauf – Grüße aus München"))
                put("text", JsonPrimitive("Milch\nBrot\nÄpfel"))
                put("html", JsonPrimitive("<div>Milch</div>"))
                put("anhaenge", kotlinx.serialization.json.JsonArray(emptyList()))
                put("geaendert", JsonPrimitive(1786000000000L))
                put("version", JsonPrimitive(1L))
                put("quelle", JsonPrimitive(eigen.kennung))
                put("symbol", JsonPrimitive("einkauf"))
                put("angelegt", JsonPrimitive(1785999999000L))
            }
            val ergebnis = Versand.zustellen(
                eigen, partner, "notiz", inhalt,
                Krypto.b64(Krypto.zufallsbytes(16)),
                WlanTransport("127.0.0.1", organizerPort)
            )
            assertTrue("Zustellung misslungen: " + ergebnis.grund, ergebnis.gelungen)

            val nachrichtZeile = gegen.warteAuf("NACHRICHT ")
            assertNotNull("Der Organizer hat nichts empfangen", nachrichtZeile)
            val angekommen = Kanonisch.json.parseToJsonElement(
                nachrichtZeile!!.substringAfter("NACHRICHT ").substringAfter(" ")
            ).jsonObject
            assertEquals(
                "Einkauf – Grüße aus München",
                angekommen["titel"]!!.jsonPrimitive.content
            )
            assertEquals("notiz", angekommen["art"]!!.jsonPrimitive.content)
            assertEquals("live-1", angekommen["freigabeId"]!!.jsonPrimitive.content)
            // Die zusätzlichen Felder überstehen den Weg unbeschadet.
            assertEquals("einkauf", angekommen["symbol"]!!.jsonPrimitive.content)

            // ---------------------------- Schritt 3: Notiz vom Organizer zurück
            val zurueck = buildJsonObject {
                put("art", JsonPrimitive("notiz"))
                put("freigabeId", JsonPrimitive("live-2"))
                put("titel", JsonPrimitive("Vom Schreibtisch"))
                put("text", JsonPrimitive("Zurückgeschrieben"))
                put("html", JsonPrimitive(""))
                put("anhaenge", kotlinx.serialization.json.JsonArray(emptyList()))
                put("geaendert", JsonPrimitive(1786000001000L))
                put("version", JsonPrimitive(1L))
            }
            gegen.sag(
                "SENDE " + Kanonisch.json.encodeToString(JsonObject.serializer(), zurueck)
            )
            val sendeErgebnis = gegen.warteAuf("SENDEERGEBNIS")
            assertEquals("SENDEERGEBNIS ja", sendeErgebnis)

            // Der Empfangsdienst hat den Inhalt an die Anwendung durchgereicht.
            var warten = 0
            while (empfangen == null && warten < 5000) {
                Thread.sleep(100)
                warten += 100
            }
            val da = empfangen
            assertNotNull("Die App hat die Notiz des Organizers nicht empfangen", da)
            assertEquals("Vom Schreibtisch", da!!["titel"]!!.jsonPrimitive.content)

            val gelesen = Nutzlast.lies(da, partner.kennung)
            assertNotNull("Die Notiz wurde fachlich nicht erkannt", gelesen)
            assertEquals("live-2", gelesen!!.freigabeId)

            // ------------------- Schritt 4: Aufgabe vom Organizer zum Handy
            empfangen = null
            val aufgabe = buildJsonObject {
                put("art", JsonPrimitive("aufgabe"))
                put("id", JsonPrimitive("aufgabe-vom-rechner-1"))
                put("titel", JsonPrimitive("Blumen kaufen"))
                put("notiz", JsonPrimitive("weil Max Mustermann morgen Geburtstag hat"))
                put("faellig", JsonPrimitive("2026-08-11"))
                put("prio", JsonPrimitive(1))
                put("erinnern", JsonPrimitive(true))
                put("herkunft", JsonPrimitive(partner.kennung))
                put("geaendert", JsonPrimitive(1786000002000L))
            }
            gegen.sag("SENDE " + Kanonisch.json.encodeToString(JsonObject.serializer(), aufgabe))
            assertEquals("SENDEERGEBNIS ja", gegen.warteAuf("SENDEERGEBNIS"))

            warten = 0
            while (empfangen == null && warten < 5000) {
                Thread.sleep(100)
                warten += 100
            }
            val angekommeneAufgabe = empfangen
            assertNotNull("Die Aufgabe kam nicht an", angekommeneAufgabe)
            val gelesenAufgabe = Nutzlast.liesAufgabe(angekommeneAufgabe!!, partner.kennung)
            assertNotNull("Die Aufgabe wurde fachlich nicht erkannt", gelesenAufgabe)
            assertEquals("Blumen kaufen", gelesenAufgabe!!.titel)
            assertEquals("weil Max Mustermann morgen Geburtstag hat", gelesenAufgabe.notiz)
            assertEquals("2026-08-11", gelesenAufgabe.faellig)
            assertEquals(1, gelesenAufgabe.prio)
            assertTrue("Die Erinnerung ging verloren", gelesenAufgabe.erinnern)
            assertEquals(partner.kennung, gelesenAufgabe.herkunft)

            // -------------- Schritt 5: Erledigt-Stand zurück zum Organizer
            val erledigt = io.gitlab.maik3531.magnolienotes.daten.Aufgabe(
                id = "oertlich-1",
                titel = gelesenAufgabe.titel,
                fremdId = gelesenAufgabe.id,
                herkunft = gelesenAufgabe.herkunft,
                erledigt = true,
                geaendert = 1786000003000L
            )
            val standErgebnis = Versand.zustellen(
                eigen, partner, "stand", Nutzlast.standInhalt(erledigt),
                Krypto.b64(Krypto.zufallsbytes(16)),
                WlanTransport("127.0.0.1", organizerPort)
            )
            assertTrue("Der Stand ging nicht durch: " + standErgebnis.grund, standErgebnis.gelungen)

            val standZeile = gegen.warteAuf("NACHRICHT ")
            assertNotNull("Der Organizer bekam keine Rückmeldung", standZeile)
            val stand = Kanonisch.json.parseToJsonElement(
                standZeile!!.substringAfter("NACHRICHT ").substringAfter(" ")
            ).jsonObject
            assertEquals("stand", stand["art"]!!.jsonPrimitive.content)
            assertEquals("aufgabe-vom-rechner-1", stand["id"]!!.jsonPrimitive.content)
            assertEquals("true", stand["erledigt"]!!.jsonPrimitive.content)
        } finally {
            server.anhalten()
            gegen.beenden()
        }
    }
}
