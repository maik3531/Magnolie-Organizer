package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardCopyOption.ATOMIC_MOVE
import java.nio.file.StandardCopyOption.REPLACE_EXISTING
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.Base64
import java.util.UUID

/** Dedicated private directory supplied by the native controller, never a SAF/wire path.
 * Uses only existing-key protection. Constructing this store does not open TelefonAblage.
 * All native users must share this publication gate (including repair).
 */
internal class ProtectedPhotoFolderPreferences(
    private val directory: File,
    private val protection: DeviceTransferProtection,
    private val boundary: (String) -> Unit = {},
    private val syncDirectory: (File) -> Unit = ::synchronisiereOrdner
) : PhotoFolderPreferenceStore {
    private val root = directory.toPath()
    private val rootKey: Any
    private val stateName = "photo-source.enc"
    private val fenceName = "photo-source-repair.enc"
    private val domain = "photo-source-preferences-v1/"

    init {
        require(directory.isAbsolute && directory.canonicalFile == directory)
        rootKey = attributes(directory).also { if (!it.isDirectory) fail("photo_store_directory_required") }.fileKey()
            ?: fail("photo_store_directory_identity_unavailable")
    }

    private data class Raw(val bytes: ByteArray, val witness: String)
    internal data class RepairInspection internal constructor(val fenceWitness: String, val stateVersion: String,
        val preference: PhotoFolderPreference?, val matchesWanted: Boolean, val stateWitness: String?)

    override fun read(): PhotoPreferenceSnapshot = gated {
        val state = raw(stateName)
        val preference = state?.let { decodePreference(it.bytes) }
        val fence = raw(fenceName)
        if (fence != null) decodeFence(fence.bytes) // Invalid fences are errors, never absent/off.
        PhotoPreferenceSnapshot(version(state), preference, fence != null)
    }

    override fun compareAndSet(expected: PhotoPreferenceSnapshot, next: PhotoFolderPreference,
        permitted: () -> Boolean): PhotoPreferenceSnapshot = gated {
        if (expected.repairPending || raw(fenceName) != null) fail("photo_source_repair_pending")
        val before = raw(stateName)
        if (PhotoPreferenceSnapshot(version(before), before?.let { decodePreference(it.bytes) }) != expected)
            fail("photo_source_cas_conflict")
        if (expected.preference?.pairingEpoch != null && next.pairingEpoch == null) fail("photo_source_pairing_downgrade")
        if (!permitted()) fail("photo_source_revoked")
        val wanted = protection.seal(encode(preferenceJson(next)), domain + stateName)
        val fenceBytes = protection.seal(encode(JsonObject(mapOf("format" to JsonPrimitive(1),
            "before" to (before?.let { JsonPrimitive(Base64.getEncoder().encodeToString(it.bytes)) } ?: JsonNull),
            "wanted" to JsonPrimitive(Base64.getEncoder().encodeToString(wanted))))), domain + fenceName)
        // This CREATE_NEW fence must be durable before any state replacement.
        create(fenceName, fenceBytes)
        try {
            syncDirectory(directory)
            val fence = requireRaw(fenceName)
            if (!fence.bytes.contentEquals(fenceBytes)) fail("photo_source_fence_readback_failed")
            boundary("fenced")
            val temporary = "photo-source-" + UUID.randomUUID().toString() + ".tmp"
            create(temporary, wanted)
            val temp = requireRaw(temporary)
            if (!temp.bytes.contentEquals(wanted)) fail("photo_source_temporary_readback_failed")
            boundary("before-publication")
            checkRaw(stateName, before)
            checkRaw(fenceName, fence)
            if (!permitted()) fail("photo_source_revoked_at_publication")
            // Cooperative writers/repair hold the native file lock throughout.
            // Unknown external changes observed before publication are preserved.
            Files.move(root.resolve(temporary), root.resolve(stateName), ATOMIC_MOVE, REPLACE_EXISTING)
            syncDirectory(directory)
            boundary("published")
            val saved = requireRaw(stateName)
            if (!saved.bytes.contentEquals(wanted) || decodePreference(saved.bytes) != next || !permitted())
                fail("photo_source_commit_readback_failed")
            clearFence(fence, saved, fenceBytes, permitted)
            PhotoPreferenceSnapshot(version(saved), next)
        } catch (error: Exception) {
            // Preserve originals and concurrent witnesses in the encrypted fence.
            // No rollback to an old preference, key recreation or baseline reset.
            throw error
        }
    }

    /** Native explicit repair only: retain the actually observed before/wanted state.
     * No automatic rollback/roll-forward. Unknown concurrent bytes stay fenced.
     */
    internal fun inspectRepair(): RepairInspection = gated {
        val fence = requireRaw(fenceName)
        val (before, wanted) = decodeFence(fence.bytes)
        val actual = raw(stateName)
        val bytes = actual?.bytes
        val isWanted = bytes != null && bytes.contentEquals(wanted)
        val isBefore = if (before == null) bytes == null else bytes != null && bytes.contentEquals(before)
        if (!isBefore && !isWanted) fail("photo_source_unknown_concurrent_state")
        RepairInspection(fence.witness, version(actual), actual?.let { decodePreference(it.bytes) }, isWanted, actual?.witness)
    }

    internal fun acknowledgeRepair(inspection: RepairInspection, permitted: () -> Boolean) = gated {
        val current = inspectRepairUnlocked()
        if (current != inspection || !permitted()) fail("photo_source_repair_observation_changed")
        val fence = requireRaw(fenceName)
        val state = raw(stateName)
        boundary("repair-acknowledgement")
        if (inspectRepairUnlocked() != inspection || !permitted()) fail("photo_source_repair_observation_changed")
        clearFence(fence, state, fence.bytes, permitted)
    }

    private fun inspectRepairUnlocked(): RepairInspection {
        val fence = requireRaw(fenceName)
        val (before, wanted) = decodeFence(fence.bytes)
        val actual = raw(stateName)
        val isWanted = actual?.bytes?.contentEquals(wanted) == true
        if (!isWanted && !(if (before == null) actual == null else actual?.bytes?.contentEquals(before) == true))
            fail("photo_source_unknown_concurrent_state")
        return RepairInspection(fence.witness, version(actual), actual?.let { decodePreference(it.bytes) }, isWanted, actual?.witness)
    }

    private fun clearFence(fence: Raw, state: Raw?, original: ByteArray, permitted: () -> Boolean) {
        boundary("before-fence-clear")
        checkRaw(stateName, state); checkRaw(fenceName, fence)
        if (!permitted()) fail("photo_source_revoked_before_fence_clear")
        Files.delete(root.resolve(fenceName))
        try {
            syncDirectory(directory)
            checkRaw(stateName, state)
            if (!permitted()) fail("photo_source_revoked_after_fence_clear")
        } catch (error: Exception) {
            // Re-establish the same fence if the unlink's durability is uncertain.
            // If storage itself is unavailable this also fails closed to the caller.
            if (raw(fenceName) == null) create(fenceName, original)
            syncDirectory(directory)
            throw error
        }
    }

    private fun decodeFence(cipher: ByteArray): Pair<ByteArray?, ByteArray> {
        val json = decode(protection.open(cipher, domain + fenceName))
        if (json.keys != setOf("format", "before", "wanted") || json["format"] != JsonPrimitive(1)) fail("invalid_photo_source_fence")
        val before = if (json["before"] == JsonNull) null else Base64.getDecoder().decode(text(json, "before"))
        val wanted = Base64.getDecoder().decode(text(json, "wanted"))
        before?.let { decodePreference(it) }; decodePreference(wanted)
        return before to wanted
    }

    private fun preferenceJson(value: PhotoFolderPreference) = JsonObject(mapOf("format" to JsonPrimitive(if (value.pairingEpoch == null) 1 else 2),
        "tree_uri" to JsonPrimitive(value.treeUri), "receiver_id" to JsonPrimitive(value.receiverId),
        "receiver_identity_sha256" to JsonPrimitive(value.receiverIdentitySha256), "epoch" to JsonPrimitive(value.epoch),
        "enabled" to JsonPrimitive(value.enabled)) + (value.pairingEpoch?.let { mapOf("pairing_epoch" to JsonPrimitive(it)) } ?: emptyMap()))

    private fun decodePreference(cipher: ByteArray): PhotoFolderPreference {
        val value = decode(protection.open(cipher, domain + stateName))
        val paired = when (value["format"]) { JsonPrimitive(1) -> false; JsonPrimitive(2) -> true; else -> fail("invalid_photo_source_preference") }
        if (value.keys != setOf("format", "tree_uri", "receiver_id", "receiver_identity_sha256", "epoch", "enabled") +
                (if (paired) setOf("pairing_epoch") else emptySet()) || value["enabled"] !in listOf(JsonPrimitive(true), JsonPrimitive(false)))
            fail("invalid_photo_source_preference")
        return PhotoFolderPreference(text(value, "tree_uri"), text(value, "receiver_id"), text(value, "receiver_identity_sha256"),
            text(value, "epoch"), value["enabled"] == JsonPrimitive(true), if (paired) text(value, "pairing_epoch") else null)
    }

    private fun encode(value: JsonObject): ByteArray = ByteArrayOutputStream().also { TelefonRahmen.schreiben(it, value, LIMIT) }.toByteArray()
    private fun decode(bytes: ByteArray): JsonObject = ByteArrayInputStream(bytes).use { input ->
        TelefonRahmen.lesen(input, LIMIT).also { if (input.read() != -1) fail("trailing_photo_source_metadata") }
    }
    private fun text(value: JsonObject, key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
        ?: fail("invalid_photo_source_string")

    private fun raw(name: String): Raw? {
        checkRoot()
        val file = root.resolve(name).toFile()
        val initial = try { attributes(file) } catch (_: java.nio.file.NoSuchFileException) { return null }
        if (!initial.isRegularFile || initial.size() !in 1..(LIMIT + 4096).toLong()) fail("unsafe_photo_source_entry")
        privateEntry(file)
        val bytes = FileChannel.open(file.toPath(), READ, NOFOLLOW_LINKS).use { channel ->
            val buffer = ByteBuffer.allocate(LIMIT + 4097)
            while (buffer.hasRemaining() && channel.read(buffer) != -1) { }
            if (buffer.position() > LIMIT + 4096) fail("oversized_photo_source_entry")
            buffer.flip(); ByteArray(buffer.remaining()).also { buffer.get(it) }
        }
        val after = attributes(file)
        if (initial.fileKey() == null || initial.fileKey() != after.fileKey() || initial.size() != bytes.size.toLong() ||
            initial.lastModifiedTime() != after.lastModifiedTime()) fail("photo_source_read_race")
        return Raw(bytes, initial.fileKey().toString() + ":" + hash(bytes))
    }
    private fun checkRaw(name: String, expected: Raw?) {
        val actual = raw(name)
        if (actual?.witness != expected?.witness || (actual != null && expected != null && !actual.bytes.contentEquals(expected.bytes)))
            fail("photo_source_concurrent_ciphertext_change")
    }
    private fun requireRaw(name: String) = raw(name) ?: fail("photo_source_entry_missing")
    private fun version(raw: Raw?) = raw?.let { hash(it.bytes) } ?: "absent-photo-source-v1"
    private fun create(name: String, bytes: ByteArray) {
        checkRoot()
        FileChannel.open(root.resolve(name), setOf(WRITE, CREATE_NEW, NOFOLLOW_LINKS),
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))).use { channel ->
            val buffer = ByteBuffer.wrap(bytes)
            while (buffer.hasRemaining()) channel.write(buffer)
            channel.force(true)
        }
    }
    private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
    private fun checkRoot() {
        val actual = attributes(directory)
        if (!actual.isDirectory || actual.fileKey() != rootKey || directory.canonicalFile != directory)
            fail("photo_store_directory_changed")
        privateEntry(directory)
    }
    private fun privateEntry(file: File) {
        val permissions = Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS)
        if (permissions.any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root, NOFOLLOW_LINKS))
            fail("photo_store_private_ownership_required")
        if (file != directory && (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1)
            fail("photo_store_linked_entry")
    }
    private fun <T> gated(action: () -> T): T = synchronized(processGate) {
        checkRoot()
        val lock = root.resolve("photo-source.lock").toFile()
        if (Files.exists(lock.toPath(), NOFOLLOW_LINKS)) {
            if (!attributes(lock).isRegularFile) fail("unsafe_photo_source_lock")
            privateEntry(lock)
        }
        FileChannel.open(root.resolve("photo-source.lock"), setOf(WRITE, CREATE, NOFOLLOW_LINKS),
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))).use { channel ->
            channel.lock().use { checkRoot(); action() }
        }
    }
    companion object {
        private val processGate = Any()
        private const val LIMIT = 65536
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
