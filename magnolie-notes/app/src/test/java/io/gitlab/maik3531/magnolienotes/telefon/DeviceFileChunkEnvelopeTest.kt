package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DeviceFileChunkEnvelopeTest {
    private val now=1_800_000_000_000L
    private fun message()=TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST,buildJsonObject {
        put("format",1);put("transfer_id","a".repeat(32));put("manifest_sha256","b".repeat(64));put("acceptance_sha256","c".repeat(64))
        put("permission_epoch","d".repeat(64));put("destination_token","e".repeat(64));put("file_id","f".repeat(32));put("chunk_index",0)
    },60_000,now)
    @Test fun requestsBindTheExactAcceptedTransferAndHaveNoPathReceiptOrGrantFields() {
        assertEquals(0,DeviceFileChunkEnvelope.parseRequest(message(),now).chunkIndex)
        for ((key,value) in listOf("chunk_index" to JsonPrimitive(true),"chunk_index" to JsonPrimitive("0"),"chunk_index" to JsonPrimitive(-1),
            "chunk_index" to JsonPrimitive(800),"file_id" to JsonPrimitive("../photo"),"path" to JsonPrimitive("/private"),"saved" to JsonPrimitive(true))) {
            val original=message();val changed=JsonObject(original+("body" to JsonObject(original["body"]!!.jsonObject+(key to value))))
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileChunkEnvelope.parseRequest(changed,now) }
        }
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileChunkEnvelope.parseRequest(message(),now+60_000) }
    }
    @Test fun completeChunkEnvelopeSupportsTheRealChunkBudgetAndExactDataReadback() {
        val request=DeviceFileChunkEnvelope.parseRequest(message(),now)
        for (size in listOf(1,DeviceFileManifest.CHUNK_BYTES)) {
            val bytes=ByteArray(size) { (it%251).toByte() };val response=DeviceFileChunkEnvelope.response(request,bytes,now)
            assertEquals(DeviceFileChunkEnvelope.RESULT,response.string("kind"))
            assertTrue(TelefonKanonisch.bytes(response).size<=TelefonParameter.ANWENDUNG_MAX)
            assertArrayEquals(bytes,java.util.Base64.getDecoder().decode(response["body"]!!.jsonObject.string("data_base64")))
        }
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileChunkEnvelope.response(request,byteArrayOf(),now) }
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileChunkEnvelope.response(request,ByteArray(DeviceFileManifest.CHUNK_BYTES+1),now) }
    }
}
