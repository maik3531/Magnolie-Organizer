package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*

/** Native read-only projection of actual protected policy. Does not construct a
 * personal store, persist defaults, scan media or request Android permissions.
 * The caller supplies the authenticated native peer and actual protected index
 * reader (for example NativeGalleryPhotoWorkflow.savedPolicy).
 */
internal class NativeGalleryFileGrantPolicy(private val currentPeer: () -> NativeFileControlPeer?,
    private val readPolicy: () -> GalleryPhotoPolicySnapshot, private val handlersReady: () -> Boolean) {
    private val owner = Any()
    private var confirmed: DeviceFileGrantState? = null
    private var relationship: Triple<String, String, String>? = null
    private var uncertain = false

    @Synchronized fun current(): NativeLocalFileGrant? {
        if (uncertain) return null
        val peer = currentPeer()?.takeIf { it.allowed } ?: return null
        val pairing = peer.pairingEpoch ?: return null
        val nextRelationship = Triple(peer.peerId, peer.identitySha256, pairing)
        if (relationship != null && relationship != nextRelationship) { uncertain = true; return null }
        relationship = nextRelationship
        try {
            val saved = readPolicy()
            val policy = saved.policy
            // Closed initial consent is derived from native relationship
            // identity only, never written as a fabricated enabled default.
            val offEpoch = DeviceFileControl.digest("magnolie-native-file-initial-off-v1\u0000", JsonArray(listOf(
                JsonPrimitive(peer.peerId), JsonPrimitive(peer.identitySha256), JsonPrimitive(pairing))))
            val off = DeviceFileGrantState(policy?.fileGrantRevision ?: 1L, offEpoch, false, false)
            if (saved.repairPending) {
                // A restarted adapter has no authenticated pre-CAS grant in
                // memory. Do not invent one at the pending policy's revision:
                // that would collide with the repaired confirmed grant later.
                val held = confirmed ?: return null
                val ready = handlersReady()
                if (!ready && held.sendFiles) return null
                return NativeLocalFileGrant(held, owner, ready, policyReady = false)
            }
            val associated = policy != null && policy.receiverId == peer.peerId && policy.receiverIdentitySha256 == peer.identitySha256 &&
                policy.pairingEpoch == pairing
            val next = if (associated) DeviceFileGrantState(policy!!.fileGrantRevision, policy.epoch, policy.enabled, false) else off
            val before = confirmed
            if (before != null && (next.revision < before.revision || next.revision == before.revision &&
                    next.permissionWire() != before.permissionWire())) { uncertain = true; return null }
            confirmed = next
            val ready = handlersReady()
            // A disabled handler cannot wrap an enabled native grant. Keep the
            // confirmed bytes intact for a later fresh native owner instead.
            if (!ready && next.sendFiles) return null
            return NativeLocalFileGrant(next, owner, ready)
        } catch (error: Exception) { uncertain = true; throw error }
    }
}
