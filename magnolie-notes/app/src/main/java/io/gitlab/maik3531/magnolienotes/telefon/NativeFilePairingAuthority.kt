package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonPrimitive
import java.security.MessageDigest
import java.util.Locale

/** Local relationship identity, not file consent. Only the code-confirmed
 * pairing path assigns it. Ordinary peer loading/copying never creates one.
 */
internal object NativeFilePairingAuthority {
    /** Public identity already proven by the actual native handshake. This
     * projection performs no identity/store/key lookup or creation.
     */
    fun fromAuthenticatedIdentity(identity: TelefonIdentitaet): NativeFileControlIdentity {
        require(identity.storage_version == 1 && identity.role == "phone")
        val key = TelefonKrypto.b64(identity.static_public, 32)
        val digest = MessageDigest.getInstance("SHA-256").digest(key)
            .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        return NativeFileControlIdentity(identity.device_id, digest)
    }

    fun epochForConfirmedTranscript(transcript: String): String {
        // The native pairing transcript is already authenticated and contains
        // fresh handshake material. Do not accept an arbitrary peer label here.
        TelefonKrypto.b64(transcript, 32)
        return DeviceFileControl.digest("magnolie-native-file-pairing-v1\u0000", JsonPrimitive(transcript))
    }

    fun currentEpoch(peer: TelefonPeer?): String? = peer?.takeIf {
        it.state == "paired" && it.own_device && it.remote_own_device && DeviceFileControl.hash(it.file_pairing_epoch)
    }?.file_pairing_epoch

    /** Called only after the native transport owner/generation checks. Existing
     * contacts/Notes grants and device-status consent do not authorize files.
     * Discovery support is metadata, not permission to read/send source bytes.
     */
    fun controlPeer(peer: TelefonPeer, owner: Any, ready: Boolean, handlersReady: Boolean): NativeFileControlPeer? {
        val epoch = currentEpoch(peer) ?: return null
        if (!ready || !handlersReady || !peer.remote_device_status_available ||
            DeviceFileControl.DISCOVERY_VERSION !in peer.remote_device_status_versions) return null
        val key = TelefonKrypto.b64(peer.static_public, 32)
        val hash = MessageDigest.getInstance("SHA-256").digest(key)
            .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        return NativeFileControlPeer(peer.device_id, hash, owner, true, true, peer.own_device, peer.remote_own_device, true, epoch)
    }
}
