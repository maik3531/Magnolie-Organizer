package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Looper
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Explicit native I/O-lane join of actual protected policy, dedicated grants,
 * secure-channel controls and source workflow. Not a service/dispatcher: no
 * construction from a wire body, store/key generation, scanning, scheduling or
 * discovery advertisement. The caller supplies existing native identity/key,
 * private directory and authenticated current-peer/channel ownership.
 */
internal class NativeGalleryFileRuntime(context: Context, directory: File, identity: NativeFileControlIdentity,
    protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
    handlersReady: () -> Boolean) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val revoked = AtomicBoolean(false)
    private val operationGate = java.util.concurrent.locks.ReentrantLock()
    private var operationActive = false // Guarded by the short-lived runtime monitor.
    private var syncRun: NativeGallerySyncRun? = null // Access only through operationGate.
    private val app = context.applicationContext
    private val localIdentity = identity
    private val localPermissionCommands = NativeGalleryPermissionCommands()
    private val localRunCommands = NativeGalleryRunCommands()
    private val ticket = AtomicReference<NativeFileConfigurationTicket?>()
    private val commandLive = AtomicReference<(() -> Boolean)?>()
    private val wireCatalog = AtomicReference<NativeGalleryAlbumCatalog?>()
    private val nativePeer = { if (closed.get() || revoked.get()) null else currentPeer() }
    private val index = PhotoSourceJobIndex(directory, protection)
    private val grants = NativeGalleryFileGrantPolicy(nativePeer, { index.galleryPolicy() }, handlersReady)
    private val controls: NativeFileControlChannel
    private val workflow: NativeGalleryPhotoWorkflow
    private val sourceWorker: NativeGallerySourceWorker
    private var closeCompletion: (() -> Unit)? = null // Guarded by this runtime monitor.

    init {
        var prepared: NativeFileControlChannel? = null
        try {
            prepared = NativeFileControlChannel(identity, channel, nativePeer, { grants.current() })
            controls = prepared
            workflow = NativeGalleryPhotoWorkflow.forAuthenticatedConfigurer(context, directory, identity.deviceId, protection,
                { if (closed.get() || revoked.get()) null else controls.session.photoReceiver() },
                { if (commandLive.get()?.invoke() == false) null else ticket.get()?.let { controls.session.configurationAuthority(it) } })
            sourceWorker = NativeGallerySourceWorker({ selected, cancellation -> workflow.freeze(selected, cancellation) }, { sourceIoEnded() })
        } catch (error: Exception) {
            closed.set(true); prepared?.close(); index.close()
            throw error // Dedicated metadata/cache is preserved, not reset.
        }
    }

    fun sendControls(now: Long = System.currentTimeMillis()): Boolean = withOperation { controls.sendIfNeeded(now) }
    fun observeControls(message: JsonObject, now: Long = System.currentTimeMillis()): Boolean = withOperation { controls.observe(message, now) }
    fun savedPolicy(): GalleryPhotoPolicySnapshot { ready(); return workflow.savedPolicy() }
    fun currentRequest(): NativeGalleryRequest? { ready(); return workflow.currentRequest() }
    fun discoverSelectable(cancellation: android.os.CancellationSignal = android.os.CancellationSignal()): NativeGalleryAlbumCatalog = withOperation {
        workflow.discoverSelectable(cancellation)
    }
    fun prepareSource(selection: NativeGalleryAlbumSelection): NativeGallerySourceRun = withOperation {
        if (syncRun != null) DeviceFileControl.fail("gallery_sync_run_busy")
        if (workflow.currentRequest() == null) DeviceFileControl.fail("gallery_source_not_activated")
        workflow.validateSelection(selection)
        sourceWorker.start(selection)
    }

    internal fun beginSyncRun(selection: NativeGalleryAlbumSelection): NativeGallerySyncRun = withOperation {
        beginSyncRunOwned(selection)
    }

    private fun beginSyncRunOwned(selection: NativeGalleryAlbumSelection, checkCommand: () -> Unit = {}): NativeGallerySyncRun {
        if (syncRun != null) DeviceFileControl.fail("gallery_sync_run_busy")
        if (workflow.currentRequest() == null) DeviceFileControl.fail("gallery_source_not_activated")
        workflow.validateSelection(selection)
        checkCommand()
        return NativeGallerySyncRun(selection, sourceWorker.start(selection)).also { syncRun = it }
    }

    /** Native-only offer path. An output receipt is not acceptance/publication.
     * Whole-run ownership remains held after source preparation and this write. */
    internal fun sendSyncRunOffer(run: NativeGallerySyncRun, send: (JsonObject) -> Unit,
        now: Long = System.currentTimeMillis()) = withOperation {
        if (syncRun !== run || run.cancelRequested) DeviceFileControl.fail("gallery_sync_run_not_current")
        if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
        val job = run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val selected = run.selection
        val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
        val offer = source.offerMessage(now)
        val fingerprint = source.manifest.fingerprint
        if (workflow.currentRequest() == null || run.cancelRequested) DeviceFileControl.fail("gallery_source_not_activated")
        send(offer)
        // Revalidate actual protected source authority after output as well.
        if (source.manifest.fingerprint != fingerprint || workflow.currentRequest() == null || run.cancelRequested)
            DeviceFileControl.fail("gallery_source_not_activated")
        run.offered.set(fingerprint)
    }

    internal fun cancelSyncRun(run: NativeGallerySyncRun) = withOperation {
        if (syncRun !== run) DeviceFileControl.fail("gallery_sync_run_not_current")
        run.stopped.set(true)
        run.preparation.cancel() // Cancellation does not release whole-run ownership.
    }

    /** Only an explicitly stopped run can end here. This neither reports sync
     * success nor retires source quota; data/publication receipts remain separate. */
    internal fun endStoppedSyncRun(run: NativeGallerySyncRun) = withOperation {
        if (syncRun !== run || !run.cancelRequested) DeviceFileControl.fail("gallery_sync_run_not_current")
        if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
        syncRun = null
    }
    fun attachPermissionHost(host: GalleryPhotoPermissionHost, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        ready(); workflow.attachPermissionHost(host, onResult)
    }
    fun requestReadPermission() { ready(); workflow.requestReadPermission() }
    fun attachForeground(onResult: (Result<GalleryReadCoverage>) -> Unit): NativeGalleryForegroundOwner {
        ready(); return NativeGalleryForeground.attach(this, onResult)
    }

    /** Guarded source commands. Status/configuration work while initial send is
     * OFF; discovery needs current send authority, and request_read reaches only
     * the explicitly queued native UI path. No transfer/publication is scheduled.
     * Replies are metadata, never SaveACKs or OS READ grants.
     */
    fun receiveSourceCommand(message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = { System.currentTimeMillis() }, permissionCommands: NativeGalleryPermissionCommands = localPermissionCommands,
        runCommands: NativeGalleryRunCommands = localRunCommands): Unit = withOperation {
        ready()
        val command = DeviceFileSourceCommand.parse(message, now())
        if (command.operation == "request_read" && Looper.myLooper() != Looper.getMainLooper())
            DeviceFileControl.fail("gallery_permission_ui_thread_required")
        val issued = controls.session.configurationTicket()
        if (!ticket.compareAndSet(null, issued)) {
            controls.session.finishConfiguration(issued)
            DeviceFileControl.fail("file_control_configuration_busy")
        }
        commandLive.set { now() < command.expires }
        fun authority(): NativeGalleryConfigurer {
            if (now() >= command.expires) DeviceFileControl.fail("file_sources_command_expired")
            return controls.session.configurationAuthority(issued) ?: DeviceFileControl.fail("file_sources_authority_changed")
        }
        try {
            val owner = authority()
            val before = workflow.savedPolicy()
            if (command.operation != "status" && before.version != command.expectedVersion) DeviceFileControl.fail("gallery_policy_cas_conflict")
            if (command.operation in setOf("run", "run_status", "cancel_run")) {
                val run = if (command.operation == "run") {
                    if (owner.pairingEpoch == null) DeviceFileControl.fail("gallery_source_not_activated")
                    val scope = DeviceFileControl.digest("magnolie-gallery-run-native-scope-v1\u0000", kotlinx.serialization.json.JsonArray(listOf(
                        JsonPrimitive(localIdentity.deviceId), JsonPrimitive(localIdentity.identitySha256), JsonPrimitive(owner.peerId),
                        JsonPrimitive(owner.identitySha256), JsonPrimitive(owner.pairingEpoch))))
                    runCommands.start(scope, this, command, message) {
                        authority()
                        val catalog = wireCatalog.get() ?: DeviceFileControl.fail("gallery_catalog_not_current")
                        val selection = catalog.select(command.catalogId!!, command.albumId!!, command.desktopChoice!!)
                        beginSyncRunOwned(selection) { authority(); Unit }
                    }
                } else syncRun?.takeIf { it.id == command.runId } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
                if (syncRun !== run) DeviceFileControl.fail("gallery_sync_run_not_current")
                if (command.operation == "cancel_run") {
                    run.stopped.set(true); run.preparation.cancel()
                }
                authority()
                val ioEnded = run.preparation.ioEnded
                val state = if (run.cancelRequested && !ioEnded) "cancel_pending"
                    else if (run.cancelRequested) "canceled_held" else if (ioEnded) run.preparation.phase else "preparing"
                val body = kotlinx.serialization.json.buildJsonObject {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                    put("state", JsonPrimitive(state)); put("source_io_ended", JsonPrimitive(ioEnded))
                }
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                authority(); send(TelefonNachrichten.message(DeviceFileSourceCommand.RUN_RESULT, body, ttl, at)); authority()
                return@withOperation
            }
            if (command.operation == "request_read") {
                if (workflow.currentRequest() == null || owner.pairingEpoch == null) DeviceFileControl.fail("gallery_source_not_activated")
                val scope = DeviceFileControl.digest("magnolie-gallery-permission-native-scope-v1\u0000", kotlinx.serialization.json.JsonArray(listOf(
                    JsonPrimitive(localIdentity.deviceId), JsonPrimitive(localIdentity.identitySha256), JsonPrimitive(owner.peerId),
                    JsonPrimitive(owner.identitySha256), JsonPrimitive(owner.pairingEpoch))))
                val state = permissionCommands.execute(scope, command, message) {
                    authority()
                    val foreground = attachForeground { }
                    val action = NativeGalleryForeground.permissionAction(foreground)
                    try {
                        authority()
                        NativeGalleryForeground.performPermissionAction(action.token)
                        "requested"
                    } catch (error: PhotoFolderScopeError) {
                        if (error.code !in NativeGalleryPermissionActions.RETRYABLE) throw error
                        if (error.code == "gallery_permission_request_pending") "requested"
                        else {
                            authority()
                            if (NativeGalleryForeground.postPermissionAction(app, action)) "notification_posted" else "foreground_required"
                        }
                    }
                }
                authority()
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                val body = kotlinx.serialization.json.buildJsonObject {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("state", JsonPrimitive(state))
                }
                send(TelefonNachrichten.message(DeviceFileSourceCommand.PERMISSION_RESULT, body, ttl, at))
                authority()
                return@withOperation
            }
            if (command.operation in setOf("discover", "catalog_page")) {
                if (workflow.currentRequest() == null) DeviceFileControl.fail("gallery_source_not_activated")
                val catalog = if (command.operation == "discover") {
                    wireCatalog.getAndSet(null)?.close()
                    workflow.discoverSelectable().also { wireCatalog.set(it) }
                } else wireCatalog.get() ?: DeviceFileControl.fail("gallery_catalog_not_current")
                val page = catalog.page(command.catalogId, command.after)
                authority()
                val body = kotlinx.serialization.json.buildJsonObject {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId))
                    put("operation", JsonPrimitive(command.operation)); put("version", JsonPrimitive(before.version)); put("page", page)
                }
                val at = now()
                val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                val reply = TelefonNachrichten.message(DeviceFileSourceCommand.CATALOG, body, ttl, at)
                if (TelefonKanonisch.bytes(reply).size > DeviceFileControl.MAX_WIRE_BYTES) DeviceFileControl.fail("gallery_catalog_envelope_too_large")
                authority(); catalog.page(command.catalogId, command.after) // Actual metadata freshness at send.
                send(reply)
                authority()
                return@withOperation
            }
            val saved = if (command.operation == "configure") {
                authority()
                workflow.configure(before, command.enabled!!, command.kinds)
            } else before
            authority()
            val policy = saved.policy
            val associated = policy != null && policy.receiverId == owner.peerId && policy.receiverIdentitySha256 == owner.identitySha256 &&
                policy.pairingEpoch == owner.pairingEpoch
            val body = kotlinx.serialization.json.buildJsonObject {
                put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId))
                put("operation", JsonPrimitive(command.operation)); put("version", JsonPrimitive(saved.version))
                put("revision", JsonPrimitive(policy?.revision ?: 0)); put("enabled", JsonPrimitive(policy?.enabled ?: false))
                put("associated", JsonPrimitive(associated)); put("repair_pending", JsonPrimitive(saved.repairPending))
                put("kinds", kotlinx.serialization.json.JsonArray((policy?.kinds ?: emptySet()).map { it.name.lowercase(java.util.Locale.ROOT) }
                    .sorted().map(::JsonPrimitive)))
            }
            val at = now()
            val reply = TelefonNachrichten.message(DeviceFileSourceCommand.RESULT, body,
                minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at).also {
                    if (it <= 0) DeviceFileControl.fail("file_sources_command_expired")
                }, at)
            authority()
            send(reply) // Actual caller's secure send, never the personal queue.
            authority()
        } finally { commandLive.set(null); ticket.compareAndSet(issued, null); controls.session.finishConfiguration(issued) }
        Unit
    }

    /** UI preparation returns attempt metadata only; background transport must
     * acquire fresh native authority independently, never from reply fields. */
    internal fun preparePermissionReply(message: JsonObject, ledger: NativeGalleryPermissionCommands,
        now: () -> Long = { System.currentTimeMillis() }): JsonObject {
        if (DeviceFileSourceCommand.parse(message, now()).operation != "request_read") DeviceFileControl.fail("file_sources_invalid_command")
        var reply: JsonObject? = null
        receiveSourceCommand(message, { reply = it }, now, ledger)
        return reply ?: DeviceFileControl.fail("file_sources_invalid_command")
    }

    internal fun sendPreparedPermissionReply(message: JsonObject, reply: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = { System.currentTimeMillis() }): Unit = withOperation {
        val command = DeviceFileSourceCommand.parse(message, now())
        if (command.operation != "request_read") DeviceFileControl.fail("file_sources_invalid_command")
        val issued = controls.session.configurationTicket()
        fun checkAuthority() {
            if (now() >= command.expires) DeviceFileControl.fail("file_sources_command_expired")
            if (controls.session.configurationAuthority(issued) == null || workflow.currentRequest() == null)
                DeviceFileControl.fail("file_sources_authority_changed")
            if (workflow.savedPolicy().version != command.expectedVersion) DeviceFileControl.fail("gallery_policy_cas_conflict")
        }
        try {
            checkAuthority()
            send(reply) // Actual completion, not queue acceptance.
            checkAuthority()
        } finally { controls.session.finishConfiguration(issued) }
    }

    fun configureFromAuthenticatedCommand(expected: GalleryPhotoPolicySnapshot, enabled: Boolean,
        kinds: Set<GallerySourceKind>): GalleryPhotoPolicySnapshot = withOperation {
        ready()
        val issued = controls.session.configurationTicket()
        if (!ticket.compareAndSet(null, issued)) {
            controls.session.finishConfiguration(issued)
            DeviceFileControl.fail("file_control_configuration_busy")
        }
        try { workflow.configure(expected, enabled, kinds) }
        finally { ticket.compareAndSet(issued, null); controls.session.finishConfiguration(issued) }
    }

    fun disableLocally(expected: GalleryPhotoPolicySnapshot): GalleryPhotoPolicySnapshot = withOperation {
        workflow.disableLocally(expected)
    }

    /** Native channel-end path can revoke file authority synchronously on any
     * thread. Metadata/permission-host ownership remains held until actual UI
     * cleanup; this is not a worker-END or quota-retirement receipt.
     */
    fun revokeControl() {
        revoked.set(true)
        controls.close()
        sourceWorker.close() // Native cancellation must run outside our ownership monitor.
    }

    internal fun closeWhenQuiescent(completed: () -> Unit): Boolean {
        if (closed.get()) return true
        revokeControl()
        // The workflow owns ActivityResult/lifecycle registration. Reject a
        // wrong-thread final close BEFORE claiming completed cleanup or closing
        // only half of the native resources. The native owner must then finish
        // close on the UI thread; authority is already synchronously revoked.
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        synchronized(this) {
            if (closed.get()) return true
            if (operationActive || !sourceWorker.isQuiescent) {
                closeCompletion = completed
                return false // Source index and native owner remain held until actual I/O end.
            }
            if (!closed.compareAndSet(false, true)) return true
            closeCompletion = null
            ticket.set(null)
            wireCatalog.getAndSet(null)?.close()
            NativeGalleryForeground.detach(this)
            try { workflow.close() } finally { index.close() }
            return true
        }
    }

    override fun close() {
        if (!closeWhenQuiescent { close() }) DeviceFileControl.fail("gallery_source_worker_io_pending")
    }

    private fun sourceIoEnded() {
        // Serialize with the quiescence check/registration to avoid losing a
        // completion between that check and installing the native close callback.
        val completion = synchronized(this) {
            if (operationActive || !sourceWorker.isQuiescent) null
            else closeCompletion.also { closeCompletion = null }
        }
        completion?.let { android.os.Handler(Looper.getMainLooper()).post { it() } }
    }

    private inline fun <T> withOperation(operation: () -> T): T {
        if (!operationGate.tryLock()) DeviceFileControl.fail("file_control_configuration_busy")
        var owned = false
        try {
            synchronized(this) {
                ready()
                if (revoked.get()) DeviceFileControl.fail("gallery_file_runtime_revoked")
                if (operationActive) DeviceFileControl.fail("file_control_configuration_busy")
                operationActive = true; owned = true
            }
            // No provider, transport write, native cancellation or policy CAS
            // runs under the UI/cleanup ownership monitor.
            return operation()
        } finally {
            if (owned) synchronized(this) { operationActive = false }
            operationGate.unlock()
            if (owned) sourceIoEnded()
        }
    }

    private fun ready() { if (closed.get()) DeviceFileControl.fail("gallery_file_runtime_closed") }
}
