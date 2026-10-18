package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Correlated manual content starts; transport and ownership are caller gates.
 * Not advertised before actor-scoped staging and commit are connected. */
internal object PersonalSyncActor {
    const val VERSION = 12
    const val START_KIND = "personal_sync.actor_start"
    const val DATA_KIND = "personal_sync.actor_data"
    private val dataKinds = setOf("personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
        "personal_sync.deletion_proposals", "personal_sync.deletion_decision", PhoneContentScope.DATA_KIND)

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

    fun validateData(value: JsonObject): JsonObject {
        TelefonNachrichten.exact(value, setOf("format", "run_id", "kind", "body"))
        val format = value["format"] as? JsonPrimitive ?: error("Missing actor data format")
        require(!format.isString && format.content == VERSION.toString())
        val runId = value.string("run_id"); TelefonNachrichten.uuid4(runId)
        val kind = value.string("kind"); require(kind in dataKinds)
        val body = value["body"] as? JsonObject ?: error("Missing actor record body")
        val recordBody = if (kind == PhoneContentScope.DATA_KIND) {
            PhoneContentScope.validateData(body); body.getValue("body").jsonObject
        } else { PersonalSyncProtokoll.validate(kind, body); body }
        require(recordBody.string("run_id") == runId &&
            ("trigger" !in recordBody || recordBody["trigger"] == JsonPrimitive("manual")) && TelefonKanonisch.bytes(value).size <= 256 * 1024)
        return value
    }

    fun wrap(runId: String, kind: String, body: JsonObject): JsonObject = validateData(buildJsonObject {
        put("format", VERSION); put("run_id", runId); put("kind", kind); put("body", body)
    })

    fun unwrap(value: JsonObject): Pair<String, JsonObject> {
        validateData(value)
        return value.string("kind") to value.getValue("body").jsonObject
    }

    fun supported(peer: TelefonPeer, local: Map<String, TelefonCapability>): Boolean =
        SharedSyncSettings.supported(peer, local) &&
            VERSION in peer.remote_personal_notes_sync_versions && VERSION in peer.remote_personal_tasks_sync_versions &&
            listOf("personal_notes_sync", "personal_tasks_sync").all { name ->
                local[name]?.let { it.available && VERSION in it.versions } == true
            }
}
