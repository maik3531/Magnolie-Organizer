package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.Freigabe
import io.gitlab.maik3531.magnolienotes.daten.Notiz

object Synchronisation {
    data class VorbereiteteNotiz(val notiz: Notiz, val art: String)
    data class VollsyncPlan(
        val notizen: List<VorbereiteteNotiz>,
        val aufgaben: List<Aufgabe>,
        val syncAnfrage: Boolean
    )

    fun planen(
        notizen: List<Notiz>,
        aufgaben: List<Aufgabe>,
        partnerKennung: String,
        eigeneKennung: String,
        jetzt: Long,
        mitAnfrage: Boolean
    ) = VollsyncPlan(
        notizen.map { notizVorbereiten(it, partnerKennung, eigeneKennung, jetzt) },
        eigeneAufgaben(aufgaben),
        mitAnfrage
    )

    fun notizVorbereiten(
        notiz: Notiz,
        partnerKennung: String,
        eigeneKennung: String,
        jetzt: Long
    ): VorbereiteteNotiz {
        val bisher = notiz.baumFreigabe
        val istNeu = bisher?.partner?.contains(partnerKennung) != true
        val freigabe = bisher ?: Freigabe(io.gitlab.maik3531.magnolienotes.daten.Ablage.kennung())
        return VorbereiteteNotiz(
            notiz.copy(
                baumFreigabe = freigabe.copy(
                    partner = (freigabe.partner + partnerKennung).distinct(),
                    anhangPartner = (freigabe.anhangPartner + partnerKennung).distinct()
                ),
                baumGeaendert = if (notiz.baumGeaendert > 0) notiz.baumGeaendert else jetzt,
                baumVersion = if (notiz.baumVersion > 0) notiz.baumVersion else 1L,
                baumQuelle = notiz.baumQuelle.ifBlank { eigeneKennung },
                persoenlichVerknuepft = notiz.persoenlichVerknuepft || notiz.baumQuelle.isBlank()
            ),
            if (istNeu) "notiz" else "notiz_sync"
        )
    }

    fun eigeneAufgaben(aufgaben: List<Aufgabe>): List<Aufgabe> = aufgaben.filterNot { it.istFremd }
}
