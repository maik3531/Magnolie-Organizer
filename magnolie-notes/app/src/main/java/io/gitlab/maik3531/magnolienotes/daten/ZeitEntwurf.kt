package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable

/** Raw edits belong in the encrypted draft file, never in an Activity Bundle. */
@Serializable
data class ZeitEntwurf(
    val original: Zeiteintrag,
    val neu: Boolean = false,
    val start: Long = original.startMinute,
    val end: Long? = original.endMinute,
    val pause: String = original.pauseMinutes.toString(),
    val pauseEdited: Boolean = false,
    val kind: String = original.type,
    val note: String = original.note,
    val duration: String? = null,
    val pauseRun: ZeitPausenlauf? = null
) {
    fun pauseMinutes(now: Long): Long =
        if (!pauseEdited && pauseRun != null && duration == null)
            pauseRun.project(original, end ?: now).pausedMinutes(end ?: now)
        else if (!pauseEdited && original.pauseMinute != null && duration == null)
            original.pausedMinutes(end ?: now) else digits(pause).trim().ifBlank { "0" }.toLong()

    fun record(now: Long = Zeiteintrag.currentMinute(), changed: Long = System.currentTimeMillis()): Zeiteintrag {
        if (pauseRun != null && !pauseEdited && duration == null && start == original.startMinute && end == original.endMinute)
            return original.copy(type = kind.trim(), note = note, modifiedMs = changed).validate()
        val pauses = pauseMinutes(now)
        val correctedEnd = duration?.let { text ->
            val match = Regex("([0-9]+):([0-5][0-9])").matchEntire(digits(text).trim()) ?: error("duration")
            Math.addExact(Math.addExact(start, pauses), Math.addExact(
                Math.multiplyExact(match.groupValues[1].toLong(), 60), match.groupValues[2].toLong()))
        } ?: end
        return original.copy(startMinute = start, endMinute = correctedEnd, pauseMinutes = pauses,
            pauseMinute = if (correctedEnd == null && original.pauseMinute != null) now else null,
            type = kind.trim(), note = note, modifiedMs = changed, pausePlan = null).validate()
    }

    companion object {
        fun digits(text: String): String = text.map { it.digitToIntOrNull()?.toString() ?: it.toString() }.joinToString("")
    }
}
