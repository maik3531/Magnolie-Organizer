package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import java.util.UUID
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Private draft parity only; no service, mutation, wire or native save claim. */
class PersonalActorIncomingTargetChoiceReviewTest {
    private val vectors = Json.parseToJsonElement(File("../contracts/notes-actor-target-choice-draft-v1-vectors.json").readText()).jsonObject
    private val input = vectors.getValue("fixture").jsonObject
    private val run = input.string("run_id")
    private inner class Fixture(val kind: String) {
        var source: String? = input.string("source")
        var scope = PhoneContentScope.create(emptyList(), emptyList(), epoch = run)
        var saved = input.getValue("saved_book").jsonObject
        val clock = JsonArray(listOf(buildJsonObject { put("actor_id", input.string("actor_id")); put("counter", 1) }))
        val target = buildJsonObject {
            put("proposal_id", input.string("proposal_id")); put("kind", kind)
            put("id", when (kind) { "note" -> "own-note"; "task" -> "own-task"; else -> "own-file" })
            put("parent_id", if (kind == "attachment") "own-note" else ""); put("prior_hash", input.string("prior_hash")); put("clock", clock)
        }
        var body = buildJsonObject {
            put("format", 1); put("run_id", run); put("proposal_batch_id", run); put("sequence", 0); put("last", true)
            put("proposals", JsonArray(listOf(JsonObject(target + mapOf("deleted_ms" to JsonPrimitive(0), "label" to input.getValue("label"))))))
        }
        fun frame() = PersonalSyncActor.wireMessage(buildJsonObject {
            put("type", "message"); put("v", 1); put("message_id", input.string("frame_id")); put("kind", "personal_sync.deletion_proposals")
            put("created_ms", input.getValue("created_ms")); put("expires_ms", input.getValue("expires_ms")); put("body", body)
        }, run)
        var duringObservation: () -> Unit = {}
        var alterTargets: (List<JsonObject>) -> Unit = {}
        var alterObservation: (JsonObject) -> JsonObject = { it }
        fun create() = PersonalActorIncomingTargetChoiceReview(run, { listOf(frame()) }, { targets ->
            alterTargets(targets)
            val observations = targets.map { target -> alterObservation(buildJsonObject {
                put("target", target); put("local_state", "live"); put("local_hash", input.string("prior_hash")); put("local_clock", target.getValue("clock"))
                put("native_saved_book", saved); put("metadata_matches", true); put("requires_conflict_choice", true)
            }) }
            duringObservation(); observations
        }, { source }, { scope }, { saved })
        fun choice(decision: String = "delete", forTarget: JsonObject = target) = buildJsonObject {
            put("proposal_id", forTarget.getValue("proposal_id")); put("decision", decision); put("expected_clock", forTarget.getValue("clock")); put("confirm_conflict", true)
        }
        fun changeLabel() {
            val proposal = body.getValue("proposals").jsonArray[0].jsonObject
            body = JsonObject(body + ("proposals" to JsonArray(listOf(JsonObject(proposal + ("label" to JsonPrimitive("Changed protected bytes")))))))
        }
    }

    @Test fun allSharedPrivateDraftRevisionVectorsMatchWithoutChangingDataScopeOrGivingActionRights() {
        for (raw in vectors.getValue("cases").jsonArray) for (decision in listOf("delete", "restore")) {
            val vector = raw.jsonObject; val f = Fixture(vector.string("kind")); val before = f.scope
            val review = f.create(); val view = review.review()
            assertEquals(vector.string("review_revision"), view.string("revision"))
            val draft = review.draftChoices(view.string("revision"), listOf(f.choice(decision)))
            assertEquals(vector.string(decision + "_choice_revision"), draft.string("choice_revision"))
            assertEquals(JsonPrimitive(false), view["action_authorized"]); assertEquals(JsonPrimitive(false), draft["action_authorized"])
            assertEquals(before, draft["content_scope"]); assertEquals(before, f.scope)
            assertFalse((view.toString() + draft.toString()).contains("PRIVATE"))
            assertEquals(draft, review.draftChoices(view.string("revision"), listOf(f.choice(decision))))
        }
    }

    @Test fun pendingTargetReviewAndBothExplicitChoicesMatchTheSharedPrivateVectorsWithoutGrantingRestoreRights() {
        for (raw in vectors.getValue("pending_cases").jsonArray) for (decision in listOf("delete", "restore")) {
            val vector = raw.jsonObject; val f = Fixture(vector.string("kind")); val before = f.scope
            f.alterObservation = { JsonObject(it + ("local_state" to JsonPrimitive("deleted"))) }
            val review = f.create(); val view = review.review()
            assertEquals(vector.string("review_revision"), view.string("revision"))
            val draft = review.draftChoices(view.string("revision"), listOf(f.choice(decision)))
            assertEquals(vector.string(decision + "_choice_revision"), draft.string("choice_revision"))
            assertEquals(JsonPrimitive(false), view["action_authorized"]); assertEquals(JsonPrimitive(false), draft["action_authorized"])
            assertEquals(before, draft["content_scope"]); assertEquals(before, f.scope)
        }
    }

    @Test fun matchingMetadataNeverPermitsImplicitOrChangedConflictChoices() {
        for (fault in listOf("missing-confirm", "false", "numeric-true", "string-true", "clock", "foreign", "unknown", "missing", "extra", "revision")) {
            val f = Fixture("note"); val review = f.create(); val view = review.review()
            var choice = f.choice()
            choice = when (fault) {
                "missing-confirm" -> JsonObject(choice - "confirm_conflict")
                "false" -> JsonObject(choice + ("confirm_conflict" to JsonPrimitive(false)))
                "numeric-true" -> JsonObject(choice + ("confirm_conflict" to JsonPrimitive(1)))
                "string-true" -> JsonObject(choice + ("confirm_conflict" to JsonPrimitive("true")))
                "clock" -> JsonObject(choice + ("expected_clock" to JsonArray(listOf(buildJsonObject { put("actor_id", input.string("actor_id")); put("counter", 2) }))))
                "foreign" -> JsonObject(choice + ("proposal_id" to JsonPrimitive(run)))
                "unknown" -> JsonObject(choice + ("decision" to JsonPrimitive("accept")))
                "extra" -> JsonObject(choice + ("action_authorized" to JsonPrimitive(true)))
                else -> choice
            }
            assertTrue(fault, runCatching { review.draftChoices(if (fault == "revision") "f".repeat(64) else view.string("revision"),
                if (fault == "missing") emptyList() else listOf(choice)) }.isFailure)
        }
    }

    @Test fun originalNativeFramesAndSourceScopeSavedBookAreCheckedBeforeAndAfterObserving() {
        for (fault in listOf("source", "scope", "save", "frame", "frame-race", "optimistic", "metadata", "content")) {
            val f = Fixture("note"); val review = f.create(); val view = review.review()
            when (fault) {
                "source" -> f.source = "f".repeat(64)
                "scope" -> f.scope = PhoneContentScope.create(listOf("different"), emptyList())
                "save" -> f.saved = JsonObject(f.saved + ("sequence" to JsonPrimitive(2)))
                "frame" -> f.changeLabel()
                "frame-race" -> f.duringObservation = { f.changeLabel() }
                "optimistic" -> f.alterObservation = { JsonObject(it + ("requires_conflict_choice" to JsonPrimitive(false))) }
                "metadata" -> f.alterObservation = { JsonObject(it + ("metadata_matches" to JsonPrimitive(false))) }
                "content" -> f.alterObservation = { JsonObject(it + ("content" to JsonPrimitive("PRIVATE"))) }
            }
            assertTrue(fault, runCatching { review.draftChoices(view.string("revision"), listOf(f.choice())) }.isFailure)
        }
    }

    @Test fun incompatibleParentChildChoicesAreRejectedEvenWhenBothConflictsWereConfirmed() {
        for (parent in listOf("delete", "restore")) for (child in listOf("delete", "restore")) {
            val f = Fixture("note")
            val attachment = JsonObject(f.target + mapOf("proposal_id" to JsonPrimitive(UUID.randomUUID().toString()), "kind" to JsonPrimitive("attachment"),
                "id" to JsonPrimitive("own-file"), "parent_id" to JsonPrimitive("own-note")))
            val proposals = listOf(f.target, attachment).map { JsonObject(it + mapOf("deleted_ms" to JsonPrimitive(0), "label" to JsonPrimitive(""))) }
                .sortedBy { it.string("proposal_id") }
            f.body = JsonObject(f.body + ("proposals" to JsonArray(proposals)))
            val review = f.create(); val view = review.review()
            val result = runCatching { review.draftChoices(view.string("revision"), listOf(f.choice(parent), f.choice(child, attachment))) }
            assertEquals(parent == "delete" && child == "restore", result.isFailure)
        }
    }

    @Test fun nativeObservationCallbackCannotReplaceTheOriginalProtectedTargetThroughItsInputList() {
        val f = Fixture("note")
        f.alterTargets = { targets ->
            @Suppress("UNCHECKED_CAST")
            (targets as MutableList<JsonObject>)[0] = JsonObject(targets[0] + ("id" to JsonPrimitive("changed-native-input")))
        }
        assertTrue(runCatching { f.create().review() }.isFailure)
    }
}
