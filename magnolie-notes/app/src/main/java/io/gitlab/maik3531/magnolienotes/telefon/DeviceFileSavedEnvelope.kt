package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.util.Collections

internal data class RemoteSavedMember(val fileId: String, val size: Long, val sha256: String, val receiptSha256: String)

/** Authenticated receiver's historical save assertion. Not a native phone save
 * receipt, current file presence, quota retirement or whole-sync success. */
internal class RemoteSavedConfirmation(val transferId: String, val manifestSha256: String, val acceptanceSha256: String,
    val permissionEpoch: String, val destinationToken: String, val expires: Long, members: List<RemoteSavedMember>, val fingerprint: String) {
    val members: List<RemoteSavedMember> = Collections.unmodifiableList(members.toList())
}

internal object DeviceFileSavedEnvelope {
    const val KIND = "file_transfer.saved"
    fun parse(message: JsonObject, manifest: DeviceFileManifest, now: Long = System.currentTimeMillis()): RemoteSavedConfirmation {
        fun fail(): Nothing = DeviceFileControl.fail("file_saved_invalid_confirmation")
        if (TelefonKanonisch.bytes(message).size > TelefonParameter.ANWENDUNG_MAX) fail()
        TelefonNachrichten.validateHeader(message,now)
        if (message.string("kind") != KIND || now >= message.long("expires_ms") ||
            message.long("expires_ms")-message.long("created_ms") > DeviceFileControl.MAX_TTL_MS) fail()
        val body=message["body"] as? JsonObject ?: fail()
        if (body.keys != setOf("format","transfer_id","manifest_sha256","acceptance_sha256","permission_epoch","destination_token","receipts") ||
            body["format"] != JsonPrimitive(1)) fail()
        fun text(name: String)=(body[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        fun hash(name: String)=text(name).takeIf(DeviceFileControl::hash) ?: fail()
        if (text("transfer_id") != manifest.transferId || hash("manifest_sha256") != manifest.fingerprint) fail()
        val receipts=body["receipts"] as? JsonArray ?: fail()
        if (receipts.size != manifest.files.size) fail()
        val members=receipts.zip(manifest.files).map { (raw,file) ->
            val receipt=raw as? JsonObject ?: fail()
            if (receipt.keys != setOf("file_id","size","sha256","receipt_sha256") || receipt["file_id"] != JsonPrimitive(file.id) ||
                receipt["size"] != JsonPrimitive(file.size) || receipt["sha256"] != JsonPrimitive(file.sha256)) fail()
            val proof=(receipt["receipt_sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf(DeviceFileControl::hash) ?: fail()
            RemoteSavedMember(file.id,file.size,file.sha256,proof)
        }
        return RemoteSavedConfirmation(manifest.transferId,manifest.fingerprint,hash("acceptance_sha256"),hash("permission_epoch"),
            hash("destination_token"),message.long("expires_ms"),members,
            DeviceFileControl.digest("magnolie-remote-file-save-confirmation-v1\u0000",body))
    }
}
