package io.gitlab.maik3531.magnolienotes.daten

import java.time.LocalDate

enum class AufgabenSortierung { FAELLIGKEIT, ERSTELLT, GEAENDERT, PRIORITAET, MANUELL }
enum class NotizenSortierung { DATUM, GEAENDERT }

data class ListenAnzeige(
    val aufgaben: AufgabenSortierung = AufgabenSortierung.FAELLIGKEIT,
    val aufgabenAbsteigend: Boolean = false,
    val notizen: NotizenSortierung = NotizenSortierung.DATUM,
    val notizenAbsteigend: Boolean = true,
    val tagesgruppen: Boolean = true
)

/** View projection only: never rewrite timestamps, identities or the manual sibling order. */
object ListenSortierung {
    fun notizZeit(note: Notiz, mode: NotizenSortierung): Long? = when (mode) {
        NotizenSortierung.DATUM -> note.angelegt.takeIf { it > 0 } ?: note.geaendert.takeIf { it > 0 }
        NotizenSortierung.GEAENDERT -> note.geaendert.takeIf { it > 0 }
    }

    fun notizen(input: List<Notiz>, options: ListenAnzeige): List<Notiz> = input.sortedWith { a, b ->
        bekannt(notizZeit(a, options.notizen), notizZeit(b, options.notizen), options.notizenAbsteigend)
            .takeIf { it != 0 } ?: a.id.compareTo(b.id)
    }

    fun aufgaben(input: List<Aufgabe>, options: ListenAnzeige): List<HierarchischeAufgabe> {
        if (options.aufgaben == AufgabenSortierung.MANUELL) return AufgabenHierarchie.flach(input)
        val dueDates = input.associate { it.id to runCatching { LocalDate.parse(it.faellig) }.getOrNull() }
        val comparator = Comparator<Aufgabe> { a, b ->
            a.erledigt.compareTo(b.erledigt).takeIf { it != 0 } ?: when (options.aufgaben) {
                AufgabenSortierung.FAELLIGKEIT -> bekannt(dueDates[a.id], dueDates[b.id], options.aufgabenAbsteigend)
                AufgabenSortierung.ERSTELLT -> bekannt(a.angelegt.takeIf { it > 0 }, b.angelegt.takeIf { it > 0 }, options.aufgabenAbsteigend)
                AufgabenSortierung.GEAENDERT -> bekannt(a.geaendert.takeIf { it > 0 }, b.geaendert.takeIf { it > 0 }, options.aufgabenAbsteigend)
                AufgabenSortierung.PRIORITAET -> if (options.aufgabenAbsteigend) b.prio.coerceIn(1, 3).compareTo(a.prio.coerceIn(1, 3))
                    else a.prio.coerceIn(1, 3).compareTo(b.prio.coerceIn(1, 3))
                AufgabenSortierung.MANUELL -> 0
            }
        }
        return AufgabenHierarchie.flach(input, comparator)
    }

    private fun <T : Comparable<T>> bekannt(a: T?, b: T?, descending: Boolean): Int = when {
        a == null && b == null -> 0
        a == null -> 1
        b == null -> -1
        descending -> b.compareTo(a)
        else -> a.compareTo(b)
    }
}
