package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.Locale

/** Minute-precision records. Rendering a running clock never modifies storage. */
@Serializable
@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
data class Zeiteintrag(
    @kotlinx.serialization.EncodeDefault
    val id: String = UUID.randomUUID().toString(),
    val startMinute: Long,
    val endMinute: Long? = null,
    val pauseMinute: Long? = null,
    val pauseMinutes: Long = 0,
    @kotlinx.serialization.EncodeDefault
    val zone: String = ZoneId.systemDefault().id,
    val type: String = "",
    val note: String = "",
    @kotlinx.serialization.EncodeDefault
    val modifiedMs: Long = System.currentTimeMillis(),
    val deleted: Boolean = false,
    val clock: Map<String, Long> = emptyMap()
) {
    fun validate(): Zeiteintrag {
        require(runCatching { UUID.fromString(id).toString() == id && id[14] == '4' }.getOrDefault(false))
        require(startMinute in 0L..MAX_MINUTE && (endMinute == null || endMinute in startMinute..MAX_MINUTE))
        require(pauseMinutes in 0L..(MAX_MINUTE - startMinute) && modifiedMs in 0L..253402300799999L)
        require(pauseMinute == null || endMinute == null && pauseMinute in startMinute..MAX_MINUTE)
        require(endMinute == null || pauseMinutes <= endMinute - startMinute)
        require(pauseMinute == null || pauseMinutes <= pauseMinute - startMinute)
        require(type.length <= 120 && note.length <= 20000)
        require(clock.size <= 32 && clock.all { (actor, counter) ->
            runCatching { UUID.fromString(actor).toString() == actor }.getOrDefault(false) && counter in 1L..9007199254740991L
        })
        ZoneId.of(zone)
        return this
    }

    fun grossMinutes(nowMinute: Long = currentMinute()): Long = ((endMinute ?: nowMinute) - startMinute).coerceAtLeast(0)
    fun pausedMinutes(nowMinute: Long = currentMinute()): Long = pauseMinutes +
        if (pauseMinute == null) 0 else (nowMinute - pauseMinute).coerceAtLeast(0)
    fun totalMinutes(nowMinute: Long = currentMinute()): Long = (grossMinutes(nowMinute) - pausedMinutes(nowMinute)).coerceAtLeast(0)
    fun localStart(): LocalDateTime = local(startMinute)
    fun sameContent(other: Zeiteintrag): Boolean = copy(modifiedMs = 0, clock = emptyMap()) ==
        other.copy(modifiedMs = 0, clock = emptyMap())
    fun localEnd(): LocalDateTime? = endMinute?.let(::local)
    fun local(value: Long): LocalDateTime = Instant.ofEpochSecond(Math.multiplyExact(value, 60)).atZone(ZoneId.of(zone)).toLocalDateTime()
    fun displayTime(value: Long, locale: Locale, use24HourClock: Boolean): String = local(value)
        .format(DateTimeFormatter.ofPattern(if (use24HourClock) "HH:mm" else "h:mm a", locale))

    fun pause(at: Long = currentMinute(), changed: Long = System.currentTimeMillis()): Zeiteintrag {
        validate(); if (deleted || endMinute != null || pauseMinute != null) return this
        require(at in startMinute..MAX_MINUTE)
        return copy(pauseMinute = at, modifiedMs = changed).validate()
    }
    fun resume(at: Long = currentMinute(), changed: Long = System.currentTimeMillis()): Zeiteintrag {
        validate(); if (deleted || endMinute != null || pauseMinute == null) return this
        require(at in pauseMinute..MAX_MINUTE)
        return copy(pauseMinute = null, pauseMinutes = Math.addExact(pauseMinutes, at - pauseMinute), modifiedMs = changed).validate()
    }
    fun finish(at: Long = currentMinute(), changed: Long = System.currentTimeMillis()): Zeiteintrag {
        validate(); if (deleted || endMinute != null) return this
        require(at >= startMinute)
        val resumed = resume(at, changed)
        return resumed.copy(endMinute = at, modifiedMs = changed).validate()
    }

    fun corrected(start: Long, end: Long, pauses: Long, kind: String, text: String,
                  changed: Long = System.currentTimeMillis()): Zeiteintrag = copy(startMinute = start, endMinute = end,
        pauseMinute = null, pauseMinutes = pauses, type = kind.trim(), note = text, modifiedMs = changed).validate()

    companion object {
        const val MAX_MINUTE = 4223371679L
        fun currentMinute(): Long = System.currentTimeMillis() / 60000
        fun duration(value: Long, locale: Locale = Locale.ROOT): String = "%d:%02d".format(locale, value / 60, value % 60)
        fun suggestedType(hour: Int): String = when (hour) {
            in 4..11 -> "early"
            in 12..19 -> "late"
            else -> "night"
        }
    }
}
