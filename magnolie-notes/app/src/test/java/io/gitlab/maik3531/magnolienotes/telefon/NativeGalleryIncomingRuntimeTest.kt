package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.os.Looper
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class NativeGalleryIncomingRuntimeTest {
    @Before fun mountedVolume() { GalleryIncomingRowsTest().mountedPrimaryVolume() }

    @Test fun actualRuntimeRejectsUnknownDefaultInventoryBeforeAcceptanceChunksOrProviderMutation() {
        Harness(collectionMode = "phone_inventory").use { h ->
            val run = h.start()
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.actualSavedOutput())
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.writeOpens); assertEquals(0, h.provider.publishes)
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) ||
                it["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST) })
        }
    }
    @Test fun queuedIncomingRunCannotAdoptALaterPositivelyAcknowledgedRemoteSessionBeforeOwnerCapture() {
        Harness().use { h ->
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val original = h.operationBinding(); val before = h.f.rows()
            h.incomingHook = {
                if (Thread.currentThread().name == "magnolie-media-incoming") {
                    entered.countDown(); assertTrue(release.await(5, TimeUnit.SECONDS))
                }
            }
            val run = h.start()
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS)); h.rotatePcSession()
                assertEquals(original.binding, h.operationBinding().binding); assertNotEquals(original.session, h.operationBinding().session)
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.actualSavedOutput()); assertNotNull(run.nativeFailure())
            assertEquals(before, h.f.rows()); assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.writeOpens); assertEquals(0, h.provider.publishes)
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) })
            h.incomingHook = {}
            val fresh = h.start(); assertTrue(fresh.awaitIoEnded(5000)); assertNull(fresh.nativeFailure()); assertNotNull(fresh.actualSavedOutput())
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun completedIncomingReadbackCannotCaptureALaterRemoteSessionAsReplacementForItsOriginalOperation() {
        Harness().use { h ->
            val run = h.start(); assertTrue(run.awaitIoEnded(5000)); assertNull(run.nativeFailure()); assertNotNull(run.actualSavedOutput())
            val original = h.operationBinding(); val reads = h.provider.readOpens; val before = h.f.rows()
            h.rotatePcSession(); assertEquals(original.binding, h.operationBinding().binding)
            val attempt = h.f.io { runCatching { run.beginPublishedReadback().also { h.inspection = it } } }
            attempt.getOrNull()?.let { assertTrue(it.awaitIoEnded(5000)) }
            assertTrue("A late remote ACK replaced the admitted receive operation's control session.", attempt.exceptionOrNull() is PhotoFolderScopeError)
            assertEquals(reads, h.provider.readOpens); assertEquals(before, h.f.rows())
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DevicePublishedReadbackEnvelope.KIND) })
        }
    }

    @Test fun queuedOrdinaryIncomingRunCannotAdoptALaterFullIncomingIntentBeforeOwnerCapture() {
        Harness().use { h ->
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val before = h.f.rows()
            h.incomingHook = {
                if (Thread.currentThread().name == "magnolie-media-incoming") {
                    entered.countDown(); assertTrue(release.await(5, TimeUnit.SECONDS))
                }
            }
            val run = h.start()
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                h.incomingToken = MediaSyncTransport.IntentToken(MediaSyncSettings.change(h.token.body,
                    "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "auto_mode", JsonPrimitive("wifi")))
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.actualSavedOutput()); assertNotNull(run.nativeFailure())
            assertEquals(before, h.f.rows()); assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.writeOpens)
            h.incomingHook = {}
            val fresh = h.start(); assertTrue(fresh.awaitIoEnded(5000)); assertNull(fresh.nativeFailure()); assertNotNull(fresh.actualSavedOutput())
        }
    }

    @Test fun completedReadbackWorkerCannotRecaptureAnotherSessionAfterItsOriginalAdmissionCheck() {
        Harness().use { h ->
            val incoming = h.start(); assertTrue(incoming.awaitIoEnded(5000)); assertNull(incoming.nativeFailure())
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val reads = h.provider.readOpens; val before = h.f.rows()
            h.incomingHook = {
                if (Thread.currentThread().name == "magnolie-media-published-read") {
                    entered.countDown(); assertTrue(release.await(5, TimeUnit.SECONDS))
                }
            }
            val read = h.f.io { incoming.beginPublishedReadback().also { h.inspection = it } }
            try { assertTrue(entered.await(5, TimeUnit.SECONDS)); h.rotatePcSession() }
            finally { release.countDown() }
            assertTrue(read.awaitIoEnded(5000)); assertNotNull(read.nativeFailure()); assertNull(read.actualReadbackOutput())
            assertEquals(reads, h.provider.readOpens); assertEquals(before, h.f.rows())
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DevicePublishedReadbackEnvelope.KIND) })
            h.incomingHook = {}
            val fresh = h.inspect(); assertTrue(fresh.awaitIoEnded(5000)); assertNull(fresh.nativeFailure()); assertNotNull(fresh.observation())
            assertEquals(before, h.f.rows())
        }
    }

    private class Harness(joined: Boolean = true, localConsent: Boolean = joined,
        collectionMode: String = "entire_collection") : AutoCloseable {
        val helper = NativeGalleryIncomingTransferTest()
        val link = NativeGalleryIncomingTransferTest.Link()
        val f = GalleryReceiveConsentTest.Fixture(link.channel)
        val raw = helper.png()
        val manifest = helper.manifest(f.pc.deviceId, raw)
        val token = helper.intent(collectionMode)
        val file = File(f.root, "runtime-native.png")
        val provider = GalleryIncomingRowsTest.Provider(f.app, payload = file).apply { allowPublish = true }
        val identity = NativeFileControlIdentity("phone_fixture_0001", "a".repeat(64))
        private val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, "f".repeat(64))
        private var pcLocal = NativeLocalFileGrant(DeviceFileGrantState(3, "d".repeat(64), true, true), Any(), true)
        private val pc = NativeFileControlSession(f.pc, { pcPeer }, { pcLocal })
        val runtime: NativeGalleryFileRuntime
        var respond = true
        val requested = CountDownLatch(1)
        var held: JsonObject? = null
        var run: NativeGalleryIncomingRun? = null
        var inspection: NativeGalleryPublishedReadRun? = null
        var incomingAgreement = true
        @Volatile var incomingHook: () -> Unit = {}
        @Volatile var incomingToken: Any? = token
        private var connection: NativeGalleryFileConnection? = null
        init {
            if (joined && localConsent) helper.grant(f)
            ShadowContentResolver.registerProviderInternal("media", provider)
            runtime = if (joined) NativeGalleryFileRuntime.withIncomingMedia(f.app, f.indexRoot, identity, f.protection, link.channel,
                { f.peer }, { true }, { true }, { token }, { incomingHook(); incomingToken }, { true })
            else NativeGalleryFileRuntime.withSharedMediaIntent(f.app, f.indexRoot, identity, f.protection, link.channel,
                { f.peer }, { true }, { true }, { token })
            link.onMessage = { message ->
                when (message.string("kind")) {
                    DeviceFileControl.KIND -> pc.observeRemote(DeviceFileControlEnvelope.validate(message), pcPeer)
                    DeviceFileChunkEnvelope.REQUEST -> if (respond) answer(message) else { held = message; requested.countDown() }
                }
            }
            handshake()
        }
        fun handshake() {
            sendPc(); runtime.sendControls()
            if (pc.needsPacket()) sendPc()
            runtime.sendControls()
        }
        fun positive(kind: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryReceiveConsent {
            val configurer = f.io { runtime.beginReceiveConfiguration() }
            val result = java.util.concurrent.atomic.AtomicReference<Result<NativeGalleryReceiveConsent>?>()
            NativeGalleryReceiveConsent.request(f.activity, "Native own PC", kind, configurer, f.book()) { result.set(it) }
            org.robolectric.shadows.ShadowAlertDialog.getLatestAlertDialog().getButton(android.content.DialogInterface.BUTTON_POSITIVE).performClick()
            Shadows.shadowOf(Looper.getMainLooper()).idle()
            return result.get()!!.getOrThrow()
        }
        fun sendPc() {
            val packet = pc.packet()
            runtime.observeControls(link.receive(DeviceFileControlEnvelope.create(packet)))
            pc.markSent(packet)
        }
        fun withdrawPcSend() {
            pcLocal = NativeLocalFileGrant(DeviceFileGrantState(4, "c".repeat(64), false, true), pcLocal.owner, true)
            sendPc()
        }
        fun operationBinding(): NativeFileOperationBinding {
            val channel = NativeGalleryFileRuntime::class.java.getDeclaredField("controls").apply { isAccessible = true }.get(runtime) as NativeFileControlChannel
            return channel.session.operationBinding(manifest.fingerprint)!!
        }
        fun rotatePcSession() {
            val own = DeviceFileControlEnvelope.validate(link.frames.last { it["kind"] == JsonPrimitive(DeviceFileControl.KIND) })
            val packet = pc.packet().copy(sessionEpoch = "a".repeat(64), sequence = 1, echo = own.challenge)
            assertTrue(runtime.observeControls(link.receive(DeviceFileControlEnvelope.create(packet))))
            runtime.sendControls()
        }
        fun answer(message: JsonObject) {
            val request = DeviceFileChunkEnvelope.parseRequest(message); val offset = request.chunkIndex * 65536
            val response = DeviceFileChunkEnvelope.response(request, raw.copyOfRange(offset, minOf(raw.size, offset + 65536)))
            val current = connection
            if (current == null) assertTrue(runtime.observeIncomingChunk(link.channel, link.receive(response)))
            else assertNull(current.receiveIncomingMedia(link.channel, link.receive(response)) { error("Chunk dispatcher must not capture a new book") })
        }
        fun start(): NativeGalleryIncomingRun = runtime.beginIncoming(DeviceFileOfferEnvelope.create(manifest), GalleryMediaType.IMAGES,
            mapOf("1".repeat(32) to "image/png"), f.book()).also { run = it }
        fun mediaOffer(settings: JsonObject = token.body): JsonObject {
            val offer = DeviceFileOfferEnvelope.create(manifest)
            return JsonObject(offer + mapOf("kind" to JsonPrimitive(MediaOfferEnvelope.KIND), "body" to buildJsonObject {
                put("format", 1); put("offer", offer.getValue("body")); put("settings", settings); put("media_type", "images")
                put("mime_types", buildJsonObject { put("1".repeat(32), "image/png") }); put("originals", buildJsonObject {})
            }))
        }
        fun startMedia(offer: JsonObject = mediaOffer()) = runtime.beginIncomingMediaOffer(link.receive(offer), f.book()).also { run = it }
        fun pcOffer(selected: DeviceFileManifest = manifest, origin: String = "a".repeat(64), previous: String? = null): JsonObject {
            val offer = DeviceFileOfferEnvelope.create(selected)
            return JsonObject(offer + mapOf("kind" to JsonPrimitive(MediaOfferEnvelope.KIND), "body" to buildJsonObject {
                put("format", 2); put("offer", offer.getValue("body")); put("settings", token.body); put("media_type", "images")
                put("mime_types", buildJsonObject { put("1".repeat(32), "image/png") }); put("originals", buildJsonObject {})
                put("pc_origins", buildJsonObject { put("1".repeat(32), buildJsonObject {
                    put("format", 1); put("origin_sha256", origin); put("previous_publication_sha256", previous?.let(::JsonPrimitive) ?: JsonNull)
                }) })
            }))
        }
        fun forkManifest(): DeviceFileManifest {
            val raw = DeviceFileOfferEnvelope.create(manifest).getValue("body").jsonObject.getValue("manifest").jsonObject
            return DeviceFileManifest.parse(JsonObject(raw + mapOf("source_id" to JsonPrimitive(java.util.UUID.randomUUID().toString().replace("-", "")),
                "transfer_id" to JsonPrimitive(java.util.UUID.randomUUID().toString().replace("-", "")))))
        }
        fun nativeConnection(): NativeGalleryFileConnection = connection ?: NativeGalleryFileConnection(link.channel, requireIncomingAgreement = {
            check(Looper.myLooper() != Looper.getMainLooper())
            if (!incomingAgreement) DeviceFileControl.fail("gallery_incoming_current_intent_required")
        }) { }.also {
            it.bind(runtime); connection = it
        }
        fun startDispatched(offer: JsonObject = mediaOffer()) = checkNotNull(nativeConnection().receiveIncomingMedia(link.channel, link.receive(offer), f::book)).also { run = it }
        fun published(): GalleryIncomingPublication {
            val id = f.rows().keys.single { it.startsWith(GalleryIncomingPublication.PREFIX) }.removePrefix(GalleryIncomingPublication.PREFIX)
            return f.index.incomingPublication(id)!!
        }
        fun inspect(selected: GalleryIncomingPublication = published()) = runtime.beginPublishedInspection(selected.id, selected.fingerprint,
            f.book()).also { inspection = it }
        fun readbackOffer() = link.receive(DeviceFileOfferEnvelope.create(manifest))
        fun readback(selected: GalleryIncomingPublication = published(), offer: JsonObject = readbackOffer()) =
            runtime.beginPublishedReadback(link.channel, offer, selected.id, selected.fingerprint, f.book()).also { inspection = it }
        fun readbackBinding(token: String) = pc.binding(token, senderIsLocal = true)!!
        override fun close() {
            runtime.revokeControl()
            run?.let { check(it.awaitIoEnded(10000)) }
            run?.takeIf { it.automaticReadbackRequested }?.let {
                check(it.awaitAutomaticReadbackStart(5000))
                runCatching { it.automaticReadbackRun() }.getOrNull()?.let { read -> check(read.awaitIoEnded(10000)) }
            }
            inspection?.let { check(it.awaitIoEnded(10000)) }
            connection?.close(); runtime.close(); pc.close(); f.close(); link.close()
            Shadows.shadowOf(Looper.getMainLooper()).idle()
        }
    }

    @Test fun mediaOfferWrapperUsesActualEncryptedNativeIncomingAndPreservesOfferIdThroughSaved() {
        Harness().use { h ->
            val offer = h.mediaOffer(); val run = h.startMedia(offer)
            assertTrue(run.awaitIoEnded(10000)); assertNull(run.nativeFailure()); assertNotNull(run.actualSavedOutput())
            val acceptance = h.link.frames.single { it["kind"] == JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) }
            assertEquals(offer["message_id"], acceptance.getValue("body").jsonObject["offer_id"])
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes)
            assertTrue(h.link.frames.any { it["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST) })
            assertEquals(JsonPrimitive(DeviceFileSavedEnvelope.KIND), run.actualSavedOutput()!!["kind"])
        }
    }

    @Test fun opaquePcOriginPublishesOnceAndForkedOrPredecessorVersionsCannotCreateAnotherGalleryRow() {
        Harness().use { h ->
            val first = h.startMedia(h.pcOffer())
            assertTrue(first.awaitIoEnded(10000)); assertNull(first.nativeFailure()); assertNotNull(first.actualSavedOutput())
            val selected = h.published()
            assertEquals(JsonPrimitive(3), selected.body["format"]); assertEquals("a".repeat(64), selected.pcOrigin!!.origin)
            assertNull(selected.pcOrigin!!.previousPublication); assertNull(selected.knownOriginalId)
            assertEquals(selected.fingerprint, first.actualSavedOutput()!!.getValue("body").jsonObject.getValue("receipts").jsonArray.single().jsonObject.string("receipt_sha256"))
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes); assertArrayEquals(h.raw, h.file.readBytes())
            val rows = h.f.rows(); val reads = h.provider.readOpens; val frames = h.link.frames.size
            for (previous in listOf(null, "b".repeat(64), selected.fingerprint)) {
                val next = h.startMedia(h.pcOffer(h.forkManifest(), previous = previous))
                assertTrue(next.awaitIoEnded(10000)); assertNotNull(next.nativeFailure()); assertNull(next.actualSavedOutput())
                assertEquals(rows, h.f.rows()); assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes)
                assertEquals(reads, h.provider.readOpens); assertArrayEquals(h.raw, h.file.readBytes())
            }
            val wrongOrigin = h.startMedia(h.pcOffer(h.forkManifest(), "c".repeat(64), selected.fingerprint))
            assertTrue(wrongOrigin.awaitIoEnded(10000)); assertNotNull(wrongOrigin.nativeFailure())
            assertEquals(rows, h.f.rows()); assertEquals(1, h.provider.inserts)
            assertTrue(h.link.frames.drop(frames).none { it["kind"] == JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) ||
                it["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST) || it["kind"] == JsonPrimitive(DeviceFileSavedEnvelope.KIND) })
        }
    }

    @Test fun pendingPcOriginIsRetainedAndNewTransferIdsCannotBypassItsJournalReservation() {
        Harness().use { h ->
            h.respond = false
            val first = h.startMedia(h.pcOffer()); assertTrue(h.requested.await(5, TimeUnit.SECONDS))
            first.cancel(); assertTrue(first.awaitIoEnded(10000)); assertNull(first.actualSavedOutput())
            val rows = h.f.rows(); val pending = h.published()
            assertNotEquals("published", pending.state); assertEquals("a".repeat(64), pending.pcOrigin!!.origin)
            val inserts = h.provider.inserts; val opens = h.provider.writeOpens
            val next = h.startMedia(h.pcOffer(h.forkManifest()))
            assertTrue(next.awaitIoEnded(10000)); assertNotNull(next.nativeFailure()); assertNull(next.actualSavedOutput())
            assertEquals(rows, h.f.rows()); assertEquals(inserts, h.provider.inserts); assertEquals(opens, h.provider.writeOpens)
            assertEquals(0, h.provider.publishes)
        }
    }

    @Test fun nativeConnectionDispatcherRoutesMediaOfferAndEncryptedChunksToExactNativeWorker() {
        Harness().use { h ->
            val offer = h.mediaOffer(); val run = h.startDispatched(offer)
            assertTrue(run.awaitIoEnded(10000)); assertNull(run.nativeFailure()); assertNotNull(run.actualSavedOutput())
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes)
            val acceptance = h.link.frames.single { it["kind"] == JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) }
            assertEquals(offer["message_id"], acceptance.getValue("body").jsonObject["offer_id"])
            assertTrue(run.awaitAutomaticReadbackStart(5000))
            val read = run.automaticReadbackRun()!!; assertTrue(read.awaitIoEnded(10000)); assertNull(read.nativeFailure())
            assertEquals(offer["message_id"], read.actualReadbackOutput()!!.getValue("body").jsonObject["offer_id"])
        }
    }

    @Test fun completedIncomingOwnerReadbackKeepsOriginalOfferPublicationAndChannelWithoutCallerMetadata() {
        Harness().use { h ->
            val offer = h.mediaOffer(); val run = h.startMedia(offer)
            assertTrue(run.awaitIoEnded(10000)); assertNull(run.nativeFailure())
            val read = h.f.io { run.beginPublishedReadback() }.also { h.inspection = it }
            assertTrue(read.awaitIoEnded(10000)); assertNull(read.nativeFailure())
            val output = read.actualReadbackOutput()!!; val body = output.getValue("body").jsonObject
            assertEquals(offer["message_id"], body["offer_id"])
            assertEquals(JsonPrimitive(h.published().fingerprint), body["publication_sha256"])
            val binding = h.readbackBinding(body.string("destination_token"))
            val ordinaryOffer = MediaOfferEnvelope.validate(offer, h.f.pc.deviceId, h.identity.deviceId).offer
            val parsed = DevicePublishedReadbackEnvelope.parse(output, ordinaryOffer, binding, GalleryMediaType.IMAGES)
            assertFalse(parsed.grantsWriteAuthority); assertFalse(parsed.isSavedReceipt); assertFalse(parsed.allowsChunkOutput)
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes)
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { run.beginPublishedReadback() } }
        }
    }

    @Test fun pendingCanceledOrMetadataOnlyIncomingCannotStartCompletedReadback() {
        Harness().use { h ->
            h.respond = false
            val run = h.startDispatched(); assertTrue(h.requested.await(5, TimeUnit.SECONDS))
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { run.beginPublishedReadback() } }
            run.cancel(); assertTrue(run.awaitIoEnded(10000))
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { run.beginPublishedReadback() } }
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DevicePublishedReadbackEnvelope.KIND) })
        }
        val metadataOnly = NativeGalleryIncomingRun(Any())
        metadataOnly.finish(buildJsonObject { put("kind", DeviceFileSavedEnvelope.KIND) }, null)
        metadataOnly.markIoEnded(); metadataOnly.ioDrained()
        assertThrows(PhotoFolderScopeError::class.java) { metadataOnly.beginPublishedReadback() }
    }

    @Test fun completedIncomingReadbackCannotReplaceOriginalBookOrRevokedControlOwner() {
        for (withdrawBook in listOf(false, true)) Harness().use { h ->
            val run = h.startMedia(); assertTrue(run.awaitIoEnded(10000)); assertNull(run.nativeFailure())
            if (withdrawBook) h.f.currentDocuments = null else h.withdrawPcSend()
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { run.beginPublishedReadback() } }
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DevicePublishedReadbackEnvelope.KIND) })
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun automaticReadbackRechecksNativeAgreementAfterSavedWithoutChangingThePublishedFile() {
        Harness().use { h ->
            val observe = h.link.onMessage
            h.link.onMessage = { message ->
                observe(message)
                if (message.string("kind") == DeviceFileSavedEnvelope.KIND) h.incomingAgreement = false
            }
            val run = h.startDispatched(); assertTrue(run.awaitIoEnded(10000)); assertNotNull(run.actualSavedOutput())
            assertTrue(run.awaitAutomaticReadbackStart(5000))
            assertThrows(PhotoFolderScopeError::class.java) { run.automaticReadbackRun() }
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DevicePublishedReadbackEnvelope.KIND) })
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun automaticReadbackCancellationRetainsTheActualBlockedOutputOwnerUntilDrain() {
        Harness().use { h ->
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val observe = h.link.onMessage
            h.link.onMessage = { message ->
                observe(message)
                if (message.string("kind") == DevicePublishedReadbackEnvelope.KIND) { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            }
            val run = h.startDispatched()
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS)); assertTrue(run.awaitAutomaticReadbackStart(5000))
                val read = run.automaticReadbackRun()!!
                run.cancel(); assertTrue(read.cancelRequested); assertFalse(read.ioEnded)
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
            } finally { release.countDown() }
            val read = run.automaticReadbackRun()!!; assertTrue(read.awaitIoEnded(5000)); assertNull(read.actualReadbackOutput())
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.publishes); assertArrayEquals(h.raw, h.file.readBytes())
        }
    }

    @Test fun nativeIncomingDispatcherCannotCreateRightsFromForeignConnectionOrdinaryOfferOrSourceOnlyFactory() {
        Harness().use { h ->
            NativeGalleryIncomingTransferTest.Link().use { foreign ->
                assertThrows(PhotoFolderScopeError::class.java) {
                    h.nativeConnection().receiveIncomingMedia(foreign.channel, h.mediaOffer()) { error("Foreign channel reached native book capture") }
                }
            }
            assertThrows(PhotoFolderScopeError::class.java) {
                h.nativeConnection().receiveIncomingMedia(h.link.channel, DeviceFileOfferEnvelope.create(h.manifest)) { error("Ordinary offer reached media receiving") }
            }
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.writeOpens)
        }
        Harness(joined = false).use { h ->
            assertThrows(PhotoFolderScopeError::class.java) { h.startDispatched() }
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.publishes)
        }
    }

    @Test fun mediaOfferWrapperCannotSubstituteCurrentIntentInventoryProofOrNativeReceivingConsent() {
        Harness().use { h ->
            val changed = MediaSyncSettings.change(h.token.body, "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
                "photos_only", JsonPrimitive(true))
            assertThrows(PhotoFolderScopeError::class.java) { h.startMedia(h.mediaOffer(changed)) }
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.writeOpens)
        }
        Harness(collectionMode = "phone_inventory").use { h ->
            assertThrows(PhotoFolderScopeError::class.java) { h.startMedia() }
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.writeOpens)
        }
        Harness(localConsent = false).use { h ->
            val run = h.startMedia(); assertTrue(run.awaitIoEnded(5000)); assertNull(run.actualSavedOutput())
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.publishes)
            assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DeviceFileAcceptanceEnvelope.KIND) })
        }
    }

    @Test fun actualRuntimeInspectsPublishedOriginalAfterFreshReceiveBindingWithoutSavedOrJournalMutation() {
        Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published()
            h.f.io { h.runtime.revokeReceiving(h.runtime.savedPolicy(), GalleryMediaType.IMAGES, h.f.book()) }; h.handshake()
            val consent = h.positive()
            h.f.io { h.runtime.grantReceiving(h.runtime.savedPolicy(), consent) }; h.handshake()
            val before = h.f.rows(); val frames = h.link.frames.toList()
            val run = h.inspect(selected)
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.nativeFailure())
            val result = run.observation()!!
            assertNull(run.actualReadbackOutput())
            assertEquals("image/png", result.mimeType); assertFalse(result.grantsWriteAuthority); assertFalse(result.isSavedReceipt)
            assertEquals(before, h.f.rows()); assertEquals(frames, h.link.frames)
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.inserts)
            assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.cancelPublishedInspection(NativeGalleryPublishedReadRun(Any())) }
        }
    }

    @Test fun publishedRuntimeRejectsStaleFingerprintMissingRightsAndSourceOnlyFactoryWithoutProviderIO() {
        Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published(); val reads = h.provider.readOpens
            val bad = h.runtime.beginPublishedInspection(selected.id, "f".repeat(64), h.f.book()).also { h.inspection = it }
            assertTrue(bad.awaitIoEnded(5000)); assertNull(bad.observation()); assertTrue(bad.nativeFailure() is PhotoFolderScopeError)
            h.f.io { h.runtime.revokeReceiving(h.runtime.savedPolicy(), GalleryMediaType.IMAGES, h.f.book()) }; h.handshake()
            val denied = h.inspect(selected); assertTrue(denied.awaitIoEnded(5000)); assertNull(denied.observation())
            assertTrue(denied.nativeFailure() is PhotoFolderScopeError); assertEquals(reads, h.provider.readOpens)
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
        }
        Harness(joined = false).use { h ->
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginPublishedInspection("a".repeat(64), "b".repeat(64), h.f.book()) }
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.readOpens)
        }
    }

    @Test fun actualRuntimeReadbackModeOutputsOnlyFreshReadProofAfterPublishedRowAndRenewedControlAgreement() {
        Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published()
            h.f.io { h.runtime.revokeReceiving(h.runtime.savedPolicy(), GalleryMediaType.IMAGES, h.f.book()) }; h.handshake()
            val consent = h.positive(); h.f.io { h.runtime.grantReceiving(h.runtime.savedPolicy(), consent) }; h.handshake()
            val offer = h.readbackOffer(); val before = h.f.rows(); val frames = h.link.frames.toList()
            val run = h.readback(selected, offer)
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.nativeFailure()); assertNull(run.observation())
            val output = run.actualReadbackOutput()!!; val body = output.getValue("body").jsonObject
            assertEquals(listOf(output), h.link.frames.drop(frames.size))
            assertEquals(DevicePublishedReadbackEnvelope.KIND, output.string("kind"))
            val parsed = DevicePublishedReadbackEnvelope.parse(output, offer, h.readbackBinding(body.string("destination_token")), GalleryMediaType.IMAGES)
            assertFalse(parsed.grantsWriteAuthority); assertFalse(parsed.isSavedReceipt); assertFalse(parsed.allowsChunkOutput)
            assertEquals(selected.fingerprint, body.string("publication_sha256"))
            assertNotEquals(selected.body.getValue("origin").jsonObject.getValue("binding").jsonObject.string("permission_epoch"), body.string("permission_epoch"))
            assertEquals(before, h.f.rows()); assertArrayEquals(h.raw, h.file.readBytes())
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
            assertEquals(1, h.link.frames.count { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        }
    }

    @Test fun runtimeReadbackRejectsForeignChannelStaleSelectionExpiredOfferAndCurrentReceiveWithdrawal() {
        Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published(); val reads = h.provider.readOpens
            NativeGalleryIncomingTransferTest.Link().use { foreign ->
                assertThrows(PhotoFolderScopeError::class.java) {
                    h.runtime.beginPublishedReadback(foreign.channel, h.readbackOffer(), selected.id, selected.fingerprint, h.f.book())
                }
            }
            val stale = h.runtime.beginPublishedReadback(h.link.channel, h.readbackOffer(), selected.id, "f".repeat(64), h.f.book()).also { h.inspection = it }
            assertTrue(stale.awaitIoEnded(5000)); assertNull(stale.actualReadbackOutput()); assertTrue(stale.nativeFailure() is PhotoFolderScopeError)
            val expired = h.link.receive(DeviceFileOfferEnvelope.create(h.manifest, System.currentTimeMillis() - 70000))
            val old = h.readback(selected, expired); assertTrue(old.awaitIoEnded(5000)); assertNull(old.actualReadbackOutput())
            assertTrue(old.nativeFailure() is PhotoFolderScopeError)
            h.f.io { h.runtime.revokeReceiving(h.runtime.savedPolicy(), GalleryMediaType.IMAGES, h.f.book()) }; h.handshake()
            val denied = h.readback(selected); assertTrue(denied.awaitIoEnded(5000)); assertNull(denied.actualReadbackOutput())
            assertTrue(denied.nativeFailure() is PhotoFolderScopeError)
            assertEquals(reads, h.provider.readOpens); assertEquals(selected.body, h.f.index.incomingPublication(selected.id)!!.body)
            assertTrue(h.link.frames.none { it.string("kind") == DevicePublishedReadbackEnvelope.KIND })
        }
        Harness(joined = false).use { h ->
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginPublishedReadback(h.link.channel, h.readbackOffer(), "a".repeat(64), "b".repeat(64), h.f.book()) }
            assertEquals(0, h.provider.inserts); assertEquals(0, h.provider.readOpens)
        }
    }

    @Test fun runtimeReadbackCancelControlDecreaseAndCloseNeverReleaseActualBlockedEncryptedOutputEarly() {
        for (change in listOf("cancel", "control", "local", "close")) Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published()
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val closed = java.util.concurrent.atomic.AtomicInteger()
            val observe = h.link.onMessage
            h.link.onMessage = { message ->
                observe(message)
                if (message.string("kind") == DevicePublishedReadbackEnvelope.KIND) { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            }
            val run = h.readback(selected)
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                assertThrows(PhotoFolderScopeError::class.java) { run.actualReadbackOutput() }
                assertThrows(PhotoFolderScopeError::class.java) { h.inspect(selected) }
                assertThrows(PhotoFolderScopeError::class.java) { h.start() }
                when (change) {
                    "cancel" -> h.runtime.cancelPublishedInspection(run)
                    "control" -> h.withdrawPcSend() // Actual independent encrypted incoming control.
                    "local" -> h.f.io { h.runtime.revokeReceiving(h.runtime.savedPolicy(), GalleryMediaType.IMAGES, h.f.book()) }
                    else -> assertFalse(h.runtime.closeWhenQuiescent { closed.incrementAndGet(); h.runtime.close() })
                }
                assertTrue(run.cancelRequested); assertFalse(run.ioEnded); assertEquals(0, closed.get())
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); Shadows.shadowOf(Looper.getMainLooper()).idle(); h.link.onMessage = observe
            assertNull(run.actualReadbackOutput()); assertNull(run.observation()); assertNotNull(run.nativeFailure())
            if (change == "close") {
                assertEquals(1, closed.get()); assertThrows(PhotoFolderScopeError::class.java) { h.runtime.savedPolicy() }
            }
            assertEquals(selected.body, h.f.index.incomingPublication(selected.id)!!.body); assertArrayEquals(h.raw, h.file.readBytes())
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
            // The encrypted frame may already have arrived: no false 'unsent' claim.
            assertEquals(1, h.link.frames.count { it.string("kind") == DevicePublishedReadbackEnvelope.KIND })
            assertEquals(1, h.link.frames.count { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        }
    }

    @Test fun runtimeReadbackBookAndDocumentWithdrawalCancelBeforeOutputWhileHoldingActualProviderLane() {
        for (change in listOf("book", "documents")) Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published(); val before = h.f.rows()
            val entered = CountDownLatch(1); val release = CountDownLatch(1)
            h.provider.beforeQuery = { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            val run = h.readback(selected)
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                if (change == "book") h.f.unlocked = false else h.f.currentDocuments = null
                h.runtime.incomingContextWithdrawn()
                assertTrue(run.cancelRequested); assertFalse(run.ioEnded)
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.actualReadbackOutput()); assertNull(run.observation()); assertNotNull(run.nativeFailure())
            assertTrue(h.link.frames.none { it.string("kind") == DevicePublishedReadbackEnvelope.KIND })
            assertEquals(before, h.f.rows()); assertArrayEquals(h.raw, h.file.readBytes())
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun actualRuntimeReadbackEncryptedOutputFailureCannotReportSuccessOrMutatePublication() {
        Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published(); val before = h.f.rows()
            h.link.failKind = DevicePublishedReadbackEnvelope.KIND
            val run = h.readback(selected)
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.actualReadbackOutput()); assertNull(run.observation())
            assertTrue(run.nativeFailure() is java.io.IOException)
            assertTrue(h.link.frames.none { it.string("kind") == DevicePublishedReadbackEnvelope.KIND })
            assertEquals(before, h.f.rows()); assertArrayEquals(h.raw, h.file.readBytes())
            val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun publishedRuntimeCancelOrControlWithdrawalRetainsBlockedReadLaneWhileControlsRemainIndependent() {
        for (withdraw in listOf(false, true)) Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published(); val before = h.f.rows()
            val entered = CountDownLatch(1); val release = CountDownLatch(1)
            h.provider.beforeQuery = { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            val run = h.inspect(selected)
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS)); assertNull(run.observationOrPending())
                assertThrows(PhotoFolderScopeError::class.java) { h.start() }
                assertThrows(PhotoFolderScopeError::class.java) { h.inspect(selected) }
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.discoverSelectable() }
                h.runtime.sendControls()
                if (withdraw) h.withdrawPcSend() else h.runtime.cancelPublishedInspection(run)
                assertFalse(run.ioEnded)
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.observation()); assertTrue(run.cancelRequested)
            assertEquals(before, h.f.rows()); assertArrayEquals(h.raw, h.file.readBytes())
            assertEquals(1, h.provider.inserts); assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
            assertEquals(1, h.link.frames.count { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        }
    }

    private fun NativeGalleryPublishedReadRun.observationOrPending(): NativeIncomingMediaObservation? {
        if (!ioEnded) { assertThrows(PhotoFolderScopeError::class.java) { observation() }; return null }
        return observation()
    }

    @Test fun localReceiveDecreaseAndBookWithdrawalCancelPublishedRuntimeReadWithoutLosingOriginal() {
        for (change in listOf("receive", "book")) Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published()
            val entered = CountDownLatch(1); val release = CountDownLatch(1)
            h.provider.beforeQuery = { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            val run = h.inspect(selected)
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                if (change == "receive") h.f.io { h.runtime.revokeReceiving(h.runtime.savedPolicy(), GalleryMediaType.IMAGES, h.f.book()) }
                else { h.f.unlocked = false; h.runtime.incomingContextWithdrawn() }
                assertTrue(run.cancelRequested); assertFalse(run.ioEnded)
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); assertNull(run.observation())
            assertEquals(selected.body, h.f.index.incomingPublication(selected.id)!!.body)
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.inserts)
            assertEquals(1, h.provider.writeOpens); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun nativeCloseDuringPublishedInspectionDefersIndexCleanupUntilRealReadDrains() {
        Harness().use { h ->
            assertTrue(h.start().awaitIoEnded(10000)); val selected = h.published()
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val closed = java.util.concurrent.atomic.AtomicInteger()
            h.provider.beforeQuery = { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            val run = h.inspect(selected)
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                assertFalse(h.runtime.closeWhenQuiescent { closed.incrementAndGet(); h.runtime.close() })
                assertEquals(0, closed.get()); assertFalse(run.ioEnded)
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(5000)); Shadows.shadowOf(Looper.getMainLooper()).idle()
            assertEquals(1, closed.get()); assertNull(run.observation()); assertTrue(run.cancelRequested)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.savedPolicy() }
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun actualRuntimeReceivesOnOwnedWorkerWhileChunkDispatcherAndControlsRemainIndependent() {
        Harness().use { h ->
            h.respond = false; val run = h.start()
            assertTrue(h.requested.await(5, TimeUnit.SECONDS))
            assertEquals("gallery_incoming_worker_busy", assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.discoverSelectable()
            }.message)
            assertThrows(PhotoFolderScopeError::class.java) { h.start() }
            h.runtime.sendControls() // This lane must not be held behind the waiting receiver.
            h.respond = true; h.answer(h.held!!)
            assertTrue(run.awaitIoEnded(10000)); assertEquals("saved_output", run.phase)
            assertNotNull(run.actualSavedOutput()); assertNull(run.nativeFailure())
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.publishes)
            assertEquals(DeviceFileSavedEnvelope.KIND, h.link.frames.last().string("kind"))
        }
    }

    @Test fun actualControlWithdrawalCancelsPendingReceiverWithoutWaitingForChunkExpiry() {
        Harness().use { h ->
            h.respond = false; val run = h.start()
            assertTrue(h.requested.await(5, TimeUnit.SECONDS)); h.withdrawPcSend()
            assertTrue(run.awaitIoEnded(5000)); assertEquals("canceled_held", run.phase)
            assertNull(run.actualSavedOutput()); assertEquals(0, h.provider.publishes)
            assertTrue(h.link.frames.none { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        }
    }

    @Test fun nativeCloseRetainsIoOwnershipAndDefersIndexCleanupUntilBlockedProviderActuallyReturns() {
        Harness().use { h ->
            val entered = CountDownLatch(1); val release = CountDownLatch(1)
            h.provider.beforeQuery = { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            val run = h.start(); val closed = java.util.concurrent.atomic.AtomicInteger()
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                assertFalse(h.runtime.closeWhenQuiescent { closed.incrementAndGet(); h.runtime.close() })
                assertFalse(run.ioEnded); assertEquals(0, closed.get())
                NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }).use { source ->
                    assertThrows(PhotoFolderScopeError::class.java) { source.startLocalInspection { } }
                }
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(10000)); Shadows.shadowOf(Looper.getMainLooper()).idle()
            assertEquals(1, closed.get()); assertNull(run.actualSavedOutput())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.savedPolicy() }
            assertEquals(0, h.provider.publishes)
        }
    }

    @Test fun sourceOnlyRuntimeFactoryNeverGainsIncomingHandlersFromMatchedTwoWayIntent() {
        Harness(joined = false).use { h ->
            val before = h.f.index.galleryPolicy()
            assertEquals("gallery_incoming_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) { h.start() }.message)
            assertEquals(before, h.f.index.galleryPolicy()); assertNull(before.policy)
            assertEquals(0, h.provider.inserts)
        }
    }

    @Test fun incomingVideoCannotFallBackToImageHandlersWithoutNativeVideoPeerCapability() {
        Harness().use { h ->
            assertEquals("gallery_video_wire_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.beginIncoming(DeviceFileOfferEnvelope.create(h.manifest), GalleryMediaType.VIDEO,
                    mapOf("1".repeat(32) to "video/mp4"), h.f.book())
            }.message)
            assertEquals(0, h.provider.inserts)
        }
    }

    @Test fun sharedProcessLaneSurvivesCancelUntilRealIncomingPreparationEndsAndThenAdmitsSource() {
        val entered = CountDownLatch(1); val release = CountDownLatch(1)
        NativeGalleryIncomingWorker().use { incoming ->
            NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }).use { source ->
                val run = incoming.start { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)); throw java.io.IOException("explicit native preparation end") }
                try {
                    assertTrue(entered.await(5, TimeUnit.SECONDS)); incoming.close()
                    assertFalse(incoming.isQuiescent); assertFalse(run.ioEnded)
                    assertThrows(PhotoFolderScopeError::class.java) { source.startLocalInspection { } }
                } finally { release.countDown() }
                assertTrue(run.awaitIoEnded(10000)); assertTrue(incoming.isQuiescent)
                assertEquals("canceled_held", run.phase)
                val sourceEnded = CountDownLatch(1)
                NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }, { sourceEnded.countDown() }).use { next ->
                    next.startLocalInspection { }; assertTrue(sourceEnded.await(5, TimeUnit.SECONDS)); assertTrue(next.isQuiescent)
                }
            }
        }
    }

    @Test fun actualForegroundPositiveConsentCommitsThroughRuntimeAndStillNeedsFreshDataControlEcho() {
        Harness(localConsent = false).use { h ->
            val before = h.runtime.savedPolicy(); assertNull(before.policy)
            val selected = h.positive()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.grantReceiving(before, selected) }
            assertNull(h.runtime.savedPolicy().policy)
            val saved = h.f.io { h.runtime.grantReceiving(before, selected) }
            assertTrue(saved.policy!!.receiving!!.photos); assertFalse(saved.policy.receiving.videos)
            assertFalse(saved.policy.enabled); assertFalse(saved.policy.videos!!.enabled)
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED, h.f.app.checkSelfPermission(android.Manifest.permission.READ_MEDIA_IMAGES))
            assertThrows(PhotoFolderScopeError::class.java) { selected.requireCurrent() }
            val held = h.start(); assertTrue(held.awaitIoEnded(5000)); assertNull(held.actualSavedOutput())
            assertEquals(0, h.provider.inserts) // Local positive choice alone is not fresh data agreement.
            h.handshake()
            val run = h.start(); assertTrue(run.awaitIoEnded(10000)); assertNotNull(run.actualSavedOutput())
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun canceledOrForeignReceiveConfigurationNeverPersistsRightsOrFinishesANewerTicket() {
        Harness(localConsent = false).use { h ->
            val before = h.f.rows(); val old = h.f.io { h.runtime.beginReceiveConfiguration() }
            val result = java.util.concurrent.atomic.AtomicReference<Result<NativeGalleryReceiveConsent>?>()
            NativeGalleryReceiveConsent.request(h.f.activity, "Native own PC", GalleryMediaType.IMAGES, old, h.f.book()) { result.set(it) }
            org.robolectric.shadows.ShadowAlertDialog.getLatestAlertDialog().getButton(android.content.DialogInterface.BUTTON_NEGATIVE).performClick()
            Shadows.shadowOf(Looper.getMainLooper()).idle(); assertTrue(result.get()!!.isFailure)
            h.runtime.finishReceiveConfiguration(old)
            val current = h.f.io { h.runtime.beginReceiveConfiguration() }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.finishReceiveConfiguration(old) }
            h.runtime.finishReceiveConfiguration(current)
            assertEquals(before, h.f.rows()); assertNull(h.runtime.savedPolicy().policy)
        }
    }

    @Test fun positiveReceiveConsentCannotCommitAcrossAnotherOwnedMediaIoAndFreshExplicitRetryWorks() {
        Harness(localConsent = false).use { h ->
            val before = h.runtime.savedPolicy(); val selected = h.positive()
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val ended = CountDownLatch(1)
            NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }, { ended.countDown() }).use { source ->
                source.startLocalInspection { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
                try {
                    assertTrue(entered.await(5, TimeUnit.SECONDS))
                    assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.runtime.grantReceiving(before, selected) } }
                    assertEquals(before, h.runtime.savedPolicy()); assertThrows(PhotoFolderScopeError::class.java) { selected.requireCurrent() }
                } finally { release.countDown() }
                assertTrue(ended.await(5000, TimeUnit.MILLISECONDS))
            }
            val fresh = h.positive()
            assertTrue(h.f.io { h.runtime.grantReceiving(before, fresh) }.policy!!.receiving!!.photos)
        }
    }

    @Test fun nativeLocalReceiveDecreaseWorksWithoutAnOnlinePcAndPreservesSourceEpochAndStoredHistory() {
        Harness().use { h ->
            val before = h.runtime.savedPolicy(); val epoch = before.policy!!.epoch
            h.f.peer = h.f.peer.copy(ready = false)
            val off = h.f.io { h.runtime.revokeReceiving(before, GalleryMediaType.IMAGES, h.f.book()) }
            assertFalse(off.policy!!.receiving!!.photos); assertEquals(epoch, off.policy.epoch)
            assertEquals(before.policy.enabled, off.policy.enabled); assertTrue(off.policy.fileGrantRevision > before.policy.fileGrantRevision)
            val rows = h.f.rows()
            assertEquals(off, h.f.io { h.runtime.revokeReceiving(off, GalleryMediaType.IMAGES, h.f.book()) }); assertEquals(rows, h.f.rows())
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.runtime.beginReceiveConfiguration() } }
            assertEquals(0, h.provider.inserts)
        }
    }

    @Test fun exhaustedReceiveRevisionHoldsTheRuntimeWithoutPretendingPositiveStoredConsentWasOff() {
        Harness().use { h ->
            val p = h.runtime.savedPolicy().policy!!
            val exhausted = h.f.seedPolicy(GalleryPhotoPolicy(p.receiverId, p.receiverIdentitySha256, p.epoch, p.enabled, p.kinds,
                DeviceFileControl.MAX_REVISION, 5, p.pairingEpoch, p.videos, DeviceFileControl.MAX_REVISION,
                p.receiving!!.copy(revision = DeviceFileControl.MAX_REVISION)))
            h.handshake(); val selected = h.positive(GalleryMediaType.VIDEO); val rows = h.f.rows()
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.runtime.grantReceiving(exhausted, selected) } }
            assertEquals(rows, h.f.rows()); assertTrue(h.runtime.savedPolicy().policy!!.receiving!!.photos)
            assertThrows(PhotoFolderScopeError::class.java) { h.start() }
            assertEquals(0, h.provider.inserts)
        }
    }
}
