package io.gitlab.maik3531.magnolienotes.telefon

import android.os.CancellationSignal
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.Locale
import java.util.UUID

internal class PhotoSnapshotBuildFailure(val pending: ProtectedPhotoSourceSnapshot, cause: Exception) :
    IOException("Photo source snapshot was not completed; native owned-cache recovery is required.", cause)

/** Native private snapshot only. No automatic source selection or network/file receipt.
 * The coordinator supplies a NEW empty reserved private directory (never a SAF URI).
 * This primitive does not allocate jobs or claim restart/job-index/quota integration.
 */
internal class ProtectedPhotoSourceSnapshot private constructor(
    private val root: File, private val protection: DeviceTransferProtection,
    private val scope: NativePhotoSourceAuthority, val lease: NativePhotoSourceLease, private val cancellation: CancellationSignal,
    private val owner: String, private val rootKey: Any, private val boundary: (String) -> Unit,
    originalContext: NativePhotoSourceContext? = null
) {
    private data class Witness(val key: String, val digest: String)
    private val owned = linkedMapOf<String, Witness>()
    private var sealedManifest: DeviceFileManifest? = null
    private var origins: GalleryPhotoOrigins? = null
    private var retired = false
    private val sourceDomain = originalContext?.snapshotDomain() ?: hash(TelefonKanonisch.bytes(JsonObject(mapOf(
        "tree" to JsonPrimitive(lease.sourceKey), "source_version" to JsonPrimitive(lease.version),
        "source_epoch" to JsonPrimitive(lease.sourceEpoch), "receiver" to JsonPrimitive(lease.receiver.peerId),
        "receiver_identity" to JsonPrimitive(lease.receiver.identitySha256), "read_grant" to JsonPrimitive(lease.readGrantToken),
        "permission_epoch" to JsonPrimitive(lease.receiver.permissionEpoch)) +
        (lease.receiver.pairingEpoch?.let { mapOf("pairing_epoch" to JsonPrimitive(it)) } ?: emptyMap()))))
    private val domain = "photo-source-snapshot-v1/$owner/$sourceDomain/"
    val manifest: DeviceFileManifest get() = synchronized(this) {
        fresh(); sealedManifest ?: fail("photo_snapshot_not_sealed")
    }
    val galleryOrigins: GalleryPhotoOrigins? get() = synchronized(this) {
        manifest // Requires a current sealed native source, not just metadata.
        origins
    }

    private fun fresh() {
        cancellation.throwIfCanceled()
        if (retired || !scope.isCurrent(lease)) fail("photo_snapshot_source_revoked")
        directory()
    }
    private fun directory(checkOwner: Boolean = true) {
        val metadata = attributes(root)
        if (!metadata.isDirectory || metadata.fileKey() != rootKey || root.canonicalFile != root) fail("photo_snapshot_directory_changed")
        privateEntry(root)
        if (checkOwner && "owner.enc" in owned) cipher("owner.enc", MAX_METADATA)
    }
    private fun privateEntry(file: File) {
        if (Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root.toPath(), NOFOLLOW_LINKS)) fail("photo_snapshot_not_private")
        if (file != root && (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1)
            fail("photo_snapshot_linked_entry")
    }
    private fun create(name: String, clear: ByteArray) {
        fresh()
        val cipher = protection.seal(clear, domain + name)
        fresh()
        val path = root.toPath().resolve(name)
        // CREATE_NEW only; publication never replaces any pre-existing bytes.
        FileChannel.open(path, setOf(WRITE, CREATE_NEW, NOFOLLOW_LINKS),
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))).use { channel ->
            val fileKey = attributes(path.toFile()).fileKey() ?: fail("photo_snapshot_file_identity_unavailable")
            try {
                val bytes = ByteBuffer.wrap(cipher)
                while (bytes.hasRemaining()) { fresh(); channel.write(bytes) }
                channel.force(true)
                owned[name] = Witness(fileKey.toString(), hash(cipher))
            } catch (error: Exception) {
                // Only a fully durable ciphertext is adopted. Unknown partial
                // bytes block cleanup instead of being guessed/deleted.
                throw error
            }
        }
        synchronisiereOrdner(root)
        val actual = read(name, clear.size)
        try { if (!actual.contentEquals(clear)) fail("photo_snapshot_write_readback_failed") }
        finally { actual.fill(0) }
    }
    private fun cipher(name: String, maximum: Int): ByteArray {
        directory(false)
        val file = File(root, name)
        val initial = attributes(file)
        if (!initial.isRegularFile || initial.size() !in 29..(maximum + 28).toLong()) fail("photo_snapshot_unsafe_entry")
        privateEntry(file)
        val result = FileChannel.open(file.toPath(), READ, NOFOLLOW_LINKS).use { channel ->
            val bytes = ByteBuffer.allocate(initial.size().toInt() + 1)
            while (bytes.hasRemaining() && channel.read(bytes) != -1) { }
            if (bytes.position() > maximum + 28) fail("photo_snapshot_oversized_entry")
            bytes.flip(); ByteArray(bytes.remaining()).also { bytes.get(it) }
        }
        val after = attributes(file)
        if (initial.fileKey() != after.fileKey() || initial.lastModifiedTime() != after.lastModifiedTime() || initial.size() != result.size.toLong() ||
            owned[name] != Witness(initial.fileKey()?.toString() ?: fail("photo_snapshot_file_identity_unavailable"), hash(result)))
            fail("photo_snapshot_original_witness_changed")
        return result
    }
    private fun read(name: String, maximum: Int): ByteArray {
        fresh()
        val clear = protection.open(cipher(name, maximum), domain + name)
        if (clear.size > maximum) fail("photo_snapshot_cleartext_size_changed")
        try { fresh(); return clear } catch (error: Exception) { clear.fill(0); throw error }
    }

    /** Bytes come only from the sealed private copy, never from a live provider. */
    @Synchronized fun readChunk(fileId: String, index: Int): ByteArray {
        fresh()
        val file = manifest.files.singleOrNull { it.id == fileId } ?: fail("photo_snapshot_unknown_member")
        return readMemberChunk(file, index)
    }
    private fun readMemberChunk(file: DeviceManifestFile, index: Int): ByteArray {
        val chunks = ((file.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
        if (index !in 0 until chunks) fail("photo_snapshot_invalid_chunk")
        val expected = minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), file.size - index.toLong() * DeviceFileManifest.CHUNK_BYTES).toInt()
        val bytes = read("${file.id}-$index.enc", expected + 1)
        if (bytes.size != expected + 1 || bytes[0] != 1.toByte()) fail("photo_snapshot_chunk_size_changed")
        return bytes.copyOfRange(1, bytes.size).also { bytes.fill(0) }
    }

    /** Native protected job-index metadata, never an IPC/storage receipt. */
    @Synchronized internal fun nativeRecord(): JsonObject {
        val sealed = manifest
        exactEntries()
        var bytes = 0L
        val files = owned.map { (name, witness) ->
            val actual = cipher(name, MAX_METADATA)
            bytes += actual.size
            JsonObject(mapOf("name" to JsonPrimitive(name), "key" to JsonPrimitive(witness.key.toString()), "sha256" to JsonPrimitive(witness.digest)))
        }
        fresh()
        val fields = mapOf("format" to JsonPrimitive(if (origins == null) 1 else 2), "owner" to JsonPrimitive(owner), "source_domain" to JsonPrimitive(sourceDomain),
            "root_key" to JsonPrimitive(rootKey.toString()), "cipher_bytes" to JsonPrimitive(bytes), "manifest" to sealed.wire(), "files" to JsonArray(files))
        return JsonObject(fields + (origins?.let { mapOf("source_origins" to it.wire()) } ?: emptyMap()))
    }

    /** Explicit exact-owned-cache cleanup also works after revocation/cancel.
     * No recursive deletion or adoption of unfamiliar entries.
     */
    @Synchronized fun discard() {
        retired = true
        directory()
        exactEntries()
        // Preflight ALL originals before deleting anything, owner marker last.
        owned.keys.forEach { cipher(it, MAX_METADATA) }
        owned.keys.sortedBy { it == "owner.enc" }.forEach {
            cipher(it, MAX_METADATA); Files.delete(File(root, it).toPath()); owned.remove(it)
            boundary("discarded-entry")
        }
        owned.clear(); sealedManifest = null; origins = null
        synchronisiereOrdner(root)
        Files.delete(root.toPath())
        synchronisiereOrdner(root.parentFile)
    }
    private fun exactEntries() {
        val names = linkedSetOf<String>()
        Files.newDirectoryStream(root.toPath()).use { stream ->
            for (entry in stream) {
                val name = entry.fileName.toString()
                if (name !in owned || names.size >= owned.size) fail("photo_snapshot_unfamiliar_entries_preserved")
                names.add(name)
            }
        }
        if (names != owned.keys) fail("photo_snapshot_unfamiliar_entries_preserved")
    }

    companion object {
        private const val MAX_METADATA = 262144
        private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        private fun hash(bytes: ByteArray) = hex(MessageDigest.getInstance("SHA-256").digest(bytes))
        private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        private fun id() = UUID.randomUUID().toString().replace("-", "")
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
        private fun frame(value: JsonObject) = ByteArrayOutputStream().also { TelefonRahmen.schreiben(it, value, MAX_METADATA - 4) }.toByteArray()

        /** The record must come from the existing-key-authenticated native index,
         * never a peer or an arbitrary disk JSON. Re-read all original witnesses.
         */
        internal fun restore(root: File, record: JsonObject, senderId: String, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease,
            protection: DeviceTransferProtection, cancellation: CancellationSignal): ProtectedPhotoSourceSnapshot =
            restoreChecked(root, record, senderId, scope, lease, protection, cancellation, null)

        internal fun restoreRenewed(root: File, record: JsonObject, senderId: String, scope: NativeGalleryRenewalAuthority,
            lease: GalleryPhotoSourceLease, originalContext: NativePhotoSourceContext, protection: DeviceTransferProtection,
            cancellation: CancellationSignal): ProtectedPhotoSourceSnapshot {
            if (!scope.isCurrent(lease) || originalContext.receiverId != lease.receiver.peerId ||
                originalContext.receiverIdentitySha256 != lease.receiver.identitySha256 || originalContext.pairingEpoch == null ||
                originalContext.pairingEpoch != lease.receiver.pairingEpoch || originalContext.permissionEpoch != lease.receiver.permissionEpoch ||
                originalContext.record["tree"] != JsonPrimitive(lease.sourceKey) || originalContext.record["epoch"] != JsonPrimitive(lease.sourceEpoch))
                fail("photo_snapshot_source_context_changed")
            return restoreChecked(root, record, senderId, scope, lease, protection, cancellation, originalContext)
        }

        private fun restoreChecked(root: File, record: JsonObject, senderId: String, scope: NativePhotoSourceAuthority,
            lease: NativePhotoSourceLease, protection: DeviceTransferProtection, cancellation: CancellationSignal,
            originalContext: NativePhotoSourceContext?): ProtectedPhotoSourceSnapshot {
            fun text(value: JsonObject, field: String): String = (value[field] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: fail("photo_snapshot_invalid_record")
            val hasOrigins = record["format"] == JsonPrimitive(2)
            if (record.keys != setOf("format", "owner", "source_domain", "root_key", "cipher_bytes", "manifest", "files") +
                (if (hasOrigins) setOf("source_origins") else emptySet()) ||
                !hasOrigins && record["format"] != JsonPrimitive(1)) fail("photo_snapshot_invalid_record")
            val manifest = DeviceFileManifest.parse(record["manifest"] as? JsonObject ?: fail("photo_snapshot_invalid_record"))
            val owner = text(record, "owner")
            if (!Regex("[0-9a-f]{32}").matches(owner) || owner != manifest.sourceId || manifest.senderId != senderId ||
                manifest.receiverId != lease.receiver.peerId) fail("photo_snapshot_native_identity_changed")
            val actual = attributes(root)
            if (!actual.isDirectory || actual.fileKey()?.toString() != text(record, "root_key")) fail("photo_snapshot_directory_changed")
            val snapshot = ProtectedPhotoSourceSnapshot(root, protection, scope, lease, cancellation, owner,
                actual.fileKey() ?: fail("photo_snapshot_directory_changed"), {}, originalContext)
            if (snapshot.sourceDomain != text(record, "source_domain")) fail("photo_snapshot_source_context_changed")
            val origins = if (hasOrigins) {
                if (lease !is GalleryPhotoSourceLease) fail("photo_snapshot_wrong_source_kind")
                GalleryPhotoOrigins.parse(record["source_origins"] as? JsonObject ?: fail("photo_snapshot_invalid_record"), manifest, lease)
            } else null // Legacy records must never infer photo identities from names.
            snapshot.fresh()
            val names = mutableSetOf("owner.enc", "manifest.enc")
            manifest.files.forEach { member ->
                if (member.size == 0L) names.add("empty-${member.id}.enc")
                else repeat(((member.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()) {
                    names.add("${member.id}-$it.enc")
                }
            }
            val proofs = record["files"] as? JsonArray ?: fail("photo_snapshot_invalid_record")
            if (proofs.size != names.size) fail("photo_snapshot_invalid_record")
            proofs.forEach { entry ->
                val value = entry as? JsonObject ?: fail("photo_snapshot_invalid_record")
                if (value.keys != setOf("name", "key", "sha256")) fail("photo_snapshot_invalid_record")
                val name = text(value, "name"); val key = text(value, "key"); val digest = text(value, "sha256")
                if (name !in names || key.length !in 1..512 || !Regex("[0-9a-f]{64}").matches(digest) ||
                    snapshot.owned.put(name, Witness(key, digest)) != null) fail("photo_snapshot_invalid_record")
            }
            snapshot.exactEntries()
            var cipherBytes = 0L
            snapshot.owned.keys.forEach { cipherBytes += snapshot.cipher(it, MAX_METADATA).size }
            val rawBytes = record["cipher_bytes"] as? JsonPrimitive ?: fail("photo_snapshot_invalid_record")
            if (rawBytes.isString || !Regex("0|[1-9][0-9]*").matches(rawBytes.content) || rawBytes.content.toLongOrNull() != cipherBytes)
                fail("photo_snapshot_invalid_record")
            fun metadata(name: String): JsonObject = ByteArrayInputStream(snapshot.read(name, MAX_METADATA)).use { input ->
                TelefonRahmen.lesen(input, MAX_METADATA - 4).also { if (input.read() != -1) fail("photo_snapshot_manifest_trailing_data") }
            }
            val ownerRecord = metadata("owner.enc")
            if (ownerRecord.keys != setOf("format", "plan") || ownerRecord["format"] != JsonPrimitive(1)) fail("photo_snapshot_invalid_record")
            val plan = DeviceFileManifest.parse(ownerRecord["plan"] as? JsonObject ?: fail("photo_snapshot_invalid_record"))
            if (plan.transferId != manifest.transferId || plan.sourceId != manifest.sourceId || plan.senderId != manifest.senderId ||
                plan.receiverId != manifest.receiverId || plan.totalBytes != manifest.totalBytes || plan.files.size != manifest.files.size ||
                !plan.files.zip(manifest.files).all { (a, b) -> a.id == b.id && a.path == b.path && a.size == b.size && a.sha256 == "0".repeat(64) })
                fail("photo_snapshot_plan_changed")
            if (DeviceFileManifest.parse(metadata("manifest.enc")).fingerprint != manifest.fingerprint) fail("photo_snapshot_manifest_readback_changed")
            manifest.files.forEach { member ->
                val digest = MessageDigest.getInstance("SHA-256")
                val chunks = ((member.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
                repeat(chunks) { snapshot.readMemberChunk(member, it).also { bytes -> digest.update(bytes); bytes.fill(0) } }
                if (member.size == 0L && !snapshot.read("empty-${member.id}.enc", 1).contentEquals(byteArrayOf(1))) fail("photo_snapshot_empty_marker_missing")
                if (hex(digest.digest()) != member.sha256) fail("photo_snapshot_final_digest_changed")
            }
            snapshot.fresh(); snapshot.sealedManifest = manifest; snapshot.origins = origins
            return snapshot
        }

        /** Native call only; senderId comes from the existing authenticated local identity.
         * On failure the caller retains the exact allocated directory for guarded recovery;
         * it must not report a completed source or reuse partial chunks as proofs.
         */
        internal fun selectFrozen(original: ProtectedPhotoSourceSnapshot, root: File, selected: List<String>,
            cancellation: CancellationSignal, boundary: (String) -> Unit = {}): ProtectedPhotoSourceSnapshot {
            val source = original.manifest
            val lease = original.lease as? GalleryPhotoSourceLease ?: fail("gallery_media_native_scope_required")
            if (selected.isEmpty() || selected != selected.sorted().distinct() || selected.any { id -> source.files.none { it.id == id } })
                fail("photo_snapshot_invalid_selection")
            val files = source.files.filter { it.id in selected }
            require(root.isAbsolute && root.canonicalFile == root)
            val metadata = attributes(root)
            if (!metadata.isDirectory || metadata.fileKey() == null || Files.newDirectoryStream(root.toPath()).use { it.iterator().hasNext() })
                fail("photo_snapshot_new_private_directory_required")
            val owner = id()
            val members = (source.wire()["files"] as JsonArray).filter { item ->
                selected.any { (item as JsonObject)["id"] == JsonPrimitive(it) }
            }
            val value = JsonObject(source.wire() + mapOf("source_id" to JsonPrimitive(owner), "transfer_id" to JsonPrimitive(id()),
                "files" to JsonArray(members), "total_bytes" to JsonPrimitive(files.sumOf { it.size })))
            val manifest = DeviceFileManifest.parse(value)
            val snapshot = ProtectedPhotoSourceSnapshot(root, original.protection, original.scope, lease, cancellation,
                owner, metadata.fileKey()!!, boundary)
            try {
                snapshot.fresh(); original.fresh()
                val plan = JsonObject(manifest.wire() + ("files" to JsonArray(members.map {
                    JsonObject((it as JsonObject) + ("sha256" to JsonPrimitive("0".repeat(64))))
                })))
                snapshot.create("owner.enc", frame(JsonObject(mapOf("format" to JsonPrimitive(1), "plan" to plan))))
                files.forEach { file ->
                    val digest = MessageDigest.getInstance("SHA-256")
                    val chunks = ((file.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
                    repeat(chunks) { index ->
                        snapshot.fresh()
                        val bytes = original.readChunk(file.id, index)
                        try {
                            digest.update(bytes)
                            val clear = byteArrayOf(1) + bytes
                            try { snapshot.create("${file.id}-$index.enc", clear) } finally { clear.fill(0) }
                        } finally { bytes.fill(0) }
                    }
                    if (hex(digest.digest()) != file.sha256) fail("photo_snapshot_final_digest_changed")
                    if (file.size == 0L) snapshot.create("empty-${file.id}.enc", byteArrayOf(1))
                }
                snapshot.create("manifest.enc", frame(manifest.wire()))
                files.forEach { file ->
                    val digest = MessageDigest.getInstance("SHA-256")
                    val chunks = ((file.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
                    repeat(chunks) { index -> snapshot.readMemberChunk(file, index).also { digest.update(it); it.fill(0) } }
                    if (hex(digest.digest()) != file.sha256) fail("photo_snapshot_final_digest_changed")
                }
                snapshot.fresh(); original.fresh()
                snapshot.sealedManifest = manifest
                snapshot.origins = original.galleryOrigins?.selected(manifest, lease) ?: fail("gallery_media_origins_required")
                return snapshot
            } catch (error: Exception) { throw PhotoSnapshotBuildFailure(snapshot, error) }
        }

        fun freeze(root: File, inventory: PhotoSourceInventory, senderId: String, scope: NativePhotoSourceAuthority,
            source: PhotoSourceAccess, protection: DeviceTransferProtection,
            cancellation: CancellationSignal = CancellationSignal(), boundary: (String) -> Unit = {}): ProtectedPhotoSourceSnapshot {
            require(root.isAbsolute && root.canonicalFile == root)
            val metadata = attributes(root)
            if (!metadata.isDirectory || metadata.fileKey() == null ||
                Files.newDirectoryStream(root.toPath()).use { it.iterator().hasNext() }) fail("photo_snapshot_new_private_directory_required")
            if (inventory.entries.size !in 1..DeviceFileManifest.MAX_FILES) fail("photo_snapshot_empty_or_unbounded_inventory")
            // Validate all paths/counts/sizes/receiver identity BEFORE any source IO.
            val sourceId = id(); val transferId = id()
            val planned = inventory.entries.map { entry -> DeviceManifestFile(id(), entry.relativePath, entry.advertisedBytes, "0".repeat(64)) }
            fun manifest(files: List<DeviceManifestFile>): DeviceFileManifest = DeviceFileManifest.parse(JsonObject(mapOf(
                "format" to JsonPrimitive(1), "transfer_id" to JsonPrimitive(transferId), "source_id" to JsonPrimitive(sourceId),
                "sender_id" to JsonPrimitive(senderId), "receiver_id" to JsonPrimitive(inventory.lease.receiver.peerId),
                "chunk_bytes" to JsonPrimitive(DeviceFileManifest.CHUNK_BYTES), "total_bytes" to JsonPrimitive(files.sumOf { it.size }),
                "files" to JsonArray(files.map { JsonObject(mapOf("id" to JsonPrimitive(it.id), "path" to JsonPrimitive(it.path),
                    "size" to JsonPrimitive(it.size), "sha256" to JsonPrimitive(it.sha256))) }))))
            val plan = manifest(planned)
            val origins = (inventory.lease as? GalleryPhotoSourceLease)?.let { GalleryPhotoOrigins.capture(it, inventory.entries, plan) }
            val snapshot = ProtectedPhotoSourceSnapshot(root, protection, scope, inventory.lease, cancellation, sourceId, metadata.fileKey()!!, boundary)
            try {
                snapshot.fresh()
                snapshot.create("owner.enc", frame(JsonObject(mapOf("format" to JsonPrimitive(1), "plan" to plan.wire()))))
                val complete = inventory.entries.zip(planned).map { (entry, member) ->
                    source.verifyMetadata(inventory.lease, entry, cancellation)
                    val digest = snapshot.stream(source, entry, member, true)
                    source.verifyMetadata(inventory.lease, entry, cancellation)
                    if (snapshot.stream(source, entry, member, false) != digest) fail("photo_snapshot_live_source_changed")
                    source.verifyMetadata(inventory.lease, entry, cancellation)
                    member.copy(sha256 = digest)
                }
                val result = manifest(complete)
                // This local bound is NOT the later complete offer-envelope check.
                val encoded = frame(result.wire())
                snapshot.create("manifest.enc", encoded)
                val readback = ByteArrayInputStream(snapshot.read("manifest.enc", MAX_METADATA)).use { input ->
                    DeviceFileManifest.parse(TelefonRahmen.lesen(input, MAX_METADATA - 4)).also {
                        if (input.read() != -1) fail("photo_snapshot_manifest_trailing_data")
                    }
                }
                if (readback.fingerprint != result.fingerprint) fail("photo_snapshot_manifest_readback_changed")
                // Final actual private-byte readback, whole SHA plus exact planned size.
                complete.forEach { member ->
                    val hash = MessageDigest.getInstance("SHA-256")
                    val chunks = ((member.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
                    repeat(chunks) { index -> snapshot.readMemberChunk(member, index).also { hash.update(it); it.fill(0) } }
                    if (member.size == 0L && !snapshot.read("empty-${member.id}.enc", 1).contentEquals(byteArrayOf(1))) fail("photo_snapshot_empty_marker_missing")
                    if (hex(hash.digest()) != member.sha256) fail("photo_snapshot_final_digest_changed")
                }
                snapshot.fresh()
                snapshot.sealedManifest = readback
                snapshot.origins = origins
                return snapshot
            } catch (error: Exception) { throw PhotoSnapshotBuildFailure(snapshot, error) }
        }
    }

    private fun stream(source: PhotoSourceAccess, entry: PhotoInventoryEntry, member: DeviceManifestFile, persist: Boolean): String {
        fresh()
        val digest = MessageDigest.getInstance("SHA-256")
        source.openRead(lease, entry, cancellation).use { input ->
            var remaining = member.size
            var index = 0
            while (remaining > 0) {
                fresh()
                val size = minOf(remaining, DeviceFileManifest.CHUNK_BYTES.toLong()).toInt()
                val bytes = ByteArray(size)
                try {
                    var filled = 0
                    var zeroReads = 0
                    while (filled < size) {
                        fresh()
                        val count = input.read(bytes, filled, size - filled)
                        fresh()
                        if (count < 0) fail("photo_snapshot_live_source_truncated")
                        if (count == 0) { if (++zeroReads > 8) fail("photo_snapshot_stalled_source") }
                        else { filled += count; zeroReads = 0 }
                    }
                    digest.update(bytes)
                    if (persist) {
                        val clear = byteArrayOf(1) + bytes
                        try { create("${member.id}-$index.enc", clear) } finally { clear.fill(0) }
                    }
                } finally { bytes.fill(0) }
                index++; remaining -= size
            }
            fresh()
            if (input.read() != -1) fail("photo_snapshot_live_source_grew")
            fresh()
            if (persist && member.size == 0L) create("empty-${member.id}.enc", byteArrayOf(1))
        }
        fresh()
        return hex(digest.digest())
    }
}
