package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DeviceFileSavedEnvelopeTest {
    private val now=1_800_000_000_000L
    private fun manifest(count: Int)=DeviceFileManifest.parse(buildJsonObject {
        put("format",1);put("transfer_id","a".repeat(32));put("source_id","b".repeat(32))
        put("sender_id","sender_fixture_01");put("receiver_id","receiver_fixture_01");put("chunk_bytes",65536);put("total_bytes",5*count)
        put("files",JsonArray((1..count).map { index -> buildJsonObject {
            put("id","%032x".format(index));put("path","Camera/a%03d.jpg".format(index));put("size",5);put("sha256","f".repeat(64))
        } }))
    })
    private fun message(manifest: DeviceFileManifest)=TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND,buildJsonObject {
        put("format",1);put("transfer_id",manifest.transferId);put("manifest_sha256",manifest.fingerprint)
        put("acceptance_sha256","c".repeat(64));put("permission_epoch","d".repeat(64));put("destination_token","e".repeat(64))
        put("receipts",JsonArray(manifest.files.map { file -> buildJsonObject {
            put("file_id",file.id);put("size",file.size);put("sha256",file.sha256);put("receipt_sha256","0".repeat(64))
        } }))
    },60_000,now)
    @Test fun fullManifestConfirmationFitsTheApplicationBudgetAndNeverExposesPaths() {
        val manifest=manifest(128);val message=message(manifest);val wire=TelefonKanonisch.bytes(message)
        assertTrue(wire.size>DeviceFileControl.MAX_WIRE_BYTES);assertTrue(wire.size<=TelefonParameter.ANWENDUNG_MAX)
        assertFalse(wire.decodeToString().contains("Camera/"))
        assertEquals(128,DeviceFileSavedEnvelope.parse(message,manifest,now).members.size)
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSavedEnvelope.parse(message,manifest,now+60_000) }
    }
    @Test fun partialDuplicateWrongHashAndAuthorityOrQuotaClaimsCannotBecomeSavedConfirmation() {
        val manifest=manifest(2);val original=message(manifest);val body=original["body"]!!.jsonObject
        val receipts=body["receipts"]!!.jsonArray
        val invalidBodies=listOf(
            body+("receipts" to JsonArray(listOf(receipts[0]))),body+("receipts" to JsonArray(listOf(receipts[0],receipts[0]))),
            body+("success" to JsonPrimitive(true)),body+("quota_retired" to JsonPrimitive(true)),body+("path" to JsonPrimitive("/private")),
            body+("receipts" to JsonArray(listOf(JsonObject(receipts[0].jsonObject+("size" to JsonPrimitive(true))),receipts[1]))))
        invalidBodies.forEach { changed ->
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileSavedEnvelope.parse(JsonObject(original+("body" to JsonObject(changed))),manifest,now) }
        }
    }
}
