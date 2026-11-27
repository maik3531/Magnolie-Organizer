package io.gitlab.maik3531.magnolienotes.baum

/** Continue after the last attempted peer, even when a slow route exhausts the probe budget. */
internal class FernAbgleichReihenfolge {
    private var zuletzt: String? = null

    @Synchronized
    fun naechste(kennungen: List<String>): List<String> {
        if (kennungen.isEmpty()) return emptyList()
        val start = (kennungen.indexOfFirst { it == zuletzt } + 1) % kennungen.size
        return List(minOf(32, kennungen.size)) { kennungen[(start + it) % kennungen.size] }
    }

    /** Advance only when the caller actually starts a probe, never when merely planning a round. */
    @Synchronized
    fun versucht(kennung: String) {
        zuletzt = kennung
    }
}
