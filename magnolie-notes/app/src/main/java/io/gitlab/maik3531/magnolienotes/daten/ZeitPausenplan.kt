package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable

/** Shared calculation data for an open entry; contains no device settings or alarm grants. */
@Serializable
data class ZeitPausenplan(
    val fixed: List<ZeitPausenfenster> = emptyList(),
    val manual: List<ZeitManuellePause> = emptyList(),
    val replaced: Set<Long> = emptySet(),
    val fixedEnds: Map<Long, Long> = emptyMap(),
    val baseMinutes: Long = 0
) {
    fun validate(entry: Zeiteintrag): ZeitPausenplan {
        require(entry.endMinute == null && !entry.deleted)
        require(fixed.size <= 16 && manual.size <= 10000 && replaced.size <= 60000 && fixedEnds.size <= 60000)
        fixed.forEach { it.validate() }
        require(baseMinutes in 0..(Zeiteintrag.MAX_MINUTE - entry.startMinute))
        require(manual.all { it.start in entry.startMinute..Zeiteintrag.MAX_MINUTE && it.end in it.start..Zeiteintrag.MAX_MINUTE })
        require(manual.zipWithNext().all { (a, b) -> a.end <= b.start })
        require(manual.all { entry.pauseMinute == null || it.end <= entry.pauseMinute })
        require(replaced.all { it in 0..Zeiteintrag.MAX_MINUTE })
        require(fixedEnds.all { (start, end) -> start in 0..Zeiteintrag.MAX_MINUTE && end in start..Zeiteintrag.MAX_MINUTE })
        return this
    }

    fun calculate(entry: Zeiteintrag, now: Long): ZeitPausen.Ergebnis {
        val result = ZeitPausen.calculate(entry.startMinute,
            maxOf(entry.startMinute, entry.pauseMinute ?: entry.startMinute, now), entry.zone,
            fixed, manual.map { it.start to it.end }, entry.pauseMinute, replaced, fixedEnds)
        return result.copy(minutes = Math.addExact(baseMinutes, result.minutes))
    }

    fun project(entry: Zeiteintrag, now: Long): Zeiteintrag {
        val active = entry.pauseMinute?.let { (now - it).coerceAtLeast(0) } ?: 0
        return entry.copy(pauseMinutes = calculate(entry, now).minutes - active).validate()
    }
}
