package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DeviceFileSourceCommandTest {
    private val now = 1_800_000_000_000L
    private fun message(body: JsonObject) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, body, 60_000, now)
    private val status = buildJsonObject { put("format", 1); put("operation", "status") }
    private val configure = buildJsonObject {
        put("format", 1); put("operation", "configure"); put("expected_version", "a".repeat(64)); put("enabled", true)
        put("kinds", JsonArray(listOf(JsonPrimitive("camera"), JsonPrimitive("screenshots"))))
    }

    @Test fun strictMetadataCommandsContainNoNativeAuthorityOrReadRunSettings() {
        val parsed = DeviceFileSourceCommand.parse(message(configure), now)
        assertEquals("configure", parsed.operation); assertEquals("a".repeat(64), parsed.expectedVersion)
        assertEquals(setOf(GallerySourceKind.CAMERA, GallerySourceKind.SCREENSHOTS), parsed.kinds)
        assertEquals("status", DeviceFileSourceCommand.parse(message(status), now).operation)
        for ((key, value) in listOf("send_files" to JsonPrimitive(true), "read_granted" to JsonPrimitive(true),
            "destination" to JsonPrimitive("/personal/path"), "automatic" to JsonPrimitive(true), "owner" to JsonPrimitive("native"))) {
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSourceCommand.parse(message(JsonObject(configure + (key to value))), now) }
        }
    }

    @Test fun aliasesUnknownKindsDuplicatesStaleVersionsAndUnsupportedRunsFailBeforeExecution() {
        val invalid = listOf(
            configure + ("enabled" to JsonPrimitive("true")), configure + ("enabled" to JsonPrimitive(1)),
            configure + ("expected_version" to JsonPrimitive("absent")), configure + ("format" to JsonPrimitive(true)),
            configure + ("kinds" to JsonArray(listOf(JsonPrimitive("camera"), JsonPrimitive("camera")))),
            configure + ("kinds" to JsonArray(listOf(JsonPrimitive("screenshots"), JsonPrimitive("camera")))),
            configure + ("kinds" to JsonArray(listOf(JsonPrimitive("CAMERA")))),
            configure + ("kinds" to JsonArray(emptyList())), status + ("operation" to JsonPrimitive("run")))
        invalid.forEach { body -> assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSourceCommand.parse(message(JsonObject(body)), now) } }
    }

    @Test fun completeEnvelopeHasStrictKindBudgetAndDeadline() {
        val valid = message(status)
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSourceCommand.parse(valid, now + 60_000) }
        for ((key, value) in listOf("kind" to JsonPrimitive(DeviceFileControl.KIND), "expires_ms" to JsonPrimitive(now + 60_001),
            "extra" to JsonPrimitive("x".repeat(9000)))) {
            assertThrows(Exception::class.java) { DeviceFileSourceCommand.parse(JsonObject(valid + (key to value)), now) }
        }
    }

    @Test fun sharedSourceCommandGoldenHasTheSameCanonicalBytesAndStrictSelection() {
        val vector = Json.parseToJsonElement(java.io.File("../contracts/file-transfer-sources-v1-vectors.json").readText()).jsonObject
        val message = vector["configure"]!!.jsonObject
        val command = DeviceFileSourceCommand.parse(message, vector["now_ms"]!!.jsonPrimitive.content.toLong())
        val bytes = TelefonKanonisch.bytes(message)
        assertEquals(vector["canonical_bytes"]!!.jsonPrimitive.content.toInt(), bytes.size)
        assertEquals(vector["canonical_sha256"]!!.jsonPrimitive.content,
            java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) })
        assertEquals(setOf(GallerySourceKind.CAMERA, GallerySourceKind.SCREENSHOTS), command.kinds)
    }

    @Test fun discoveryAndPagingRequireTheExactPolicyVersionAndCanonicalOpaqueCatalogCursor() {
        val discover = buildJsonObject { put("format", 1); put("operation", "discover"); put("expected_version", "a".repeat(64)) }
        assertEquals("discover", DeviceFileSourceCommand.parse(message(discover), now).operation)
        val page = JsonObject(discover + mapOf("operation" to JsonPrimitive("catalog_page"),
            "catalog_id" to JsonPrimitive("11111111-1111-4111-8111-111111111111"), "after" to JsonPrimitive(1)))
        assertEquals(1, DeviceFileSourceCommand.parse(message(page), now).after)
        for ((key, value) in listOf("after" to JsonPrimitive(true), "after" to JsonPrimitive("1"), "after" to JsonPrimitive(129),
            "catalog_id" to JsonPrimitive("/storage/private"), "expected_version" to JsonPrimitive("stale-label"),
            "send_files" to JsonPrimitive(true))) {
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSourceCommand.parse(message(JsonObject(page + (key to value))), now) }
        }
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSourceCommand.parse(message(JsonObject(discover + ("after" to JsonPrimitive(0)))), now) }
    }
}
