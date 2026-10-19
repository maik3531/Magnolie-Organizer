package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Correlated manual content starts; transport and ownership are caller gates.
 * Not advertised before actor-scoped staging and commit are connected. */
internal object PersonalSyncActor {
    const val VERSION = 12
    const val START_KIND = "personal_sync.actor_start"
    const val DATA_KIND = "personal_sync.actor_data"
    const val ACK_KIND = "personal_sync.actor_ack"
    private val reservedKinds = setOf(START_KIND, DATA_KIND, ACK_KIND)
    private const val STORAGE_PEER_PREFIX = "@mcp-actor-"
    private val dataKinds = setOf("personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
        "personal_sync.deletion_proposals", "personal_sync.deletion_decision", PhoneContentScope.DATA_KIND)

    fun isReservedMessage(value: JsonObject): Boolean = value["type"] == JsonPrimitive("message") &&
        (value["kind"] as? JsonPrimitive)?.let { it.isString && isReservedKind(it.content) } == true

    fun isReservedKind(kind: String): Boolean = kind in reservedKinds
    fun storagePeer(runId: String): String { start(runId); return STORAGE_PEER_PREFIX + runId }
    fun isStoragePeer(value: String?): Boolean = value?.startsWith(STORAGE_PEER_PREFIX) == true

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

    fun validateAck(body: JsonObject): JsonObject {
        TelefonNachrichten.exact(body, setOf("format", "run_id", "message_id", "status", "error"))
        val format = body["format"] as? JsonPrimitive ?: error("Missing actor acknowledgement format")
        require(!format.isString && format.content == VERSION.toString())
        TelefonNachrichten.uuid4(body.string("run_id"))
        TelefonNachrichten.validateAck(buildJsonObject {
            put("type", "ack"); put("message_id", body.getValue("message_id")); put("status", body.getValue("status")); put("error", body.getValue("error"))
        })
        return body
    }

    fun ack(runId: String, messageId: String, status: String = "accepted", error: String = "none"): JsonObject = validateAck(buildJsonObject {
        put("format", VERSION); put("run_id", runId); put("message_id", messageId); put("status", status); put("error", error)
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

    /** Caller validates the original header; ACK identity/lifetime remain unchanged. */
    fun wireMessage(message: JsonObject, runId: String): JsonObject = JsonObject(message + mapOf(
        "kind" to JsonPrimitive(DATA_KIND),
        "body" to wrap(runId, message.string("kind"), message.getValue("body").jsonObject))).also {
            require(TelefonKanonisch.bytes(it).size <= 256 * 1024)
        }

    /** Explicit semantic inspection must never replace the persisted/sent wire frame. */
    fun semanticMessage(message: JsonObject): JsonObject {
        if (message.string("kind") != DATA_KIND) return message
        val (kind, body) = unwrap(message.getValue("body").jsonObject)
        return JsonObject(message + mapOf("kind" to JsonPrimitive(kind), "body" to body))
    }

    fun supported(peer: TelefonPeer, local: Map<String, TelefonCapability>): Boolean =
        SharedSyncSettings.supported(peer, local) &&
            VERSION in peer.remote_personal_notes_sync_versions && VERSION in peer.remote_personal_tasks_sync_versions &&
            listOf("personal_notes_sync", "personal_tasks_sync").all { name ->
                local[name]?.let { it.available && VERSION in it.versions } == true
            }
}
