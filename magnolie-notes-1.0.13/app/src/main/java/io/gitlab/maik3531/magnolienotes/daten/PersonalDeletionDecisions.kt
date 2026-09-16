package io.gitlab.maik3531.magnolienotes.daten

import kotlin.math.floor

enum class PersonalDeletionPrompt { NORMAL, REMEMBERED, CONFLICT, BLOCKED }

/** Run-scoped, deliberately volatile deletion consent. */
class PersonalDeletionDecisions {
    private var rememberedRun = ""
    private var rememberedDecision = ""

    fun remember(runId: String, decision: String) {
        require(runId.isNotBlank() && decision in setOf("delete", "restore"))
        rememberedRun = runId
        rememberedDecision = decision
    }

    fun resolveRun(runId: String) {
        if (rememberedRun == runId) {
            rememberedRun = ""
            rememberedDecision = ""
        }
    }

    fun remembered(runId: String): String? =
        rememberedDecision.takeIf { rememberedRun == runId && it.isNotBlank() }

    fun prompt(input: Bestand, proposal: PersonalDeletionProposal): PersonalDeletionPrompt {
        if (proposal.kind == "notebook" && input.notizen.any { it.notizbuchId == proposal.id })
            return PersonalDeletionPrompt.BLOCKED
        val key = if (proposal.kind == "attachment")
            "attachment\u0000${proposal.parent_id}\u0000${proposal.id}" else "${proposal.kind}\u0000${proposal.id}"
        val meta = input.personalSync.entities[key]
        val unchanged = meta != null && meta.state == "live" && meta.hash == proposal.prior_hash &&
            PersonalSync.matchesCurrent(input, proposal) &&
            runCatching { PersonalSync.compare(meta.clock, proposal.clock) == "dominated" }.getOrDefault(false)
        if (!unchanged) return PersonalDeletionPrompt.CONFLICT
        return if (remembered(proposal.run_id) != null) PersonalDeletionPrompt.REMEMBERED
        else PersonalDeletionPrompt.NORMAL
    }

    fun threshold(syncedLive: Int): Int = minOf(10, maxOf(1, floor(syncedLive * 0.1).toInt()))

    fun needsMassConfirmation(count: Int, syncedLive: Int): Boolean = count > threshold(syncedLive)

    fun typeCounts(proposals: List<PersonalDeletionProposal>): Map<String, Int> =
        listOf("note", "notebook", "task", "attachment").associateWith { kind ->
            proposals.count { it.kind == kind }
        }
}
