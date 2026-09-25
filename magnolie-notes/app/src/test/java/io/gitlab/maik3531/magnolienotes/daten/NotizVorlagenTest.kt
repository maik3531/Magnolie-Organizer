package io.gitlab.maik3531.magnolienotes.daten

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class NotizVorlagenTest {
    private val templates = Json.parseToJsonElement(listOf("../contracts", "contracts")
        .map { File(it, "note-identity-templates.json") }.first { it.isFile }.readText())
        .jsonObject.getValue("templates").jsonArray

    @Test fun `only exact legacy welcome templates ignore the storage path`() {
        for (entry in templates) {
            val t = entry.jsonObject
            fun field(name: String) = t.getValue(name).jsonPrimitive.content
            val title = field("title")
            val canonical = field("text")
            fun text(path: String) = field("before") + path + field("after")
            val original = text("/home/fixture/data.json")
            for (value in listOf(original, text("C:\\Users\\Fixture\\data.json"),
                original.replace("\n", "\r\n"), canonical)) {
                assertEquals(field("locale"), canonical, NotizVorlagen.vergleichsText(title, value))
            }
            for (value in listOf(original + "User addition", text("relative/data.json"),
                text("/home/fixture\nUser addition"), text("/home/fixture\u0000data.json"),
                text("/" + "x".repeat(4096)))) {
                assertNotEquals(field("locale"), canonical, NotizVorlagen.vergleichsText(title, value))
            }
            assertEquals(original, NotizVorlagen.vergleichsText(title + " edited", original))
        }
        assertEquals("/home/fixture/data.json", NotizVorlagen.vergleichsText("My paths", "/home/fixture/data.json"))
    }

    @Test fun `welcome identities converge through personal sync and replay without conflict copies`() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val peer = "22222222-2222-4222-8222-222222222222"
        for (entry in templates) for (format in 1..3) {
            val t = entry.jsonObject
            fun field(name: String) = t.getValue(name).jsonPrimitive.content
            fun initial(id: String, device: String, path: String) = PersonalSync.reconcile(
                Bestand(notizen = listOf(Notiz(id, titel = field("title"),
                    text = field("before") + path + field("after"), html = "", angelegt = 1, geaendert = 1)),
                    personalSync = PersonalSyncState(actor_id = device)), setOf("notes"), format, peer)
            val local = initial("z-local", actor, "/home/fixture/data.json")
            val remote = initial("a-local", peer, "C:\\Users\\Fixture\\data.json")
            val result = PersonalSync.apply(local.first, remote.second)
            assertEquals(field("locale"), 0, result.conflicts)
            assertEquals(field("locale"), 1, result.bestand.notizen.size)
            assertEquals("z-local", result.bestand.notizen.single().id)
            assertEquals(field("text"), NotizVorlagen.vergleichsText(field("title"), result.bestand.notizen.single().text))
            val replay = PersonalSync.apply(result.bestand, remote.second)
            assertEquals(1, replay.bestand.notizen.size)
            assertEquals(0, replay.conflicts)
            val reverse = PersonalSync.apply(remote.first, local.second)
            val next = PersonalSync.reconcile(replay.bestand, setOf("notes"), format, peer)
            val other = PersonalSync.reconcile(reverse.bestand, setOf("notes"), format, actor)
            assertEquals(next.second.single { it.kind == "note" }.hash,
                other.second.single { it.kind == "note" }.hash)
            assertEquals(next.second.single { it.kind == "note" }.id,
                other.second.single { it.kind == "note" }.id)
        }
    }

    @Test fun `personal sync preserves edited formatted and differently translated welcome notes`() {
        val actor = "11111111-1111-4111-8111-111111111111"
        val peer = "22222222-2222-4222-8222-222222222222"
        val english = templates.first().jsonObject
        fun field(name: String) = english.getValue(name).jsonPrimitive.content
        val local = Notiz("z-local", titel = field("title"), text = field("before") +
            "/home/fixture/data.json" + field("after"), html = "", angelegt = 1, geaendert = 1)
        val otherLanguage = templates.first { it.jsonObject.getValue("locale").jsonPrimitive.content == "de" }.jsonObject
        val variants = listOf(local.copy(id = "a-local", text = local.text + "User addition"),
            local.copy(id = "a-local", titel = local.titel + " edited"),
            local.copy(id = "a-local", html = "<b>Welcome</b>"),
            local.copy(id = "a-local", titel = otherLanguage.getValue("title").jsonPrimitive.content,
                text = otherLanguage.getValue("text").jsonPrimitive.content))
        for (format in 1..3) for (remote in variants) {
            val a = PersonalSync.reconcile(Bestand(notizen = listOf(local),
                personalSync = PersonalSyncState(actor_id = actor)), setOf("notes"), format, peer)
            val b = PersonalSync.reconcile(Bestand(notizen = listOf(remote),
                personalSync = PersonalSyncState(actor_id = peer)), setOf("notes"), format, actor)
            val result = PersonalSync.apply(a.first, b.second)
            assertEquals(2, result.bestand.notizen.size)
            assertEquals(local, result.bestand.notizen.first { it.id == local.id })
        }
    }
}
