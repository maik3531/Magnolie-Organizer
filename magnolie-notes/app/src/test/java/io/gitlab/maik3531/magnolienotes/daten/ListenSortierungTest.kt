package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.*
import org.junit.Test

class ListenSortierungTest {
    private fun task(id: String, due: String = "", order: Int = 0, done: Boolean = false, priority: Int = 2,
                     created: Long = 0, changed: Long = 0, parent: String = "") = Aufgabe(id = id, uid = id,
        titel = "Owned $id", faellig = due, reihenfolge = order, erledigt = done, prio = priority,
        angelegt = created, geaendert = changed, elternUid = parent)
    private fun ids(tasks: List<Aufgabe>, options: ListenAnzeige = ListenAnzeige()) =
        ListenSortierung.aufgaben(tasks, options).map { it.aufgabe.id }

    @Test fun defaultsMatchDueTasksAndDatedNotesWithDayGroupsEnabled() {
        val defaults = ListenAnzeige()
        assertEquals(AufgabenSortierung.FAELLIGKEIT, defaults.aufgaben)
        assertFalse(defaults.aufgabenAbsteigend)
        assertEquals(NotizenSortierung.DATUM, defaults.notizen)
        assertTrue(defaults.notizenAbsteigend); assertTrue(defaults.tagesgruppen)
    }

    @Test fun dueOrderKeepsUndatedAndCompletedTasksOutOfTheUpcomingHead() {
        val input = listOf(task("undated", order = 0), task("future", "2026-10-28", 1), task("today", "2026-10-25", 2),
            task("done", "2026-10-01", 3, done = true), task("invalid", "not-a-date", 4))
        val before = input.toList()
        assertEquals(listOf("today", "future", "undated", "invalid", "done"), ids(input))
        assertEquals(listOf("future", "today", "undated", "invalid", "done"), ids(input, ListenAnzeige(aufgabenAbsteigend = true)))
        assertEquals(before, input)
    }

    @Test fun hierarchyAndManualSiblingOrderRemainIntactWhenChangingTheView() {
        val input = listOf(task("root", "2026-10-25", 0), task("child-later", "2026-10-28", 0, parent = "root"),
            task("child-earlier", "2026-10-24", 1, parent = "root"), task("other-root", "2026-10-26", 1))
        val sorted = ListenSortierung.aufgaben(input, ListenAnzeige())
        assertEquals(listOf("root", "child-earlier", "child-later", "other-root"), sorted.map { it.aufgabe.id })
        assertEquals(listOf(0, 1, 1, 0), sorted.map { it.tiefe })
        assertEquals(listOf("root", "child-later", "child-earlier", "other-root"), ids(input, ListenAnzeige(aufgaben = AufgabenSortierung.MANUELL)))
        assertEquals(0, input[1].reihenfolge); assertEquals(1, input[2].reihenfolge)
    }

    @Test fun priorityCreatedAndModifiedAreSeparateNumericCriteria() {
        val input = listOf(task("a", order = 0, priority = 3, created = 100, changed = 300),
            task("b", order = 1, priority = 1, created = 300, changed = 100), task("c", order = 2, priority = 2, created = 200, changed = 200))
        assertEquals(listOf("b", "c", "a"), ids(input, ListenAnzeige(aufgaben = AufgabenSortierung.PRIORITAET)))
        assertEquals(listOf("a", "c", "b"), ids(input, ListenAnzeige(aufgaben = AufgabenSortierung.ERSTELLT)))
        assertEquals(listOf("b", "c", "a"), ids(input, ListenAnzeige(aufgaben = AufgabenSortierung.GEAENDERT)))
        assertEquals(listOf("a", "c", "b"), ids(input, ListenAnzeige(aufgaben = AufgabenSortierung.GEAENDERT, aufgabenAbsteigend = true)))
    }

    @Test fun notesCanUseOriginalDateOrLastChangeWithoutMutatingTheirContent() {
        val first = Notiz("a", text = "Owned original content", angelegt = 100, geaendert = 300, herkunft = "Owned imported source")
        val second = Notiz("b", angelegt = 200, geaendert = 150)
        val unknown = Notiz("unknown")
        val input = listOf(first, second, unknown)
        assertEquals(listOf("b", "a", "unknown"), ListenSortierung.notizen(input, ListenAnzeige()).map { it.id })
        assertEquals(listOf("a", "b", "unknown"), ListenSortierung.notizen(input, ListenAnzeige(notizen = NotizenSortierung.GEAENDERT)).map { it.id })
        assertEquals(listOf("a", "b", "unknown"), ListenSortierung.notizen(input, ListenAnzeige(notizenAbsteigend = false)).map { it.id })
        assertEquals("Owned original content", first.text); assertEquals(100L, first.angelegt); assertEquals(300L, first.geaendert)
        assertEquals("Owned imported source", first.herkunft)
    }

    @Test fun missingTimesStayLastAndLegacyDayProjectionRetainsItsExistingFallback() {
        val legacy = Notiz("legacy", angelegt = 0, geaendert = 200)
        assertEquals(200L, ListenSortierung.notizZeit(legacy, NotizenSortierung.DATUM))
        assertNull(ListenSortierung.notizZeit(Notiz("unknown"), NotizenSortierung.GEAENDERT))
        for (descending in listOf(false, true)) {
            assertEquals(listOf("known", "unknown"), ids(listOf(task("unknown", order = 0), task("known", order = 1, created = 10)),
                ListenAnzeige(aufgaben = AufgabenSortierung.ERSTELLT, aufgabenAbsteigend = descending)))
        }
    }
}
