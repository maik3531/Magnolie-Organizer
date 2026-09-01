package io.gitlab.maik3531.magnolienotes.baum

import io.gitlab.maik3531.magnolienotes.daten.KontaktAblehnung
import io.gitlab.maik3531.magnolienotes.daten.KontaktEingang
import io.gitlab.maik3531.magnolienotes.daten.KontaktSpur
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import java.security.MessageDigest

enum class KontaktGruppenArt { SICHER, PRUEFEN, KONFLIKT }

data class KontaktKonflikt(val feld: String, val werte: List<String>)
data class KontaktGruppe(
    val id: String,
    val partner: String,
    val karten: List<KontaktEingang>,
    val kontakt: KontaktDaten,
    val art: KontaktGruppenArt,
    val konflikte: List<KontaktKonflikt>,
    val zusammenfuehrbar: Boolean
)
data class KontaktImportErgebnis(
    val kontakt: AndroidKontakt,
    val spuren: List<KontaktSpur>
)

/** Reine Vorimportlogik. Sie betrachtet niemals örtliche Android-Kontakte. */
object KontaktEingangslogik {
    fun istNeuer(version: Long, quelle: String, altVersion: Long, altQuelle: String) =
        version > altVersion || version == altVersion && quelle > altQuelle

    fun sollAufnehmen(
        neu: KontaktNachricht,
        wartend: KontaktEingang?,
        gebundenVersion: Long?,
        gebundenQuelle: String?,
        abgelehnt: KontaktAblehnung?
    ): Boolean {
        val staende = listOfNotNull(
            wartend?.let { it.version to it.quelle },
            gebundenVersion?.let { it to gebundenQuelle.orEmpty() },
            abgelehnt?.let { it.version to it.quelle }
        )
        return staende.all { (version, quelle) -> istNeuer(neu.version, neu.quelle, version, quelle) }
    }

    fun gruppiere(eingang: List<KontaktEingang>): List<KontaktGruppe> {
        if (eingang.isEmpty()) return emptyList()
        require(eingang.map { it.partner }.distinct().size == 1)
        val karten = eingang.groupBy { it.freigabeId }.values.map { revisionen ->
            revisionen.maxWith(compareBy<KontaktEingang> { it.version }.thenBy { it.quelle })
        }.sortedBy { it.freigabeId }

        val gruppen = karten.map { mutableListOf(it) }.toMutableList()
        val telefonAnzahl = karten.flatMap { k -> k.kontakt.telefone.map { telefon(it.wert) }.distinct() }
            .filter(String::isNotBlank).groupingBy { it }.eachCount()
        val mailAnzahl = karten.flatMap { k -> k.kontakt.emailEintraege.map { email(it.wert) }.distinct() }
            .filter(String::isNotBlank).groupingBy { it }.eachCount()

        // Harte Merkmale dürfen Gruppen verbinden; vor jeder Union wird die Gesamtgruppe neu validiert.
        var geaendert: Boolean
        do {
            geaendert = false
            loop@ for (a in gruppen.indices) for (b in a + 1 until gruppen.size) {
                val links = gruppen[a]; val rechts = gruppen[b]
                val gemeinsameTelefone = telefone(links).intersect(telefone(rechts))
                    .any { (telefonAnzahl[it] ?: 0) >= 2 }
                val gemeinsameMails = mails(links).intersect(mails(rechts))
                    .any { (mailAnzahl[it] ?: 0) >= 2 }
                if ((gemeinsameTelefone || gemeinsameMails) && konflikte(links + rechts).isEmpty()) {
                    links += rechts; gruppen.removeAt(b); geaendert = true; break@loop
                }
            }
        } while (geaendert)

        // Schwaches Namensmatching verbindet ausschließlich bislang einzelne, fragmentarische Karten.
        val nachName = gruppen.filter { it.size == 1 }.groupBy { name(it.single().kontakt) }
        nachName.filterKeys(String::isNotBlank).values.forEach { kandidaten ->
            if (kandidaten.size < 2 || kandidaten.any { !fragmentarisch(it.single().kontakt) }) return@forEach
            val zusammen = kandidaten.flatten()
            if (konflikte(zusammen).isNotEmpty()) return@forEach
            gruppen.removeAll(kandidaten.toSet()); gruppen += zusammen.toMutableList()
        }

        // Übrige gleichnamige Karten werden gemeinsam zur Prüfung gezeigt, aber nie automatisch importiert.
        val restNachName = gruppen.groupBy { gruppe -> name(gruppe.first().kontakt) }
        restNachName.filterKeys(String::isNotBlank).values.forEach { kandidaten ->
            if (kandidaten.size < 2) return@forEach
            val zusammen = kandidaten.flatten()
            gruppen.removeAll(kandidaten.toSet()); gruppen += zusammen.toMutableList()
        }

        return gruppen.map { gruppe ->
            val konflikt = konflikte(gruppe)
            val sicher = konflikt.isEmpty() && (gruppe.size == 1 ||
                hatGemeinsamesHartesMerkmal(gruppe) || gruppe.all { fragmentarisch(it.kontakt) })
            KontaktGruppe(
                id = gruppenId(gruppe.first().partner, gruppe.map { it.freigabeId }),
                partner = gruppe.first().partner,
                karten = gruppe.sortedBy { it.freigabeId },
                kontakt = vereinige(gruppe.map { it.kontakt }),
                art = if (konflikt.isNotEmpty()) KontaktGruppenArt.KONFLIKT
                    else if (sicher) KontaktGruppenArt.SICHER else KontaktGruppenArt.PRUEFEN,
                konflikte = konflikt,
                zusammenfuehrbar = konflikt.isEmpty()
            )
        }.sortedBy { KontaktPruefung.name(it.kontakt).lowercase() }
    }

    fun gruppenId(partner: String, ids: List<String>): String {
        val roh = partner + "\u0000" + ids.sorted().joinToString("\u0000")
        return MessageDigest.getInstance("SHA-256").digest(roh.toByteArray())
            .take(12).joinToString("") { "%02x".format(it) }
    }

    fun importiere(karten: List<KontaktEingang>, schreiber: KontaktSchreiber,
                   gebundeneRawId: Long? = null): KontaktImportErgebnis {
        require(karten.isNotEmpty() && karten.map { it.partner }.distinct().size == 1)
        val kontakt = vereinige(karten.map { it.kontakt })
        var lokal = gebundeneRawId?.let { schreiber.mischen(it, kontakt.copy(foto = "")) }
            ?: schreiber.anlegen(kontakt.copy(foto = ""))
        if (kontakt.foto.isNotEmpty()) lokal = schreiber.fotoErgaenzen(lokal.rawContactId, kontakt.foto) ?: lokal
        val spuren = karten.map { karte -> KontaktSpur(
            lokal.lookupKey, lokal.rawContactId, karte.freigabeId, karte.version, karte.quelle,
            KontaktSync.hash(kontakt), karte.partner, KontaktPruefung.name(kontakt)
        ) }
        return KontaktImportErgebnis(lokal, spuren)
    }

    fun bereinigePartner(zustand: Baumzustand, partner: String): Baumzustand = zustand.copy(
        partner = zustand.partner.filterNot { it.kennung == partner },
        postfach = zustand.postfach.filterNot { it.an == partner },
        eingang = zustand.eingang.filterNot { it.von == partner },
        kontaktEingang = zustand.kontaktEingang.filterNot { it.partner == partner },
        kontaktAblehnungen = zustand.kontaktAblehnungen.filterNot { it.partner == partner },
        kontaktVorschlaege = zustand.kontaktVorschlaege.filterNot { it.partner == partner },
        kontaktSpuren = zustand.kontaktSpuren.filterNot { it.partner == partner },
        kontaktLoeschStaende = zustand.kontaktLoeschStaende.filterNot { it.partner == partner }
    )

    fun vereinige(kontakte: List<KontaktDaten>): KontaktDaten {
        fun eindeutig(block: (KontaktDaten) -> String): String {
            val werte = kontakte.map(block).map(String::trim).filter(String::isNotBlank)
            return werte.distinctBy(::text).singleOrNull().orEmpty()
        }
        val notizen = kontakte.map { it.notiz.trim() }.filter(String::isNotBlank).distinct()
        return KontaktSync.normalisiere(KontaktDaten(
            vorname = eindeutig { it.vorname }, nachname = eindeutig { it.nachname },
            firma = eindeutig { it.firma }, geburtstag = eindeutig { it.geburtstag },
            notiz = notizen.singleOrNull().orEmpty(),
            foto = kontakte.map { it.foto }.filter(String::isNotBlank).distinct().singleOrNull().orEmpty(),
            telefone = kontakte.flatMap { it.telefone }.distinctBy { telefon(it.wert) },
            emailEintraege = kontakte.flatMap { it.emailEintraege }.distinctBy { email(it.wert) },
            anschriften = kontakte.flatMap { it.anschriften }
        ))
    }

    private fun konflikte(karten: List<KontaktEingang>): List<KontaktKonflikt> {
        val kontakte = karten.map { it.kontakt }
        fun werte(name: String, normal: (String) -> String = ::text,
                  block: (KontaktDaten) -> String): KontaktKonflikt? {
            val v = kontakte.map(block).map(String::trim).filter(String::isNotBlank).distinctBy(normal)
            return if (v.size > 1) KontaktKonflikt(name, v) else null
        }
        return listOfNotNull(
            werte("Vorname") { it.vorname }, werte("Nachname") { it.nachname },
            werte("Firma") { it.firma }, werte("Geburtstag") { it.geburtstag },
            werte("Bild", { it }) { it.foto }, werte("Notiz", { it.trim() }) { it.notiz }
        )
    }

    private fun fragmentarisch(k: KontaktDaten): Boolean {
        val klassen = listOf(k.telefone.isNotEmpty(), k.emailEintraege.isNotEmpty(),
            k.anschriften.isNotEmpty(), k.firma.isNotBlank(), k.geburtstag.isNotBlank(),
            k.foto.isNotBlank(), k.notiz.isNotBlank()).count { it }
        return name(k).isNotBlank() && klassen <= 1
    }

    private fun hatGemeinsamesHartesMerkmal(karten: List<KontaktEingang>): Boolean =
        karten.flatMap { it.kontakt.telefone.map { w -> telefon(w.wert) } }.groupingBy { it }.eachCount().any { it.key.isNotBlank() && it.value > 1 } ||
            karten.flatMap { it.kontakt.emailEintraege.map { w -> email(w.wert) } }.groupingBy { it }.eachCount().any { it.key.isNotBlank() && it.value > 1 }

    private fun telefone(k: List<KontaktEingang>) = k.flatMap { it.kontakt.telefone }.map { telefon(it.wert) }.filter(String::isNotBlank).toSet()
    private fun mails(k: List<KontaktEingang>) = k.flatMap { it.kontakt.emailEintraege }.map { email(it.wert) }.filter(String::isNotBlank).toSet()
    private fun name(k: KontaktDaten) = listOf(k.vorname, k.nachname).joinToString(" ") { text(it) }.trim()
    private fun text(s: String) = s.trim().lowercase().replace(Regex("\\s+"), " ")
    private fun email(s: String) = s.trim().lowercase()
    private fun telefon(s: String): String {
        val roh = s.trim(); val ziffern = roh.filter(Char::isDigit)
        return when { roh.startsWith("+") -> ziffern; ziffern.startsWith("00") -> ziffern.drop(2); else -> ziffern }
    }
}
