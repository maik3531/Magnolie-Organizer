package io.gitlab.maik3531.magnolienotes.einfuhr

import java.io.IOException

/** Refs #821: one budget for the complete traversal, including expanded ZIP notes. */
internal class OrdnerImportBudget(
    private val maxEintraege: Int = 5000,
    private val maxNotizen: Int = 5000,
    private val maxRohbytes: Long = 64L * 1024 * 1024,
    private val maxTextbytes: Long = 64L * 1024 * 1024
) {
    private var eintraege = 0
    private var notizen = 0
    private var rohbytes = 0L
    private var textbytes = 0L
    val verbleibendeRohbytes: Long get() = maxRohbytes - rohbytes

    fun besuchen() {
        if (++eintraege > maxEintraege) throw IOException("Zu viele Ordnereintraege")
    }

    fun gelesen(bytes: Long) {
        if (bytes < 0 || bytes > verbleibendeRohbytes) throw IOException("Ordnerimport zu gross")
        rohbytes += bytes
    }

    fun aufnehmen(notiz: Rohnotiz) {
        if (++notizen > maxNotizen) throw IOException("Zu viele importierte Notizen")
        for (text in listOf(notiz.titel, notiz.text, notiz.html, notiz.herkunft, notiz.notizbuch)) {
            val bytes = text.toByteArray(Charsets.UTF_8).size.toLong()
            if (bytes > maxTextbytes - textbytes) throw IOException("Entpackgrenze des Ordnerimports ueberschritten")
            textbytes += bytes
        }
    }
}
