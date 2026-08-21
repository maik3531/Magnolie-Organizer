package io.gitlab.maik3531.magnolienotes.baum

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.content.Context
import androidx.annotation.StringRes
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.fehlertext
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Eingangsstueck
import io.gitlab.maik3531.magnolienotes.daten.Freigabe
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Partner
import io.gitlab.maik3531.magnolienotes.daten.Sendung
import io.gitlab.maik3531.magnolienotes.daten.Symbol
import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur
import io.gitlab.maik3531.magnolienotes.daten.KontaktVorschlag
import io.gitlab.maik3531.magnolienotes.daten.KontaktLoeschStand
import io.gitlab.maik3531.magnolienotes.daten.KontaktEingang
import io.gitlab.maik3531.magnolienotes.daten.KontaktAblehnung
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.util.UUID
import io.gitlab.maik3531.magnolienotes.journal.AndroidJournal

/**
 * Die Schaltstelle des Magnolienbaums auf diesem Gerät: Identität, Partner,
 * Postfach, Empfangsdienst. Die Oberfläche spricht ausschließlich hierher.
 */
class Baumwerk private constructor(
    private val ablage: Ablage,
    private val zusammenhang: Context
) : Server.Handlung {

    private val server = Server(this)
    private var bluetooth: BluetoothHorcher? = null

    private val _meldungen = MutableStateFlow<List<String>>(emptyList())
    val meldungen: StateFlow<List<String>> = _meldungen.asStateFlow()

    val zustand: StateFlow<Baumzustand> get() = ablage.baum

    /** Legt beim ersten Aufruf ein dauerhaftes Schlüsselpaar an. */
    fun sorgeFuerIdentitaet(vorgabename: String) {
        if (ablage.baum.value.kennung.isNotEmpty() && ablage.baum.value.geheim.isNotEmpty()) return
        val (geheim, oeffentlich) = Krypto.neuesSchluesselpaar()
        ablage.aendereBaum {
            it.copy(
                kennung = zufallskennung(),
                name = it.name.ifBlank { vorgabename },
                geheim = Krypto.b64(geheim),
                oeffentlich = Krypto.b64(oeffentlich),
                port = Netz.PORT
            )
        }
    }

    fun fingerabdruck(): String = Krypto.fingerabdruck(ablage.baum.value.oeffentlich)

    fun benenne(name: String) {
        ablage.aendereBaum { it.copy(name = name.take(60)) }
        if (ablage.baum.value.dienstAn) {
            // Der Name steckt in der mDNS-Ankündigung; die muss neu heraus.
            Entdeckung.neuVeroeffentlichen(eigen(), server.port)
        }
    }

    // ----------------------------------------------------------- Empfangsdienst

    fun dienstStarten(zusammenhang: Context): Boolean {
        if (!server.starten()) {
            melde(R.string.baum_meldung_dienst_fehler)
            return false
        }
        ablage.aendereBaum { it.copy(dienstAn = true) }
        Entdeckung.veroeffentlichen(zusammenhang, eigen(), server.port)
        if (ablage.baum.value.bluetoothAn) bluetoothStarten()
        return true
    }

    fun dienstAnhalten() {
        server.anhalten()
        Entdeckung.beenden()
        bluetoothAnhalten()
        ablage.aendereBaum { it.copy(dienstAn = false) }
    }

    fun bluetoothStarten(): Boolean {
        if (bluetooth != null) return true
        val neuerHorcher = BluetoothHorcher(server)
        if (!neuerHorcher.starten()) {
            ablage.aendereBaum { it.copy(bluetoothAn = false) }
            melde(R.string.baum_meldung_bluetooth_fehler)
            return false
        }
        bluetooth = neuerHorcher
        ablage.aendereBaum { it.copy(bluetoothAn = true) }
        return true
    }

    fun bluetoothAnhalten() {
        bluetooth?.anhalten()
        bluetooth = null
        ablage.aendereBaum { it.copy(bluetoothAn = false) }
    }

    @SuppressLint("MissingPermission")
    fun gekoppelteBluetoothGeraete(): List<BluetoothZiel> {
        val adapter = BluetoothAdapter.getDefaultAdapter() ?: return emptyList()
        return try {
            if (!adapter.isEnabled) return emptyList()
            adapter.bondedDevices.map {
                BluetoothZiel(it.address, it.name.orEmpty().ifBlank { it.address })
            }.sortedBy { it.name.lowercase() }
        } catch (fehler: SecurityException) {
            emptyList()
        }
    }

    fun bluetoothZuordnen(kennung: String, adresse: String) {
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == kennung) it.copy(bluetooth = adresse) else it
            })
        }
    }

    fun fernzielSichern(kennung: String, host: String, port: Int) {
        val saubererPort = port.takeIf { it in 1..65535 } ?: Netz.PORT
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == kennung) {
                    it.copy(fernAdresse = host.trim().take(253), fernPort = saubererPort)
                } else it
            })
        }
    }

    fun automatischWlan(an: Boolean) {
        ablage.aendereBaum { it.copy(automatischWlan = an) }
    }

    fun suchen(zusammenhang: Context): List<Gefunden> {
        val ausMdns = Entdeckung.suchen(zusammenhang, eigen()?.kennung.orEmpty())
        val ausRuf = server.rufen()
        return (ausMdns + ausRuf).distinctBy { it.kennung }
    }

    // ------------------------------------------------------------------ Paarung

    /** Paarung über eine Datei aus dem Organizer. */
    fun paareMitDatei(text: String): Partner {
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val dokument = Paarung.pruefeDatei(text)
        val bluetoothWege = if (ablage.baum.value.bluetoothAn) gekoppelteBluetoothGeraete().map {
            Versand.Paarungsweg(BluetoothTransport(it.adresse), it.adresse)
        } else emptyList()
        val partner = Versand.paareMitDatei(dokument, eigen, bluetoothWege)
        partnerAufnehmen(partner)
        melde(R.string.baum_meldung_gepaart, partner.name.ifBlank { partner.kennung })
        return partner
    }

    /** Eine eigene Paarungsdatei, die am Rechner eingelesen werden kann. */
    fun erzeugePaarungsdatei(): String {
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val adresse = Netz.eigeneAdresse()
        if (adresse.isBlank()) throw BaumFehler("Dieses Gerät hat gerade keine Netzadresse.")
        val (dokument, einladung) = Paarung.erzeugeDatei(eigen, adresse)
        val jetzt = System.currentTimeMillis() / 1000
        ablage.aendereBaum { alt ->
            alt.copy(einladungen = alt.einladungen.filter { it.gueltigBis > jetzt }.take(19) + einladung)
        }
        return Kanonisch.json.encodeToString(JsonObject.serializer(), dokument)
    }

    /** Der kurze Codeweg von hier aus. */
    fun frageAn(adresse: String, port: Int): Pair<Partner, String> {
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val (partner, code) = Versand.frageAn(adresse, port, eigen)
        partnerAufnehmen(partner)
        return partner to code
    }

    fun bestaetigen(kennung: String) {
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == kennung) it.copy(bestaetigt = true, wartet = false) else it
            })
        }
    }

    /** Schaltet für einen Zweig um, ob seine Inhalte ohne Rückfrage kommen. */
    fun vertrauen(kennung: String, vertraut: Boolean) {
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == kennung) it.copy(vertraut = vertraut) else it
            })
        }
    }

    fun kontaktSyncSchalten(kennung: String, an: Boolean) {
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == kennung && it.bestaetigt && it.vertraut) it.copy(kontaktSync = an)
                else it
            })
        }
    }

    fun kontaktLoeschSyncSchalten(kennung: String, an: Boolean) {
        ablage.aendereBaum { alt -> alt.copy(partner = alt.partner.map {
            if (it.kennung == kennung && it.bestaetigt && it.vertraut && it.kontaktSync) {
                it.copy(kontaktLoeschSync = an)
            } else it
        }) }
    }

    /** Nimmt ein wartendes Angebot an. */
    fun eingangAnnehmen(stueckId: String) {
        val stueck = ablage.baum.value.eingang.firstOrNull { it.id == stueckId } ?: return
        if (stueck.art == "termin") {
            melde(R.string.baum_termin_nicht_unterstuetzt)
            return
        }
        val inhalt = runCatching {
            Kanonisch.json.parseToJsonElement(stueck.inhalt).jsonObject
        }.getOrNull()
        if (inhalt == null) return
        if (stueck.art == "kontakt_loeschen" &&
            (zusammenhang.checkSelfPermission(android.Manifest.permission.READ_CONTACTS) != android.content.pm.PackageManager.PERMISSION_GRANTED ||
                zusammenhang.checkSelfPermission(android.Manifest.permission.WRITE_CONTACTS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
        ) return
        if (stueck.art == "kontakt_loeschen") kontaktLoeschungUebernehmen(stueck.von, inhalt)
        else uebernehmen(stueck.von, stueck.vonName, inhalt)
        eingangEntfernen(stueckId)
    }

    fun eingangEntfernen(stueckId: String) {
        ablage.aendereBaum { alt ->
            alt.copy(eingang = alt.eingang.filterNot { it.id == stueckId })
        }
    }

    fun entfernen(kennung: String) {
        ablage.aendereBaum { KontaktEingangslogik.bereinigePartner(it, kennung) }
    }

    private fun partnerAufnehmen(neu: Partner) {
        ablage.aendereBaum { alt ->
            val vorhanden = alt.partner.firstOrNull { it.kennung == neu.kennung }
            if (vorhanden != null &&
                vorhanden.bestaetigt && vorhanden.oeffentlich.isNotEmpty() &&
                vorhanden.oeffentlich != neu.oeffentlich
            ) {
                throw BaumFehler(
                    "Der Schlüssel dieses Zweigs hat sich geändert. Entferne die alte " +
                        "Verbindung zuerst und vergleiche den neuen Fingerabdruck besonders sorgfältig."
                )
            }
            val zusammen = if (vorhanden == null) neu else vorhanden.copy(
                name = neu.name.ifBlank { vorhanden.name },
                oeffentlich = neu.oeffentlich,
                adresse = neu.adresse.ifBlank { vorhanden.adresse },
                port = if (neu.adresse.isNotBlank()) neu.port else vorhanden.port,
                bestaetigt = vorhanden.bestaetigt || neu.bestaetigt,
                vertraut = vorhanden.vertraut || neu.vertraut,
                wartet = neu.wartet && !vorhanden.bestaetigt,
                code = neu.code.ifBlank { vorhanden.code },
                protokoll = neu.protokoll
            )
            alt.copy(partner = alt.partner.filterNot { it.kennung == neu.kennung } + zusammen)
        }
    }

    // ------------------------------------------------------------------ Senden

    /**
     * Gibt eine Notiz an Zweige weiter. Beim ersten Mal als Angebot (`notiz`),
     * danach als Fortschreibung (`notiz_sync`).
     */
    fun teileNotiz(notiz: Notiz, kennungen: List<String>): Notiz {
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val vorhandeneFreigabe = notiz.baumFreigabe
        val freigabe = vorhandeneFreigabe ?: Freigabe(id = UUID.randomUUID().toString())
        val alleKennungen = (freigabe.partner + kennungen).distinct()
        val erneuert = notiz.copy(
            baumFreigabe = freigabe.copy(
                partner = alleKennungen,
                anhangPartner = (freigabe.anhangPartner + kennungen).distinct()
            ),
            baumGeaendert = System.currentTimeMillis(),
            baumVersion = notiz.baumVersion + 1,
            baumQuelle = eigen.kennung
        )
        ablage.setzeNotiz(erneuert)

        for (kennung in kennungen) {
            val neuFuerDiesen = vorhandeneFreigabe == null ||
                !vorhandeneFreigabe.partner.contains(kennung)
            val art = if (neuFuerDiesen) "notiz" else "notiz_sync"
            einreihen(kennung, art, Nutzlast.notizInhalt(erneuert, art, eigen.kennung))
        }
        // Wer die Notiz schon kennt, bekommt die Fortschreibung mit.
        for (kennung in freigabe.partner.filterNot { it in kennungen }) {
            einreihen(kennung, "notiz_sync", Nutzlast.notizInhalt(erneuert, "notiz_sync", eigen.kennung))
        }
        postfachAbarbeiten()
        return erneuert
    }

    /**
     * Gibt eine Aufgabe an einen Zweig weiter. Der Ursprung behält sie; der
     * Empfänger bekommt eine gekennzeichnete Kopie und darf nur den
     * Erledigt-Stand zurückmelden – genau wie zwischen zwei Organizern.
     */
    fun teileAufgabe(aufgabe: Aufgabe, kennungen: List<String>): Aufgabe {
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val erneuert = aufgabe.copy(
            delegiertAn = kennungen.firstOrNull() ?: aufgabe.delegiertAn,
            geaendert = System.currentTimeMillis()
        )
        ablage.setzeAufgabe(erneuert)
        val inhalt = Nutzlast.aufgabeInhalt(erneuert, eigen.kennung)
        for (kennung in kennungen) einreihen(kennung, "aufgabe", inhalt)
        postfachAbarbeiten()
        return erneuert
    }

    /**
     * Hakt eine Aufgabe ab und meldet den Stand zurück, wenn sie von einem
     * anderen Zweig stammt. Das ist die einzige Änderung, die zurückfließt.
     */
    fun aufgabeAbhaken(id: String, erledigt: Boolean): Aufgabe? {
        val aufgabe = ablage.aufgabe(id) ?: return null
        val erneuert = ablage.sichereAufgabe(aufgabe.copy(erledigt = erledigt))
        Erinnerung.stellen(zusammenhang, erneuert)
        if (erneuert.istFremd) {
            einreihen(erneuert.herkunft, "stand", Nutzlast.standInhalt(erneuert))
            postfachAbarbeiten()
        }
        return erneuert
    }

    /** Schreibt eine schon geteilte Notiz bei allen Partnern fort. */
    fun notizFortschreiben(notiz: Notiz): Notiz {
        val freigabe = notiz.baumFreigabe ?: return notiz
        if (freigabe.partner.isEmpty()) return notiz
        return teileNotiz(notiz, emptyList())
    }

    /** Eigener, ausschließlich vom Kontaktknopf aufgerufener Synchronisationslauf. */
    fun kontakteSynchronisieren(kennung: String) {
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val zweig = partner(kennung)
        if (zweig?.bestaetigt != true || !zweig.vertraut || !zweig.kontaktSync) {
            throw BaumFehler("Die Kontaktsynchronisation ist für diesen Zweig nicht freigegeben.")
        }
        val adapter = AndroidKontakte(zusammenhang)
        val snapshot = adapter.snapshot()
        if (!snapshot.vollstaendig) throw BaumFehler("Kontakte konnten nicht vollständig gelesen werden.")
        if (snapshot.kontakte.isEmpty()) throw BaumFehler("Der Kontaktsnapshot ist leer; es wurde nichts geändert.")
        val jetzt = System.currentTimeMillis()
        val alteSpuren = ablage.baum.value.kontaktSpuren.filter { it.partner == kennung }
        val vorschlaege = mutableListOf<KontaktVorschlag>()
        snapshot.kontakte.forEach { lokal ->
            val passendeSpuren = ablage.baum.value.kontaktSpuren.filter {
                it.rawContactId in lokal.rawContactIds && it.partner == kennung
            }
            val alt = passendeSpuren.minByOrNull { it.freigabeId }
            val hash = KontaktSync.hash(lokal.daten)
            val geaendert = alt == null || alt.hash != hash
            val spur = KontaktSpur(
                lookupKey = lokal.lookupKey, rawContactId = lokal.rawContactId,
                freigabeId = alt?.freigabeId ?: UUID.randomUUID().toString(),
                version = if (alt == null) 1 else if (geaendert) alt.version + 1 else alt.version,
                quelle = if (alt == null || geaendert) eigen.kennung else alt.quelle,
                hash = hash, partner = kennung, name = KontaktPruefung.name(lokal.daten)
            )
            KontaktVorschlag(
                id = UUID.randomUUID().toString(), partner = kennung,
                art = if (alt == null) "neu" else if (geaendert) "geaendert" else "",
                name = spur.name, rawContactId = lokal.rawContactId, lookupKey = lokal.lookupKey,
                freigabeId = spur.freigabeId, version = spur.version, quelle = spur.quelle,
                geaendert = jetzt
            ).takeIf { it.art.isNotEmpty() }?.let { vorschlaege += it }
            spurSichern(spur)
            einreihen(kennung, "kontakt_sync", KontaktSync.inhalt(KontaktNachricht(
                spur.freigabeId, spur.version, spur.quelle, jetzt, lokal.daten
            )))
        }
        KontaktPruefung.dubletten(snapshot.kontakte).forEach { d ->
            vorschlaege += KontaktVorschlag(
                id = UUID.randomUUID().toString(), partner = kennung, art = "dublette",
                name = KontaktPruefung.name(d.erste.daten) + " / " + KontaktPruefung.name(d.zweite.daten),
                rawContactId = d.erste.rawContactId, lookupKey = d.erste.lookupKey,
                andereRawContactId = d.zweite.rawContactId, andereLookupKey = d.zweite.lookupKey,
                geaendert = jetzt
            )
        }
        if (zweig.kontaktLoeschSync && !ablage.baum.value.additiveBaselineAusstehend) {
            KontaktPruefung.fehlendeSpuren(alteSpuren, snapshot.kontakte.map { it.rawContactId }.toSet(), true)
                .forEach { spur -> vorschlaege += KontaktVorschlag(
                    id = UUID.randomUUID().toString(), partner = kennung, art = "loeschen",
                    name = spur.name, rawContactId = spur.rawContactId, lookupKey = spur.lookupKey,
                    freigabeId = spur.freigabeId, version = spur.version + 1,
                    quelle = eigen.kennung, geaendert = jetzt
                ) }
        }
        ablage.aendereBaum { alt -> alt.copy(kontaktVorschlaege =
            alt.kontaktVorschlaege.filterNot { it.partner == kennung } + vorschlaege) }
        postfachAbarbeiten()
    }

    fun kontaktVorschlagAblehnen(id: String) {
        ablage.aendereBaum { it.copy(kontaktVorschlaege = it.kontaktVorschlaege.filterNot { v -> v.id == id }) }
    }

    fun kontaktGruppen(partner: String): List<KontaktGruppe> =
        KontaktEingangslogik.gruppiere(ablage.baum.value.kontaktEingang.filter { it.partner == partner })

    fun kontaktPartnerMitEingang(): List<String> = ablage.baum.value.kontaktEingang
        .map { it.partner }.distinct()

    fun kontaktGruppeImportieren(id: String, getrennt: Boolean = false): Int {
        val gruppe = kontaktPartnerMitEingang().asSequence().flatMap { kontaktGruppen(it).asSequence() }
            .firstOrNull { it.id == id } ?: return 0
        if (!getrennt && !gruppe.zusammenfuehrbar) return 0
        val teile = if (getrennt) gruppe.karten.map { listOf(it) } else listOf(gruppe.karten)
        val adapter = AndroidKontakte(zusammenhang)
        val gebundene = ablage.baum.value.kontaktSpuren.filter { spur ->
            gruppe.karten.any { it.partner == spur.partner && it.freigabeId == spur.freigabeId }
        }.map { it.rawContactId }
        val mutationId = "contact-import:${gruppe.id}:${if (getrennt) "split" else "merge"}"
        val staende = adapter.journalStaende(gebundene, "update") +
            if (gebundene.isEmpty()) teile.map { adapter.geplanterStand(
                KontaktEingangslogik.vereinige(it.map { k -> k.kontakt }), "create") } else emptyList()
        AndroidJournal.hole(zusammenhang).kontaktSnapshot("contact-import", staende, mutationId)
        teile.forEach { karten -> importiereKarten(adapter, karten) }
        entferneKontaktKarten(gruppe.karten)
        lokaleDublettenAktualisieren(gruppe.partner)
        return teile.size
    }

    fun sichereKontaktGruppenImportieren(partner: String): Int {
        val gruppen = kontaktGruppen(partner).filter { it.art == KontaktGruppenArt.SICHER }
        if (gruppen.isEmpty()) return 0
        val adapter = AndroidKontakte(zusammenhang)
        val mutationId = "contact-safe-batch:$partner:${gruppen.joinToString { it.id }}"
        val rawIds = ablage.baum.value.kontaktSpuren.filter { spur -> gruppen.any { g ->
            g.karten.any { it.partner == spur.partner && it.freigabeId == spur.freigabeId }
        } }.map { it.rawContactId }
        val staende = adapter.journalStaende(rawIds, "update") + groupsPlanned@ run {
            if (rawIds.isNotEmpty()) emptyList() else gruppen.map { adapter.geplanterStand(it.kontakt, "create") }
        }
        AndroidJournal.hole(zusammenhang).kontaktSnapshot("contact-import", staende, mutationId)
        gruppen.forEach { gruppe -> importiereKarten(adapter, gruppe.karten) }
        entferneKontaktKarten(gruppen.flatMap { it.karten })
        lokaleDublettenAktualisieren(partner)
        return gruppen.size
    }

    fun kontaktGruppeAblehnen(id: String) {
        val gruppe = kontaktPartnerMitEingang().asSequence().flatMap { kontaktGruppen(it).asSequence() }
            .firstOrNull { it.id == id } ?: return
        kontaktKartenAblehnen(gruppe.karten)
    }

    fun alleKontaktKartenAblehnen(partner: String) {
        kontaktKartenAblehnen(ablage.baum.value.kontaktEingang.filter { it.partner == partner })
    }

    private fun kontaktKartenAblehnen(karten: List<KontaktEingang>) {
        if (karten.isEmpty()) return
        val schluessel = karten.map { it.partner to it.freigabeId }.toSet()
        ablage.aendereBaum { alt -> alt.copy(
            kontaktEingang = alt.kontaktEingang.filterNot { it.partner to it.freigabeId in schluessel },
            kontaktAblehnungen = alt.kontaktAblehnungen.filterNot {
                it.partner to it.freigabeId in schluessel
            } + karten.map { KontaktAblehnung(it.partner, it.freigabeId, it.version, it.quelle) }
        ) }
    }

    private fun entferneKontaktKarten(karten: List<KontaktEingang>) {
        val schluessel = karten.map { it.partner to it.freigabeId }.toSet()
        ablage.aendereBaum { alt -> alt.copy(
            kontaktEingang = alt.kontaktEingang.filterNot { it.partner to it.freigabeId in schluessel },
            kontaktAblehnungen = alt.kontaktAblehnungen.filterNot { it.partner to it.freigabeId in schluessel }
        ) }
    }

    private fun importiereKarten(adapter: AndroidKontakte, karten: List<KontaktEingang>) {
        val gebundene = ablage.baum.value.kontaktSpuren.filter { spur ->
            karten.any { it.partner == spur.partner && it.freigabeId == spur.freigabeId }
        }.map { it.rawContactId }.distinct()
        // Mehrere bestehende Zielkontakte werden nie stillschweigend vereinigt.
        val rawId = gebundene.singleOrNull()
        KontaktEingangslogik.importiere(karten, adapter, rawId).spuren.forEach(::spurSichern)
    }

    private fun lokaleDublettenAktualisieren(partner: String) {
        val snapshot = AndroidKontakte(zusammenhang).snapshot()
        if (!snapshot.vollstaendig) return
        val jetzt = System.currentTimeMillis()
        val dubletten = KontaktPruefung.dubletten(snapshot.kontakte).map { d -> KontaktVorschlag(
            id = UUID.randomUUID().toString(), partner = partner, art = "dublette",
            name = KontaktPruefung.name(d.erste.daten) + " / " + KontaktPruefung.name(d.zweite.daten),
            rawContactId = d.erste.rawContactId, lookupKey = d.erste.lookupKey,
            andereRawContactId = d.zweite.rawContactId, andereLookupKey = d.zweite.lookupKey,
            geaendert = jetzt
        ) }
        ablage.aendereBaum { alt -> alt.copy(kontaktVorschlaege =
            alt.kontaktVorschlaege.filterNot { it.partner == partner && it.art == "dublette" } + dubletten) }
    }

    fun dubletteVerknuepfen(id: String): Boolean {
        val v = ablage.baum.value.kontaktVorschlaege.firstOrNull { it.id == id && it.art == "dublette" }
            ?: return false
        val adapter = AndroidKontakte(zusammenhang)
        AndroidJournal.hole(zusammenhang).kontaktSnapshot("contact-keep-together",
            adapter.journalStaende(listOf(v.rawContactId, v.andereRawContactId), "keep-together"),
            "keep-together:$id")
        val ok = adapter.verknuepfen(v.rawContactId, v.andereRawContactId)
        if (ok) kontaktVorschlagAblehnen(id)
        return ok
    }

    /** Bestätigt genau einen lokalen Löschvorschlag und reiht erst dann die Nachricht ein. */
    fun kontaktLoeschungSenden(id: String) {
        val v = ablage.baum.value.kontaktVorschlaege.firstOrNull { it.id == id && it.art == "loeschen" } ?: return
        val p = partner(v.partner)
        if (p?.bestaetigt != true || !p.vertraut || !p.kontaktSync || !p.kontaktLoeschSync) return
        val spur = ablage.baum.value.kontaktSpuren.firstOrNull {
            it.partner == v.partner && it.freigabeId == v.freigabeId && it.rawContactId == v.rawContactId &&
                it.lookupKey == v.lookupKey
        } ?: return
        einreihen(v.partner, "kontakt_loeschen", KontaktPruefung.loeschInhalt(
            KontaktLoeschung(spur.freigabeId, v.version, v.quelle, v.geaendert)))
        ablage.aendereBaum { it.copy(
            kontaktVorschlaege = it.kontaktVorschlaege.filterNot { x -> x.id == id },
            kontaktSpuren = it.kontaktSpuren.filterNot { s -> s == spur }
        ) }
        postfachAbarbeiten()
    }

    fun dubletteOeffnen(id: String): Boolean {
        val v = ablage.baum.value.kontaktVorschlaege.firstOrNull { it.id == id && it.art == "dublette" } ?: return false
        return AndroidKontakte(zusammenhang).systemkontaktOeffnen(v.lookupKey)
    }

    /** Sendet den vollständigen örtlichen Bestand; eine Antwortanfrage ist optional. */
    fun allesSynchronisieren(
        kennung: String,
        mitAnfrage: Boolean = true,
        sofortSenden: Boolean = true
    ) = synchronized(Ablage.SCHREIBSPERRE) {
        AndroidJournal.hole(zusammenhang).appSnapshot("pre-sync-full")
        val eigen = eigen() ?: throw BaumFehler("Die eigene Identität fehlt noch.")
        val partner = partner(kennung)
        if (partner?.bestaetigt != true || !partner.vertraut) {
            throw BaumFehler("Dieser Zweig ist nicht bestätigt und vertraut.")
        }
        val jetzt = System.currentTimeMillis()
        val plan = Synchronisation.planen(
            ablage.notizen(), ablage.aufgaben(), kennung, eigen.kennung, jetzt, mitAnfrage
        )
        for (vorbereitet in plan.notizen) {
            val vorher = ablage.notiz(vorbereitet.notiz.id)
            if (vorbereitet.notiz != vorher) ablage.setzeNotiz(vorbereitet.notiz)
            einreihen(
                kennung,
                vorbereitet.art,
                Nutzlast.notizInhalt(vorbereitet.notiz, vorbereitet.art, eigen.kennung)
            )
        }
        for (aufgabe in plan.aufgaben) {
            einreihen(kennung, "aufgabe", Nutzlast.aufgabeInhalt(aufgabe, eigen.kennung))
        }
        if (plan.syncAnfrage) einreihen(kennung, "sync_anfrage", JsonObject(emptyMap()))
        if (ablage.baum.value.additiveBaselineAusstehend) {
            ablage.aendereBaum { it.copy(additiveBaselineAusstehend = false) }
        }
        if (sofortSenden) postfachAbarbeiten()
    }

    fun automatischSynchronisierenWennFaellig(istWlan: Boolean, jetzt: Long = System.currentTimeMillis()): Boolean {
        val zustand = ablage.baum.value
        val partner = zustand.partner.filter { it.bestaetigt && it.vertraut }
        if (!AutoSync.sollLaufen(
                zustand.automatischWlan, zustand.dienstAn, istWlan,
                zustand.letzteAutoSync, jetzt, partner.isNotEmpty()
            )
        ) return false
        ablage.aendereBaum { it.copy(letzteAutoSync = jetzt) }
        partner.forEach { allesSynchronisieren(it.kennung) }
        return true
    }

    private fun einreihen(an: String, art: String, inhalt: JsonObject) {
        val sendung = Sendung(
            id = UUID.randomUUID().toString(),
            transportId = Krypto.b64(Krypto.zufallsbytes(16)),
            an = an,
            art = art,
            inhalt = Kanonisch.json.encodeToString(JsonObject.serializer(), inhalt),
            angelegt = System.currentTimeMillis(),
            syncEpoch = ablage.baum.value.syncEpoch
        )
        // Erst ins Postfach, dann ins Netz – ein Absturz verliert nichts.
        ablage.aendereBaum { it.copy(postfach = it.postfach + sendung) }
    }

    /** Arbeitet fällige Sendungen ab. Läuft im Aufruferfaden; nie im Hauptfaden. */
    fun postfachAbarbeiten(): Int {
        val eigen = eigen() ?: return 0
        val jetzt = System.currentTimeMillis()
        var zugestellt = 0
        for (sendung in ablage.baum.value.postfach.toList()) {
            if (sendung.aufgegeben || sendung.naechsterVersuch > jetzt) continue
            val partner = ablage.baum.value.partner.firstOrNull { it.kennung == sendung.an }
            if (partner == null) {
                aufgeben(sendung)
                continue
            }
            val transporte = Versand.wegeZu(partner, ablage.baum.value.bluetoothAn)
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
            var ergebnis = Versand.Ergebnis(false, grund = "Nicht erreichbar.")
            for (transport in transporte) {
                ergebnis = Versand.zustellen(
                    eigen, partner, sendung.art, inhalt, sendung.transportId, transport
                )
                transport.schliessen()
                if (ergebnis.gelungen) break
            }
            if (ergebnis.gelungen) {
                zugestellt++
                ablage.aendereBaum { alt ->
                    alt.copy(
                        postfach = alt.postfach.filterNot { it.id == sendung.id },
                        partner = alt.partner.map {
                            if (it.kennung != partner.kennung) it
                            else it.copy(
                                zuletzt = System.currentTimeMillis(),
                                zaehlerRaus = if (ergebnis.zaehler > 0) ergebnis.zaehler else it.zaehlerRaus
                            )
                        }
                    )
                }
            } else {
                fehlversuch(sendung, ergebnis.grund)
            }
        }
        return zugestellt
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
        if (versuche == 1) meldeFehler(grund)
    }

    private fun aufgeben(sendung: Sendung) {
        ablage.aendereBaum { alt ->
            alt.copy(postfach = alt.postfach.map {
                if (it.id == sendung.id) it.copy(aufgegeben = true) else it
            })
        }
    }

    // ------------------------------------------------- Server.Handlung

    override fun eigen(): EigeneIdentitaet? {
        val z = ablage.baum.value
        if (z.kennung.isEmpty() || z.geheim.isEmpty()) return null
        return EigeneIdentitaet(z.kennung, z.name, z.oeffentlich, z.geheim, z.port)
    }

    override fun istAn(): Boolean = ablage.baum.value.dienstAn

    override fun partner(kennung: String): Partner? =
        ablage.baum.value.partner.firstOrNull { it.kennung == kennung }

    override fun einladungen(): List<Einladung> = ablage.baum.value.einladungen

    override fun paarungFertig(zweig: JsonObject, adresse: String, einladung: Einladung) {
        val ueberBluetooth = istBluetoothAdresse(adresse)
        partnerAufnehmen(
            Partner(
                kennung = text(zweig, "kennung").take(32),
                name = text(zweig, "name").take(60),
                oeffentlich = text(zweig, "oeffentlich"),
                adresse = if (ueberBluetooth) "" else adresse,
                port = zahl(zweig, "port")?.toInt() ?: Netz.PORT,
                bluetooth = if (ueberBluetooth) adresse else "",
                bestaetigt = true,
                vertraut = true,
                wartet = false,
                protokoll = "baum-fs1"
            )
        )
        ablage.aendereBaum { alt ->
            alt.copy(einladungen = alt.einladungen.filterNot { it.paarung == einladung.paarung })
        }
        melde(R.string.baum_meldung_datei_verbunden)
    }

    override fun codeAnfrage(
        name: String, kennung: String, oeffentlich: String, adresse: String, port: Int
    ) {
        val eigen = eigen() ?: return
        partnerAufnehmen(
            Partner(
                kennung = kennung,
                name = name,
                oeffentlich = oeffentlich,
                adresse = adresse,
                port = port,
                bestaetigt = false,
                vertraut = false,
                wartet = true,
                code = Krypto.paarungsCode(eigen.oeffentlich, oeffentlich),
                protokoll = "baum-1"
            )
        )
        melde(R.string.baum_meldung_code_anfrage)
    }

    /**
     * Eine geöffnete Nachricht eines bestätigten Zweigs.
     *
     * Ein `stand` wird immer sofort verarbeitet – er ändert nur ein Häkchen an
     * einer Aufgabe, die man selbst vergeben hat. Neue Inhalte kommen ohne
     * Rückfrage herein, solange der Zweig als vertraut geführt wird; sonst
     * warten sie im Eingang.
     */
    override fun nachricht(vonKennung: String, inhalt: JsonObject) {
        val art = text(inhalt, "art")
        val zweig = partner(vonKennung)
        if (art == "termin") {
            val name = zweig?.name?.ifBlank { vonKennung } ?: vonKennung
            inEingang(vonKennung, name, art, inhalt)
            melde(R.string.baum_termin_nicht_unterstuetzt)
            return
        }
        if (art == "stand") {
            standUebernehmen(inhalt)
            return
        }
        if (art == "kontakt_loeschen") {
            val partnerName = zweig?.name?.ifBlank { vonKennung } ?: vonKennung
            val loeschung = KontaktPruefung.liesLoeschung(inhalt)
                ?: throw BaumFehler("Die Kontaktlöschung ist ungültig oder hat eine unbekannte Fassung.")
            val schon = ablage.baum.value.kontaktLoeschStaende.any {
                it.partner == vonKennung && it.freigabeId == loeschung.freigabeId &&
                    !KontaktSync.istNeu(KontaktNachricht(loeschung.freigabeId, loeschung.version,
                        loeschung.quelle, loeschung.geaendert, KontaktDaten()), it.version, it.quelle)
            }
            val kontaktName = ablage.baum.value.kontaktSpuren.firstOrNull {
                it.partner == vonKennung && it.freigabeId == loeschung.freigabeId
            }?.name.orEmpty()
            if (!schon) inEingang(vonKennung,
                listOf(kontaktName, partnerName).filter(String::isNotBlank).joinToString(" · "), art, inhalt)
            return
        }
        if (art == "kontakt_sync") {
            val name = zweig?.name?.ifBlank { vonKennung } ?: vonKennung
            if (zweig?.bestaetigt == true && zweig.vertraut && zweig.kontaktSync) {
                kontaktUebernehmen(vonKennung, inhalt)
            } else {
                inEingang(vonKennung, name, art, inhalt)
            }
            return
        }
        if (art == "sync_anfrage") {
            if (zweig?.bestaetigt == true && zweig.vertraut) {
                // Erst quittieren, dann übernimmt der Dienst das vorbereitete Postfach.
                allesSynchronisieren(vonKennung, mitAnfrage = false, sofortSenden = false)
            }
            return
        }
        val name = zweig?.name?.ifBlank { vonKennung } ?: vonKennung
        if (zweig != null && !zweig.vertraut) {
            inEingang(vonKennung, name, art, inhalt)
            return
        }
        uebernehmen(vonKennung, name, inhalt)
    }

    override fun verarbeiteNachricht(
        vonKennung: String,
        inhalt: JsonObject,
        zaehler: Long?,
        transportId: String?
    ): Boolean {
        val verarbeitet = ablage.verarbeiteBaumNachricht(vonKennung, zaehler, transportId) {
            nachricht(vonKennung, inhalt)
        }
        if (text(inhalt, "art") == "termin") {
            throw BaumFehler(zusammenhang.getString(R.string.baum_termin_nicht_unterstuetzt))
        }
        return verarbeitet
    }

    /** Übernimmt einen Inhalt tatsächlich – nach Vertrauen oder nach Annahme. */
    private fun uebernehmen(vonKennung: String, vonName: String, inhalt: JsonObject) {
        when (text(inhalt, "art")) {
            "aufgabe" -> aufgabeUebernehmen(vonKennung, vonName, inhalt)
            "notiz", "notiz_sync" -> notizUebernehmen(vonKennung, inhalt)
            "kontakt_sync" -> kontaktUebernehmen(vonKennung, inhalt)
            else -> Unit                       // Unbekanntes wird übergangen.
        }
    }

    private fun inEingang(von: String, name: String, art: String, inhalt: JsonObject) {
        ablage.aendereBaum { alt -> alt.copy(eingang = (alt.eingang + Eingangsstueck(
            id = UUID.randomUUID().toString(), von = von, vonName = name, art = art,
            inhalt = Kanonisch.json.encodeToString(JsonObject.serializer(), inhalt),
            empfangen = System.currentTimeMillis()
        )).takeLast(500)) }
        melde(R.string.baum_meldung_angebot, name)
    }

    private fun kontaktUebernehmen(von: String, inhalt: JsonObject) {
        val n = KontaktSync.lies(inhalt)
            ?: throw BaumFehler("Die Kontaktnachricht ist ungültig oder hat eine unbekannte Fassung.")
        val alt = ablage.baum.value.kontaktSpuren.firstOrNull {
            it.freigabeId == n.freigabeId && it.partner == von
        }
        val wartend = ablage.baum.value.kontaktEingang.firstOrNull {
            it.partner == von && it.freigabeId == n.freigabeId
        }
        val abgelehnt = ablage.baum.value.kontaktAblehnungen.firstOrNull {
            it.partner == von && it.freigabeId == n.freigabeId
        }
        if (!KontaktEingangslogik.sollAufnehmen(n, wartend, alt?.version, alt?.quelle, abgelehnt)) return
        val karte = KontaktEingang(von, n.freigabeId, n.version, n.quelle, n.geaendert,
            n.kontakt, System.currentTimeMillis())
        ablage.aendereBaum { zustand -> zustand.copy(
            kontaktEingang = zustand.kontaktEingang.filterNot {
                it.partner == von && it.freigabeId == n.freigabeId
            } + karte
        ) }
        melde(R.string.baum_kontakte_empfangen)
    }

    /** Löscht nur die exakt an diesen Partner gebundene RawContact-/Lookup-Spur. */
    private fun kontaktLoeschungUebernehmen(von: String, inhalt: JsonObject) {
        val l = KontaktPruefung.liesLoeschung(inhalt)
            ?: throw BaumFehler("Die Kontaktlöschung ist ungültig oder hat eine unbekannte Fassung.")
        val stand = ablage.baum.value.kontaktLoeschStaende.firstOrNull {
            it.partner == von && it.freigabeId == l.freigabeId
        }
        if (stand != null && !KontaktSync.istNeu(KontaktNachricht(l.freigabeId, l.version, l.quelle,
                l.geaendert, KontaktDaten()), stand.version, stand.quelle)) return
        val spur = ablage.baum.value.kontaktSpuren.firstOrNull {
            it.partner == von && it.freigabeId == l.freigabeId
        } ?: return
        val adapter = AndroidKontakte(zusammenhang)
        AndroidJournal.hole(zusammenhang).kontaktSnapshot("contact-delete",
            adapter.journalStaende(listOf(spur.rawContactId), "delete"),
            "contact-delete:$von:${l.freigabeId}:${l.version}")
        if (!adapter.loeschen(spur.rawContactId, spur.lookupKey)) return
        ablage.aendereBaum { alt -> alt.copy(
            kontaktSpuren = alt.kontaktSpuren.filterNot { it == spur },
            kontaktLoeschStaende = alt.kontaktLoeschStaende.filterNot {
                it.partner == von && it.freigabeId == l.freigabeId
            } + KontaktLoeschStand(von, l.freigabeId, l.version, l.quelle)
        ) }
        melde(R.string.baum_kontakt_geloescht)
    }

    private fun spurSichern(spur: KontaktSpur) {
        ablage.aendereBaum { alt -> alt.copy(kontaktSpuren =
            alt.kontaktSpuren.filterNot { it.freigabeId == spur.freigabeId && it.partner == spur.partner } + spur) }
    }

    private fun aufgabeUebernehmen(vonKennung: String, vonName: String, inhalt: JsonObject) {
        AndroidJournal.hole(zusammenhang).appSnapshot("pre-sync-task")
        val gelesen = Nutzlast.liesAufgabe(inhalt, vonKennung) ?: return
        val vorhanden = ablage.aufgabeNachFremdId(gelesen.id, gelesen.herkunft)
        val jetzt = System.currentTimeMillis()
        val aufgabe = (vorhanden ?: Aufgabe(id = UUID.randomUUID().toString())).copy(
            titel = gelesen.titel,
            notiz = gelesen.notiz,
            faellig = gelesen.faellig,
            prio = gelesen.prio,
            erinnern = gelesen.erinnern,
            herkunft = gelesen.herkunft,
            vonZweig = vonName,
            fremdId = gelesen.id,
            angelegt = vorhanden?.angelegt ?: jetzt,
            geaendert = if (gelesen.geaendert > 0) gelesen.geaendert else jetzt
        )
        ablage.setzeAufgabe(aufgabe)
        Erinnerung.stellen(zusammenhang, aufgabe)
        Erinnerung.neueAufgabeMelden(zusammenhang, aufgabe, vonName)
        melde(R.string.baum_meldung_aufgabe, vonName)
    }

    /** Der Erledigt-Stand einer Aufgabe, die man selbst vergeben hat. */
    private fun standUebernehmen(inhalt: JsonObject) {
        val stand = Nutzlast.liesStand(inhalt) ?: return
        val aufgabe = ablage.aufgaben().firstOrNull {
            it.id == stand.id || it.fremdId == stand.id
        } ?: return
        // Ein mindestens ebenso neuer Zeitstempel gewinnt – wie im Organizer.
        if (stand.geaendert > 0 && stand.geaendert < aufgabe.geaendert) return
        val erneuert = aufgabe.copy(
            erledigt = stand.erledigt,
            geaendert = if (stand.geaendert > 0) stand.geaendert else System.currentTimeMillis()
        )
        ablage.setzeAufgabe(erneuert)
        Erinnerung.stellen(zusammenhang, erneuert)
        melde(
            if (stand.erledigt) R.string.baum_meldung_aufgabe_erledigt
            else R.string.baum_meldung_aufgabe_geoeffnet
        )
    }

    private fun notizUebernehmen(vonKennung: String, inhalt: JsonObject) {
        AndroidJournal.hole(zusammenhang).appSnapshot("pre-sync-note")
        val gelesen = Nutzlast.lies(inhalt, vonKennung) ?: return
        val vorhanden = ablage.notizen().firstOrNull {
            it.baumFreigabe?.id == gelesen.freigabeId
        }
        if (vorhanden == null) {
            if (gelesen.art != "notiz") return   // Fortschreibung ohne Angebot: übergehen
            val jetzt = System.currentTimeMillis()
            val anhaenge = begrenzeAnhaenge(emptyList(), gelesen.anhaenge)
            ablage.setzeNotiz(
                Notiz(
                    id = UUID.randomUUID().toString(),
                    titel = gelesen.titel,
                    text = gelesen.text,
                    html = Nutzlast.saeubereHtml(gelesen.html),
                    symbol = gelesen.symbol.ifBlank { Symbol.raten(gelesen.titel, gelesen.text) },
                    angelegt = if (gelesen.angelegt > 0) gelesen.angelegt else jetzt,
                    geaendert = jetzt,
                    anhaenge = anhaenge,
                    herkunft = zusammenhang.getString(R.string.herkunft_magnolienbaum),
                    einfuhrSchluessel = Ablage.einfuhrSchluessel(gelesen.titel, gelesen.text),
                    baumFreigabe = Freigabe(gelesen.freigabeId, listOf(vonKennung), listOf(vonKennung)),
                    baumGeaendert = gelesen.geaendert,
                    baumVersion = gelesen.version,
                    baumQuelle = gelesen.quelle
                )
            )
            melde(R.string.baum_meldung_notiz)
            return
        }
        // Höhere Fassung gewinnt; bei gleicher gewinnt die größere Quelle.
        val neuer = gelesen.version > vorhanden.baumVersion ||
            (gelesen.version == vorhanden.baumVersion && gelesen.quelle > vorhanden.baumQuelle)
        if (!neuer) return
        val freigabe = vorhanden.baumFreigabe ?: Freigabe(gelesen.freigabeId)
        val darfAnhaenge = freigabe.anhangPartner.contains(vonKennung) || gelesen.art == "notiz"
        val anhaenge = if (darfAnhaenge) begrenzeAnhaenge(vorhanden.anhaenge, gelesen.anhaenge)
            else vorhanden.anhaenge
        ablage.setzeNotiz(
            vorhanden.copy(
                titel = gelesen.titel,
                text = gelesen.text,
                html = Nutzlast.saeubereHtml(gelesen.html),
                symbol = gelesen.symbol.ifBlank { vorhanden.symbol },
                anhaenge = anhaenge,
                geaendert = System.currentTimeMillis(),
                baumFreigabe = freigabe.copy(
                    partner = (freigabe.partner + vonKennung).distinct(),
                    anhangPartner = if (gelesen.art == "notiz") {
                        (freigabe.anhangPartner + vonKennung).distinct()
                    } else freigabe.anhangPartner
                ),
                baumGeaendert = gelesen.geaendert,
                baumVersion = gelesen.version,
                baumQuelle = gelesen.quelle
            )
        )
        melde(R.string.baum_meldung_notiz_aktualisiert)
    }

    private fun begrenzeAnhaenge(bisherNotiz: List<io.gitlab.maik3531.magnolienotes.daten.Anhang>,
                                 neuNotiz: List<io.gitlab.maik3531.magnolienotes.daten.Anhang>): List<io.gitlab.maik3531.magnolienotes.daten.Anhang> {
        val sauber = Nutzlast.saubere(neuNotiz)
        val alle = ablage.notizen().flatMap { it.anhaenge }
        val entscheidung = AnhangSpeicher.entscheide(alle, bisherNotiz, sauber, zusammenhang.filesDir.usableSpace)
        if (entscheidung.erlaubt) return sauber
        melde(R.string.baum_anhaenge_speicher)
        return bisherNotiz
    }

    override fun merkeZaehler(vonKennung: String, zaehler: Long) {
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == vonKennung) {
                    it.copy(zaehlerRein = zaehler, zuletzt = System.currentTimeMillis())
                } else it
            })
        }
    }

    override fun schonGesehen(vonKennung: String, transportId: String): Boolean =
        partner(vonKennung)?.gesehen?.contains(transportId) == true

    override fun merkeTransportId(vonKennung: String, transportId: String) {
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == vonKennung) {
                    it.copy(gesehen = (it.gesehen + transportId).takeLast(256))
                } else it
            })
        }
    }

    override fun adresseGesehen(vonKennung: String, adresse: String) {
        if (adresse.isBlank()) return
        ablage.aendereBaum { alt ->
            alt.copy(partner = alt.partner.map {
                if (it.kennung == vonKennung && istBluetoothAdresse(adresse)) {
                    it.copy(bluetooth = adresse, zuletzt = System.currentTimeMillis())
                } else if (it.kennung == vonKennung && it.adresse != adresse) {
                    it.copy(adresse = adresse, zuletzt = System.currentTimeMillis())
                } else if (it.kennung == vonKennung) {
                    it.copy(zuletzt = System.currentTimeMillis())
                } else it
            })
        }
    }

    // ------------------------------------------------------------------ Hilfen

    private fun melde(@StringRes text: Int, vararg argumente: Any) {
        _meldungen.value = (_meldungen.value + zusammenhang.getString(text, *argumente)).takeLast(20)
    }

    private fun meldeFehler(grund: String) {
        _meldungen.value = (_meldungen.value + zusammenhang.fehlertext(grund)).takeLast(20)
    }

    fun meldungenLeeren() {
        _meldungen.value = emptyList()
    }

    private fun zufallskennung(laenge: Int = 16): String {
        val zeichen = "abcdefghijkmnopqrstuvwxyz23456789"
        val roh = Krypto.zufallsbytes(laenge)
        return roh.map { zeichen[(it.toInt() and 0xff) % zeichen.length] }.joinToString("")
    }

    private fun istBluetoothAdresse(adresse: String): Boolean =
        Regex("^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$").matches(adresse)

    companion object {
        @Volatile
        private var einzig: Baumwerk? = null

        fun hole(zusammenhang: Context): Baumwerk =
            einzig ?: synchronized(this) {
                einzig ?: Baumwerk(
                    Ablage.hole(zusammenhang), zusammenhang.applicationContext
                ).also { einzig = it }
            }

        internal fun fuerTest(ablage: Ablage, zusammenhang: Context): Baumwerk =
            Baumwerk(ablage, zusammenhang.applicationContext)
    }
}

data class BluetoothZiel(val adresse: String, val name: String)
