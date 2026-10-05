package io.gitlab.maik3531.magnolienotes.daten

/** Causal merge only; callers must authenticate and authorize the current peer. */
object ZeiterfassungAbgleich {
    fun dominates(left: Map<String, Long>, right: Map<String, Long>): Boolean =
        right.all { (actor, counter) -> (left[actor] ?: 0) >= counter }

    fun clock(left: Map<String, Long>, right: Map<String, Long>): Map<String, Long> =
        (left.keys + right.keys).associateWith { maxOf(left[it] ?: 0, right[it] ?: 0) }

    data class Ergebnis(val state: ZeiterfassungStand, val outcomes: Map<String, String>)

    fun merge(state: ZeiterfassungStand, incoming: List<Zeiteintrag>, fromOrganizer: Boolean = false,
              nowMs: Long = System.currentTimeMillis()): Ergebnis {
        state.validate()
        require(incoming.size <= 32 && incoming.map { it.id }.distinct().size == incoming.size)
        incoming.forEach { it.validate(); require(it.clock.isNotEmpty() && (!it.deleted || fromOrganizer)) }
        if (incoming.isEmpty()) return Ergebnis(state, emptyMap())
        val records = state.entries.associateBy { it.id }.toMutableMap()
        val conflicts = state.conflicts.toMutableMap()
        val outcomes = linkedMapOf<String, String>()
        val actor = state.actor.ifEmpty { java.util.UUID.randomUUID().toString() }
        var counter = state.counter
        for (remote in incoming) {
            counter = maxOf(counter, remote.clock[actor] ?: 0)
            if (state.suppressIncoming(remote)) {
                outcomes[remote.id] = "locally_removed"
                continue
            }
            val local = records[remote.id]
            if (local == null) {
                records[remote.id] = remote
                outcomes[remote.id] = "applied"
            } else if (local.sameContent(remote)) {
                records[remote.id] = local.copy(clock = clock(local.clock, remote.clock),
                    modifiedMs = maxOf(local.modifiedMs, remote.modifiedMs)).validate()
                outcomes[remote.id] = "same_content"
            } else if (dominates(local.clock, remote.clock) && local.clock != remote.clock) {
                outcomes[remote.id] = "older"
            } else if (dominates(remote.clock, local.clock) && local.clock != remote.clock) {
                records[remote.id] = remote
                outcomes[remote.id] = "applied"
            } else {
                val versions = conflicts[remote.id].orEmpty()
                if (versions.none { it.clock == remote.clock && it.sameContent(remote) }) {
                    check(versions.size < 16)
                    conflicts[remote.id] = versions + remote
                }
                outcomes[remote.id] = "conflict"
            }
        }
        for ((id, versions) in conflicts.toMap()) {
            val local = records.getValue(id)
            val remaining = versions.filterNot { value -> dominates(local.clock, value.clock) &&
                (local.clock != value.clock || local.sameContent(value)) }
            if (remaining.isEmpty()) conflicts.remove(id) else conflicts[id] = remaining
        }
        val wifi = state.entries.filter { !it.deleted && it.endMinute == null }.fold(state.wifi) { value, before ->
            val after = records.getValue(before.id)
            if (after.deleted || after.endMinute != null) value.afterStop(after.id, nowMs, ZeitWlanAutomatik.stopEvent(after)) else value
        }
        return Ergebnis(state.copy(actor = actor, counter = counter, entries = records.values.toList(), conflicts = conflicts, wifi = wifi,
            pauseRuns = state.pauseRuns.mapNotNull { (id, run) ->
                val before = state.entries.single { it.id == id }
                val after = records.getValue(id)
                (if (before.sameContent(after)) run else run.follow(after))?.let { id to it }
            }.toMap()
        ).validate(), outcomes)
    }

    fun resolve(state: ZeiterfassungStand, id: String, selected: Zeiteintrag,
                expected: List<Zeiteintrag>, expectedLocal: Zeiteintrag,
                nowMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        state.validate()
        val local = state.entries.single { it.id == id }
        val versions = state.conflicts[id].orEmpty()
        check(local == expectedLocal && versions == expected && versions.isNotEmpty())
        require(selected in versions + local && selected.id == id)
        val merged = versions.fold(local.clock) { value, record -> clock(value, record.clock) }
        val counter = maxOf(state.counter, merged[state.actor] ?: 0)
        check(state.actor.isNotEmpty() && counter < 9007199254740991L)
        val record = selected.copy(clock = merged + (state.actor to counter + 1),
            modifiedMs = nowMs).validate()
        return state.copy(counter = counter + 1, entries = state.entries.map { if (it.id == id) record else it },
            conflicts = state.conflicts - id,
            wifi = if (!local.deleted && local.endMinute == null && (record.deleted || record.endMinute != null))
                state.wifi.afterStop(id, nowMs, ZeitWlanAutomatik.stopEvent(record)) else state.wifi,
            pauseRuns = state.pauseRuns[id]?.let { run ->
                val next = if (local.sameContent(record)) run else run.follow(record)
                if (next == null) state.pauseRuns - id else state.pauseRuns + (id to next)
            } ?: state.pauseRuns).validate()
    }
}
