package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.util.Base64

internal data class DeviceFileChunkRequest(val requestId: String, val expires: Long, val transferId: String,
    val manifestSha256: String, val acceptanceSha256: String, val permissionEpoch: String,
    val destinationToken: String, val fileId: String, val chunkIndex: Int)

/** Chunk bytes are source data only, never publication/checkpoint/SaveACKs. */
internal object DeviceFileChunkEnvelope {
    const val REQUEST = "file_transfer.chunk.request"
    const val RESULT = "file_transfer.chunk"
    fun parseRequest(message: JsonObject, now: Long = System.currentTimeMillis()): DeviceFileChunkRequest {
        fun fail(): Nothing = DeviceFileControl.fail("file_chunk_invalid_request")
        if (TelefonKanonisch.bytes(message).size > DeviceFileControl.MAX_WIRE_BYTES) fail()
        TelefonNachrichten.validateHeader(message,now)
        if (message.string("kind") != REQUEST || now >= message.long("expires_ms") ||
            message.long("expires_ms")-message.long("created_ms") > DeviceFileControl.MAX_TTL_MS) fail()
        val body=message["body"] as? JsonObject ?: fail()
        if (body.keys != setOf("format","transfer_id","manifest_sha256","acceptance_sha256","permission_epoch","destination_token","file_id","chunk_index") ||
            body["format"] != JsonPrimitive(1)) fail()
        fun text(name: String)=(body[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        fun hash(name: String)=text(name).takeIf(DeviceFileControl::hash) ?: fail()
        fun id(name: String)=text(name).takeIf { Regex("[0-9a-f]{32}").matches(it) } ?: fail()
        val index=(body["chunk_index"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toIntOrNull()
            ?.takeIf { it in 0 until (DeviceFileManifest.MAX_FILE_BYTES / DeviceFileManifest.CHUNK_BYTES).toInt() } ?: fail()
        return DeviceFileChunkRequest(message.string("message_id"),message.long("expires_ms"),id("transfer_id"),hash("manifest_sha256"),
            hash("acceptance_sha256"),hash("permission_epoch"),hash("destination_token"),id("file_id"),index)
    }

    fun response(request: DeviceFileChunkRequest, data: ByteArray, now: Long = System.currentTimeMillis()): JsonObject {
        if (data.isEmpty() || data.size > DeviceFileManifest.CHUNK_BYTES || now >= request.expires)
            DeviceFileControl.fail("file_chunk_invalid_response")
        val body=buildJsonObject {
            put("format",1);put("request_id",request.requestId);put("transfer_id",request.transferId)
            put("manifest_sha256",request.manifestSha256);put("acceptance_sha256",request.acceptanceSha256)
            put("permission_epoch",request.permissionEpoch);put("destination_token",request.destinationToken)
            put("file_id",request.fileId);put("chunk_index",request.chunkIndex)
            put("data_base64",Base64.getEncoder().encodeToString(data))
            put("data_sha256",MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it.toInt() and 255) })
        }
        return TelefonNachrichten.message(RESULT,body,minOf(DeviceFileControl.MAX_TTL_MS,request.expires-now),now).also {
            if (TelefonKanonisch.bytes(it).size > TelefonParameter.ANWENDUNG_MAX) DeviceFileControl.fail("file_chunk_invalid_response")
        }
    }
}
