package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.ZoneId

/** Reminder only: it never finishes or modifies the tracked interval. */
@Serializable
data class ZeitFeierabendwecker(
    val clockMinute: Int? = null,
    val workedMinutes: Long? = null,
    val includePauses: Boolean = false,
    val autoStop: Boolean = false,
    val fired: Boolean = false
) {
    fun validate(): ZeitFeierabendwecker {
        require(clockMinute == null || clockMinute in 0..1439)
        require(workedMinutes == null || workedMinutes in 1L..525600L)
        require(clockMinute == null || workedMinutes == null)
        return this
    }

    fun clockDue(entry: Zeiteintrag): Long? {
        validate(); entry.validate()
        val minute = clockMinute ?: return null
        val zone = ZoneId.of(entry.zone)
        val start = Instant.ofEpochSecond(entry.startMinute * 60).atZone(zone)
        var day = start.toLocalDate()
        var due = day.atStartOfDay().plusMinutes(minute.toLong()).atZone(zone).toEpochSecond() / 60
        if (due <= entry.startMinute) {
            day = day.plusDays(1)
            due = day.atStartOfDay().plusMinutes(minute.toLong()).atZone(zone).toEpochSecond() / 60
        }
        return due
    }

    fun due(entry: Zeiteintrag, nowMinute: Long): Boolean {
        validate(); entry.validate()
        if (fired || entry.deleted || entry.endMinute != null) return false
        return workedMinutes?.let { (if (includePauses) entry.grossMinutes(nowMinute) else entry.totalMinutes(nowMinute)) >= it }
            ?: clockDue(entry)?.let { nowMinute >= it } ?: false
    }

    fun markFired(entry: Zeiteintrag, nowMinute: Long): ZeitFeierabendwecker =
        if (due(entry, nowMinute)) copy(fired = true) else this
}
