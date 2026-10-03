package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull

/** Authenticated availability hints; never a document or permission transfer. */
object PersonalDesktopFeatures {
    const val VERSION = 6
    const val KIND = "personal_sync.desktop_features"

    fun customAvailable(peer: TelefonPeer): Boolean = peer.remote_desktop_features?.let {
        runCatching { validate(it); (it.getValue("custom_tab") as JsonPrimitive).booleanOrNull == true }.getOrDefault(false)
    } ?: (VERSION !in peer.remote_personal_tasks_sync_versions)

    fun treeVisible(peer: TelefonPeer?, independent: Boolean, pending: Boolean): Boolean {
        if (independent || pending || peer == null) return true
        return peer.remote_desktop_features?.let {
            runCatching { validate(it); (it.getValue("tree") as JsonPrimitive).booleanOrNull == true }.getOrDefault(false)
        } ?: (VERSION !in peer.remote_personal_tasks_sync_versions)
    }

    fun validate(body: JsonObject) {
        TelefonNachrichten.exact(body, setOf("format", "revision", "custom_tab", "tree"))
        if (body.long("format") != VERSION.toLong() || body.long("revision") !in 1..9_007_199_254_740_991L ||
            listOf("custom_tab", "tree").any { name ->
                val value = body[name] as? JsonPrimitive
                value == null || value.isString || value.booleanOrNull == null
            }) throw TelefonProtokollFehler("Ungültige Desktop-Funktionen.")
    }

    fun accept(current: JsonObject?, incoming: JsonObject): JsonObject {
        validate(incoming)
        if (current != null) {
            validate(current)
            if (incoming.long("revision") < current.long("revision") ||
                incoming.long("revision") == current.long("revision") && incoming != current)
                throw TelefonProtokollFehler("Veraltete Desktop-Funktionen.")
        }
        return incoming
    }
}
