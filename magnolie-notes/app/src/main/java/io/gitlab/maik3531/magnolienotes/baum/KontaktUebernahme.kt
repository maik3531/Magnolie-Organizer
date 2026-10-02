package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.KontaktEingang
import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur

enum class KontaktEntscheidung { BEHALTEN, MISCHEN, ERSETZEN, NEU, NEUESTE }

data class KontaktZiel(val kontakt: AndroidKontakt, val stark: Boolean, val inhaltszeit: Long)
data class KontaktUebernahme(
    val gruppe: KontaktGruppe,
    val ziele: List<KontaktZiel>,
    val fernzeit: Long,
    val vorauswahl: KontaktEntscheidung?
)
data class KontaktAuswahl(
    val gruppe: String,
    val entscheidung: KontaktEntscheidung,
    val rawId: Long? = null,
    val fernfelder: Set<String> = emptySet(),
    val geburtsnameBehalten: Boolean = false
)
data class KontaktUebernahmeVorschau(val id: String, val eintraege: List<KontaktUebernahme>)

/** Pure planning: local contacts are read once by the caller; no provider writes. */
object KontaktUebernahmePlan {
    val felder = setOf("vorname", "nachname", "anzeigename", "firma", "geburtstag", "jubilaeum", "notiz", "foto")

    fun planen(gruppen: List<KontaktGruppe>, snapshot: KontaktSnapshot, spuren: List<KontaktSpur>,
               jetzt: Long = System.currentTimeMillis()): List<KontaktUebernahme> {
        require(snapshot.vollstaendig)
        return gruppen.map { gruppe ->
            val bindungen = spuren.filter { spur -> gruppe.karten.any {
                it.partner == spur.partner && it.freigabeId == spur.freigabeId
            } }
            val gebunden = snapshot.kontakte.filter { lokal -> bindungen.any {
                it.rawContactId in lokal.rawContactIds && (it.lookupKey.isBlank() || it.lookupKey == lokal.lookupKey)
            } }
            val hart = snapshot.kontakte.filter { lokal -> gruppe.karten.any { hartGleich(it.kontakt, lokal.daten) } }
            val namen = gruppe.karten.map { name(it.kontakt) }.filter(String::isNotBlank).toSet()
            val schwach = snapshot.kontakte.filter { name(it.daten).let { n -> n.isNotBlank() && n in namen } }
            val kandidaten = (gebunden + hart + schwach).distinctBy { it.contactId }
            val starke = (gebunden + hart).distinctBy { it.contactId }
            val zeit = originalZeit(gruppe.karten, gruppe.kontakt, jetzt)
            val ziele = kandidaten.map { kontakt ->
                val spurenHier = spuren.filter { it.rawContactId in kontakt.rawContactIds }
                val raw = bindungen.map { it.rawContactId }.filter { it in kontakt.rawContactIds }.distinct().singleOrNull()
                KontaktZiel(if (raw == null) kontakt else kontakt.copy(rawContactId = raw),
                    starke.size == 1 && kontakt.contactId == starke.single().contactId && bindungen.all {
                        it.rawContactId in kontakt.rawContactIds && (it.lookupKey.isBlank() || it.lookupKey == kontakt.lookupKey)
                    },
                    KontaktSync.inhaltszeit(KontaktSync.hash(kontakt.daten), kontakt.providerGeaendert, spurenHier, jetzt))
            }
            val identisch = ziele.singleOrNull()?.let { it.stark &&
                KontaktSync.hash(it.kontakt.daten) == KontaktSync.hash(gruppe.kontakt) } == true
            KontaktUebernahme(gruppe, ziele, zeit, when {
                gruppe.art != KontaktGruppenArt.SICHER -> null
                kandidaten.isEmpty() && bindungen.isEmpty() -> KontaktEntscheidung.NEU
                identisch -> KontaktEntscheidung.MISCHEN
                else -> null
            })
        }
    }

    fun originalZeit(karten: List<KontaktEingang>, inhalt: KontaktDaten, jetzt: Long): Long {
        val hash = KontaktSync.hash(inhalt)
        return karten.filter { KontaktSync.hash(it.kontakt) == hash }
            .map { it.inhaltGeaendert }.filter { it > 0 && it <= jetzt + 300_000 && it <= 253402300799999L }
            .maxOrNull() ?: 0
    }

    fun neuesteMoeglich(eintrag: KontaktUebernahme, ziel: KontaktZiel) = ziel.stark &&
        eintrag.gruppe.zusammenfuehrbar && ziel.kontakt.rawContactIds.size == 1 &&
        eintrag.fernzeit > 0 && ziel.inhaltszeit > 0 && eintrag.fernzeit != ziel.inhaltszeit

    fun inhalt(eintrag: KontaktUebernahme, wahl: KontaktAuswahl,
               geburtsname: (String) -> String = { "Birth name: $it" }): KontaktDaten {
        val neu = inhaltOhneGeburtsname(eintrag, wahl)
        if (!wahl.geburtsnameBehalten) return neu
        val alt = eintrag.ziele.single { it.kontakt.rawContactId == wahl.rawId }.kontakt.daten
        require(alt.nachname.isNotBlank() && neu.nachname.isNotBlank() && alt.nachname != neu.nachname)
        val zeile = geburtsname(alt.nachname)
        return if (zeile in neu.notiz.lines()) neu else neu.copy(notiz = listOf(neu.notiz, zeile).filter(String::isNotBlank).joinToString("\n"))
    }

    private fun inhaltOhneGeburtsname(eintrag: KontaktUebernahme, wahl: KontaktAuswahl): KontaktDaten {
        require(wahl.gruppe == eintrag.gruppe.id && wahl.fernfelder.all { it in felder })
        require(eintrag.gruppe.zusammenfuehrbar)
        val fern = eintrag.gruppe.kontakt
        if (wahl.entscheidung == KontaktEntscheidung.NEU) { require(wahl.rawId == null); return fern }
        val ziel = eintrag.ziele.single { it.kontakt.rawContactId == wahl.rawId }
        val lokal = ziel.kontakt.daten
        if (wahl.entscheidung == KontaktEntscheidung.BEHALTEN) return lokal
        if (wahl.entscheidung == KontaktEntscheidung.NEUESTE) {
            require(neuesteMoeglich(eintrag, ziel))
            return if (ziel.inhaltszeit > eintrag.fernzeit) lokal else fern.copy(foto = lokal.foto.ifBlank { fern.foto })
        }
        if (wahl.entscheidung == KontaktEntscheidung.ERSETZEN) {
            require(ziel.kontakt.rawContactIds.size == 1)
            return fern.copy(foto = if ("foto" in wahl.fernfelder) fern.foto else lokal.foto.ifBlank { fern.foto })
        }
        fun wert(feld: String, a: String, b: String) = if (feld in wahl.fernfelder) b else a.ifBlank { b }
        val namenFern = wahl.fernfelder.any { it in setOf("vorname", "nachname", "anzeigename") }
        return KontaktSync.mische(lokal, fern).copy(
            vorname = wert("vorname", lokal.vorname, fern.vorname),
            nachname = wert("nachname", lokal.nachname, fern.nachname),
            anzeigename = wert("anzeigename", lokal.anzeigename, fern.anzeigename),
            vcardName = if (namenFern) fern.vcardName else lokal.vcardName.ifEmpty { fern.vcardName },
            firma = wert("firma", lokal.firma, fern.firma),
            geburtstag = wert("geburtstag", lokal.geburtstag, fern.geburtstag),
            jubilaeum = wert("jubilaeum", lokal.jubilaeum, fern.jubilaeum),
            notiz = if ("notiz" in wahl.fernfelder) fern.notiz else
                if (fern.notiz.isBlank() || lokal.notiz == fern.notiz ||
                    ("\n\n" + lokal.notiz + "\n\n").contains("\n\n" + fern.notiz + "\n\n")) lokal.notiz
                else listOf(lokal.notiz, fern.notiz).filter(String::isNotBlank).joinToString("\n\n"),
            foto = wert("foto", lokal.foto, fern.foto)
        )
    }

    private fun name(k: KontaktDaten) = listOf(k.vorname, k.nachname).joinToString(" ")
        .trim().ifBlank { k.anzeigename.trim() }.lowercase().replace(Regex("\\s+"), " ")
    private fun telefon(s: String): String {
        val roh = s.trim(); val ziffern = roh.filter(Char::isDigit)
        return if (roh.startsWith("00")) "+" + ziffern.drop(2) else if (roh.startsWith("+")) "+$ziffern" else ziffern
    }
    private fun hartGleich(a: KontaktDaten, b: KontaktDaten): Boolean {
        val nummern = a.telefone.map { telefon(it.wert) }.filter(String::isNotBlank).toSet()
        val mails = a.emailEintraege.map { it.wert.trim().lowercase() }.filter(String::isNotBlank).toSet()
        return b.telefone.any { telefon(it.wert) in nummern } || b.emailEintraege.any { it.wert.trim().lowercase() in mails }
    }
}
