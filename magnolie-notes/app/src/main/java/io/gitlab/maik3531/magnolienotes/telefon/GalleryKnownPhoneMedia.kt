package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** A PC's return reference is untrusted correlation metadata, not admission,
 * source READ, Gallery mutation identity or permission to replay a deletion. */
internal class GalleryPhoneMediaReference private constructor(internal val body: JsonObject) {
    internal fun key(phoneId: String, peerId: String, peerIdentity: String, pairing: String): String =
        DeviceFileControl.digest("magnolie-known-phone-media-id-v1\u0000", buildJsonObject {
            put("phone_id", phoneId); put("peer_id", peerId); put("peer_identity_sha256", peerIdentity)
            put("pairing_epoch", pairing); put("reference", body)
        })
    companion object {
        internal fun parse(value: JsonObject): GalleryPhoneMediaReference {
            if (value.keys != setOf("source_epoch", "photo_id", "media_type", "manifest_sha256", "file_id", "original_size", "original_sha256", "receipt_sha256")) fail()
            for (name in listOf("source_epoch", "photo_id", "manifest_sha256", "original_sha256", "receipt_sha256"))
                if (!DeviceFileControl.hash(text(value, name))) fail()
            if (!Regex("[0-9a-f]{32}").matches(text(value, "file_id")) || GalleryMediaType.entries.none { it.uriSegment == text(value, "media_type") }) fail()
            val size = (value["original_size"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("[1-9][0-9]*").matches(it.content) }
                ?.content?.toLongOrNull() ?: fail()
            if (size !in 1..DeviceFileManifest.MAX_FILE_BYTES) fail()
            return GalleryPhoneMediaReference(value)
        }
        private fun text(value: JsonObject, name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_phone_media_reference_invalid")
    }
}

/** Immutable native historical original association, surviving source-cache
 * retirement. Metadata only: no backup bytes, retention subsystem, renewed
 * permission, complete inventory/deletion evidence or live row authority. */
internal class GalleryKnownPhoneMedia private constructor(internal val body: JsonObject) {
    internal val reference: GalleryPhoneMediaReference get() = GalleryPhoneMediaReference.parse(body["reference"]!!.jsonObject)
    internal val id: String get() = reference.key(body.string("phone_id"), body.string("peer_id"), body.string("peer_identity_sha256"), body.string("pairing_epoch"))
    internal val grantsWriteAuthority: Boolean get() = false
    internal val provesDeletion: Boolean get() = false
    internal val isSavedReceipt: Boolean get() = false
    companion object {
        internal const val PREFIX = "gallery-known-phone-media-v1/"
        internal const val MAX_RECORDS = 4096

        internal fun capture(job: PhotoSourceJob, saved: PhotoSourceRemoteSaved, accepted: PhotoSourceRemoteAcceptance,
            sourceLease: NativePhotoSourceLease?): List<GalleryKnownPhoneMedia> {
            val lease = sourceLease as? GalleryPhotoSourceLease ?: return emptyList()
            val original = accepted.originalAuthority ?: return emptyList()
            if (original.pairingEpoch == null || original.pairingEpoch != lease.receiver.pairingEpoch ||
                original.receiverId != lease.receiver.peerId || original.receiverIdentitySha256 != lease.receiver.identitySha256) return emptyList()
            val snapshot = job.snapshot ?: return emptyList()
            val manifest = DeviceFileManifest.parse(snapshot["manifest"] as? JsonObject ?: fail())
            val raw = snapshot["source_origins"] as? JsonObject ?: return emptyList()
            val namespace = lease.access.mediaStoreVersion ?: return emptyList()
            if (raw["format"] != JsonPrimitive(2)) return emptyList()
            val origins = GalleryPhotoOrigins.parse(raw, manifest, lease)
            if (!origins.hasNativeInsertionWitness) return emptyList() // Never promote legacy/unknown namespaces.
            return manifest.files.mapNotNull { file ->
                if (file.size == 0L) return@mapNotNull null
                val origin = origins.entries.single { it.fileId == file.id }
                val receipt = saved.confirmation.members.single { it.fileId == file.id }
                parse(buildJsonObject {
                    put("format", 1); put("phone_id", manifest.senderId); put("peer_id", manifest.receiverId)
                    put("peer_identity_sha256", original.receiverIdentitySha256); put("pairing_epoch", original.pairingEpoch)
                    put("reference", buildJsonObject {
                        put("source_epoch", original.record.getValue("epoch")); put("photo_id", origin.photoId)
                        put("media_type", lease.activation.mediaType.uriSegment); put("manifest_sha256", manifest.fingerprint)
                        put("file_id", file.id); put("original_size", file.size); put("original_sha256", file.sha256); put("receipt_sha256", receipt.receiptSha256)
                    })
                    put("native_member", origin.nativeMember); put("native_revision", origin.nativeRevision ?: fail()); put("native_namespace", namespace)
                    put("source_job_id", job.id); put("source_job_sha256", job.version); put("source_context_sha256", job.sourceContext)
                    put("native_acceptance_sha256", DeviceFileControl.digest("magnolie-known-phone-original-acceptance-v1\u0000", accepted.record))
                    put("remote_saved_sha256", saved.confirmation.fingerprint)
                })
            }
        }

        internal fun parse(value: JsonObject): GalleryKnownPhoneMedia {
            if (value.keys != setOf("format", "phone_id", "peer_id", "peer_identity_sha256", "pairing_epoch", "reference", "native_member",
                    "native_revision", "native_namespace", "source_job_id", "source_job_sha256", "source_context_sha256", "native_acceptance_sha256", "remote_saved_sha256") ||
                value["format"] != JsonPrimitive(1)) fail()
            fun text(name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            for (name in listOf("phone_id", "peer_id")) if (!DeviceFileControl.id(text(name))) fail()
            if (text("phone_id") == text("peer_id")) fail()
            for (name in listOf("peer_identity_sha256", "pairing_epoch", "source_job_sha256", "source_context_sha256", "native_acceptance_sha256", "remote_saved_sha256"))
                if (!DeviceFileControl.hash(text(name))) fail()
            if (!Regex("[0-9a-f]{32}").matches(text("source_job_id"))) fail()
            GalleryPhoneMediaReference.parse(value["reference"] as? JsonObject ?: fail())
            val member = text("native_member").split(':')
            if (member.size != 3 || member.any { !Regex("0|[1-9][0-9]*").matches(it) || it.toLongOrNull() == null } ||
                member[0].toLong() <= 0 || member[2].toLong() <= 0) fail()
            val revisionText = text("native_revision")
            if (!Regex("0|[1-9][0-9]*").matches(revisionText)) fail()
            val revision = revisionText.toLongOrNull() ?: fail()
            val namespace = text("native_namespace")
            if (revision < member[2].toLong() || namespace.length !in 1..1024 || namespace.any { it.code < 32 || it.code == 127 }) fail()
            return GalleryKnownPhoneMedia(value)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_known_phone_media_invalid")
    }
}
