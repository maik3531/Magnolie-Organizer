package io.gitlab.maik3531.magnolienotes.baum

/** Native decision core only. Actual UI/transport/journal/receipt must be joined
 * before enabling automatic return; these native APIs alone are not the feature.
 * None of these types is a portable contact/tree setting or wire grant.
 */
internal class KontaktOriginalFreigaben(private val dauerStore: KontaktOriginalDauerfreigaben? = null,
                                      private val aktuellerPartner: () -> Partner?) {
    data class Partner(val kennung: String, val schluessel: String)
    data class Quelle(val datenbank: Long, val konto: KontaktOriginalBindung.Quelle)
    private class Beleg(val scope: KontaktOriginalFreigaben, val generation: Long,
                        val bindung: KontaktOriginalBindung, val quelle: Quelle)
    private class SetupBeleg(val scope: KontaktOriginalFreigaben, val generation: Long,
        val partner: Partner, val quellen: Set<Quelle>, val originale: List<KontaktOriginalBindung>)
    class Entscheidung internal constructor(private val beleg: Any) {
        private fun native(): SetupBeleg = (beleg as? SetupBeleg)
            ?: throw SecurityException("contact_original_native_setup_required")
        fun pruefen() { native().let { it.scope.pruefen(it) } }
        fun partner(): Partner = native().also { pruefen() }.partner
        fun quellen(): Set<Quelle> = native().also { pruefen() }.quellen.toSet()
    }
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
    private var setup: SetupBeleg? = null
    private var dauer: KontaktOriginalDauerfreigaben.Gespeichert? = null
    private var blockiert = false
    val gewuenscht: Boolean get() = synchronized(lock) { quellen.isNotEmpty() }

    /** Explicit native setup entry, not called by deserialization or discovery.
     * Cancel preserves the previous decision; empty selection explicitly revokes.
     */
    fun einrichten(bindungen: List<KontaktOriginalBindung>, speichern: ((Entscheidung) -> Unit)? = null,
                   waehlen: (List<Quelle>) -> Set<Quelle>?): Boolean {
        val originals = bindungen.toList()
        require(originals.size <= 1000)
        val expectedGeneration = synchronized(lock) {
            check(setup == null) { "contact_original_setup_busy" }
            generation
        }
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
        val pending = synchronized(lock) {
            check(generation == expectedGeneration && setup == null) { "contact_original_decision_changed" }
            generation++
            SetupBeleg(this, generation, peer, selected.toSet(), originals.filter { quelle(it) in selected }).also { setup = it }
        }
        val decision = Entscheidung(pending)
        var persisted: KontaktOriginalDauerfreigaben.Gespeichert? = null
        try {
            decision.pruefen()
            if (dauerStore != null) {
                persisted = dauerStore.bewilligen(decision)
                if (selected.isNotEmpty()) {
                    val stored = requireNotNull(persisted)
                    stored.pruefen()
                    require(stored.aus(dauerStore) && stored.partner() == peer && stored.quellen() == selected)
                }
            }
            speichern?.invoke(decision)
            decision.pruefen()
        } catch (error: Exception) {
            // An unsuccessful durable setup may have invalidated its old key.
            // Hold volatile permission; this never deletes persistent human intent.
            synchronized(lock) {
                if (generation == pending.generation && setup === pending) {
                    generation++; quellen = emptySet(); partner = null; setup = null; dauer = null; blockiert = true
                }
            }
            throw error
        }
        synchronized(lock) {
            check(generation == pending.generation && setup === pending) { "contact_original_decision_changed" }
            partner = peer; quellen = selected.toSet(); generation++; setup = null; dauer = persisted
            blockiert = selected.isEmpty()
        }
        return true
    }

    fun pausieren() = synchronized(lock) { generation++; quellen = emptySet(); partner = null; setup = null; dauer = null }

    fun widerrufen() {
        synchronized(lock) {
            generation++; quellen = emptySet(); partner = null; setup = null; dauer = null; blockiert = true
        }
        dauerStore?.widerrufen()
    }

    /** Typed authenticated native state only; no portable/JSON restore entry. */
    fun wiederherstellen(stored: KontaktOriginalDauerfreigaben.Gespeichert): Boolean {
        val expected = synchronized(lock) {
            if (blockiert || setup != null) throw SecurityException("contact_original_restore_blocked")
            generation
        }
        val owner = dauerStore ?: throw SecurityException("contact_original_native_store_required")
        require(stored.aus(owner)) { "contact_original_foreign_store" }
        stored.pruefen()
        val peer = stored.partner(); val sources = stored.quellen()
        if (aktuellerPartner() != peer) throw SecurityException("contact_original_peer_unavailable")
        stored.pruefen()
        val restoredGeneration = synchronized(lock) {
            check(generation == expected && !blockiert && setup == null) { "contact_original_restore_context_changed" }
            if (dauer?.gleich(stored) != true || partner != peer || quellen != sources) {
                generation++; partner = peer; quellen = sources.toSet(); dauer = stored
            }
            generation
        }
        try {
            stored.pruefen()
            if (aktuellerPartner() != peer) throw SecurityException("contact_original_peer_unavailable")
            synchronized(lock) { check(generation == restoredGeneration && !blockiert && setup == null) }
            return true
        } catch (error: Exception) {
            synchronized(lock) {
                if (generation == restoredGeneration) {
                    generation++; partner = null; quellen = emptySet(); dauer = null
                }
            }
            throw error
        }
    }

    fun freigabe(bindung: KontaktOriginalBindung): Freigabe {
        val key = quelle(bindung)
        val native = synchronized(lock) {
            if (blockiert || setup != null || key !in quellen) throw SecurityException("contact_original_source_not_granted")
            Beleg(this, generation, bindung, key)
        }
        return Freigabe(bindung, native).also { it.pruefen() }
    }

    private fun pruefen(beleg: Beleg, versionPruefen: Boolean) {
        fun current(): Pair<Partner, KontaktOriginalDauerfreigaben.Gespeichert?> = synchronized(lock) {
            if (blockiert || setup != null || generation != beleg.generation || beleg.quelle !in quellen)
                throw SecurityException("contact_original_source_not_granted")
            (partner ?: throw SecurityException("contact_original_source_not_granted")) to dauer
        }
        val state = current(); val peer = state.first
        state.second?.pruefen()
        if (aktuellerPartner() != peer) throw SecurityException("contact_original_peer_unavailable")
        if (versionPruefen) beleg.bindung.aktuell()
        state.second?.pruefen()
        if (aktuellerPartner() != peer || quelle(beleg.bindung) != beleg.quelle || current() != state)
            throw SecurityException("contact_original_native_decision_changed")
    }

    private fun pruefen(beleg: SetupBeleg) {
        fun current() = synchronized(lock) {
            if (generation != beleg.generation || setup !== beleg) throw SecurityException("contact_original_native_setup_stale")
        }
        current()
        if (aktuellerPartner() != beleg.partner) throw SecurityException("contact_original_peer_changed")
        beleg.originale.forEach { it.aktuell() }
        if (aktuellerPartner() != beleg.partner) throw SecurityException("contact_original_peer_changed")
        current()
    }

    private fun quelle(bindung: KontaktOriginalBindung) = Quelle(bindung.datenbankErstellt, bindung.quelle)
}
