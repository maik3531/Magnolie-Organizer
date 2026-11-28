package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncClock
import io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord
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
    @Test fun authenticatedHistoricalTargetsStayInPrivateOriginWithoutDataSaveOrSuccessAck() = exercise("actor-deletions-origin")
    @Test fun rawActorJournalCannotSupplyAuthenticatedHistoricalOrigin() = exercise("actor-deletions-origin-raw")
    @Test fun conflictingHistoricalFrameRetiresItsPrivateOrigin() = exercise("actor-deletions-origin-conflict")
    @Test fun historicalOriginCannotSurviveNativeGrantRevocation() = exercise("actor-deletions-origin-grants")
    @Test fun nativeHistoricalRestoreClosesDataBeforeOneSaveAndKeepsScopeFrozenUntilTheExactDecisionReceipt() = exercise("actor-deletions-origin-pending-save")
    @Test fun nativeHistoricalTaskRestoreKeepsOriginalDataScopeUntilItsExactReceipt() = exercise("actor-deletions-origin-pending-save-task")
    @Test fun nativeHistoricalRestoreAcross256MembersKeepsTheOriginalAcceptedScopePartsUntilCompletion() = exercise("actor-deletions-origin-pending-save-boundary")
    @Test fun nativeHistoricalWriterFailureDoesNotRestoreOrSendAndCannotReplayTheClosedOwner() = exercise("actor-deletions-origin-pending-save-writer-failure")
    @Test fun nativeHistoricalSaveRejectsAChangedBookReviewWithoutOverwritingTheUserChange() = exercise("actor-deletions-origin-pending-save-before-book")
    @Test fun nativeHistoricalSaveRejectsAChangedOriginalFrame() = exercise("actor-deletions-origin-pending-save-before-frame")
    @Test fun nativeHistoricalSaveRejectsAChangedChoiceClock() = exercise("actor-deletions-origin-pending-save-before-clock")
    @Test fun nativeHistoricalSaveCannotSkipAnOrdinaryUnresolvedIntentGroup() = exercise("actor-deletions-origin-pending-save-before-intents")
    @Test fun nativeHistoricalSaveCannotAdoptAReplacementBookInstance() = exercise("actor-deletions-origin-pending-save-before-instance")
    @Test fun nativeHistoricalSavedReceiptCannotSurviveAnIndependentBookWrite() = exercise("actor-deletions-origin-pending-save-after-book")
    @Test fun nativeHistoricalSavedReceiptCannotSurviveGrantRevocation() = exercise("actor-deletions-origin-pending-save-after-grants")
    @Test fun nativeHistoricalSavedReceiptCannotSurviveAReplacementBookInstance() = exercise("actor-deletions-origin-pending-save-after-instance")
    @Test fun actualPendingNoteOriginAndExplicitRestoreDraftPreserveTheEncryptedBookAndClosedDataScope() = exercise("actor-producer-origin-pending")
    @Test fun nativeActorCompleteReportCheckpointsAndPersistsPrivateReplyExactlyOnce() = exercise("actor-commit")
    @Test fun nativeActorCompleteReportRejectsConcurrentPhoneBookChange() = exercise("actor-commit-changed")
    @Test fun nativeActorCompleteReportNeverRecordsFailedNetworkAckAsReceipt() = exercise("actor-commit-ack-failure")
    @Test fun nativeActorCompleteReportReceiptCannotSurviveChangedBookOrRevokedGrants() = exercise("actor-commit-receipt-revoked")
    @Test fun nativeActorTerminalDeleteUsesOneSaveAndFreshScopeBeforeDecisionAck() = exercise("actor-commit-terminal-delete")
    @Test fun nativeActorTerminalRestoreKeepsMembershipAndUsesExactDecisionAck() = exercise("actor-commit-terminal-restore")
    @Test fun nativeActorTerminalLedgerFailureRetriesWithoutRepeatingBookSave() = exercise("actor-commit-terminal-ledger")
    @Test fun nativeActorTerminalWriterFailureNeverConsumesIntentsOrSendsDecision() = exercise("actor-commit-terminal-write-failure")
    @Test fun nativeActorTerminalAutoPolicyRunsThroughActualTransportPump() = exercise("actor-commit-terminal-auto")
    @Test fun nativeActorTerminalAutoWaitsForSuccessfulDataAckWrite() = exercise("actor-commit-terminal-auto-ack-failure")
    @Test fun nativeActorProducesCompleteScopedDeletionBatchesFromTheActualBook() = exercise("actor-producer")
    @Test fun nativeActorProducerRequiresDeletionGrants() = exercise("actor-producer-no-grants")
    @Test fun nativeActorProducerHonorsAgreedSkipDeletions() = exercise("actor-producer-skip")
    @Test fun nativeActorProducerRollsBackOutboxAndTargetProofTogether() = exercise("actor-producer-sql-failure")
    @Test fun nativeIncomingDecisionDeleteUsesActualOutgoingProofAndOneSave() = exercise("actor-producer-incoming-delete")
    @Test fun nativeIncomingDecisionRestoreRetainsDraftAndActuallySendsTheAck() = exercise("actor-producer-incoming-restore")
    @Test fun nativeIncomingDecisionFailedAckFlushNeverCountsAsSuccess() = exercise("actor-producer-incoming-send-failure")
    @Test fun nativeIncomingDecisionLedgerRetryDoesNotRepeatTheBookWrite() = exercise("actor-producer-incoming-ledger-failure")
    @Test fun nativeIncomingDecisionWriterFailureNeverSendsSuccess() = exercise("actor-producer-incoming-writer-failure")
    @Test fun nativeIncomingDecisionSentAckMetadataFailureStillNeedsPersistence() = exercise("actor-producer-incoming-metadata-failure")
    @Test fun nativeIncomingDecisionDeniedAfterGrantRevocation() = exercise("actor-producer-incoming-deny-grants")
    @Test fun nativeIncomingDecisionDeniedAfterAnotherBookWrite() = exercise("actor-producer-incoming-deny-book")
    @Test fun nativeIncomingDecisionDeniedAfterPeerKeyReplacement() = exercise("actor-producer-incoming-deny-key")
    @Test fun nativeIncomingDecisionDeniedOnOldChannel() = exercise("actor-producer-incoming-deny-channel")
    @Test fun nativeIncomingDecisionDeniedAfterBookInstanceReplacement() = exercise("actor-producer-incoming-deny-instance")
    @Test fun nativeIncomingDecisionDeniedAfterRestore() = exercise("actor-producer-incoming-deny-restore")
    @Test fun nativeIncomingDecisionDeniedAfterCancellation() = exercise("actor-producer-incoming-deny-cancel")
    @Test fun nativeIncomingDecisionMixedDeleteRequiresBothReceiptDirectionsAndOneDataCommit() = exercise("actor-producer-incoming-mixed-delete")
    @Test fun nativeIncomingDecisionMixedRestoreKeepsBothTargetsAndDraft() = exercise("actor-producer-incoming-mixed-restore")
    @Test fun nativeIncomingDecisionMixedRejectedWithMissingReview() = exercise("actor-producer-incoming-mixed-reject-review-missing")
    @Test fun nativeIncomingDecisionMixedRejectedWithExtraReview() = exercise("actor-producer-incoming-mixed-reject-review-extra")
    @Test fun nativeIncomingDecisionMixedRejectedWithPartialDecisions() = exercise("actor-producer-incoming-mixed-reject-partial")
    @Test fun nativeIncomingDecisionMixedRejectedWithOverlappingTargets() = exercise("actor-producer-incoming-mixed-reject-overlap")
    @Test fun nativeIncomingDecisionMixedLedgerRetryRetainsAtomicGroupAndOneDataCommit() = exercise("actor-producer-incoming-mixed-restore-ledger-failure")
    @Test fun nativeIncomingDecisionMixedSendRetryNeedsActualNativeAckFlush() = exercise("actor-producer-incoming-mixed-restore-send-failure")
    @Test fun nativeIncomingDecisionMixedMetadataRetryNeedsProtectedAckPersistence() = exercise("actor-producer-incoming-mixed-restore-metadata-failure")
    @Test fun nativeIncomingDecisionMixedDeniedAfterGrantRevocation() = exercise("actor-producer-incoming-mixed-restore-deny-grants")
    @Test fun nativeIncomingDecisionMixedDeniedAfterAnotherBookWrite() = exercise("actor-producer-incoming-mixed-restore-deny-book")
    @Test fun nativeIncomingDecisionMixedDeniedAfterPeerKeyReplacement() = exercise("actor-producer-incoming-mixed-restore-deny-key")
    @Test fun nativeIncomingDecisionMixedDeniedOnOldChannel() = exercise("actor-producer-incoming-mixed-restore-deny-channel")
    @Test fun nativeIncomingDecisionMixedDeniedAfterBookInstanceReplacement() = exercise("actor-producer-incoming-mixed-restore-deny-instance")
    @Test fun nativeIncomingDecisionMixedDeniedAfterRestore() = exercise("actor-producer-incoming-mixed-restore-deny-restore")
    @Test fun nativeIncomingDecisionMixedDeniedAfterCancellation() = exercise("actor-producer-incoming-mixed-restore-deny-cancel")
    @Test fun nativeIncomingDecisionMixedDeniedAfterNativeOwnerEpochReplacement() = exercise("actor-producer-incoming-mixed-restore-deny-epoch")
    @Test fun nativeActorTerminalCannotFinishAfterGrantRevocation() = exercise("actor-commit-terminal-deny-grants")
    @Test fun nativeActorTerminalCannotFinishAfterAnotherBookWrite() = exercise("actor-commit-terminal-deny-book")
    @Test fun nativeActorTerminalCannotFinishWithAReplacedPeerKey() = exercise("actor-commit-terminal-deny-key")
    @Test fun nativeActorTerminalCannotFinishOnTheOldChannel() = exercise("actor-commit-terminal-deny-channel")
    @Test fun channelLossStopsOrdinaryActorCompletionAndRetainsEvidenceAcrossSqlRetry() = exercise("actor-commit-terminal-retire-channel")
    @Test fun nativeActorTerminalCannotFinishAfterRestore() = exercise("actor-commit-terminal-deny-restore")
    @Test fun nativeActorTerminalCannotFinishAfterCancellation() = exercise("actor-commit-terminal-deny-cancel")
    @Test fun nativeActorTerminalCannotFinishWithAnOldBookInstance() = exercise("actor-commit-terminal-deny-instance")
    @Test fun independentTimeChangeDefersScopedDataWithoutAdmittingRawFallback() = exercise("time")
    @Test fun selectedOrganizerNoteCanBeSentAgainAfterDeletingItsPhoneCopy() = exercise("single")
    @Test fun ownershipControlAndItsAckDoNotRequireContentRunId() = exercise("ownership")
    @Test fun organizerDeletionRemovesPhoneCopyAndKeepsItsAcknowledgmentAcrossMembershipChange() = exercise("delete")
    @Test fun skippingDeletionsKeepsThePhoneCopy() = exercise("skip-delete")
    @Test fun sharedChoicesFromEitherDeviceConvergeWithoutOldEchoUndoingTheLatestChoice() = exercise("preferences")
    @Test fun authenticatedUnpairClearsOnlyTheCurrentComputerAndKeepsPhoneContent() = exercise("unpair")

    @Test fun provenanceFormatUsesScopedTransportAndRetainsOriginalAppOnReceive() = exercise("receive", 14)
    @Test fun provenanceFormatProducesACompleteMatchingScopedReply() = exercise("receive-request", 14)
    @Test fun scopedWifiRequestOnBluetoothLeavesNoRunOrScope() = exercise("receive-auto-wifi-bluetooth", 14)
    @Test fun scopedConnectionRequestOnCurrentBluetoothNeedsItsOwnRunPolicy() = exercise("receive-auto-connection", 14)
    @Test fun scopedConnectionRequestWaitsForTheActuallyAdvertisedRevision() =
        exercise("receive-auto-connection-advertisement", 14)
    @Test fun scopedConnectionRequestFromTheNonElectedPeerDoesNotCreateARun() =
        exercise("receive-auto-connection-higher-uuid", 14)
    @Test fun scopedConnectionReaderRejectsASecondAutomaticRun() = exercise("receive-auto-connection-second-run", 14)
    @Test fun scopedConnectionReaderRejectsARepackagedRequest() = exercise("receive-auto-connection-repackaged", 14)
    @Test fun scopedConnectionInitiatorWaitsForTheOriginalRequestAckBeforeItsBatch() =
        exercise("start-auto-connection", 3)
    @Test fun scopedConnectionInitiatorSavesTheReplyOriginalBeforeSendingItsResult() =
        exercise("start-auto-connection-attachment", 3)
    @Test fun scopedConnectionRejectsLowerFormatMissingFromPeerAnnouncement() =
        exercise("receive-auto-connection-remote-format", 3)
    @Test fun scopedConnectionRejectsLowerFormatMissingFromLocalCapabilities() =
        exercise("receive-auto-connection-local-format", 3)
    @Test fun scopedConnectionRequestRollsBackRunAndScopeWhenItsReceiptFails() = exercise("receive-auto-connection-atomic", 14)
    @Test fun scopedConnectionBatchSavesOnlyOnTheOriginalReader() = exercise("receive-auto-connection-batch", 14)
    @Test fun scopedConnectionBatchOnReplacementReaderLeavesBookAndStagingUntouched() = exercise("receive-auto-connection-batch-replaced", 14)
    @Test fun scopedConnectionBatchLosingReaderBeforeReplacementPreservesTheBook() = exercise("receive-auto-connection-batch-write-reader", 14)
    @Test fun scopedConnectionBatchRetriesItsFailedNativeSaveOnTheSameReader() = exercise("receive-auto-connection-batch-write-retry", 14)
    @Test fun scopedConnectionReplyUsesOnlyTheOriginalAcknowledgedReaderAfterSave() = exercise("receive-auto-connection-reply", 14)
    @Test fun scopedConnectionReplyRetriesAfterOutboxFailureWithoutSavingTwice() = exercise("receive-auto-connection-outbox-reply", 14)
    @Test fun scopedConnectionReportWaitsForReplyAndItsOwnSentAcknowledgment() = exercise("receive-auto-connection-report-reply", 14)
    @Test fun scopedConnectionReportRemainsHeldAfterTerminalReplyRejection() = exercise("receive-auto-connection-terminal-report-reply", 14)
    @Test fun scopedConnectionReportWaitsForEveryExactReplyAndRollsBackItsFailedAck() =
        exercise("receive-auto-connection-multi-report-reply", 14)
    @Test fun scopedConnectionAttachmentDescriptorRequestsBytesWithoutApplyingTheBook() =
        exercise("receive-auto-connection-attachment-request", 14)
    @Test fun scopedConnectionAttachmentStagesOnlyCurrentWindowAndExactOriginalBytes() =
        exercise("receive-auto-connection-attachment-window", 14)
    @Test fun scopedConnectionAttachmentResultNeedsActualBookSaveEvenAfterRetry() =
        exercise("receive-auto-connection-attachment-save", 14)
    @Test fun scopedConnectionReplyAdvertisesSavedAttachmentButHoldsItsReport() =
        exercise("receive-auto-connection-attachment-reply", 14)
    @Test fun scopedConnectionReplySendsOnlyAcknowledgedWindowsOnItsOriginalReader() =
        exercise("receive-auto-connection-attachment-send", 14)
    @Test fun scopedConnectionAttachmentCompletionNeedsEverySentAckAndCommitsWithItsReceipt() =
        exercise("receive-auto-connection-attachment-complete", 14)
    @Test fun provenanceFormatSurvivesManualScopeAndReceiptGates() = exercise("manual", 14)
    @Test fun provenanceFormatUsesTheNativeActorCommitAndCompletionReport() = exercise("actor-commit", 14)
    @Test fun provenanceFormatCanAdmitOneSelectedOrganizerNote() = exercise("single", 14)
    @Test fun aNoteSwipeQueuesOnlyItsSelectedEntryAndWaitsForRequestReceipt() = exercise("send-note", 14)
    @Test fun aTaskSwipeQueuesOnlyItsSelectedEntryAndWaitsForRequestReceipt() = exercise("send-task", 14)
    @Test fun offlineSingleSendDoesNotQueueOrStartAFullRun() = exercise("send-offline", 14)
    @Test fun revokedSingleSendDoesNotQueueOrStartAFullRun() = exercise("send-revoked", 14)
    @Test fun linkedNotesUsePersonalRouteWhileForeignNotesAndDelegatedTasksDoNot() = exercise("send-route", 14)

    @Test fun authenticatedWifiWithLateSettingsReplacesOnlyTheStaleAutomaticRun() = exercise("auto-late-stale")
    @Test fun automaticWifiWaitsForLateSettingsWithoutExpiringTheTransition() = exercise("auto-late-delayed")
    @Test fun automaticWifiImportWaitsForLateSharedSettings() = exercise("auto-late-import")
    @Test fun automaticWifiFullCollectionWaitsForLateSharedSettings() = exercise("auto-late-full")
    @Test fun customWifiRequestStartsAfterLateModuleSettingsWithoutContentGrants() = exercise("custom-wlan-late")
    @Test fun customWifiRequestUsesSettingsReceivedDuringReaderSetup() = exercise("custom-wlan-setup")
    @Test fun customWifiRequestDoesNotStartAfterModuleRevocation() = exercise("custom-wlan-revoked")
    @Test fun customWifiRequestDoesNotStartOnBluetooth() = exercise("custom-wlan-bluetooth")
    @Test fun unchangedWifiReconnectDoesNotQueueAnotherRun() = exercise("auto-late-unchanged")
    @Test fun resumedValidAutomaticRunDoesNotCreateADuplicateAfterCompletion() = exercise("auto-late-active")
    @Test fun automaticWifiOffThenOnDoesNotReviveAnOldPendingTransition() = exercise("auto-late-off")
    @Test fun revokedThenRestoredGrantsDoNotReviveAnOldPendingTransition() = exercise("auto-late-grants")
    @Test fun bluetoothAuthenticationDoesNotAuthorizeALaterAutomaticWifiRun() = exercise("auto-late-bluetooth")
    @Test fun aReplacedAuthenticatedChannelCannotStartItsPendingAutomaticRun() = exercise("auto-late-channel")
    @Test fun aReplacedOriginalPipeCannotStartItsPendingAutomaticRun() = exercise("auto-late-pipe")

    private fun checkLateWholeCollectionWifi(work: TelefonWerk, peer: TelefonPeer, channel: TelefonSecureChannel,
        agreed: JsonObject, documents: Ablage, queue: TelefonQueue, pump: () -> Unit,
        sent: () -> List<JsonObject>, acknowledge: (String) -> Unit) {
        val peerId = peer.device_id
        assertFalse("An unconfirmed import/full choice staged a durable automatic run", queue.hasActiveAutoRun(peerId))
        pump()
        assertTrue(sent().none { it["kind"] == JsonPrimitive("personal_sync.request") })
        work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, agreed, 60000), channel, 0)
        repeat(2) { pump() }
        val outgoing = sent()
        val request = outgoing.single { it["kind"] == JsonPrimitive("personal_sync.request") }
        val body = request.getValue("body").jsonObject
        val runId = body.string("run_id")
        assertEquals("auto_wifi", body.string("trigger"))
        assertEquals("wifi_only", queue.personalRunPolicy(peerId, runId))
        val records = outgoing.filter { it["kind"] == JsonPrimitive("personal_sync.batch") }
            .flatMap { PersonalSyncProtokoll.decodeBatch(it.getValue("body").jsonObject) }
        assertTrue(records.any { it.kind == "note" && it.id ==
            PersonalSync.noteWireId(documents.bestand.value.personalSync, "new-offline-note") })
        outgoing.filter { it["type"] == JsonPrimitive("message") }.forEach { acknowledge(it.string("message_id")) }
        queue.markPersonalRun(peerId, runId, "reported")
        repeat(3) { pump() }
        assertFalse(queue.hasActiveAutoRun(peerId))
        assertTrue(sent().none { it["kind"] == JsonPrimitive("personal_sync.request") })
    }

    private fun checkLateCustomWifi(mode: String, work: TelefonWerk, peer: TelefonPeer, channel: TelefonSecureChannel,
        queue: TelefonQueue, pump: () -> Unit, sent: () -> List<JsonObject>, acknowledge: (String) -> Unit) {
        fun receive(kind: String, body: JsonObject) =
            work.receiveMessage(peer, TelefonNachrichten.message(kind, body, 60000), channel, 0)
        fun List<JsonObject>.customRequests() = filter { it["kind"] == JsonPrimitive("personal_sync.custom_request") }
        val before = sent()
        receive(PersonalDesktopFeatures.KIND, buildJsonObject {
            put("format", 6); put("revision", 1); put("custom_tab", true); put("tree", false)
        })
        pump()
        val setup = before + sent()
        assertTrue(setup.customRequests().isEmpty())
        val advertised = setup.last { it["kind"] == JsonPrimitive("personal_sync.custom_settings") &&
            it["body"]?.jsonObject?.get("enabled") == JsonPrimitive(true) }
        val local = advertised.getValue("body").jsonObject
        val remote = buildJsonObject {
            put("format", 4); put("scope", "custom"); put("enabled", true)
            put("revision", 1); put("epoch", UUID.randomUUID().toString())
        }
        val activeReader = field(TelefonWerk::class.java, "activeChannel")
        if (mode == "custom-wlan-setup") activeReader.set(work, null)
        receive("personal_sync.custom_settings", remote)
        if (mode == "custom-wlan-setup") activeReader.set(work, channel)
        pump()
        assertTrue("The local Custom setting has not been acknowledged", sent().customRequests().isEmpty())
        if (mode == "custom-wlan-revoked") receive("personal_sync.custom_settings", JsonObject(remote + mapOf(
            "enabled" to JsonPrimitive(false), "revision" to JsonPrimitive(2), "epoch" to JsonPrimitive(UUID.randomUUID().toString()))))
        acknowledge(advertised.string("message_id"))
        repeat(2) { pump() }
        val requests = sent().customRequests()
        if (mode in setOf("custom-wlan-bluetooth", "custom-wlan-revoked")) {
            assertTrue(requests.isEmpty())
            assertFalse(queue.hasKind(peer.device_id, "personal_sync.custom_request"))
            return
        }
        assertEquals("A late, authenticated Custom setting must start one WLAN request", 1, requests.size)
        val request = requests.single()
        val body = request.getValue("body").jsonObject
        assertEquals("auto_wifi", body.string("trigger"))
        assertEquals("wifi_only", queue.outboxPolicy(peer.device_id, request.string("message_id")))
        assertEquals(local["epoch"], body["sender_epoch"])
        assertEquals(remote["epoch"], body["receiver_epoch"])
        assertFalse(queue.hasActiveAutoRun(peer.device_id))
        acknowledge(request.string("message_id"))
        receive("personal_sync.custom_settings", remote)
        repeat(3) { pump() }
        assertTrue(sent().customRequests().isEmpty())
        assertFalse(queue.hasKind(peer.device_id, "personal_sync.custom_request"))
    }

    private fun checkCompetingConnectionRequest(
        request: JsonObject, manifest: JsonObject, peerId: String, queue: TelefonQueue,
        repackage: Boolean, receive: (JsonObject) -> JsonObject
    ) {
        val run = request.string("run_id")
        val competingRun = if (repackage) run else UUID.randomUUID().toString()
        val competing = JsonObject(request + ("run_id" to JsonPrimitive(competingRun)))
        val packet = TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
            PhoneContentScope.wrap("personal_sync.request", competing, manifest), 60_000)
        val rejected = receive(packet)
        assertEquals("rejected", rejected.string("status"))
        assertEquals("not_granted", rejected.string("error"))
        assertNull(queue.duplicateResult(peerId, packet.string("message_id")))
        if (!repackage) {
            assertNull(queue.personalRun(peerId, competingRun))
            assertFalse(queue.containsScopedRun(peerId, competingRun))
        }
        assertEquals(request, queue.personalRun(peerId, run))
    }

    private fun checkConnectionRequestRollback(
        queue: TelefonQueue, peerId: String, run: String, messageId: String, receive: () -> JsonObject
    ) {
        val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
        database.execSQL("CREATE TRIGGER connection_request_receipt_failure BEFORE INSERT ON inbox " +
            "WHEN NEW.message_id='$messageId' AND NEW.state='accepted' " +
            "BEGIN SELECT RAISE(ABORT,'synthetic connection request receipt failure'); END")
        try {
            val failed = receive()
            assertEquals("rejected", failed.string("status"))
            assertNull("Rejected request left a persisted run", queue.personalRun(peerId, run))
            assertFalse(queue.containsScopedRun(peerId, run))
            assertNull(queue.duplicateResult(peerId, messageId))
            assertEquals("temporary_failure", failed.string("error"))
        } finally { database.execSQL("DROP TRIGGER connection_request_receipt_failure") }
    }

    private fun checkConnectionInitiator(work: TelefonWerk, peer: TelefonPeer, queue: TelefonQueue, manifest: JsonObject,
                                        sendDue: () -> List<JsonObject>, ackScope: () -> Unit,
                                        ack: (String, String, String) -> Unit, receive: (JsonObject) -> JsonObject,
                                        failBookWrites: AtomicBoolean, failNextFlush: AtomicBoolean, replyOriginal: Boolean) {
        val enqueue = TelefonWerk::class.java.getDeclaredMethod("enqueuePersonalSync", TelefonPeer::class.java,
            String::class.java, String::class.java, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
        assertEquals(true, enqueue.invoke(work, peer, PersonalAutoSync.CONNECTION, null, false))
        assertTrue("Request preceded the collection ACK", sendDue().isEmpty())
        ackScope()
        val requestFrame = sendDue().single()
        val (kind, request) = PhoneContentScope.unwrap(requestFrame.getValue("body").jsonObject, manifest)
        assertEquals("personal_sync.request", kind)
        assertEquals(PersonalAutoSync.CONNECTION, request.string("trigger"))
        val run = request.string("run_id")
        val requestId = requestFrame.string("message_id")
        assertEquals("connection_only", queue.personalRunPolicy(peer.device_id, run))
        assertFalse(queue.scopedRequestAccepted(peer.device_id, run))
        rejectPrematureConnectionReport(work, peer, queue, manifest, request)
        assertTrue("Batch preceded the Request ACK", sendDue().isEmpty())
        ack(requestId, "rejected", "temporary_failure")
        replacementConnectionAck(work, peer, requestId)
        assertFalse("A failure or a replacement reader released the batch", queue.scopedRequestAccepted(peer.device_id, run))
        assertTrue(sendDue().isEmpty())
        for (transport in TelefonTransportArt.entries) assertTrue(queue.due(peer.device_id, transport)
            .none { it.payload.string("kind") in setOf("personal_sync.request", "personal_sync.batch") })
        ack(requestId, "accepted", "none")
        val batchFrame = sendDue().single()
        val (batchKind, batch) = PhoneContentScope.unwrap(batchFrame.getValue("body").jsonObject, manifest)
        assertEquals("personal_sync.batch", batchKind)
        assertEquals(run, batch.string("run_id"))
        val note = PersonalSyncProtokoll.decodeBatch(batch).single { it.kind == "note" && it.id == "phone-note" }
        val task = PersonalSyncProtokoll.decodeBatch(batch).single { it.kind == "task" && it.id == "phone-task" }
        val reply = outboundConnectionTestReply(peer.device_id, manifest, batch, task)
        assertEquals("rejected", receive(reply).string("status"))
        assertNull(queue.duplicateResult(peer.device_id, reply.string("message_id")))
        val attachment = note.value.getValue("attachments").jsonArray.single().jsonObject
        checkConnectionInitialOriginal(queue, peer.device_id, manifest, batchFrame, batch, attachment, sendDue, ack, receive)
        if (replyOriginal) {
            val target = PersonalSyncProtokoll.decodeBatch(batch).single { it.kind == "note" && it.id == "return-note" }
            checkConnectionReplyOriginal(peer.device_id, queue, manifest, batch, target, sendDue, receive, ack, failBookWrites, failNextFlush)
        } else checkConnectionReplySave(queue, peer.device_id, run, reply, receive, failBookWrites)
    }

    private fun outboundConnectionTestReply(peerId: String, manifest: JsonObject, batch: JsonObject, task: PersonalSyncRecord): JsonObject {
        val value = JsonObject(task.value + mapOf("title" to JsonPrimitive("Organizer task update"),
            "modified_ms" to JsonPrimitive(task.modifiedMs + 1)))
        val clock = PersonalSync.merge(task.clock, listOf(PersonalSyncClock(peerId, 1)))
        val changed = task.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = task.modifiedMs + 1, clock = clock)
        val body = PersonalSyncProtokoll.batch(batch.string("run_id"), listOf(changed), 0, true, true,
            batch.long("format").toInt(), PersonalSync.recordsHash(listOf(changed)))
        return TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.batch", body, manifest), 60_000)
    }

    private fun checkConnectionReplySave(queue: TelefonQueue, peerId: String, run: String, reply: JsonObject,
                                         receive: (JsonObject) -> JsonObject, failBookWrites: AtomicBoolean) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val path = java.io.File(context.filesDir, "notizen.json")
        val before = path.readBytes()
        val documents = Ablage.hole(context)
        failBookWrites.set(true)
        try {
            assertEquals("temporary_failure", receive(reply).string("error"))
        } finally {
            failBookWrites.set(false)
        }
        assertArrayEquals(before, path.readBytes())
        assertEquals("Mobile task", documents.bestand.value.aufgaben.single { it.id == "phone-task" }.titel)
        assertFalse(queue.personalDirectionApplied(peerId, run, true))
        assertEquals("duplicate", receive(reply).string("status"))
        assertTrue(queue.personalDirectionApplied(peerId, run, true))
        assertFalse(queue.personalRunMarked(peerId, run, "reported"))
        val after = path.readBytes()
        assertFalse(before.contentEquals(after))
        assertEquals("duplicate", receive(reply).string("status"))
        assertArrayEquals(after, path.readBytes())
        val reopened = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        assertEquals("Organizer task update", reopened.bestand.value.aufgaben.single { it.id == "phone-task" }.titel)
        assertEquals(documents.notiz("phone-note")?.anhaenge, reopened.notiz("phone-note")?.anhaenge)
    }

    private fun checkConnectionReplyOriginal(peerId: String, queue: TelefonQueue, manifest: JsonObject, batch: JsonObject,
                                              note: PersonalSyncRecord, sendDue: () -> List<JsonObject>,
                                              receive: (JsonObject) -> JsonObject, ack: (String, String, String) -> Unit,
                                              failBookWrites: AtomicBoolean, failNextFlush: AtomicBoolean) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val file = java.io.File(context.filesDir, "notizen.json")
        val before = file.readBytes()
        val run = batch.string("run_id")
        val bytes = initialConnectionOriginal().apply { this[lastIndex] = 66 }
        val dataUrl = "data:image/png;base64," + java.util.Base64.getEncoder().encodeToString(bytes)
        val descriptor = requireNotNull(PersonalSync.attachmentDescriptor(Anhang("desktop-original", "Desktop.png", "image", dataUrl))).descriptor
        val digest = descriptor.string("sha256")
        val value = JsonObject(note.value + mapOf("text" to JsonPrimitive("Organizer original"),
            "attachments" to JsonArray(listOf(descriptor)), "modified_ms" to JsonPrimitive(note.modifiedMs + 1)))
        val clock = PersonalSync.merge(note.clock, listOf(PersonalSyncClock(peerId, 1)))
        val updated = note.copy(value = value, clock = clock, modifiedMs = note.modifiedMs + 1, hash = PersonalSync.hash(value))
        val aggregate = PersonalSync.recordsHash(listOf(updated))
        fun wire(kind: String, body: JsonObject) =
            TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap(kind, body, manifest), 60_000)
        val reply = wire("personal_sync.batch", PersonalSyncProtokoll.batch(run, listOf(updated), 0, true, true,
            batch.long("format").toInt(), aggregate))
        fun chunk(index: Int, reply: Boolean = true) = wire("personal_sync.attachment_chunk", buildJsonObject {
            put("format", 2); put("run_id", run); put("reply", reply); put("records_hash", aggregate)
            put("sha256", digest); put("index", index)
            val start = index * PersonalSyncProtokoll.CHUNK_RAW
            put("data", java.util.Base64.getEncoder().encodeToString(bytes.copyOfRange(start, minOf(start + PersonalSyncProtokoll.CHUNK_RAW, bytes.size))))
        })
        fun wanted(start: Int, end: Int) {
            val (kind, body) = PhoneContentScope.unwrap(sendDue().single().getValue("body").jsonObject, manifest)
            assertEquals("personal_sync.attachment_request", kind)
            assertEquals(JsonPrimitive(true), body["reply"])
            val want = body.getValue("wants").jsonArray.single().jsonObject
            assertEquals(digest, want.string("sha256"))
            assertEquals(JsonArray(listOf(JsonPrimitive(start), JsonPrimitive(end))), want.getValue("ranges").jsonArray.single())
        }
        assertEquals("accepted", receive(reply).string("status"))
        assertEquals("rejected", receive(chunk(0)).string("status")) // Window not yet sent.
        wanted(0, 8)
        assertEquals("rejected", receive(chunk(0, reply = false)).string("status"))
        assertEquals("rejected", receive(chunk(8)).string("status"))
        repeat(8) { index -> assertEquals("accepted", receive(chunk(index)).string("status")) }
        wanted(8, 9)
        val last = chunk(8)
        failBookWrites.set(true)
        try {
            assertEquals("temporary_failure", receive(last).string("error"))
        } finally {
            failBookWrites.set(false)
        }
        assertArrayEquals(before, file.readBytes())
        assertFalse(queue.personalDirectionApplied(peerId, run, true))
        assertTrue(sendDue().isEmpty())
        assertEquals("duplicate", receive(last).string("status"))
        assertTrue(queue.personalDirectionApplied(peerId, run, true))
        val resultFrame = sendDue().single()
        val (kind, result) = PhoneContentScope.unwrap(resultFrame.getValue("body").jsonObject, manifest)
        assertEquals("personal_sync.attachment_result", kind)
        assertEquals(JsonPrimitive(true), result["reply"])
        assertEquals(digest, result.string("sha256"))
        assertEquals("complete", result.string("state"))
        val reopened = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
        assertEquals(dataUrl, reopened.notiz("return-note")?.anhaenge?.single()?.daten)
        assertEquals("Organizer original", reopened.notiz("return-note")?.text)
        assertFalse(queue.personalRunMarked(peerId, run, "reported"))
        val report = connectionTestReport(manifest, batch)
        assertEquals("rejected", receive(report).string("status"))
        assertNull(queue.duplicateResult(peerId, report.string("message_id")))
        ack(resultFrame.string("message_id"), "accepted", "none")
        assertEquals("rejected", receive(connectionTestReport(manifest, batch, transport = "wifi")).string("status"))
        failNextFlush.set(true)
        assertTrue(runCatching { receive(report) }.exceptionOrNull() is java.io.IOException)
        assertFalse("Failed transport write marked the report complete", queue.personalRunMarked(peerId, run, "reported"))
        assertTrue(sendDue().isEmpty()) // Drain the ciphertext from the simulated failed write.
        val savedBook = file.readBytes()
        assertEquals("duplicate", receive(report).string("status"))
        assertTrue(queue.personalRunMarked(peerId, run, "reported"))
        assertEquals("duplicate", receive(report).string("status"))
        assertEquals("rejected", receive(connectionTestReport(manifest, batch)).string("status"))
        assertArrayEquals(savedBook, file.readBytes())
    }

    private fun initialConnectionOriginal(): ByteArray = ByteArray(8 * PersonalSyncProtokoll.CHUNK_RAW + 32) { 65 }.apply {
        byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a).copyInto(this)
    }

    private fun checkConnectionInitialOriginal(queue: TelefonQueue, peerId: String, manifest: JsonObject, frame: JsonObject,
                                               batch: JsonObject, attachment: JsonObject, sendDue: () -> List<JsonObject>,
                                               ack: (String, String, String) -> Unit, receive: (JsonObject) -> JsonObject) {
        val run = batch.string("run_id")
        val aggregate = batch.string("records_hash")
        val digest = attachment.string("sha256")
        fun envelope(kind: String, extra: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) =
            TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap(kind, buildJsonObject {
                put("format", 2); put("run_id", run); put("reply", false); put("records_hash", aggregate)
                extra()
            }, manifest), 60_000)
        fun want(start: Int, end: Int) = envelope("personal_sync.attachment_request") {
            put("wants", JsonArray(listOf(buildJsonObject {
                put("sha256", digest)
                put("ranges", JsonArray(listOf(JsonArray(listOf(JsonPrimitive(start), JsonPrimitive(end))))))
            })))
        }
        val result = envelope("personal_sync.attachment_result") {
            put("sha256", digest); put("state", "complete"); put("error", "none")
        }
        val first = want(0, 8)
        assertEquals("rejected", receive(first).string("status"))
        assertNull(queue.duplicateResult(peerId, first.string("message_id")))
        assertTrue(sendDue().isEmpty())
        ack(frame.string("message_id"), "accepted", "none")
        assertEquals("accepted", receive(first).string("status"))
        assertEquals("duplicate", receive(first).string("status"))
        assertEquals("rejected", receive(want(8, 9)).string("status"))
        val delivered = mutableMapOf<Int, ByteArray>()
        fun readChunks(count: Int) {
            val chunks = sendDue()
            assertEquals(count, chunks.size)
            for (wire in chunks) {
                val (kind, body) = PhoneContentScope.unwrap(wire.getValue("body").jsonObject, manifest)
                assertEquals("personal_sync.attachment_chunk", kind)
                assertEquals(JsonPrimitive(false), body["reply"])
                assertEquals(digest, body.string("sha256"))
                assertEquals(aggregate, body.string("records_hash"))
                assertNull(delivered.put(body.long("index").toInt(), java.util.Base64.getDecoder().decode(body.string("data"))))
                ack(wire.string("message_id"), "accepted", "none")
            }
        }
        readChunks(8)
        assertEquals("rejected", receive(result).string("status"))
        assertNull(queue.duplicateResult(peerId, result.string("message_id")))
        assertEquals("accepted", receive(want(8, 9)).string("status"))
        readChunks(1)
        assertArrayEquals(initialConnectionOriginal(), delivered.toSortedMap().values.flatMap { it.asIterable() }.toByteArray())
        assertEquals("accepted", receive(result).string("status"))
        assertEquals("duplicate", receive(result).string("status"))
        assertTrue(sendDue().isEmpty())
    }

    private fun rejectPrematureConnectionReport(work: TelefonWerk, peer: TelefonPeer, queue: TelefonQueue,
                                                manifest: JsonObject, request: JsonObject) {
        val run = request.string("run_id")
        val wire = connectionTestReport(manifest, request)
        val channel = field(TelefonWerk::class.java, "activeChannel").get(work) as TelefonSecureChannel
        work.receiveMessage(peer, wire, channel, 0L)
        assertFalse("Premature remote report completed a connection run", queue.personalRunMarked(peer.device_id, run, "reported"))
        assertNull(queue.duplicateResult(peer.device_id, wire.string("message_id")))
    }

    private fun connectionTestReport(manifest: JsonObject, runBody: JsonObject, transport: String = "bluetooth"): JsonObject {
        val report = buildJsonObject {
            put("format", runBody.getValue("format")); put("run_id", runBody.string("run_id")); put("state", "complete")
            put("trigger", PersonalAutoSync.CONNECTION); put("transport", transport); put("error", "none")
            val zero = buildJsonObject { for (name in listOf("notes", "tasks", "notebooks")) put(name, 0) }
            put("sent", zero); put("received", zero)
            for (name in listOf("conflicts", "attachments_omitted", "oversized_skipped")) put(name, 0)
            put("started_ms", 1); put("finished_ms", 2)
            put("attachments", buildJsonObject {
                for (name in listOf("declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes")) put(name, 0)
            })
            put("deletions", buildJsonObject {
                for (name in listOf("pending", "deleted", "restored", "conflicts", "blocked")) put(name, 0)
                put("trash", JsonObject(zero + ("attachments" to JsonPrimitive(0))))
            })
        }
        return TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
            PhoneContentScope.wrap("personal_sync.report", report, manifest), 60_000)
    }

    private fun replacementConnectionAck(work: TelefonWerk, peer: TelefonPeer, requestId: String) {
        val active = field(TelefonWerk::class.java, "activeChannel")
        val original = active.get(work) as TelefonSecureChannel
        @Suppress("UNCHECKED_CAST")
        val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
        val first = sessions.getValue(original)
        val replacement = PersonalNoteSession().apply {
            capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
            sharedSent = first.sharedSent; sharedReceived = first.sharedReceived
            localContentScope = first.localContentScope; contentScopeSelection = first.contentScopeSelection
            contentScopeRestoreEpoch = first.contentScopeRestoreEpoch; contentScopePreference = first.contentScopePreference
            contentScopeAccepted.addAll(first.contentScopeAccepted)
        }
        TelefonSecureChannel(ByteArrayInputStream(ByteArray(0)), ByteArrayOutputStream(), ByteArray(32) { 1 },
            ByteArray(32) { 2 }, ByteArray(4) { 3 }, ByteArray(32) { 4 }, ByteArray(4) { 5 }).use { reader ->
            active.set(work, reader)
            bindSyntheticPhoneSession(work, reader)
            sessions[reader] = replacement
            try {
                work.handleSessionAck(peer, TelefonNachrichten.ack(requestId, "accepted", "none"), replacement,
                    0L, TelefonTransportArt.BLUETOOTH, reader)
            } finally {
                sessions.remove(reader)
                active.set(work, original)
            }
        }
    }

    private fun exercise(mode: String, format: Int = 3) {
        val automaticReconnect = mode.startsWith("auto-late-")
        val customWifi = mode.startsWith("custom-wlan-")
        val connectionStart = mode.startsWith("start-auto-connection")
        val connectionAutomation = mode.startsWith("receive-auto-connection") || connectionStart
        val multiConnectionReply = mode == "receive-auto-connection-multi-report-reply"
        val actorDeletion = mode.startsWith("actor-deletions")
        val actorCommit = mode.startsWith("actor-commit")
        val actorTerminal = mode.startsWith("actor-commit-terminal")
        val actorProducer = mode.startsWith("actor-producer")
        val historicalSave = mode.startsWith("actor-deletions-origin-pending-save")
        val historicalTask = mode == "actor-deletions-origin-pending-save-task"
        val historicalBoundary = mode == "actor-deletions-origin-pending-save-boundary"
        val actorAckFailure = mode in setOf("actor-commit-ack-failure", "actor-commit-terminal-auto-ack-failure")
        val nativeActor = actorDeletion || actorCommit || actorProducer || mode in setOf("actor-source", "actor-snapshot", "actor-cancel", "actor-cancel-pending", "actor-revoked", "actor-restart", "actor-transport")
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
        val journalInstance = field(io.gitlab.maik3531.magnolienotes.journal.AndroidJournal::class.java, "instance")
        val priorJournal = journalInstance.get(null)
        field(TelefonAblage::class.java, "instance").set(null, null)
        field(TelefonWerk::class.java, "instance").set(null, null)
        journalInstance.set(null, null)
        val failBookWrites = AtomicBoolean(false)
        val documents = Ablage.fuerTest(context) {
            if (failBookWrites.get()) throw java.io.IOException("Synthetic actual book writer failure")
            SecretKeySpec(ByteArray(32) { 19 }, "AES")
        }
        field(Ablage::class.java, "einzig").set(null, documents)
        var runtimeWork: TelefonWerk? = null
        try {
            val book = documents.legeNotizbuchAn("Field notes")
            documents.setzeNotiz(Notiz("phone-note", "Mobile", "Initial phone text", notizbuchId = book.id, angelegt = 1, geaendert = 2,
                ursprungApp = if (format == 14) "notes" else "",
                anhaenge = if (connectionStart) listOf(Anhang("original", "Synthetic original.png", "image",
                    "data:image/png;base64," + java.util.Base64.getEncoder().encodeToString(initialConnectionOriginal()))) else emptyList(),
                baumQuelle = if (mode == "send-route") "linked-origin" else "",
                persoenlichVerknuepft = mode == "send-route"))
            if (mode == "start-auto-connection-attachment")
                documents.setzeNotiz(Notiz("return-note", "Return note", notizbuchId = book.id))
            if (multiConnectionReply) repeat(32) { index ->
                documents.setzeNotiz(Notiz("reply-member-$index", "Additional member", "Synthetic text",
                    notizbuchId = book.id, angelegt = 1, geaendert = 2, ursprungApp = "notes"))
            }
            if (connectionStart || automaticReconnect || actorDeletion || actorCommit || mode.startsWith("actor-producer-incoming-mixed-") || mode.startsWith("send-") || mode in setOf("manual", "actor", "actor-snapshot", "actor-cancel", "actor-cancel-pending", "actor-revoked", "actor-transport")) documents.setzeAufgabe(Aufgabe("phone-task", "Mobile task"))
            if (mode.startsWith("send-")) {
                documents.setzeNotiz(Notiz("private-note", "Unselected note", "Never transfer", notizbuchId = book.id))
                documents.setzeAufgabe(Aufgabe("private-task", "Unselected task",
                    delegiertAn = if (mode == "send-route") "tree-peer" else ""))
                if (mode == "send-route") documents.setzeNotiz(Notiz("foreign-note", "Foreign tree note", baumQuelle = "tree-peer"))
            }
            val storage = TelefonAblage.get(context)
            storage.identity("Synthetic").second.fill(0)
            storage.setEnabled(true); storage.setPersonalSync(true, true, true, false, false)
            val nonElectedPeer = mode == "receive-auto-connection-higher-uuid"
            val peerId = when {
                connectionStart || nonElectedPeer -> "ffffffff-ffff-4fff-bfff-ffffffffffff"
                connectionAutomation -> "00000000-0000-4000-8000-000000000000"
                else -> "22222222-2222-4222-8222-222222222222"
            }
            if (actorProducer) {
                val fixture = TelefonKanonisch.json.parseToJsonElement(requireNotNull(javaClass.getResource("/personal-sync-contract.json")).readText()).jsonObject
                val dataUrl = fixture.getValue("format2").jsonObject.getValue("data_url").jsonPrimitive.content
                documents.setzeNotiz(requireNotNull(documents.notiz("phone-note")).copy(anhaenge = (0..32).map {
                    Anhang("native-file-$it", "Synthetic $it.png", "image", dataUrl) }))
                documents.setzeNotiz(Notiz("removed-note", "Outside current membership"))
                documents.personalSyncSnapshot(setOf("notes"), 3)
                documents.personalSyncAcknowledge(peerId)
                for (index in 0..32) documents.loescheAnhang("phone-note", "native-file-$index")
                documents.loescheNotiz("removed-note")
                documents.personalSyncSnapshot(setOf("notes"), 3)
                assertEquals(33, PersonalSync.proposals(documents.bestand.value, peerId).count { it.kind == "attachment" })
            }
            if (historicalSave) {
                if (historicalBoundary) repeat(254) { documents.setzeNotiz(Notiz("boundary-note-$it", text = "Synthetic boundary note $it")) }
                if (historicalTask) documents.setzeAufgabe(Aufgabe("removed-task", titel = "Synthetic historical task"))
                else documents.setzeNotiz(Notiz("removed-note", text = "Synthetic historical source"))
                documents.personalSyncSnapshot(setOf("notes", "tasks"), 3); documents.personalSyncAcknowledge(peerId)
                if (historicalTask) documents.loescheAufgabe("removed-task") else documents.loescheNotiz("removed-note")
                documents.personalSyncSnapshot(setOf("notes", "tasks"), 3)
            }
            val deletionGrant = actorDeletion || actorTerminal || actorProducer && mode != "actor-producer-no-grants" || mode in setOf("delete", "skip-delete")
            val connectionVersions = if (connectionAutomation) listOf(PersonalAutoSync.VERSION) else emptyList()
            val missingRemoteFormat = mode == "receive-auto-connection-remote-format"
            val newerFormat = if (format == 14 || missingRemoteFormat) listOf(14) else emptyList()
            val peer = TelefonPeer(peerId, "Synthetic desktop", TelefonKrypto.b64(ByteArray(32) { 23 }),
                own_device = true, remote_own_device = true, personal_notes_sync_granted = !customWifi, personal_tasks_sync_granted = !customWifi,
                capabilities_revision = if (connectionAutomation) 2 else 0,
                remote_personal_notes_sync_granted = !customWifi, remote_personal_tasks_sync_granted = !customWifi,
                personal_deletions_sync_granted = deletionGrant, remote_personal_deletions_sync_granted = deletionGrant,
                remote_personal_notes_sync_available = true, remote_personal_tasks_sync_available = true,
                remote_personal_notes_sync_versions = (listOf(1, 2, 3, 5, 9, 10) + connectionVersions + newerFormat +
                    if (nativeActor) listOf(12) else emptyList()).filterNot { missingRemoteFormat && it == 3 }.sorted(),
                remote_personal_tasks_sync_versions = (listOf(1, 2, 3, 4, 6, 7, 9, 10) + connectionVersions + newerFormat +
                    if (nativeActor) listOf(12) else emptyList()).sorted())
            storage.savePeer(peer)
            val work = TelefonWerk.get(context)
            runtimeWork = work
            work.sharedLocalCapabilities = { TelefonCapabilities.phase1() }
            if (connectionAutomation) work.sharedLocalCapabilities = {
                TelefonCapabilities.phase1().mapValues { (name, value) ->
                    if (name in setOf("personal_notes_sync", "personal_tasks_sync"))
                        value.copy(versions = (value.versions + PersonalAutoSync.VERSION)
                            .filterNot { mode == "receive-auto-connection-local-format" && name == "personal_tasks_sync" && it == 3 }
                            .sorted()) else value
                }
            }
            if (nativeActor) work.sharedLocalCapabilities = {
                TelefonCapabilities.phase1().mapValues { (name, value) ->
                    if (name in setOf("personal_notes_sync", "personal_tasks_sync")) value.copy(versions = value.versions + 12) else value
                }
            }
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            (field(TelefonWerk::class.java, "connecting").get(work) as AtomicBoolean).set(true)
            val closed = AtomicInteger()
            val wake = AtomicReference<CountDownLatch?>()
            val failNextFlush = AtomicBoolean(false)
            val checkNativeAckLocks = AtomicBoolean(false)
            val nativeAckLockChecks = AtomicInteger()
            val wireOutput = object : ByteArrayOutputStream() {
                override fun flush() {
                    var nativeAck = false
                    if (checkNativeAckLocks.get()) {
                        // Normal ownership/settings controls use a different
                        // existing send lane. Check the actual encrypted Actor
                        // ACK, not every unrelated control flushed by the pump.
                        val input = ByteArrayInputStream(toByteArray())
                        var envelope: JsonObject? = null
                        while (input.available() > 0) envelope = TelefonRahmen.lesen(input, TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
                        val frame = requireNotNull(envelope)
                        val clear = TelefonKrypto.entschluesseln(ByteArray(32) { 11 },
                            TelefonKrypto.nonce(ByteArray(4) { 12 }, frame.long("seq")),
                            java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(JsonObject(frame - "ciphertext")))
                        val ack = try { TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) }
                            finally { clear.fill(0) }
                        if (ack) {
                            nativeAck = true
                            check(!Thread.holdsLock(work) && !Thread.holdsLock(Ablage.SCHREIBSPERRE)) { "Native ACK I/O held service/book guards" }
                            nativeAckLockChecks.incrementAndGet()
                        }
                    }
                    if ((!checkNativeAckLocks.get() || nativeAck) && failNextFlush.getAndSet(false))
                        throw java.io.IOException("Synthetic encrypted channel write failure")
                    super.flush(); wake.get()?.countDown()
                }
            }
            val preparedBook = java.io.File(context.filesDir, "notizen.json.neu")
            val watchBookReplacement = AtomicBoolean(false)
            val readerLostAtReplacement = AtomicBoolean(false)
            val pipe = object : TelefonRoehre {
                override val input = ByteArrayInputStream(ByteArray(0))
                override val output = wireOutput
                override fun close() { closed.incrementAndGet() }
                override fun aktuell(): Boolean {
                    if (watchBookReplacement.get() && preparedBook.isFile) readerLostAtReplacement.set(true)
                    return !readerLostAtReplacement.get()
                }
            }
            val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
            fun queueConnectionAdvertisement(revision: Long) = queue.queue(peerId, "capabilities.update",
                TelefonNachrichten.capabilities(revision, work.sharedLocalCapabilities()), 60_000)
            val lateAdvertisement = mode == "receive-auto-connection-advertisement"
            if (connectionAutomation && !lateAdvertisement) queueConnectionAdvertisement(peer.capabilities_revision)
            var local = work.changeSharedSetting(peerId, peer.static_public, "content_mode", JsonPrimitive("phone_scope"))
            if (automaticReconnect) local = work.changeSharedSetting(peerId, peer.static_public, "auto_mode", JsonPrimitive("wifi"))
            if (customWifi) {
                work.changeSharedSetting(peerId, peer.static_public, "auto_mode", JsonPrimitive("wifi"))
                local = work.changeSharedSetting(peerId, peer.static_public, "custom_enabled", JsonPrimitive(true))
            }
            if (connectionAutomation) local = work.changeSharedSetting(peerId, peer.static_public, "auto_mode", JsonPrimitive("connection"))
            if (actorTerminal || actorProducer && mode != "actor-producer-skip" || mode.startsWith("actor-deletions-origin") || mode in setOf("delete", "actor-deletions")) local = work.changeSharedSetting(peerId, peer.static_public, "skip_deletions", JsonPrimitive(false))
            val transport = if (connectionStart || mode == "custom-wlan-bluetooth") TelefonTransportArt.BLUETOOTH else TelefonTransportArt.WIFI
            field(TelefonWerk::class.java, "activeTransport").set(work, transport to pipe)
            val identity = storage.identity("Synthetic"); val actor = identity.first.device_id; identity.second.fill(0)
            val shared = SharedSyncSettings.merge(SharedSyncSettings.create(peerId), local, peerId, actor)
            TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 }, ByteArray(4) { 12 },
                ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { channel ->
                bindSyntheticPhoneSession(work, channel)
                var session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true }
                if (nativeActor) session.observeActorOwnDecision(true)
                @Suppress("UNCHECKED_CAST")
                val sessions = field(TelefonWerk::class.java, "noteSessions").get(work) as MutableMap<TelefonSecureChannel, PersonalNoteSession>
                sessions[channel] = session
                if (connectionStart || customWifi) field(TelefonWerk::class.java, "activeChannel").set(work, channel)
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
                    work.handleSessionAck(peer, TelefonNachrichten.ack(id, status, error), session, 0L, transport)
                fun ackScope() { session.contentScopeMessages.keys.toList().also { assertTrue(it.isNotEmpty()) }.forEach { ack(it) } }
                fun scoped(messages: List<JsonObject>) = messages.filter { it["kind"] == JsonPrimitive(PhoneContentScope.DATA_KIND) }
                if (customWifi) {
                    checkLateCustomWifi(mode, work, peer, channel, queue, { pump.invoke(work, peer, channel, 0L, false) }, ::sent, { ack(it) })
                    return@use
                }
                val manifest = requireNotNull(session.localContentScope)
                if (connectionStart) {
                    sent()
                    checkConnectionInitiator(work, peer, queue, manifest, {
                        pump.invoke(work, peer, channel, 0L, false)
                        scoped(sent())
                    }, ::ackScope, ::ack, { wire ->
                        work.receiveMessage(peer, wire, channel, 0L)
                        sent().single { it["message_id"] == wire["message_id"] }
                    }, failBookWrites, failNextFlush, replyOriginal = mode == "start-auto-connection-attachment")
                    return@use
                }
                fun checkAutomaticWifiReconnect() {
                    val enqueue = TelefonWerk::class.java.getDeclaredMethod("enqueuePersonalSync", TelefonPeer::class.java,
                        String::class.java, String::class.java, Boolean::class.javaPrimitiveType).apply { isAccessible = true }
                    val secureTransition = TelefonWerk::class.java.getDeclaredMethod("startPersonalSyncOnSecureWifi",
                        TelefonPeer::class.java, TelefonSecureChannel::class.java, Long::class.javaPrimitiveType).apply { isAccessible = true }
                    field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    (field(TelefonWerk::class.java, "scopedWakeup").get(work) as AtomicBoolean).set(true)
                    sent(); ackScope(); pump.invoke(work, peer, channel, 0L, false); sent()
                    val needsReplacement = mode in setOf("auto-late-stale", "auto-late-delayed")
                    val oldRun = if (needsReplacement || mode == "auto-late-active") {
                        assertEquals(true, enqueue.invoke(work, peer, "auto_wifi", null, false))
                        pump.invoke(work, peer, channel, 0L, false)
                        val request = scoped(sent()).single { PhoneContentScope.unwrap(it.getValue("body").jsonObject,
                            requireNotNull(session.localContentScope)).first == "personal_sync.request" }
                        assertTrue(queue.hasActiveAutoRun(peerId))
                        PhoneContentScope.unwrap(request.getValue("body").jsonObject,
                            requireNotNull(session.localContentScope)).second.string("run_id")
                    } else {
                        documents.personalSyncScopedSnapshot(PersonalSync.livePersonalContent(documents.bestand.value), peerId, format)
                        null
                    }
                    val baselineCounter = documents.personalSyncCounter()
                    storage.setPersonalSyncLastCounter(baselineCounter)
                    storage.setPersonalSyncLastAuto(System.currentTimeMillis())
                    if (mode !in setOf("auto-late-unchanged", "auto-late-active"))
                        documents.setzeNotiz(Notiz("new-offline-note", "Offline note", "Synthetic content", notizbuchId = book.id))
                    // Reconnect with fresh bilateral controls but delayed common settings.
                    session = PersonalNoteSession().apply { capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true }
                    sessions[channel] = session
                    val wholeCollectionMode = when (mode) {
                        "auto-late-import" -> "phone_import"
                        "auto-late-full" -> "two_way"
                        else -> null
                    }
                    val agreed = wholeCollectionMode?.let {
                        SharedSyncSettings.merge(shared,
                            work.changeSharedSetting(peerId, peer.static_public, "content_mode", JsonPrimitive(it)), peerId, actor)
                    }
                    queue.removeKind(peerId, SharedSyncSettings.KIND)
                    pump.invoke(work, peer, channel, 0L, true); sent()
                    assertNull(session.sharedReceived)
                    if (mode == "auto-late-bluetooth")
                        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.BLUETOOTH to pipe)
                    secureTransition.invoke(work, peer, channel, 0L)
                    if (agreed != null) {
                        checkLateWholeCollectionWifi(work, peer, channel, agreed, documents, queue,
                            { pump.invoke(work, peer, channel, 0L, false) }, ::sent, { ack(it) })
                        return
                    }
                    if (mode == "auto-late-bluetooth")
                        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
                    if (mode == "auto-late-delayed")
                        org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofSeconds(61))
                    var currentShared = shared
                    if (mode == "auto-late-off") {
                        val disabled = SharedSyncSettings.change(shared, peerId, actor, "auto_mode", JsonPrimitive("manual"))
                        work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, disabled, 60000), channel, 0)
                        assertNull(session.pendingSharedWifiStart)
                        val enabled = SharedSyncSettings.change(disabled, peerId, actor, "auto_mode", JsonPrimitive("wifi"))
                        work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, enabled, 60000), channel, 0)
                        currentShared = enabled
                    }
                    if (mode == "auto-late-grants") {
                        for ((revision, granted) in listOf(1L to false, 2L to true)) {
                            work.receiveMessage(peer, TelefonNachrichten.message("grants.update",
                                TelefonNachrichten.grants(revision, personalNotes = granted, personalTasks = true), 60000), channel, 0)
                            assertNull(session.pendingSharedWifiStart)
                        }
                    }
                    if (mode == "auto-late-channel") {
                        TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 1 }, ByteArray(32) { 2 }, ByteArray(4) { 3 },
                            ByteArray(32) { 4 }, ByteArray(4) { 5 }).use { replacement ->
                            field(TelefonWerk::class.java, "activeChannel").set(work, replacement)
                            pump.invoke(work, peer, channel, 0L, false)
                            assertNull(session.pendingSharedWifiStart)
                        }
                        field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                    }
                    if (mode == "auto-late-pipe") {
                        val replacement = object : TelefonRoehre {
                            override val input = ByteArrayInputStream(ByteArray(0))
                            override val output = ByteArrayOutputStream()
                            override fun close() {}
                        }
                        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to replacement)
                        pump.invoke(work, peer, channel, 0L, false)
                        assertNull(session.pendingSharedWifiStart)
                        field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
                    }
                    // No data is permitted merely because shared settings arrived.
                    work.receiveMessage(peer, TelefonNachrichten.message(SharedSyncSettings.KIND, currentShared, 60000), channel, 0)
                    pump.invoke(work, peer, channel, 0L, false); pump.invoke(work, peer, channel, 0L, false)
                    if (needsReplacement) {
                        assertNull(queue.personalRun(peerId, requireNotNull(oldRun)))
                        assertFalse(queue.hasActiveAutoRun(peerId))
                    }
                    assertTrue("Unconfirmed membership sent a request", scoped(sent()).isEmpty())
                    ackScope(); pump.invoke(work, peer, channel, 0L, false)
                    if (needsReplacement) {
                        assertTrue(queue.hasActiveAutoRun(peerId))
                        val requests = scoped(sent())
                        assertEquals(1, requests.size)
                        val nextManifest = requireNotNull(session.localContentScope)
                        val request = PhoneContentScope.unwrap(requests.single().getValue("body").jsonObject, nextManifest)
                        assertEquals("personal_sync.request", request.first)
                        assertEquals("auto_wifi", request.second.string("trigger"))
                        assertNotEquals(oldRun, request.second.string("run_id"))
                        assertFalse(queue.scopedRequestAccepted(peerId, request.second.string("run_id")))
                        pump.invoke(work, peer, channel, 0L, false)
                        assertTrue("Data preceded request receipt", scoped(sent()).isEmpty())
                        ack(requests.single().string("message_id")); pump.invoke(work, peer, channel, 0L, false)
                        val records = scoped(sent()).map { PhoneContentScope.unwrap(it.getValue("body").jsonObject, nextManifest) }
                            .filter { it.first == "personal_sync.batch" }.flatMap { PersonalSyncProtokoll.decodeBatch(it.second) }
                        assertTrue(records.any { it.kind == "note" && it.id == PersonalSync.noteWireId(documents.bestand.value.personalSync, "new-offline-note") })
                        queue.markPersonalRun(peerId, request.second.string("run_id"), "reported")
                    } else if (mode == "auto-late-active") {
                        assertTrue(queue.hasActiveAutoRun(peerId)); assertNotNull(queue.personalRun(peerId, requireNotNull(oldRun)))
                        assertTrue(scoped(sent()).none { PhoneContentScope.unwrap(it.getValue("body").jsonObject,
                            requireNotNull(session.localContentScope)).second.string("run_id") != oldRun })
                        queue.markPersonalRun(peerId, oldRun, "reported")
                    } else {
                        assertFalse(queue.hasActiveAutoRun(peerId)); assertTrue(scoped(sent()).isEmpty())
                    }
                    assertNull(session.pendingSharedWifiStart)
                    repeat(3) { pump.invoke(work, peer, channel, 0L, false) }
                    assertFalse("A heartbeat repeated the completed transition", queue.hasActiveAutoRun(peerId))
                }
                if (automaticReconnect) {
                    checkAutomaticWifiReconnect()
                    return@use
                }
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
                if (mode == "actor-transport" || actorDeletion || actorCommit || actorProducer) {
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
                    if (mode == "actor-producer-sql-failure") {
                        val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                        database.execSQL("CREATE TRIGGER actor_producer_failure BEFORE INSERT ON inbox WHEN NEW.state='actor_staged' BEGIN SELECT RAISE(ABORT,'synthetic native proposal target failure'); END")
                    }
                    pump.invoke(work, peer, channel, 0L, false)
                    if (mode == "actor-producer-sql-failure") {
                        assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                        assertTrue(queue.actorDeletionIntents(run, true).isEmpty())
                        assertNull(queue.personalRun(peerId, run))
                        assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).none { it.payload["body"]?.jsonObject?.get("run_id") == JsonPrimitive(run) })
                        return@use
                    }
                    val request = sent().single { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                    assertEquals("personal_sync.request", PersonalSyncActor.unwrap(request.getValue("body").jsonObject).first)
                    assertFalse(queue.scopedRequestAccepted(peerId, run))
                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                        PersonalSyncActor.ack(run, request.string("message_id")), 60000), channel, 0L)
                    assertTrue(sent().isEmpty()); assertTrue(queue.scopedRequestAccepted(peerId, run))
                    pump.invoke(work, peer, channel, 0L, false)
                    val batches = sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                    if (actorProducer) {
                        val dispatched = batches.toMutableList()
                        repeat(3) {
                            pump.invoke(work, peer, channel, 0L, false)
                            dispatched.addAll(sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                        }
                        val proposals = dispatched.map { PersonalSyncActor.unwrap(it.getValue("body").jsonObject) }
                            .filter { it.first == "personal_sync.deletion_proposals" }.map { it.second }.sortedBy { it.long("sequence") }
                        val proofs = queue.actorDeletionIntents(run, true)
                        if (mode in setOf("actor-producer-no-grants", "actor-producer-skip")) {
                            assertTrue(proposals.isEmpty()); assertTrue(proofs.isEmpty())
                        } else {
                            assertEquals(listOf(0L, 1L), proposals.map { it.long("sequence") })
                            assertEquals(listOf(JsonPrimitive(false), JsonPrimitive(true)), proposals.map { it["last"] })
                            assertEquals(1, proposals.map { it.string("proposal_batch_id") }.distinct().size)
                            val decoded = proposals.flatMap(PersonalSyncProtokoll::decodeDeletionProposals)
                            assertEquals(33, decoded.size); assertEquals(33, decoded.map { it.proposalId }.distinct().size)
                            assertTrue(decoded.all { it.kind == "attachment" && it.parentId == "phone-note" })
                            val native = PersonalSync.proposals(documents.bestand.value, peerId).associateBy { it.proposal_id }
                            assertTrue(decoded.all { native[it.proposalId]?.clock == it.clock && native[it.proposalId]?.prior_hash == it.priorHash })
                            assertEquals(proposals.toSet(), proofs.map { it.getValue("body").jsonObject }.toSet())
                            assertEquals(proofs.map { it.string("message_id") }.toSet(), dispatched.filter {
                                PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.deletion_proposals" }.map { it.string("message_id") }.toSet())
                        }
                        assertNull(documents.notiz("removed-note")); assertTrue(documents.notiz("phone-note")!!.anhaenge.isEmpty())
                        if (mode == "actor-producer-origin-pending") {
                            @Suppress("UNCHECKED_CAST")
                            val handle = (field(TelefonWerk::class.java, "personalActorHandles").get(work) as Map<String, PersonalActorHandle>).getValue(run)
                            val meta = documents.bestand.value.personalSync.entities.getValue("note\u0000removed-note")
                            assertEquals("deleted", meta.state); assertEquals("local_pending", meta.status)
                            val target = buildJsonObject {
                                put("proposal_id", UUID.randomUUID().toString()); put("kind", "note"); put("id", "removed-note"); put("parent_id", "")
                                put("clock", JsonArray(meta.clock.map { buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } }))
                                put("prior_hash", meta.prior_hash)
                            }
                            val original = PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.deletion_proposals", buildJsonObject {
                                put("format", 1); put("run_id", run); put("proposal_batch_id", UUID.randomUUID().toString()); put("sequence", 0); put("last", true)
                                put("proposals", JsonArray(listOf(JsonObject(target + mapOf("deleted_ms" to JsonPrimitive(2), "label" to JsonPrimitive("Synthetic pending target"))))))
                            }, 60000), run)
                            val retained = documents.bestand.value; val saved = documents.personalActorSavedBookState()
                            val bytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                            work.receiveMessage(peer, original, channel, 0L); assertTrue(sent().isEmpty())
                            assertEquals(listOf(original), work.readPersonalActorIncomingTargetFrames(handle))
                            val view = work.reviewPersonalActorIncomingTargets(handle)
                            assertEquals(JsonPrimitive(false), view["action_authorized"])
                            assertEquals(JsonPrimitive("deleted"), view.getValue("observations").jsonArray.single().jsonObject["local_state"])
                            val choices = listOf(buildJsonObject {
                                put("proposal_id", target.getValue("proposal_id")); put("decision", "restore")
                                put("expected_clock", target.getValue("clock")); put("confirm_conflict", true)
                            })
                            val draft = work.reviewPersonalActorIncomingTargets(handle, view.string("revision"), choices)
                            assertEquals(JsonPrimitive(false), draft["action_authorized"])
                            assertEquals(JsonPrimitive(true), draft["conflicts_explicitly_confirmed"])
                            assertSame(retained, documents.bestand.value); assertEquals(saved, documents.personalActorSavedBookState())
                            assertArrayEquals(bytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                            assertTrue(queue.actorDeletionIntents(run).isEmpty()); assertNull(documents.notiz("removed-note")); assertTrue(sent().isEmpty())
                            documents.setzeNotiz(requireNotNull(documents.notiz("phone-note")).copy(text = "Synthetic later native save"))
                            assertTrue(runCatching { work.reviewPersonalActorIncomingTargets(handle, view.string("revision"), choices) }.isFailure)
                            work.stopPersonalActor(handle)
                            return@use
                        }
                        if (mode.startsWith("actor-producer-incoming-")) {
                            @Suppress("UNCHECKED_CAST")
                            val handle = (field(TelefonWerk::class.java, "personalActorHandles").get(work) as Map<String, PersonalActorHandle>).getValue(run)
                            val native = proofs.flatMap { PersonalSyncProtokoll.decodeDeletionProposals(it.getValue("body").jsonObject) }.sortedBy { it.proposalId }
                            val choice = if (mode.endsWith("restore") || mode.contains("mixed-restore")) "restore" else "delete"
                            val decisionBodies = native.chunked(32).map { chunk -> buildJsonObject {
                                put("format", 1); put("run_id", run); put("decision_id", UUID.randomUUID().toString())
                                put("decisions", JsonArray(chunk.map { proposal -> buildJsonObject {
                                    put("proposal_id", proposal.proposalId); put("decision", choice)
                                    put("expected_clock", JsonArray(proposal.clock.map { buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } }))
                                } }))
                            } }
                            val decisionBody = decisionBodies.first()
                            val wrongDecisions = decisionBody.getValue("decisions").jsonArray.toMutableList()
                            wrongDecisions[0] = JsonObject(wrongDecisions[0].jsonObject + ("expected_clock" to buildJsonArray { add(buildJsonObject {
                                put("actor_id", peerId); put("counter", 999) }) }))
                            work.receiveMessage(peer, PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.deletion_decision",
                                JsonObject(decisionBody + ("decisions" to JsonArray(wrongDecisions))), 60000), run), channel, 0L)
                            assertTrue(sent().isEmpty()); assertTrue(queue.actorDeletionIntents(run).isEmpty())
                            val incomingDecisions = (if (mode.endsWith("reject-partial")) decisionBodies.take(1) else decisionBodies)
                                .map { PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.deletion_decision", it, 60000), run) }
                            val incomingDecision = incomingDecisions.first()
                            val incomingIds = incomingDecisions.map { it.getValue("message_id") }.toSet()
                            for (wire in incomingDecisions) work.receiveMessage(peer, wire, channel, 0L)
                            assertTrue(sent().isEmpty()); assertEquals(incomingDecisions.size, queue.actorDeletionIntents(run).size)
                            assertTrue(runCatching { work.commitPersonalActorDeletionReview(handle, emptyMap()) }.isFailure)
                            // Complete the actual data direction first. Its ACK
                            // is distinct from the ACK for this deletion decision.
                            val replyRecords = batches.filter { PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.batch" }
                                .flatMap { PersonalSyncProtokoll.decodeBatch(PersonalSyncActor.unwrap(it.getValue("body").jsonObject).second) }
                            val mixed = mode.startsWith("actor-producer-incoming-mixed-")
                            val localProposalId = UUID.randomUUID().toString()
                            if (mixed) {
                                val task = replyRecords.single { it.kind == "task" }
                                val overlap = if (mode.endsWith("reject-overlap")) native.first() else null
                                val localProposal = TelefonNachrichten.message("personal_sync.deletion_proposals", buildJsonObject {
                                    put("format", 1); put("run_id", run); put("proposal_batch_id", UUID.randomUUID().toString()); put("sequence", 0); put("last", true)
                                    put("proposals", buildJsonArray { add(buildJsonObject {
                                        put("proposal_id", localProposalId); put("kind", overlap?.kind ?: "task"); put("id", overlap?.id ?: task.id); put("parent_id", overlap?.parentId ?: "")
                                        put("prior_hash", overlap?.priorHash ?: task.hash); put("deleted_ms", System.currentTimeMillis()); put("label", "Mixed native review")
                                        put("clock", JsonArray((overlap?.clock ?: PersonalSync.merge(task.clock, listOf(PersonalSyncClock(peerId, 2)))).map {
                                            buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } }))
                                    }) })
                                }, 60000)
                                work.receiveMessage(peer, PersonalSyncActor.wireMessage(localProposal, run), channel, 0L)
                                assertTrue(sent().isEmpty()); assertEquals(incomingDecisions.size + 1, queue.actorDeletionIntents(run).size)
                            }
                            val incomingBatch = PersonalSyncProtokoll.batch(run, replyRecords, 0, true, true, format, PersonalSync.recordsHash(replyRecords))
                            work.receiveMessage(peer, PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.batch", incomingBatch, 60000), run), channel, 0L)
                            assertEquals(1, sent().size)
                            val reportBody = buildJsonObject {
                                put("format", format); put("run_id", run); put("state", "complete"); put("trigger", "manual"); put("transport", "wifi")
                                for (direction in listOf("sent", "received")) put(direction, buildJsonObject {
                                    put("notes", replyRecords.count { it.kind == "note" }); put("tasks", replyRecords.count { it.kind == "task" }); put("notebooks", replyRecords.count { it.kind == "notebook" }) })
                                put("conflicts", 0); put("attachments_omitted", 0); put("oversized_skipped", 0)
                                put("started_ms", System.currentTimeMillis()); put("finished_ms", System.currentTimeMillis()); put("error", "none")
                                put("attachments", buildJsonObject {
                                    for (name in listOf("declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes")) put(name, 0)
                                })
                                put("deletions", buildJsonObject {
                                    put("pending", native.size)
                                    for (name in listOf("deleted", "restored", "conflicts", "blocked")) put(name, 0)
                                    put("trash", buildJsonObject {
                                        for (name in listOf("notes", "tasks", "notebooks")) put(name, 0)
                                        put("attachments", native.size)
                                    })
                                })
                            }
                            work.receiveMessage(peer, PersonalSyncActor.wireMessage(TelefonNachrichten.message("personal_sync.report", reportBody, 60000), run), channel, 0L)
                            assertEquals(1, sent().size); assertNotNull(work.actorDataReportReceipt(handle))
                            documents.setzeNotizEntwurf(documents.notiz("phone-note")!!.copy(text = "Retained incoming-decision GUI draft")); documents.sichereEntwurf()
                            val draft = documents.entwurf.value
                            val witness = requireNotNull(documents.personalActorSavedBookState())
                            val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                            val denyIncomingAck = mode.startsWith("actor-producer-incoming-deny-") || mode.startsWith("actor-producer-incoming-mixed-restore-deny-")
                            if (mode.endsWith("ledger-failure") || denyIncomingAck) database.execSQL("CREATE TRIGGER incoming_ledger_failure BEFORE UPDATE ON inbox WHEN NEW.state='actor_processed' BEGIN SELECT RAISE(ABORT,'synthetic incoming decision ledger failure'); END")
                            if (mode.endsWith("metadata-failure")) database.execSQL("CREATE TRIGGER incoming_metadata_failure BEFORE INSERT ON meta WHEN NEW.key GLOB 'personal_actor_completion_wire:*' BEGIN SELECT RAISE(ABORT,'synthetic sent ACK persistence failure'); END")
                            if (mode.endsWith("writer-failure")) failBookWrites.set(true)
                            if (mode.endsWith("send-failure")) failNextFlush.set(true)
                            checkNativeAckLocks.set(true)
                            if (mode.startsWith("actor-producer-incoming-mixed-reject-")) {
                                val retainedBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                val exactReview = mapOf(localProposalId to choice)
                                val review = when {
                                    mode.endsWith("review-missing") -> emptyMap()
                                    mode.endsWith("review-extra") -> exactReview + (native.first().proposalId to choice)
                                    else -> exactReview
                                }
                                assertTrue(runCatching { work.commitPersonalActorDeletionReview(handle, review) }.isFailure)
                                assertEquals(witness, documents.personalActorSavedBookState())
                                assertArrayEquals(retainedBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                assertEquals(draft, documents.entwurf.value)
                                assertEquals(incomingDecisions.size + 1, queue.actorDeletionIntents(run).size)
                                assertTrue(sent().isEmpty())
                                assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).none {
                                    it.payload["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) &&
                                        PersonalSyncActor.unwrap(it.payload.getValue("body").jsonObject).first == "personal_sync.deletion_decision"
                                })
                                assertEquals(0, work.personalActorJournal.withActive(handle) { 0 })
                                return@use
                            }
                            if (mixed) assertEquals(if (mode.endsWith("ledger-failure") || denyIncomingAck) "metadata_pending" else "completion",
                                work.commitPersonalActorDeletionReview(handle, mapOf(localProposalId to choice)))
                            val firstPumpStarted = android.os.SystemClock.elapsedRealtime()
                            val first = runCatching { pump.invoke(work, peer, channel, 0L, false) }
                            val firstPumpEnded = android.os.SystemClock.elapsedRealtime()
                            val firstWire = sent().toMutableList()
                            if (mode.endsWith("writer-failure")) {
                                failBookWrites.set(false)
                                assertEquals(witness, documents.personalActorSavedBookState())
                                assertTrue(documents.notiz("phone-note")!!.anhaenge.isEmpty())
                                assertTrue(firstWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) && it.getValue("body").jsonObject["message_id"] in incomingIds })
                                assertEquals(draft, documents.entwurf.value)
                                assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                                return@use
                            }
                            val after = requireNotNull(documents.personalActorSavedBookState())
                            assertEquals(witness.getValue("sequence").jsonPrimitive.long + 1, after.getValue("sequence").jsonPrimitive.long)
                            assertEquals(if (choice == "restore") 33 else 0, documents.notiz("phone-note")!!.anhaenge.size)
                            assertEquals(draft, documents.entwurf.value)
                            var mixedPeerAck: JsonObject? = null
                            var finalWitness = after
                            if (mixed && choice == "delete") {
                                assertTrue(session.contentScopeMessages.isNotEmpty())
                                assertTrue(firstWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) && it.getValue("body").jsonObject["message_id"] in incomingIds })
                                assertTrue(firstWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) &&
                                    PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.deletion_decision" })
                            }
                            if (mixed && mode.endsWith("ledger-failure")) {
                                assertEquals(3, queue.actorDeletionIntents(run).size)
                                assertTrue(firstWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) && it.getValue("body").jsonObject["message_id"] in incomingIds })
                                assertTrue(firstWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) &&
                                    PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.deletion_decision" })
                                database.execSQL("DROP TRIGGER incoming_ledger_failure")
                                pump.invoke(work, peer, channel, 0L, false)
                                firstWire += sent()
                                assertTrue(queue.actorDeletionIntents(run).isEmpty())
                                assertEquals(after, documents.personalActorSavedBookState())
                            }
                            if (mixed && (mode.endsWith("send-failure") || mode.endsWith("metadata-failure"))) {
                                assertTrue(first.isFailure)
                                assertEquals("completion", work.personalActorJournal.completionState(handle))
                                @Suppress("UNCHECKED_CAST")
                                val completion = (field(TelefonWerk::class.java, "personalActorCompletions").get(work) as Map<String, Any>).getValue(run)
                                val guard = field(completion.javaClass, "guard").get(completion) as PersonalActorDecisionCompletion
                                assertEquals(JsonPrimitive(0), guard.summary()["saved"])
                                val fakePeerAck = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                                    PersonalSyncActor.ack(run, incomingDecision.string("message_id")), 60000)
                                work.receiveMessage(peer, fakePeerAck, channel, 0L)
                                assertEquals(JsonPrimitive(0), guard.summary()["saved"])
                                if (mode.endsWith("metadata-failure")) database.execSQL("DROP TRIGGER incoming_metadata_failure")
                                pump.invoke(work, peer, channel, 0L, false)
                                val beforeDue = sent()
                                assertTrue(beforeDue.none { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) && it.getValue("body").jsonObject["message_id"] in incomingIds })
                                firstWire += beforeDue
                                field(completion.javaClass, "nextOwnAckAttempt").setLong(completion, 0)
                                pump.invoke(work, peer, channel, 0L, false)
                                firstWire += sent()
                                assertEquals(JsonPrimitive(2), guard.summary()["saved"])
                                assertEquals("completion", work.personalActorJournal.completionState(handle))
                                assertEquals(after, documents.personalActorSavedBookState())
                            }
                            if (mixed && !denyIncomingAck) {
                                if (session.contentScopeMessages.isNotEmpty()) ackScope()
                                pump.invoke(work, peer, channel, 0L, false)
                                firstWire += sent()
                                val localFrames = firstWire.filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) &&
                                    PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.deletion_decision" }.distinctBy { it.string("message_id") }
                                assertEquals(1, localFrames.size)
                                val localDecisions = PersonalSyncProtokoll.decodeDeletionDecisions(PersonalSyncActor.unwrap(localFrames.single().getValue("body").jsonObject).second)
                                assertEquals(setOf(localProposalId), localDecisions.map { it.proposalId }.toSet())
                                // Own ACKs for received decisions cannot replace
                                // the peer's receipt for our locally made decision.
                                assertEquals("completion", work.personalActorJournal.completionState(handle))
                                mixedPeerAck = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                                    PersonalSyncActor.ack(run, localFrames.single().string("message_id")), 60000)
                                val committedBook = documents.bestand.value
                                work.receiveMessage(peer, mixedPeerAck, channel, 0L)
                                // Terminal data is committed once. The existing
                                // receipt handler separately removes only the
                                // now-acknowledged pending decision metadata.
                                assertEquals(committedBook.copy(personalSync = committedBook.personalSync.copy(
                                    pending_decisions = committedBook.personalSync.pending_decisions.filterNot {
                                        it.decision_id == PersonalSyncActor.unwrap(localFrames.single().getValue("body").jsonObject).second.string("decision_id")
                                    })), documents.bestand.value)
                                finalWitness = requireNotNull(documents.personalActorSavedBookState())
                                assertEquals(after.getValue("sequence").jsonPrimitive.long + 1, finalWitness.getValue("sequence").jsonPrimitive.long)
                                work.receiveMessage(peer, mixedPeerAck, channel, 0L)
                                assertEquals(finalWitness, documents.personalActorSavedBookState())
                                assertEquals(choice == "restore", documents.aufgaben().any { it.id == "phone-task" })
                            }
                            if (denyIncomingAck) {
                                assertEquals("completion", work.personalActorJournal.completionState(handle))
                                assertTrue(firstWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) && it.getValue("body").jsonObject["message_id"] in incomingIds })
                                when (mode.substringAfterLast("deny-")) {
                                    "grants" -> {
                                        val bound = requireNotNull(storage.peers().peer)
                                        storage.savePeer(bound.copy(remote_personal_deletions_sync_granted = false,
                                            remote_grants_revision = bound.remote_grants_revision + 1))
                                    }
                                    "book" -> documents.setzeNotiz(Notiz("other-local-note", "New local edit", "Must not be overwritten"))
                                    "key" -> {
                                        val bound = requireNotNull(storage.peers().peer)
                                        storage.replaceConfirmedPeer(bound, bound.copy(
                                            static_public = TelefonKrypto.b64(ByteArray(32) { 99 }), state = "paired_unverified"))
                                    }
                                    "channel" -> field(TelefonWerk::class.java, "activeChannel").set(work, null)
                                    "instance" -> {
                                        val replacement = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                                        assertEquals(documents.bestand.value, replacement.bestand.value)
                                        assertNotEquals(documents.personalActorSavedBookState()?.get("book_source"), replacement.personalActorSavedBookState()?.get("book_source"))
                                        field(Ablage::class.java, "einzig").set(null, replacement)
                                    }
                                    "restore" -> documents.setzeBaum(documents.baum.value.copy(syncEpoch = "new-incoming-restore-epoch"))
                                    "cancel" -> work.stopPersonalActor(handle)
                                    "epoch" -> {
                                        val replacement = queue.actorJournal(work, Ablage.SCHREIBSPERRE) { id, key ->
                                            work.currentActorSource(id, key, channel, 0L)
                                        }
                                        val retired = replacement.reapInactive { id, oldRun ->
                                            queue.stopCurrentActorRun(id, oldRun)
                                            queue.purgePersonal(PersonalSyncActor.storagePeer(oldRun))
                                        }
                                        assertEquals(listOf(peerId to run), retired)
                                        assertTrue(runCatching { work.personalActorJournal.completionState(handle) }.isFailure)
                                        for (wire in incomingDecisions) work.receiveMessage(peer, wire, channel, 0L)
                                        work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                                            PersonalSyncActor.ack(run, incomingDecision.string("message_id")), 60000), channel, 0L)
                                        assertEquals(after, documents.personalActorSavedBookState())
                                    }
                                    else -> error("Unexpected incoming ACK deny fixture")
                                }
                                val retainedBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                database.execSQL("DROP TRIGGER incoming_ledger_failure")
                                runCatching { pump.invoke(work, peer, channel, 0L, false) }
                                val deniedWire = sent()
                                assertTrue(deniedWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) && it.getValue("body").jsonObject["message_id"] in incomingIds })
                                if (mixed) assertTrue(deniedWire.none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) &&
                                    PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.deletion_decision" })
                                if (mode.endsWith("deny-epoch")) assertTrue(runCatching { work.personalActorJournal.completionState(handle) }.isFailure)
                                else assertNotEquals("completed", work.personalActorJournal.completionState(handle))
                                assertArrayEquals(retainedBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                assertEquals(draft, documents.entwurf.value)
                                if (mode.endsWith("deny-book")) assertEquals("Must not be overwritten", documents.notiz("other-local-note")?.text)
                                assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                                return@use
                            }
                            if (!mixed && (mode.endsWith("ledger-failure") || mode.endsWith("send-failure") || mode.endsWith("metadata-failure"))) {
                                assertEquals("completion", work.personalActorJournal.completionState(handle))
                                @Suppress("UNCHECKED_CAST")
                                val completion = (field(TelefonWerk::class.java, "personalActorCompletions").get(work) as Map<String, Any>).getValue(run)
                                val guard = field(completion.javaClass, "guard").get(completion) as PersonalActorDecisionCompletion
                                assertEquals(JsonPrimitive(0), guard.summary()["saved"])
                                if (mode.endsWith("send-failure") || mode.endsWith("metadata-failure")) {
                                    assertTrue(first.isFailure)
                                    assertEquals(1, field(completion.javaClass, "ownAckAttempts").getInt(completion))
                                    val retryAt = field(completion.javaClass, "nextOwnAckAttempt").getLong(completion)
                                    assertTrue("Native first retry must retain its 1000-ms backoff", retryAt in (firstPumpStarted + 1000)..(firstPumpEnded + 1000))
                                }
                                val peerAck = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND, PersonalSyncActor.ack(run, incomingDecision.string("message_id")), 60000)
                                work.receiveMessage(peer, peerAck, channel, 0L)
                                assertEquals(JsonPrimitive(0), guard.summary()["saved"])
                                if (mode.endsWith("ledger-failure")) database.execSQL("DROP TRIGGER incoming_ledger_failure")
                                if (mode.endsWith("metadata-failure")) database.execSQL("DROP TRIGGER incoming_metadata_failure")
                                // Book/journal I/O above may outlast the real first retry.
                                // Exercise the before-deadline branch explicitly, then the
                                // existing overdue branch below, without a wall-time race.
                                if (mode.endsWith("send-failure") || mode.endsWith("metadata-failure")) {
                                    val heldUntil = android.os.SystemClock.elapsedRealtime() + 30000
                                    field(completion.javaClass, "nextOwnAckAttempt").setLong(completion, heldUntil)
                                    pump.invoke(work, peer, channel, 0L, false)
                                    val beforeRetryWire = sent()
                                    assertEquals(heldUntil, field(completion.javaClass, "nextOwnAckAttempt").getLong(completion))
                                    assertEquals(1, field(completion.javaClass, "ownAckAttempts").getInt(completion))
                                    // The fixture peer must acknowledge unrelated startup
                                    // controls, which may legitimately become due during I/O.
                                    val startupControls = setOf("capabilities.update", "grants.update", "personal_sync.settings",
                                        "personal_sync.time_settings", "personal_sync.custom_settings", "personal_sync.shared_settings")
                                    for (wire in beforeRetryWire) {
                                        assertTrue("Unexpected data/ACK frame before native retry deadline: ${wire["kind"]}", wire.string("kind") in startupControls)
                                        ack(wire.string("message_id"))
                                    }
                                }
                                field(completion.javaClass, "nextOwnAckAttempt").setLong(completion, 0)
                                pump.invoke(work, peer, channel, 0L, false)
                            } else if (!mixed || !mode.endsWith("send-failure") && !mode.endsWith("metadata-failure")) assertTrue(first.isSuccess)
                            val allWire = firstWire + sent()
                            val actualAcks = allWire.filter { it["kind"] == JsonPrimitive(PersonalSyncActor.ACK_KIND) &&
                                it.getValue("body").jsonObject["message_id"] in incomingIds }.toSet()
                            assertEquals(incomingIds, actualAcks.map { it.getValue("body").jsonObject.getValue("message_id") }.toSet())
                            assertTrue(nativeAckLockChecks.get() >= actualAcks.size)
                            assertEquals("completed", work.personalActorJournal.completionState(handle))
                            val controls = if (mixed) {
                                // Receipt cleanup is a new writer observation;
                                // the retired completion must reject a fresh read
                                // against its old saved-book witness. Inspect only
                                // the actual protected SQLite bytes in this test.
                                assertTrue(runCatching { work.personalActorJournal.readCompletionControls(handle) }.isFailure)
                                val persisted = mutableListOf<JsonObject>()
                                database.query("meta", arrayOf("key", "value"), "key GLOB ?",
                                    arrayOf("personal_actor_completion_wire:$peerId:$run:*"), null, null, "key").use { rows ->
                                    while (rows.moveToNext()) {
                                        val id = rows.getString(0)
                                        val sealed = rows.getBlob(1)
                                        val clear = storage.decryptPayload(sealed, "personal_actor_completion_wire", id)
                                        try {
                                            assertFalse(sealed.contentEquals(clear))
                                            persisted += TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
                                        } finally { clear.fill(0) }
                                    }
                                }
                                persisted
                            } else work.personalActorJournal.readCompletionControls(handle)
                            assertEquals(actualAcks + listOfNotNull(mixedPeerAck), controls.toSet())
                            assertEquals(finalWitness, documents.personalActorSavedBookState())
                            assertTrue(queue.actorDeletionIntents(run).isEmpty())
                            assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                            val reopened = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                            assertEquals(draft, reopened.entwurf.value)
                            assertEquals(if (choice == "restore") 33 else 0, reopened.notiz("phone-note")!!.anhaenge.size)
                        }
                        return@use
                    }
                    val snapshotBatches = batches.filter { PersonalSyncActor.unwrap(it.getValue("body").jsonObject).first == "personal_sync.batch" }
                    val batch = if (historicalBoundary) snapshotBatches.first() else snapshotBatches.single()
                    val records = (if (historicalBoundary) snapshotBatches else listOf(batch))
                        .flatMap { PersonalSyncProtokoll.decodeBatch(PersonalSyncActor.unwrap(it.getValue("body").jsonObject).second) }
                    assertEquals(setOf("phone-note") + (if (historicalBoundary) (0..253).map { "boundary-note-$it" }.toSet() else emptySet()), records.filter { it.kind == "note" }.map { it.id }.toSet())
                    assertEquals(setOf("phone-task"), records.filter { it.kind == "task" }.map { it.id }.toSet())
                    ack(batch.string("message_id"))
                    assertEquals(batch, queue.outboxWireMessage(peerId, batch.string("message_id")))
                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                        PersonalSyncActor.ack("55555555-5555-4555-8555-555555555555", batch.string("message_id")), 60000), channel, 0L)
                    assertEquals(batch, queue.outboxWireMessage(peerId, batch.string("message_id")))
                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                        PersonalSyncActor.ack(run, batch.string("message_id")), 60000), channel, 0L)
                    assertNull(queue.outboxWireMessage(peerId, batch.string("message_id"))); assertTrue(sent().isEmpty())
                    if (historicalBoundary) snapshotBatches.drop(1).forEach { remaining ->
                        work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                            PersonalSyncActor.ack(run, remaining.string("message_id")), 60000), channel, 0L)
                    }
                    val old = records.single { it.kind == "note" && it.id == "phone-note" }
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
                        if (mode.startsWith("actor-deletions-origin")) {
                            @Suppress("UNCHECKED_CAST")
                            val handle = requireNotNull((field(TelefonWerk::class.java, "personalActorHandles").get(work) as Map<String, PersonalActorHandle>)[run])
                            val restoredId = if (historicalTask) "removed-task" else "removed-note"
                            val historical = if (historicalSave) {
                                val meta = documents.bestand.value.personalSync.entities.getValue((if (historicalTask) "task" else "note") + "\u0000" + restoredId)
                                proposals(JsonObject(proposal + mapOf("kind" to JsonPrimitive(if (historicalTask) "task" else "note"), "id" to JsonPrimitive(restoredId), "prior_hash" to JsonPrimitive(meta.prior_hash),
                                    "clock" to JsonArray(meta.clock.map { buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } }))))
                            } else proposals(JsonObject(proposal + ("id" to JsonPrimitive("outside-scope"))))
                            val wire = PersonalSyncActor.wireMessage(historical, run)
                            val saved = documents.personalActorSavedBookState()
                            val bytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                            val currentBook = documents.bestand.value
                            if (mode.endsWith("-raw")) {
                                work.personalActorJournal.putWire(handle, wire)
                                assertTrue(runCatching { work.readPersonalActorIncomingTargetFrames(handle) }.isFailure)
                            } else {
                                assertTrue(runCatching { work.readPersonalActorIncomingTargetFrames(handle) }.isFailure)
                                receive(historical)
                                assertEquals(listOf(wire), work.readPersonalActorIncomingTargetFrames(handle))
                                assertTrue(queue.actorDeletionIntents(run).isEmpty())
                                assertTrue(runCatching { work.personalActorJournal.readWire(handle, wire.string("message_id")) }.isFailure)
                                if (historicalSave) {
                                    val beforeScope = checkNotNull(session.localContentScope)
                                    if (historicalBoundary) {
                                        assertEquals(256, session.contentScopeSelection!!.let { it.notes.size + it.tasks.size })
                                        assertEquals(setOf(0), session.contentScopeAccepted)
                                    }
                                    val beforeAuthority = checkNotNull(work.currentActorCompletionAuthority(peerId, peer.static_public, channel, 0L))
                                    val view = work.reviewPersonalActorIncomingTargets(handle)
                                    val target = view.getValue("targets").jsonArray.single().jsonObject
                                    val choices = listOf(buildJsonObject {
                                        put("proposal_id", target.getValue("proposal_id")); put("decision", "restore")
                                        put("expected_clock", target.getValue("clock")); put("confirm_conflict", true)
                                    })
                                    if (mode.contains("-before-")) {
                                        var submitted = choices
                                        when {
                                            mode.endsWith("-book") -> documents.setzeNotiz(requireNotNull(documents.notiz("phone-note")).copy(text = "Synthetic independent change"))
                                            mode.endsWith("-frame") -> { work.receiveMessage(peer, JsonObject(wire + ("expires_ms" to JsonPrimitive(wire.long("expires_ms") - 1))), channel, 0L); assertTrue(sent().isEmpty()) }
                                            mode.endsWith("-clock") -> submitted = listOf(JsonObject(choices.single() + ("expected_clock" to JsonArray(listOf(buildJsonObject { put("actor_id", peerId); put("counter", 999) })))))
                                            mode.endsWith("-intents") -> receive(valid)
                                            mode.endsWith("-instance") -> field(Ablage::class.java, "einzig").set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
                                        }
                                        val active = Ablage.hole(context); val retained = active.bestand.value; val beforeSave = active.personalActorSavedBookState()
                                        val expectedBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                        assertTrue(runCatching { work.commitHistoricalActorTargetReview(handle, view.string("revision"), submitted) }.isFailure)
                                        assertSame(retained, active.bestand.value); assertEquals(beforeSave, active.personalActorSavedBookState())
                                        assertArrayEquals(expectedBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                        assertEquals(beforeScope, session.localContentScope); assertNull(active.notiz("removed-note")); assertTrue(sent().isEmpty())
                                        work.stopPersonalActor(handle)
                                        return@use
                                    }
                                    if (mode.endsWith("-writer-failure")) {
                                        failBookWrites.set(true)
                                        assertTrue(runCatching { work.commitHistoricalActorTargetReview(handle, view.string("revision"), choices) }.isFailure)
                                        failBookWrites.set(false)
                                        assertSame(currentBook, documents.bestand.value); assertEquals(saved, documents.personalActorSavedBookState())
                                        assertArrayEquals(bytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                        assertEquals("cancelled", work.personalActorJournal.completionState(handle))
                                        assertTrue(runCatching { work.commitHistoricalActorTargetReview(handle, view.string("revision"), choices) }.isFailure)
                                        assertNull(documents.notiz("removed-note")); assertTrue(sent().isEmpty())
                                        return@use
                                    }
                                    assertEquals("completion", work.commitHistoricalActorTargetReview(handle, view.string("revision"), choices))
                                    val after = checkNotNull(documents.personalActorSavedBookState())
                                    assertEquals(checkNotNull(saved).getValue("sequence").jsonPrimitive.long + 1, after.getValue("sequence").jsonPrimitive.long)
                                    assertEquals(saved["book_source"], after["book_source"])
                                    if (historicalTask) assertEquals("Synthetic historical task", documents.bestand.value.aufgaben.single { it.id == restoredId }.titel)
                                    else assertEquals("Synthetic historical source", documents.notiz(restoredId)?.text)
                                    assertEquals(beforeScope, session.localContentScope)
                                    assertFalse(JsonPrimitive(restoredId) in beforeScope.getValue("members").jsonObject.getValue(if (historicalTask) "tasks" else "notes").jsonArray)
                                    assertNull(work.currentActorSource(peerId, peer.static_public, channel, 0L))
                                    assertEquals(beforeAuthority, work.currentActorCompletionAuthority(peerId, peer.static_public, channel, 0L))
                                    assertTrue(runCatching { work.personalActorJournal.withActive(handle) {} }.isFailure)
                                    val afterBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                    assertEquals("completion", work.commitHistoricalActorTargetReview(handle, view.string("revision"), choices))
                                    assertEquals(after, documents.personalActorSavedBookState())
                                    assertArrayEquals(afterBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                    val queueScope = TelefonWerk::class.java.getDeclaredMethod("queueContentScope", TelefonPeer::class.java, PersonalNoteSession::class.java).apply { isAccessible = true }
                                    synchronized(work) { synchronized(Ablage.SCHREIBSPERRE) { queueScope.invoke(work, peer, session) } }
                                    assertEquals(beforeScope, session.localContentScope); assertTrue(sent().isEmpty())
                                    pump.invoke(work, peer, channel, 0L, false)
                                    val emitted = sent()
                                    // The real pump also retransmits its six existing
                                    // session controls. No scope/content frame is allowed.
                                    val controlKinds = setOf("capabilities.update", "grants.update", "personal_sync.settings",
                                        "personal_sync.time_settings", "personal_sync.custom_settings", SharedSyncSettings.KIND)
                                    assertTrue(emitted.map { it.string("kind") }.toString(), emitted.all { it.string("kind") in controlKinds || it.string("kind") == PersonalSyncActor.DATA_KIND })
                                    val sentDecision = emitted.filter { it.string("kind") == PersonalSyncActor.DATA_KIND }.single()
                                    assertEquals(PersonalSyncActor.DATA_KIND, sentDecision.string("kind"))
                                    assertEquals("personal_sync.deletion_decision", PersonalSyncActor.unwrap(sentDecision.getValue("body").jsonObject).first)
                                    assertEquals("completion", work.personalActorJournal.completionState(handle))
                                    if (mode.contains("-after-")) {
                                        when {
                                            mode.endsWith("-book") -> documents.setzeNotiz(requireNotNull(documents.notiz("phone-note")).copy(text = "Synthetic independent change"))
                                            mode.endsWith("-grants") -> storage.savePeer(requireNotNull(storage.peers().peer).copy(remote_personal_deletions_sync_granted = false))
                                            mode.endsWith("-instance") -> field(Ablage::class.java, "einzig").set(null, Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") })
                                        }
                                        assertNull(work.currentActorCompletionAuthority(peerId, peer.static_public, channel, 0L))
                                        val active = Ablage.hole(context); val retained = active.bestand.value
                                        val expectedBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                        work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                                            PersonalSyncActor.ack(run, sentDecision.string("message_id")), 60000), channel, 0L)
                                        // Missing consent leaves no fresh terminal authority;
                                        // its ACK is blocked before lifecycle maintenance retires it.
                                        assertNotEquals("completed", work.personalActorJournal.completionState(handle))
                                        assertEquals("pending", active.bestand.value.personalSync.pending_decisions.single { it.proposal_id == target.string("proposal_id") }.state)
                                        assertSame(retained, active.bestand.value); assertArrayEquals(expectedBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                        assertEquals(beforeScope, session.localContentScope); assertTrue(sent().isEmpty())
                                        assertEquals("Synthetic historical source", active.notiz(restoredId)?.text)
                                        work.maintenance()
                                        assertEquals("cancelled", work.personalActorJournal.completionState(handle))
                                        assertTrue((field(TelefonWerk::class.java, "personalActorHistoricalHandoffs").get(work) as Map<*, *>).isEmpty())
                                        return@use
                                    }
                                    work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                                        PersonalSyncActor.ack(run, sentDecision.string("message_id")), 60000), channel, 0L)
                                    assertTrue(sent().isEmpty()); assertEquals("completed", work.personalActorJournal.completionState(handle))
                                    assertEquals(beforeScope, session.localContentScope)
                                    synchronized(work) { synchronized(Ablage.SCHREIBSPERRE) { queueScope.invoke(work, peer, session) } }
                                    assertTrue(JsonPrimitive(restoredId) in checkNotNull(session.localContentScope).getValue("members").jsonObject.getValue(if (historicalTask) "tasks" else "notes").jsonArray)
                                    assertNotEquals(PhoneContentScope.reference(beforeScope), PhoneContentScope.reference(checkNotNull(session.localContentScope)))
                                    if (historicalBoundary) assertEquals(2, session.contentScopeMessages.size)
                                    assertTrue(runCatching { work.personalActorJournal.withActive(handle) {} }.isFailure)
                                    return@use
                                }
                                // Origin is not evidence that this unselected target exists locally.
                                assertTrue(runCatching { work.reviewPersonalActorIncomingTargets(handle) }.isFailure)
                                if (mode.endsWith("-conflict")) {
                                    val changed = JsonObject(wire + ("expires_ms" to JsonPrimitive(wire.long("expires_ms") - 1)))
                                    work.receiveMessage(peer, changed, channel, 0L); assertTrue(sent().isEmpty())
                                    assertTrue(runCatching { work.readPersonalActorIncomingTargetFrames(handle) }.isFailure)
                                }
                                if (mode.endsWith("-grants")) {
                                    storage.savePeer(requireNotNull(storage.peers().peer).copy(remote_personal_deletions_sync_granted = false))
                                    assertTrue(runCatching { work.readPersonalActorIncomingTargetFrames(handle) }.isFailure)
                                }
                            }
                            assertSame(currentBook, documents.bestand.value)
                            assertEquals(saved, documents.personalActorSavedBookState())
                            assertArrayEquals(bytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                            work.stopPersonalActor(handle)
                            assertTrue((field(TelefonWerk::class.java, "personalActorTargetOrigins").get(work) as Map<*, *>).isEmpty())
                            assertTrue(sent().isEmpty())
                            return@use
                        }
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
                        @Suppress("UNCHECKED_CAST")
                        val handle = (field(TelefonWerk::class.java, "personalActorHandles").get(work) as Map<String, PersonalActorHandle>).getValue(run)
                        assertNull(work.actorDataReportReceipt(handle))
                        val proposalId = UUID.randomUUID().toString()
                        val review = mapOf(proposalId to if (mode == "actor-commit-terminal-restore") "restore" else "delete")
                        if (actorTerminal) {
                            val proposals = TelefonNachrichten.message("personal_sync.deletion_proposals", buildJsonObject {
                                put("format", 1); put("run_id", run); put("proposal_batch_id", UUID.randomUUID().toString()); put("sequence", 0); put("last", true)
                                put("proposals", buildJsonArray { add(buildJsonObject {
                                    put("proposal_id", proposalId); put("kind", "note"); put("id", incoming.id); put("parent_id", "")
                                    put("prior_hash", incoming.hash); put("deleted_ms", System.currentTimeMillis()); put("label", "Synthetic review")
                                    put("clock", JsonArray(PersonalSync.merge(incoming.clock, listOf(PersonalSyncClock(peerId, 2))).map {
                                        buildJsonObject { put("actor_id", it.actor_id); put("counter", it.counter) } }))
                                }) })
                            }, 60000)
                            work.receiveMessage(peer, PersonalSyncActor.wireMessage(proposals, run), channel, 0L)
                            assertTrue(sent().isEmpty()); assertEquals(1, queue.actorDeletionIntents(run).size)
                            assertTrue(runCatching { work.commitPersonalActorDeletionReview(handle, review) }.isFailure)
                        }
                        if (mode == "actor-commit-changed") documents.setzeNotiz(documents.notizen().single { it.id == "phone-note" }.copy(text = "Concurrent phone edit"))
                        if (actorAckFailure) {
                            failNextFlush.set(true)
                            assertTrue(runCatching { work.receiveMessage(peer, completionWire, channel, 0L) }.isFailure)
                            // The write may have reached the stream before flush failed:
                            // its outcome is unknown, never a successful receipt.
                            sent()
                            assertTrue(queue.personalDirectionApplied(peerId, run, true))
                            assertNull(work.actorDataReportReceipt(handle))
                            if (actorTerminal) {
                                pump.invoke(work, peer, channel, 0L, false)
                                assertTrue(sent().none { PersonalSyncActor.semanticMessage(it)["kind"] == JsonPrimitive("personal_sync.deletion_decision") })
                                assertNotNull(documents.notiz("phone-note"))
                                assertEquals("active", work.personalActorJournal.completionState(handle))
                            }
                        } else work.receiveMessage(peer, completionWire, channel, 0L)
                        if (mode == "actor-commit-changed") {
                            assertTrue(sent().isEmpty()); assertFalse(queue.personalDirectionApplied(peerId, run, true))
                            assertEquals("Concurrent phone edit", documents.notizen().single { it.id == "phone-note" }.text)
                        } else {
                            if (actorAckFailure) work.receiveMessage(peer, completionWire, channel, 0L)
                            assertEquals(completionWire.string("message_id"), sent().single().getValue("body").jsonObject.string("message_id"))
                            assertTrue(queue.personalDirectionApplied(peerId, run, true))
                            val receipt = requireNotNull(work.actorDataReportReceipt(handle))
                            assertEquals(documents.personalActorSavedBookState(), receipt["saved_book"])
                            assertEquals(completionWire, receipt["report"])
                            assertEquals(completionWire.string("message_id"), receipt.getValue("sent_ack").jsonObject.getValue("body").jsonObject.string("message_id"))
                            assertNull(work.actorDataReportReceipt(PersonalActorHandle(handle.peerId, handle.runId, "0".repeat(64))))
                            assertEquals("Private desktop draft", documents.notizen().single { it.id == "phone-note" }.text)
                            val reopened = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                            assertEquals("Private desktop draft", reopened.notizen().single { it.id == "phone-note" }.text)
                            if (format == 14) assertEquals("notes", reopened.notizen().single { it.id == "phone-note" }.ursprungApp)
                            assertEquals(1, reopened.notizen().single { it.id == "phone-note" }.anhaenge.size)
                            assertTrue(io.gitlab.maik3531.magnolienotes.journal.AndroidJournal.hole(context).state.value.entries.any { it.reason == "pre-sync-note" })
                            val savedBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                            work.receiveMessage(peer, completionWire, channel, 0L); assertEquals(1, sent().size)
                            assertEquals(receipt, work.actorDataReportReceipt(handle))
                            assertArrayEquals(savedBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                            assertTrue(queue.readyPersonalBatches().none { it.first == privatePeer })
                            if (actorTerminal) {
                                documents.setzeNotizEntwurf(requireNotNull(documents.notiz("phone-note")).copy(text = "Unsaved GUI draft must survive"))
                                documents.sichereEntwurf()
                                val retainedDraft = documents.entwurf.value
                                val savedWitness = requireNotNull(documents.personalActorSavedBookState())
                                val beforeDeletionBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                                if (mode == "actor-commit-terminal-ledger") database.execSQL("CREATE TRIGGER actor_terminal_ledger_failure BEFORE UPDATE ON inbox WHEN NEW.state='actor_processed' BEGIN SELECT RAISE(ABORT,'synthetic terminal ledger failure'); END")
                                if (mode == "actor-commit-terminal-write-failure") {
                                    failBookWrites.set(true)
                                    assertTrue(runCatching { work.commitPersonalActorDeletionReview(handle, review) }.isFailure)
                                    failBookWrites.set(false)
                                    assertNotNull(documents.notiz("phone-note"))
                                    assertArrayEquals(beforeDeletionBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                    assertEquals(savedWitness, documents.personalActorSavedBookState())
                                    assertEquals(retainedDraft, documents.entwurf.value)
                                    pump.invoke(work, peer, channel, 0L, false)
                                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                                    assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                                    return@use
                                }
                                val result = if (mode.startsWith("actor-commit-terminal-auto")) {
                                    pump.invoke(work, peer, channel, 0L, false)
                                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                                    work.personalActorJournal.completionState(handle)
                                } else work.commitPersonalActorDeletionReview(handle, review)
                                assertEquals(if (mode == "actor-commit-terminal-ledger") "metadata_pending" else "completion", result)
                                val deletionWitness = requireNotNull(documents.personalActorSavedBookState())
                                assertEquals(savedWitness.getValue("sequence").jsonPrimitive.long + 1, deletionWitness.getValue("sequence").jsonPrimitive.long)
                                assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                                if (mode == "actor-commit-terminal-restore") assertNotNull(documents.notiz("phone-note")) else assertNull(documents.notiz("phone-note"))
                                val queuedDecision = queue.due(peerId, TelefonTransportArt.WIFI).single {
                                    PersonalSyncActor.semanticMessage(it.payload)["kind"] == JsonPrimitive("personal_sync.deletion_decision") }.payload
                                if (mode == "actor-commit-terminal-retire-channel") {
                                    val decisionId = queuedDecision.string("message_id")
                                    val savedAfterDeletion = java.io.File(context.filesDir, "notizen.json").readBytes()
                                    val retire = TelefonWerk::class.java.getDeclaredMethod("retireInvalidPersonalActors")
                                        .apply { isAccessible = true }
                                    fun evidence() = database.rawQuery(
                                        "SELECT key, hex(value) FROM meta WHERE key GLOB ? OR key GLOB ? ORDER BY key",
                                        arrayOf("personal_actor_wire:$peerId:$run:*", "personal_actor_completion_wire:$peerId:$run:*")
                                    ).use { cursor -> buildMap {
                                        while (cursor.moveToNext()) put(cursor.getString(0), cursor.getString(1))
                                    } }
                                    val originalEvidence = evidence()
                                    assertTrue(originalEvidence.isNotEmpty())
                                    retire.invoke(work)
                                    assertEquals("completion", work.personalActorJournal.completionState(handle))
                                    field(TelefonWerk::class.java, "activeChannel").set(work, null)
                                    database.execSQL("CREATE TRIGGER fail_actor_stop BEFORE UPDATE OF next_attempt_ms ON outbox " +
                                        "WHEN NEW.message_id='$decisionId' BEGIN SELECT RAISE(ABORT,'synthetic actor stop failure'); END")
                                    try {
                                        retire.invoke(work)
                                        assertEquals("completion", work.personalActorJournal.completionState(handle))
                                        assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).any { it.messageId == decisionId })
                                    } finally {
                                        database.execSQL("DROP TRIGGER fail_actor_stop")
                                    }
                                    retire.invoke(work)
                                    assertEquals("cancelled", work.personalActorJournal.completionState(handle))
                                    assertTrue(queue.due(peerId, TelefonTransportArt.WIFI).none { it.messageId == decisionId })
                                    assertNotNull(queue.outboxPersonalMessage(peerId, decisionId))
                                    assertEquals(originalEvidence, evidence())
                                    assertEquals(deletionWitness, documents.personalActorSavedBookState())
                                    assertArrayEquals(savedAfterDeletion, java.io.File(context.filesDir, "notizen.json").readBytes())
                                    assertEquals(retainedDraft, documents.entwurf.value)
                                    return@use
                                }
                                val terminalAck = TelefonNachrichten.message(PersonalSyncActor.ACK_KIND,
                                    PersonalSyncActor.ack(run, queuedDecision.string("message_id")), 60000)
                                if (mode.startsWith("actor-commit-terminal-deny-")) {
                                    pump.invoke(work, peer, channel, 0L, false)
                                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                                    ackScope() // Deny even after the exact expected new membership was accepted.
                                    when (mode.substringAfterLast("deny-")) {
                                        "grants" -> {
                                            val bound = requireNotNull(storage.peers().peer)
                                            storage.savePeer(bound.copy(remote_personal_deletions_sync_granted = false,
                                                remote_grants_revision = bound.remote_grants_revision + 1))
                                        }
                                        "book" -> documents.setzeNotiz(Notiz("other-local-note", "New local edit", "Must not be overwritten"))
                                        "key" -> {
                                            val bound = requireNotNull(storage.peers().peer)
                                            storage.replaceConfirmedPeer(bound, bound.copy(
                                                static_public = TelefonKrypto.b64(ByteArray(32) { 99 }), state = "paired_unverified"))
                                        }
                                        "channel" -> field(TelefonWerk::class.java, "activeChannel").set(work, null)
                                        "instance" -> {
                                            val replacement = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                                            assertEquals(documents.bestand.value, replacement.bestand.value)
                                            assertNotEquals(documents.personalActorSavedBookState()?.get("book_source"), replacement.personalActorSavedBookState()?.get("book_source"))
                                            field(Ablage::class.java, "einzig").set(null, replacement)
                                        }
                                        "restore" -> documents.setzeBaum(documents.baum.value.copy(syncEpoch = "new-native-restore-epoch"))
                                        "cancel" -> work.stopPersonalActor(handle)
                                        else -> error("Unexpected terminal deny fixture")
                                    }
                                    work.receiveMessage(peer, terminalAck, channel, 0L)
                                    runCatching { pump.invoke(work, peer, channel, 0L, false) }
                                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                                    assertNotEquals("completed", work.personalActorJournal.completionState(handle))
                                    assertEquals(retainedDraft, documents.entwurf.value)
                                    assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                                    if (mode.endsWith("deny-book")) assertEquals("Must not be overwritten", documents.notiz("other-local-note")?.text)
                                    return@use
                                }
                                if (mode != "actor-commit-terminal-restore") {
                                    work.receiveMessage(peer, terminalAck, channel, 0L)
                                    assertEquals("completion", work.personalActorJournal.completionState(handle))
                                }
                                pump.invoke(work, peer, channel, 0L, false)
                                val firstDispatch = sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                                if (mode != "actor-commit-terminal-restore") assertTrue(firstDispatch.isEmpty())
                                if (session.contentScopeMessages.isNotEmpty()) ackScope()
                                if (mode == "actor-commit-terminal-ledger") {
                                    pump.invoke(work, peer, channel, 0L, false)
                                    assertTrue(sent().none { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) })
                                    assertEquals(1, queue.actorDeletionIntents(run).size)
                                    database.execSQL("DROP TRIGGER actor_terminal_ledger_failure")
                                }
                                assertEquals("completion", work.commitPersonalActorDeletionReview(handle, review))
                                assertEquals(deletionWitness, documents.personalActorSavedBookState())
                                assertTrue(queue.actorDeletionIntents(run).isEmpty())
                                pump.invoke(work, peer, channel, 0L, false)
                                val dispatched = firstDispatch + sent().filter { it["kind"] == JsonPrimitive(PersonalSyncActor.DATA_KIND) }
                                assertEquals(listOf(queuedDecision), dispatched)
                                work.receiveMessage(peer, terminalAck, channel, 0L)
                                assertEquals("completed", work.personalActorJournal.completionState(handle))
                                val afterAckBytes = java.io.File(context.filesDir, "notizen.json").readBytes()
                                work.receiveMessage(peer, terminalAck, channel, 0L)
                                assertArrayEquals(afterAckBytes, java.io.File(context.filesDir, "notizen.json").readBytes())
                                assertTrue(runCatching { work.personalActorJournal.withActive(handle) { 0 } }.isFailure)
                                val afterDelete = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                                if (mode != "actor-commit-terminal-restore") assertNull(afterDelete.notiz("phone-note"))
                                assertEquals(documents.entwurf.value, afterDelete.entwurf.value)
                                assertEquals(retainedDraft, afterDelete.entwurf.value)
                                return@use
                            }
                            if (mode == "actor-commit-receipt-revoked") {
                                val boundPeer = requireNotNull(storage.peers().peer)
                                storage.savePeer(boundPeer.copy(remote_personal_notes_sync_granted = false))
                                assertNull(work.actorDataReportReceipt(handle))
                                storage.savePeer(boundPeer)
                                assertNotNull(work.actorDataReportReceipt(handle))
                                documents.setzeNotiz(documents.notizen().single { it.id == "phone-note" }.copy(text = "Later phone edit"))
                                assertNull(work.actorDataReportReceipt(handle))
                            }
                        }
                        work.receiveMessage(peer, TelefonNachrichten.message(PersonalSyncActor.CANCEL_KIND, PersonalSyncActor.cancel(run), 60000), channel, 0L); sent()
                        assertNull(work.actorDataReportReceipt(handle))
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
                 val old = snapshot.records.single { it.kind == "note" && (!multiConnectionReply || it.id == "phone-note") }
                val value = JsonObject(old.value + mapOf("text" to JsonPrimitive("Organizer addition"), "modified_ms" to JsonPrimitive(old.modifiedMs + 1)))
                val updated = old.copy(value = value, hash = PersonalSync.hash(value), modifiedMs = old.modifiedMs + 1,
                    clock = (old.clock + PersonalSyncClock(peerId, 1)).sortedWith { a, b -> PersonalSync.compareUtf8(a.actor_id, b.actor_id) })
                 val run = UUID.randomUUID().toString()
                 val wifiOverBluetooth = mode == "receive-auto-wifi-bluetooth"
                 val request = buildJsonObject { put("format", format); put("run_id", run); put("trigger", when {
                     connectionAutomation -> PersonalAutoSync.CONNECTION
                     wifiOverBluetooth -> "auto_wifi"
                     else -> "manual"
                 })
                     put("modules", JsonArray(listOf(JsonPrimitive("notes"), JsonPrimitive("tasks")))) }
                 if (connectionAutomation) {
                     sent()
                     field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.BLUETOOTH to pipe)
                     val activeReader = field(TelefonWerk::class.java, "activeChannel")
                     activeReader.set(work, channel)
                     val wrapped = buildJsonObject {
                         put("format", PhoneContentScope.VERSION)
                         put("scope", PhoneContentScope.reference(manifest))
                         put("kind", "personal_sync.request")
                         put("body", request)
                     }
                     // The outer frame bypasses the local encoder only; receive and acknowledgement use the product handler.
                      val requestMessage = TelefonNachrichten.message(PhoneContentScope.DATA_KIND, wrapped, 60000)
                      fun requestAck() = sent().single { it["message_id"] == requestMessage["message_id"] }
                      if (lateAdvertisement) {
                          fun assertWaiting() {
                              work.receiveMessage(peer, requestMessage, channel, 0)
                              val waiting = requestAck()
                              assertEquals("rejected", waiting.string("status"))
                              assertEquals("temporary_failure", waiting.string("error"))
                              assertNull(queue.personalRun(peerId, run))
                              assertFalse(queue.containsScopedRun(peerId, run))
                              assertNull(queue.duplicateResult(peerId, requestMessage.string("message_id")))
                          }
                          fun publish(revision: Long) {
                              val advertisement = queueConnectionAdvertisement(revision)
                              pump.invoke(work, peer, channel, 0L, false)
                              assertEquals(advertisement, sent().single { it["message_id"] == advertisement["message_id"] })
                              assertEquals(revision, session.connectionCapabilityRevision)
                              queue.acknowledge(peerId, advertisement.string("message_id"))
                          }
                          assertNull(session.connectionCapabilityRevision)
                          assertWaiting()
                          publish(peer.capabilities_revision - 1)
                          assertWaiting()
                          publish(peer.capabilities_revision)
                      }
                      if (mode.endsWith("-atomic")) {
                          checkConnectionRequestRollback(queue, peerId, run, requestMessage.string("message_id")) {
                              work.receiveMessage(peer, requestMessage, channel, 0)
                              requestAck()
                          }
                      }
                      work.receiveMessage(peer, requestMessage, channel, 0)
                      val ack = requestAck()
                       if (mode.endsWith("-format") || nonElectedPeer) {
                          assertEquals("rejected", ack.string("status"))
                          assertEquals("not_granted", ack.string("error"))
                           assertNull(queue.personalRun(peerId, run))
                           assertFalse(queue.containsScopedRun(peerId, run))
                           assertNull(queue.duplicateResult(peerId, requestMessage.string("message_id")))
                          return
                      }
                      assertEquals(ack.toString(), "accepted", ack.string("status"))
                     assertEquals(request, queue.personalRun(peerId, run))
                     assertEquals("connection_only", queue.personalRunPolicy(peerId, run))
                      work.receiveMessage(peer, requestMessage, channel, 0)
                      assertEquals("duplicate", requestAck().string("status"))
                      if (mode.endsWith("-second-run") || mode.endsWith("-repackaged")) {
                          checkCompetingConnectionRequest(request, manifest, peerId, queue, mode.endsWith("-repackaged")) { packet ->
                              work.receiveMessage(peer, packet, channel, 0)
                              sent().single { it["message_id"] == packet["message_id"] }
                          }
                          return
                      }

                      val attachmentSave = mode.endsWith("-attachment-save")
                     val attachmentComplete = mode.endsWith("-attachment-complete")
                     val attachmentSend = mode.endsWith("-attachment-send") || attachmentComplete
                     val attachmentReply = mode.endsWith("-attachment-reply") || attachmentSend
                     val attachmentWindow = mode.endsWith("-attachment-window") || attachmentSave || attachmentReply
                     val attachment = if (mode.endsWith("-attachment-request") || attachmentWindow) {
                         val fixture = TelefonKanonisch.json.parseToJsonElement(
                             requireNotNull(javaClass.getResource("/personal-sync-contract.json")).readText()).jsonObject
                         val singleUrl = fixture.getValue("format2").jsonObject.getValue("data_url").jsonPrimitive.content
                         val dataUrl = if (attachmentWindow) {
                             val png = java.io.ByteArrayOutputStream().use { buffer ->
                                 val image = java.awt.image.BufferedImage(1, 1, java.awt.image.BufferedImage.TYPE_INT_RGB)
                                 check(javax.imageio.ImageIO.write(image, "png", buffer))
                                 buffer.toByteArray()
                             }
                             val type = "tEXt".encodeToByteArray()
                             val text = "Comment\u0000".encodeToByteArray() + ByteArray(8 * PersonalSyncProtokoll.CHUNK_RAW) { 'a'.code.toByte() }
                             val crc = java.util.zip.CRC32().apply { update(type); update(text) }
                             val chunk = java.nio.ByteBuffer.allocate(12 + text.size).putInt(text.size).put(type).put(text)
                                 .putInt(crc.value.toInt()).array()
                             val beforeEnd = png.size - 12
                             "data:image/png;base64," + java.util.Base64.getEncoder().encodeToString(
                                 png.copyOfRange(0, beforeEnd) + chunk + png.copyOfRange(beforeEnd, png.size))
                         } else singleUrl
                         requireNotNull(PersonalSync.attachmentDescriptor(Anhang("phone-original", "Original.png", "image", dataUrl)))
                     } else null
                     val remoteRecord = attachment?.let {
                         val content = JsonObject(updated.value + ("attachments" to JsonArray(listOf(it.descriptor))))
                         updated.copy(value = content, hash = PersonalSync.hash(content))
                     } ?: updated
                     val aggregate = PersonalSync.recordsHash(listOf(remoteRecord))
                     val connectionBatch = PersonalSyncProtokoll.batch(run, listOf(remoteRecord), 0, true, false, format, aggregate)
                     val batchMessage = TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
                         PhoneContentScope.wrap("personal_sync.batch", connectionBatch, manifest), 60000)
                     fun batchAck() = sent().single { it["message_id"] == batchMessage["message_id"] }
                     val book = java.io.File(context.filesDir, "notizen.json")
                     fun verifyConnectionAttachmentWindow(original: PersonalSync.AttachmentSnapshot) {
                         val before = book.readBytes()
                         work.receiveMessage(peer, batchMessage, channel, 0)
                         val staged = batchAck()
                         assertEquals(staged.toString(), "accepted", staged.string("status"))
                         assertArrayEquals(before, book.readBytes())
                         assertTrue(queue.readyPersonalBatches().any { it.first == peerId })
                         pump.invoke(work, peer, channel, 0L, false)
                         assertTrue(scoped(sent()).isEmpty())
                         session.contentScopeMessages.keys.toList().also { assertTrue(it.isNotEmpty()) }.forEach { id ->
                             work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"), session,
                                 0L, TelefonTransportArt.BLUETOOTH, channel)
                         }
                         pump.invoke(work, peer, channel, 0L, false)
                         val wanted = scoped(sent()).single()
                         val envelope = wanted.getValue("body").jsonObject
                         val requestBody = envelope.getValue("body").jsonObject
                         assertEquals("personal_sync.attachment_request", envelope.string("kind"))
                         assertEquals(run, requestBody.string("run_id"))
                         assertEquals(aggregate, requestBody.string("records_hash"))
                         assertEquals(JsonPrimitive(false), requestBody["reply"])
                         fun wants(end: Int, start: Int = 0) = JsonArray(listOf(buildJsonObject {
                             put("sha256", original.descriptor.getValue("sha256"))
                             put("ranges", JsonArray(listOf(JsonArray(listOf(JsonPrimitive(start), JsonPrimitive(end))))))
                         }))
                         assertEquals(wants(if (attachmentWindow) 8 else 1), requestBody["wants"])
                         work.handleSessionAck(peer, TelefonNachrichten.ack(wanted.string("message_id"), "accepted", "none"),
                             session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                         assertNotNull("A window ACK is not attachment data", queue.outboxPersonalMessage(peerId, wanted.string("message_id")))
                         assertArrayEquals(before, book.readBytes())
                         assertFalse(queue.personalDirectionApplied(peerId, run, reply = false))
                         if (!attachmentWindow) return
                         val hash = original.descriptor.string("sha256")
                         val width = PersonalSyncProtokoll.CHUNK_RAW
                         val bytes = original.bytes
                         val chunks = (0..8).map { index ->
                             val chunk = buildJsonObject {
                                 put("format", 2); put("run_id", run); put("reply", false)
                                 put("records_hash", aggregate); put("sha256", hash); put("index", index)
                                 put("data", java.util.Base64.getEncoder().encodeToString(
                                     bytes.copyOfRange(index * width, minOf(bytes.size, (index + 1) * width))))
                             }
                             TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap(
                                 "personal_sync.attachment_chunk", chunk, manifest), 60000)
                         }
                         fun chunkAck(reader: TelefonSecureChannel, index: Int): JsonObject {
                             work.receiveMessage(peer, chunks[index], reader, 0)
                             return sent().single { it["message_id"] == chunks[index]["message_id"] }
                         }
                         assertEquals("rejected", chunkAck(channel, 8).string("status"))
                         assertNull(queue.duplicateResult(peerId, chunks[8].string("message_id")))
                         TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 },
                             ByteArray(4) { 12 }, ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { replacement ->
                             bindSyntheticPhoneSession(work, replacement)
                             sessions[replacement] = PersonalNoteSession().apply {
                                 capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                                 sharedSent = shared; sharedReceived = shared
                             }
                             activeReader.set(work, replacement)
                             pump.invoke(work, peer, replacement, 0L, false)
                             sent()
                             assertEquals("rejected", chunkAck(replacement, 0).string("status"))
                             assertNull(queue.duplicateResult(peerId, chunks[0].string("message_id")))
                             sessions.remove(replacement)
                             activeReader.set(work, channel)
                         }
                         val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                         database.execSQL("CREATE TRIGGER connection_chunk_staging_failure BEFORE INSERT ON personal_attachment_chunk " +
                             "WHEN NEW.run_id='$run' BEGIN SELECT RAISE(ABORT,'synthetic encrypted chunk failure'); END")
                         try {
                             val failed = chunkAck(channel, 0)
                             assertEquals("rejected", failed.string("status"))
                             assertEquals("temporary_failure", failed.string("error"))
                             assertNull(queue.duplicateResult(peerId, chunks[0].string("message_id")))
                         } finally { database.execSQL("DROP TRIGGER connection_chunk_staging_failure") }
                         for (index in 0..7) {
                             val ack = chunkAck(channel, index)
                             assertEquals(ack.toString(), "accepted", ack.string("status"))
                         }
                         assertEquals("duplicate", chunkAck(channel, 7).string("status"))
                         assertArrayEquals(before, book.readBytes())
                         pump.invoke(work, peer, channel, 0L, false)
                         val lastWindow = scoped(sent()).single().getValue("body").jsonObject.getValue("body").jsonObject
                         assertEquals(wants(9, 8), lastWindow["wants"])
                         if (attachmentSave) {
                             failBookWrites.set(true)
                             try {
                                 val failed = chunkAck(channel, 8)
                                 assertEquals(failed.toString(), "rejected", failed.string("status"))
                                 assertEquals("temporary_failure", failed.string("error"))
                                 assertArrayEquals(before, book.readBytes())
                                 assertFalse(queue.personalDirectionApplied(peerId, run, reply = false))
                                 pump.invoke(work, peer, channel, 0L, false)
                                 assertTrue("No result may escape before a successful book save", scoped(sent()).isEmpty())
                             } finally { failBookWrites.set(false) }
                         }
                         assertEquals(if (attachmentSave) "duplicate" else "accepted", chunkAck(channel, 8).string("status"))
                         assertTrue(queue.incomingAttachmentComplete(peerId, run, false, aggregate, hash))
                         val verified = java.io.ByteArrayOutputStream()
                         assertTrue(queue.verifyIncomingAttachment(peerId, run, false, aggregate, hash, verified))
                         assertArrayEquals(bytes, verified.toByteArray())
                         if (attachmentSave || attachmentReply) {
                             val reopened = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 19 }, "AES") }
                             val savedNote = requireNotNull(reopened.notiz("phone-note"))
                             val saved = savedNote.anhaenge.single()
                             assertEquals("Organizer addition", savedNote.text)
                             assertEquals("Original.png", saved.name)
                             assertEquals("image", saved.art)
                             assertArrayEquals(bytes, requireNotNull(
                                 io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung.dataUrl(saved.daten)).bytes)
                             assertFalse(before.contentEquals(book.readBytes()))
                             assertTrue(queue.personalDirectionApplied(peerId, run, reply = false))
                             pump.invoke(work, peer, channel, 0L, false)
                             val completion = scoped(sent())
                             val result = completion.single {
                                 it.getValue("body").jsonObject.string("kind") == "personal_sync.attachment_result"
                             }
                             val envelope = result.getValue("body").jsonObject
                             val body = envelope.getValue("body").jsonObject
                             assertEquals("personal_sync.attachment_result", envelope.string("kind"))
                             assertEquals(aggregate, body.string("records_hash"))
                             assertEquals(hash, body.string("sha256"))
                             assertEquals("complete", body.string("state"))
                             assertEquals(JsonPrimitive(false), body["reply"])
                             val savedAttachmentAck = TelefonNachrichten.ack(result.string("message_id"), "accepted", "none")
                             if (!attachmentComplete) {
                                 work.handleSessionAck(peer, savedAttachmentAck, session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                 assertNull(queue.outboxPersonalMessage(peerId, result.string("message_id")))
                             }
                             if (attachmentReply) {
                                 val reply = completion.singleOrNull {
                                     it.getValue("body").jsonObject.string("kind") == "personal_sync.batch"
                                 }
                                 assertNotNull("Saved attachment must be advertised in the protected Reply", reply)
                                 val replyBody = requireNotNull(reply).getValue("body").jsonObject.getValue("body").jsonObject
                                 val note = PersonalSyncProtokoll.decodeBatch(replyBody).single { it.kind == "note" }
                                 val descriptor = (note.value.getValue("attachments") as JsonArray).single().jsonObject
                                 assertEquals(hash, descriptor.string("sha256"))
                                 assertEquals(bytes.size.toLong(), descriptor.long("size"))
                                 assertEquals("Original.png", descriptor.string("name"))
                                 val replyHash = replyBody.string("records_hash")
                                 assertTrue(queue.requestedAttachmentChunks(peerId, run, true, replyHash,
                                     listOf(hash to listOf(listOf(0, 8))), TelefonTransportArt.BLUETOOTH).isEmpty())
                                 database.query("personal_attachment_transfer", arrayOf("transport_policy", "metadata", "complete"),
                                     "peer_id=? AND run_id=? AND direction='outgoing' AND reply=1 AND records_hash=? AND sha256=?",
                                     arrayOf(peerId, run, replyHash, hash), null, null, null).use { rows ->
                                     assertTrue("Original outgoing bytes need an authenticated snapshot", rows.moveToFirst())
                                     assertTrue(rows.getString(0).startsWith("connection_only:"))
                                     assertFalse(rows.isNull(1)); assertEquals(0, rows.getInt(2))
                                 }
                                 fun outgoingWindow(start: Int, end: Int) = TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
                                     PhoneContentScope.wrap("personal_sync.attachment_request", buildJsonObject {
                                         put("format", 2); put("run_id", run); put("reply", true)
                                         put("records_hash", replyHash); put("wants", wants(end, start))
                                     }, manifest), 60000)
                                 fun outgoingWindowAck(message: JsonObject, reader: TelefonSecureChannel = channel): JsonObject {
                                     work.receiveMessage(peer, message, reader, 0)
                                     return sent().single { it["message_id"] == message["message_id"] }
                                 }
                                 val firstWindow = outgoingWindow(0, 8)
                                 if (attachmentSend) {
                                     assertEquals("rejected", outgoingWindowAck(firstWindow).string("status"))
                                     assertNull(queue.duplicateResult(peerId, firstWindow.string("message_id")))
                                 }
                                 work.handleSessionAck(peer, TelefonNachrichten.ack(reply.string("message_id"), "accepted", "none"),
                                     session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                 pump.invoke(work, peer, channel, 0L, false)
                                 assertTrue("Reply ACK alone must not release the report", scoped(sent()).isEmpty())
                                 assertFalse(queue.personalRunMarked(peerId, run, "reported"))
                                 if (attachmentSend) {
                                     assertEquals("rejected", outgoingWindowAck(outgoingWindow(0, 9)).string("status"))
                                     TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 },
                                         ByteArray(4) { 12 }, ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { replacement ->
                                         bindSyntheticPhoneSession(work, replacement)
                                         val replacementSession = PersonalNoteSession().apply {
                                             capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                                             sharedSent = shared; sharedReceived = shared
                                         }
                                         sessions[replacement] = replacementSession
                                         activeReader.set(work, replacement)
                                         pump.invoke(work, peer, replacement, 0L, false); sent()
                                         replacementSession.contentScopeMessages.keys.toList().also { assertTrue(it.isNotEmpty()) }.forEach { id ->
                                             work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"),
                                                 replacementSession, 0L, TelefonTransportArt.BLUETOOTH, replacement)
                                         }
                                         assertEquals("rejected", outgoingWindowAck(firstWindow, replacement).string("status"))
                                         assertNull(queue.duplicateResult(peerId, firstWindow.string("message_id")))
                                         sessions.remove(replacement)
                                         activeReader.set(work, channel)
                                     }
                                     val first = outgoingWindowAck(firstWindow)
                                     assertEquals(first.toString(), "accepted", first.string("status"))
                                     assertEquals("duplicate", outgoingWindowAck(firstWindow).string("status"))
                                     fun readSentChunks() = scoped(sent()).associate { frame ->
                                         val wrapped = frame.getValue("body").jsonObject
                                         assertEquals("personal_sync.attachment_chunk", wrapped.string("kind"))
                                         val chunk = wrapped.getValue("body").jsonObject
                                         assertEquals(hash, chunk.string("sha256"))
                                         assertEquals(replyHash, chunk.string("records_hash"))
                                         assertEquals(JsonPrimitive(true), chunk["reply"])
                                         chunk.long("index").toInt() to (frame.string("message_id") to
                                             java.util.Base64.getDecoder().decode(chunk.string("data")))
                                     }
                                     pump.invoke(work, peer, channel, 0L, false)
                                     val firstChunks = readSentChunks()
                                     assertEquals((0..7).toSet(), firstChunks.keys)
                                     val secondWindow = outgoingWindow(8, 9)
                                     assertEquals("rejected", outgoingWindowAck(secondWindow).string("status"))
                                     firstChunks.values.forEach { (id, _) ->
                                         work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"),
                                             session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                     }
                                     assertEquals("accepted", outgoingWindowAck(secondWindow).string("status"))
                                     pump.invoke(work, peer, channel, 0L, false)
                                     val secondChunks = readSentChunks()
                                     assertEquals(setOf(8), secondChunks.keys)
                                     val received = java.io.ByteArrayOutputStream()
                                     (firstChunks + secondChunks).toSortedMap().values.forEach { (_, chunk) -> received.write(chunk) }
                                     assertArrayEquals(bytes, received.toByteArray())
                                     val savedByPeer = TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
                                         PhoneContentScope.wrap("personal_sync.attachment_result", buildJsonObject {
                                             put("format", 2); put("run_id", run); put("reply", true)
                                             put("records_hash", replyHash); put("sha256", hash)
                                             put("state", "complete"); put("error", "none")
                                         }, manifest), 60000)
                                     if (attachmentComplete) {
                                         assertEquals("rejected", outgoingWindowAck(savedByPeer).string("status"))
                                         assertNull(queue.duplicateResult(peerId, savedByPeer.string("message_id")))
                                     }
                                     work.handleSessionAck(peer, TelefonNachrichten.ack(secondChunks.getValue(8).first, "accepted", "none"),
                                         session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                     pump.invoke(work, peer, channel, 0L, false)
                                     assertTrue("Chunk ACKs alone do not release the report", scoped(sent()).isEmpty())
                                     if (attachmentComplete) {
                                         fun outgoingComplete() = database.query("personal_attachment_transfer", arrayOf("complete"),
                                             "peer_id=? AND run_id=? AND direction='outgoing' AND reply=1 AND records_hash=? AND sha256=?",
                                             arrayOf(peerId, run, replyHash, hash), null, null, null).use {
                                             it.moveToFirst() && it.getInt(0) == 1
                                         }
                                         database.execSQL("CREATE TRIGGER connection_result_receipt_failure BEFORE INSERT ON inbox " +
                                             "WHEN NEW.message_id='${savedByPeer.string("message_id")}' AND NEW.state='accepted' " +
                                             "BEGIN SELECT RAISE(ABORT,'synthetic attachment result receipt failure'); END")
                                         try {
                                             val failed = outgoingWindowAck(savedByPeer)
                                             assertEquals(failed.toString(), "temporary_failure", failed.string("error"))
                                             assertFalse(outgoingComplete())
                                             assertNull(queue.duplicateResult(peerId, savedByPeer.string("message_id")))
                                         } finally { database.execSQL("DROP TRIGGER connection_result_receipt_failure") }
                                         val accepted = outgoingWindowAck(savedByPeer)
                                         assertEquals(accepted.toString(), "accepted", accepted.string("status"))
                                         assertTrue(outgoingComplete())
                                         assertEquals("duplicate", outgoingWindowAck(savedByPeer).string("status"))
                                         pump.invoke(work, peer, channel, 0L, false)
                                         assertTrue("The incoming original result still needs its own ACK", scoped(sent()).isEmpty())
                                         assertNotNull(queue.outboxPersonalMessage(peerId, result.string("message_id")))
                                         work.handleSessionAck(peer, savedAttachmentAck, session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                         pump.invoke(work, peer, channel, 0L, false)
                                         val report = scoped(sent()).single()
                                         val reportEnvelope = report.getValue("body").jsonObject
                                         assertEquals("personal_sync.report", reportEnvelope.string("kind"))
                                         val attachmentCounts = reportEnvelope.getValue("body").jsonObject.getValue("attachments").jsonObject
                                         assertEquals(1L, attachmentCounts.long("sent"))
                                         assertEquals(1L, attachmentCounts.long("received"))
                                         assertEquals(bytes.size.toLong(), attachmentCounts.long("bytes"))
                                         assertFalse(queue.personalRunMarked(peerId, run, "reported"))
                                         work.handleSessionAck(peer, TelefonNachrichten.ack(report.string("message_id"), "accepted", "none"),
                                             session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                         assertTrue(queue.personalRunMarked(peerId, run, "reported"))
                                     }
                                 }
                             }
                         }
                     }
                     if (attachment != null) {
                         verifyConnectionAttachmentWindow(attachment)
                         return@use
                     }
                     if (mode.endsWith("-write-reader")) {
                         val original = book.readBytes()
                         watchBookReplacement.set(true)
                         work.receiveMessage(peer, batchMessage, channel, 0)
                         assertArrayEquals("Lost reader must not replace the book", original, book.readBytes())
                         assertTrue("Original transport must be checked again at the native writer", readerLostAtReplacement.get())
                         assertFalse("A cancelled save left its prepared encrypted book", preparedBook.exists())
                         assertEquals("rejected", batchAck().string("status"))
                         return@use
                     }
                     if (mode.endsWith("-write-retry")) {
                         val original = book.readBytes()
                         assertTrue(preparedBook.mkdir())
                         val failed = try {
                             work.receiveMessage(peer, batchMessage, channel, 0)
                             sent().filter { it["message_id"] == batchMessage["message_id"] }
                         } finally { assertTrue(preparedBook.delete()) }
                         assertArrayEquals(original, book.readBytes())
                         val staged = queue.readyPersonalBatches().single { it.first == peerId }.second
                         val replay = TelefonWerk::class.java.getDeclaredMethod("completePersonalBatch",
                             TelefonPeer::class.java, List::class.java, PersonalNoteSession::class.java).apply { isAccessible = true }
                         replay.invoke(work, peer, staged, PersonalNoteSession())
                         assertArrayEquals("An initializing reader must not replay the saved queue", original, book.readBytes())
                         work.receiveMessage(peer, batchMessage, channel, 0)
                         assertEquals("Organizer addition", documents.notiz("phone-note")!!.text)
                         assertFalse(original.contentEquals(book.readBytes()))
                         assertEquals("duplicate", batchAck().string("status"))
                         assertEquals(listOf("rejected" to "temporary_failure"),
                             failed.map { it.string("status") to it.string("error") })
                         return@use
                     }
                     var connectionReplyIds = emptyList<String>()
                     if (mode.endsWith("-batch") || mode.endsWith("-reply")) {
                         val original = book.readBytes()
                         val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                         fun pendingConnectionReplies(): List<String> = database.query("outbox", arrayOf("message_id"),
                             "peer_id=? AND kind='personal_sync.batch' AND transport_policy GLOB 'connection_only:*'",
                             arrayOf(peerId), null, null, null).use { rows ->
                             buildList { while (rows.moveToNext()) add(rows.getString(0)) }
                         }
                         val savedBeforeRetry = if (mode.endsWith("-outbox-reply")) {
                             database.execSQL("CREATE TRIGGER connection_reply_write_failure BEFORE INSERT ON outbox " +
                                 "WHEN NEW.kind='personal_sync.batch' AND NEW.transport_policy GLOB 'connection_only:*' " +
                                 "BEGIN SELECT RAISE(ABORT,'synthetic connection reply write failure'); END")
                             try {
                                 work.receiveMessage(peer, batchMessage, channel, 0)
                                 val failed = batchAck()
                                 assertEquals("rejected", failed.string("status"))
                                 assertEquals("temporary_failure", failed.string("error"))
                                 assertEquals("Organizer addition", documents.notiz("phone-note")!!.text)
                                 assertFalse(queue.personalRunMarked(peerId, run, "responded"))
                                 assertTrue(pendingConnectionReplies().isEmpty())
                                 book.readBytes().also { assertFalse(original.contentEquals(it)) }
                             } finally { database.execSQL("DROP TRIGGER connection_reply_write_failure") }
                         } else null
                         work.receiveMessage(peer, batchMessage, channel, 0)
                         val stagedAck = batchAck()
                         assertEquals(stagedAck.toString(), if (savedBeforeRetry == null) "accepted" else "duplicate", stagedAck.string("status"))
                         assertEquals("Organizer addition", documents.notiz("phone-note")!!.text)
                         val saved = book.readBytes()
                         if (savedBeforeRetry != null) assertArrayEquals(savedBeforeRetry, saved)
                         assertFalse(original.contentEquals(saved))
                         assertTrue(queue.readyPersonalBatches().any { (owner, messages) ->
                             owner == peerId && messages.any { it["message_id"] == batchMessage["message_id"] }
                         })
                         work.receiveMessage(peer, batchMessage, channel, 0)
                         assertEquals("duplicate", batchAck().string("status"))
                         assertArrayEquals(saved, book.readBytes())
                         if (mode.endsWith("-batch")) return@use
                         fun replyFrames() = scoped(sent()).filter {
                             it.getValue("body").jsonObject.string("kind") == "personal_sync.batch"
                         }
                         pump.invoke(work, peer, channel, 0L, false)
                         assertTrue("Reply must wait for the current scope ACK", replyFrames().isEmpty())
                         session.contentScopeMessages.keys.toList().also { assertTrue(it.isNotEmpty()) }.forEach { id ->
                             work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"), session,
                                 0L, TelefonTransportArt.BLUETOOTH, channel)
                         }
                         val unsentReplies = pendingConnectionReplies()
                         assertEquals(if (multiConnectionReply) 2 else 1, unsentReplies.size)
                         val unsentReplyId = unsentReplies.first()
                         assertEquals(0, queue.attempts(unsentReplyId))
                         work.handleSessionAck(peer, TelefonNachrichten.ack(unsentReplyId, "accepted", "none"), session,
                             0L, TelefonTransportArt.BLUETOOTH, channel)
                         assertEquals(unsentReplies.toSet(), pendingConnectionReplies().toSet())
                         pump.invoke(work, peer, channel, 0L, false)
                         val replies = replyFrames()
                         assertTrue("Saved Batch needs a protected reply on the original reader", replies.isNotEmpty())
                         val bodies = replies.map { it.getValue("body").jsonObject.getValue("body").jsonObject }
                         assertTrue(bodies.all { it.string("run_id") == run && it["reply"] == JsonPrimitive(true) })
                         assertEquals("Organizer addition", bodies.flatMap(PersonalSyncProtokoll::decodeBatch)
                             .single { it.kind == "note" && it.id == "phone-note" }.value.getValue("text").jsonPrimitive.content)
                         connectionReplyIds = replies.map { it.string("message_id") }
                         assertEquals(unsentReplies.toSet(), connectionReplyIds.toSet())
                         connectionReplyIds.forEach { id ->
                             assertNotNull(queue.outboxPersonalMessage(peerId, id))
                             queue.sent(id, 0, System.currentTimeMillis() - 30_000)
                         }
                     }

                     TelefonSecureChannel(pipe.input, pipe.output, ByteArray(32) { 7 }, ByteArray(32) { 11 },
                         ByteArray(4) { 12 }, ByteArray(32) { 13 }, ByteArray(4) { 14 }).use { replacement ->
                         bindSyntheticPhoneSession(work, replacement)
                         sessions[replacement] = PersonalNoteSession().apply {
                             capabilitiesReceived = true; grantsReceived = true; ownSettingsReceived = true
                             sharedSent = shared; sharedReceived = shared
                         }
                         activeReader.set(work, replacement)
                         pump.invoke(work, peer, replacement, 0L, false)
                         assertEquals(manifest, sessions.getValue(replacement).localContentScope)
                         sent()
                         if (connectionReplyIds.isNotEmpty()) {
                             val replacementSession = sessions.getValue(replacement)
                             replacementSession.contentScopeMessages.keys.toList().also { assertTrue(it.isNotEmpty()) }.forEach { control ->
                                 work.handleSessionAck(peer, TelefonNachrichten.ack(control, "accepted", "none"),
                                     replacementSession, 0L, TelefonTransportArt.BLUETOOTH, replacement)
                             }
                             connectionReplyIds.forEach { id ->
                                 work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"),
                                     replacementSession, 0L, TelefonTransportArt.BLUETOOTH, replacement)
                                 assertNotNull(queue.outboxPersonalMessage(peerId, id))
                             }
                             pump.invoke(work, peer, replacement, 0L, false)
                             assertTrue(scoped(sent()).isEmpty())
                         }
                         work.receiveMessage(peer, requestMessage, replacement, 0)
                         assertEquals("rejected", requestAck().string("status"))
                         assertEquals(request, queue.personalRun(peerId, run))
                         if (mode.endsWith("-batch-replaced")) {
                             val before = book.readBytes()
                             work.receiveMessage(peer, batchMessage, replacement, 0)
                             val rejected = batchAck()
                             assertEquals("rejected", rejected.string("status"))
                             assertEquals("not_granted", rejected.string("error"))
                             assertArrayEquals(before, book.readBytes())
                             assertNull(queue.duplicateResult(peerId, batchMessage.string("message_id")))
                         }
                         sessions.remove(replacement)
                         activeReader.set(work, channel)
                     }
                     if (connectionReplyIds.isNotEmpty()) {
                         val id = connectionReplyIds.first()
                         val beforeReport = storage.personalSyncReport()
                         pump.invoke(work, peer, channel, 0L, false)
                         assertEquals(connectionReplyIds.toSet(), scoped(sent()).map { it.string("message_id") }.toSet())
                         assertFalse(queue.personalRunMarked(peerId, run, "reported"))
                         if (mode.endsWith("-terminal-report-reply")) {
                             work.handleSessionAck(peer, TelefonNachrichten.ack(id, "rejected", "not_granted"), session,
                                 0L, TelefonTransportArt.BLUETOOTH, channel)
                             work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"), session,
                                 0L, TelefonTransportArt.BLUETOOTH, channel)
                             pump.invoke(work, peer, channel, 0L, false)
                             assertTrue(scoped(sent()).isEmpty())
                             assertNotNull(queue.outboxPersonalMessage(peerId, id))
                             assertFalse(queue.personalRunMarked(peerId, run, "reported"))
                             assertEquals(beforeReport, storage.personalSyncReport())
                             return@use
                         }
                         connectionReplyIds.drop(1).forEach { other ->
                             work.handleSessionAck(peer, TelefonNachrichten.ack(other, "accepted", "none"), session,
                                 0L, TelefonTransportArt.BLUETOOTH, channel)
                             assertNull(queue.outboxPersonalMessage(peerId, other))
                             pump.invoke(work, peer, channel, 0L, false)
                             assertTrue("A different reply is still outstanding", scoped(sent()).isEmpty())
                         }
                         work.handleSessionAck(peer, TelefonNachrichten.ack(id, "accepted", "none"), session,
                             0L, TelefonTransportArt.BLUETOOTH, channel)
                         assertNull(queue.outboxPersonalMessage(peerId, id))
                         if (mode.endsWith("-report-reply")) {
                             val database = (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).writableDatabase
                             val unsentReport = database.query("outbox", arrayOf("message_id"),
                                 "peer_id=? AND kind='personal_sync.report' AND transport_policy GLOB 'connection_only:*'",
                                 arrayOf(peerId), null, null, null).use { rows ->
                                 assertTrue("Last reply ACK must release the held Notes report", rows.moveToFirst())
                                 rows.getString(0)
                             }
                             val reportAck = TelefonNachrichten.ack(unsentReport, "accepted", "none")
                             assertEquals(0, queue.attempts(unsentReport))
                             work.handleSessionAck(peer, reportAck, session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                             assertNotNull(queue.outboxPersonalMessage(peerId, unsentReport))
                             assertEquals(beforeReport, storage.personalSyncReport())
                             assertFalse(queue.personalRunMarked(peerId, run, "reported"))
                             pump.invoke(work, peer, channel, 0L, false)
                             val report = scoped(sent()).singleOrNull()
                             assertNotNull("Last reply ACK must release the held Notes report", report)
                             val envelope = requireNotNull(report).getValue("body").jsonObject
                             val reportBody = envelope.getValue("body").jsonObject
                             assertEquals("personal_sync.report", envelope.string("kind"))
                             assertEquals(run, reportBody.string("run_id"))
                             assertEquals("auto_connection", reportBody.string("trigger"))
                             assertEquals("bluetooth", reportBody.string("transport"))
                             assertEquals(unsentReport, report.string("message_id"))
                             if (multiConnectionReply) {
                                 assertEquals(33L, reportBody.getValue("sent").jsonObject.long("notes"))
                                 database.execSQL("CREATE TRIGGER connection_report_ack_failure BEFORE UPDATE ON personal_run " +
                                     "WHEN NEW.run_id='$run' AND NEW.reported=1 " +
                                     "BEGIN SELECT RAISE(ABORT,'synthetic report receipt failure'); END")
                                 try {
                                     val failure = runCatching {
                                         work.handleSessionAck(peer, reportAck, session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                                     }.exceptionOrNull()
                                     assertTrue(failure is android.database.sqlite.SQLiteException)
                                     assertFalse(queue.personalRunMarked(peerId, run, "reported"))
                                     assertNotNull(queue.outboxPersonalMessage(peerId, unsentReport))
                                     assertTrue(queue.readyPersonalBatches().any { it.first == peerId })
                                 } finally { database.execSQL("DROP TRIGGER connection_report_ack_failure") }
                             }
                             assertEquals(beforeReport, storage.personalSyncReport())
                             work.handleSessionAck(peer, reportAck, session, 0L, TelefonTransportArt.BLUETOOTH, channel)
                             assertTrue(queue.personalRunMarked(peerId, run, "reported"))
                             assertNull(queue.outboxPersonalMessage(peerId, report.string("message_id")))
                             assertEquals(context.getString(io.gitlab.maik3531.magnolienotes.R.string.personal_sync_vollstaendig),
                                 storage.personalSyncReport())
                             assertTrue(queue.readyPersonalBatches().none { it.first == peerId })
                         }
                     }
                     return@use
                 }
                 val requestMessage = TelefonNachrichten.message(PhoneContentScope.DATA_KIND, PhoneContentScope.wrap("personal_sync.request", request, manifest), 60000)
                 if (wifiOverBluetooth) {
                     sent()
                     field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.BLUETOOTH to pipe)
                     work.receiveMessage(peer, requestMessage, channel, 0)
                     val ack = sent().single { it["message_id"] == requestMessage["message_id"] }
                     assertEquals("rejected", ack.string("status"))
                     assertNull(queue.personalRun(peerId, run))
                     assertFalse(queue.containsScopedRun(peerId, run))
                     assertFalse(queue.hasActiveAutoRun(peerId))
                     field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
                     val retry = TelefonNachrichten.message(PhoneContentScope.DATA_KIND,
                         PhoneContentScope.wrap("personal_sync.request", request, manifest), 60000)
                     work.receiveMessage(peer, retry, channel, 0)
                     assertEquals("accepted", sent().single { it["message_id"] == retry["message_id"] }.string("status"))
                     assertEquals(request, queue.personalRun(peerId, run))
                     assertEquals("wifi_only", queue.personalRunPolicy(peerId, run))
                     return@use
                 }
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
            journalInstance.set(null, priorJournal)
            Security.removeProvider(provider.name)
        }
    }
}
