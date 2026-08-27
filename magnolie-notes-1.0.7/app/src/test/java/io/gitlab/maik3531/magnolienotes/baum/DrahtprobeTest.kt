package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Der Beweis, dass diese App und der Magnolie Organizer dieselbe Sprache
 * sprechen.
 *
 * Die Prüfvektoren in `vektoren.json` stammen nicht aus einer Nachbildung,
 * sondern aus dem laufenden Organizer selbst: `werkzeuge/vektoren.py` lädt
 * `bin/magnolie-organizer` als Modul und lässt dessen eigene Funktionen
 * rechnen. Was hier verglichen wird, ist also echte Drahtkompatibilität.
 *
 * Neue Vektoren erzeugt man mit:
 *
 *     python3 werkzeuge/vektoren.py app/src/test/resources/vektoren.json
 */
class DrahtprobeTest {

    private val vektoren: JsonObject by lazy {
        val roh = javaClass.classLoader!!.getResourceAsStream("vektoren.json")
            ?.readBytes()?.toString(Charsets.UTF_8)
        assertNotNull("vektoren.json fehlt in den Testressourcen", roh)
        Kanonisch.json.parseToJsonElement(roh!!).jsonObject
    }

    private fun text(objekt: JsonObject, name: String) =
        objekt[name]!!.jsonPrimitive.content

    private fun identitaet(welche: String): EigeneIdentitaet {
        val roh = vektoren["identitaeten"]!!.jsonObject[welche]!!.jsonObject
        return EigeneIdentitaet(
            kennung = text(roh, "kennung"),
            name = text(roh, "name"),
            oeffentlich = text(roh, "oeffentlich"),
            geheim = text(roh, "geheim"),
            port = roh["port"]!!.jsonPrimitive.content.toInt()
        )
    }

    // ------------------------------------------------------------ Kanonisch

    @Test
    fun `kanonische Schreibweise gleicht Python zeichengenau`() {
        val faelle = vektoren["kanonisch"]!! as kotlinx.serialization.json.JsonArray
        assertTrue("keine Fälle", faelle.isNotEmpty())
        for (fall in faelle) {
            val objekt = fall.jsonObject
            val wert: JsonElement = objekt["wert"]!!
            assertEquals(
                "kanonische Schreibweise weicht ab",
                text(objekt, "erwartet"),
                Kanonisch.text(wert)
            )
        }
    }

    // ---------------------------------------------------- Schlüsselableitung

    @Test
    fun `Fingerabdruck stimmt mit dem Organizer ueberein`() {
        val f = vektoren["fingerabdruck"]!!.jsonObject
        assertEquals(text(f, "erwartetA"), Krypto.fingerabdruck(text(f, "oeffentlichA")))
        assertEquals(text(f, "erwartetB"), Krypto.fingerabdruck(text(f, "oeffentlichB")))
    }

    @Test
    fun `sechsstelliger Paarungscode stimmt ueberein`() {
        val p = vektoren["paarungscode"]!!.jsonObject
        assertEquals(text(p, "erwartet"), Krypto.paarungsCode(text(p, "a"), text(p, "b")))
    }

    @Test
    fun `Partnerschluessel wird gleich abgeleitet`() {
        val p = vektoren["partnerschluessel"]!!.jsonObject
        val schluessel = Krypto.partnerschluessel(
            text(p, "geheim"), text(p, "fremd"), text(p, "kennungA"), text(p, "kennungB")
        )
        assertEquals(text(p, "erwartet"), Krypto.b64(schluessel))
    }

    @Test
    fun `Auth-Schluessel der sicheren Sitzung wird gleich abgeleitet`() {
        val a = vektoren["authschluessel"]!!.jsonObject
        val schluessel = Krypto.authSchluessel(
            text(a, "geheim"), text(a, "fremd"), text(a, "eigene"), text(a, "partner")
        )
        assertEquals(text(a, "erwartet"), Krypto.b64(schluessel))
    }

    // ------------------------------------------------------------- Paarung

    @Test
    fun `Paarungsdatei des Organizers wird angenommen`() {
        val p = vektoren["paarungsdatei"]!!.jsonObject
        val dokument = p["dokument"]!!.jsonObject
        val jetzt = p["jetzt"]!!.jsonPrimitive.content.toLong()
        // Wirft, wenn Commitment oder HMAC nicht passen.
        val geprueft = Paarung.pruefe(dokument, jetzt)
        assertEquals(dokument, geprueft)
    }

    @Test
    fun `veraenderte Paarungsdatei wird abgewiesen`() {
        val p = vektoren["paarungsdatei"]!!.jsonObject
        val dokument = p["dokument"]!!.jsonObject
        val jetzt = p["jetzt"]!!.jsonPrimitive.content.toLong()
        val verbogen = buildJsonObject {
            dokument.forEach { (name, wert) ->
                if (name == "ziel") {
                    put("ziel", buildJsonObject {
                        put("adresse", JsonPrimitive("10.0.0.1"))   // umgebogenes Ziel
                        put("port", wert.jsonObject.getValue("port"))
                    })
                } else put(name, wert)
            }
        }
        val fehler = runCatching { Paarung.pruefe(verbogen, jetzt) }.exceptionOrNull()
        assertTrue("eine veränderte Datei muss auffallen", fehler is BaumFehler)
    }

    @Test
    fun `unsere Paarungsanfrage gleicht der des Organizers`() {
        val p = vektoren["paarungsdatei"]!!.jsonObject
        val dokument = p["dokument"]!!.jsonObject
        val erwartet = vektoren["paarungsanfrage"]!!.jsonObject["erwartet"]!!.jsonObject
        val handy = identitaet("handy")

        // Dieselbe Nonce erzwingen, damit der Beweis vergleichbar wird.
        val unsere = Paarung.anfrage(dokument, handy)
        val mitGleicherNonce = buildJsonObject {
            unsere.forEach { (name, wert) ->
                if (name == "nonce") put(name, erwartet.getValue("nonce")) else put(name, wert)
            }
        }
        // Der Beweis muss über dem Kern mit der übernommenen Nonce neu entstehen.
        val kern = buildJsonObject {
            mitGleicherNonce.forEach { (name, wert) -> if (name != "beweis") put(name, wert) }
        }
        val geheimnis = Krypto.b64UrlLesen(
            dokument["geheimnis"]!!.jsonPrimitive.content, 32
        )
        val beweis = Krypto.b64Url(
            Krypto.hmacUeber(geheimnis, "magnolie-pair-request-v2\u0000".toByteArray(), kern)
        )
        assertEquals(erwartet["beweis"]!!.jsonPrimitive.content, beweis)
        assertEquals(erwartet["zweig"], mitGleicherNonce["zweig"])
    }

    @Test
    fun `Antwort des Organizers auf die Paarung wird anerkannt`() {
        val p = vektoren["paarungsdatei"]!!.jsonObject
        val dokument = p["dokument"]!!.jsonObject
        val anfrage = vektoren["paarungsanfrage"]!!.jsonObject["erwartet"]!!.jsonObject
        val antwort = vektoren["paarungsantwort"]!!.jsonObject["erwartet"]!!.jsonObject
        Paarung.pruefeAntwort(dokument, anfrage, antwort)   // wirft bei Abweichung
    }

    // -------------------------------------------------------------- baum-fs1

    @Test
    fun `Start des Organizers wird beantwortet und ergibt dieselben Schluessel`() {
        val start = vektoren["fs_start"]!!.jsonObject["erwartet"]!!.jsonObject
        val handy = identitaet("handy")
        val organizer = identitaet("organizer")

        val antwort = Sitzung.baueAntwort(
            handy, organizer.kennung, organizer.oeffentlich, start
        )
        val erwartet = vektoren["fs_antwort"]!!.jsonObject
        // Unsere ephemere Hälfte ist zufällig; die Schlüssel des Organizers
        // lassen sich damit nicht Byte für Byte treffen. Was zählt: die
        // Sitzung des Organizers muss unsere Nachrichten öffnen können und
        // umgekehrt – das prüft der nächste Test über den festen Vektor.
        assertEquals("baum-fs1-antwort", antwort.nachricht["magnolie"]!!.jsonPrimitive.content)
        assertEquals(start["sid"], antwort.nachricht["sid"])
        assertEquals(
            erwartet["erwartet"]!!.jsonObject["startHash"],
            antwort.nachricht["startHash"]
        )
        antwort.sitzung.loeschen()
    }

    @Test
    fun `Sitzungsschluessel des Organizers werden Byte fuer Byte nachgerechnet`() {
        // Mit der festen ephemeren Hälfte aus dem Vektor muss dieselbe
        // Ableitung herauskommen wie im Organizer.
        val start = vektoren["fs_start"]!!.jsonObject["erwartet"]!!.jsonObject
        val fs = vektoren["fs_antwort"]!!.jsonObject
        val antwort = fs["erwartet"]!!.jsonObject
        val handy = identitaet("handy")
        val organizer = identitaet("organizer")

        val ephemerGeheim = Krypto.b64Lesen(text(fs, "ephemer"), 32)
        val startKern = buildJsonObject {
            start.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val antwortKern = buildJsonObject {
            antwort.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val auth = Krypto.authSchluessel(
            handy.geheim, organizer.oeffentlich, handy.kennung, organizer.kennung
        )
        val sitzung = Sitzung.schluesselplanFuerTest(
            ephemerGeheim,
            Krypto.b64Lesen(startKern["epk"]!!.jsonPrimitive.content, 32),
            auth, startKern, antwortKern
        )
        assertEquals("Transkript weicht ab", text(fs, "transkript"), Krypto.b64(sitzung.transkript))
        assertEquals("kenc weicht ab", text(fs, "kenc"), Krypto.b64(sitzung.kenc))
        assertEquals("kack weicht ab", text(fs, "kack"), Krypto.b64(sitzung.kack))
        sitzung.loeschen()
    }

    @Test
    fun `Notizumschlag des Organizers laesst sich oeffnen`() {
        val start = vektoren["fs_start"]!!.jsonObject["erwartet"]!!.jsonObject
        val fs = vektoren["fs_antwort"]!!.jsonObject
        val antwort = fs["erwartet"]!!.jsonObject
        val handy = identitaet("handy")
        val organizer = identitaet("organizer")

        val sitzung = sitzungAusVektor(start, antwort, fs, handy, organizer)
        val umschlagVektor = vektoren["fs_umschlag"]!!.jsonObject
        val umschlag = umschlagVektor["erwartet"]!!.jsonObject

        val (inhalt, mid) = Sitzung.oeffneUmschlag(
            sitzung, handy.kennung, organizer.kennung, umschlag
        )
        assertEquals(text(umschlagVektor, "mid"), mid)
        assertEquals(umschlagVektor["inhalt"], inhalt)

        // Der Inhalt muss auch fachlich ankommen.
        val gelesen = Nutzlast.lies(inhalt, organizer.kennung)
        assertNotNull("die Notiz wurde nicht erkannt", gelesen)
        assertEquals("Einkauf für Sonntag", gelesen!!.titel)
        assertEquals(3L, gelesen.version)
        sitzung.loeschen()
    }

    @Test
    fun `unsere Quittung ist die, die der Organizer erwartet`() {
        val start = vektoren["fs_start"]!!.jsonObject["erwartet"]!!.jsonObject
        val fs = vektoren["fs_antwort"]!!.jsonObject
        val antwort = fs["erwartet"]!!.jsonObject
        val handy = identitaet("handy")
        val organizer = identitaet("organizer")

        val sitzung = sitzungAusVektor(start, antwort, fs, handy, organizer)
        val umschlag = vektoren["fs_umschlag"]!!.jsonObject["erwartet"]!!.jsonObject
        val unsere = Sitzung.baueQuittung(sitzung, umschlag)
        assertEquals(vektoren["fs_quittung"]!!.jsonObject["erwartet"], unsere)
        sitzung.loeschen()
    }

    @Test
    fun `ein von uns gebauter Umschlag traegt denselben Inhalt`() {
        val start = vektoren["fs_start"]!!.jsonObject["erwartet"]!!.jsonObject
        val fs = vektoren["fs_antwort"]!!.jsonObject
        val antwort = fs["erwartet"]!!.jsonObject
        val handy = identitaet("handy")
        val organizer = identitaet("organizer")

        val hinaus = sitzungAusVektor(start, antwort, fs, handy, organizer)
        val inhalt = vektoren["fs_umschlag"]!!.jsonObject["inhalt"]!!.jsonObject
        val mid = Krypto.b64(ByteArray(16) { (it * 3).toByte() })
        val umschlag = Sitzung.baueUmschlag(hinaus, handy.kennung, organizer.kennung, inhalt, mid)

        // Mit derselben Sitzung wieder auf – so würde der Organizer es tun.
        val herein = sitzungAusVektor(start, antwort, fs, handy, organizer)
        val (zurueck, zurueckMid) = Sitzung.oeffneUmschlag(
            herein, organizer.kennung, handy.kennung, umschlag
        )
        assertEquals(mid, zurueckMid)
        assertEquals(inhalt, zurueck)
        hinaus.loeschen()
        herein.loeschen()
    }

    // ---------------------------------------------------------------- baum-1

    @Test
    fun `alter Umschlag baum-1 des Organizers laesst sich oeffnen`() {
        val b = vektoren["baum1"]!!.jsonObject
        val handy = identitaet("handy")
        val (inhalt, zaehler) = Baum1.oeffne(
            handy,
            text(b, "kennungA"),
            text(b, "oeffentlichA"),
            b["umschlag"]!!.jsonObject,
            0L
        )
        assertEquals(42L, zaehler)
        assertEquals(b["inhalt"], inhalt)
    }

    @Test
    fun `ein wiederholter Zaehler wird abgewiesen`() {
        val b = vektoren["baum1"]!!.jsonObject
        val handy = identitaet("handy")
        val fehler = runCatching {
            Baum1.oeffne(
                handy, text(b, "kennungA"), text(b, "oeffentlichA"),
                b["umschlag"]!!.jsonObject, 42L
            )
        }.exceptionOrNull()
        assertTrue("ein alter Zähler muss auffallen", fehler is BaumFehler)
    }

    // ----------------------------------------------------------------- Hilfe

    private fun sitzungAusVektor(
        start: JsonObject,
        antwort: JsonObject,
        fs: JsonObject,
        handy: EigeneIdentitaet,
        organizer: EigeneIdentitaet
    ): Sitzung.Offen {
        val startKern = buildJsonObject {
            start.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val antwortKern = buildJsonObject {
            antwort.forEach { (name, wert) -> if (name != "mac") put(name, wert) }
        }
        val auth = Krypto.authSchluessel(
            handy.geheim, organizer.oeffentlich, handy.kennung, organizer.kennung
        )
        return Sitzung.schluesselplanFuerTest(
            Krypto.b64Lesen(text(fs, "ephemer"), 32),
            Krypto.b64Lesen(startKern["epk"]!!.jsonPrimitive.content, 32),
            auth, startKern, antwortKern
        )
    }
}
