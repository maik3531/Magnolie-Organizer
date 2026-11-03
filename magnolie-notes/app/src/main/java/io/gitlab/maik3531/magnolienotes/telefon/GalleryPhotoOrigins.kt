package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonNull
import java.security.MessageDigest
import java.util.Collections
import java.util.Locale

internal data class GalleryPhotoOrigin(val fileId: String, val nativeMember: String, val photoId: String, val nativeRevision: String? = null)

/** Private native origin mapping, not a shared receipt, baseline, permission or
 * provider URI. It is persisted only inside the authenticated native job record.
 */
internal class GalleryPhotoOrigins private constructor(entries: List<GalleryPhotoOrigin>, private val format: Int,
    val hasNativeInsertionWitness: Boolean) {
    val entries: List<GalleryPhotoOrigin> = Collections.unmodifiableList(entries.toList())
    // date_added can have coarse provider resolution. Correlation is not proof
    // that a deleted/reinserted row is the same mutable photo object. Native
    // mutation ownership/WRITE consent and fresh byte CAS are separate work,
    // even when native insertion-generation witnesses are available.
    val provesMutationIdentity: Boolean get() = false
    internal fun wire() = JsonObject(mapOf("format" to JsonPrimitive(format), "entries" to JsonArray(entries.map {
        val fields = mapOf("file_id" to JsonPrimitive(it.fileId), "native_member" to JsonPrimitive(it.nativeMember), "photo_id" to JsonPrimitive(it.photoId))
        JsonObject(fields + (if (format == 2) mapOf("native_revision" to (it.nativeRevision?.let(::JsonPrimitive) ?: JsonNull)) else emptyMap()))
    })))

    companion object {
        private val member = Regex("[1-9][0-9]{0,18}:(0|[1-9][0-9]{0,18})(:(0|[1-9][0-9]{0,18}))?")
        private fun validMember(value: String) = member.matches(value) && value.split(':').all { it.toLongOrNull() != null }
        private fun validRevision(member: String, revision: String?): Boolean {
            val generation = member.split(':').getOrNull(2) ?: return revision == null
            return revision != null && Regex("0|[1-9][0-9]{0,18}").matches(revision) &&
                revision.toLongOrNull()?.let { it >= generation.toLong() } == true
        }

        internal fun capture(lease: GalleryPhotoSourceLease, inventory: List<PhotoInventoryEntry>, manifest: DeviceFileManifest): GalleryPhotoOrigins {
            if (inventory.size != manifest.files.size) fail()
            val entries = inventory.zip(manifest.files).map { (entry, file) ->
                if (!validMember(entry.documentId) || !validRevision(entry.documentId, entry.nativeRevision) ||
                    entry.relativePath != file.path || entry.advertisedBytes != file.size ||
                    entry.documentUri != "content://media/${lease.album.volume}/${lease.activation.mediaType.uriSegment}/media/${entry.documentId.substringBefore(':')}") fail()
                GalleryPhotoOrigin(file.id, entry.documentId, photoId(lease, manifest.senderId, entry.documentId), entry.nativeRevision)
            }
            return parse(GalleryPhotoOrigins(entries, 2, false).wire(), manifest, lease)
        }

        /** Lease is mandatory for usable restored source metadata. Retirement-
         * only authenticated-cache validation may check structural witnesses
         * without acquiring any live source authority.
         */
        internal fun parse(value: JsonObject, manifest: DeviceFileManifest, lease: GalleryPhotoSourceLease? = null): GalleryPhotoOrigins {
            val format = when (value["format"]) { JsonPrimitive(1) -> 1; JsonPrimitive(2) -> 2; else -> fail() }
            if (value.keys != setOf("format", "entries")) fail()
            val raw = value["entries"] as? JsonArray ?: fail()
            if (raw.size != manifest.files.size) fail()
            val entries = raw.mapIndexed { index, item ->
                val entry = item as? JsonObject ?: fail()
                if (entry.keys != setOf("file_id", "native_member", "photo_id") + (if (format == 2) setOf("native_revision") else emptySet())) fail()
                fun text(name: String) = (entry[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
                val file = text("file_id"); val native = text("native_member"); val photo = text("photo_id")
                val revision = if (format == 1 || entry["native_revision"] == JsonNull) null else text("native_revision")
                if (file != manifest.files[index].id || !validMember(native) || !Regex("[0-9a-f]{64}").matches(photo) ||
                    format == 1 && native.count { it == ':' } != 1 || !validRevision(native, revision) ||
                    lease != null && photo != photoId(lease, manifest.senderId, native)) fail()
                GalleryPhotoOrigin(file, native, photo, revision)
            }
            if (entries.map { it.nativeMember }.distinct().size != entries.size || entries.map { it.photoId }.distinct().size != entries.size) fail()
            val insertionProof = format == 2 && lease?.access?.mediaStoreVersion != null && entries.all {
                it.nativeMember.split(':').getOrNull(2)?.toLongOrNull()?.let { generation -> generation > 0 } == true
            }
            return GalleryPhotoOrigins(entries, format, insertionProof)
        }

        private fun photoId(lease: GalleryPhotoSourceLease, senderId: String, nativeMember: String): String {
            // A known volume namespace survives edits/renames/access refresh.
            // Legacy unknown namespaces cannot safely reuse row IDs across
            // runtime proofs. Neither case implies a complete deletion scan.
            val namespace = lease.access.mediaStoreVersion ?: "runtime:" + lease.readGrantToken
            val bytes = TelefonKanonisch.bytes(JsonObject(mapOf("sender_id" to JsonPrimitive(senderId),
                "source_key" to JsonPrimitive(lease.sourceKey), "media_namespace" to JsonPrimitive(namespace),
                "native_member" to JsonPrimitive(nativeMember))))
            return MessageDigest.getInstance("SHA-256").run {
                update("magnolie-gallery-photo-origin-v1\u0000".toByteArray(Charsets.US_ASCII)); update(bytes)
                digest().joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
            }
        }
        private fun fail(): Nothing = throw PhotoFolderScopeError("gallery_photo_origin_invalid")
    }
}
