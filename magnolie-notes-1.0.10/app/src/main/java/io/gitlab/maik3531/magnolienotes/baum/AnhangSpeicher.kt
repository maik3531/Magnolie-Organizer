package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Anhang

/** Reine Kapazitätsrechnung; Android liefert nur den aktuellen freien Speicher. */
object AnhangSpeicher {
    const val RESERVE_BYTES = 256L * 1024 * 1024
    const val APP_MAX_BYTES = 512L * 1024 * 1024

    data class Entscheidung(
        val erlaubt: Boolean,
        val bisherBytes: Long,
        val danachBytes: Long,
        val appGrenzeBytes: Long,
        val notizGrenzeZeichen: Long
    )

    fun entscheide(
        bisherAlle: List<Anhang>,
        bisherNotiz: List<Anhang>,
        neuNotiz: List<Anhang>,
        freierSpeicherBytes: Long
    ): Entscheidung {
        val oberhalbReserve = (freierSpeicherBytes - RESERVE_BYTES).coerceAtLeast(0)
        val appGrenze = minOf(APP_MAX_BYTES, oberhalbReserve / 10)
        val einProzentRoh = oberhalbReserve / 100
        val notizGrenzeZeichen = minOf(
            Nutzlast.ANHANG_GESAMT_MAX.toLong(),
            einProzentRoh * 4 / 3
        )
        val bisher = rohBytes(bisherAlle)
        val danach = (bisher - rohBytes(bisherNotiz) + rohBytes(neuNotiz)).coerceAtLeast(0)
        val neuZeichen = neuNotiz.sumOf { Nutzlast.nutzlastZeichen(it.daten).toLong() }
        val differenz = (danach - bisher).coerceAtLeast(0)
        return Entscheidung(
            erlaubt = neuZeichen <= notizGrenzeZeichen && danach <= appGrenze &&
                differenz <= oberhalbReserve,
            bisherBytes = bisher,
            danachBytes = danach,
            appGrenzeBytes = appGrenze,
            notizGrenzeZeichen = notizGrenzeZeichen
        )
    }

    fun rohBytes(anhaenge: List<Anhang>): Long = anhaenge.sumOf {
        val zeichen = Nutzlast.nutzlastZeichen(it.daten).toLong()
        (zeichen * 3 / 4).coerceAtLeast(0)
    }
}
