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
    @Test fun correlatedCallerRunSurvivesScopePreparationAndReceiptGates() = exercise("actor")
    @Test fun reservedActorWireWaitsForItsOwnTransportRouteWithoutLegacyFallback() = exercise("actor-wire")
    @Test fun unadmittedActorReceiveNeverReachesOrdinaryStorageOrDocumentState() = exercise("actor-receive")
    @Test fun actorScopeSnapshotPersistsProtectedClassificationAndWireMarkersBeforeSending() = exercise("actor-snapshot")
    @Test fun actorSourceBindsTheActualChannelFreshControlsAndCurrentBookScope() = exercise("actor-source")
    @Test fun actorCancellationRetiresQueuedSnapshotWithoutChangingTheBook() = exercise("actor-cancel")
    @Test fun actorCancellationBeforeSnapshotPreventsLaterProducerWork() = exercise("actor-cancel-pending")
    @Test fun actorGrantRevocationRetiresPendingSnapshotInsteadOfWaitingForLegacyControls() = exercise("actor-revoked")
    @Test fun nativeMaintenanceRetiresPreviousActorEpochWithoutRebindingItsQueueRun() = exercise("actor-restart")
    @Test fun nativeActorStartOwnsEncryptedSnapshotDispatchAndMarkedAckCancellation() = exercise("actor-transport")
    @Test fun nativeActorDeletionIntentsStayPrivateAndRequirePriorClockScopeAndGrants() = exercise("actor-deletions")
    @Test fun nativeActorDeletionSkipChoiceBlocksIntentsWithBothGrantsPresent() = exercise("actor-deletions-skip")
    @Test fun nativeActorCompleteReportCheckpointsAndPersistsPrivateReplyExactlyOnce() = exercise("actor-commit")
    @Test fun nativeActorCompleteReportRejectsConcurrentPhoneBookChange() = exercise("actor-commit-changed")
    @Test fun independentTimeChangeDefersScopedDataWithoutAdmittingRawFallback() = exercise("time")
    @Test fun selectedOrganizerNoteCanBeSentAgainAfterDeletingItsPhoneCopy() = exercise("single")
    @Test fun ownershipControlAndItsAckDoNotRequireContentRunId() = exercise("ownership")
    @Test fun organizerDeletionRemovesPhoneCopyAndKeepsItsAcknowledgmentAcrossMembershipChange() = exercise("delete")
    @Test fun skippingDeletionsKeepsThePhoneCopy() = exercise("skip-delete")
    @Test fun sharedChoicesFromEitherDeviceConvergeWithoutOldEchoUndoingTheLatestChoice() = exercise("preferences")
    @Test fun authenticatedUnpairClearsOnlyTheCurrentComputerAndKeepsPhoneContent() = exercise("unpair")

    @Test fun provenanceFormatUsesScopedTransportAndRetainsOriginalAppOnReceive() = exercise("receive", 14)
    @Test fun provenanceFormatProducesACompleteMatchingScopedReply() = exercise("receive-request", 14)
    @Test fun provenanceFormatSurvivesManualScopeAndReceiptGates() = exercise("manual", 14)
    @Test fun provenanceFormatUsesTheNativeActorCommitAndCompletionReport() = exercise("actor-commit", 14)
    @Test fun provenanceFormatCanAdmitOneSelectedOrganizerNote() = exercise("single", 14)
    @Test fun aNoteSwipeQueuesOnlyItsSelectedEntryAndWaitsForRequestReceipt() = exercise("send-note", 14)
    @Test fun aTaskSwipeQueuesOnlyItsSelectedEntryAndWaitsForRequestReceipt() = exercise("send-task", 14)
    @Test fun offlineSingleSendDoesNotQueueOrStartAFullRun() = exercise("send-offline", 14)
    @Test fun revokedSingleSendDoesNotQueueOrStartAFullRun() = exercise("send-revoked", 14)
    @Test fun linkedNotesUsePersonalRouteWhileForeignNotesAndDelegatedTasksDoNot() = exercise("send-route", 14)

    private fun exercise(mode: String, format: Int = 3) {
        val actorDeletion = mode.startsWith("actor-deletions")
        val actorCommit = mode.startsWith("actor-commit")
        val nativeActor = actorDeletion || actorCommit || mode in setOf("actor-source", "actor-snapshot", "actor-cancel", "actor-cancel-pending", "actor-revoked", "actor-restart", "actor-transport")
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
            documents.setzeNotiz(Notiz("phone-note", "Mobile", "Initial phone text", notizbuchId = book.id, angelegt = 1, geaendert = 2,
                ursprungApp = if (format == 14) "notes" else "",
                baumQuelle = if (mode == "send-route") "linked-origin" else "",
                persoenlichVerknuepft = mode == "send-route"))
            if (actorDeletion || actorCommit || mode.startsWith("send-") || mode in setOf("manual", "actor", "actor-snapshot", "actor-cancel", "actor-cancel-pending", "actor-revoked", "actor-transport")) documents.setzeAufgabe(Aufgabe("phone-task", "Mobile task"))
            if (mode.startsWith("send-")) {
                documents.setzeNotiz(Notiz("private-note", "Unselected note", "Never transfer", notizbuchId = book.id))
                documents.setzeAufgabe(Aufgabe("private-task", "Unselected task",
                    delegiertAn = if (mode == "send-route") "tree-peer" else ""))
                if (mode == "send-route") documents.setzeNotiz(Notiz("foreign-note", "Foreign tree note", baumQuelle = "tree-peer"))
            }
            val storage = TelefonAblage.get(context)
            storage.identity("Synthetic").second.fill(0)
            storage.setEnabled(true); storage.setPersonalSync(true, true, true, false, false)
            val peerId = "22222222-2222-4222-8222-222222222222"
            val peer = TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32) { 23 }),
                own_device = true, remote_own_device = true, personal_notes_sync_granted = true, personal_tasks_sync_granted = true,
                remote_personal_notes_sync_granted = true, remote_personal_tasks_sync_granted = true,
                personal_deletions_sync_granted = actorDeletion || mode in setOf("delete", "skip-delete"), remote_personal_deletions_sync_granted = actorDeletion || mode in setOf("delete", "skip-delete"),
                remote_personal_notes_sync_available = true, remote_personal_tasks_sync_available = true,
                remote_personal_notes_sync_versions = listOf(1, 2, 3, 5, 9, 10) + (if (format == 14) listOf(14) else emptyList()) + if (nativeActor) listOf(12) else emptyList(),
                remote_personal_tasks_sync_versions = listOf(1, 2, 3, 4, 6, 7, 9, 10) + (if (format == 14) listOf(14) else emptyList()) + if (nativeActor) listOf(12) else emptyList())
            storage.savePeer(peer)
            val work = TelefonWerk.get(context)
            runtimeWork = work
            work.sharedLocalCapabilities = { TelefonCapabilities.phase1() }
            if (nativeActor) work.sharedLocalCapabilities = {
                TelefonCapabilities.phase1().mapValues { (name, value) ->
                    if (name in setOf("personal_notes_sync", "personal_tasks_sync")) value.copy(versions = value.versions + 12) else value
                }
            }
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
            var local = work.changeSharedSetting(peerId, peer.static_public, "content_mode", JsonPrimitive("phone_scope"))
            if (mode in setOf("delete", "actor-deletions")) local = work.changeSharedSetting(peerId, peer.static_public, "skip_deletions", JsonPrimitive(false))
            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
            val identity = storage.identity("Synthetic"); val actor = identity.first.device_id; identity.second.fill(0)
            val shared = SharedSyncSettings.merge(SharedSyncSettings.create(peerId), local, peerId, actor)
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                var session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true }
                if (nativeActor) session.observeActorOwnDecision(true)
                @Suppress("UNCHECKED_CAST")
                val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                sessions[channel] = session
                work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, shared, 60000), channel, 0)
                val pump = TelefonWerk::class.java.getDeclaredMethod("sendDue", TelefonPeer::class.java, TelefonSecureChannel::class.java,
                    Long::class.javaPrimitiveType, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
                val ownership = if (mode == "ownership") TelefonNachrichten.message("personal_sync.settings",
                    buildJsonObject { put("format", 1); put("own_device", true) }, 60000).also { queue.queuePrepared(peerId, it) } else null
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
                if (mode.startsWith("send-")) {
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    (field(TelefonWerk::class.java, "scopedWakeup").get(work) as AtomicBoolean).set(true)
                    sent()
                    assertFalse(work.personalItemSyncAvailable("note"))
                    assertNull(work.personalItemSyncIfAvailable("note", "phone-note"))
                    assertTrue("Unacknowledged membership permitted a send", runCatching { work.personalItemSyncNow("note", "phone-note") }.isFailure)
                    ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    if (mode == "send-route") {
                        assertTrue(work.personalItemSyncAvailable("note", "phone-note"))
                        assertFalse(work.personalItemSyncAvailable("note", "foreign-note"))
                        assertNull(work.personalItemSyncIfAvailable("note", "foreign-note"))
                        assertFalse(work.personalItemSyncAvailable("task", "private-task"))
                        assertNull(work.personalItemSyncIfAvailable("task", "private-task"))
                        assertFalse(queue.hasActiveScopedRun(peerId))
                    }
                    if (mode == "send-offline") field(TelefonWerk::class.java, "activeChannel").set(work, null)
                    if (mode == "send-revoked") storage.savePeer(peer.copy(remote_personal_notes_sync_granted = false))
                    if (mode in setOf("send-offline", "send-revoked")) {
                        assertFalse(work.personalItemSyncAvailable("note"))
                        assertNull(work.personalItemSyncIfAvailable("note", "phone-note"))
                        assertTrue(runCatching { work.personalItemSyncNow("note", "phone-note") }.isFailure)
                        assertFalse(queue.hasActiveScopedRun(peerId))
                        assertEquals(2, documents.notizen().size); assertEquals(2, documents.bestand.value.aufgaben.size)
                        return@use
                    }
                    val kind = if (mode == "send-task") "task" else "note"
                    val id = if (kind == "task") "phone-task" else "phone-note"
                    assertTrue(work.personalItemSyncAvailable(kind))
                    field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.BLUETOOTH to pipe)
                    assertFalse(work.personalItemSyncAvailable(kind))
                    assertNull(work.personalItemSyncIfAvailable(kind, id))
                    assertFalse(queue.hasActiveScopedRun(peerId))
                    field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
                    assertTrue(work.personalItemSyncAvailable(kind))
                    val run = requireNotNull(work.personalItemSyncIfAvailable(kind, id))
                    pump.invoke(work, peer, channel, 0L, false)
                    val outgoing = scoped(sent())
                    assertEquals(1, outgoing.size)
                    val request = PhoneContentScope.unwrap(outgoing.single().getValue("body").jsonObject, manifest)
                    assertEquals("personal_sync.request", request.first)
                    val wireId = if (kind == "note") PersonalSync.noteWireId(documents.bestand.value.personalSync, id) else id
                    assertEquals(wireId, request.second.getValue("send_item").jsonObject.string("id"))
                    assertEquals(run, request.second.string("run_id"))
                    assertFalse(queue.scopedRequestAccepted(peerId, run))
                    ack(outgoing.single().string("message_id")); pump.invoke(work, peer, channel, 0L, false)
                    val batches = scoped(sent()).map { PhoneContentScope.unwrap(it.getValue("body").jsonObject, manifest) }
                        .filter { it.first == "personal_sync.batch" }.map { it.second }
                    assertTrue(batches.isNotEmpty())
                    val records = batches.flatMap(PersonalSyncProtokoll::decodeBatch)
                    assertEquals(listOf(wireId), records.filter { it.kind != "notebook" }.map { it.id })
                    assertTrue(records.none { it.id in setOf("private-note", "private-task") })
                    assertEquals(if (mode == "send-route") 3 else 2, documents.notizen().size); assertEquals(2, documents.bestand.value.aufgaben.size)
                    return@use
                }
                if (mode == "actor-transport" || actorDeletion || actorCommit) {
                    sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    TelefonWerk::class.java.getDeclaredMethod("refreshSharedPreferenceState").apply { isAccessible = true }.invoke(work)
                    val beforeState = work.state.value; val beforeBook = documents.bestand.value
                    val run = "44444444-4444-4444-8444-444444444444"
                    val start = TelefonNachrichten.message(PersonalSyncActor.START_KIND, PersonalSyncActor.start(run), 60000)
                    work.receiveMessage(peer, start, channel, 0L)
                    val accepted = sent().single { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) }
                    assertEquals("accepted", accepted.getValue("body").jsonObject.string("status"))
                    work.receiveMessage(peer, start, channel, 0L)
                    assertEquals("duplicate", sent().single().getValue("body").jsonObject.string("status"))
                    pump.invoke(work, peer, channel, 0L, false)
                    val request = sent().single { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                    assertEquals("personal_sync.request", PersonalSyncActor.unwrap(request.getValue("body").jsonObject).first)
                    assertFalse(queue.scopedRequestAccepted(peerId, run))
                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                        PersonalSyncActor.ack(run, request.string("message_id")), 60000), channel, 0L)
                    assertTrue(sent().isEmpty()); assertTrue(queue.scopedRequestAccepted(peerId, run))
                    pump.invoke(work, peer, channel, 0L, false)
                    val batches = sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                    val batch = batches.single { PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.batch" }
                    val records = PersonalSyncProtokoll.decodeBatch(PersonalSyncActor.unwrap(batch.getValue("body").jsonObject).second)
                    assertEquals(setOf("phone-note"), records.filter { it.kind == "note" }.map { it.id }.toSet())
                    assertEquals(setOf("phone-task"), records.filter { it.kind == "task" }.map { it.id }.toSet())
                    ack(batch.string("message_id"))
                    assertEquals(batch, queue.outboxWireMessage(peerId, batch.string("message_id")))
                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                        PersonalSyncActor.ack("55555555-5555-4555-8555-555555555555", batch.string("message_id")), 60000), channel, 0L)
                    assertEquals(batch, queue.outboxWireMessage(peerId, batch.string("message_id")))
                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                        PersonalSyncActor.ack(run, batch.string("message_id")), 60000), channel, 0L)
                    assertNull(queue.outboxWireMessage(peerId, batch.string("message_id"))); assertTrue(sent().isEmpty())
                    val old = records.single { it.kind == "note" }
                    if (actorDeletion) {
                        val privatePeer = PersonalSyncActor.storagePeer(run)
                        val proposalId = UUID.randomUUID().toString()
                        val clock = JsonArray(listOf(buildJsonObject { put("actor_id", peerId); put("counter", 1) }))
                        val proposal = buildJsonObject {
                            put("proposal_id", proposalId); put("kind", "note"); put("id", "phone-note"); put("parent_id", "")
                            put("clock", clock); put("prior_hash", old.hash); put("deleted_ms", System.currentTimeMillis()); put("label", "Mobile")
                        }
                        fun proposals(value: JsonObject = proposal) = TelefonNachrichten.message("personal_sync.deletion_proposals", buildJsonObject {
                            put("format", 1); put("run_id", run); put("proposals", JsonArray(listOf(value)))
                            put("proposal_batch_id", UUID.randomUUID().toString()); put("sequence", 0); put("last", true)
                        }, 86_400_000)
                        fun decision(expected: JsonArray = clock) = TelefonNachrichten.message("personal_sync.deletion_decision", buildJsonObject {
                            put("format", 1); put("run_id", run); put("decision_id", UUID.randomUUID().toString())
                            put("decisions", JsonArray(listOf(buildJsonObject {
                                put("proposal_id", proposalId); put("decision", "delete"); put("expected_clock", expected)
                            })))
                        }, 86_400_000)
                        fun receive(value: JsonObject) { work.receiveMessage(peer, PersonalSyncActor.wireMessage(value, run), channel, 0L); assertTrue(sent().isEmpty()) }
                        val valid = proposals()
                        if (mode == "actor-deletions-skip") {
                            receive(valid); assertTrue(queue.actorDeletionIntents(run).isEmpty())
                            assertEquals(beforeBook.copy(personalSync = documents.bestand.value.personalSync), documents.bestand.value)
                            work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.CANCEL_KIND, PersonalSyncActor.cancel(run), 60000), channel, 0L); sent()
                            assertEquals(beforeState, work.state.value)
                            return@use
                        }
                        val boundPeer = requireNotNull(storage.peers().peer)
                        storage.savePeer(boundPeer.copy(remote_personal_deletions_sync_granted = false))
                        receive(valid); assertTrue(queue.actorDeletionIntents(run).isEmpty())
                        storage.savePeer(boundPeer.copy(personal_deletions_sync_granted = false))
                        receive(valid); assertTrue(queue.actorDeletionIntents(run).isEmpty())
                        storage.savePeer(boundPeer)
                        receive(proposals(JsonObject(proposal + ("id" to JsonPrimitive("outside-scope")))))
                        assertTrue(queue.actorDeletionIntents(run).isEmpty())
                        receive(valid); receive(valid)
                        assertEquals(listOf(valid), queue.actorDeletionIntents(run))
                        val otherRun = "55555555-5555-4555-8555-555555555555"
                        val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                        database.execSQL("INSERT INTO inbox(message_id,peer_id,kind,received_ms,expires_ms,payload,state) SELECT message_id,?,kind,received_ms,expires_ms,payload,state FROM inbox WHERE peer_id=? AND message_id=?",
                            arrayOf(PersonalSyncActor.storagePeer(otherRun), privatePeer, valid.string("message_id")))
                        assertTrue(runCatching { queue.actorDeletionIntents(otherRun) }.isFailure)
                        queue.purgePersonal(PersonalSyncActor.storagePeer(otherRun))
                        receive(decision()); assertEquals(1, queue.actorDeletionIntents(run).size)
                        queue.stageActorDeletionIntent(run, proposals(), outgoing = true)
                        receive(decision(JsonArray(listOf(buildJsonObject { put("actor_id", peerId); put("counter", 2) }))))
                        assertEquals(1, queue.actorDeletionIntents(run).size)
                        val acceptedDecision = decision(); receive(acceptedDecision); receive(acceptedDecision)
                        assertEquals(2, queue.actorDeletionIntents(run).size)
                        assertEquals(beforeBook.copy(personalSync = documents.bestand.value.personalSync), documents.bestand.value)
                        work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.CANCEL_KIND, PersonalSyncActor.cancel(run), 60000), channel, 0L)
                        assertEquals("accepted", sent().single().getValue("body").jsonObject.string("status"))
                        assertTrue(queue.actorDeletionIntents(run).isEmpty()); assertTrue(queue.actorDeletionIntents(run, true).isEmpty())
                        assertEquals(beforeState, work.state.value)
                        assertEquals(beforeBook.copy(personalSync = documents.bestand.value.personalSync), documents.bestand.value)
                        return@use
                    }
                    val image = ByteArray(PersonalSyncProtokoll.CHUNK_RAW * 9 + 11).also {
                        byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10, 1, 2, 3).copyInto(it)
                    }
                    val imageHash = java.security.MessageDigest.getInstance("SHA-256").digest(image).joinToString("") { "%02x".format(it) }
                    val descriptor = buildJsonObject {
                        put("attachment_id", JsonPrimitive("desktop-image")); put("name", JsonPrimitive("desktop.png"))
                        put("kind", JsonPrimitive("image")); put("mime", JsonPrimitive("image/png"))
                        put("size", JsonPrimitive(image.size)); put("sha256", JsonPrimitive(imageHash))
                    }
                    val privateValue = JsonObject(old.value + mapOf("text" to JsonPrimitive("Private desktop draft"),
                        "modified_ms" to JsonPrimitive(old.modifiedMs + 1), "attachments" to JsonArray(listOf(descriptor))))
                    val incoming = old.copy(value = privateValue, hash = PersonalSync.hash(privateValue), modifiedMs = old.modifiedMs + 1,
                        clock = if (actorCommit) PersonalSync.merge(old.clock, listOf(PersonalSyncClock(peerId, 1))) else old.clock)
                    val incomingBody = PersonalSyncProtokoll.batch(run, listOf(incoming), 0, true, true, format, PersonalSync.recordsHash(listOf(incoming)))
                    val incomingWire = PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.batch", incomingBody, 86_400_000), run)
                    work.receiveMessage(peer, incomingWire, channel, 0L)
                    assertEquals(incomingWire.string("message_id"), sent().single().getValue("body").jsonObject.string("message_id"))
                    val privatePeer = PersonalSyncActor.storagePeer(run)
                    val completionWire = PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.report", buildJsonObject {
                        put("format", format); put("run_id", run); put("state", "complete"); put("trigger", "manual"); put("transport", "wifi")
                        for (name in listOf("sent", "received")) put(name, buildJsonObject { put("notes", 1); put("tasks", if (name == "received") 1 else 0); put("notebooks", 0) })
                        put("conflicts", 0); put("attachments_omitted", 0); put("oversized_skipped", 0)
                        put("started_ms", System.currentTimeMillis()); put("finished_ms", System.currentTimeMillis()); put("error", "none")
                        put("attachments", buildJsonObject { for (name in listOf("declared", "requested", "sent", "received", "preserved")) put(name, 1)
                            for (name in listOf("reused", "failed")) put(name, 0); put("bytes", image.size) })
                        put("deletions", buildJsonObject { for (name in listOf("pending", "deleted", "restored", "conflicts", "blocked")) put(name, 0)
                            put("trash", buildJsonObject { for (name in listOf("notes", "tasks", "notebooks", "attachments")) put(name, 0) }) })
                    }, 86_400_000), run)
                    if (actorCommit) {
                        work.receiveMessage(peer, completionWire, channel, 0L)
                        assertTrue(sent().isEmpty()); assertEquals("Initial phone text", documents.notizen().single { it.id == "phone-note" }.text)
                        assertFalse(queue.personalDirectionApplied(peerId, run, true))
                    }
                    val staged = queue.readyPersonalBatches().single { it.first == privatePeer }
                    assertEquals("Private desktop draft", PersonalSyncProtokoll.decodeBatch(staged.second.single().getValue("body").jsonObject).single().value.string("text"))
                    work.receiveMessage(peer, incomingWire, channel, 0L); sent()
                    assertEquals(staged, queue.readyPersonalBatches().single { it.first == privatePeer })
                    pump.invoke(work, peer, channel, 0L, false)
                    val attachmentRequests = sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                        .map { PersonalSyncActor.unwrap(it.getValue("body").jsonObject) }.filter { it.first == "personal_sync.attachment_request" }
                    assertEquals(2, attachmentRequests.size)
                    assertEquals(listOf(0, 8), attachmentRequests.map {
                        (((it.second.getValue("wants") as JsonArray).single().jsonObject.getValue("ranges") as JsonArray).single() as JsonArray).first().jsonPrimitive.content.toInt()
                    }.sorted())
                    fun imageChunk(index: Int, hash: String = imageHash): JsonObject = PersonalSyncActor.wireMessage(
                        TelefonNachrichten.message("personal_sync.attachment_chunk", buildJsonObject {
                            put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(run)); put("reply", JsonPrimitive(true))
                            put("records_hash", incomingBody.getValue("records_hash")); put("sha256", JsonPrimitive(hash)); put("index", JsonPrimitive(index))
                            put("data", JsonPrimitive(java.util.Base64.getEncoder().encodeToString(image.copyOfRange(index * PersonalSyncProtokoll.CHUNK_RAW,
                                minOf(image.size, (index + 1) * PersonalSyncProtokoll.CHUNK_RAW)))))
                        }, 86_400_000), run)
                    work.receiveMessage(peer, imageChunk(0, "a".repeat(64)), channel, 0L)
                    assertTrue(sent().isEmpty())
                    repeat(10) { index ->
                        val chunk = imageChunk(index)
                        work.receiveMessage(peer, chunk, channel, 0L)
                        assertEquals(chunk.string("message_id"), sent().single().getValue("body").jsonObject.string("message_id"))
                        if (index == 9) {
                            work.receiveMessage(peer, chunk, channel, 0L); sent()
                            work.receiveMessage(peer, imageChunk(index), channel, 0L); sent()
                        }
                    }
                    val verified = ByteArrayOutputStream()
                    assertTrue(queue.verifyIncomingAttachment(privatePeer, run, true, incomingBody.string("records_hash"), imageHash, verified))
                    assertArrayEquals(image, verified.toByteArray())
                    pump.invoke(work, peer, channel, 0L, false)
                    assertEquals(1, sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                        .count { PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.attachment_result" })
                    if (actorCommit) {
                        if (mode == "actor-commit-changed") documents.setzeNotiz(documents.notizen().single { it.id == "phone-note" }.copy(text = "Concurrent phone edit"))
                        work.receiveMessage(peer, completionWire, channel, 0L)
                        if (mode == "actor-commit-changed") {
                            assertTrue(sent().isEmpty()); assertFalse(queue.personalDirectionApplied(peerId, run, true))
                            assertEquals("Concurrent phone edit", documents.notizen().single { it.id == "phone-note" }.text)
                        } else {
                            assertEquals(completionWire.string("message_id"), sent().single().getValue("body").jsonObject.string("message_id"))
                            assertTrue(queue.personalDirectionApplied(peerId, run, true))
                            assertEquals("Private desktop draft", documents.notizen().single { it.id == "phone-note" }.text)
                            val reopened = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                            assertEquals("Private desktop draft", reopened.notizen().single { it.id == "phone-note" }.text)
                            if (format == 14) assertEquals("notes", reopened.notizen().single { it.id == "phone-note" }.ursprungApp)
                            assertEquals(1, reopened.notizen().single { it.id == "phone-note" }.anhaenge.size)
                            assertTrue(io.gitlab.maik3531.magnolienotes.journal.AndroidJournal.hole(context).state.value.entries.any { it.reason == "pre-sync-note" })
                            val savedBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                            work.receiveMessage(peer, completionWire, channel, 0L); assertEquals(1, sent().size)
                            assertArrayEquals(savedBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                            assertTrue(queue.readyPersonalBatches().none { it.first == privatePeer })
                        }
                        work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.CANCEL_KIND, PersonalSyncActor.cancel(run), 60000), channel, 0L); sent()
                        return@use
                    }
                    val foreign = incoming.copy(id = "outside-phone-scope")
                    val foreignBody = PersonalSyncProtokoll.batch(run, listOf(foreign), 0, true, true, format, PersonalSync.recordsHash(listOf(foreign)))
                    work.receiveMessage(peer, PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.batch", foreignBody, 60000), run), channel, 0L)
                    assertTrue(sent().isEmpty())
                    pump.invoke(work, peer, channel, 0L, false); sent()
                    assertEquals(beforeBook.copy(personalSync = documents.bestand.value.personalSync), documents.bestand.value)
                    val cancel = TelefonNachrichten.message(PersonalSyncActor.CANCEL_KIND, PersonalSyncActor.cancel(run), 60000)
                    work.receiveMessage(peer, cancel, channel, 0L)
                    assertEquals("accepted", sent().single().getValue("body").jsonObject.string("status"))
                    assertTrue(queue.readyPersonalBatches().none { it.first == privatePeer })
                    assertFalse(queue.verifyIncomingAttachment(privatePeer, run, true, incomingBody.string("records_hash"), imageHash, ByteArrayOutputStream()))
                    pump.invoke(work, peer, channel, 0L, false)
                    assertTrue(sent().none { PersonalSyncActor.isReservedMessage(it) })
                    assertEquals(beforeState, work.state.value)
                    assertEquals(beforeBook.copy(personalSync = documents.bestand.value.personalSync), documents.bestand.value)
                    return@use
                }
                if (mode == "actor-restart") {
                    sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    val revision = requireNotNull(work.currentActorSource(peerId, peer.static_public, channel, 0L))
                    val previous = PersonalSyncActorJournal(field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank,
                        storage, { id, key -> work.currentActorSource(id, key, channel, 0L) }, { documents.baum.value.syncEpoch },
                        ownerEpoch = "a".repeat(64), sourceLock = work, bookLock = Ablage.SCHREIBSPERRE)
                    val old = previous.create(peerId, peer.static_public, revision)
                    val request = buildJsonObject {
                        put("format", format); put("run_id", old.runId); put("trigger", "manual")
                        put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks"))))
                    }
                    queue.rememberPersonalRun(peerId, request, System.currentTimeMillis() + 60000, actorRun = true)
                    val wire = queue.queue(peerId, "personal_sync.request", request, 60000)
                    val privatePeer = PersonalSyncActor.storagePeer(old.runId)
                    val privateBody = PersonalSyncProtokoll.batch(old.runId, emptyList(), 0, true, true, format, PersonalSync.recordsHash(emptyList()))
                    queue.stagePersonalBatch(privatePeer, TelefonNachrichten.message("personal_sync.batch", privateBody, 60000))
                    assertTrue(queue.readyPersonalBatches().any { it.first == privatePeer })
                    val before = documents.bestand.value
                    work.maintenance()
                    assertTrue(runCatching { previous.stopped(old) }.isFailure)
                    assertTrue(queue.isActorRun(peerId, old.runId))
                    assertTrue(runCatching { queue.queue(peerId, "personal_sync.request", request, 60000) }.isFailure)
                    assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).none { it.messageId == wire.string("message_id") })
                    assertEquals(wire, queue.outboxWireMessage(peerId, wire.string("message_id")))
                    assertTrue(queue.readyPersonalBatches().none { it.first == privatePeer })
                    assertEquals(before, documents.bestand.value)
                    return@use
                }
                if (mode == "actor-source") {
                    fun source() = work.currentActorSource(peerId, peer.static_public, channel, 0L)
                    fun completionAuthority() = work.currentActorCompletionAuthority(peerId, peer.static_public, channel, 0L)
                    assertNull(source())
                    assertNull(completionAuthority())
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    assertNull(source()) // The manifest must actually have been acknowledged.
                    sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    val revision = requireNotNull(source())
                    assertNotEquals(revision, requireNotNull(completionAuthority()))
                    val boundPeer = requireNotNull(storage.peers().peer)
                    assertTrue(Regex("[0-9a-f]{64}").matches(revision)); assertEquals(revision, source())
                    assertNull(work.currentActorSource(peerId, peer.static_public, channel, 1L))
                    assertNull(work.currentActorCompletionAuthority(peerId, peer.static_public, channel, 1L))
                    assertNull(work.currentActorSource(peerId, TelefonKrypto.b64(ByteArray(32) { 24 }), channel, 0L))
                    val capabilities = work.sharedLocalCapabilities
                    work.sharedLocalCapabilities = { TelefonCapabilities.phase1() }
                    assertNull(source()); work.sharedLocalCapabilities = capabilities
                    session.grantsReceived = false; assertNull(source()); assertNull(completionAuthority()); session.grantsReceived = true
                    session.ownSettingsReceived = false; assertNull(source()); assertNull(completionAuthority()); session.ownSettingsReceived = true
                    for (revoked in listOf(boundPeer.copy(state = "paired_unverified"), boundPeer.copy(remote_personal_notes_sync_granted = false),
                        boundPeer.copy(personal_notes_sync_granted = false), boundPeer.copy(remote_personal_tasks_sync_granted = false))) {
                        storage.savePeer(revoked); assertNull(source()); assertNull(completionAuthority())
                    }
                    storage.savePeer(boundPeer)
                    assertEquals(revision, source())
                    val journal = work.personalActorJournal
                    val handle = journal.create(peerId, peer.static_public, revision)
                    assertEquals(7, journal.withActive(handle) { 7 })
                    val oldSession = session
                    session = PersonalNoteSession().apply {
                        capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                        observeActorOwnDecision(true)
                        sharedSent = oldSession.sharedSent; sharedReceived = oldSession.sharedReceived
                        localContentScope = oldSession.localContentScope; contentScopeSelection = oldSession.contentScopeSelection
                        contentScopeRestoreEpoch = oldSession.contentScopeRestoreEpoch; contentScopePreference = oldSession.contentScopePreference
                        contentScopeAccepted.addAll(oldSession.contentScopeAccepted)
                    }
                    sessions[channel] = session
                    assertNotEquals(revision, requireNotNull(source())); assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
                    session = oldSession; sessions[channel] = session
                    session.observeActorOwnDecision(false); assertNull(source())
                    session.observeActorOwnDecision(true)
                    val reownedSource = requireNotNull(source())
                    assertNotEquals(revision, reownedSource)
                    assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
                    session.observeActorOwnDecision(true); assertEquals(reownedSource, source())
                    field(TelefonWerk::class.java, "activeChannel").set(work, null)
                    assertNull(source()); assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    storage.savePeer(boundPeer.copy(remote_grants_revision = boundPeer.remote_grants_revision + 1))
                    assertNotEquals(reownedSource, source())
                    storage.savePeer(boundPeer)
                    val beforeScopeAuthority = requireNotNull(completionAuthority())
                    documents.setzeNotiz(Notiz("scope-change", "Additional", "New scope member"))
                    assertNull(source()); assertNull(completionAuthority()); assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
                    pump.invoke(work, peer, channel, 0L, false); sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    assertNotEquals(reownedSource, requireNotNull(source()))
                    assertEquals(beforeScopeAuthority, completionAuthority())
                    assertTrue(runCatching { journal.withActive(handle) { 0 } }.isFailure)
                    journal.retire(handle)
                    return@use
                }
                if (mode in setOf("actor-snapshot", "actor-cancel", "actor-cancel-pending", "actor-revoked")) {
                    sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    val run = "44444444-4444-4444-8444-444444444444"
                    val beforeBook = documents.bestand.value
                    val handle = work.preparePersonalActor(peerId, peer.static_public, run)
                    if (mode == "actor-cancel-pending") work.stopPersonalActor(handle)
                    if (mode == "actor-revoked") storage.savePeer(requireNotNull(storage.peers().peer).copy(remote_personal_tasks_sync_granted = false))
                    pump.invoke(work, peer, channel, 0L, false)
                    if (mode in setOf("actor-cancel-pending", "actor-revoked")) {
                        assertTrue(work.personalActorJournal.stopped(handle))
                        assertNull(queue.personalRun(peerId, run))
                        assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).none { it.payload["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                        assertEquals(beforeBook, documents.bestand.value)
                        return@use
                    }
                    assertTrue(queue.isActorRun(peerId, run))
                    val actorFrames = queue.due(peerId, TelefonTransportArt.WIFI).map { it.payload }.filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                    assertTrue(actorFrames.size >= 2)
                    val semantic = actorFrames.map { PersonalSyncActor.unwrap(it.getValue("body").jsonObject) }
                    assertTrue(semantic.any { it.first == "personal_sync.request" })
                    val records = semantic.filter { it.first == "personal_sync.batch" }.flatMap { PersonalSyncProtokoll.decodeBatch(it.second) }
                    assertEquals(setOf("phone-note"), records.filter { it.kind == "note" }.map { it.id }.toSet())
                    assertEquals(setOf("phone-task"), records.filter { it.kind == "task" }.map { it.id }.toSet())
                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                    assertTrue(runCatching { queue.rememberPersonalRun(peerId, requireNotNull(queue.personalRun(peerId, run)), System.currentTimeMillis() + 60000) }.isFailure)
                    if (mode == "actor-cancel") {
                        work.stopPersonalActor(handle); work.stopPersonalActor(handle)
                        assertTrue(work.personalActorJournal.stopped(handle))
                        assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).none { it.payload["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                        assertEquals(actorFrames.first(), queue.outboxWireMessage(peerId, actorFrames.first().string("message_id")))
                        var touched = false
                        assertTrue(runCatching { work.personalActorJournal.withActive(handle) { touched = true } }.isFailure)
                        assertFalse(touched)
                        // Existing source reconcile may persist protocol bookkeeping, never user content.
                        assertEquals(beforeBook.copy(personalSync = documents.bestand.value.personalSync), documents.bestand.value)
                    }
                    return@use
                }
                if (mode == "actor-receive") {
                    sent()
                    fun counts() = context.openOrCreateDatabase("magnolie_phone.db", Context.MODE_PRIVATE, null).use { db ->
                        listOf("inbox", "dedupe", "personal_batch", "personal_run", "personal_attachment_transfer", "personal_attachment_chunk", "meta").associateWith { table ->
                            db.rawQuery("SELECT COUNT(*) FROM $table", null).use { row -> assertTrue(row.moveToFirst()); row.getLong(0) }
                        }
                    }
                    val run = "44444444-4444-4444-8444-444444444444"
                    val request = buildJsonObject {
                        put("format", format); put("run_id", run); put("trigger", "manual")
                        put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks"))))
                    }
                    queue.rememberPersonalRun(peerId, request, System.currentTimeMillis() + 60000, actorRun = true)
                    val queued = queue.queue(peerId, "personal_sync.request", request, 60000, actorRunId = run)
                    val beforeRows = counts(); val beforeBook = documents.bestand.value; val beforeState = work.state.value
                    val wire = PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.request", request, 60000), run)
                    val start = TelefonNachrichten.message(PersonalSyncActor.START_KIND, PersonalSyncActor.start(run), 60000, id = run)
                    val malformed = JsonObject(wire + ("body" to buildJsonObject { put("owned_unclaimed", "Must not reach documents") }))
                    val markedAck = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND, PersonalSyncActor.ack(run, queued.string("message_id")), 60000)
                    val cancel = TelefonNachrichten.message(PersonalSyncActor.CANCEL_KIND, PersonalSyncActor.cancel(run), 60000)
                    for (frame in listOf(start, wire, malformed, markedAck, cancel)) work.receiveMessage(peer, frame, channel, 0L)
                    work.receiveMessage(peer, PersonalSyncActor.semanticMessage(wire), channel, 0L)
                    work.receiveMessage(peer, TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.request", request, manifest), 60000), channel, 0L)
                    ack(queued.string("message_id"))
                    assertTrue(sent().isEmpty()); assertEquals(beforeRows, counts())
                    assertEquals(queued, queue.due(peerId, TelefonTransportArt.WIFI).single { it.messageId == queued.string("message_id") }.payload)
                    assertEquals(beforeBook, documents.bestand.value); assertEquals(beforeState, work.state.value)
                    return@use
                }
                if (mode == "actor-wire") {
                    sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    val run = "44444444-4444-4444-8444-444444444444"
                    val request = buildJsonObject {
                        put("format", format); put("run_id", run); put("trigger", "manual")
                        put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks"))))
                    }
                    queue.rememberPersonalRun(peerId, request, System.currentTimeMillis() + 60000, actorRun = true)
                    val wire = queue.queue(peerId, "personal_sync.request", request, 60000, actorRunId = run)
                    pump.invoke(work, peer, channel, 0L, false)
                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) ||
                        (it["body"] as? JsonObject)?.get("run_id") == JsonPrimitive(run) })
                    assertEquals(wire, queue.due(peerId, TelefonTransportArt.WIFI).single { it.messageId == wire.string("message_id") }.payload)
                    assertEquals(0, queue.attempts(wire.string("message_id")))
                    return@use
                }
                if (mode == "preferences") {
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    val latest = work.configureCommonPreferences(peerId, peer.static_public,
                        SharedSyncSettings.effective(shared), "skip_deletions", JsonPrimitive(false))
                    assertEquals(JsonPrimitive(false), work.state.value.sharedPreferencesValues?.get("skip_deletions"))
                    work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, shared, 60000), channel, 0)
                    assertEquals(JsonPrimitive(false), work.state.value.sharedPreferencesValues?.get("skip_deletions"))
                    val desktopChoice = SharedSyncSettings.change(SharedSyncSettings.merge(shared, latest, peerId, actor),
                        peerId, actor, "auto_mode", JsonPrimitive("wifi"))
                    work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, desktopChoice, 60000), channel, 0)
                    pump.invoke(work, peer, channel, 0L, false)
                    assertEquals(SharedSyncSettings.effective(desktopChoice), work.state.value.sharedPreferencesValues)
                    assertEquals(JsonPrimitive(false), work.state.value.sharedPreferencesValues?.get("skip_deletions"))
                    assertEquals(desktopChoice, session.sharedSent)
                    return@use
                }
                if (mode == "unpair") {
                    val other = peer.copy(device_id = UUID.randomUUID().toString(), display_name = "Other computer")
                    storage.savePeer(other); storage.selectPeer(peer.device_id)
                    assertThrows(Exception::class.java) { work.handleSessionClose(other,
                        buildJsonObject { put("type", "close"); put("reason", "unpaired") }, 0) }
                    work.handleSessionClose(peer, buildJsonObject { put("type", "close"); put("reason", "normal") }, 0)
                    assertNotNull(storage.peers().peer)
                    work.handleSessionClose(peer, buildJsonObject { put("type", "close"); put("reason", "unpaired") }, 0)
                    assertNull(storage.peers().peer)
                    assertEquals(other.device_id, storage.peers().all().single().device_id)
                    assertNotNull(documents.notiz("phone-note"))
                    return@use
                }
                if (mode in setOf("delete", "skip-delete")) {
                    val original = documents.personalSyncSnapshot(setOf("notes"), format).single { it.kind == "note" }
                    val run = UUID.randomUUID().toString()
                    val request = buildJsonObject { put("format", format); put("run_id", run); put("trigger", "manual"); put("modules", JsonArray(listOf(JsonPrimitive("notes")))) }
                    work.receiveMessage(peer, TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
                        PhoneContentScope.wrap("personal_sync.request", request, manifest), 60000), channel, 0)
                    queue.markPersonalRun(peerId, run, "reported")
                    val proposal = buildJsonObject {
                        put("proposal_id", UUID.randomUUID().toString()); put("kind", "note"); put("id", "phone-note"); put("parent_id", "")
                        put("clock", JsonArray((original.clock + io.gitlab.maik3531.magnolienotes.daten.PersonalSyncClock(peerId, 1)).sortedBy { it.actor_id }
                            .map { buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } }))
                        put("prior_hash", original.hash); put("deleted_ms", System.currentTimeMillis()); put("label", "Mobile")
                    }
                    val proposals = buildJsonObject { put("format", 1); put("run_id", run); put("proposal_batch_id", UUID.randomUUID().toString())
                        put("sequence", 0); put("last", true); put("proposals", JsonArray(listOf(proposal))) }
                    work.receiveMessage(peer, TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
                        PhoneContentScope.wrap("personal_sync.deletion_proposals", proposals, manifest), 60000), channel, 0)
                    if (mode == "skip-delete") { assertNotNull(documents.notiz("phone-note")); return@use }
                    assertNull(documents.notiz("phone-note"))
                    pump.invoke(work, peer, channel, 0L, false)
                    assertTrue("Deletion completion was discarded with its previous membership", sent().any { it["kind"] == JsonPrimitive("personal_sync.deletion_decision") })
                    return@use
                }
                if (ownership != null) {
                    assertTrue(sent().any { it["message_id"] == ownership["message_id"] && it["kind"] == JsonPrimitive("personal_sync.settings") })
                    ack(ownership.string("message_id"))
                    assertNull(queue.outboxPersonalMessage(peerId, ownership.string("message_id")))
                    return@use
                }
                if (mode == "single") {
                    val selected = documents.personalSyncSnapshot(setOf("notes"), format).first { it.kind == "note" }.copy(id = "organizer-note")
                    repeat(2) {
                        val run = UUID.randomUUID().toString()
                        val request = buildJsonObject {
                            put("format", format); put("run_id", run); put("trigger", "manual")
                            put("modules", JsonArray(listOf(JsonPrimitive("notes"))))
                            put("send_item", buildJsonObject { put("kind", "note"); put("id", selected.id) })
                        }
                        work.receiveMessage(peer, TelefonNachrichten.message("personal_sync.request", request, 60000), channel, 0)
                        val batch = PersonalSyncProtokoll.batch(run, listOf(selected), 0, true, false, format, PersonalSync.recordsHash(listOf(selected)))
                        work.receiveMessage(peer, TelefonNachrichten.message("personal_sync.batch", batch, 60000), channel, 0)
                        assertEquals(selected.value.getValue("text").jsonPrimitive.content, documents.notiz(selected.id)?.text)
                        assertNotNull(documents.notiz("phone-note"))
                        assertTrue(queue.readyPersonalBatches().isEmpty())
                        documents.loescheNotiz(selected.id)
                        assertNull(documents.notiz(selected.id))
                    }
                    return@use
                }
                if (mode in setOf("manual", "actor")) {
                    sent()
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    val chosenRun = "44444444-4444-4444-8444-444444444444"
                    if (mode == "manual") {
                        val awakened = CountDownLatch(1); wake.set(awakened)
                        work.personalSyncNow()
                        assertTrue(awakened.await(2, TimeUnit.SECONDS)); wake.set(null)
                        assertTrue(sent().any { it["type"] == JsonPrimitive("ping") })
                    } else {
                        val enqueue = TelefonWerk::class.java.getDeclaredMethod("enqueuePersonalSync",
                            TelefonPeer::class.java, String::class.java, String::class.java, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
                        assertEquals(true, enqueue.invoke(work, peer, "manual", chosenRun, false))
                    }
                    assertEquals(0, closed.get())
                    pump.invoke(work, peer, channel, 0L, false)
                    assertTrue(scoped(sent()).isEmpty()); assertFalse(queue.hasActiveScopedRun(peerId))
                    ackScope(); pump.invoke(work, peer, channel, 0L, false)
                    val requestMessage = scoped(sent()).single()
                    val wrapped = requestMessage.getValue("body").jsonObject
                    assertEquals("personal_sync.request", wrapped.string("kind"))
                    val runId = wrapped.getValue("body").jsonObject.string("run_id")
                    if (mode == "actor") assertEquals(chosenRun, runId)
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
                val snapshot = documents.personalSyncScopedSnapshot(selection, peerId, format)
                val old = snapshot.records.single { it.kind == "note" }
                val value = JsonObject(old.value + mapOf("text" to JsonPrimitive("Organizer addition"), "modified_ms" to JsonPrimitive(old.modifiedMs + 1)))
                val updated = old.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = old.modifiedMs + 1,
                    clock = (old.clock + PersonalSyncClock(peerId, 1)).sortedWith { a, b -> PersonalSync.compareUtf8(a.actor_id, b.actor_id) })
                val run = UUID.randomUUID().toString()
                val request = buildJsonObject { put("format", format); put("run_id", run); put("trigger", "manual")
                    put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
                val requestMessage = TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.request", request, manifest), 60000)
                work.receiveMessage(peer, requestMessage, channel, 0)
                // duplicateResult reports the ACK for a subsequent replay of a durable acceptance.
                assertEquals("duplicate" to "none", queue.duplicateResult(peerId, requestMessage.string("message_id")))
                val batch = PersonalSyncProtokoll.batch(run, listOf(updated), 0, true, mode != "receive-request", format, PersonalSync.recordsHash(listOf(updated)))
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
                    work.sharedLocalCapabilities = { TelefonCapabilities.phase1().mapValues { (_, capability) ->
                        capability.copy(versions = capability.versions.filter { it < 9 }) } }
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
                if (format == 14) assertEquals("notes", documents.notiz("phone-note")!!.ursprungApp)
                if (mode == "receive-request") {
                    assertTrue("Scoped reply was not completed", queue.personalRunMarked(peerId, run, "responded"))
                    val replies = queue.due(peerId, TelefonTransportArt.WIFI).map { it.payload }
                        .filter { it["kind"] == JsonPrimitive("personal_sync.batch") }
                        .map { it.getValue("body").jsonObject }.filter { it["run_id"] == JsonPrimitive(run) }
                    assertTrue("No matching reply batch was queued", replies.isNotEmpty())
                    assertTrue(replies.all { it["format"] == JsonPrimitive(format) && it["reply"] == JsonPrimitive(true) })
                    val replyRecords = replies.flatMap(PersonalSyncProtokoll::decodeBatch)
                    assertEquals("notes", replyRecords.single { it.kind == "note" }.value.string("origin_app"))
                    return@use
                }
                assertEquals(1, documents.notizen().size)
                val foreign = updated.copy(id = "organizer-only")
                val foreignBatch = PersonalSyncProtokoll.batch(run, listOf(foreign), 0, true, true, format, PersonalSync.recordsHash(listOf(foreign)))
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
