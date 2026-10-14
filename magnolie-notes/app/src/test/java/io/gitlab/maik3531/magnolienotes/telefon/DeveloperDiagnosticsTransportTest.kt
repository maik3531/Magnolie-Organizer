package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.Entwicklermodus
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.io.File
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.Socket
import java.security.Provider
import java.security.Security
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec

/** Real TCP/AES-GCM and production Notes receiver; no installed phone or user data. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class DeveloperDiagnosticsTransportTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun pythonReadsOnlyLocallyEnabledOwnWifiDiagnostics() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_developer_diagnostics_host.py"))

    @Test fun windowsReadsOnlyLocallyEnabledOwnWifiDiagnostics() = runHost(listOf(
        System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
        System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--phone-developer-read-host"))

    private fun runHost(command: List<String>) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("DeveloperReadFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("magnolie_developer", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        field(Ablage::class.java, "einzig").set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
        val storage = TelefonAblage.get(context)
        storage.identity("Synthetic phone")
        storage.setEnabled(true); storage.setPersonalSync(true, false, false, false, false)
        val peerId = "11111111-1111-4111-8111-111111111111"
        storage.savePeer(TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32)),
            capabilities_revision = 1, grants_revision = 1, own_device = true, remote_own_device = true))
        val developer = Entwicklermodus(context)
        repeat(10) { developer.versionAngeklickt() }; developer.wlanSetzen(true)
        val work = TelefonWerk.get(context)
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
        val failedPipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(ByteArray(0))
            override val output = ByteArrayOutputStream()
            override fun close() = Unit
        }
        val session = TelefonWerk::class.java.getDeclaredMethod("session", TelefonPeer::class.java,
            TelefonTransportArt::class.java, TelefonRoehre::class.java, String::class.java, String::class.java,
            Boolean::class.javaPrimitiveType, kotlin.jvm.functions.Function0::class.java).apply { isAccessible = true }
        assertTrue(runCatching { session.invoke(work, storage.peers().peer, TelefonTransportArt.WIFI,
            failedPipe, "", "", false, {}) }.isFailure)
        assertTrue("Production authentication failure was not recorded", developer.bericht()["events"]!!.jsonArray.any {
            it.jsonObject["stage"] == JsonPrimitive("failed") && it.jsonObject["failure"] == JsonPrimitive(true)
        })
        developer.ereignis("online", "wifi")
        val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
        val errors = File(context.cacheDir, "developer-host-stderr.log")
        errors.writeText("")
        val process = ProcessBuilder(command).redirectError(errors).start()
        var requests = 0
        var packetKind = "none"
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
                    @Suppress("UNCHECKED_CAST")
                    val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                    val originalSession = PersonalNoteSession()
                    sessions[channel] = originalSession
                    TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java)
                        .apply { isAccessible = true }.invoke(work, storage.peers().peer)
                    queue.queue(peerId, "personal_sync.settings", buildJsonObject {
                        put("format", JsonPrimitive(1)); put("own_device", JsonPrimitive(true))
                    }, 60_000)
                    val send = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java).apply { isAccessible = true }
                    val acknowledge = TelefonWerk::class.java.getDeclaredMethod("handleAck", String::class.java,
                        String::class.java, String::class.java, String::class.java).apply { isAccessible = true }
                    send.invoke(work, storage.peers().peer, channel)
                    var closed = false
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(50)
                    while (System.nanoTime() < deadline) {
                        val packet = channel.receive()
                        packetKind = (packet["kind"] as? JsonPrimitive)?.content ?: packet.string("type")
                        when (packet.string("type")) {
                            "message" -> {
                                TelefonNachrichten.validate(packet)
                                if (packet.string("kind") == "device_status.request" && (packet["body"] as JsonObject)["version"] == JsonPrimitive(11)) {
                                    requests++
                                    when (requests) {
                                        2 -> sessions[channel] = PersonalNoteSession()
                                        3 -> { sessions[channel] = originalSession; developer.deaktivieren() }
                                        4 -> {
                                            developer.aktivieren(); developer.wlanSetzen(true)
                                            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.BLUETOOTH to pipe)
                                        }
                                        5 -> {
                                            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
                                            storage.savePeer(storage.peers().peer!!.copy(own_device = false))
                                        }
                                    }
                                }
                                work.receiveMessage(storage.peers().peer!!, packet, channel, field(TelefonWerk::class.java, "pairingGeneration").getLong(work))
                            }
                            "ack" -> {
                                TelefonNachrichten.validateAck(packet)
                                acknowledge.invoke(work, peerId, packet.string("message_id"), packet.string("status"), packet.string("error"))
                            }
                            "ping" -> channel.send(buildJsonObject {
                                put("type", JsonPrimitive("pong")); put("ping_id", packet.getValue("ping_id")); put("sent_ms", packet.getValue("sent_ms"))
                            })
                            "close" -> {
                                channel.send(buildJsonObject { put("type", JsonPrimitive("close")); put("reason", JsonPrimitive("normal")) })
                                closed = true; break
                            }
                            else -> error("Unexpected developer fixture packet type: ${packet.string("type")}")
                        }
                        send.invoke(work, storage.peers().peer, channel)
                    }
                    assertTrue("Developer host did not finish", closed)
                    assertEquals(5, requests)
                }
            }
            assertTrue(process.waitFor(10, TimeUnit.SECONDS))
            assertEquals(output.readText(), 0, process.exitValue())
        } catch (error: Exception) {
            if (!process.waitFor(2, TimeUnit.SECONDS)) { process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS) }
            throw AssertionError("Developer fixture failed after $requests requests, packet $packetKind, host exit ${process.exitValue()}: " +
                errors.readText().take(8000), error)
        } finally {
            process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS)
            work.serviceStopped()
            (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).close()
            field(TelefonWerk::class.java, "instance").set(null, null)
            field(TelefonAblage::class.java, "instance").set(null, null)
            field(Ablage::class.java, "einzig").set(null, oldDocuments)
            Security.removeProvider(provider.name)
            errors.delete()
        }
    }
}
