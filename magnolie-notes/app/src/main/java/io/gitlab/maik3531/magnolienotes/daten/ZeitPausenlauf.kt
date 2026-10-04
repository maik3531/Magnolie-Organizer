package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable

@Serializable
data class ZeitManuellePause(val start: Long, val end: Long)

/** Local, encrypted automation snapshot; finished wire records retain only their total. */
@Serializable
data class ZeitPausenlauf(
    val fixed: List<ZeitPausenfenster> = emptyList(),
    val manual: List<ZeitManuellePause> = emptyList(),
    val alarm: ZeitPausenwecker? = null,
    val replaced: Set<Long> = emptySet(),
    val pendingNotices: Set<Long> = emptySet(),
    val fixedEnds: Map<Long, Long> = emptyMap()
) {
    fun validate(entry: Zeiteintrag): ZeitPausenlauf {
        require(entry.endMinute == null && !entry.deleted)
        require(fixed.size <= 16)
        fixed.forEach { it.validate() }
        require(manual.all { it.start >= entry.startMinute && it.end in it.start..Zeiteintrag.MAX_MINUTE })
        require(manual.zipWithNext().all { (a, b) -> a.end <= b.start })
        require(manual.all { entry.pauseMinute == null || it.end <= entry.pauseMinute })
        require(replaced.all { it in 0..Zeiteintrag.MAX_MINUTE } && pendingNotices.all { it in replaced })
        require(fixedEnds.all { (start, end) -> start in 0..Zeiteintrag.MAX_MINUTE && end in start..Zeiteintrag.MAX_MINUTE })
        alarm?.let { it.validate(); require(entry.pauseMinute == it.startedMs / 60000) }
        return this
    }

    fun calculate(entry: Zeiteintrag, now: Long): ZeitPausen.Ergebnis = ZeitPausen.calculate(
        entry.startMinute, maxOf(entry.startMinute, entry.pauseMinute ?: entry.startMinute, now), entry.zone,
        fixed, manual.map { it.start to it.end }, entry.pauseMinute, replaced, fixedEnds)

    fun evaluated(entry: Zeiteintrag, now: Long): ZeitPausenlauf {
        val replacements = calculate(entry, now).replacements
        if (replacements.isEmpty()) return this
        val starts = replacements.map { it.fixedStart }.toSet()
        val target = replacements.lastOrNull { it.manualStart == entry.pauseMinute }
        return copy(replaced = replaced + starts, pendingNotices = pendingNotices + starts,
            alarm = if (target == null) alarm else alarm?.adoptFixed(target.durationMinutes.toInt()))
    }

    fun project(entry: Zeiteintrag, now: Long): Zeiteintrag {
        val active = entry.pauseMinute?.let { (now - it).coerceAtLeast(0) } ?: 0
        return entry.copy(pauseMinutes = calculate(entry, now).minutes - active).validate()
    }
}
