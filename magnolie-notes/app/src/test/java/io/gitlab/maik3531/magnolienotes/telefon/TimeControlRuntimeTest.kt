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
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class TimeControlRuntimeTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }
    private class Fixture(val context: Context, val documents: Ablage, val storage: TelefonAblage, val work: TelefonWerk,
                          val peer: TelefonPeer, val session: PersonalNoteSession, val channel: TelefonSecureChannel,
                          val output: ByteArrayOutputStream) {
        fun receive(body: JsonObject, target: TelefonPeer = peer, generation: Long = 0): JsonObject? {
            work.receiveMessage(target, TelefonNachrichten.message(TimeControlProtokoll.REQUEST, body, 60000), channel, generation)
            val input = ByteArrayInputStream(output.toByteArray()); output.reset()
            if (input.available() == 0) return null
            val envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
            val header = JsonObject(envelope - "ciphertext")
            val clear = TelefonKrypto.entschluesseln(ByteArray(32) { 11 }, TelefonKrypto.nonce(ByteArray(4) { 12 }, envelope.long("seq")),
                Base64.getDecoder().decode(envelope.string("ciphertext")), TelefonKanonisch.bytes(header))
            return try {
                val wire = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
                assertEquals(TimeControlProtokoll.REPORT, wire.string("kind")); TelefonNachrichten.validate(wire)
                wire.getValue("body").jsonObject.also { assertEquals(0, input.available()) }
            } finally { clear.fill(0) }
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
        val pipe = object : TelefonRoehre { override val input = ByteArrayInputStream(ByteArray(0)); override val output = wireOutput; override fun close() {} }
        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
        try {
            documents.aendereZeiterfassung { ZeiterfassungStand(enabled = true) }
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                val session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                    timeSent = peer.personal_time_policy; timeReceived = peer.remote_personal_time_policy }
                @Suppress("UNCHECKED_CAST")
                (field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>)[channel] = session
                action(Fixture(context, documents, storage, work, peer, session, channel, wireOutput))
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

    @Test fun unsupportedControlsAndWithdrawnOwnershipDoNotLeakOrWriteTimerData() = fixture { f ->
        val before = f.documents.bestand.value
        f.work.sharedLocalCapabilities = { TelefonCapabilities.phase1().mapValues { (name, value) ->
            if (name == "personal_tasks_sync") value.copy(versions = value.versions - TimeControlProtokoll.VERSION) else value } }
        val rejected = f.read(); assertEquals("unsupported_feature", rejected.string("error")); assertEquals("", rejected.string("revision"))
        f.storage.savePeer(f.peer.copy(remote_own_device = false))
        assertNull(f.receive(TimeControlProtokoll.request(UUID.randomUUID().toString())))
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
    }
}
