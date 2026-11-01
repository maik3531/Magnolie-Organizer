package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Native saved-book/scope correlation, not a document writer or transport.
 * All callbacks must observe native state under the journal's service/book locks.
 * In particular, queued controls and persisted controls are not save receipts. */
internal class PersonalActorDecisionCompletion(
    private val runId: String,
    nativeTargets: JsonArray,
    queuedDecisions: List<JsonObject>,
    private val currentAuthority: () -> String?,
    private val currentScope: () -> JsonObject?,
    private val currentSavedBook: () -> JsonObject?,
    private val persistedControls: () -> List<JsonObject>,
    // Native controller may capture these before retiring data ownership and
    // performing its actual one-save; they are never accepted from wire input.
    nativeBeforeScope: JsonObject? = null,
    nativeAuthority: String? = null,
    // Exact locally generated ACKs for incoming native decisions. They must
    // actually be sent before their encrypted journal controls can count.
    nativeSentAcknowledgments: List<JsonObject> = emptyList(),
    nativeHistoricalTargets: JsonArray? = null
) {
    private val before = snapshot(requireNotNull(nativeBeforeScope ?: currentScope())).also(PhoneContentScope::validate)
    private val authority = requireNotNull(nativeAuthority ?: currentAuthority()).also { require(HEX.matches(it)) }
    private val savedBook = checkedSavedBook(currentSavedBook())
    private val targets = Json.parseToJsonElement(nativeTargets.toString()).jsonArray
    private val historicalTargets = nativeHistoricalTargets?.let { Json.parseToJsonElement(it.toString()).jsonArray }
    private val controls = linkedMapOf<String, JsonObject>()
    private val frames = linkedMapOf<String, JsonObject>()
    private val received = linkedMapOf<String, JsonObject>()
    private val ownAcknowledgments = linkedMapOf<String, JsonObject>()
    private val successfullySent = mutableSetOf<String>()
    private val decisions: JsonArray

    // Stable callback identity is part of the volatile native owner capability.
    val validator: (String, JsonObject?) -> Boolean? = ::validate

    init {
        PersonalSyncActor.start(runId)
        require(queuedDecisions.size in 1..256) { "invalid_actor_completion_controls" }
        val all = mutableListOf<JsonElement>()
        for (queued in queuedDecisions) {
            val wire = snapshot(queued)
            require(wire["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND)) { "invalid_actor_completion_controls" }
            val id = wire.string("message_id"); TelefonNachrichten.uuid4(id)
            val (kind, body) = PersonalSyncActor.unwrap(wire.getValue("body").jsonObject)
            require(kind == "personal_sync.deletion_decision" && body.string("run_id") == runId && id !in controls) {
                "invalid_actor_completion_controls"
            }
            controls[id] = body; frames[id] = wire
            all.addAll(body.getValue("decisions").jsonArray)
        }
        decisions = JsonArray(all)
        if (historicalTargets == null) PersonalSyncActor.completionMembers(runId, before, targets, decisions)
        else PersonalSyncActor.historicalCompletionMembers(runId, before, targets, decisions, historicalTargets)
        require(nativeSentAcknowledgments.size <= 256)
        for (queued in nativeSentAcknowledgments) {
            val wire = snapshot(queued)
            val body = ack(wire)
            require(body.string("status") == "accepted" && body.string("error") == "none" &&
                ownAcknowledgments.putIfAbsent(body.string("message_id"), wire) == null) { "invalid_actor_completion_controls" }
        }
    }

    private fun ack(wire: JsonObject): JsonObject {
        require(wire["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND)) { "unexpected_actor_completion_control" }
        val body = PersonalSyncActor.validateAck(wire.getValue("body").jsonObject)
        require(body.string("run_id") == runId && body.string("message_id") in controls) { "unexpected_actor_completion_control" }
        ownAcknowledgments[body.string("message_id")]?.let {
            require(it == wire) { "unexpected_actor_completion_control" }
        }
        val previous = received[body.string("message_id")]
        require(previous?.string("status") !in SUCCESS || body.string("status") != "rejected") { "actor_completion_outcome_changed" }
        return body
    }

    private fun validate(operation: String, wire: JsonObject?): Boolean? {
        require(operation in setOf("begin", "put", "read", "send", "finish")) { "unexpected_actor_completion_operation" }
        val body = if (operation == "send") {
            requireNotNull(wire)
            if (wire["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND)) {
                val value = ack(wire)
                require(ownAcknowledgments[value.string("message_id")] == wire) { "unexpected_actor_completion_control" }
                value
            } else {
                require(frames[wire.string("message_id")] == wire &&
                    wire.string("message_id") !in ownAcknowledgments) { "unexpected_actor_completion_control" }
                null
            }
        } else wire?.let(::ack)
        if (runCatching { checkedSavedBook(currentSavedBook()) }.getOrNull() != savedBook) return false
        val actualAuthority = currentAuthority() ?: return null
        if (actualAuthority != authority) return false
        val actual = currentScope() ?: return null
        if (runCatching { PhoneContentScope.validate(actual) }.isFailure) return false
        val atBefore = PhoneContentScope.reference(actual) == PhoneContentScope.reference(before)
        val atAfter = runCatching {
            if (historicalTargets == null) PersonalSyncActor.requireCompletionScope(runId, before, targets, decisions, actual)
            else PersonalSyncActor.requireHistoricalCompletionScope(runId, before, targets, decisions, historicalTargets, actual)
        }.isSuccess
        if (!atBefore && !atAfter) return false
        if (body?.string("status") in SUCCESS && !atAfter) return null
        if (operation == "put" && body != null && body.string("message_id") in ownAcknowledgments &&
            body.string("message_id") !in successfullySent) return null
        if (operation == "finish" && (!atAfter || received.keys != controls.keys ||
                received.values.any { it.string("status") !in SUCCESS })) return null
        return true
    }

    fun expectsNativeAcknowledgment(messageId: String): Boolean = messageId in ownAcknowledgments

    /** Native controller calls only after the actual channel send returned, under
     * fresh service/book gates. An outbox enqueue or failed flush cannot call it. */
    fun recordSuccessfulAcknowledgmentSend(wire: JsonObject) {
        check(validate("send", wire) == true) { "actor_completion_not_ready" }
        val body = ack(wire)
        check(ownAcknowledgments[body.string("message_id")] == wire) { "unexpected_actor_completion_control" }
        successfullySent.add(body.string("message_id"))
    }

    /** Only call after the journal transaction committed this exact encrypted control. */
    fun recordPersisted(wire: JsonObject) {
        check(validate("put", wire) == true) { "actor_completion_not_ready" }
        check(persistedControls().any { it == wire }) { "actor_completion_control_not_persisted" }
        val body = ack(wire)
        received[body.string("message_id")] = snapshot(body)
    }

    fun summary(): JsonObject = buildJsonObject {
        put("expected", controls.size); put("received", received.size)
        put("saved", received.values.count { it.string("status") in SUCCESS })
        put("rejected", received.values.count { it.string("status") == "rejected" })
    }

    companion object {
        private val HEX = Regex("[0-9a-f]{64}")
        private val SUCCESS = setOf("accepted", "duplicate")
        private fun snapshot(value: JsonObject): JsonObject = Json.parseToJsonElement(value.toString()).jsonObject
        private fun checkedSavedBook(value: JsonObject?): JsonObject {
            requireNotNull(value) { "native_book_not_saved" }
            TelefonNachrichten.exact(value, setOf("book_source", "sequence", "sha256"))
            require(listOf("book_source", "sha256").all { value[it]?.let { raw ->
                raw is JsonPrimitive && raw.isString && HEX.matches(raw.content)
            } == true } && value["sequence"]?.let { raw ->
                raw is JsonPrimitive && !raw.isString && (raw.longOrNull ?: 0) > 0
            } == true) { "native_book_not_saved" }
            return snapshot(value)
        }
    }
}
