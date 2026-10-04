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
    val calendar: ZeitKalender = ZeitKalender()
) {
    fun validate(): ZeiterfassungStand {
        require(reportName.length <= 240)
        calendar.validate()
        require(if (actor.isEmpty()) counter == 0L && entries.isEmpty()
            else UUID.fromString(actor).toString() == actor)
        require(counter in 0L..MAX_COUNTER)
        require(entries.map { it.id }.toSet().size == entries.size)
        require(removedIds.all { UUID.fromString(it).toString() == it })
        require(entries.none { it.id in removedIds })
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
        return store(entry)
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
        return clean.copy(entries = entries.filterNot { it.id in ids }, removedIds = removedIds + ids,
            removedMonths = if (month == null) removedMonths else removedMonths + month,
            trash = clean.trash + ZeitPapierkorb(removedMs = now, entries = removed, month = month)).validate()
    }

    fun purgeExpired(now: Long = System.currentTimeMillis()): ZeiterfassungStand =
        copy(trash = trash.filter { it.expiresMs > now })

    fun restoreLocal(id: String, now: Long = System.currentTimeMillis()): ZeiterfassungStand {
        validate()
        val item = trash.firstOrNull { it.id == id && it.expiresMs > now } ?: error("expired time trash")
        val ids = item.entries.mapTo(mutableSetOf()) { it.id }
        return purgeExpired(now).copy(entries = entries + item.entries, removedIds = removedIds - ids,
            removedMonths = if (item.month == null) removedMonths else removedMonths - item.month,
            trash = trash.filter { it.id != id && it.expiresMs > now }).validate()
    }

    fun permanentlyRemoveLocal(id: String): ZeiterfassungStand =
        copy(trash = trash.filterNot { it.id == id }).validate()

    fun suppressIncoming(entry: Zeiteintrag): Boolean = entry.id in removedIds ||
        YearMonth.from(entry.localStart()).toString() in removedMonths

    private fun store(entry: Zeiteintrag): ZeiterfassungStand {
        check(counter < MAX_COUNTER)
        val localActor = actor.ifEmpty { UUID.randomUUID().toString() }
        val next = counter + 1
        val stamped = entry.copy(clock = entry.clock + (localActor to next)).validate()
        return copy(actor = localActor, counter = next,
            entries = entries.filterNot { it.id == entry.id } + stamped,
            removedMonths = removedMonths - YearMonth.from(entry.localStart()).toString()).validate()
    }

    companion object {
        private const val MAX_COUNTER = 9007199254740991L
    }
}
