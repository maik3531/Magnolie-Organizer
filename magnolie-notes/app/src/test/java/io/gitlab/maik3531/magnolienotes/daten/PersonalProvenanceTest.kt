package io.gitlab.maik3531.magnolienotes.daten

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class PersonalProvenanceTest {
    private val modules = setOf("notes", "tasks")
    private val creator = "11111111-1111-4111-8111-111111111111"
    private val editor = "22222222-2222-4222-8222-222222222222"

    @Test fun originsSurviveRoundTripEditsPersistenceAndLegacyDowngrade() {
        for (origin in listOf("notes", "organizer", "")) {
            val initial = Bestand(notizen = listOf(Notiz("note", titel = "Synthetic note", angelegt = 1000,
                geaendert = 2000, ursprungApp = origin)),
                aufgaben = listOf(Aufgabe("task", titel = "Synthetic task", angelegt = 1000, geaendert = 2000,
                    uid = "task-uid", ursprungApp = origin)), personalSync = PersonalSyncState(actor_id = creator))
            val sent = PersonalSync.reconcile(initial, modules, 14)
            assertTrue(sent.second.filter { it.kind != "notebook" }.all { it.value["origin_app"] == JsonPrimitive(origin) })
            val other = PersonalSync.apply(Bestand(personalSync = PersonalSyncState(actor_id = editor)), sent.second).bestand
            assertEquals(origin, other.notizen.single().ursprungApp)
            assertEquals(origin, other.aufgaben.single().ursprungApp)
            val edited = other.copy(notizen = other.notizen.map { it.copy(text = "Edited elsewhere", geaendert = 3000) },
                aufgaben = other.aufgaben.map { it.copy(notiz = "Edited elsewhere", geaendert = 3000) })
            val reply = PersonalSync.reconcile(edited, modules, 14)
            val returned = PersonalSync.apply(sent.first, reply.second).bestand
            assertEquals(origin, returned.notizen.single().ursprungApp)
            assertEquals(origin, returned.aufgaben.single().ursprungApp)
            assertEquals(1000L, returned.notizen.single().angelegt)
            val loaded = Json.decodeFromString<Bestand>(Json.encodeToString(returned))
            val legacy = PersonalSync.reconcile(loaded, modules, 3)
            assertTrue(legacy.second.all { "origin_app" !in it.value })
            assertEquals(origin, legacy.first.notizen.single().ursprungApp)
            assertEquals(origin, legacy.first.aufgaben.single().ursprungApp)
        }
    }
}
