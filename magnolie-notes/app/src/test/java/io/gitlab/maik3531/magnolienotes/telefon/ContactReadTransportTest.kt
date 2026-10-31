package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import io.gitlab.maik3531.magnolienotes.baum.KontaktGruppenProviderTest
import io.gitlab.maik3531.magnolienotes.baum.KontaktDaten
import io.gitlab.maik3531.magnolienotes.baum.KontaktWert
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.shadows.ShadowContentResolver
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

    @Test fun pythonWritesGroupsThroughActualNotesProviderAndReadsThemBack() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_contact_read_host.py"), groups = true)

    @Test fun windowsWritesGroupsThroughActualNotesProviderAndReadsThemBack() = runHost(listOf(
        System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
        System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--phone-contact-read-host"), groups = true)

    @Test fun pythonCanReadNativeGroupFailurePhasesWithoutWritingContacts() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_contact_read_host.py"), groups = true, probe = true)

    @Test fun pythonGroupProbeCannotBypassLocalDeveloperWifiOptIn() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_contact_read_host.py"), groups = true, probe = true, debugAllowed = false)

    @Test fun windowsCanReadNativeGroupFailurePhasesWithoutWritingContacts() = runHost(listOf(
        System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
        System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--phone-contact-read-host"), groups = true, probe = true)

    @Test fun pythonWritesPhoneAndEmailValuesThroughActualNotesProvider() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_contact_read_host.py"), values = true)

    @Test fun windowsWritesPhoneAndEmailValuesThroughActualNotesProvider() = runHost(listOf(
        System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
        System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--phone-contact-read-host"), values = true)

    @Test fun windowsRenamesTheSameNativeGroupAcrossItsMembers() = runHost(listOf(
        System.getenv("MAGNOLIE_DOTNET") ?: error("MAGNOLIE_DOTNET is required"),
        System.getenv("PHONE_TEST_WINDOWS_DLL") ?: error("PHONE_TEST_WINDOWS_DLL is required"), "--phone-contact-read-host"), titles = true)

    @Test fun pythonRecoversALostGroupTitleResultByNativeIdentity() = runHost(listOf(System.getenv("MAGNOLIE_PYTHON") ?: "python3",
        "../magnolie-organizer/pruefungen/phone_contact_read_host.py"), titles = true)

    private fun runHost(command: List<String>, groups: Boolean = false, probe: Boolean = false, debugAllowed: Boolean = true, values: Boolean = false, titles: Boolean = false) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val debug = io.gitlab.maik3531.magnolienotes.Entwicklermodus(context)
        debug.deaktivieren()
        if (probe && debugAllowed) { debug.aktivieren(); debug.wlanSetzen(true) }
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_CONTACTS)
        var groupProvider: KontaktGruppenProviderTest.GroupProvider? = null
        var groupContact: AndroidKontakt? = null
        var unrelated: AndroidKontakt? = null
        var automatic = 0L
        var contactMembers: Set<Long> = emptySet(); var otherMembers: Set<Long> = emptySet()
        var batchesBefore = 0
        if (groups || values || titles) {
            Shadows.shadowOf(context).grantPermissions(Manifest.permission.WRITE_CONTACTS)
            groupProvider = KontaktGruppenProviderTest.GroupProvider().also {
                it.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
                ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, it)
            }
            val contacts = AndroidKontakte(context, android.accounts.Account("fixture@example.test", "synthetic-provider"))
            groupContact = contacts.anlegen(KontaktDaten(vorname = "Preserve name", firma = "Preserve company", gruppen = listOf("Coworkers"),
                telefone = if (values) listOf(KontaktWert("mobil", "111")) else emptyList(),
                emailEintraege = if (values) listOf(KontaktWert("arbeit", "old@example.invalid")) else emptyList()))
            if (groups) {
                val overlay = AndroidKontakte(context, android.accounts.Account("messenger", "overlay-provider"))
                    .anlegen(KontaktDaten(vorname = "Linked messaging contact"))
                groupProvider.aggregate(overlay.rawContactId, groupContact.contactId)
            }
            unrelated = contacts.anlegen(KontaktDaten(vorname = "Unrelated", gruppen = listOf("Coworkers")))
            automatic = groupProvider.group("MY CONTACTS", "fixture@example.test", "synthetic-provider", automatic = true)
            groupProvider.member(groupContact.rawContactId, automatic)
            contactMembers = groupProvider.memberIds(groupContact.rawContactId)
            otherMembers = groupProvider.memberIds(unrelated.rawContactId)
            batchesBefore = groupProvider.batchCalls
            // The real Samsung report exposes fully readable groups while its
            // MIME hint is not recognized. Exercise that actual failure shape.
            groupProvider.groupsMime = null
        }
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
        storage.identity("Synthetic phone").second.fill(0)
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
                assertEquals(1, uids.size)
                val requested = uids.single()
                assertTrue(requested in (0 until 6).map { "fixture-%03d".format(it) })
                val card = ContactReadAndroid.vcard(AndroidKontakt(requested, requested.takeLast(3).toLong() + 1,
                    KontaktDaten(vorname = "Fixture", nachname = "Contact", telefone = listOf(KontaktWert("home", "+49123456789"))),
                    providerGeaendert = 1700000000000L), "", listOf(social)).replace("END:VCARD\r\n",
                    "PHOTO;ENCODING=b;TYPE=PNG:iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=\r\nEND:VCARD\r\n")
                return ContactRead.report(request, 1, listOf(buildJsonObject {
                    put("uid", JsonPrimitive(uids.single())); put("timestamp", JsonPrimitive(1700000000000L)); put("vcard", JsonPrimitive(card))
                }))
            }
        }
        work.contactReadSource = source
        val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
        val process = ProcessBuilder(command).apply {
            environment()["PHONE_TEST_DEVICE_ID"] = storage.identity("Synthetic phone").also { it.second.fill(0) }.first.device_id
            if (groups) environment()["PHONE_TEST_GROUP_UID"] = groupContact!!.lookupKey
            if (values) environment()["PHONE_TEST_VALUES_UID"] = groupContact!!.lookupKey
            if (titles) environment()["PHONE_TEST_GROUP_TITLE_UID"] = groupContact!!.lookupKey
            if (probe) environment()["PHONE_TEST_GROUP_PROBE"] = "1"
            if (probe && !debugAllowed) environment()["PHONE_TEST_PROBE_DENIED"] = "1"
        }.redirectError(ProcessBuilder.Redirect.INHERIT).start()
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
                                if (!groups && !injected && packet.string("kind") == "device_status.request" && body["version"] == JsonPrimitive(5)) {
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
                                    val outgoing = queue.outboxWireMessage(peerId, packet.string("message_id"))
                                    assertNotEquals("${packet}; queued_kind=${outgoing?.get("kind")}; queued_version=${(outgoing?.get("body") as? JsonObject)?.get("version")}", "rejected", packet.string("status"))
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
                    if (titles) {
                        assertEquals("Title writer must read the actual provider", 0, reads)
                        val actual = AndroidKontakte(context).liesRaw(groupContact!!.rawContactId)!!
                        assertEquals(listOf("Arbeit"), actual.daten.gruppen)
                        assertEquals(listOf("Arbeit"), AndroidKontakte(context).liesRaw(unrelated!!.rawContactId)!!.daten.gruppen)
                        assertEquals(contactMembers, groupProvider!!.memberIds(groupContact.rawContactId))
                        assertEquals(otherMembers, groupProvider.memberIds(unrelated.rawContactId))
                        assertEquals("Recovery inspection must not repeat the mutation", batchesBefore + 1, groupProvider.batchCalls)
                        assertEquals("Preserve name", actual.daten.vorname); assertEquals("Preserve company", actual.daten.firma)
                        assertTrue(automatic in groupProvider.memberIds(groupContact.rawContactId))
                    } else if (values) {
                        assertEquals("Value writer must read the actual provider", 0, reads)
                        val actual = AndroidKontakte(context).liesRaw(groupContact!!.rawContactId)!!
                        assertEquals(listOf(KontaktWert("mobil", "222")), actual.daten.telefone)
                        assertTrue(actual.daten.emailEintraege.isEmpty())
                        assertEquals("Preserve name", actual.daten.vorname); assertEquals("Preserve company", actual.daten.firma)
                        assertEquals(listOf("Coworkers"), actual.daten.gruppen)
                        assertEquals(listOf("Coworkers"), AndroidKontakte(context).liesRaw(unrelated!!.rawContactId)!!.daten.gruppen)
                    } else if (groups) {
                        assertEquals("Group writer must not use the synthetic contact-read source", 0, reads)
                        val actual = AndroidKontakte(context).liesRaw(groupContact!!.rawContactId)!!
                        assertEquals(if (probe) listOf("Coworkers") else emptyList<String>(), actual.daten.gruppen)
                        assertEquals("Preserve name", actual.daten.vorname)
                        assertEquals("Preserve company", actual.daten.firma)
                        assertEquals(listOf("Coworkers"), AndroidKontakte(context).liesRaw(unrelated!!.rawContactId)!!.daten.gruppen)
                        assertTrue(automatic in groupProvider!!.memberIds(groupContact.rawContactId))
                    } else {
                        assertTrue("An unsolicited contact response was not rejected", rejectedForged)
                        assertTrue("An expired contact response was not rejected", rejectedExpired)
                        assertEquals("Only two index pages and the six explicitly requested cards may be read", 8, reads)
                    }
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
            groupProvider?.shutdown()
        }
    }
}
