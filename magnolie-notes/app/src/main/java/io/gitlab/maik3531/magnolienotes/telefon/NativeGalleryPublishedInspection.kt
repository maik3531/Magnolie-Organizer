package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Build
import android.os.Looper
import kotlinx.serialization.json.*
import java.util.concurrent.atomic.AtomicBoolean

/** Fresh local read-only ownership of ONE protected already-published row.
 * Never an incoming write owner, historical Saved ACK or transfer-resume grant.
 * A new control binding may inspect the same static pair, not reuse old rights.
 * Private native primitive only; production UI/dispatcher remains unjoined. */
internal class NativeGalleryPublishedInspection private constructor(private val session: NativeFileControlSession,
    private val index: PhotoSourceJobIndex, private val book: NativeGalleryReceiveBookPermit,
    private val peer: () -> NativeFileControlPeer?, private val incomingIntent: () -> Any?,
    internal val selected: GalleryIncomingPublication, expectedControl: NativeFileOperationBinding?) : AutoCloseable {
    internal val kind = GalleryMediaType.entries.single { it.uriSegment == selected.body.string("media_type") }
    private val token = incomingIntent() as? MediaSyncTransport.IntentToken ?: fail()
    private val originalPeer = peer()?.takeIf { it.allowed && it.pairingEpoch != null } ?: fail()
    private val origin = selected.body.getValue("origin").jsonObject
    private val originalBinding = origin.getValue("binding").jsonObject
    private val originalControl = session.operationBinding(origin.string("manifest_sha256")) ?: fail()
    private val binding = originalControl.binding
    private val policy = index.galleryPolicy()
    private val issued = DeviceFileControl.monotonicMs()
    private var last = issued
    private val closed = AtomicBoolean(false)
    private val used = AtomicBoolean(false)
    internal val grantsWriteAuthority: Boolean get() = false
    internal val isSavedReceipt: Boolean get() = false

    init {
        if (expectedControl != null && originalControl != expectedControl) fail()
        requireCurrent()
    }
    @Synchronized internal fun requireCurrent() {
        try {
            val now = DeviceFileControl.monotonicMs()
            if (closed.get() || now < last || now - issued >= DeviceFileControl.MAX_TTL_MS || incomingIntent() !== token ||
                !token.requestedIncoming(kind)) fail()
            book.requireCurrent()
            val current = peer() ?: fail()
            if (current != originalPeer || current.owner !== originalPeer.owner || !current.allowed || kind == GalleryMediaType.VIDEO && !current.videoSupported ||
                session.operationBinding(origin.string("manifest_sha256")) != originalControl || index.galleryPolicy() != policy || policy.repairPending ||
                policy.policy?.let { it.receiverId == current.peerId && it.receiverIdentitySha256 == current.identitySha256 &&
                    it.pairingEpoch == current.pairingEpoch && it.receiving?.enabled(kind) == true } != true ||
                selected.state != "published" || selected.row == null || index.incomingPublication(selected.id)?.body != selected.body ||
                binding.senderId != current.peerId || binding.senderIdentitySha256 != current.identitySha256 ||
                listOf("sender_id", "receiver_id", "sender_identity_sha256", "receiver_identity_sha256").any {
                    originalBinding[it] != binding.snapshot()[it]
                }) fail()
            last = now
        } catch (error: Exception) { closed.set(true); throw error }
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
    override fun close() { closed.set(true) }
    companion object {
        internal fun capture(session: NativeFileControlSession, index: PhotoSourceJobIndex, book: NativeGalleryReceiveBookPermit,
            peer: () -> NativeFileControlPeer?, incomingIntent: () -> Any?, selected: GalleryIncomingPublication,
            expectedControl: NativeFileOperationBinding? = null): NativeGalleryPublishedInspection {
            if (Build.VERSION.SDK_INT < 30 || Looper.myLooper() == Looper.getMainLooper()) fail()
            return NativeGalleryPublishedInspection(session, index, book, peer, incomingIntent, selected, expectedControl)
        }
        private fun fail(): Nothing = DeviceFileControl.fail("gallery_published_current_read_owner_required")
    }
}
