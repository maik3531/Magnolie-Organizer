package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.Freigabe
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Symbol
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Die Notiznutzlast und der HTML-Filter – die Stellen, an denen App und
 * Organizer sich fachlich verstehen müssen.
 */
class NutzlastTest {

    private val notiz = Notiz(
        id = "n1",
        titel = "Einkauf",
        text = "Milch\nBrot",
        html = "<div>Milch</div>",
        symbol = Symbol.EINKAUF,
        angelegt = 1_700_000_000_000L,
        geaendert = 1_700_000_500_000L,
        baumFreigabe = Freigabe("f1", listOf("partner1"), listOf("partner1")),
        baumGeaendert = 1_700_000_500_000L,
        baumVersion = 2L,
        baumQuelle = "handy"
    )

    @Test
    fun `die Nutzlast traegt genau die Felder des Organizers plus zwei`() {
        val inhalt = Nutzlast.notizInhalt(notiz, "notiz_sync", "handy")
        assertEquals(
            setOf(
                "freigabeId", "titel", "text", "html", "anhaenge", "geaendert",
                "version", "quelle", "art", "symbol", "angelegt"
            ),
            inhalt.keys
        )
        assertEquals("f1", inhalt["freigabeId"]!!.jsonPrimitive.content)
        assertEquals("notiz_sync", inhalt["art"]!!.jsonPrimitive.content)
        assertEquals("2", inhalt["version"]!!.jsonPrimitive.content)
        assertEquals("einkauf", inhalt["symbol"]!!.jsonPrimitive.content)
    }

    @Test
    fun `Nutzlast und Rueckweg sind zueinander passend`() {
        val inhalt = Nutzlast.notizInhalt(notiz, "notiz", "handy")
        val gelesen = Nutzlast.lies(inhalt, "partner1")
        assertNotNull(gelesen)
        assertEquals(notiz.titel, gelesen!!.titel)
        assertEquals(notiz.text, gelesen.text)
        assertEquals(notiz.baumVersion, gelesen.version)
        assertEquals(notiz.symbol, gelesen.symbol)
        assertEquals(notiz.angelegt, gelesen.angelegt)
    }

    @Test
    fun `fremde Nachrichtenarten werden nicht als Notiz gelesen`() {
        val aufgabe = kotlinx.serialization.json.buildJsonObject {
            put("art", kotlinx.serialization.json.JsonPrimitive("aufgabe"))
            put("titel", kotlinx.serialization.json.JsonPrimitive("Nicht für uns"))
        }
        assertEquals(null, Nutzlast.lies(aufgabe, "partner1"))
    }

    @Test
    fun `nur Bilder und PDF ueberstehen den Anhangsfilter`() {
        val gemischt = listOf(
            Anhang("a", "gut.png", "image", "data:image/png;base64,QUJD"),
            Anhang("b", "gut.pdf", "pdf", "data:application/pdf;base64,QUJD"),
            Anhang("c", "boese.svg", "image", "data:image/svg+xml;base64,QUJD"),
            Anhang("d", "boese.js", "image", "javascript:alert(1)"),
            Anhang("e", "leer", "image", "")
        )
        val sauber = Nutzlast.saubere(gemischt)
        assertEquals(2, sauber.size)
        assertEquals(listOf("gut.png", "gut.pdf"), sauber.map { it.name })
        assertEquals("pdf", sauber[1].art)
    }

    @Test
    fun `Organizer Empfang und APK Rueckversand erhalten Bild und PDF bytegleich`() {
        val bild = Anhang("bild", "bild.png", "image", "data:image/png;base64,iVBORw0KGgo=")
        val pdf = Anhang("pdf", "brief.pdf", "pdf", "data:application/pdf;base64,JVBERi0xLjQ=")
        val mit = notiz.copy(anhaenge = listOf(bild, pdf))
        val empfangen = Nutzlast.lies(Nutzlast.notizInhalt(mit, "notiz", "handy"), "organizer")!!
        assertEquals(listOf(bild.daten, pdf.daten), empfangen.anhaenge.map { it.daten })
        val zurueck = Nutzlast.notizInhalt(mit.copy(anhaenge = empfangen.anhaenge), "notiz_sync", "handy")
        val nochmals = Nutzlast.lies(zurueck, "organizer")!!
        assertEquals(listOf(bild.daten, pdf.daten), nochmals.anhaenge.map { it.daten })
    }

    @Test fun `JPEG PNG WebP GIF und PDF bleiben im Nutzlastrundlauf erhalten`() {
        val typen = listOf("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf")
        val anhaenge = typen.mapIndexed { index, mime ->
            Anhang("a$index", "a$index", if (mime == "application/pdf") "pdf" else "image", "data:$mime;base64,QUJD")
        }
        val mit = notiz.copy(anhaenge = anhaenge)
        val gelesen = Nutzlast.lies(Nutzlast.notizInhalt(mit, "notiz", "handy"), "partner")!!
        assertEquals(anhaenge.map { it.daten }, gelesen.anhaenge.map { it.daten })
    }

    @Test
    fun `gefaehrliche Anhang MIME Typen werden in beiden Richtungen verworfen`() {
        val boese = listOf(
            Anhang("svg", "x.svg", "image", "data:image/svg+xml;base64,PHN2Zz4="),
            Anhang("js", "x.js", "image", "data:text/javascript;base64,YWxlcnQoMSk="),
            Anhang("html", "x.html", "pdf", "data:text/html;base64,PGgxPng8L2gxPg==")
        )
        assertTrue(Nutzlast.saubere(boese).isEmpty())
        val gelesen = Nutzlast.lies(Nutzlast.notizInhalt(notiz.copy(anhaenge = boese), "notiz", "handy"), "p")!!
        assertTrue(gelesen.anhaenge.isEmpty())
    }

    @Test
    fun `der HTML-Filter laesst nur schlichte Auszeichnungen stehen`() {
        val roh = "<div>Hallo <b>Welt</b><script>alert(1)</script>" +
            "<img src=x onerror=y><i>kursiv</i></div>"
        val sauber = Nutzlast.saeubereHtml(roh)
        assertTrue("fett bleibt", sauber.contains("<b>Welt</b>"))
        assertTrue("kursiv bleibt", sauber.contains("<i>kursiv</i>"))
        assertTrue("kein script", !sauber.contains("script"))
        assertTrue("kein img", !sauber.contains("<img"))
        assertTrue("kein onerror", !sauber.contains("onerror"))
    }

    @Test
    fun `Verweise behalten nur unbedenkliche Ziele`() {
        val gut = Nutzlast.saeubereHtml("""<a href="https://example.org/x">Hin</a>""")
        assertTrue(gut.contains("""href="https://example.org/x""""))
        assertTrue(gut.contains("noopener"))

        val boese = Nutzlast.saeubereHtml("""<a href="javascript:alert(1)">Weg</a>""")
        assertTrue("kein javascript-Ziel", !boese.contains("javascript"))
        assertTrue("der Verweis bleibt als Text", boese.contains("<a>"))
    }

    @Test
    fun `aus Text wird schlichtes HTML mit Leerzeilen`() {
        val html = Nutzlast.textZuHtml("eins\n\nzwei & <drei>")
        assertEquals("<div>eins</div><div><br></div><div>zwei &amp; &lt;drei&gt;</div>", html)
    }

    // ------------------------------------------------------------- Aufgaben

    private val aufgabe = io.gitlab.maik3531.magnolienotes.daten.Aufgabe(
        id = "a1",
        titel = "Blumen kaufen",
        notiz = "weil Max Mustermann morgen Geburtstag hat",
        faellig = "2026-08-11",
        prio = 1,
        erinnern = true,
        geaendert = 1_700_000_500_000L
    )

    @Test
    fun `die Aufgabennutzlast traegt genau die Felder des Organizers`() {
        val inhalt = Nutzlast.aufgabeInhalt(aufgabe, "handy")
        // schickeAnZweig() im Organizer schickt genau diese acht Schlüssel.
        assertEquals(
            setOf("id", "titel", "notiz", "faellig", "prio", "erinnern", "herkunft",
                "geaendert", "art"),
            inhalt.keys
        )
        assertEquals("Blumen kaufen", inhalt["titel"]!!.jsonPrimitive.content)
        assertEquals("2026-08-11", inhalt["faellig"]!!.jsonPrimitive.content)
        assertEquals("1", inhalt["prio"]!!.jsonPrimitive.content)
        assertEquals("true", inhalt["erinnern"]!!.jsonPrimitive.content)
        // Ohne eigene Herkunft trägt die Aufgabe die eigene Kennung ein.
        assertEquals("handy", inhalt["herkunft"]!!.jsonPrimitive.content)
        assertEquals("aufgabe", inhalt["art"]!!.jsonPrimitive.content)
    }

    @Test
    fun `eine weitergereichte Aufgabe behaelt die Kennung des Ursprungs`() {
        val fremd = aufgabe.copy(fremdId = "ursprung-7", herkunft = "rechner")
        val inhalt = Nutzlast.aufgabeInhalt(fremd, "handy")
        assertEquals("ursprung-7", inhalt["id"]!!.jsonPrimitive.content)
        assertEquals("rechner", inhalt["herkunft"]!!.jsonPrimitive.content)
    }

    @Test
    fun `Aufgabennutzlast und Rueckweg passen zueinander`() {
        val inhalt = Nutzlast.aufgabeInhalt(aufgabe, "handy")
        val gelesen = Nutzlast.liesAufgabe(inhalt, "handy")
        assertNotNull(gelesen)
        assertEquals("Blumen kaufen", gelesen!!.titel)
        assertEquals("weil Max Mustermann morgen Geburtstag hat", gelesen.notiz)
        assertEquals("2026-08-11", gelesen.faellig)
        assertEquals(1, gelesen.prio)
        assertTrue(gelesen.erinnern)
    }

    @Test
    fun `eine Aufgabe ohne Titel wird nicht angenommen`() {
        val leer = Nutzlast.aufgabeInhalt(aufgabe.copy(titel = "   "), "handy")
        assertEquals(null, Nutzlast.liesAufgabe(leer, "rechner"))
    }

    @Test
    fun `ein unbrauchbares Datum und eine unbekannte Dringlichkeit werden geglaettet`() {
        val krumm = kotlinx.serialization.json.buildJsonObject {
            put("art", kotlinx.serialization.json.JsonPrimitive("aufgabe"))
            put("id", kotlinx.serialization.json.JsonPrimitive("x"))
            put("titel", kotlinx.serialization.json.JsonPrimitive("Etwas tun"))
            put("faellig", kotlinx.serialization.json.JsonPrimitive("morgen früh"))
            put("prio", kotlinx.serialization.json.JsonPrimitive(9))
        }
        val gelesen = Nutzlast.liesAufgabe(krumm, "rechner")
        assertNotNull(gelesen)
        assertEquals("", gelesen!!.faellig)
        assertEquals(2, gelesen.prio)
    }

    @Test
    fun `der Stand traegt die Kennung des Ursprungs`() {
        val fremd = aufgabe.copy(fremdId = "ursprung-7", herkunft = "rechner", erledigt = true)
        val stand = Nutzlast.standInhalt(fremd)
        assertEquals(setOf("id", "erledigt", "geaendert", "art"), stand.keys)
        assertEquals("ursprung-7", stand["id"]!!.jsonPrimitive.content)
        assertEquals("true", stand["erledigt"]!!.jsonPrimitive.content)

        val gelesen = Nutzlast.liesStand(stand)
        assertNotNull(gelesen)
        assertEquals("ursprung-7", gelesen!!.id)
        assertTrue(gelesen.erledigt)
    }

    @Test
    fun `eine Aufgabennachricht wird nicht als Notiz gelesen und umgekehrt`() {
        val alsAufgabe = Nutzlast.aufgabeInhalt(aufgabe, "handy")
        assertEquals(null, Nutzlast.lies(alsAufgabe, "rechner"))
        val alsNotiz = Nutzlast.notizInhalt(notiz, "notiz", "handy")
        assertEquals(null, Nutzlast.liesAufgabe(alsNotiz, "rechner"))
        assertEquals(null, Nutzlast.liesStand(alsNotiz))
    }

    @Test
    fun `eine Notiz ohne Freigabe traegt eine leere Freigabekennung`() {
        val ohne = notiz.copy(baumFreigabe = null)
        val inhalt = Nutzlast.notizInhalt(ohne, "notiz", "handy")
        assertEquals("", inhalt["freigabeId"]!!.jsonPrimitive.content)
        // Und wird auf der Gegenseite folgerichtig nicht angenommen.
        assertEquals(null, Nutzlast.lies(inhalt, "partner1"))
    }
}
