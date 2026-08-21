package io.gitlab.maik3531.magnolienotes

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.einfuhr.Einfuhr
import io.gitlab.maik3531.magnolienotes.einfuhr.Rohnotiz
import io.gitlab.maik3531.magnolienotes.baum.AnhangSpeicher
import io.gitlab.maik3531.magnolienotes.baum.Nutzlast
import kotlin.concurrent.thread
import kotlinx.coroutines.runBlocking

/**
 * Das Ziel von „Teilen“. Aus Samsung Notes, Google Keep, ColorNote, dem
 * Browser oder sonstwo landet der Wortlaut hier und wird sofort als Notiz
 * abgelegt – mit Tag und Uhrzeit des Augenblicks.
 *
 * Das ist der Weg, der bei jedem Notizprogramm funktioniert, weil er keine
 * fremde Datenbank anfassen muss.
 */
class FreigabeActivity : Activity() {

    override fun onCreate(zustand: Bundle?) {
        super.onCreate(zustand)
        val absicht = intent
        if (absicht == null) {
            finish()
            return
        }
        thread {
            val bereit = runBlocking { (application as MagnolieApp).awaitReady() }
            val bericht = if (bereit) runCatching { verarbeite(absicht) }.getOrElse { 0 } else 0
            runOnUiThread {
                val text = when {
                    bericht > 1 -> resources.getQuantityString(
                        R.plurals.einfuhr_ergebnis, bericht, bericht, 0
                    )
                    bericht == 1 -> getString(R.string.freigabe_ziel)
                    else -> getString(R.string.einfuhr_nichts)
                }
                Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
                setResult(Activity.RESULT_OK)
                finish()
            }
        }
    }

    private fun verarbeite(absicht: Intent): Int {
        val jetzt = System.currentTimeMillis()
        val betreff = absicht.getStringExtra(Intent.EXTRA_SUBJECT)?.trim().orEmpty()
        val rohnotizen = mutableListOf<Rohnotiz>()
        val anhaenge = mutableListOf<Anhang>()

        when (absicht.action) {
            Intent.ACTION_SEND, Intent.ACTION_PROCESS_TEXT -> {
                val text = (absicht.getStringExtra(Intent.EXTRA_TEXT)
                    ?: absicht.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)?.toString())
                    .orEmpty()
                val html = absicht.getStringExtra(Intent.EXTRA_HTML_TEXT).orEmpty()
                val datei = absicht.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
                if (text.isNotBlank() || html.isNotBlank()) {
                    rohnotizen += ausText(betreff, text, html, jetzt, absicht)
                }
                if (datei != null) {
                    val ausDatei = ausAnhang(datei, jetzt)
                    rohnotizen += ausDatei.first
                    anhaenge += ausDatei.second
                }
            }

            Intent.ACTION_SEND_MULTIPLE -> {
                val texte = absicht.getStringArrayListExtra(Intent.EXTRA_TEXT).orEmpty()
                for (stueck in texte) {
                    if (stueck.isBlank()) continue
                    rohnotizen += ausText("", stueck, "", jetzt, absicht)
                }
                val dateien = absicht.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
                for (datei in dateien) {
                    val ausDatei = ausAnhang(datei, jetzt)
                    rohnotizen += ausDatei.first
                    anhaenge += ausDatei.second
                }
            }
        }

        if (rohnotizen.isEmpty() && anhaenge.isEmpty()) return 0

        val ablage = Ablage.hole(this)
        if (rohnotizen.isEmpty() && anhaenge.isNotEmpty()) {
            // Nur Bilder geteilt: eine Notiz, die sie zusammenhält.
            rohnotizen += Rohnotiz(
                titel = betreff.ifBlank { getString(R.string.herkunft_geteilt) },
                text = "",
                angelegt = jetzt,
                geaendert = jetzt,
                herkunft = herkunft(intent),
                notizbuch = getString(R.string.herkunft_geteilt)
            )
        }
        val buchId = ablage.legeNotizbuchAn(
            rohnotizen.first().notizbuch.ifBlank { getString(R.string.herkunft_geteilt) }
        ).id
        val saubereAnhaenge = Nutzlast.saubere(anhaenge)
        val entscheidung = AnhangSpeicher.entscheide(
            ablage.notizen().flatMap { it.anhaenge }, emptyList(), saubereAnhaenge, filesDir.usableSpace
        )
        val gespeicherteAnhaenge = if (entscheidung.erlaubt) saubereAnhaenge else emptyList()
        if (!entscheidung.erlaubt && saubereAnhaenge.isNotEmpty()) runOnUiThread {
            Toast.makeText(this, getString(R.string.baum_anhaenge_speicher), Toast.LENGTH_LONG).show()
        }
        val notizen = rohnotizen.mapIndexed { platz, roh ->
            val notiz = roh.zuNotiz(buchId)
            if (platz == 0 && gespeicherteAnhaenge.isNotEmpty()) notiz.copy(
                anhaenge = gespeicherteAnhaenge,
                einfuhrSchluessel = Ablage.einfuhrSchluessel(notiz.titel, notiz.text, gespeicherteAnhaenge)
            ) else notiz
        }
        val (neu, _) = ablage.uebernehmen(notizen)
        return neu
    }

    private fun ausText(
        betreff: String,
        text: String,
        html: String,
        wann: Long,
        absicht: Intent
    ): List<Rohnotiz> {
        val quelle = herkunft(absicht)
        // Kommt geteiltes JSON oder eine ganze Exportdatei als Text herein,
        // wird sie auch als solche gelesen.
        val erkannt = if (text.length > 200 &&
            (text.trimStart().startsWith("{") || text.trimStart().startsWith("["))
        ) {
            Einfuhr.ausInhalt(text.toByteArray(Charsets.UTF_8), "geteilt.json", wann, this)
        } else emptyList()
        if (erkannt.isNotEmpty()) return erkannt

        val titel = betreff.ifBlank {
            text.lineSequence().firstOrNull { it.isNotBlank() }?.trim()?.take(120).orEmpty()
        }
        val koerper = if (betreff.isBlank() && text.lineSequence().count() > 1 &&
            text.lineSequence().first().trim() == titel
        ) {
            text.substringAfter('\n').trim()
        } else text.trim()
        return listOf(
            Rohnotiz(
                titel = titel,
                text = koerper,
                html = html,
                angelegt = wann,
                geaendert = wann,
                herkunft = quelle,
                notizbuch = quelle
            )
        )
    }

    /** Bilder und PDF werden als Anhang übernommen, Textdateien als Notiz. */
    private fun ausAnhang(quelle: Uri, wann: Long): Pair<List<Rohnotiz>, List<Anhang>> {
        val gelesen = AnhangLeser.lies(this, quelle)
        if (gelesen.anhang != null) return emptyList<Rohnotiz>() to listOf(gelesen.anhang)
        val gemeldet = runCatching { contentResolver.getType(quelle) }.getOrNull().orEmpty().lowercase()
        if (gemeldet.isBlank() || gemeldet == "application/octet-stream" ||
            gemeldet.startsWith("image/") || gemeldet == "application/pdf"
        ) return emptyList<Rohnotiz>() to emptyList()
        val name = Einfuhr.dateiname(this, quelle)
        val roh = runCatching {
            contentResolver.openInputStream(quelle)?.use { AnhangLeser.begrenztLesen(it) }
        }.getOrNull() ?: return emptyList<Rohnotiz>() to emptyList()
        return Einfuhr.ausInhalt(roh, name, wann, this) to emptyList()
    }

    /** Woher die Freigabe kam, so gut es sich feststellen lässt. */
    private fun herkunft(absicht: Intent): String {
        val paket = runCatching { referrer?.host }.getOrNull().orEmpty()
        return when {
            paket.contains("samsung", true) && paket.contains("note", true) ->
                getString(R.string.produkt_samsung_notes)
            paket.contains("keep", true) -> getString(R.string.produkt_google_keep)
            paket.contains("colornote", true) -> getString(R.string.produkt_colornote)
            paket.contains("evernote", true) -> getString(R.string.produkt_evernote)
            paket.contains("standardnotes", true) -> getString(R.string.produkt_standard_notes)
            paket.isNotBlank() -> paket.substringAfterLast('.')
                .replaceFirstChar { it.uppercase() }
            else -> getString(R.string.herkunft_geteilt)
        }
    }
}
