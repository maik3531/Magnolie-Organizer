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
    val fixedEnds: Map<Long, Long> = emptyMap(),
    val endAlarm: ZeitFeierabendwecker = ZeitFeierabendwecker(),
    val baseMinutes: Long = 0
) {
    fun validate(entry: Zeiteintrag): ZeitPausenlauf {
        require(entry.endMinute == null && !entry.deleted)
        endAlarm.validate()
        require(baseMinutes in 0..(Zeiteintrag.MAX_MINUTE - entry.startMinute))
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

    fun calculate(entry: Zeiteintrag, now: Long): ZeitPausen.Ergebnis {
        val result = ZeitPausen.calculate(entry.startMinute,
            maxOf(entry.startMinute, entry.pauseMinute ?: entry.startMinute, now), entry.zone,
            fixed, manual.map { it.start to it.end }, entry.pauseMinute, replaced, fixedEnds)
        return result.copy(minutes = Math.addExact(baseMinutes, result.minutes))
    }

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

    fun sharedPlan(): ZeitPausenplan? = if (fixed.isEmpty()) null else
        ZeitPausenplan(fixed, manual, replaced, fixedEnds, baseMinutes)

    /** Remote edits carry calculation data, never another device's alarm choices. */
    fun follow(entry: Zeiteintrag): ZeitPausenlauf? {
        if (entry.deleted || entry.endMinute != null) return null
        val plan = entry.pausePlan
        return copy(fixed = plan?.fixed.orEmpty(), manual = plan?.manual.orEmpty(),
            replaced = plan?.replaced.orEmpty(), fixedEnds = plan?.fixedEnds.orEmpty(),
            baseMinutes = plan?.baseMinutes ?: entry.pauseMinutes,
            pendingNotices = pendingNotices.intersect(plan?.replaced.orEmpty()),
            alarm = alarm?.takeIf { entry.pauseMinute == it.startedMs / 60000 }).validate(entry)
    }

    fun nextEndAlarmMinute(entry: Zeiteintrag, now: Long): Long? {
        if (endAlarm.fired || entry.endMinute != null || entry.deleted) return null
        val projected = project(entry, now)
        if (endAlarm.due(projected, now)) return now
        endAlarm.clockDue(entry)?.let { return it }
        val target = endAlarm.workedMinutes ?: return null
        val remaining = target - if (endAlarm.includePauses) projected.grossMinutes(now) else projected.totalMinutes(now)
        if (endAlarm.includePauses) return now + remaining
        if (entry.pauseMinute != null) return null
        val fixedEnd = calculate(entry, now).activeFixed.maxOfOrNull { it.second } ?: now
        // Future breaks may move this estimate. Delivery always rechecks actual worked time.
        return fixedEnd + remaining
    }
}
