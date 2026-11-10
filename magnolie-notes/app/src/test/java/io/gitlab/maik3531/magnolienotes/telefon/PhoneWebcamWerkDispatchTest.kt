package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.security.Provider
import java.security.Security
import java.util.UUID
import javax.crypto.spec.SecretKeySpec

/** Actual Werk routing with an admitted encrypted TCP parent. Admission is a
 * controlled native fixture; full signed handshake vectors are checked separately.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamWerkDispatchTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }
    private inner class Fixture : AutoCloseable {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("WebcamWerkFixture", 1.0, "Controlled AndroidKeyStore") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        val storage: TelefonAblage
        val work: TelefonWerk
        val listener = ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))
        val pipe = TelefonTcpRoehre("127.0.0.1", port = listener.localPort)
        val desktop = listener.accept().also { it.soTimeout = 3_000 }
        val parent = TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16) { 3 }, ByteArray(32) { 1 },
            ByteArray(4) { 4 }, ByteArray(32) { 2 }, ByteArray(4) { 5 })
        val session = PersonalNoteSession()
        val peer = TelefonPeer(UUID.randomUUID().toString(), "Controlled desktop", TelefonKrypto.b64(ByteArray(32) { 7 }),
            capabilities_revision = 5, remote_device_status_available = true, remote_device_status_versions = listOf(1, 24))
        var sent = 0L
        var received = 0L
        init {
            Security.insertProviderAt(provider, 1)
            context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
            context.deleteDatabase("magnolie_phone.db")
            field(Ablage::class.java, "einzig").set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
            storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java).apply { isAccessible = true }.newInstance(context)
            storage.identity("Controlled phone").second.fill(0)
            storage.setEnabled(true); storage.savePeer(peer)
            work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
                .apply { isAccessible = true }.newInstance(context, storage)
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
            field(TelefonWerk::class.java, "activeChannel").set(work, parent)
            @Suppress("UNCHECKED_CAST")
            (field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>)[parent] = session
        }
        fun receive(): JsonObject {
            val wire = TelefonRahmen.lesen(desktop.getInputStream(), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
            assertEquals(JsonPrimitive(received), wire["seq"])
            val cipher = java.util.Base64.getDecoder().decode(wire.string("ciphertext"))
            val clear = TelefonKrypto.entschluesseln(ByteArray(32) { 1 }, TelefonKrypto.nonce(ByteArray(4) { 4 }, received++),
                cipher, TelefonKanonisch.bytes(JsonObject(wire - "ciphertext")))
            return TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
        }
        fun deliver(payload: JsonObject) {
            val header = buildJsonObject {
                put("p", TelefonParameter.PROTOKOLL); put("sid", TelefonKrypto.b64(ByteArray(16) { 3 }))
                put("seq", sent); put("dir", "desktop_to_phone")
            }
            val encrypted = TelefonKrypto.verschluesseln(ByteArray(32) { 2 }, TelefonKrypto.nonce(ByteArray(4) { 5 }, sent++),
                TelefonKanonisch.bytes(payload), TelefonKanonisch.bytes(header))
            TelefonRahmen.schreiben(desktop.getOutputStream(), JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(encrypted)))))
            val message = parent.receive()
            if (message["type"] == JsonPrimitive("ack")) work.handleSessionAck(peer, message, session, 0, TelefonTransportArt.WIFI, parent)
            else work.receiveMessage(peer, message, parent, 0)
        }
        fun capabilities(revision: Long, supported: Boolean): JsonObject {
            val items = TelefonCapabilities.phase1().toMutableMap()
            items["device_status"] = TelefonCapability(true, "available", if (supported) listOf(1, 24) else listOf(1))
            return TelefonNachrichten.message("capabilities.update", TelefonNachrichten.capabilities(revision, items), 60_000)
        }
        fun runtime() = field(TelefonWerk::class.java, "webcamRuntime").get(work) as PhoneWebcamNotesRuntime?
        fun idleUntil(predicate: () -> Boolean) {
            val deadline = System.nanoTime() + 3_000_000_000L
            while (!predicate() && System.nanoTime() < deadline) { Shadows.shadowOf(Looper.getMainLooper()).idle(); Thread.sleep(5) }
            assertTrue(predicate())
        }
        override fun close() {
            val runtime = runtime()
            work.serviceStopped()
            if (runtime != null) idleUntil { runtime.isCompletelyStopped() }
            parent.close(); pipe.close(); desktop.close(); listener.close()
            field(Ablage::class.java, "einzig").set(null, oldDocuments)
            Security.removeProvider(provider.name)
        }
    }

    @Test fun savedV24CapabilityNeverStartsProbeOrPermissionWithoutFreshParentControl() {
        Fixture().use { f ->
            TelefonWerk::class.java.getDeclaredMethod("maybeStartWebcam").apply { isAccessible = true }.invoke(f.work)
            assertNull(f.runtime())
            f.desktop.soTimeout = 100
            assertThrows(SocketTimeoutException::class.java) { f.receive() }
        }
    }

    @Test fun freshEncryptedCapabilityUsesActualWerkDispatcherButBackgroundOfferCannotStartCapture() {
        Fixture().use { f ->
            f.deliver(f.capabilities(6, true))
            assertEquals(JsonPrimitive("accepted"), f.receive()["status"])
            val probeMessage = f.receive()
            val probe = probeMessage["body"] as JsonObject
            assertEquals(JsonPrimitive("probe"), probe["op"])
            val offer = JsonObject(probe + mapOf("op" to JsonPrimitive("offer"), "session" to JsonPrimitive("a".repeat(32)),
                "secret" to JsonPrimitive("b".repeat(64)), "port" to JsonPrimitive(24401), "muted" to JsonPrimitive(false), "front" to JsonPrimitive(false)))
            val offerMessage = TelefonNachrichten.message(PhoneWebcamControl.REPORT, offer, 60_000)
            f.deliver(offerMessage)
            assertEquals(JsonPrimitive("accepted"), f.receive()["status"])
            val runtime = checkNotNull(f.runtime())
            f.idleUntil { runtime.terminalFailure != null }
            val errorMessage = f.receive()
            assertEquals(JsonPrimitive("foreground_required"), (errorMessage["body"] as JsonObject)["reason"])
            f.deliver(TelefonNachrichten.ack(errorMessage.string("message_id"), "accepted", "none"))
            f.idleUntil { runtime.isCompletelyStopped() }
            assertFalse(f.pipe.isClosed)
            f.context.openOrCreateDatabase("magnolie_phone.db", Context.MODE_PRIVATE, null).use { db ->
                for (message in listOf(probeMessage, offerMessage, errorMessage)) for (table in listOf("outbox", "inbox", "dedupe")) {
                    db.rawQuery("SELECT COUNT(*) FROM $table WHERE message_id=?", arrayOf(message.string("message_id"))).use {
                        assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                    }
                }
            }
        }
    }

    @Test fun actualCapabilityWithdrawalRetiresOriginalProbeWithoutClosingHealthyParent() {
        Fixture().use { f ->
            f.deliver(f.capabilities(6, true)); f.receive()
            val probe = f.receive()
            val original = checkNotNull(f.runtime())
            f.deliver(f.capabilities(7, false))
            assertEquals(JsonPrimitive("accepted"), f.receive()["status"])
            f.idleUntil { original.isCompletelyStopped() }
            assertNull(f.runtime()); assertFalse(f.pipe.isClosed)
            f.deliver(TelefonNachrichten.ack(probe.string("message_id"), "rejected", "not_granted"))
            assertFalse(f.pipe.isClosed)
        }
    }

    @Test fun originalProbeWriterDoesNotAcquireWerkMonitorOrProtectedStorageDuringIo() {
        Fixture().use { f ->
            synchronized(f.work) {
                f.deliver(f.capabilities(6, true))
                assertEquals(JsonPrimitive("accepted"), f.receive()["status"])
                // The real control worker must publish its encrypted probe even
                // while this unrelated native caller retains Werk's monitor.
                assertEquals(JsonPrimitive("probe"), (f.receive()["body"] as JsonObject)["op"])
            }
            assertFalse(f.pipe.isClosed)
        }
    }
}
