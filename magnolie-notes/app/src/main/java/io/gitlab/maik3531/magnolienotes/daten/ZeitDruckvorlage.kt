package io.gitlab.maik3531.magnolienotes.daten

import android.icu.text.DateTimePatternGenerator
import android.icu.text.SimpleDateFormat
import android.icu.util.TimeZone
import java.time.DayOfWeek
import java.time.LocalDateTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.Date
import java.util.Locale

data class ZeitDruckTexte(val title: String, val name: String, val date: String,
                         val signature: String, val total: String, val clock: String,
                         val columns: List<String>)

/** Same A4 landscape geometry, colors, columns and totals as the editable ODS. */
object ZeitDruckvorlage {
    val columnWidths = listOf(3.0, 3.0, 1.8, 3.0, 1.8, 1.6, 1.8, 1.8, 4.7, 2.2)

    fun html(month: YearMonth, days: Set<Int>, entries: List<Zeiteintrag>, name: String,
             calendar: ZeitKalender, texts: ZeitDruckTexte, locale: Locale, use24HourClock: Boolean): String {
        require(days.isNotEmpty() && days.all { it in 1..month.lengthOfMonth() })
        require(name.length <= 240 && texts.columns.size == 10)
        calendar.validate()
        entries.forEach { it.validate() }
        val selected = entries.filter { !it.deleted && YearMonth.from(it.localStart()) == month }
            .sortedBy { it.startMinute }.groupBy { it.localStart().dayOfMonth }
        val patterns = DateTimePatternGenerator.getInstance(locale)
        fun formatter(skeleton: String) = SimpleDateFormat(patterns.getBestPattern(skeleton), locale).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        val dateFormat = formatter("EEEyyyyMMdd")
        val clockFormat = formatter(if (use24HourClock) "HHmm" else "hhmm")
        val monthFormat = formatter("yMMMM")
        fun stamp(value: LocalDateTime) = Date(value.toInstant(ZoneOffset.UTC).toEpochMilli())
        fun esc(value: String) = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\"", "&quot;").replace("'", "&#39;")
        fun cell(value: String, style: String = "") = "<td class=\"$style\">${esc(value).replace("\n", "<br>")}</td>"
        fun duration(value: Long) = "%02d:%02d".format(locale, value / 60, value % 60)
        val number = java.text.NumberFormat.getIntegerInstance(locale).apply { isGroupingUsed = false }
        var gross = 0L
        var pauses = 0L
        var total = 0L
        val rows = buildString {
            for (day in days.sorted()) {
                val date = month.atDay(day)
                val holidays = calendar.names(date)
                val style = if (holidays.isNotEmpty()) "holiday" else if (date.dayOfWeek == DayOfWeek.SUNDAY) "sunday" else ""
                val records: List<Zeiteintrag?> = selected[day]?.map { it } ?: listOf(null)
                for (entry in records) {
                    val start = entry?.localStart() ?: date.atStartOfDay()
                    val end = entry?.localEnd()
                    val finished = entry?.endMinute != null
                    val elapsed = if (finished) entry!!.grossMinutes() else 0L
                    val paused = entry?.pauseMinutes ?: 0L
                    val adjustment = if (finished) {
                        val zone = ZoneId.of(entry!!.zone)
                        val before = java.time.Instant.ofEpochSecond(entry.startMinute * 60).atZone(zone).offset.totalSeconds
                        val after = java.time.Instant.ofEpochSecond(entry.endMinute!! * 60).atZone(zone).offset.totalSeconds
                        (after - before) / 60
                    } else 0
                    if (finished) { gross += elapsed; pauses += paused; total += elapsed - paused }
                    append("<tr class=\"$style\">")
                    append(cell(dateFormat.format(stamp(start)), "number"))
                    append(cell(entry?.type.orEmpty()))
                    append(cell(if (entry == null) "" else clockFormat.format(stamp(start)), "number"))
                    append(cell(dateFormat.format(stamp(end ?: start)), "number"))
                    append(cell(end?.let { clockFormat.format(stamp(it)) }.orEmpty(), "number"))
                    append(cell(if (finished) duration(elapsed) else "", "number"))
                    append(cell(number.format(paused), "number"))
                    append(cell(if (finished) duration(elapsed - paused) else "", "number"))
                    append(cell((listOf(entry?.note.orEmpty()) + holidays + listOf(entry?.zone.orEmpty()))
                        .filter { it.isNotEmpty() }.joinToString("\n")))
                    append(cell(number.format(adjustment), "number"))
                    append("</tr>")
                }
            }
        }
        val direction = if (locale.language == "ar") "rtl" else "ltr"
        val columns = columnWidths.joinToString("") { "<col style=\"width:${String.format(Locale.ROOT, "%.1f", it)}cm\">" }
        val headers = texts.columns.joinToString("") { "<th>${esc(it)}</th>" }
        return """<!doctype html><html lang="${esc(locale.toLanguageTag())}" dir="$direction"><head><meta charset="utf-8">
<style>@page{size:A4 landscape;margin:1cm}*{box-sizing:border-box}body{margin:0;font-family:sans-serif;font-size:8pt;line-height:1.05;color:#3d2a1d}
table{width:24.7cm;border-collapse:collapse;table-layout:fixed}td,th{padding:.05cm;vertical-align:middle;overflow-wrap:anywhere;border-bottom:.01cm solid #c9baa0}
thead{display:table-header-group}tr{break-inside:avoid}td{height:.4cm}th{font-size:9pt;text-align:start;background:#5b3927;color:#f6e5b7}
.title{background:#f8f1e1;color:#4b3022;font-size:20pt;font-weight:bold}.number{text-align:right}.sunday td{background:#f4efe5}.holiday td{background:#e8f0eb}
.heading{width:24.7cm}.heading div{padding:.05cm;border-bottom:.01cm solid #c9baa0}.gap{height:.4cm}.signature{margin-top:.4cm;break-inside:avoid}
@media print{body{-webkit-print-color-adjust:exact;print-color-adjust:exact}}</style></head><body>
<div class="heading"><div class="title">${esc(texts.title)}</div><div>${esc(texts.name)}: ${esc(name)}</div>
<div>${esc(monthFormat.format(stamp(month.atDay(1).atStartOfDay())))}</div><div class="gap"></div></div>
<table>$columns<thead><tr><td colspan="2"></td><th colspan="3">${esc(texts.clock)}</th><td colspan="5"></td></tr><tr>$headers</tr></thead>
<tbody>$rows<tr><th>${esc(texts.total)}</th><td colspan="4"></td>${cell(duration(gross), "number")}${cell(number.format(pauses), "number")}${cell(duration(total), "number")}<td colspan="2"></td></tr></tbody></table>
<div class="signature">${esc(texts.date)}: ____________________ &nbsp; ${esc(texts.signature)}: ____________________</div></body></html>"""
    }
}
