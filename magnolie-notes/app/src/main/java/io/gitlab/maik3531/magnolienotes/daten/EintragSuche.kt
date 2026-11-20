package io.gitlab.maik3531.magnolienotes.daten

import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

/** Read-only list search (Refs #719); dates use the device's local calendar. */
internal class EintragSuche(eingabe: String, private val zone: ZoneId = ZoneId.systemDefault()) {
    private val text = eingabe.trim()
    private val zeitraum = datum(text)

    fun notizPasst(notiz: Notiz): Boolean = text.isEmpty() ||
        notiz.titel.contains(text, ignoreCase = true) || notiz.text.contains(text, ignoreCase = true) ||
        zeitPasst(notiz.angelegt) || zeitPasst(notiz.geaendert)

    fun aufgabePasst(aufgabe: Aufgabe): Boolean = text.isEmpty() ||
        aufgabe.titel.contains(text, ignoreCase = true) || aufgabe.notiz.contains(text, ignoreCase = true) ||
        zeitPasst(aufgabe.angelegt) || zeitPasst(aufgabe.geaendert) ||
        tagPasst(runCatching { LocalDate.parse(aufgabe.faellig) }.getOrNull())

    private fun zeitPasst(zeit: Long): Boolean = zeit > 0 && zeitraum != null &&
        tagPasst(Instant.ofEpochMilli(zeit).atZone(zone).toLocalDate())

    private fun tagPasst(tag: LocalDate?): Boolean = tag != null && zeitraum?.let {
        tag >= it.first && tag < it.second
    } == true

    private fun datum(wert: String): Pair<LocalDate, LocalDate>? = runCatching {
        val tag = Regex("(\\d{1,2})\\.(\\d{1,2})\\.(\\d{4}|\\d{2})\\.?").matchEntire(wert)
        val monat = Regex("(\\d{1,2})\\.(\\d{4}|\\d{2})\\.?").matchEntire(wert)
        when {
            tag != null -> LocalDate.of(jahr(tag.groupValues[3]), tag.groupValues[2].toInt(), tag.groupValues[1].toInt())
                .let { it to it.plusDays(1) }
            monat != null -> YearMonth.of(jahr(monat.groupValues[2]), monat.groupValues[1].toInt())
                .let { it.atDay(1) to it.plusMonths(1).atDay(1) }
            Regex("\\d{4}-\\d{2}-\\d{2}").matches(wert) -> LocalDate.parse(wert).let { it to it.plusDays(1) }
            Regex("\\d{4}-\\d{2}").matches(wert) -> YearMonth.parse(wert).let { it.atDay(1) to it.plusMonths(1).atDay(1) }
            Regex("\\d{4}").matches(wert) -> jahr(wert).let { LocalDate.of(it, 1, 1) to LocalDate.of(it + 1, 1, 1) }
            else -> null
        }
    }.getOrNull()

    // Explicit and stable: 26 means 2026, never a moving two-digit-year window.
    private fun jahr(wert: String): Int = (wert.toInt() + if (wert.length == 2) 2000 else 0)
        .also { require(it in 1..9999) }
}
