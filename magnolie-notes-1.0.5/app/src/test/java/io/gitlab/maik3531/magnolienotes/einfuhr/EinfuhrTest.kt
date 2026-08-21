package io.gitlab.maik3531.magnolienotes.einfuhr

import io.gitlab.maik3531.magnolienotes.daten.Symbol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Prüft die Übernahme an echten Ausschnitten der Exportformate, so wie
 * Google Takeout, Evernote und die anderen sie tatsächlich schreiben.
 */
class EinfuhrTest {

    private fun lies(text: String, name: String, wann: Long = 1_700_000_000_000L) =
        Einfuhr.ausInhalt(text.toByteArray(Charsets.UTF_8), name, wann)

    @Test
    fun `Google Keep JSON wird mit Datum und Uhrzeit uebernommen`() {
        val keep = """
            {
              "color": "DEFAULT",
              "isTrashed": false,
              "isPinned": false,
              "isArchived": false,
              "textContent": "Milch\nBrot\nÄpfel",
              "title": "Einkauf Samstag",
              "userEditedTimestampUsec": 1700000123456789,
              "createdTimestampUsec": 1699999000000000,
              "labels": [{"name": "Haushalt"}]
            }
        """.trimIndent()
        val notizen = lies(keep, "Einkauf Samstag.json")
        assertEquals(1, notizen.size)
        val n = notizen.first()
        assertEquals("Einkauf Samstag", n.titel)
        assertTrue(n.text.contains("Äpfel"))
        assertEquals("Google Keep", n.herkunft)
        assertEquals("Haushalt", n.notizbuch)
        // Mikrosekunden werden zu Millisekunden.
        assertEquals(1700000123456L, n.geaendert)
        assertEquals(1699999000000L, n.angelegt)
        assertEquals(Symbol.EINKAUF, n.zuNotiz("b").symbol)
    }

    @Test
    fun `Keep-Haekchenliste wird zur Aufgabenliste`() {
        val keep = """
            {"title":"Packliste","listContent":[
              {"text":"Zahnbürste","isChecked":true},
              {"text":"Ladegerät","isChecked":false},
              {"text":"Reisepass","isChecked":false}],
             "userEditedTimestampUsec":1700000000000000}
        """.trimIndent()
        val n = lies(keep, "Packliste.json").single()
        assertTrue(n.text.contains("[x] Zahnbürste"))
        assertTrue(n.text.contains("[ ] Reisepass"))
        // Reise sticht, weil „Reisepass“ und „Packliste“ deutlich sind.
        assertEquals(Symbol.REISE, n.zuNotiz("b").symbol)
    }

    @Test
    fun `Evernote enex liefert alle Notizen des Notizbuchs`() {
        val enex = """
            <?xml version="1.0" encoding="UTF-8"?>
            <en-export export-date="20240101T101010Z">
            <note><title>Erste Notiz</title>
            <content><![CDATA[<en-note><div>Hallo <b>Welt</b></div></en-note>]]></content>
            <created>20230815T142530Z</created><updated>20231002T090000Z</updated>
            </note>
            <note><title>Zweite Notiz</title>
            <content><![CDATA[<en-note><div>Noch etwas</div></en-note>]]></content>
            <created>20230816T142530Z</created><updated>20231003T090000Z</updated>
            </note>
            </en-export>
        """.trimIndent()
        val notizen = lies(enex, "Notizbuch.enex")
        assertEquals(2, notizen.size)
        assertEquals("Erste Notiz", notizen[0].titel)
        assertEquals("Evernote", notizen[0].herkunft)
        assertTrue("Der Zeitstempel fehlt", notizen[0].angelegt > 0)
        // Aus dem HTML wird lesbarer Text.
        assertTrue(notizen[0].zuNotiz("b").text.contains("Hallo"))
    }

    @Test
    fun `Simplenote-Sicherung wird gelesen`() {
        val roh = """
            {"activeNotes":[
              {"id":"a","content":"Einfall\n\nVielleicht könnte man …",
               "creationDate":"2024-03-01T10:00:00.000Z",
               "lastModified":"2024-03-02T11:30:00.000Z"}],
             "trashedNotes":[{"id":"b","content":"Weg damit"}]}
        """.trimIndent()
        val notizen = lies(roh, "notes.json")
        assertEquals("nur die aktiven Notizen gehören übernommen", 1, notizen.size)
        assertEquals("Einfall", notizen[0].titel)
        assertEquals(Symbol.IDEE, notizen[0].zuNotiz("b").symbol)
    }

    @Test
    fun `Standard Notes Sicherung wird gelesen`() {
        val roh = """
            {"items":[
              {"content_type":"Note","created_at":"2024-05-01T08:00:00.000Z",
               "updated_at":"2024-05-04T09:00:00.000Z",
               "content":{"title":"Besprechung","text":"Projekt Magnolie, Kunde ruft an"}},
              {"content_type":"Tag","content":{"title":"Arbeit"}}]}
        """.trimIndent()
        val notizen = lies(roh, "Standard Notes Backup.json")
        assertEquals(1, notizen.size)
        assertEquals("Besprechung", notizen[0].titel)
        assertEquals(Symbol.ARBEIT, notizen[0].zuNotiz("b").symbol)
    }

    @Test
    fun `Markdown wird an der Ueberschrift getrennt`() {
        val md = "# Rezept für Zwetschgenkuchen\n\nZutaten: 500 g Mehl, Teig ruhen lassen."
        val n = lies(md, "kuchen.md").single()
        assertEquals("Rezept für Zwetschgenkuchen", n.titel)
        assertTrue(n.text.startsWith("Zutaten"))
        assertEquals(Symbol.REZEPT, n.zuNotiz("b").symbol)
    }

    @Test
    fun `schlichter Text ohne Ueberschrift nimmt den Dateinamen`() {
        val n = lies("Nur eine Zeile ohne alles", "Meine_Gedanken.txt").single()
        assertEquals("Meine Gedanken", n.titel)
    }

    @Test
    fun `unverschluesseltes Desktop Gesamtarchiv wird nicht zur JSON Notiz`() {
        val archiv = """{"appversion":"2.0.0","daten":{"notizen":[{"text":"${"x".repeat(5000)}"}]},"datenschema":1,"fassung":1,"magnolie":"magnolie-gesamtarchiv"}"""
        assertThrows(GesamtarchivNichtUnterstuetzt::class.java) {
            lies(archiv, "desktop.magnolie")
        }
    }

    @Test
    fun `verschluesselte Magnolie Huelle wird nicht zur JSON Notiz`() {
        val archiv = """{"magnolie":"magnolie-verschluesselt","fassung":1,"verfahren":"AES-256-GCM/PBKDF2-SHA256","daten":"AA=="}"""
        assertThrows(GesamtarchivNichtUnterstuetzt::class.java) {
            lies(archiv, "desktop.magnolie")
        }
    }

    @Test
    fun `normale Text und Keep Importe bleiben unveraendert`() {
        assertEquals("Normale Notiz", lies("# Normale Notiz\n\nInhalt", "notiz.md").single().titel)
        val keep = lies("""{"title":"Keep","textContent":"Inhalt"}""", "keep.json").single()
        assertEquals("Keep", keep.titel)
        assertEquals("Google Keep", keep.herkunft)
    }

    @Test
    fun `Joplins Fusszeilen fallen weg`() {
        val joplin = "Notiz von Joplin\n\nDer eigentliche Text.\n\n" +
            "id: 0123456789abcdef0123456789abcdef\n" +
            "parent_id: fedcba9876543210fedcba9876543210\n" +
            "is_todo: 0\n"
        val n = lies(joplin, "notiz.md").single()
        assertTrue("Die Kennungszeilen gehören nicht in den Text", !n.text.contains("parent_id"))
        assertTrue(n.text.contains("Der eigentliche Text"))
    }

    @Test
    fun `ein Takeout-Archiv wird ausgepackt`() {
        val puffer = ByteArrayOutputStream()
        ZipOutputStream(puffer).use { zip ->
            fun schreibe(name: String, inhalt: String) {
                zip.putNextEntry(ZipEntry(name))
                zip.write(inhalt.toByteArray(Charsets.UTF_8))
                zip.closeEntry()
            }
            schreibe("Takeout/Keep/Erste.json",
                """{"title":"Erste","textContent":"Eins","userEditedTimestampUsec":1700000000000000}""")
            schreibe("Takeout/Keep/Zweite.json",
                """{"title":"Zweite","textContent":"Zwei","userEditedTimestampUsec":1700000001000000}""")
            schreibe("Takeout/archive_browser.html", "<html><body>Nichts</body></html>")
        }
        val notizen = Einfuhr.ausInhalt(puffer.toByteArray(), "takeout-keep.zip", 0L)
        val titel = notizen.map { it.titel }
        assertTrue("Erste fehlt: $titel", titel.contains("Erste"))
        assertTrue("Zweite fehlt: $titel", titel.contains("Zweite"))
    }

    @Test
    fun `kumulative Entpackgrenze verwirft das ganze Archiv`() {
        val archiv = zip(
            "eins.txt" to "123456",
            "zwei.txt" to "abcdef"
        )
        assertThrows(java.io.IOException::class.java) {
            Einfuhr.ausZip(archiv, "sicherung.magnolie", null, eintragMax = 8, archivEntpacktMax = 10)
        }
    }

    @Test
    fun `Einzelgrenze verwirft statt Teilergebnis zu liefern`() {
        val archiv = zip("gut.txt" to "gut", "zu-gross.txt" to "123456789")
        assertThrows(java.io.IOException::class.java) {
            Einfuhr.ausZip(archiv, "sicherung.magnolie", null, eintragMax = 8, archivEntpacktMax = 100)
        }
    }

    @Test
    fun `auch unbekannte Eintraege zaehlen zur kumulativen Grenze`() {
        val archiv = zip("ignoriert.bin" to "123456789", "gut.txt" to "gut")
        assertThrows(java.io.IOException::class.java) {
            Einfuhr.ausZip(archiv, "sicherung.magnolie", null, eintragMax = 20, archivEntpacktMax = 10)
        }
    }

    @Test
    fun `abgeschnittenes Archiv liefert kein Teilergebnis`() {
        val vollstaendig = zip("gut.txt" to "erste Notiz", "zweite.txt" to "zweite Notiz")
        val abgeschnitten = vollstaendig.copyOf(vollstaendig.size - 30)
        assertThrows(java.io.IOException::class.java) {
            Einfuhr.ausZip(abgeschnitten, "kaputt.magnolie", null)
        }
    }

    @Test
    fun `Samsung-HTML-Ausgabe wird als Notiz gelesen`() {
        val html = """
            <html><head><title>Gedanken vom Dienstag</title></head>
            <body><div>Erste Zeile</div><div>Zweite Zeile</div></body></html>
        """.trimIndent()
        val n = lies(html, "Gedanken vom Dienstag.html").single()
        assertEquals("Gedanken vom Dienstag", n.titel)
        val fertig = n.zuNotiz("b")
        assertTrue(fertig.text.contains("Erste Zeile"))
        assertTrue(fertig.text.contains("Zweite Zeile"))
    }

    @Test
    fun `leere und unlesbare Dateien liefern nichts`() {
        assertTrue(lies("", "leer.txt").isEmpty())
        assertTrue(lies("   \n  \n", "weiss.md").isEmpty())
    }

    @Test
    fun `derselbe Wortlaut ergibt denselben Einfuhrschluessel`() {
        val a = lies("# Titel\n\nText", "a.md").single().zuNotiz("b")
        val b = lies("#   Titel\n\nText  ", "andere-datei.md").single().zuNotiz("b")
        assertEquals(
            "Zweimal derselbe Wortlaut darf nicht zweimal in der Liste landen",
            a.einfuhrSchluessel, b.einfuhrSchluessel
        )
    }

    private fun zip(vararg eintraege: Pair<String, String>): ByteArray {
        val puffer = ByteArrayOutputStream()
        ZipOutputStream(puffer).use { zip ->
            eintraege.forEach { (name, inhalt) ->
                zip.putNextEntry(ZipEntry(name))
                zip.write(inhalt.toByteArray())
                zip.closeEntry()
            }
        }
        return puffer.toByteArray()
    }
}
