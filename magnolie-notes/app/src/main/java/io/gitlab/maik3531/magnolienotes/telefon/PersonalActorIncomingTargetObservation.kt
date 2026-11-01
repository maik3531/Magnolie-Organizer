package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.Bestand
import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import kotlinx.serialization.json.*

/** Private native LIVE/current-pending observation only, never admission, typed action, data,
 * queue or ACK authority. All callbacks run under the native service/book locks.
 * The saved-book callback must be the actual writer witness, not wire JSON. */
internal class PersonalActorIncomingTargetObservation(
    private val peerId: String,
    private val runId: String,
    private val currentOwner: () -> Boolean,
    private val currentSource: () -> String?,
    private val currentBook: () -> Bestand,
    private val currentSavedBook: () -> JsonObject?,
    private val currentScope: () -> JsonObject?
) {
    private val source: String
    private val saved: JsonObject
    private val book: Bestand
    private val before: JsonObject
    private val observed = linkedMapOf<String, JsonObject>()
    private val identities = mutableMapOf<String, String>()

    init {
        PersonalSyncActor.start(peerId); PersonalSyncActor.start(runId)
        check(currentOwner()) { "actor_target_owner_changed" }
        source = requireNotNull(currentSource()).also { require(HEX.matches(it)) }
        saved = savedBook()
        book = currentBook()
        before = snapshot(requireNotNull(currentScope())).also(PhoneContentScope::validate)
        checkCurrent()
    }

    private fun savedBook(): JsonObject = snapshot(requireNotNull(currentSavedBook())).also {
        require(it.keys == setOf("book_source", "sequence", "sha256") &&
            it.getValue("book_source").jsonPrimitive.isString && it.getValue("sha256").jsonPrimitive.isString &&
            !it.getValue("sequence").jsonPrimitive.isString &&
            HEX.matches(it.string("book_source")) && HEX.matches(it.string("sha256")) &&
            it.getValue("sequence").jsonPrimitive.long in 1..9_007_199_254_740_991L)
    }

    private fun checkCurrent() {
        check(currentOwner() && currentSource() == source) { "actor_target_source_changed" }
        check(currentScope() == before) { "actor_target_scope_changed" }
        check(currentBook() === book && savedBook() == saved) { "actor_target_book_changed" }
        check(currentOwner() && currentSource() == source) { "actor_target_source_changed" }
    }

    fun observeMany(expectedRunId: String, targets: List<JsonObject>): List<JsonObject> {
        checkCurrent()
        require(expectedRunId == runId) { "actor_target_proof_changed" }
        require(targets.size in 1..256) { "actor_target_capacity" }
        val previous = observed.toMap(); val previousIdentities = identities.toMap()
        return try {
            val seen = mutableSetOf<String>()
            val result = targets.map { target ->
                check(seen.add(target.string("proposal_id"))) { "actor_target_duplicate_group" }
                observeTarget(target)
            }
            checkCurrent()
            result
        } catch (error: Exception) {
            observed.clear(); observed.putAll(previous)
            identities.clear(); identities.putAll(previousIdentities)
            throw error
        }
    }

    private fun validateTarget(target: JsonObject) {
        require(target.keys == setOf("proposal_id", "kind", "id", "parent_id", "prior_hash", "clock"))
        PersonalSyncProtokoll.validate("personal_sync.deletion_proposals", buildJsonObject {
            put("format", 1); put("run_id", runId); put("proposal_batch_id", runId); put("sequence", 0); put("last", true)
            put("proposals", JsonArray(listOf(JsonObject(target + mapOf("deleted_ms" to JsonPrimitive(0), "label" to JsonPrimitive(""))))))
        })
    }

    private fun observeTarget(input: JsonObject): JsonObject {
        val target = snapshot(input); validateTarget(target)
        val kind = target.string("kind"); val id = target.string("id"); val parent = target.string("parent_id")
        val proposal = target.string("proposal_id")
        require(kind in setOf("note", "task", "attachment"))
        val member = if (kind == "attachment") parent else id
        check(JsonPrimitive(member) !in before.getValue("members").jsonObject.getValue(if (kind == "task") "tasks" else "notes").jsonArray) {
            "actor_target_already_in_content_scope"
        }
        val identity = JsonArray(listOf(kind, parent, id).map(::JsonPrimitive)).toString()
        check((observed[proposal]?.get("target")?.let { it == target } ?: true) &&
            (identities[identity]?.let { it == proposal } ?: true)) { "actor_target_proof_changed" }
        require(proposal in observed || observed.size < 256) { "actor_target_capacity" }
        val state = book.personalSync
        val key = kind + "\u0000" + (if (kind == "attachment") parent + "\u0000" else "") + id
        val meta = requireNotNull(state.entities[key]) { "actor_target_live_native_proof_missing" }
        check(state.peer_device_id == peerId && meta.peer_device_id == peerId) { "actor_target_live_native_proof_missing" }
        val pending = meta.state == "deleted" && meta.status == "local_pending"
        val localHash = if (pending) meta.prior_hash else meta.hash
        check((meta.state == "live" || pending) && meta.parent_id == parent && !meta.conflict && HEX.matches(localHash)) {
            "actor_target_live_native_proof_missing"
        }
        val clock = JsonArray(meta.clock.map { buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } })
        validateTarget(JsonObject(target + ("clock" to clock)))
        if (pending) {
            val local = buildJsonObject {
                put("proposal_id", meta.proposal_id); put("kind", kind); put("id", id); put("parent_id", parent)
                put("clock", clock); put("prior_hash", localHash); put("deleted_ms", meta.deleted_ms); put("label", meta.label)
            }
            PersonalSyncProtokoll.validate("personal_sync.deletion_proposals", buildJsonObject {
                put("format", 1); put("run_id", runId); put("proposal_batch_id", runId); put("sequence", 0); put("last", true)
                put("proposals", JsonArray(listOf(local)))
            })
            check(meta.hash.isEmpty() && meta.proposal_id == PersonalSync.proposalId(peerId, kind, id, parent, meta.clock, localHash)) {
                "actor_target_pending_native_proof_missing"
            }
        }
        val notes = book.notizen.filter { PersonalSync.noteWireId(state, it.id) == (if (kind == "attachment") parent else id) }
        val own = if (kind == "task") book.aufgaben.filter { it.id == id }.let { if (pending) it.isEmpty() else it.size == 1 && PersonalSync.ownTask(it.single()) }
            else if (kind == "note" && pending) notes.isEmpty()
            else notes.size == 1 && PersonalSync.ownNote(notes.single()) && (kind != "attachment" ||
                notes.single().anhaenge.count { PersonalSync.attachmentId(state, parent, it.id) == id } == if (pending) 0 else 1)
        check(own) { "actor_target_live_native_proof_missing" }
        val result = buildJsonObject {
            put("target", target); put("local_state", if (pending) "deleted" else "live"); put("local_hash", localHash); put("local_clock", clock)
            put("native_saved_book", saved); put("metadata_matches", localHash == target.string("prior_hash") && clock == target["clock"])
            // Metadata equality is not a recomputed current content hash.
            put("requires_conflict_choice", true)
        }
        observed[proposal] = result; identities[identity] = proposal
        return snapshot(result)
    }

    companion object {
        private val HEX = Regex("[a-f0-9]{64}")
        private fun snapshot(value: JsonObject) = Json.parseToJsonElement(value.toString()).jsonObject
    }
}
