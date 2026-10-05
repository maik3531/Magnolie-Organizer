package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Zeiteintrag
import io.gitlab.maik3531.magnolienotes.daten.ZeiterfassungStand
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

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class TimeSyncTransportTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun pythonRuntimeAndNotesExchangeDurableTimeRecordsOverTheSecureChannel() {
        runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3", "../magnolie-organizer/pruefungen/time_sync_transport_host.py"))
    }

    @Test fun windowsRuntimeAndNotesExchangeDurableTimeRecordsOverTheSecureChannel() {
        runHost(listOf(System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
            System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--time-sync-host"))
    }

    private fun runHost(command: List<String>) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("TimeSyncFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        val key = SecretKeySpec(ByteArray(32) { 19 }, "AES")
        val documents = Ablage.fuerTest(context) { key }
        field(Ablage::class.java, "einzig").set(null, documents)
        documents.aendereZeiterfassung { ZeiterfassungStand(enabled = true).replace(null,
            Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC", note = "Phone time fixture")) }
        val originalNotes = documents.notizen(); val originalTasks = documents.aufgaben()
        val storage = TelefonAblage.get(context)
        storage.setEnabled(true); storage.setPersonalSync(true, false, false, false, false)
        val peerId = "11111111-1111-4111-8111-111111111111"
        storage.savePeer(TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32)),
            capabilities_revision = 1, grants_revision = 1, own_device = true,
            remote_personal_tasks_sync_available = true, remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4, 6, 7),
            personal_time_policy = TimeSyncProtokoll.newSettings(true)))
        val work = TelefonWerk.get(context)
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
        val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
        val process = ProcessBuilder(command)
            .redirectError(ProcessBuilder.Redirect.INHERIT).start()
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
                TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 },
                    ByteArray(4) { 12 }, ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                    val session = PersonalNoteSession()
                    @Suppress("UNCHECKED_CAST")
                    val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                    sessions[channel] = session
                    TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java)
                        .apply { isAccessible = true }.invoke(work, storage.peers().peer)
                    queue.queue(peerId, "personal_sync.settings", buildJsonObject { put("format", 1); put("own_device", true) }, 60000)
                    val send = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java).apply { isAccessible = true }
                    val receive = TelefonWerk::class.java.getDeclaredMethod("receiveMessage", TelefonPeer::class.java,
                        JsonObject::class.java, kotlin.jvm.functions.Function1::class.java, PersonalNoteSession::class.java).apply { isAccessible = true }
                    val acknowledge = TelefonWerk::class.java.getDeclaredMethod("handleAck", String::class.java,
                        String::class.java, String::class.java, String::class.java).apply { isAccessible = true }
                    send.invoke(work, storage.peers().peer, channel)
                    var closed = false
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(55)
                    while (System.nanoTime() < deadline) {
                        val packet = channel.receive()
                        when (packet.string("type")) {
                            "message" -> {
                                TelefonNachrichten.validate(packet)
                                receive.invoke(work, storage.peers().peer, packet, { reply: JsonObject ->
                                    val current = storage.peers().peer!!
                                    assertNotEquals("Rejected ${packet.string("kind")}: $reply; controls=" +
                                        "${session.capabilitiesReceived}/${session.grantsReceived}/${session.ownSettingsReceived}; " +
                                        "own=${current.own_device}/${current.remote_own_device}; " +
                                        "available=${current.remote_personal_tasks_sync_available}; versions=${current.remote_personal_tasks_sync_versions}; " +
                                        "received=${session.timeReceived != null}; failed=${field(TelefonWerk::class.java, "timePolicyFailed").get(work)}",
                                        "rejected", reply.string("status"))
                                    if (packet.string("kind") == TimeSyncProtokoll.BATCH) {
                                        val reopened = Ablage.fuerTest(context) { key }
                                        assertTrue(reopened.bestand.value.zeiterfassung.entries.any { it.note == "Desktop time fixture" })
                                        assertEquals("DE", reopened.bestand.value.zeiterfassung.calendar.country)
                                    }
                                    channel.send(reply); Unit
                                }, session)
                            }
                            "ack" -> {
                                TelefonNachrichten.validateAck(packet)
                                assertNotEquals(packet.toString(), "rejected", packet.string("status"))
                                acknowledge.invoke(work, peerId, packet.string("message_id"), packet.string("status"), packet.string("error"))
                            }
                            "ping" -> channel.send(buildJsonObject {
                                put("type", "pong"); put("ping_id", packet.getValue("ping_id")); put("sent_ms", packet.getValue("sent_ms"))
                            })
                            "close" -> { assertEquals("normal", packet.string("reason")); closed = true; break }
                            else -> error("Unexpected fixture packet: $packet")
                        }
                        send.invoke(work, storage.peers().peer, channel)
                    }
                    assertTrue("Native host did not complete", closed)
                    assertEquals(2, documents.bestand.value.zeiterfassung.entries.size)
                    assertEquals(originalNotes, documents.notizen()); assertEquals(originalTasks, documents.aufgaben())
                    assertEquals(JsonPrimitive(false), storage.peers().peer!!.remote_personal_time_policy!!["enabled"])
                }
            }
            assertTrue(process.waitFor(10, TimeUnit.SECONDS)); assertEquals(output.readText(), 0, process.exitValue())
        } finally {
            process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS); work.serviceStopped()
            (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).close()
            field(TelefonWerk::class.java, "instance").set(null, null); field(TelefonAblage::class.java, "instance").set(null, null)
            field(Ablage::class.java, "einzig").set(null, oldDocuments); Security.removeProvider(provider.name)
        }
    }
}
