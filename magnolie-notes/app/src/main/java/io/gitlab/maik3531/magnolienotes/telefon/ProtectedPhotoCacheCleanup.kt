package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardOpenOption.READ
import java.nio.file.attribute.BasicFileAttributes
import java.security.MessageDigest
import java.util.Locale

/** Retirement-only cleanup of authenticated native cache records. Not a source
 * authority or reader: no phone URI, live permission, plaintext or manifest is
 * released. Only the index calls this AFTER durable retirement/CAS verification.
 */
internal object ProtectedPhotoCacheCleanup {
    private data class Witness(val key: String, val digest: String)

    fun discard(root: File, job: PhotoSourceJob, boundary: (String) -> Unit) {
        if (job.phase != "retired") fail("photo_cache_retirement_required")
        val record = job.snapshot ?: fail("photo_cache_snapshot_missing")
        fun text(value: JsonObject, name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
            ?: fail("photo_cache_invalid_record")
        val hasOrigins = record["format"] == JsonPrimitive(2)
        if (record.keys != setOf("format", "owner", "source_domain", "root_key", "cipher_bytes", "manifest", "files") +
            (if (hasOrigins) setOf("source_origins") else emptySet()) ||
            !hasOrigins && record["format"] != JsonPrimitive(1) || text(record, "root_key") != job.rootKey ||
            !Regex("[0-9a-f]{64}").matches(text(record, "source_domain"))) fail("photo_cache_invalid_record")
        val manifest = DeviceFileManifest.parse(record["manifest"] as? JsonObject ?: fail("photo_cache_invalid_record"))
        if (hasOrigins) GalleryPhotoOrigins.parse(record["source_origins"] as? JsonObject ?: fail("photo_cache_invalid_record"), manifest)
        if (text(record, "owner") != manifest.sourceId || manifest.totalBytes != job.plainBytes) fail("photo_cache_invalid_record")
        val names = mutableSetOf("owner.enc", "manifest.enc")
        manifest.files.forEach { member ->
            if (member.size == 0L) names.add("empty-${member.id}.enc")
            else repeat(((member.size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()) {
                names.add("${member.id}-$it.enc")
            }
        }
        val proofs = record["files"] as? JsonArray ?: fail("photo_cache_invalid_record")
        if (proofs.size != names.size) fail("photo_cache_invalid_record")
        val witnesses = linkedMapOf<String, Witness>()
        proofs.forEach { item ->
            val proof = item as? JsonObject ?: fail("photo_cache_invalid_record")
            if (proof.keys != setOf("name", "key", "sha256")) fail("photo_cache_invalid_record")
            val name = text(proof, "name"); val key = text(proof, "key"); val digest = text(proof, "sha256")
            if (name !in names || key.length !in 1..512 || !Regex("[0-9a-f]{64}").matches(digest) ||
                witnesses.put(name, Witness(key, digest)) != null) fail("photo_cache_invalid_record")
        }
        val bytes = (record["cipher_bytes"] as? JsonPrimitive)?.takeIf { !it.isString && Regex("0|[1-9][0-9]*").matches(it.content) }
            ?.content?.toLongOrNull() ?: fail("photo_cache_invalid_record")
        if (bytes !in names.size * 29L..job.cipherBudget) fail("photo_cache_invalid_record")
        fun directory() {
            val actual = attributes(root)
            if (!actual.isDirectory || actual.fileKey()?.toString() != job.rootKey || root.canonicalFile != root)
                fail("photo_cache_directory_changed")
            privateEntry(root, root)
        }
        fun verify(name: String): Long {
            directory()
            val file = File(root, name)
            val before = attributes(file)
            val witness = witnesses.getValue(name)
            if (!before.isRegularFile || before.fileKey()?.toString() != witness.key || before.size() !in 29..262172)
                fail("photo_cache_original_changed")
            privateEntry(file, root)
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteBuffer.allocate(64 * 1024)
            var count = 0L
            FileChannel.open(file.toPath(), READ, NOFOLLOW_LINKS).use { channel ->
                while (true) {
                    val read = channel.read(buffer)
                    if (read == -1) break
                    count += read
                    if (count > 262172) fail("photo_cache_original_changed")
                    buffer.flip(); digest.update(buffer); buffer.clear()
                }
            }
            val after = attributes(file)
            if (before.fileKey() != after.fileKey() || before.size() != count || after.size() != count ||
                before.lastModifiedTime() != after.lastModifiedTime() || hex(digest.digest()) != witness.digest)
                fail("photo_cache_original_changed")
            directory()
            return count
        }
        directory()
        val present = mutableSetOf<String>()
        Files.newDirectoryStream(root.toPath()).use { entries ->
            for (entry in entries) {
                val name = entry.fileName.toString()
                if (name !in witnesses || !present.add(name)) fail("photo_cache_unknown_entries_preserved")
            }
        }
        // Missing originals are permitted only in this retired cleanup path:
        // a previous unlink/ack failure may have left a proper subset behind.
        // The immutable authenticated head is retained throughout every retry.
        var actualBytes = 0L
        present.forEach { actualBytes += verify(it) }
        if (actualBytes > bytes) fail("photo_cache_original_changed")
        present.sortedBy { it == "owner.enc" }.forEach { name ->
            verify(name)
            Files.delete(File(root, name).toPath())
            boundary("cached-entry-discarded")
        }
        directory()
        synchronisiereOrdner(root)
        Files.delete(root.toPath())
        synchronisiereOrdner(root.parentFile)
    }

    private fun privateEntry(file: File, root: File) {
        if (Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root.toPath(), NOFOLLOW_LINKS) ||
            Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            file != root && (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1)
            fail("photo_cache_unsafe_entry")
    }
    private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
