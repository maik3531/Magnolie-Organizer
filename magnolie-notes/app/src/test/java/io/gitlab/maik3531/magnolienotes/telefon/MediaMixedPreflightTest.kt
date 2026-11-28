package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class MediaMixedPreflightTest {
    @Test fun acceptsExactDesktopHashesAndRejectsChangedOrExpiredWitness() {
        val a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        val b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        var settings = MediaSyncSettings.create(a)
        for ((field, value) in listOf("enabled" to JsonPrimitive(true), "videos_enabled" to JsonPrimitive(true),
            "direction" to JsonPrimitive("pc_to_phone"), "collection_mode" to JsonPrimitive("entire_collection")))
            settings = MediaSyncSettings.change(settings, a, b, field, value)
        val binding = DeviceTransferBinding(a, b, "a".repeat(64), "b".repeat(64), "c".repeat(64), "0".repeat(64))
        val id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        val request = buildJsonObject {
            put("type", "message")
            put("v", 1)
            put("message_id", id)
            put("kind", MediaMixedPreflight.REQUEST)
            put("created_ms", 90_000)
            put("expires_ms", 100_000)
            put("body", buildJsonObject {
                put("format", 1)
                put("settings_sha256", "f4ab550c3a03323ed421de4c8b40e018326ed7943bbe774bdb423a6e296f532c")
                put("binding_sha256", "9d893a016e746872e29a19566dc3fbd8fff08c3e8e443a240d0c2bde047e8d88")
            })
        }
        val ready = MediaMixedPreflight.readyResult(request, settings, binding, 90_031)
        assertEquals(100_000L, ready.long("expires_ms"))
        assertEquals(id, ready.getValue("body").jsonObject.string("request_id"))
        assertNotEquals(id, ready.string("message_id"))
        assertEquals(90_031L, ready.long("created_ms"))
        fun refuse(frame: JsonObject = request, s: JsonObject = settings, control: DeviceTransferBinding = binding, now: Long = 90_031) {
            assertTrue(runCatching { MediaMixedPreflight.readyResult(frame, s, control, now) }.isFailure)
        }
        refuse(now = 100_000)
        refuse(now = 89_999)
        refuse(frame = JsonObject(request + ("expires_ms" to JsonPrimitive(100_001))))
        refuse(control = binding.copy(permissionEpoch = "d".repeat(64)))
        refuse(s = MediaSyncSettings.change(settings, a, b, "auto_mode", JsonPrimitive("wifi")))
        refuse(s = MediaSyncSettings.change(settings, a, b, "videos_enabled", JsonPrimitive(false)))
        refuse(frame = JsonObject(request + ("expires_ms" to JsonPrimitive("100000"))))
    }
}
