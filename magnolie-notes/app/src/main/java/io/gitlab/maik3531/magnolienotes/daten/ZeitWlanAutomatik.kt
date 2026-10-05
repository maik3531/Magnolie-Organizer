package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.util.UUID

/** Scan observation, not association: no credentials or WLAN connection needed. */
@Serializable
data class ZeitWlanAutomatik(
    val enabled: Boolean = false,
    val ssid: String = "",
    val cooldownMinutes: Int = 60,
    val blockedUntilMs: Long = 0,
    val lastStoppedEntryId: String = "",
    val lastStoppedEvent: String = ""
) {
    fun validate(): ZeitWlanAutomatik {
        require(Charsets.UTF_8.newEncoder().canEncode(ssid) && ssid.toByteArray(Charsets.UTF_8).size <= 32)
        require(!enabled || ssid.isNotEmpty())
        require(cooldownMinutes in 1..1440)
        require(blockedUntilMs >= 0)
        require(lastStoppedEntryId.isEmpty() || UUID.fromString(lastStoppedEntryId).toString() == lastStoppedEntryId)
        require(lastStoppedEvent.length <= 200 && lastStoppedEvent.none { it.code < 32 })
        return this
    }

    fun canStart(observedSsid: String, observedMs: Long, nowMs: Long, hasRunningEntry: Boolean,
                 trackingEnabled: Boolean): Boolean {
        validate()
        return enabled && trackingEnabled && !hasRunningEntry && observedSsid == ssid &&
            nowMs >= blockedUntilMs && observedMs >= blockedUntilMs &&
            observedMs in 0..nowMs && nowMs - observedMs <= 120000L
    }

    fun afterStop(entryId: String, nowMs: Long, event: String = entryId): ZeitWlanAutomatik {
        validate()
        require(UUID.fromString(entryId).toString() == entryId && nowMs >= 0)
        require(event.isNotEmpty() && event.length <= 200 && event.none { it.code < 32 })
        if (event == lastStoppedEvent || entryId == lastStoppedEntryId && event == entryId) return this
        return copy(blockedUntilMs = maxOf(blockedUntilMs, Math.addExact(nowMs, cooldownMinutes * 60000L)),
            lastStoppedEntryId = entryId, lastStoppedEvent = event).validate()
    }

    companion object {
        fun stopEvent(entry: Zeiteintrag): String {
            val value = entry.id + "\n" + entry.clock.toSortedMap().entries.joinToString("\n") { "${it.key}=${it.value}" }
            return java.security.MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
                .joinToString("") { (it.toInt() and 255).toString(16).padStart(2, '0') }
        }
    }
}
