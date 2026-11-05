package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.CancellationSignal
import android.os.Looper
import androidx.activity.ComponentActivity
import java.io.File
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal class GalleryPhotoBuildFailure internal constructor(val reservationId: String, cause: Exception) :
    IOException("Native gallery snapshot not completed; its reserved cache remains held.", cause)

/** Explicit native source operation joining actual protected policy, Android
 * permission lifecycle, selected album inventory/PFDs and encrypted job storage.
 * Not a service/worker/remote handler: callers must supply the authenticated
 * native receiver and existing local sender identity/key/private directory.
 */
internal class NativeGalleryPhotoWorkflow private constructor(context: Context, directory: File, private val senderId: String,
    private val protection: DeviceTransferProtection, currentReceiver: () -> NativePhotoReceiver?,
    currentConfigurer: (() -> NativeGalleryConfigurer?)?, videoAvailable: () -> Boolean,
    currentMediaIntent: ((GalleryMediaType) -> Any?)?) : AutoCloseable {
    constructor(context: Context, directory: File, senderId: String, protection: DeviceTransferProtection,
        currentReceiver: () -> NativePhotoReceiver?) : this(context, directory, senderId, protection, currentReceiver, null, { true }, null)
    companion object {
        fun forAuthenticatedConfigurer(context: Context, directory: File, senderId: String, protection: DeviceTransferProtection,
            currentReceiver: () -> NativePhotoReceiver?, currentConfigurer: () -> NativeGalleryConfigurer?) =
            NativeGalleryPhotoWorkflow(context, directory, senderId, protection, currentReceiver, currentConfigurer, { true }, null)
        fun forAuthenticatedConfigurer(context: Context, directory: File, senderId: String, protection: DeviceTransferProtection,
            currentReceiver: () -> NativePhotoReceiver?, currentConfigurer: () -> NativeGalleryConfigurer?, videoAvailable: () -> Boolean) =
            NativeGalleryPhotoWorkflow(context, directory, senderId, protection, currentReceiver, currentConfigurer, videoAvailable, null)
        fun forSharedMediaIntent(context: Context, directory: File, senderId: String, protection: DeviceTransferProtection,
            currentReceiver: () -> NativePhotoReceiver?, currentConfigurer: () -> NativeGalleryConfigurer?, videoAvailable: () -> Boolean,
            currentMediaIntent: ((GalleryMediaType) -> Any?)?) =
            NativeGalleryPhotoWorkflow(context, directory, senderId, protection, currentReceiver, currentConfigurer, videoAvailable, currentMediaIntent)
    }
    private val app = context.applicationContext
    init { require(Regex("[A-Za-z0-9_-]{16,160}").matches(senderId)) }
    private val index = PhotoSourceJobIndex(directory, protection)
    private val policy = if (currentConfigurer == null) GalleryPhotoPolicyController(index, currentReceiver)
        else GalleryPhotoPolicyController.forSharedMediaIntent(index, currentReceiver, currentConfigurer, videoAvailable, currentMediaIntent)
    private class Binding(val launcher: GalleryPhotoPermissionLauncher, val scope: GalleryPhotoSourceScope, val host: GalleryPhotoPermissionHost? = null)
    private data class Pending(val error: GalleryPhotoBuildFailure, val snapshot: ProtectedPhotoSourceSnapshot?)
    private val binding = AtomicReference<Binding?>()
    private val videoBinding = AtomicReference<Binding?>()
    private val pending = ConcurrentHashMap<String, Pending>()
    private val closed = AtomicBoolean(false)
    private class ReadBinding(val access: GalleryPhotoAccessController, val scope: GalleryPhotoSourceScope,
        val activity: Binding? = null, val mediaType: GalleryMediaType = GalleryMediaType.IMAGES)
    // App-wide OS READ and the dedicated current file policy may authorize a
    // fresh background lease without retaining an Activity or its prompt ticket.
    // Construction neither observes media nor requests a permission.
    private val backgroundAccess = GalleryPhotoAccessController(app, { if (closed.get()) null else policy.currentRequest() })
    private val backgroundRead = ReadBinding(backgroundAccess,
        GalleryPhotoSourceScope({ if (closed.get()) null else policy.currentRequest() }, backgroundAccess.environment))
    private val backgroundVideoAccess = GalleryPhotoAccessController(app,
        { if (closed.get()) null else policy.currentRequest(GalleryMediaType.VIDEO) }, mediaType = GalleryMediaType.VIDEO)
    private val backgroundVideoRead = ReadBinding(backgroundVideoAccess,
        GalleryPhotoSourceScope({ if (closed.get()) null else policy.currentRequest(GalleryMediaType.VIDEO) }, backgroundVideoAccess.environment),
        mediaType = GalleryMediaType.VIDEO)

    fun savedPolicy(): GalleryPhotoPolicySnapshot { ready(); return index.galleryPolicy() }
    fun configure(expected: GalleryPhotoPolicySnapshot, enabled: Boolean, kinds: Set<GallerySourceKind>): GalleryPhotoPolicySnapshot {
        ready()
        return policy.configure(expected, enabled, kinds)
    }
    fun disableLocally(expected: GalleryPhotoPolicySnapshot): GalleryPhotoPolicySnapshot {
        ready()
        return policy.disableLocally(expected)
    }
    fun configureVideos(expected: GalleryPhotoPolicySnapshot, enabled: Boolean): GalleryPhotoPolicySnapshot {
        ready(); return policy.configureVideos(expected, enabled)
    }
    fun currentRequest(mediaType: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryRequest? { ready(); return policy.currentRequest(mediaType) }
    fun jobs(): List<PhotoSourceJob> { ready(); return index.jobs() }

    /** Blocking native inspection only, off the UI thread. It does not restore
     * cache READ, create a source run or publish a fresh offer. */
    fun inspectResume(selection: NativeGalleryAlbumSelection, expected: PhotoSourceJob,
        cancellation: CancellationSignal = CancellationSignal()): NativeGalleryResumeInspection {
        ready()
        val original = index.requireGalleryResumeOriginal(expected)
        val observed = readBound(mediaType(selection.catalog.source))
        val album = selection.catalog.resolve(this, selection)
        val lease = observed.scope.capture(selection.catalog.source, album, selection.desktopChoice)
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val inventory = reader.enumerate(lease, cancellation)
        return NativeGalleryResumeInspection.inspect(senderId, expected, original, inventory, observed.scope, reader, cancellation, {
            ready()
            if (!readCurrent(observed) || index.requireGalleryResumeOriginal(expected).record != original.record)
                fail("gallery_resume_original_not_revalidated")
            selection.catalog.resolve(this, selection)
        })
    }

    /** Explicit local-only reopen after full live-byte inspection and original
     * encrypted-cache readback. This does not start/resume a transfer run. */
    fun renewSource(selection: NativeGalleryAlbumSelection, expected: PhotoSourceJob,
        cancellation: CancellationSignal = CancellationSignal()): NativeGalleryRenewedSource {
        ready(); index.requireGalleryResumeOriginal(expected)
        val observed = readBound(mediaType(selection.catalog.source))
        val album = selection.catalog.resolve(this, selection)
        val lease = observed.scope.capture(selection.catalog.source, album, selection.desktopChoice)
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val inventory = reader.enumerate(lease, cancellation)
        fun current() {
            ready()
            if (!readCurrent(observed)) fail("gallery_resume_original_not_revalidated")
        }
        return index.renewGallerySource(expected, senderId, inventory, observed.scope, reader, cancellation, {
            current(); selection.catalog.resolve(this, selection)
        }, ::current)
    }

    /** Called from native onCreate before STARTED, not from a wire/UI path.
     * Binding only registers an OS launcher; it never prompts on construction.
     */
    fun bindActivity(activity: ComponentActivity, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        bindActivity(activity, GalleryMediaType.IMAGES, onResult)
    }
    fun bindActivity(activity: ComponentActivity, mediaType: GalleryMediaType, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        uiThread(); ready()
        if (activity.applicationContext !== app) fail("gallery_workflow_foreign_application")
        background(mediaType).access.onAccessChanged()
        nativeBinding(mediaType).getAndSet(null)?.let(::releaseBinding)
        val launcher = GalleryPhotoPermissionLauncher(activity, { if (closed.get()) null else policy.currentRequest(mediaType) }, mediaType) { result ->
            nativeReadAccessChanged(); onResult(result)
        }
        nativeBinding(mediaType).set(Binding(launcher, GalleryPhotoSourceScope({ if (closed.get()) null else policy.currentRequest(mediaType) }, launcher.access.environment)))
    }

    /** Host already registered during native Activity.onCreate; no late
     * ActivityResult registration or forced recreation/draft loss is needed.
     */
    fun attachPermissionHost(host: GalleryPhotoPermissionHost, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        uiThread(); ready()
        if (host.applicationContext !== app) fail("gallery_workflow_foreign_application")
        val mediaType = host.mediaType
        background(mediaType).access.onAccessChanged()
        val launcher = host.attach(this, onResult)
        nativeBinding(mediaType).getAndSet(Binding(launcher, GalleryPhotoSourceScope({ if (closed.get()) null else policy.currentRequest(mediaType) },
            launcher.access.environment), host))?.let { old -> if (old.host !== host) releaseBinding(old) }
    }

    internal fun detachPermissionHost(host: GalleryPhotoPermissionHost) {
        val selected = nativeBinding(host.mediaType)
        val current = selected.get()?.takeIf { it.host === host } ?: return
        if (selected.compareAndSet(current, null)) background(host.mediaType).access.onAccessChanged()
    }
    private fun releaseBinding(value: Binding) { if (value.host == null) value.launcher.close() else value.host.detach(this) }

    fun requestReadPermission(mediaType: GalleryMediaType = GalleryMediaType.IMAGES) {
        ready()
        if (binding.get()?.launcher?.requestPending == true || videoBinding.get()?.launcher?.requestPending == true)
            fail("gallery_permission_request_pending")
        val current = bound(mediaType)
        if (current.host == null) current.launcher.request() else current.host.request(this)
    }
    internal fun permissionRequestPending(mediaType: GalleryMediaType): Boolean =
        nativeBinding(mediaType).get()?.launcher?.requestPending == true

    fun discover(cancellation: CancellationSignal = CancellationSignal(), mediaType: GalleryMediaType = GalleryMediaType.IMAGES): GalleryAlbumCatalog {
        ready()
        if (policy.currentRequest(mediaType) == null) return GalleryAlbumCatalog(GalleryReadCoverage.NONE, emptyList())
        val observed = readBound(mediaType)
        return AndroidGalleryAlbumDiscovery(app, { policy.currentRequest(mediaType) },
            accessEpoch = { observed.access.accessEpoch() }, mediaType = mediaType).discover(cancellation)
    }

    fun discoverSelectable(cancellation: CancellationSignal = CancellationSignal(), mediaType: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryAlbumCatalog {
        ready()
        index.requireMembershipReady()
        val observed = readBound(mediaType)
        val catalog = discover(cancellation, mediaType)
        return NativeGalleryAlbumCatalog(catalog, this, {
            !closed.get() && readCurrent(observed) &&
                catalog.accessEpoch?.let { it == observed.access.accessEpoch() } != false &&
                AndroidGalleryReadPermissions.observe(app, mediaType) == catalog.coverage && observed.scope.isCatalogCurrent(catalog)
        })
    }

    fun freeze(selection: NativeGalleryAlbumSelection, cancellation: CancellationSignal = CancellationSignal()): PhotoSourceJob {
        ready()
        val album = selection.catalog.resolve(this, selection)
        return freeze(selection.catalog.source, album, selection.desktopChoice, cancellation)
    }

    internal fun archiveRecoverableMember(selection: NativeGalleryAlbumSelection, job: PhotoSourceJob, fileId: String,
        permit: NativeGalleryTrashBookPermit, cancellation: CancellationSignal): NativeGalleryArchiveEntry {
        ready(); permit.requireCurrent()
        val album = selection.catalog.resolve(this, selection)
        val observed = readBound(mediaType(selection.catalog.source))
        val lease = observed.scope.capture(selection.catalog.source, album, selection.desktopChoice)
        val frozen = source(job, selection.catalog.source, album, selection.desktopChoice, cancellation)
        val file = frozen.manifest.files.singleOrNull { it.id == fileId } ?: fail("gallery_archive_original_file_required")
        val origins = frozen.galleryOrigins?.takeIf { it.hasNativeInsertionWitness } ?: fail("gallery_archive_native_origin_required")
        val origin = origins.entries.single { it.fileId == fileId }
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val entry = reader.observeOriginalForRecovery(lease, origin, file, cancellation)
        // Separate local recovery store. Never inside source-index directories,
        // never retired with a transfer or invalidated by remote unpairing.
        return NativeGalleryTrashArchive.openForApplication(app, protection).use {
            it.archive(lease, observed.scope, entry, reader, file.sha256, permit, cancellation)
        }
    }

    internal fun prepareWriteConsent(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit,
        cancellation: CancellationSignal): NativeGalleryWriteRequest {
        ready(); permit.requireCurrent(); cancellation.throwIfCanceled()
        return NativeGalleryTrashArchive.openExistingForApplication(app, protection).use { archive ->
            val origin = archive.verifiedOrigin(entry, permit)
            val kind = GalleryMediaType.entries.single { it.uriSegment == origin.string("media_type") }
            val admitted = currentRequest(kind) ?: fail("gallery_write_native_receiver_required")
            NativeGalleryWriteRequest.prepare(app, archive, entry, permit, {
                ready(); cancellation.throwIfCanceled()
                // Video policy can rotate independently of the acknowledged
                // photo/data binding. Never transfer an old OS request across a
                // disable/re-enable cycle just because the peer is unchanged.
                currentRequest(kind)?.takeIf {
                    it.policyEpoch == admitted.policyEpoch && it.mediaIntent === admitted.mediaIntent && it.mediaType == admitted.mediaType && it.kinds == admitted.kinds
                }?.receiver
            }).also { cancellation.throwIfCanceled() }
        }
    }

    internal fun requestOriginalAccess(mediaType: GalleryMediaType, permit: NativeGalleryTrashBookPermit, result: (Result<Unit>) -> Unit) {
        ready(); permit.requireCurrent()
        val host = nativeBinding(mediaType).get()?.host ?: fail("gallery_write_foreground_required")
        val request = NativeGalleryOriginalAccessRequest.prepare(permit) { ready(); currentRequest(mediaType) }
        host.requestOriginalAccess(this, request, result)
    }

    internal fun requestWriteConsent(request: NativeGalleryWriteRequest, result: (Result<NativeGalleryWriteGrant>) -> Unit) {
        ready(); request.requireCurrent()
        val host = nativeBinding(request.mediaType).get()?.host ?: fail("gallery_write_foreground_required")
        host.requestWrite(this, request, result)
    }

    internal class VerifiedWriteTarget internal constructor(internal val grant: NativeGalleryWriteGrant,
        internal val reader: AndroidGalleryPhotoSource, internal val lease: GalleryPhotoSourceLease,
        internal val member: PhotoInventoryEntry, private val current: () -> Unit) {
        val isRemoteDeletionReceipt: Boolean get() = false
        internal fun requireCurrent() { current() }
    }

    /** No old catalogue, pre-dialog lease, or saved URI is admitted here. A
     * successful result is only a current local target check, not a mutation. */
    internal fun validateWriteTarget(grant: NativeGalleryWriteGrant, cancellation: CancellationSignal): VerifiedWriteTarget {
        val request = grant.request
        fun active() { ready(); cancellation.throwIfCanceled(); grant.requireCurrent(); request.permit.requireCurrent() }
        active()
        return NativeGalleryTrashArchive.openExistingForApplication(app, protection).use { archive ->
            val origin = archive.verifiedOriginalOrigin(request.entry, request.permit); active()
            val observed = readBound(request.mediaType)
            val catalog = discover(cancellation, request.mediaType); active()
            val album = catalog.albums.singleOrNull {
                it.volume == origin.string("volume") && it.relativePath == origin.string("album_path")
            } ?: fail("gallery_write_original_album_not_current")
            // Original explicit selection is authenticated by archive provenance;
            // this does not admit another album or use a human-readable label.
            val lease = observed.scope.capture(catalog, album, desktopAlbumChoice = true)
            fun current() {
                active()
                if (!readCurrent(observed) || !observed.scope.isCurrent(lease)) fail("gallery_write_original_scope_changed")
            }
            current()
            val reader = AndroidGalleryPhotoSource(app, observed.scope)
            val member = reader.observeArchivedOriginalForWrite(lease, origin, request.entry, cancellation)
            val hash = java.security.MessageDigest.getInstance("SHA-256"); var bytes = 0L
            reader.openOriginalForRecovery(lease, member, cancellation).use { input ->
                val buffer = ByteArray(DeviceFileManifest.CHUNK_BYTES)
                try {
                    while (true) {
                        current(); val count = input.read(buffer)
                        if (count == -1) break
                        if (count <= 0 || bytes + count > request.entry.bytes) fail("gallery_write_original_content_changed")
                        hash.update(buffer, 0, count); bytes += count
                    }
                } finally { buffer.fill(0) }
            }
            if (bytes != request.entry.bytes || hash.digest().joinToString("") { "%02x".format(it) } != request.entry.sha256)
                fail("gallery_write_original_content_changed")
            reader.verifyMetadata(lease, member, cancellation); current()
            VerifiedWriteTarget(grant, reader, lease, member, ::current)
        }
    }

    internal fun trashOriginal(grant: NativeGalleryWriteGrant, cancellation: CancellationSignal): NativeGalleryTrashAction {
        val target = validateWriteTarget(grant, cancellation)
        val request = grant.request
        return NativeGalleryTrashArchive.openExistingForApplication(app, protection).use { archive ->
            val origin = archive.verifiedOriginalOrigin(request.entry, request.permit)
            target.requireCurrent()
            val action = archive.prepareTrash(request.entry, request.permit, target::requireCurrent)
            // An interrupted/uncertain mutation remains prepared, never canceled
            // or acknowledged from a provider return count alone.
            grant.consume(); target.requireCurrent()
            target.reader.trashOriginal(target.lease, target.member, origin.string("mime_type"), request.entry,
                cancellation, target::requireCurrent)
            archive.finishTrash(action, request.permit, target::requireCurrent)
        }
    }

    internal fun restoreOriginal(session: NativeGalleryRestoreSession, cancellation: CancellationSignal): NativeGalleryTrashAction {
        ready(); session.requireCurrent(); cancellation.throwIfCanceled()
        return NativeGalleryTrashArchive.openExistingForApplication(app, protection).use {
            NativeGalleryMediaRestore(app).restore(it, session, cancellation)
        }
    }

    internal fun validateSelection(selection: NativeGalleryAlbumSelection) {
        ready(); selection.catalog.resolve(this, selection)
    }

    internal class FrozenBatch internal constructor(val job: PhotoSourceJob?, val reachedCurrentEnd: Boolean) {
        val provesDeletion: Boolean get() = false
    }

    /** One live native album scan. Each batch becomes a real reserved, frozen,
     * read-back source, not a partial manifest or a metadata-only success.
     * The caller must finish/retire its previous source before requesting more.
     */
    internal inner class AlbumBatches internal constructor(private val selection: NativeGalleryAlbumSelection,
        private val maxFiles: Int) : AutoCloseable {
        private val observed = readBound(mediaType(selection.catalog.source))
        private val retainedAlbum = NativeGalleryAlbumLease(this@NativeGalleryPhotoWorkflow, selection)
        private val album = retainedAlbum.resolve(this@NativeGalleryPhotoWorkflow)
        private val lease = try { observed.scope.capture(selection.catalog.source, album, selection.desktopChoice) }
            catch (error: Exception) { retainedAlbum.close(); throw error }
        private val reader = try { AndroidGalleryPhotoSource(app, observed.scope) }
            catch (error: Exception) { retainedAlbum.close(); throw error }
        private var continuation: AndroidGalleryPhotoSource.Continuation? = null
        private var previous: PhotoSourceJob? = null
        private var ended = false
        private var failed = false
        private val stopped = AtomicBoolean(false)
        private val activeCancellation = AtomicReference<CancellationSignal?>()

        @Synchronized internal fun requireAuthority() {
            try {
                ready()
                if (stopped.get() || failed || !readCurrent(observed)) fail("gallery_album_batch_not_current")
                retainedAlbum.resolve(this@NativeGalleryPhotoWorkflow)
                if (!observed.scope.isCurrent(lease)) fail("gallery_inventory_source_revoked")
            } catch (error: Exception) { failed = true; retainedAlbum.close(); throw error }
        }

        @Synchronized fun next(cancellation: CancellationSignal = CancellationSignal()): FrozenBatch {
            fun current() {
                ready(); cancellation.throwIfCanceled()
                if (ended) fail("gallery_album_batch_not_current")
                requireAuthority()
            }
            current(); index.requireMembershipReady()
            if (previous?.let { old -> index.jobs().any { it.id == old.id } } == true)
                fail("gallery_album_previous_batch_held")
            activeCancellation.set(cancellation)
            try {
                current()
                val batch = reader.enumerateBatch(lease, continuation, cancellation, maxFiles)
                current()
                val job = if (batch.inventory.entries.isEmpty()) null else
                    freezeInventory(batch.inventory, observed, reader, cancellation)
                current()
                previous = job; continuation = batch.continuation; ended = batch.reachedCurrentEnd
                return FrozenBatch(job, ended)
            } catch (error: Exception) {
                failed = true // No implicit replay after a potentially committed reservation.
                retainedAlbum.close()
                throw error
            } finally {
                activeCancellation.compareAndSet(cancellation, null)
            }
        }

        override fun close() {
            stopped.set(true)
            retainedAlbum.close()
            activeCancellation.get()?.cancel() // Nonblocking request, never source owner release or deletion.
        }
    }

    internal fun albumBatches(selection: NativeGalleryAlbumSelection, maxFiles: Int = DeviceFileManifest.MAX_FILES): AlbumBatches {
        ready(); index.requireMembershipReady(); validateSelection(selection)
        if (maxFiles !in 1..DeviceFileManifest.MAX_FILES) fail("gallery_inventory_file_limit")
        return AlbumBatches(selection, maxFiles)
    }

    /** Blocking bounded IO: run off the main UI thread in the real coordinator.
     * No partial source or manifest is offered on any failure; reservation and
     * exact native in-process cleanup witnesses remain held for explicit repair.
     */
    fun freeze(catalog: GalleryAlbumCatalog, album: GalleryAlbumCandidate, desktopAlbumChoice: Boolean = false,
        cancellation: CancellationSignal = CancellationSignal()): PhotoSourceJob {
        ready()
        index.requireMembershipReady()
        val observed = readBound(mediaType(catalog))
        val lease = observed.scope.capture(catalog, album, desktopAlbumChoice)
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val inventory = reader.enumerate(lease, cancellation)
        return freezeInventory(inventory, observed, reader, cancellation)
    }

    private fun freezeInventory(inventory: PhotoSourceInventory, observed: ReadBinding, reader: AndroidGalleryPhotoSource,
        cancellation: CancellationSignal): PhotoSourceJob {
        ready()
        if (!readCurrent(observed)) fail("gallery_album_batch_not_current")
        val lease = inventory.lease
        val reserved = index.reserve(inventory, observed.scope)
        var snapshot: ProtectedPhotoSourceSnapshot? = null
        try {
            snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, senderId, observed.scope,
                reader, protection, cancellation)
            return index.publishSnapshot(reserved, snapshot, observed.scope, lease)
        } catch (error: Exception) {
            val failure = GalleryPhotoBuildFailure(reserved.id, error)
            pending[reserved.id] = Pending(failure, (error as? PhotoSnapshotBuildFailure)?.pending ?: snapshot)
            throw failure
        }
    }

    fun source(job: PhotoSourceJob, catalog: GalleryAlbumCatalog, album: GalleryAlbumCandidate,
        desktopAlbumChoice: Boolean = false, cancellation: CancellationSignal = CancellationSignal()): IndexedPhotoSource {
        ready()
        val observed = readBound(mediaType(catalog))
        val lease = observed.scope.capture(catalog, album, desktopAlbumChoice)
        return index.restore(job, senderId, observed.scope, lease, cancellation)
    }

    /** Only an exact failure handle created by this native workflow, never an
     * IPC cleanup payload. Restart without partial witnesses remains held.
     */
    fun discardFailedBuild(error: GalleryPhotoBuildFailure) {
        ready()
        val held = pending[error.reservationId]?.takeIf { it.error === error } ?: fail("gallery_workflow_unknown_failure")
        val actual = index.jobs().singleOrNull { it.id == error.reservationId } ?: fail("photo_jobs_missing_job")
        if (actual.snapshot != null) index.retireCachedSnapshot(actual)
        else {
            val snapshot = held.snapshot ?: fail("gallery_workflow_partial_witness_missing")
            index.retireAndClean(actual) { snapshot.discard() }
        }
        pending.remove(error.reservationId, held)
    }

    fun retireCached(job: PhotoSourceJob) { ready(); index.retireCachedSnapshot(job) }
    internal fun nativeReadAccessChanged() {
        if (closed.get()) return
        fun invalidate(access: GalleryPhotoAccessController) {
            try { access.onAccessChanged() } catch (error: PhotoFolderScopeError) {
                if (error.code != "gallery_access_controller_closed") throw error
            }
        }
        invalidate(backgroundAccess); invalidate(backgroundVideoAccess)
        binding.get()?.let { invalidate(it.launcher.access) }
        videoBinding.get()?.let { invalidate(it.launcher.access) }
    }
    private fun mediaType(catalog: GalleryAlbumCatalog): GalleryMediaType = catalog.activation?.mediaType ?: fail("gallery_source_not_activated")
    private fun nativeBinding(mediaType: GalleryMediaType) = if (mediaType == GalleryMediaType.IMAGES) binding else videoBinding
    private fun background(mediaType: GalleryMediaType) = if (mediaType == GalleryMediaType.IMAGES) backgroundRead else backgroundVideoRead
    private fun readBound(mediaType: GalleryMediaType = GalleryMediaType.IMAGES): ReadBinding {
        ready()
        val activity = nativeBinding(mediaType).get()
        return if (activity == null) background(mediaType).also { it.access.accessEpoch() }
            else ReadBinding(activity.launcher.access, activity.scope, activity, mediaType).also { it.access.accessEpoch() }
    }
    private fun readCurrent(value: ReadBinding): Boolean = !closed.get() &&
        if (value.activity == null) value === background(value.mediaType) && nativeBinding(value.mediaType).get() == null
        else nativeBinding(value.mediaType).get() === value.activity
    private fun bound(mediaType: GalleryMediaType = GalleryMediaType.IMAGES): Binding = nativeBinding(mediaType).get()?.also { it.launcher.access.accessEpoch() }
        ?: fail("gallery_workflow_permission_host_missing")
    private fun ready() { if (closed.get()) fail("gallery_workflow_closed") }
    override fun close() {
        uiThread()
        if (!closed.compareAndSet(false, true)) return
        try { binding.getAndSet(null)?.let(::releaseBinding) }
        finally {
            try { videoBinding.getAndSet(null)?.let(::releaseBinding) }
            finally { try { backgroundAccess.close() } finally { try { backgroundVideoAccess.close() } finally { index.close() } } }
        }
    }
    private fun uiThread() { if (Looper.myLooper() != Looper.getMainLooper()) fail("gallery_permission_ui_thread_required") }
    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
