package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PhoneContentScopeTest {
    private fun record(kind: String, id: String, text: String = "", notebook: String = "") = buildJsonObject {
        put("kind", kind); put("id", id); put("state", "live")
        put("value", buildJsonObject { put("text", text); put("notebook_id", notebook) })
    }
    @Test fun portableIdentityOrderAndHashMatchPythonGolden() {
        val manifest = PhoneContentScope.create(listOf("mobile-note", "\ue000", "😀"), listOf("mobile-task"), 7, "44444444-4444-4444-8444-444444444444")
        assertEquals("589f36e8c7d673b4e24e3bebc8a020441d9e313a465f2f8f011b9cebb596fdc2", manifest.getValue("scope_hash").jsonPrimitive.content)
        assertEquals(manifest, PhoneContentScope.assemble(PhoneContentScope.chunks(manifest)))
    }
    @Test fun existingPhoneNotesAndTasksReceiveUpdatesWithoutUnrelatedOrganizerContent() {
        val manifest = PhoneContentScope.create(listOf("mobile-note"), listOf("mobile-task"))
        val records = listOf(record("note", "mobile-note", "Organizer addition", "shared-book"),
            record("note", "organizer-only", "Private organizer text", "private-book"), record("task", "mobile-task"),
            record("task", "organizer-task"), record("notebook", "shared-book"), record("notebook", "private-book"))
        val selected = PhoneContentScope.filterRecords(records, manifest)
        assertEquals(listOf("mobile-note", "mobile-task", "shared-book"), selected.map { it.getValue("id").jsonPrimitive.content })
        assertEquals("Organizer addition", selected[0].getValue("value").jsonObject.getValue("text").jsonPrimitive.content)
        val before = records.toString(); val removed = PhoneContentScope.advance(manifest, emptyList(), emptyList())
        assertTrue(PhoneContentScope.filterRecords(records, removed).isEmpty()); assertEquals(before, records.toString())
        assertTrue(runCatching { PhoneContentScope.requireCurrent(PhoneContentScope.reference(manifest), removed) }.isFailure)
        PhoneContentScope.requireCurrent(PhoneContentScope.reference(removed), removed)
        assertSame(manifest, PhoneContentScope.advance(manifest, listOf("mobile-note"), listOf("mobile-task")))
    }
    @Test fun boundedLargeManifestAcceptsOnlyCompleteConsistentGenerations() {
        val manifest = PhoneContentScope.create((0 until 1300).map { "note-%05d".format(it) }, (0 until 700).map { "task-%05d".format(it) })
        val pieces = PhoneContentScope.chunks(manifest)
        assertTrue(pieces.size > 1 && pieces.all { it.getValue("members").jsonArray.size <= 256 })
        assertEquals(manifest, PhoneContentScope.assemble(pieces.reversed() + pieces[0]))
        assertTrue(runCatching { PhoneContentScope.assemble(pieces.dropLast(1)) }.isFailure)
        val newer = PhoneContentScope.chunks(PhoneContentScope.advance(manifest, listOf("different"), emptyList()))
        assertTrue(runCatching { PhoneContentScope.assemble(listOf(pieces[0], newer[0])) }.isFailure)
        val badMembers = pieces[0].getValue("members").jsonArray.toMutableList()
        badMembers[0] = JsonObject(badMembers[0].jsonObject + ("id" to JsonPrimitive("aaa-different")))
        val bad = JsonObject(pieces[0] + ("members" to JsonArray(badMembers)))
        assertTrue(runCatching { PhoneContentScope.assemble(pieces + bad) }.isFailure)
    }
    @Test fun emptyScopeAndDeletedRecordsCannotAuthorizeLibraryCopies() {
        val empty = PhoneContentScope.create(emptyList(), emptyList())
        val live = record("note", "mobile-note")
        assertTrue(PhoneContentScope.filterRecords(listOf(live), empty).isEmpty())
        assertEquals(empty, PhoneContentScope.assemble(PhoneContentScope.chunks(empty)))
        val manifest = PhoneContentScope.create(listOf("mobile-note"), emptyList())
        val deleted = buildJsonObject { put("kind", "note"); put("id", "mobile-note"); put("state", "deleted") }
        assertEquals(listOf(live), PhoneContentScope.filterRecords(listOf(live, deleted), manifest))
        val wrong = JsonObject(PhoneContentScope.reference(manifest) + ("scope_revision" to JsonPrimitive(true)))
        assertTrue(runCatching { PhoneContentScope.requireCurrent(wrong, manifest) }.isFailure)
    }
}
