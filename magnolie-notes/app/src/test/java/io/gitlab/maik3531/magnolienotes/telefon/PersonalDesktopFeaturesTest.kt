package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PersonalDesktopFeaturesTest {
    private fun features(revision: Long = 1, custom: Boolean = false, tree: Boolean = false) = buildJsonObject {
        put("format", 6); put("revision", revision); put("custom_tab", custom); put("tree", tree)
    }

    @Test fun exactBooleanSchemaAndReplayProtection() {
        val initial = features()
        assertEquals(initial, PersonalDesktopFeatures.accept(null, initial))
        assertEquals(initial, PersonalDesktopFeatures.accept(initial, initial))
        for ((name, value) in listOf("custom_tab" to JsonPrimitive("false"), "tree" to JsonPrimitive(0),
            "revision" to JsonPrimitive("1"), "revision" to JsonPrimitive(0), "extra" to JsonPrimitive(false)))
            assertThrows(TelefonProtokollFehler::class.java) { PersonalDesktopFeatures.validate(JsonObject(initial + (name to value))) }
        assertThrows(TelefonProtokollFehler::class.java) { PersonalDesktopFeatures.accept(initial, features(custom = true)) }
        val next = features(2, custom = true)
        assertEquals(next, PersonalDesktopFeatures.accept(initial, next))
        assertThrows(TelefonProtokollFehler::class.java) { PersonalDesktopFeatures.accept(next, initial) }
    }

    @Test fun visibilityUsesThisComputerAndPreservesIndependentTreeAndPendingContent() {
        val modern = TelefonPeer("desktop", "Desktop", "key", remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4, 6))
        assertFalse(PersonalDesktopFeatures.customAvailable(modern))
        assertFalse(PersonalDesktopFeatures.treeVisible(modern, false, false))
        assertTrue(PersonalDesktopFeatures.treeVisible(modern, true, false))
        assertTrue(PersonalDesktopFeatures.treeVisible(modern, false, true))
        assertTrue(PersonalDesktopFeatures.treeVisible(null, false, false))
        val active = modern.copy(remote_desktop_features = features(custom = true, tree = true))
        assertTrue(PersonalDesktopFeatures.customAvailable(active))
        assertTrue(PersonalDesktopFeatures.treeVisible(active, false, false))
        assertFalse(PersonalDesktopFeatures.customAvailable(modern.copy(remote_desktop_features = features(tree = true))))
        assertTrue(PersonalDesktopFeatures.customAvailable(modern.copy(remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4))))
    }
}
