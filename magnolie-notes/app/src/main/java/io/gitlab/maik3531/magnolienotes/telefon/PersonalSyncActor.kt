package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Correlated manual content starts; transport and ownership are caller gates.
 * Not advertised before actor-scoped staging and commit are connected. */
internal object PersonalSyncActor {
    const val VERSION = 12
    const val START_KIND = "personal_sync.actor_start"
    const val DATA_KIND = "personal_sync.actor_data"
    const val ACK_KIND = "personal_sync.actor_ack"
    const val CANCEL_KIND = "personal_sync.actor_cancel"
    private val reservedKinds = setOf(START_KIND, DATA_KIND, ACK_KIND, CANCEL_KIND)
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

    fun validateCancel(body: JsonObject): JsonObject {
        TelefonNachrichten.exact(body, setOf("format", "run_id"))
        val format = body["format"] as? JsonPrimitive ?: error("Missing actor cancellation format")
        require(!format.isString && format.content == VERSION.toString())
        TelefonNachrichten.uuid4(body.string("run_id"))
        return body
    }
    fun cancel(runId: String): JsonObject = validateCancel(buildJsonObject { put("format", VERSION); put("run_id", runId) })

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

    /** Exact terminal delta only; native target/source/save authority are caller gates. */
    fun completionMembers(runId: String, before: JsonObject, nativeTargets: JsonArray, decisions: JsonArray): JsonObject {
        start(runId); PhoneContentScope.validate(before)
        require(nativeTargets.size == decisions.size && decisions.size <= 256) { "invalid_actor_completion_targets" }
        val targets = linkedMapOf<String, JsonObject>(); val choices = linkedMapOf<String, String>()
        val identities = mutableSetOf<Triple<String, String, String>>()
        for (raw in nativeTargets) {
            val target = raw.jsonObject
            TelefonNachrichten.exact(target, setOf("proposal_id", "kind", "id", "parent_id", "prior_hash", "clock"))
            val proposal = JsonObject(target + mapOf("deleted_ms" to JsonPrimitive(0), "label" to JsonPrimitive("")))
            PersonalSyncProtokoll.validate("personal_sync.deletion_proposals", buildJsonObject {
                put("format", 1); put("run_id", runId); put("proposal_batch_id", runId)
                put("sequence", 0); put("last", true); put("proposals", JsonArray(listOf(proposal)))
            })
            val id = target.string("proposal_id"); val kind = target.string("kind")
            require(kind in setOf("note", "task", "attachment") && id !in targets &&
                identities.add(Triple(kind, target.string("parent_id"), target.string("id")))) { "ambiguous_actor_completion_target" }
            targets[id] = target
        }
        for (raw in decisions) {
            val decision = raw.jsonObject
            PersonalSyncProtokoll.validate("personal_sync.deletion_decision", buildJsonObject {
                put("format", 1); put("run_id", runId); put("decision_id", runId); put("decisions", JsonArray(listOf(decision)))
            })
            val id = decision.string("proposal_id"); val target = targets[id]
            require(id !in choices && target != null && decision["expected_clock"] == target["clock"]) { "actor_completion_decision_changed" }
            choices[id] = decision.string("decision")
        }
        require(choices.keys == targets.keys) { "actor_completion_decision_missing" }
        val members = before.getValue("members").jsonObject
        val notes = members.getValue("notes").jsonArray.map { it.jsonPrimitive.content }.toMutableSet()
        val tasks = members.getValue("tasks").jsonArray.map { it.jsonPrimitive.content }.toMutableSet()
        val allowedParents = notes.toMutableSet(); val deletedNotes = mutableSetOf<String>()
        for ((id, target) in targets.filterValues { it.string("kind") == "note" })
            if (choices[id] == "restore") allowedParents.add(target.string("id")) else deletedNotes.add(target.string("id"))
        for ((id, target) in targets) {
            val choice = choices.getValue(id); val kind = target.string("kind"); val entity = target.string("id")
            if (kind == "attachment") {
                val parent = target.string("parent_id")
                require(parent in allowedParents && !(choice == "restore" && parent in deletedNotes)) { "actor_completion_parent_unavailable" }
            } else if (choice == "delete") {
                require((if (kind == "note") notes else tasks).remove(entity)) { "actor_completion_delete_outside_scope" }
            } else (if (kind == "note") notes else tasks).add(entity)
        }
        return PhoneContentScope.create(notes, tasks, epoch = runId).getValue("members").jsonObject
    }

    /** Actual membership must come from fresh native evidence, never a wire claim. */
    fun requireCompletionScope(runId: String, before: JsonObject, nativeTargets: JsonArray, decisions: JsonArray, actualAfter: JsonObject): JsonObject {
        val members = completionMembers(runId, before, nativeTargets, decisions); PhoneContentScope.validate(actualAfter)
        require(members == actualAfter["members"]) { "actor_completion_scope_changed" }
        if (members == before["members"]) {
            require(PhoneContentScope.reference(actualAfter) == PhoneContentScope.reference(before)) { "actor_completion_scope_generation_changed" }
        } else require(actualAfter.getValue("revision").jsonPrimitive.long > before.getValue("revision").jsonPrimitive.long &&
            actualAfter["epoch"] != before["epoch"]) { "actor_completion_scope_not_advanced" }
        return PhoneContentScope.reference(actualAfter)
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
