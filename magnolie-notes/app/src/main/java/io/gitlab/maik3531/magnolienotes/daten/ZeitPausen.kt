package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit

@Serializable
data class ZeitPausenfenster(val start: Int, val end: Int) {
    fun validate(): ZeitPausenfenster {
        require(start in 0..1439 && end in 0..1439 && start != end)
        return this
    }
}

/** A manual pause already in progress replaces a scheduled occurrence completely. */
object ZeitPausen {
    data class Ersetzung(val fixedStart: Long, val fixedEnd: Long, val manualStart: Long) {
        val durationMinutes: Long get() = fixedEnd - fixedStart
    }
    data class Ergebnis(val minutes: Long, val replacements: List<Ersetzung>,
                        val activeFixed: List<Pair<Long, Long>> = emptyList())

    fun minutes(from: Long, until: Long, zone: String, fixed: List<ZeitPausenfenster>,
                manual: List<Pair<Long, Long>> = emptyList()): Long =
        calculate(from, until, zone, fixed, manual).minutes

    fun calculate(from: Long, until: Long, zone: String, fixed: List<ZeitPausenfenster>,
                  manual: List<Pair<Long, Long>> = emptyList(), activeManualStart: Long? = null,
                  replacedFixedStarts: Set<Long> = emptySet(),
                  fixedEndMinutes: Map<Long, Long> = emptyMap()): Ergebnis {
        require(from in 0..Zeiteintrag.MAX_MINUTE && until in from..Zeiteintrag.MAX_MINUTE)
        require(fixed.size <= 16)
        fixed.forEach { it.validate() }
        val manualSorted = manual.sortedBy { it.first }
        manualSorted.forEach { require(it.second >= it.first) }
        require(manualSorted.zipWithNext().all { (first, second) -> first.second <= second.first })
        if (activeManualStart != null) {
            require(activeManualStart in 0..until)
            require(manualSorted.all { it.second <= activeManualStart })
        }
        val replacements = mutableListOf<Ersetzung>()
        val activeFixed = mutableListOf<Pair<Long, Long>>()
        val intervals = mutableListOf<Pair<Long, Long>>()
        fun add(start: Long, end: Long) {
            val left = maxOf(from, start)
            val right = minOf(until, end)
            if (right > left) intervals += left to right
        }
        manualSorted.forEach { (start, end) -> add(start, end) }
        activeManualStart?.let { add(it, until) }
        if (fixed.isNotEmpty()) {
            val timezone = ZoneId.of(zone)
            var day = Instant.ofEpochSecond(from * 60).atZone(timezone).toLocalDate().minusDays(1)
            val last = Instant.ofEpochSecond(until * 60).atZone(timezone).toLocalDate()
            require(ChronoUnit.DAYS.between(day, last) <= 3660)
            while (!day.isAfter(last)) {
                for (window in fixed.distinct()) {
                    val endDay = if (window.end < window.start) day.plusDays(1) else day
                    val begin = day.atStartOfDay().plusMinutes(window.start.toLong()).atZone(timezone).toEpochSecond() / 60
                    val scheduledEnd = endDay.atStartOfDay().plusMinutes(window.end.toLong()).atZone(timezone).toEpochSecond() / 60
                    val end = minOf(scheduledEnd, fixedEndMinutes[begin] ?: scheduledEnd)
                    if (end <= from || begin > until || end <= begin || begin in replacedFixedStarts) continue
                    val manualStart = manualSorted.firstOrNull { it.first <= begin && it.second > begin }?.first
                        ?: activeManualStart?.takeIf { it <= begin }
                    if (manualStart != null) {
                        replacements += Ersetzung(begin, end, manualStart)
                    } else {
                        // Starting another pause while the fixed pause is active is invalid.
                        require(manualSorted.none { it.first > begin && it.first < end })
                        require(activeManualStart == null || activeManualStart <= begin || activeManualStart >= end)
                        add(begin, end)
                        if (begin <= until && until < end) activeFixed += begin to end
                    }
                }
                day = day.plusDays(1)
            }
        }
        var total = 0L
        var left = 0L
        var right = 0L
        for ((start, end) in intervals.sortedBy { it.first }) {
            if (start > right) { total += right - left; left = start; right = end }
            else right = maxOf(right, end)
        }
        return Ergebnis(total + right - left, replacements, activeFixed)
    }
}

@Serializable
data class ZeitPausenwecker(val startedMs: Long, val minutes: Int? = null,
                           val signaled: Set<Int> = emptySet()) {
    fun validate(): ZeitPausenwecker {
        require(startedMs in 0L..253402300799999L)
        require(minutes == null || minutes in 1..2880)
        require(signaled.all { it in 1..2880 })
        return this
    }

    fun warningMs(): Long? {
        validate()
        return minutes?.takeIf { it !in signaled }?.let { startedMs + (it - 1) * 60000L }
    }
    fun nextMs(now: Long): Long? = warningMs()?.coerceAtLeast(now)
    fun select(value: Int?): ZeitPausenwecker {
        require(value == null || value in CHOICES)
        return copy(minutes = value).validate()
    }
    fun adoptFixed(durationMinutes: Int): ZeitPausenwecker = copy(minutes = durationMinutes).validate()
    fun markSignaled(expected: Int, now: Long): ZeitPausenwecker {
        validate()
        if (minutes != expected || expected in signaled || now < startedMs + (expected - 1) * 60000L) return this
        return copy(signaled = signaled + expected)
    }

    companion object { val CHOICES = setOf(5, 15, 30, 45) }
}
