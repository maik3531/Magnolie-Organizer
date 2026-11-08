package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class MediaSyncSettingsTest {
    private val pc = "11111111-1111-4111-8111-111111111111"
    private val phone = "22222222-2222-4222-8222-222222222222"

    @Test fun explicitManualWireRequiresFullSnapshotNoPathsAndDoesNotClaimFullSync() {
        val snapshot = MediaSyncSettings.create(pc)
        val start = buildJsonObject { put("format", 1); put("settings", snapshot) }
        MediaSyncSettings.validateStart(start)
        val partial = JsonObject(snapshot + ("settings" to JsonObject(snapshot.getValue("settings").jsonObject - "enabled")))
        assertThrows(IllegalArgumentException::class.java) { MediaSyncSettings.validateStart(JsonObject(start + ("settings" to partial))) }
        assertThrows(TelefonProtokollFehler::class.java) { MediaSyncSettings.validateStart(JsonObject(start + ("path" to JsonPrimitive("/must-not-open")))) }
        val report = buildJsonObject { put("format", 1); put("request_id", pc); put("state", "content_pass") }
        MediaSyncSettings.validateResult(report)
        assertThrows(IllegalArgumentException::class.java) { MediaSyncSettings.validateResult(JsonObject(report + ("state" to JsonPrimitive("complete")))) }
    }

    @Test fun mediaDefaultsAreSeparateManualAndOffWithoutAnyGrant() {
        val body = MediaSyncSettings.create(pc)
        val values = MediaSyncSettings.effective(body)
        assertEquals(8, values.size)
        assertEquals(JsonPrimitive(false), values["photos_only"])
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

    @Test fun scopeDirectionMatrixRetainsIndependentChoiceAndImportNeverExports() {
        for (scope in listOf("phone_inventory", "entire_collection", "import_only"))
        for (direction in listOf("phone_to_pc", "two_way", "pc_to_phone")) {
            var body = MediaSyncSettings.change(MediaSyncSettings.create(pc), pc, phone, "enabled", JsonPrimitive(true))
            body = MediaSyncSettings.change(body, pc, phone, "collection_mode", JsonPrimitive(scope))
            body = MediaSyncSettings.change(body, pc, phone, "direction", JsonPrimitive(direction))
            val before = body.toString(); val activeDirection = if (scope == "import_only") "phone_to_pc" else direction
            assertEquals(JsonPrimitive(activeDirection), MediaSyncSettings.effective(body)["direction"])
            assertEquals(activeDirection in setOf("phone_to_pc", "two_way"), MediaSyncSettings.transferRequestedFor(body, "images", false))
            assertEquals(activeDirection in setOf("pc_to_phone", "two_way"), MediaSyncSettings.transferRequestedFor(body, "images", true))
            assertEquals(before, body.toString())
            val restored = MediaSyncSettings.change(body, pc, phone, "collection_mode", JsonPrimitive("phone_inventory"))
            assertEquals(JsonPrimitive(direction), MediaSyncSettings.effective(restored)["direction"])
            assertEquals(body.getValue("settings").jsonObject["direction"], restored.getValue("settings").jsonObject["direction"])
        }
    }

    @Test fun storedSevenFieldProjectionPreservesAllChoicesAndNeverRepairsWireSnapshots() {
        val selected = MediaSyncSettings.change(MediaSyncSettings.create(pc), pc, phone, "skip_deletions", JsonPrimitive(true))
        val old = JsonObject(selected + ("settings" to JsonObject(selected.getValue("settings").jsonObject - "photos_only")))
        val before = old.toString()
        val projected = MediaSyncSettings.normalizeStored(old, pc, phone)
        assertEquals(before, old.toString())
        assertEquals(old.getValue("settings"), JsonObject(projected.getValue("settings").jsonObject - "photos_only"))
        assertEquals(JsonPrimitive(false), MediaSyncSettings.effective(projected)["photos_only"])
        assertEquals(projected, MediaSyncSettings.normalizeStored(projected, pc, phone))
        assertThrows(IllegalArgumentException::class.java) { MediaSyncSettings.validateStart(buildJsonObject { put("format", 1); put("settings", old) }) }
        val broken = JsonObject(old + ("settings" to JsonObject(old.getValue("settings").jsonObject - "enabled")))
        assertThrows(IllegalArgumentException::class.java) { MediaSyncSettings.normalizeStored(broken, pc, phone) }
        val filtered = MediaSyncSettings.change(projected, pc, phone, "photos_only", JsonPrimitive(true))
        val unfiltered = MediaSyncSettings.change(MediaSyncSettings.create(phone), phone, pc, "photos_only", JsonPrimitive(false))
        assertEquals(JsonPrimitive(true), MediaSyncSettings.effective(MediaSyncSettings.merge(filtered, unfiltered, pc, phone))["photos_only"])
        assertEquals(projected.getValue("settings").jsonObject["skip_deletions"], filtered.getValue("settings").jsonObject["skip_deletions"])
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
