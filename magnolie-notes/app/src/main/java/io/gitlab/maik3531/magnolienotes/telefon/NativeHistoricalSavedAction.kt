package io.gitlab.maik3531.magnolienotes.telefon

import java.util.concurrent.atomic.AtomicBoolean

/** Explicit native metadata-recovery intent. Never deserialized from IPC. */
internal class NativeHistoricalSavedAction internal constructor(private val owner: Any,
    internal val job: PhotoSourceJob, internal val original: PhotoSourceRemoteAcceptance,
    private val observed: NativePhotoReceiver, private val current: () -> NativePhotoReceiver?,
    private val elapsed: () -> Long) {
    private val used = AtomicBoolean(false)
    private val issued = elapsed()
    private var last = issued
    private var invalid = false

    @Synchronized internal fun validate(expectedOwner: Any) {
        val now = elapsed()
        if (invalid || owner !== expectedOwner || issued < 0 || now < last ||
            now - issued >= DeviceFileControl.MAX_TTL_MS) {
            invalid = true; DeviceFileControl.fail("photo_jobs_historical_action_not_current")
        }
        last = now
        val peer = current()
        val originalPeer = original.originalAuthority
        if (peer == null || !peer.allowed || originalPeer == null || originalPeer.pairingEpoch == null ||
            peer.owner !== observed.owner || peer.peerId != observed.peerId || peer.identitySha256 != observed.identitySha256 ||
            peer.permissionEpoch != observed.permissionEpoch || peer.pairingEpoch != observed.pairingEpoch ||
            peer.peerId != originalPeer.receiverId || peer.identitySha256 != originalPeer.receiverIdentitySha256 ||
            peer.permissionEpoch != originalPeer.permissionEpoch || peer.pairingEpoch != originalPeer.pairingEpoch) {
            invalid = true; DeviceFileControl.fail("photo_jobs_historical_authority_changed")
        }
    }

    internal fun consume(expectedOwner: Any) {
        if (!used.compareAndSet(false, true)) DeviceFileControl.fail("photo_jobs_historical_action_consumed")
        validate(expectedOwner)
    }
}
