package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.Provider
import java.security.Security
import java.util.Base64
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class TimeControlRuntimeTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }
    private class Fixture(val context: Context, val documents: Ablage, val storage: TelefonAblage, val work: TelefonWerk,
                          val peer: TelefonPeer, val session: PersonalNoteSession, val channel: TelefonSecureChannel,
                          val output: ByteArrayOutputStream, val pipe: TelefonRoehre,
                          val transportCurrent: AtomicReference<() -> Boolean>) {
        fun receive(body: JsonObject, target: TelefonPeer = peer, generation: Long = 0): JsonObject? {
            work.receiveMessage(target, TelefonNachrichten.message(TimeControlProtokoll.REQUEST, body, 60000), channel, generation)
            val replies = frames()
            if (replies.isEmpty()) return null
            return replies.single().let { wire ->
                assertEquals(TimeControlProtokoll.REPORT, wire.string("kind")); TelefonNachrichten.validate(wire)
                wire.getValue("body").jsonObject
            }
        }
        fun frames(): List<JsonObject> {
            val input = ByteArrayInputStream(output.toByteArray()); output.reset()
            return buildList {
                while (input.available() > 0) {
                    val envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
                    val header = JsonObject(envelope - "ciphertext")
                    val clear = TelefonKrypto.entschluesseln(ByteArray(32) { 11 }, TelefonKrypto.nonce(ByteArray(4) { 12 }, envelope.long("seq")),
                        Base64.getDecoder().decode(envelope.string("ciphertext")), TelefonKanonisch.bytes(header))
                    try { add(TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject) }
                    finally { clear.fill(0) }
                }
            }
        }
        fun read() = receive(TimeControlProtokoll.request(UUID.randomUUID().toString()))!!
        fun command(action: String, state: JsonObject, id: String = "") = ZeitSteuerBefehl(UUID.randomUUID().toString(), action, state.string("revision"), id)
        fun execute(command: ZeitSteuerBefehl, epoch: String = documents.baum.value.syncEpoch) =
            receive(TimeControlProtokoll.request(UUID.randomUUID().toString(), epoch, command))!!
    }
    private fun fixture(action: (Fixture) -> Unit) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("TimerControlFixture", 1.0, "Synthetic keys") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        val oldStorage = field(TelefonAblage::class.java, "instance").get(null)
        val oldWork = field(TelefonWerk::class.java, "instance").get(null)
        val oldDocuments = field(Ablage::class.java, "einzig").get(null)
        field(TelefonAblage::class.java, "instance").set(null, null); field(TelefonWerk::class.java, "instance").set(null, null)
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        field(Ablage::class.java, "einzig").set(null, documents)
        val storage = TelefonAblage.get(context); storage.identity("Native fixture").second.fill(0)
        storage.setEnabled(true); storage.setPersonalSync(true, false, false, false, false)
        val peer = TelefonPeer("22222222-2222-4222-8222-222222222222", "Owned desktop", TelefonKrypto.b64(ByteArray(32) { 23 }),
            own_device = true, remote_own_device = true, remote_personal_tasks_sync_available = true,
            remote_personal_tasks_sync_versions = listOf(7, 13), personal_time_policy = TimeSyncProtokoll.newSettings(true),
            remote_personal_time_policy = TimeSyncProtokoll.newSettings(true))
        storage.savePeer(peer)
        val work = TelefonWerk.get(context)
        field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
        (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
        val wireOutput = ByteArrayOutputStream()
        val transportCurrent = AtomicReference<() -> Boolean>({ true })
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(ByteArray(0))
            override val output = wireOutput
            override fun aktuell() = transportCurrent.get().invoke()
            override fun close() {}
        }
        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
        try {
            documents.aendereZeiterfassung { ZeiterfassungStand(enabled = true) }
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                bindSyntheticPhoneSession(work, channel)
                val session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                    timeSent = peer.personal_time_policy; timeReceived = peer.remote_personal_time_policy }
                @Suppress("UNCHECKED_CAST")
                (field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>)[channel] = session
                action(Fixture(context, documents, storage, work, peer, session, channel, wireOutput, pipe, transportCurrent))
            }
        } finally {
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, false)
            field(TelefonWerk::class.java, "activeChannel").set(work, null)
            field(TelefonWerk::class.java, "activeTransport").set(work, null)
            field(TelefonWerk::class.java, "instance").set(null, oldWork)
            field(TelefonAblage::class.java, "instance").set(null, oldStorage)
            field(Ablage::class.java, "einzig").set(null, oldDocuments)
            Security.removeProvider(provider.name)
        }
    }

    @Test fun headerSyncRequiresLiveManualRouteAndRejectsStaleSelection() = fixture { f ->
        val queue = field(TelefonWerk::class.java, "queue").get(f.work) as TelefonQueue
        fun ready() = f.work.run { refreshModules(); state.value.personalHeaderSyncReady }
        fun queued() = queue.hasKind(f.peer.device_id, TimeSyncProtokoll.REQUEST)
        f.session.timeReceived = null
        assertFalse(ready())
        f.work.personalHeaderSyncNow(f.peer)
        assertFalse(queued())
        f.session.timeReceived = f.peer.remote_personal_time_policy
        assertTrue(ready())

        // A still-rendered enabled action does not survive a dead original pipe.
        f.transportCurrent.set { false }
        f.work.personalHeaderSyncNow(f.peer)
        assertFalse(f.work.state.value.personalHeaderSyncReady)
        assertFalse(queued())
        f.transportCurrent.set { true }
        field(TelefonWerk::class.java, "activeTransport").set(f.work, TelefonTransportArt.BLUETOOTH to f.pipe)
        assertTrue(ready())
        f.work.personalHeaderSyncNow(f.peer.copy(static_public = TelefonKrypto.b64(ByteArray(32) { 24 })))
        assertFalse(queued())

        f.storage.setPersonalSync(true, false, false, true, false)
        assertFalse(ready())
        f.work.personalHeaderSyncNow(f.peer)
        assertFalse(queued())
        f.storage.setPersonalSync(true, false, false, false, false)
        assertTrue(ready())
        // The outbox is the production queue; the fixture supplies no remote pong loop.
        (field(TelefonWerk::class.java, "scopedWakeup").get(f.work) as AtomicBoolean).set(true)
        f.work.personalHeaderSyncNow(f.peer)
        assertTrue(queued())
        assertFalse(queue.hasKind(f.peer.device_id, "personal_sync.request"))
    }

    @Test fun headerSyncRequiresAgreedManualModeAndRejectsConnectionMode() = fixture { f ->
        val peer = f.peer.copy(remote_personal_notes_sync_available = true,
            remote_personal_notes_sync_versions = listOf(SharedSyncSettings.VERSION),
            remote_personal_tasks_sync_versions = f.peer.remote_personal_tasks_sync_versions + SharedSyncSettings.VERSION)
        f.storage.savePeer(peer)
        (field(TelefonWerk::class.java, "scopedWakeup").get(f.work) as AtomicBoolean).set(true)
        val initial = SharedSyncSettings.effective(SharedSyncSettings.create(peer.device_id)) +
            mapOf("auto_mode" to JsonPrimitive("manual"), "skip_deletions" to JsonPrimitive(!peer.personal_deletions_sync_granted))
        val manual = f.work.configureCommonPreferences(peer.device_id, peer.static_public, initial)
        assertFalse(f.work.state.value.personalHeaderSyncReady)
        f.session.sharedSent = manual
        f.session.sharedReceived = manual
        f.work.refreshModules()
        assertTrue(f.work.state.value.personalHeaderSyncReady)

        val connection = f.work.configureCommonPreferences(peer.device_id, peer.static_public, initial,
            "auto_mode", JsonPrimitive("connection"))
        f.session.sharedSent = connection
        f.session.sharedReceived = connection
        f.work.refreshModules()
        assertFalse(f.work.state.value.personalHeaderSyncReady)
        f.work.personalHeaderSyncNow(peer)
        val queue = field(TelefonWerk::class.java, "queue").get(f.work) as TelefonQueue
        assertFalse(queue.hasKind(peer.device_id, TimeSyncProtokoll.REQUEST))
    }

    @Test fun automaticTimeWaitsForTheSharedWifiEchoWithoutOtherModules() = exerciseAutomaticTime("late")
    @Test fun automaticTimeDoesNotSendQueuedFramesAfterManualSelection() = exerciseAutomaticTime("manual")
    @Test fun automaticTimeCannotStartOnBluetooth() = exerciseAutomaticTime("bluetooth")
    @Test fun automaticTimeCannotStartFromARetiredWifiReader() = exerciseAutomaticTime("retired")
    @Test fun automaticTimeCannotStartWhenTimeIsOff() = exerciseAutomaticTime("off")

    private fun exerciseAutomaticTime(mode: String) = fixture { f ->
        val peer = f.peer.copy(remote_personal_notes_sync_available = true,
            remote_personal_notes_sync_versions = listOf(SharedSyncSettings.VERSION),
            remote_personal_tasks_sync_versions = f.peer.remote_personal_tasks_sync_versions + SharedSyncSettings.VERSION)
        f.storage.savePeer(peer)
        (field(TelefonWerk::class.java, "scopedWakeup").get(f.work) as AtomicBoolean).set(true)
        val actor = f.storage.identity("Native fixture").let { (identity, key) -> key.fill(0); identity.device_id }
        val initial = SharedSyncSettings.effective(SharedSyncSettings.create(peer.device_id)) + mapOf(
            "auto_mode" to JsonPrimitive("wifi"), "time_enabled" to JsonPrimitive(mode != "off"))
        val local = f.work.configureCommonPreferences(peer.device_id, peer.static_public, initial)
        val agreed = SharedSyncSettings.merge(SharedSyncSettings.create(peer.device_id, initial), local, peer.device_id, actor)
        val entry = Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC",
            clock = mapOf(actor to 1L), note = "Independent WLAN time")
        f.documents.aendereZeiterfassung { it.copy(actor = actor, counter = 1L, entries = listOf(entry)) }
        val transport = if (mode == "bluetooth") TelefonTransportArt.BLUETOOTH else TelefonTransportArt.WIFI
        field(TelefonWerk::class.java, "activeTransport").set(f.work, transport to f.pipe)
        val pump = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java,
            Long::class.javaPrimitiveType, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
        fun advance() { pump.invoke(f.work, peer, f.channel, 0L, false) }
        fun observe(settings: JsonObject) =
            f.work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, settings, 60000), f.channel, 0)
        val queue = field(TelefonWerk::class.java, "queue").get(f.work) as TelefonQueue
        val timeKinds = setOf(TimeSyncProtokoll.BATCH, TimeSyncProtokoll.REQUEST)
        fun timeFrames() = f.frames().filter { it["kind"]?.jsonPrimitive?.content in timeKinds }
        if (mode == "late") {
            advance()
            assertFalse("Unconfirmed shared settings staged a V7 request", queue.hasKind(peer.device_id, TimeSyncProtokoll.REQUEST))
            assertTrue(timeFrames().isEmpty())
        }
        observe(agreed)
        if (mode == "retired") field(TelefonWerk::class.java, "activeChannel").set(f.work, null)
        if (mode == "manual") {
            advance()
            timeFrames()
            assertTrue(queue.hasKind(peer.device_id, TimeSyncProtokoll.REQUEST))
            observe(SharedSyncSettings.change(agreed, peer.device_id, actor, "auto_mode", JsonPrimitive("manual")))
        }
        repeat(2) { advance() }
        val sent = timeFrames()
        if (mode != "late") {
            assertTrue(sent.isEmpty())
            return@fixture
        }
        val byKind = sent.associateBy { it.string("kind") }
        assertEquals(timeKinds, byKind.keys)
        assertEquals(2, sent.size)
        sent.forEach { packet ->
            assertEquals("auto_wifi", packet.getValue("body").jsonObject.string("trigger"))
            assertEquals("wifi_only", queue.outboxPolicy(peer.device_id, packet.string("message_id")))
            f.work.handleSessionAck(peer, TelefonNachrichten.ack(packet.string("message_id"), "accepted", "none"),
                f.session, 0, transport, f.channel)
        }
        val exported = TimeSyncProtokoll.decodeRecords(byKind.getValue(TimeSyncProtokoll.BATCH).getValue("body").jsonObject,
            fromOrganizer = false)
        assertEquals(entry.id, exported.single().id)
        assertFalse(queue.hasActiveAutoRun(peer.device_id))
        assertFalse(queue.hasKind(peer.device_id, "personal_sync.custom_request"))
        repeat(3) { advance() }
        assertTrue(timeFrames().isEmpty())
    }

    @Test fun sourceBoundCommandsUseActualEncryptedWriterAndNativeLifecycle() = fixture { f ->
        val read = f.read(); assertEquals(JsonPrimitive(false), read["persisted"])
        val start = f.command("start", read).copy(activity = "Actual native timer control")
        val started = f.execute(start); assertEquals(JsonPrimitive(true), started["persisted"])
        val bytes = File(f.context.filesDir, "notizen.json").readBytes()
        assertEquals("duplicate", f.execute(start).string("status"))
        assertArrayEquals(bytes, File(f.context.filesDir, "notizen.json").readBytes())
        val paused = f.execute(f.command("pause", f.read(), start.operationId)); assertEquals(JsonPrimitive(true), paused["paused"])
        val resumed = f.execute(f.command("resume", f.read(), start.operationId)); assertEquals(JsonPrimitive(false), resumed["paused"])
        val done = f.execute(f.command("finish", f.read(), start.operationId)); assertTrue(done.getValue("entries").jsonArray.isEmpty())
        assertEquals(4, f.documents.bestand.value.zeiterfassung.controlReceipts.size)
        val reopened = Ablage.fuerTest(f.context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        assertEquals(f.documents.bestand.value.zeiterfassung, reopened.bestand.value.zeiterfassung)
    }

    @Test fun unsupportedControlsAndUnpairDoNotLeakOrWriteTimerData() = fixture { f ->
        val before = f.documents.bestand.value
        f.work.sharedLocalCapabilities = { TelefonCapabilities.phase1().mapValues { (name, value) ->
            if (name == "personal_tasks_sync") value.copy(versions = value.versions - TimeControlProtokoll.VERSION) else value } }
        val rejected = f.read(); assertEquals("unsupported_feature", rejected.string("error")); assertEquals("", rejected.string("revision"))
        f.storage.savePeer(f.peer.copy(remote_own_device = false))
        assertEquals("unsupported_feature", f.read().string("error"))
        f.storage.savePeer(null)
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString())))
        assertEquals(before, f.documents.bestand.value)
    }

    @Test fun completedPairingKeepsTimerReadAvailableDespiteLegacyOwnFlags() = fixture { f ->
        val before = f.documents.bestand.value
        f.storage.savePeer(f.peer.copy(own_device = false, remote_own_device = false))
        val report = f.read()
        assertEquals(JsonPrimitive(false), report["persisted"])
        assertTrue(report.string("revision").isNotBlank())
        assertEquals(before, f.documents.bestand.value)
    }

    @Test fun wrongChannelGenerationKeyAndStaleTimerRevisionCannotExecute() = fixture { f ->
        val initial = f.read(); val start = f.command("start", initial)
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString()), generation = 1))
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString()), f.peer.copy(static_public = TelefonKrypto.b64(ByteArray(32) { 24 }))))
        f.execute(start)
        val stale = f.execute(f.command("pause", initial, start.operationId)); assertEquals("conflict", stale.string("error"))
        val wrong = f.execute(f.command("pause", f.read(), UUID.randomUUID().toString())); assertEquals("conflict", wrong.string("error"))
        assertNull(f.documents.bestand.value.zeiterfassung.entries.single().pauseMinute)
        f.session.timeReceived = null
        assertEquals("not_granted", f.execute(f.command("finish", initial, start.operationId)).string("error"))
        f.session.ownSettingsReceived = false
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString())))
    }

    @Test fun revokedTransportRejectsDecodedTimerCommandsBeforeDispatch() = fixture { f ->
        val state = f.read()
        val before = File(f.context.filesDir, "notizen.json").readBytes()
        val command = f.command("start", state)
        f.transportCurrent.set { false }
        assertFalse(f.work.sessionTransportAktuell(f.channel, 0))
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString(), f.documents.baum.value.syncEpoch, command)))
        assertArrayEquals(before, File(f.context.filesDir, "notizen.json").readBytes())
        assertTrue(f.documents.bestand.value.zeiterfassung.controlReceipts.isEmpty())
    }

    @Test fun permissionLostAtActualBookWriterDoesNotCommitAnEarlierDecodedCommand() = fixture { f ->
        val state = f.read()
        val before = File(f.context.filesDir, "notizen.json").readBytes()
        val command = f.command("start", state)
        // Dispatch is still valid. The native book gate observes the later
        // revocation, after parsing and waiting for the actual writer lock.
        f.transportCurrent.set { !Thread.holdsLock(Ablage.SCHREIBSPERRE) }
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString(), f.documents.baum.value.syncEpoch, command)))
        assertArrayEquals(before, File(f.context.filesDir, "notizen.json").readBytes())
        assertTrue(f.documents.bestand.value.zeiterfassung.controlReceipts.isEmpty())
    }

    @Test fun aReplacementPipeCannotReviveTheOldSecureChannel() = fixture { f ->
        assertTrue(f.work.sessionTransportAktuell(f.channel, 0))
        val replacement = object : TelefonRoehre {
            override val input = ByteArrayInputStream(ByteArray(0))
            override val output = ByteArrayOutputStream()
            override fun close() {}
        }
        field(TelefonWerk::class.java, "activeTransport").set(f.work, TelefonTransportArt.BLUETOOTH to replacement)
        assertFalse(f.work.sessionTransportAktuell(f.channel, 0))
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString())))
        field(TelefonWerk::class.java, "activeTransport").set(f.work, TelefonTransportArt.WIFI to f.pipe)
    }

    @Test fun aTimeSyncImportRechecksItsSourceInsideTheNativeWriter() = fixture { f ->
        val entry = Zeiteintrag(startMinute = 1000, endMinute = 1060, zone = "UTC",
            clock = mapOf(UUID.randomUUID().toString() to 1L), note = "Allowed synthetic import")
        val allowedBody = TimeSyncProtokoll.batches(requireNotNull(f.peer.remote_personal_time_policy),
            requireNotNull(f.peer.personal_time_policy), listOf(entry)).single()
        f.work.receiveMessage(f.peer, TelefonNachrichten.message(TimeSyncProtokoll.BATCH, allowedBody, 60000), f.channel, 0)
        assertEquals(entry.id, f.documents.bestand.value.zeiterfassung.entries.single().id)
        val before = File(f.context.filesDir, "notizen.json").readBytes()
        val retired = entry.copy(id = UUID.randomUUID().toString(), note = "Revoked synthetic import")
        val body = TimeSyncProtokoll.batches(requireNotNull(f.peer.remote_personal_time_policy),
            requireNotNull(f.peer.personal_time_policy), listOf(retired)).single()
        val nativeCheck = AtomicBoolean(false)
        f.transportCurrent.set {
            if (Thread.holdsLock(Ablage.SCHREIBSPERRE)) { nativeCheck.set(true); false } else true
        }
        // The import rejects the revoked source. Its follow-up module refresh
        // must also reject a native write from that same retired receive scope.
        assertThrows(java.io.IOException::class.java) {
            f.work.receiveMessage(f.peer, TelefonNachrichten.message(TimeSyncProtokoll.BATCH, body, 60000), f.channel, 0)
        }
        assertTrue("The native writer never rechecked the receive source", nativeCheck.get())
        assertArrayEquals(before, File(f.context.filesDir, "notizen.json").readBytes())
        assertEquals(entry.id, f.documents.bestand.value.zeiterfassung.entries.single().id)
    }

    @Test fun anEstablishedChannelWithoutItsOriginalPipeIsNotAuthorized() = fixture { f ->
        assertTrue(f.work.sessionTransportAktuell(f.channel, 0))
        @Suppress("UNCHECKED_CAST")
        val pipes = field(TelefonWerk::class.java, "sessionPipes").get(f.work) as MutableMap<TelefonSecureChannel, TelefonRoehre>
        pipes.remove(f.channel)
        assertFalse(f.work.sessionTransportAktuell(f.channel, 0))
        assertFalse(f.work.sessionTransportAktuell(f.channel, 0, establishedOnly = false))
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString())))
    }
}
