package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class DeviceFileManifestTest {
    private fun vector() = Json.parseToJsonElement(File("../contracts/file-transfer-manifest-v1-vectors.json").readText())
        .jsonObject["vectors"]!!.jsonArray.first().jsonObject
    private fun raw() = vector()["manifest"]!!.jsonObject
    private fun changed(field: String, value: kotlinx.serialization.json.JsonElement) = JsonObject(raw() + (field to value))
    private fun fileChanged(field: String, value: kotlinx.serialization.json.JsonElement): JsonObject {
        val file = raw()["files"]!!.jsonArray.first().jsonObject
        return changed("files", JsonArray(listOf(JsonObject(file + (field to value)))))
    }
    private fun reject(value: JsonObject) {
        assertThrows(TelefonProtokollFehler::class.java) { DeviceFileManifest.parse(value) }
    }

    @Test fun sharedUtf8FingerprintAndImmutableList() {
        val manifest = DeviceFileManifest.parse(raw())
        assertEquals(vector()["manifest_sha256"]!!.jsonPrimitive.content, manifest.fingerprint)
        assertEquals("Photos/Blüte.jpg", manifest.files.single().path)
        assertEquals(5L, manifest.totalBytes)
        assertEquals(manifest.fingerprint, DeviceFileManifest.parse(manifest.wire()).fingerprint)
        assertThrows(UnsupportedOperationException::class.java) {
            (manifest.files as MutableList<DeviceManifestFile>).clear()
        }
        assertNotEquals(manifest.fingerprint, DeviceFileManifest.parse(fileChanged("path", JsonPrimitive("other.jpg"))).fingerprint)
        assertNotEquals(manifest.fingerprint, DeviceFileManifest.parse(changed("source_id", JsonPrimitive("d".repeat(32)))).fingerprint)
    }

    @Test fun unsafePortablePathsAndCaseAliasesAreRejected() {
        for (path in listOf("../a", "/absolute", "a//b", "a/./b", "a/../b", "C:drive", "a\\b", "a/NUL.txt",
            "a/COM¹.jpg", "CON .jpg", "a/b.", "a/b ", "a/\u202e.jpg", "a/\ud800", "e\u0301.jpg",
            "a".repeat(256), List(17) { "a" }.joinToString("/"))) reject(fileChanged("path", JsonPrimitive(path)))
        val first = raw()["files"]!!.jsonArray.first().jsonObject
        for (path in listOf("photos/BLÜTE.jpg", "Photos/Blüte.jpg/child")) {
            val second = JsonObject(first + mapOf("id" to JsonPrimitive("d".repeat(32)), "path" to JsonPrimitive(path)))
            reject(JsonObject(raw() + mapOf("files" to JsonArray(listOf(first, second)), "total_bytes" to JsonPrimitive(10))))
        }
        val street = JsonObject(first + ("path" to JsonPrimitive("photos/straße.jpg")))
        val upper = JsonObject(street + mapOf("id" to JsonPrimitive("d".repeat(32)), "path" to JsonPrimitive("PHOTOS/STRASSE.jpg")))
        reject(JsonObject(raw() + mapOf("files" to JsonArray(listOf(street, upper)), "total_bytes" to JsonPrimitive(10))))
        val capitalSharp = JsonObject(upper + ("path" to JsonPrimitive("PHOTOS/STRAẞE.jpg")))
        reject(JsonObject(raw() + mapOf("files" to JsonArray(listOf(street, capitalSharp)), "total_bytes" to JsonPrimitive(10))))
    }

    @Test fun onlyExactIntegerAndFieldShapesAreAccepted() {
        for (field in listOf("format", "chunk_bytes", "total_bytes")) {
            reject(changed(field, JsonPrimitive(true))); reject(changed(field, JsonPrimitive("1")))
            reject(changed(field, Json.parseToJsonElement("1.0"))); reject(changed(field, Json.parseToJsonElement("1e0")))
        }
        reject(changed("format", JsonPrimitive(2)))
        reject(changed("total_bytes", JsonPrimitive(6)))
        reject(changed("receiver_id", raw()["sender_id"]!!))
        reject(changed("files", JsonArray(emptyList())))
        reject(changed("extra", JsonPrimitive(true)))
        reject(fileChanged("size", JsonPrimitive(true)))
        reject(fileChanged("grant", JsonPrimitive(true)))
        reject(fileChanged("sha256", JsonPrimitive("A".repeat(64))))
    }
}
