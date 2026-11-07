package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.graphics.Bitmap
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class NativeGalleryIncomingTransferTest {
    private val fileId = "1".repeat(32)
    @Before fun mountedVolume() { GalleryIncomingRowsTest().mountedPrimaryVolume() }

    internal class Link : AutoCloseable {
        val key = ByteArray(32) { 7 }; val prefix = ByteArray(4) { 8 }; val sid = ByteArray(16) { 9 }
        val frames = mutableListOf<JsonObject>()
        var onMessage: (JsonObject) -> Unit = {}
        var failKind: String? = null
        private var receiveSequence = 0L
        private val incoming = java.util.ArrayDeque<Int>()
        private val input = object : InputStream() { override fun read(): Int = if (incoming.isEmpty()) -1 else incoming.removeFirst() }
        private val output = object : ByteArrayOutputStream() {
            override fun flush() {
                val frame = TelefonRahmen.lesen(ByteArrayInputStream(toByteArray()), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX); reset()
                val header = JsonObject(frame.filterKeys { it != "ciphertext" })
                val clear = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")),
                    TelefonKrypto.b64(frame.string("ciphertext"), java.util.Base64.getDecoder().decode(frame.string("ciphertext")).size), TelefonKanonisch.bytes(header))
                val message = TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject
                if (message.string("kind") == failKind) throw java.io.IOException("explicit secure output failure")
                frames += message; onMessage(message)
            }
        }
        val channel = TelefonSecureChannel(input, output, sid.copyOf(), key.copyOf(), prefix.copyOf(), key.copyOf(), prefix.copyOf())
        fun receive(message: JsonObject): JsonObject {
            val header = buildJsonObject { put("p", TelefonParameter.PROTOKOLL); put("sid", TelefonKrypto.b64(sid)); put("seq", receiveSequence); put("dir", "desktop_to_phone") }
            val cipher = TelefonKrypto.verschluesseln(key, TelefonKrypto.nonce(prefix, receiveSequence++), TelefonKanonisch.bytes(message), TelefonKanonisch.bytes(header))
            val frame = ByteArrayOutputStream().also {
                TelefonRahmen.schreiben(it, JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(cipher)))), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
            }.toByteArray()
            frame.forEach { incoming.addLast(it.toInt() and 255) }
            return channel.receive()
        }
        override fun close() { channel.close(); key.fill(0); prefix.fill(0) }
    }

    internal fun png(): ByteArray {
        val bitmap = Bitmap.createBitmap(256, 256, Bitmap.Config.ARGB_8888)
        val pixels = IntArray(256 * 256); val random = java.util.Random(338)
        pixels.indices.forEach { pixels[it] = random.nextInt() or (0xff shl 24) }; bitmap.setPixels(pixels, 0, 256, 0, 0, 256, 256)
        return try { ByteArrayOutputStream().use { output -> check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)); output.toByteArray() } }
            finally { bitmap.recycle() }
    }
    internal fun manifest(peer: String, bytes: ByteArray) = DeviceFileManifest.parse(buildJsonObject {
        put("format", 1); put("chunk_bytes", 65536); put("total_bytes", bytes.size); put("transfer_id", "2".repeat(32)); put("source_id", "3".repeat(32))
        put("sender_id", peer); put("receiver_id", "phone_fixture_0001")
        put("files", JsonArray(listOf(buildJsonObject { put("id", fileId); put("path", "original.png"); put("size", bytes.size)
            put("sha256", MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }) })))
    })
    internal fun intent(collectionMode: String = "entire_collection"): MediaSyncTransport.IntentToken {
        val a = "11111111-1111-4111-8111-111111111111"; val b = "22222222-2222-4222-8222-222222222222"
        val enabled = MediaSyncSettings.change(MediaSyncSettings.change(MediaSyncSettings.create(a), a, b,
            "collection_mode", JsonPrimitive(collectionMode)), a, b, "enabled", JsonPrimitive(true))
        return MediaSyncTransport.IntentToken(MediaSyncSettings.change(enabled, a, b, "direction", JsonPrimitive("two_way")))
    }
    internal fun grant(f: GalleryReceiveConsentTest.Fixture) {
        val selected = f.approve(); f.io { f.controller.grant(f.index.galleryPolicy(), selected) }; f.handshake()
    }
    private fun respond(link: Link, transfer: NativeGalleryIncomingTransfer, message: JsonObject, raw: ByteArray,
        change: (JsonObject) -> JsonObject = { it }) {
        if (message.string("kind") != DeviceFileChunkEnvelope.REQUEST) return
        val request = DeviceFileChunkEnvelope.parseRequest(message)
        val offset = request.chunkIndex * 65536
        val response = change(DeviceFileChunkEnvelope.response(request, raw.copyOfRange(offset, minOf(raw.size, offset + 65536))))
        assertTrue(transfer.observeChunk(link.channel, link.receive(response)))
    }

    @Test fun actualEncryptedAcceptanceChunksAndSavedFollowDurableNativePublishedLineage() {
        Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); assertTrue(raw.size > 65536)
            val manifest = manifest(f.pc.deviceId, raw); val token = intent(); val file = File(f.root, "incoming-native.png")
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = file).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).use { transfer ->
                    assertEquals(transfer.acceptance.body, f.index.incomingAcceptance(transfer.acceptance.id)!!.body)
                    assertEquals(0, provider.inserts)
                    link.onMessage = { message ->
                        if (message.string("kind") == DeviceFileSavedEnvelope.KIND) assertFalse(transfer.actualSavedOutput)
                        respond(link, transfer, message, raw) // Can race send return; worker must await actual output completion.
                    }
                    val accepted = DeviceFileAcceptanceEnvelope.parse(transfer.sendAcceptance())
                    val savedMessage = transfer.receiveAndSendSaved(); assertTrue(transfer.actualSavedOutput)
                    val saved = DeviceFileSavedEnvelope.parse(savedMessage, manifest)
                    assertEquals(accepted.acceptanceSha256, saved.acceptanceSha256)
                    val plan = GalleryIncomingPublication.plan(owner.binding, manifest, fileId, owner.pairingEpoch, owner.kind, "image/png")
                    val published = f.index.incomingPublication(plan.id)!!
                    assertEquals("published", published.state); assertEquals(published.fingerprint, saved.members.single().receiptSha256)
                    assertEquals(DeviceFileAcceptanceEnvelope.KIND, link.frames.first().string("kind"))
                    assertEquals(DeviceFileSavedEnvelope.KIND, link.frames.last().string("kind"))
                    assertTrue(link.frames.count { it.string("kind") == DeviceFileChunkEnvelope.REQUEST } > 1)
                    assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndSendSaved() }
                }
            }
            assertArrayEquals(raw, file.readBytes()); assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        } }
    }

    @Test fun failedActualAcceptanceOutputCannotStartReceiveOrPromoteStoredAcceptanceToPermission() {
        Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = File(f.root, "never-written"))
            ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).use { transfer ->
                    link.failKind = DeviceFileAcceptanceEnvelope.KIND
                    assertThrows(java.io.IOException::class.java) { transfer.sendAcceptance() }
                    assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndSendSaved() }
                    assertFalse(transfer.actualSavedOutput)
                    assertNotNull(f.index.incomingAcceptance(transfer.acceptance.id))
                }
            }
            assertEquals(0, provider.inserts); assertEquals(0, provider.writeOpens)
        } }
    }

    @Test fun forgedCorrelatedChunkFieldsOrHashHoldBeforePublicationAndNeverSendSaved() {
        for (field in listOf("permission_epoch", "acceptance_sha256", "data_sha256")) Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = File(f.root, "held-native.png")).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).use { transfer ->
                    link.onMessage = { message -> respond(link, transfer, message, raw) { response ->
                        JsonObject(response + ("body" to JsonObject(response["body"]!!.jsonObject + (field to JsonPrimitive("0".repeat(64))))))
                    } }
                    transfer.sendAcceptance()
                    assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndSendSaved() }
                    assertFalse(transfer.actualSavedOutput)
                }
            }
            assertEquals(0, provider.publishes); assertTrue(link.frames.none { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        } }
    }

    @Test fun failedSavedSecureOutputPreservesPublishedBytesAndNativeMappingWithoutClaimingCompletion() {
        Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent(); val file = File(f.root, "saved-output-failed.png")
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = file).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).use { transfer ->
                    link.onMessage = { respond(link, transfer, it, raw) }; transfer.sendAcceptance(); link.failKind = DeviceFileSavedEnvelope.KIND
                    assertThrows(java.io.IOException::class.java) { transfer.receiveAndSendSaved() }
                    assertFalse(transfer.actualSavedOutput)
                    val plan = GalleryIncomingPublication.plan(owner.binding, manifest, fileId, owner.pairingEpoch, owner.kind, "image/png")
                    assertEquals("published", f.index.incomingPublication(plan.id)!!.state)
                }
            }
            assertArrayEquals(raw, file.readBytes()); assertEquals(1, provider.publishes)
        } }
    }

    @Test fun wrongChannelAndIdenticalEarlyChunkReplayCannotAdvanceOrChangeAnotherRequest() {
        Link().use { other -> Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = File(f.root, "correlated-native.png")).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            var last: JsonObject? = null
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).use { transfer ->
                    link.onMessage = { message ->
                        if (message.string("kind") == DeviceFileChunkEnvelope.REQUEST) {
                            val request = DeviceFileChunkEnvelope.parseRequest(message); val offset = request.chunkIndex * 65536
                            val response = link.receive(DeviceFileChunkEnvelope.response(request, raw.copyOfRange(offset, minOf(raw.size, offset + 65536))))
                            assertFalse(transfer.observeChunk(other.channel, response))
                            assertTrue(transfer.observeChunk(link.channel, response))
                            assertTrue(transfer.observeChunk(link.channel, response)) // Provisional identical response only; no extra write.
                            last = response
                        }
                    }
                    transfer.sendAcceptance(); transfer.receiveAndSendSaved()
                    assertFalse(transfer.observeChunk(link.channel, last!!)); assertTrue(transfer.actualSavedOutput)
                }
            }
            assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        } } }
    }

    @Test fun nativeCloseDrainsAnOutstandingChunkWorkerWithoutLeakingAThreadOrSendingSaved() {
        Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = File(f.root, "cancelled-native.png")).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            val transfer = f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).also { it.sendAcceptance() }
            }
            val requested = java.util.concurrent.CountDownLatch(1); val ended = java.util.concurrent.CountDownLatch(1)
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            link.onMessage = { if (it.string("kind") == DeviceFileChunkEnvelope.REQUEST) requested.countDown() }
            val worker = Thread {
                try { f.io { transfer.receiveAndSendSaved() } }
                catch (error: Throwable) { failure.set(error) }
                finally { ended.countDown() }
            }
            try {
                worker.start(); assertTrue(requested.await(5, java.util.concurrent.TimeUnit.SECONDS))
                transfer.close(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
            } finally { transfer.close(); worker.join(5000); assertFalse(worker.isAlive) }
            assertTrue(failure.get() is PhotoFolderScopeError); assertFalse(transfer.actualSavedOutput)
            assertEquals(0, provider.publishes); assertTrue(link.frames.none { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        } }
    }

    @Test fun deletedAcceptanceIntentIsIntegrityFailureBeforeSecureAcceptOutputNotAnEmptyRecreatableSlot() {
        Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest), mapOf(fileId to "image/png")).use { transfer ->
                    android.database.sqlite.SQLiteDatabase.openDatabase(File(f.indexRoot, "photo-source-jobs.db").path, null,
                        android.database.sqlite.SQLiteDatabase.OPEN_READWRITE).use { db ->
                        assertEquals(1, db.delete("source_meta", "name=?", arrayOf(GalleryIncomingAcceptance.PREFIX + transfer.acceptance.id)))
                    }
                    assertThrows(PhotoFolderScopeError::class.java) { transfer.sendAcceptance() }
                    assertFalse(transfer.actualSavedOutput); assertTrue(link.frames.isEmpty())
                }
            }
        } }
    }

    @Test fun offerMismatchOrMissingMimeMetadataCannotCreateAcceptanceOrReceiveRows() {
        for (mode in listOf("manifest", "mime", "channel")) Link().use { other -> Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            val before = f.rows()
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                    val offered = if (mode == "manifest") DeviceFileManifest.parse(JsonObject(manifest.wire() + ("source_id" to JsonPrimitive("4".repeat(32))))) else manifest
                    assertThrows(PhotoFolderScopeError::class.java) {
                        NativeGalleryIncomingTransfer.prepare(owner, if (mode == "channel") other.channel else link.channel, f.index,
                            NativeGalleryIncomingRows(f.app, f.index), DeviceFileOfferEnvelope.create(offered),
                            if (mode == "mime") emptyMap() else mapOf(fileId to "image/png"))
                    }
                }
            }
            assertEquals(before, f.rows()); assertTrue(link.frames.isEmpty())
        } } }
    }

    @Test fun correlatedChunkCannotExtendItsOriginalRequestExpiryOrSurviveControlWithdrawal() {
        for (mode in listOf("expires", "control")) Link().use { link -> GalleryReceiveConsentTest.Fixture(link.channel).use { f ->
            grant(f); val raw = png(); val manifest = manifest(f.pc.deviceId, raw); val token = intent()
            val provider = GalleryIncomingRowsTest.Provider(f.app, payload = File(f.root, "held-expiry.png")).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                NativeGalleryIncomingTransfer.prepare(owner, link.channel, f.index, NativeGalleryIncomingRows(f.app, f.index),
                    DeviceFileOfferEnvelope.create(manifest, ttlMs = 50_000), mapOf(fileId to "image/png")).use { transfer ->
                    link.onMessage = { message ->
                        if (message.string("kind") == DeviceFileChunkEnvelope.REQUEST) {
                            val request = DeviceFileChunkEnvelope.parseRequest(message)
                            var response = DeviceFileChunkEnvelope.response(request, raw.copyOfRange(0, minOf(65536, raw.size)))
                            if (mode == "expires") response = JsonObject(response + ("expires_ms" to JsonPrimitive(request.expires + 1000)))
                            else f.session.close()
                            transfer.observeChunk(link.channel, link.receive(response))
                        }
                    }
                    transfer.sendAcceptance()
                    assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndSendSaved() }
                    assertFalse(transfer.actualSavedOutput)
                }
            }
            assertEquals(0, provider.publishes)
        } }
    }
}
