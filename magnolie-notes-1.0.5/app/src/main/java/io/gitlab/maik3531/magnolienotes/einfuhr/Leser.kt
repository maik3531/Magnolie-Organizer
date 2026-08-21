package io.gitlab.maik3531.magnolienotes.einfuhr

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.Json
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * Die Leser für die einzelnen Exportformate. Jeder bekommt den Rohtext und
 * liefert Notizen; welcher zuständig ist, entscheidet [Einfuhr].
 */
object Leser {

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    // ------------------------------------------------------------ Google Keep

    /**
     * Google Takeout legt je Notiz eine JSON-Datei ab:
     * `{"title":…,"textContent":…,"listContent":[…],"userEditedTimestampUsec":…}`
     */
    fun keepJson(text: String, dateiname: String): List<Rohnotiz> {
        val wurzel = runCatching { json.parseToJsonElement(text) }.getOrNull() ?: return emptyList()
        val objekte = when (wurzel) {
            is JsonArray -> wurzel.filterIsInstance<JsonObject>()
            is JsonObject -> listOf(wurzel)
            else -> return emptyList()
        }
        return objekte.mapNotNull { objekt ->
            val titel = zeichenkette(objekt, "title")
            val inhalt = zeichenkette(objekt, "textContent")
            val liste = (objekt["listContent"] as? JsonArray)?.mapNotNull { teil ->
                val eintrag = teil as? JsonObject ?: return@mapNotNull null
                val erledigt = (eintrag["isChecked"] as? JsonPrimitive)?.content == "true"
                val zeile = zeichenkette(eintrag, "text")
                if (zeile.isBlank()) null else (if (erledigt) "[x] " else "[ ] ") + zeile
            }?.joinToString("\n").orEmpty()
            val zusammen = listOf(inhalt, liste).filter { it.isNotBlank() }.joinToString("\n")
            if (titel.isBlank() && zusammen.isBlank()) return@mapNotNull null
            // Keep zählt in Mikrosekunden.
            val bearbeitet = zahl(objekt, "userEditedTimestampUsec")?.div(1000) ?: 0L
            val erzeugt = zahl(objekt, "createdTimestampUsec")?.div(1000) ?: bearbeitet
            Rohnotiz(
                titel = titel,
                text = zusammen,
                angelegt = erzeugt,
                geaendert = bearbeitet,
                herkunft = "Google Keep",
                notizbuch = erstesEtikett(objekt).ifBlank { "Google Keep" }
            )
        }.also { if (it.isEmpty() && dateiname.isNotBlank()) Unit }
    }

    private fun erstesEtikett(objekt: JsonObject): String {
        val etiketten = objekt["labels"] as? JsonArray ?: return ""
        val erstes = etiketten.firstOrNull() as? JsonObject ?: return ""
        return zeichenkette(erstes, "name")
    }

    /** Takeout schreibt zusätzlich HTML je Notiz. */
    fun keepHtml(text: String, dateiname: String): List<Rohnotiz> {
        val titel = zwischen(text, "<div class=\"title\">", "</div>")
            .ifBlank { zwischen(text, "<title>", "</title>") }
            .let { Rohnotiz.entwirreEntitaeten(nurText(it)) }
        val koerper = zwischen(text, "<div class=\"content\">", "</div>")
            .ifBlank { zwischen(text, "<body", "</body>").substringAfter('>') }
        val zeitstempel = zwischen(text, "<div class=\"heading\"", "</div>")
            .let { nurText(it.substringAfter('>')) }.trim()
        if (koerper.isBlank() && titel.isBlank()) return emptyList()
        val wann = zeitAusText(zeitstempel)
        return listOf(
            Rohnotiz(
                titel = titel.ifBlank { dateiname.substringBeforeLast('.') },
                text = "",
                html = koerper,
                angelegt = wann,
                geaendert = wann,
                herkunft = "Google Keep",
                notizbuch = "Google Keep"
            )
        )
    }

    // -------------------------------------------------------------- Evernote

    /** `.enex` ist XML mit `<note><title/><content/><created/><updated/></note>`. */
    fun enex(text: String): List<Rohnotiz> {
        val aus = mutableListOf<Rohnotiz>()
        var stelle = 0
        while (true) {
            val auf = text.indexOf("<note>", stelle)
            if (auf < 0) break
            val zu = text.indexOf("</note>", auf)
            if (zu < 0) break
            val stueck = text.substring(auf, zu)
            val titel = Rohnotiz.entwirreEntitaeten(zwischen(stueck, "<title>", "</title>").trim())
            val inhalt = zwischen(stueck, "<content>", "</content>")
                .replace("<![CDATA[", "").replace("]]>", "")
            aus += Rohnotiz(
                titel = titel,
                text = "",
                html = inhalt,
                angelegt = enexZeit(zwischen(stueck, "<created>", "</created>").trim()),
                geaendert = enexZeit(zwischen(stueck, "<updated>", "</updated>").trim()),
                herkunft = "Evernote",
                notizbuch = "Evernote"
            )
            stelle = zu + 7
        }
        return aus.filter { it.hatInhalt }
    }

    private fun enexZeit(roh: String): Long = runCatching {
        val formen = SimpleDateFormat("yyyyMMdd'T'HHmmss'Z'", Locale.ROOT)
        formen.timeZone = TimeZone.getTimeZone("UTC")
        formen.parse(roh)?.time ?: 0L
    }.getOrDefault(0L)

    // ------------------------------------------------------------ Simplenote

    /** `{"activeNotes":[{"content":…,"creationDate":…,"lastModified":…}]}` */
    fun simplenote(text: String): List<Rohnotiz> {
        val wurzel = runCatching { json.parseToJsonElement(text) as? JsonObject }.getOrNull()
            ?: return emptyList()
        val aus = mutableListOf<Rohnotiz>()
        for (feld in listOf("activeNotes", "trashedNotes")) {
            if (feld == "trashedNotes") continue      // Papierkorb bleibt Papierkorb.
            val liste = wurzel[feld] as? JsonArray ?: continue
            for (teil in liste) {
                val objekt = teil as? JsonObject ?: continue
                val inhalt = zeichenkette(objekt, "content")
                if (inhalt.isBlank()) continue
                aus += Rohnotiz(
                    titel = inhalt.lineSequence().first().trim().take(120),
                    text = inhalt,
                    angelegt = isoZeit(zeichenkette(objekt, "creationDate")),
                    geaendert = isoZeit(zeichenkette(objekt, "lastModified")),
                    herkunft = "Simplenote",
                    notizbuch = "Simplenote"
                )
            }
        }
        return aus
    }

    // ----------------------------------------------------- Standard Notes u. a.

    /** Standard Notes schreibt `{"items":[{"content_type":"Note","content":{…}}]}`. */
    fun standardNotes(text: String): List<Rohnotiz> {
        val wurzel = runCatching { json.parseToJsonElement(text) as? JsonObject }.getOrNull()
            ?: return emptyList()
        val posten = wurzel["items"] as? JsonArray ?: return emptyList()
        val aus = mutableListOf<Rohnotiz>()
        for (teil in posten) {
            val objekt = teil as? JsonObject ?: continue
            if (zeichenkette(objekt, "content_type") != "Note") continue
            val inhalt = objekt["content"] as? JsonObject ?: continue
            val titel = zeichenkette(inhalt, "title")
            val koerper = zeichenkette(inhalt, "text")
            if (titel.isBlank() && koerper.isBlank()) continue
            aus += Rohnotiz(
                titel = titel,
                text = koerper,
                angelegt = isoZeit(zeichenkette(objekt, "created_at")),
                geaendert = isoZeit(zeichenkette(objekt, "updated_at")),
                herkunft = "Standard Notes",
                notizbuch = "Standard Notes"
            )
        }
        return aus
    }

    // ---------------------------------------------------- Markdown und Text

    /**
     * Schlichter Text oder Markdown. Die erste Überschrift wird zum Titel.
     * Joplin schreibt hinter dem Text noch `id:`-Zeilen; die fliegen raus.
     */
    fun schlicht(text: String, dateiname: String, herkunft: String, wann: Long): List<Rohnotiz> {
        val zeilen = text.replace("\r\n", "\n").trim()
        if (zeilen.isBlank()) return emptyList()
        val ohneJoplinFuss = zeilen.replace(
            Regex("\\n\\nid: [0-9a-f]{32}\\n(?:[a-z_]+: .*\\n?)+$"), ""
        ).trim()
        val alleZeilen = ohneJoplinFuss.lines()
        val ersteZeile = alleZeilen.first().trim()
        val titel = when {
            ersteZeile.startsWith("#") -> ersteZeile.trimStart('#').trim()
            ersteZeile.length in 1..120 && alleZeilen.size > 1 &&
                alleZeilen[1].isBlank() -> ersteZeile
            else -> dateiname.substringBeforeLast('.').replace('_', ' ').trim()
        }
        val koerper = if (ersteZeile.startsWith("#")) {
            alleZeilen.drop(1).joinToString("\n").trim()
        } else ohneJoplinFuss
        return listOf(
            Rohnotiz(
                titel = titel,
                text = koerper,
                angelegt = wann,
                geaendert = wann,
                herkunft = herkunft,
                notizbuch = herkunft
            )
        )
    }

    /** Reines HTML, wie Samsung Notes und viele Browser es teilen. */
    fun html(text: String, dateiname: String, herkunft: String, wann: Long): List<Rohnotiz> {
        val titel = Rohnotiz.entwirreEntitaeten(nurText(zwischen(text, "<title>", "</title>")))
            .ifBlank { dateiname.substringBeforeLast('.').replace('_', ' ') }
        val koerper = zwischen(text, "<body", "</body>").substringAfter('>').ifBlank { text }
        if (nurText(koerper).isBlank()) return emptyList()
        return listOf(
            Rohnotiz(
                titel = titel.trim(),
                text = "",
                html = koerper,
                angelegt = wann,
                geaendert = wann,
                herkunft = herkunft,
                notizbuch = herkunft
            )
        )
    }

    // ---------------------------------------------------------------- Hilfen

    fun zeichenkette(objekt: JsonObject, name: String): String =
        (objekt[name] as? JsonPrimitive)?.content.orEmpty()

    private fun zahl(objekt: JsonObject, name: String): Long? =
        (objekt[name] as? JsonPrimitive)?.content?.toLongOrNull()

    fun zwischen(text: String, auf: String, zu: String): String {
        val start = text.indexOf(auf, ignoreCase = true)
        if (start < 0) return ""
        val ab = start + auf.length
        val ende = text.indexOf(zu, ab, ignoreCase = true)
        return if (ende < 0) text.substring(ab) else text.substring(ab, ende)
    }

    fun nurText(html: String): String = html
        .replace(Regex("<script[\\s\\S]*?</script>", RegexOption.IGNORE_CASE), "")
        .replace(Regex("<style[\\s\\S]*?</style>", RegexOption.IGNORE_CASE), "")
        .replace(Regex("<br\\s*/?>", RegexOption.IGNORE_CASE), "\n")
        .replace(Regex("</(?:div|p|li|tr|h[1-6])>", RegexOption.IGNORE_CASE), "\n")
        .replace(Regex("<[^>]*>"), "")
        .let { Rohnotiz.entwirreEntitaeten(it) }

    private val ISO_FORMEN = listOf(
        "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
        "yyyy-MM-dd'T'HH:mm:ssXXX",
        "yyyy-MM-dd'T'HH:mm:ss'Z'",
        "yyyy-MM-dd HH:mm:ss",
        "yyyy-MM-dd"
    )

    fun isoZeit(roh: String): Long {
        if (roh.isBlank()) return 0L
        roh.toLongOrNull()?.let { return if (it > 100_000_000_000L) it else it * 1000 }
        for (form in ISO_FORMEN) {
            val ergebnis = runCatching {
                val formen = SimpleDateFormat(form, Locale.ROOT)
                if (form.endsWith("'Z'")) formen.timeZone = TimeZone.getTimeZone("UTC")
                formen.parse(roh)?.time
            }.getOrNull()
            if (ergebnis != null && ergebnis > 0) return ergebnis
        }
        return 0L
    }

    /** Deutsche und englische Datumszeilen, wie Keep sie ins HTML schreibt. */
    private val TEXT_FORMEN = listOf(
        "MMM d, yyyy, h:mm:ss a",
        "d. MMMM yyyy 'um' HH:mm:ss",
        "dd.MM.yyyy, HH:mm",
        "yyyy-MM-dd HH:mm"
    )

    fun zeitAusText(roh: String): Long {
        if (roh.isBlank()) return 0L
        for (sprache in listOf(Locale.GERMANY, Locale.US)) {
            for (form in TEXT_FORMEN) {
                val ergebnis = runCatching {
                    SimpleDateFormat(form, sprache).parse(roh)?.time
                }.getOrNull()
                if (ergebnis != null && ergebnis > 0) return ergebnis
            }
        }
        return isoZeit(roh)
    }
}
