package io.gitlab.maik3531.magnolienotes.telefon

import java.io.IOException
import java.security.SecureRandom
import java.util.Locale

internal class PhotoFolderScopeError(val code: String) : IOException(code)

/** Native observations only. Deliberately not serializable or a wire grant. */
internal data class NativePhotoReceiver(val peerId: String, val identitySha256: String, val owner: Any,
    val permissionEpoch: String, val ready: Boolean, val paired: Boolean, val ownDevice: Boolean,
    val remoteOwnDevice: Boolean, val sendGranted: Boolean, val receiveGranted: Boolean, val manifestVersion: Int,
    val pairingEpoch: String? = null) {
    init {
        require(Regex("[A-Za-z0-9_-]{16,160}").matches(peerId))
        require(Regex("[0-9a-f]{64}").matches(identitySha256) && Regex("[0-9a-f]{64}").matches(permissionEpoch))
        require(pairingEpoch == null || Regex("[0-9a-f]{64}").matches(pairingEpoch))
    }
    val allowed: Boolean get() = ready && paired && ownDevice && remoteOwnDevice && sendGranted && receiveGranted && manifestVersion == 1
}

internal data class PhotoFolderPreference(val treeUri: String, val receiverId: String,
    val receiverIdentitySha256: String, val epoch: String, val enabled: Boolean, val pairingEpoch: String? = null) {
    init {
        require(treeUri.isNotEmpty() && treeUri.length <= 4096 && treeUri.none { it.code < 32 || it.code == 127 })
        require(Regex("[A-Za-z0-9_-]{16,160}").matches(receiverId))
        require(Regex("[0-9a-f]{64}").matches(receiverIdentitySha256) && Regex("[0-9a-f]{64}").matches(epoch))
        require(pairingEpoch == null || Regex("[0-9a-f]{64}").matches(pairingEpoch))
    }
}

internal data class PhotoPreferenceSnapshot(val version: String, val preference: PhotoFolderPreference?, val repairPending: Boolean = false)

internal interface PhotoFolderPreferenceStore {
    /** Protected dedicated source state; absence is off, never a key/store reset. */
    fun read(): PhotoPreferenceSnapshot
    /** CAS must recheck permitted at actual native publication and return a real readback.
     * Failed/uncertain writes must retain a durable repair fence for later reads.
     */
    fun compareAndSet(expected: PhotoPreferenceSnapshot, next: PhotoFolderPreference,
        permitted: () -> Boolean): PhotoPreferenceSnapshot
}

internal interface ReadOnlyPhotoTrees {
    fun canonicalTree(uri: String): String
    fun persistRead(uri: String)
    fun readGrantToken(uri: String): String?
    fun hasPersistedRead(uri: String): Boolean = readGrantToken(uri) != null
    // No write, delete, release-shared-permission or gallery fallback API.
}

internal class PhotoFolderPickerTicket internal constructor(internal val receiver: NativePhotoReceiver,
    internal val expected: PhotoPreferenceSnapshot)

/** Native source proofs, never deserialized permission grants. Gallery albums
 * and SAF trees have different access models; neither is disguised as the other.
 */
internal interface NativePhotoSourceLease {
    val sourceKey: String
    val sourceEpoch: String
    val version: String
    val receiver: NativePhotoReceiver
    val readGrantToken: String
}

internal interface NativePhotoSourceAuthority {
    fun isCurrent(lease: NativePhotoSourceLease): Boolean
}

internal class PhotoFolderLease internal constructor(val preference: PhotoFolderPreference,
    override val version: String, override val receiver: NativePhotoReceiver, override val readGrantToken: String) : NativePhotoSourceLease {
    override val sourceKey: String get() = preference.treeUri
    override val sourceEpoch: String get() = preference.epoch
}

/** Explicit source consent only; no scanner, worker, capability advertisement or automatic send. */
internal class PhotoFolderScope(private val currentReceiver: () -> NativePhotoReceiver?,
    private val trees: ReadOnlyPhotoTrees, private val store: PhotoFolderPreferenceStore,
    private val newEpoch: () -> String = {
        ByteArray(32).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    }) : NativePhotoSourceAuthority {
    private var picker: PhotoFolderPickerTicket? = null
    private var uncertain = false

    private fun sameAuthority(first: NativePhotoReceiver, second: NativePhotoReceiver?): Boolean =
        second != null && first.allowed && second.allowed && first.peerId == second.peerId &&
            first.identitySha256 == second.identitySha256 && first.permissionEpoch == second.permissionEpoch &&
            first.owner === second.owner && first.pairingEpoch == second.pairingEpoch

    private fun receiver(): NativePhotoReceiver = currentReceiver()?.takeIf { it.allowed }
        ?: throw PhotoFolderScopeError("photo_receiver_not_ready")
    private fun snapshot(): PhotoPreferenceSnapshot = store.read().also {
        if (uncertain || it.repairPending) throw PhotoFolderScopeError("photo_source_repair_pending")
    }

    @Synchronized fun beginPicker(): PhotoFolderPickerTicket {
        if (picker != null) throw PhotoFolderScopeError("photo_picker_already_open")
        return PhotoFolderPickerTicket(receiver(), snapshot()).also { picker = it }
    }

    @Synchronized fun completePicker(ticket: PhotoFolderPickerTicket, resultUri: String?): Boolean {
        if (picker !== ticket) throw PhotoFolderScopeError("photo_picker_not_current")
        try {
            if (resultUri == null) return false
            if (!sameAuthority(ticket.receiver, currentReceiver())) throw PhotoFolderScopeError("photo_picker_owner_changed")
            val tree = trees.canonicalTree(resultUri)
            trees.persistRead(tree)
            val readGrant = trees.readGrantToken(tree) ?: throw PhotoFolderScopeError("photo_tree_read_permission_missing")
            val next = PhotoFolderPreference(tree, ticket.receiver.peerId, ticket.receiver.identitySha256, newEpoch(), false, ticket.receiver.pairingEpoch)
            commit(ticket.expected, next) {
                sameAuthority(ticket.receiver, currentReceiver()) && trees.readGrantToken(tree) == readGrant
            }
            return true
        } finally { if (picker === ticket) picker = null }
    }

    @Synchronized fun cancelPicker(ticket: PhotoFolderPickerTicket) {
        if (picker === ticket) picker = null
    }

    @Synchronized fun setEnabled(enabled: Boolean) {
        if (enabled && picker != null) throw PhotoFolderScopeError("photo_picker_pending")
        if (!enabled) picker = null
        val expected = snapshot()
        val old = expected.preference
        if (old == null) {
            if (enabled) throw PhotoFolderScopeError("photo_tree_not_selected")
            return
        }
        val observed = if (enabled) receiver() else null
        val readGrant = if (enabled) trees.readGrantToken(old.treeUri) else null
        if (enabled && (old.receiverId != observed!!.peerId || old.receiverIdentitySha256 != observed.identitySha256 || old.pairingEpoch != observed.pairingEpoch ||
            trees.canonicalTree(old.treeUri) != old.treeUri || readGrant == null))
            throw PhotoFolderScopeError("photo_source_permission_changed")
        val next = old.copy(enabled = enabled, epoch = newEpoch())
        commit(expected, next) {
            // Disabling this one feature never requires an online peer and
            // never releases Android's app-wide grants used by other features.
            !enabled || (sameAuthority(observed!!, currentReceiver()) && trees.readGrantToken(old.treeUri) == readGrant)
        }
    }

    private fun commit(expected: PhotoPreferenceSnapshot, next: PhotoFolderPreference, permitted: () -> Boolean) {
        try {
            val saved = store.compareAndSet(expected, next, permitted)
            if (saved.repairPending || saved.preference != next || store.read() != saved || !permitted())
                throw PhotoFolderScopeError("photo_source_commit_readback_failed")
        } catch (error: Exception) { uncertain = true; throw error }
    }

    @Synchronized fun lease(): PhotoFolderLease? {
        if (picker != null || uncertain) return null
        return runCatching {
            val observed = receiver()
            val saved = snapshot()
            val preference = saved.preference ?: return null
            val readGrant = trees.readGrantToken(preference.treeUri) ?: return null
            if (!preference.enabled || preference.receiverId != observed.peerId ||
                preference.receiverIdentitySha256 != observed.identitySha256 || preference.pairingEpoch != observed.pairingEpoch ||
                trees.canonicalTree(preference.treeUri) != preference.treeUri) return null
            if (!sameAuthority(observed, currentReceiver()) || store.read() != saved ||
                trees.readGrantToken(preference.treeUri) != readGrant) return null
            PhotoFolderLease(preference, saved.version, observed, readGrant)
        }.getOrNull()
    }

    @Synchronized override fun isCurrent(lease: NativePhotoSourceLease): Boolean {
        if (lease !is PhotoFolderLease) return false
        val live = this.lease() ?: return false
        return live.preference == lease.preference && live.version == lease.version && live.readGrantToken == lease.readGrantToken &&
            sameAuthority(lease.receiver, live.receiver)
    }
}
