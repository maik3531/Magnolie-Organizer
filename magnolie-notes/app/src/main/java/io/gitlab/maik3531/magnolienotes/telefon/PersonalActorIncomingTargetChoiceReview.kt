package io.gitlab.maik3531.magnolienotes.telefon

import java.security.MessageDigest
import kotlinx.serialization.json.*

/** Private explicit-choice draft, NOT incoming admission, save/mutation or ACK
 * authority. Original frames and fresh observations are native callbacks under
 * the service/book guards. No controller/wire/public tool invokes this draft. */
internal class PersonalActorIncomingTargetChoiceReview(
    private val runId: String,
    private val currentFrames: () -> List<JsonObject>,
    private val currentObservations: (List<JsonObject>) -> List<JsonObject>,
    private val currentAuthority: () -> String?,
    private val currentScope: () -> JsonObject?,
    private val currentSavedBook: () -> JsonObject?
) {
    private val authority = requireNotNull(currentAuthority()).also { require(HEX.matches(it)) }
    private val before = snapshot(requireNotNull(currentScope())).also(PhoneContentScope::validate)
    private val saved = checkedSaved()
    private val original: Pair<List<JsonObject>, Map<String, String>>

    init {
        PersonalSyncActor.start(runId)
        original = originalFrames()
        current()
    }

    private fun checkedSaved() = snapshot(requireNotNull(currentSavedBook())).also {
        require(it.keys == setOf("book_source", "sequence", "sha256") &&
            it.getValue("book_source").jsonPrimitive.isString && it.getValue("sha256").jsonPrimitive.isString &&
            HEX.matches(it.string("book_source")) && HEX.matches(it.string("sha256")) &&
            !it.getValue("sequence").jsonPrimitive.isString && it.getValue("sequence").jsonPrimitive.long in 1..9_007_199_254_740_991L)
    }

    private fun current() {
        check(currentAuthority() == authority) { "actor_target_review_source_changed" }
        check(currentScope() == before) { "actor_target_review_scope_changed" }
        check(checkedSaved() == saved) { "actor_target_review_book_changed" }
        check(originalFrames() == original) { "actor_target_review_frame_changed" }
    }

    private fun originalFrames(): Pair<List<JsonObject>, Map<String, String>> {
        val frames = currentFrames()
        require(frames.size in 1..256) { "invalid_actor_target_review_frames" }
        val hashes = linkedMapOf<String, String>(); val sequences = mutableMapOf<Int, Boolean>()
        var batch: String? = null
        val targets = mutableListOf<JsonObject>(); val ids = mutableSetOf<String>(); val identities = mutableSetOf<Triple<String, String, String>>()
        for (wire in frames) {
            require(wire["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND))
            val frameId = wire.string("message_id"); PersonalSyncActor.start(frameId)
            val (kind, body) = PersonalSyncActor.unwrap(wire.getValue("body").jsonObject)
            require(kind == "personal_sync.deletion_proposals" && body.string("run_id") == runId)
            val digest = hash(wire)
            hashes[frameId]?.let { require(it == digest) { "actor_target_review_frame_changed" } }
            if (frameId in hashes) continue
            val sequence = body.getValue("sequence").jsonPrimitive.int
            require(sequence !in sequences && (batch == null || batch == body.string("proposal_batch_id"))) { "invalid_actor_target_review_group" }
            hashes[frameId] = digest; sequences[sequence] = body.getValue("last").jsonPrimitive.boolean; batch = body.string("proposal_batch_id")
            for (raw in body.getValue("proposals").jsonArray) {
                val proposal = raw.jsonObject
                val target = snapshot(JsonObject(TARGET_KEYS.associateWith(proposal::getValue)))
                val targetKind = target.string("kind"); val parent = target.string("parent_id"); val id = target.string("id")
                require(targetKind in setOf("note", "task", "attachment") && ids.add(target.string("proposal_id")) &&
                    identities.add(Triple(targetKind, parent, id))) { "ambiguous_actor_target_review_target" }
                val member = if (targetKind == "attachment") parent else id
                check(JsonPrimitive(member) !in before.getValue("members").jsonObject.getValue(if (targetKind == "task") "tasks" else "notes").jsonArray) {
                    "actor_target_review_content_target"
                }
                targets += target
            }
        }
        require(targets.size in 1..256 && sequences.keys.sorted() == (0 until sequences.size).toList() &&
            sequences.all { (index, last) -> last == (index == sequences.size - 1) }) { "invalid_actor_target_review_group" }
        return targets.sortedBy { it.string("proposal_id") } to hashes
    }

    fun review(): JsonObject {
        current()
        val targets = original.first.map(::snapshot)
        val observations = currentObservations(targets.map(::snapshot))
        require(observations.size == targets.size)
        val expected = targets.associateBy { it.string("proposal_id") }
        val checked = linkedMapOf<String, JsonObject>()
        for (observation in observations) {
            require(observation.keys == setOf("target", "local_state", "local_hash", "local_clock", "native_saved_book", "metadata_matches", "requires_conflict_choice"))
            val target = observation.getValue("target").jsonObject; val id = target.string("proposal_id")
            require(expected[id] == target && id !in checked && observation["local_state"] in setOf(JsonPrimitive("live"), JsonPrimitive("deleted")) &&
                observation["requires_conflict_choice"] == JsonPrimitive(true) && HEX.matches(observation.string("local_hash")) &&
                observation["native_saved_book"] == saved) { "invalid_actor_target_review_observation" }
            // Validate the local clock with the same strict proposal schema.
            val localTarget = JsonObject(target + ("clock" to observation.getValue("local_clock")))
            PersonalSyncProtokoll.validate("personal_sync.deletion_proposals", buildJsonObject {
                put("format", 1); put("run_id", runId); put("proposal_batch_id", runId); put("sequence", 0); put("last", true)
                put("proposals", JsonArray(listOf(JsonObject(localTarget + mapOf("deleted_ms" to JsonPrimitive(0), "label" to JsonPrimitive(""))))))
            })
            val matches = observation.string("local_hash") == target.string("prior_hash") && observation["local_clock"] == target["clock"]
            require(observation["metadata_matches"] == JsonPrimitive(matches)) { "invalid_actor_target_review_metadata" }
            checked[id] = snapshot(observation)
        }
        val ordered = JsonArray(targets.map { checked.getValue(it.string("proposal_id")) })
        val binding = buildJsonObject {
            put("run_id", runId); put("source", authority); put("saved_book", saved); put("content_scope", before)
            put("frame_hashes", JsonArray(original.second.entries.sortedBy { it.key }.map { JsonArray(listOf(JsonPrimitive(it.key), JsonPrimitive(it.value))) }))
            put("targets", JsonArray(targets)); put("observations", ordered)
        }
        current()
        return buildJsonObject {
            put("revision", hash(binding)); put("targets", JsonArray(targets)); put("observations", ordered)
            put("content_scope", before); put("action_authorized", false)
        }
    }

    fun draftChoices(expectedRevision: String, choices: List<JsonObject>): JsonObject {
        val view = review()
        check(view.string("revision") == expectedRevision) { "actor_target_review_revision_changed" }
        val expected = original.first.associateBy { it.string("proposal_id") }
        require(choices.size == expected.size) { "actor_target_review_explicit_choices_required" }
        val seen = mutableSetOf<String>()
        val decisions = choices.map { choice ->
            require(choice.keys == setOf("proposal_id", "decision", "expected_clock", "confirm_conflict") &&
                choice["confirm_conflict"] == JsonPrimitive(true) && choice.string("proposal_id") in expected && seen.add(choice.string("proposal_id")) &&
                choice["expected_clock"] == expected.getValue(choice.string("proposal_id"))["clock"]) { "actor_target_review_explicit_choices_required" }
            val decision = snapshot(JsonObject(listOf("proposal_id", "decision", "expected_clock").associateWith(choice::getValue)))
            PersonalSyncProtokoll.validate("personal_sync.deletion_decision", buildJsonObject {
                put("format", 1); put("run_id", runId); put("decision_id", runId); put("decisions", JsonArray(listOf(decision)))
            })
            decision
        }.sortedBy { it.string("proposal_id") }
        val deletedParents = decisions.filter { it.string("decision") == "delete" && expected.getValue(it.string("proposal_id")).string("kind") == "note" }
            .map { expected.getValue(it.string("proposal_id")).string("id") }.toSet()
        require(decisions.none { it.string("decision") == "restore" && expected.getValue(it.string("proposal_id")).let { target ->
            target.string("kind") == "attachment" && target.string("parent_id") in deletedParents } }) { "actor_target_review_parent_unavailable" }
        current()
        val result = buildJsonObject {
            put("review_revision", expectedRevision); put("decisions", JsonArray(decisions)); put("conflicts_explicitly_confirmed", true)
            put("content_scope", before); put("action_authorized", false)
        }
        return JsonObject(result + ("choice_revision" to JsonPrimitive(hash(result))))
    }

    companion object {
        private val HEX = Regex("[a-f0-9]{64}")
        private val TARGET_KEYS = listOf("proposal_id", "kind", "id", "parent_id", "prior_hash", "clock")
        private fun snapshot(value: JsonObject) = Json.parseToJsonElement(value.toString()).jsonObject
        private fun hash(value: JsonObject) = MessageDigest.getInstance("SHA-256").digest(TelefonKanonisch.bytes(value)).joinToString("") { "%02x".format(it) }
    }
}
