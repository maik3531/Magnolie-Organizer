package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
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
import java.security.Provider
import java.security.Security
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.crypto.spec.SecretKeySpec

/** Real receiver, encrypted documents/queue, synthetic Keystore and established session controls. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@LooperMode(LooperMode.Mode.PAUSED)
class ScopedDataRuntimeTest {
    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).apply { isAccessible = true }

    @Test fun scopedOrganizerUpdateReachesExistingPhoneNoteButRemovedOrOtherNotesNeverAppear() = exercise("receive")
    @Test fun manualStartWaitsForScopeAndRequestReceiptsAndResumesOnlyAfterFreshSessionControls() = exercise("manual")
    @Test fun independentTimeChangeDefersScopedDataWithoutAdmittingRawFallback() = exercise("time")

    private fun exercise(mode: String) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("ScopedDataFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        context.filesDir.deleteRecursively(); context.filesDir.mkdirs(); context.deleteDatabase("magnolie_phone.db")
        val priorStorage = field(TelefonAblage::class.java, "instance").get(null)
        val priorWork = field(TelefonWerk::class.java, "instance").get(null)
        val priorDocuments = field(Ablage::class.java, "einzig").get(null)
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        val documents = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        field(Ablage::class.java, "einzig").set(null, documents)
        var runtimeWork: TelefonWerk? = null
        try {
            val book = documents.legeNotizbuchAn("Field notes")
            documents.setzeNotiz(Notiz("phone-note", "Mobile", "Initial phone text", notizbuchId = book.id, angelegt = 1, geaendert = 2))
            if (mode == "manual") documents.setzeAufgabe(Aufgabe("phone-task", "Mobile task"))
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
            runtimeWork = work
            work.sharedLocalCapabilities = { TelefonCapabilities.phase1().mapValues { (name, capability) ->
                if (name in setOf("personal_notes_sync", "personal_tasks_sync")) capability.copy(versions = capability.versions + listOf(9, 10)) else capability } }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
            val closed = AtomicInteger()
            val wake = AtomicReference<CountDownLatch?>()
            val wireOutput = object : ByteArrayOutputStream() {
                override fun flush() { super.flush(); wake.get()?.countDown() }
            }
            val pipe = object : TelefonRoehre {
                override val input = ByteArrayInputStream(ByteArray(0))
                override val output = wireOutput
                override fun close() { closed.incrementAndGet() }
            }
            val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
            val local = work.changeSharedSetting(peerId, peer.static_public, "content_mode", JsonPrimitive("phone_scope"))
            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
            val identity = storage.identity("Synthetic"); val actor = identity.first.device_id; identity.second.fill(0)
            val shared = SharedSyncSettings.merge(SharedSyncSettings.create(peerId), local, peerId, actor)
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                var session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true }
                @Suppress("UNCHECKED_CAST")
                val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                sessions[channel] = session
                work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, shared, 60000), channel, 0)
                val pump = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java,
                    Long::class.javaPrimitiveType, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
                pump.invoke(work, peer, channel, 0L, false); pump.invoke(work, peer, channel, 0L, false)
                assertEquals(shared, session.sharedReceived); assertEquals(shared, session.sharedSent)
                fun sent(): List<JsonObject> {
                    val bytes = synchronized(wireOutput) { wireOutput.toByteArray().also { wireOutput.reset() } }
                    val input = ByteArrayInputStream(bytes)
                    val result = mutableListOf<JsonObject>()
                    while (input.available() > 0) {
                        val envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
                        val header = JsonObject(envelope - "ciphertext")
                        val clear = TelefonKrypto.entschluesseln(ByteArray(32) { 11 },
                            TelefonKrypto.nonce(ByteArray(4) { 12 }, envelope.long("seq")),
                            java.util.Base64.getDecoder().decode(envelope.string("ciphertext")), TelefonKanonisch.bytes(header))
                        try { result += TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()) as JsonObject }
                        finally { clear.fill(0) }
                    }
                    return result
                }
                fun ack(id: String, status: String = "accepted", error: String = "none") =
                    work.handleSessionAck(peer, TelefonNachrichten.ack(id, status, error), session, 0L, TelefonTransportArt.WIFI)
                fun ackScope() { session.contentScopeMessages.keys.toList().also { assertTrue(it.isNotEmpty()) }.forEach { ack(it) } }
                fun scoped(messages: List<JsonObject>) = messages.filter { it["kind"] == JsonPrimitive(PhoneContentScope.DATA_KIND) }
                val manifest = requireNotNull(session.localContentScope)
                if (mode == "manual") {
                    sent()
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    val awakened = CountDownLatch(1); wake.set(awakened)
                    work.personalSyncNow()
                    assertTrue(awakened.await(2, TimeUnit.SECONDS)); wake.set(null)
                    assertTrue(sent().any { it["type"] == JsonPrimitive("ping") })
                    assertEquals(0, closed.get())
                    pump.invoke(work, peer, channel, 0L, false)
                    assertTrue(scoped(sent()).isEmpty()); assertFalse(queue.hasActiveScopedRun(peerId))
                    ackScope(); pump.invoke(work, peer, channel, 0L, false)
                    val requestMessage = scoped(sent()).single()
                    val wrapped = requestMessage.getValue("body").jsonObject
                    assertEquals("personal_sync.request", wrapped.string("kind"))
                    val runId = wrapped.getValue("body").jsonObject.string("run_id")
                    assertFalse(queue.scopedRequestAccepted(peerId, runId))
                    ack(requestMessage.string("message_id"), "rejected", "temporary_failure")
                    pump.invoke(work, peer, channel, 0L, false)
                    assertTrue(scoped(sent()).none { it.getValue("body").jsonObject.string("kind") == "personal_sync.batch" })
                    ack(requestMessage.string("message_id")); pump.invoke(work, peer, channel, 0L, false)
                    val batches = scoped(sent()).filter { it.getValue("body").jsonObject.string("kind") == "personal_sync.batch" }
                    assertTrue(batches.isNotEmpty())
                    val records = batches.flatMap { PersonalSyncProtokoll.decodeBatch(it.getValue("body").jsonObject.getValue("body").jsonObject) }
                    assertEquals(setOf("phone-note"), records.filter { it.kind == "note" }.map { it.id }.toSet())
                    assertEquals(setOf("phone-task"), records.filter { it.kind == "task" }.map { it.id }.toSet())
                    batches.forEach { queue.sent(it.string("message_id"), 0, System.currentTimeMillis() - 30000) }
                    session = PersonalNoteSession().apply {
                        capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                        sharedSent = shared; sharedReceived = shared
                    }
                    sessions[channel] = session
                    pump.invoke(work, peer, channel, 0L, false)
                    assertEquals(manifest, session.localContentScope)
                    assertTrue(scoped(sent()).isEmpty())
                    ackScope(); pump.invoke(work, peer, channel, 0L, false)
                    assertEquals(batches.map { it.string("message_id") }.toSet(), scoped(sent()).map { it.string("message_id") }.toSet())
                    documents.loescheNotiz("phone-note"); pump.invoke(work, peer, channel, 0L, false)
                    assertNull(queue.personalRun(peerId, runId)); assertTrue(scoped(sent()).isEmpty())
                    ack(requestMessage.string("message_id"))
                    assertFalse(queue.scopedRequestAccepted(peerId, runId)); assertNull(documents.notiz("phone-note"))
                    return
                }
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
                if (mode == "time") {
                    val changed = SharedSyncSettings.change(shared, peerId, actor, "time_enabled", JsonPrimitive(true))
                    work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, changed, 60000), channel, 0)
                    sent()
                    work.receiveMessage(peer, message, channel, 0)
                    val rejected = sent().last { it["type"] == JsonPrimitive("ack") }
                    assertEquals("rejected", rejected.string("status")); assertEquals("temporary_failure", rejected.string("error"))
                    assertEquals("Initial phone text", documents.notiz("phone-note")!!.text)
                    val rawRun = UUID.randomUUID().toString()
                    val raw = TelefonNachrichten.message("personal_sync.request", JsonObject(request + ("run_id" to JsonPrimitive(rawRun))), 60000)
                    work.receiveMessage(peer, raw, channel, 0)
                    assertEquals("not_granted", sent().last { it["type"] == JsonPrimitive("ack") }.string("error"))
                    assertNull(queue.personalRun(peerId, rawRun))
                    val previousCapabilities = work.sharedLocalCapabilities
                    work.sharedLocalCapabilities = { TelefonCapabilities.phase1() }
                    val downgradedRun = UUID.randomUUID().toString()
                    work.receiveMessage(peer, TelefonNachrichten.message("personal_sync.request",
                        JsonObject(request + ("run_id" to JsonPrimitive(downgradedRun))), 60000), channel, 0)
                    assertEquals("not_granted", sent().last { it["type"] == JsonPrimitive("ack") }.string("error"))
                    assertNull(queue.personalRun(peerId, downgradedRun))
                    work.sharedLocalCapabilities = previousCapabilities
                    pump.invoke(work, peer, channel, 0L, false)
                    assertEquals(changed, session.sharedSent); assertEquals(changed, session.sharedReceived)
                    assertEquals(manifest, session.localContentScope)
                }
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
            runtimeWork?.let {
                field(TelefonWerk::class.java, "serviceRunning").setBoolean(it, false)
                field(TelefonWerk::class.java, "activeChannel").set(it, null)
            }
            field(TelefonAblage::class.java, "instance").set(null, priorStorage)
            field(TelefonWerk::class.java, "instance").set(null, priorWork)
            field(Ablage::class.java, "einzig").set(null, priorDocuments)
            Security.removeProvider(provider.name)
        }
    }
}
