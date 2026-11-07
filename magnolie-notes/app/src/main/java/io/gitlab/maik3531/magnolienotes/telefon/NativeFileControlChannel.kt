package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

internal object DeviceFileControlEnvelope {
    fun create(packet: DeviceFileControlPacket, now: Long = System.currentTimeMillis(),
        messageId: String = UUID.randomUUID().toString()): JsonObject {
        if (now !in 0..253_402_300_739_999L) DeviceFileControl.fail("file_control_invalid_time")
        return TelefonNachrichten.message(DeviceFileControl.KIND, packet.wire(), DeviceFileControl.MAX_TTL_MS, now, messageId)
            .also { validate(it, now) }
    }

    fun validate(message: JsonObject, now: Long = System.currentTimeMillis()): DeviceFileControlPacket {
        if (TelefonKanonisch.bytes(message).size > DeviceFileControl.MAX_WIRE_BYTES) DeviceFileControl.fail("file_control_envelope_too_large")
        TelefonNachrichten.validateHeader(message, now)
        if (message.string("kind") != DeviceFileControl.KIND ||
            message.long("expires_ms") - message.long("created_ms") > DeviceFileControl.MAX_TTL_MS ||
            now > message.long("expires_ms")) DeviceFileControl.fail("file_control_invalid_envelope")
        return DeviceFileControlPacket.parse(message["body"] as? JsonObject ?: DeviceFileControl.fail("file_control_invalid_envelope"))
    }
}

/** Exact actual secure-channel send/receive adapter. It is not registered or
 * advertised here and never constructs a store, source scanner or background
 * worker. The native owner supplies the current authenticated channel/peer.
 */
internal class NativeFileControlChannel(identity: NativeFileControlIdentity,
    private val channel: TelefonSecureChannel, private val currentPeer: () -> NativeFileControlPeer?,
    currentLocal: () -> NativeLocalFileGrant?, receiveHandlersReady: () -> Boolean = { false }) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private fun peer(): NativeFileControlPeer {
        if (closed.get()) DeviceFileControl.fail("file_control_native_channel_closed")
        return currentPeer()?.takeIf { it.allowed && it.owner === channel }
            ?: run { close(); DeviceFileControl.fail("file_control_native_channel_changed") }
    }
    val session = NativeFileControlSession(identity, currentPeer, currentLocal, receiveHandlersReady = receiveHandlersReady)
    init { peer() }

    @Synchronized fun sendIfNeeded(now: Long = System.currentTimeMillis()): Boolean {
        if (closed.get()) DeviceFileControl.fail("file_control_native_channel_closed")
        peer()
        if (!session.needsPacket()) return false
        val packet = session.packet()
        val message = DeviceFileControlEnvelope.create(packet, now)
        try {
            peer()
            channel.send(message) // Actual synchronous encrypted frame write.
            peer()
            session.markSent(packet) // Never before/after a failed/stale send.
            return true
        } catch (error: Exception) { close(); throw error }
    }

    @Synchronized fun observe(message: JsonObject, now: Long = System.currentTimeMillis()): Boolean {
        if (closed.get()) DeviceFileControl.fail("file_control_native_channel_closed")
        val nativePeer = peer()
        val packet = DeviceFileControlEnvelope.validate(message, now)
        val changed = session.observeRemote(packet, nativePeer)
        peer()
        return changed
    }

    override fun close() {
        if (closed.compareAndSet(false, true)) session.close()
        // This file adapter does not own the shared phone transport socket.
    }
}
