package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable

/**
 * Eine Notiz. Die Felder `titel`, `text`, `html` und `anhaenge` entsprechen
 * genau denen des Organizers, damit sie ohne Umrechnung durch den
 * Magnolienbaum passen. Alles Weitere ist entweder rein örtlich (`symbol`,
 * `herkunft`) oder wird vom Organizer bis auf Weiteres überlesen.
 */
@Serializable
data class Notiz(
    val id: String,
    val titel: String = "",
    val text: String = "",
    val html: String = "",
    val notizbuchId: String = Ablage.STANDARD_BUCH,
    val symbol: String = Symbol.NOTIZ,
    /** Anlagezeit in Millisekunden seit 1970 – Tag und Uhrzeit der Notiz. */
    val angelegt: Long = 0L,
    /** Letzte Änderung in Millisekunden seit 1970. */
    val geaendert: Long = 0L,
    val anhaenge: List<Anhang> = emptyList(),
    /** Aus welchem Fremdprogramm die Notiz stammt, für die Herkunftszeile. */
    val herkunft: String = "",
    /** Fingerabdruck des Ursprungstextes; verhindert doppelte Übernahmen. */
    val einfuhrSchluessel: String = "",
    /** Freigabe an den Magnolienbaum, sobald die Notiz geteilt wurde. */
    val baumFreigabe: Freigabe? = null,
    val baumGeaendert: Long = 0L,
    val baumVersion: Long = 0L,
    val baumQuelle: String = ""
) {
    val vorschau: String
        get() {
            val roh = text.ifBlank { html.replace(Regex("<[^>]*>"), " ") }
            return roh.replace(Regex("\\s+"), " ").trim().take(140)
        }

    val anzeigeTitel: String
        get() = titel.ifBlank { text.lineSequence().firstOrNull()?.trim().orEmpty() }
            .ifBlank { "" }
}

@Serializable
data class Anhang(
    val id: String,
    val name: String = "",
    /** "image" oder "pdf" – dieselben zwei Arten wie im Organizer. */
    val art: String = "image",
    /** Vollständige data:-URL mit Base64-Nutzlast. */
    val daten: String = ""
)

@Serializable
data class Freigabe(
    val id: String,
    val partner: List<String> = emptyList(),
    val anhangPartner: List<String> = emptyList()
)

@Serializable
data class Notizbuch(
    val id: String,
    val name: String
)

/**
 * Eine Aufgabe. Die Felder `titel`, `notiz`, `faellig`, `prio` und `erinnern`
 * sind genau die, die der Organizer beim Delegieren überträgt; `fremdId` und
 * `herkunft` merken sich, woher sie kam, damit die Rückmeldung den Weg
 * zurückfindet.
 */
@Serializable
data class Aufgabe(
    val id: String,
    val titel: String = "",
    val notiz: String = "",
    /** Fälligkeit als ISO-Datum `JJJJ-MM-TT`; leer heißt „ohne Termin“. */
    val faellig: String = "",
    /** 1 = dringend, 2 = normal, 3 = kann warten – wie im Organizer. */
    val prio: Int = 2,
    val erledigt: Boolean = false,
    val erinnern: Boolean = false,
    /** Wie viele Tage vor der Fälligkeit erinnert wird; 0 heißt am Tag selbst. */
    val vorlaufTage: Int = 0,
    /** Uhrzeit der Erinnerung in Minuten seit Mitternacht. */
    val erinnerungsMinute: Int = 8 * 60,
    /** Kennung des Zweigs, von dem die Aufgabe stammt. */
    val herkunft: String = "",
    /** Klarname dieses Zweigs, für die Herkunftszeile. */
    val vonZweig: String = "",
    /** Die Kennung, unter der die Aufgabe beim Ursprung geführt wird. */
    val fremdId: String = "",
    /** An welchen Zweig sie weitergereicht wurde. */
    val delegiertAn: String = "",
    val angelegt: Long = 0L,
    val geaendert: Long = 0L,
    /** Stable cross-platform hierarchy identity; legacy rows are normalized on load. */
    val uid: String = "",
    val elternUid: String = "",
    val reihenfolge: Int = 0
) {
    /** Eine fremde Aufgabe darf nur den Erledigt-Stand zurückmelden. */
    val istFremd: Boolean get() = fremdId.isNotEmpty() && herkunft.isNotEmpty()

    val anzeigeTitel: String get() = titel.ifBlank { notiz.lineSequence().firstOrNull().orEmpty() }
}

/**
 * Ein bestätigter Zweig. Der öffentliche Schlüssel ist bei der Paarung
 * angeheftet worden und wird nie stillschweigend ersetzt.
 */
@Serializable
data class Partner(
    val kennung: String,
    val name: String = "",
    val oeffentlich: String = "",
    val adresse: String = "",
    val port: Int = 8737,
    /** Optionaler, ausdrücklich eingerichteter Weg über Internet, VPN oder eigenen Server. */
    val fernAdresse: String = "",
    val fernPort: Int = 8737,
    /** MAC-Adresse, falls der Zweig über Bluetooth erreichbar ist. */
    val bluetooth: String = "",
    val bestaetigt: Boolean = false,
    /**
     * Ein einmal gepaarter Zweig bleibt vertraut: sein Schlüssel ist
     * angeheftet, seine Inhalte werden ohne erneute Rückfrage übernommen.
     * Wer das nicht will, schaltet es ab – dann wartet alles im Eingang.
     */
    val vertraut: Boolean = false,
    /** Kontakte sind je Zweig separat und grundsätzlich ausgeschaltet. */
    val kontaktSync: Boolean = false,
    /** Manuell bestätigte Löschmeldungen sind separat und standardmäßig ausgeschaltet. */
    val kontaktLoeschSync: Boolean = false,
    /** Wartet auf die Bestätigung des Menschen (kurzer Codeweg). */
    val wartet: Boolean = false,
    /** Der beim kurzen Weg zu vergleichende sechsstellige Code. */
    val code: String = "",
    val protokoll: String = "baum-fs1",
    val zuletzt: Long = 0L,
    /** Zählerstand beider Richtungen für den älteren Umschlag `baum-1`. */
    val zaehlerRaus: Long = 0L,
    val zaehlerRein: Long = 0L,
    /** Zuletzt gesehene Transportkennungen, gegen doppelte Zustellung. */
    val gesehen: List<String> = emptyList()
)

/** Ein Eintrag im Postfach – gespeichert, bevor der erste Netzversuch läuft. */
@Serializable
data class Sendung(
    val id: String,
    val transportId: String,
    val an: String,
    val art: String,
    val inhalt: String,
    val versuche: Int = 0,
    val naechsterVersuch: Long = 0L,
    val angelegt: Long = 0L,
    val aufgegeben: Boolean = false,
    val syncEpoch: String = ""
)

/** Ein empfangenes Angebot, das noch angenommen oder abgelehnt werden will. */
@Serializable
data class Eingangsstueck(
    val id: String,
    val von: String,
    val vonName: String = "",
    val art: String = "",
    /** Der vollständige Inhalt als JSON, damit nichts verlorengeht. */
    val inhalt: String = "",
    val empfangen: Long = 0L
)

/** Die eigene, dauerhafte Baumidentität. */
@Serializable
data class Baumzustand(
    val kennung: String = "",
    val name: String = "",
    val oeffentlich: String = "",
    val geheim: String = "",
    val port: Int = 8737,
    val dienstAn: Boolean = false,
    val bluetoothAn: Boolean = false,
    val automatischWlan: Boolean = false,
    val letzteAutoSync: Long = 0L,
    val partner: List<Partner> = emptyList(),
    val postfach: List<Sendung> = emptyList(),
    /** Angebote, die auf eine Entscheidung warten. */
    val eingang: List<Eingangsstueck> = emptyList(),
    /** Offene eigene Einladungen samt Einmalgeheimnis. */
    val einladungen: List<io.gitlab.maik3531.magnolienotes.baum.Einladung> = emptyList(),
    /** Ausschließliche Zuordnung zwischen Systemkontakt und Baumfreigabe. */
    val kontaktSpuren: List<KontaktSpur> = emptyList(),
    /** Validierte Kontaktkarten, die vor jedem Android-Schreibzugriff auf eine Entscheidung warten. */
    val kontaktEingang: List<KontaktEingang> = emptyList(),
    /** Dauerhafte Entscheidungen verhindern, dass dieselbe abgelehnte Revision erneut angeboten wird. */
    val kontaktAblehnungen: List<KontaktAblehnung> = emptyList(),
    val kontaktVorschlaege: List<KontaktVorschlag> = emptyList(),
    val kontaktLoeschStaende: List<KontaktLoeschStand> = emptyList(),
    /** Trennt vor einer Wiederherstellung erzeugte Lösch-/Outbox-Stände sicher ab. */
    val syncEpoch: String = "",
    val additiveBaselineAusstehend: Boolean = false,
    val quarantiniertesPostfach: List<Sendung> = emptyList()
)

@Serializable
data class KontaktEingang(
    val partner: String = "",
    val freigabeId: String = "",
    val version: Long = 0L,
    val quelle: String = "",
    val geaendert: Long = 0L,
    val kontakt: io.gitlab.maik3531.magnolienotes.baum.KontaktDaten =
        io.gitlab.maik3531.magnolienotes.baum.KontaktDaten(),
    val empfangen: Long = 0L
)

@Serializable
data class KontaktAblehnung(
    val partner: String = "",
    val freigabeId: String = "",
    val version: Long = 0L,
    val quelle: String = ""
)

@Serializable
data class KontaktSpur(
    val lookupKey: String = "",
    val rawContactId: Long = 0L,
    val freigabeId: String = "",
    val version: Long = 0L,
    val quelle: String = "",
    val hash: String = "",
    val partner: String = "",
    val name: String = ""
)

@Serializable
data class KontaktVorschlag(
    val id: String = "",
    val partner: String = "",
    /** neu, geaendert, dublette oder loeschen */
    val art: String = "",
    val name: String = "",
    val rawContactId: Long = 0L,
    val lookupKey: String = "",
    val andereRawContactId: Long = 0L,
    val andereLookupKey: String = "",
    val freigabeId: String = "",
    val version: Long = 0L,
    val quelle: String = "",
    val geaendert: Long = 0L
)

@Serializable
data class KontaktLoeschStand(
    val partner: String = "",
    val freigabeId: String = "",
    val version: Long = 0L,
    val quelle: String = ""
)

@Serializable
data class PapierkorbEinstellungen(
    val an: Boolean = true,
    /** 0 means manual cleanup only. */
    val tage: Int = 30
)

/** A typed private snapshot. Exactly one payload is set for valid entries. */
@Serializable
data class PapierkorbEintrag(
    val id: String,
    val art: String,
    val name: String = "",
    val geloescht_ms: Long,
    val parent_id: String = "",
    val notiz: Notiz? = null,
    val aufgabe: Aufgabe? = null,
    val notizbuch: Notizbuch? = null,
    val anhang: Anhang? = null,
    /** Original note-to-notebook mappings for notebook restoration. */
    val notiz_zuordnungen: Map<String, String> = emptyMap()
)

@Serializable
data class Bestand(
    val fassung: Int = 2,
    val notizen: List<Notiz> = emptyList(),
    val notizbuecher: List<Notizbuch> = emptyList(),
    val aufgaben: List<Aufgabe> = emptyList(),
    val papierkorb: List<PapierkorbEintrag> = emptyList(),
    val papierkorbEinstellungen: PapierkorbEinstellungen = PapierkorbEinstellungen(),
    val personalSync: PersonalSyncState = PersonalSyncState()
)

/** Die Sinnbilder, mit denen eine Notiz in der Liste steht. */
object Symbol {
    const val NOTIZ = "notiz"
    const val EINKAUF = "einkauf"
    const val AUFGABE = "aufgabe"
    const val TERMIN = "termin"
    const val IDEE = "idee"
    const val REISE = "reise"
    const val REZEPT = "rezept"
    const val GELD = "geld"
    const val ARBEIT = "arbeit"
    const val PERSON = "person"
    const val GESUNDHEIT = "gesundheit"
    const val ZITAT = "zitat"

    val alle = listOf(
        NOTIZ, EINKAUF, AUFGABE, TERMIN, IDEE, REISE,
        REZEPT, GELD, ARBEIT, PERSON, GESUNDHEIT, ZITAT
    )

    /**
     * Rät ein Sinnbild aus dem Wortlaut. Wer selbst eines wählt, überschreibt
     * das Ergebnis dauerhaft; geraten wird nur beim Anlegen und Übernehmen.
     */
    fun raten(titel: String, text: String): String {
        val alles = (titel + "\n" + text).lowercase()
        val ersteZeilen = alles.lineSequence().take(6).joinToString("\n")
        fun trifft(vararg woerter: String) = woerter.any { it in alles }

        if (trifft("einkauf", "einkaufsliste", "supermarkt", "milch", "besorgen",
                "shopping", "grocery", "aldi", "lidl", "rewe", "edeka")
        ) return EINKAUF
        if (trifft("rezept", "zutaten", "backen", "kochen", "teig", "recipe",
                "ingredients", "esslöffel", "gramm mehl")
        ) return REZEPT
        if (trifft("urlaub", "reise", "flug", "hotel", "koffer", "packliste",
                "travel", "flight", "bahn ", "zugticket")
        ) return REISE
        if (trifft("rechnung", "konto", "überweisung", "euro", "betrag",
                "budget", "steuer", "invoice", "payment")
        ) return GELD
        if (trifft("arzt", "medikament", "tablette", "blutdruck", "termin beim arzt",
                "praxis", "rezept vom arzt", "doctor", "pharmacy")
        ) return GESUNDHEIT
        if (trifft("besprechung", "meeting", "projekt", "protokoll", "kunde",
                "arbeit", "kollege", "deadline", "sprint")
        ) return ARBEIT
        if (trifft("idee", "einfall", "konzept", "brainstorm", "vielleicht könnte",
                "idea")
        ) return IDEE
        if (trifft("geburtstag", "telefon", "anrufen", "adresse von", "kontakt",
                "handynummer")
        ) return PERSON
        if (trifft("uhr", "termin", "montag", "dienstag", "mittwoch", "donnerstag",
                "freitag", "samstag", "sonntag", "kalender")
        ) return TERMIN
        // Eine Liste aus Spiegelstrichen oder Häkchen ist fast immer eine Aufgabe.
        val listenzeilen = ersteZeilen.lineSequence().count {
            val z = it.trim()
            z.startsWith("- ") || z.startsWith("* ") || z.startsWith("[ ]") ||
                z.startsWith("[x]") || z.startsWith("☐") || z.startsWith("☑") ||
                z.startsWith("•")
        }
        if (listenzeilen >= 2) return AUFGABE
        if (alles.trimStart().startsWith("„") || alles.trimStart().startsWith("\"")) {
            return ZITAT
        }
        return NOTIZ
    }
}
