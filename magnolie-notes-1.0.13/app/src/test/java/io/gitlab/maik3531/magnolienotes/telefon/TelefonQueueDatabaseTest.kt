package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class TelefonQueueDatabaseTest {
    private lateinit var context: Context
    private lateinit var queue: TelefonQueue
    private val storage = object : TelefonPayloadStorage {
        override fun encryptPayload(clear: ByteArray, type: String, id: String) = clear.copyOf()
        override fun decryptPayload(value: ByteArray, type: String, id: String) = value.copyOf()
    }

    @Before fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.deleteDatabase("magnolie_phone.db")
        queue = TelefonQueue(context, storage)
    }

    @After fun tearDown() {
        context.deleteDatabase("magnolie_phone.db")
    }

    @Test fun `terminal decision ack is removed while temporary rejection keeps same message`() {
        val terminalErrors = listOf("conflict", "restore_unavailable", "invalid_schema", "permanent_failure")
        terminalErrors.forEachIndexed { index, error ->
            val runId = uuid(40 + index)
            queue.rememberPersonalRun("peer", request(runId), System.currentTimeMillis() + 86_400_000)
            val message = queue.queueDeletionDecision("peer", decisionBody(index, runId), "any")
            val ack = queue.acknowledge("peer", message.string("message_id"), "rejected", error)
            assertEquals("terminal:$error", ack?.state)
            assertFalse(queue.due("peer", TelefonTransportArt.WIFI).any { it.messageId == message.string("message_id") })
        }

        val temporaryRun = uuid(50)
        queue.rememberPersonalRun("peer", request(temporaryRun), System.currentTimeMillis() + 86_400_000)
        val temporary = queue.queueDeletionDecision("peer", decisionBody(10, temporaryRun), "any")
        val ack = queue.acknowledge("peer", temporary.string("message_id"), "rejected", "not_granted")
        assertEquals("temporary:not_granted", ack?.state)
        assertTrue(queue.due("peer", TelefonTransportArt.WIFI).any { it.messageId == temporary.string("message_id") })

        val expiredRun = uuid(51)
        queue.rememberPersonalRun("peer", request(expiredRun), System.currentTimeMillis() + 86_400_000)
        val expired = queue.queueDeletionDecision("peer", decisionBody(11, expiredRun), "any")
        assertEquals("expired", queue.acknowledge("peer", expired.string("message_id"), "rejected", "expired")?.state)
        assertFalse(queue.due("peer", TelefonTransportArt.WIFI).any { it.messageId == expired.string("message_id") })
    }

    @Test fun `stale personal rows are removed transactionally without blocking unrelated messages`() {
        val now = 1_000L
        val expiredRun = uuid(20)
        queue.rememberPersonalRun("peer", request(expiredRun), now + 100, now)
        queue.queue("peer", "personal_sync.deletion_decision", decisionBody(20, expiredRun), 86_400_000, now)

        val missingRun = uuid(21)
        queue.queue("peer", "personal_sync.deletion_decision", decisionBody(21, missingRun), 86_400_000, now)

        val tamperedRun = uuid(22)
        queue.rememberPersonalRun("peer", request(tamperedRun), now + 10_000, now)
        queue.queue("peer", "personal_sync.deletion_decision", decisionBody(22, tamperedRun), 86_400_000, now)
        context.openOrCreateDatabase("magnolie_phone.db", Context.MODE_PRIVATE, null).use {
            it.execSQL("UPDATE personal_run SET trigger='tampered' WHERE run_id=?", arrayOf(tamperedRun))
        }

        val unrelated = queue.queue("peer", "device_status.request", buildJsonObject {
            put("request_id", JsonPrimitive(uuid(30))); put("version", JsonPrimitive(1))
        }, 86_400_000, now)

        val due = queue.due("peer", TelefonTransportArt.WIFI, now + 200)
        assertEquals(listOf(unrelated.string("message_id")), due.map { it.messageId })
        assertEquals(listOf(unrelated.string("message_id")),
            queue.due("peer", TelefonTransportArt.WIFI, now + 200).map { it.messageId })
    }

    @Test fun `format 2 report is queued only after attachment completion`() {
        val runId = uuid(60)
        val recordsHash = "a".repeat(64)
        val bytes = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
        val hash = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        queue.rememberPersonalRun("peer", request(runId), System.currentTimeMillis() + 86_400_000)
        val batch = buildJsonObject { put("run_id", JsonPrimitive(runId)); put("sequence", JsonPrimitive(0)) }
        val report = buildJsonObject { put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)) }

        assertTrue(queue.queuePersonalCompletion("peer", runId, listOf(batch), report, "any", recordsHash,
            listOf(Triple(hash, "image/png", bytes))))
        val before = queue.due("peer", TelefonTransportArt.WIFI)
        assertEquals(listOf("personal_sync.batch"), before.map { it.payload.string("kind") })
        before.forEach { queue.acknowledge("peer", it.messageId) }

        queue.completeOutgoingAttachment("peer", runId, true, recordsHash, hash)
        queue.releasePersonalReport("peer", runId, "any")
        assertEquals(listOf("personal_sync.report"),
            queue.due("peer", TelefonTransportArt.WIFI).map { it.payload.string("kind") })
    }

    private fun request(runId: String) = buildJsonObject {
        put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(runId)); put("trigger", JsonPrimitive("manual"))
        put("modules", JsonArray(listOf(JsonPrimitive("notes"))))
    }

    @Test fun `restore epoch invalidates old encrypted runs and queued payloads`() {
        var epoch = "before"
        val scoped = TelefonQueue(context, storage) { epoch }
        val runId = uuid(600)
        scoped.rememberPersonalRun("peer", request(runId), System.currentTimeMillis() + 60_000)
        scoped.queue("peer", "personal_sync.request", request(runId), 60_000)
        assertEquals(1, scoped.due("peer", TelefonTransportArt.WIFI).size)
        epoch = "after"
        assertEquals(null, scoped.personalRun("peer", runId))
        assertTrue(scoped.due("peer", TelefonTransportArt.WIFI).isEmpty())
        scoped.rememberPersonalRun("peer", request(uuid(601)), System.currentTimeMillis() + 60_000)
        assertTrue(scoped.personalRun("peer", uuid(601)) != null)
    }

    @Test fun `notification revocation removes only disallowed queued packages`() {
        for (name in listOf("allowed", "revoked")) queue.queue("peer", "selected_notifications_readonly.event",
            buildJsonObject { put("package", JsonPrimitive(name)) }, 60_000)
        queue.purgeNotifications(setOf("allowed"))
        assertEquals(listOf("allowed"), queue.due("peer", TelefonTransportArt.WIFI).map {
            (it.payload["body"] as kotlinx.serialization.json.JsonObject).string("package") })
    }

    @Test fun `control replay must match the durable original payload`() {
        val message = TelefonNachrichten.message("grants.update", TelefonNachrichten.grants(), 60_000)
        assertEquals("accepted", queue.receive("peer", message).first)
        assertTrue(queue.receivedMatches("peer", message))
        assertFalse(queue.receivedMatches("peer", kotlinx.serialization.json.JsonObject(message +
            ("body" to TelefonNachrichten.grants(2)))))
    }

    private fun decisionBody(index: Int, runId: String = uuid(40 + index)) = buildJsonObject {
        put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(runId)); put("decision_id", JsonPrimitive(uuid(80 + index)))
        put("decisions", JsonArray(listOf(buildJsonObject {
            put("proposal_id", JsonPrimitive(uuid(120 + index))); put("decision", JsonPrimitive("restore"))
            put("expected_clock", JsonArray(listOf(buildJsonObject {
                put("actor_id", JsonPrimitive(uuid(200 + index))); put("counter", JsonPrimitive(1))
            })))
        })))
    }

    private fun uuid(value: Int) = "%08x-0000-4000-8000-%012x".format(value, value)
}
