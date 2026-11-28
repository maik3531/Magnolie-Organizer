package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Build
import android.os.Looper
import kotlinx.serialization.json.*
import java.util.concurrent.atomic.AtomicBoolean

/** Fresh local read-only ownership of protected already-published rows.
 * Never an incoming write owner, historical Saved ACK or transfer-resume grant.
 * A new control binding may inspect the same static pair, not reuse old rights.
 * Private native primitive only; production UI/dispatcher remains unjoined. */
internal class NativeGalleryPublishedInspection private constructor(private val session: NativeFileControlSession,
    private val index: PhotoSourceJobIndex, private val book: NativeGalleryReceiveBookPermit,
    private val peer: () -> NativeFileControlPeer?, private val incomingIntent: () -> Any?,
    internal val selected: GalleryIncomingPublication, expectedControl: NativeFileOperationBinding?,
    private val archiveAction: NativeGalleryPcArchiveAction?,
    internal val publications: Map<String, GalleryIncomingPublication> =
        mapOf(selected.body.getValue("origin").jsonObject.string("file_id") to selected)) : AutoCloseable {
    internal val kind = GalleryMediaType.entries.single { it.uriSegment == selected.body.string("media_type") }
    private val token = incomingIntent() as? MediaSyncTransport.IntentToken ?: fail()
    private val originalPeer = peer()?.takeIf { it.allowed && it.pairingEpoch != null } ?: fail()
    private val origin = selected.body.getValue("origin").jsonObject
    internal val manifestSha256 = origin.string("manifest_sha256")
    private val originalControl = session.operationBinding(manifestSha256) ?: fail()
    private val binding = originalControl.binding
    private val identityFields = setOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256")
    private val identity = binding.snapshot().filterKeys { it in identityFields }
    private val policy = index.galleryPolicy()
    internal val issuedMs = DeviceFileControl.monotonicMs()
    private var last = issuedMs
    private val closed = AtomicBoolean(false)
    private val used = AtomicBoolean(false)
    internal val grantsWriteAuthority: Boolean get() = false
    internal val isSavedReceipt: Boolean get() = false

    init {
        if (archiveAction != null && archiveAction.kind != kind) fail()
        if (expectedControl != null && originalControl != expectedControl) fail()
        requireCurrent()
    }
    @Synchronized internal fun requireCurrent() {
        try {
            archiveAction?.requireCurrent()
            val now = DeviceFileControl.monotonicMs()
            if (closed.get() || now < last || now - issuedMs >= DeviceFileControl.MAX_TTL_MS || incomingIntent() !== token ||
                !token.requestedIncoming(kind)) fail()
            book.requireCurrent()
            val current = peer() ?: fail()
            if (current != originalPeer || current.owner !== originalPeer.owner || !current.allowed || kind == GalleryMediaType.VIDEO && !current.videoSupported ||
                session.operationBinding(manifestSha256) != originalControl || index.galleryPolicy() != policy || policy.repairPending ||
                policy.policy?.let { it.receiverId == current.peerId && it.receiverIdentitySha256 == current.identitySha256 &&
                    it.pairingEpoch == current.pairingEpoch && it.receiving?.enabled(kind) == true } != true ||
                binding.senderId != current.peerId || binding.senderIdentitySha256 != current.identitySha256 ||
                publications.any { (id, publication) ->
                    val memberOrigin = publication.body.getValue("origin").jsonObject
                    publication.state != "published" || publication.row == null ||
                        publication.body.string("media_type") != kind.uriSegment || memberOrigin.string("file_id") != id ||
                        memberOrigin.string("manifest_sha256") != manifestSha256 ||
                        memberOrigin.getValue("binding").jsonObject.filterKeys { it in identityFields } != identity ||
                        index.incomingPublication(publication.id)?.body != publication.body
                }) fail()
            last = now
        } catch (error: Exception) { closed.set(true); archiveAction?.close(); throw error }
    }

    internal fun consume() {
        requireCurrent()
        if (!used.compareAndSet(false, true)) fail()
    }
    internal fun requireIndex(actual: PhotoSourceJobIndex) {
        if (actual !== index) { close(); fail() }
        requireCurrent()
    }
    internal fun requireArchiveBook(permit: NativeGalleryTrashBookPermit) {
        requireCurrent(); book.requireArchiveBook(permit); permit.requireTrashEnabled()
    }
    internal fun requireChannel(channel: TelefonSecureChannel) {
        requireCurrent()
        if (originalPeer.owner !== channel) { close(); fail() }
    }
    internal fun bindingForReadback(destinationToken: String): DeviceTransferBinding {
        requireCurrent()
        val current = session.operationBinding(destinationToken) ?: fail()
        if (current.session != originalControl.session || current.binding.permissionEpoch != binding.permissionEpoch) { close(); fail() }
        requireCurrent(); return current.binding
    }
    override fun close() { closed.set(true); archiveAction?.close() }
    companion object {
        internal fun capture(session: NativeFileControlSession, index: PhotoSourceJobIndex, book: NativeGalleryReceiveBookPermit,
            peer: () -> NativeFileControlPeer?, incomingIntent: () -> Any?, selected: GalleryIncomingPublication,
            expectedControl: NativeFileOperationBinding? = null,
            archiveAction: NativeGalleryPcArchiveAction? = null): NativeGalleryPublishedInspection {
            if (Build.VERSION.SDK_INT < 30 || Looper.myLooper() == Looper.getMainLooper()) fail()
            return try { NativeGalleryPublishedInspection(session, index, book, peer, incomingIntent, selected, expectedControl, archiveAction) }
            catch (error: Throwable) { archiveAction?.close(); throw error }
        }
        internal fun captureBatch(session: NativeFileControlSession, index: PhotoSourceJobIndex, book: NativeGalleryReceiveBookPermit,
            peer: () -> NativeFileControlPeer?, incomingIntent: () -> Any?, publications: Map<String, GalleryIncomingPublication>,
            expectedControl: NativeFileOperationBinding): NativeGalleryPublishedInspection {
            if (Build.VERSION.SDK_INT < 30 || Looper.myLooper() == Looper.getMainLooper() ||
                publications.size !in 1..DeviceFileManifest.MAX_FILES ||
                publications.values.map { it.id }.toSet().size != publications.size ||
                publications.values.map { it.row?.string("uri") }.toSet().size != publications.size) fail()
            return NativeGalleryPublishedInspection(session, index, book, peer, incomingIntent,
                publications.values.first(), expectedControl, null, publications.toMap())
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_published_current_read_owner_required")
    }
}
