package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DeviceFileAcceptanceEnvelopeTest {
    private val now=1_800_000_000_000L
    private fun message()=TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
        put("format",1); put("offer_id","11111111-1111-4111-8111-111111111111"); put("transfer_id","a".repeat(32))
        put("manifest_sha256","b".repeat(64)); put("acceptance_sha256","c".repeat(64))
        put("permission_epoch","d".repeat(64)); put("destination_token","e".repeat(64))
    },60_000,now)
    @Test fun exactAcceptanceIsMetadataNotASourceGrantOrSavedReceipt() {
        val parsed=DeviceFileAcceptanceEnvelope.parse(message(),now)
        assertEquals("a".repeat(32),parsed.transferId); assertEquals("e".repeat(64),parsed.destinationToken)
        for ((key,value) in listOf("format" to JsonPrimitive(true),"offer_id" to JsonPrimitive("wrong"),
            "transfer_id" to JsonPrimitive("A".repeat(32)),"permission_epoch" to JsonPrimitive("old"),
            "path" to JsonPrimitive("/private"),"saved" to JsonPrimitive(true),"read_granted" to JsonPrimitive(true))) {
            val original=message()
            val invalid=JsonObject(original+("body" to JsonObject(original["body"]!!.jsonObject+(key to value))))
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileAcceptanceEnvelope.parse(invalid,now) }
        }
    }
    @Test fun completeAcceptanceEnvelopeHasStrictKindTtlAndDeadline() {
        val original=message()
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileAcceptanceEnvelope.parse(original,now+60_000) }
        for ((key,value) in listOf("kind" to JsonPrimitive(DeviceFileControl.KIND),"expires_ms" to JsonPrimitive(now+60_001))) {
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileAcceptanceEnvelope.parse(JsonObject(original+(key to value)),now) }
        }
    }

    @Test fun sharedAcceptanceGoldenHasExactCanonicalBytesAcrossNativeCodecs() {
        val vector=Json.parseToJsonElement(java.io.File("../contracts/file-transfer-acceptance-v1-vectors.json").readText()).jsonObject
        val wire=vector["acceptance"]!!.jsonObject
        assertEquals("e".repeat(64),DeviceFileAcceptanceEnvelope.parse(wire,now).destinationToken)
        val bytes=TelefonKanonisch.bytes(wire)
        assertEquals(vector["canonical_bytes"]!!.jsonPrimitive.content.toInt(),bytes.size)
        assertEquals(vector["canonical_sha256"]!!.jsonPrimitive.content,
            java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) })
    }
}
