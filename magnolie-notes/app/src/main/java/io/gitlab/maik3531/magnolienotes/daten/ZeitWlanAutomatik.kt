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
    val lastStoppedEntryId: String = ""
) {
    fun validate(): ZeitWlanAutomatik {
        require(Charsets.UTF_8.newEncoder().canEncode(ssid) && ssid.toByteArray(Charsets.UTF_8).size <= 32)
        require(!enabled || ssid.isNotEmpty())
        require(cooldownMinutes in 1..1440)
        require(blockedUntilMs >= 0)
        require(lastStoppedEntryId.isEmpty() || UUID.fromString(lastStoppedEntryId).toString() == lastStoppedEntryId)
        return this
    }

    fun canStart(observedSsid: String, observedMs: Long, nowMs: Long, hasRunningEntry: Boolean,
                 trackingEnabled: Boolean): Boolean {
        validate()
        return enabled && trackingEnabled && !hasRunningEntry && observedSsid == ssid &&
            nowMs >= blockedUntilMs && observedMs >= blockedUntilMs &&
            observedMs in 0..nowMs && nowMs - observedMs <= 120000L
    }

    fun afterStop(entryId: String, nowMs: Long): ZeitWlanAutomatik {
        validate()
        require(UUID.fromString(entryId).toString() == entryId && nowMs >= 0)
        if (entryId == lastStoppedEntryId) return this
        return copy(blockedUntilMs = maxOf(blockedUntilMs, Math.addExact(nowMs, cooldownMinutes * 60000L)),
            lastStoppedEntryId = entryId).validate()
    }
}
