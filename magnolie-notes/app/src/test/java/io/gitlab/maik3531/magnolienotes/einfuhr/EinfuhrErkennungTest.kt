package io.gitlab.maik3531.magnolienotes.einfuhr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Refs #822: unrelated exports must retain their text, origin and file time. */
class EinfuhrErkennungTest {
    private val fileTime = 1_700_000_000_000L
    private fun read(text: String, name: String) = Einfuhr.ausInhalt(text.toByteArray(), name, fileTime).single()

    @Test fun `allgemeines JSON mit Titel verliert keine unbekannten Inhaltsfelder`() {
        val raw = """{"title":"Example","body":"important","extra":{"value":"Keep this too"}}"""
        val note = read(raw, "ordinary.json")
        assertEquals(raw, note.text)
        assertEquals("Übernommen", note.herkunft)
        assertEquals(fileTime, note.angelegt)
        assertEquals(fileTime, note.geaendert)
    }

    @Test fun `gemischtes JSON Array wird vollstaendig als Text erhalten`() {
        for (raw in listOf("""[{"title":"Keep","textContent":"Known"},{"title":"Other","body":"Important"}]""",
            """[{"title":"Keep","textContent":"Known"},"Important"]""")) {
            val note = read(raw, "mixed.json")
            assertEquals(raw, note.text)
            assertEquals("Übernommen", note.herkunft)
        }
    }

    @Test fun `Samsung HTML behaelt Herkunft und Dateizeit`() {
        val raw = "<html><head><title>Samsung export</title></head><body><div>One</div><div>Two</div></body></html>"
        val note = read(raw, "samsung-export.html")
        assertEquals("Samsung Notes", note.herkunft)
        assertEquals("Samsung Notes", note.notizbuch)
        assertEquals("Samsung export", note.titel)
        assertEquals(fileTime, note.angelegt)
        assertEquals(fileTime, note.geaendert)
        assertTrue(note.html.contains("One"))
        assertTrue(note.html.contains("Two"))
    }

    @Test fun `Browser HTML und allgemeine CSS Klassen sind kein Takeout Nachweis`() {
        for (heading in listOf("", "<div class=\"heading\">Section</div>")) {
            val note = read("<html><body>$heading<div class=\"title\">Heading</div><div class=\"content\">Important</div></body></html>",
                "page.html")
            assertEquals("Übernommen", note.herkunft)
            assertEquals(fileTime, note.angelegt)
            assertTrue(note.html.contains("Heading") && note.html.contains("Important"))
        }
    }

    @Test fun `unspezifische oder unvollstaendige Listen werden nicht gekuerzt`() {
        for (raw in listOf(
            """{"title":"Generic","listContent":[{"value":"preserve me"}],"body":"extra content"}""",
            """[{"title":"Good","textContent":"recognized"},{"title":"Mixed","listContent":[{"text":"part","isChecked":false},42]}]"""
        )) {
            val note = read(raw, "ordinary.json")
            assertEquals(raw, note.text)
            assertEquals("Übernommen", note.herkunft)
        }
    }

    @Test fun `Keep Text Listen und Titelnotizen mit Zeitmetadaten bleiben erkannt`() {
        val raw = """[{"title":"Text","textContent":"Known"},
            {"title":"List","listContent":[{"text":"Done","isChecked":true}]},
            {"title":"Title only","createdTimestampUsec":1700000000000000,"userEditedTimestampUsec":1700000001000000}]"""
        val notes = Einfuhr.ausInhalt(raw.toByteArray(), "takeout.json", fileTime)
        assertEquals(3, notes.size)
        assertTrue(notes.all { it.herkunft == "Google Keep" })
        assertEquals("Known", notes[0].text)
        assertEquals("[x] Done", notes[1].text)
        assertEquals("Title only", notes[2].titel)
        assertEquals(1_700_000_001_000L, notes[2].geaendert)
    }

    @Test fun `unterstuetztes Keep HTML behaelt Inhalt und Herkunft`() {
        val raw = "<html><body><div class=\"heading\">Nov 14, 2023, 10:13:20 PM</div>" +
            "<div class=\"title\">Keep title</div><div class=\"content\">Keep content</div></body></html>"
        val note = read(raw, "keep.html")
        assertEquals("Google Keep", note.herkunft)
        assertEquals("Keep title", note.titel)
        assertEquals("Keep content", note.html)
        assertTrue(note.angelegt > 0)
    }
}
