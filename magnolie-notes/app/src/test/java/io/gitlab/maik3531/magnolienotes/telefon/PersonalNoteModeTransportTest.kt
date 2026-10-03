package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.io.File
import java.net.Socket
import java.security.Provider
import java.security.Security
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec

/** Synthetic established-session keys; real Notes receiver, encrypted queue and documents. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class PersonalNoteModeTransportTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun pythonSecureRuntimeImportsPhoneNotesWithoutSendingDesktopNotesBack() {
        runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
            "../magnolie-organizer/pruefungen/personal_note_mode_transport_host.py"))
    }

    @Test fun windowsSecureRuntimeImportsPhoneNotesWithoutSendingDesktopNotesBack() {
        runHost(listOf(System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
            System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"),
            "--personal-note-mode-host"))
    }

    private fun runHost(command: List<String>) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("NoteDirectionFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        field(Ablage::class.java, "einzig").set(null, documents)
        val notebook = documents.legeNotizbuchAn("Field notes")
        documents.setzeNotiz(Notiz("phone-note", "Offline note", "Phone formatting", "<b>Phone formatting</b>",
            notizbuchId = notebook.id, angelegt = 1, geaendert = 2,
            anhaenge = listOf(Anhang("phone-file", "field.pdf", "pdf", "data:application/pdf;base64,JVBERi0xLjQK"))))
        val storage = TelefonAblage.get(context)
        storage.setEnabled(true); storage.setPersonalSync(true, true, true, false, false)
        val peerId = "11111111-1111-4111-8111-111111111111"
        storage.savePeer(TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32)),
            capabilities_revision = 1, grants_revision = 1,
            own_device = true, personal_notes_sync_granted = true, personal_tasks_sync_granted = true,
            remote_personal_notes_sync_available = true, remote_personal_notes_sync_versions = listOf(1, 2, 3, 5),
            remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4)))
        val work = TelefonWerk.get(context)
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
        val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
        val process = ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.INHERIT).start()
        try {
            val output = process.inputStream.bufferedReader()
            val port = CompletableFuture.supplyAsync { output.readLine().toInt() }.get(20, TimeUnit.SECONDS)
            Socket("127.0.0.1", port).use { socket ->
                socket.soTimeout = 25_000
                val pipe = object : TelefonRoehre {
                    override val input = socket.getInputStream()
                    override val output = socket.getOutputStream()
                    override fun close() = Unit
                }
                field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
                TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 },
                    ByteArray(32) { 11 }, ByteArray(4) { 12 }, ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                    val session = PersonalNoteSession()
                    @Suppress("UNCHECKED_CAST")
                    val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                    sessions[channel] = session
                    TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java)
                        .apply { isAccessible = true }.invoke(work, storage.peers().peer)
                    queue.queue(peerId, "personal_sync.settings", buildJsonObject {
                        put("format", JsonPrimitive(1)); put("own_device", JsonPrimitive(true))
                    }, 60_000)
                    val send = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java)
                        .apply { isAccessible = true }
                    val receive = TelefonWerk::class.java.getDeclaredMethod("receiveMessage", TelefonPeer::class.java,
                        JsonObject::class.java, kotlin.jvm.functions.Function1::class.java, PersonalNoteSession::class.java)
                        .apply { isAccessible = true }
                    val acknowledge = TelefonWerk::class.java.getDeclaredMethod("handleAck", String::class.java,
                        String::class.java, String::class.java, String::class.java).apply { isAccessible = true }
                    send.invoke(work, storage.peers().peer, channel)
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(45)
                    var closed = false
                    while (System.nanoTime() < deadline) {
                        val packet = channel.receive()
                        when (packet.string("type")) {
                            "message" -> {
                                TelefonNachrichten.validate(packet)
                                receive.invoke(work, storage.peers().peer, packet, { reply: JsonObject ->
                                    if (reply.string("type") == "ack") assertNotEquals("Rejected ${packet.string("kind")}: $reply", "rejected", reply.string("status"))
                                    channel.send(reply); Unit
                                }, session)
                            }
                            "ack" -> {
                                TelefonNachrichten.validateAck(packet)
                                val pending = queue.due(peerId, TelefonTransportArt.WIFI, System.currentTimeMillis() + 2_000)
                                    .firstOrNull { it.messageId == packet.string("message_id") }?.payload
                                assertNotEquals("$packet for $pending", "rejected", packet.string("status"))
                                acknowledge.invoke(work, peerId, packet.string("message_id"), packet.string("status"), packet.string("error"))
                            }
                            "ping" -> {
                                TelefonNachrichten.validateHeartbeat(packet)
                                channel.send(buildJsonObject {
                                    put("type", JsonPrimitive("pong")); put("ping_id", packet.getValue("ping_id")); put("sent_ms", packet.getValue("sent_ms"))
                                })
                            }
                            "close" -> { assertEquals("normal", packet.string("reason")); closed = true; break }
                            else -> error("Unexpected fixture packet: $packet")
                        }
                        send.invoke(work, storage.peers().peer, channel)
                    }
                    assertTrue("Native host did not complete", closed)
                    val peer = storage.peers().peer!!
                    assertTrue(session.ready(peer.personal_note_policy, peer.remote_personal_note_policy))
                    assertTrue(PersonalNoteMode.importing(peer.personal_note_policy, peer.remote_personal_note_policy))
                    assertTrue(peer.remote_desktop_features!!.long("revision") >= 2)
                    assertFalse(PersonalDesktopFeatures.customAvailable(peer))
                    assertFalse(PersonalDesktopFeatures.treeVisible(peer, independent = false, pending = false))
                    assertEquals(listOf("phone-note"), documents.notizen().map { it.id })
                    assertEquals("Phone formatting", documents.notizen().single().text)
                    assertEquals(1, documents.notizen().single().anhaenge.size)
                }
            }
            assertTrue(process.waitFor(10, TimeUnit.SECONDS))
            assertEquals(output.readText(), 0, process.exitValue())
        } finally {
            process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS)
            work.serviceStopped()
            (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).close()
            field(TelefonWerk::class.java, "instance").set(null, null)
            field(TelefonAblage::class.java, "instance").set(null, null)
            field(Ablage::class.java, "einzig").set(null, oldDocuments)
            Security.removeProvider(provider.name)
        }
    }
}
