
package io.gitlab.maik3531.magnolienotes.baum

internal data class Partner(val kennung: String, val bestaetigt: Boolean = true,
    val vertraut: Boolean = true, val fernAdresse: String = "fixture.invalid", val fernPort: Int = 8737,
    val oeffentlich: String = "pinned-key", val protokoll: String = "baum-fs1")
internal data class Baumzustand(val partner: List<Partner>, val dienstAn: Boolean = true,
    val syncEpoch: String = "epoch", val kennung: String = "own", val oeffentlich: String = "own-key")
internal data class State(var value: Baumzustand)
internal class Ablage(val baum: State)
internal data class EigeneIdentitaet(val kennung: String = "own", val oeffentlich: String = "own-key")
internal object System { var now = 0L; fun nanoTime() = now }
internal object FernAbgleich {
    val attempts = mutableListOf<String>()
    var slow = false
    var expire = false
    var during: (Partner) -> Unit = {}
    fun reset() { attempts.clear(); slow = false; expire = false; during = {}; System.now = 0 }
    fun pruefen(identity: EigeneIdentitaet, peer: Partner, epoch: String): FernAbgleichVerbindung? {
        attempts += peer.kennung
        if (slow && peer.kennung.startsWith("offline")) { System.now += 1_500_000_000L; return null }
        System.now += 1_000_000L
        during(peer)
        return FernAbgleichVerbindung(peer, identity.kennung, identity.oeffentlich, epoch,
            System.now + if (expire) 0 else 30_000_000_000L)
    }
}
internal data class FernAbgleichVerbindung(
    val partner: Partner,
    val eigeneKennung: String,
    val eigenerSchluessel: String,
    val epoch: String,
    val gueltigBis: Long
) {
    fun passt(baum: Baumzustand, jetzt: Long = System.nanoTime()): Boolean =
        jetzt < gueltigBis && baum.dienstAn && baum.kennung == eigeneKennung &&
            baum.oeffentlich == eigenerSchluessel && baum.syncEpoch == epoch &&
            baum.partner.any { it.kennung == partner.kennung && it.bestaetigt && it.vertraut &&
                it.oeffentlich == partner.oeffentlich && it.protokoll == partner.protokoll &&
                it.fernAdresse == partner.fernAdresse && it.fernPort == partner.fernPort }
}

internal class Work(val ablage: Ablage) {
    var online = true
    var ownAvailable = true
    fun fernInternet() = online
    fun eigen(): EigeneIdentitaet? = if (ownAvailable) EigeneIdentitaet() else null
    private val fernAbgleichReihenfolge = FernAbgleichReihenfolge()
    internal fun fernAbgleichVerbindungen(): List<FernAbgleichVerbindung> {
        if (!fernInternet()) return emptyList()
        val vorher = ablage.baum.value
        if (!vorher.dienstAn) return emptyList()
        val identitaet = eigen() ?: return emptyList()
        val result = mutableListOf<FernAbgleichVerbindung>()
        val ende = System.nanoTime() + 8_000_000_000L
        val partner = vorher.partner.filter { it.bestaetigt && it.vertraut && it.fernAdresse.isNotBlank() }
            .associateBy { it.kennung }
        for (kennung in fernAbgleichReihenfolge.naechste(partner.keys.toList())) {
            if (Thread.currentThread().isInterrupted || System.nanoTime() >= ende || !fernInternet()) break
            val peer = partner.getValue(kennung)
            fernAbgleichReihenfolge.versucht(kennung)
            FernAbgleich.pruefen(identitaet, peer, vorher.syncEpoch)?.let { proof ->
                if (proof.passt(ablage.baum.value)) result += proof
            }
        }
        return result
    }

}
private fun fixture(vararg peers: Partner) = Work(Ablage(State(Baumzustand(peers.toList()))))
fun main() {
    var failures = 0; var passed = 0
    fun test(name: String, body: () -> Unit) {
        FernAbgleich.reset()
        try { body(); passed++; println("PASS $name") }
        catch (e: Throwable) { failures++; println("FAIL $name: ${e.message}") }
        finally { Thread.interrupted() }
    }
    test("reachable peer after six timeouts becomes available on a later refresh") {
        val peers = (1..6).map { Partner("offline$it") } + Partner("reachable")
        val work = fixture(*peers.toTypedArray())
        FernAbgleich.slow = true
        val seen = mutableSetOf<String>()
        repeat(3) {
            FernAbgleich.attempts.clear()
            seen += work.fernAbgleichVerbindungen().map { p -> p.partner.kennung }
            check(FernAbgleich.attempts.size <= 7)
            System.now += 15_000_000_000L
        }
        check("reachable" in seen) { "reachable peer never probed after repeated refreshes" }
    }
    test("all seventy peers are considered without exceeding thirty-two per refresh") {
        val peers = (1..70).map { Partner("peer$it") }
        val work = fixture(*peers.toTypedArray())
        val seen = mutableSetOf<String>()
        repeat(3) {
            FernAbgleich.attempts.clear()
            seen += work.fernAbgleichVerbindungen().map { p -> p.partner.kennung }
            check(FernAbgleich.attempts.size <= 32)
            check(FernAbgleich.attempts.distinct().size == FernAbgleich.attempts.size)
            System.now += 15_000_000_000L
        }
        check(seen == peers.map { it.kennung }.toSet()) { "only ${seen.size}/70 peers were considered" }
    }
    test("offline does not probe") {
        val work = fixture(Partner("allowed")); work.online = false
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    test("disabled service does not probe") {
        val work = fixture(Partner("allowed"))
        work.ablage.baum.value = work.ablage.baum.value.copy(dienstAn = false)
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    test("missing own identity does not probe") {
        val work = fixture(Partner("allowed")); work.ownAvailable = false
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    test("unconfirmed untrusted and unconfigured peers are not probed") {
        val work = fixture(Partner("unconfirmed", bestaetigt = false), Partner("untrusted", vertraut = false),
            Partner("unconfigured", fernAdresse = ""), Partner("allowed"))
        check(work.fernAbgleichVerbindungen().map { it.partner.kennung } == listOf("allowed"))
        check(FernAbgleich.attempts == listOf("allowed"))
    }
    test("trust revocation during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { p -> work.ablage.baum.value = work.ablage.baum.value.copy(partner = listOf(p.copy(vertraut = false))) }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("endpoint replacement during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { p -> work.ablage.baum.value = work.ablage.baum.value.copy(partner = listOf(p.copy(fernPort = 9999))) }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("restore epoch replacement during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { work.ablage.baum.value = work.ablage.baum.value.copy(syncEpoch = "restored") }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("own key replacement during handshake invalidates proof") {
        val work = fixture(Partner("allowed"))
        FernAbgleich.during = { work.ablage.baum.value = work.ablage.baum.value.copy(oeffentlich = "new-key") }
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("expired proof is never reported available") {
        val work = fixture(Partner("allowed")); FernAbgleich.expire = true
        check(work.fernAbgleichVerbindungen().isEmpty())
    }
    test("interruption stops before any network attempt") {
        val work = fixture(Partner("allowed")); Thread.currentThread().interrupt()
        check(work.fernAbgleichVerbindungen().isEmpty()); check(FernAbgleich.attempts.isEmpty())
    }
    println("RESULT passed=$passed failures=$failures")
    check(failures == 0) { "$failures regression assertions failed" }
}
