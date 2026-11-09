package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.*
import java.io.File
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/** Incoming successor ciphertext only. Not an outgoing photo source, archive,
 * plaintext temp file, new MediaStore row, writer or restart-adoption factory. */
internal class NativeGalleryPcStage private constructor(private val base: File, private val parent: File, private val root: File,
    private val baseKey: String, private val parentKey: String, private val index: PhotoSourceJobIndex,
    private val owner: NativeGalleryIncomingOwner, private val grant: NativeGalleryPcWriteGrant,
    private val channel: TelefonSecureChannel, record: GalleryPcStageRecord,
    private val lane: Any, private val boundary: (String) -> Unit) : AutoCloseable {
    private data class Records(val current: GalleryPcStageRecord, val committing: GalleryPcStageRecord? = null)
    @Volatile private var records = Records(record)
    internal val record: GalleryPcStageRecord get() = records.current
    private data class Witness(val key: String, val size: Long, val sha256: String) {
        fun wire() = buildJsonObject { put("key", key); put("size", size); put("sha256", sha256) }
    }
    private val protection = index.pcStageProtection(grant)
    private val closed = AtomicBoolean(false)
    private val files = linkedMapOf<String, Witness>()
    private val membershipGate = Any()
    private val media = GalleryPcStageRecord.media(record.plan)
    internal val manifest: DeviceFileManifest get() = media.manifest
    internal val kind: GalleryMediaType get() = media.kind
    internal val mimeType: String get() = media.mimeTypes.values.single()
    private val expected = manifest.files.single()
    private val domain = "magnolie-incoming-pc-stage-v1/${record.id}/${record.acceptance.id}/"
    private val digest = MessageDigest.getInstance("SHA-256")
    private var chunks = 0
    private var size = 0L
    private var writing: String? = null
    @Volatile private var complete = false

    internal fun requireCurrent() {
        if (closed.get() || !NativeGalleryMediaIoLane.isOwnedBy(lane)) fail("gallery_pc_stage_closed")
        grant.requireCurrent(); owner.requireChannel(channel)
        val before = records
        boundary("pc-stage-before-record-check")
        val actual = index.pcStage(before.current.id)?.body
        val after = records
        // Only this exact native reservation -> verified-seal transition may
        // overlap an already admitted observer. No transport lock spans the CAS.
        if (listOfNotNull(before.current, before.committing, after.current, after.committing).none { it.body == actual }) fail("gallery_pc_stage_changed")
        checkDirectory(base, baseKey); checkDirectory(parent, parentKey); checkDirectory(root, record.body.string("root_key"))
        val hasOwner = synchronized(membershipGate) {
            val allowed = files.keys.toSet() + listOfNotNull(writing)
            val names = linkedSetOf<String>()
            Files.newDirectoryStream(root.toPath()).use { entries ->
                for (entry in entries) {
                    val name = entry.fileName.toString()
                    if (name !in allowed || !names.add(name) || names.size > allowed.size) fail("gallery_pc_stage_membership_changed")
                }
            }
            if (!names.containsAll(files.keys)) fail("gallery_pc_stage_membership_changed")
            files.containsKey("owner.enc")
        }
        if (hasOwner) read("owner.enc").fill(0)
        localOpen()
    }
    private fun localOpen() {
        if (closed.get() || !NativeGalleryMediaIoLane.isOwnedBy(lane)) fail("gallery_pc_stage_closed")
        grant.request.admission.requireLocal(); owner.requireLocal()
    }
    private fun checkDirectory(file: File, key: String) {
        val value = attributes(file)
        if (!value.isDirectory || value.fileKey()?.toString() != key || file.canonicalFile != file) fail("gallery_pc_stage_root_changed")
        privateEntry(file)
    }
    private fun privateEntry(file: File) {
        if (Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(base.toPath(), NOFOLLOW_LINKS)) fail("gallery_pc_stage_not_private")
        if (file != base && !attributes(file).isDirectory && (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1)
            fail("gallery_pc_stage_linked_file")
    }
    private fun read(name: String): ByteArray {
        localOpen()
        val witness = synchronized(membershipGate) { files[name] } ?: fail("gallery_pc_stage_member_missing")
        val file = File(root, name); val before = attributes(file)
        if (!before.isRegularFile || before.fileKey()?.toString() != witness.key || before.size() != witness.size) fail("gallery_pc_stage_member_changed")
        privateEntry(file)
        val bytes = ByteArray(witness.size.toInt())
        FileChannel.open(file.toPath(), READ, NOFOLLOW_LINKS).use { held ->
            boundary("pc-stage-cipher-read-open")
            localOpen()
            val buffer = ByteBuffer.wrap(bytes)
            while (buffer.hasRemaining()) { localOpen(); if (held.read(buffer) <= 0) fail("gallery_pc_stage_member_changed"); localOpen() }
            if (held.read(ByteBuffer.allocate(1)) != -1) fail("gallery_pc_stage_member_changed")
        }
        val after = attributes(file)
        if (before.fileKey() != after.fileKey() || before.size() != after.size() || before.lastModifiedTime() != after.lastModifiedTime() ||
            hash(bytes) != witness.sha256) fail("gallery_pc_stage_member_changed")
        localOpen(); return protection.open(bytes, domain + name)
    }
    private fun create(name: String, clear: ByteArray): Witness {
        requireCurrent()
        val cipher = protection.seal(clear, domain + name)
        requireCurrent()
        synchronized(membershipGate) {
            if (writing != null) fail("gallery_pc_stage_chunk_invalid")
            writing = name
        }
        try {
            val file = File(root, name)
            val witness = FileChannel.open(file.toPath(), setOf(WRITE, CREATE_NEW, NOFOLLOW_LINKS), PRIVATE_FILE).use { held ->
                val key = attributes(file).fileKey()?.toString() ?: fail("gallery_pc_stage_identity_required")
                val buffer = ByteBuffer.wrap(cipher)
                while (buffer.hasRemaining()) { requireCurrent(); held.write(buffer) }
                held.force(true)
                boundary("pc-stage-cipher-durable-before-close")
                requireCurrent()
                if (attributes(file).fileKey()?.toString() != key) fail("gallery_pc_stage_member_changed")
                Witness(key, cipher.size.toLong(), hash(cipher))
            }
            synchronized(membershipGate) { files[name] = witness }
            synchronisiereOrdner(root)
            val actual = read(name)
            try { if (!actual.contentEquals(clear)) fail("gallery_pc_stage_readback_failed") } finally { actual.fill(0) }
            return witness
        } finally { synchronized(membershipGate) { writing = null } }
    }
    internal fun append(number: Int, bytes: ByteArray) {
        requireCurrent()
        val wanted = minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), expected.size - size).toInt()
        if (complete || number != chunks || wanted <= 0 || bytes.size != wanted) fail("gallery_pc_stage_chunk_invalid")
        create("chunk-$number.enc", bytes)
        digest.update(bytes); size += bytes.size; chunks++
        requireCurrent()
    }
    internal fun finish(): NativeIncomingMediaObservation {
        requireCurrent()
        if (complete || size != expected.size || NativeHex.lower(digest.digest()) != expected.sha256) fail("gallery_pc_stage_content_changed")
        val body = buildJsonObject {
            put("format", 1); put("reservation", DeviceFileControl.digest("magnolie-pc-stage-reservation-v1\u0000", record.body))
            put("manifest", manifest.wire()); put("files", synchronized(membershipGate) { JsonObject(files.mapValues { it.value.wire() }) })
        }
        val clear = TelefonKanonisch.bytes(body)
        val witness = try { create("complete.enc", clear) } finally { clear.fill(0) }
        complete = true
        verifyRaw()
        val observed = NativeIncomingMediaInspection.inspectStagedPc(this, owner.photosOnly)
        verifyRaw(); requireCurrent()
        val previous = record; val next = previous.seal(witness.wire(), observed)
        records = Records(previous, next)
        try {
            index.sealPcStage(previous, next, owner, grant, channel)
            records = Records(next)
        } catch (error: Throwable) { close(); throw error }
        requireCurrent()
        return observed
    }
    internal fun verifyRaw() {
        requireCurrent()
        if (!complete) fail("gallery_pc_stage_not_complete")
        read("complete.enc").fill(0)
        val hash = MessageDigest.getInstance("SHA-256"); var count = 0L
        for (number in 0 until chunks) {
            requireCurrent(); val clear = read("chunk-$number.enc")
            try {
                if (clear.size != minOf(DeviceFileManifest.CHUNK_BYTES.toLong(), expected.size - count).toInt()) fail("gallery_pc_stage_content_changed")
                hash.update(clear); count += clear.size
            } finally { clear.fill(0) }
        }
        if (count != expected.size || NativeHex.lower(hash.digest()) != expected.sha256) fail("gallery_pc_stage_content_changed")
        requireCurrent()
    }
    internal fun readAt(position: Long, target: ByteArray, offset: Int, length: Int): Int {
        requireCurrent()
        if (!complete || position < 0 || offset < 0 || length < 0 || offset > target.size - length) fail("gallery_pc_stage_range_invalid")
        if (length == 0) return 0
        if (position >= expected.size) return -1
        read("complete.enc").fill(0)
        val wanted = minOf(length.toLong(), expected.size - position).toInt(); var copied = 0
        try {
            while (copied < wanted) {
                requireCurrent(); val at = position + copied
                val clear = read("chunk-${at / DeviceFileManifest.CHUNK_BYTES}.enc")
                try {
                    val start = (at % DeviceFileManifest.CHUNK_BYTES).toInt(); val amount = minOf(wanted - copied, clear.size - start)
                    if (amount <= 0) fail("gallery_pc_stage_range_invalid")
                    clear.copyInto(target, offset + copied, start, start + amount); copied += amount
                } finally { clear.fill(0) }
            }
            requireCurrent(); return wanted
        } catch (error: Throwable) { target.fill(0, offset, offset + copied); throw error }
    }
    internal fun input(): InputStream = object : InputStream() {
        private var position = 0L
        private var closed = false
        override fun read(): Int {
            val one = ByteArray(1)
            return try { if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 255 } finally { one.fill(0) }
        }
        override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
            if (closed) fail("gallery_pc_stage_closed")
            return readAt(position, bytes, offset, minOf(length, DeviceFileManifest.CHUNK_BYTES)).also { if (it > 0) position += it }
        }
        override fun skip(count: Long): Long {
            if (closed) fail("gallery_pc_stage_closed")
            requireCurrent()
            return minOf(maxOf(0L, count), expected.size - position).also { position += it }
        }
        override fun available(): Int {
            if (closed) fail("gallery_pc_stage_closed")
            requireCurrent(); return minOf(Int.MAX_VALUE.toLong(), expected.size - position).toInt()
        }
        override fun close() { closed = true }
    }
    override fun close() { closed.set(true) } // No deletion, eviction, or name-based restart adoption.

    companion object {
        private val PRIVATE_FILE = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))
        private val PRIVATE_DIRECTORY = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))
        private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        private fun hash(bytes: ByteArray) = NativeHex.lower(MessageDigest.getInstance("SHA-256").digest(bytes))
        private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
        internal fun allocate(context: Context, index: PhotoSourceJobIndex, plan: GalleryPcReplacementPlan, acceptance: GalleryIncomingAcceptance,
            owner: NativeGalleryIncomingOwner, grant: NativeGalleryPcWriteGrant, channel: TelefonSecureChannel,
            lane: Any, boundary: (String) -> Unit): NativeGalleryPcStage {
            if (!NativeGalleryMediaIoLane.isOwnedBy(lane)) fail("gallery_incoming_worker_busy")
            if (GalleryPcStageRecord.media(plan).kind != GalleryMediaType.IMAGES) fail("gallery_pc_stage_video_owner_required")
            index.requirePcStageAdmission(grant, channel, plan); index.requirePcStageCapacity(plan)
            val base = context.applicationContext.noBackupFilesDir.canonicalFile
            val parent = File(base, "native-pc-replacement-stages")
            if (!Files.exists(parent.toPath(), NOFOLLOW_LINKS)) Files.createDirectory(parent.toPath(), PRIVATE_DIRECTORY)
            val baseKey = attributes(base).fileKey()?.toString() ?: fail("gallery_pc_stage_identity_required")
            val parentKey = attributes(parent).fileKey()?.toString() ?: fail("gallery_pc_stage_identity_required")
            if (!attributes(parent).isDirectory || parent.canonicalFile != parent || Files.getPosixFilePermissions(parent.toPath(), NOFOLLOW_LINKS)
                    .any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") }) fail("gallery_pc_stage_not_private")
            val root = File(parent, plan.id)
            Files.createDirectory(root.toPath(), PRIVATE_DIRECTORY) // Occupied/uncertain roots are never adopted or reset.
            val key = attributes(root).fileKey()?.toString() ?: fail("gallery_pc_stage_identity_required")
            val record = GalleryPcStageRecord.create(plan, root, key, acceptance)
            val stage = NativeGalleryPcStage(base, parent, root, baseKey, parentKey, index, owner, grant, channel, record, lane, boundary)
            try {
                index.reservePcStage(record, owner, grant, channel)
                val header = TelefonKanonisch.bytes(record.body)
                try { stage.create("owner.enc", header) } finally { header.fill(0) }
                return stage
            } catch (error: Throwable) { stage.close(); throw error }
        }
    }
}
