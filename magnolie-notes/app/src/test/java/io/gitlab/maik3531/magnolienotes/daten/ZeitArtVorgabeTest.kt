package io.gitlab.maik3531.magnolienotes.daten

import io.gitlab.maik3531.magnolienotes.telefon.TimeSyncProtokoll
import kotlinx.serialization.json.*
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class ZeitArtVorgabeTest {
    private val now = 1793505600000L
    private val json = Json { ignoreUnknownKeys = true }
    private fun configured(value: JsonElement, state: ZeiterfassungStand = ZeiterfassungStand(enabled = true)): ZeiterfassungStand {
        val body = json.encodeToJsonElement(ZeiterfassungStand.serializer(), state).jsonObject
        return json.decodeFromJsonElement(ZeiterfassungStand.serializer(), JsonObject(body + ("defaultType" to value))).validate()
    }
    private fun entry() = Zeiteintrag(startMinute = now / 60000, zone = "UTC", modifiedMs = now)

    @Test fun aFreeDefaultActivityIsDurableAndUsedForAnUnspecifiedManualStart() {
        val configured = configured(JsonPrimitive("Trainingseinheit"))
        val encoded = json.encodeToJsonElement(ZeiterfassungStand.serializer(), configured).jsonObject
        assertEquals(JsonPrimitive("Trainingseinheit"), encoded["defaultType"])
        val restored = json.decodeFromJsonElement(ZeiterfassungStand.serializer(), encoded)
        val started = restored.start(entry())
        assertEquals("Trainingseinheit", started.entries.single().type)
        assertEquals("manual", started.startKind(started.entries.single()))
        val wire = TimeSyncProtokoll.encodeRecords(started.entries).single().jsonObject
        assertFalse(wire.containsKey("defaultType"))
        assertEquals(JsonPrimitive("Trainingseinheit"), wire["type"])
    }

    @Test fun wifiUsesTheConfiguredActivityInsteadOfAWorkShiftSuggestion() {
        val state = configured(JsonPrimitive("Meeting")).copy(wifi = ZeitWlanAutomatik(true, "Synthetic WLAN"))
        val started = state.startFromWifi("Synthetic WLAN", now, now, "Nachtdienst")
        assertEquals("Meeting", started.entries.single().type)
        assertEquals("wifi", started.startKind(started.entries.single()))
    }

    @Test fun explicitEmptyActivityDisablesShiftSuggestionsWhileMissingPreferenceKeepsLegacyBehavior() {
        val base = ZeiterfassungStand(enabled = true, wifi = ZeitWlanAutomatik(true, "Synthetic WLAN"))
        assertEquals("Frühdienst", base.startFromWifi("Synthetic WLAN", now, now, "Frühdienst").entries.single().type)
        val empty = configured(JsonPrimitive(""), base)
        assertEquals("", empty.startFromWifi("Synthetic WLAN", now, now, "Frühdienst").entries.single().type)
        val automatic = configured(JsonNull, base)
        assertEquals("Frühdienst", automatic.startFromWifi("Synthetic WLAN", now, now, "Frühdienst").entries.single().type)
    }

    @Test fun computerActivityWinsWhenExplicitAndOtherwiseUsesTheConfiguredDefault() {
        for (activity in listOf("", "Meeting")) {
            val state = configured(JsonPrimitive("Sport"))
            val command = ZeitSteuerBefehl(UUID.randomUUID().toString(), "start", ZeitSteuerung.revision(state), activity = activity)
            val started = ZeitSteuerung.apply(state, command, "a".repeat(64), "owned-epoch", now, "UTC").state
            assertEquals(if (activity.isEmpty()) "Sport" else activity, started.entries.single().type)
            assertEquals("computer", started.startKind(started.entries.single()))
        }
    }

    @Test fun changingThePreferenceNeverRewritesExistingTimesOrTheirClockAndStartReceipt() {
        val initial = configured(JsonPrimitive("Sport"))
        val command = ZeitSteuerBefehl(UUID.randomUUID().toString(), "start", ZeitSteuerung.revision(initial), activity = "Meeting")
        val started = ZeitSteuerung.apply(initial, command, "a".repeat(64), "owned-epoch", now, "UTC").state
        val changed = configured(JsonPrimitive("Training"), started)
        assertEquals(started.entries, changed.entries); assertEquals(started.counter, changed.counter)
        assertEquals(started.pauseRuns, changed.pauseRuns); assertEquals(started.controlReceipts, changed.controlReceipts)
        val retry = ZeitSteuerung.apply(changed, command, "a".repeat(64), "owned-epoch", now + 1, "UTC")
        assertTrue(retry.duplicate); assertEquals(changed, retry.state)
    }

    @Test fun explicitEntryTypesAreNotReplacedAndRetriedStartsDoNotAcquireANewerDefault() {
        val original = entry().copy(type = "Meeting")
        val state = configured(JsonPrimitive("Sport")).start(original)
        assertEquals("Meeting", state.entries.single().type)
        val changed = configured(JsonPrimitive("Training"), state)
        assertEquals(changed, changed.start(original))
    }

    @Test fun overlongDefaultActivityCannotEnterTheSavedState() {
        assertTrue(runCatching { configured(JsonPrimitive("x".repeat(121))) }.isFailure)
        val longest = configured(JsonPrimitive("x".repeat(120))).start(entry())
        assertEquals(120, longest.entries.single().type.length)
    }

    @Test fun ownActivityNeverChangesWithTheHourAndLegacySuggestionsRemainOptional() {
        for (hour in 0..23) {
            val shift = Zeiteintrag.suggestedType(hour)
            assertEquals("Trainingseinheit", configured(JsonPrimitive("Trainingseinheit")).activityType(shift))
            assertEquals("", configured(JsonPrimitive("")).activityType(shift))
            assertEquals(shift, ZeiterfassungStand().activityType(shift))
        }
    }

    @Test fun preferenceSaveRejectsStaleSettingsButPreservesUnrelatedConcurrentChanges() {
        val original = configured(JsonPrimitive("Trainingseinheit"))
        val concurrent = original.start(entry()).copy(reportName = "Synthetic report")
        val changed = concurrent.changeDefaultType(original.defaultType, "Meeting")
        assertEquals(concurrent.entries, changed.entries)
        assertEquals(concurrent.pauseRuns, changed.pauseRuns)
        assertEquals(concurrent.reportName, changed.reportName)
        assertTrue(runCatching { changed.changeDefaultType(original.defaultType, "Other") }.isFailure)
    }
}
