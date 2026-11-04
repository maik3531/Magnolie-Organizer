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
internal data class GalleryVideoPolicy(val enabled: Boolean, val epoch: String, val revision: Long = 1) {
    init { require(DeviceFileControl.hash(epoch) && revision in 1..DeviceFileControl.MAX_REVISION) }
    internal fun wire() = JsonObject(mapOf("enabled" to JsonPrimitive(enabled), "epoch" to JsonPrimitive(epoch), "revision" to JsonPrimitive(revision)))
    companion object {
        internal fun parse(value: JsonObject): GalleryVideoPolicy {
            fun fail(): Nothing = throw PhotoFolderScopeError("gallery_video_policy_invalid_record")
            if (value.keys != setOf("enabled", "epoch", "revision")) fail()
            val enabled = (value["enabled"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
            val epoch = (value["epoch"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            val revision = (value["revision"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull() ?: fail()
            return try { GalleryVideoPolicy(enabled, epoch, revision) } catch (_: IllegalArgumentException) { fail() }
        }
    }
}

internal class GalleryPhotoPolicy(val receiverId: String, val receiverIdentitySha256: String,
    val epoch: String, val enabled: Boolean, kinds: Set<GallerySourceKind>, val revision: Long = 1,
    private val recordFormat: Int = 1, val pairingEpoch: String? = null,
    val videos: GalleryVideoPolicy? = null, private val permissionRevision: Long? = null) {
    val kinds: Set<GallerySourceKind> = Collections.unmodifiableSet(kinds.toSet())
    val fileGrantRevision: Long get() = permissionRevision ?: revision
    init {
        require(Regex("[A-Za-z0-9_-]{16,160}").matches(receiverId))
        require(Regex("[0-9a-f]{64}").matches(receiverIdentitySha256) && Regex("[0-9a-f]{64}").matches(epoch))
        require(!enabled || kinds.isNotEmpty())
        require(recordFormat in 1..4 && revision in 1..DeviceFileControl.MAX_REVISION && (recordFormat != 1 || revision == 1L))
        require(if (recordFormat >= 3) pairingEpoch != null && DeviceFileControl.hash(pairingEpoch) else pairingEpoch == null)
        require(if (recordFormat == 4) videos != null && permissionRevision != null && permissionRevision in 1..revision
            else videos == null && permissionRevision == null)
    }
    override fun equals(other: Any?): Boolean = other is GalleryPhotoPolicy && wire() == other.wire()
    override fun hashCode(): Int = wire().hashCode()
    internal fun wire() = JsonObject(mapOf("format" to JsonPrimitive(recordFormat), "receiver_id" to JsonPrimitive(receiverId),
        "receiver_identity_sha256" to JsonPrimitive(receiverIdentitySha256), "epoch" to JsonPrimitive(epoch),
        "enabled" to JsonPrimitive(enabled), "kinds" to JsonArray(kinds.sortedBy { it.ordinal }.map { JsonPrimitive(it.name) })) +
        (if (recordFormat >= 2) mapOf("revision" to JsonPrimitive(revision)) else emptyMap()) +
        (if (recordFormat >= 3) mapOf("pairing_epoch" to JsonPrimitive(pairingEpoch)) else emptyMap()) +
        (if (recordFormat == 4) mapOf("videos" to videos!!.wire(), "permission_revision" to JsonPrimitive(permissionRevision)) else emptyMap()))

    companion object {
        internal fun parse(value: JsonObject): GalleryPhotoPolicy {
            fun fail(): Nothing = throw PhotoFolderScopeError("gallery_policy_invalid_record")
            fun text(name: String) = (value[name] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            val format = when (value["format"]) { JsonPrimitive(1) -> 1; JsonPrimitive(2) -> 2; JsonPrimitive(3) -> 3; JsonPrimitive(4) -> 4; else -> fail() }
            if (value.keys != setOf("format", "receiver_id", "receiver_identity_sha256", "epoch", "enabled", "kinds") +
                (if (format >= 2) setOf("revision") else emptySet()) + (if (format >= 3) setOf("pairing_epoch") else emptySet()) +
                (if (format == 4) setOf("videos", "permission_revision") else emptySet())) fail()
            val revision = if (format == 1) 1L else (value["revision"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull() ?: fail()
            val enabled = (value["enabled"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
            val rawKinds = value["kinds"] as? JsonArray ?: fail()
            if (rawKinds.size > GallerySourceKind.entries.size) fail()
            val kinds = rawKinds.map { item ->
                val name = (item as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
                GallerySourceKind.entries.singleOrNull { it.name == name } ?: fail()
            }
            if (kinds.distinct().size != kinds.size) fail()
            val videos = if (format == 4) GalleryVideoPolicy.parse(value["videos"] as? JsonObject ?: fail()) else null
            val permissionRevision = if (format == 4) (value["permission_revision"] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull() ?: fail() else null
            return try { GalleryPhotoPolicy(text("receiver_id"), text("receiver_identity_sha256"), text("epoch"), enabled, kinds.toSet(), revision, format,
                if (format >= 3) text("pairing_epoch") else null, videos, permissionRevision) }
            catch (_: IllegalArgumentException) { fail() }
        }
    }
}

internal data class GalleryPhotoPolicySnapshot(val version: String, val policy: GalleryPhotoPolicy?, val repairPending: Boolean)
internal data class GalleryPhotoPolicyRepair internal constructor(val fenceVersion: String, val state: GalleryPhotoPolicySnapshot,
    val matchesWanted: Boolean)

/** Native configure-command authority, deliberately not source READ/send consent.
 * It can bootstrap an explicitly requested own-PC policy before data grants or
 * Android media permission exist. There is no wire parser for this type.
 */
internal data class NativeGalleryConfigurer(val peerId: String, val identitySha256: String, val owner: Any,
    val permissionEpoch: String, val ready: Boolean, val paired: Boolean, val ownDevice: Boolean, val remoteOwnDevice: Boolean,
    val pairingEpoch: String? = null) {
    init { require(DeviceFileControl.id(peerId) && DeviceFileControl.hash(identitySha256) && DeviceFileControl.hash(permissionEpoch) &&
        (pairingEpoch == null || DeviceFileControl.hash(pairingEpoch))) }
    val allowed: Boolean get() = ready && paired && ownDevice && remoteOwnDevice
}

/** Native adapter target for authenticated desktop controls. No remote policy
 * epoch or Boolean callback becomes Android permission. Failed/uncertain commits
 * fence this controller too; explicit store repair requires a fresh owner.
 */
internal class GalleryPhotoPolicyController private constructor(private val index: PhotoSourceJobIndex,
    private val currentReceiver: () -> NativePhotoReceiver?, private val currentConfigurer: (() -> NativeGalleryConfigurer?)?,
    private val videoAvailable: () -> Boolean) {
    constructor(index: PhotoSourceJobIndex, currentReceiver: () -> NativePhotoReceiver?) : this(index, currentReceiver, null, { true })
    companion object {
        fun forAuthenticatedConfigurer(index: PhotoSourceJobIndex, currentReceiver: () -> NativePhotoReceiver?,
            currentConfigurer: () -> NativeGalleryConfigurer?) = GalleryPhotoPolicyController(index, currentReceiver, currentConfigurer, { true })
        fun forAuthenticatedConfigurer(index: PhotoSourceJobIndex, currentReceiver: () -> NativePhotoReceiver?,
            currentConfigurer: () -> NativeGalleryConfigurer?, videoAvailable: () -> Boolean) =
            GalleryPhotoPolicyController(index, currentReceiver, currentConfigurer, videoAvailable)
    }
    private var uncertain = false
    // Saved video preference is not fresh session consent. Only an explicit
    // successful positive command with an acknowledged native data receiver can
    // arm this owner. Nothing here is serialized or recovered from job history.
    private var videoActivation: Pair<String, NativePhotoReceiver>? = null

    private fun configurer(): NativeGalleryConfigurer? {
        if (currentConfigurer != null) return currentConfigurer.invoke()
        val receiver = currentReceiver()?.takeIf { it.allowed } ?: return null
        return NativeGalleryConfigurer(receiver.peerId, receiver.identitySha256, receiver.owner, receiver.permissionEpoch,
            receiver.ready, receiver.paired, receiver.ownDevice, receiver.remoteOwnDevice, receiver.pairingEpoch)
    }

    @Synchronized fun configure(expected: GalleryPhotoPolicySnapshot, enabled: Boolean, kinds: Set<GallerySourceKind>): GalleryPhotoPolicySnapshot {
        if (uncertain || expected.repairPending) fail("gallery_policy_repair_pending")
        val receiver = configurer()
        val old = expected.policy
        if (currentConfigurer != null && receiver?.allowed != true) fail("gallery_configurer_not_ready")
        if (enabled && (receiver?.allowed != true || kinds.isEmpty())) fail("gallery_receiver_not_ready")
        if (old == null && receiver?.allowed != true) fail("gallery_receiver_not_ready")
        if (receiver != null && old != null && (old.receiverId != receiver.peerId || old.receiverIdentitySha256 != receiver.identitySha256))
            fail("gallery_policy_receiver_changed")
        val peer = old?.receiverId ?: receiver!!.peerId
        val identity = old?.receiverIdentitySha256 ?: receiver!!.identitySha256
        // A remote disable is still an authenticated command throughout its
        // transaction. Only the explicit native decrease-only path may proceed
        // without a live remote configurer.
        fun allowed() = if (currentConfigurer != null || enabled)
            receiver != null && sameConfigurer(receiver, configurer()) else true
        val pairingEpoch = receiver?.pairingEpoch ?: old?.pairingEpoch
        if (old != null && old.enabled == enabled && old.kinds == kinds && old.pairingEpoch == pairingEpoch) {
            if (index.galleryPolicy() != expected || !allowed()) fail("gallery_policy_cas_conflict")
            return expected // Same policy/mode-only traffic never rekeys data consent.
        }
        if ((old?.revision ?: 1L) >= DeviceFileControl.MAX_REVISION) fail("gallery_policy_revision_exhausted")
        val epoch = ByteArray(32).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        val next = GalleryPhotoPolicy(peer, identity, epoch, enabled, kinds, (old?.revision ?: 1L) + 1,
            if (old?.videos != null) 4 else if (pairingEpoch == null) 2 else 3, pairingEpoch,
            old?.videos?.let { if (old.pairingEpoch == pairingEpoch) it else it.copy(enabled = false) },
            if (old?.videos != null) old.revision + 1 else null)
        try {
            val saved = index.compareAndSetGalleryPolicy(expected, next, ::allowed)
            if (saved.repairPending || saved.policy != next || index.galleryPolicy() != saved || !allowed())
                fail("gallery_policy_commit_readback_failed")
            return saved
        } catch (error: Exception) { uncertain = true; throw error }
    }

    /** Separate explicit native video consent. It neither grants OS READ nor
     * rekeys the already acknowledged photo transport or its saved history. */
    @Synchronized fun configureVideos(expected: GalleryPhotoPolicySnapshot, enabled: Boolean): GalleryPhotoPolicySnapshot {
        if (uncertain || expected.repairPending) fail("gallery_policy_repair_pending")
        if (enabled && !videoAvailable()) fail("gallery_video_handlers_unavailable")
        val receiver = configurer()?.takeIf { it.allowed } ?: fail("gallery_configurer_not_ready")
        val old = expected.policy ?: fail("gallery_video_photo_policy_required")
        if (!old.enabled || old.receiverId != receiver.peerId || old.receiverIdentitySha256 != receiver.identitySha256 ||
            old.pairingEpoch == null || old.pairingEpoch != receiver.pairingEpoch) fail("gallery_video_photo_policy_required")
        fun allowed() = sameConfigurer(receiver, configurer()) && (!enabled || videoAvailable())
        if (index.galleryPolicy() != expected || !allowed()) fail("gallery_policy_cas_conflict")
        if (!enabled) videoActivation = null
        if ((old.videos?.enabled ?: false) == enabled) {
            if (index.galleryPolicy() != expected || !allowed()) fail("gallery_policy_cas_conflict")
            if (enabled) armVideo(old)
            return expected
        }
        val exhausted = when {
            old.revision >= DeviceFileControl.MAX_REVISION -> "gallery_policy_revision_exhausted"
            (old.videos?.revision ?: 0L) >= DeviceFileControl.MAX_REVISION -> "gallery_video_revision_exhausted"
            else -> null
        }
        if (exhausted != null) {
            // A stale/foreign command must not acquire decrease authority. A
            // current explicit decrease that cannot be committed must HOLD this
            // owner just like an uncertain CAS, never silently keep VIDEO READ.
            // This is NOT a persisted off policy, counter reset or repair ACK.
            if (index.galleryPolicy() != expected || !allowed()) fail("gallery_policy_cas_conflict")
            if (!enabled) uncertain = true
            fail(exhausted)
        }
        val epoch = ByteArray(32).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
        val next = GalleryPhotoPolicy(old.receiverId, old.receiverIdentitySha256, old.epoch, old.enabled, old.kinds,
            old.revision + 1, 4, old.pairingEpoch, GalleryVideoPolicy(enabled, epoch, (old.videos?.revision ?: 0L) + 1), old.fileGrantRevision)
        try {
            val saved = index.compareAndSetGalleryPolicy(expected, next, ::allowed)
            if (saved.repairPending || saved.policy != next || index.galleryPolicy() != saved || !allowed())
                fail("gallery_policy_commit_readback_failed")
            if (enabled) armVideo(next)
            return saved
        } catch (error: Exception) { uncertain = true; throw error }
    }

    @Synchronized fun currentRequest(mediaType: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryRequest? {
        if (uncertain) return null
        if (mediaType == GalleryMediaType.VIDEO && !videoAvailable()) return null
        val receiver = currentReceiver()?.takeIf { it.allowed } ?: return null
        val saved = index.galleryPolicy()
        val policy = saved.policy ?: return null
        if (saved.repairPending || !policy.enabled || policy.receiverId != receiver.peerId || policy.receiverIdentitySha256 != receiver.identitySha256 ||
            policy.pairingEpoch != receiver.pairingEpoch)
            return null
        if (!same(receiver, currentReceiver()) || index.galleryPolicy() != saved) return null
        val epoch = if (mediaType == GalleryMediaType.IMAGES) policy.epoch else policy.videos?.takeIf { it.enabled }?.epoch ?: return null
        if (mediaType == GalleryMediaType.VIDEO) {
            val activation = videoActivation ?: return null
            if (activation.first != epoch || !same(activation.second, receiver)) return null
        }
        return NativeGalleryRequest(receiver, epoch, policy.kinds, mediaType)
    }

    private fun armVideo(policy: GalleryPhotoPolicy) {
        val video = policy.videos?.takeIf { it.enabled } ?: return
        val receiver = currentReceiver()?.takeIf { it.allowed && it.peerId == policy.receiverId &&
            it.identitySha256 == policy.receiverIdentitySha256 && it.pairingEpoch == policy.pairingEpoch }
        videoActivation = receiver?.let { video.epoch to it }
    }

    /** Explicit native local decrease only, not a remote configure bypass.
     * Never creates an off default or releases app-wide Android URI permissions.
     */
    @Synchronized fun disableLocally(expected: GalleryPhotoPolicySnapshot): GalleryPhotoPolicySnapshot {
        if (expected.policy == null) {
            if (index.galleryPolicy() != expected || expected.repairPending) fail("gallery_policy_repair_pending")
            return expected
        }
        return GalleryPhotoPolicyController(index, currentReceiver).configure(expected, false, emptySet())
    }

    private fun same(first: NativePhotoReceiver, second: NativePhotoReceiver?): Boolean = second != null && first.allowed && second.allowed &&
        first.peerId == second.peerId && first.identitySha256 == second.identitySha256 && first.permissionEpoch == second.permissionEpoch &&
        first.owner === second.owner && first.pairingEpoch == second.pairingEpoch
    private fun sameConfigurer(first: NativeGalleryConfigurer, second: NativeGalleryConfigurer?): Boolean = second != null && first.allowed && second.allowed &&
        first.peerId == second.peerId && first.identitySha256 == second.identitySha256 && first.permissionEpoch == second.permissionEpoch &&
        first.owner === second.owner && first.pairingEpoch == second.pairingEpoch
    private fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}
