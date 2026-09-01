package io.gitlab.maik3531.magnolienotes.baum

object AutoSync {
    const val ABSTAND_MS = 6L * 60 * 60 * 1000

    fun sollLaufen(
        eingeschaltet: Boolean,
        dienstLaeuft: Boolean,
        istWlan: Boolean,
        letzteAusfuehrung: Long,
        jetzt: Long,
        hatPartner: Boolean
    ): Boolean = eingeschaltet && dienstLaeuft && istWlan && hatPartner &&
        jetzt - letzteAusfuehrung >= ABSTAND_MS
}
