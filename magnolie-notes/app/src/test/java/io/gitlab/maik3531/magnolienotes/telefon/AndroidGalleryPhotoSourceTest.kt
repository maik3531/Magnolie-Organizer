package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.ContentProvider
import android.content.ContentResolver
import android.content.ContentValues
import android.content.Intent
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.os.CancellationSignal
import android.os.OperationCanceledException
import android.os.ParcelFileDescriptor
import androidx.activity.ComponentActivity
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Robolectric
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.nio.file.Files
import javax.crypto.spec.SecretKeySpec
import kotlinx.serialization.json.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29], application = Application::class, shadows = [AndroidGalleryVolumeAccessTest.MountedVolumes::class])
class AndroidGalleryPhotoSourceTest {
    private data class Row(val id: Long = 1, val bucket: String = "camera", val label: String = "Camera",
        val name: String = "image.jpg", val bytes: Long = 5, val modified: Any = 100L, val added: Long = 90,
        val mime: String = "image/jpeg", val path: String = "DCIM/Camera/", val pending: Long = 0, val trashed: Long = 0,
        val generationAdded: Any = 1L, val generationModified: Any = 1L)
    private class Provider(val root: File) : ContentProvider() {
        var rows = listOf(Row())
        var ignoreSelection = false
        var ignoreLimit = false
        var reverse = false
        var onQuery: (() -> Unit)? = null
        var onOpen: (() -> Unit)? = null
        val cursors = mutableListOf<Cursor>()
        val opens = mutableListOf<String>()
        val requests = mutableListOf<Bundle>()
        override fun onCreate() = true
        override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
            check(method == "get_version" && extras?.getString(Intent.EXTRA_TEXT) == "external_primary")
            return Bundle().apply { putString(Intent.EXTRA_TEXT, "native-fixture-v1") }
        }
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, sort: String?): Cursor =
            throw AssertionError("Expected API26+ bundle query")
        override fun query(uri: Uri, projection: Array<out String>?, queryArgs: Bundle?, cancellation: CancellationSignal?): Cursor {
            val columns = requireNotNull(projection)
            check("_data" !in columns)
            val volume = if (Build.VERSION.SDK_INT >= 29) "external_primary" else "external"
            check(uri.toString().startsWith("content://media/$volume/images/media") ||
                uri.toString() == "content://media/1234-5678/images/media")
            val args = requireNotNull(queryArgs)
            var selected = rows
            if (uri.pathSegments.size == 3) {
                requests += Bundle(args)
                check(args.getString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER) == "_id ASC")
                val values = requireNotNull(args.getStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS))
                if ("_display_name" !in columns) {
                    check(args.getString(ContentResolver.QUERY_ARG_SQL_SELECTION)!!.startsWith("_id > ? AND LOWER(relative_path) IN ("))
                    selected = selected.filter { it.id > values[0].toLong() && it.path.lowercase(java.util.Locale.ROOT) in values.drop(1) }
                } else {
                    check(args.getString(ContentResolver.QUERY_ARG_SQL_SELECTION) == "_id > ? AND bucket_id = ?" +
                        (if (Build.VERSION.SDK_INT >= 29) " AND is_pending = 0" else "") +
                        (if (Build.VERSION.SDK_INT >= 30) " AND is_trashed = 0" else ""))
                    if (!ignoreSelection) selected = selected.filter { it.id > values[0].toLong() && it.bucket == values[1] &&
                        (Build.VERSION.SDK_INT < 29 || it.pending == 0L) && (Build.VERSION.SDK_INT < 30 || it.trashed == 0L) }
                }
                if (uri.pathSegments.first() == "1234-5678") selected = emptyList()
                selected = selected.sortedBy { it.id }
                if (reverse) selected = selected.reversed()
                if (!ignoreLimit) selected = selected.take(args.getInt(ContentResolver.QUERY_ARG_LIMIT))
            } else selected = selected.filter { it.id.toString() == uri.lastPathSegment }
            val cursor = MatrixCursor(columns)
            selected.forEach { row ->
                val data = mapOf("_id" to row.id, "bucket_id" to row.bucket, "bucket_display_name" to row.label,
                    "_display_name" to row.name, "mime_type" to row.mime, "_size" to row.bytes,
                    "date_modified" to row.modified, "date_added" to row.added, "relative_path" to row.path, "is_pending" to row.pending,
                    "is_trashed" to row.trashed, "generation_added" to row.generationAdded, "generation_modified" to row.generationModified)
                cursor.addRow(columns.map { data[it] }.toTypedArray())
            }
            cursors += cursor
            onQuery?.invoke()
            return cursor
        }
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            check(mode == "r")
            opens += uri.toString()
            onOpen?.invoke()
            return ParcelFileDescriptor.open(File(root, "source.bin"), ParcelFileDescriptor.MODE_READ_ONLY)
        }
        override fun getType(uri: Uri) = "image/jpeg"
        override fun insert(uri: Uri, values: ContentValues?): Uri = throw AssertionError("Unexpected photo write")
        override fun update(uri: Uri, values: ContentValues?, where: String?, args: Array<out String>?): Int = throw AssertionError("Unexpected photo write")
        override fun delete(uri: Uri, where: String?, args: Array<out String>?): Int = throw AssertionError("Unexpected photo delete")
    }
    private class Fixture : AutoCloseable {
        val context = RuntimeEnvironment.getApplication()
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-pfd329-").toFile()
        val provider = Provider(root)
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        var request: NativeGalleryRequest? = NativeGalleryRequest(receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, if (Build.VERSION.SDK_INT >= 29) "external_primary" else "external",
            "camera", "Camera", if (Build.VERSION.SDK_INT >= 29) "DCIM/Camera/" else null, 1, false)
        val scope = GalleryPhotoSourceScope({ request }, AndroidGalleryAccessEnvironment(context) { "a".repeat(64) })
        val reader = AndroidGalleryPhotoSource(context, scope)
        init {
            File(root, "source.bin").writeText("hello")
            Shadows.shadowOf(context as Application).grantPermissions(if (Build.VERSION.SDK_INT >= 33)
                Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE)
            provider.attachInfo(context, ProviderInfo().apply { authority = "media"; exported = true })
            ShadowContentResolver.registerProviderInternal("media", provider)
        }
        fun lease() = scope.capture(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(album), request), album)
        fun assertClosed() = assertTrue(provider.cursors.all { it.isClosed })
        override fun close() { assertClosed(); root.deleteRecursively() }
    }

    @Test fun nativeWorkflowJoinsProtectedPolicyActualDiscoveryPfdSnapshotOfferAndRevokedCacheCleanup() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                assertNull(workflow.savedPolicy().policy)
                assertTrue(workflow.discover().albums.isEmpty()); assertTrue(f.provider.requests.isEmpty())
                val saved = workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { throw AssertionError("No startup permission prompt expected") }
                activity.start().resume()
                assertNull(Shadows.shadowOf(activity.get()).lastRequestedPermission)
                val catalog = workflow.discover(); val album = catalog.albums.single()
                assertEquals("external_primary", album.volume); assertNotNull(catalog.accessEpoch)
                val job = workflow.freeze(catalog, album)
                assertEquals("sealed", job.phase); assertEquals(2, f.provider.opens.size)
                val source = workflow.source(job, catalog, album)
                assertEquals("1:90", source.galleryOrigins!!.entries.single().nativeMember)
                assertEquals(source.manifest.files.single().id, source.galleryOrigins!!.entries.single().fileId)
                assertEquals(source.manifest.fingerprint, DeviceFileOfferEnvelope.validate(source.offerMessage(), "sender_fixture_01", f.receiver.peerId).fingerprint)
                File(f.root, "source.bin").writeText("changed live photo")
                assertArrayEquals("hello".toByteArray(), source.readChunk(source.manifest.files.single().id, 0))
                assertEquals(2, f.provider.opens.size)
                workflow.configure(saved, false, emptySet())
                assertThrows(PhotoFolderScopeError::class.java) { source.offerMessage() }
                workflow.retireCached(job)
                assertTrue(workflow.jobs().isEmpty()); assertEquals("changed live photo", File(f.root, "source.bin").readText())
            } finally { workflow.close(); activity.pause().stop().destroy() }
        }
    }

    @Test fun nativeWorkflowHoldsFailedReservationAndOnlyItsExactFailureCanDiscardOwnedPrivateCache() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { }
                activity.start().resume()
                val catalog = workflow.discover(); val album = catalog.albums.single()
                File(f.root, "source.bin").writeText("bad")
                val error = assertThrows(GalleryPhotoBuildFailure::class.java) { workflow.freeze(catalog, album) }
                val held = workflow.jobs().single()
                assertEquals(error.reservationId, held.id); assertEquals("reserved", held.phase); assertEquals(5L, held.plainBytes)
                assertThrows(PhotoFolderScopeError::class.java) { workflow.source(held, catalog, album) }
                val forged = GalleryPhotoBuildFailure(error.reservationId, java.io.IOException("foreign failure"))
                assertThrows(PhotoFolderScopeError::class.java) { workflow.discardFailedBuild(forged) }
                assertEquals(held, workflow.jobs().single())
                workflow.discardFailedBuild(error)
                assertTrue(workflow.jobs().isEmpty()); assertEquals("bad", File(f.root, "source.bin").readText())
            } finally { workflow.close(); activity.pause().stop().destroy() }
        }
    }

    @Test fun nativeOpaqueAlbumSelectionJoinsActualDiscoveryAndFrozenReadOnlyPfdWithoutTrustingWirePaths() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "selectable-workflow-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                val enabled = workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { throw AssertionError("No automatic permission prompt") }
                activity.start().resume()
                val catalog = workflow.discoverSelectable()
                val page = catalog.page()
                assertTrue(f.provider.opens.isEmpty()) // Listing metadata never opens any image bytes.
                val selection = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                val job = workflow.freeze(selection)
                assertEquals("sealed", job.phase); assertEquals(2, f.provider.opens.size)
                assertNull(Shadows.shadowOf(activity.get()).lastRequestedPermission)
                workflow.configure(enabled, false, emptySet())
                assertThrows(PhotoFolderScopeError::class.java) { catalog.page() }
                assertThrows(PhotoFolderScopeError::class.java) { workflow.freeze(selection) }
                workflow.retireCached(job)
                assertEquals("hello", File(f.root, "source.bin").readText())
            } finally { workflow.close(); activity.pause().stop().destroy() }
        }
    }

    @Test fun wireDiscoveryAndPagingReturnActualNativeAlbumMetadataWithoutOpeningPhotoBytesOrPrompting() {
        Fixture().use { f ->
            val now = 1_800_000_000_000L
            val root = Files.createTempDirectory(f.root.toPath(), "wire-catalog-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val output = ByteArrayOutputStream(); val key = ByteArray(32) { 3 }; val prefix = ByteArray(4) { 4 }
            val channel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output, ByteArray(16), key.copyOf(), prefix, ByteArray(32), ByteArray(4))
            val identity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
            val peer = NativeFileControlPeer(f.receiver.peerId, f.receiver.identitySha256, channel, true, true, true, true, true, "1".repeat(64))
            val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, peer.pairingEpoch)
            val pcState = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
            val desktop = NativeFileControlSession(NativeFileControlIdentity(peer.peerId, peer.identitySha256), { pcPeer }, { pcState })
            val runtime = NativeGalleryFileRuntime(f.context, root, identity, protection, channel, { peer }, { true })
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val host = GalleryPhotoPermissionHost(activity.get())
            try {
                runtime.attachPermissionHost(host) { throw AssertionError("Metadata cannot request OS permissions") }
                activity.start().resume()
                fun drain(): List<JsonObject> {
                    val input = ByteArrayInputStream(output.toByteArray()); output.reset(); val messages = mutableListOf<JsonObject>()
                    while (input.available() > 0) {
                        val frame = TelefonRahmen.lesen(input); val header = JsonObject(frame - "ciphertext")
                        val cipher = java.util.Base64.getDecoder().decode(frame.string("ciphertext"))
                        val clear = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")), cipher, TelefonKanonisch.bytes(header))
                        messages += Json.parseToJsonElement(clear.decodeToString()).jsonObject
                    }
                    return messages
                }
                fun echo() {
                    if (runtime.sendControls(now)) drain().forEach { desktop.observeRemote(DeviceFileControlEnvelope.validate(it, now), pcPeer) }
                    val packet = desktop.packet(); desktop.markSent(packet)
                    runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
                    if (runtime.sendControls(now)) drain().forEach { desktop.observeRemote(DeviceFileControlEnvelope.validate(it, now), pcPeer) }
                }
                fun request(operation: String, version: String, catalogId: String? = null) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", 1); put("operation", operation); put("expected_version", version)
                    if (catalogId != null) { put("catalog_id", catalogId); put("after", 0) }
                }, 60_000, now)
                echo()
                assertThrows(PhotoFolderScopeError::class.java) {
                    runtime.receiveSourceCommand(request("discover", runtime.savedPolicy().version), channel::send, { now })
                }
                assertTrue(f.provider.requests.isEmpty())
                runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                val version = runtime.savedPolicy().version
                runtime.receiveSourceCommand(request("discover", version), channel::send, { now })
                val response = drain().single()
                assertEquals(DeviceFileSourceCommand.CATALOG, response.string("kind"))
                assertTrue(TelefonKanonisch.bytes(response).size <= DeviceFileControl.MAX_WIRE_BYTES)
                val page = response["body"]!!.jsonObject["page"]!!.jsonObject
                assertEquals("Camera", page["albums"]!!.jsonArray.single().jsonObject.string("display_name"))
                assertEquals(JsonPrimitive(false), page["proves_deletion"])
                assertTrue(f.provider.opens.isEmpty()); assertNull(Shadows.shadowOf(activity.get()).lastRequestedPermission)
                runtime.receiveSourceCommand(request("catalog_page", version, page.string("catalog_id")), channel::send, { now })
                assertEquals(page, drain().single()["body"]!!.jsonObject["page"])
                runtime.receiveSourceCommand(request("discover", version), channel::send, { now }); drain()
                assertThrows(PhotoFolderScopeError::class.java) {
                    runtime.receiveSourceCommand(request("catalog_page", version, page.string("catalog_id")), channel::send, { now })
                }
                assertTrue(f.provider.opens.isEmpty())
                Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
                val read = request("request_read", version)
                val sharedReceipts = NativeGalleryPermissionCommands()
                runtime.receiveSourceCommand(read, channel::send, { now }, sharedReceipts)
                val permission = drain().single()
                assertEquals(DeviceFileSourceCommand.PERMISSION_RESULT, permission.string("kind"))
                assertEquals("requested", permission["body"]!!.jsonObject.string("state"))
                assertEquals(setOf("format", "request_id", "operation", "version", "state"), permission["body"]!!.jsonObject.keys)
                val pending = Shadows.shadowOf(activity.get()).lastRequestedPermission!!
                runtime.receiveSourceCommand(read, channel::send, { now }, sharedReceipts)
                assertEquals("requested", drain().single()["body"]!!.jsonObject.string("state"))
                assertSame(pending, Shadows.shadowOf(activity.get()).lastRequestedPermission)
                assertTrue(f.provider.opens.isEmpty())
            } finally { runtime.close(); host.close(); activity.pause().stop().destroy(); desktop.close(); channel.close() }
        }
    }

    @Test fun explicitNativeWorkerPreparesActualReadOnlyPfdSnapshotOffMainAndKeepsCacheUntilExplicitRetirement() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "native-worker-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            val ended = java.util.concurrent.CountDownLatch(1)
            val worker = NativeGallerySourceWorker({ selected, cancellation ->
                assertNotSame(android.os.Looper.getMainLooper(), android.os.Looper.myLooper())
                workflow.freeze(selected, cancellation)
            }, { ended.countDown() })
            var catalog: NativeGalleryAlbumCatalog? = null
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { throw AssertionError("Worker must not request permissions") }
                activity.start().resume()
                val discovered = workflow.discoverSelectable(); catalog = discovered
                val page = discovered.page()
                val selected = discovered.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                assertTrue(f.provider.opens.isEmpty()); assertTrue(worker.isQuiescent)
                val run = worker.start(selected)
                assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertNull(run.nativeFailure())
                assertTrue(run.ioEnded); assertEquals("snapshot_ready", run.phase); assertTrue(worker.isQuiescent)
                val job = run.snapshotJob()!!
                assertEquals(job, workflow.jobs().single()) // I/O end is not quota retirement.
                assertEquals("sealed", job.phase); assertEquals(2, f.provider.opens.size)
                val source = workflow.source(job, selected.catalog.source, selected.album, selected.desktopChoice)
                File(f.root, "source.bin").writeText("keep changed original")
                assertArrayEquals("hello".toByteArray(), source.readChunk(source.manifest.files.single().id, 0))
                assertEquals(1, workflow.jobs().size)
                workflow.retireCached(job) // Explicit native cleanup only after real preparation I/O ended.
                assertTrue(workflow.jobs().isEmpty())
                assertEquals("keep changed original", File(f.root, "source.bin").readText())
                assertNull(Shadows.shadowOf(activity.get()).lastRequestedPermission)
            } finally {
                worker.close()
                if (!worker.isQuiescent) assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                catalog?.close(); workflow.close(); activity.pause().stop().destroy()
            }
        }
    }

    @Test fun runtimeAndConnectionKeepSourceIndexOwnershipUntilBlockedProviderIoActuallyEnds() {
        for (mode in listOf("connection_pending", "runtime_pending", "completed")) {
            Fixture().use { f ->
                val now = 1_800_000_000_000L
                val root = Files.createTempDirectory(f.root.toPath(), "runtime-worker-").toFile()
                val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
                val output = ByteArrayOutputStream(); val key = ByteArray(32) { 3 }; val prefix = ByteArray(4) { 4 }
                val channel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output, ByteArray(16), key.copyOf(), prefix, ByteArray(32), ByteArray(4))
                val identity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
                val peer = NativeFileControlPeer(f.receiver.peerId, f.receiver.identitySha256, channel, true, true, true, true, true, "1".repeat(64))
                val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, peer.pairingEpoch)
                val pcState = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
                val desktop = NativeFileControlSession(NativeFileControlIdentity(peer.peerId, peer.identitySha256), { pcPeer }, { pcState })
                val runtime = NativeGalleryFileRuntime(f.context, root, identity, protection, channel, { peer }, { true })
                val released = java.util.concurrent.atomic.AtomicInteger()
                val connection = if (mode != "runtime_pending") NativeGalleryFileConnection(channel) { released.incrementAndGet() }.also { it.bind(runtime) } else null
                val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
                val host = GalleryPhotoPermissionHost(activity.get())
                val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
                val completed = java.util.concurrent.CountDownLatch(1)
                var run: NativeGallerySourceRun? = null
                var catalog: NativeGalleryAlbumCatalog? = null
                try {
                    // Observe completion without replacing the actual runtime's
                    // native I/O-end/final-close callback behavior.
                    val workerField = NativeGalleryFileRuntime::class.java.getDeclaredField("sourceWorker").also { it.isAccessible = true }
                    val worker = workerField.get(runtime) as NativeGallerySourceWorker
                    val endedField = NativeGallerySourceWorker::class.java.getDeclaredField("onEnded").also { it.isAccessible = true }
                    @Suppress("UNCHECKED_CAST") val original = endedField.get(worker) as (NativeGallerySourceRun) -> Unit
                    endedField.set(worker, { value: NativeGallerySourceRun -> try { original(value) } finally { completed.countDown() } })
                    runtime.attachPermissionHost(host) { throw AssertionError("Preparation cannot prompt") }
                    activity.start().resume()
                    fun toDesktop() {
                        if (!runtime.sendControls(now)) return
                        val frame = TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray())); output.reset()
                        val header = JsonObject(frame - "ciphertext")
                        val clear = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")),
                            java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header))
                        desktop.observeRemote(DeviceFileControlEnvelope.validate(Json.parseToJsonElement(clear.decodeToString()).jsonObject, now), pcPeer)
                    }
                    fun echo() {
                        toDesktop(); val packet = desktop.packet(); desktop.markSent(packet)
                        runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now); toDesktop()
                    }
                    echo(); runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                    val discovered = runtime.discoverSelectable(); catalog = discovered
                    val page = discovered.page()
                    val selected = discovered.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                    f.provider.onOpen = {
                        entered.countDown()
                        if (mode != "completed") check(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    }
                    val started = runtime.prepareSource(selected); run = started
                    assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    if (mode != "completed") {
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.prepareSource(selected) }
                        started.cancellation.setOnCancelListener {
                            assertFalse("Native cancellation ran under runtime ownership", Thread.holdsLock(runtime))
                        }
                        if (connection != null) connection.close()
                        else assertEquals("gallery_source_worker_io_pending", assertThrows(PhotoFolderScopeError::class.java) { runtime.close() }.code)
                        assertFalse(started.ioEnded); assertTrue(started.cancelRequested)
                        assertEquals(0, released.get())
                        assertNotNull(runtime.savedPolicy().policy) // Source DB is still owned/open.
                        assertNull(runtime.currentRequest())
                        release.countDown()
                    }
                    assertTrue(completed.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    assertTrue(started.ioEnded)
                    if (mode == "completed") {
                        assertEquals("snapshot_ready", started.phase); assertNotNull(started.snapshotJob())
                        assertNotNull(runtime.savedPolicy().policy); assertEquals(0, released.get())
                        connection!!.close()
                    } else {
                        assertEquals("canceled_held", started.phase); assertNull(started.snapshotJob())
                    }
                    Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                    assertThrows(PhotoFolderScopeError::class.java) { runtime.savedPolicy() }
                    assertEquals(if (connection == null) 0 else 1, released.get())
                    connection?.close()
                    assertEquals(if (connection == null) 0 else 1, released.get())
                    PhotoSourceJobIndex(root, protection).use { held ->
                        assertEquals(1, held.jobs().size) // Closing I/O ownership does not retire cache quota.
                        assertEquals(if (mode == "completed") "sealed" else "reserved", held.jobs().single().phase)
                    }
                    assertEquals("hello", File(f.root, "source.bin").readText())
                } finally {
                    release.countDown(); runtime.revokeControl()
                    if (run != null) assertTrue(completed.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                    connection?.close(); runtime.close(); catalog?.close(); host.close()
                    activity.pause().stop().destroy(); desktop.close(); channel.close()
                }
            }
        }
    }

    @Test fun closingNativeConnectionDoesNotBlockTheUiBehindAnInFlightAlbumProviderQuery() {
        Fixture().use { f ->
            val now = 1_800_000_000_000L
            val root = Files.createTempDirectory(f.root.toPath(), "runtime-query-close-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val output = ByteArrayOutputStream(); val key = ByteArray(32) { 3 }; val prefix = ByteArray(4) { 4 }
            val channel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output, ByteArray(16), key.copyOf(), prefix, ByteArray(32), ByteArray(4))
            val identity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
            val peer = NativeFileControlPeer(f.receiver.peerId, f.receiver.identitySha256, channel, true, true, true, true, true, "1".repeat(64))
            val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, peer.pairingEpoch)
            val pcState = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
            val desktop = NativeFileControlSession(NativeFileControlIdentity(peer.peerId, peer.identitySha256), { pcPeer }, { pcState })
            val runtime = NativeGalleryFileRuntime(f.context, root, identity, protection, channel, { peer }, { true })
            val released = java.util.concurrent.atomic.AtomicInteger()
            val connection = NativeGalleryFileConnection(channel) { released.incrementAndGet() }.also { it.bind(runtime) }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create(); val host = GalleryPhotoPermissionHost(activity.get())
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
            val closeReturned = java.util.concurrent.CountDownLatch(1); val queryEnded = java.util.concurrent.CountDownLatch(1)
            val uiBlocked = java.util.concurrent.atomic.AtomicBoolean(false); val replies = java.util.concurrent.atomic.AtomicInteger()
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            var query: Thread? = null; var guard: Thread? = null
            try {
                runtime.attachPermissionHost(host) { throw AssertionError("Metadata cannot prompt") }; activity.start().resume()
                fun toDesktop() {
                    if (!runtime.sendControls(now)) return
                    val frame = TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray())); output.reset()
                    val header = JsonObject(frame - "ciphertext")
                    val clear = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")),
                        java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header))
                    desktop.observeRemote(DeviceFileControlEnvelope.validate(Json.parseToJsonElement(clear.decodeToString()).jsonObject, now), pcPeer)
                }
                fun echo() {
                    toDesktop(); val packet = desktop.packet(); desktop.markSent(packet)
                    runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now); toDesktop()
                }
                echo(); runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                val version = runtime.savedPolicy().version
                val request = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", 1); put("operation", "discover"); put("expected_version", version)
                }, 60_000, now)
                f.provider.onQuery = { entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                query = Thread {
                    try { runtime.receiveSourceCommand(request, { replies.incrementAndGet() }, { now }) }
                    catch (error: Throwable) { failure.set(error) }
                    finally { queryEnded.countDown() }
                }.also { it.start() }
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                guard = Thread {
                    try { uiBlocked.set(!closeReturned.await(500, java.util.concurrent.TimeUnit.MILLISECONDS)) }
                    finally { release.countDown() }
                }.also { it.start() }
                connection.close(); closeReturned.countDown()
                assertTrue(queryEnded.await(5, java.util.concurrent.TimeUnit.SECONDS)); guard.join(5000); query.join(5000)
                assertFalse("UI close waited behind the blocked album provider query", uiBlocked.get())
                assertEquals(0, replies.get()); assertTrue(failure.get() is PhotoFolderScopeError)
                Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                assertEquals(1, released.get()); assertThrows(PhotoFolderScopeError::class.java) { runtime.savedPolicy() }
                assertTrue(f.provider.opens.isEmpty())
            } finally {
                release.countDown(); closeReturned.countDown()
                query?.let { assertTrue(queryEnded.await(5, java.util.concurrent.TimeUnit.SECONDS)); it.join(5000) }; guard?.join(5000)
                Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                connection.close(); runtime.close(); host.close(); activity.pause().stop().destroy(); desktop.close(); channel.close()
            }
        }
    }

    @Test fun nativeWorkflowRejectsCatalogCapturedBeforeResumeWithoutOpeningContentsOrReservingQuota() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { }
                activity.start().resume()
                val catalog = workflow.discover(); val album = catalog.albums.single()
                activity.pause().stop().restart().start().resume()
                assertEquals("gallery_source_visibility_changed", assertThrows(PhotoFolderScopeError::class.java) { workflow.freeze(catalog, album) }.code)
                assertTrue(workflow.jobs().isEmpty()); assertTrue(f.provider.opens.isEmpty())
                val fresh = workflow.discover()
                assertNotEquals(catalog.accessEpoch, fresh.accessEpoch)
            } finally { workflow.close(); activity.pause().stop().destroy() }
        }
    }

    @Test fun boundedPagesEnumerateOnlyTheSelectedAlbumWithoutOpeningContents() {
        Fixture().use { f ->
            f.provider.rows = (1..70).map { Row(id = it.toLong(), name = "image-$it.jpg") } + Row(id = 100, bucket = "private")
            val inventory = f.reader.enumerate(f.lease())
            assertEquals(70, inventory.entries.size); assertEquals(3, f.provider.requests.size)
            assertEquals("1:90", inventory.entries.first().documentId)
            assertEquals(100_000L, inventory.entries.first().advertisedModifiedMs)
            assertTrue(f.provider.opens.isEmpty()); assertFalse((inventory.lease as GalleryPhotoSourceLease).provesFileDeletion)
            assertThrows(UnsupportedOperationException::class.java) { (inventory.entries as MutableList<PhotoInventoryEntry>).clear() }
        }
    }

    @Test fun actualReadPfdFeedsEncryptedSnapshotAndDurableIndexRestoreWithoutLiveReopen() {
        Fixture().use { f ->
            val lease = f.lease(); val inventory = f.reader.enumerate(lease)
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val job: PhotoSourceJob
            val cache = Files.createTempDirectory(f.root.toPath(), "cache-").toFile()
            PhotoSourceJobIndex(cache, protection).use { index ->
                val reserved = index.reserve(inventory, f.scope)
                val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, f.reader, protection)
                job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
            }
            assertEquals(2, f.provider.opens.size)
            File(f.root, "source.bin").writeText("changed")
            PhotoSourceJobIndex(cache, protection).use { index ->
                val restored = index.restore(job, "sender_fixture_01", f.scope, lease)
                assertArrayEquals("hello".toByteArray(), restored.readChunk(restored.manifest.files.single().id, 0))
                assertEquals(2, f.provider.opens.size)
                restored.retireAndDiscard(); assertTrue(index.jobs().isEmpty())
            }
        }
    }

    @Test fun nativeControllerLifecycleRotatesActualGalleryLeasesEvenWithUnchangedOsReadFlags() {
        Fixture().use { f ->
            val controller = GalleryPhotoAccessController(f.context, { f.request })
            controller.onResume()
            val scope = GalleryPhotoSourceScope({ f.request }, controller.environment)
            val catalog = GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(f.album), f.request)
            val lease = scope.capture(catalog, f.album)
            assertTrue(scope.isCurrent(lease))
            controller.onPause(); controller.onResume()
            assertFalse(scope.isCurrent(lease))
            val resumed = scope.capture(catalog, f.album)
            assertNotEquals(lease.readGrantToken, resumed.readGrantToken)
            assertTrue(scope.isCurrent(resumed))
            controller.onAccessChanged(); assertFalse(scope.isCurrent(resumed))
            val refreshed = scope.capture(catalog, f.album)
            controller.close(); assertFalse(scope.isCurrent(refreshed))
            assertTrue(f.provider.opens.isEmpty())
            assertEquals(GalleryReadCoverage.FULL_IMAGES, AndroidGalleryReadPermissions.observe(f.context))
        }
    }

    @Test fun obsoleteGalleryScopeCanCleanOnlyItsAuthenticatedPrivateSnapshotWithoutLivePhotoAccess() {
        Fixture().use { f ->
            val lease = f.lease(); val inventory = f.reader.enumerate(lease)
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val cache = Files.createTempDirectory(f.root.toPath(), "cache-").toFile()
            val job: PhotoSourceJob
            PhotoSourceJobIndex(cache, protection).use { index ->
                val reserved = index.reserve(inventory, f.scope)
                val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, f.reader, protection)
                job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
            }
            val opens = f.provider.opens.size
            Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
            f.request = null
            PhotoSourceJobIndex(cache, protection).use { index ->
                assertThrows(PhotoFolderScopeError::class.java) { index.restore(job, "sender_fixture_01", f.scope, lease) }
                index.retireCachedSnapshot(job)
                assertTrue(index.jobs().isEmpty()); assertFalse(index.rootFile(job).exists())
            }
            assertEquals(opens, f.provider.opens.size); assertEquals("hello", File(f.root, "source.bin").readText())
        }
    }

    @Test fun foreignMembershipUnsafeNamesPendingAndMalformedMetadataRejectTheWholeInventory() {
        val bad = listOf(Row(bucket = "other"), Row(label = "Private"), Row(path = "Pictures/Private/"), Row(pending = 1),
            Row(name = "../escape.jpg"), Row(bytes = -1), Row(mime = "text/plain"), Row(modified = "100"),
            Row(modified = Long.MAX_VALUE), Row(added = -1), Row(id = 0))
        bad.forEach { row -> Fixture().use { f ->
            f.provider.ignoreSelection = true; f.provider.rows = listOf(row)
            assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(f.lease()) }
            assertTrue(f.provider.opens.isEmpty())
        } }
    }

    @Test fun duplicateAliasesOversizedInventoriesAndProviderPageViolationsNeverReturnSubsets() {
        for (mode in listOf("alias", "count", "page", "order", "size", "total")) Fixture().use { f ->
            f.provider.rows = when (mode) {
                "alias" -> listOf(Row(), Row(id = 2, name = "IMAGE.JPG"))
                "count" -> (1..129).map { Row(id = it.toLong(), name = "$it.jpg") }
                "page" -> { f.provider.ignoreLimit = true; (1..33).map { Row(id = it.toLong(), name = "$it.jpg") } }
                "order" -> { f.provider.reverse = true; listOf(Row(), Row(id = 2, name = "two.jpg")) }
                "size" -> listOf(Row(bytes = DeviceFileManifest.MAX_FILE_BYTES + 1))
                else -> (1..9).map { Row(id = it.toLong(), name = "$it.jpg", bytes = DeviceFileManifest.MAX_FILE_BYTES) }
            }
            assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(f.lease()) }
            assertTrue(f.provider.opens.isEmpty())
        }
    }

    @Test fun queryRevocationCancellationAndMidStreamRevocationCloseBoundaries() {
        for (cancel in listOf(false, true)) Fixture().use { f ->
            val lease = f.lease(); val cancellation = CancellationSignal()
            f.provider.onQuery = { if (cancel) cancellation.cancel() else f.request = null }
            if (cancel) assertThrows(OperationCanceledException::class.java) { f.reader.enumerate(lease, cancellation) }
            else assertEquals("gallery_inventory_source_revoked", assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(lease) }.code)
        }
        Fixture().use { f ->
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            f.reader.openRead(lease, entry, CancellationSignal()).use { input ->
                assertEquals('h'.code, input.read())
                Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
                assertEquals("gallery_inventory_source_revoked", assertThrows(PhotoFolderScopeError::class.java) { input.read() }.code)
            }
        }
    }

    @Test fun replacedRowAndForgedUrisCannotOpenAnUnselectedPhoto() {
        Fixture().use { f ->
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            f.provider.rows = listOf(Row(added = 91))
            assertEquals("gallery_inventory_member_changed", assertThrows(PhotoFolderScopeError::class.java) {
                f.reader.openRead(lease, entry, CancellationSignal()) }.code)
            for (forged in listOf(entry.copy(documentUri = "content://media/external_primary/images/media/2"),
                entry.copy(documentId = "01:90"), entry.copy(relativePath = "other.jpg")))
                assertThrows(PhotoFolderScopeError::class.java) { f.reader.openRead(lease, forged, CancellationSignal()) }
            assertTrue(f.provider.opens.isEmpty())
        }
    }

    @Test @Config(sdk = [35]) fun nativeProviderInsertionGenerationSurvivesCropsWhileModificationRevisionChanges() {
        Fixture().use { f ->
            f.provider.rows = listOf(Row(generationAdded = 7L, generationModified = 9L))
            val lease = f.lease(); val inventory = f.reader.enumerate(lease)
            assertEquals("1:90:7", inventory.entries.single().documentId)
            assertEquals("9", inventory.entries.single().nativeRevision)
            val cache = Files.createTempDirectory(f.root.toPath(), "generation-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            PhotoSourceJobIndex(cache, protection).use { index ->
                fun freeze(value: PhotoSourceInventory): PhotoSourceJob {
                    val reserved = index.reserve(value, f.scope)
                    val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), value, "sender_fixture_01", f.scope, f.reader, protection)
                    return index.publishSnapshot(reserved, snapshot, f.scope, lease)
                }
                val first = freeze(inventory)
                val before = index.restore(first, "sender_fixture_01", f.scope, lease)
                assertTrue(before.galleryOrigins!!.hasNativeInsertionWitness)
                assertFalse(before.galleryOrigins!!.provesMutationIdentity)
                val origin = before.galleryOrigins!!.entries.single()
                f.provider.rows = listOf(Row(generationAdded = 7L, generationModified = 10L)) // Same size, coarse mtime and bytes.
                assertEquals("gallery_inventory_member_changed", assertThrows(PhotoFolderScopeError::class.java) {
                    f.reader.verifyMetadata(lease, inventory.entries.single(), CancellationSignal()) }.code)
                f.provider.rows = listOf(Row(bytes = 3, generationAdded = 7L, generationModified = 10L))
                File(f.root, "source.bin").writeText("hey")
                val second = freeze(f.reader.enumerate(lease))
                val after = index.restore(second, "sender_fixture_01", f.scope, lease)
                assertEquals(origin.photoId, after.galleryOrigins!!.entries.single().photoId)
                assertEquals("10", after.galleryOrigins!!.entries.single().nativeRevision)
                assertNotEquals(before.manifest.files.single().sha256, after.manifest.files.single().sha256)
                assertArrayEquals("hello".toByteArray(), before.readChunk(before.manifest.files.single().id, 0))
                assertArrayEquals("hey".toByteArray(), after.readChunk(after.manifest.files.single().id, 0))
                index.retireCachedSnapshot(first); index.retireCachedSnapshot(second)
            }
            assertEquals("hey", File(f.root, "source.bin").readText())
        }
    }

    @Test @Config(sdk = [35]) fun malformedOrUnknownNativeGenerationsNeverManufactureAnInsertionWitness() {
        for (row in listOf(Row(generationAdded = -1L), Row(generationAdded = 8L, generationModified = 7L),
            Row(generationAdded = "1"), Row(generationModified = "1"))) Fixture().use { f ->
            f.provider.rows = listOf(row)
            assertEquals("gallery_inventory_invalid_metadata", assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(f.lease()) }.code)
            assertTrue(f.provider.opens.isEmpty())
        }
        Fixture().use { f ->
            f.provider.rows = listOf(Row(generationAdded = 0L, generationModified = 0L))
            val lease = f.lease(); val inventory = f.reader.enumerate(lease)
            val root = Files.createTempDirectory(f.root.toPath(), "unknown-generation-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val snapshot = ProtectedPhotoSourceSnapshot.freeze(root, inventory, "sender_fixture_01", f.scope, f.reader, protection)
            assertFalse(snapshot.galleryOrigins!!.hasNativeInsertionWitness)
            assertFalse(snapshot.galleryOrigins!!.provesMutationIdentity)
            snapshot.discard()
        }
    }

    @Test @Config(sdk = [28]) fun legacyMediaColumnsStillUseActualReadPfdWithoutInventingAVolumeNamespace() {
        Fixture().use { f ->
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            assertNull(lease.access.mediaStoreVersion)
            assertEquals("content://media/external/images/media/1", entry.documentUri)
            f.reader.openRead(lease, entry, CancellationSignal()).use { assertArrayEquals("hello".toByteArray(), it.readBytes()) }
        }
    }

    @Test @Config(sdk = [35]) fun actualModernReadPermissionExcludesPendingAndTrashedImagesAndRejectsProviderViolations() {
        Fixture().use { f ->
            val lease = f.lease()
            f.provider.rows = listOf(Row(), Row(id = 2, name = "pending.jpg", pending = 1), Row(id = 3, name = "trashed.jpg", trashed = 1))
            assertEquals(1, f.reader.enumerate(lease).entries.size)
            f.provider.ignoreSelection = true
            assertEquals("gallery_inventory_album_changed", assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(lease) }.code)
            f.provider.rows = listOf(Row(trashed = 1))
            assertEquals("gallery_inventory_album_changed", assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(lease) }.code)
            assertTrue(f.provider.opens.isEmpty())
        }
    }
}
