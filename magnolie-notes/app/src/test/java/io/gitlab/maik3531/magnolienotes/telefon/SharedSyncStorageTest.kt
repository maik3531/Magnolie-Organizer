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
class SharedSyncStorageTest {
    private lateinit var context: Context
    private lateinit var helper: TelefonDatenbank
    private val expected = SharedSettingsBinding("11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222", TelefonKrypto.b64(ByteArray(32) { 31 }))
    private var current: SharedSettingsBinding? = expected
    private var restoring = false
    private var failSeal = false
    private val secret = SecretKeySpec(ByteArray(32) { 29 }, "AES")
    private val codec = object : TelefonPayloadStorage {
        override fun encryptPayload(clear: ByteArray, type: String, id: String): ByteArray {
            check(!failSeal) { "synthetic seal failure" }
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
}
