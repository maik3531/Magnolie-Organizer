package io.gitlab.maik3531.magnolienotes.telefon

import android.os.Looper
import java.security.SecureRandom
import java.util.Locale

/** Local native consent CAS only, never a transport/OS/file-write grant.
 * The runtime must serialize this lane with its control/policy operations and
 * hold positive configuration while any source/receiver job owns media IO. */
internal class GalleryReceivePolicyController(private val index: PhotoSourceJobIndex,
    private val peer: NativeFileControlIdentity, private val currentConfigurer: () -> NativeFileReceiveConfigurer?) {
    @Volatile private var uncertain = false
    internal fun available(): Boolean = !uncertain

    @Synchronized internal fun grant(expected: GalleryPhotoPolicySnapshot,
        selection: NativeGalleryReceiveConsent): GalleryPhotoPolicySnapshot {
        ioRequired(); ready(expected); selection.consume()
        fun current(): Boolean {
            selection.requireConfigurer(currentConfigurer())
            val selected = selection.configurer
            if (selected.peerId != peer.deviceId || selected.identitySha256 != peer.identitySha256)
                fail("gallery_receive_receiver_changed")
            return true
        }
        current(); original(expected)
        val old = expected.policy
        requirePeer(old)
        val pairing = selection.configurer.pairingEpoch
        val samePair = old?.pairingEpoch == pairing
        if (samePair && old?.receiving?.enabled(selection.mediaType) == true) return expected
        capacity(old)
        val before = old?.receiving
        val wanted = if (samePair && before != null) before else GalleryReceivePolicy(false, false, epoch())
        val receiving = wanted.copy(photos = if (selection.mediaType == GalleryMediaType.IMAGES) true else wanted.photos,
            videos = if (selection.mediaType == GalleryMediaType.VIDEO) true else wanted.videos,
            epoch = epoch(), revision = (before?.revision ?: 0L) + 1)
        val revision = (old?.revision ?: 1L) + 1
        val videos = old?.videos?.let { if (samePair) it else it.copy(enabled = false) }
            ?: GalleryVideoPolicy(false, epoch())
        val next = GalleryPhotoPolicy(peer.deviceId, peer.identitySha256, old?.epoch ?: epoch(),
            samePair && old?.enabled == true, old?.kinds ?: emptySet(), revision, 5, pairing, videos, revision, receiving)
        return commit(expected, next, ::current)
    }

    /** Explicit local decrease needs the saved/unlocked book, not a live PC or
     * receive handler. It cannot bootstrap missing settings or rebind a peer. */
    @Synchronized internal fun revoke(expected: GalleryPhotoPolicySnapshot, kind: GalleryMediaType,
        book: NativeGalleryReceiveBookPermit): GalleryPhotoPolicySnapshot {
        ioRequired(); ready(expected)
        fun current(): Boolean { book.requireCurrent(); return true }
        current(); original(expected)
        val old = expected.policy
        requirePeer(old)
        val before = old?.receiving
        if (old == null || before == null || !before.enabled(kind)) return expected
        capacity(old)
        val receiving = before.copy(photos = if (kind == GalleryMediaType.IMAGES) false else before.photos,
            videos = if (kind == GalleryMediaType.VIDEO) false else before.videos, epoch = epoch(), revision = before.revision + 1)
        val revision = old.revision + 1
        val next = GalleryPhotoPolicy(old.receiverId, old.receiverIdentitySha256, old.epoch, old.enabled, old.kinds,
            revision, 5, old.pairingEpoch, old.videos, revision, receiving)
        return commit(expected, next, ::current)
    }

    private fun ready(expected: GalleryPhotoPolicySnapshot) {
        if (uncertain || expected.repairPending) fail("gallery_receive_policy_repair_pending")
    }
    private fun original(expected: GalleryPhotoPolicySnapshot) {
        if (index.galleryPolicy() != expected) fail("gallery_policy_cas_conflict")
    }
    private fun requirePeer(old: GalleryPhotoPolicy?) {
        if (old != null && (old.receiverId != peer.deviceId || old.receiverIdentitySha256 != peer.identitySha256))
            fail("gallery_receive_receiver_changed")
    }
    private fun capacity(old: GalleryPhotoPolicy?) {
        if ((old?.revision ?: 1L) >= DeviceFileControl.MAX_REVISION || (old?.receiving?.revision ?: 0L) >= DeviceFileControl.MAX_REVISION) {
            uncertain = true; fail("gallery_receive_policy_revision_exhausted")
        }
    }
    private fun commit(expected: GalleryPhotoPolicySnapshot, next: GalleryPhotoPolicy, current: () -> Boolean): GalleryPhotoPolicySnapshot {
        try {
            val saved = index.compareAndSetGalleryPolicy(expected, next, current)
            if (saved.repairPending || saved.policy != next || index.galleryPolicy() != saved || !current())
                fail("gallery_receive_policy_commit_readback_failed")
            return saved
        } catch (error: Exception) { uncertain = true; throw error }
    }
    private fun ioRequired() {
        if (Looper.myLooper() == Looper.getMainLooper()) fail("gallery_receive_policy_io_thread_required")
    }
    private fun epoch() = ByteArray(32).also(SecureRandom()::nextBytes)
        .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    private fun fail(code: String): Nothing = DeviceFileControl.fail(code)
}
