package io.gitlab.maik3531.magnolienotes.baum

/** Native decision core only. Persistence/UI/transport must be joined before
 * enabling automatic return; this session core alone is not the finished feature.
 * None of these types is a portable contact/tree setting or wire grant.
 */
internal class KontaktOriginalFreigaben(private val aktuellerPartner: () -> Partner?) {
    data class Partner(val kennung: String, val schluessel: String)
    data class Quelle(val datenbank: Long, val konto: KontaktOriginalBindung.Quelle)
    private class Beleg(val scope: KontaktOriginalFreigaben, val generation: Long,
                        val bindung: KontaktOriginalBindung, val quelle: Quelle)
    class Freigabe internal constructor(internal val bindung: KontaktOriginalBindung, private val beleg: Any) {
        fun pruefen() = pruefen(versionPruefen = true)
        internal fun pruefenNachSchreiben() = pruefen(versionPruefen = false)
        private fun pruefen(versionPruefen: Boolean) {
            val native = beleg as? Beleg ?: throw SecurityException("contact_original_native_decision_required")
            if (native.bindung !== bindung) throw SecurityException("contact_original_native_decision_retargeted")
            native.scope.pruefen(native, versionPruefen)
        }
    }
    private val lock = Any()
    private var generation = 0L
    private var partner: Partner? = null
    private var quellen: Set<Quelle> = emptySet()
    val gewuenscht: Boolean get() = synchronized(lock) { quellen.isNotEmpty() }

    /** Explicit native setup entry, not called by deserialization or discovery.
     * Cancel preserves the previous decision; empty selection explicitly revokes.
     */
    fun einrichten(bindungen: List<KontaktOriginalBindung>, waehlen: (List<Quelle>) -> Set<Quelle>?): Boolean {
        val originals = bindungen.toList()
        require(originals.size <= 1000)
        val expectedGeneration = synchronized(lock) { generation }
        val peer = aktuellerPartner() ?: throw SecurityException("contact_original_peer_unavailable")
        require(peer.kennung.isNotBlank() && peer.schluessel.isNotBlank())
        originals.forEach { it.aktuell() }
        val choices = originals.map(::quelle).distinct()
        require(choices.size <= 32)
        val selected = waehlen(choices.toList())?.toSet() ?: return false
        require(selected.all { it in choices }) { "contact_original_source_not_offered" }
        require(aktuellerPartner() == peer) { "contact_original_peer_changed" }
        originals.filter { quelle(it) in selected }.forEach { it.aktuell() }
        require(aktuellerPartner() == peer) { "contact_original_peer_changed" }
        synchronized(lock) {
            check(generation == expectedGeneration) { "contact_original_decision_changed" }
            partner = peer; quellen = selected.toSet(); generation++
        }
        return true
    }

    fun widerrufen() = synchronized(lock) { generation++; quellen = emptySet(); partner = null }

    fun freigabe(bindung: KontaktOriginalBindung): Freigabe {
        val key = quelle(bindung)
        val native = synchronized(lock) {
            if (key !in quellen) throw SecurityException("contact_original_source_not_granted")
            Beleg(this, generation, bindung, key)
        }
        return Freigabe(bindung, native).also { it.pruefen() }
    }

    private fun pruefen(beleg: Beleg, versionPruefen: Boolean) {
        fun current(): Partner = synchronized(lock) {
            if (generation != beleg.generation || beleg.quelle !in quellen)
                throw SecurityException("contact_original_source_not_granted")
            partner ?: throw SecurityException("contact_original_source_not_granted")
        }
        val peer = current()
        if (aktuellerPartner() != peer) throw SecurityException("contact_original_peer_unavailable")
        if (versionPruefen) beleg.bindung.aktuell()
        if (aktuellerPartner() != peer || quelle(beleg.bindung) != beleg.quelle || current() != peer)
            throw SecurityException("contact_original_native_decision_changed")
    }

    private fun quelle(bindung: KontaktOriginalBindung) = Quelle(bindung.datenbankErstellt, bindung.quelle)
}
