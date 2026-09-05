package io.gitlab.maik3531.magnolienotes.daten

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AufgabenHierarchieTest {
    @Test fun `10k tiefe Hierarchie bleibt iterativ und geordnet`() {
        val tasks = (0 until 10_000).map { index ->
            Aufgabe("id-$index", uid = "uid-$index",
                elternUid = if (index == 0) "" else "uid-${index - 1}", reihenfolge = 0)
        }
        val flat = AufgabenHierarchie.flach(tasks)
        assertEquals(10_000, flat.size)
        assertEquals(9_999, flat.last().tiefe)
    }

    @Test fun `Waisen Selbstbezug Duplikate und Zyklen werden deterministisch normalisiert`() {
        val input = listOf(
            Aufgabe("b", uid = "cycle-b", elternUid = "cycle-a", reihenfolge = -2),
            Aufgabe("a", uid = "cycle-a", elternUid = "cycle-b", reihenfolge = 7),
            Aufgabe("orphan", uid = "orphan", elternUid = "missing"),
            Aufgabe("self", uid = "self", elternUid = "self"),
            Aufgabe("dup-2", uid = "duplicate"), Aufgabe("dup-1", uid = "duplicate")
        )
        val first = AufgabenHierarchie.normalisieren(input)
        assertEquals(first, AufgabenHierarchie.normalisieren(input))
        assertEquals("", first.single { it.uid == "cycle-a" }.elternUid)
        assertEquals("", first.single { it.id == "orphan" }.elternUid)
        assertEquals("", first.single { it.id == "self" }.elternUid)
        assertEquals(first.size, first.map(Aufgabe::uid).distinct().size)
        assertTrue(first.all { it.reihenfolge >= 0 })
    }

    @Test fun `Elternwechsel Bewegung Wurzel und Loeschen schuetzen den Graphen`() {
        val root = Aufgabe("root", uid = "root", reihenfolge = 0)
        val first = Aufgabe("first", uid = "first", elternUid = "root", reihenfolge = 0)
        val grandchild = Aufgabe("grand", uid = "grand", elternUid = "first", reihenfolge = 0)
        val second = Aufgabe("second", uid = "second", elternUid = "root", reihenfolge = 1)
        val tasks = listOf(root, first, grandchild, second)
        assertNull(AufgabenHierarchie.elternSetzen(tasks, "root", "grand"))
        assertNull(AufgabenHierarchie.elternSetzen(tasks, "first", "first"))
        val moved = AufgabenHierarchie.verschieben(tasks, "second", -1)!!
        assertEquals(0, moved.single { it.uid == "second" }.reihenfolge)
        val rooted = AufgabenHierarchie.elternSetzen(tasks, "grand", "")!!
        assertEquals("", rooted.single { it.uid == "grand" }.elternUid)
        val deleted = AufgabenHierarchie.loeschenUndKinderHochheben(tasks, "first")
        assertFalse(deleted.any { it.uid == "first" })
        assertEquals("root", deleted.single { it.uid == "grand" }.elternUid)
    }

    @Test fun `altes Archiv erhaelt ids und migriert flache Aufgaben`() {
        val migrated = PortableArchiv.migrieren(1, Bestand(aufgaben = listOf(Aufgabe("legacy"))))
        assertEquals("legacy", migrated.aufgaben.single().id)
        assertEquals(AufgabenHierarchie.stabileUid("legacy"), migrated.aufgaben.single().uid)
    }

    @Test fun `doppelte UIDs werden ersetzt und gleiche IDs erhalten fortlaufende Salze`() {
        val input = listOf(Aufgabe("gleich", uid = "doppelt"), Aufgabe("gleich", uid = "doppelt"))
        val result = AufgabenHierarchie.normalisieren(input)
        assertEquals(AufgabenHierarchie.stabileUid("gleich"), result[0].uid)
        assertEquals(AufgabenHierarchie.stabileUid("gleich", "0"), result[1].uid)
        assertEquals(result, AufgabenHierarchie.normalisieren(input))
    }

    @Test fun `reservierte UIDs bleiben erhalten und Eltern zeigen weiter auf sie`() {
        val reserved = AufgabenHierarchie.stabileUid("a")
        val input = listOf(
            Aufgabe("a"),
            Aufgabe("z", uid = reserved),
            Aufgabe("kind", uid = "kind", elternUid = reserved),
        )
        val result = AufgabenHierarchie.normalisieren(input)
        assertEquals(AufgabenHierarchie.stabileUid("a", "0"), result[0].uid)
        assertEquals(reserved, result[1].uid)
        assertEquals(reserved, result[2].elternUid)
    }

    @Test fun `ungueltige Reihenfolge verwendet den Eingabeindex`() {
        val result = AufgabenHierarchie.normalisieren(listOf(
            Aufgabe("spaet", uid = "spaet", reihenfolge = 5),
            Aufgabe("fallback", uid = "fallback", reihenfolge = -1),
        ))
        assertEquals(0, result.single { it.uid == "fallback" }.reihenfolge)
        assertEquals(1, result.single { it.uid == "spaet" }.reihenfolge)
    }

    @Test(timeout = 5_000) fun `adversarische Reservierungen bleiben linear und deterministisch`() {
        val reserved = (0 until 1_000).map { index ->
            AufgabenHierarchie.stabileUid("gleich", if (index == 0) "" else (index - 1).toString())
        }
        val input = List(2_000) { Aufgabe("gleich") } + reserved.mapIndexed { index, uid ->
            Aufgabe("z-${index.toString().padStart(4, '0')}", uid = uid)
        }
        val result = AufgabenHierarchie.normalisieren(input)
        assertEquals("mag-task-c550891a472d30da@magnolie-organizer", result.first().uid)
        assertEquals("mag-task-93262cbd5f907f91@magnolie-organizer", result[1_999].uid)
        assertEquals(reserved, result.drop(2_000).map(Aufgabe::uid))
        assertEquals(result, AufgabenHierarchie.normalisieren(input))
    }

    @Test fun `Kinder ersetzen geloeschten Parent ohne sich mit Geschwistern zu mischen`() {
        val tasks = listOf(
            Aufgabe("before", uid = "before", reihenfolge = 0),
            Aufgabe("parent", uid = "parent", reihenfolge = 1),
            Aufgabe("after", uid = "after", reihenfolge = 2),
            Aufgabe("child-b", uid = "child-b", elternUid = "parent", reihenfolge = 1),
            Aufgabe("child-a", uid = "child-a", elternUid = "parent", reihenfolge = 0))
        val result = AufgabenHierarchie.loeschenUndKinderHochheben(tasks, "parent")
            .filter { it.elternUid.isEmpty() }.sortedBy { it.reihenfolge }.map { it.uid }
        assertEquals(listOf("before", "child-a", "child-b", "after"), result)
    }

    @Test fun `Restore einer Teilaufgabe ohne Parent hebt sie sicher zur Wurzel`() {
        val child = Aufgabe("child", uid = "child", elternUid = "parent")
        val deleted = PapierkorbLogik.loescheAufgabe(Bestand(aufgaben = listOf(
            Aufgabe("parent", uid = "parent"), child)), "child", 1)
        val trashId = deleted.papierkorb.single().id
        assertTrue(PapierkorbLogik.wiederherstellen(deleted, trashId) != null)
        val withoutParent = deleted.copy(aufgaben = emptyList())
        val restored = PapierkorbLogik.wiederherstellen(withoutParent, trashId)!!
        assertEquals("", restored.aufgaben.single().elternUid)
        assertTrue(restored.papierkorb.isEmpty())
    }

    @Test fun `technische Kennungen verwenden plattformuebergreifend UTF-8-Reihenfolge`() {
        val input = listOf("ä", "z", "\uD800\uDC00", "a", "é", "e\u0301", "\uE000")
            .reversed().map { Aufgabe(it, uid = it, reihenfolge = 0) }
        val result = AufgabenHierarchie.normalisieren(input).sortedBy(Aufgabe::reihenfolge)
        assertEquals(listOf("a", "e\u0301", "z", "ä", "é", "\uE000", "\uD800\uDC00"),
            result.map(Aufgabe::uid))
    }
}
