package io.gitlab.maik3531.magnolienotes.baum

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class KontaktGruppenVertragTest {
    private fun message(groups: List<String>?) = KontaktNachricht("fixture:contact", 2, "fixture", 1000,
        KontaktDaten(vorname = "Synthetic", gruppen = groups), fassung = 4, inhaltGeaendert = 900)

    @Test fun explicitGroupSetRoundtripsAndEmptyMeansRemoval() {
        for (groups in listOf(listOf("Arbeit", "Kollegen"), listOf("Arbeit"), emptyList())) {
            val encoded = KontaktSync.inhalt(message(groups))
            assertEquals(JsonPrimitive(4), encoded["fassung"])
            assertEquals(groups, requireNotNull(KontaktSync.lies(encoded)).kontakt.gruppen)
            assertEquals(900L, requireNotNull(KontaktSync.lies(encoded)).inhaltGeaendert)
        }
    }

    @Test fun legacyUnknownGroupsPreserveMembershipWhileKnownEmptyClearsIt() {
        val local = KontaktDaten(vorname = "Synthetic", gruppen = listOf("Kollegen"))
        assertEquals(listOf("Kollegen"), KontaktSync.mische(local, KontaktDaten()).gruppen)
        assertEquals(listOf("Arbeit"), KontaktSync.mische(local, KontaktDaten(gruppen = listOf("Arbeit"))).gruppen)
        assertEquals(emptyList<String>(), KontaktSync.mische(local, KontaktDaten(gruppen = emptyList())).gruppen)
        for (version in 1..3) {
            val legacy = KontaktSync.inhalt(message(null).copy(fassung = version))
            assertFalse(legacy.getValue("kontakt").jsonObject.containsKey("gruppen"))
            assertNull(requireNotNull(KontaktSync.lies(legacy)).kontakt.gruppen)
        }
    }

    @Test fun groupOnlyChangesHaveDifferentModernFingerprintsAndKeepLegacyHashesStable() {
        val base = KontaktDaten(vorname = "Synthetic")
        val a = base.copy(gruppen = listOf("Kollegen"))
        val b = base.copy(gruppen = listOf("Arbeit", "Kollegen"))
        assertNotEquals(KontaktSync.hash(a), KontaktSync.hash(b))
        assertEquals(KontaktSync.hash(base), KontaktSync.hash(a.copy(gruppen = null)))
        assertEquals(KontaktSync.hash(b), KontaktSync.hash(b.copy(gruppen = listOf("Kollegen", "Arbeit", "Arbeit"))))
    }

    @Test fun unknownAndMalformedGroupSetsCannotBecomeAccidentalRemoval() {
        assertTrue(runCatching { KontaktSync.inhalt(message(null)) }.isFailure)
        val encoded = KontaktSync.inhalt(message(listOf("Arbeit")))
        val contact = encoded.getValue("kontakt").jsonObject
        for (bad in listOf(JsonNull, JsonPrimitive("Arbeit"), JsonArray(listOf(JsonPrimitive(""))), JsonArray(listOf(JsonPrimitive("bad\nname"))))) {
            assertNull(KontaktSync.lies(JsonObject(encoded + ("kontakt" to JsonObject(contact + ("gruppen" to bad))))))
        }
        assertNull(KontaktSync.lies(JsonObject(encoded + ("kontakt" to JsonObject(contact - "gruppen")))))
        assertNull(KontaktSync.lies(JsonObject(encoded + ("fassung" to JsonPrimitive(3)))))
    }
}
