package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.util.Collections
import java.security.SecureRandom
import java.util.Locale

/** Dedicated source policy; Android read permission is separate. No remote
 * access epochs, phone writes/deletions, destination paths or book settings.
 */
internal class GalleryPhotoPolicy(val receiverId: String, val receiverIdentitySha256: String,
    val epoch: String, val enabled: Boolean, kinds: Set<GallerySourceKind>) {
    val kinds: Set<GallerySourceKind> = Collections.unmodifiableSet(kinds.toSet())
    init {
        require(Regex("[A-Za-z0-9_-]{16,160}").matches(receiverId))
        require(Regex("[0-9a-f]{64}").matches(receiverIdentitySha256) && Regex("[0-9a-f]{64}").matches(epoch))
        require(!enabled || kinds.isNotEmpty())
    }
    override fun equals(other: Any?): Boolean = other is GalleryPhotoPolicy && wire() == other.wire()
    override fun hashCode(): Int = wire().hashCode()
    internal fun wire() = JsonObject(mapOf("format" to JsonPrimitive(1), "receiver_id" to JsonPrimitive(receiverId),
        "receiver_identity_sha256" to JsonPrimitive(receiverIdentitySha256), "epoch" to JsonPrimitive(epoch),
        "enabled" to JsonPrimitive(enabled), "kinds" to JsonArray(kinds.sortedBy { it.ordinal }.map { JsonPrimitive(it.name) })))

    companion object {
        internal fun parse(value: JsonObject): GalleryPhotoPolicy {
            fun fail(): Nothing = throw PhotoFolderScopeError("gallery_policy_invalid_record")
            fun text(name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            if (value.keys != setOf("format", "receiver_id", "receiver_identity_sha256", "epoch", "enabled", "kinds") ||
                value["format"] != JsonPrimitive(1)) fail()
            val enabled = (value["enabled"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
            val rawKinds = value["kinds"] as? JsonArray ?: fail()
            if (rawKinds.size > GallerySourceKind.entries.size) fail()
            val kinds = rawKinds.map { item ->
                val name = (item as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
                GallerySourceKind.entries.singleOrNull { it.name == name } ?: fail()
            }
            if (kinds.distinct().size != kinds.size) fail()
            return try { GalleryPhotoPolicy(text("receiver_id"), text("receiver_identity_sha256"), text("epoch"), enabled, kinds.toSet()) }
            catch (_: IllegalArgumentException) { fail() }
        }
    }
}

internal data class GalleryPhotoPolicySnapshot(val version: String, val policy: GalleryPhotoPolicy?, val repairPending: Boolean)
internal data class GalleryPhotoPolicyRepair internal constructor(val fenceVersion: String, val state: GalleryPhotoPolicySnapshot,
    val matchesWanted: Boolean)

/** Native adapter target for authenticated desktop controls. No remote policy
 * epoch or Boolean callback becomes Android permission. Failed/uncertain commits
 * fence this controller too; explicit store repair requires a fresh owner.
 */
internal class GalleryPhotoPolicyController(private val index: PhotoSourceJobIndex,
    private val currentReceiver: () -> NativePhotoReceiver?) {
    private var uncertain = false

    @Synchronized fun configure(expected: GalleryPhotoPolicySnapshot, enabled: Boolean, kinds: Set<GallerySourceKind>): GalleryPhotoPolicySnapshot {
        if (uncertain || expected.repairPending) fail("gallery_policy_repair_pending")
        val receiver = currentReceiver()
        val old = expected.policy
        if (enabled && (receiver?.allowed != true || kinds.isEmpty())) fail("gallery_receiver_not_ready")
        if (old == null && receiver?.allowed != true) fail("gallery_receiver_not_ready")
        if (receiver != null && old != null && (old.receiverId != receiver.peerId || old.receiverIdentitySha256 != receiver.identitySha256))
            fail("gallery_policy_receiver_changed")
        val peer = old?.receiverId ?: receiver!!.peerId
        val identity = old?.receiverIdentitySha256 ?: receiver!!.identitySha256
        val epoch = ByteArray(32).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        val next = GalleryPhotoPolicy(peer, identity, epoch, enabled, kinds)
        fun allowed() = !enabled || receiver != null && same(receiver, currentReceiver())
        try {
            val saved = index.compareAndSetGalleryPolicy(expected, next, ::allowed)
            if (saved.repairPending || saved.policy != next || index.galleryPolicy() != saved || !allowed())
                fail("gallery_policy_commit_readback_failed")
            return saved
        } catch (error: Exception) { uncertain = true; throw error }
    }

    @Synchronized fun currentRequest(): NativeGalleryRequest? {
        if (uncertain) return null
        val receiver = currentReceiver()?.takeIf { it.allowed } ?: return null
        val saved = index.galleryPolicy()
        val policy = saved.policy ?: return null
        if (saved.repairPending || !policy.enabled || policy.receiverId != receiver.peerId || policy.receiverIdentitySha256 != receiver.identitySha256)
            return null
        if (!same(receiver, currentReceiver()) || index.galleryPolicy() != saved) return null
        return NativeGalleryRequest(receiver, policy.epoch, policy.kinds)
    }

    private fun same(first: NativePhotoReceiver, second: NativePhotoReceiver?): Boolean = second != null && first.allowed && second.allowed &&
        first.peerId == second.peerId && first.identitySha256 == second.identitySha256 && first.permissionEpoch == second.permissionEpoch &&
        first.owner === second.owner
    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
