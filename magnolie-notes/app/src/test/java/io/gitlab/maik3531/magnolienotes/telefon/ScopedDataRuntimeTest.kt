package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncClock
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
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.spec.SecretKeySpec

/** Real receiver, encrypted documents/queue, synthetic Keystore and established session controls. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class ScopedDataRuntimeTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun scopedOrganizerUpdateReachesExistingPhoneNoteButRemovedOrOtherNotesNeverAppear() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("ScopedDataFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        val priorStorage = field(TelefonAblage::class.java, "instance").get(null)
        val priorWork = field(TelefonWerk::class.java, "instance").get(null)
        val priorDocuments = field(Ablage::class.java, "einzig").get(null)
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        field(Ablage::class.java, "einzig").set(null, documents)
        try {
            val book = documents.legeNotizbuchAn("Field notes")
            documents.setzeNotiz(Notiz("phone-note", "Mobile", "Initial phone text", notizbuchId = book.id, angelegt = 1, geaendert = 2))
            val storage = TelefonAblage.get(context)
            storage.identity("Synthetic").second.fill(0)
            storage.setEnabled(true); storage.setPersonalSync(true, true, true, false, false)
            val peerId = "22222222-2222-4222-8222-222222222222"
            val peer = TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32) { 23 }),
                own_device = true, remote_own_device = true, personal_notes_sync_granted = true, personal_tasks_sync_granted = true,
                remote_personal_notes_sync_granted = true, remote_personal_tasks_sync_granted = true,
                remote_personal_notes_sync_available = true, remote_personal_tasks_sync_available = true,
                remote_personal_notes_sync_versions = listOf(1, 2, 3, 5, 9, 10), remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4, 6, 7, 9, 10))
            storage.savePeer(peer)
            val work = TelefonWerk.get(context)
            work.sharedLocalCapabilities = { TelefonCapabilities.phase1().mapValues { (name, capability) ->
                if (name in setOf("personal_notes_sync", "personal_tasks_sync")) capability.copy(versions = capability.versions + listOf(9, 10)) else capability } }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
            val pipe = object : TelefonRoehre {
                override val input = ByteArrayInputStream(ByteArray(0))
                override val output = ByteArrayOutputStream()
                override fun close() = Unit
            }
            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
            val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
            val local = work.changeSharedSetting(peerId, peer.static_public, "content_mode", JsonPrimitive("phone_scope"))
            val identity = storage.identity("Synthetic"); val actor = identity.first.device_id; identity.second.fill(0)
            val shared = SharedSyncSettings.merge(SharedSyncSettings.create(peerId), local, peerId, actor)
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                val session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true }
                @Suppress("UNCHECKED_CAST")
                val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                sessions[channel] = session
                work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, shared, 60000), channel, 0)
                val pump = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java,
                    Long::class.javaPrimitiveType, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
                pump.invoke(work, peer, channel, 0L, false); pump.invoke(work, peer, channel, 0L, false)
                assertEquals(shared, session.sharedReceived); assertEquals(shared, session.sharedSent)
                val manifest = requireNotNull(session.localContentScope)
                val selection = PersonalSync.livePersonalContent(documents.bestand.value)
                val snapshot = documents.personalSyncScopedSnapshot(selection, peerId)
                val old = snapshot.records.single { it.kind == "note" }
                val value = JsonObject(old.value + mapOf("text" to JsonPrimitive("Organizer addition"), "modified_ms" to JsonPrimitive(old.modifiedMs + 1)))
                val updated = old.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = old.modifiedMs + 1,
                    clock = (old.clock + PersonalSyncClock(peerId, 1)).sortedWith { a, b -> PersonalSync.compareUtf8(a.actor_id, b.actor_id) })
                val run = UUID.randomUUID().toString()
                val request = buildJsonObject { put("format", 3); put("run_id", run); put("trigger", "manual")
                    put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
                val requestMessage = TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.request", request, manifest), 60000)
                work.receiveMessage(peer, requestMessage, channel, 0)
                // duplicateResult reports the ACK for a subsequent replay of a durable acceptance.
                assertEquals("duplicate" to "none", queue.duplicateResult(peerId, requestMessage.string("message_id")))
                val batch = PersonalSyncProtokoll.batch(run, listOf(updated), 0, true, true, 3, PersonalSync.recordsHash(listOf(updated)))
                val message = TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.batch", batch, manifest), 60000)
                work.receiveMessage(peer, message, channel, 0)
                assertEquals("Organizer addition", documents.notiz("phone-note")!!.text)
                assertEquals(1, documents.notizen().size)
                val foreign = updated.copy(id = "organizer-only")
                val foreignBatch = PersonalSyncProtokoll.batch(run, listOf(foreign), 0, true, true, 3, PersonalSync.recordsHash(listOf(foreign)))
                work.receiveMessage(peer, TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.batch", foreignBatch, manifest), 60000), channel, 0)
                assertNull(documents.notiz("organizer-only")); assertEquals(1, documents.notizen().size)
                documents.loescheNotiz("phone-note")
                work.receiveMessage(peer, TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.batch", batch, manifest), 60000), channel, 0)
                assertNull(documents.notiz("phone-note")); assertTrue(documents.notizen().isEmpty())
                assertEquals("Organizer addition", updated.value.getValue("text").jsonPrimitive.content)
            }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, false)
        } finally {
            field(TelefonAblage::class.java, "instance").set(null, priorStorage)
            field(TelefonWerk::class.java, "instance").set(null, priorWork)
            field(Ablage::class.java, "einzig").set(null, priorDocuments)
            Security.removeProvider(provider.name)
        }
    }
}
