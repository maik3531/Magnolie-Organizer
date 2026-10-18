package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Correlated manual content starts; transport and ownership are caller gates.
 * Not advertised before actor-scoped staging and commit are connected. */
internal object PersonalSyncActor {
    const val VERSION = 12
    const val START_KIND = "personal_sync.actor_start"

    fun validateStart(body: JsonObject): JsonObject {
        TelefonNachrichten.exact(body, setOf("format", "run_id", "trigger"))
        val format = body["format"] as? JsonPrimitive ?: error("Missing actor start format")
        require(!format.isString && format.content == VERSION.toString())
        require(body["trigger"] == JsonPrimitive("manual"))
        TelefonNachrichten.uuid4(body.string("run_id"))
        return body
    }

    fun start(runId: String): JsonObject = validateStart(buildJsonObject {
        put("format", VERSION); put("run_id", runId); put("trigger", "manual")
    })

    fun supported(peer: TelefonPeer, local: Map<String, TelefonCapability>): Boolean =
        SharedSyncSettings.supported(peer, local) &&
            VERSION in peer.remote_personal_notes_sync_versions && VERSION in peer.remote_personal_tasks_sync_versions &&
            listOf("personal_notes_sync", "personal_tasks_sync").all { name ->
                local[name]?.let { it.available && VERSION in it.versions } == true
            }
}
