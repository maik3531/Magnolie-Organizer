package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

/** Terminal metadata math only: not native origin, save or mutation acceptance. */
class PersonalActorHistoricalResultScopeTest {
    private val run = "44444444-4444-4444-8444-444444444444"
    private val actor = "11111111-1111-4111-8111-111111111111"
    private fun target(kind: String = "note", id: String = "historical-target", parent: String = "") = buildJsonObject {
        put("proposal_id", UUID.randomUUID().toString()); put("kind", kind); put("id", id); put("parent_id", parent); put("prior_hash", "a".repeat(64))
        put("clock", JsonArray(listOf(buildJsonObject { put("actor_id", actor); put("counter", 1) })))
    }
    private fun choice(target: JsonObject, decision: String) = buildJsonObject {
        put("proposal_id", target.getValue("proposal_id")); put("decision", decision); put("expected_clock", target.getValue("clock"))
    }
    private fun array(vararg values: JsonObject) = JsonArray(values.toList())

    @Test fun historicalNoteTaskAndChildActionsNeverChangeTheOriginalDataMembershipOrGeneration() {
        for (kind in listOf("note", "task", "attachment")) for (decision in listOf("delete", "restore")) {
            val before = PhoneContentScope.create(listOf("data-note"), listOf("data-task"))
            val target = target(kind, parent = if (kind == "attachment") "historical-parent" else "")
            assertEquals(before["members"], PersonalSyncActor.historicalCompletionMembers(run, before, array(target), array(choice(target, decision)), array(target)))
            PersonalSyncActor.requireHistoricalCompletionScope(run, before, array(target), array(choice(target, decision)), array(target), before)
            val advanced = PhoneContentScope.advance(before, listOf("data-note", if (kind == "attachment") "historical-parent" else "historical-target"), listOf("data-task"))
            assertTrue(runCatching { PersonalSyncActor.requireHistoricalCompletionScope(run, before, array(target), array(choice(target, decision)), array(target), advanced) }.isFailure)
        }
    }

    @Test fun nativeHistoricalSubsetCannotRelabelDataTargetsOrChangeProofsAndClocks() {
        for (fault in listOf("data-target", "changed-proof", "foreign-proof", "duplicate-proof", "missing-decision", "changed-clock", "duplicate-target")) {
            val before = PhoneContentScope.create(listOf("data-note"), listOf("data-task"))
            val target = target(id = if (fault == "data-target") "data-note" else "historical-target")
            var targets = array(target); var historical = array(target); var choices = array(choice(target, "restore"))
            when (fault) {
                "changed-proof" -> historical = array(JsonObject(target + ("prior_hash" to JsonPrimitive("b".repeat(64)))))
                "foreign-proof" -> historical = array(target())
                "duplicate-proof" -> historical = array(target, target)
                "missing-decision" -> choices = array()
                "changed-clock" -> choices = array(JsonObject(choice(target, "restore") + ("expected_clock" to JsonArray(listOf(buildJsonObject { put("actor_id", actor); put("counter", 2) })))))
                "duplicate-target" -> { val duplicate = JsonObject(target + ("proposal_id" to JsonPrimitive(UUID.randomUUID().toString())))
                    targets = array(target, duplicate); choices = array(choice(target, "restore"), choice(duplicate, "restore")) }
            }
            assertTrue(fault, runCatching { PersonalSyncActor.historicalCompletionMembers(run, before, targets, choices, historical) }.isFailure)
        }
        val parent = target(id = "historical-parent"); val child = target("attachment", "historical-child", "historical-parent")
        assertTrue(runCatching { PersonalSyncActor.historicalCompletionMembers(run, PhoneContentScope.create(listOf("data-note"), emptyList()),
            array(parent, child), array(choice(parent, "delete"), choice(child, "restore")), array(parent, child)) }.isFailure)
    }

    @Test fun mixedDataAndHistoricalReceiptsNeedBothDirectionsWithoutHistoricalDataMembership() {
        val before = PhoneContentScope.create(listOf("data-note"), listOf("data-task")); val data = target(id = "data-note"); val historical = target("task")
        val targets = array(data, historical); val choices = listOf(choice(data, "delete"), choice(historical, "restore"))
        val after = PhoneContentScope.advance(before, emptyList(), listOf("data-task"))
        assertEquals(after["members"], PersonalSyncActor.historicalCompletionMembers(run, before, targets, JsonArray(choices), array(historical)))
        val frames = choices.map { decision -> PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.deletion_decision", buildJsonObject {
            put("format", 1); put("run_id", run); put("decision_id", UUID.randomUUID().toString()); put("decisions", array(decision))
        }, 60000), run) }
        val acks = frames.map { TelefonNachrichten.message(PersonalSyncActor.ACK_KIND, PersonalSyncActor.ack(run, it.string("message_id")), 60000) }
        val retained = mutableListOf<JsonObject>()
        val saved = buildJsonObject { put("book_source", "b".repeat(64)); put("sequence", 2); put("sha256", "c".repeat(64)) }
        val completion = PersonalActorDecisionCompletion(run, targets, frames, { "d".repeat(64) }, { after }, { saved }, { retained.toList() },
            nativeBeforeScope = before, nativeSentAcknowledgments = listOf(acks[1]), nativeHistoricalTargets = array(historical))
        assertEquals(true, completion.validator("begin", null))
        retained += acks[0]; completion.recordPersisted(acks[0])
        assertEquals(JsonPrimitive(1), completion.summary()["saved"]); assertNotEquals(true, completion.validator("finish", null))
        retained += acks[1]
        assertTrue(runCatching { completion.recordPersisted(acks[1]) }.isFailure)
        assertNotEquals(true, completion.validator("finish", null))
        completion.recordSuccessfulAcknowledgmentSend(acks[1]); completion.recordPersisted(acks[1])
        assertEquals(JsonPrimitive(2), completion.summary()["saved"]); assertEquals(true, completion.validator("finish", null))
    }
}
