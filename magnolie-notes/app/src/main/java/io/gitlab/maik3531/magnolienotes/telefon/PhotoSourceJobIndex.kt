package io.gitlab.maik3531.magnolienotes.telefon

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.os.CancellationSignal
import io.gitlab.maik3531.magnolienotes.daten.synchronisiereOrdner
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.NoSuchFileException
import java.nio.file.StandardOpenOption.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.util.UUID

internal data class PhotoSourceJob internal constructor(val id: String, val version: String,
    val sourceContext: String, val plainBytes: Long, val cipherBudget: Long,
    val rootKey: String?, val phase: String, val snapshot: JsonObject?)

internal class IndexedPhotoSource internal constructor(private val index: PhotoSourceJobIndex,
    val job: PhotoSourceJob, private val scope: NativePhotoSourceAuthority, private val lease: NativePhotoSourceLease,
    private val snapshot: ProtectedPhotoSourceSnapshot) {
    val manifest: DeviceFileManifest get() = index.withSealedHead(job, scope, lease) { snapshot.manifest }
    val galleryOrigins: GalleryPhotoOrigins? get() = index.withSealedHead(job, scope, lease) { snapshot.galleryOrigins }
    fun readChunk(fileId: String, chunk: Int): ByteArray = index.withSealedHead(job, scope, lease) { snapshot.readChunk(fileId, chunk) }
    fun observeImageAnimation(fileId: String, ensureNative: () -> Unit = {}): NativeImageAnimationObservation = index.withSealedHead(job, scope, lease) {
        if (lease !is GalleryPhotoSourceLease || lease.activation.mediaType != GalleryMediaType.IMAGES)
            DeviceFileControl.fail("image_animation_native_image_scope_required")
        ensureNative()
        NativeImageAnimation.inspect(snapshot.manifest, fileId) { ensureNative(); readChunk(fileId, it) }.also { ensureNative() }
    }
    fun mediaPage(after: Int, ensureNative: () -> Unit = {}): JsonObject = index.withSealedHead(job, scope, lease) {
        NativeGalleryMediaProjection.page(snapshot, lease, after, ::readChunk, ensureNative)
    }

    internal fun selectedJob(fileIds: List<String>, cancellation: CancellationSignal, permitted: () -> Unit): PhotoSourceJob =
        index.withSealedHead(job, scope, lease) {
            permitted(); cancellation.throwIfCanceled()
            if (lease !is GalleryPhotoSourceLease || fileIds.isEmpty() || fileIds != fileIds.sorted().distinct() ||
                fileIds.any { id -> snapshot.manifest.files.none { it.id == id } }) DeviceFileControl.fail("photo_snapshot_invalid_selection")
            if (index.remoteAcceptance(job) != null || index.resumeAttempt(job) != null)
                DeviceFileControl.fail("photo_jobs_selected_preview_already_accepted")
            val origins = snapshot.galleryOrigins ?: DeviceFileControl.fail("gallery_media_origins_required")
            val chosen = snapshot.manifest.files.filter { it.id in fileIds }
            val entries = chosen.map { file ->
                val origin = origins.entries.single { it.fileId == file.id }
                PhotoInventoryEntry("content://media/${lease.album.volume}/${lease.activation.mediaType.uriSegment}/media/${origin.nativeMember.substringBefore(':')}",
                    origin.nativeMember, file.path, file.size, null, origin.nativeRevision)
            }
            val reserved = index.reserve(PhotoSourceInventory(lease, entries), scope)
            permitted(); cancellation.throwIfCanceled()
            val selected = ProtectedPhotoSourceSnapshot.selectFrozen(snapshot, index.rootFile(reserved), fileIds, cancellation)
            permitted(); cancellation.throwIfCanceled()
            index.publishSnapshot(reserved, selected, scope, lease)
        }
    /** Preflight only; the actual send handler must recheck live negotiated
     * authority. Returning an envelope does not preserve consent after revoke.
     */
    fun offerMessage(now: Long = System.currentTimeMillis(), messageId: String = UUID.randomUUID().toString()): JsonObject =
        index.withSealedHead(job, scope, lease) { DeviceFileOfferEnvelope.create(snapshot.manifest, now, messageId) }
    fun retireAndDiscard() = index.retireAndClean(job) { snapshot.discard() }

    fun commitRemoteSaved(accepted: DeviceFileRemoteAcceptance, message: JsonObject, permitted: () -> Unit): PhotoSourceRemoteSaved =
        index.commitRemoteSaved(job, scope, lease, accepted, message, permitted)

    fun commitRemoteAcceptance(offer: NativeGalleryOfferOutput, accepted: DeviceFileRemoteAcceptance, permitted: () -> Unit): PhotoSourceRemoteAcceptance =
        index.commitRemoteAcceptance(job, scope, lease, offer, accepted, permitted)

    fun requireRemoteAcceptance(accepted: DeviceFileRemoteAcceptance) = index.withSealedHead(job, scope, lease) {
        val original = index.remoteAcceptance(job) ?: DeviceFileControl.fail("photo_jobs_remote_acceptance_required")
        if (original.originalAuthority == null) DeviceFileControl.fail("photo_jobs_remote_acceptance_repair_required")
        if (original.acceptance != PhotoSourceRemoteAcceptance.acceptanceWire(accepted)) DeviceFileControl.fail("photo_jobs_remote_acceptance_changed")
    }
}

/** Dedicated source-job DB only. Never opens/migrates the personal phone DB.
 * Retired/uncertain jobs retain both quota and their actual persisted metadata.
 */
internal class PhotoSourceJobIndex private constructor(private val directory: File, private val protection: DeviceTransferProtection,
    private val allowCreate: Boolean, private val boundary: (String) -> Unit) : AutoCloseable {
    constructor(directory: File, protection: DeviceTransferProtection, boundary: (String) -> Unit = {}) :
        this(directory, protection, true, boundary)
    private val root = directory.toPath()
    private val rootKey: Any = attributes(directory).fileKey() ?: fail("photo_jobs_root_identity_unavailable")
    private val path = File(directory, "photo-source-jobs.db")
    private lateinit var db: SQLiteDatabase
    private lateinit var dbKey: Any
    private var closed = false
    private var membership: PhotoSourceMembership? = null
    private var uncertain = false

    init {
        require(directory.isAbsolute && directory.canonicalFile == directory)
        gated {
            val exists = Files.exists(path.toPath(), NOFOLLOW_LINKS)
            if (!exists && !allowCreate) fail("photo_jobs_existing_index_required")
            val preparedHeader = if (!exists) {
                Files.newDirectoryStream(root).use { entries ->
                    if (entries.any { it.fileName.toString() != "photo-source-jobs.lock" }) fail("photo_jobs_missing_index_preserved")
                }
                protection.seal(MEMBER_HEADER.toByteArray(Charsets.US_ASCII), "photo-source-jobs-v1/header")
            } else null
            if (exists) regular(path) else Files.createFile(path.toPath(), PRIVATE_FILE)
            sidecars()
            db = SQLiteDatabase.openDatabase(path.path, null, SQLiteDatabase.OPEN_READWRITE or SQLiteDatabase.NO_LOCALIZED_COLLATORS)
            try {
                dbKey = attributes(path).fileKey() ?: fail("photo_jobs_db_identity_unavailable")
                if (exists) verifyHeader()
                db.enableWriteAheadLogging()
                db.execSQL("PRAGMA synchronous=FULL")
                db.rawQuery("PRAGMA wal_autocheckpoint=256", null).use { if (!it.moveToFirst()) fail("photo_jobs_wal_configuration_failed") }
                if (!exists) {
                    transaction(bootstrap = true) {
                        db.execSQL("CREATE TABLE source_meta(name TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)")
                        db.execSQL("CREATE TABLE source_jobs(job_id TEXT PRIMARY KEY NOT NULL, sealed BLOB NOT NULL)")
                        db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", "format"); put("sealed", preparedHeader!!) })
                        membershipModel().initialize()
                    }
                    synchronisiereOrdner(directory)
                }
                verifyHeader()
            } catch (error: Exception) { db.close(); closed = true; throw error }
        }
    }

    /** Durable encrypted reservation/readback BEFORE creating any source root. */
    fun reserve(inventory: PhotoSourceInventory, scope: NativePhotoSourceAuthority): PhotoSourceJob = gated {
        writableMembership()
        val lease = inventory.lease
        fun allowed() { if (!scope.isCurrent(lease)) fail("photo_jobs_source_revoked") }
        allowed()
        if (inventory.entries.size !in 1..DeviceFileManifest.MAX_FILES) fail("photo_jobs_inventory_limit")
        var plain = 0L; var chunks = 0L; var empty = 0L
        inventory.entries.forEach {
            if (it.advertisedBytes !in 0..DeviceFileManifest.MAX_FILE_BYTES || !DeviceFileManifest.portablePath(it.relativePath))
                fail("photo_jobs_inventory_limit")
            plain += it.advertisedBytes
            chunks += (it.advertisedBytes + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES
            if (it.advertisedBytes == 0L) empty++
        }
        if (plain > DeviceFileManifest.MAX_TOTAL_BYTES) fail("photo_jobs_source_bytes_limit")
        val budget = plain + chunks * 29L + empty * 29L + 2 * (262144L + 28L)
        val id = UUID.randomUUID().toString().replace("-", "")
        val next = PhotoSourceJob(id, "", context(lease), plain, budget, null, "reserved", null)
        transaction {
            val jobs = readAll()
            validateLayout(jobs)
            if (jobs.size >= MAX_JOBS || jobs.sumOf { it.plainBytes } + plain > DeviceFileManifest.MAX_TOTAL_BYTES ||
                jobs.sumOf { it.cipherBudget } + budget > MAX_CIPHER_BYTES) fail("photo_jobs_quota_reached")
            allowed()
            insert(next)
            allowed()
        }
        val reserved = readOne(id) ?: fail("photo_jobs_reservation_readback_missing")
        if (data(reserved) != data(next)) fail("photo_jobs_reservation_readback_changed")
        boundary("reservation-committed")
        allowed()
        val child = rootFile(reserved)
        Files.createDirectory(child.toPath(), PRIVATE_DIRECTORY)
        synchronisiereOrdner(directory)
        allowed()
        update(reserved, reserved.copy(rootKey = attributes(child).fileKey()?.toString()
            ?: fail("photo_jobs_child_identity_unavailable")), ::allowed)
    }

    fun jobs(): List<PhotoSourceJob> = gated { readAll() }

    /** Native preflight before enumerating live media, not a READ grant. */
    fun requireMembershipReady(): Unit = gated { writableMembership(); Unit }

    /** Metadata-only historical inspection; never renews a source lease. */
    fun remoteSaved(expected: PhotoSourceJob): PhotoSourceRemoteSaved? = gated {
        val actual = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        if (actual != expected) fail("photo_jobs_cas_conflict")
        readRemoteSaved(actual)
    }

    private fun readRemoteSaved(job: PhotoSourceJob): PhotoSourceRemoteSaved? = meta("remote-saved-v1/" + job.id)?.let {
        PhotoSourceRemoteSaved.parse(parse(protection.open(it, "photo-source-jobs-v1/remote-saved/" + job.id)), job)
    }

    fun remoteAcceptance(expected: PhotoSourceJob): PhotoSourceRemoteAcceptance? = gated {
        val actual = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        if (actual != expected) fail("photo_jobs_cas_conflict")
        readRemoteAcceptance(actual)
    }

    private fun readRemoteAcceptance(job: PhotoSourceJob): PhotoSourceRemoteAcceptance? = meta("remote-acceptance-v1/" + job.id)?.let {
        PhotoSourceRemoteAcceptance.parse(parse(protection.open(it, "photo-source-jobs-v1/remote-acceptance/" + job.id)), job)
    }

    fun resumeAttempt(expected: PhotoSourceJob): PhotoSourceResumeAttempt? = gated {
        val actual = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        if (actual != expected) fail("photo_jobs_cas_conflict")
        readResumeAttempt(actual)
    }

    /** Exact historical metadata lookup, never a cache/OS READ or run grant. */
    internal fun lookupGalleryResume(senderId: String, sourceId: String, transferId: String, manifestSha256: String,
        receiver: NativePhotoReceiver, policyEpoch: String): JsonObject = gated {
        writableMembership()
        if (!receiver.allowed || receiver.pairingEpoch == null) fail("photo_jobs_historical_authority_changed")
        val matches = readAll().filter { job ->
            job.snapshot?.get("manifest")?.let { value ->
                val manifest = DeviceFileManifest.parse(value as? JsonObject ?: fail("photo_jobs_snapshot_missing"))
                manifest.senderId == senderId && manifest.sourceId == sourceId && manifest.transferId == transferId && manifest.fingerprint == manifestSha256
            } == true
        }
        val job = matches.singleOrNull() ?: fail("photo_jobs_historical_original_job_required")
        if (job.phase !in setOf("sealed", "retired")) fail("photo_jobs_historical_original_job_required")
        val original = readRemoteAcceptance(job) ?: fail("photo_jobs_remote_acceptance_required")
        val authority = original.originalAuthority ?: fail("photo_jobs_remote_acceptance_repair_required")
        val tree = authority.record["tree"] as JsonPrimitive
        if (authority.receiverId != receiver.peerId || authority.receiverIdentitySha256 != receiver.identitySha256 ||
            authority.pairingEpoch != receiver.pairingEpoch || authority.permissionEpoch != receiver.permissionEpoch ||
            authority.record["epoch"] != JsonPrimitive(policyEpoch) ||
            !(tree.content.startsWith("gallery-album-v1:") || tree.content.startsWith("gallery-video-album-v1:")))
            fail("photo_jobs_historical_authority_changed")
        val attempt = readResumeAttempt(job)
        buildJsonObject {
            put("job_id", job.id); put("job_version", job.version); put("phase", job.phase)
            put("source_id", sourceId); put("transfer_id", transferId); put("manifest_sha256", manifestSha256)
            put("remote_saved_history", readRemoteSaved(job) != null)
            put("attempt_phase", attempt?.phase?.let(::JsonPrimitive) ?: JsonNull)
            put("attempt_id", attempt?.id?.let(::JsonPrimitive) ?: JsonNull)
            put("attempt_sha256", attempt?.version?.let(::JsonPrimitive) ?: JsonNull)
        }
    }

    private fun readResumeAttempt(job: PhotoSourceJob): PhotoSourceResumeAttempt? = meta("resume-attempt-v1/" + job.id)?.let {
        val original = readRemoteAcceptance(job) ?: fail("photo_jobs_remote_acceptance_required")
        PhotoSourceResumeAttempt.parse(parse(protection.open(it, "photo-source-jobs-v1/resume-attempt/" + job.id)), job, original)
    }

    internal fun resumeAbandonments(job: PhotoSourceJob): List<PhotoSourceResumeAbandonment> = gated {
        writableMembership()
        if (readOne(job.id) != job) fail("photo_jobs_cas_conflict")
        readResumeAbandonments(job)
    }

    private fun readResumeAbandonments(job: PhotoSourceJob): List<PhotoSourceResumeAbandonment> {
        val cipher = meta("resume-abandonments-v1/" + job.id) ?: return emptyList()
        val value = parse(protection.open(cipher, "photo-source-jobs-v1/resume-abandonments/" + job.id))
        val entries = value["receipts"] as? JsonArray ?: fail("photo_jobs_resume_abandonment_invalid")
        if (value.keys != setOf("format", "receipts") || value["format"] != JsonPrimitive(1) ||
            entries.size !in 1..PhotoSourceResumeAbandonment.MAX_HISTORY) fail("photo_jobs_resume_abandonment_invalid")
        val original = readRemoteAcceptance(job) ?: fail("photo_jobs_remote_acceptance_required")
        val receipts = entries.map { PhotoSourceResumeAbandonment.parse(it as? JsonObject ?: fail("photo_jobs_resume_abandonment_invalid"), job, original) }
        if (receipts.map { it.head["attempt_id"] }.distinct().size != receipts.size) fail("photo_jobs_resume_abandonment_invalid")
        return receipts
    }

    /** Called only with the runtime's actual stopped/ended ownership gate.
     * Equality tokens alone never call this method from a metadata lookup. */
    internal fun abandonResumeAttempt(job: PhotoSourceJob, command: JsonObject, observedAt: Long,
        permitted: () -> Unit): PhotoSourceResumeAbandonment = gated {
        writableMembership(); permitted()
        if (job.phase != "sealed" || readOne(job.id) != job || readRemoteSaved(job) != null)
            fail("photo_jobs_resume_abandonment_held")
        val parsed = DeviceFileSourceCommand.parse(command, observedAt)
        val head = readResumeAttempt(job) ?: fail("photo_jobs_resume_attempt_missing")
        if (head.id != parsed.attemptId || head.version != parsed.attemptSha256)
            fail("photo_jobs_resume_attempt_changed")
        val original = readRemoteAcceptance(job) ?: fail("photo_jobs_remote_acceptance_required")
        val prior = readResumeAbandonments(job)
        prior.singleOrNull { it.head["attempt_id"] == head.record["attempt_id"] }?.let {
            if (it.head != head.record || it.command != command) fail("photo_jobs_resume_abandonment_changed")
            permitted(); return@gated it
        }
        if (prior.size >= PhotoSourceResumeAbandonment.MAX_HISTORY) fail("photo_jobs_resume_abandonments_held")
        val next = PhotoSourceResumeAbandonment.create(job, original, head, command, observedAt)
        val name = "resume-abandonments-v1/" + job.id
        val before = meta(name)
        val value = JsonObject(mapOf("format" to JsonPrimitive(1), "receipts" to JsonArray(prior.map { it.record } + next.record)))
        val cipher = protection.seal(frame(value), "photo-source-jobs-v1/resume-abandonments/" + job.id)
        permitted()
        transaction {
            if (readOne(job.id) != job || readResumeAttempt(job)?.record != head.record || readRemoteSaved(job) != null ||
                (before == null && meta(name) != null) || (before != null && meta(name)?.contentEquals(before) != true)) fail("photo_jobs_cas_conflict")
            permitted()
            if (before == null) db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", name); put("sealed", cipher) })
            else if (db.update("source_meta", ContentValues().apply { put("sealed", cipher) }, "name=?", arrayOf(name)) != 1)
                fail("photo_jobs_cas_conflict")
            membership!!.advance(); permitted()
        }
        permitted()
        if (readResumeAbandonments(job).last().record != next.record) fail("photo_jobs_resume_abandonment_readback_failed")
        next
    }

    internal fun prepareResumeAttempt(owner: NativeGalleryResumeAttempt, job: PhotoSourceJob, original: PhotoSourceRemoteAcceptance,
        offer: JsonObject, permitted: () -> Unit): NativeResumeAttemptStorage = gated {
        writableMembership(); permitted()
        if (job.phase != "sealed" || readOne(job.id) != job || readRemoteAcceptance(job)?.record != original.record)
            fail("photo_jobs_historical_original_job_required")
        val next = PhotoSourceResumeAttempt.prepare(job, original, owner.id, offer)
        val existing = readResumeAttempt(job)
        val replacing = existing != null && existing.base != next.base
        if (replacing && readResumeAbandonments(job).none { it.head == existing!!.record })
            fail("photo_jobs_resume_original_attempt_held")
        if (existing == null || replacing) {
            val cipher = protection.seal(frame(next.record), "photo-source-jobs-v1/resume-attempt/" + job.id)
            permitted()
            transaction {
                if (readOne(job.id) != job || readResumeAttempt(job)?.record != existing?.record || readRemoteSaved(job) != null)
                    fail("photo_jobs_cas_conflict")
                if (replacing && readResumeAbandonments(job).none { it.head == existing!!.record }) fail("photo_jobs_cas_conflict")
                permitted()
                if (existing == null) db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", "resume-attempt-v1/" + job.id); put("sealed", cipher) })
                else if (db.update("source_meta", ContentValues().apply { put("sealed", cipher) }, "name=?", arrayOf("resume-attempt-v1/" + job.id)) != 1)
                    fail("photo_jobs_cas_conflict")
                membership!!.advance(); permitted()
            }
            if (readResumeAttempt(job)?.record != next.record) fail("photo_jobs_resume_attempt_readback_failed")
        }
        permitted()
        NativeResumeAttemptStorage(this, owner, job, next.base)
    }

    internal fun requireResumeAttempt(job: PhotoSourceJob, base: JsonObject): PhotoSourceResumeAttempt = gated {
        writableMembership()
        if (job.phase != "sealed" || readOne(job.id) != job) fail("photo_jobs_historical_original_job_required")
        val state = readResumeAttempt(job) ?: fail("photo_jobs_resume_attempt_missing")
        if (state.base != base) fail("photo_jobs_resume_attempt_changed")
        state
    }

    internal fun advanceResumeAttempt(job: PhotoSourceJob, base: JsonObject, phase: String, message: JsonObject?, observedAt: Long?,
        permitted: () -> Unit): Unit = gated {
        val prior = requireResumeAttempt(job, base); permitted()
        if (phase == "sent" && prior.phase == "sent") return@gated
        if (phase == "accepted" && prior.phase == "accepted") {
            if (prior.record["acceptance"] != message) fail("photo_jobs_resume_acceptance_changed")
            permitted(); return@gated
        }
        if (phase == "sent" && prior.phase != "prepared" || phase == "accepted" && prior.phase != "sent" || phase !in setOf("sent", "accepted"))
            fail("photo_jobs_resume_attempt_phase_conflict")
        val original = readRemoteAcceptance(job) ?: fail("photo_jobs_remote_acceptance_required")
        val next = PhotoSourceResumeAttempt.advance(prior, phase, job, original, message, observedAt)
        val name = "resume-attempt-v1/" + job.id
        val before = meta(name) ?: fail("photo_jobs_resume_attempt_missing")
        val cipher = protection.seal(frame(next.record), "photo-source-jobs-v1/resume-attempt/" + job.id)
        permitted()
        transaction {
            if (readOne(job.id) != job || meta(name)?.contentEquals(before) != true) fail("photo_jobs_cas_conflict")
            permitted()
            if (db.update("source_meta", ContentValues().apply { put("sealed", cipher) }, "name=?", arrayOf(name)) != 1)
                fail("photo_jobs_resume_attempt_missing")
            membership!!.advance(); permitted()
        }
        permitted()
        if (readResumeAttempt(job)?.record != next.record) fail("photo_jobs_resume_attempt_readback_failed")
    }

    internal fun requireGalleryResumeOriginal(expected: PhotoSourceJob): PhotoSourceRemoteAcceptance = gated {
        writableMembership()
        if (expected.phase != "sealed" || readOne(expected.id) != expected) fail("photo_jobs_historical_original_job_required")
        val original = readRemoteAcceptance(expected) ?: fail("photo_jobs_remote_acceptance_required")
        if (original.originalAuthority == null) fail("photo_jobs_remote_acceptance_repair_required")
        original
    }

    internal fun renewGallerySource(expected: PhotoSourceJob, senderId: String, inventory: PhotoSourceInventory,
        scope: GalleryPhotoSourceScope, reader: AndroidGalleryPhotoSource, cancellation: CancellationSignal,
        preparingPermitted: () -> Unit, currentPermitted: () -> Unit,
        elapsed: () -> Long = DeviceFileControl::monotonicMs): NativeGalleryRenewedSource {
        val issued = elapsed(); var last = issued
        fun preparationCurrent() {
            val tick = elapsed()
            if (issued < 0 || tick < last || tick - issued >= DeviceFileControl.MAX_TTL_MS) fail("gallery_resume_preparation_expired")
            last = tick; preparingPermitted()
        }
        preparationCurrent()
        val original = requireGalleryResumeOriginal(expected)
        val lease = inventory.lease as? GalleryPhotoSourceLease ?: fail("photo_snapshot_wrong_source_kind")
        fun originalCurrent() {
            currentPermitted()
            if (requireGalleryResumeOriginal(expected).record != original.record) fail("photo_jobs_cas_conflict")
        }
        NativeGalleryResumeInspection.inspect(senderId, expected, original, inventory, scope, reader, cancellation, {
            preparationCurrent(); originalCurrent()
        }, elapsed)
        val preparing = java.util.concurrent.atomic.AtomicBoolean(true)
        val renewed = NativeGalleryRenewalAuthority(scope, lease) {
            if (preparing.get()) preparationCurrent()
            originalCurrent()
        }
        val context = original.originalAuthority ?: fail("photo_jobs_remote_acceptance_repair_required")
        val snapshot = ProtectedPhotoSourceSnapshot.restoreRenewed(rootFile(expected), expected.snapshot ?: fail("photo_jobs_snapshot_missing"),
            senderId, renewed, lease, context, protection, cancellation)
        preparationCurrent(); originalCurrent(); preparing.set(false)
        snapshot.manifest // Actual current READ gate after the preparation ticket ends.
        return NativeGalleryRenewedSource(expected, snapshot, original)
    }

    fun issueHistoricalSavedAction(expected: PhotoSourceJob, current: () -> NativePhotoReceiver?,
        elapsed: () -> Long = DeviceFileControl::monotonicMs): NativeHistoricalSavedAction = gated {
        writableMembership()
        if (readOne(expected.id) != expected || expected.phase != "sealed") fail("photo_jobs_historical_original_job_required")
        val original = readRemoteAcceptance(expected) ?: fail("photo_jobs_remote_acceptance_required")
        val receiver = current() ?: fail("photo_jobs_historical_authority_changed")
        NativeHistoricalSavedAction(this, expected, original, receiver, current, elapsed).also { it.validate(this) }
    }

    /** A fresh explicit native action, not an incoming packet, supplies the
     * original-job authority. No source lease/cache/MediaStore is opened here. */
    fun commitHistoricalRemoteSaved(action: NativeHistoricalSavedAction, message: JsonObject,
        now: () -> Long = System::currentTimeMillis): PhotoSourceRemoteSaved {
        action.consume(this)
        return gated {
            writableMembership(); action.validate(this)
            val job = action.job
            if (job.phase != "sealed" || readOne(job.id) != job || readRemoteAcceptance(job)?.record != action.original.record)
                fail("photo_jobs_historical_original_job_required")
            val manifest = DeviceFileManifest.parse(job.snapshot?.get("manifest") as? JsonObject ?: fail("photo_jobs_snapshot_missing"))
            val observed = DeviceFileSavedEnvelope.parse(message, manifest, now())
            val next = PhotoSourceRemoteSaved.capture(job, action.original.historicalAcceptance(), message)
            fun permitted() {
                action.validate(this)
                if (now() >= observed.expires) fail("photo_jobs_historical_confirmation_expired")
            }
            permitted()
            commitRemoteSavedRecord(job, next, ::permitted).also { permitted() }
        }
    }

    internal fun commitRemoteAcceptance(expected: PhotoSourceJob, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease,
        offer: NativeGalleryOfferOutput, accepted: DeviceFileRemoteAcceptance, permitted: () -> Unit): PhotoSourceRemoteAcceptance =
        withSealedHead(expected, scope, lease) {
            permitted()
            if (accepted.permissionEpoch != lease.receiver.permissionEpoch) fail("photo_jobs_remote_acceptance_authority_changed")
            val next = PhotoSourceRemoteAcceptance.capture(expected, offer, accepted, lease)
            val original = readRemoteAcceptance(expected)
            if (original != null) {
                if (original.originalAuthority == null) fail("photo_jobs_remote_acceptance_repair_required")
                if (original.record != next.record) fail("photo_jobs_remote_acceptance_changed")
                permitted(); original
            } else {
                if (readRemoteSaved(expected) != null) fail("photo_jobs_remote_acceptance_repair_required")
                val cipher = protection.seal(frame(next.record), "photo-source-jobs-v1/remote-acceptance/" + expected.id)
                permitted()
                transaction {
                    if (readOne(expected.id) != expected || meta("remote-acceptance-v1/" + expected.id) != null) fail("photo_jobs_cas_conflict")
                    permitted()
                    db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", "remote-acceptance-v1/" + expected.id); put("sealed", cipher) })
                    membership!!.advance(); permitted()
                }
                permitted()
                val result = readRemoteAcceptance(expected) ?: fail("photo_jobs_remote_acceptance_readback_failed")
                if (result.record != next.record) fail("photo_jobs_remote_acceptance_readback_failed")
                result
            }
        }

    internal fun commitRemoteSaved(expected: PhotoSourceJob, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease,
        accepted: DeviceFileRemoteAcceptance, message: JsonObject, permitted: () -> Unit): PhotoSourceRemoteSaved =
        withSealedHead(expected, scope, lease) {
            permitted()
            if (accepted.permissionEpoch != lease.receiver.permissionEpoch) fail("photo_jobs_remote_saved_authority_changed")
            val next = PhotoSourceRemoteSaved.capture(expected, accepted, message)
            val durableAcceptance = readRemoteAcceptance(expected) ?: fail("photo_jobs_remote_acceptance_required")
            if (durableAcceptance.originalAuthority == null) fail("photo_jobs_remote_acceptance_repair_required")
            if (durableAcceptance.acceptance != PhotoSourceRemoteAcceptance.acceptanceWire(accepted)) fail("photo_jobs_remote_acceptance_changed")
            commitRemoteSavedRecord(expected, next, permitted, GalleryKnownPhoneMedia.capture(expected, next, durableAcceptance, lease))
        }

    internal fun commitResumeRemoteSaved(source: NativeGalleryRenewedSource, projection: NativeResumeAcceptanceProjection,
        message: JsonObject, permitted: () -> Unit): PhotoSourceRemoteSaved = gated {
        writableMembership(); permitted()
        val job = source.job
        if (job.phase != "sealed" || readOne(job.id) != job) fail("photo_jobs_historical_original_job_required")
        val original = readRemoteAcceptance(job) ?: fail("photo_jobs_remote_acceptance_required")
        if (source.originalAcceptance().record != original.record) fail("photo_jobs_remote_acceptance_changed")
        val head = readResumeAttempt(job) ?: fail("photo_jobs_resume_attempt_missing")
        if (head.phase != "accepted" || head.id != projection.attemptId || head.record["acceptance"] != projection.message ||
            DeviceFileAcceptanceEnvelope.parse(projection.message, head.record.long("accepted_at")) != projection.accepted)
            fail("photo_jobs_resume_acceptance_changed")
        // New negotiation's command digest is not the original accepted source
        // witness. Preserve the old acceptance exactly after validating the child.
        val next = PhotoSourceRemoteSaved.capture(job, original.historicalAcceptance(), message)
        permitted()
        commitRemoteSavedRecord(job, next, permitted, GalleryKnownPhoneMedia.capture(job, next, original, source.nativeGalleryLease()))
    }

    private fun commitRemoteSavedRecord(expected: PhotoSourceJob, next: PhotoSourceRemoteSaved, permitted: () -> Unit,
        known: List<GalleryKnownPhoneMedia> = emptyList()): PhotoSourceRemoteSaved {
        val original = readRemoteSaved(expected)
        val additions = known.filter { value ->
            val before = knownPhoneMedia(value.id)
            if (before != null && before.body != value.body) fail("gallery_known_phone_media_original_changed")
            before == null
        }
        if (original != null) {
            if (original.confirmation.fingerprint != next.confirmation.fingerprint ||
                original.record["acceptance"] != next.record["acceptance"]) fail("photo_jobs_remote_saved_changed")
            if (additions.isNotEmpty()) transaction {
                if (readOne(expected.id) != expected || readRemoteSaved(expected)?.record != original.record) fail("photo_jobs_cas_conflict")
                permitted(); appendKnownPhoneMedia(additions); permitted()
            }
            permitted()
            return original
        } else {
            val cipher = protection.seal(frame(next.record), "photo-source-jobs-v1/remote-saved/" + expected.id)
            permitted()
            transaction {
                if (readOne(expected.id) != expected || meta("remote-saved-v1/" + expected.id) != null) fail("photo_jobs_cas_conflict")
                permitted()
                db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", "remote-saved-v1/" + expected.id); put("sealed", cipher) })
                membership!!.advance()
                appendKnownPhoneMedia(additions)
                permitted()
            }
            permitted()
            val result = readRemoteSaved(expected) ?: fail("photo_jobs_remote_saved_readback_failed")
            if (result.record != next.record) fail("photo_jobs_remote_saved_readback_failed")
            return result
        }
    }

    internal fun knownPhoneMedia(id: String): GalleryKnownPhoneMedia? = gated {
        if (!DeviceFileControl.hash(id)) fail("gallery_known_phone_media_invalid")
        val name = GalleryKnownPhoneMedia.PREFIX + id
        meta(name)?.let { cipher ->
            GalleryKnownPhoneMedia.parse(parse(protection.open(cipher, "photo-source-jobs-v1/" + name))).also {
                if (it.id != id) fail("gallery_known_phone_media_original_changed")
            }
        }
    }

    internal fun knownPhoneMedia(): List<GalleryKnownPhoneMedia> = gated {
        val ids = mutableListOf<String>()
        db.query("source_meta", arrayOf("name"), "name LIKE ?", arrayOf(GalleryKnownPhoneMedia.PREFIX + "%"), null, null, "name",
            (GalleryKnownPhoneMedia.MAX_RECORDS + 1).toString()).use { cursor ->
            while (cursor.moveToNext()) ids += cursor.getString(0).removePrefix(GalleryKnownPhoneMedia.PREFIX)
        }
        if (ids.size > GalleryKnownPhoneMedia.MAX_RECORDS) fail("gallery_known_phone_media_capacity")
        ids.map { knownPhoneMedia(it) ?: fail("gallery_known_phone_media_missing") }
    }

    /** Only invoked inside the source Saved writer transaction. No provider IO,
     * new READ owner or payload copying occurs. Aggregate advances once after
     * the bounded metadata batch; no callbacks see an unsealed intermediate. */
    private fun appendKnownPhoneMedia(values: List<GalleryKnownPhoneMedia>) {
        if (values.isEmpty()) return
        if (!db.inTransaction() || values.size > DeviceFileManifest.MAX_FILES || values.map { it.id }.distinct().size != values.size)
            fail("gallery_known_phone_media_writer_required")
        db.rawQuery("SELECT COUNT(*) FROM source_meta WHERE name LIKE ?", arrayOf(GalleryKnownPhoneMedia.PREFIX + "%")).use {
            if (!it.moveToFirst() || it.getLong(0) + values.size > GalleryKnownPhoneMedia.MAX_RECORDS) fail("gallery_known_phone_media_capacity")
        }
        for (value in values) {
            val name = GalleryKnownPhoneMedia.PREFIX + value.id
            if (meta(name) != null) fail("gallery_known_phone_media_original_changed")
            val cipher = protection.seal(frame(value.body), "photo-source-jobs-v1/" + name)
            if (cipher.size !in 29..8192) fail("gallery_known_phone_media_invalid")
            db.insertOrThrow("source_meta", null, ContentValues().apply { put("name", name); put("sealed", cipher) })
        }
        membership!!.advance(); boundary("gallery-known-phone-media-recorded")
    }

    /** Dedicated encrypted gallery policy rows in this private source DB, never
     * personal sync settings. Absence is off; corrupt/missing keys never reset.
     */
    fun galleryPolicy(): GalleryPhotoPolicySnapshot = gated { readGalleryPolicy() }

    fun compareAndSetGalleryPolicy(expected: GalleryPhotoPolicySnapshot, next: GalleryPhotoPolicy,
        permitted: () -> Boolean): GalleryPhotoPolicySnapshot = gated {
        verifyHeader()
        if (expected.repairPending || meta(GALLERY_FENCE) != null) fail("gallery_policy_repair_pending")
        if (readGalleryPolicy() != expected) fail("gallery_policy_cas_conflict")
        val oldPolicy = expected.policy
        if (oldPolicy?.pairingEpoch != null && next.pairingEpoch == null) fail("gallery_policy_pairing_downgrade")
        if (next != oldPolicy && ((oldPolicy?.revision ?: 1L) > 1 && next.revision == 1L ||
                next.revision > 1 && next.revision != (oldPolicy?.revision ?: 1L) + 1))
            fail("gallery_policy_revision_conflict")
        if (oldPolicy != null) {
            if (next.fileGrantRevision < oldPolicy.fileGrantRevision) fail("gallery_policy_permission_revision_rollback")
            if (next.fileGrantRevision == oldPolicy.fileGrantRevision &&
                (next.epoch != oldPolicy.epoch || next.enabled != oldPolicy.enabled || next.kinds != oldPolicy.kinds ||
                    next.receiverId != oldPolicy.receiverId || next.receiverIdentitySha256 != oldPolicy.receiverIdentitySha256 ||
                    next.pairingEpoch != oldPolicy.pairingEpoch || next.receiving != oldPolicy.receiving))
                fail("gallery_policy_permission_revision_conflict")
            if (oldPolicy.videos != null && (next.videos == null || next.videos.revision < oldPolicy.videos.revision))
                fail("gallery_video_policy_downgrade")
            if (oldPolicy.receiving != null && (next.receiving == null || next.receiving.revision < oldPolicy.receiving.revision))
                fail("gallery_receive_policy_downgrade")
        }
        if (!permitted()) fail("gallery_policy_revoked")
        val wanted = protection.seal(frame(next.wire()), "photo-source-jobs-v1/" + GALLERY_POLICY)
        val fence = protection.seal(frame(JsonObject(mapOf("format" to JsonPrimitive(1),
            "before" to JsonPrimitive(expected.version), "wanted" to JsonPrimitive(hash(wanted))))), "photo-source-jobs-v1/" + GALLERY_FENCE)
        transaction {
            if (readGalleryPolicy() != expected || meta(GALLERY_FENCE) != null) fail("gallery_policy_cas_conflict")
            if (!permitted()) fail("gallery_policy_revoked")
            putMeta(GALLERY_FENCE, fence)
        }
        if (meta(GALLERY_FENCE)?.contentEquals(fence) != true) fail("gallery_policy_fence_readback_failed")
        boundary("gallery-policy-fenced")
        transaction {
            if (galleryVersion(meta(GALLERY_POLICY)) != expected.version || meta(GALLERY_FENCE)?.contentEquals(fence) != true)
                fail("gallery_policy_cas_conflict")
            if (!permitted()) fail("gallery_policy_revoked")
            putMeta(GALLERY_POLICY, wanted)
            if (!permitted()) fail("gallery_policy_revoked")
        }
        boundary("gallery-policy-published")
        val saved = readGalleryPolicy()
        if (saved.version != hash(wanted) || saved.policy != next || !saved.repairPending || !permitted())
            fail("gallery_policy_commit_readback_failed")
        clearGalleryFence(fence, saved.version, permitted)
        readGalleryPolicy().also {
            if (it.repairPending || it.version != saved.version || it.policy != next) fail("gallery_policy_commit_readback_failed")
        }
    }

    fun inspectGalleryPolicyRepair(): GalleryPhotoPolicyRepair = gated { inspectGalleryRepair() }

    fun acknowledgeGalleryPolicyRepair(expected: GalleryPhotoPolicyRepair, permitted: () -> Boolean) = gated {
        if (inspectGalleryRepair() != expected || !permitted()) fail("gallery_policy_repair_observation_changed")
        val fence = meta(GALLERY_FENCE) ?: fail("gallery_policy_fence_missing")
        boundary("gallery-policy-repair-acknowledgement")
        if (inspectGalleryRepair() != expected || !permitted()) fail("gallery_policy_repair_observation_changed")
        clearGalleryFence(fence, expected.state.version, permitted)
    }

    private fun inspectGalleryRepair(): GalleryPhotoPolicyRepair {
        val fence = meta(GALLERY_FENCE) ?: fail("gallery_policy_fence_missing")
        val (before, wanted) = galleryFence(fence)
        val state = readGalleryPolicy()
        if (state.version != before && state.version != wanted) fail("gallery_policy_unknown_concurrent_state")
        return GalleryPhotoPolicyRepair(hash(fence), state, state.version == wanted)
    }

    private fun clearGalleryFence(fence: ByteArray, stateVersion: String, permitted: () -> Boolean) {
        // Re-establish the SAME original repair fence on uncertain clear/ACK.
        // Never overwrite a different repair head or roll back policy bytes.
        try {
            transaction {
                if (meta(GALLERY_FENCE)?.contentEquals(fence) != true || galleryVersion(meta(GALLERY_POLICY)) != stateVersion || !permitted())
                    fail("gallery_policy_repair_observation_changed")
                if (db.delete("source_meta", "name=?", arrayOf(GALLERY_FENCE)) != 1) fail("gallery_policy_fence_clear_failed")
                membership!!.advance()
                if (!permitted()) fail("gallery_policy_revoked")
            }
            boundary("gallery-policy-fence-cleared")
            if (meta(GALLERY_FENCE) != null || galleryVersion(meta(GALLERY_POLICY)) != stateVersion || !permitted())
                fail("gallery_policy_commit_readback_failed")
        } catch (error: Exception) {
            try { transaction { if (meta(GALLERY_FENCE) == null) putMeta(GALLERY_FENCE, fence) } }
            catch (repairError: Exception) { error.addSuppressed(repairError) }
            throw error
        }
    }

    /** Incoming lineage shares existing exact-root protection/membership, never
     * source cache quota or source READ ownership. No row is created on reads.
     * The native caller must serialize source/receive IO; current must be a
     * lock-free book/intent/retirement guard, not a transport/Werk monitor. */
    internal fun incomingPublication(id: String): GalleryIncomingPublication? = gated {
        if (!DeviceFileControl.hash(id)) fail("gallery_incoming_publication_invalid")
        val name = GalleryIncomingPublication.PREFIX + id
        meta(name)?.let { cipher ->
            GalleryIncomingPublication.parse(parse(protection.open(cipher, "photo-source-jobs-v1/" + name))).also {
                if (it.id != id) fail("gallery_incoming_publication_changed")
            }
        }
    }

    internal fun incomingAcceptance(id: String): GalleryIncomingAcceptance? = gated {
        if (!DeviceFileControl.hash(id)) fail("gallery_incoming_acceptance_invalid")
        val name = GalleryIncomingAcceptance.PREFIX + id
        meta(name)?.let { cipher ->
            GalleryIncomingAcceptance.parse(parse(protection.open(cipher, "photo-source-jobs-v1/" + name))).also {
                if (it.id != id) fail("gallery_incoming_acceptance_changed")
            }
        }
    }

    internal fun reserveIncomingAcceptance(value: GalleryIncomingAcceptance, current: () -> Unit): GalleryIncomingAcceptance = gated {
        writableMembership(); current()
        incomingAcceptance(value.id)?.let {
            if (it.body != value.body) fail("gallery_incoming_acceptance_changed")
            return@gated it
        }
        db.rawQuery("SELECT COUNT(*) FROM source_meta WHERE name LIKE ?", arrayOf(GalleryIncomingAcceptance.PREFIX + "%")).use {
            if (!it.moveToFirst() || it.getLong(0) >= GalleryIncomingAcceptance.MAX_RECORDS) fail("gallery_incoming_acceptance_capacity")
        }
        val name = GalleryIncomingAcceptance.PREFIX + value.id
        val cipher = protection.seal(frame(value.body), "photo-source-jobs-v1/" + name)
        transaction {
            if (meta(name) != null) fail("gallery_incoming_acceptance_changed")
            current(); putMeta(name, cipher); current()
        }
        boundary("gallery-incoming-acceptance-recorded"); current()
        val saved = incomingAcceptance(value.id) ?: fail("gallery_incoming_acceptance_readback_failed")
        if (saved.body != value.body) fail("gallery_incoming_acceptance_readback_failed")
        saved
    }

    internal fun reserveIncomingPublication(planned: GalleryIncomingPublication, current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        if (planned.state != "planned" || planned.row != null) fail("gallery_incoming_planned_required")
        incomingPublication(planned.id)?.let {
            if (it.body.filterKeys { key -> key !in setOf("row", "state") } != planned.body.filterKeys { key -> key !in setOf("row", "state") })
                fail("gallery_incoming_original_changed")
            return@gated it // An inserted row is never replanned/reinserted.
        }
        db.rawQuery("SELECT COUNT(*) FROM source_meta WHERE name LIKE ?", arrayOf(GalleryIncomingPublication.PREFIX + "%")).use {
            if (!it.moveToFirst() || it.getLong(0) >= GalleryIncomingPublication.MAX_RECORDS) fail("gallery_incoming_publication_capacity")
        }
        writeIncomingPublication(null, planned, current)
    }

    internal fun recordIncomingRow(expected: GalleryIncomingPublication, row: JsonObject, current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        val next = expected.withInsertedRow(row)
        writeIncomingPublication(expected, next, current)
    }

    internal fun beginIncomingInsertion(expected: GalleryIncomingPublication, current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        writeIncomingPublication(expected, expected.beforeInsert(), current)
    }

    internal fun beginIncomingCopy(expected: GalleryIncomingPublication, current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        writeIncomingPublication(expected, expected.beforeCopy(), current)
    }

    internal fun recordIncomingVerifiedCopy(expected: GalleryIncomingPublication, row: JsonObject,
        current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        writeIncomingPublication(expected, expected.withVerifiedCopy(row), current)
    }

    internal fun beginIncomingPublishing(expected: GalleryIncomingPublication, current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        writeIncomingPublication(expected, expected.beforePublish(), current)
    }

    internal fun recordIncomingPublished(expected: GalleryIncomingPublication, row: JsonObject,
        current: () -> Unit): GalleryIncomingPublication = gated {
        writableMembership(); current()
        writeIncomingPublication(expected, expected.withPublishedRow(row), current)
    }

    private fun writeIncomingPublication(expected: GalleryIncomingPublication?, next: GalleryIncomingPublication,
        current: () -> Unit): GalleryIncomingPublication {
        val name = GalleryIncomingPublication.PREFIX + next.id
        val cipher = protection.seal(frame(next.body), "photo-source-jobs-v1/" + name)
        transaction {
            if (incomingPublication(next.id)?.body != expected?.body) fail("gallery_incoming_publication_cas_conflict")
            next.knownOriginalId?.let { id ->
                val known = knownPhoneMedia(id) ?: fail("gallery_incoming_original_reference_missing")
                val binding = next.body.getValue("origin").jsonObject.getValue("binding").jsonObject
                if (known.body.string("phone_id") != binding.string("receiver_id") ||
                    known.body.string("peer_id") != binding.string("sender_id") ||
                    known.body.string("peer_identity_sha256") != binding.string("sender_identity_sha256") ||
                    known.reference.body.string("media_type") != next.body.string("media_type"))
                    fail("gallery_incoming_original_reference_changed")
            }
            current(); putMeta(name, cipher); current()
        }
        boundary("gallery-incoming-" + next.state)
        current()
        val saved = incomingPublication(next.id) ?: fail("gallery_incoming_publication_readback_failed")
        if (saved.body != next.body) fail("gallery_incoming_publication_readback_failed")
        return saved
    }

    private fun readGalleryPolicy(): GalleryPhotoPolicySnapshot {
        verifyHeader()
        val state = meta(GALLERY_POLICY)
        val policy = state?.let { GalleryPhotoPolicy.parse(parse(protection.open(it, "photo-source-jobs-v1/" + GALLERY_POLICY))) }
        val fence = meta(GALLERY_FENCE)
        fence?.let(::galleryFence)
        // Native readiness only: preserve the exact protected consent/version.
        // An uncertain aggregate or legacy index is not a renewed READ grant.
        return GalleryPhotoPolicySnapshot(galleryVersion(state), policy, fence != null || uncertain || membership == null)
    }

    private fun galleryFence(cipher: ByteArray): Pair<String, String> {
        val value = parse(protection.open(cipher, "photo-source-jobs-v1/" + GALLERY_FENCE))
        if (value.keys != setOf("format", "before", "wanted") || value["format"] != JsonPrimitive(1)) fail("gallery_policy_invalid_fence")
        fun version(name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString && SHA.matches(it.content) }?.content
            ?: fail("gallery_policy_invalid_fence")
        return version("before") to version("wanted")
    }

    private fun meta(name: String): ByteArray? = db.query("source_meta", arrayOf("sealed"), "name=?", arrayOf(name), null, null, null).use {
        if (!it.moveToFirst()) null else it.getBlob(0).also { bytes ->
            if (bytes.size !in 29..8192) fail("gallery_policy_invalid_cipher_bounds")
        }
    }
    private fun putMeta(name: String, bytes: ByteArray) {
        if (bytes.size !in 29..8192) fail("gallery_policy_invalid_cipher_bounds")
        val values = ContentValues().apply { put("name", name); put("sealed", bytes) }
        if (db.update("source_meta", values, "name=?", arrayOf(name)) == 0) db.insertOrThrow("source_meta", null, values)
        membership!!.advance()
    }
    private fun galleryVersion(cipher: ByteArray?) = cipher?.let(::hash) ?: hash("magnolie-gallery-policy-v1/absent".toByteArray(Charsets.US_ASCII))

    fun restore(expected: PhotoSourceJob, senderId: String, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease,
        cancellation: CancellationSignal = CancellationSignal()): IndexedPhotoSource = withSealedHead(expected, scope, lease) {
        val actual = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        val snapshot = ProtectedPhotoSourceSnapshot.restore(rootFile(actual), actual.snapshot ?: fail("photo_jobs_snapshot_missing"),
            senderId, scope, lease, protection, cancellation)
        IndexedPhotoSource(this, actual, scope, lease, snapshot)
    }

    internal fun <T> withSealedHead(expected: PhotoSourceJob, scope: NativePhotoSourceAuthority, lease: NativePhotoSourceLease, action: () -> T): T = gated {
        writableMembership()
        fun check() {
            verifyHeader()
            val current = readOne(expected.id) ?: fail("photo_jobs_missing_job")
            if (current.version != expected.version || data(current) != data(expected) || current.phase != "sealed")
                fail("photo_jobs_sealed_head_changed")
            if (!scope.isCurrent(lease) || current.sourceContext != context(lease)) fail("photo_jobs_source_revoked")
            if (attributes(rootFile(current)).fileKey()?.toString() != current.rootKey) fail("photo_jobs_root_changed")
        }
        check()
        val result = action()
        try { check(); result } catch (error: Exception) { if (result is ByteArray) result.fill(0); throw error }
    }

    fun rootFile(job: PhotoSourceJob): File {
        if (!ID.matches(job.id)) fail("photo_jobs_invalid_id")
        return File(directory, "photo-source-" + job.id)
    }

    /** Only an actual verified snapshot object may be passed, never an IPC payload. */
    internal fun publishSnapshot(expected: PhotoSourceJob, snapshot: ProtectedPhotoSourceSnapshot, scope: NativePhotoSourceAuthority,
        lease: NativePhotoSourceLease): PhotoSourceJob = gated {
        fun allowed() {
            if (!scope.isCurrent(lease) || expected.sourceContext != context(lease)) fail("photo_jobs_source_revoked")
        }
        allowed()
        if (expected.phase != "reserved" || expected.rootKey == null ||
            attributes(rootFile(expected)).fileKey()?.toString() != expected.rootKey) fail("photo_jobs_root_changed")
        if (snapshot.lease !== lease || snapshot.manifest.totalBytes != expected.plainBytes) fail("photo_jobs_snapshot_binding_changed")
        val record = snapshot.nativeRecord()
        val actualBytes = (record["cipher_bytes"] as? JsonPrimitive)?.content?.toLongOrNull() ?: fail("photo_jobs_invalid_snapshot")
        if (record["root_key"] != JsonPrimitive(expected.rootKey) || actualBytes > expected.cipherBudget)
            fail("photo_jobs_snapshot_reservation_exceeded")
        update(expected, expected.copy(phase = "sealed", snapshot = record), ::allowed)
    }

    /** Explicit local-cache retirement, including obsolete/revoked gallery
     * scopes. Does not restore source access or accept a remote cleanup record.
     * Reserved/partial jobs without authenticated original witnesses stay held.
     */
    fun retireCachedSnapshot(expected: PhotoSourceJob) {
        if (expected.snapshot == null) fail("photo_cache_snapshot_missing")
        retireAndClean(expected) {
            val retired = readOne(expected.id) ?: fail("photo_jobs_missing_job")
            ProtectedPhotoCacheCleanup.discard(rootFile(retired), retired, boundary)
        }
    }

    /** Commit retirement first; retain quota on ANY cleanup failure.
     * A retry uses the actually re-read retired head, not a stale caller head.
     */
    fun retireAndClean(expected: PhotoSourceJob, cleanup: () -> Unit) = gated {
        writableMembership()
        val observed = readOne(expected.id) ?: fail("photo_jobs_missing_job")
        if (observed.version != expected.version || data(observed) != data(expected)) fail("photo_jobs_cas_conflict")
        val retired = if (observed.phase == "retired") observed else update(observed, observed.copy(phase = "retired")) { }
        val child = rootFile(retired)
        val childAttributes = cleanupAttributes(child)
        if (childAttributes != null) {
            if (!childAttributes.isDirectory || retired.rootKey == null || childAttributes.fileKey()?.toString() != retired.rootKey)
                fail("photo_jobs_unknown_root_preserved")
            cleanup()
        }
        if (cleanupAttributes(child) != null) fail("photo_jobs_cleanup_not_proven")
        synchronisiereOrdner(directory)
        boundary("cleanup-proven")
        transaction {
            if (cleanupAttributes(child) != null) fail("photo_jobs_cleanup_not_proven")
            val current = readOne(retired.id) ?: fail("photo_jobs_missing_job")
            if (current.version != retired.version) fail("photo_jobs_cas_conflict")
            db.delete("source_meta", "name=?", arrayOf("remote-saved-v1/" + retired.id))
            db.delete("source_meta", "name=?", arrayOf("remote-acceptance-v1/" + retired.id))
            db.delete("source_meta", "name=?", arrayOf("resume-attempt-v1/" + retired.id))
            db.delete("source_meta", "name=?", arrayOf("resume-abandonments-v1/" + retired.id))
            if (db.delete("source_jobs", "job_id=?", arrayOf(retired.id)) != 1) fail("photo_jobs_retirement_failed")
            membership!!.advance()
        }
        if (readOne(retired.id) != null) fail("photo_jobs_retirement_readback_failed")
    }

    /** exists(false) also means inaccessible. Only exact ENOENT under the
     * original searchable private parent is evidence of completed cleanup. */
    private fun cleanupAttributes(child: File): BasicFileAttributes? {
        fun parent() {
            checkDirectory()
            if (!Files.getPosixFilePermissions(directory.toPath(), NOFOLLOW_LINKS)
                    .containsAll(PosixFilePermissions.fromString("rwx------"))) fail("photo_jobs_cleanup_parent_inaccessible")
        }
        parent()
        val result = try { attributes(child) } catch (_: NoSuchFileException) { null }
        parent()
        return result
    }

    private fun update(expected: PhotoSourceJob, wanted: PhotoSourceJob, permitted: () -> Unit = {}): PhotoSourceJob {
        val cipher = protect(wanted)
        transaction {
            val current = readOne(expected.id) ?: fail("photo_jobs_missing_job")
            if (current.version != expected.version || data(current) != data(expected)) fail("photo_jobs_cas_conflict")
            permitted()
            if (db.update("source_jobs", ContentValues().apply { put("sealed", cipher) }, "job_id=?", arrayOf(expected.id)) != 1)
                fail("photo_jobs_update_failed")
            membership!!.advance()
            permitted()
        }
        boundary("job-head-committed")
        val saved = readOne(expected.id) ?: fail("photo_jobs_update_readback_missing")
        if (saved.version != hash(cipher) || data(saved) != data(wanted)) fail("photo_jobs_update_readback_changed")
        permitted()
        return saved
    }
    private fun insert(value: PhotoSourceJob) {
        db.insertOrThrow("source_jobs", null, ContentValues().apply { put("job_id", value.id); put("sealed", protect(value)) })
        membership!!.advance()
    }
    private fun protect(value: PhotoSourceJob) = protection.seal(frame(data(value)), "photo-source-jobs-v1/job/" + value.id)
    private fun readOne(id: String): PhotoSourceJob? = db.query("source_jobs", arrayOf("job_id", "sealed"), "job_id=?", arrayOf(id), null, null, null).use {
        if (!it.moveToFirst()) null else decode(it.getString(0), it.getBlob(1))
    }
    private fun readAll(): List<PhotoSourceJob> {
        verifyHeader()
        val jobs = mutableListOf<PhotoSourceJob>()
        db.query("source_jobs", arrayOf("job_id", "sealed"), null, null, null, null, "job_id").use {
            while (it.moveToNext()) {
                if (jobs.size >= MAX_JOBS) fail("photo_jobs_unbounded_index")
                jobs += decode(it.getString(0), it.getBlob(1))
            }
        }
        return jobs
    }
    private fun decode(id: String, cipher: ByteArray): PhotoSourceJob {
        if (!ID.matches(id)) fail("photo_jobs_invalid_id")
        val value = parse(protection.open(cipher, "photo-source-jobs-v1/job/$id"))
        if (value.keys != setOf("format", "source_context", "plain_bytes", "cipher_budget", "root_key", "phase", "snapshot") ||
            value["format"] != JsonPrimitive(1)) fail("photo_jobs_invalid_record")
        fun text(key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail("photo_jobs_invalid_record")
        fun integer(key: String): Long = (value[key] as? JsonPrimitive)?.takeIf { !it.isString && Regex("0|[1-9][0-9]*").matches(it.content) }
            ?.content?.toLongOrNull() ?: fail("photo_jobs_invalid_record")
        val plain = integer("plain_bytes"); val budget = integer("cipher_budget"); val phase = text("phase")
        val key = if (value["root_key"] == JsonNull) null else text("root_key")
        val snapshot = if (value["snapshot"] == JsonNull) null else value["snapshot"] as? JsonObject ?: fail("photo_jobs_invalid_record")
        if (plain !in 0..DeviceFileManifest.MAX_TOTAL_BYTES || budget !in plain..MAX_CIPHER_BYTES ||
            phase !in setOf("reserved", "sealed", "retired") || !SHA.matches(text("source_context")) ||
            (key != null && key.length !in 1..512) || phase == "sealed" && (key == null || snapshot == null)) fail("photo_jobs_invalid_record")
        return PhotoSourceJob(id, hash(cipher), text("source_context"), plain, budget, key, phase, snapshot)
    }
    private fun verifyHeader() {
        try { db.query("source_meta", arrayOf("sealed"), "name=?", arrayOf("format"), null, null, null).use {
            if (!it.moveToFirst()) fail("photo_jobs_header_invalid")
            val clear = protection.open(it.getBlob(0), "photo-source-jobs-v1/header")
            if (clear.contentEquals(HEADER.toByteArray(Charsets.US_ASCII))) {
                if (membership != null || meta(PhotoSourceMembership.NAME) != null) fail("photo_jobs_membership_downgrade")
            } else if (clear.contentEquals(MEMBER_HEADER.toByteArray(Charsets.US_ASCII))) membershipModel().verify()
            else fail("photo_jobs_header_invalid")
        } } catch (error: Exception) { uncertain = true; throw error }
    }

    private fun membershipModel(): PhotoSourceMembership = membership ?: PhotoSourceMembership(db, rootKey.toString(), dbKey.toString(),
        ::decode, { boundary("membership-protect"); protection.seal(frame(it), "photo-source-jobs-v1/membership") },
        { parse(protection.open(it, "photo-source-jobs-v1/membership")) }).also { membership = it }

    private fun writableMembership(): PhotoSourceMembership {
        if (uncertain) fail("photo_jobs_membership_repair_pending")
        verifyHeader()
        return membership ?: fail("photo_jobs_legacy_membership_upgrade_required")
    }

    private fun <T> transaction(bootstrap: Boolean = false, action: () -> T): T {
        val members = if (bootstrap) null else writableMembership()
        members?.begin()
        var began = false; var success = false
        try {
            db.beginTransaction(); began = true
            val result = action()
            membershipModel().verify()
            db.setTransactionSuccessful(); success = true
            return result
        } finally {
            try { if (began) db.endTransaction() }
            catch (error: Exception) { uncertain = true; throw error }
            finally { members?.end() }
            if (success) try {
                boundary("membership-sync")
                synchronisiereOrdner(directory)
                membershipModel().verify()
                boundary("membership-committed")
            } catch (error: Exception) { uncertain = true; throw error }
        }
    }
    private fun checkDirectory() {
        if (closed || !attributes(directory).isDirectory || attributes(directory).fileKey() != rootKey || directory.canonicalFile != directory)
            fail("photo_jobs_directory_changed")
        if (Files.getPosixFilePermissions(root, NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") })
            fail("photo_jobs_private_directory_required")
    }
    private fun regular(file: File) {
        if (!attributes(file).isRegularFile || Files.getOwner(file.toPath(), NOFOLLOW_LINKS) != Files.getOwner(root, NOFOLLOW_LINKS) ||
            Files.getPosixFilePermissions(file.toPath(), NOFOLLOW_LINKS).any { it.name.startsWith("GROUP_") || it.name.startsWith("OTHERS_") } ||
            (Files.getAttribute(file.toPath(), "unix:nlink", NOFOLLOW_LINKS) as Number).toInt() != 1) fail("photo_jobs_unsafe_entry")
    }
    private fun validateLayout(jobs: List<PhotoSourceJob>) {
        val roots = jobs.associateBy { rootFile(it).name }
        val indexNames = setOf(path.name, path.name + "-wal", path.name + "-shm", path.name + "-journal", "photo-source-jobs.lock")
        Files.newDirectoryStream(root).use { entries ->
            for (entry in entries) {
                val name = entry.fileName.toString()
                if (name in indexNames) regular(entry.toFile())
                else {
                    val job = roots[name] ?: fail("photo_jobs_unindexed_entries_preserved")
                    val actual = attributes(entry.toFile())
                    if (!actual.isDirectory || job.rootKey == null || actual.fileKey()?.toString() != job.rootKey)
                        fail("photo_jobs_unknown_root_preserved")
                    var count = 0L; var bytes = 0L
                    val maximum = (job.plainBytes + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES + DeviceFileManifest.MAX_FILES + 2
                    Files.newDirectoryStream(entry).use { children ->
                        for (child in children) {
                            if (++count > maximum) fail("photo_jobs_root_budget_exceeded")
                            val childName = child.fileName.toString()
                            if (childName !in setOf("owner.enc", "manifest.enc") &&
                                !Regex("empty-[0-9a-f]{32}\\.enc|[0-9a-f]{32}-(0|[1-9][0-9]{0,3})\\.enc").matches(childName))
                                fail("photo_jobs_unfamiliar_root_entry")
                            if (job.snapshot != null && (job.snapshot["files"] as? kotlinx.serialization.json.JsonArray)?.none {
                                    (it as? JsonObject)?.get("name") == JsonPrimitive(childName) } != false)
                                fail("photo_jobs_unfamiliar_root_entry")
                            regular(child.toFile())
                            bytes += attributes(child.toFile()).size()
                            if (bytes > job.cipherBudget) fail("photo_jobs_root_budget_exceeded")
                        }
                    }
                }
            }
        }
    }
    private fun sidecars() {
        listOf("-wal", "-shm", "-journal").forEach {
            val file = File(path.path + it)
            if (Files.exists(file.toPath(), NOFOLLOW_LINKS)) regular(file)
        }
    }
    private fun <T> gated(action: () -> T): T = synchronized(gate) {
        checkDirectory()
        val lock = File(directory, "photo-source-jobs.lock")
        if (Files.exists(lock.toPath(), NOFOLLOW_LINKS)) regular(lock)
        fun checked(): T {
            checkDirectory()
            if (::dbKey.isInitialized) {
                regular(path)
                sidecars()
                if (attributes(path).fileKey() != dbKey) fail("photo_jobs_db_replaced")
                verifyHeader()
            }
            return action()
        }
        // A source-authority check may read its protected policy in this SAME
        // index (or another native index object for the same directory). The
        // global process monitor is reentrant, FileChannel.lock is not. Only
        // the same thread already holding this exact root's OS lock may reuse
        // it; all root/DB/sidecar checks still run on every nested operation.
        val key = directory.path
        if (heldRoots.get()?.contains(key) == true) return@synchronized checked()
        FileChannel.open(lock.toPath(), setOf(WRITE, CREATE, NOFOLLOW_LINKS), PRIVATE_FILE).use { channel ->
            channel.lock().use {
                val held = heldRoots.get() ?: mutableSetOf<String>().also { heldRoots.set(it) }
                held.add(key)
                try { checked() } finally {
                    held.remove(key)
                    if (held.isEmpty()) heldRoots.remove()
                }
            }
        }
    }
    override fun close() = synchronized(gate) { if (!closed) { closed = true; if (::db.isInitialized) db.close() } }

    companion object {
        internal fun openExisting(directory: File, protection: DeviceTransferProtection) =
            PhotoSourceJobIndex(directory, protection, false, {})
        const val MAX_JOBS = 8
        const val MAX_CIPHER_BYTES = DeviceFileManifest.MAX_TOTAL_BYTES + 8L * 1024 * 1024
        private val gate = Any()
        private val heldRoots = ThreadLocal<MutableSet<String>>()
        private val ID = Regex("[0-9a-f]{32}")
        private val SHA = Regex("[0-9a-f]{64}")
        private const val HEADER = "magnolie-private-photo-source-jobs-v1"
        private const val MEMBER_HEADER = "magnolie-private-photo-source-jobs-v2"
        private const val GALLERY_POLICY = "gallery-policy-v1"
        private const val GALLERY_FENCE = "gallery-policy-v1-repair"
        private val PRIVATE_FILE = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))
        private val PRIVATE_DIRECTORY = PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))
        private fun attributes(file: File) = Files.readAttributes(file.toPath(), BasicFileAttributes::class.java, NOFOLLOW_LINKS)
        private fun hash(bytes: ByteArray) = NativeHex.lower(MessageDigest.getInstance("SHA-256").digest(bytes))
        private fun context(lease: NativePhotoSourceLease) = hash(TelefonKanonisch.bytes(NativePhotoSourceContext.wire(lease)))
        private fun data(value: PhotoSourceJob) = JsonObject(mapOf("format" to JsonPrimitive(1), "source_context" to JsonPrimitive(value.sourceContext),
            "plain_bytes" to JsonPrimitive(value.plainBytes), "cipher_budget" to JsonPrimitive(value.cipherBudget),
            "root_key" to (value.rootKey?.let { JsonPrimitive(it) } ?: JsonNull), "phase" to JsonPrimitive(value.phase),
            "snapshot" to (value.snapshot ?: JsonNull)))
        private fun frame(value: JsonObject) = ByteArrayOutputStream().also {
            TelefonRahmen.schreiben(it, value, DeviceTransferProtection.MAX_CLEAR_BYTES - 4)
        }.toByteArray()
        private fun parse(bytes: ByteArray) = ByteArrayInputStream(bytes).use { input ->
            TelefonRahmen.lesen(input, DeviceTransferProtection.MAX_CLEAR_BYTES - 4).also { if (input.read() != -1) fail("photo_jobs_trailing_metadata") }
        }
        private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
    }
}
