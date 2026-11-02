package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Collections
import java.util.Locale
import java.util.IdentityHashMap
import java.util.concurrent.atomic.AtomicBoolean

/** Dedicated file controls, not contacts/personal-sync grants or Android READ.
 * Discovery version is reserved, NOT advertised until actual handlers are ready.
 * No store, scanner, permission prompt, worker or transport is started here.
 */
internal object DeviceFileControl {
    const val KIND = "file_transfer.control"
    const val DISCOVERY_VERSION = 21
    const val MAX_REVISION = 9_007_199_254_740_991L
    const val MAX_WIRE_BYTES = 8192
    const val MAX_TTL_MS = 60_000L
    private val clockOrigin = System.nanoTime()
    fun monotonicMs() = (System.nanoTime() - clockOrigin) / 1_000_000L
    fun hash(value: String) = Regex("[0-9a-f]{64}").matches(value)
    fun id(value: String) = Regex("[A-Za-z0-9_-]{16,160}").matches(value)
    fun digest(domain: String, value: JsonElement) = MessageDigest.getInstance("SHA-256")
        .digest(domain.toByteArray(Charsets.UTF_8) + TelefonKanonisch.bytes(value))
        .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    fun fail(code: String): Nothing = throw PhotoFolderScopeError(code)
}

internal class DeviceFileGrantState(val revision: Long, val epoch: String, val sendFiles: Boolean = false,
    val receiveFiles: Boolean = false, versions: List<Int> = listOf(1)) {
    val manifestVersions: List<Int> = Collections.unmodifiableList(ArrayList(versions))
    init {
        if (revision !in 1..DeviceFileControl.MAX_REVISION || !DeviceFileControl.hash(epoch) ||
            manifestVersions.size !in 1..8 || manifestVersions.any { it !in 1..65535 } ||
            manifestVersions.sorted().distinct() != manifestVersions) DeviceFileControl.fail("file_control_invalid_grant_state")
    }
    fun permissionWire() = JsonObject(mapOf("grant_revision" to JsonPrimitive(revision), "grant_epoch" to JsonPrimitive(epoch),
        "send_files" to JsonPrimitive(sendFiles), "receive_files" to JsonPrimitive(receiveFiles)))
    fun wire() = JsonObject(permissionWire() + ("manifest_versions" to JsonArray(manifestVersions.map(::JsonPrimitive))))
    override fun equals(other: Any?) = other is DeviceFileGrantState && wire() == other.wire()
    override fun hashCode() = wire().hashCode()
}

internal data class DeviceFileControlPacket(val grants: DeviceFileGrantState, val sessionEpoch: String,
    val sequence: Long, val echo: String?) {
    init {
        if (!DeviceFileControl.hash(sessionEpoch) || sequence !in 1..DeviceFileControl.MAX_REVISION ||
            echo != null && !DeviceFileControl.hash(echo)) DeviceFileControl.fail("file_control_invalid_packet")
    }
    fun wire() = JsonObject(grants.wire() + mapOf("format" to JsonPrimitive(1), "session_epoch" to JsonPrimitive(sessionEpoch),
        "sequence" to JsonPrimitive(sequence), "echo" to (echo?.let(::JsonPrimitive) ?: JsonNull)))
    val challenge: String get() = DeviceFileControl.digest("magnolie-file-control-challenge-v1\u0000",
        JsonObject(grants.wire() + mapOf("format" to JsonPrimitive(1), "session_epoch" to JsonPrimitive(sessionEpoch))))

    companion object {
        fun parse(value: JsonObject): DeviceFileControlPacket {
            fun fail(): Nothing = DeviceFileControl.fail("file_control_invalid_packet")
            if (value.keys != setOf("format", "grant_revision", "grant_epoch", "send_files", "receive_files", "manifest_versions",
                    "session_epoch", "sequence", "echo") || value["format"] != JsonPrimitive(1)) fail()
            fun text(key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: fail()
            fun number(key: String) = (value[key] as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toLongOrNull() ?: fail()
            fun flag(key: String) = (value[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: fail()
            val versionsValue = value["manifest_versions"] as? JsonArray ?: fail()
            if (versionsValue.size !in 1..8) fail()
            val versions = versionsValue.map {
                (it as? JsonPrimitive)?.takeIf { element -> !element.isString }?.content?.toIntOrNull() ?: fail()
            }
            return DeviceFileControlPacket(DeviceFileGrantState(number("grant_revision"), text("grant_epoch"),
                flag("send_files"), flag("receive_files"), versions), text("session_epoch"), number("sequence"),
                if (value["echo"] == JsonNull) null else text("echo"))
        }
    }
}

internal data class NativeFileControlIdentity(val deviceId: String, val identitySha256: String) {
    init { require(DeviceFileControl.id(deviceId) && DeviceFileControl.hash(identitySha256)) }
}

/** Only native protected-policy state can supply this wrapper; wire parsing
 * returns DeviceFileControlPacket, never this authority/owner-bearing type.
 */
internal class NativeLocalFileGrant(val grants: DeviceFileGrantState, val owner: Any, val handlersReady: Boolean, val policyReady: Boolean = true) {
    init { require(handlersReady || !grants.sendFiles && !grants.receiveFiles) }
}

internal data class NativeFileControlPeer(val peerId: String, val identitySha256: String, val owner: Any,
    val ready: Boolean, val paired: Boolean, val ownDevice: Boolean, val remoteOwnDevice: Boolean, val controlSupported: Boolean,
    val pairingEpoch: String? = null) {
    init { require(DeviceFileControl.id(peerId) && DeviceFileControl.hash(identitySha256) &&
        (pairingEpoch == null || DeviceFileControl.hash(pairingEpoch))) }
    val allowed: Boolean get() = ready && paired && ownDevice && remoteOwnDevice && controlSupported
}

internal class NativeFileConfigurationTicket internal constructor()

internal class NativeFileControlSession(private val identity: NativeFileControlIdentity,
    private val currentPeer: () -> NativeFileControlPeer?, private val currentLocal: () -> NativeLocalFileGrant?,
    private val monotonicMs: () -> Long = { DeviceFileControl.monotonicMs() }) : AutoCloseable {
    private val revoked = AtomicBoolean(false)
    private val peer = currentPeer()?.takeIf { it.allowed && it.peerId != identity.deviceId }
        ?: DeviceFileControl.fail("file_control_native_scope_required")
    private var local = currentLocal() ?: DeviceFileControl.fail("file_control_native_scope_required")
    private val sessionEpoch = ByteArray(32).also { SecureRandom().nextBytes(it) }
        .joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    private var sequence = 0L
    private var remote: DeviceFileControlPacket? = null
    private var pending: DeviceFileControlPacket? = null
    private var sentGrants: DeviceFileGrantState? = null
    private var sentEcho: String? = null
    private var faulted = false
    private data class ConfigurationScope(val remoteEpoch: String, val permission: JsonObject, val issued: Long, val expires: Long,
        var invalidated: Boolean = false)
    private val configurations = IdentityHashMap<NativeFileConfigurationTicket, ConfigurationScope>()

    private fun scope(): Pair<NativeFileControlPeer, NativeLocalFileGrant>? {
        if (revoked.get()) return null
        val nextPeer = currentPeer(); val nextLocal = currentLocal()
        if (nextPeer != null && (nextPeer.owner !== peer.owner || nextPeer.peerId != peer.peerId || nextPeer.identitySha256 != peer.identitySha256 ||
                nextPeer.pairingEpoch != peer.pairingEpoch) ||
            nextLocal != null && nextLocal.owner !== local.owner) faulted = true
        if (revoked.get() || faulted || nextPeer == null || !nextPeer.allowed || nextLocal == null) return null
        if (nextLocal.grants.revision < local.grants.revision || nextLocal.grants.revision == local.grants.revision &&
            nextLocal.grants.permissionWire() != local.grants.permissionWire()) { faulted = true; return null }
        local = nextLocal
        return nextPeer to nextLocal
    }

    @Synchronized fun packet(): DeviceFileControlPacket {
        val (_, state) = scope() ?: DeviceFileControl.fail("file_control_native_scope_changed")
        if (sequence >= DeviceFileControl.MAX_REVISION) DeviceFileControl.fail("file_control_native_scope_changed")
        if (!state.policyReady) DeviceFileControl.fail("file_control_policy_pending")
        return DeviceFileControlPacket(state.grants, sessionEpoch, ++sequence, remote?.challenge).also { pending = it }
    }

    @Synchronized fun markSent(packet: DeviceFileControlPacket) {
        val (_, state) = scope() ?: DeviceFileControl.fail("file_control_invalid_native_send_completion")
        if (!state.policyReady || packet !== pending || packet.grants != state.grants || packet.echo != remote?.challenge)
            DeviceFileControl.fail("file_control_invalid_native_send_completion")
        sentGrants = packet.grants; sentEcho = packet.echo; pending = null
    }

    @Synchronized fun needsPacket(): Boolean {
        val (_, state) = scope() ?: return false
        return state.policyReady && (sentGrants != state.grants || remote?.let { sentEcho != it.challenge } == true)
    }

    @Synchronized fun observeRemote(packet: DeviceFileControlPacket, boundPeer: NativeFileControlPeer): Boolean {
        if (scope() == null || !boundPeer.allowed || boundPeer.owner !== peer.owner || boundPeer.peerId != peer.peerId ||
            boundPeer.identitySha256 != peer.identitySha256) DeviceFileControl.fail("file_control_native_scope_changed")
        remote?.let { before ->
            val same = packet.sessionEpoch == before.sessionEpoch
            if (same && packet.sequence < before.sequence || packet.grants.revision < before.grants.revision)
                DeviceFileControl.fail("file_control_stale_packet")
            if (same && packet.sequence == before.sequence && packet != before ||
                packet.grants.revision == before.grants.revision && packet.grants.permissionWire() != before.grants.permissionWire()) {
                faulted = true; DeviceFileControl.fail("file_control_equivocation")
            }
            if (same && packet == before) return false
            if (!same || packet.grants.permissionWire() != before.grants.permissionWire() || 1 !in packet.grants.manifestVersions)
                configurations.values.forEach { it.invalidated = true }
        }
        remote = packet
        return true
    }

    private fun agreed(): Triple<NativeFileControlPeer, NativeLocalFileGrant, DeviceFileControlPacket>? {
        val (current, state) = scope() ?: return null
        val received = remote ?: return null
        val challenge = DeviceFileControlPacket(state.grants, sessionEpoch, 1, null).challenge
        if (!state.handlersReady || !state.policyReady || received.echo != challenge || sentGrants != state.grants || sentEcho != received.challenge ||
            1 !in state.grants.manifestVersions || 1 !in received.grants.manifestVersions) return null
        return Triple(current, state, received)
    }

    private fun permitted(senderIsLocal: Boolean): Pair<NativeFileControlPeer, String>? {
        val (current, state, received) = agreed() ?: return null
        if (!(if (senderIsLocal) state.grants.sendFiles && received.grants.receiveFiles else received.grants.sendFiles && state.grants.receiveFiles)) return null
        val entries = listOf(identity.deviceId to JsonArray(listOf(JsonPrimitive(identity.deviceId), JsonPrimitive(identity.identitySha256), state.grants.permissionWire())),
            current.peerId to JsonArray(listOf(JsonPrimitive(current.peerId), JsonPrimitive(current.identitySha256), received.grants.permissionWire())))
        val epoch = DeviceFileControl.digest("magnolie-file-permission-v1\u0000", JsonArray(entries.sortedBy { it.first }.map { it.second }))
        return current to epoch
    }

    /** Issued only from a fresh native authenticated own-PC configure command,
     * not from a remote Boolean. Allows source consent bootstrap while local
     * send-files is still OFF; it is not a photo read/send permission.
     */
    @Synchronized fun configurationTicket(): NativeFileConfigurationTicket {
        val (_, _, received) = agreed() ?: DeviceFileControl.fail("file_control_configuration_not_ready")
        if (!received.grants.receiveFiles || configurations.isNotEmpty()) DeviceFileControl.fail("file_control_configuration_not_ready")
        val now = monotonicMs()
        if (now < 0 || now > Long.MAX_VALUE - DeviceFileControl.MAX_TTL_MS) DeviceFileControl.fail("file_control_configuration_not_ready")
        return NativeFileConfigurationTicket().also {
            configurations[it] = ConfigurationScope(received.sessionEpoch, received.grants.permissionWire(), now, now + DeviceFileControl.MAX_TTL_MS)
        }
    }

    @Synchronized fun configurationAuthority(ticket: NativeFileConfigurationTicket): NativeGalleryConfigurer? {
        val configured = configurations[ticket] ?: return null
        if (configured.invalidated) return null
        val (current, state) = scope() ?: run { configured.invalidated = true; return null }
        val received = remote ?: return null
        val now = monotonicMs()
        if (!state.handlersReady || now < configured.issued || now >= configured.expires || received.sessionEpoch != configured.remoteEpoch ||
            !received.grants.receiveFiles || received.grants.permissionWire() != configured.permission ||
            1 !in received.grants.manifestVersions || 1 !in state.grants.manifestVersions) {
            configured.invalidated = true; return null
        }
        // Do not bind to local grant bytes/policyReady: this exact authorized
        // policy transaction intentionally changes them and temporarily fences
        // ordinary data I/O. The remote consent/native owner must stay current.
        val epoch = DeviceFileControl.digest("magnolie-file-configurer-v1\u0000", JsonObject(mapOf(
            "local_session" to JsonPrimitive(sessionEpoch), "remote_session" to JsonPrimitive(received.sessionEpoch),
            "peer_id" to JsonPrimitive(current.peerId), "peer_identity" to JsonPrimitive(current.identitySha256),
            "remote_permission" to configured.permission)))
        return NativeGalleryConfigurer(current.peerId, current.identitySha256, ticket, epoch, true,
            current.paired, current.ownDevice, current.remoteOwnDevice, current.pairingEpoch)
    }

    @Synchronized fun finishConfiguration(ticket: NativeFileConfigurationTicket) {
        if (configurations.remove(ticket) == null) DeviceFileControl.fail("file_control_foreign_configuration_ticket")
    }

    @Synchronized fun binding(destinationToken: String, senderIsLocal: Boolean = false): DeviceTransferBinding? {
        val (current, epoch) = permitted(senderIsLocal) ?: return null
        return if (senderIsLocal) DeviceTransferBinding(identity.deviceId, current.peerId, identity.identitySha256,
            current.identitySha256, epoch, destinationToken) else DeviceTransferBinding(current.peerId, identity.deviceId,
            current.identitySha256, identity.identitySha256, epoch, destinationToken)
    }

    /** Actual native receiver observation for Gallery/SAF scopes. Still no OS
     * READ permission: existing source authority must independently prove it.
     */
    @Synchronized fun photoReceiver(): NativePhotoReceiver? {
        val (current, epoch) = permitted(true) ?: return null
        return NativePhotoReceiver(current.peerId, current.identitySha256, this, epoch, true, current.paired,
            current.ownDevice, current.remoteOwnDevice, local.grants.sendFiles, remote!!.grants.receiveFiles, 1, current.pairingEpoch)
    }

    override fun close() {
        // Revocation must not wait behind a native metadata lookup. Keep the
        // bounded in-memory ticket map intact for exact finally-cleanup under
        // its ordinary monitor; none of these tickets can authorize after this
        // permanent flag, and no map is mutated concurrently from close().
        revoked.set(true)
    }
}
