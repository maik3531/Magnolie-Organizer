package io.gitlab.maik3531.magnolienotes.daten

import java.time.LocalDate
import java.time.Instant
import java.time.ZoneId
import org.junit.Assert.*
import org.junit.Test

class EintragSucheTest {
    private val berlin = ZoneId.of("Europe/Berlin")
    private fun zeit(tag: String) = LocalDate.parse(tag).atStartOfDay(berlin).toInstant().toEpochMilli()

    @Test fun beideMonatsangabenFindenAnlageUndAenderungAberKeineAnderenMonate() {
        for (query in listOf("09.2026", "09.26", "9.26", " 09.2026 ", "2026-09")) {
            val suche = EintragSuche(query, berlin)
            assertTrue(suche.notizPasst(Notiz("created", angelegt = zeit("2026-09-01"))))
            assertTrue(suche.notizPasst(Notiz("changed", angelegt = zeit("2026-07-01"), geaendert = zeit("2026-09-30"))))
            for (day in listOf("2026-08-31", "2026-10-01", "2025-09-01"))
                assertFalse("$query: $day", suche.notizPasst(Notiz(day, angelegt = zeit(day))))
        }
    }

    @Test fun aufgabenFindenTitelInhaltAnlageAenderungUndFaelligkeit() {
        val suche = EintragSuche("09.26", berlin)
        assertTrue(suche.aufgabePasst(Aufgabe("created", angelegt = zeit("2026-09-08"))))
        assertTrue(suche.aufgabePasst(Aufgabe("changed", geaendert = zeit("2026-09-08"))))
        assertTrue(suche.aufgabePasst(Aufgabe("due", faellig = "2026-09-30")))
        assertFalse(suche.aufgabePasst(Aufgabe("outside", faellig = "2026-10-01")))
        assertTrue(EintragSuche("PrOjEkT").aufgabePasst(Aufgabe("title", titel = "Projekt planen")))
        assertTrue(EintragSuche("abholen").aufgabePasst(Aufgabe("body", notiz = "Paket abholen")))
        assertTrue(EintragSuche("projekt").notizPasst(Notiz("n", text = "PROJEKT besprochen")))
    }

    @Test fun tagJahrUndSchalttagSindStriktUndZweistelligeJahreStabil() {
        for (q in listOf("18.09.2026", "18.9.26", "2026-09-18")) {
            val suche = EintragSuche(q, berlin)
            assertTrue(suche.notizPasst(Notiz("yes", angelegt = zeit("2026-09-18"))))
            assertFalse(suche.notizPasst(Notiz("no", angelegt = zeit("2026-09-19"))))
        }
        assertTrue(EintragSuche("2026", berlin).aufgabePasst(Aufgabe("year", faellig = "2026-12-31")))
        assertTrue(EintragSuche("29.02.24", berlin).aufgabePasst(Aufgabe("leap", faellig = "2024-02-29")))
        assertFalse(EintragSuche("09.99", berlin).notizPasst(Notiz("old", angelegt = zeit("1999-09-01"))))
        for (q in listOf("29.02.26", "31.09.26", "13.26", "00.2026", "2026-13", "no date"))
            assertFalse(q, EintragSuche(q, berlin).aufgabePasst(Aufgabe("bad", faellig = "2026-09-01", angelegt = zeit("2026-09-01"))))
    }

    @Test fun unbekannteZeitenWerdenNichtAlsJanuar1970ErfundenUndTextBleibtSuchbar() {
        assertFalse(EintragSuche("01.1970").notizPasst(Notiz("unknown")))
        assertFalse(EintragSuche("09.26").aufgabePasst(Aufgabe("invalid", faellig = "2026-09-31")))
        assertTrue(EintragSuche("31.09.26").notizPasst(Notiz("literal", text = "Termin 31.09.26 korrigieren")))
        assertTrue(EintragSuche("  ").notizPasst(Notiz("empty")))
        assertTrue(EintragSuche("").aufgabePasst(Aufgabe("empty")))
    }

    @Test fun monatsgrenzeVerwendetLokalenTagUndKeineUtcOderFix24StundenAnnahme() {
        val instant = Instant.parse("2026-08-31T22:30:00Z").toEpochMilli()
        val note = Notiz("boundary", angelegt = instant)
        assertTrue(EintragSuche("09.26", berlin).notizPasst(note))
        assertFalse(EintragSuche("09.26", ZoneId.of("UTC")).notizPasst(note))
        val dst = Notiz("dst", angelegt = Instant.parse("2026-10-25T22:30:00Z").toEpochMilli())
        assertTrue(EintragSuche("25.10.26", berlin).notizPasst(dst))
        assertFalse(EintragSuche("26.10.26", berlin).notizPasst(dst))
    }

    @Test fun filterBehältHierarchieTiefeUndQuellobjekteAuchBeiVerstecktenEltern() {
        val parent = Aufgabe("parent", titel = "Eltern", uid = "parent")
        val child = Aufgabe("child", titel = "Treffer", uid = "child", elternUid = "parent", faellig = "2026-09-10")
        val source = listOf(parent, child)
        val projection = ListenSortierung.aufgaben(source, ListenAnzeige(aufgaben = AufgabenSortierung.MANUELL))
        val result = projection.filter { EintragSuche("09.26", berlin).aufgabePasst(it.aufgabe) }
        assertEquals(listOf("child"), result.map { it.aufgabe.id })
        assertEquals(1, result.single().tiefe)
        assertEquals("parent", result.single().aufgabe.elternUid)
        assertEquals(listOf(parent, child), source)
        assertEquals(projection, projection.filter { EintragSuche("").aufgabePasst(it.aufgabe) })
    }
}
