package io.gitlab.maik3531.magnolietabletbeta

import org.threeten.bp.Instant
import org.threeten.bp.LocalDate
import org.threeten.bp.LocalDateTime
import org.threeten.bp.ZoneId
import org.threeten.bp.ZoneOffset
import org.threeten.bp.format.DateTimeFormatter
import org.threeten.bp.zone.ZoneOffsetTransitionRule
import org.threeten.bp.zone.ZoneRules
import org.threeten.bp.zone.ZoneRulesProvider
import java.util.Locale

/** RFC 5545 history and infinite future from the pinned, complete ThreeTen TZDB.
 * No event occurrence expansion, guessed DST rules or finite future snapshots. */
object TimeZoneExport {
    class UnsupportedException(message: String) : IllegalArgumentException(message)
    /** The public data version actually loaded from the bundled TZDB resource. */
    val databaseVersion: String get() = ZoneRulesProvider.getVersions("Europe/Berlin").lastKey()
    private val names = listOf("SU", "MO", "TU", "WE", "TH", "FR", "SA")
    private val stamp = DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss", Locale.ROOT)
    private data class Key(val daylight: Boolean, val before: Int, val after: Int)
    private data class FuturePattern(val text: String, val months: Set<Int>, val days: Set<Int>?, val weekday: Int?, val ordinal: Int?)
    private fun requireZone(condition: Boolean) { if (!condition) throw UnsupportedException("This time zone cannot be exported without changing its transition rules.") }
    private fun offset(value: Int): String {
        requireZone(value > -86400 && value < 86400)
        val n = kotlin.math.abs(value)
        return (if (value < 0) "-" else "+") + "%02d%02d".format(Locale.ROOT, n / 3600, n % 3600 / 60) +
            (if (n % 60 == 0) "" else "%02d".format(Locale.ROOT, n % 60))
    }
    private fun component(key: Key, dates: List<LocalDateTime>, rule: String? = null): List<String> {
        requireZone(dates.isNotEmpty() && dates.all { it.year in 1..9999 })
        val kind = if (key.daylight) "DAYLIGHT" else "STANDARD"
        val lines = mutableListOf("BEGIN:$kind", "DTSTART:" + dates.first().format(stamp), "TZOFFSETFROM:" + offset(key.before), "TZOFFSETTO:" + offset(key.after))
        dates.drop(1).chunked(100).forEach { lines.add("RDATE:" + it.joinToString(",") { date -> date.format(stamp) }) }
        rule?.let { lines.add("RRULE:$it") }; lines.add("END:$kind"); return lines
    }
    private fun candidates(pattern: FuturePattern, year: Int, clock: org.threeten.bp.LocalTime): List<LocalDateTime> {
        val dates = mutableListOf<LocalDateTime>()
        for (month in pattern.months.sorted()) {
            val length = LocalDate.of(year, month, 1).lengthOfMonth()
            for (day in 1..length) {
                if (pattern.days != null && day !in pattern.days && day - length - 1 !in pattern.days) continue
                val date = LocalDate.of(year, month, day)
                if (pattern.weekday != null && date.dayOfWeek.value % 7 != pattern.weekday) continue
                if (pattern.ordinal != null) {
                    val ordinal = pattern.ordinal
                    if (ordinal > 0 && (day - 1) / 7 + 1 != ordinal || ordinal < 0 && -((length - day) / 7 + 1) != ordinal) continue
                }
                dates.add(date.atTime(clock))
            }
        }
        return dates
    }
    private fun futurePattern(rule: ZoneOffsetTransitionRule, check: () -> Unit): String {
        // ZoneOffsetTransitionRule is annual and uses only Gregorian dates and
        // fixed offsets. Checking the complete 400-year leap/weekday cycle is
        // therefore a proof for every future year, including UTC/STANDARD clocks,
        // end-of-day rules and date shifts caused by their offset conversion.
        val byYear = (1999..2400).map { rule.createTransition(it).dateTimeBefore }
            .filter { it.year in 2000..2399 }.groupBy { it.year }
        requireZone(byYear.size == 400 && byYear.values.all { it.size == 1 })
        val dates = byYear.values.map { it.single() }
        val clocks = dates.map { it.toLocalTime() }.toSet(); requireZone(clocks.size == 1)
        val months = dates.map { it.monthValue }.toSet(); val days = dates.map { it.dayOfMonth }.toSet()
        val weekdays = dates.map { it.dayOfWeek.value % 7 }.toSet()
        val positive = dates.map { (it.dayOfMonth - 1) / 7 + 1 }.toSet()
        val negative = dates.map { -((it.toLocalDate().lengthOfMonth() - it.dayOfMonth) / 7 + 1) }.toSet()
        val base = "FREQ=YEARLY;BYMONTH=" + months.sorted().joinToString(",")
        val patterns = mutableListOf<FuturePattern>()
        if (months.size == 1 && days.size == 1) patterns.add(FuturePattern(base + ";BYMONTHDAY=" + days.single(), months, days, null, null))
        if (months.size == 1 && weekdays.size == 1) {
            val weekday = weekdays.single()
            if (negative.size == 1) patterns.add(FuturePattern(base + ";BYDAY=" + negative.single() + names[weekday], months, null, weekday, negative.single()))
            if (positive.size == 1) patterns.add(FuturePattern(base + ";BYDAY=" + positive.single() + names[weekday], months, null, weekday, positive.single()))
        }
        if (weekdays.size == 1) patterns.add(FuturePattern(base + ";BYDAY=" + names[weekdays.single()] + ";BYMONTHDAY=" + days.sorted().joinToString(","), months, days, weekdays.single(), null))
        for (pattern in patterns) {
            var valid = true
            for (year in 2000..2399) {
                if (year % 32 == 0) check()
                if (candidates(pattern, year, clocks.single()) != byYear.getValue(year)) { valid = false; break }
            }
            if (valid) return pattern.text
        }
        throw UnsupportedException("The system time zone's future rule has no verified lossless RFC 5545 representation.")
    }
    /** Empty lists may mean unknown, not fixed (notably desugar's public
     * TimeZone-backed provider). Require a complete fixed-offset value before
     * representing such a provider as one observance for all time. */
    internal fun requireCompleteRules(rules: ZoneRules) {
        if (rules.transitions.isEmpty()) {
            requireZone(rules.transitionRules.isEmpty() && rules.isFixedOffset &&
                rules == ZoneRules.of(rules.getOffset(Instant.EPOCH)))
        }
    }
    @JvmOverloads
    fun definition(identifier: String, checkCancelled: () -> Unit = {}): List<String> {
        requireZone(identifier.isNotEmpty() && identifier.toByteArray(Charsets.UTF_8).size <= 255 && identifier.none { it.code < 32 || it.code == 127 || it == ':' || it == ';' })
        val zone = try { ZoneId.of(identifier) } catch (_: org.threeten.bp.DateTimeException) { throw UnsupportedException("The system time zone is unavailable.") }
        val rules = zone.rules
        requireCompleteRules(rules)
        val history = rules.transitions; val future = rules.transitionRules
        requireZone(history.size <= 100_000 && future.size <= 16 && (future.isEmpty() || history.isNotEmpty()))
        val minimum = LocalDate.of(1, 1, 1).atStartOfDay()
        val firstOffset = history.firstOrNull()?.offsetBefore ?: rules.getOffset(Instant.EPOCH)
        val initial = Key(rules.isDaylightSavings(minimum.toInstant(ZoneOffset.UTC)), firstOffset.totalSeconds, firstOffset.totalSeconds)
        val groups = linkedMapOf<Key, MutableList<LocalDateTime>>()
        groups[initial] = mutableListOf(minimum.plusSeconds(maxOf(0, initial.before).toLong()))
        for (transition in history) {
            checkCancelled()
            requireZone(transition.dateTimeBefore.year in 1..9999)
            val key = Key(rules.isDaylightSavings(transition.instant.plusSeconds(1)), transition.offsetBefore.totalSeconds, transition.offsetAfter.totalSeconds)
            groups.getOrPut(key) { mutableListOf() }.add(transition.dateTimeBefore)
        }
        val lines = mutableListOf("BEGIN:VTIMEZONE", "TZID:" + identifier.replace("\\", "\\\\").replace(",", "\\,"))
        for ((key, dates) in groups) lines.addAll(component(key, dates))
        val last = history.lastOrNull()?.instant
        for (rule in future) {
            checkCancelled()
            val text = futurePattern(rule, checkCancelled)
            val boundary = last ?: throw UnsupportedException("Missing time-zone history boundary.")
            val year = boundary.atOffset(ZoneOffset.UTC).year
            requireZone(year in 1..9995)
            val first = (maxOf(1, year - 1)..year + 4).map { rule.createTransition(it) }.filter { it.instant > boundary }.minByOrNull { it.instant }
                ?: throw UnsupportedException("Missing future time-zone transition.")
            val key = Key(rule.offsetAfter != rule.standardOffset, rule.offsetBefore.totalSeconds, rule.offsetAfter.totalSeconds)
            lines.addAll(component(key, listOf(first.dateTimeBefore), text))
        }
        lines.add("END:VTIMEZONE"); return lines
    }
}
