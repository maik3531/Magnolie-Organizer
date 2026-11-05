package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class MediaSyncSettingsTest {
    private val pc = "11111111-1111-4111-8111-111111111111"
    private val phone = "22222222-2222-4222-8222-222222222222"

    @Test fun mediaDefaultsAreSeparateManualAndOffWithoutAnyGrant() {
        val body = MediaSyncSettings.create(pc)
        val values = MediaSyncSettings.effective(body)
        assertEquals(7, values.size)
        assertEquals(JsonPrimitive(false), values["enabled"])
        assertEquals(JsonPrimitive(true), values["photos_enabled"])
        assertEquals(JsonPrimitive(false), values["videos_enabled"])
        assertEquals(JsonPrimitive("manual"), values["auto_mode"])
        assertEquals(JsonPrimitive(false), values["skip_deletions"])
        assertEquals(JsonPrimitive("phone_inventory"), values["collection_mode"])
        assertEquals(JsonPrimitive("phone_to_pc"), values["direction"])
        assertFalse(body.toString().contains("content_mode"))
        assertFalse(MediaSyncSettings.requestedFor(body, "images"))
        assertFalse(MediaSyncSettings.requestedFor(body, "video"))
        val active = MediaSyncSettings.change(body, pc, phone, "enabled", JsonPrimitive(true))
        assertTrue(MediaSyncSettings.requestedFor(active, "images"))
        assertFalse(MediaSyncSettings.requestedFor(active, "video"))
        assertEquals(0L, active.getValue("settings").jsonObject.getValue("photos_enabled").jsonObject.getValue(pc).jsonObject.getValue("counter").jsonPrimitive.long)
    }

    @Test fun independentOfflineEditsMergeWithoutChangingInputsOrDependingOnOrder() {
        val initial = MediaSyncSettings.create(pc); val original = initial.toString()
        val left = MediaSyncSettings.change(initial, pc, phone, "photos_enabled", JsonPrimitive(true))
        val right = MediaSyncSettings.change(MediaSyncSettings.create(phone), phone, pc, "videos_enabled", JsonPrimitive(true))
        val merged = MediaSyncSettings.merge(left, right, pc, phone)
        assertEquals(merged, MediaSyncSettings.merge(right, left, phone, pc))
        assertEquals(JsonPrimitive(true), MediaSyncSettings.effective(merged)["photos_enabled"])
        assertEquals(JsonPrimitive(true), MediaSyncSettings.effective(merged)["videos_enabled"])
        assertEquals(original, initial.toString())
    }

    @Test fun simultaneousChoicesUseOffManualAndSkipAsSafeTies() {
        for ((field, first, second, expected) in listOf(
            listOf("photos_enabled", JsonPrimitive(true), JsonPrimitive(false), JsonPrimitive(false)),
            listOf("auto_mode", JsonPrimitive("wifi"), JsonPrimitive("manual"), JsonPrimitive("manual")),
            listOf("skip_deletions", JsonPrimitive(false), JsonPrimitive(true), JsonPrimitive(true)))) {
            val name = field as String
            val left = MediaSyncSettings.change(MediaSyncSettings.create(pc), pc, phone, name, first as JsonElement)
            val right = MediaSyncSettings.change(MediaSyncSettings.create(phone), phone, pc, name, second as JsonElement)
            assertEquals(expected, MediaSyncSettings.effective(MediaSyncSettings.merge(left, right, pc, phone))[name])
        }
    }

    @Test fun personalModesForeignActorsAndForgedLocalEditsAreRejected() {
        val initial = MediaSyncSettings.create(pc)
        assertThrows(IllegalArgumentException::class.java) {
            MediaSyncSettings.change(initial, pc, phone, "auto_mode", JsonPrimitive("connection"))
        }
        val forged = MediaSyncSettings.change(initial, pc, phone, "photos_enabled", JsonPrimitive(true))
        assertThrows(IllegalArgumentException::class.java) { MediaSyncSettings.merge(initial, forged, pc, phone) }
        val foreign = MediaSyncSettings.create("33333333-3333-4333-8333-333333333333")
        assertThrows(IllegalArgumentException::class.java) { MediaSyncSettings.merge(initial, foreign, pc, phone) }
    }
}
