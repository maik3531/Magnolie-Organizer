package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.util.Base64
import java.util.concurrent.TimeUnit

/** Actual Kotlin provider/producer -> Python sender in separate processes.
 * Robolectric provider and synthetic test keys/history, NOT physical Android. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class PairedPublishedReadbackTest {
    @Test fun actualKotlinPublishedReadbackCompletesPythonRetryWithoutSyntheticPeerProof() = runPaired("positive")
    @Test fun actualKotlinProofForDifferentOfferCannotCompleteCurrentPythonRetry() = runPaired("wrong_offer")
    @Test fun actualKotlinReadbackVerifiesCompletedPythonRetryAfterFreshOriginalPreparation() = runPaired("verification_positive")
    @Test fun actualWrongOfferKotlinProofCannotCompleteReadbackOnlyVerification() = runPaired("verification_wrong_offer")
    @Test fun normalPcImageUploadPublishesOriginalOnceAndCompletesBackupWithoutSyntheticAcceptanceOrSaved() = runPaired("normal_upload")

    private fun runPaired(mode: String) {
        GalleryIncomingRowsTest().mountedPrimaryVolume()
        val app = RuntimeEnvironment.getApplication()
        val log = File.createTempFile("paired416-", ".log", File("/tmp/opencode"))
        ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { server ->
            server.soTimeout = 30000
            val builder = ProcessBuilder(System.getenv("MAGNOLIE_PYTHON") ?: "python3", "-u", "-m", "pytest", "-q", "-s",
                "../magnolie-organizer/pruefungen/paired_published_readback_host.py")
            builder.environment()["MAGNOLIE_PAIRED_READBACK_PORT"] = server.localPort.toString()
            val process = builder.redirectErrorStream(true).redirectOutput(log).start()
            try {
                server.accept().use { socket ->
                    socket.soTimeout = 15000
                    val bitmap = android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)
                    val raw = try { java.io.ByteArrayOutputStream().use { out ->
                        check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out)); out.toByteArray()
                    } } finally { bitmap.recycle() }
                    TelefonRahmen.schreiben(socket.getOutputStream(), buildJsonObject { put("png", Base64.getEncoder().encodeToString(raw)); put("mode", mode) })
                    val config = TelefonRahmen.lesen(socket.getInputStream(), 65536)
                    val manifest = DeviceFileManifest.parse(config.getValue("manifest").jsonObject)
                    TelefonSecureChannel(socket.getInputStream(), socket.getOutputStream(), ByteArray(16) { 3 },
                        ByteArray(32) { 2 }, ByteArray(4) { 2 }, ByteArray(32) { 1 }, ByteArray(4) { 1 }).use { channel ->
                        // Continue the exact transport sequences after preparatory
                        // fixture traffic. No counters/TTL in product are reset.
                        for ((field, key) in listOf("sendSequence" to "phone_send_seq", "receiveSequence" to "phone_receive_seq"))
                            TelefonSecureChannel::class.java.getDeclaredField(field).apply { isAccessible = true }.setLong(channel, config.long(key))
                        GalleryReceiveConsentTest.Fixture(channel, NativeFileControlIdentity(config.string("pc_id"), config.string("pc_hash")),
                            NativeFileControlIdentity(config.string("phone_id"), config.string("phone_hash"))).use fixture@ { f ->
                            val consent = f.approve(); f.io { f.controller.grant(f.index.galleryPolicy(), consent) }; f.handshake()
                            val a = "11111111-1111-4111-8111-111111111111"; val b = "22222222-2222-4222-8222-222222222222"
                            val enabled = MediaSyncSettings.change(MediaSyncSettings.create(a), a, b, "enabled", JsonPrimitive(true))
                            // Explicit synthetic fixture scope, not an inferred
                            // phone-inventory reference or production default.
                            val collection = MediaSyncSettings.change(enabled, a, b, "collection_mode", JsonPrimitive("entire_collection"))
                            val token = MediaSyncTransport.IntentToken(MediaSyncSettings.change(collection, a, b, "direction", JsonPrimitive("two_way")))
                            val payload = File(f.root, "paired-original.png")
                            val provider = GalleryIncomingRowsTest.Provider(app, payload = payload).apply { allowPublish = true }
                            ShadowContentResolver.registerProviderInternal("media", provider)
                            val rows = NativeGalleryIncomingRows(app, f.index)
                            if (mode == "normal_upload") {
                                repeat(3) {
                                    val remote = channel.receive()
                                    f.session.observeRemote(DeviceFileControlEnvelope.validate(remote), f.peer)
                                    val packet = f.session.packet(); channel.send(DeviceFileControlEnvelope.create(packet)); f.session.markSent(packet)
                                }
                                val offer = channel.receive()
                                val transfer = f.io {
                                    val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES)
                                    NativeGalleryIncomingTransfer.prepare(owner, channel, f.index, rows, offer, mapOf(manifest.files.single().id to "image/png"))
                                }
                                transfer.use {
                                    f.io { it.sendAcceptance() }
                                    val ended = java.util.concurrent.CountDownLatch(1)
                                    val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
                                    val worker = Thread {
                                        try { f.io { transfer.receiveAndSendSaved() } } catch (error: Throwable) { failure.set(error) }
                                        finally { ended.countDown() }
                                    }.also { it.start() }
                                    try {
                                        val chunkCount = ((manifest.files.single().size + DeviceFileManifest.CHUNK_BYTES - 1) / DeviceFileManifest.CHUNK_BYTES).toInt()
                                        repeat(chunkCount) { assertTrue(transfer.observeChunk(channel, channel.receive())) }
                                        assertTrue(ended.await(10, TimeUnit.SECONDS)); assertNull(failure.get())
                                        val result = TelefonRahmen.lesen(socket.getInputStream(), 65536)
                                        assertEquals("uploaded", result.string("result"))
                                        assertEquals(manifest.files.single().sha256, result.string("sha256"))
                                        assertArrayEquals(raw, payload.readBytes())
                                        assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
                                    } finally { transfer.close(); worker.join(5000); assertFalse(worker.isAlive) }
                                }
                                return@fixture
                            }
                            val published = f.io {
                                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                                    rows.publish(owner, rows.copyAndVerify(owner, rows.prepare(owner, manifest.files.single().id, "image/png"), { raw.copyOf() }))
                                }
                            }
                            f.io { f.controller.revoke(f.index.galleryPolicy(), GalleryMediaType.IMAGES, f.book()) }; f.handshake()
                            val renewed = f.approve(); f.io { f.controller.grant(f.index.galleryPolicy(), renewed) }; f.handshake()
                            val rounds = if (mode.startsWith("verification_")) 2 else 1
                            val before = f.rows()
                            repeat(rounds) { round ->
                                repeat(3) {
                                    val remote = channel.receive()
                                    assertEquals(DeviceFileControl.KIND, remote.string("kind"))
                                    f.session.observeRemote(DeviceFileControlEnvelope.validate(remote), f.peer)
                                    val packet = f.session.packet(); channel.send(DeviceFileControlEnvelope.create(packet)); f.session.markSent(packet)
                                }
                                val offer = channel.receive()
                                val wrong = mode.endsWith("wrong_offer") && round == rounds - 1
                                val selectedOffer = if (wrong) DeviceFileOfferEnvelope.create(manifest) else offer
                                val output = f.io {
                                    val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                                    NativeGalleryPublishedReadback.capture(owner, selectedOffer, channel).use { it.perform(rows) }
                                }
                                assertEquals(DevicePublishedReadbackEnvelope.KIND, output.string("kind"))
                                val result = TelefonRahmen.lesen(socket.getInputStream(), 65536)
                                assertEquals(if (round < rounds - 1) "verify_next" else if (wrong) "rejected" else "archived", result.string("result"))
                                assertEquals(0L, result.long("sent_bits"))
                                assertEquals(output.getValue("body").jsonObject["readback_sha256"], result["proof_sha256"])
                                assertEquals(offer["message_id"], result["offer_id"])
                                assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
                            }
                        }
                    }
                }
                assertTrue(process.waitFor(20, TimeUnit.SECONDS)); assertEquals(log.readText(), 0, process.exitValue())
            } catch (error: Throwable) {
                throw AssertionError("Paired native readback failed. Python: ${log.readText().takeLast(6000)}", error)
            } finally {
                if (process.isAlive) { process.destroy(); if (!process.waitFor(3, TimeUnit.SECONDS)) { process.destroyForcibly(); process.waitFor(3, TimeUnit.SECONDS) } }
            }
        }
    }
}
