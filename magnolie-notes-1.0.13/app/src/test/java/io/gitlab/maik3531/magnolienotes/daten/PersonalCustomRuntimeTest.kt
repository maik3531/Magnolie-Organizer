package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.telefon.PersonalSyncProtokoll
import kotlinx.serialization.json.*
import java.io.File
import java.time.Instant
import java.util.TimeZone
import org.junit.Assert.*
import org.junit.Test

internal object CustomFixtures {
    val consent = Json.parseToJsonElement(File("../contracts/personal-custom-consent-v4-vectors.json").readText()).jsonObject
    val wire = Json.parseToJsonElement(File("../contracts/personal-custom-v4-vectors.json").readText()).jsonObject
    val batch = wire.getValue("batch").jsonObject
    val state = PersonalCustomState(owner = "fixture:public-key", generation = "fixture-generation", active = true,
        local = consent.getValue("local").jsonObject, remote = consent.getValue("remote").jsonObject)
    fun changed(transform: (MutableMap<String, JsonElement>) -> Unit): JsonObject {
        val record = batch.getValue("upserts").jsonArray.single().jsonObject.toMutableMap()
        val value = record.getValue("value").jsonObject.toMutableMap(); transform(value)
        record["value"] = JsonObject(value); record["hash"] = JsonPrimitive(PersonalSync.hash(JsonObject(value)))
        return JsonObject(batch + ("upserts" to JsonArray(listOf(JsonObject(record)))))
    }
    fun alarm(body: JsonObject, after: String): String? {
        val applied = PersonalCustom.apply(state, body)
        return PersonalCustom.nextAlarm(applied, applied.items.values.single(), Instant.parse(after).toEpochMilli())?.let { Instant.ofEpochMilli(it).toString() }
    }
}

class PersonalCustomRuntimeTest {
    @Test fun exactWireAndUnfilteredReadOnlyMirror() {
        val body = CustomFixtures.batch
        PersonalSyncProtokoll.validateCustomBody("personal_sync.custom_batch", body)
        val state = PersonalCustom.apply(CustomFixtures.state, body)
        assertEquals(state, PersonalCustom.apply(state, body))
        val serialized = Json.encodeToString(PersonalCustomState.serializer(), state)
        assertEquals(state, Json.decodeFromString(PersonalCustomState.serializer(), serialized))
        assertEquals(1, state.items.size)
        val ordinary = Bestand(personalCustom = state)
        assertTrue(ordinary.aufgaben.isEmpty()); assertTrue(ordinary.notizen.isEmpty())
        assertThrows(IllegalStateException::class.java) { PersonalCustom.apply(PersonalCustomState(), body) }
        val unrelated = body.getValue("upserts").jsonArray.single().jsonObject.toMutableMap()
        unrelated["textItemId"] = JsonPrimitive("private-text")
        assertThrows(Exception::class.java) { PersonalSyncProtokoll.validateCustomBody("personal_sync.custom_batch",
            JsonObject(body + ("upserts" to JsonArray(listOf(JsonObject(unrelated)))))) }
    }

    @Test fun withdrawalRetainsCopiesAndOffOnCannotReviveOldBatch() {
        val state = PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch)
        val off = state.copy(local = CustomFixtures.consent.getValue("revoked").jsonObject)
        assertEquals(state.items, off.items)
        assertNull(PersonalCustom.nextAlarm(off, off.items.values.single(), 0))
        assertThrows(IllegalStateException::class.java) { PersonalCustom.apply(off, CustomFixtures.batch) }
        val on = off.copy(local = CustomFixtures.consent.getValue("reenabled").jsonObject)
        assertThrows(IllegalStateException::class.java) { PersonalCustom.apply(on, CustomFixtures.batch) }
        val unpaired = PersonalCustomState(items = state.items)
        assertNull(PersonalCustom.nextAlarm(unpaired, state.items.values.single(), 0))
        val other = PersonalCustom.bind(unpaired, "other:public-key").copy(active = true,
            local = CustomFixtures.state.local, remote = CustomFixtures.state.remote)
        assertThrows(IllegalStateException::class.java) { PersonalCustom.apply(other, CustomFixtures.batch) }
    }

    @Test fun explicitDeletionRequiresConfirmationAndCannotDeleteDesktop() {
        val state = PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch)
        val pending = PersonalCustom.apply(state, CustomFixtures.wire.getValue("deletion").jsonObject)
        val id = state.items.keys.single()
        assertEquals("pending", pending.items.getValue(id).status)
        assertNotNull(pending.items.getValue(id).record["value"])
        val kept = PersonalCustom.decide(pending, id, 2, false)
        assertEquals("kept", kept.items.getValue(id).status)
        val replay = JsonObject(CustomFixtures.wire.getValue("deletion").jsonObject + ("revision" to JsonPrimitive(3)))
        assertEquals("kept", PersonalCustom.apply(kept, replay).items.getValue(id).status)
        val deleted = PersonalCustom.decide(pending, id, 2, true)
        assertEquals("deleted", deleted.items.getValue(id).status)
        assertNull(deleted.items.getValue(id).record["value"])
        assertEquals(deleted, PersonalCustom.apply(deleted, CustomFixtures.batch))
        assertThrows(IllegalStateException::class.java) { PersonalCustom.decide(pending, id, 1, true) }
    }

    @Test fun unknownDeletionFencesDelayedUpsertsAcrossRestore() {
        val deletion = CustomFixtures.wire.getValue("deletion").jsonObject
        val received = PersonalCustom.apply(CustomFixtures.state, deletion)
        assertTrue(received.items.isEmpty())
        assertEquals(received, PersonalCustom.apply(received, CustomFixtures.batch))
        val restored = PersonalCustom.restore(received, CustomFixtures.state)
        assertTrue(PersonalCustom.apply(restored, CustomFixtures.batch).items.isEmpty())
        val newer = JsonObject(CustomFixtures.batch + ("revision" to JsonPrimitive(3)))
        val live = PersonalCustom.apply(received, newer)
        assertEquals(1, live.items.size)
        assertThrows(IllegalStateException::class.java) { PersonalCustom.apply(live, deletion) }
    }

    @Test fun restoreCannotLoseAcknowledgedDeletionOrRewindKeepDelete() {
        val on = PersonalCustom.apply(CustomFixtures.state, CustomFixtures.batch)
        val pending = PersonalCustom.apply(on, CustomFixtures.wire.getValue("deletion").jsonObject)
        val id = pending.items.keys.single()
        for (live in listOf(pending, PersonalCustom.decide(pending, id, 2, false), PersonalCustom.decide(pending, id, 2, true))) {
            for (archive in listOf(on, CustomFixtures.state)) {
                val restored = PersonalCustom.restore(live, archive)
                assertEquals(live.items.getValue(id), restored.items.getValue(id))
                assertEquals(live.local, restored.local)
                assertNull(PersonalCustom.nextAlarm(restored, restored.items.getValue(id), 0))
                assertEquals(restored, PersonalCustom.apply(restored, CustomFixtures.batch))
            }
        }
    }

    @Test fun parsedCanonicalEdgesNeverReplaceInvalidUnicode() {
        assertEquals("{\"n\":0,\"ordinal\":-1}", PersonalSync.canonical(Json.parseToJsonElement("{\"n\":-0,\"ordinal\":-1}")).decodeToString())
        assertEquals(CustomFixtures.wire.getValue("canonical").jsonPrimitive.content, PersonalSync.canonical(CustomFixtures.batch).decodeToString())
        for (raw in listOf("\"\\ud800\"", "{\"\\udfff\":1}", "0.5", "1e0"))
            assertThrows(Exception::class.java) { PersonalSync.canonical(Json.parseToJsonElement(raw)) }
        assertEquals("\"\ud83d\ude00\"", PersonalSync.canonical(Json.parseToJsonElement("\"\\ud83d\\ude00\"")).decodeToString())
    }

    @Test fun recurrenceMatchesDesktopClampingAndFutureAlarmVectors() {
        for (raw in CustomFixtures.wire.getValue("alarms").jsonArray) {
            assertEquals(raw.jsonObject.getValue("expected").jsonPrimitive.content,
                CustomFixtures.alarm(CustomFixtures.batch, raw.jsonObject.getValue("after").jsonPrimitive.content))
        }
        val yearly = CustomFixtures.changed { value ->
            value["date"] = JsonPrimitive("2028-02-29")
            value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + ("frequency" to JsonPrimitive("yearly")))
        }
        assertEquals("2029-02-28T07:45:00Z", CustomFixtures.alarm(yearly, "2028-03-01T00:00:00Z"))
        val custom = CustomFixtures.changed { value ->
            value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + mapOf(
                "frequency" to JsonPrimitive("custom"), "dates" to JsonArray(listOf(JsonPrimitive("2028-02-05"), JsonPrimitive("2028-02-10")))))
        }
        assertEquals("2028-01-31T07:45:00Z", CustomFixtures.alarm(custom, "2028-01-01T00:00:00Z"))
        assertEquals("2028-02-05T07:45:00Z", CustomFixtures.alarm(custom, "2028-02-01T00:00:00Z"))
        val ordinal = CustomFixtures.changed { value ->
            value["date"] = JsonPrimitive("2028-01-01")
            value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + mapOf("ordinal" to JsonPrimitive(-1), "weekday" to JsonPrimitive(1)))
        }
        assertEquals("2028-01-31T07:45:00Z", CustomFixtures.alarm(ordinal, "2028-01-02T00:00:00Z"))
    }

    @Test fun sourceTimezoneGapOverlapAndDeviceTimezoneChanges() {
        fun daily(date: String) = CustomFixtures.changed { value ->
            value["date"] = JsonPrimitive(date); value["time"] = JsonPrimitive("02:30"); value["lead_minutes"] = JsonPrimitive(0)
            value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + ("frequency" to JsonPrimitive("daily")))
        }
        val saved = TimeZone.getDefault()
        try {
            for (zone in listOf("UTC", "Asia/Tokyo", "America/New_York")) {
                TimeZone.setDefault(TimeZone.getTimeZone(zone))
                assertEquals("2028-03-26T01:30:00Z", CustomFixtures.alarm(daily("2028-03-26"), "2028-03-25T00:00:00Z"))
                assertEquals("2028-10-29T00:30:00Z", CustomFixtures.alarm(daily("2028-10-29"), "2028-10-28T00:00:00Z"))
            }
        } finally { TimeZone.setDefault(saved) }
        for (flag in listOf("module_reminders", "item_reminder"))
            assertNull(CustomFixtures.alarm(CustomFixtures.changed { it[flag] = JsonPrimitive(false) }, "2028-01-01T00:00:00Z"))
    }

    @Test fun taskCompletionDefaultTimeAndReminderChoicesArePreserved() {
        val base = CustomFixtures.changed { value ->
            value["date"] = JsonPrimitive("2028-02-01"); value["time"] = JsonPrimitive("")
            value["lead_minutes"] = JsonPrimitive(0)
            value["recurrence"] = JsonObject(value.getValue("recurrence").jsonObject + ("frequency" to JsonPrimitive("none")))
        }
        val record = base.getValue("upserts").jsonArray.single().jsonObject
        val body = JsonObject(base + ("upserts" to JsonArray(listOf(JsonObject(record + ("kind" to JsonPrimitive("task")))))))
        assertEquals("2028-02-01T07:00:00Z", CustomFixtures.alarm(body, "2028-01-01T00:00:00Z"))
        val doneValue = JsonObject(record.getValue("value").jsonObject + ("completed" to JsonPrimitive(true)))
        val done = JsonObject(record + mapOf("kind" to JsonPrimitive("task"), "value" to doneValue, "hash" to JsonPrimitive(PersonalSync.hash(doneValue))))
        assertNull(CustomFixtures.alarm(JsonObject(body + ("upserts" to JsonArray(listOf(done)))), "2028-01-01T00:00:00Z"))
    }
}
