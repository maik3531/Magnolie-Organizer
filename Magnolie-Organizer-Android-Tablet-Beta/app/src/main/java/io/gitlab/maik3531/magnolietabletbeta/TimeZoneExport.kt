package io.gitlab.maik3531.magnolietabletbeta

import org.threeten.bp.LocalDate
import org.threeten.bp.LocalDateTime
import org.threeten.bp.format.DateTimeFormatter
import java.util.Locale

/** RFC 5545 history and infinite future from the pinned normative TZif/POSIX provider.
 * No event occurrence expansion, guessed DST rules or finite future snapshots. */
object TimeZoneExport {
    class UnsupportedException(message: String) : IllegalArgumentException(message)
    /** The public data version actually loaded from the bundled TZDB resource. */
    val databaseVersion: String get() = ProviderZoneDatabase.bundled.version
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
    private fun futurePatterns(rule: ProviderZone.DateRule, check: () -> Unit): List<FuturePattern> {
        // The normative POSIX date rule is annual and uses only Gregorian dates and
        // fixed offsets. Checking the complete 400-year leap/weekday cycle is
        // therefore a proof for every future year, including UTC/STANDARD clocks,
        // end-of-day rules and date shifts caused by their offset conversion.
        val byYear = (1999..2400).map { rule.wall(it) }
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
            if (valid) return listOf(pattern)
        }
        // A wall-clock shift can cross a month boundary (for example Egypt's
        // last Thursday at 24:00). Separate annual month predicates remain
        // unlimited and avoid a spurious Cartesian product of month/day sets.
        val split=dates.groupBy {it.monthValue}.toSortedMap().map { (month,entries) ->
            val monthDays=entries.map {it.dayOfMonth}.toSet()
            val negativeDays=entries.map {it.dayOfMonth-it.toLocalDate().lengthOfMonth()-1}.toSet()
            val selected=if(negativeDays.size==1) negativeDays else monthDays
            val weekday=weekdays.singleOrNull()
            FuturePattern("FREQ=YEARLY;BYMONTH=$month;BYMONTHDAY="+selected.sorted().joinToString(",")+
                (weekday?.let {";BYDAY="+names[it]} ?: ""),setOf(month),selected,weekday,null)
        }
        if((2000..2399).all { year ->
                if(year%32==0) check()
                split.flatMap {candidates(it,year,clocks.single())}.distinct().sorted()==byYear.getValue(year)
            }) return split
        throw UnsupportedException("The system time zone's future rule has no verified lossless RFC 5545 representation.")
    }
    @JvmOverloads
    fun definition(identifier: String, checkCancelled: () -> Unit = {}): List<String> {
        requireZone(identifier.isNotEmpty() && identifier.toByteArray(Charsets.UTF_8).size <= 255 && identifier.none { it.code < 32 || it.code == 127 || it == ':' || it == ';' })
        val zone = try { ProviderZoneDatabase.bundled.zone(identifier) } catch (_: IllegalArgumentException) { throw UnsupportedException("The system time zone is unavailable.") }
        val model=zone.model
        val history=model.history
        requireZone(history.size<=100_000)
        val minimum = LocalDate.of(1, 1, 1).atStartOfDay()
        val firstOffset = if(history.isEmpty()) zone.offsetAt(ProviderZone.seconds(minimum)) else model.initial.offset
        val initial = Key(zone.daylightAt(ProviderZone.seconds(minimum)), firstOffset, firstOffset)
        val groups = linkedMapOf<Key, MutableList<LocalDateTime>>()
        groups[initial] = mutableListOf(minimum.plusSeconds(maxOf(0, initial.before).toLong()))
        for (transition in history) {
            checkCancelled()
            val wall=ProviderZone.fromSeconds(transition.at+transition.before)
            requireZone(wall.year in 1..9999)
            val key=Key(transition.daylight,transition.before,transition.after)
            groups.getOrPut(key) { mutableListOf() }.add(wall)
        }
        val lines = mutableListOf("BEGIN:VTIMEZONE", "TZID:" + identifier.replace("\\", "\\\\").replace(",", "\\,"))
        for ((key, dates) in groups) lines.addAll(component(key, dates))
        val boundary=history.lastOrNull()?.at ?: ProviderZone.seconds(minimum)-1
        val future=if(model.tail.daylightOffset==null) emptyList() else listOf(
            model.tail.start!! to Key(true,model.tail.standardOffset,model.tail.daylightOffset),
            model.tail.end!! to Key(false,model.tail.daylightOffset,model.tail.standardOffset))
        for ((rule,key) in future) {
            checkCancelled()
            val patterns=futurePatterns(rule,checkCancelled)
            val year=ProviderZone.fromSeconds(boundary).year
            requireZone(year in 0..9598)
            for(pattern in patterns) {
                val first=(maxOf(1,year-1)..year+401).map {
                    if(it%32==0) checkCancelled()
                    rule.wall(it)
                }.filter {ProviderZone.seconds(it)-key.before>boundary && it.year in 1..9999 &&
                    it in candidates(pattern,it.year,it.toLocalTime())}
                    .minByOrNull {ProviderZone.seconds(it)-key.before}
                    ?: throw UnsupportedException("Missing future time-zone transition.")
                lines.addAll(component(key,listOf(first),pattern.text))
            }
        }
        lines.add("END:VTIMEZONE"); return lines
    }
}
