package io.gitlab.maik3531.magnolienotes.daten

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.system.ErrnoException
import android.system.OsConstants
import io.gitlab.maik3531.magnolienotes.R
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.security.KeyStore
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import java.util.Base64
import java.util.UUID
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.AEADBadTagException

enum class StartFehlerArt {
    ALIAS_FEHLT, KEY_INVALIDIERT, MANIPULATION, UNBEKANNTES_FORMAT,
    RECOVERY, SPEICHER_VOLL, EINGABE_AUSGABE
}

class StartFehler(val art: StartFehlerArt, ursache: Throwable? = null) : Exception(null, ursache)

private fun Throwable.enthaelt(predicate: (Throwable) -> Boolean): Boolean {
    var aktuell: Throwable? = this
    while (aktuell != null) {
        if (predicate(aktuell)) return true
        aktuell = aktuell.cause.takeIf { it !== aktuell }
    }
    return false
}

internal fun startFehler(fehler: Throwable): StartFehler {
    if (fehler is StartFehler) return fehler
    return when {
        fehler.enthaelt { it is KeyPermanentlyInvalidatedException } ->
            StartFehler(StartFehlerArt.KEY_INVALIDIERT, fehler)
        fehler.enthaelt { it is AEADBadTagException } -> StartFehler(StartFehlerArt.MANIPULATION, fehler)
        fehler.enthaelt { it is ErrnoException && it.errno == OsConstants.ENOSPC } ->
            StartFehler(StartFehlerArt.SPEICHER_VOLL, fehler)
        fehler.enthaelt { it is java.io.IOException } -> StartFehler(StartFehlerArt.EINGABE_AUSGABE, fehler)
        else -> StartFehler(StartFehlerArt.UNBEKANNTES_FORMAT, fehler)
    }
}

internal enum class PaarCommitSchritt {
    NOTIZEN_BEREIT,
    BAUM_BEREIT,
    ABSICHT_DAUERHAFT,
    NOTIZEN_ERSETZT,
    BAUM_ERSETZT,
    ERFOLG_DAUERHAFT,
    ABSICHT_ENTFERNT,
    NEBENDATEIEN_ENTFERNT
}

/** Dauerhaftes Roll-forward-Protokoll fuer genau die beiden Restore-Dateien. */
internal class WiederherstellungsPaarCommit(
    private val ordner: File,
    private val kodieren: (String, ByteArray) -> ByteArray = { _, bytes -> bytes },
    private val nachSchritt: (PaarCommitSchritt) -> Unit = {}
) {
    private val notizen = File(ordner, "notizen.json")
    private val baum = File(ordner, "baum.json")
    private val notizenBereit = File(ordner, "notizen.json.restore")
    private val baumBereit = File(ordner, "baum.json.restore")
    private val absicht = File(ordner, "wiederherstellung.pending")

    fun istAbgeschlossen(operationId: String): Boolean = erfolg(operationId).exists()

    fun commit(notizenJson: String, baumJson: String, operationId: String) {
        wiederaufnehmen()
        if (istAbgeschlossen(operationId)) return

        dauerhaftSchreiben(notizenBereit, kodiert(notizen.name, notizenJson))
        nachSchritt(PaarCommitSchritt.NOTIZEN_BEREIT)
        dauerhaftSchreiben(baumBereit, kodiert(baum.name, baumJson))
        nachSchritt(PaarCommitSchritt.BAUM_BEREIT)
        veroeffentlichen(absicht, Base64.getUrlEncoder().withoutPadding()
            .encode(operationId.toByteArray(Charsets.UTF_8)))
        nachSchritt(PaarCommitSchritt.ABSICHT_DAUERHAFT)
        fertigstellen(operationId)
    }

    fun wiederaufnehmen() {
        if (!absicht.exists()) {
            aufraeumen()
            return
        }
        val operationId = try {
            String(Base64.getUrlDecoder().decode(absicht.readBytes()), Charsets.UTF_8)
                .takeIf { it.matches(Regex("[A-Za-z0-9._-]{1,200}")) }
                ?: throw IllegalArgumentException("Ungueltige Wiederherstellungskennung")
        } catch (fehler: Exception) {
            throw StartFehler(StartFehlerArt.RECOVERY, fehler)
        }
        if (!notizenBereit.isFile || !baumBereit.isFile) {
            throw StartFehler(StartFehlerArt.RECOVERY)
        }
        fertigstellen(operationId)
    }

    fun vergesseErfolge(prefix: String) {
        val anfang = "wiederherstellung-$prefix"
        val entfernt = ordner.listFiles().orEmpty()
            .filter { it.name.startsWith(anfang) && it.name.endsWith(".ok") }
            .any { it.delete() }
        if (entfernt) ordnerSynchronisieren()
    }

    private fun fertigstellen(operationId: String) {
        installieren(notizenBereit, notizen)
        nachSchritt(PaarCommitSchritt.NOTIZEN_ERSETZT)
        installieren(baumBereit, baum)
        nachSchritt(PaarCommitSchritt.BAUM_ERSETZT)
        veroeffentlichen(erfolg(operationId), ByteArray(0))
        nachSchritt(PaarCommitSchritt.ERFOLG_DAUERHAFT)
        check(absicht.delete() || !absicht.exists())
        ordnerSynchronisieren()
        nachSchritt(PaarCommitSchritt.ABSICHT_ENTFERNT)
        aufraeumen()
        nachSchritt(PaarCommitSchritt.NEBENDATEIEN_ENTFERNT)
    }

    private fun installieren(quelle: File, ziel: File) {
        val neu = File(ordner, ziel.name + ".restore-install")
        FileInputStream(quelle).use { eingang ->
            FileOutputStream(neu).use { ausgang ->
                eingang.copyTo(ausgang)
                ausgang.flush()
                ausgang.fd.sync()
            }
        }
        atomarVerschieben(neu, ziel)
        ordnerSynchronisieren()
    }

    private fun veroeffentlichen(datei: File, inhalt: ByteArray) {
        val neu = File(ordner, datei.name + ".neu")
        dauerhaftSchreiben(neu, inhalt)
        atomarVerschieben(neu, datei)
        ordnerSynchronisieren()
    }

    private fun dauerhaftSchreiben(datei: File, inhalt: ByteArray) {
        FileOutputStream(datei).use { strom ->
            strom.write(inhalt)
            strom.flush()
            strom.fd.sync()
        }
    }

    private fun kodiert(name: String, inhalt: String): ByteArray {
        val klar = inhalt.toByteArray(Charsets.UTF_8)
        return try {
            kodieren(name, klar).let { if (it === klar) it.copyOf() else it }
        } finally { klar.fill(0) }
    }

    private fun atomarVerschieben(quelle: File, ziel: File) {
        Files.move(quelle.toPath(), ziel.toPath(), StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING)
    }

    private fun ordnerSynchronisieren() {
        synchronisiereOrdner(ordner)
    }

    private fun aufraeumen() {
        listOf(notizenBereit, baumBereit,
            File(ordner, "notizen.json.restore-install"),
            File(ordner, "baum.json.restore-install"),
            File(ordner, absicht.name + ".neu")
        ).forEach { it.delete() }
        ordnerSynchronisieren()
    }

    private fun erfolg(operationId: String): File =
        File(ordner, "wiederherstellung-$operationId.ok")
}

/**
 * Alles, was bleiben soll, liegt verschluesselt in zwei Dateien im privaten
 * App-Verzeichnis. Atomare Nebendateien verhindern halbe Schreibstaende.
 */
class Ablage private constructor(
    zusammenhang: Context,
    datenKey: () -> SecretKey,
    nachCommitSchritt: (PaarCommitSchritt) -> Unit = {}
) {

    private val ordner = zusammenhang.filesDir
    private val standardBuchName = runCatching { zusammenhang.getString(R.string.notizbuch_standard) }
        .getOrDefault("Lose Notizen")

    private val notizDatei = File(ordner, "notizen.json")
    private val baumDatei = File(ordner, "baum.json")
    private val entwurfDatei = File(ordner, "entwurf.json")
    private val entwurfSchreibsperre = Any()
    private val _entwurf = MutableStateFlow(EditorEntwurf())
    val entwurf: StateFlow<EditorEntwurf> = _entwurf.asStateFlow()
    private var gesicherterEntwurf = EditorEntwurf()
    private val dateiKrypto = DatenDateiKrypto(datenKey)
    private val wiederherstellung = WiederherstellungsPaarCommit(ordner,
        kodieren = { name, bytes -> dateiKrypto.verschluesseln(bytes, name) },
        nachSchritt = nachCommitSchritt)
    private val sperre = SCHREIBSPERRE
    private val baumTransporte = mutableSetOf<AutoCloseable>()
    private var baumTransportGeneration = 0L
    private var baumNachrichtenTransaktion = false
    @Volatile private var recoveryErforderlich = false

    private fun schreibbar() {
        if (recoveryErforderlich) throw StartFehler(StartFehlerArt.RECOVERY)
    }

    private fun paarCommit(notizen: String, baum: String, operationId: String) {
        schreibbar()
        try { wiederherstellung.commit(notizen, baum, operationId) }
        catch (fehler: Throwable) {
            // Even a failed directory sync may have published the durable intent.
            recoveryErforderlich = true
            baumTransporteAbbrechen()
            throw fehler
        }
    }

    private val _bestand = MutableStateFlow(Bestand())
    val bestand: StateFlow<Bestand> = _bestand.asStateFlow()

    private val _baum = MutableStateFlow(Baumzustand())
    val baum: StateFlow<Baumzustand> = _baum.asStateFlow()

    init {
        // Vor jeglicher Recovery-Bereinigung muss Aliasverlust erkannt sein.
        dateiKrypto.schluesselPruefen()
        wiederherstellung.wiederaufnehmen()
        wiederherstellung.vergesseErfolge("baum-nachricht-")
        val notizStand = lesen(notizDatei, Bestand())
        val baumStand = lesen(baumDatei, Baumzustand())
        _bestand.value = notizStand.wert.let { gelesen ->
            val sauber = PapierkorbLogik.bereinigen(gelesen).copy(
                aufgaben = AufgabenHierarchie.normalisieren(gelesen.aufgaben))
            if (sauber.notizbuecher.isEmpty()) {
                sauber.copy(notizbuecher = listOf(Notizbuch(STANDARD_BUCH, standardBuchName)))
            } else sauber
        }
        _baum.value = io.gitlab.maik3531.magnolienotes.baum.Paarung.bereinigen(baumStand.wert)
        val entwurfStand = lesen(entwurfDatei, EditorEntwurf())
        require(entwurfStand.wert.notiz == null || entwurfStand.wert.aufgabe == null)
        _entwurf.value = entwurfStand.wert
        gesicherterEntwurf = entwurfStand.wert
        if (entwurfStand.klartext) schreiben(entwurfDatei,
            json.encodeToString(EditorEntwurf.serializer(), entwurfStand.wert))
        if (notizStand.klartext || baumStand.klartext) {
            wiederherstellung.commit(
                json.encodeToString(Bestand.serializer(), _bestand.value),
                json.encodeToString(Baumzustand.serializer(), _baum.value),
                "at-rest-migration-${UUID.randomUUID()}"
            )
        } else if (notizDatei.exists()) {
            schreibeBestand(_bestand.value)
        }
        if (_baum.value != baumStand.wert) setzeBaum(_baum.value)
    }

    // ---------------------------------------------------------------- Notizen

    fun setzeNotizEntwurf(notiz: Notiz?) = synchronized(sperre) {
        schreibbar(); _entwurf.value = EditorEntwurf(notiz = notiz)
    }

    fun setzeAufgabenEntwurf(aufgabe: Aufgabe?) = synchronized(sperre) {
        schreibbar(); _entwurf.value = EditorEntwurf(aufgabe = aufgabe)
    }

    /** Debounced on IO while typing; flushed at the Activity lifecycle boundary. No Binder payload. */
    fun sichereEntwurf() = synchronized(entwurfSchreibsperre) {
        val aktuell = _entwurf.value
        if (aktuell != gesicherterEntwurf) {
            schreiben(entwurfDatei, json.encodeToString(EditorEntwurf.serializer(), aktuell))
            gesicherterEntwurf = aktuell
        }
    }

    fun beendeEntwurf(erwartet: EditorEntwurf): Boolean = synchronized(entwurfSchreibsperre) {
        if (_entwurf.value != erwartet) return@synchronized false
        val leer = EditorEntwurf()
        schreiben(entwurfDatei, json.encodeToString(EditorEntwurf.serializer(), leer))
        gesicherterEntwurf = leer
        _entwurf.compareAndSet(erwartet, leer)
    }

    fun notizen(): List<Notiz> = _bestand.value.notizen

    fun notiz(id: String): Notiz? = _bestand.value.notizen.firstOrNull { it.id == id }

    fun sichereNotiz(notiz: Notiz) = synchronized(sperre) {
        val jetzt = System.currentTimeMillis()
        val fertig = notiz.copy(
            angelegt = if (notiz.angelegt > 0) notiz.angelegt else jetzt,
            geaendert = jetzt
        )
        val liste = _bestand.value.notizen.toMutableList()
        val platz = liste.indexOfFirst { it.id == fertig.id }
        if (platz >= 0) liste[platz] = fertig else liste.add(fertig)
        schreibeBestand(_bestand.value.copy(notizen = liste))
        fertig
    }

    /** Setzt eine Notiz genau so, wie sie übergeben wird – ohne Zeitstempel anzufassen. */
    fun setzeNotiz(notiz: Notiz) = synchronized(sperre) {
        val liste = _bestand.value.notizen.toMutableList()
        val platz = liste.indexOfFirst { it.id == notiz.id }
        if (platz >= 0) liste[platz] = notiz else liste.add(notiz)
        schreibeBestand(_bestand.value.copy(notizen = liste))
    }

    fun loescheNotiz(id: String) = synchronized(sperre) {
        schreibeBestand(PapierkorbLogik.loescheNotiz(_bestand.value, id))
    }

    /**
     * Nimmt übernommene Notizen auf und überspringt, was schon einmal
     * hereingekommen ist. Liefert (neu, übersprungen).
     */
    fun uebernehmen(neue: List<Notiz>): Pair<Int, Int> = synchronized(sperre) {
        val vorhanden = _bestand.value.notizen
            .map { it.einfuhrSchluessel }.filter { it.isNotEmpty() }.toMutableSet()
        val liste = _bestand.value.notizen.toMutableList()
        var uebernommen = 0
        var doppelt = 0
        for (n in neue) {
            val schluessel = n.einfuhrSchluessel.ifEmpty { einfuhrSchluessel(n.titel, n.text) }
            if (schluessel in vorhanden) {
                doppelt++
                continue
            }
            vorhanden += schluessel
            liste += n.copy(einfuhrSchluessel = schluessel)
            uebernommen++
        }
        if (uebernommen > 0) schreibeBestand(_bestand.value.copy(notizen = liste))
        uebernommen to doppelt
    }

    /** Normalisiert Notizbuecher und Notizen unter derselben Sperre und persistiert genau einmal. */
    fun uebernehmenMitNotizbuechern(neue: List<Pair<Notiz, String>>): Pair<Int, Int> =
        synchronized(sperre) {
            val buecher = _bestand.value.notizbuecher.toMutableList()
            val buchIds = linkedMapOf<String, String>()
            buecher.forEach { buch -> buchIds.putIfAbsent(buch.name.trim(), buch.id) }
            neue.forEach { (_, rohName) ->
                val name = rohName.trim().ifBlank { standardBuchName }
                if (name !in buchIds) {
                    val buch = Notizbuch(kennung(), name)
                    buecher += buch
                    buchIds[name] = buch.id
                }
            }

            val vorhanden = _bestand.value.notizen.map { it.einfuhrSchluessel }
                .filter { it.isNotEmpty() }.toMutableSet()
            val notizen = _bestand.value.notizen.toMutableList()
            var uebernommen = 0
            var doppelt = 0
            neue.forEach { (notiz, rohName) ->
                val schluessel = notiz.einfuhrSchluessel.ifEmpty {
                    einfuhrSchluessel(notiz.titel, notiz.text)
                }
                if (!vorhanden.add(schluessel)) {
                    doppelt++
                } else {
                    val name = rohName.trim().ifBlank { standardBuchName }
                    notizen += notiz.copy(
                        notizbuchId = buchIds.getValue(name),
                        einfuhrSchluessel = schluessel
                    )
                    uebernommen++
                }
            }
            if (uebernommen > 0) {
                schreibeBestand(_bestand.value.copy(notizen = notizen, notizbuecher = buecher))
            }
            uebernommen to doppelt
        }

    // --------------------------------------------------------------- Aufgaben

    fun aufgaben(): List<Aufgabe> = _bestand.value.aufgaben

    fun personalCustomChange(change: (PersonalCustomState) -> PersonalCustomState) = synchronized(sperre) {
        val next = change(_bestand.value.personalCustom)
        if (next != _bestand.value.personalCustom) schreibeBestand(_bestand.value.copy(personalCustom = next))
    }

    fun aufgabe(id: String): Aufgabe? = _bestand.value.aufgaben.firstOrNull { it.id == id }

    fun sichereAufgabe(aufgabe: Aufgabe): Aufgabe = synchronized(sperre) {
        val jetzt = System.currentTimeMillis()
        val fertig = aufgabe.copy(
            angelegt = if (aufgabe.angelegt > 0) aufgabe.angelegt else jetzt,
            geaendert = jetzt
        )
        val liste = AufgabenHierarchie.normalisieren(_bestand.value.aufgaben).toMutableList()
        val platz = liste.indexOfFirst { it.id == fertig.id }
        if (platz >= 0) liste[platz] = fertig else liste.add(fertig.copy(
            reihenfolge = liste.count { it.elternUid == fertig.elternUid }))
        val normal = AufgabenHierarchie.normalisieren(liste)
        schreibeBestand(_bestand.value.copy(aufgaben = normal))
        normal.first { it.id == fertig.id }
    }

    /** Setzt eine Aufgabe unverändert – für Nachrichten aus dem Magnolienbaum. */
    fun setzeAufgabe(aufgabe: Aufgabe) = synchronized(sperre) {
        val liste = _bestand.value.aufgaben.toMutableList()
        val platz = liste.indexOfFirst { it.id == aufgabe.id }
        if (platz >= 0) liste[platz] = aufgabe else liste.add(aufgabe)
        schreibeBestand(_bestand.value.copy(aufgaben = AufgabenHierarchie.normalisieren(liste)))
    }

    fun loescheAufgabe(id: String) = synchronized(sperre) {
        schreibeBestand(PapierkorbLogik.loescheAufgabe(_bestand.value, id))
    }

    fun setzeAufgabenEltern(uid: String, elternUid: String): Boolean = synchronized(sperre) {
        val neu = AufgabenHierarchie.elternSetzen(_bestand.value.aufgaben, uid, elternUid)
            ?: return@synchronized false
        schreibeBestand(_bestand.value.copy(aufgaben = neu)); true
    }

    fun verschiebeAufgabe(uid: String, delta: Int): Boolean = synchronized(sperre) {
        val neu = AufgabenHierarchie.verschieben(_bestand.value.aufgaben, uid, delta)
            ?: return@synchronized false
        schreibeBestand(_bestand.value.copy(aufgaben = neu)); true
    }

    fun loescheAnhang(notizId: String, anhangId: String) = synchronized(sperre) {
        schreibeBestand(PapierkorbLogik.loescheAnhang(_bestand.value, notizId, anhangId))
    }

    fun loescheNotizbuch(id: String): Boolean = synchronized(sperre) {
        val neu = PapierkorbLogik.loescheNotizbuch(_bestand.value, id) ?: return@synchronized false
        schreibeBestand(neu); true
    }

    fun setzePapierkorb(an: Boolean, tage: Int) = synchronized(sperre) {
        require(tage in setOf(0, 7, 30, 90, 365))
        schreibeBestand(PapierkorbLogik.bereinigen(_bestand.value.copy(
            papierkorbEinstellungen = PapierkorbEinstellungen(an, tage))))
    }

    fun papierkorbWiederherstellen(id: String): Boolean = synchronized(sperre) {
        val neu = PapierkorbLogik.wiederherstellen(_bestand.value, id) ?: return@synchronized false
        schreibeBestand(neu); true
    }

    fun papierkorbEndgueltig(id: String) = synchronized(sperre) {
        schreibeBestand(_bestand.value.copy(papierkorb = _bestand.value.papierkorb.filterNot { it.id == id }))
    }

    fun papierkorbLeeren() = synchronized(sperre) {
        schreibeBestand(_bestand.value.copy(papierkorb = emptyList()))
    }

    fun personalSyncStageProposals(runId: String, source: String,
                                   proposals: List<PersonalDeletionProposal>) = synchronized(sperre) {
        schreibeBestand(PersonalSync.stageProposals(_bestand.value, runId, source, proposals))
    }

    /** Returns applied, conflict, blocked, or missing. The mutation and decision state share one write. */
    fun personalSyncDecide(peerId: String, proposalId: String, decisionId: String, decision: String,
                           allowChanged: Boolean = false): String = synchronized(sperre) {
        _bestand.value.personalSync.applied_decision_proofs.filter { it.decision_id == decisionId }.takeIf {
            it.isNotEmpty()
        }?.let { previous -> return@synchronized if (previous.size == 1 && previous.single().proposal_id == proposalId &&
            previous.single().decision == decision) "applied" else "conflict" }
        val proposal = _bestand.value.personalSync.pending_proposals.firstOrNull {
            it.proposal_id == proposalId } ?: return@synchronized "missing"
        if (proposal.source_device != peerId) return@synchronized "conflict"
        if (proposal.kind == "note" && PersonalSync.noteId(_bestand.value.personalSync, proposal.id) != proposal.id ||
            proposal.kind == "attachment" && PersonalSync.noteId(_bestand.value.personalSync, proposal.parent_id) != proposal.parent_id)
            return@synchronized "conflict"
        val reconciled = PersonalSync.reconcile(_bestand.value,
            setOf(if (proposal.kind == "task") "tasks" else "notes"),
            _bestand.value.personalSync.format).first
        if (reconciled != _bestand.value) schreibeBestand(reconciled)
        val key = if (proposal.kind == "attachment")
            "attachment\u0000${proposal.parent_id}\u0000${proposal.id}" else "${proposal.kind}\u0000${proposal.id}"
        val meta = _bestand.value.personalSync.entities[key]
        if (decision == "delete" && !allowChanged &&
            (meta == null || meta.hash != proposal.prior_hash || meta.state != "live" ||
             !PersonalSync.matchesCurrent(_bestand.value, proposal) ||
             runCatching { PersonalSync.compare(meta.clock, proposal.clock) != "dominated" }.getOrDefault(true)))
            return@synchronized "conflict"
        var next = _bestand.value
        if (decision == "delete") next = when (proposal.kind) {
            "note" -> PapierkorbLogik.loescheNotiz(next, PersonalSync.noteLocalId(next, proposal.id), proposal.deleted_ms)
            "task" -> PapierkorbLogik.loescheAufgabe(next, proposal.id, proposal.deleted_ms)
            "attachment" -> PapierkorbLogik.loescheAnhang(next, PersonalSync.noteLocalId(next, proposal.parent_id), proposal.id, proposal.deleted_ms)
            "notebook" -> PapierkorbLogik.loescheNotizbuch(next, proposal.id, proposal.deleted_ms)
                ?: return@synchronized "blocked"
            else -> return@synchronized "missing"
        }
        if (decision == "restore") {
            val deleted = meta?.takeIf { it.state == "deleted" }
            if (deleted != null) {
                val trash = next.papierkorb.lastOrNull { item -> when (item.art) {
                    "note" -> item.notiz?.id == PersonalSync.noteLocalId(next, proposal.id)
                    "task" -> item.aufgabe?.id == proposal.id
                    "notebook" -> item.notizbuch?.id == proposal.id
                    "attachment" -> item.anhang?.id == proposal.id && item.parent_id == PersonalSync.noteLocalId(next, proposal.parent_id)
                    else -> false } } ?: return@synchronized "restore_unavailable"
                next = PapierkorbLogik.wiederherstellen(next, trash.id)
                    ?: return@synchronized "restore_unavailable"
            }
        }
        val resolved = if (decision == "delete") PersonalSyncEntity(clock = proposal.clock,
            state = "deleted", peer_device_id = proposal.source_device, prior_hash = proposal.prior_hash,
            deleted_ms = proposal.deleted_ms, label = proposal.label, parent_id = proposal.parent_id,
            proposal_id = proposal.proposal_id, status = "resolved") else meta
        next = next.copy(personalSync = next.personalSync.copy(
            entities = if (resolved == null) next.personalSync.entities else next.personalSync.entities + (key to resolved),
            pending_proposals = next.personalSync.pending_proposals.filterNot { it.proposal_id == proposalId },
            applied_decisions = next.personalSync.applied_decisions + "$proposalId:$decision",
            applied_decision_proofs = (next.personalSync.applied_decision_proofs + AppliedPersonalDecision(
                proposalId, decision, proposal.clock, decisionId)),
            pending_decisions = (next.personalSync.pending_decisions + PendingPersonalDecision(
                peerId, proposal.run_id, decisionId, proposal.proposal_id, decision, proposal.clock)).distinctBy {
                    it.decision_id }.takeLast(500)))
        schreibeBestand(next); "applied"
    }

    fun personalSyncPendingDecisions(): List<PendingPersonalDecision> = synchronized(sperre) {
        _bestand.value.personalSync.pending_decisions
    }

    fun personalSyncRevokeModules(modules: Set<String>) = synchronized(sperre) {
        val revokedKinds = buildSet {
            if ("notes" in modules) addAll(listOf("note", "notebook", "attachment"))
            if ("tasks" in modules) add("task")
        }
        if (revokedKinds.isEmpty()) return@synchronized
        val removed = _bestand.value.personalSync.pending_proposals.filter { it.kind in revokedKinds }
            .mapTo(mutableSetOf()) { it.proposal_id }
        _bestand.value.personalSync.entities.forEach { (key, value) ->
            if (key.substringBefore('\u0000') in revokedKinds && value.proposal_id.isNotEmpty()) removed += value.proposal_id
        }
        val state = _bestand.value.personalSync
        schreibeBestand(_bestand.value.copy(personalSync = state.copy(
            pending_proposals = state.pending_proposals.filterNot { it.kind in revokedKinds },
            pending_decisions = state.pending_decisions.filterNot { it.proposal_id in removed })))
    }

    fun personalSyncRevokeDeletions() = synchronized(sperre) {
        val state = _bestand.value.personalSync
        if (state.pending_proposals.isNotEmpty() || state.pending_decisions.isNotEmpty())
            schreibeBestand(_bestand.value.copy(personalSync = state.copy(
                pending_proposals = emptyList(), pending_decisions = emptyList())))
    }

    fun personalSyncDecisionAccepted(decisionId: String) = synchronized(sperre) {
        val pending = _bestand.value.personalSync.pending_decisions
        if (pending.any { it.decision_id == decisionId }) schreibeBestand(_bestand.value.copy(personalSync =
            _bestand.value.personalSync.copy(pending_decisions = pending.filterNot { it.decision_id == decisionId })))
    }

    fun personalSyncDecisionStopped(decisionId: String, state: String) = synchronized(sperre) {
        require(state == "expired" || state.startsWith("terminal:"))
        val pending = _bestand.value.personalSync.pending_decisions
        if (pending.any { it.decision_id == decisionId && it.state == "pending" })
            schreibeBestand(_bestand.value.copy(personalSync = _bestand.value.personalSync.copy(
                pending_decisions = pending.map { if (it.decision_id == decisionId) it.copy(state = state) else it })))
    }

    /** Validates and applies one wire decision message with one durable Bestand write. */
    fun personalSyncApplyDecisions(decisionId: String,
        decisions: List<Triple<String, String, List<PersonalSyncClock>>>): String = synchronized(sperre) {
        val (next, result) = PersonalSync.applyDeletionDecisions(_bestand.value, decisions.map {
            AppliedPersonalDecision(it.first, it.second, it.third, decisionId)
        })
        if (result == "applied" && next != _bestand.value) schreibeBestand(next)
        result
    }

    fun personalSyncApplyDecision(proposalId: String, decision: String): Boolean = synchronized(sperre) {
        val clock = _bestand.value.personalSync.entities.values.firstOrNull { it.proposal_id == proposalId }?.clock
            ?: return@synchronized false
        personalSyncApplyDecisions("", listOf(Triple(proposalId, decision, clock))) == "applied"
    }

    /** Findet eine Aufgabe über die Kennung des Ursprungs. */
    fun aufgabeNachFremdId(fremdId: String, herkunft: String): Aufgabe? =
        _bestand.value.aufgaben.firstOrNull {
            it.fremdId == fremdId && it.herkunft == herkunft
        }

    fun notizbuecher(): List<Notizbuch> = _bestand.value.notizbuecher

    fun legeNotizbuchAn(name: String): Notizbuch = synchronized(sperre) {
        val vorhanden = _bestand.value.notizbuecher.firstOrNull { it.name == name }
        if (vorhanden != null) return@synchronized vorhanden
        val buch = Notizbuch(kennung(), name)
        schreibeBestand(_bestand.value.copy(notizbuecher = _bestand.value.notizbuecher + buch))
        buch
    }

    fun personalSyncSnapshot(modules: Set<String>, format: Int = 1): List<PersonalSyncRecord> = synchronized(sperre) {
        val (neu, records) = PersonalSync.reconcile(_bestand.value, modules, format)
        if (neu != _bestand.value) schreibeBestand(neu)
        records
    }

    fun personalSyncSnapshotMitAnhaengen(modules: Set<String>, format: Int = 2): PersonalSyncSnapshot = synchronized(sperre) {
        require(format in 2..3)
        val (neu, records) = PersonalSync.reconcile(_bestand.value, modules, format)
        if (neu != _bestand.value) schreibeBestand(neu)
        val attachments = linkedMapOf<String, PersonalSync.AttachmentSnapshot>()
        _bestand.value.notizen.filter { it.baumQuelle.isBlank() }.flatMap { it.anhaenge }.forEach { attachment ->
            PersonalSync.attachmentDescriptor(attachment)?.let { snapshot ->
                attachments[(snapshot.descriptor["sha256"] as JsonPrimitive).content] = snapshot
            }
        }
        PersonalSyncSnapshot(records, attachments)
    }

    fun personalSyncCounter(): Long = synchronized(sperre) { _bestand.value.personalSync.counter }

    fun personalSyncAcknowledge(peerId: String) = synchronized(sperre) {
        val durable = PersonalSync.acknowledge(_bestand.value, peerId)
        if (durable != _bestand.value) schreibeBestand(durable)
    }

    fun personalSyncApply(records: List<PersonalSyncRecord>): PersonalSyncResult = synchronized(sperre) {
        val modules = records.map { if (it.kind == "task") "tasks" else "notes" }.toSet()
        val local = PersonalSync.reconcile(_bestand.value, modules, 1).first
        val result = PersonalSync.apply(local, records)
        schreibeBestand(result.bestand)
        result
    }

    fun personalSyncApplyOnce(records: List<PersonalSyncRecord>, batchKey: String): PersonalSyncResult? =
        personalSyncApplyOnce(records, emptyMap(), batchKey,
            records.map { if (it.kind == "task") "tasks" else "notes" }.toSet(), 1)

    fun personalSyncApplyOnce(records: List<PersonalSyncRecord>, attachments: Map<String, Anhang>,
                              batchKey: String, modules: Set<String>, format: Int): PersonalSyncResult? = synchronized(sperre) {
        if (batchKey in _bestand.value.personalSync.applied_batches) return@synchronized null
        // Content, clocks, incoming changes and replay protection share one durable write.
        val local = PersonalSync.reconcile(_bestand.value, modules, format).first
        val result = PersonalSync.apply(local, records, attachments)
        val applied = (result.bestand.personalSync.applied_batches + batchKey).takeLast(500)
        val durable = result.copy(bestand = result.bestand.copy(
            personalSync = result.bestand.personalSync.copy(applied_batches = applied)))
        schreibeBestand(durable.bestand)
        durable
    }

    private fun schreibeBestand(neu: Bestand) {
        schreibbar()
        if (baumNachrichtenTransaktion) {
            merkeBestandInTransaktion(neu)
            return
        }
        schreiben(notizDatei, json.encodeToString(Bestand.serializer(), neu))
        _bestand.value = neu
    }

    private fun merkeBestandInTransaktion(neu: Bestand) {
        _bestand.value = neu
    }

    // ------------------------------------------------------------------- Baum

    fun setzeBaum(neu: Baumzustand) = synchronized(sperre) {
        schreibbar()
        if (!baumNachrichtenTransaktion) {
            schreiben(baumDatei, json.encodeToString(Baumzustand.serializer(), neu))
        }
        _baum.value = neu
    }

    /** Konsistenter Rohstand beider Domänen-Dateien unter derselben Schreibsperre. */
    fun journalNutzlast(): Pair<String, String> = synchronized(sperre) {
        json.encodeToString(Bestand.serializer(), _bestand.value) to
            json.encodeToString(Baumzustand.serializer(), _baum.value)
    }

    /** Ersetzt beide Bestände als eine Operation und trennt alte Netzmutation ab. */
    fun journalWiederherstellen(notizenJson: String, baumJson: String, operationId: String): Boolean =
        synchronized(sperre) {
            schreibbar()
            if (wiederherstellung.istAbgeschlossen(operationId)) return@synchronized false
            val neuBestand = json.decodeFromString(Bestand.serializer(), notizenJson).let {
                it.copy(aufgaben = AufgabenHierarchie.normalisieren(it.aufgaben),
                    personalCustom = PersonalCustom.restore(_bestand.value.personalCustom, it.personalCustom),
                    personalSync = it.personalSync.copy(pending_proposals = emptyList(), pending_decisions = emptyList()))
            }
            val altBaum = _baum.value
            val gelesen = json.decodeFromString(Baumzustand.serializer(), baumJson)
            val neueEpoch = UUID.randomUUID().toString()
            val neuBaum = gelesen.copy(
                syncEpoch = neueEpoch,
                additiveBaselineAusstehend = true,
                postfach = emptyList(),
                kontaktLoeschStaende = emptyList(),
                quarantiniertesPostfach = (altBaum.quarantiniertesPostfach + altBaum.postfach).takeLast(500)
            )
            // Closing a registered transport also forbids its next handshake/payload request.
            // No network IO or waiting for a sender is allowed while holding the data lock.
            baumTransporteAbbrechen()
            paarCommit(
                json.encodeToString(Bestand.serializer(), neuBestand),
                json.encodeToString(Baumzustand.serializer(), neuBaum),
                operationId
            )
            _bestand.value = neuBestand
            _baum.value = neuBaum
            true
        }

    internal fun baumVersandGeneration(): Long = synchronized(sperre) { baumTransportGeneration }

    internal fun baumTransportAnmelden(epoch: String, generation: Long, transport: AutoCloseable): Boolean = synchronized(sperre) {
        if (epoch != _baum.value.syncEpoch || generation != baumTransportGeneration) { transport.close(); false }
        else { baumTransporte += transport; true }
    }

    internal fun baumTransportAbmelden(transport: AutoCloseable) {
        transport.close()
        synchronized(sperre) { baumTransporte -= transport }
    }

    internal fun baumTransporteAbbrechen() = synchronized(sperre) {
        baumTransportGeneration++
        baumTransporte.forEach { runCatching { it.close() } }
        baumTransporte.clear()
    }

    /** Setzt nur den portablen Bestand ein; die aktuelle Baumidentitaet bleibt erhalten. */
    fun portableWiederherstellen(bestandJson: String, operationId: String): Boolean =
        journalWiederherstellen(bestandJson,
            json.encodeToString(Baumzustand.serializer(), _baum.value), operationId)

    fun aendereBaum(block: (Baumzustand) -> Baumzustand) = synchronized(sperre) {
        schreibbar()
        val neu = block(_baum.value)
        if (neu != _baum.value && !baumNachrichtenTransaktion) {
            schreiben(baumDatei, json.encodeToString(Baumzustand.serializer(), neu))
        }
        _baum.value = neu
        neu
    }

    /**
     * Veröffentlicht eine empfangene Mutation und ihren Replay-Schutz gemeinsam.
     * Ein nach der dauerhaften Absicht abgebrochener Commit wird beim nächsten Laden
     * vor dem Einlesen beider Dateien zu Ende geführt.
     */
    fun verarbeiteBaumNachricht(
        vonKennung: String,
        zaehler: Long? = null,
        transportId: String? = null,
        umschlagHash: String? = null,
        receipt: String? = null,
        mutation: () -> Unit
    ): Boolean = synchronized(sperre) {
        schreibbar()
        require((zaehler == null) != (transportId == null))
        check(!baumNachrichtenTransaktion)
        val partner = _baum.value.partner.firstOrNull { it.kennung == vonKennung }
            ?: return@synchronized false
        if (zaehler != null && zaehler <= partner.zaehlerRein) return@synchronized false
        if (transportId != null && transportId in partner.gesehen) return@synchronized false

        val altBestand = _bestand.value
        val altBaum = _baum.value
        baumNachrichtenTransaktion = true
        var commitBegonnen = false
        try {
            mutation()
            val jetzt = System.currentTimeMillis()
            _baum.value = _baum.value.copy(partner = _baum.value.partner.map {
                if (it.kennung != vonKennung) it else if (zaehler != null) {
                    it.copy(zaehlerRein = zaehler, zuletzt = jetzt,
                        baum1Belege = if (umschlagHash == null) it.baum1Belege else
                            (it.baum1Belege + Baum1Beleg(zaehler, umschlagHash, receipt.orEmpty())).takeLast(64))
                } else {
                    it.copy(gesehen = (it.gesehen + transportId!!).takeLast(256), zuletzt = jetzt)
                }
            })
            if (receipt != null) {
                val alteEingaenge = altBaum.eingang.mapTo(mutableSetOf()) { it.id }
                _baum.value = _baum.value.copy(eingang = _baum.value.eingang.map {
                    if (it.id in alteEingaenge) it else it.copy(envelopeSha256 = umschlagHash.orEmpty())
                })
                val peers = _baum.value.partner.map { it.copy(baum1Belege = it.baum1Belege.takeLast(64)) }.toMutableList()
                while (peers.sumOf { it.baum1Belege.size } > 256) {
                    val index = peers.indices.maxBy { peers[it].baum1Belege.size }
                    val peer = peers[index]
                    peers[index] = peer.copy(baum1Belege = peer.baum1Belege.drop(1))
                }
                _baum.value = _baum.value.copy(partner = peers)
            }
            val operationId = "baum-nachricht-${UUID.randomUUID()}"
            commitBegonnen = true
            paarCommit(
                json.encodeToString(Bestand.serializer(), _bestand.value),
                json.encodeToString(Baumzustand.serializer(), _baum.value),
                operationId
            )
            wiederherstellung.vergesseErfolge(operationId)
            true
        } catch (abbruch: Throwable) {
            if (commitBegonnen) recoveryErforderlich = true
            _bestand.value = altBestand
            _baum.value = altBaum
            throw abbruch
        } finally {
            baumNachrichtenTransaktion = false
        }
    }

    // ------------------------------------------------------------------ Datei

    private data class Gelesen<T>(val wert: T, val klartext: Boolean)

    private inline fun <reified T> lesen(datei: File, vorgabe: T): Gelesen<T> {
        if (!datei.exists()) return Gelesen(vorgabe, false)
        val roh = datei.readBytes()
        if (dateiKrypto.istVerschluesselt(roh)) {
            val klar = dateiKrypto.entschluesseln(roh, datei.name)
            return try {
                Gelesen(json.decodeFromString<T>(klar.decodeToString()), false)
            } finally {
                klar.fill(0)
            }
        }
        return try {
            require(istJsonObjekt(roh)) { "Unbekanntes oder beschaedigtes Datenformat" }
            try {
                Gelesen(json.decodeFromString<T>(roh.decodeToString()), true)
            } catch (fehler: Exception) {
                throw StartFehler(StartFehlerArt.UNBEKANNTES_FORMAT, fehler)
            }
        } finally {
            roh.fill(0)
        }
    }

    private fun istJsonObjekt(bytes: ByteArray): Boolean {
        for (byte in bytes) {
            if (byte != 0x20.toByte() && byte != 0x09.toByte() &&
                byte != 0x0a.toByte() && byte != 0x0d.toByte()) return byte == '{'.code.toByte()
        }
        return false
    }

    private fun schreiben(datei: File, inhalt: String) = synchronized(sperre) {
        schreibbar()
        val neben = File(datei.parentFile, datei.name + ".neu")
        val klar = inhalt.toByteArray(Charsets.UTF_8)
        val geheim = try { dateiKrypto.verschluesseln(klar, datei.name) } finally { klar.fill(0) }
        try {
            FileOutputStream(neben).use { strom ->
                strom.write(geheim); strom.flush(); strom.fd.sync()
            }
        } finally { geheim.fill(0) }
        runCatching { neben.setReadable(false, false); neben.setReadable(true, true) }
        Files.move(neben.toPath(), datei.toPath(), StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING)
        try { synchronisiereOrdner(requireNotNull(datei.parentFile)) }
        catch (fehler: Throwable) { recoveryErforderlich = true; throw fehler }
    }

    companion object {
        const val STANDARD_BUCH = "notizbuch-lose-notizen"
        private const val DATEN_KEY_ALIAS = "magnolie-hauptdaten-v1"

        private fun androidDatenKey(zusammenhang: Context): SecretKey = synchronized(Ablage::class.java) {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            try {
                (store.getKey(DATEN_KEY_ALIAS, null) as? SecretKey)?.let { return@synchronized it }
            } catch (fehler: Throwable) {
                throw StartFehler(StartFehlerArt.KEY_INVALIDIERT, fehler)
            }
            // Alle Commitstufen und auch kuenftige Backupnamen werden erkannt. Der Inhalt,
            // nicht ein unvollstaendiger Namenskatalog, entscheidet ueber Aliasverlust.
            if (enthaeltKryptoBestand(zusammenhang.filesDir)) {
                val marker = File(zusammenhang.filesDir, "alias-fehlt.recovery")
                if (!marker.exists()) FileOutputStream(marker).use {
                    it.write("ALIAS_FEHLT\n".toByteArray(Charsets.US_ASCII)); it.fd.sync()
                }
                throw StartFehler(StartFehlerArt.ALIAS_FEHLT)
            }
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            generator.init(KeyGenParameterSpec.Builder(DATEN_KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setUserAuthenticationRequired(false)
                .build())
            generator.generateKey()
        }

        val json = Json {
            ignoreUnknownKeys = true
            encodeDefaults = true
            prettyPrint = false
        }

        @Volatile
        private var einzig: Ablage? = null

        /** Gemeinsame Mutex für UI, Baumdienst, Sync und Journal-Restore. */
        val SCHREIBSPERRE = Any()

        fun hole(zusammenhang: Context): Ablage =
            einzig ?: synchronized(this) {
                einzig ?: try {
                    val app = zusammenhang.applicationContext
                    Ablage(app, datenKey = { androidDatenKey(app) }).also { einzig = it }
                } catch (fehler: Throwable) {
                    throw startFehler(fehler)
                }
            }

        internal fun fuerTest(zusammenhang: Context, key: () -> SecretKey): Ablage =
            Ablage(zusammenhang.applicationContext, key)

        internal fun fuerTest(
            zusammenhang: Context,
            key: () -> SecretKey,
            nachCommitSchritt: (PaarCommitSchritt) -> Unit
        ): Ablage = Ablage(zusammenhang.applicationContext, key, nachCommitSchritt)

        internal fun singletonFuerTestZuruecksetzen() {
            synchronized(this) { einzig = null }
        }

        internal fun enthaeltKryptoBestand(ordner: File): Boolean = ordner.walkTopDown()
            .filter(File::isFile)
            .any { datei ->
                FileInputStream(datei).use { strom ->
                    val kopf = ByteArray(14)
                    strom.read(kopf) == kopf.size && DatenDateiKrypto(key = { error("nicht benutzt") })
                        .istVerschluesselt(kopf)
                }
            }

        fun kennung(): String = UUID.randomUUID().toString()

        /** Ein stabiler Fingerabdruck über den Wortlaut, gegen doppelte Übernahmen. */
        fun einfuhrSchluessel(titel: String, text: String): String {
            val roh = (titel.trim() + "\u0000" + text.trim()).replace(Regex("\\s+"), " ")
            val h = MessageDigest.getInstance("SHA-256").digest(roh.toByteArray())
            return h.take(16).joinToString("") { "%02x".format(it) }
        }

        fun einfuhrSchluessel(titel: String, text: String, anhaenge: List<Anhang>): String {
            val digest = MessageDigest.getInstance("SHA-256")
            digest.update((titel.trim() + "\u0000" + text.trim()).replace(Regex("\\s+"), " ").toByteArray())
            anhaenge.forEach {
                digest.update(0)
                digest.update(it.daten.toByteArray(Charsets.US_ASCII))
            }
            return digest.digest().take(16).joinToString("") { "%02x".format(it) }
        }
    }
}
