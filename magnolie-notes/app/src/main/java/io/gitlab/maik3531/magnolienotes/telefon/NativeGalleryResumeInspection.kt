package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.util.Locale

/** A point-in-time comparison, NOT a renewed cache/offer/chunk authority. */
internal class NativeGalleryResumeInspection private constructor(val jobId: String, val manifestSha256: String,
    val verifiedFiles: Int, val verifiedBytes: Long) {
    val allowsChunkOutput: Boolean get() = false
    val provesDeletion: Boolean get() = false

    companion object {
        fun inspect(senderId: String, job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance, inventory: PhotoSourceInventory,
            scope: GalleryPhotoSourceScope, reader: AndroidGalleryPhotoSource, cancellation: CancellationSignal,
            permitted: () -> Unit, elapsed: () -> Long = DeviceFileControl::monotonicMs): NativeGalleryResumeInspection {
            fun fail(): Nothing = DeviceFileControl.fail("gallery_resume_original_not_revalidated")
            val lease = inventory.lease as? GalleryPhotoSourceLease ?: fail()
            val issued = elapsed(); var last = issued
            fun fresh() {
                cancellation.throwIfCanceled()
                val now = elapsed()
                if (issued < 0 || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS || !scope.isCurrent(lease)) fail()
                last = now; permitted()
            }
            fresh()
            val authority = original.originalAuthority ?: fail()
            val current = lease.receiver
            if (authority.pairingEpoch == null || authority.pairingEpoch != current.pairingEpoch ||
                authority.receiverId != current.peerId || authority.receiverIdentitySha256 != current.identitySha256 ||
                authority.permissionEpoch != current.permissionEpoch || authority.record["tree"] != JsonPrimitive(lease.sourceKey) ||
                authority.record["epoch"] != JsonPrimitive(lease.sourceEpoch) || lease.access.mediaStoreVersion == null ||
                lease.access.coverage == GalleryReadCoverage.SELECTED_ONLY) fail()
            val snapshot = job.snapshot ?: fail()
            val manifest = DeviceFileManifest.parse(snapshot["manifest"] as? JsonObject ?: fail())
            if (manifest.senderId != senderId || manifest.receiverId != current.peerId) fail()
            val origins = GalleryPhotoOrigins.parse(snapshot["source_origins"] as? JsonObject ?: fail(), manifest)
            val entries = origins.entries.map { origin -> inventory.entries.singleOrNull { it.documentId == origin.nativeMember } ?: fail() }
            val currentOrigins = GalleryPhotoOrigins.capture(lease, entries, manifest)
            if (!origins.entries.zip(currentOrigins.entries).all { (old, new) ->
                    old.fileId == new.fileId && old.nativeMember == new.nativeMember && old.photoId == new.photoId }) fail()
            var verified = 0L
            val buffer = ByteArray(64 * 1024)
            try {
                entries.zip(manifest.files).forEach { (entry, file) ->
                    fresh(); reader.verifyMetadata(lease, entry, cancellation)
                    val digest = MessageDigest.getInstance("SHA-256")
                    var count = 0L
                    reader.openRead(lease, entry, cancellation).use { input ->
                        while (count < file.size) {
                            fresh()
                            val size = input.read(buffer, 0, minOf(buffer.size.toLong(), file.size - count).toInt())
                            if (size <= 0) fail()
                            fresh(); digest.update(buffer, 0, size); count += size
                            buffer.fill(0)
                        }
                        fresh(); if (input.read() != -1) fail(); fresh()
                    }
                    reader.verifyMetadata(lease, entry, cancellation); fresh()
                    val actual = digest.digest().joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
                    if (actual != file.sha256 || count != file.size) fail()
                    verified += count
                }
            } finally { buffer.fill(0) }
            fresh()
            return NativeGalleryResumeInspection(job.id, manifest.fingerprint, manifest.files.size, verified)
        }
    }
}
