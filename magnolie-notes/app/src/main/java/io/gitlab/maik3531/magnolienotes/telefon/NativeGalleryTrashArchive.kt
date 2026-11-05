package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.os.CancellationSignal
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.UUID

internal data class NativeGalleryArchiveEntry internal constructor(val id: String, val version: String,
    val bytes: Long, val sha256: String, val displayName: String, val archivedMs: Long, val originalBytesVerified: Boolean = false) {
    // Copy time only, NOT a trash/deletion event or retention-start witness.
    val grantsMutationAuthority: Boolean get() = false
    val isRemoteDeletionReceipt: Boolean get() = false
}

internal data class NativeGalleryTrashAction internal constructor(val operation: String, val archiveId: String,
    val archiveVersion: String, val sequence: Int, val state: String, val changedMs: Long, val version: String) {
    val isRemoteDeletionReceipt: Boolean get() = false
}

/** Separate LOCAL recovery ownership. Never a PhotoSourceJobIndex cache, live
 * receiver grant, OS consent or deletion receipt. No MediaStore mutation occurs
 * here. A later mutation owner must reverify this archive before requesting OS
 * consent and must journal/read back the actual provider result separately.
 *
 * No eviction: full/damaged/uncertain storage blocks new destructive operations.
 * Existing phone key only. Source-job quotas, histories and pairings untouched.
 */
internal class NativeGalleryTrashArchive(private val directory: File, private val protection: DeviceTransferProtection) : AutoCloseable {
    private val root = directory.toPath()
    private val rootKey = attributes(directory).fileKey()?.toString() ?: fail("gallery_archive_root_identity_required")
    private val path = File(directory, "media-recovery.db")
    private val header = File(directory, "media-recovery-owner.enc")
    private val lockFile = File(directory, "media-recovery.lock")
    private val lockChannel: FileChannel
    private val ownership: FileLock
    private val lockKey: String
    private val db: SQLiteDatabase
    private val databaseKey: String
    private val owner: String
    private val schema: String
    private var closed = false
    private var failed = false
    private var observedRevision = 0L

    init {
        require(directory.isAbsolute && directory.canonicalFile == directory)
        checkRoot()
        val empty = Files.newDirectoryStream(root).use { !it.iterator().hasNext() }
        // Probe the EXISTING key before even creating a lock or SQLite file.
        protection.seal(byteArrayOf(1), HEADER_DOMAIN)
        if (empty) Files.createFile(lockFile.toPath(), PRIVATE_FILE)
        regular(lockFile)
        lockKey = attributes(lockFile).fileKey()?.toString() ?: fail("gallery_archive_lock_identity_required")
        lockChannel = FileChannel.open(lockFile.toPath(), READ, WRITE, NOFOLLOW_LINKS)
        try { ownership = lockChannel.tryLock() ?: fail("gallery_archive_owner_busy") }
        catch (error: Exception) { lockChannel.close(); throw error }
        try {
            if (!empty && (!Files.exists(header.toPath(), NOFOLLOW_LINKS) || !Files.exists(path.toPath(), NOFOLLOW_LINKS)))
                fail("gallery_archive_incomplete_storage_preserved")
            val previous = if (empty) null else decodeHeader()
            if (empty) Files.createFile(path.toPath(), PRIVATE_FILE)
            regular(path)
            databaseKey = attributes(path).fileKey()?.toString() ?: fail("gallery_archive_database_identity_required")
            if (previous != null && (previous.string("root") != rootKey || previous.string("database") != databaseKey))
                fail("gallery_archive_original_storage_required")
            db = SQLiteDatabase.openDatabase(path.path, null, SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.NO_LOCALIZED_COLLATORS)
            try {
                db.enableWriteAheadLogging(); db.execSQL("PRAGMA synchronous=FULL")
                owner = previous?.string("owner") ?: UUID.randomUUID().toString()
                if (empty) {
                    db.execSQL("CREATE TABLE recovery_meta(name TEXT PRIMARY KEY NOT NULL,sealed BLOB NOT NULL)")
                    db.execSQL("CREATE TABLE recovery_entries(id TEXT PRIMARY KEY NOT NULL,sealed BLOB NOT NULL)")
                    db.execSQL("CREATE TABLE recovery_chunks(id TEXT NOT NULL,number INTEGER NOT NULL,sealed BLOB NOT NULL,PRIMARY KEY(id,number))")
                }
                schema = schemaHash()
                if (previous != null && previous.string("schema") != schema) fail("gallery_archive_schema_changed")
                if (empty) {
                    db.beginTransaction()
                    try { writeMembership(1); db.setTransactionSuccessful() } finally { db.endTransaction() }
                    val clear = TelefonKanonisch.bytes(buildJsonObject {
                        put("format", 1); put("owner", owner); put("root", rootKey); put("database", databaseKey); put("schema", schema)
                    })
                    val cipher = protection.seal(clear, HEADER_DOMAIN)
                    FileChannel.open(header.toPath(), setOf(WRITE, CREATE_NEW, NOFOLLOW_LINKS), PRIVATE_FILE).use {
                        val buffer = ByteBuffer.wrap(cipher)
                        while (buffer.hasRemaining()) it.write(buffer)
                        it.force(true)
                    }
                    synchronisiereOrdner(directory)
                }
                verify()
            } catch (error: Exception) { db.close(); throw error }
        } catch (error: Exception) { ownership.release(); lockChannel.close(); throw error }
    }

    private fun checkRoot() {
        val value = attributes(directory)
        if (!value.isDirectory || value.fileKey()?.toString() != rootKey || directory.canonicalFile != directory ||
            Files.getPosixFilePermissions(root, NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") })
            fail("gallery_archive_private_root_required")
    }
    private fun regular(file: File) {
        val value = attributes(file)
        if (!value.isRegularFile || (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1 ||
            Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root, NOFOLLOW_LINKS) ||
            Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") })
            fail("gallery_archive_private_file_required")
    }
    private fun decodeHeader(): JsonObject {
        regular(header)
        if (header.length() !in 29..8192) fail("gallery_archive_header_invalid")
        val cipher = FileChannel.open(header.toPath(), READ, NOFOLLOW_LINKS).use {
            if (it.size() !in 29..8192) fail("gallery_archive_header_invalid")
            val buffer = ByteBuffer.allocate(it.size().toInt())
            while (buffer.hasRemaining()) if (it.read(buffer) <= 0) fail("gallery_archive_header_invalid")
            if (it.read(ByteBuffer.allocate(1)) != -1) fail("gallery_archive_header_invalid")
            buffer.array()
        }
        val clear = protection.open(cipher, HEADER_DOMAIN)
        return try {
            TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject.also {
                if (it.keys != setOf("format", "owner", "root", "database", "schema") || it["format"] != JsonPrimitive(1) ||
                    !validId(it.string("owner"))) fail("gallery_archive_header_invalid")
            }
        } finally { clear.fill(0) }
    }
    private fun domain(suffix: String) = "gallery-media-recovery-v1/$owner/$suffix"
    private fun schemaHash(): String {
        val entries = mutableListOf<JsonElement>()
        db.rawQuery("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name", null).use {
            while (it.moveToNext()) entries.add(JsonArray((0..3).map { column -> if (it.isNull(column)) JsonNull else JsonPrimitive(it.getString(column)) }))
        }
        return digest(TelefonKanonisch.bytes(JsonArray(entries)))
    }
    private fun members(): JsonArray {
        val values = mutableListOf<JsonElement>()
        db.rawQuery("SELECT id,sealed FROM recovery_entries ORDER BY id", null).use {
            while (it.moveToNext()) {
                if (values.size >= MAX_ENTRIES) fail("gallery_archive_capacity_held")
                val id = it.getString(0); val cipher = it.getBlob(1)
                if (!validId(id) || cipher.size !in 29..16384) fail("gallery_archive_record_invalid")
                values += buildJsonObject { put("id", id); put("sha256", digest(cipher)) }
            }
        }
        return JsonArray(values)
    }
    private fun writeMembership(revision: Long) {
        val clear = TelefonKanonisch.bytes(buildJsonObject { put("format", 2); put("revision", revision); put("entries", members()); put("actions", actionMembers()) })
        val cipher = protection.seal(clear, domain("membership"))
        db.insertWithOnConflict("recovery_meta", null, ContentValues().apply { put("name", "membership"); put("sealed", cipher) }, SQLiteDatabase.CONFLICT_REPLACE)
    }
    private fun verify(): Long {
        if (closed || failed) fail("gallery_archive_not_current")
        checkRoot(); regular(path); regular(lockFile)
        if (!ownership.isValid || attributes(lockFile).fileKey()?.toString() != lockKey || attributes(path).fileKey()?.toString() != databaseKey ||
            decodeHeader().string("owner") != owner || schemaHash() != schema)
            fail("gallery_archive_original_storage_required")
        Files.newDirectoryStream(root).use { entries ->
            for (file in entries) {
                if (file.fileName.toString() !in FILES) fail("gallery_archive_unknown_entry_preserved")
                regular(file.toFile())
            }
        }
        val bytes = db.rawQuery("SELECT sealed FROM recovery_meta WHERE name='membership'", null).use {
            if (!it.moveToFirst()) fail("gallery_archive_membership_missing")
            it.getBlob(0).also { _ -> if (it.moveToNext()) fail("gallery_archive_membership_invalid") }
        }
        val clear = protection.open(bytes, domain("membership"))
        val record = try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject } finally { clear.fill(0) }
        val revision = record["revision"]?.jsonPrimitive?.longOrNull ?: fail("gallery_archive_membership_invalid")
        val legacy = record["format"] == JsonPrimitive(1)
        val actions = actionMembers()
        if (record.keys != setOf("format", "revision", "entries") + (if (legacy) emptySet() else setOf("actions")) ||
            !legacy && record["format"] != JsonPrimitive(2) || revision <= 0 || revision < observedRevision || record["entries"] != members() ||
            (if (legacy) actions.isNotEmpty() else record["actions"] != actions)) fail("gallery_archive_membership_changed")
        db.rawQuery("SELECT count(*),COALESCE(max(length(sealed)),0) FROM recovery_chunks", null).use {
            if (!it.moveToFirst() || it.getLong(0) > MAX_BYTES / DeviceFileManifest.CHUNK_BYTES + MAX_ENTRIES ||
                it.getLong(1) > DeviceFileManifest.CHUNK_BYTES + 28) fail("gallery_archive_chunks_changed")
        }
        db.rawQuery("SELECT count(*) FROM recovery_chunks WHERE NOT EXISTS(SELECT 1 FROM recovery_entries WHERE recovery_entries.id=recovery_chunks.id)", null).use {
            if (!it.moveToFirst() || it.getLong(0) != 0L) fail("gallery_archive_membership_changed")
        }
        if (!db.inTransaction()) observedRevision = revision
        return revision
    }

    private fun readRecord(id: String): Pair<NativeGalleryArchiveEntry, JsonObject> {
        if (!validId(id)) fail("gallery_archive_record_invalid")
        val bytes = db.rawQuery("SELECT sealed FROM recovery_entries WHERE id=?", arrayOf(id)).use {
            if (!it.moveToFirst()) fail("gallery_archive_original_entry_required")
            it.getBlob(0)
        }
        val clear = protection.open(bytes, domain("$id/metadata"))
        val value = try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject } finally { clear.fill(0) }
        val size = value["size"]?.jsonPrimitive?.longOrNull ?: fail("gallery_archive_record_invalid")
        val at = value["archived_ms"]?.jsonPrimitive?.longOrNull ?: fail("gallery_archive_record_invalid")
        val original = value["format"] == JsonPrimitive(2)
        if (value.keys != setOf("format", "id", "size", "sha256", "name", "archived_ms", "origin") +
                (if (original) setOf("original_bytes", "baseline_sha256") else emptySet()) ||
            !original && value["format"] != JsonPrimitive(1) || original && (value["original_bytes"] != JsonPrimitive(true) || !DeviceFileControl.hash(value.string("baseline_sha256"))) ||
            value.string("id") != id || size !in 0..DeviceFileManifest.MAX_FILE_BYTES || at <= 0 || !DeviceFileControl.hash(value.string("sha256")) ||
            !DeviceFileManifest.portablePath(value.string("name")) || '/' in value.string("name")) fail("gallery_archive_record_invalid")
        val origin = value["origin"] as? JsonObject ?: fail("gallery_archive_record_invalid")
        if (origin.keys != setOf("uri", "member", "revision", "namespace", "source", "media_type", "peer", "peer_identity", "volume", "album_path", "mime_type"))
            fail("gallery_archive_record_invalid")
        val kind = GalleryMediaType.entries.singleOrNull { it.uriSegment == origin.string("media_type") } ?: fail("gallery_archive_record_invalid")
        val member = origin.string("member").split(':')
        if (member.size != 3 || member.any { it.toLongOrNull() == null } || member[0].toLong() <= 0 || member[1].toLong() < 0 || member[2].toLong() <= 0 ||
            origin.string("revision").toLongOrNull()?.let { it >= member[2].toLong() } != true ||
            !Regex("[A-Za-z0-9_-]{1,128}").matches(origin.string("volume")) ||
            origin.string("uri") != "content://media/${origin.string("volume")}/${kind.uriSegment}/media/${member[0]}" ||
            !kind.acceptsMime(origin.string("mime_type")) || !DeviceFileControl.id(origin.string("peer")) || !DeviceFileControl.hash(origin.string("peer_identity")) ||
            !Regex("gallery-(video-)?album-v1:[0-9a-f]{64}").matches(origin.string("source")) ||
            origin.string("namespace").length !in 1..1024 || origin.string("namespace").any { it.code < 32 || it.code == 127 } ||
            origin.string("album_path").length !in 1..4096) fail("gallery_archive_record_invalid")
        return NativeGalleryArchiveEntry(id, digest(bytes), size, value.string("sha256"), value.string("name"), at, original) to value
    }

    @Synchronized fun entries(permit: NativeGalleryTrashBookPermit): List<NativeGalleryArchiveEntry> {
        permit.requireCurrent(); verify()
        val items = members().map { readRecord(it.jsonObject.string("id")).first }
        if (items.sumOf { it.bytes } > MAX_BYTES) fail("gallery_archive_capacity_held")
        permit.requireCurrent(); return items
    }

    @Synchronized internal fun verifiedOrigin(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit): JsonObject {
        verifyContent(entry, permit)
        return readRecord(entry.id).second["origin"]!!.jsonObject
    }

    @Synchronized internal fun verifiedOriginalOrigin(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit): JsonObject {
        val origin = verifiedOrigin(entry, permit)
        if (!readRecord(entry.id).first.originalBytesVerified) fail("gallery_archive_original_bytes_not_verified")
        return origin
    }

    private fun actionMembers(): JsonArray {
        val values = mutableListOf<JsonElement>()
        db.rawQuery("SELECT name,sealed FROM recovery_meta WHERE name<>'membership' ORDER BY name", null).use {
            while (it.moveToNext()) {
                val name = it.getString(0); val cipher = it.getBlob(1)
                if (values.size >= MAX_ACTIONS * 4 || !Regex("trash/[0-9a-f-]{36}/[1-4]").matches(name) || cipher.size !in 29..16384)
                    fail("gallery_archive_action_membership_invalid")
                values.add(buildJsonObject { put("name", name); put("sha256", digest(cipher)) })
            }
        }
        return JsonArray(values)
    }

    private fun readActions(): List<NativeGalleryTrashAction> {
        val heads = linkedMapOf<String, NativeGalleryTrashAction>()
        db.rawQuery("SELECT name,sealed FROM recovery_meta WHERE name<>'membership' ORDER BY name", null).use {
            while (it.moveToNext()) {
                val name = it.getString(0); val cipher = it.getBlob(1)
                val clear = protection.open(cipher, domain(name))
                val body = try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject } finally { clear.fill(0) }
                if (body.keys != setOf("format", "operation", "archive", "archive_version", "sequence", "state", "changed_ms", "previous") || body["format"] != JsonPrimitive(1))
                    fail("gallery_archive_action_invalid")
                val operation = body.string("operation"); val archive = body.string("archive"); val archiveVersion = body.string("archive_version")
                val sequence = body["sequence"]?.jsonPrimitive?.intOrNull ?: fail("gallery_archive_action_invalid")
                val state = body.string("state"); val at = body["changed_ms"]?.jsonPrimitive?.longOrNull ?: fail("gallery_archive_action_invalid")
                val previous = heads[operation]
                val predecessor = when (state) {
                    "prepared" -> null; "trashed", "canceled" -> "prepared"; "restore_prepared" -> "trashed"; "restored" -> "restore_prepared"
                    else -> fail("gallery_archive_action_invalid")
                }
                val expectedSequence = when (state) { "prepared" -> 1; "trashed", "canceled" -> 2; "restore_prepared" -> 3; else -> 4 }
                if (!validId(operation) || !validId(archive) || !DeviceFileControl.hash(archiveVersion) || at <= 0 || sequence != expectedSequence ||
                    name != "trash/$operation/$sequence" || previous?.state != predecessor ||
                    (if (previous == null) body["previous"] != JsonNull else body.string("previous") != previous.version ||
                        archive != previous.archiveId || archiveVersion != previous.archiveVersion || at < previous.changedMs) ||
                    readRecord(archive).first.version != archiveVersion) fail("gallery_archive_action_lineage_changed")
                heads[operation] = NativeGalleryTrashAction(operation, archive, archiveVersion, sequence, state, at, digest(cipher))
            }
        }
        if (heads.size > MAX_ACTIONS) fail("gallery_archive_action_capacity_held")
        return heads.values.toList()
    }

    @Synchronized fun actions(permit: NativeGalleryTrashBookPermit): List<NativeGalleryTrashAction> {
        permit.requireCurrent(); verify(); val result = readActions(); permit.requireCurrent(); return result
    }

    @Synchronized internal fun prepareTrash(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit, current: () -> Unit): NativeGalleryTrashAction {
        verifyContent(entry, permit); current()
        val previous = readActions()
        if (previous.size >= MAX_ACTIONS || previous.any { it.archiveId == entry.id && it.state != "canceled" })
            fail("gallery_archive_original_action_pending")
        return appendAction(entry, null, "prepared", permit, current)
    }

    @Synchronized internal fun finishTrash(selected: NativeGalleryTrashAction, permit: NativeGalleryTrashBookPermit, current: () -> Unit): NativeGalleryTrashAction =
        appendAction(readRecord(selected.archiveId).first, selected, "trashed", permit, current)

    @Synchronized internal fun cancelUnmutatedTrash(selected: NativeGalleryTrashAction, permit: NativeGalleryTrashBookPermit, current: () -> Unit): NativeGalleryTrashAction =
        appendAction(readRecord(selected.archiveId).first, selected, "canceled", permit, current)

    private fun appendAction(entry: NativeGalleryArchiveEntry, selected: NativeGalleryTrashAction?, state: String,
        permit: NativeGalleryTrashBookPermit, current: () -> Unit): NativeGalleryTrashAction {
        permit.requireCurrent(); current(); val revision = verify(); val heads = readActions()
        if (readRecord(entry.id).first != entry || selected != null && heads.none { it == selected } ||
            selected != null && (selected.state != "prepared" || state !in setOf("trashed", "canceled"))) fail("gallery_archive_stale_action")
        val operation = selected?.operation ?: UUID.randomUUID().toString(); val sequence = (selected?.sequence ?: 0) + 1
        val body = buildJsonObject {
            put("format", 1); put("operation", operation); put("archive", entry.id); put("archive_version", entry.version)
            put("sequence", sequence); put("state", state); put("changed_ms", maxOf(System.currentTimeMillis(), selected?.changedMs ?: 0))
            put("previous", selected?.version?.let(::JsonPrimitive) ?: JsonNull)
        }
        val name = "trash/$operation/$sequence"; val cipher = protection.seal(TelefonKanonisch.bytes(body), domain(name))
        db.beginTransaction()
        try {
            db.insertOrThrow("recovery_meta", null, ContentValues().apply { put("name", name); put("sealed", cipher) })
            writeMembership(revision + 1); current(); permit.requireCurrent(); db.setTransactionSuccessful()
        } finally { db.endTransaction() }
        verify(); val result = readActions().single { it.operation == operation }
        if (result.version != digest(cipher) || result.state != state) fail("gallery_archive_action_readback_failed")
        current(); permit.requireCurrent(); return result
    }

    @Synchronized fun verifyContent(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit) {
        permit.requireCurrent(); verify()
        val actual = readRecord(entry.id).first
        if (actual != entry) fail("gallery_archive_stale_selection")
        val hash = MessageDigest.getInstance("SHA-256"); var size = 0L; var number = 0
        db.rawQuery("SELECT number,sealed FROM recovery_chunks WHERE id=? ORDER BY number", arrayOf(entry.id)).use {
            while (it.moveToNext()) {
                permit.requireCurrent()
                if (it.getInt(0) != number || size >= entry.bytes) fail("gallery_archive_chunks_changed")
                val clear = protection.open(it.getBlob(1), domain("${entry.id}/chunk/$number"))
                try {
                    if (clear.size != minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), entry.bytes - size).toInt()) fail("gallery_archive_chunks_changed")
                    hash.update(clear); size += clear.size; number++
                } finally { clear.fill(0) }
            }
        }
        if (size != entry.bytes || digestHash(hash) != entry.sha256) fail("gallery_archive_content_changed")
        permit.requireCurrent(); verify()
    }

    @Synchronized fun readContent(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit, consume: (ByteArray) -> Unit) {
        verifyContent(entry, permit)
        db.rawQuery("SELECT number,sealed FROM recovery_chunks WHERE id=? ORDER BY number", arrayOf(entry.id)).use {
            while (it.moveToNext()) {
                permit.requireCurrent()
                val clear = protection.open(it.getBlob(1), domain("${entry.id}/chunk/${it.getInt(0)}"))
                try { consume(clear); permit.requireCurrent() } finally { clear.fill(0) }
            }
        }
        verifyContent(entry, permit)
    }

    @Synchronized fun archive(lease: GalleryPhotoSourceLease, scope: GalleryPhotoSourceScope, entry: PhotoInventoryEntry,
        reader: AndroidGalleryPhotoSource, expectedSha256: String, permit: NativeGalleryTrashBookPermit,
        cancellation: CancellationSignal = CancellationSignal()): NativeGalleryArchiveEntry {
        fun current() {
            permit.requireCurrent(); cancellation.throwIfCanceled()
            if (!scope.isCurrent(lease)) fail("gallery_archive_source_revoked")
        }
        current(); val revision = verify()
        val previous = entries(permit)
        if (previous.size >= MAX_ENTRIES || entry.advertisedBytes < 0 || entry.advertisedBytes > DeviceFileManifest.MAX_FILE_BYTES ||
            previous.sumOf { it.bytes } > MAX_BYTES - entry.advertisedBytes) fail("gallery_archive_capacity_held")
        if (!DeviceFileControl.hash(expectedSha256) || lease.access.mediaStoreVersion == null || lease.access.coverage == GalleryReadCoverage.SELECTED_ONLY ||
            entry.documentId.split(':').getOrNull(2)?.toLongOrNull()?.let { it > 0 } != true || entry.nativeRevision == null)
            fail("gallery_archive_native_origin_required")
        reader.verifyMetadata(lease, entry, cancellation); current()
        val mime = reader.observeRecoveryMime(lease, entry, cancellation); current()
        // The frozen transfer view may legitimately have EXIF redacted. Check
        // that view against its baseline WITHOUT confusing it with raw recovery
        // bytes or silently accepting an edit of the current provider object.
        val baseline = MessageDigest.getInstance("SHA-256"); var baselineSize = 0L
        reader.openRead(lease, entry, cancellation).use { source ->
            val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
            try {
                while (true) {
                    current(); val count = source.read(buffer)
                    if (count == -1) break
                    if (count <= 0 || baselineSize + count > entry.advertisedBytes) fail("gallery_archive_source_changed")
                    baseline.update(buffer, 0, count); baselineSize += count
                }
            } finally { buffer.fill(0) }
        }
        if (baselineSize != entry.advertisedBytes || digestHash(baseline) != expectedSha256) fail("gallery_archive_source_changed")
        current(); reader.verifyMetadata(lease, entry, cancellation)
        val id = UUID.randomUUID().toString(); val hash = MessageDigest.getInstance("SHA-256")
        db.beginTransaction()
        try {
            var size = 0L; var number = 0
            reader.openOriginalForRecovery(lease, entry, cancellation).use { source ->
                val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
                try {
                    while (size < entry.advertisedBytes) {
                        current(); val wanted = minOf(buffer.size.toLong(), entry.advertisedBytes - size).toInt(); var read = 0
                        while (read < wanted) {
                            current(); val got = source.read(buffer, read, wanted - read)
                            if (got <= 0) fail("gallery_archive_source_short_read")
                            read += got
                        }
                        hash.update(buffer, 0, wanted)
                        val clear = buffer.copyOf(wanted)
                        val cipher = try { protection.seal(clear, domain("$id/chunk/$number")) } finally { clear.fill(0) }
                        db.insertOrThrow("recovery_chunks", null, ContentValues().apply { put("id", id); put("number", number); put("sealed", cipher) })
                        size += wanted; number++
                    }
                    if (source.read() != -1) fail("gallery_archive_source_grew")
                } finally { buffer.fill(0) }
            }
            current(); reader.verifyMetadata(lease, entry, cancellation)
            val originalSha256 = digestHash(hash)
            val record = buildJsonObject {
                put("format", 2); put("id", id); put("size", size); put("sha256", originalSha256); put("name", entry.relativePath); put("archived_ms", System.currentTimeMillis())
                put("original_bytes", true); put("baseline_sha256", expectedSha256)
                put("origin", buildJsonObject {
                    put("uri", entry.documentUri); put("member", entry.documentId); put("revision", entry.nativeRevision)
                    put("namespace", lease.access.mediaStoreVersion); put("source", lease.sourceKey)
                    put("media_type", lease.activation.mediaType.uriSegment); put("peer", lease.receiver.peerId); put("peer_identity", lease.receiver.identitySha256)
                    put("volume", lease.album.volume); put("album_path", lease.album.relativePath); put("mime_type", mime)
                })
            }
            val cipher = protection.seal(TelefonKanonisch.bytes(record), domain("$id/metadata"))
            db.insertOrThrow("recovery_entries", null, ContentValues().apply { put("id", id); put("sealed", cipher) })
            writeMembership(revision + 1); current(); db.setTransactionSuccessful()
        } catch (error: Exception) { failed = true; throw error }
        finally { db.endTransaction() }
        try {
            synchronisiereOrdner(directory); current(); verify()
            val result = readRecord(id).first; verifyContent(result, permit); current()
            return result
        } catch (error: Exception) { failed = true; throw error }
    }

    @Synchronized override fun close() {
        if (closed) return
        closed = true
        try { db.close() } finally { try { ownership.release() } finally { lockChannel.close() } }
    }

    companion object {
        fun openForApplication(context: android.content.Context, protection: DeviceTransferProtection): NativeGalleryTrashArchive {
            protection.seal(byteArrayOf(1), HEADER_DOMAIN)
            val directory = File(context.applicationContext.noBackupFilesDir, "native-media-recovery")
            if (!Files.exists(directory.toPath(), NOFOLLOW_LINKS)) Files.createDirectory(directory.toPath(),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")))
            return NativeGalleryTrashArchive(directory, protection)
        }
        const val MAX_ENTRIES = 128
        const val MAX_ACTIONS = 128
        const val MAX_BYTES = DeviceFileManifest.MAX_TOTAL_BYTES
        private const val HEADER_DOMAIN = "gallery-media-recovery-v1/header"
        private val PRIVATE_FILE = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))
        private val FILES = setOf("media-recovery.db", "media-recovery.db-wal", "media-recovery.db-shm", "media-recovery.db-journal", "media-recovery.lock", "media-recovery-owner.enc")
        private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        private fun validId(value: String) = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(value)
        private fun digest(bytes: ByteArray) = digestHash(MessageDigest.getInstance("SHA-256").apply { update(bytes) })
        private fun digestHash(hash: MessageDigest) = hash.digest().joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
