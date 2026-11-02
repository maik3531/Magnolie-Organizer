package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Looper
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Explicit native I/O-lane join of actual protected policy, dedicated grants,
 * secure-channel controls and source workflow. Not a service/dispatcher: no
 * construction from a wire body, store/key generation, scanning, scheduling or
 * discovery advertisement. The caller supplies existing native identity/key,
 * private directory and authenticated current-peer/channel ownership.
 */
internal class NativeGalleryFileRuntime(context: Context, directory: File, identity: NativeFileControlIdentity,
    protection: DeviceTransferProtection, channel: TelefonSecureChannel, currentPeer: () -> NativeFileControlPeer?,
    handlersReady: () -> Boolean) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val ticket = AtomicReference<NativeFileConfigurationTicket?>()
    private val commandLive = AtomicReference<(() -> Boolean)?>()
    private val nativePeer = { if (closed.get()) null else currentPeer() }
    private val index = PhotoSourceJobIndex(directory, protection)
    private val grants = NativeGalleryFileGrantPolicy(nativePeer, { index.galleryPolicy() }, handlersReady)
    private val controls: NativeFileControlChannel
    private val workflow: NativeGalleryPhotoWorkflow

    init {
        var prepared: NativeFileControlChannel? = null
        try {
            prepared = NativeFileControlChannel(identity, channel, nativePeer, { grants.current() })
            controls = prepared
            workflow = NativeGalleryPhotoWorkflow.forAuthenticatedConfigurer(context, directory, identity.deviceId, protection,
                { if (closed.get()) null else controls.session.photoReceiver() },
                { if (commandLive.get()?.invoke() == false) null else ticket.get()?.let { controls.session.configurationAuthority(it) } })
        } catch (error: Exception) {
            closed.set(true); prepared?.close(); index.close()
            throw error // Dedicated metadata/cache is preserved, not reset.
        }
    }

    fun sendControls(now: Long = System.currentTimeMillis()): Boolean { ready(); return controls.sendIfNeeded(now) }
    fun observeControls(message: JsonObject, now: Long = System.currentTimeMillis()): Boolean { ready(); return controls.observe(message, now) }
    fun savedPolicy(): GalleryPhotoPolicySnapshot { ready(); return workflow.savedPolicy() }
    fun currentRequest(): NativeGalleryRequest? { ready(); return workflow.currentRequest() }
    fun attachPermissionHost(host: GalleryPhotoPermissionHost, onResult: (Result<GalleryReadCoverage>) -> Unit) {
        ready(); workflow.attachPermissionHost(host, onResult)
    }
    fun requestReadPermission() { ready(); workflow.requestReadPermission() }
    fun attachForeground(onResult: (Result<GalleryReadCoverage>) -> Unit): NativeGalleryForegroundOwner {
        ready(); return NativeGalleryForeground.attach(this, onResult)
    }

    /** Real source command execution, using a fresh native metadata ticket even
     * while initial local send consent is OFF. This never scans, requests OS
     * permissions or schedules a transfer. Replies are metadata, not SaveACKs.
     */
    @Synchronized fun receiveSourceCommand(message: JsonObject, send: (JsonObject) -> Unit,
        now: () -> Long = { System.currentTimeMillis() }) {
        ready()
        val command = DeviceFileSourceCommand.parse(message, now())
        val issued = controls.session.configurationTicket()
        if (!ticket.compareAndSet(null, issued)) {
            controls.session.finishConfiguration(issued)
            DeviceFileControl.fail("file_control_configuration_busy")
        }
        commandLive.set { now() < command.expires }
        fun authority(): NativeGalleryConfigurer {
            if (now() >= command.expires) DeviceFileControl.fail("file_sources_command_expired")
            return controls.session.configurationAuthority(issued) ?: DeviceFileControl.fail("file_sources_authority_changed")
        }
        try {
            val owner = authority()
            val before = workflow.savedPolicy()
            val saved = if (command.operation == "configure") {
                if (before.version != command.expectedVersion) DeviceFileControl.fail("gallery_policy_cas_conflict")
                authority()
                workflow.configure(before, command.enabled!!, command.kinds)
            } else before
            authority()
            val policy = saved.policy
            val associated = policy != null && policy.receiverId == owner.peerId && policy.receiverIdentitySha256 == owner.identitySha256 &&
                policy.pairingEpoch == owner.pairingEpoch
            val body = kotlinx.serialization.json.buildJsonObject {
                put("format", JsonPrimitive(1)); put("request_id", JsonPrimitive(command.requestId))
                put("operation", JsonPrimitive(command.operation)); put("version", JsonPrimitive(saved.version))
                put("revision", JsonPrimitive(policy?.revision ?: 0)); put("enabled", JsonPrimitive(policy?.enabled ?: false))
                put("associated", JsonPrimitive(associated)); put("repair_pending", JsonPrimitive(saved.repairPending))
                put("kinds", kotlinx.serialization.json.JsonArray((policy?.kinds ?: emptySet()).map { it.name.lowercase(java.util.Locale.ROOT) }
                    .sorted().map(::JsonPrimitive)))
            }
            val at = now()
            val reply = TelefonNachrichten.message(DeviceFileSourceCommand.RESULT, body,
                minOf(DeviceFileControl.MAX_TTL_MS, command.expires - at).also {
                    if (it <= 0) DeviceFileControl.fail("file_sources_command_expired")
                }, at)
            authority()
            send(reply) // Actual caller's secure send, never the personal queue.
            authority()
        } finally { commandLive.set(null); ticket.compareAndSet(issued, null); controls.session.finishConfiguration(issued) }
    }

    @Synchronized fun configureFromAuthenticatedCommand(expected: GalleryPhotoPolicySnapshot, enabled: Boolean,
        kinds: Set<GallerySourceKind>): GalleryPhotoPolicySnapshot {
        ready()
        val issued = controls.session.configurationTicket()
        if (!ticket.compareAndSet(null, issued)) {
            controls.session.finishConfiguration(issued)
            DeviceFileControl.fail("file_control_configuration_busy")
        }
        try { return workflow.configure(expected, enabled, kinds) }
        finally { ticket.compareAndSet(issued, null); controls.session.finishConfiguration(issued) }
    }

    @Synchronized fun disableLocally(expected: GalleryPhotoPolicySnapshot): GalleryPhotoPolicySnapshot {
        ready(); return workflow.disableLocally(expected)
    }

    /** Native channel-end path can revoke file authority synchronously on any
     * thread. Metadata/permission-host ownership remains held until actual UI
     * cleanup; this is not a worker-END or quota-retirement receipt.
     */
    @Synchronized fun revokeControl() { controls.close() }

    @Synchronized override fun close() {
        if (closed.get()) return
        revokeControl()
        // The workflow owns ActivityResult/lifecycle registration. Reject a
        // wrong-thread final close BEFORE claiming completed cleanup or closing
        // only half of the native resources. The native owner must then finish
        // close on the UI thread; authority is already synchronously revoked.
        if (Looper.myLooper() != Looper.getMainLooper()) DeviceFileControl.fail("gallery_permission_ui_thread_required")
        if (!closed.compareAndSet(false, true)) return
        ticket.set(null)
        NativeGalleryForeground.detach(this)
        try { workflow.close() } finally { index.close() }
    }

    private fun ready() { if (closed.get()) DeviceFileControl.fail("gallery_file_runtime_closed") }
}
