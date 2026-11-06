package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
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
class MediaSyncStorageTest {
    private lateinit var context: Context
    private lateinit var helper: TelefonDatenbank
    private val expected = MediaSettingsBinding("11111111-1111-4111-8111-111111111111", "a".repeat(64),
        "22222222-2222-4222-8222-222222222222", "b".repeat(64), "c".repeat(64))
    private var current: MediaSettingsBinding? = expected
    private var restoring = false
    private var failSeal = false
    private var unsealReads = 0
    private val queues = mutableListOf<TelefonQueue>()
    private val secret = SecretKeySpec(ByteArray(32) { 29 }, "AES")
    private val codec = object : TelefonPayloadStorage {
        override fun encryptPayload(clear: ByteArray, type: String, id: String): ByteArray {
            check(!failSeal)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, secret); cipher.updateAAD("$type\u0000$id".toByteArray())
            return cipher.iv + cipher.doFinal(clear)
        }
        override fun decryptPayload(value: ByteArray, type: String, id: String): ByteArray {
            unsealReads++
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, secret, GCMParameterSpec(128, value.copyOfRange(0, 12)))
            cipher.updateAAD("$type\u0000$id".toByteArray()); return cipher.doFinal(value.copyOfRange(12, value.size))
        }
    }
    private fun store() = MediaSyncStorage({ helper.writableDatabase }, codec, { current }, { restoring })
    private fun blob(): ByteArray = helper.readableDatabase.rawQuery("SELECT value FROM native_media_shared_settings", null).use {
        assertTrue(it.moveToFirst()); it.getBlob(0)
    }
    private fun reject(action: () -> Unit) {
        try { action(); fail("Rejected operation succeeded") } catch (expected: Exception) { /* HOLD */ }
    }
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext(); context.deleteDatabase("magnolie_phone.db")
        helper = TelefonDatenbank(context); current = expected; restoring = false; failSeal = false; unsealReads = 0
    }
    @After fun cleanup() {
        queues.forEach { queue ->
            (TelefonQueue::class.java.getDeclaredField("helper").also { it.isAccessible = true }.get(queue) as TelefonDatenbank).close()
        }
        queues.clear(); helper.close(); context.deleteDatabase("magnolie_phone.db")
    }

    @Test fun channelNeedsCurrentPeerEchoAndExactOutboundAckAndInvalidatesOldMetadata() {
        val queue = TelefonQueue(context, codec).also { queues += it }
        val storage = store()
        val local = storage.change(expected, "enabled", JsonPrimitive(true), storage.fieldVersion(expected, "enabled"))
        var ready = true
        val channel = MediaSyncTransport(expected, storage, queue) { ready }
        channel.queueSettings()
        val outbound = queue.due(expected.peerActor, TelefonTransportArt.WIFI).single().payload
        assertTrue(channel.send(outbound) { })
        assertFalse(channel.matched())
        val remote = MediaSyncSettings.merge(MediaSyncSettings.create(expected.peerActor), local, expected.peerActor, expected.localActor)
        channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, remote, 60000)) { reply ->
            assertEquals(JsonPrimitive("accepted"), reply["status"])
            assertNotNull(storage.read(expected))
        }
        val persisted = storage.read(expected)!!
        channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, persisted, 60000)) { }
        val currentOut = queue.due(expected.peerActor, TelefonTransportArt.WIFI).single().payload
        channel.send(currentOut) { }
        channel.acknowledge(TelefonNachrichten.ack(java.util.UUID.randomUUID().toString(), "accepted", "none"))
        assertFalse(channel.matched())
        channel.acknowledge(TelefonNachrichten.ack(currentOut.string("message_id"), "accepted", "none"))
        assertTrue(channel.matched())
        val imageIntent = channel.intentFor(GalleryMediaType.IMAGES)
        assertNotNull(imageIntent); assertNull(channel.intentFor(GalleryMediaType.VIDEO))
        channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, persisted, 60000)) { }
        assertSame("An unchanged echo must not retire an active source choice", imageIntent, channel.intentFor(GalleryMediaType.IMAGES))
        val requests = mutableListOf<JsonObject>()
        channel.startManual(requests::add)
        val request = requests.single()
        assertEquals(JsonPrimitive(MediaSyncSettings.START_KIND), request["kind"])
        assertEquals(persisted, request["body"]!!.jsonObject["settings"])
        assertTrue(channel.manualStatus().first)
        reject { channel.startManual(requests::add) }; assertEquals(1, requests.size)
        channel.acknowledge(TelefonNachrichten.ack(request.string("message_id"), "accepted", "none"))
        assertTrue("Receipt acceptance is not worker completion", channel.manualStatus().first)
        fun result(id: String) = TelefonNachrichten.message(MediaSyncSettings.RESULT_KIND, buildJsonObject {
            put("format", 1); put("request_id", id); put("state", "content_pass")
        }, 60_000)
        channel.receiveManualResult(result(java.util.UUID.randomUUID().toString())) { assertEquals(JsonPrimitive("rejected"), it["status"]) }
        assertTrue(channel.manualStatus().first)
        channel.receiveManualResult(result(request.string("message_id"))) { assertEquals(JsonPrimitive("accepted"), it["status"]) }
        assertEquals(false to "content_pass", channel.manualStatus())
        channel.startManual(requests::add)
        assertTrue(channel.manualStatus().first)
        assertFalse(queue.due(expected.peerActor, TelefonTransportArt.WIFI).any { it.payload["kind"] == JsonPrimitive(MediaSyncSettings.START_KIND) })
        channel.invalidate()
        assertEquals(false to "held", channel.manualStatus())
        assertNull(channel.intentFor(GalleryMediaType.IMAGES))
        channel.acknowledge(TelefonNachrichten.ack(currentOut.string("message_id"), "accepted", "none"))
        assertFalse(channel.matched())
        channel.send(currentOut) { }
        channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, persisted, 60000)) { }
        channel.acknowledge(TelefonNachrichten.ack(currentOut.string("message_id"), "accepted", "none"))
        assertTrue(channel.matched())
        assertNotSame("A fresh agreement must not resurrect the older native source lease", imageIntent, channel.intentFor(GalleryMediaType.IMAGES))
        channel.receiveManualResult(result(requests.last().string("message_id"))) { assertEquals(JsonPrimitive("rejected"), it["status"]) }
        assertEquals(false to "held", channel.manualStatus())
        reject { channel.startManual { throw java.io.IOException("Synthetic explicit request write failed") } }
        assertEquals(false to "held", channel.manualStatus())
        ready = false; channel.queueSettings(); assertFalse(channel.matched()); assertNull(channel.intentFor(GalleryMediaType.IMAGES))
    }

    @Test fun channelFailedSecureAckPreservesCommittedChoiceWithoutAgreementAndUnsupportedDoesNotCreateIt() {
        val queue = TelefonQueue(context, codec).also { queues += it }
        val storage = store()
        var ready = false
        val channel = MediaSyncTransport(expected, storage, queue) { ready }
        val message = TelefonNachrichten.message(MediaSyncSettings.KIND, MediaSyncSettings.create(expected.peerActor), 60000)
        channel.receive(message) { assertEquals(JsonPrimitive("rejected"), it["status"]) }
        assertNull(storage.read(expected))
        ready = true
        reject { channel.receive(message) { throw java.io.IOException("Synthetic secure ACK failure") } }
        assertNotNull(storage.read(expected)); assertFalse(channel.matched())
        assertTrue(queue.due(expected.peerActor, TelefonTransportArt.WIFI).isEmpty())
    }

    @Test fun incomingIntentRequiresExactMatchedTwoWayMasterAndIndependentMediaChoiceWithoutCreatingPermissions() {
        val queue = TelefonQueue(context, codec).also { queues += it }; val storage = store()
        fun tables(): Set<String> = helper.readableDatabase.rawQuery("SELECT name FROM sqlite_master WHERE type='table'", null).use { cursor ->
            buildSet { while (cursor.moveToNext()) add(cursor.getString(0)) }
        }
        val expectedTables = tables() + "native_media_shared_settings"
        var ready = true
        val channel = MediaSyncTransport(expected, storage, queue) { ready }
        fun edit(field: String, value: JsonElement) {
            channel.invalidate(); storage.change(expected, field, value, storage.fieldVersion(expected, field))
        }
        fun match() {
            channel.queueSettings()
            val sent = queue.due(expected.peerActor, TelefonTransportArt.WIFI).single().payload
            assertTrue(channel.send(sent) { })
            channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, storage.read(expected)!!, 60_000)) { }
            assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES)); assertNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
            channel.acknowledge(TelefonNachrichten.ack(sent.string("message_id"), "accepted", "none"))
            queue.acknowledge(expected.peerActor, sent.string("message_id")); assertTrue(channel.matched())
        }
        assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES))
        edit("enabled", JsonPrimitive(true)); match()
        assertNotNull(channel.intentFor(GalleryMediaType.IMAGES)); assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES))
        assertNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
        edit("direction", JsonPrimitive("two_way")); match()
        val first = channel.incomingIntentFor(GalleryMediaType.IMAGES)!!
        assertSame(first, channel.intentFor(GalleryMediaType.IMAGES)); assertNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
        val unchanged = storage.read(expected)!!
        channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, unchanged, 60_000)) { }
        assertSame(first, channel.incomingIntentFor(GalleryMediaType.IMAGES))
        val before = blob(); val reads = unsealReads
        repeat(1000) { assertSame(first, channel.incomingIntentFor(GalleryMediaType.IMAGES)) }
        assertEquals(reads, unsealReads); assertArrayEquals(before, blob())
        channel.invalidate(); assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES)); match()
        assertNotSame(first, channel.incomingIntentFor(GalleryMediaType.IMAGES))
        edit("videos_enabled", JsonPrimitive(true)); match()
        assertSame(channel.incomingIntentFor(GalleryMediaType.IMAGES), channel.incomingIntentFor(GalleryMediaType.VIDEO))
        edit("photos_enabled", JsonPrimitive(false)); match()
        assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES)); assertNotNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
        edit("enabled", JsonPrimitive(false)); match()
        assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES)); assertNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
        edit("enabled", JsonPrimitive(true)); match(); assertNotNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
        ready = false; channel.queueSettings(); assertNull(channel.incomingIntentFor(GalleryMediaType.VIDEO))
        assertEquals("Shared intent must not construct a receiver policy or gallery index", expectedTables, tables())
    }

    @Test fun incomingIntentLookupDoesNotWaitForTransportMonitorOrReadProtectedMetadata() {
        val queue = TelefonQueue(context, codec).also { queues += it }; val storage = store()
        storage.change(expected, "enabled", JsonPrimitive(true), storage.fieldVersion(expected, "enabled"))
        storage.change(expected, "direction", JsonPrimitive("two_way"), storage.fieldVersion(expected, "direction"))
        val channel = MediaSyncTransport(expected, storage, queue) { true }; channel.queueSettings()
        val message = queue.due(expected.peerActor, TelefonTransportArt.WIFI).single().payload
        channel.send(message) { }; channel.receive(TelefonNachrichten.message(MediaSyncSettings.KIND, storage.read(expected)!!, 60_000)) { }
        channel.acknowledge(TelefonNachrichten.ack(message.string("message_id"), "accepted", "none"))
        val intent = channel.incomingIntentFor(GalleryMediaType.IMAGES); assertNotNull(intent)
        val ended = java.util.concurrent.CountDownLatch(1); val observed = java.util.concurrent.atomic.AtomicReference<Any?>()
        val worker = Thread { try { observed.set(channel.incomingIntentFor(GalleryMediaType.IMAGES)) } finally { ended.countDown() } }
        val reads = unsealReads
        try {
            synchronized(channel) { worker.start(); assertTrue(ended.await(1, java.util.concurrent.TimeUnit.SECONDS)) }
        } finally { worker.join(5000); assertFalse(worker.isAlive) }
        assertSame(intent, observed.get()); assertEquals(reads, unsealReads)
        channel.invalidate(); assertNull(channel.incomingIntentFor(GalleryMediaType.IMAGES))
    }

    @Test fun readonlyPreviewAndIndependentFieldEditsPersistWithoutPermissionsOrQueue() {
        val store = store()
        assertNull(store.read(expected)); assertFalse(MediaSyncSettings.requestedFor(store.project(expected), "images"))
        helper.readableDatabase.rawQuery("SELECT 1 FROM sqlite_master WHERE name='native_media_shared_settings'", null).use {
            assertFalse(it.moveToFirst())
        }
        val masterVersion = store.fieldVersion(expected, "enabled")
        val videoVersion = store.fieldVersion(expected, "videos_enabled")
        store.change(expected, "enabled", JsonPrimitive(true), masterVersion)
        val body = store.change(expected, "videos_enabled", JsonPrimitive(true), videoVersion)
        assertTrue(MediaSyncSettings.requestedFor(body, "images")); assertTrue(MediaSyncSettings.requestedFor(body, "video"))
        reject { store.change(expected, "enabled", JsonPrimitive(false), masterVersion) }
        assertEquals(body, store().read(expected)); assertFalse(blob().decodeToString().contains("photos_enabled"))
        helper.writableDatabase.execSQL("DELETE FROM meta")
        helper.deletePeer(expected.peerActor)
        assertEquals(body, store().read(expected))
        helper.readableDatabase.rawQuery("SELECT COUNT(*) FROM outbox", null).use { it.moveToFirst(); assertEquals(0, it.getInt(0)) }
    }

    @Test fun remoteMergeIsDurableEchoDoesNotRewriteAndForgedLocalClockIsRejected() {
        val store = store()
        val initial = store.project(expected)
        var remote = MediaSyncSettings.merge(MediaSyncSettings.create(expected.peerActor), initial, expected.peerActor, expected.localActor)
        remote = MediaSyncSettings.change(remote, expected.peerActor, expected.localActor, "auto_mode", JsonPrimitive("wifi"))
        val merged = store.merge(expected, remote)
        assertEquals(JsonPrimitive("wifi"), MediaSyncSettings.effective(merged)["auto_mode"])
        val before = blob(); assertEquals(merged, store.merge(expected, remote)); assertArrayEquals(before, blob())
        val values = remote.getValue("settings").jsonObject.toMutableMap()
        values["enabled"] = buildJsonObject { put(expected.localActor, buildJsonObject { put("counter", 99); put("value", true) }) }
        reject { store.merge(expected, JsonObject(remote + ("settings" to JsonObject(values)))) }
        assertArrayEquals(before, blob())
    }

    @Test fun changedBindingRestoreCorruptionAndFailedSealRetainHistoricalBytes() {
        val store = store()
        store.change(expected, "enabled", JsonPrimitive(true), store.fieldVersion(expected, "enabled"))
        val before = blob()
        for (changed in listOf(null, expected.copy(localActor = expected.peerActor), expected.copy(localKey = "d".repeat(64)),
            expected.copy(peerKey = "e".repeat(64)), expected.copy(pairingEpoch = "f".repeat(64)))) {
            current = changed
            reject { store.read(changed ?: expected) }; reject { store.merge(changed ?: expected, MediaSyncSettings.create(expected.peerActor)) }
            assertArrayEquals(before, blob())
        }
        current = expected; restoring = true
        reject { store.read(expected) }; reject { store.project(expected) }
        restoring = false; failSeal = true
        reject { store.change(expected, "enabled", JsonPrimitive(false), store.fieldVersion(expected, "enabled")) }
        assertArrayEquals(before, blob()); failSeal = false
        val damaged = before.copyOf(); damaged[damaged.lastIndex] = (damaged.last().toInt() xor 1).toByte()
        helper.writableDatabase.execSQL("UPDATE native_media_shared_settings SET value=?", arrayOf(damaged))
        reject { store.project(expected) }; reject { store.merge(expected, MediaSyncSettings.create(expected.peerActor)) }
        assertArrayEquals(damaged, blob())
    }
}
