package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SharedSyncSettingsTest {
    private val a = "11111111-1111-4111-8111-111111111111"
    private val b = "22222222-2222-4222-8222-222222222222"
    private val c = "33333333-3333-4333-8333-333333333333"
    private fun pair(): Pair<JsonObject, JsonObject> {
        val one = SharedSyncSettings.create(a); val two = SharedSyncSettings.create(b)
        return converge(one, two)
    }
    private fun converge(one: JsonObject, two: JsonObject) =
        SharedSyncSettings.merge(one, two, a, b) to SharedSyncSettings.merge(two, one, b, a)
    private fun mode(body: JsonObject) = SharedSyncSettings.effective(body).getValue("content_mode").jsonPrimitive.content

    @Test fun oneChoiceAtEitherEndChangesTheSharedContentScopeAndEchoDoesNotCreateEdits() {
        var (one, two) = pair()
        assertEquals("phone_scope", mode(one))
        one = SharedSyncSettings.change(one, a, b, "content_mode", JsonPrimitive("two_way"))
        val first = converge(one, two); one = first.first; two = first.second
        assertEquals("two_way", mode(two))
        two = SharedSyncSettings.change(two, b, a, "content_mode", JsonPrimitive("phone_scope"))
        val second = converge(one, two); one = second.first; two = second.second
        assertEquals("phone_scope", mode(one))
        assertEquals(SharedSyncSettings.effective(one), SharedSyncSettings.effective(two))
        assertEquals(one, SharedSyncSettings.merge(one, two, a, b))
    }

    @Test fun independentEditsKeepTimeDirectionSeparateFromNoteAndTaskScope() {
        var (one, two) = pair()
        one = SharedSyncSettings.change(one, a, b, "auto_mode", JsonPrimitive("connection"))
        two = SharedSyncSettings.change(two, b, a, "time_mode", JsonPrimitive("two_way"))
        val result = converge(one, two)
        val values = SharedSyncSettings.effective(result.first)
        assertEquals("connection", values.getValue("auto_mode").jsonPrimitive.content)
        assertEquals("two_way", values.getValue("time_mode").jsonPrimitive.content)
        assertEquals("phone_scope", values.getValue("content_mode").jsonPrimitive.content)
        assertFalse(values.getValue("custom_enabled").jsonPrimitive.boolean)
        assertEquals(values, SharedSyncSettings.effective(result.second))
    }

    @Test fun concurrentScopeEditsConvergeAndOneLaterChoiceCanSelectFullSynchronization() {
        var (one, two) = pair()
        one = SharedSyncSettings.change(one, a, b, "content_mode", JsonPrimitive("two_way"))
        two = SharedSyncSettings.change(two, b, a, "content_mode", JsonPrimitive("phone_scope"))
        val first = converge(one, two); one = first.first; two = first.second
        assertEquals("phone_scope", mode(one))
        assertEquals(mode(one), mode(two))
        two = SharedSyncSettings.change(two, b, a, "content_mode", JsonPrimitive("two_way"))
        val second = converge(one, two)
        assertEquals("two_way", mode(second.first)); assertEquals(mode(second.first), mode(second.second))
    }

    @Test fun oldReplayCannotUndoNewerSavedPreferences() {
        var (one, two) = pair(); val old = two
        two = SharedSyncSettings.change(two, b, a, "skip_deletions", JsonPrimitive(false))
        two = SharedSyncSettings.change(two, b, a, "skip_deletions", JsonPrimitive(true))
        one = converge(one, two).first
        val reopened = Json.parseToJsonElement(one.toString()).jsonObject
        assertEquals(reopened, SharedSyncSettings.merge(reopened, old, a, b))
    }

    @Test fun differentPeerAndForgedLocalEchoFailWithoutPartiallyChangingState() {
        val (one, two) = pair(); val before = one.toString()
        assertTrue(runCatching { SharedSyncSettings.merge(one, SharedSyncSettings.create(c), a, b) }.isFailure)
        val wrong = Json.parseToJsonElement(two.toString()).jsonObject
        val fields = wrong.getValue("settings").jsonObject.toMutableMap()
        val edits = fields.getValue("content_mode").jsonObject.toMutableMap()
        edits[a] = buildJsonObject { put("counter", 1); put("value", "two_way") }
        fields["content_mode"] = JsonObject(edits)
        val forged = JsonObject(wrong + ("settings" to JsonObject(fields)))
        assertTrue(runCatching { SharedSyncSettings.merge(one, forged, a, b) }.isFailure)
        assertEquals(before, one.toString())
        assertTrue(runCatching { SharedSyncSettings.change(one, a, b, "custom_enabled", JsonPrimitive(1)) }.isFailure)
        assertTrue(runCatching { SharedSyncSettings.change(one, a, b, "unknown", JsonPrimitive(true)) }.isFailure)
    }

    @Test fun initialLegacyWifiOptInNeverBecomesTransportFreeAutomation() {
        val one = SharedSyncSettings.create(a, mapOf("auto_mode" to JsonPrimitive("wifi")))
        val two = SharedSyncSettings.create(b)
        val result = converge(one, two)
        assertEquals("wifi", SharedSyncSettings.effective(result.first).getValue("auto_mode").jsonPrimitive.content)
        assertEquals(SharedSyncSettings.effective(result.first), SharedSyncSettings.effective(result.second))
    }
}
