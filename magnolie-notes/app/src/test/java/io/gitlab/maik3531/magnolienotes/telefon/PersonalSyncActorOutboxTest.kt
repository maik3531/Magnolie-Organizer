package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.security.Provider
import java.security.Security

/** Actual encrypted queue with a synthetic Keystore; no listener or handset. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PersonalSyncActorOutboxTest {
    @Test fun actorWireMarkerSurvivesQueueReopenWithoutChangingOrdinaryTraffic() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = object : Provider("ActorOutboxFixture", 1.0, "Synthetic keys only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        val singleton = TelefonAblage::class.java.getDeclaredField("instance").apply { isAccessible = true }
        val prior = singleton.get(null); singleton.set(null, null)
        val helper = TelefonQueue::class.java.getDeclaredField("helper").apply { isAccessible = true }
        var queue: TelefonQueue? = null
        try {
            context.deleteDatabase("magnolie_phone.db")
            val storage = TelefonAblage.get(context)
            val active = TelefonQueue(context, storage); queue = active
            val peer = "22222222-2222-4222-8222-222222222222"
            val run = "11111111-1111-4111-8111-111111111111"
            val legacyRun = "33333333-3333-4333-8333-333333333333"
            fun request(id: String) = buildJsonObject {
                put("format", 3); put("run_id", id); put("trigger", "manual")
                put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks"))))
            }
            val now = System.currentTimeMillis()
            active.rememberPersonalRun(peer, request(run), now + 60000, now, actorRun = true)
            active.rememberPersonalRun(peer, request(legacyRun), now + 60000, now)
            val actor = active.queue(peer, "personal_sync.request", request(run), 60000, now)
            val ordinary = active.queue(peer, "personal_sync.request", request(legacyRun), 60000, now)
            (helper.get(active) as TelefonDatenbank).close(); queue = null
            singleton.set(null, null)
            val reopenedStorage = TelefonAblage.get(context)
            val reopened = TelefonQueue(context, reopenedStorage); queue = reopened
            val pending = reopened.due(peer, TelefonTransportArt.WIFI, now + 1).associateBy { it.messageId }
            assertEquals(actor, pending.getValue(actor.string("message_id")).payload)
            assertEquals(PersonalSyncActor.DATA_KIND, actor.string("kind"))
            assertEquals("personal_sync.request" to request(run), PersonalSyncActor.unwrap(actor.getValue("body").jsonObject))
            assertEquals(now, actor.long("created_ms")); assertEquals(now + 60000, actor.long("expires_ms"))
            assertEquals(ordinary, pending.getValue(ordinary.string("message_id")).payload)
            assertEquals("any", reopened.outboxPolicy(peer, actor.string("message_id")))
            context.openOrCreateDatabase("magnolie_phone.db", Context.MODE_PRIVATE, null).use { db ->
                db.rawQuery("SELECT kind,payload FROM outbox WHERE message_id=?", arrayOf(actor.string("message_id"))).use { row ->
                    assertTrue(row.moveToFirst()); assertEquals("personal_sync.request", row.getString(0))
                    val clear = reopenedStorage.decryptPayload(row.getBlob(1), "outbox", actor.string("message_id"))
                    try { assertEquals(actor, TelefonKanonisch.json.parseToJsonElement(clear.decodeToString())) } finally { clear.fill(0) }
                }
            }
            assertTrue(runCatching { reopened.queue(peer, "personal_sync.request", request(run), 60000, now, actorRunId = legacyRun) }.isFailure)
            assertTrue(runCatching { reopened.queue(peer, "personal_sync.settings", buildJsonObject { put("format", 1); put("own_device", true) }, 60000, now, actorRunId = run) }.isFailure)
            assertEquals(2, reopened.due(peer, TelefonTransportArt.WIFI, now + 1).size)
            val decisionId = "44444444-4444-4444-8444-444444444444"
            val decision = buildJsonObject {
                put("format", 1); put("run_id", run); put("decision_id", decisionId)
                put("decisions", JsonArray(listOf(buildJsonObject {
                    put("proposal_id", "55555555-5555-4555-8555-555555555555"); put("decision", "restore")
                    put("expected_clock", JsonArray(listOf(buildJsonObject {
                        put("actor_id", "66666666-6666-4666-8666-666666666666"); put("counter", 1)
                    })))
                })))
            }
            val decisionWire = reopened.queueDeletionDecision(peer, decision, "any")
            assertEquals(decisionWire, reopened.queueDeletionDecision(peer, decision, "any"))
            assertEquals("temporary:temporary_failure", reopened.acknowledge(peer, decisionWire.string("message_id"), "rejected", "temporary_failure")?.state)
            assertEquals(decisionWire, reopened.due(peer, TelefonTransportArt.WIFI, decisionWire.long("created_ms") + 1).single { it.messageId == decisionWire.string("message_id") }.payload)
            assertEquals(DeletionDecisionAck(decisionId, "accepted"), reopened.acknowledge(peer, decisionWire.string("message_id")))
            reopened.acknowledge(peer, actor.string("message_id"))
            assertEquals(listOf(ordinary), reopened.due(peer, TelefonTransportArt.WIFI, now + 1).map { it.payload })
            assertTrue(reopened.isActorRun(peer, run)); assertFalse(reopened.isActorRun(peer, legacyRun))
            assertTrue(runCatching { reopened.rememberPersonalRun(peer, request(run), now + 60000, now) }.isFailure)
            assertTrue(runCatching { reopened.rememberPersonalRun(peer, request(legacyRun), now + 60000, now, actorRun = true) }.isFailure)
            val lateChunk = buildJsonObject {
                put("format", 2); put("run_id", run); put("reply", false); put("records_hash", "a".repeat(64)); put("sha256", "b".repeat(64)); put("index", 0)
                put("data", java.util.Base64.getEncoder().encodeToString(byteArrayOf(1, 2, 3)))
            }
            val late = reopened.queue(peer, "personal_sync.attachment_chunk", lateChunk, 60000)
            assertEquals(PersonalSyncActor.DATA_KIND, late.string("kind"))
            assertEquals("personal_sync.attachment_chunk", PersonalSyncActor.unwrap(late.getValue("body").jsonObject).first)
            val changedScope = TelefonQueue(context, reopenedStorage) { "changed-book-scope" }
            try {
                assertTrue(changedScope.isActorRun(peer, run))
                assertTrue(runCatching { changedScope.queue(peer, "personal_sync.attachment_chunk", lateChunk, 60000) }.isFailure)
            } finally { (helper.get(changedScope) as TelefonDatenbank).close() }
            reopened.markPersonalRun(peer, run, "reported")
            assertTrue(reopened.isActorRun(peer, run))
            assertEquals(PersonalSyncActor.DATA_KIND, reopened.queue(peer, "personal_sync.attachment_chunk", lateChunk, 60000).string("kind"))
            repeat(33) { reopened.queue(peer, "personal_sync.attachment_chunk", lateChunk, 60000) }
            val ordinaryLate = reopened.queue(peer, "personal_sync.attachment_chunk",
                JsonObject(lateChunk + ("run_id" to JsonPrimitive(legacyRun))), 60000)
            reopened.stopActorRun(peer, run)
            assertTrue(runCatching { reopened.queue(peer, "personal_sync.attachment_chunk", lateChunk, 60000) }.isFailure)
            assertTrue(reopened.due(peer, TelefonTransportArt.WIFI).none { it.messageId == late.string("message_id") })
            assertEquals(late, reopened.outboxWireMessage(peer, late.string("message_id")))
            assertTrue(reopened.due(peer, TelefonTransportArt.WIFI).any { it.payload == ordinaryLate })
        } finally {
            queue?.let { (helper.get(it) as TelefonDatenbank).close() }
            context.deleteDatabase("magnolie_phone.db")
            singleton.set(null, prior); Security.removeProvider(provider.name)
        }
    }
}
