package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class TelefonComputerTest {
    private val home = TelefonPeer("11111111-1111-4111-8111-111111111111", "Computer", "home-key")
    private val office = TelefonPeer("22222222-2222-4222-8222-222222222222", "Computer", "office-key")

    @Test fun automaticReconnectPrefersCurrentAndOnlyFallsBackToVerifiedSavedIdentities() {
        val nearbyOffice = GefundenerDesktop(office.device_id, "Computer", "192.0.2.2", "")
        val nearbyHome = GefundenerDesktop(home.device_id, "Other name", "192.0.2.1", "")
        val unknown = GefundenerDesktop("33333333-3333-4333-8333-333333333333", "Computer", "192.0.2.3", "")
        assertEquals(nearbyHome, knownReconnectTarget(home, listOf(home, office), listOf(unknown, nearbyOffice, nearbyHome)))
        assertEquals(nearbyOffice, knownReconnectTarget(home, listOf(home, office), listOf(unknown, nearbyOffice)))
        assertNull(knownReconnectTarget(home, listOf(home), listOf(unknown, nearbyOffice)))
        assertNull(knownReconnectTarget(home, listOf(home, office.copy(state = "paired_unverified")), listOf(nearbyOffice)))
        assertNull(knownReconnectTarget(home, listOf(home, office), emptyList()))
    }

    @Test fun oldSingleComputerStorageSurvivesAddingSelectingAndRemovingAnotherComputer() {
        val encoded = TelefonKanonisch.json.encodeToJsonElement(TelefonBestand.serializer(), TelefonBestand(peer = home)) as JsonObject
        val legacy = JsonObject((encoded - "other_peers") + ("storage_version" to JsonPrimitive(1)))
        val migrated = TelefonKanonisch.json.decodeFromJsonElement(TelefonBestand.serializer(), sanitizeLegacyPeer(legacy).first).validated()
        assertEquals(home, migrated.peer)
        val pairMore = migrated.select(null)
        assertNull(pairMore.peer); assertEquals(listOf(home), pairMore.all())
        val two = pairMore.remember(office)
        val loaded = TelefonKanonisch.json.decodeFromJsonElement(TelefonBestand.serializer(),
            sanitizeLegacyPeer(JsonObject((TelefonKanonisch.json.encodeToJsonElement(TelefonBestand.serializer(), two) as JsonObject) +
                ("storage_version" to JsonPrimitive(1)))).first).validated()
        assertEquals(listOf(office, home), loaded.all())
        assertEquals(home, loaded.select(home.device_id).peer)
        assertEquals(listOf(office), loaded.select(home.device_id).remember(null).all())
        assertThrows(IllegalArgumentException::class.java) { loaded.remember(home.copy(static_public = "replacement")) }
        assertThrows(NoSuchElementException::class.java) { loaded.select("unknown") }
    }

    @Test fun corruptOrUnknownArchivedComputerFieldsAreRejected() {
        val value = JsonObject((TelefonKanonisch.json.encodeToJsonElement(TelefonBestand.serializer(), TelefonBestand(peer = home, other_peers = listOf(office))) as JsonObject) +
            ("storage_version" to JsonPrimitive(1)))
        val archive = (value.getValue("other_peers") as JsonArray).single() as JsonObject
        assertThrows(TelefonProtokollFehler::class.java) {
            sanitizeLegacyPeer(JsonObject(value + ("other_peers" to JsonArray(listOf(JsonObject(archive + ("unknown" to JsonPrimitive(true))))))))
        }
        assertThrows(TelefonProtokollFehler::class.java) {
            sanitizeLegacyPeer(JsonObject(value + ("other_peers" to JsonPrimitive("invalid"))))
        }
        assertThrows(IllegalArgumentException::class.java) { TelefonBestand(peer = home, other_peers = listOf(home)).validated() }
    }
}
