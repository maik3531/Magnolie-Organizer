package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class PersonalFormatProjectionTest {
    private val first = "11111111-1111-4111-8111-111111111111"
    private val second = "22222222-2222-4222-8222-222222222222"
    private val peer = "33333333-3333-4333-8333-333333333333"
    private val modules = setOf("notes")
    private fun book(actor: String, origin: String = "") = Bestand(
        notizbuecher = listOf(Notizbuch("shared-book", "Shared notebook")),
        notizen = listOf(Notiz("shared-note", titel = "Synthetic note", text = "Same content", html = "Same content",
            notizbuchId = "shared-book", angelegt = 1000, geaendert = 2000, ursprungApp = origin)),
        personalSync = PersonalSyncState(actor_id = actor))
    private fun prepare(data: Bestand, format: Int) = PersonalSync.reconcile(data, modules, format, peer)
    private fun establish(format: Int, aOrigin: String = "", bOrigin: String = ""): Pair<Bestand, Bestand> {
        val a = prepare(book(first, aOrigin), format); val b = prepare(book(second, bOrigin), format)
        return PersonalSync.apply(a.first, b.second).bestand to PersonalSync.apply(b.first, a.second).bestand
    }
    private fun reopen(data: Bestand) = Json.decodeFromString<Bestand>(Json.encodeToString(data))

    @Test fun legacyProjectionMigrationIsNotAConcurrentUserEditAndDoesNotChangeTheClock() {
        for (format in 1..3) for ((aOrigin, bOrigin) in listOf("" to "", "organizer" to "organizer", "" to "notes", "notes" to "", "notes" to "organizer")) {
            for (edit in listOf(false, true)) {
                val (originalA, originalB) = establish(format, aOrigin, bOrigin)
                val a = if (edit) originalA.copy(notizen = originalA.notizen.map { it.copy(text = "Changed on A", html = "Changed on A", geaendert = 3000) }) else originalA
                val before = originalB.personalSync.entities.getValue("note\u0000shared-note")
                val sent = prepare(a, 14); val receiver = prepare(originalB, 14)
                assertEquals(originalB.personalSync.counter, receiver.first.personalSync.counter)
                assertEquals(before.clock, receiver.first.personalSync.entities.getValue("note\u0000shared-note").clock)
                val applied = PersonalSync.apply(receiver.first, sent.second)
                assertEquals("format=$format/$aOrigin/$bOrigin/edit=$edit", 0, applied.conflicts)
                assertEquals(1, applied.bestand.notizen.size)
                assertEquals(if (edit) "Changed on A" else "Same content", applied.bestand.notizen.single().text)
                assertEquals(originalB.personalSync.counter, applied.bestand.personalSync.counter)
                val reply = prepare(reopen(applied.bestand), 14)
                val returned = PersonalSync.apply(sent.first, reply.second)
                assertEquals(0, returned.conflicts); assertEquals(1, returned.bestand.notizen.size)
                if (aOrigin.isNotEmpty()) assertEquals(aOrigin, returned.bestand.notizen.single().ursprungApp)
                if (bOrigin.isNotEmpty()) assertEquals(bOrigin, reply.first.notizen.single().ursprungApp)
                val legacy = prepare(reopen(returned.bestand), format)
                assertEquals(returned.bestand.personalSync.counter, legacy.first.personalSync.counter)
                assertEquals(legacy.first.personalSync.counter, prepare(legacy.first, 14).first.personalSync.counter)
            }
        }
    }

    @Test fun sixAlternatingUpdatesAndReopensRetainOneNote() {
        var (a, b) = establish(3)
        for (step in 0..5) {
            val text = "One-sided update $step"
            val writer = if (step % 2 == 0) a else b
            val reader = if (step % 2 == 0) b else a
            val changed = writer.copy(notizen = writer.notizen.map { it.copy(text = text, html = text, geaendert = 3000L + step) })
            val sent = prepare(changed, 14)
            val accepted = PersonalSync.apply(prepare(reader, 14).first, sent.second)
            assertEquals(0, accepted.conflicts); assertEquals(listOf(text), accepted.bestand.notizen.map { it.text })
            val reply = prepare(reopen(accepted.bestand), 14)
            val returned = PersonalSync.apply(sent.first, reply.second)
            assertEquals(0, returned.conflicts); assertEquals(listOf(text), returned.bestand.notizen.map { it.text })
            if (step % 2 == 0) { a = reopen(returned.bestand); b = reopen(reply.first) }
            else { b = reopen(returned.bestand); a = reopen(reply.first) }
        }
    }

    @Test fun realConcurrentEditsDuringMigrationStillPreserveBothContentsWithoutReplayCopies() {
        val (baseA, baseB) = establish(3)
        val a = prepare(baseA.copy(notizen = baseA.notizen.map { it.copy(text = "Independent A", html = "Independent A", geaendert = 3000) }), 14)
        val b = prepare(baseB.copy(notizen = baseB.notizen.map { it.copy(text = "Independent B", html = "Independent B", geaendert = 3000) }), 14)
        for ((local, remote) in listOf(a.first to b.second, b.first to a.second)) {
            val applied = PersonalSync.apply(local, remote)
            assertTrue(applied.conflicts > 0)
            assertEquals(setOf("Independent A", "Independent B"), applied.bestand.notizen.map { it.text }.toSet())
            val ids = applied.bestand.notizen.map { it.id }.toSet()
            val replay = PersonalSync.apply(prepare(reopen(applied.bestand), 14).first, remote)
            assertEquals(ids, replay.bestand.notizen.map { it.id }.toSet())
        }
    }

    @Test fun projectionDoesNotRehashTamperedWireContentIntoAnAcceptedRecord() {
        val (a, b) = establish(3, "organizer", "notes")
        val sender = prepare(a, 14)
        val bad = sender.second.map { record -> if (record.kind == "note") record.copy(
            value = JsonObject(record.value + ("text" to JsonPrimitive("Tampered without new hash")))) else record }
        val receiver = prepare(b, 14).first
        assertThrows(IllegalArgumentException::class.java) { PersonalSync.apply(receiver, bad) }
        assertEquals("Same content", receiver.notizen.single().text)
        val equalClock = sender.second.map { record -> if (record.kind == "note") {
            val value = JsonObject(record.value + ("text" to JsonPrimitive("Different real content at the same clock")))
            record.copy(value = value, hash = PersonalSync.hash(value))
        } else record }
        assertThrows(IllegalArgumentException::class.java) { PersonalSync.apply(receiver, equalClock) }
    }
}
