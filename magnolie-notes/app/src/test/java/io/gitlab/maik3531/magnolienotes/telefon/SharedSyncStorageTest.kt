package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class SharedSyncStorageTest {
    private lateinit var context: Context
    private lateinit var helper: TelefonDatenbank
    private val expected = SharedSettingsBinding("11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222", TelefonKrypto.b64(ByteArray(32) { 31 }))
    private var current: SharedSettingsBinding? = expected
    private var restoring = false
    private var failSeal = false
    private var failScopeSeal = false
    private var failOutboxAt = 0
    private var outboxSeals = 0
    private val secret = SecretKeySpec(ByteArray(32) { 29 }, "AES")
    private val codec = object : TelefonPayloadStorage {
        override fun encryptPayload(clear: ByteArray, type: String, id: String): ByteArray {
            check(!failSeal) { "synthetic seal failure" }
            check(!failScopeSeal || type != "personal_scope") { "synthetic scope seal failure" }
            if (type == "outbox") check(++outboxSeals != failOutboxAt) { "synthetic outbox seal failure" }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, secret); cipher.updateAAD("$type\u0000$id".toByteArray())
            return cipher.iv + cipher.doFinal(clear)
        }
        override fun decryptPayload(value: ByteArray, type: String, id: String): ByteArray {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, secret, GCMParameterSpec(128, value.copyOfRange(0, 12)))
            cipher.updateAAD("$type\u0000$id".toByteArray()); return cipher.doFinal(value.copyOfRange(12, value.size))
        }
    }
    private fun store() = SharedSyncStorage({ helper.writableDatabase }, codec, { current }, { restoring })
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext(); context.deleteDatabase("magnolie_phone.db")
        helper = TelefonDatenbank(context); current = expected
    }
    @After fun cleanup() { helper.close(); context.deleteDatabase("magnolie_phone.db") }

    @Test fun previewDoesNotInitializeAndSingleChangeIsEncryptedDurableWithoutOutbox() {
        val store = store(); assertNull(store.read(expected))
        val value = store.change(expected, "content_mode", JsonPrimitive("two_way"))
        helper.close(); helper = TelefonDatenbank(context)
        assertEquals(value, store().read(expected))
        helper.readableDatabase.rawQuery("SELECT value FROM meta WHERE key LIKE 'personal_shared_settings:%'", null).use {
            assertTrue(it.moveToFirst()); assertFalse(it.getBlob(0).decodeToString().contains("content_mode"))
        }
        helper.readableDatabase.rawQuery("SELECT COUNT(*) FROM outbox", null).use { it.moveToFirst(); assertEquals(0, it.getInt(0)) }
    }

    @Test fun explicitInitializationPreservesLegacyChoicesAtZeroAndNeverReseeds() {
        val shared = store()
        val initial = mapOf("content_mode" to JsonPrimitive("phone_import"), "auto_mode" to JsonPrimitive("wifi"),
            "skip_deletions" to JsonPrimitive(true), "custom_enabled" to JsonPrimitive(false),
            "time_enabled" to JsonPrimitive(true), "time_mode" to JsonPrimitive("phone_import"))
        val body = shared.initialize(expected, initial)
        assertEquals(initial, SharedSyncSettings.effective(body))
        assertTrue(body.getValue("settings").jsonObject.values.all { field -> field.jsonObject.values.all { it.jsonObject.long("counter") == 0L } })
        val changed = shared.change(expected, "content_mode", JsonPrimitive("phone_scope"))
        assertEquals(changed, shared.initialize(expected, initial + ("content_mode" to JsonPrimitive("two_way"))))
        helper.readableDatabase.rawQuery("SELECT COUNT(*) FROM outbox", null).use { it.moveToFirst(); assertEquals(0, it.getInt(0)) }
    }

    @Test fun remoteChoiceAndEchoPersistExactlyOneCommonState() {
        val store = store(); val value = store.change(expected, "content_mode", JsonPrimitive("two_way"))
        var remote = SharedSyncSettings.merge(SharedSyncSettings.create(expected.peerActor), value, expected.peerActor, expected.localActor)
        remote = SharedSyncSettings.change(remote, expected.peerActor, expected.localActor, "content_mode", JsonPrimitive("phone_scope"))
        val accepted = store.merge(expected, remote)
        assertEquals("phone_scope", SharedSyncSettings.effective(accepted).getValue("content_mode").jsonPrimitive.content)
        assertEquals(accepted, store.merge(expected, remote)); assertEquals(accepted, store.read(expected))
    }

    @Test fun failedSealAndChangedBindingRollBackAndUnpairClearsState() {
        val store = store(); val before = store.change(expected, "content_mode", JsonPrimitive("two_way"))
        failSeal = true
        assertTrue(runCatching { store.change(expected, "auto_mode", JsonPrimitive("connection")) }.isFailure)
        failSeal = false; assertEquals(before, store.read(expected))
        current = expected.copy(peerPublic = TelefonKrypto.b64(ByteArray(32) { 41 }))
        assertTrue(runCatching { store.read(expected) }.isFailure)
        assertNull(store.read(current!!))
        current = expected; assertEquals(before, store.read(expected))
        helper.deletePeer(expected.peerActor)
        assertNull(store.read(expected))
    }

    @Test fun restoreBarrierBlocksWritesWithoutResettingStoredChoice() {
        val store = store(); val before = store.change(expected, "content_mode", JsonPrimitive("two_way"))
        restoring = true
        assertTrue(runCatching { store.change(expected, "auto_mode", JsonPrimitive("connection")) }.isFailure)
        assertEquals(before, store.read(expected))
        restoring = false; assertEquals(before, store.read(expected))
    }

    @Test fun rejectedForgedEchoDoesNotPartiallyPersistOtherFields() {
        val store = store(); val before = store.change(expected, "content_mode", JsonPrimitive("two_way"))
        val remote = SharedSyncSettings.merge(SharedSyncSettings.create(expected.peerActor), before, expected.peerActor, expected.localActor)
        val fields = remote.getValue("settings").jsonObject.toMutableMap()
        fields["content_mode"] = JsonObject(fields.getValue("content_mode").jsonObject +
            (expected.localActor to buildJsonObject { put("counter", 100); put("value", "phone_scope") }))
        assertTrue(runCatching { store.merge(expected, JsonObject(remote + ("settings" to JsonObject(fields)))) }.isFailure)
        assertEquals(before, store.read(expected))
    }

    @Test fun controlUsesExistingEncryptedQueueAndReceiptWithBoundedWireLifetime() {
        val queue = TelefonQueue(context, codec)
        val body = SharedSyncSettings.create(expected.localActor)
        val message = queue.queue(expected.peerActor, SharedSyncSettings.KIND, body, 60_000)
        TelefonNachrichten.validate(message)
        assertEquals(message, queue.due(expected.peerActor, TelefonTransportArt.WIFI).single().payload)
        assertEquals("accepted" to "none", queue.receive(expected.peerActor, message))
        assertEquals("duplicate" to "none", queue.receive(expected.peerActor, message))
        assertTrue(queue.receivedMatches(expected.peerActor, message))
        val changed = SharedSyncSettings.change(body, expected.localActor, expected.peerActor, "content_mode", JsonPrimitive("two_way"))
        assertFalse(queue.receivedMatches(expected.peerActor, JsonObject(message + ("body" to changed))))
        assertTrue(runCatching { queue.queue(expected.peerActor, SharedSyncSettings.KIND, body, 86_400_001) }.isFailure)
        val invalid = TelefonNachrichten.message(SharedSyncSettings.KIND, body, 86_400_001)
        assertTrue(runCatching { TelefonNachrichten.validate(invalid) }.isFailure)
        val manifest = PhoneContentScope.create(listOf("mobile-note"), listOf("mobile-task"))
        val scopeMessage = queue.queue(expected.peerActor, PhoneContentScope.KIND, PhoneContentScope.chunks(manifest).single(), 60_000)
        TelefonNachrichten.validate(scopeMessage)
        assertEquals("accepted" to "none", queue.receive(expected.peerActor, scopeMessage))
        assertTrue(runCatching { queue.queue(expected.peerActor, PhoneContentScope.KIND, PhoneContentScope.chunks(manifest).single(), 60_001) }.isFailure)
    }

    @Test fun scopedRunPersistsExactMembershipAndTimeChangesRemainIndependent() {
        val shared = store(); shared.change(expected, "content_mode", JsonPrimitive("phone_scope"))
        val queue = TelefonQueue(context, codec)
        val request = buildJsonObject { put("format", 3); put("run_id", "55555555-5555-4555-8555-555555555555")
            put("trigger", "manual"); put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
        val runId = request.getValue("run_id").jsonPrimitive.content
        val reference = PhoneContentScope.reference(PhoneContentScope.create(listOf("note"), listOf("task")))
        val now = System.currentTimeMillis(); val expires = now + 60000
        queue.rememberScopedRun(expected, shared, request, reference, expires, now)
        val reopened = TelefonQueue(context, codec)
        assertEquals(reference, reopened.scopedRunReference(expected, store(), runId, now))
        assertEquals(request, reopened.personalRun(expected.peerActor, runId))
        reopened.rememberScopedRun(expected, shared, request, reference, expires, now)
        assertTrue(runCatching { reopened.rememberScopedRun(expected, shared, request, reference, expires + 1, now) }.isFailure)
        val changed = JsonObject(reference + ("scope_revision" to JsonPrimitive(2)))
        assertTrue(runCatching { reopened.rememberScopedRun(expected, shared, request, changed, expires, now) }.isFailure)
        shared.change(expected, "time_mode", JsonPrimitive("two_way"))
        assertEquals(reference, reopened.scopedRunReference(expected, shared, runId, now))
        shared.change(expected, "content_mode", JsonPrimitive("two_way"))
        assertTrue(runCatching { reopened.scopedRunReference(expected, shared, runId, now) }.isFailure)
        shared.change(expected, "content_mode", JsonPrimitive("phone_scope"))
        assertTrue(runCatching { reopened.scopedRunReference(expected, shared, runId, now) }.isFailure)
        val fresh = JsonObject(request + ("run_id" to JsonPrimitive("66666666-6666-4666-8666-666666666666")))
        failScopeSeal = true
        assertTrue(runCatching { reopened.rememberScopedRun(expected, shared, fresh, reference, expires, now) }.isFailure)
        failScopeSeal = false
        assertNull(reopened.personalRun(expected.peerActor, fresh.getValue("run_id").jsonPrimitive.content))
        assertNull(reopened.scopedRunReference(expected, shared, fresh.getValue("run_id").jsonPrimitive.content, now))
        reopened.rememberScopedRun(expected, shared, fresh, reference, expires, now)
        restoring = true
        assertTrue(runCatching { reopened.scopedRunReference(expected, shared, fresh.getValue("run_id").jsonPrimitive.content, now) }.isFailure)
        restoring = false
        reopened.purgePersonalModules(expected.peerActor, setOf("notes"))
        assertNull(reopened.scopedRunReference(expected, shared, fresh.getValue("run_id").jsonPrimitive.content, now))
    }

    @Test fun unchangedLocalMembershipSurvivesReopenButRemovalAndRestoreRotateIt() {
        val shared = store()
        val initial = shared.localContentScope(expected, "restore-a", listOf("note"), listOf("task"))
        helper.close(); helper = TelefonDatenbank(context)
        val reopened = store()
        assertEquals(initial, reopened.localContentScope(expected, "restore-a", listOf("note"), listOf("task")))
        val removed = reopened.localContentScope(expected, "restore-a", emptyList(), listOf("task"))
        assertEquals(initial.long("revision") + 1, removed.long("revision"))
        assertNotEquals(initial["epoch"], removed["epoch"])
        val restored = reopened.localContentScope(expected, "restore-b", emptyList(), listOf("task"))
        assertEquals(removed.long("revision") + 1, restored.long("revision"))
        assertNotEquals(removed["epoch"], restored["epoch"])
        helper.deletePeer(expected.peerActor)
        assertEquals(1L, reopened.localContentScope(expected, "restore-b", emptyList(), listOf("task")).long("revision"))
    }

    @Test fun newMembershipPurgesOnlyStaleScopedRunsAndKeepsUnrelatedMessages() {
        val shared = store(); shared.change(expected, "content_mode", JsonPrimitive("phone_scope"))
        val queue = TelefonQueue(context, codec)
        val current = shared.localContentScope(expected, "", listOf("note"), emptyList())
        val run = "55555555-5555-4555-8555-555555555555"
        val request = buildJsonObject { put("format", 3); put("run_id", run); put("trigger", "manual")
            put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
        val now = System.currentTimeMillis()
        queue.rememberScopedRun(expected, shared, request, PhoneContentScope.reference(current), now + 60000, now)
        val pending = queue.queue(expected.peerActor, "personal_sync.request", request, 60000, now)
        val unrelated = queue.queue(expected.peerActor, "device_status.request", buildJsonObject {
            put("version", 1); put("request_id", "77777777-7777-4777-8777-777777777777") }, 60000, now)
        assertTrue(queue.purgeStaleScopedRuns(expected, shared, PhoneContentScope.reference(current)).isEmpty())
        assertNotNull(queue.outboxPersonalMessage(expected.peerActor, pending.string("message_id")))
        val removed = shared.localContentScope(expected, "", emptyList(), emptyList())
        assertEquals(setOf(run), queue.purgeStaleScopedRuns(expected, shared, PhoneContentScope.reference(removed)))
        assertNull(queue.personalRun(expected.peerActor, run))
        assertNull(queue.outboxPersonalMessage(expected.peerActor, pending.string("message_id")))
        assertTrue(queue.due(expected.peerActor, TelefonTransportArt.WIFI).any { it.messageId == unrelated.string("message_id") })
        queue.rememberScopedRun(expected, shared, request, PhoneContentScope.reference(removed), now + 60000, now)
        shared.change(expected, "content_mode", JsonPrimitive("two_way"))
        assertEquals(setOf(run), queue.purgeStaleScopedRuns(expected, shared, null))
    }

    @Test fun freshScopeControlsPrecedeOlderQueuedDataAfterReconnect() {
        val queue = TelefonQueue(context, codec); val now = System.currentTimeMillis()
        val request = buildJsonObject { put("format", 3); put("run_id", "55555555-5555-4555-8555-555555555555")
            put("trigger", "manual"); put("modules", JsonArray(listOf(JsonPrimitive("notes")))) }
        queue.rememberPersonalRun(expected.peerActor, request, now + 60000, now)
        val data = queue.queue(expected.peerActor, "personal_sync.request", request, 60000, now)
        val manifest = PhoneContentScope.create(listOf("note"), emptyList())
        val scope = queue.queue(expected.peerActor, PhoneContentScope.KIND, PhoneContentScope.chunks(manifest).single(), 60000, now + 1)
        val preferences = queue.queue(expected.peerActor, SharedSyncSettings.KIND, SharedSyncSettings.create(expected.localActor), 60000, now + 2)
        assertEquals(listOf(preferences.string("message_id"), scope.string("message_id"), data.string("message_id")),
            queue.due(expected.peerActor, TelefonTransportArt.WIFI, now + 3).map { it.messageId })
    }

    @Test fun localScopedStartIsAtomicAcrossDifferentDatabaseHandlesAndWaitsForItsExactRequestReceipt() {
        val shared = store(); shared.change(expected, "content_mode", JsonPrimitive("phone_scope"))
        val queue = TelefonQueue(context, codec)
        val bytes = ByteArray(PersonalSyncProtokoll.CHUNK_RAW + 32) { 65 }
        byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a).copyInto(bytes)
        val attachment = Anhang("image", "Synthetic", "image", "data:image/png;base64," + java.util.Base64.getEncoder().encodeToString(bytes))
        val data = Bestand(notizen = listOf(Notiz("note", "Synthetic", notizbuchId = "book", anhaenge = listOf(attachment))),
            notizbuecher = listOf(Notizbuch("book", "Synthetic")), personalSync = PersonalSyncState(actor_id = expected.localActor))
        val records = PersonalSync.reconcile(data, setOf("notes", "tasks"), 3, expected.peerActor).second
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        val manifest = PhoneContentScope.create(listOf("note"), emptyList())
        val run = "88888888-8888-4888-8888-888888888888"
        val request = buildJsonObject { put("format", 3); put("run_id", run); put("trigger", "manual")
            put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
        val now = System.currentTimeMillis()
        val message = TelefonNachrichten.message("personal_sync.request", request, 60000, now)
        val batch = PersonalSyncProtokoll.batch(run, records, 0, true, false, 3, PersonalSync.recordsHash(records))
        val attachments = listOf(Triple(digest, "image/png", bytes))
        failOutboxAt = 2 // Batches have been inserted when request encryption fails.
        assertTrue(runCatching { queue.queueScopedRequest(expected, shared, message, PhoneContentScope.reference(manifest), listOf(batch), attachments, now) }.isFailure)
        assertFalse(queue.hasActiveScopedRun(expected.peerActor, now))
        assertFalse(queue.containsScopedRun(expected.peerActor, run))
        for (table in listOf("outbox", "personal_run", "personal_attachment_transfer", "personal_attachment_chunk"))
            helper.readableDatabase.rawQuery("SELECT COUNT(*) FROM $table", null).use { it.moveToFirst(); assertEquals(table, 0, it.getInt(0)) }
        failOutboxAt = 0
        assertTrue(queue.queueScopedRequest(expected, shared, message, PhoneContentScope.reference(manifest), listOf(batch), attachments, now))
        assertTrue(queue.hasActiveScopedRun(expected.peerActor, now))
        assertFalse(queue.scopedRequestAccepted(expected.peerActor, run))
        val due = queue.due(expected.peerActor, TelefonTransportArt.WIFI, now + 1000)
        assertEquals("personal_sync.request", due.first().payload.string("kind"))
        assertTrue(queue.acknowledgeScopedRequest(expected.peerActor, message.string("message_id"), "rejected", "temporary_failure"))
        assertFalse(queue.scopedRequestAccepted(expected.peerActor, run))
        assertNotNull(queue.outboxPersonalMessage(expected.peerActor, message.string("message_id")))
        assertTrue(queue.acknowledgeScopedRequest(expected.peerActor, message.string("message_id"), "accepted", "none"))
        val reopened = TelefonQueue(context, codec)
        assertTrue(reopened.scopedRequestAccepted(expected.peerActor, run))
        val chunks = reopened.requestedAttachmentChunks(expected.peerActor, run, false, batch.string("records_hash"),
            listOf(digest to listOf(listOf(0, 2))), TelefonTransportArt.WIFI)
        assertEquals(2, chunks.size)
        assertArrayEquals(bytes, chunks.sortedBy { it.second }.flatMap { it.third.asIterable() }.toByteArray())
    }

    @Test fun terminalScopedRequestRejectionDropsOnlyItsTransientRun() {
        val shared = store(); shared.change(expected, "content_mode", JsonPrimitive("phone_scope"))
        val queue = TelefonQueue(context, codec); val now = System.currentTimeMillis()
        val run = "88888888-8888-4888-8888-888888888888"
        val request = buildJsonObject { put("format", 3); put("run_id", run); put("trigger", "manual")
            put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
        val message = TelefonNachrichten.message("personal_sync.request", request, 60000, now)
        val batch = PersonalSyncProtokoll.batch(run, emptyList(), 0, true, false, 3, PersonalSync.recordsHash(emptyList()))
        val unrelated = queue.queue(expected.peerActor, "device_status.request", buildJsonObject { put("version", 1)
            put("request_id", "77777777-7777-4777-8777-777777777777") }, 60000, now)
        assertTrue(queue.queueScopedRequest(expected, shared, message,
            PhoneContentScope.reference(PhoneContentScope.create(emptyList(), emptyList())), listOf(batch), emptyList(), now))
        assertTrue(queue.acknowledgeScopedRequest(expected.peerActor, message.string("message_id"), "rejected", "not_granted"))
        assertNull(queue.personalRun(expected.peerActor, run))
        assertFalse(queue.containsScopedRun(expected.peerActor, run))
        assertEquals(listOf(unrelated.string("message_id")), queue.due(expected.peerActor, TelefonTransportArt.WIFI, now + 1000).map { it.messageId })
        assertFalse(queue.acknowledgeScopedRequest(expected.peerActor, message.string("message_id"), "accepted", "none"))
        assertFalse(queue.scopedRequestAccepted(expected.peerActor, run))
    }
}
