package io.gitlab.maik3531.magnolienotes.daten

import android.icu.text.DateTimePatternGenerator
import android.icu.text.SimpleDateFormat
import android.icu.util.TimeZone
import java.time.DayOfWeek
import java.time.LocalDateTime
import java.time.YearMonth
import java.time.ZoneOffset
import java.util.Date
import java.util.Locale

data class ZeitDruckTexte(val title: String, val name: String, val date: String,
                         val signature: String, val total: String, val clock: String,
                         val columns: List<String>)

/** Portrait timesheet following the user's original ODS layout. */
object ZeitDruckvorlage {
    val columnWidths = listOf(5.846, 1.342, 1.453, 2.265, 2.247, 2.265)

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
            this.calendar = android.icu.util.GregorianCalendar(TimeZone.getTimeZone("UTC"), locale)
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
        var rowCount = 0
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
                    if (finished) { gross += elapsed; pauses += paused; total += elapsed - paused }
                    append("<tr class=\"$style\">")
                    rowCount++
                    append(cell(dateFormat.format(stamp(start))))
                    append(cell(if (entry == null) "" else clockFormat.format(stamp(start)), "number"))
                    append(cell(end?.let { clockFormat.format(stamp(it)) }.orEmpty(), "number"))
                    append(cell(if (finished) duration(elapsed) else "", "number"))
                    append(cell(if (entry == null) "" else number.format(paused), "number"))
                    append(cell(if (finished) duration(elapsed - paused) else "", "number"))
                    append("</tr>")
                }
            }
            repeat((40 - rowCount).coerceAtLeast(0)) { append("<tr>" + cell("").repeat(6) + "</tr>") }
        }
        val direction = if (locale.language == "ar") "rtl" else "ltr"
        val columns = columnWidths.joinToString("") { "<col style=\"width:${String.format(Locale.ROOT, "%.3f", it)}cm\">" }
        val headers = listOf(0, 2, 4, 5, 6, 7).joinToString("") { "<th>${esc(texts.columns[it])}</th>" }
        return """<!doctype html><html lang="${esc(locale.toLanguageTag())}" dir="$direction"><head><meta charset="utf-8">
<style>@page{size:A4 portrait;margin:.5cm 2cm}*{box-sizing:border-box}body{margin:0;font-family:"Arial Narrow","Liberation Sans Narrow",sans-serif;font-size:8pt;line-height:1.05;color:#000}
table{width:15.418cm;border-collapse:collapse;table-layout:fixed}td,th{padding:.025cm;vertical-align:middle;overflow-wrap:anywhere}
thead{display:table-header-group}tr{break-inside:avoid}tbody td{height:.5cm;border:.02cm solid #000;background:#ffffcc}th{font-size:8pt;text-align:center;background:#fff;color:#000}
tbody td:nth-child(4),tbody td:nth-child(6){background:#ffcc99}tbody td:nth-child(5){background:#ccffff}tbody tr:first-child td{border-top:.06cm solid #000}tbody td:first-child{border-left:.06cm solid #000}tbody td:last-child{border-right:.06cm solid #000}
.title{font-size:12pt;font-weight:bold;text-align:center}.number{text-align:right}.sunday td:first-child{font-weight:bold}.holiday td:first-child{background:#e8f0eb}
.heading{width:15.418cm;margin-bottom:.6cm}.heading div{padding:.15cm}.heading div:not(.title):not(.gap){max-width:9cm;border-bottom:.02cm solid #000}.gap{height:.2cm}.signature{margin-top:.6cm;break-inside:avoid}.totals td{border-top:.5cm solid #fff;font-weight:bold}
.sunday td:first-child{background:#f4efe5}.number{font-size:7pt;white-space:nowrap}.totals td{border-top:.04cm solid #000;height:.8cm}.totals td:first-child{background:white;border-left:0}.totals td:nth-child(2),.totals td:nth-child(4){background:#ffcc99}.totals td:nth-child(3){background:#ccffff}
@media print{body{-webkit-print-color-adjust:exact;print-color-adjust:exact}}</style></head><body>
<div class="heading"><div class="title">${esc(texts.title)}</div><div>${esc(monthFormat.format(stamp(month.atDay(1).atStartOfDay())))}</div>
<div>${esc(texts.name)}: ${esc(name)}</div><div class="gap"></div></div>
<table>$columns<thead><tr><td></td><th colspan="2">${esc(texts.clock)}</th><td colspan="3"></td></tr><tr>$headers</tr></thead>
<tbody>$rows<tr class="totals"><td colspan="3">${esc(texts.total)}</td>${cell(duration(gross), "number")}${cell(number.format(pauses), "number")}${cell(duration(total), "number")}</tr></tbody></table>
<div class="signature">${esc(texts.date)}: ____________________ &nbsp; ${esc(texts.signature)}: ____________________</div></body></html>"""
    }
}
