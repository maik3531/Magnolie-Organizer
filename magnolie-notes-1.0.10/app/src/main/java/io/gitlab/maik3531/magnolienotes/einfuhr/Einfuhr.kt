package io.gitlab.maik3531.magnolienotes.einfuhr

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.documentfile.provider.DocumentFile
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.PortableArchiv
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.zip.ZipInputStream
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Nimmt Notizen aus fremden Programmen auf.
 *
 * Ein Wort zur Lage: Samsung Notes, Google Keep und die übrigen bewahren ihre
 * Datenbank in der eigenen App-Sandbox auf. Android lässt keine fremde App
 * hineinsehen, und eine öffentliche Schnittstelle gibt es nicht. Was bleibt,
 * sind die beiden Wege, die immer offenstehen: die Notiz hierher teilen, oder
 * die Exportdatei einlesen, die diese Programme selbst schreiben. Genau das
 * macht diese Stelle – und zwar für alle Formate, die dabei vorkommen.
 */
object Einfuhr {

    private const val DATEI_MAX = 64L * 1024 * 1024
    private const val EINTRAG_MAX = 8L * 1024 * 1024
    private const val ARCHIV_ENTPACKT_MAX = 64L * 1024 * 1024

    /** Eine einzelne gewählte Datei. */
    fun ausDatei(zusammenhang: Context, quelle: Uri): Einfuhrergebnis {
        val name = dateiname(zusammenhang, quelle)
        return try {
            val roh = lies(zusammenhang, quelle) ?: return Einfuhrergebnis(
                0, 0, 0, name, zusammenhang.getString(R.string.einfuhr_datei_oeffnen_fehler)
            )
            val wann = geaendert(zusammenhang, quelle)
            val notizen = ausInhalt(roh, name, wann, zusammenhang)
            uebernehmen(zusammenhang, notizen, name)
        } catch (_: GesamtarchivNichtUnterstuetzt) {
            Einfuhrergebnis(
                0, 0, 0, name, zusammenhang.getString(R.string.einfuhr_gesamtarchiv_nicht_unterstuetzt)
            )
        } catch (fehler: Exception) {
            Einfuhrergebnis(
                0, 0, 0, name, zusammenhang.getString(R.string.einfuhr_unbekannter_fehler)
            )
        }
    }

    /** Ein ganzer Ordner, rekursiv – so kommt ein Samsung-Notizbuch herein. */
    fun ausOrdner(zusammenhang: Context, baum: Uri): Einfuhrergebnis {
        val wurzel = DocumentFile.fromTreeUri(zusammenhang, baum)
            ?: return Einfuhrergebnis(
                0, 0, 0, "", zusammenhang.getString(R.string.einfuhr_ordner_oeffnen_fehler)
            )
        return try {
            val gesammelt = mutableListOf<Rohnotiz>()
            sammle(zusammenhang, wurzel, gesammelt, 0)
            uebernehmen(zusammenhang, gesammelt, wurzel.name.orEmpty())
        } catch (_: GesamtarchivNichtUnterstuetzt) {
            Einfuhrergebnis(
                0, 0, 0, wurzel.name.orEmpty(),
                zusammenhang.getString(R.string.einfuhr_gesamtarchiv_nicht_unterstuetzt)
            )
        } catch (fehler: Exception) {
            Einfuhrergebnis(
                0, 0, 0, wurzel.name.orEmpty(),
                zusammenhang.getString(R.string.einfuhr_unbekannter_fehler)
            )
        }
    }

    private fun sammle(
        zusammenhang: Context,
        ordner: DocumentFile,
        ziel: MutableList<Rohnotiz>,
        tiefe: Int
    ) {
        if (tiefe > 6 || ziel.size > 5000) return
        for (kind in ordner.listFiles()) {
            if (kind.isDirectory) {
                sammle(zusammenhang, kind, ziel, tiefe + 1)
                continue
            }
            if (kind.length() > DATEI_MAX) continue
            val name = kind.name.orEmpty()
            if (!kommtInFrage(name)) continue
            val roh = lies(zusammenhang, kind.uri) ?: continue
            ziel += ausInhalt(roh, name, kind.lastModified(), zusammenhang)
        }
    }

    private fun kommtInFrage(name: String): Boolean {
        val klein = name.lowercase()
        return listOf(
            ".txt", ".md", ".markdown", ".json", ".html", ".htm", ".enex",
            ".zip", ".magnolie", ".sdoc", ".sdocx", ".snote", ".jex", ".memo"
        ).any { klein.endsWith(it) }
    }

    // ------------------------------------------------------------ Erkennung

    /** Entscheidet anhand von Name und Inhalt, wer die Datei lesen darf. */
    fun ausInhalt(
        roh: ByteArray,
        name: String,
        wann: Long,
        zusammenhang: Context? = null
    ): List<Rohnotiz> {
        val klein = name.lowercase()
        if (PortableArchiv.istArchiv(roh)) throw GesamtarchivNichtUnterstuetzt()
        if (istZip(roh)) return lokalisiere(ausZip(roh, name, zusammenhang), zusammenhang)

        val text = roh.toString(Charsets.UTF_8)
        val angeschaut = text.take(4000)
        if (istGesamtarchiv(text, klein.endsWith(".magnolie"))) {
            throw GesamtarchivNichtUnterstuetzt()
        }

        return lokalisiere(when {
            klein.endsWith(".enex") || angeschaut.contains("<en-export") -> Leser.enex(text)

            angeschaut.contains("\"activeNotes\"") -> Leser.simplenote(text)

            angeschaut.contains("\"content_type\"") && angeschaut.contains("Note") ->
                Leser.standardNotes(text)

            klein.endsWith(".json") || angeschaut.trimStart().startsWith("{") ||
                angeschaut.trimStart().startsWith("[") -> {
                val ausKeep = Leser.keepJson(text, name)
                ausKeep.ifEmpty { Leser.schlicht(text, name, herkunftAus(name), wann) }
            }

            klein.endsWith(".html") || klein.endsWith(".htm") ||
                angeschaut.contains("<html", ignoreCase = true) -> {
                val ausKeep = Leser.keepHtml(text, name)
                ausKeep.ifEmpty { Leser.html(text, name, herkunftAus(name), wann) }
            }

            else -> Leser.schlicht(text, name, herkunftAus(name), wann)
        }.filter { it.hatInhalt }, zusammenhang)
    }

    private fun istZip(roh: ByteArray): Boolean =
        roh.size > 4 && roh[0] == 0x50.toByte() && roh[1] == 0x4B.toByte() &&
            (roh[2] == 0x03.toByte() || roh[2] == 0x05.toByte() || roh[2] == 0x07.toByte())

    private fun istGesamtarchiv(text: String, istMagnolieDatei: Boolean): Boolean {
        val wurzel = runCatching { Json.parseToJsonElement(text) as? JsonObject }.getOrNull()
        val kennung = (wurzel?.get("magnolie") as? JsonPrimitive)?.content
            ?: Regex("\"magnolie\"\\s*:\\s*\"magnolie-verschluesselt\"")
                .find(text.take(400))?.let { "magnolie-verschluesselt" }
        return kennung == "magnolie-gesamtarchiv" ||
            (istMagnolieDatei && kennung == "magnolie-verschluesselt")
    }

    /**
     * Google Takeout und Samsung `.sdocx` sind beide ZIP-Archive. Beim
     * Takeout stehen die Notizen unter `Takeout/Keep/`; bei Samsung liegt
     * der Wortlaut in einer der enthaltenen Dateien. Beides wird hier
     * gleich behandelt: jeder lesbare Eintrag wird einzeln vorgelegt.
     */
    internal fun ausZip(
        roh: ByteArray,
        aussenName: String,
        zusammenhang: Context?,
        eintragMax: Long = EINTRAG_MAX,
        archivEntpacktMax: Long = ARCHIV_ENTPACKT_MAX
    ): List<Rohnotiz> {
        val erwarteteEintraege = pruefeZipStruktur(roh)
        val aus = mutableListOf<Rohnotiz>()
        val strom = ZipInputStream(roh.inputStream())
        var eintraege = 0
        var archivGesamt = 0L
        strom.use {
            while (true) {
                val eintrag = it.nextEntry ?: break
                if (++eintraege > 5000) throw IOException("Zu viele Archiveintraege")
                val name = eintrag.name.substringAfterLast('/')
                val lesbar = !eintrag.isDirectory && kommtInFrage(name) &&
                    !name.lowercase().endsWith(".zip")
                val puffer = if (lesbar) ByteArrayOutputStream() else null
                val brocken = ByteArray(16 * 1024)
                var gesamt = 0L
                while (true) {
                    val gelesen = it.read(brocken)
                    if (gelesen < 0) break
                    gesamt += gelesen
                    archivGesamt += gelesen
                    if (gesamt > eintragMax || archivGesamt > archivEntpacktMax) {
                        throw IOException("Entpackgrenze ueberschritten")
                    }
                    puffer?.write(brocken, 0, gelesen)
                }
                if (!lesbar) continue
                val zeit = eintrag.time.takeIf { wert -> wert > 0 } ?: 0L
                aus += ausInhalt(puffer!!.toByteArray(), name, zeit, zusammenhang).map { notiz ->
                    if (notiz.herkunft.isBlank()) {
                        notiz.copy(herkunft = herkunftAus(aussenName))
                    } else notiz
                }
            }
        }
        if (eintraege != erwarteteEintraege) throw IOException("Widerspruechliches ZIP-Archiv")
        // Samsung-Archive enthalten oft eine einzige Textdatei ohne Titel.
        return aus.ifEmpty { emptyList() }
    }

    private fun pruefeZipStruktur(roh: ByteArray): Int {
        val kleinsterAbschluss = 22
        if (roh.size < kleinsterAbschluss) throw IOException("Unvollstaendiges ZIP-Archiv")
        val untergrenze = (roh.size - kleinsterAbschluss - 65_535).coerceAtLeast(0)
        for (stelle in roh.size - kleinsterAbschluss downTo untergrenze) {
            if (roh[stelle] == 0x50.toByte() && roh[stelle + 1] == 0x4b.toByte() &&
                roh[stelle + 2] == 0x05.toByte() && roh[stelle + 3] == 0x06.toByte()
            ) {
                val kommentarLaenge = u16(roh, stelle + 20)
                if (stelle + kleinsterAbschluss + kommentarLaenge != roh.size) continue
                if (u16(roh, stelle + 4) != 0 || u16(roh, stelle + 6) != 0) {
                    throw IOException("Mehrteilige ZIP-Archive werden nicht unterstuetzt")
                }
                val aufDatentraeger = u16(roh, stelle + 8)
                val gesamt = u16(roh, stelle + 10)
                if (aufDatentraeger != gesamt || gesamt > 5000) {
                    throw IOException("Widerspruechliches ZIP-Archiv")
                }
                val zentralLaenge = u32(roh, stelle + 12)
                val zentralStart = u32(roh, stelle + 16)
                if (zentralStart + zentralLaenge != stelle.toLong() ||
                    zentralStart > roh.size) {
                    throw IOException("Ungueltiges ZIP-Zentralverzeichnis")
                }
                var position = zentralStart.toInt()
                repeat(gesamt) {
                    if (position + 46 > stelle || roh[position] != 0x50.toByte() ||
                        roh[position + 1] != 0x4b.toByte() || roh[position + 2] != 0x01.toByte() ||
                        roh[position + 3] != 0x02.toByte()) {
                        throw IOException("Ungueltiges ZIP-Zentralverzeichnis")
                    }
                    position += 46 + u16(roh, position + 28) + u16(roh, position + 30) +
                        u16(roh, position + 32)
                    if (position > stelle) throw IOException("Ungueltiges ZIP-Zentralverzeichnis")
                }
                if (position != stelle) throw IOException("Ungueltiges ZIP-Zentralverzeichnis")
                return gesamt
            }
        }
        throw IOException("Unvollstaendiges ZIP-Archiv")
    }

    private fun u16(roh: ByteArray, stelle: Int): Int =
        (roh[stelle].toInt() and 0xff) or ((roh[stelle + 1].toInt() and 0xff) shl 8)

    private fun u32(roh: ByteArray, stelle: Int): Long =
        u16(roh, stelle).toLong() or (u16(roh, stelle + 2).toLong() shl 16)

    private fun herkunftAus(name: String): String {
        val klein = name.lowercase()
        return when {
            klein.contains("takeout") || klein.contains("keep") -> "Google Keep"
            klein.contains("sdoc") || klein.contains("snote") ||
                klein.contains("samsung") -> "Samsung Notes"
            klein.endsWith(".enex") -> "Evernote"
            klein.contains("colornote") || klein.endsWith(".memo") -> "ColorNote"
            klein.contains("joplin") || klein.endsWith(".jex") -> "Joplin"
            klein.contains("simplenote") -> "Simplenote"
            else -> "Übernommen"
        }
    }

    private fun lokalisiere(notizen: List<Rohnotiz>, zusammenhang: Context?): List<Rohnotiz> {
        if (zusammenhang == null) return notizen
        fun name(text: String): String = when (text) {
            "Samsung Notes" -> zusammenhang.getString(R.string.produkt_samsung_notes)
            "Google Keep" -> zusammenhang.getString(R.string.produkt_google_keep)
            "ColorNote" -> zusammenhang.getString(R.string.produkt_colornote)
            "Evernote" -> zusammenhang.getString(R.string.produkt_evernote)
            "Standard Notes" -> zusammenhang.getString(R.string.produkt_standard_notes)
            "Joplin" -> zusammenhang.getString(R.string.produkt_joplin)
            "Simplenote" -> zusammenhang.getString(R.string.produkt_simplenote)
            "Übernommen" -> zusammenhang.getString(R.string.herkunft_uebernommen)
            else -> text
        }
        return notizen.map { it.copy(herkunft = name(it.herkunft), notizbuch = name(it.notizbuch)) }
    }

    // ------------------------------------------------------------ Aufnehmen

    fun uebernehmen(
        zusammenhang: Context,
        rohnotizen: List<Rohnotiz>,
        quelle: String
    ): Einfuhrergebnis {
        val brauchbar = rohnotizen.filter { it.hatInhalt }
        if (brauchbar.isEmpty()) return Einfuhrergebnis(0, 0, 0, quelle)
        val ablage = Ablage.hole(zusammenhang)
        // Jede Herkunft bekommt ihr eigenes Notizbuch, wie im Organizer.
        val vorgabe = zusammenhang.getString(R.string.herkunft_uebernommen)
        val notizen = brauchbar.map { roh ->
            roh.zuNotiz(Ablage.STANDARD_BUCH) to roh.notizbuch.ifBlank { vorgabe }
        }
        val (neu, doppelt) = ablage.uebernehmenMitNotizbuechern(notizen)
        return Einfuhrergebnis(brauchbar.size, neu, doppelt, quelle)
    }

    // ------------------------------------------------------------ Dateizugriff

    private fun lies(zusammenhang: Context, quelle: Uri): ByteArray? = try {
        zusammenhang.contentResolver.openInputStream(quelle)?.use { strom ->
            val puffer = ByteArrayOutputStream()
            val brocken = ByteArray(64 * 1024)
            var gesamt = 0L
            while (true) {
                val gelesen = strom.read(brocken)
                if (gelesen < 0) break
                gesamt += gelesen
                if (gesamt > DATEI_MAX) return null
                puffer.write(brocken, 0, gelesen)
            }
            puffer.toByteArray()
        }
    } catch (fehler: Exception) {
        null
    }

    fun dateiname(zusammenhang: Context, quelle: Uri): String {
        runCatching {
            zusammenhang.contentResolver.query(quelle, null, null, null, null)?.use { zeiger ->
                val spalte = zeiger.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (spalte >= 0 && zeiger.moveToFirst()) return zeiger.getString(spalte).orEmpty()
            }
        }
        return quelle.lastPathSegment?.substringAfterLast('/').orEmpty()
    }

    private fun geaendert(zusammenhang: Context, quelle: Uri): Long = runCatching {
        DocumentFile.fromSingleUri(zusammenhang, quelle)?.lastModified() ?: 0L
    }.getOrDefault(0L)
}

internal class GesamtarchivNichtUnterstuetzt : IOException()
