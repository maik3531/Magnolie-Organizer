package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.KontaktDaten
import io.gitlab.maik3531.magnolienotes.baum.KontaktWert
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.io.File
import java.net.Socket
import java.security.Provider
import java.security.Security
import java.util.UUID
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec

/** Actual Notes authorization/dispatcher and desktop readers; synthetic contact source. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class ContactReadTransportTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun pythonReadsOnlyAuthorizedPhoneContacts() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_contact_read_host.py"))

    @Test fun windowsReadsOnlyAuthorizedPhoneContacts() = runHost(listOf(
        System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
        System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--phone-contact-read-host"))

    private fun runHost(command: List<String>) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS)
        val provider = object : Provider("ContactReadFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        field(Ablage::class.java, "einzig").set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
        val storage = TelefonAblage.get(context)
        storage.setEnabled(true); storage.setPersonalSync(true, false, false, false, false)
        val peerId = "11111111-1111-4111-8111-111111111111"
        storage.savePeer(TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32)),
            capabilities_revision = 1, grants_revision = 1, own_device = true, remote_own_device = true, contacts_read_enabled = true))
        val work = TelefonWerk.get(context)
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
        var reads = 0
        val source = object : ContactReadSource {
            override fun permission() = true
            override fun read(request: JsonObject): JsonObject {
                reads++
                val uids = ContactRead.validateRequest(request)
                if (request.string("action") == "index") return ContactRead.report(request, 130,
                    (0 until 130).drop(request.long("offset").toInt()).take(ContactRead.PAGE_SIZE).map { index ->
                        buildJsonObject { put("uid", JsonPrimitive("fixture-%03d".format(index))); put("timestamp", JsonPrimitive(1700000000000L)) }
                    })
                val social = ContactReadAndroid.messenger("vnd.android.cursor.item/vnd.com.whatsapp.profile", "49123456789@s.whatsapp.net", "", "")!!
                val card = ContactReadAndroid.vcard(AndroidKontakt("fixture-000", 1,
                    KontaktDaten(vorname = "Fixture", nachname = "Contact", telefone = listOf(KontaktWert("home", "+49123456789"))),
                    providerGeaendert = 1700000000000L), "", listOf(social)).replace("END:VCARD\r\n",
                    "PHOTO;ENCODING=b;TYPE=PNG:iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=\r\nEND:VCARD\r\n")
                assertEquals(listOf("fixture-000"), uids)
                return ContactRead.report(request, 1, listOf(buildJsonObject {
                    put("uid", JsonPrimitive(uids.single())); put("timestamp", JsonPrimitive(1700000000000L)); put("vcard", JsonPrimitive(card))
                }))
            }
        }
        work.contactReadSource = source
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
                    @Suppress("UNCHECKED_CAST")
                    val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                    sessions[channel] = PersonalNoteSession()
                    TelefonWerk::class.java.getDeclaredMethod("ensureControlMessages", TelefonPeer::class.java)
                        .apply { isAccessible = true }.invoke(work, storage.peers().peer)
                    queue.queue(peerId, "personal_sync.settings", buildJsonObject {
                        put("format", JsonPrimitive(1)); put("own_device", JsonPrimitive(true))
                    }, 60_000)
                    val send = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java).apply { isAccessible = true }
                    val acknowledge = TelefonWerk::class.java.getDeclaredMethod("handleAck", String::class.java,
                        String::class.java, String::class.java, String::class.java).apply { isAccessible = true }
                    send.invoke(work, storage.peers().peer, channel)
                    val forgedId = UUID.randomUUID().toString()
                    val expiredId = UUID.randomUUID().toString()
                    var injected = false; var rejectedForged = false; var rejectedExpired = false; var closed = false
                    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(45)
                    while (System.nanoTime() < deadline) {
                        val packet = channel.receive()
                        when (packet.string("type")) {
                            "message" -> {
                                TelefonNachrichten.validate(packet)
                                val body = packet["body"] as JsonObject
                                if (!injected && packet.string("kind") == "device_status.request" && body["version"] == JsonPrimitive(5)) {
                                    injected = true
                                    val unsolicited = ContactRead.report(JsonObject(body + ("request_id" to JsonPrimitive(UUID.randomUUID().toString()))), 0, emptyList())
                                    channel.send(TelefonNachrichten.message("device_status.report", unsolicited, 60_000, id = forgedId))
                                    channel.send(TelefonNachrichten.message("device_status.report", ContactRead.report(body, 0, emptyList()),
                                        1000, now = System.currentTimeMillis() - 1001, id = expiredId))
                                }
                                work.receiveMessage(storage.peers().peer!!, packet, channel, field(TelefonWerk::class.java, "pairingGeneration").getLong(work))
                            }
                            "ack" -> {
                                TelefonNachrichten.validateAck(packet)
                                if (packet.string("message_id") == forgedId) {
                                    assertEquals("rejected", packet.string("status")); assertEquals("not_granted", packet.string("error")); rejectedForged = true
                                } else if (packet.string("message_id") == expiredId) {
                                    assertEquals("rejected", packet.string("status")); assertEquals("expired", packet.string("error")); rejectedExpired = true
                                } else {
                                    assertNotEquals(packet.toString(), "rejected", packet.string("status"))
                                    acknowledge.invoke(work, peerId, packet.string("message_id"), packet.string("status"), packet.string("error"))
                                }
                            }
                            "ping" -> channel.send(buildJsonObject {
                                put("type", JsonPrimitive("pong")); put("ping_id", packet.getValue("ping_id")); put("sent_ms", packet.getValue("sent_ms"))
                            })
                            "close" -> { closed = true; break }
                            else -> error("Unexpected contact fixture packet: $packet")
                        }
                        send.invoke(work, storage.peers().peer, channel)
                    }
                    assertTrue("Native contact host did not finish", closed)
                    assertTrue("An unsolicited contact response was not rejected", rejectedForged)
                    assertTrue("An expired contact response was not rejected", rejectedExpired)
                    assertEquals("Only two index pages and the requested card may be read", 3, reads)
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
