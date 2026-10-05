package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.Serializable
import java.util.UUID
import java.time.YearMonth

/** Saved in the encrypted Bestand, including the running/paused interval. */
@Serializable
data class ZeiterfassungStand(
    val enabled: Boolean = false,
    val actor: String = "",
    val counter: Long = 0,
    val entries: List<Zeiteintrag> = emptyList(),
    /** Local suppression only: never transmit as an Organizer deletion. */
    val removedIds: Set<String> = emptySet(),
    val removedMonths: Set<String> = emptySet(),
    val trash: List<ZeitPapierkorb> = emptyList(),
    val reportName: String = "",
    val calendar: ZeitKalender = ZeitKalender(),
    val conflicts: Map<String, List<Zeiteintrag>> = emptyMap(),
    val wifi: ZeitWlanAutomatik = ZeitWlanAutomatik(),
    val fixedPauses: List<ZeitPausenfenster> = emptyList(),
    val pauseRuns: Map<String, ZeitPausenlauf> = emptyMap(),
    val endAlarm: ZeitFeierabendwecker = ZeitFeierabendwecker()
) {
    fun validate(): ZeiterfassungStand {
        require(reportName.length <= 240)
        calendar.validate()
        wifi.validate()
        endAlarm.validate()
        require(!endAlarm.fired)
        require(fixedPauses.size <= 16)
        fixedPauses.forEach { it.validate() }
        pauseRuns.forEach { (id, run) -> run.validate(entries.single { it.id == id }) }
        require(if (actor.isEmpty()) counter == 0L && entries.isEmpty()
            else UUID.fromString(actor).toString() == actor)
        require(counter in 0L..MAX_COUNTER)
        require(entries.map { it.id }.toSet().size == entries.size)
        require(removedIds.all { UUID.fromString(it).toString() == it })
        require(entries.none { it.id in removedIds })
        require(conflicts.size <= 10000)
        conflicts.forEach { (id, versions) ->
            require(entries.any { it.id == id } && id !in removedIds && versions.size in 1..16)
            versions.forEach { require(it.id == id); it.validate() }
        }
        removedMonths.forEach { require(YearMonth.parse(it).toString() == it) }
        require(trash.map { it.id }.toSet().size == trash.size)
        val trashed = mutableSetOf<String>()
        trash.forEach { item ->
            require(UUID.fromString(item.id).toString() == item.id && item.removedMs in 0L..253402300799999L)
            require(item.entries.isNotEmpty())
            item.month?.let { require(YearMonth.parse(it).toString() == it) }
            item.entries.forEach {
                it.validate()
                require(it.id in removedIds && trashed.add(it.id))
                require((it.clock[actor] ?: 0) <= counter)
                if (item.month != null) require(YearMonth.from(it.localStart()).toString() == item.month)
            }
            item.conflicts.forEach { (id, versions) ->
                require(item.entries.any { it.id == id } && versions.size in 1..16)
                versions.forEach { require(it.id == id); it.validate() }
            }
            item.pauseRuns.forEach { (id, run) -> run.validate(item.entries.single { it.id == id }) }
        }
        entries.forEach {
            it.validate()
            require((it.clock[actor] ?: 0) <= counter)
        }
        return this
    }

    /** A caller-supplied UUID is also the durable operation identity for retry. */
    fun start(entry: Zeiteintrag): ZeiterfassungStand {
        validate(); entry.validate()
        if (entry.id in removedIds || entries.any { it.id == entry.id }) return this
        check(enabled)
        check(entries.none { !it.deleted && it.endMinute == null })
        require(entry.endMinute == null && entry.pauseMinute == null && entry.pauseMinutes == 0L)
        require(!entry.deleted && entry.clock.isEmpty())
        return store(entry).copy(pauseRuns = pauseRuns + (entry.id to ZeitPausenlauf(
            fixed = fixedPauses.toList(), endAlarm = endAlarm))).validate()
    }

    fun projected(entry: Zeiteintrag, now: Long = Zeiteintrag.currentMinute()): Zeiteintrag =
        pauseRuns[entry.id]?.project(entry, now) ?: entry.pausePlan?.project(entry, now) ?: entry

    fun isPaused(entry: Zeiteintrag, now: Long = Zeiteintrag.currentMinute()): Boolean =
        entry.pauseMinute != null || (pauseRuns[entry.id]?.calculate(entry, now)
            ?: entry.pausePlan?.calculate(entry, now))?.activeFixed?.isNotEmpty() == true

    /** Persist a causal version when shared calculation data changes, never a rendered clock value. */
    fun prepareSharedPlans(nowMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        var state = this
        for (entry in entries) {
            val run = pauseRuns[entry.id] ?: continue
            val plan = run.sharedPlan()
            if (entry.pausePlan != plan) state = state.store(entry.copy(pausePlan = plan,
                modifiedMs = maxOf(entry.modifiedMs, nowMs)))
        }
        return state.validate()
    }

    /** Evaluation only persists newly observed replacements, never a per-minute clock tick. */
    fun evaluatePauses(now: Long = Zeiteintrag.currentMinute()): ZeiterfassungStand = copy(
        pauseRuns = pauseRuns.mapValues { (id, run) -> run.evaluated(entries.single { it.id == id }, now) }).validate()

    fun pause(expected: Zeiteintrag, nowMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        check(entries.firstOrNull { it.id == expected.id } == expected)
        if (expected.endMinute != null || expected.deleted) return this
        val now = nowMs / 60000
        if (isPaused(expected, now)) return this
        val run = pauseRuns[expected.id] ?: expected.pausePlan?.let { ZeitPausenlauf().follow(expected) }
            ?: return replace(expected, expected.pause(now, nowMs))
        val evaluated = run.evaluated(expected, now)
        val record = evaluated.project(expected, now).pause(now, nowMs)
        return store(record).copy(pauseRuns = pauseRuns + (record.id to evaluated.copy(
            alarm = ZeitPausenwecker(nowMs)))).evaluatePauses(now)
    }

    fun resume(expected: Zeiteintrag, nowMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        check(entries.firstOrNull { it.id == expected.id } == expected)
        if (expected.endMinute != null || expected.deleted) return this
        val now = nowMs / 60000
        val run = pauseRuns[expected.id] ?: expected.pausePlan?.let { ZeitPausenlauf().follow(expected) }
            ?: return replace(expected, expected.resume(now, nowMs))
        val evaluated = run.evaluated(expected, now)
        val result = evaluated.calculate(expected, now)
        if (expected.pauseMinute == null && result.activeFixed.isEmpty()) return this
        val nextRun = if (expected.pauseMinute != null) {
            require(now >= expected.pauseMinute)
            evaluated.copy(manual = evaluated.manual + ZeitManuellePause(expected.pauseMinute, now), alarm = null)
        } else evaluated.copy(fixedEnds = evaluated.fixedEnds + result.activeFixed.associate { it.first to now })
        val record = expected.copy(pauseMinute = null, pauseMinutes = result.minutes, modifiedMs = nowMs).validate()
        return store(record).copy(pauseRuns = pauseRuns + (record.id to nextRun)).validate()
    }

    fun finish(expected: Zeiteintrag, nowMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        check(entries.firstOrNull { it.id == expected.id } == expected)
        if (expected.endMinute != null || expected.deleted) return this
        val now = nowMs / 60000
        return store(projected(expected, now).finish(now, nowMs), nowMs)
    }

    fun claimEndAlarm(id: String, nowMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        val entry = entries.firstOrNull { it.id == id } ?: return this
        val run = pauseRuns[id] ?: return this
        val now = nowMs / 60000
        if (!run.endAlarm.due(projected(entry, now), now)) return this
        return if (run.endAlarm.autoStop) finish(entry, nowMs)
        else copy(pauseRuns = pauseRuns + (id to run.copy(endAlarm = run.endAlarm.copy(fired = true)))).validate()
    }

    fun startFromWifi(observedSsid: String, observedMs: Long, nowMs: Long, activity: String): ZeiterfassungStand {
        validate()
        if (!wifi.canStart(observedSsid, observedMs, nowMs, entries.any { !it.deleted && it.endMinute == null }, enabled)) return this
        return start(Zeiteintrag(startMinute = nowMs / 60000, modifiedMs = nowMs, type = activity))
    }

    /** Compare the complete edited snapshot to avoid overwriting a newer edit. */
    fun replace(expected: Zeiteintrag?, replacement: Zeiteintrag): ZeiterfassungStand {
        validate(); replacement.validate()
        check(replacement.id !in removedIds)
        val current = entries.firstOrNull { it.id == replacement.id }
        if (current?.sameContent(replacement) == true) return this
        check(current == expected)
        require(expected == null || expected.id == replacement.id)
        if (current == replacement) return this
        if (expected == null) {
            check(enabled)
            require(replacement.endMinute != null && !replacement.deleted && replacement.clock.isEmpty())
        } else {
            require(replacement.clock == expected.clock)
            // Reopening a finished record would bypass the single-running-entry guard.
            require(expected.endMinute == null || replacement.endMinute != null)
            require(!expected.deleted || replacement.deleted)
        }
        return store(replacement)
    }

    /** Keep local removals in encrypted trash for 30 days; never emit remote deletions. */
    fun removeLocal(expected: List<Zeiteintrag>, now: Long = System.currentTimeMillis(),
                    month: String? = null): ZeiterfassungStand {
        validate()
        require(expected.map { it.id }.toSet().size == expected.size)
        expected.forEach { old ->
            val current = entries.firstOrNull { it.id == old.id }
            check(current == old || current == null && old.id in removedIds)
        }
        val ids = expected.mapTo(mutableSetOf()) { it.id }
        val removed = entries.filter { it.id in ids }
        val clean = purgeExpired(now)
        if (removed.isEmpty()) return clean
        val archived = ZeitPapierkorb(removedMs = now, entries = removed, month = month,
            conflicts = conflicts.filterKeys { it in ids }, pauseRuns = pauseRuns.filterKeys { it in ids })
        return clean.copy(entries = entries.filterNot { it.id in ids }, removedIds = removedIds + ids,
            removedMonths = if (month == null) removedMonths else removedMonths + month,
            trash = clean.trash + archived,
            conflicts = conflicts - ids,
            pauseRuns = pauseRuns - ids,
            wifi = removed.filter { it.endMinute == null }.fold(wifi) { value, record ->
                value.afterStop(record.id, now, "remove:${archived.id}:${record.id}") }).validate()
    }

    fun purgeExpired(now: Long = System.currentTimeMillis()): ZeiterfassungStand =
        copy(trash = trash.filter { it.expiresMs > now })

    fun restoreLocal(id: String, now: Long = System.currentTimeMillis()): ZeiterfassungStand {
        validate()
        val item = trash.firstOrNull { it.id == id && it.expiresMs > now } ?: error("expired time trash")
        val ids = item.entries.mapTo(mutableSetOf()) { it.id }
        return purgeExpired(now).copy(entries = entries + item.entries, removedIds = removedIds - ids,
            removedMonths = if (item.month == null) removedMonths else removedMonths - item.month,
            trash = trash.filter { it.id != id && it.expiresMs > now }, conflicts = conflicts + item.conflicts,
            pauseRuns = pauseRuns + item.pauseRuns).validate()
    }

    fun permanentlyRemoveLocal(id: String): ZeiterfassungStand =
        copy(trash = trash.filterNot { it.id == id }).validate()

    fun suppressIncoming(entry: Zeiteintrag): Boolean = entry.id in removedIds ||
        YearMonth.from(entry.localStart()).toString() in removedMonths

    private fun store(entry: Zeiteintrag, stoppedMs: Long = System.currentTimeMillis()): ZeiterfassungStand {
        check(counter < MAX_COUNTER)
        val localActor = actor.ifEmpty { UUID.randomUUID().toString() }
        val next = counter + 1
        val stamped = entry.copy(clock = entry.clock + (localActor to next)).validate()
        val wasRunning = entries.any { it.id == entry.id && !it.deleted && it.endMinute == null }
        val old = entries.firstOrNull { it.id == entry.id }
        val keepRun = old != null && !entry.deleted && entry.endMinute == null && old.startMinute == entry.startMinute &&
            old.zone == entry.zone && old.pauseMinute == entry.pauseMinute && old.pauseMinutes == entry.pauseMinutes
        val priorRun = pauseRuns[entry.id]
        val updatedRuns = when {
            keepRun -> pauseRuns
            priorRun != null && !entry.deleted && entry.endMinute == null -> pauseRuns + (entry.id to ZeitPausenlauf(
                baseMinutes = entry.pauseMinutes, endAlarm = priorRun.endAlarm,
                alarm = priorRun.alarm?.takeIf { it.startedMs / 60000 == entry.pauseMinute }))
            else -> pauseRuns - entry.id
        }
        return copy(actor = localActor, counter = next,
            entries = entries.filterNot { it.id == entry.id } + stamped,
            pauseRuns = updatedRuns,
            removedMonths = removedMonths - YearMonth.from(entry.localStart()).toString(),
            wifi = if (wasRunning && entry.endMinute != null) wifi.afterStop(entry.id, stoppedMs, ZeitWlanAutomatik.stopEvent(stamped)) else wifi).validate()
    }

    companion object {
        private const val MAX_COUNTER = 9007199254740991L
    }
}
