package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Durable incoming lineage only. Neither an upload acceptance nor MediaStore
 * authority. Planned/inserted rows can never be emitted as file_transfer.saved. */
internal class GalleryIncomingPublication private constructor(internal val body: JsonObject) {
    internal val id: String get() = body.string("id")
    internal val state: String get() = body.string("state")
    internal val row: JsonObject? get() = body["row"] as? JsonObject
    internal val knownOriginalId: String? get() = (body["known_original_id"] as? JsonPrimitive)?.takeIf { it.isString }?.content
    internal val pcOrigin: GalleryPcMediaOrigin? get() = (body["pc_origin"] as? JsonObject)?.let(GalleryPcMediaOrigin::parse)
    internal val grantsWriteAuthority: Boolean get() = false
    internal val isSavedReceipt: Boolean get() = false
    internal val fingerprint: String get() = DeviceFileControl.digest("magnolie-gallery-incoming-publication-v1\u0000", body)

    /** Historical collision identity only, never permission to adopt or mutate
     * an older row. Grant/pairing epochs and manifest changes cannot fork the
     * same sender-selected source/transfer/file identity into another insert. */
    internal fun sameOriginalTransferFile(other: GalleryIncomingPublication): Boolean {
        val first = body.getValue("origin").jsonObject
        val second = other.body.getValue("origin").jsonObject
        val firstBinding = first.getValue("binding").jsonObject
        val secondBinding = second.getValue("binding").jsonObject
        return listOf("source_id", "transfer_id", "file_id").all { first[it] == second[it] } &&
            listOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256")
                .all { firstBinding[it] == secondBinding[it] }
    }

    internal fun samePcSource(other: GalleryIncomingPublication): Boolean {
        val first = pcOrigin ?: return false
        val second = other.pcOrigin ?: return false
        val a = body.getValue("origin").jsonObject.getValue("binding").jsonObject
        val b = other.body.getValue("origin").jsonObject.getValue("binding").jsonObject
        return first.origin == second.origin && listOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256").all { a[it] == b[it] }
    }

    internal fun withInsertedRow(witness: JsonObject): GalleryIncomingPublication {
        if (state != "inserting" || row != null) fail()
        return parse(JsonObject(body + mapOf("state" to JsonPrimitive("inserted"), "row" to witness)))
    }

    internal fun beforeInsert(): GalleryIncomingPublication {
        if (state != "planned" || row != null) fail()
        return parse(JsonObject(body + ("state" to JsonPrimitive("inserting"))))
    }

    internal fun beforeCopy(): GalleryIncomingPublication {
        if (state != "inserted" || row == null) fail()
        return parse(JsonObject(body + ("state" to JsonPrimitive("copying"))))
    }

    internal fun withVerifiedCopy(witness: JsonObject): GalleryIncomingPublication {
        val previous = row ?: fail()
        if (state != "copying" || previous.filterKeys { it != "revision" } != witness.filterKeys { it != "revision" } ||
            (witness["revision"] as? JsonPrimitive)?.content?.toLongOrNull()?.let { it >= previous.string("revision").toLong() } != true) fail()
        return parse(JsonObject(body + mapOf("state" to JsonPrimitive("copy_verified"), "row" to witness)))
    }

    internal fun beforePublish(): GalleryIncomingPublication {
        if (state != "copy_verified" || row == null) fail()
        return parse(JsonObject(body + ("state" to JsonPrimitive("publishing"))))
    }

    internal fun withPublishedRow(witness: JsonObject): GalleryIncomingPublication {
        val original = row ?: fail()
        if (state != "publishing" || original.filterKeys { it != "revision" } != witness.filterKeys { it != "revision" } ||
            (witness["revision"] as? JsonPrimitive)?.content?.toLongOrNull()?.let { it > original.string("revision").toLong() } != true) fail()
        return parse(JsonObject(body + mapOf("state" to JsonPrimitive("published"), "row" to witness)))
    }

    companion object {
        internal const val MAX_RECORDS = 4096
        internal const val PREFIX = "gallery-incoming-v1/"
        internal fun plan(binding: DeviceTransferBinding, manifest: DeviceFileManifest, fileId: String,
            pairingEpoch: String, kind: GalleryMediaType, mimeType: String,
            scope: GalleryIncomingScope? = null): GalleryIncomingPublication {
            val file = manifest.files.singleOrNull { it.id == fileId } ?: fail()
            if (binding.senderId != manifest.senderId || binding.receiverId != manifest.receiverId) fail()
            val identity = buildJsonObject {
                put("binding", binding.snapshot()); put("manifest_sha256", manifest.fingerprint)
                put("transfer_id", manifest.transferId); put("source_id", manifest.sourceId); put("file_id", file.id)
                put("pairing_epoch", pairingEpoch)
            }
            return parse(buildJsonObject {
                val pc = scope?.pcOrigins?.get(fileId)
                put("format", if (pc != null) 3 else if (scope == null) 1 else 2); put("id", DeviceFileControl.digest("magnolie-gallery-incoming-id-v1\u0000", identity))
                if (pc != null) put("pc_origin", pc.body)
                if (scope != null) {
                    put("collection_mode", scope.collectionMode)
                    put("known_original_id", scope.associations[fileId]?.let { JsonPrimitive(it.id) } ?: JsonNull)
                    put("scope_sha256", scope.fingerprint(manifest))
                }
                put("origin", identity); put("state", "planned"); put("row", JsonNull)
                put("size", file.size); put("sha256", file.sha256); put("name", file.path.substringAfterLast('/'))
                put("media_type", kind.uriSegment); put("mime_type", mimeType)
            })
        }

        internal fun parse(value: JsonObject): GalleryIncomingPublication {
            val pc = value["format"] == JsonPrimitive(3)
            val scoped = pc || value["format"] == JsonPrimitive(2)
            if (value.keys != setOf("format", "id", "origin", "state", "row", "size", "sha256", "name", "media_type", "mime_type") +
                (if (scoped) setOf("collection_mode", "known_original_id", "scope_sha256") else emptySet()) + (if (pc) setOf("pc_origin") else emptySet()) ||
                !scoped && value["format"] != JsonPrimitive(1)) fail()
            if (scoped) {
                val mode = text(value, "collection_mode")
                if (mode !in setOf("phone_inventory", "entire_collection") || !DeviceFileControl.hash(text(value, "scope_sha256"))) fail()
                val original = value["known_original_id"]
                if (original == JsonNull) { if (mode == "phone_inventory") fail() }
                else if (!DeviceFileControl.hash(text(value, "known_original_id"))) fail()
                if (pc) {
                    if (mode != "entire_collection" || original != JsonNull) fail()
                    GalleryPcMediaOrigin.parse(value["pc_origin"] as? JsonObject ?: fail())
                }
            }
            val origin = value["origin"] as? JsonObject ?: fail()
            if (origin.keys != setOf("binding", "manifest_sha256", "transfer_id", "source_id", "file_id", "pairing_epoch")) fail()
            val binding = origin["binding"] as? JsonObject ?: fail()
            if (binding.keys != setOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token")) fail()
            // Reuse the actual native binding validator, not a JSON truth flag.
            DeviceTransferBinding(text(binding, "sender_id"), text(binding, "receiver_id"), text(binding, "sender_identity_sha256"),
                text(binding, "receiver_identity_sha256"), text(binding, "permission_epoch"), text(binding, "destination_token"))
            for (field in listOf("manifest_sha256", "pairing_epoch")) if (!DeviceFileControl.hash(text(origin, field))) fail()
            for (field in listOf("transfer_id", "source_id", "file_id")) if (!Regex("[0-9a-f]{32}").matches(text(origin, field))) fail()
            val id = text(value, "id")
            if (id != DeviceFileControl.digest("magnolie-gallery-incoming-id-v1\u0000", origin)) fail()
            val size = (value["size"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull() ?: fail()
            if (size !in 1..DeviceFileManifest.MAX_FILE_BYTES || !DeviceFileControl.hash(text(value, "sha256"))) fail()
            val name = text(value, "name")
            if (!DeviceFileManifest.portablePath(name) || '/' in name) fail()
            val kind = GalleryMediaType.entries.singleOrNull { it.uriSegment == text(value, "media_type") } ?: fail()
            val mime = text(value, "mime_type")
            if (!Regex(if (kind == GalleryMediaType.IMAGES) "image/[a-z0-9.+-]{1,80}" else "video/[a-z0-9.+-]{1,80}").matches(mime)) fail()
            when (text(value, "state")) {
                "planned", "inserting" -> if (value["row"] != JsonNull) fail()
                "inserted", "copying", "copy_verified", "publishing", "published" -> {
                    val row = value["row"] as? JsonObject ?: fail()
                    validateRow(row, kind)
                    if (text(row, "mime_type") != mime) fail()
                }
                else -> fail() // A native publication journal is never a network Saved receipt.
            }
            return GalleryIncomingPublication(value)
        }

        private fun validateRow(row: JsonObject, kind: GalleryMediaType) {
            if (row.keys != setOf("uri", "namespace", "volume", "member", "revision", "path", "name", "mime_type", "owner")) fail()
            val volume = text(row, "volume")
            if (!Regex("[a-z0-9_-]{1,128}").matches(volume)) fail()
            val parts = text(row, "member").split(':')
            if (parts.size != 3 || parts.any { !Regex("0|[1-9][0-9]*").matches(it) || it.toLongOrNull() == null } ||
                parts[0].toLong() <= 0 || parts[2].toLong() <= 0) fail()
            val revision = text(row, "revision").toLongOrNull() ?: fail()
            if (revision < parts[2].toLong() || text(row, "uri") != "content://media/$volume/${kind.uriSegment}/media/${parts[0]}") fail()
            val namespace = text(row, "namespace")
            if (namespace.length !in 1..1024 || namespace.any { it.code < 32 || it.code == 127 }) fail()
            if (text(row, "path") != if (kind == GalleryMediaType.IMAGES) "Pictures/Magnolie/" else "Movies/Magnolie/") fail()
            val name = text(row, "name")
            if (!DeviceFileManifest.portablePath(name) || '/' in name || text(row, "owner").length !in 1..255) fail()
        }

        private fun text(value: JsonObject, name: String): String = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_incoming_publication_invalid")
    }
}
