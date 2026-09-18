package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.telefon.PersonalSyncProtokoll
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*
import java.time.*
import java.time.temporal.ChronoUnit
import java.time.temporal.TemporalAdjusters

@Serializable
data class PersonalCustomState(
    val owner: String = "", val generation: String = "",
    val local: JsonObject? = null, val remote: JsonObject? = null,
    val active: Boolean = false, val items: Map<String, PersonalCustomMirror> = emptyMap(),
    val firedHighWater: Map<String, Long> = emptyMap(),
    val revisionHighWater: Map<String, Long> = emptyMap()
)

@Serializable
data class PersonalCustomMirror(
    val owner: String, val generation: String, val source: String, val revision: Long,
    val record: JsonObject, val status: String = "live", val deletion: JsonObject? = null,
    val firedMs: Long = 0
)

/** One-way custom mirror. The ordinary task/calendar collections are never touched. */
object PersonalCustom {
    /** Archive copies carry content/provenance, never a grant or an active generation. */
    fun restore(live: PersonalCustomState, archived: PersonalCustomState): PersonalCustomState {
        val fired = live.firedHighWater.toMutableMap()
        val revisions = live.revisionHighWater.toMutableMap()
        for ((id, item) in live.items) {
            fired[id] = maxOf(fired[id] ?: 0, item.firedMs)
            if (item.owner == live.owner && item.generation == live.generation)
                revisions[id] = maxOf(revisions[id] ?: 0, item.revision)
        }
        val items = archived.items.mapValues { (id, item) ->
            item.copy(generation = "", revision = 0, deletion = null,
                status = if (item.status == "pending") "kept" else item.status,
                firedMs = fired[id] ?: 0)
        }.toMutableMap()
        // Accepted source deletions may already be retired by the sender. Content
        // restore must not rewind their pending review or the live local decision.
        for ((id, item) in live.items) if (item.status in setOf("pending", "kept", "deleted")) items[id] = item
        return live.copy(firedHighWater = fired, revisionHighWater = revisions, items = items)
    }

    fun bind(state: PersonalCustomState, owner: String): PersonalCustomState =
        if (state.owner == owner) state else PersonalCustomState(owner = owner,
            generation = java.util.UUID.randomUUID().toString(), items = state.items, firedHighWater = state.firedHighWater)

    fun apply(state: PersonalCustomState, body: JsonObject): PersonalCustomState {
        PersonalSyncProtokoll.validateCustomBody("personal_sync.custom_batch", body)
        check(state.owner.isNotEmpty() && state.active && PersonalSyncProtokoll.customScopeAllowed(
            state.local, state.remote, listOf(4), listOf(4), true, true,
            body.getValue("sender_epoch").jsonPrimitive.content, body.getValue("receiver_epoch").jsonPrimitive.content,
            body.getValue("sender_revision").jsonPrimitive.long, body.getValue("receiver_revision").jsonPrimitive.long))
        val source = body.getValue("source_id").jsonPrimitive.content
        val revision = body.getValue("revision").jsonPrimitive.long
        val items = state.items.toMutableMap()
        val revisions = state.revisionHighWater.toMutableMap()
        for (raw in body.getValue("upserts").jsonArray) {
            val record = raw.jsonObject; val id = record.getValue("id").jsonPrimitive.content
            val previous = items[id]
            check(previous == null || previous.owner == state.owner && previous.source == source && previous.record["item_id"] == record["item_id"])
            if ((previous == null || previous.generation != state.generation) &&
                revision <= (state.revisionHighWater[id] ?: 0)) continue
            if (previous != null && previous.generation == state.generation) {
                if (previous.revision > revision) continue
                if (previous.revision == revision) { check(previous.record == record && previous.status == "live"); continue }
            }
            items[id] = PersonalCustomMirror(state.owner, state.generation, source, revision, record,
                firedMs = maxOf(previous?.firedMs ?: 0, state.firedHighWater[id] ?: 0))
        }
        for (raw in body.getValue("deletions").jsonArray) {
            val deletion = raw.jsonObject; val id = deletion.getValue("id").jsonPrimitive.content
            val previous = items[id]
            if (previous == null) {
                // An ACK for an unknown deletion must fence delayed older upserts too.
                revisions[id] = maxOf(revisions[id] ?: 0, revision)
                continue
            }
            check(previous.source == source && previous.record["item_id"] == deletion["item_id"])
            // A successful receipt must not retire a deletion while a newer live mirror remains.
            check(previous.revision <= revision || previous.status != "live")
            if (previous.owner != state.owner || previous.revision > revision ||
                previous.generation != state.generation && revision <= (state.revisionHighWater[id] ?: 0)) continue
            if (previous.revision == revision) { check(previous.deletion == deletion); continue }
            // Hash differences remain visible for explicit review; no copy is deleted here.
            items[id] = previous.copy(generation = state.generation, revision = revision,
                status = if (previous.deletion == deletion && previous.status != "live") previous.status else "pending", deletion = deletion)
        }
        return state.copy(items = items, revisionHighWater = revisions)
    }

    fun decide(state: PersonalCustomState, id: String, revision: Long, delete: Boolean): PersonalCustomState {
        val item = state.items[id] ?: return state
        check(state.active && state.local?.get("enabled")?.jsonPrimitive?.booleanOrNull == true &&
            state.remote?.get("enabled")?.jsonPrimitive?.booleanOrNull == true &&
            item.owner == state.owner && item.generation == state.generation && item.status == "pending" && item.revision == revision)
        return state.copy(items = state.items + (id to item.copy(status = if (delete) "deleted" else "kept",
            record = if (delete) JsonObject(item.record.filterKeys { it != "value" }) else item.record)))
    }

    fun remindersAllowed(state: PersonalCustomState, item: PersonalCustomMirror): Boolean {
        if (runCatching {
            PersonalSyncProtokoll.validateCustomSettings(state.local ?: return false)
            PersonalSyncProtokoll.validateCustomSettings(state.remote ?: return false)
        }.isFailure) return false
        if (!state.active || state.owner != item.owner || state.generation != item.generation || item.status != "live" ||
            state.local?.get("enabled")?.jsonPrimitive?.booleanOrNull != true ||
            state.remote?.get("enabled")?.jsonPrimitive?.booleanOrNull != true) return false
        val value = item.record.getValue("value").jsonObject
        return value.getValue("module_reminders").jsonPrimitive.boolean && value.getValue("item_reminder").jsonPrimitive.boolean &&
            !value.getValue("completed").jsonPrimitive.boolean && value.getValue("date").jsonPrimitive.content.isNotEmpty()
    }

    fun nextAlarm(state: PersonalCustomState, item: PersonalCustomMirror, afterMs: Long): Long? {
        if (!remindersAllowed(state, item)) return null
        val value = item.record.getValue("value").jsonObject
        val start = LocalDate.parse(value.getValue("date").jsonPrimitive.content)
        val zone = PersonalSyncProtokoll.customZone(value.getValue("timezone").jsonPrimitive.content)
        val time = value.getValue("time").jsonPrimitive.content.let {
            if (it.isEmpty()) LocalTime.ofSecondOfDay(value.getValue("default_minute").jsonPrimitive.long * 60) else LocalTime.parse(it) }
        val lead = value.getValue("lead_minutes").jsonPrimitive.long
        val recurrence = value.getValue("recurrence").jsonObject
        val frequency = recurrence.getValue("frequency").jsonPrimitive.content
        val interval = recurrence.getValue("interval").jsonPrimitive.long
        val until = recurrence.getValue("until").jsonPrimitive.content.let { if (it.isEmpty()) LocalDate.of(9999, 12, 31) else LocalDate.parse(it) }
        val after = maxOf(afterMs, item.firedMs)
        fun alarm(day: LocalDate): Long? {
            if (day < start || day != start && day > until) return null
            // java.time shifts nonexistent local times forward and chooses the earlier overlap offset.
            val ms = day.atTime(time).atZone(zone).minusMinutes(lead).toInstant().toEpochMilli()
            return ms.takeIf { it > after }
        }
        if (frequency == "none") return alarm(start)
        alarm(start)?.let { return it }
        if (frequency == "custom") return recurrence.getValue("dates").jsonArray
            .mapNotNull { alarm(LocalDate.parse(it.jsonPrimitive.content)) }.minOrNull()
        val threshold = Instant.ofEpochMilli(after).atZone(zone).plusMinutes(lead).toLocalDate()
        val unit = when (frequency) { "daily" -> ChronoUnit.DAYS; "weekly" -> ChronoUnit.WEEKS; "monthly" -> ChronoUnit.MONTHS; else -> ChronoUnit.YEARS }
        var index = maxOf(0, unit.between(start, threshold) / interval - 1)
        val ordinal = recurrence.getValue("ordinal").jsonPrimitive.int
        val weekday = recurrence.getValue("weekday").jsonPrimitive.int
        // Calendar cycles repeat within 400 years, including leap-day and ordinal cases.
        repeat(4802) {
            val day = try {
                when (frequency) {
                    "daily" -> start.plusDays(index * interval)
                    "weekly" -> start.plusWeeks(index * interval)
                    "monthly" -> {
                        val month = YearMonth.from(start).plusMonths(index * interval)
                        if (ordinal != 0) month.atDay(1).with(TemporalAdjusters.dayOfWeekInMonth(ordinal, DayOfWeek.of(weekday)))
                        else month.atDay(minOf(start.dayOfMonth, month.lengthOfMonth()))
                    }
                    else -> {
                        val year = Math.toIntExact(start.year + index * interval)
                        LocalDate.of(year, start.month, minOf(start.dayOfMonth, YearMonth.of(year, start.month).lengthOfMonth()))
                    }
                }
            } catch (_: DateTimeException) { return null } catch (_: ArithmeticException) { return null }
            index++
            if (day != null) {
                if (day > until) return null
                alarm(day)?.let { return it }
            }
        }
        return null
    }
}
