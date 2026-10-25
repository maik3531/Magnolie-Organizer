package io.gitlab.maik3531.magnolienotes.ui

import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import org.junit.Assert.*
import org.junit.Test

class EintragDruckenTest {
    @Test fun notePrintUsesTheCurrentDraftAndEscapesEveryTextField() {
        val saved = Notiz("owned", titel = "Old title", text = "Old text", angelegt = 10, geaendert = 20)
        val draft = saved.copy(titel = "<script>owned</script>", text = "New draft & details\nSecond line")
        val html = EintragDrucken.notizHtml(draft, "Note")
        assertTrue(html.contains("&lt;script&gt;owned&lt;/script&gt;"))
        assertFalse(html.contains("<script>")); assertFalse(html.contains("Old text"))
        assertTrue(html.contains("New draft &amp; details\nSecond line"))
        assertEquals(20L, draft.geaendert); assertEquals("Old text", saved.text)
    }
    @Test fun taskPrintUsesCurrentTitleBodyDuePriorityAndCompletion() {
        val task = Aufgabe("owned-task", titel = "Owned draft", notiz = "Current <body>", faellig = "2026-10-25", prio = 1, erledigt = true)
        val html = EintragDrucken.aufgabeHtml(task, "Task", "Due", "Priority", "Done")
        assertTrue(html.contains("Owned draft")); assertTrue(html.contains("Current &lt;body&gt;"))
        assertTrue(html.contains("Due: 2026-10-25")); assertTrue(html.contains("Priority: 1")); assertTrue(html.contains("✓"))
        assertEquals(0L, task.geaendert)
    }
    @Test fun externalAndActiveImageSourcesCannotBecomePrintNetworkRequests() {
        val note = Notiz("owned-attachments", anhaenge = listOf(
            Anhang("outside", "<outside>", "image", "https://outside.invalid/image.png"),
            Anhang("active", "Active source", "image", "data:image/svg+xml,<svg onload='owned'/>")
        ))
        val html = EintragDrucken.notizHtml(note, "Note")
        assertFalse(html.contains("<img")); assertFalse(html.contains("outside.invalid")); assertFalse(html.contains("onload"))
        assertTrue(html.contains("&lt;outside&gt;")); assertTrue(html.contains("Active source"))
    }
}
