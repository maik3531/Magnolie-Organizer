package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonPrimitive

/** Local relationship identity, not file consent. Only the code-confirmed
 * pairing path assigns it. Ordinary peer loading/copying never creates one.
 */
internal object NativeFilePairingAuthority {
    fun epochForConfirmedTranscript(transcript: String): String {
        // The native pairing transcript is already authenticated and contains
        // fresh handshake material. Do not accept an arbitrary peer label here.
        TelefonKrypto.b64(transcript, 32)
        return DeviceFileControl.digest("magnolie-native-file-pairing-v1\u0000", JsonPrimitive(transcript))
    }

    fun currentEpoch(peer: TelefonPeer?): String? = peer?.takeIf {
        it.state == "paired" && it.own_device && it.remote_own_device && DeviceFileControl.hash(it.file_pairing_epoch)
    }?.file_pairing_epoch
}
