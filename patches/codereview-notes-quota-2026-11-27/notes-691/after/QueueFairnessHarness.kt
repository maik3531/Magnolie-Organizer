
package io.gitlab.maik3531.magnolienotes.baum
import kotlinx.serialization.json.*
import io.gitlab.maik3531.magnolienotes.netz.LanRegel

object System { var ms = 1_000_000_000L; var ns = 0L; fun currentTimeMillis() = ms; fun nanoTime() = ns }
object LanFreigabe {
    var granted = false
    fun erlaubt() = granted
    fun ziel(host: String): java.net.InetAddress = LanRegel.ziel(host,
        { if (!granted) throw java.io.IOException("LAN grant missing") },
        { java.net.InetAddress.getByName(it) })
}
interface Transport: AutoCloseable { val name: String; override fun close() {} }
class WlanTransport(private val host: String, override val name: String): Transport {
    fun wartetAufLan(): Boolean = !LanFreigabe.erlaubt() && runCatching { LanFreigabe.ziel(host) }.isFailure
}
class BluetoothTransport(override val name: String): Transport
data class Partner(val kennung: String, val bestaetigt: Boolean = true, val protokoll: String = "baum-fs1",
    val kontaktSyncFassungen: List<Int> = listOf(1), val kontaktImportFassungen: List<Int> = listOf(1),
    val kontaktV3Geprueft: Boolean = false, val kontaktV4Geprueft: Boolean = false,
    val zuletzt: Long = 0, val zaehlerRaus: Long = 0)
data class Baum(val postfach: List<Sendung>, val partner: List<Partner>, val bluetoothAn: Boolean = true, val syncEpoch: String = "epoch")
data class State(var value: Baum)
class Ablage(val baum: State) {
    var generation = 0L
    val registered = mutableListOf<String>(); val closed = mutableListOf<String>()
    fun baumVersandGeneration() = generation
    fun aendereBaum(f: (Baum) -> Baum) { baum.value = f(baum.value) }
    fun baumTransportAnmelden(epoch: String, expected: Long, transport: Transport): Boolean {
        if (epoch != baum.value.syncEpoch || expected != generation) { transport.close(); return false }
        registered += transport.name; return true
    }
    fun baumTransportAbmelden(t: Transport) { t.close(); closed += t.name }
}
object Kanonisch {
    val json = this
    fun parseToJsonElement(s: String): JsonElement {
        require(s != "invalid") { "invalid fixture payload" }
        return JsonObject()
    }
}
object Versand {
    data class Ergebnis(val gelungen: Boolean, val zaehler: Long = 0, val grund: String = "", val unsicher: Boolean = false, val httpStatus: Int = 0)
    val routes = mutableMapOf<String,List<Transport>>()
    val sent = mutableListOf<String>()
    var beforeRoute: () -> Unit = {}
    var onSend: () -> Unit = {}
    var result = Ergebnis(true)
    fun reset() { routes.clear(); sent.clear(); beforeRoute = {}; onSend = {}; result = Ergebnis(true); System.ns = 0; LanFreigabe.granted = false }
    fun wegeZu(p: Partner, bluetoothErlaubt: Boolean): List<Transport> {
        beforeRoute()
        return routes[p.kennung].orEmpty().filter { bluetoothErlaubt || it !is BluetoothTransport }
    }
    fun zustellen(eigen: String, p: Partner, art: String, inhalt: JsonObject, id: String, transport: Transport, legacy: JsonObject?): Ergebnis {
        sent += id; onSend(); return result
    }
}
class Work(val ablage: Ablage) {
    private val versandSperre = java.util.concurrent.locks.ReentrantLock()
    var identity: String? = "own"
    var onPrepare: () -> Unit = {}
    val prepared = mutableListOf<String>()
    var nullPrepared = emptySet<String>()
    var failedPreparation = emptySet<String>()
    val errors = mutableListOf<String>()
    fun eigen() = identity
    fun meldeFehler(reason: String) { errors += reason }
    fun sendungVorbereiten(id: String): Sendung? {
        prepared += id; onPrepare()
        if (id in nullPrepared) return null
        require(id !in failedPreparation) { "controlled preparation error" }
        return ablage.baum.value.postfach.firstOrNull { it.id == id }
    }
    fun sendungVersuchen(s: Sendung, generation: Long) = s.syncEpoch == ablage.baum.value.syncEpoch && generation == ablage.generation && !s.brauchtPruefung
    fun postfachAbarbeiten(maxSendungen: Int = 64): Int {
        if (!versandSperre.tryLock()) return 0
        try {
        val generation = ablage.baumVersandGeneration()
        val eigen = eigen() ?: return 0
        val jetzt = System.currentTimeMillis()
        var zugestellt = 0
        val wartendePartner = mutableSetOf<String>()
        val ende = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(30)
        var versucht = 0
        for (snapshot in ablage.baum.value.postfach.toList()) {
            if (Thread.currentThread().isInterrupted || System.nanoTime() >= ende || versucht >= maxSendungen) break
            if (snapshot.brauchtPruefung) {
                sendungVorbereiten(snapshot.id)
                wartendePartner += snapshot.an
                continue
            }
            if (snapshot.aufgegeben || !(snapshot.kontaktV3Probe || snapshot.kontaktV4Probe) && snapshot.an in wartendePartner) continue
            if (snapshot.naechsterVersuch > jetzt) {
                if (snapshot.baum1Umschlag.isNotEmpty()) wartendePartner += snapshot.an
                continue
            }
            versucht++
            val sendung = try { sendungVorbereiten(snapshot.id) } catch (_: IllegalArgumentException) {
                aufgeben(snapshot); continue
            } ?: continue
            val partner = ablage.baum.value.partner.firstOrNull { it.kennung == sendung.an }
            if (partner == null) {
                aufgeben(sendung)
                continue
            }
            val bekannteTransporte = Versand.wegeZu(partner, ablage.baum.value.bluetoothAn)
            val transporte = bekannteTransporte.filter { it !is WlanTransport || !it.wartetAufLan() }
            if (transporte.isEmpty() && bekannteTransporte.isNotEmpty()) {
                // Only a LAN wait refunds this run's attempt; preparation failures keep their bound.
                versucht--
                continue // wait, no failed-attempt/deletion
            }
            if (transporte.isEmpty()) {
                fehlversuch(sendung, "Für diesen Zweig ist kein Weg bekannt.")
                continue
            }
            val inhalt = try {
                Kanonisch.json.parseToJsonElement(sendung.inhalt).jsonObject
            } catch (fehler: Exception) {
                aufgeben(sendung)
                continue
            }
            if (sendung.art in setOf("kontakt_sync", "kontakt_import_manifest", "kontakt_import_karte")) {
                val versions = if (sendung.art == "kontakt_sync") partner.kontaktSyncFassungen else partner.kontaktImportFassungen
                if (!partner.bestaetigt || inhalt["fassung"] !in versions.map { kotlinx.serialization.json.JsonPrimitive(it) }) {
                    fehlversuch(sendung, "contact_version_not_available")
                    continue
                }
            }
            var ergebnis = Versand.Ergebnis(false, grund = "Nicht erreichbar.")
            for (transport in transporte) {
                if (!ablage.baumTransportAnmelden(sendung.syncEpoch, generation, transport)) break
                try {
                    if (sendung.baum1Umschlag.isNotEmpty() && !sendungVersuchen(sendung, generation)) break
                    ergebnis = Versand.zustellen(
                    eigen, if (sendung.kontaktV3Probe || sendung.kontaktV4Probe) partner.copy(protokoll = "baum-fs1") else partner,
                    sendung.art, inhalt, sendung.transportId, transport,
                    sendung.baum1Umschlag.takeIf(String::isNotEmpty)?.let { Kanonisch.json.parseToJsonElement(it).jsonObject }
                )
                    if (sendung.baum1Umschlag.isNotEmpty() && !ergebnis.gelungen && !ergebnis.unsicher) {
                        ablage.aendereBaum { alt ->
                            if (alt.syncEpoch != sendung.syncEpoch || ablage.baumVersandGeneration() != generation) alt
                            else alt.copy(postfach = alt.postfach.map {
                                if (it.id == sendung.id) it.copy(receiptAttempted = false, unsicher = false) else it
                            })
                        }
                    }
                } finally { ablage.baumTransportAbmelden(transport) }
                if (ergebnis.gelungen || ergebnis.unsicher) break
            }
            if (sendung.syncEpoch != ablage.baum.value.syncEpoch || generation != ablage.baumVersandGeneration()) break
            if ((sendung.kontaktV3Probe || sendung.kontaktV4Probe) && ergebnis.httpStatus in setOf(400, 403, 404)) {
                ablage.aendereBaum { alt ->
                    if (alt.syncEpoch != sendung.syncEpoch || generation != ablage.baumVersandGeneration()) alt
                    else alt.copy(postfach = alt.postfach.filterNot { it.id == sendung.id },
                        partner = alt.partner.map { if (it.kennung == partner.kennung) it.copy(
                            kontaktV3Geprueft = it.kontaktV3Geprueft || sendung.kontaktV3Probe,
                            kontaktV4Geprueft = it.kontaktV4Geprueft || sendung.kontaktV4Probe) else it })
                }
            } else if (ergebnis.gelungen) {
                zugestellt++
                ablage.aendereBaum { alt ->
                    if (sendung.syncEpoch != alt.syncEpoch || generation != ablage.baumVersandGeneration()) return@aendereBaum alt
                    alt.copy(
                        postfach = alt.postfach.filterNot { it.id == sendung.id },
                        partner = alt.partner.map {
                            if (it.kennung != partner.kennung) it
                            else it.copy(
                                zuletzt = System.currentTimeMillis(),
                                zaehlerRaus = maxOf(ergebnis.zaehler, it.zaehlerRaus)
                            )
                        }
                    )
                }
            } else if (ergebnis.unsicher) {
                wartendePartner += sendung.an
            } else {
                if (!LanFreigabe.erlaubt()) continue // revocation must not consume retries
                if (sendung.baum1Umschlag.isNotEmpty()) wartendePartner += sendung.an
                fehlversuch(sendung, ergebnis.grund)
            }
        }
        return zugestellt
        } finally { versandSperre.unlock() }
    }

    private fun fehlversuch(sendung: Sendung, grund: String) {
        val abstaende = longArrayOf(60, 120, 300, 600, 1800, 3600)
        val versuche = sendung.versuche + 1
        val abstand = abstaende.getOrElse(versuche - 1) { 3600L } * 1000
        val zuAlt = System.currentTimeMillis() - sendung.angelegt > 7L * 24 * 3600 * 1000
        ablage.aendereBaum { alt ->
            alt.copy(postfach = alt.postfach.map {
                if (it.id != sendung.id) it
                else it.copy(
                    versuche = versuche,
                    naechsterVersuch = System.currentTimeMillis() + abstand,
                    aufgegeben = zuAlt
                )
            })
        }
        if (versuche == 1 && !(sendung.kontaktV3Probe || sendung.kontaktV4Probe)) meldeFehler(grund)
    }

    private fun aufgeben(sendung: Sendung) {
        ablage.aendereBaum { alt ->
            alt.copy(postfach = alt.postfach.map {
                if (it.id == sendung.id) it.copy(aufgegeben = true) else it
            })
        }
    }

}
fun note(id: String, peer: String = id) = Sendung(id, id, peer, "notiz_sync", "{}", angelegt = System.ms, syncEpoch = "epoch", protokoll = "baum-fs1")
fun fixture(rows: List<Sendung>): Work = Work(Ablage(State(Baum(rows, rows.map { Partner(it.an) }.distinctBy { it.kennung }))))
fun blocked(id: String) { Versand.routes[id] = listOf(WlanTransport("192.168.50.20", "blocked-$id")) }
fun remote(id: String) { Versand.routes[id] = listOf(WlanTransport("203.0.113.20", "remote-$id")) }
fun waitingThen(id: String): Work {
    val rows = (1..3).map { note("wait$it") } + note(id)
    (1..3).forEach { blocked("wait$it") }
    return fixture(rows)
}
fun main() {
    var passed = 0; var failed = 0
    fun test(name: String, body: () -> Unit) {
        Versand.reset()
        try { body(); passed++; println("PASS $name") }
        catch (e: Throwable) { failed++; println("FAIL $name: ${e.message}") }
        finally { Thread.interrupted() }
    }
    test("public remote note is delivered behind LAN waiters on repeated maintenance") {
        val w = waitingThen("remote"); remote("remote")
        repeat(3) { w.postfachAbarbeiten(2) }
        check(Versand.sent == listOf("remote")) { "permitted remote update was starved: ${Versand.sent}" }
        check(w.ablage.baum.value.postfach.map { it.id } == listOf("wait1", "wait2", "wait3"))
    }
    test("permitted Bluetooth note is delivered behind LAN waiters") {
        val w = waitingThen("bt"); Versand.routes["bt"] = listOf(BluetoothTransport("approved-bt"))
        repeat(3) { w.postfachAbarbeiten(2) }
        check(Versand.sent == listOf("bt")) { "permitted Bluetooth update was starved: ${Versand.sent}" }
    }
    test("default sixty-four quota does not strand remote note behind seventy LAN waiters") {
        val rows = (1..70).map { note("wait$it") } + note("r")
        (1..70).forEach { blocked("wait$it") }; remote("r")
        val w = fixture(rows)
        repeat(3) { w.postfachAbarbeiten() }
        check(Versand.sent == listOf("r")) { "default quota stranded permitted remote note" }
        check(w.ablage.baum.value.postfach == rows.dropLast(1))
    }
    test("waiting alone preserves payload IDs epoch attempts and pending state") {
        val rows = (1..5).map { note("wait$it") }; rows.forEach { blocked(it.id) }
        val w = fixture(rows); repeat(3) { check(w.postfachAbarbeiten(2) == 0) }
        check(w.ablage.baum.value.postfach == rows); check(Versand.sent.isEmpty()); check(w.errors.isEmpty())
    }
    test("null preparation keeps the original attempt bound before a later eligible frame") {
        val rows = (1..3).map { note("null$it") } + note("r")
        val w = fixture(rows); w.nullPrepared = setOf("null1", "null2", "null3"); remote("r")
        check(w.postfachAbarbeiten(2) == 0)
        check(w.prepared == listOf("null1", "null2")) { "null preparation bypassed the original quota: ${w.prepared}" }
        check(Versand.sent.isEmpty()); check(w.ablage.baum.value.postfach == rows)
    }
    test("preparation exception keeps the original attempt bound before a later eligible frame") {
        val rows = (1..3).map { note("throw$it") } + note("r")
        val w = fixture(rows); w.failedPreparation = setOf("throw1", "throw2", "throw3"); remote("r")
        check(w.postfachAbarbeiten(2) == 0)
        check(w.prepared == listOf("throw1", "throw2")) { "preparation exceptions bypassed the original quota: ${w.prepared}" }
        check(Versand.sent.isEmpty())
        check(w.ablage.baum.value.postfach.map { it.aufgegeben } == listOf(true, true, false, false))
    }
    test("missing partner after preparation keeps the original attempt bound") {
        val rows = (1..3).map { note("missing$it") } + note("r")
        val w = fixture(rows); remote("r")
        w.ablage.baum.value = w.ablage.baum.value.copy(partner = listOf(Partner("r")))
        check(w.postfachAbarbeiten(2) == 0)
        check(w.prepared == listOf("missing1", "missing2")) { "missing partners bypassed the original quota: ${w.prepared}" }
        check(Versand.sent.isEmpty())
        check(w.ablage.baum.value.postfach.map { it.aufgegeben } == listOf(true, true, false, false))
    }
    test("actual send quota remains two and remaining delivery resumes") {
        val w = waitingThen("r1")
        w.ablage.baum.value = w.ablage.baum.value.copy(postfach = w.ablage.baum.value.postfach + listOf(note("r2"), note("r3")),
            partner = w.ablage.baum.value.partner + listOf(Partner("r2"), Partner("r3")))
        listOf("r1", "r2", "r3").forEach(::remote)
        check(w.postfachAbarbeiten(2) == 2) { "first bounded round failed to deliver two eligible notes" }
        check(Versand.sent == listOf("r1", "r2"))
        check(w.postfachAbarbeiten(2) == 1); check(Versand.sent == listOf("r1", "r2", "r3"))
    }
    test("zero quota performs no attempts") {
        val w = waitingThen("r"); remote("r")
        check(w.postfachAbarbeiten(0) == 0); check(Versand.sent.isEmpty())
    }
    test("thirty-second deadline remains enforced while scanning waiting routes") {
        val w = waitingThen("r"); remote("r")
        Versand.beforeRoute = { System.ns += 10_000_000_000L }
        check(w.postfachAbarbeiten(64) == 0); check(Versand.sent.isEmpty()); check(System.ns == 30_000_000_000L)
    }
    test("future retry and expired message remain unsent") {
        val later = note("later").copy(naechsterVersuch = System.ms + 5000)
        val expired = note("expired").copy(aufgegeben = true)
        val w = fixture(listOf(later, expired, note("r"))); listOf("later", "expired", "r").forEach(::remote)
        check(w.postfachAbarbeiten(1) == 1); check(Versand.sent == listOf("r"))
        check(w.ablage.baum.value.postfach == listOf(later, expired))
    }
    test("legacy uncertain peer remains fenced while another peer can send") {
        val pending = note("uncertain", "same").copy(unsicher = true, baum1Umschlag = "{}", receiptProtocol = 1)
        val next = note("next", "same")
        val w = fixture(listOf(pending, next, note("r"))); remote("same"); remote("r")
        check(w.postfachAbarbeiten(1) == 1); check(Versand.sent == listOf("r"))
        check(w.ablage.baum.value.postfach == listOf(pending, next))
    }
    test("permission revocation keeps local waiting but allows separately permitted public route") {
        LanFreigabe.granted = true
        val w = fixture(listOf(note("local1"), note("local2"), note("r")))
        blocked("local1"); blocked("local2"); remote("r")
        Versand.onSend = { LanFreigabe.granted = false }
        check(w.postfachAbarbeiten(2) == 2) { "public route starved after independent LAN revocation" }
        check(Versand.sent == listOf("local1", "r")); check(w.ablage.baum.value.postfach == listOf(note("local2")))
    }
    test("Bluetooth disabled is not silently enabled") {
        val w = fixture(listOf(note("bt")))
        w.ablage.baum.value = w.ablage.baum.value.copy(bluetoothAn = false)
        Versand.routes["bt"] = listOf(BluetoothTransport("disabled-bt"))
        check(w.postfachAbarbeiten(2) == 0); check(Versand.sent.isEmpty()); check(!w.ablage.baum.value.bluetoothAn)
    }
    test("restore before transport admission prevents any payload send") {
        val w = fixture(listOf(note("r"))); remote("r")
        Versand.beforeRoute = { w.ablage.baum.value = w.ablage.baum.value.copy(syncEpoch = "restored") }
        check(w.postfachAbarbeiten(2) == 0); check(Versand.sent.isEmpty()); check(w.ablage.baum.value.postfach.size == 1)
    }
    test("shutdown generation before transport admission prevents payload send") {
        val w = fixture(listOf(note("r"))); remote("r")
        Versand.beforeRoute = { w.ablage.generation++ }
        check(w.postfachAbarbeiten(2) == 0); check(Versand.sent.isEmpty()); check(w.ablage.baum.value.postfach.size == 1)
    }
    test("restore during delivery does not discard the changed queue") {
        val w = fixture(listOf(note("r"))); remote("r")
        Versand.onSend = { w.ablage.baum.value = w.ablage.baum.value.copy(syncEpoch = "restored"); w.ablage.generation++ }
        check(w.postfachAbarbeiten(2) == 0); check(w.ablage.baum.value.postfach.size == 1)
    }
    test("unknown route and malformed payload retain explicit failure behavior") {
        LanFreigabe.granted = true
        val invalid = note("bad").copy(inhalt = "invalid")
        val w = fixture(listOf(note("unknown"), invalid)); remote("bad")
        check(w.postfachAbarbeiten(2) == 0); check(Versand.sent.isEmpty())
        check(w.ablage.baum.value.postfach.first().versuche == 1)
        check(w.ablage.baum.value.postfach.last().aufgegeben)
    }
    test("missing identity leaves pending data unchanged") {
        val rows = listOf(note("r")); val w = fixture(rows); w.identity = null; remote("r")
        check(w.postfachAbarbeiten(2) == 0); check(Versand.sent.isEmpty()); check(w.ablage.baum.value.postfach == rows)
    }
    test("interruption stops before route or payload attempts") {
        val w = fixture(listOf(note("r"))); remote("r"); Thread.currentThread().interrupt()
        check(w.postfachAbarbeiten(2) == 0); check(Versand.sent.isEmpty())
    }
    println("RESULT passed=$passed failures=$failed")
    check(failed == 0) { "$failed regression assertions failed" }
}
