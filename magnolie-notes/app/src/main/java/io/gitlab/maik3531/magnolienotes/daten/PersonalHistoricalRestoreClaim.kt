package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import java.util.UUID

/** Native-only prepared local restore. Not serializable, not wire/data authority.
 * The service must bind authenticated origin and explicit choices, retire data
 * ownership before the writer, and issue the terminal saved-live-delta handoff
 * only after the actual writer acknowledgement. Never retain this book claim. */
internal class PersonalHistoricalRestoreClaim private constructor(
    val beforeBook: Bestand,
    val beforeSavedBook: JsonObject,
    val afterBook: Bestand,
    val beforeLive: PersonalContentSelection,
    val afterLive: PersonalContentSelection,
    val batchKey: String
) {
    companion object {
        fun prepare(peerId: String, runId: String, book: Bestand, saved: JsonObject,
            dataSelection: PersonalContentSelection, proposals: List<PersonalDeletionProposal>,
            choices: List<AppliedPersonalDecision>): PersonalHistoricalRestoreClaim {
            fun uuid(value: String) = runCatching { UUID.fromString(value).let { it.version() == 4 && it.toString() == value } }.getOrDefault(false)
            require(uuid(peerId) && uuid(runId) && uuid(book.personalSync.actor_id) && proposals.size in 1..256 && proposals.size == choices.size)
            val beforeLive = PersonalSync.livePersonalContent(book)
            check(beforeLive == dataSelection) { "actor_source_changed" }
            check(proposals.map { it.proposal_id }.distinct().size == proposals.size &&
                proposals.map { it.kind to it.id }.distinct().size == proposals.size &&
                choices.map { it.proposal_id }.toSet() == proposals.map { it.proposal_id }.toSet() &&
                choices.map { it.decision_id }.distinct().size == choices.size &&
                choices.all { uuid(it.decision_id) && it.decision == "restore" &&
                    book.personalSync.applied_decision_proofs.none { old -> old.decision_id == it.decision_id } }) {
                "actor_historical_restore_review_required"
            }
            check(book.personalSync.pending_decisions.size + choices.size <= 500) { "actor_capacity" }
            val byId = proposals.associateBy { it.proposal_id }
            check(choices.all { it.expected_clock == byId.getValue(it.proposal_id).clock }) { "actor_decision_clock_changed" }
            val trashIds = mutableSetOf<String>(); val restoredNotes = mutableSetOf<String>(); val restoredTasks = mutableSetOf<String>()
            val targetKeys = mutableSetOf<String>()
            for (proposal in proposals) {
                require(uuid(proposal.proposal_id) && proposal.run_id == runId && proposal.source_device == peerId)
                // Notes' current data owner contains every live own entry. The
                // first historical save lane therefore restores only absent
                // own notes/tasks; it does not invent offscope LIVE/child rights.
                check(proposal.kind in setOf("note", "task") && proposal.parent_id.isEmpty() &&
                    proposal.id !in (if (proposal.kind == "note") beforeLive.notes else beforeLive.tasks)) { "actor_historical_target_is_data_member" }
                val key = proposal.kind + "\u0000" + proposal.id
                val meta = checkNotNull(book.personalSync.entities[key]) { "actor_target_pending_native_proof_missing" }
                check(book.personalSync.peer_device_id == peerId && meta.peer_device_id == peerId && meta.state == "deleted" &&
                    meta.status == "local_pending" && meta.hash.isEmpty() && !meta.conflict && meta.parent_id.isEmpty() &&
                    Regex("[a-f0-9]{64}").matches(meta.prior_hash) &&
                    meta.proposal_id == PersonalSync.proposalId(peerId, proposal.kind, proposal.id, "", meta.clock, meta.prior_hash)) {
                    "actor_target_pending_native_proof_missing"
                }
                check(meta.clock == proposal.clock && meta.prior_hash == proposal.prior_hash) { "actor_historical_conflict_not_ready" }
                val sources = book.papierkorb.filter { item -> item.art == proposal.kind && when (proposal.kind) {
                    "note" -> item.notiz?.let { PersonalSync.noteWireId(book.personalSync, it.id) == proposal.id } == true
                    else -> item.aufgabe?.id == proposal.id
                } }
                val source = checkNotNull(sources.singleOrNull()) { "restore_unavailable" }
                check(if (proposal.kind == "note") PersonalSync.ownNote(requireNotNull(source.notiz)) else PersonalSync.ownTask(requireNotNull(source.aufgabe))) {
                    "restore_unavailable"
                }
                check(PersonalSync.historicalRestoreSourceHash(book, source, proposal.id) == meta.prior_hash) { "restore_unavailable" }
                if (proposal.kind == "note") {
                    check(book.personalSync.entities.none { (entity, value) -> entity.startsWith("attachment\u0000${proposal.id}\u0000") && value.state == "deleted" }) {
                        "actor_historical_child_review_required"
                    }
                    restoredNotes += requireNotNull(source.notiz).id
                } else restoredTasks += requireNotNull(source.aufgabe).id
                trashIds += source.id; targetKeys += key
            }
            val (prepared, result) = PersonalSync.prepareActorDeletion(book, peerId, runId, proposals, choices, emptyList())
            check(result == "applied") { result }
            val afterLive = PersonalSync.livePersonalContent(prepared)
            val addedNotes = proposals.filter { it.kind == "note" }.map { it.id }.toSet()
            val addedTasks = proposals.filter { it.kind == "task" }.map { it.id }.toSet()
            check(afterLive == PersonalContentSelection(beforeLive.notes + addedNotes, beforeLive.tasks + addedTasks)) { "actor_historical_live_delta_changed" }
            check(prepared.notizen.filterNot { it.id in restoredNotes } == book.notizen &&
                prepared.aufgaben.filterNot { it.id in restoredTasks } == book.aufgaben &&
                prepared.papierkorb == book.papierkorb.filterNot { it.id in trashIds } &&
                prepared.copy(notizen = book.notizen, aufgaben = book.aufgaben, papierkorb = book.papierkorb, personalSync = book.personalSync) == book &&
                prepared.personalSync.entities.filterKeys { it !in targetKeys } == book.personalSync.entities.filterKeys { it !in targetKeys } &&
                prepared.personalSync.copy(counter = book.personalSync.counter, entities = book.personalSync.entities,
                    restoration_requests = book.personalSync.restoration_requests, pending_proposals = book.personalSync.pending_proposals,
                    applied_decisions = book.personalSync.applied_decisions, applied_decision_proofs = book.personalSync.applied_decision_proofs,
                    pending_decisions = book.personalSync.pending_decisions) == book.personalSync) {
                "actor_historical_non_target_changed"
            }
            val batchKey = "$peerId:$runId:historical-target-restore"
            check(batchKey !in book.personalSync.applied_batches) { "actor_historical_save_replayed" }
            val durable = prepared.copy(personalSync = prepared.personalSync.copy(
                applied_batches = (prepared.personalSync.applied_batches + batchKey).takeLast(500)))
            return PersonalHistoricalRestoreClaim(book, Json.parseToJsonElement(saved.toString()) as JsonObject,
                durable, beforeLive, afterLive, batchKey)
        }
    }
}
