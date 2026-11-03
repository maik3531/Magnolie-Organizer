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
        now: Long = System.currentTimeMillis()): Unit = withOperation {
        sendSyncRunOfferOwned(run, send, { now })
        Unit
    }

    private fun sendSyncRunOfferOwned(run: NativeGallerySyncRun, send: (JsonObject) -> Unit,
        now: () -> Long, checkCommand: () -> Unit = {},
        wire: Pair<DeviceFileSourceCommand, JsonObject>? = null): NativeGalleryOfferOutput {
        if (syncRun !== run || run.cancelRequested) DeviceFileControl.fail("gallery_sync_run_not_current")
        if (run.acceptance.get() != null) DeviceFileControl.fail("file_accept_already_bound")
        val held = run.wireOfferAttempt.get()
        val digest = wire?.let { DeviceFileControl.digest("magnolie-gallery-offer-command-v1\u0000", it.second) }
        if (held != null && (wire == null || held.requestId != wire.first.requestId || held.commandSha256 != digest))
            DeviceFileControl.fail("gallery_sync_offer_attempt_held")
        held?.checkCurrent(now())
        if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
        val job = run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val selected = run.selection
        val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
        val manifest = source.manifest
        val fingerprint = manifest.fingerprint
        checkCommand()
        val offer = held?.message ?: if (wire == null) source.offerMessage(now()) else {
            val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, wire.first.expires - at)
            if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
            DeviceFileOfferEnvelope.create(manifest, at, ttlMs = ttl).also {
                // Capture the exact immutable envelope BEFORE actual output.
                // A lost offer/result write may retry only this native attempt,
                // never silently replace the remotely pending offer identity.
                run.wireOfferAttempt.set(NativeGalleryWireOfferAttempt(wire.first.requestId, digest!!, it, at))
            }
        }
        if (DeviceFileOfferEnvelope.validate(offer, manifest.senderId, manifest.receiverId, now()).fingerprint != fingerprint ||
            now() >= offer.long("expires_ms")) DeviceFileControl.fail("file_offer_invalid_envelope")
        if (workflow.currentRequest() == null || run.cancelRequested) DeviceFileControl.fail("gallery_source_not_activated")
        checkCommand()
        run.wireOfferAttempt.get()?.checkCurrent(now())
        send(offer)
        // Revalidate actual protected source authority after output as well.
        if (source.manifest.fingerprint != fingerprint || workflow.currentRequest() == null || run.cancelRequested)
            DeviceFileControl.fail("gallery_source_not_activated")
        checkCommand()
        run.wireOfferAttempt.get()?.checkCurrent(now())
        if (now() >= offer.long("expires_ms")) DeviceFileControl.fail("file_offer_invalid_envelope")
        run.offered.set(fingerprint)
        return NativeGalleryOfferOutput(offer.string("message_id"), manifest.transferId, fingerprint, offer.long("expires_ms")).also {
            run.offerOutput.set(it)
        }
    }

    internal fun observeAcceptance(message: JsonObject, now: () -> Long = { System.currentTimeMillis() }): Unit = withOperation {
        val accepted = DeviceFileAcceptanceEnvelope.parse(message, now())
        val run = syncRun?.takeUnless { it.cancelRequested } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        val offer = run.offerOutput.get() ?: DeviceFileControl.fail("file_accept_offer_not_sent")
        run.wireOfferAttempt.get()?.let {
            it.checkCurrent(now())
            if (offer.messageId != it.message.string("message_id")) DeviceFileControl.fail("file_accept_offer_not_sent")
        }
        if (now() >= offer.expires || accepted.offerId != offer.messageId || accepted.transferId != offer.transferId ||
            accepted.manifestSha256 != offer.manifestSha256) DeviceFileControl.fail("file_accept_offer_changed")
        val request = workflow.currentRequest() ?: DeviceFileControl.fail("gallery_source_not_activated")
        if (request.receiver.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_accept_permission_changed")
        val prior = run.acceptance.get()
        if (prior != null && prior != accepted) DeviceFileControl.fail("file_accept_already_bound")
        // Actual protected source validation is independent of the remote token.
        val job = run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val selected = run.selection
        val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
        if (source.manifest.fingerprint != accepted.manifestSha256 || workflow.currentRequest()?.receiver?.permissionEpoch != accepted.permissionEpoch)
            DeviceFileControl.fail("file_accept_permission_changed")
        val checked = now()
        run.wireOfferAttempt.get()?.checkCurrent(checked)
        if (checked >= accepted.expires || checked >= offer.expires) DeviceFileControl.fail("file_accept_offer_changed")
        source.commitRemoteAcceptance(offer, accepted) {
            val current = now()
            run.wireOfferAttempt.get()?.checkCurrent(current)
            if (run.cancelRequested || current >= accepted.expires || current >= offer.expires ||
                workflow.currentRequest()?.receiver?.permissionEpoch != accepted.permissionEpoch)
                DeviceFileControl.fail("file_accept_permission_changed")
        }
        if (now() >= accepted.expires || now() >= offer.expires || run.cancelRequested ||
            workflow.currentRequest()?.receiver?.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_accept_permission_changed")
        run.acceptance.set(accepted)
    }

    internal fun cancelSyncRun(run: NativeGallerySyncRun) = withOperation {
        if (syncRun !== run) DeviceFileControl.fail("gallery_sync_run_not_current")
        run.stopped.set(true)
        run.preparation.cancel() // Cancellation does not release whole-run ownership.
    }

    internal fun receiveChunkRequest(message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = { System.currentTimeMillis() }): Unit = withOperation {
        val request=DeviceFileChunkEnvelope.parseRequest(message,now())
        val run=syncRun?.takeUnless { it.cancelRequested } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        val accepted=run.acceptance.get() ?: DeviceFileControl.fail("file_chunk_not_accepted")
        if (request.transferId != accepted.transferId || request.manifestSha256 != accepted.manifestSha256 ||
            request.acceptanceSha256 != accepted.acceptanceSha256 || request.destinationToken != accepted.destinationToken ||
            request.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_chunk_acceptance_changed")
        fun authority() {
            if (now() >= request.expires || run.cancelRequested || workflow.currentRequest()?.receiver?.permissionEpoch != accepted.permissionEpoch)
                DeviceFileControl.fail("file_chunk_authority_changed")
        }
        authority()
        val selected=run.selection
        val job=run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val source=workflow.source(job,selected.catalog.source,selected.album,selected.desktopChoice)
        if (source.manifest.fingerprint != accepted.manifestSha256) DeviceFileControl.fail("file_chunk_acceptance_changed")
        source.requireRemoteAcceptance(accepted)
        val data=source.readChunk(request.fileId,request.chunkIndex)
        try {
            authority()
            val response=DeviceFileChunkEnvelope.response(request,data,now())
            authority();send(response);authority()
            if (source.manifest.fingerprint != accepted.manifestSha256) DeviceFileControl.fail("file_chunk_acceptance_changed")
            source.requireRemoteAcceptance(accepted)
        } finally { data.fill(0) }
        // A completed chunk write releases no source quota or whole-run owner.
    }

    internal fun observeRemoteSaved(message: JsonObject, now: () -> Long = { System.currentTimeMillis() }): Unit = withOperation {
        val run=syncRun?.takeUnless { it.cancelRequested } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        val accepted=run.acceptance.get() ?: DeviceFileControl.fail("file_chunk_not_accepted")
        fun authority() {
            if (run.cancelRequested || workflow.currentRequest()?.receiver?.permissionEpoch != accepted.permissionEpoch)
                DeviceFileControl.fail("file_saved_authority_changed")
        }
        authority()
        val job=run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val selected=run.selection
        val source=workflow.source(job,selected.catalog.source,selected.album,selected.desktopChoice)
        val confirmation=DeviceFileSavedEnvelope.parse(message,source.manifest,now())
        if (confirmation.transferId != accepted.transferId || confirmation.manifestSha256 != accepted.manifestSha256 ||
            confirmation.acceptanceSha256 != accepted.acceptanceSha256 || confirmation.permissionEpoch != accepted.permissionEpoch ||
            confirmation.destinationToken != accepted.destinationToken) DeviceFileControl.fail("file_saved_acceptance_changed")
        val prior=run.remoteSaved.get()
        if (prior != null && prior.fingerprint != confirmation.fingerprint) DeviceFileControl.fail("file_saved_already_bound")
        authority()
        if (source.manifest.fingerprint != confirmation.manifestSha256 || now() >= confirmation.expires)
            DeviceFileControl.fail("file_saved_authority_changed")
        val durable = source.commitRemoteSaved(accepted, message) {
            authority()
            if (now() >= confirmation.expires) DeviceFileControl.fail("file_saved_authority_changed")
        }
        authority()
        if (now() >= confirmation.expires) DeviceFileControl.fail("file_saved_authority_changed")
        run.remoteSaved.set(prior ?: durable.confirmation)
        // Do not retire source quota, commit photo baselines or report whole-run
        // success from a remote historical assertion. Those native steps differ.
    }

    /** Explicit native caller only; no IPC routing or automatic selection. */
    internal fun historicalSourceJobs(): List<PhotoSourceJob> = withOperation { index.jobs() }

    internal fun issueHistoricalSavedAction(expected: PhotoSourceJob): NativeHistoricalSavedAction = withOperation {
        if (syncRun != null || !sourceWorker.isQuiescent) DeviceFileControl.fail("gallery_sync_run_held")
        index.issueHistoricalSavedAction(expected, { workflow.currentRequest()?.receiver })
    }

    internal fun recoverHistoricalSaved(action: NativeHistoricalSavedAction, message: JsonObject,
        now: () -> Long = { System.currentTimeMillis() }): PhotoSourceRemoteSaved = withOperation {
        if (syncRun != null || !sourceWorker.isQuiescent) DeviceFileControl.fail("gallery_sync_run_held")
        index.commitHistoricalRemoteSaved(action, message, now)
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
            if (command.operation == "media_page") {
                val run = syncRun?.takeIf { it.id == command.runId && !it.cancelRequested }
                    ?: DeviceFileControl.fail("gallery_sync_run_not_current")
                fun mediaAuthority() { authority(); run.mediaAttempts.check(command, message, now()) }
                mediaAuthority()
                if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
                val job = run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
                val selected = run.selection
                val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
                val page = source.mediaPage(command.after, ::mediaAuthority)
                mediaAuthority()
                val body = kotlinx.serialization.json.buildJsonObject {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId))
                    put("operation", JsonPrimitive(command.operation)); put("version", JsonPrimitive(before.version))
                    put("run_id", JsonPrimitive(run.id)); put("page", page)
                }
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                val reply = TelefonNachrichten.message(DeviceFileSourceCommand.MEDIA, body, ttl, at)
                if (TelefonKanonisch.bytes(reply).size > DeviceFileControl.MAX_WIRE_BYTES) DeviceFileControl.fail("gallery_media_page_budget")
                mediaAuthority(); send(reply); mediaAuthority()
                return@withOperation
            }
            if (command.operation in setOf("run", "run_status", "cancel_run", "offer_run")) {
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
                val output = if (command.operation == "offer_run") sendSyncRunOfferOwned(run, send, now,
                    { authority(); Unit }, command to message) else null
                authority()
                val ioEnded = run.preparation.ioEnded
                val state = if (run.cancelRequested && !ioEnded) "cancel_pending"
                    else if (run.cancelRequested) "canceled_held" else if (ioEnded) run.preparation.phase else "preparing"
                val body = kotlinx.serialization.json.buildJsonObject {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                    put("state", JsonPrimitive(state)); put("source_io_ended", JsonPrimitive(ioEnded))
                    if (output != null) {
                        put("offer_id", JsonPrimitive(output.messageId)); put("manifest_sha256", JsonPrimitive(output.manifestSha256))
                    }
                }
                val at = now(); val deadline = minOf(command.expires, output?.expires ?: command.expires)
                val ttl = minOf(DeviceFileControl.MAX_TTL_MS, deadline - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                authority(); send(TelefonNachrichten.message(DeviceFileSourceCommand.RUN_RESULT, body, ttl, at)); authority()
                if (now() >= deadline) DeviceFileControl.fail("file_sources_command_expired")
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
