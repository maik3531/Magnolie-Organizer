package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Looper
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonArray
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Explicit native I/O-lane join of actual protected policy, dedicated grants,
 * secure-channel controls and source workflow. Not a service/dispatcher: no
 * construction from a wire body, store/key generation, scanning, scheduling or
 * discovery advertisement. The caller supplies existing native identity/key,
 * private directory and authenticated current-peer/channel ownership.
 */
internal class NativeGalleryFileRuntime private constructor(context: Context, directory: File, identity: NativeFileControlIdentity,
    protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
    handlersReady: () -> Boolean, videoHandlersReady: () -> Boolean,
    currentMediaIntent: ((GalleryMediaType) -> Any?)?,
    private val currentIncomingIntent: ((GalleryMediaType) -> Any?)? = null,
    receiveHandlersReady: () -> Boolean = { false }) : AutoCloseable {
    constructor(context: Context, directory: File, identity: NativeFileControlIdentity,
        protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
        handlersReady: () -> Boolean) : this(context, directory, identity, protection, channel, currentPeer, handlersReady, { false }, null)
    companion object {
        internal fun withVideoHandlers(context: Context, directory: File, identity: NativeFileControlIdentity,
            protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
            handlersReady: () -> Boolean, videoHandlersReady: () -> Boolean) =
            NativeGalleryFileRuntime(context, directory, identity, protection, channel, currentPeer, handlersReady, videoHandlersReady, null)
        internal fun withSharedMediaIntent(context: Context, directory: File, identity: NativeFileControlIdentity,
            protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
            handlersReady: () -> Boolean, videoHandlersReady: () -> Boolean, currentMediaIntent: ((GalleryMediaType) -> Any?)?) =
            NativeGalleryFileRuntime(context, directory, identity, protection, channel, currentPeer, handlersReady, videoHandlersReady, currentMediaIntent)
        /** Explicit native integration seam only. Existing source factories
         * remain receive-closed; this does not advertise discovery/UI readiness. */
        internal fun withIncomingMedia(context: Context, directory: File, identity: NativeFileControlIdentity,
            protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
            handlersReady: () -> Boolean, videoHandlersReady: () -> Boolean, currentMediaIntent: ((GalleryMediaType) -> Any?)?,
            currentIncomingIntent: (GalleryMediaType) -> Any?, receiveHandlersReady: () -> Boolean) =
            NativeGalleryFileRuntime(context, directory, identity, protection, channel, currentPeer, handlersReady, videoHandlersReady,
                currentMediaIntent, currentIncomingIntent, receiveHandlersReady)
    }
    private val closed = AtomicBoolean(false)
    private val revoked = AtomicBoolean(false)
    private val operationGate = java.util.concurrent.locks.ReentrantLock()
    private var operationActive = false // Guarded by the short-lived runtime monitor.
    private var syncRun: NativeGallerySyncRun? = null // Access only through operationGate.
    private var resumeRun: NativeGalleryResumeRun? = null // Same whole-run owner, not disk metadata.
    private var resumeEnd: ResumeEndOutput? = null // Bounded metadata retry, never a live source owner.
    private var normalEnd: Pair<NativeGalleryWireOfferAttempt, JsonObject>? = null
    private class AlbumBatchOwner(val selection: NativeGalleryAlbumSelection,
        val scan: NativeGalleryPhotoWorkflow.AlbumBatches) {
        val prepared = AtomicReference<NativeGalleryPhotoWorkflow.FrozenBatch?>()
        var run: NativeGallerySyncRun? = null // operationGate only
    }
    private var albumBatchOwner: AlbumBatchOwner? = null
    private var albumEnd: Pair<NativeGalleryWireOfferAttempt, JsonObject>? = null
    private class ResumeEndOutput(val command: JsonObject, val reply: JsonObject, issuedWall: Long,
        val job: PhotoSourceJob, val headId: String?, val headSha256: String?) {
        var abandonmentCommand: NativeGalleryWireOfferAttempt? = null
        private val issued = DeviceFileControl.monotonicMs()
        private val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.long("expires_ms") - issuedWall)
        private val clock = NativeGalleryWireOfferAttempt(command.string("message_id"),
            DeviceFileControl.digest("magnolie-gallery-resume-end-command-v1\u0000", command), command, issuedWall, issued)
        private var invalid = false
        init { if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired") }
        fun check(wall: Long) {
            val elapsed = DeviceFileControl.monotonicMs()
            clock.checkCurrent(wall, elapsed)
            if (invalid || elapsed >= issued + ttl) {
                invalid = true; DeviceFileControl.fail("file_sources_command_expired")
            }
        }
    }
    private val app = context.applicationContext
    private val localIdentity = identity
    private val localPermissionCommands = NativeGalleryPermissionCommands()
    private val localRunCommands = NativeGalleryRunCommands()
    private val localResumeCommands = NativeGalleryResumeCommands()
    private val ticket = AtomicReference<NativeFileConfigurationTicket?>()
    private val receiveTicket = AtomicReference<NativeFileConfigurationTicket?>()
    private val receiveConfiguration = AtomicReference<Pair<NativeFileReceiveConfigurer, NativeFileControlPeer>?>()
    private val receivePolicyHealthy = AtomicBoolean(true)
    private val commandLive = AtomicReference<(() -> Boolean)?>()
    private val wireCatalog = AtomicReference<NativeGalleryAlbumCatalog?>()
    private val videoWireCatalog = AtomicReference<NativeGalleryAlbumCatalog?>()
    private fun wireCatalog(mediaType: GalleryMediaType) = if (mediaType == GalleryMediaType.IMAGES) wireCatalog else videoWireCatalog
    private val nativePeer = { if (closed.get() || revoked.get()) null else currentPeer() }
    private val incomingAvailable = { receivePolicyHealthy.get() && handlersReady() && receiveHandlersReady() && currentIncomingIntent != null && nativePeer()?.allowed == true }
    private val videoAvailable = { handlersReady() && videoHandlersReady() && nativePeer()?.let { it.allowed && it.videoSupported } == true }
    private val index = PhotoSourceJobIndex(directory, protection)
    private val grants = NativeGalleryFileGrantPolicy(nativePeer, { index.galleryPolicy() }, handlersReady, incomingAvailable)
    private val incomingWorker = NativeGalleryIncomingWorker { sourceIoEnded() }
    private val incomingRows = NativeGalleryIncomingRows(context, index)
    private val publishedReadWorker = NativeGalleryPublishedReadWorker(incomingRows) { sourceIoEnded() }
    private val nativeChannel = channel
    private val controls: NativeFileControlChannel
    private val receivePolicy: GalleryReceivePolicyController
    private val workflow: NativeGalleryPhotoWorkflow
    private val sourceWorker: NativeGallerySourceWorker
    private var closeCompletion: (() -> Unit)? = null // Guarded by this runtime monitor.

    init {
        var prepared: NativeFileControlChannel? = null
        try {
            prepared = NativeFileControlChannel(identity, channel, nativePeer, { grants.current() }, incomingAvailable)
            controls = prepared
            val receivePeer = nativePeer() ?: DeviceFileControl.fail("gallery_incoming_current_owner_required")
            receivePolicy = GalleryReceivePolicyController(index, NativeFileControlIdentity(receivePeer.peerId, receivePeer.identitySha256),
                ::currentReceiveConfiguration)
            workflow = NativeGalleryPhotoWorkflow.forSharedMediaIntent(context, directory, identity.deviceId, protection,
                { if (closed.get() || revoked.get()) null else controls.session.photoReceiver() },
                 { if (commandLive.get()?.invoke() == false) null else ticket.get()?.let { controls.session.configurationAuthority(it) } },
                 videoAvailable, currentMediaIntent)
            sourceWorker = NativeGallerySourceWorker({ selected, cancellation -> workflow.freeze(selected, cancellation) }, { sourceIoEnded() })
        } catch (error: Exception) {
            closed.set(true); prepared?.close(); index.close()
            throw error // Dedicated metadata/cache is preserved, not reset.
        }
    }

    fun sendControls(now: Long = System.currentTimeMillis()): Boolean = withOperation(allowIncoming = true) {
        controls.sendIfNeeded(now).also { incomingWorker.current?.retireIfChanged(); publishedReadWorker.current?.retireIfChanged() }
    }
    fun observeControls(message: JsonObject, now: Long = System.currentTimeMillis()): Boolean = withOperation(allowIncoming = true) {
        controls.observe(message, now).also { incomingWorker.current?.retireIfChanged(); publishedReadWorker.current?.retireIfChanged() }
    }
    internal fun beginIncomingMediaOffer(message: JsonObject, book: NativeGalleryReceiveBookPermit,
        automaticReadback: Boolean = false, requireReadbackAgreement: () -> Unit = {}): NativeGalleryIncomingRun {
        val peer = nativePeer() ?: DeviceFileControl.fail("gallery_incoming_current_owner_required")
        val media = MediaOfferEnvelope.validate(message, peer.peerId, localIdentity.deviceId)
        val intent = currentIncomingIntent?.invoke(media.kind) as? MediaSyncTransport.IntentToken
            ?: DeviceFileControl.fail("gallery_incoming_current_intent_required")
        if (intent.body != media.settings) DeviceFileControl.fail("gallery_incoming_offer_intent_changed")
        return beginIncomingOwned(media.offer, media.kind, media.mimeTypes, book, media.originals, intent, automaticReadback, requireReadbackAgreement, media.pcOrigins)
    }

    internal fun beginIncoming(offer: JsonObject, kind: GalleryMediaType, mimeTypes: Map<String, String>,
        book: NativeGalleryReceiveBookPermit, references: Map<String, GalleryPhoneMediaReference> = emptyMap(),
         expectedIntent: MediaSyncTransport.IntentToken? = null, automaticReadback: Boolean = false,
          requireReadbackAgreement: () -> Unit = {}): NativeGalleryIncomingRun =
        beginIncomingOwned(offer, kind, mimeTypes, book, references, expectedIntent, automaticReadback, requireReadbackAgreement, emptyMap())

    private fun beginIncomingOwned(offer: JsonObject, kind: GalleryMediaType, mimeTypes: Map<String, String>,
        book: NativeGalleryReceiveBookPermit, references: Map<String, GalleryPhoneMediaReference>,
        expectedIntent: MediaSyncTransport.IntentToken?, automaticReadback: Boolean,
        requireReadbackAgreement: () -> Unit, pcOrigins: Map<String, GalleryPcMediaOrigin>): NativeGalleryIncomingRun = withOperation {
        if (!incomingAvailable()) DeviceFileControl.fail("gallery_incoming_handlers_unavailable")
        if (kind == GalleryMediaType.VIDEO && !videoAvailable()) DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
        if (!sourceWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null)
            DeviceFileControl.fail("gallery_sync_run_busy")
        val current = nativePeer() ?: DeviceFileControl.fail("gallery_incoming_current_owner_required")
        if (expectedIntent != null && currentIncomingIntent?.invoke(kind) !== expectedIntent)
            DeviceFileControl.fail("gallery_incoming_offer_intent_changed")
        val manifest = DeviceFileOfferEnvelope.validate(offer, current.peerId, localIdentity.deviceId)
        val types = mimeTypes.toMap()
        val originalReferences = references.toMap()
        val originalPcOrigins = pcOrigins.toMap()
        val originalIntent = currentIncomingIntent?.invoke(kind)
            ?: DeviceFileControl.fail("gallery_incoming_current_intent_required")
        incomingWorker.start(completedReadback = { completed ->
            if (!automaticReadback) beginCompletedIncomingReadback(completed, offer, book, kind, originalIntent)
            else {
                val remaining = minOf(1000L, offer.long("expires_ms") - System.currentTimeMillis())
                if (remaining <= 0 || !operationGate.tryLock(remaining, java.util.concurrent.TimeUnit.MILLISECONDS))
                    DeviceFileControl.fail("file_control_configuration_busy")
                try {
                    // The original start operation may still be returning on the
                    // receiver. Wait only on this native thread, bounded, with no
                    // index guard held. All owners are checked again below.
                    requireReadbackAgreement()
                    beginCompletedIncomingReadback(completed, offer, book, kind, originalIntent)
                } finally { operationGate.unlock() }
            }
        }, automaticReadback = automaticReadback) {
            val owner = NativeGalleryIncomingOwner.capture(controls.session, index, book, nativePeer,
                { currentIncomingIntent?.invoke(kind)?.takeIf { expectedIntent == null || it === expectedIntent } }, manifest, kind, originalReferences, originalPcOrigins)
            try { NativeGalleryIncomingTransfer.prepare(owner, nativeChannel, index, incomingRows, offer, types) }
            catch (error: Throwable) { owner.close(); throw error }
        }
    }
    private fun beginCompletedIncomingReadback(completed: NativeGalleryIncomingRun, offer: JsonObject,
        book: NativeGalleryReceiveBookPermit, kind: GalleryMediaType, originalIntent: Any): NativeGalleryPublishedReadRun = withOperation {
        if (Looper.myLooper() == Looper.getMainLooper()) DeviceFileControl.fail("gallery_incoming_worker_io_required")
        if (!incomingWorker.owns(completed) || !incomingAvailable() || currentIncomingIntent?.invoke(kind) !== originalIntent)
            DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        book.requireCurrent()
        if (kind == GalleryMediaType.VIDEO && !videoAvailable()) DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
        if (!sourceWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null)
            DeviceFileControl.fail("gallery_sync_run_busy")
        val selected = completed.actualPublishedOutput()
        val origin = selected.body.getValue("origin").jsonObject
        val originalEpoch = origin.getValue("binding").jsonObject.string("permission_epoch")
        if (controls.session.binding(origin.string("manifest_sha256"))?.permissionEpoch != originalEpoch)
            DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        val saved = completed.actualSavedOutput() ?: DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        val receipt = saved.getValue("body").jsonObject.getValue("receipts").jsonArray.singleOrNull()?.jsonObject
            ?: DeviceFileControl.fail("gallery_incoming_completed_owner_required")
        if (receipt["receipt_sha256"] != JsonPrimitive(selected.fingerprint) ||
            index.incomingPublication(selected.id)?.body != selected.body)
            DeviceFileControl.fail("gallery_incoming_original_changed")
        publishedReadWorker.startReadback {
            val owner = NativeGalleryPublishedInspection.capture(controls.session, index, book, nativePeer,
                { currentIncomingIntent?.invoke(kind)?.takeIf { it === originalIntent } }, selected)
            try {
                if (owner.bindingForReadback(origin.string("manifest_sha256")).permissionEpoch != originalEpoch)
                    DeviceFileControl.fail("gallery_incoming_completed_owner_required")
                NativeGalleryPublishedReadback.capture(owner, offer, nativeChannel)
            } catch (error: Throwable) { owner.close(); throw error }
        }
    }
    /** Exact native authenticated dispatcher input; never take the operation
     * gate behind a worker waiting for this very chunk. */
    internal fun observeIncomingChunk(channel: TelefonSecureChannel, message: JsonObject): Boolean {
        if (closed.get() || revoked.get() || channel !== nativeChannel) return false
        return incomingWorker.current?.observe(channel, message) ?: false
    }
    internal fun cancelIncoming(run: NativeGalleryIncomingRun) {
        if (!incomingWorker.owns(run)) DeviceFileControl.fail("gallery_incoming_worker_foreign_run")
        run.cancel()
    }
    internal fun incomingContextWithdrawn() { incomingWorker.current?.cancel(); publishedReadWorker.current?.cancel() }

    /** Explicit native selection of one exact historical publication, not a wire
     * command/automatic receipt. All journal/provider work runs off the UI thread. */
    internal fun beginPublishedInspection(id: String, fingerprint: String,
        book: NativeGalleryReceiveBookPermit): NativeGalleryPublishedReadRun = withOperation {
        if (!incomingAvailable()) DeviceFileControl.fail("gallery_incoming_handlers_unavailable")
        if (!DeviceFileControl.hash(id) || !DeviceFileControl.hash(fingerprint)) DeviceFileControl.fail("gallery_incoming_publication_invalid")
        if (!sourceWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null)
            DeviceFileControl.fail("gallery_sync_run_busy")
        publishedReadWorker.start {
            val selected = index.incomingPublication(id)?.takeIf { it.fingerprint == fingerprint }
                ?: DeviceFileControl.fail("gallery_incoming_original_changed")
            val kind = GalleryMediaType.entries.single { it.uriSegment == selected.body.string("media_type") }
            if (kind == GalleryMediaType.VIDEO && !videoAvailable()) DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
            NativeGalleryPublishedInspection.capture(controls.session, index, book, nativePeer,
                { currentIncomingIntent?.invoke(kind) }, selected)
        }
    }
    internal fun cancelPublishedInspection(run: NativeGalleryPublishedReadRun) {
        if (!publishedReadWorker.owns(run)) DeviceFileControl.fail("gallery_published_worker_foreign_run")
        run.cancel()
    }
    internal fun beginPublishedReadback(channel: TelefonSecureChannel, offer: JsonObject, id: String, fingerprint: String,
        book: NativeGalleryReceiveBookPermit): NativeGalleryPublishedReadRun = withOperation {
        if (channel !== nativeChannel) DeviceFileControl.fail("gallery_published_foreign_channel")
        if (!incomingAvailable()) DeviceFileControl.fail("gallery_incoming_handlers_unavailable")
        if (!DeviceFileControl.hash(id) || !DeviceFileControl.hash(fingerprint)) DeviceFileControl.fail("gallery_incoming_publication_invalid")
        if (!sourceWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null)
            DeviceFileControl.fail("gallery_sync_run_busy")
        publishedReadWorker.startReadback {
            val selected = index.incomingPublication(id)?.takeIf { it.fingerprint == fingerprint }
                ?: DeviceFileControl.fail("gallery_incoming_original_changed")
            val kind = GalleryMediaType.entries.single { it.uriSegment == selected.body.string("media_type") }
            if (kind == GalleryMediaType.VIDEO && !videoAvailable()) DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
            val owner = NativeGalleryPublishedInspection.capture(controls.session, index, book, nativePeer,
                { currentIncomingIntent?.invoke(kind) }, selected)
            NativeGalleryPublishedReadback.capture(owner, offer, channel)
        }
    }

    /** No transport/session/Werk monitor inside protected index guards. The
     * control authority is freshly checked under operationGate before freezing;
     * its exact ticket/native peer remain revocable during the local policy CAS. */
    private fun currentReceiveConfiguration(): NativeFileReceiveConfigurer? {
        val frozen = receiveConfiguration.get() ?: return null
        if (receiveTicket.get() !== frozen.first.owner) return null
        val peer = nativePeer()?.takeIf { it.allowed } ?: return null
        if (peer.owner !== frozen.second.owner || peer.peerId != frozen.second.peerId || peer.identitySha256 != frozen.second.identitySha256 ||
            peer.pairingEpoch != frozen.second.pairingEpoch) return null
        return frozen.first
    }

    private inline fun <T> withReceiveIdleLane(action: () -> T): T {
        if (!incomingAvailable()) DeviceFileControl.fail("gallery_incoming_handlers_unavailable")
        if (!sourceWorker.isQuiescent || !incomingWorker.isQuiescent || !publishedReadWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null)
            DeviceFileControl.fail("gallery_sync_run_busy")
        val lease = Any()
        if (!NativeGalleryMediaIoLane.acquire(lease)) DeviceFileControl.fail("gallery_incoming_worker_busy")
        try { return action() } finally { NativeGalleryMediaIoLane.release(lease) }
    }

    /** Native IO-lane preparation only. The UI must still present the real
     * foreground positive dialog with its current saved-book witness. */
    internal fun receiveConsentIntent(kind: GalleryMediaType): MediaSyncTransport.IntentToken = withOperation {
        if (!incomingAvailable()) DeviceFileControl.fail("gallery_incoming_handlers_unavailable")
        if (kind == GalleryMediaType.VIDEO && !videoAvailable()) DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
        currentIncomingIntent?.invoke(kind) as? MediaSyncTransport.IntentToken
            ?: DeviceFileControl.fail("gallery_incoming_current_intent_required")
    }

    internal fun beginReceiveConfiguration(): NativeFileReceiveConfigurer = withOperation {
        if (Looper.myLooper() == Looper.getMainLooper()) DeviceFileControl.fail("gallery_receive_policy_io_thread_required")
        withReceiveIdleLane {
            val issued = controls.session.receiveConfigurationTicket()
            if (!receiveTicket.compareAndSet(null, issued)) {
                controls.session.finishConfiguration(issued); DeviceFileControl.fail("file_control_configuration_busy")
            }
            try { controls.session.receiveConfigurationAuthority(issued) ?: DeviceFileControl.fail("file_control_configuration_not_ready") }
            catch (error: Exception) {
                receiveTicket.compareAndSet(issued, null); controls.session.finishConfiguration(issued); throw error
            }
        }
    }

    internal fun finishReceiveConfiguration(configurer: NativeFileReceiveConfigurer) {
        val issued = receiveTicket.get() ?: return
        if (issued !== configurer.owner) DeviceFileControl.fail("gallery_receive_configurer_changed")
        if (receiveTicket.compareAndSet(issued, null)) controls.session.finishConfiguration(issued)
    }

    internal fun grantReceiving(expected: GalleryPhotoPolicySnapshot, selection: NativeGalleryReceiveConsent): GalleryPhotoPolicySnapshot {
        if (Looper.myLooper() == Looper.getMainLooper()) DeviceFileControl.fail("gallery_receive_policy_io_thread_required")
        try {
            return withOperation {
                withReceiveIdleLane {
                    val issued = receiveTicket.get() ?: DeviceFileControl.fail("file_control_configuration_not_ready")
                    val configured = controls.session.receiveConfigurationAuthority(issued) ?: DeviceFileControl.fail("file_control_configuration_not_ready")
                    selection.requireConfigurer(configured)
                    val peer = nativePeer() ?: DeviceFileControl.fail("gallery_incoming_current_owner_required")
                    receiveConfiguration.set(configured to peer)
                    try {
                        val saved = receivePolicy.grant(expected, selection)
                        if (!incomingAvailable()) {
                            receivePolicyHealthy.set(false); DeviceFileControl.fail("gallery_receive_policy_commit_readback_failed")
                        }
                        saved
                    } finally {
                        receiveConfiguration.set(null)
                        if (!receivePolicy.available()) receivePolicyHealthy.set(false)
                    }
                }
            }
        } finally {
            try { finishReceiveConfiguration(selection.configurer) } finally { selection.close() }
        }
    }

    /** Explicit decrease works offline, without a receive backend or live PC.
     * It cancels actual old IO but keeps its lane/index until real drain. */
    internal fun revokeReceiving(expected: GalleryPhotoPolicySnapshot, kind: GalleryMediaType,
        book: NativeGalleryReceiveBookPermit): GalleryPhotoPolicySnapshot = withOperation(allowIncoming = true) {
        if (Looper.myLooper() == Looper.getMainLooper()) DeviceFileControl.fail("gallery_receive_policy_io_thread_required")
        book.requireCurrent()
        if (index.galleryPolicy() != expected) DeviceFileControl.fail("gallery_policy_cas_conflict")
        if (expected.policy?.receiving?.enabled(kind) == true) {
            incomingWorker.current?.cancel()
            publishedReadWorker.current?.cancel()
            sourceWorker.current?.let { sourceWorker.cancel(it) }
        }
        try { receivePolicy.revoke(expected, kind, book) }
        finally { if (!receivePolicy.available()) receivePolicyHealthy.set(false) }
    }
    fun savedPolicy(): GalleryPhotoPolicySnapshot { ready(); return workflow.savedPolicy() }
    fun currentRequest(mediaType: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryRequest? { ready(); return workflow.currentRequest(mediaType) }
    fun discoverSelectable(cancellation: android.os.CancellationSignal = android.os.CancellationSignal(),
        mediaType: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryAlbumCatalog = withOperation {
        workflow.discoverSelectable(cancellation, mediaType)
    }
    private fun selectionRequest(selection: NativeGalleryAlbumSelection): NativeGalleryRequest? = workflow.currentRequest(
        selection.catalog.source.activation?.mediaType ?: DeviceFileControl.fail("gallery_source_not_activated"))
    fun prepareSource(selection: NativeGalleryAlbumSelection): NativeGallerySourceRun = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        if (selectionRequest(selection) == null) DeviceFileControl.fail("gallery_source_not_activated")
        workflow.validateSelection(selection)
        sourceWorker.start(selection)
    }

    internal fun prepareRecoverableMember(selection: NativeGalleryAlbumSelection, job: PhotoSourceJob, fileId: String,
        permit: NativeGalleryTrashBookPermit): NativeGallerySourceRun = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        workflow.validateSelection(selection); permit.requireCurrent()
        sourceWorker.startArchive(selection) { cancellation -> workflow.archiveRecoverableMember(selection, job, fileId, permit, cancellation) }
    }

    internal fun requestGalleryOriginalAccess(mediaType: GalleryMediaType, permit: NativeGalleryTrashBookPermit,
        result: (Result<Unit>) -> Unit) = withOperation {
        if (!sourceWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        workflow.requestOriginalAccess(mediaType, permit, result)
    }

    internal fun prepareGalleryWriteConsent(entry: NativeGalleryArchiveEntry, permit: NativeGalleryTrashBookPermit): NativeGallerySourceRun = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        sourceWorker.startWriteRequest { cancellation -> workflow.prepareWriteConsent(entry, permit, cancellation) }
    }

    internal fun requestGalleryWriteConsent(request: NativeGalleryWriteRequest, result: (Result<NativeGalleryWriteGrant>) -> Unit) = withOperation {
        if (!sourceWorker.isQuiescent || syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        workflow.requestWriteConsent(request, result)
    }

    internal fun validateGalleryWriteTarget(grant: NativeGalleryWriteGrant): NativeGallerySourceRun = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        sourceWorker.startWriteTarget { cancellation -> workflow.validateWriteTarget(grant, cancellation) }
    }

    internal fun trashGalleryOriginal(grant: NativeGalleryWriteGrant): NativeGallerySourceRun = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        sourceWorker.startTrash { cancellation -> workflow.trashOriginal(grant, cancellation) }
    }

    internal fun restoreGalleryOriginal(session: NativeGalleryRestoreSession): NativeGallerySourceRun = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        sourceWorker.startTrash { cancellation -> workflow.restoreOriginal(session, cancellation) }
    }

    internal fun beginSyncRun(selection: NativeGalleryAlbumSelection): NativeGallerySyncRun = withOperation {
        beginSyncRunOwned(selection)
    }

    private fun beginSyncRunOwned(selection: NativeGalleryAlbumSelection, checkCommand: () -> Unit = {}): NativeGallerySyncRun {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        if (selectionRequest(selection) == null) DeviceFileControl.fail("gallery_source_not_activated")
        workflow.validateSelection(selection)
        checkCommand()
        return NativeGallerySyncRun(selection, sourceWorker.start(selection)).also { syncRun = it }
    }

    private fun beginAlbumBatchOwned(selection: NativeGalleryAlbumSelection, checkCommand: () -> Unit): NativeGallerySyncRun {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null) DeviceFileControl.fail("gallery_sync_run_busy")
        checkCommand(); workflow.validateSelection(selection)
        // Keep live authority validation within ordinary control deadlines.
        // This is a smaller working batch, never a relaxed manifest/quota limit.
        val owner = AlbumBatchOwner(selection, workflow.albumBatches(selection, maxFiles = 16))
        albumBatchOwner = owner
        return prepareAlbumBatchOwned(owner, checkCommand)
    }

    private fun nextAlbumBatchOwned(command: DeviceFileSourceCommand, checkCommand: () -> Unit): NativeGallerySyncRun {
        val owner = albumBatchOwner ?: DeviceFileControl.fail("gallery_album_batch_not_current")
        val previous = owner.run ?: DeviceFileControl.fail("gallery_album_batch_not_current")
        val endedId = normalEnd?.second?.get("body")?.let { it as? JsonObject }?.get("run_id")
        if (syncRun != null || resumeRun != null || !sourceWorker.isQuiescent || !previous.preparation.ioEnded ||
            !previous.cancelRequested || previous.id != command.runId || endedId != JsonPrimitive(previous.id) ||
            owner.prepared.get()?.reachedCurrentEnd != false)
            DeviceFileControl.fail("gallery_album_batch_not_current")
        val job = previous.preparation.completedNativeJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        // END alone is not Saved. Unconfirmed accepted sources retain their
        // cache and prevent continuation, also after explicit subset selection.
        if (index.jobs().any { it.id == job.id }) DeviceFileControl.fail("gallery_album_previous_batch_held")
        checkCommand(); owner.scan.requireAuthority()
        return prepareAlbumBatchOwned(owner, checkCommand)
    }

    private fun prepareAlbumBatchOwned(owner: AlbumBatchOwner, checkCommand: () -> Unit): NativeGallerySyncRun {
        checkCommand()
        owner.prepared.set(null)
        val preparing = sourceWorker.startBatch(owner.selection) { cancellation ->
            ready()
            owner.scan.next(cancellation).also { owner.prepared.set(it) }.job
        }
        return NativeGallerySyncRun(owner.selection, preparing).also { owner.run = it; syncRun = it }
    }

    internal fun beginResumeRun(selection: NativeGalleryAlbumSelection, original: PhotoSourceJob): NativeGalleryResumeRun = withOperation {
        beginResumeRunOwned(selection, original)
    }

    private fun selectSyncRunOwned(command: DeviceFileSourceCommand, checkCommand: () -> Unit): NativeGallerySyncRun {
        ready()
        val previous = syncRun?.takeIf { it.id == command.runId && !it.cancelRequested && it.acceptance.get() == null }
            ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        if (resumeRun != null || !sourceWorker.isQuiescent || !previous.preparation.ioEnded)
            DeviceFileControl.fail("gallery_source_worker_io_pending")
        val job = previous.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val selection = previous.selection
        val source = workflow.source(job, selection.catalog.source, selection.album, selection.desktopChoice)
        if (source.manifest.fingerprint != command.selectionManifestSha256 || index.remoteAcceptance(job) != null ||
            index.resumeAttempt(job) != null) DeviceFileControl.fail("photo_jobs_selected_preview_already_accepted")
        if (command.selectedFileIds.any { id -> source.manifest.files.none { it.id == id } })
            DeviceFileControl.fail("photo_snapshot_invalid_selection")
        checkCommand()
        val issued = DeviceFileControl.monotonicMs()
        previous.stopped.set(true) // Exact preview can no longer accept or output data.
        val preparing = sourceWorker.startSelected(selection) { cancellation ->
            var last = issued
            fun permitted() {
                val tick = DeviceFileControl.monotonicMs()
                if (issued < 0 || tick < last || tick - issued >= DeviceFileControl.MAX_TTL_MS)
                    DeviceFileControl.fail("gallery_selected_source_preparation_expired")
                last = tick; ready(); cancellation.throwIfCanceled()
                val batch = albumBatchOwner
                if (batch != null && batch.selection === selection) batch.scan.requireAuthority()
                else workflow.validateSelection(selection)
            }
            permitted()
            val selected = source.selectedJob(command.selectedFileIds, cancellation, ::permitted)
            permitted()
            // The selected cache has committed/read back. Only the never-accepted
            // preview is retired; original phone media is never changed.
            if (index.remoteAcceptance(job) != null || index.resumeAttempt(job) != null)
                DeviceFileControl.fail("photo_jobs_selected_preview_already_accepted")
            workflow.retireCached(job)
            permitted()
            selected
        }
        return NativeGallerySyncRun(selection, preparing).also {
            syncRun = it
            albumBatchOwner?.takeIf { owner -> owner.run === previous }?.run = it
        }
    }

    private fun beginResumeRunOwned(selection: NativeGalleryAlbumSelection, original: PhotoSourceJob,
        checkCommand: () -> Unit = {}): NativeGalleryResumeRun {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null || !sourceWorker.isQuiescent) DeviceFileControl.fail("gallery_sync_run_busy")
        if (selectionRequest(selection) == null) DeviceFileControl.fail("gallery_source_not_activated")
        index.requireGalleryResumeOriginal(original)
        workflow.validateSelection(selection)
        checkCommand()
        val preparing = sourceWorker.startRenewed(selection) { selected, cancellation -> workflow.renewSource(selected, original, cancellation) }
        return NativeGalleryResumeRun(selection, original, preparing).also { resumeRun = it }
    }

    internal fun cancelResumeRun(run: NativeGalleryResumeRun) = withOperation {
        if (resumeRun !== run) DeviceFileControl.fail("gallery_resume_run_not_current")
        run.cancel()
    }

    internal fun endStoppedResumeRun(run: NativeGalleryResumeRun) = withOperation {
        endStoppedResumeRunOwned(run)
    }

    private fun endStoppedResumeRunOwned(run: NativeGalleryResumeRun) {
        if (resumeRun !== run || !run.cancelRequested) DeviceFileControl.fail("gallery_resume_run_not_current")
        if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
        resumeRun = null // No cache/proof/quota cleanup or successful sync assertion.
    }

    private fun resumeSourceOwned(run: NativeGalleryResumeRun, allowSaved: Boolean = false): NativeGalleryRenewedSource {
        ready()
        if (resumeRun !== run || run.cancelRequested || syncRun != null) DeviceFileControl.fail("gallery_resume_run_not_current")
        if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
        if (!allowSaved && index.remoteSaved(run.originalJob) != null) DeviceFileControl.fail("gallery_resume_original_already_saved")
        val source = run.source()
        source.manifest // Recheck actual fresh native READ/peer/index ownership.
        return source
    }

    /** Native-only handoff. No incoming packet or persisted head creates a run. */
    internal fun sendResumeRunOffer(run: NativeGalleryResumeRun, send: (JsonObject) -> Unit,
        now: () -> Long = System::currentTimeMillis): Unit = withOperation {
        sendResumeRunOfferOwned(run, send, now)
        Unit
    }

    private fun sendResumeRunOfferOwned(run: NativeGalleryResumeRun, send: (JsonObject) -> Unit,
        now: () -> Long, checkCommand: () -> Unit = {}, wire: Pair<DeviceFileSourceCommand, JsonObject>? = null): NativeGalleryOfferOutput {
        val source = resumeSourceOwned(run)
        if (run.acceptance.get() != null) DeviceFileControl.fail("gallery_resume_acceptance_already_bound")
        val digest = wire?.let { DeviceFileControl.digest("magnolie-gallery-resume-offer-command-v1\u0000", it.second) }
        var held = run.wireOfferCommand.get()
        if (held != null && (wire == null || held.requestId != wire.first.requestId || held.commandSha256 != digest || held.message != wire.second))
            DeviceFileControl.fail("gallery_resume_offer_command_held")
        if (wire != null && held == null) {
            if (run.attempt.get() != null) DeviceFileControl.fail("gallery_resume_offer_command_held")
            checkCommand()
            held = NativeGalleryWireOfferAttempt(wire.first.requestId, digest!!, wire.second, now()).also { run.wireOfferCommand.set(it) }
        }
        fun currentWall(): Long {
            val at = now(); held?.checkCurrent(at)
            try { checkCommand() } catch (error: Exception) {
                try { held?.checkCurrent(now()) } catch (_: Exception) { }
                throw error
            }
            return at
        }
        val at = currentWall()
        val ttl = minOf(DeviceFileControl.MAX_TTL_MS, wire?.first?.expires?.minus(at) ?: DeviceFileControl.MAX_TTL_MS)
        if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
        val attempt = run.attempt.get() ?: NativeGalleryResumeAttempt.begin(source, at, ttlMs = ttl).also {
            // Keep this exact envelope even when preparation or output fails.
            run.attempt.set(it)
        }
        attempt.prepareStorage(index, ::currentWall)
        if (resumeSourceOwned(run) !== source) DeviceFileControl.fail("gallery_resume_original_changed")
        attempt.sendOffer({ message ->
            if (resumeSourceOwned(run) !== source) DeviceFileControl.fail("gallery_resume_original_changed")
            send(message)
            if (resumeSourceOwned(run) !== source) DeviceFileControl.fail("gallery_resume_original_changed")
        }, ::currentWall)
        if (resumeSourceOwned(run) !== source) DeviceFileControl.fail("gallery_resume_original_changed")
        currentWall()
        val manifest = source.manifest
        return NativeGalleryOfferOutput(attempt.offerId, manifest.transferId, manifest.fingerprint, attempt.offerExpires)
    }

    internal fun observeResumeRunAcceptance(run: NativeGalleryResumeRun, message: JsonObject,
        now: () -> Long = System::currentTimeMillis): NativeResumeAcceptanceProjection = withOperation {
        observeResumeRunAcceptanceOwned(run, message, now)
    }

    private fun observeResumeRunAcceptanceOwned(run: NativeGalleryResumeRun, message: JsonObject,
        now: () -> Long): NativeResumeAcceptanceProjection {
        val source = resumeSourceOwned(run)
        val attempt = run.attempt.get() ?: DeviceFileControl.fail("gallery_resume_offer_not_sent")
        fun acceptanceWall(): Long = now().also { run.wireOfferCommand.get()?.checkCurrent(it) }
        val projection = attempt.observeAcceptance(message, ::acceptanceWall)
        if (resumeSourceOwned(run) !== source || now() >= projection.validUntil)
            DeviceFileControl.fail("gallery_resume_run_not_current")
        val prior = run.acceptance.get()
        if (prior != null && prior !== projection) DeviceFileControl.fail("gallery_resume_acceptance_already_bound")
        run.acceptance.set(projection) // Durable accepted head precedes this projection.
        return projection // Still explicitly allows NO Chunk output.
    }

    /** Active native owner + exact durable accepted head, not a historical
     * projection's message lifetime, govern this data-run inspection. */
    private fun acceptedResumeSourceOwned(run: NativeGalleryResumeRun,
        projection: NativeResumeAcceptanceProjection, allowSaved: Boolean = false): NativeGalleryRenewedSource {
        val source = resumeSourceOwned(run, allowSaved)
        val attempt = run.attempt.get() ?: DeviceFileControl.fail("gallery_resume_offer_not_sent")
        if (run.acceptance.get() !== projection || projection.attemptId != attempt.id)
            DeviceFileControl.fail("gallery_resume_run_not_current")
        val durable = index.resumeAttempt(run.originalJob) ?: DeviceFileControl.fail("photo_jobs_resume_attempt_missing")
        if (durable.phase != "accepted" || durable.id != attempt.id || durable.record["acceptance"] != projection.message ||
            DeviceFileAcceptanceEnvelope.parse(projection.message, durable.record.long("accepted_at")) != projection.accepted ||
            source.manifest.fingerprint != projection.accepted.manifestSha256)
            DeviceFileControl.fail("gallery_resume_acceptance_changed")
        return source
    }

    /** Explicit native data API only. Normal packet routes never select a resume
     * run, and neither stored metadata nor a standalone projection can call this. */
    internal fun receiveResumeRunChunkRequest(run: NativeGalleryResumeRun, message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = System::currentTimeMillis): Unit = withOperation {
        receiveResumeRunChunkRequestOwned(run, message, send, now)
    }

    private fun receiveResumeRunChunkRequestOwned(run: NativeGalleryResumeRun, message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long) {
        val at = now()
        val request = DeviceFileChunkEnvelope.parseRequest(message, at)
        val projection = run.acceptance.get() ?: DeviceFileControl.fail("file_chunk_not_accepted")
        val source = acceptedResumeSourceOwned(run, projection)
        val accepted = projection.accepted
        if (request.transferId != accepted.transferId || request.manifestSha256 != accepted.manifestSha256 ||
            request.acceptanceSha256 != accepted.acceptanceSha256 || request.destinationToken != accepted.destinationToken ||
            request.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_chunk_acceptance_changed")
        val issued = DeviceFileControl.monotonicMs()
        val ttl = minOf(DeviceFileControl.MAX_TTL_MS, request.expires - at)
        if (issued < 0 || ttl <= 0 || issued > Long.MAX_VALUE - ttl) DeviceFileControl.fail("file_chunk_authority_changed")
        var lastWall = at; var lastElapsed = issued
        fun authority() {
            val wall = now(); val tick = DeviceFileControl.monotonicMs()
            if (wall < lastWall || wall >= request.expires || tick < lastElapsed || tick >= issued + ttl ||
                acceptedResumeSourceOwned(run, projection) !== source) DeviceFileControl.fail("file_chunk_authority_changed")
            lastWall = wall; lastElapsed = tick
        }
        authority()
        val data = source.readChunk(request.fileId, request.chunkIndex)
        try {
            authority()
            val response = DeviceFileChunkEnvelope.response(request, data, now())
            authority(); send(response); authority()
        } finally { data.fill(0) }
        // No Saved assertion, baseline, quota retirement or whole-run release.
    }

    /** Current native resume ownership validates the new observation; immutable
     * original acceptance remains the persisted historical proof's context. */
    internal fun observeResumeRunRemoteSaved(run: NativeGalleryResumeRun, message: JsonObject,
        now: () -> Long = System::currentTimeMillis): PhotoSourceRemoteSaved = withOperation {
        observeResumeRunRemoteSavedOwned(run, message, now)
    }

    private fun observeResumeRunRemoteSavedOwned(run: NativeGalleryResumeRun, message: JsonObject,
        now: () -> Long): PhotoSourceRemoteSaved {
        val projection = run.acceptance.get() ?: DeviceFileControl.fail("file_chunk_not_accepted")
        val source = acceptedResumeSourceOwned(run, projection, allowSaved = true)
        val confirmation = DeviceFileSavedEnvelope.parse(message, source.manifest, now())
        val accepted = projection.accepted
        if (confirmation.acceptanceSha256 != accepted.acceptanceSha256 || confirmation.permissionEpoch != accepted.permissionEpoch ||
            confirmation.destinationToken != accepted.destinationToken) DeviceFileControl.fail("file_saved_acceptance_changed")
        val prior = run.remoteSaved.get()
        if (prior != null && prior.fingerprint != confirmation.fingerprint) DeviceFileControl.fail("photo_jobs_remote_saved_changed")
        fun authority() {
            if (now() >= confirmation.expires || acceptedResumeSourceOwned(run, projection, allowSaved = true) !== source)
                DeviceFileControl.fail("file_saved_authority_changed")
        }
        authority()
        val durable = index.commitResumeRemoteSaved(source, projection, message, ::authority)
        authority()
        run.remoteSaved.set(prior ?: durable.confirmation)
        return durable // Not a local receipt, baseline, quota retirement or run END.
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
        if (selectionRequest(run.selection) == null || run.cancelRequested) DeviceFileControl.fail("gallery_source_not_activated")
        checkCommand()
        run.wireOfferAttempt.get()?.checkCurrent(now())
        send(offer)
        // Revalidate actual protected source authority after output as well.
        if (source.manifest.fingerprint != fingerprint || selectionRequest(run.selection) == null || run.cancelRequested)
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
        observeAcceptanceOwned(message, now)
    }

    private fun observeAcceptanceOwned(message: JsonObject, now: () -> Long) {
        val accepted = DeviceFileAcceptanceEnvelope.parse(message, now())
        val run = syncRun?.takeUnless { it.cancelRequested } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        val offer = run.offerOutput.get() ?: DeviceFileControl.fail("file_accept_offer_not_sent")
        run.wireOfferAttempt.get()?.let {
            it.checkCurrent(now())
            if (offer.messageId != it.message.string("message_id")) DeviceFileControl.fail("file_accept_offer_not_sent")
        }
        if (now() >= offer.expires || accepted.offerId != offer.messageId || accepted.transferId != offer.transferId ||
            accepted.manifestSha256 != offer.manifestSha256) DeviceFileControl.fail("file_accept_offer_changed")
        val request = selectionRequest(run.selection) ?: DeviceFileControl.fail("gallery_source_not_activated")
        if (request.receiver.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_accept_permission_changed")
        val prior = run.acceptance.get()
        if (prior != null && prior != accepted) DeviceFileControl.fail("file_accept_already_bound")
        // Actual protected source validation is independent of the remote token.
        val job = run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
        val selected = run.selection
        val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
        if (source.manifest.fingerprint != accepted.manifestSha256 || selectionRequest(run.selection)?.receiver?.permissionEpoch != accepted.permissionEpoch)
            DeviceFileControl.fail("file_accept_permission_changed")
        val checked = now()
        run.wireOfferAttempt.get()?.checkCurrent(checked)
        if (checked >= accepted.expires || checked >= offer.expires) DeviceFileControl.fail("file_accept_offer_changed")
        source.commitRemoteAcceptance(offer, accepted) {
            val current = now()
            run.wireOfferAttempt.get()?.checkCurrent(current)
            if (run.cancelRequested || current >= accepted.expires || current >= offer.expires ||
                selectionRequest(run.selection)?.receiver?.permissionEpoch != accepted.permissionEpoch)
                DeviceFileControl.fail("file_accept_permission_changed")
        }
        if (now() >= accepted.expires || now() >= offer.expires || run.cancelRequested ||
            selectionRequest(run.selection)?.receiver?.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_accept_permission_changed")
        run.acceptance.set(accepted)
    }

    internal fun cancelSyncRun(run: NativeGallerySyncRun) = withOperation {
        if (syncRun !== run) DeviceFileControl.fail("gallery_sync_run_not_current")
        run.stopped.set(true)
        run.preparation.cancel() // Cancellation does not release whole-run ownership.
    }

    internal fun receiveChunkRequest(message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = { System.currentTimeMillis() }): Unit = withOperation {
        receiveChunkRequestOwned(message, send, now)
    }

    private fun receiveChunkRequestOwned(message: JsonObject, send: (JsonObject) -> Unit, now: () -> Long) {
        val request=DeviceFileChunkEnvelope.parseRequest(message,now())
        val run=syncRun?.takeUnless { it.cancelRequested } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        val accepted=run.acceptance.get() ?: DeviceFileControl.fail("file_chunk_not_accepted")
        if (request.transferId != accepted.transferId || request.manifestSha256 != accepted.manifestSha256 ||
            request.acceptanceSha256 != accepted.acceptanceSha256 || request.destinationToken != accepted.destinationToken ||
            request.permissionEpoch != accepted.permissionEpoch) DeviceFileControl.fail("file_chunk_acceptance_changed")
        fun authority() {
            if (now() >= request.expires || run.cancelRequested || selectionRequest(run.selection)?.receiver?.permissionEpoch != accepted.permissionEpoch)
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
        observeRemoteSavedOwned(message, now)
    }

    private fun observeRemoteSavedOwned(message: JsonObject, now: () -> Long) {
        val run=syncRun?.takeUnless { it.cancelRequested } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
        val accepted=run.acceptance.get() ?: DeviceFileControl.fail("file_chunk_not_accepted")
        fun authority() {
            if (run.cancelRequested || selectionRequest(run.selection)?.receiver?.permissionEpoch != accepted.permissionEpoch)
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

    /** Dispatch only to an ALREADY owned native run. No packet/transfer ID or
     * historical head can create, restore or adopt a source/attempt here. */
    internal fun receiveTransferMessage(message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = System::currentTimeMillis): Unit = withOperation {
        val resumed = resumeRun
        if (resumed != null && syncRun != null) DeviceFileControl.fail("gallery_sync_run_busy")
        when (message["kind"]) {
            JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) -> if (resumed == null) observeAcceptanceOwned(message, now)
                else observeResumeRunAcceptanceOwned(resumed, message, now)
            JsonPrimitive(DeviceFileChunkEnvelope.REQUEST) -> if (resumed == null) receiveChunkRequestOwned(message, send, now)
                else receiveResumeRunChunkRequestOwned(resumed, message, send, now)
            JsonPrimitive(DeviceFileSavedEnvelope.KIND) -> if (resumed == null) observeRemoteSavedOwned(message, now)
                else observeResumeRunRemoteSavedOwned(resumed, message, now)
            else -> DeviceFileControl.fail("file_sources_unexpected_result")
        }
        Unit
    }

    /** Explicit native caller only; no automatic historical job selection. */
    internal fun historicalSourceJobs(): List<PhotoSourceJob> = withOperation { index.jobs() }

    internal fun issueHistoricalSavedAction(expected: PhotoSourceJob): NativeHistoricalSavedAction = withOperation {
        if (syncRun != null || resumeRun != null || !sourceWorker.isQuiescent) DeviceFileControl.fail("gallery_sync_run_held")
        // Exact original-job Saved metadata is not an image READ job. A valid
        // VIDEO-only receiver must not need to opt into images to confirm it.
        index.issueHistoricalSavedAction(expected, {
            workflow.currentRequest(GalleryMediaType.IMAGES)?.receiver ?: workflow.currentRequest(GalleryMediaType.VIDEO)?.receiver
        })
    }

    internal fun recoverHistoricalSaved(action: NativeHistoricalSavedAction, message: JsonObject,
        now: () -> Long = { System.currentTimeMillis() }): PhotoSourceRemoteSaved = withOperation {
        if (syncRun != null || resumeRun != null || !sourceWorker.isQuiescent) DeviceFileControl.fail("gallery_sync_run_held")
        index.commitHistoricalRemoteSaved(action, message, now)
    }

    /** Only an explicitly stopped run can end here. This neither reports sync
     * success nor retires source quota; data/publication receipts remain separate. */
    internal fun endStoppedSyncRun(run: NativeGallerySyncRun) = withOperation {
        endStoppedSyncRunOwned(run)
    }

    private fun endStoppedSyncRunOwned(run: NativeGallerySyncRun) {
        if (syncRun !== run || !run.cancelRequested) DeviceFileControl.fail("gallery_sync_run_not_current")
        if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
        syncRun = null
        albumBatchOwner?.takeIf { it.run === run && it.prepared.get()?.reachedCurrentEnd == true }?.let {
            it.scan.close(); albumBatchOwner = null
        }
    }
    fun attachPermissionHost(host: GalleryPhotoPermissionHost, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        ready(); workflow.attachPermissionHost(host, onResult)
    }
    fun requestReadPermission(mediaType: GalleryMediaType = GalleryMediaType.IMAGES) { ready(); workflow.requestReadPermission(mediaType) }
    // Epoch rotation only: no runtime/session I/O lock or READ creation. Safe
    // from native lifecycle notifications while Werk owns its monitor.
    internal fun nativeReadAccessChanged() { workflow.nativeReadAccessChanged() }
    fun attachForeground(onResult: (Result<GalleryReadCoverage>) -> Unit): NativeGalleryForegroundOwner {
        return attachForeground(GalleryMediaType.IMAGES, onResult)
    }
    fun attachForeground(mediaType: GalleryMediaType, onResult: (Result<GalleryReadCoverage>) -> Unit): NativeGalleryForegroundOwner {
        ready(); return NativeGalleryForeground.attach(this, onResult, mediaType)
    }

    /** Guarded source commands. Status/configuration work while initial send is
     * OFF; discovery needs current send authority, and request_read reaches only
     * the explicitly queued native UI path. No transfer/publication is scheduled.
     * Replies are metadata, never SaveACKs or OS READ grants.
     */
    fun receiveSourceCommand(message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = { System.currentTimeMillis() }, permissionCommands: NativeGalleryPermissionCommands = localPermissionCommands,
        runCommands: NativeGalleryRunCommands = localRunCommands,
        resumeCommands: NativeGalleryResumeCommands = localResumeCommands): Unit = withOperation {
        ready()
        val command = DeviceFileSourceCommand.parse(message, now())
        // Revoked video READ must not prevent exact-owner cancellation/status/END.
        // These paths still need current base configuration authority and match
        // the native media owner before any mutation below.
        val closing = command.operation in setOf("run_status", "cancel_run", "end_run", "end_album", "resume_status", "cancel_resume", "end_resume")
        if (command.mediaType == GalleryMediaType.VIDEO && !closing && !videoAvailable())
            DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
        if (command.operation == "configure_videos" && command.enabled == true && !videoAvailable())
            DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
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
            if ((command.mediaType == GalleryMediaType.VIDEO && !closing || command.operation == "configure_videos" && command.enabled == true) && !videoAvailable())
                DeviceFileControl.fail("gallery_video_handlers_unavailable")
            return controls.session.configurationAuthority(issued) ?: DeviceFileControl.fail("file_sources_authority_changed")
        }
        fun requireMedia(selection: NativeGalleryAlbumSelection) {
            if (selection.catalog.source.activation?.mediaType != command.mediaType)
                DeviceFileControl.fail("gallery_source_media_scope_changed")
        }
        fun replyBody(block: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit): JsonObject = kotlinx.serialization.json.buildJsonObject {
            block()
            if (command.mediaType == GalleryMediaType.VIDEO) put("media_type", JsonPrimitive("video"))
        }
        try {
            val owner = authority()
            val before = workflow.savedPolicy()
            if (command.operation != "status" && before.version != command.expectedVersion) DeviceFileControl.fail("gallery_policy_cas_conflict")
            if (command.operation == "configure_videos" && (syncRun != null || resumeRun != null || albumBatchOwner != null || !sourceWorker.isQuiescent))
                DeviceFileControl.fail("gallery_sync_run_busy")
            if (command.operation == "end_album") {
                val prior = albumEnd
                val output = if (prior != null && prior.first.requestId == command.requestId) {
                    if (prior.first.message != message) DeviceFileControl.fail("gallery_sync_end_command_changed")
                    prior
                } else {
                    val batch = albumBatchOwner ?: DeviceFileControl.fail("gallery_album_batch_not_current")
                    requireMedia(batch.selection)
                    val run = batch.run ?: DeviceFileControl.fail("gallery_album_batch_not_current")
                    val endedId = normalEnd?.second?.get("body")?.let { it as? JsonObject }?.get("run_id")
                    if (run.id != command.runId || syncRun != null || resumeRun != null || !sourceWorker.isQuiescent ||
                        !run.cancelRequested || !run.preparation.ioEnded || endedId != JsonPrimitive(run.id))
                        DeviceFileControl.fail("gallery_album_batch_not_current")
                    val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                    if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                    val guard = NativeGalleryWireOfferAttempt(command.requestId,
                        DeviceFileControl.digest("magnolie-gallery-album-end-v1\u0000", message), message, at)
                    val body = replyBody {
                        put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                        put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                        put("state", JsonPrimitive("canceled_held")); put("source_io_ended", JsonPrimitive(true)); put("run_ended", JsonPrimitive(true))
                    }
                    guard.checkCurrent(now()); authority()
                    batch.scan.close(); albumBatchOwner = null // No cache deletion, Saved or full-album success.
                    (guard to TelefonNachrichten.message(DeviceFileSourceCommand.RUN_RESULT, body, ttl, at)).also { albumEnd = it }
                }
                output.first.checkCurrent(now()); authority(); send(output.second)
                output.first.checkCurrent(now()); authority()
                return@withOperation
            }
            if (command.operation == "end_run") {
                val prior = normalEnd
                val output = if (prior != null && prior.first.requestId == command.requestId) {
                    if (prior.first.message != message) DeviceFileControl.fail("gallery_sync_end_command_changed")
                    prior
                } else {
                    val run = syncRun?.takeIf { it.id == command.runId && it.cancelRequested }
                        ?: DeviceFileControl.fail("gallery_sync_run_not_current")
                    requireMedia(run.selection)
                    if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
                    val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                    if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                    val guard = NativeGalleryWireOfferAttempt(command.requestId,
                        DeviceFileControl.digest("magnolie-gallery-normal-end-v1\u0000", message), message, at)
                    fun current() { guard.checkCurrent(now()); authority() }
                    current()
                    val job = run.preparation.completedNativeJob()
                    if (job != null && ((index.remoteAcceptance(job) == null && index.resumeAttempt(job) == null) || index.remoteSaved(job) != null)) {
                        // This exact stopped native cache is either never accepted
                        // or completely confirmed Saved by the authenticated receiver.
                        // Original phone media is never touched.
                        current(); workflow.retireCached(job); current()
                    }
                    val body = replyBody {
                        put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                        put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                        put("state", JsonPrimitive("canceled_held")); put("source_io_ended", JsonPrimitive(true)); put("run_ended", JsonPrimitive(true))
                    }
                    val reply = TelefonNachrichten.message(DeviceFileSourceCommand.RUN_RESULT, body, ttl, at)
                    current(); endStoppedSyncRunOwned(run)
                    (guard to reply).also { normalEnd = it }
                }
                fun current() { output.first.checkCurrent(now()); authority() }
                try { current(); send(output.second); current() } catch (error: Exception) {
                    try { current() } catch (_: Exception) { }
                    throw error
                }
                return@withOperation // Not Saved or permission to delete a phone image.
            }
            if (command.operation == "end_resume") {
                val prior = resumeEnd
                val output = if (prior != null && prior.command.string("message_id") == command.requestId) {
                    if (prior.command != message) DeviceFileControl.fail("gallery_resume_end_command_changed")
                    prior
                } else {
                    val run = resumeRun?.takeIf { it.id == command.runId } ?: DeviceFileControl.fail("gallery_resume_run_not_current")
                    requireMedia(run.selection)
                    if (!run.cancelRequested) DeviceFileControl.fail("gallery_resume_run_not_current")
                    if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
                    val body = replyBody {
                        put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                        put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                        put("state", JsonPrimitive("canceled_held")); put("source_io_ended", JsonPrimitive(true)); put("run_ended", JsonPrimitive(true))
                    }
                    val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                    if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                    val head = index.resumeAttempt(run.originalJob)
                    val prepared = ResumeEndOutput(message, TelefonNachrichten.message(DeviceFileSourceCommand.RUN_RESULT, body, ttl, at), at,
                        run.originalJob, head?.id, head?.version)
                    prepared.check(now()); authority()
                    if (index.remoteSaved(run.originalJob) != null) {
                        // Only the exact original's authenticated Saved proof,
                        // after actual quiescent source END, permits cache retirement.
                        // An END or a historical hint alone never frees quota.
                        workflow.retireCached(run.originalJob)
                        prepared.check(now()); authority()
                    }
                    resumeEnd = prepared // Exact bounded result survives uncertain output.
                    endStoppedResumeRunOwned(run)
                    prepared
                }
                fun endAuthority() { output.check(now()); authority() }
                try { endAuthority(); send(output.reply); endAuthority() } catch (error: Exception) {
                    try { endAuthority() } catch (_: Exception) { }
                    throw error
                }
                return@withOperation // No Saved assertion or original phone-media deletion.
            }
            if (command.operation == "abandon_resume") {
                val ended = resumeEnd ?: DeviceFileControl.fail("gallery_resume_end_proof_required")
                if (DeviceFileSourceCommand.parse(ended.command, ended.command.long("created_ms")).mediaType != command.mediaType)
                    DeviceFileControl.fail("gallery_source_media_scope_changed")
                fun abandonmentAuthority() {
                    authority()
                    if (syncRun != null || resumeRun != null || !sourceWorker.isQuiescent)
                        DeviceFileControl.fail("gallery_sync_run_held")
                    if (ended.job.id != command.originalJobId || ended.job.version != command.originalJobVersion ||
                        ended.command["body"]?.let { (it as? JsonObject)?.get("run_id") } != JsonPrimitive(command.runId) ||
                        ended.headId != command.attemptId || ended.headSha256 != command.attemptSha256)
                        DeviceFileControl.fail("gallery_resume_end_proof_changed")
                    val request = workflow.currentRequest(command.mediaType) ?: DeviceFileControl.fail("gallery_source_not_activated")
                    val manifest = DeviceFileManifest.parse(ended.job.snapshot!!["manifest"] as JsonObject)
                    index.lookupGalleryResume(localIdentity.deviceId, manifest.sourceId, manifest.transferId, manifest.fingerprint,
                        request.receiver, request.policyEpoch)
                }
                // The abandonment command gets its own exact bounded clock;
                // an old offer/END lifetime is never rewritten or reused.
                val held = ended.abandonmentCommand
                if (held != null && held.message != message) DeviceFileControl.fail("gallery_resume_abandon_command_changed")
                abandonmentAuthority()
                val clock = held ?: NativeGalleryWireOfferAttempt(command.requestId,
                    DeviceFileControl.digest("magnolie-gallery-resume-abandon-command-v1\u0000", message), message, now())
                    .also { ended.abandonmentCommand = it }
                fun permitted() { clock.checkCurrent(now()); abandonmentAuthority() }
                permitted()
                val receipt = index.abandonResumeAttempt(ended.job, message, now(), ::permitted)
                permitted()
                val body = replyBody {
                    put("format", JsonPrimitive(1)); put("operation", JsonPrimitive(command.operation)); put("request_id", JsonPrimitive(command.requestId))
                    put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(command.runId))
                    put("job_id", JsonPrimitive(ended.job.id)); put("job_version", JsonPrimitive(ended.job.version))
                    put("attempt_id", JsonPrimitive(command.attemptId)); put("attempt_sha256", JsonPrimitive(command.attemptSha256))
                    put("receipt_sha256", JsonPrimitive(receipt.version))
                }
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                try {
                    permitted(); send(TelefonNachrichten.message("file_transfer.sources.abandoned", body, ttl, at)); permitted()
                } catch (error: Exception) {
                    try { permitted() } catch (_: Exception) { }
                    throw error
                }
                return@withOperation
            }
            if (command.operation == "resume_lookup") {
                val request = workflow.currentRequest(command.mediaType) ?: DeviceFileControl.fail("gallery_source_not_activated")
                val history = index.lookupGalleryResume(localIdentity.deviceId, command.lookupSourceId!!, command.lookupTransferId!!, command.lookupManifestSha256!!,
                    request.receiver, request.policyEpoch)
                authority()
                val body = replyBody {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("history", history)
                }
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                authority(); send(TelefonNachrichten.message(DeviceFileSourceCommand.RESUME, body, ttl, at)); authority()
                return@withOperation // Historical metadata only, not readiness or a native owner.
            }
            if (command.operation in setOf("resume_run", "resume_status", "cancel_resume", "offer_resume")) {
                val run = if (command.operation == "resume_run") {
                    if (owner.pairingEpoch == null) DeviceFileControl.fail("gallery_source_not_activated")
                    val scope = DeviceFileControl.digest("magnolie-gallery-resume-native-scope-v1\u0000", kotlinx.serialization.json.JsonArray(listOf(
                        JsonPrimitive(localIdentity.deviceId), JsonPrimitive(localIdentity.identitySha256), JsonPrimitive(owner.peerId),
                        JsonPrimitive(owner.identitySha256), JsonPrimitive(owner.pairingEpoch))))
                    resumeCommands.start(scope, this, command, message) {
                        authority()
                        val original = index.jobs().singleOrNull { it.id == command.originalJobId && it.version == command.originalJobVersion }
                            ?: DeviceFileControl.fail("photo_jobs_historical_original_job_required")
                        if (index.remoteSaved(original) != null) DeviceFileControl.fail("gallery_resume_original_already_saved")
                        val catalog = wireCatalog(command.mediaType).get() ?: DeviceFileControl.fail("gallery_catalog_not_current")
                        val selection = catalog.select(command.catalogId!!, command.albumId!!, command.desktopChoice!!)
                        requireMedia(selection)
                        beginResumeRunOwned(selection, original) { authority(); Unit }
                    }
                } else resumeRun?.takeIf { it.id == command.runId } ?: DeviceFileControl.fail("gallery_resume_run_not_current")
                if (resumeRun !== run) DeviceFileControl.fail("gallery_resume_run_not_current")
                requireMedia(run.selection)
                authority()
                if (command.operation == "cancel_resume") run.cancel()
                val offered = if (command.operation == "offer_resume") sendResumeRunOfferOwned(run, send, now,
                    { authority(); Unit }, command to message) else null
                val ended = run.preparation.ioEnded
                val state = if (run.cancelRequested && !ended) "cancel_pending"
                    else if (run.cancelRequested) "canceled_held" else if (ended) run.preparation.phase else "preparing"
                val body = replyBody {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                    put("state", JsonPrimitive(state)); put("source_io_ended", JsonPrimitive(ended))
                    if (offered != null) {
                        put("offer_id", JsonPrimitive(offered.messageId)); put("manifest_sha256", JsonPrimitive(offered.manifestSha256))
                    }
                }
                val at = now(); val deadline = minOf(command.expires, offered?.expires ?: command.expires)
                val ttl = minOf(DeviceFileControl.MAX_TTL_MS, deadline - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                try {
                    authority(); send(TelefonNachrichten.message(DeviceFileSourceCommand.RUN_RESULT, body, ttl, at)); authority()
                    run.wireOfferCommand.get()?.takeIf { command.operation == "offer_resume" }?.checkCurrent(now())
                } catch (error: Exception) {
                    // Observe clock expiry/rollback even if authority or reply
                    // output also failed. A transport error alone keeps retry.
                    if (command.operation == "offer_resume") try { run.wireOfferCommand.get()?.checkCurrent(now()) } catch (_: Exception) { }
                    throw error
                }
                return@withOperation
            }
            if (command.operation == "resume_media_page") {
                val run = resumeRun?.takeIf { it.id == command.runId } ?: DeviceFileControl.fail("gallery_resume_run_not_current")
                requireMedia(run.selection)
                val source = resumeSourceOwned(run)
                fun mediaAuthority() {
                    run.mediaAttempts.check(command, message, now()); authority()
                    if (resumeSourceOwned(run) !== source) DeviceFileControl.fail("gallery_resume_original_changed")
                }
                mediaAuthority()
                val page = source.mediaPage(command.after, ::mediaAuthority)
                val body = replyBody {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId))
                    put("operation", JsonPrimitive(command.operation)); put("version", JsonPrimitive(before.version))
                    put("run_id", JsonPrimitive(run.id)); put("page", page)
                }
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                val reply = TelefonNachrichten.message(DeviceFileSourceCommand.MEDIA, body, ttl, at)
                if (TelefonKanonisch.bytes(reply).size > DeviceFileControl.MAX_WIRE_BYTES) DeviceFileControl.fail("gallery_media_page_budget")
                try { mediaAuthority(); send(reply); mediaAuthority() } catch (error: Exception) {
                    try { mediaAuthority() } catch (_: Exception) { }
                    throw error
                }
                return@withOperation
            }
            if (command.operation == "media_page") {
                val run = syncRun?.takeIf { it.id == command.runId && !it.cancelRequested }
                    ?: DeviceFileControl.fail("gallery_sync_run_not_current")
                requireMedia(run.selection)
                fun mediaAuthority() { authority(); run.mediaAttempts.check(command, message, now()) }
                mediaAuthority()
                if (!sourceWorker.isQuiescent || !run.preparation.ioEnded) DeviceFileControl.fail("gallery_source_worker_io_pending")
                val job = run.preparation.snapshotJob() ?: DeviceFileControl.fail("gallery_sync_run_snapshot_unavailable")
                val selected = run.selection
                val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
                val page = source.mediaPage(command.after, ::mediaAuthority)
                mediaAuthority()
                val body = replyBody {
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
            if (command.operation in setOf("run", "batch_run", "next_batch", "run_status", "cancel_run", "offer_run", "select_run")) {
                val run = if (command.operation in setOf("run", "batch_run", "next_batch", "select_run")) {
                    if (owner.pairingEpoch == null) DeviceFileControl.fail("gallery_source_not_activated")
                    val scope = DeviceFileControl.digest("magnolie-gallery-run-native-scope-v1\u0000", kotlinx.serialization.json.JsonArray(listOf(
                        JsonPrimitive(localIdentity.deviceId), JsonPrimitive(localIdentity.identitySha256), JsonPrimitive(owner.peerId),
                        JsonPrimitive(owner.identitySha256), JsonPrimitive(owner.pairingEpoch))))
                    runCommands.start(scope, this, command, message) {
                        authority()
                        if (command.operation == "select_run") {
                            requireMedia(syncRun?.selection ?: DeviceFileControl.fail("gallery_sync_run_not_current"))
                            return@start selectSyncRunOwned(command) { authority(); Unit }
                        }
                        if (command.operation == "next_batch") {
                            requireMedia(albumBatchOwner?.selection ?: DeviceFileControl.fail("gallery_album_batch_not_current"))
                            return@start nextAlbumBatchOwned(command) { authority(); Unit }
                        }
                        val catalog = wireCatalog(command.mediaType).get() ?: DeviceFileControl.fail("gallery_catalog_not_current")
                        val selection = catalog.select(command.catalogId!!, command.albumId!!, command.desktopChoice!!)
                        requireMedia(selection)
                        if (command.operation == "batch_run") return@start beginAlbumBatchOwned(selection) { authority(); Unit }
                        beginSyncRunOwned(selection) { authority(); Unit }
                    }
                } else syncRun?.takeIf { it.id == command.runId } ?: DeviceFileControl.fail("gallery_sync_run_not_current")
                if (syncRun !== run) DeviceFileControl.fail("gallery_sync_run_not_current")
                requireMedia(run.selection)
                if (command.operation == "cancel_run") {
                    run.stopped.set(true); run.preparation.cancel()
                }
                val output = if (command.operation == "offer_run") sendSyncRunOfferOwned(run, send, now,
                    { authority(); Unit }, command to message) else null
                authority()
                val ioEnded = run.preparation.ioEnded
                val state = if (run.cancelRequested && !ioEnded) "cancel_pending"
                    else if (run.cancelRequested) "canceled_held" else if (ioEnded) run.preparation.phase else "preparing"
                val body = replyBody {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("run_id", JsonPrimitive(run.id))
                    put("state", JsonPrimitive(state)); put("source_io_ended", JsonPrimitive(ioEnded))
                    albumBatchOwner?.takeIf { it.run === run }?.let { batch ->
                        put("batch_end", batch.prepared.get()?.let { JsonPrimitive(it.reachedCurrentEnd) } ?: kotlinx.serialization.json.JsonNull)
                    }
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
                if (workflow.currentRequest(command.mediaType) == null || owner.pairingEpoch == null) DeviceFileControl.fail("gallery_source_not_activated")
                val scope = DeviceFileControl.digest("magnolie-gallery-permission-native-scope-v1\u0000", kotlinx.serialization.json.JsonArray(listOf(
                    JsonPrimitive(localIdentity.deviceId), JsonPrimitive(localIdentity.identitySha256), JsonPrimitive(owner.peerId),
                    JsonPrimitive(owner.identitySha256), JsonPrimitive(owner.pairingEpoch))))
                val state = permissionCommands.execute(scope, command, message) {
                    authority()
                    val foreground = attachForeground(command.mediaType) { }
                    val action = NativeGalleryForeground.permissionAction(foreground)
                    try {
                        authority()
                        NativeGalleryForeground.performPermissionAction(action.token)
                        "requested"
                    } catch (error: PhotoFolderScopeError) {
                        if (error.code !in NativeGalleryPermissionActions.RETRYABLE) throw error
                        if (error.code == "gallery_permission_request_pending") {
                            if (workflow.permissionRequestPending(command.mediaType)) "requested" else "foreground_required"
                        }
                        else {
                            authority()
                            if (NativeGalleryForeground.postPermissionAction(app, action)) "notification_posted" else "foreground_required"
                        }
                    }
                }
                authority()
                val at = now(); val ttl = minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at)
                if (ttl <= 0) DeviceFileControl.fail("file_sources_command_expired")
                val body = replyBody {
                    put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId)); put("operation", JsonPrimitive(command.operation))
                    put("version", JsonPrimitive(before.version)); put("state", JsonPrimitive(state))
                }
                send(TelefonNachrichten.message(DeviceFileSourceCommand.PERMISSION_RESULT, body, ttl, at))
                authority()
                return@withOperation
            }
            if (command.operation in setOf("discover", "catalog_page")) {
                if (workflow.currentRequest(command.mediaType) == null) DeviceFileControl.fail("gallery_source_not_activated")
                val selectedCatalog = wireCatalog(command.mediaType)
                val catalog = if (command.operation == "discover") {
                    selectedCatalog.getAndSet(null)?.close()
                    workflow.discoverSelectable(mediaType = command.mediaType).also { selectedCatalog.set(it) }
                } else selectedCatalog.get() ?: DeviceFileControl.fail("gallery_catalog_not_current")
                val page = catalog.page(command.catalogId, command.after)
                authority()
                val body = replyBody {
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
            } else if (command.operation == "configure_videos") {
                authority()
                workflow.configureVideos(before, command.enabled!!)
            } else before
            authority()
            val policy = saved.policy
            val associated = policy != null && policy.receiverId == owner.peerId && policy.receiverIdentitySha256 == owner.identitySha256 &&
                policy.pairingEpoch == owner.pairingEpoch
            val body = replyBody {
                put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId))
                put("operation", JsonPrimitive(command.operation)); put("version", JsonPrimitive(saved.version))
                put("revision", JsonPrimitive(policy?.revision ?: 0)); put("enabled", JsonPrimitive(policy?.enabled ?: false))
                put("associated", JsonPrimitive(associated)); put("repair_pending", JsonPrimitive(saved.repairPending))
                put("kinds", kotlinx.serialization.json.JsonArray((policy?.kinds ?: emptySet()).map { it.name.lowercase(java.util.Locale.ROOT) }
                    .sorted().map(::JsonPrimitive)))
                if (videoAvailable()) put("videos", kotlinx.serialization.json.buildJsonObject {
                    put("enabled", JsonPrimitive(policy?.videos?.enabled ?: false))
                    put("revision", JsonPrimitive(policy?.videos?.revision ?: 0L))
                })
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
        if (command.mediaType == GalleryMediaType.VIDEO && !videoAvailable()) DeviceFileControl.fail("gallery_video_wire_handlers_unavailable")
        if ((reply["body"] as? JsonObject)?.get("media_type") !=
            (if (command.mediaType == GalleryMediaType.VIDEO) JsonPrimitive("video") else null))
            DeviceFileControl.fail("file_sources_invalid_command")
        val issued = controls.session.configurationTicket()
        fun checkAuthority() {
            if (now() >= command.expires) DeviceFileControl.fail("file_sources_command_expired")
            if (controls.session.configurationAuthority(issued) == null || workflow.currentRequest(command.mediaType) == null)
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

    fun disableLocally(expected: GalleryPhotoPolicySnapshot): GalleryPhotoPolicySnapshot = withOperation(allowIncoming = true) {
        incomingWorker.current?.cancel()
        publishedReadWorker.current?.cancel()
        workflow.disableLocally(expected)
    }

    internal fun configureVideosFromAuthenticatedCommand(expected: GalleryPhotoPolicySnapshot, enabled: Boolean): GalleryPhotoPolicySnapshot = withOperation {
        if (syncRun != null || resumeRun != null || albumBatchOwner != null || !sourceWorker.isQuiescent)
            DeviceFileControl.fail("gallery_sync_run_busy")
        val issued = controls.session.configurationTicket()
        if (!ticket.compareAndSet(null, issued)) {
            controls.session.finishConfiguration(issued)
            DeviceFileControl.fail("file_control_configuration_busy")
        }
        try { workflow.configureVideos(expected, enabled) }
        finally { ticket.compareAndSet(issued, null); controls.session.finishConfiguration(issued) }
    }

    /** Native channel-end path can revoke file authority synchronously on any
     * thread. Metadata/permission-host ownership remains held until actual UI
     * cleanup; this is not a worker-END or quota-retirement receipt.
     */
    fun revokeControl() {
        revoked.set(true)
        controls.close()
        incomingWorker.close()
        publishedReadWorker.close()
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
            if (operationActive || !sourceWorker.isQuiescent || !incomingWorker.isQuiescent || !publishedReadWorker.isQuiescent) {
                closeCompletion = completed
                return false // Source index and native owner remain held until actual I/O end.
            }
            if (!closed.compareAndSet(false, true)) return true
            closeCompletion = null
            ticket.set(null)
            receiveTicket.set(null); receiveConfiguration.set(null)
            wireCatalog.getAndSet(null)?.close()
            videoWireCatalog.getAndSet(null)?.close()
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
            if (operationActive || !sourceWorker.isQuiescent || !incomingWorker.isQuiescent || !publishedReadWorker.isQuiescent) null
            else closeCompletion.also { closeCompletion = null }
        }
        completion?.let { android.os.Handler(Looper.getMainLooper()).post { it() } }
    }

    private inline fun <T> withOperation(allowIncoming: Boolean = false, operation: () -> T): T {
        if (!operationGate.tryLock()) DeviceFileControl.fail("file_control_configuration_busy")
        var owned = false
        try {
            synchronized(this) {
                ready()
                if (revoked.get()) DeviceFileControl.fail("gallery_file_runtime_revoked")
                if (operationActive) DeviceFileControl.fail("file_control_configuration_busy")
                if (!allowIncoming && !incomingWorker.isQuiescent) DeviceFileControl.fail("gallery_incoming_worker_busy")
                if (!allowIncoming && !publishedReadWorker.isQuiescent) DeviceFileControl.fail("gallery_published_worker_busy")
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
