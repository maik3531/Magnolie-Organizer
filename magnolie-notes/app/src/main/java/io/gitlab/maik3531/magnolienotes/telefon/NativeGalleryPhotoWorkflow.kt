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
    currentConfigurer: (() -> NativeGalleryConfigurer?)?) : AutoCloseable {
    constructor(context: Context, directory: File, senderId: String, protection: DeviceTransferProtection,
        currentReceiver: () -> NativePhotoReceiver?) : this(context, directory, senderId, protection, currentReceiver, null)
    companion object {
        fun forAuthenticatedConfigurer(context: Context, directory: File, senderId: String, protection: DeviceTransferProtection,
            currentReceiver: () -> NativePhotoReceiver?, currentConfigurer: () -> NativeGalleryConfigurer?) =
            NativeGalleryPhotoWorkflow(context, directory, senderId, protection, currentReceiver, currentConfigurer)
    }
    private val app = context.applicationContext
    init { require(Regex("[A-Za-z0-9_-]{16,160}").matches(senderId)) }
    private val index = PhotoSourceJobIndex(directory, protection)
    private val policy = if (currentConfigurer == null) GalleryPhotoPolicyController(index, currentReceiver)
        else GalleryPhotoPolicyController.forAuthenticatedConfigurer(index, currentReceiver, currentConfigurer)
    private class Binding(val launcher: GalleryPhotoPermissionLauncher, val scope: GalleryPhotoSourceScope, val host: GalleryPhotoPermissionHost? = null)
    private data class Pending(val error: GalleryPhotoBuildFailure, val snapshot: ProtectedPhotoSourceSnapshot?)
    private val binding = AtomicReference<Binding?>()
    private val pending = ConcurrentHashMap<String, Pending>()
    private val closed = AtomicBoolean(false)

    fun savedPolicy(): GalleryPhotoPolicySnapshot { ready(); return index.galleryPolicy() }
    fun configure(expected: GalleryPhotoPolicySnapshot, enabled: Boolean, kinds: Set<GallerySourceKind>): GalleryPhotoPolicySnapshot {
        ready()
        return policy.configure(expected, enabled, kinds)
    }
    fun disableLocally(expected: GalleryPhotoPolicySnapshot): GalleryPhotoPolicySnapshot {
        ready()
        return policy.disableLocally(expected)
    }
    fun currentRequest(): NativeGalleryRequest? { ready(); return policy.currentRequest() }
    fun jobs(): List<PhotoSourceJob> { ready(); return index.jobs() }

    /** Blocking native inspection only, off the UI thread. It does not restore
     * cache READ, create a source run or publish a fresh offer. */
    fun inspectResume(selection: NativeGalleryAlbumSelection, expected: PhotoSourceJob,
        cancellation: CancellationSignal = CancellationSignal()): NativeGalleryResumeInspection {
        ready()
        val original = index.requireGalleryResumeOriginal(expected)
        val observed = bound()
        val album = selection.catalog.resolve(this, selection)
        val lease = observed.scope.capture(selection.catalog.source, album, selection.desktopChoice)
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val inventory = reader.enumerate(lease, cancellation)
        return NativeGalleryResumeInspection.inspect(senderId, expected, original, inventory, observed.scope, reader, cancellation, {
            ready()
            if (binding.get() !== observed || index.requireGalleryResumeOriginal(expected).record != original.record)
                fail("gallery_resume_original_not_revalidated")
            selection.catalog.resolve(this, selection)
        })
    }

    /** Explicit local-only reopen after full live-byte inspection and original
     * encrypted-cache readback. This does not start/resume a transfer run. */
    fun renewSource(selection: NativeGalleryAlbumSelection, expected: PhotoSourceJob,
        cancellation: CancellationSignal = CancellationSignal()): NativeGalleryRenewedSource {
        ready(); index.requireGalleryResumeOriginal(expected)
        val observed = bound()
        val album = selection.catalog.resolve(this, selection)
        val lease = observed.scope.capture(selection.catalog.source, album, selection.desktopChoice)
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val inventory = reader.enumerate(lease, cancellation)
        fun current() {
            ready()
            if (binding.get() !== observed) fail("gallery_resume_original_not_revalidated")
        }
        return index.renewGallerySource(expected, senderId, inventory, observed.scope, reader, cancellation, {
            current(); selection.catalog.resolve(this, selection)
        }, ::current)
    }

    /** Called from native onCreate before STARTED, not from a wire/UI path.
     * Binding only registers an OS launcher; it never prompts on construction.
     */
    fun bindActivity(activity: ComponentActivity, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        uiThread(); ready()
        if (activity.applicationContext !== app) fail("gallery_workflow_foreign_application")
        binding.getAndSet(null)?.let(::releaseBinding)
        val launcher = GalleryPhotoPermissionLauncher(activity, { if (closed.get()) null else policy.currentRequest() }, onResult)
        binding.set(Binding(launcher, GalleryPhotoSourceScope({ if (closed.get()) null else policy.currentRequest() }, launcher.access.environment)))
    }

    /** Host already registered during native Activity.onCreate; no late
     * ActivityResult registration or forced recreation/draft loss is needed.
     */
    fun attachPermissionHost(host: GalleryPhotoPermissionHost, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        uiThread(); ready()
        if (host.applicationContext !== app) fail("gallery_workflow_foreign_application")
        val launcher = host.attach(this, onResult)
        binding.getAndSet(Binding(launcher, GalleryPhotoSourceScope({ if (closed.get()) null else policy.currentRequest() },
            launcher.access.environment), host))?.let { old -> if (old.host !== host) releaseBinding(old) }
    }

    internal fun detachPermissionHost(host: GalleryPhotoPermissionHost) {
        val current = binding.get()?.takeIf { it.host === host } ?: return
        binding.compareAndSet(current, null)
    }
    private fun releaseBinding(value: Binding) { if (value.host == null) value.launcher.close() else value.host.detach(this) }

    fun requestReadPermission() {
        ready()
        val current = bound()
        if (current.host == null) current.launcher.request() else current.host.request(this)
    }

    fun discover(cancellation: CancellationSignal = CancellationSignal()): GalleryAlbumCatalog {
        ready()
        if (policy.currentRequest() == null) return GalleryAlbumCatalog(GalleryReadCoverage.NONE, emptyList())
        val observed = bound()
        return AndroidGalleryAlbumDiscovery(app, { policy.currentRequest() },
            accessEpoch = { observed.launcher.access.accessEpoch() }).discover(cancellation)
    }

    fun discoverSelectable(cancellation: CancellationSignal = CancellationSignal()): NativeGalleryAlbumCatalog {
        ready()
        index.requireMembershipReady()
        val observed = bound()
        val catalog = discover(cancellation)
        return NativeGalleryAlbumCatalog(catalog, this, {
            !closed.get() && binding.get() === observed &&
                catalog.accessEpoch?.let { it == observed.launcher.access.accessEpoch() } != false &&
                AndroidGalleryReadPermissions.observe(app) == catalog.coverage && observed.scope.isCatalogCurrent(catalog)
        })
    }

    fun freeze(selection: NativeGalleryAlbumSelection, cancellation: CancellationSignal = CancellationSignal()): PhotoSourceJob {
        ready()
        val album = selection.catalog.resolve(this, selection)
        return freeze(selection.catalog.source, album, selection.desktopChoice, cancellation)
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
    internal inner class AlbumBatches internal constructor(private val selection: NativeGalleryAlbumSelection) : AutoCloseable {
        private val observed = bound()
        private val album = selection.catalog.resolve(this@NativeGalleryPhotoWorkflow, selection)
        private val lease = observed.scope.capture(selection.catalog.source, album, selection.desktopChoice)
        private val reader = AndroidGalleryPhotoSource(app, observed.scope)
        private var continuation: AndroidGalleryPhotoSource.Continuation? = null
        private var previous: PhotoSourceJob? = null
        private var ended = false
        private var failed = false
        private val stopped = AtomicBoolean(false)
        private val activeCancellation = AtomicReference<CancellationSignal?>()

        @Synchronized fun next(cancellation: CancellationSignal = CancellationSignal()): FrozenBatch {
            fun current() {
                ready(); cancellation.throwIfCanceled()
                if (stopped.get() || ended || failed || binding.get() !== observed) fail("gallery_album_batch_not_current")
                validateSelection(selection)
                if (!observed.scope.isCurrent(lease)) fail("gallery_inventory_source_revoked")
            }
            current(); index.requireMembershipReady()
            if (previous?.let { old -> index.jobs().any { it.id == old.id } } == true)
                fail("gallery_album_previous_batch_held")
            activeCancellation.set(cancellation)
            try {
                current()
                val batch = reader.enumerateBatch(lease, continuation, cancellation)
                current()
                val job = if (batch.inventory.entries.isEmpty()) null else
                    freezeInventory(batch.inventory, observed, reader, cancellation)
                current()
                previous = job; continuation = batch.continuation; ended = batch.reachedCurrentEnd
                return FrozenBatch(job, ended)
            } catch (error: Exception) {
                failed = true // No implicit replay after a potentially committed reservation.
                throw error
            } finally {
                activeCancellation.compareAndSet(cancellation, null)
            }
        }

        override fun close() {
            stopped.set(true)
            activeCancellation.get()?.cancel() // Nonblocking request, never source owner release or deletion.
        }
    }

    internal fun albumBatches(selection: NativeGalleryAlbumSelection): AlbumBatches {
        ready(); index.requireMembershipReady(); validateSelection(selection)
        return AlbumBatches(selection)
    }

    /** Blocking bounded IO: run off the main UI thread in the real coordinator.
     * No partial source or manifest is offered on any failure; reservation and
     * exact native in-process cleanup witnesses remain held for explicit repair.
     */
    fun freeze(catalog: GalleryAlbumCatalog, album: GalleryAlbumCandidate, desktopAlbumChoice: Boolean = false,
        cancellation: CancellationSignal = CancellationSignal()): PhotoSourceJob {
        ready()
        index.requireMembershipReady()
        val observed = bound()
        val lease = observed.scope.capture(catalog, album, desktopAlbumChoice)
        val reader = AndroidGalleryPhotoSource(app, observed.scope)
        val inventory = reader.enumerate(lease, cancellation)
        return freezeInventory(inventory, observed, reader, cancellation)
    }

    private fun freezeInventory(inventory: PhotoSourceInventory, observed: Binding, reader: AndroidGalleryPhotoSource,
        cancellation: CancellationSignal): PhotoSourceJob {
        ready()
        if (binding.get() !== observed) fail("gallery_album_batch_not_current")
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
        val observed = bound()
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
    private fun bound(): Binding = binding.get()?.also { it.launcher.access.accessEpoch() }
        ?: fail("gallery_workflow_permission_host_missing")
    private fun ready() { if (closed.get()) fail("gallery_workflow_closed") }
    override fun close() {
        uiThread()
        if (!closed.compareAndSet(false, true)) return
        try { binding.getAndSet(null)?.let(::releaseBinding) } finally { index.close() }
    }
    private fun uiThread() { if (Looper.myLooper() != Looper.getMainLooper()) fail("gallery_permission_ui_thread_required") }
    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
