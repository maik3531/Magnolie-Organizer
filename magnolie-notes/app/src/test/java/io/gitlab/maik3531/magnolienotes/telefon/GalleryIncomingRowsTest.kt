package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Intent
import android.content.res.AssetFileDescriptor
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Environment
import android.os.Process
import android.os.ParcelFileDescriptor
import android.os.storage.StorageManager
import android.provider.MediaStore
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.Before
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import org.robolectric.shadows.StorageVolumeBuilder
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class GalleryIncomingRowsTest {
    @Before fun mountedPrimaryVolume() {
        val app = RuntimeEnvironment.getApplication()
        val storage = Shadows.shadowOf(app.getSystemService(StorageManager::class.java))
        storage.resetStorageVolumeList()
        storage.addStorageVolume(StorageVolumeBuilder("primary", File("/storage/emulated/0"), "Synthetic primary",
            Process.myUserHandle(), Environment.MEDIA_MOUNTED).setIsPrimary(true).setIsEmulated(true).build())
        assertTrue(MediaStore.VOLUME_EXTERNAL_PRIMARY in MediaStore.getExternalVolumeNames(app))
    }
    private val fileId = "1".repeat(32)
    private fun manifest(pc: String, kind: GalleryMediaType = GalleryMediaType.IMAGES, raw: ByteArray? = null) = DeviceFileManifest.parse(buildJsonObject {
        val size = raw?.size ?: 5
        val hash = raw?.let { java.security.MessageDigest.getInstance("SHA-256").digest(it).joinToString("") { byte -> "%02x".format(byte) } } ?: "a".repeat(64)
        put("format", 1); put("chunk_bytes", 65536); put("total_bytes", size)
        put("transfer_id", "2".repeat(32)); put("source_id", "3".repeat(32)); put("sender_id", pc); put("receiver_id", "phone_fixture_0001")
        put("files", JsonArray(listOf(buildJsonObject { put("id", fileId); put("path", if (kind == GalleryMediaType.IMAGES) "album/original.jpg" else "album/original.mp4"); put("size", size); put("sha256", hash) })))
    })
    private fun intent(kind: GalleryMediaType = GalleryMediaType.IMAGES, twoWay: Boolean = true,
        collectionMode: String = "entire_collection", photosOnly: Boolean = false): MediaSyncTransport.IntentToken {
        val a = "11111111-1111-4111-8111-111111111111"; val b = "22222222-2222-4222-8222-222222222222"
        var body = MediaSyncSettings.change(MediaSyncSettings.create(a), a, b, "enabled", JsonPrimitive(true))
        body = MediaSyncSettings.change(body, a, b, "collection_mode", JsonPrimitive(collectionMode))
        if (photosOnly) body = MediaSyncSettings.change(body, a, b, "photos_only", JsonPrimitive(true))
        if (twoWay) body = MediaSyncSettings.change(body, a, b, "direction", JsonPrimitive("two_way"))
        if (kind == GalleryMediaType.VIDEO) {
            body = MediaSyncSettings.change(body, a, b, "videos_enabled", JsonPrimitive(true))
            body = MediaSyncSettings.change(body, a, b, "photos_enabled", JsonPrimitive(false))
        }
        return MediaSyncTransport.IntentToken(body)
    }
    internal class Provider(private val app: Application, private val kind: GalleryMediaType = GalleryMediaType.IMAGES,
        private val payload: File? = null) : ContentProvider() {
        var inserts = 0
        var namespace = "incoming-provider-v1"
        var afterInsert: () -> Unit = {}
        var wrongOwner = false
        var generation = 10L
        var pending = 1L
        var writeOpens = 0
        var readOpens = 0
        var failReadback = false
        var corruptReadback: File? = null
        var allowPublish = false
        var publishes = 0
        var afterPublish: () -> Unit = {}
        var beforeQuery: () -> Unit = {}
        private var lastSize = 0L
        private var values: ContentValues? = null
        init { attachInfo(app, ProviderInfo().apply { authority = "media"; exported = true }) }
        override fun onCreate() = true
        override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
            check(method == "get_version"); return Bundle().apply { putString(Intent.EXTRA_TEXT, namespace) }
        }
        override fun insert(uri: Uri, values: ContentValues?): Uri {
            check(uri.toString() == "content://media/external_primary/${kind.uriSegment}/media")
            this.values = ContentValues(values!!); inserts++; afterInsert()
            return Uri.withAppendedPath(uri, "99")
        }
        override fun query(uri: Uri, projection: Array<out String>?, queryArgs: Bundle?, cancellationSignal: CancellationSignal?): Cursor {
            beforeQuery()
            check(uri.toString() == "content://media/external_primary/${kind.uriSegment}/media/99")
            val v = values!!
            val size = payload?.length() ?: 0L
            if (size != lastSize) { generationModified++; lastSize = size }
            val data: Map<String, Any> = mapOf("_id" to 99L, "_display_name" to v.getAsString("_display_name"), "mime_type" to v.getAsString("mime_type"),
                "relative_path" to v.getAsString("relative_path"), "_size" to size, "date_added" to 100L, "generation_added" to generation,
                "generation_modified" to maxOf(generation, generationModified), "is_pending" to pending, "is_trashed" to 0L,
                "owner_package_name" to if (wrongOwner) "foreign.application" else app.packageName)
            return MatrixCursor(projection).apply { addRow(projection!!.map { data.getValue(it) }.toTypedArray()) }
        }
        override fun query(uri: Uri, p: Array<out String>?, s: String?, a: Array<out String>?, o: String?): Cursor = error("Unexpected legacy query")
        override fun getType(uri: Uri): String = "image/jpeg"
        private var generationModified = 10L
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            check(uri.toString() == "content://media/external_primary/${kind.uriSegment}/media/99")
            val file = payload ?: error("Unexpected byte IO")
            if (mode == "w") {
                check(pending == 1L)
                check(file.length() == 0L); writeOpens++
                return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_READ_WRITE)
            }
            check(mode == "r"); readOpens++
            return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).also {
                NativeIncomingMediaInspectionTest.FixtureLinux.files[it.fileDescriptor] = file
            }
        }
        override fun openTypedAssetFile(uri: Uri, mimeType: String, opts: Bundle?): AssetFileDescriptor {
            check(MediaStore.getRequireOriginal(uri))
            check(opts?.getBoolean(MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT) == true)
            if (failReadback) throw java.io.IOException("explicit original readback failure")
            val clean = uri.buildUpon().clearQuery().build()
            return AssetFileDescriptor(corruptReadback?.let { ParcelFileDescriptor.open(it, ParcelFileDescriptor.MODE_READ_ONLY) }
                ?: openFile(clean, "r"), 0, AssetFileDescriptor.UNKNOWN_LENGTH)
        }
        override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?): Int {
            check(allowPublish)
            check(values!!.keySet() == setOf("is_pending") && values.getAsLong("is_pending") == 0L)
            check(selection == "_id = ? AND date_added = ? AND generation_added = ? AND generation_modified = ? AND owner_package_name = ? AND relative_path = ? AND mime_type = ? AND _display_name = ? AND _size = ? AND is_pending = 1 AND is_trashed = 0")
            check(uri.toString() == "content://media/external_primary/${kind.uriSegment}/media/99")
            val v = this.values!!
            check(args!!.toList() == listOf("99", "100", generation.toString(), maxOf(generation, generationModified).toString(), app.packageName,
                v.getAsString("relative_path"), v.getAsString("mime_type"), v.getAsString("_display_name"), payload!!.length().toString()))
            if (pending != 1L || wrongOwner) return 0
            pending = 0; generationModified++; publishes++; afterPublish(); return 1
        }
        override fun delete(uri: Uri, selection: String?, args: Array<out String>?): Int = error("No deletion permitted")
    }

    private fun ready(f: GalleryReceiveConsentTest.Fixture) {
        val consent = f.approve(); f.io { f.controller.grant(f.index.galleryPolicy(), consent) }; f.handshake()
    }

    private fun renewReceiving(f: GalleryReceiveConsentTest.Fixture) {
        f.io { f.controller.revoke(f.index.galleryPolicy(), GalleryMediaType.IMAGES, f.book()) }; f.handshake()
        val consent = f.approve()
        f.io { f.controller.grant(f.index.galleryPolicy(), consent) }; f.handshake()
    }

    @Test fun defaultPhoneInventoryCannotCreatePendingRowsFromAnUnknownPcImage() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(collectionMode = "phone_inventory")
            val before = f.index.galleryPolicy()
            f.io {
                assertEquals("gallery_incoming_inventory_reference_required", assertThrows(PhotoFolderScopeError::class.java) {
                    NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token },
                        manifest(f.pc.deviceId), GalleryMediaType.IMAGES)
                }.code)
            }
            assertEquals(before, f.index.galleryPolicy()); assertEquals(0, provider.inserts)
            assertEquals(0, provider.writeOpens); assertEquals(0, provider.publishes)
        }
    }

    @Test fun legacyUnscopedJournalCannotBeAdoptedOrDuplicatedByANewScopedNativeOwner() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val manifest = manifest(f.pc.deviceId)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                    val legacy = GalleryIncomingPublication.plan(owner.binding, manifest, fileId, owner.pairingEpoch, owner.kind, "image/jpeg")
                    f.index.reserveIncomingPublication(legacy, owner::requireLocal)
                    assertEquals("gallery_incoming_original_changed", assertThrows(PhotoFolderScopeError::class.java) {
                        NativeGalleryIncomingRows(f.app, f.index).prepare(owner, fileId, "image/jpeg")
                    }.code)
                    assertEquals(legacy.body, f.index.incomingPublication(legacy.id)!!.body)
                }
            }
            assertEquals(0, provider.inserts); assertEquals(0, provider.writeOpens)
        }
    }

    @Test fun renewedReceivingConsentCannotInsertAgainForAnAlreadyPublishedOriginalTransfer() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f)
            val bitmap = android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)
            val raw = try { java.io.ByteArrayOutputStream().use { output ->
                check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)); output.toByteArray()
            } } finally { bitmap.recycle() }
            val payload = File(f.root, "same-original-after-regrant.png")
            val provider = Provider(f.app, payload = payload).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val manifest = manifest(f.pc.deviceId, raw = raw)
            val rows = NativeGalleryIncomingRows(f.app, f.index)
            var firstEpoch = ""
            val first = f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                    firstEpoch = owner.binding.permissionEpoch
                    val inserted = rows.prepare(owner, fileId, "image/png")
                    val verified = rows.copyAndVerify(owner, inserted, { index ->
                        raw.copyOfRange(index * 65536, minOf(raw.size, (index + 1) * 65536))
                    })
                    rows.publish(owner, verified)
                }
            }
            assertEquals("published", first.state); assertEquals(1, provider.inserts)
            renewReceiving(f)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { renewed ->
                    assertNotEquals(firstEpoch, renewed.binding.permissionEpoch)
                    assertEquals("gallery_incoming_original_transfer_held", assertThrows(PhotoFolderScopeError::class.java) {
                        rows.prepare(renewed, fileId, "image/png")
                    }.code)
                }
            }
            assertEquals("A renewed control epoch must not cause another provider insertion", 1, provider.inserts)
            assertEquals(first.body, f.index.incomingPublication(first.id)!!.body)
            assertArrayEquals(raw, payload.readBytes()); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }
    }

    @Test fun newRemoteControlSessionCannotRenewAnAdmittedIncomingRowWriterAtTheSamePersistentBinding() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f)
            val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val transfer = manifest(f.pc.deviceId); val rows = NativeGalleryIncomingRows(f.app, f.index)
            val before = f.rows()
            f.io {
                val owner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, transfer, GalleryMediaType.IMAGES)
                val cycleOwner = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, transfer, GalleryMediaType.IMAGES)
                val binding = owner.binding
                val own = f.session.packet(); f.session.markSent(own)
                val remote = NativeFileControlSession::class.java.getDeclaredField("remote").apply { isAccessible = true }.get(f.session) as DeviceFileControlPacket
                assertTrue(f.session.observeRemote(remote.copy(sessionEpoch = "a".repeat(64), sequence = 1, echo = own.challenge), f.peer))
                val echo = f.session.packet(); f.session.markSent(echo)
                assertEquals(binding, f.session.binding(transfer.fingerprint))
                assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(owner, fileId, "image/png") }
                assertEquals(before, f.rows()); assertEquals(0, provider.inserts); assertEquals(0, provider.writeOpens)
                assertTrue(f.session.observeRemote(remote.copy(sequence = remote.sequence + 1, echo = own.challenge), f.peer))
                val returned = f.session.packet(); f.session.markSent(returned)
                assertEquals(binding, f.session.binding(transfer.fingerprint))
                assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(cycleOwner, fileId, "image/png") }
                assertEquals(before, f.rows()); assertEquals(0, provider.inserts)
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, transfer, GalleryMediaType.IMAGES).use { fresh ->
                    assertEquals("inserted", rows.prepare(fresh, fileId, "image/png").state)
                }
            }
            assertEquals(1, provider.inserts); assertEquals(0, provider.writeOpens); assertEquals(0, provider.publishes)
        }
    }

    private fun withPublishedInspection(peerOwner: Any = Any(), pcSource: Boolean = false, paddedBytes: Int = 0, action: (GalleryReceiveConsentTest.Fixture, NativeGalleryIncomingRows,
        Provider, GalleryIncomingPublication, ByteArray, File, MediaSyncTransport.IntentToken) -> Unit) {
        GalleryReceiveConsentTest.Fixture(peerOwner).use { f ->
            ready(f)
            val bitmap = android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)
            val encoded = try { java.io.ByteArrayOutputStream().use { output ->
                check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)); output.toByteArray()
            } } finally { bitmap.recycle() }
            val raw = if (paddedBytes == 0) encoded else encoded.copyOf(paddedBytes.also { require(it >= encoded.size) })
            val payload = File(f.root, "published-read-only.png")
            val provider = Provider(f.app, payload = payload).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val manifest = manifest(f.pc.deviceId, raw = raw)
            val pcOrigins = if (pcSource) mapOf(fileId to GalleryPcMediaOrigin.parse(buildJsonObject {
                put("format", 1); put("origin_sha256", "b".repeat(64)); put("previous_publication_sha256", JsonNull)
            })) else emptyMap()
            val rows = NativeGalleryIncomingRows(f.app, f.index)
            val published = f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES, pcOrigins = pcOrigins).use { owner ->
                    rows.publish(owner, rows.copyAndVerify(owner, rows.prepare(owner, fileId, "image/png"), { chunk ->
                        val start = chunk * DeviceFileManifest.CHUNK_BYTES
                        raw.copyOfRange(start, minOf(raw.size, start + DeviceFileManifest.CHUNK_BYTES))
                    }))
                }
            }
            renewReceiving(f)
            action(f, rows, provider, published, raw, payload, token)
        }
    }

    @Test fun actualPublishedPcRowArchivesWithoutPhoneReadLeaseAndRestoresRawOfflineWithoutRenewingCopyTime() =
        withPublishedInspection(pcSource = true, paddedBytes = DeviceFileManifest.CHUNK_BYTES + 19) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30)
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-archive-").toFile(); val before = f.rows()
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED, f.app.checkSelfPermission(android.Manifest.permission.READ_MEDIA_IMAGES))
            val saved = f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    fun owner() = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    val admitted = owner()
                    assertThrows(PhotoFolderScopeError::class.java) {
                        archive.archivePublishedPc(rows, admitted, permit, CancellationSignal())
                    } // No actual rows-owned verification/IO permit, even with genuine metadata.
                    assertTrue(archive.entries(permit).isEmpty())
                    val entry = rows.archivePublishedPc(admitted, archive, permit)
                    val origin = archive.verifiedOrigin(entry, permit)
                    assertEquals(published.body, origin["publication"]); assertFalse(origin.containsKey("source"))
                    assertEquals(permit.version, origin.string("book_version"))
                    assertTrue(entry.originalBytesVerified); assertFalse(entry.grantsMutationAuthority); assertFalse(entry.isRemoteDeletionReceipt)
                    assertThrows(PhotoFolderScopeError::class.java) { archive.verifiedOriginalOrigin(entry, permit) }
                    val read = NativeGalleryTrashArchive::class.java.getDeclaredMethod("readRecord", String::class.java).apply { isAccessible = true }
                    val record = (read.invoke(archive, entry.id) as Pair<*, *>).second as JsonObject
                    val validate = NativeGalleryTrashArchive::class.java.getDeclaredMethod("validatePcRecord", JsonObject::class.java, JsonObject::class.java).apply { isAccessible = true }
                    val variants = listOf(
                        JsonObject(record + ("sha256" to JsonPrimitive("a".repeat(64)))),
                        JsonObject(record + ("size" to JsonPrimitive(entry.bytes + 1))),
                        JsonObject(record + ("name" to JsonPrimitive("other.png"))),
                        JsonObject(record + ("origin" to JsonObject(origin + ("book_version" to JsonPrimitive("bad"))))),
                        JsonObject(record + ("origin" to JsonObject(origin + ("peer" to JsonPrimitive("other_fixture_01"))))),
                        JsonObject(record + ("origin" to JsonObject(origin + ("member" to JsonPrimitive("999:1:1"))))),
                        JsonObject(record + ("origin" to JsonObject(origin + ("source" to JsonPrimitive("gallery-album-v1:" + "f".repeat(64)))))),
                        JsonObject(record + ("origin" to JsonObject(origin + ("publication" to JsonObject(published.body - "pc_origin"))))),
                        JsonObject(record + ("origin" to JsonObject(origin + ("publication" to JsonObject(published.body + ("state" to JsonPrimitive("inserted")))))))
                    )
                    for (changed in variants) {
                        val error = assertThrows(java.lang.reflect.InvocationTargetException::class.java) {
                            validate.invoke(archive, changed, changed.getValue("origin").jsonObject)
                        }
                        assertTrue(error.cause is PhotoFolderScopeError)
                    }
                    assertEquals(entry, rows.archivePublishedPc(owner(), archive, permit))
                    assertEquals(listOf(entry), archive.entries(permit)); entry
                }
            }
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            f.session.close(); f.index.close(); assertTrue(payload.renameTo(File(payload.parentFile, "retained-pc-source.png")))
            f.documents.setzePapierkorb(false, 30) // OFF preserves existing independent recovery bytes.
            val offline = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            NativeGalleryTrashArchive(root, f.protection, allowCreate = false).use { archive ->
                assertEquals(listOf(saved), archive.entries(offline))
                val restored = java.io.ByteArrayOutputStream()
                archive.readContent(saved, offline) { restored.write(it) }
                assertArrayEquals(raw, restored.toByteArray())
            }
        }

    @Test fun pcArchiveDoesNotRelabelAnOlderNonPcPublication() =
        withPublishedInspection { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30)
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-archive-").toFile(); val before = f.rows(); val reads = provider.readOpens
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(owner, archive, permit) }
                    assertTrue(archive.entries(permit).isEmpty())
                }
            }
            assertEquals(reads, provider.readOpens); assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
        }

    @Test fun pcArchiveTrashOffAndExistingMediaIoLaneDenyBeforeAnyNewProviderRead() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-archive-").toFile(); val before = f.rows(); val reads = provider.readOpens
            f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    fun owner() = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    val off = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
                    assertFalse(off.trashEnabled)
                    assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(owner(), archive, off) }
                    assertTrue(archive.entries(off).isEmpty())
                    f.documents.setzePapierkorb(true, 30)
                    val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }; val lane = Any()
                    assertTrue(NativeGalleryMediaIoLane.acquire(lane))
                    try { assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(owner(), archive, permit) } }
                    finally { NativeGalleryMediaIoLane.release(lane) }
                    assertTrue(archive.entries(permit).isEmpty())
                }
            }
            assertEquals(reads, provider.readOpens); assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
        }

    @Test fun publishedPcArchiveCancellationKeepsItsActualProviderIoLaneUntilTheCopyDrains() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30)
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-archive-").toFile(); val before = f.rows()
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
            val owner = java.util.concurrent.atomic.AtomicReference<NativeGalleryPublishedInspection?>()
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>(); var queries = 0
            provider.beforeQuery = {
                if (++queries == 4) { // Actual archive payload read ended; its final provider query is still outstanding.
                    entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
                }
            }
            val worker = Thread {
                try {
                    f.io {
                        NativeGalleryTrashArchive(root, f.protection).use { archive ->
                            val actual = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                            owner.set(actual); rows.archivePublishedPc(actual, archive, permit)
                        }
                    }
                } catch (error: Throwable) { failure.set(error) }
            }.also { it.start() }
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); owner.get()!!.close()
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
                assertTrue(worker.isAlive)
            } finally { release.countDown(); worker.join(7000); provider.beforeQuery = {} }
            assertFalse(worker.isAlive); assertTrue(failure.get() is PhotoFolderScopeError)
            val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
            NativeGalleryTrashArchive(root, f.protection, allowCreate = false).use { archive -> assertTrue(archive.entries(permit).isEmpty()) }
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun publishedPcArchiveCannotUseAnotherActualBookOrReviveAnOldUnlockedPermit() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30)
            GalleryReceiveConsentTest.Fixture().use { other ->
                other.documents.setzePapierkorb(true, 30)
                val wrongBook = NativeGalleryTrashBookPermit.capture(other.documents) { other.unlocked }
                val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
                val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-archive-").toFile(); val before = f.rows(); val reads = provider.readOpens
                f.io {
                    NativeGalleryTrashArchive(root, f.protection).use { archive ->
                        fun owner() = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                        assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(owner(), archive, wrongBook) }
                        val revoked = owner(); f.unlocked = false
                        assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(revoked, archive, permit) }
                        f.unlocked = true
                        assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(revoked, archive, permit) }
                        assertEquals(reads, provider.readOpens)
                        assertTrue(archive.entries(NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }).isEmpty())
                    }
                }
                assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
        }

    @Test fun publishedPcArchiveRejectsCurrentByteEditsWithoutTouchingProviderOrRetainedIndex() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30)
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-archive-").toFile(); val before = f.rows()
            val edited = raw.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() }; payload.writeBytes(edited)
            f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    assertThrows(PhotoFolderScopeError::class.java) { rows.archivePublishedPc(owner, archive, permit) }
                    assertTrue(archive.entries(permit).isEmpty())
                }
            }
            assertEquals(before, f.rows()); assertArrayEquals(edited, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun renewedBindingInspectsPublishedOriginalReadOnlyWithoutJournalMutationOrAnotherInsert() =
        withPublishedInspection { f, rows, provider, published, raw, payload, token ->
            val before = f.rows(); val reads = provider.readOpens
            f.io {
                assertNotEquals(published.body.getValue("origin").jsonObject.getValue("binding").jsonObject.string("permission_epoch"),
                    f.session.binding(published.body.getValue("origin").jsonObject.string("manifest_sha256"))!!.permissionEpoch)
                val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                assertFalse(owner.grantsWriteAuthority); assertFalse(owner.isSavedReceipt)
                val observation = rows.inspectPublished(owner)
                assertEquals("image/png", observation.mimeType); assertEquals(8, observation.width); assertEquals(8, observation.height)
                assertFalse(observation.grantsWriteAuthority); assertFalse(observation.isSavedReceipt)
                assertThrows(PhotoFolderScopeError::class.java) { rows.inspectPublished(owner) }
            }
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertTrue(provider.readOpens > reads); assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun laterRemoteControlSessionCannotRenewAnAdmittedPublishedInspectionAtTheSamePermissionEpoch() =
        withPublishedInspection { f, rows, provider, published, raw, payload, token ->
            val before = f.rows(); val reads = provider.readOpens
            f.io {
                val destination = published.body.getValue("origin").jsonObject.string("manifest_sha256")
                val binding = f.session.binding(destination)!!
                val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                val cycleOwner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                owner.requireCurrent()
                val own = f.session.packet(); f.session.markSent(own)
                val field = NativeFileControlSession::class.java.getDeclaredField("remote").apply { isAccessible = true }
                val remote = field.get(f.session) as DeviceFileControlPacket
                assertTrue(f.session.observeRemote(remote.copy(sequence = remote.sequence + 1, echo = own.challenge), f.peer))
                val unchanged = f.session.packet(); f.session.markSent(unchanged)
                owner.requireCurrent() // Ordinary sequence/echo traffic is not a new session.
                assertNotEquals("a".repeat(64), remote.sessionEpoch)
                assertTrue(f.session.observeRemote(remote.copy(sessionEpoch = "a".repeat(64), sequence = 1, echo = own.challenge), f.peer))
                val echo = f.session.packet(); f.session.markSent(echo)
                assertEquals(binding, f.session.binding(destination))
                assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() }
                assertThrows(PhotoFolderScopeError::class.java) { rows.inspectPublished(owner) }
                assertEquals(reads, provider.readOpens)
                assertTrue(f.session.observeRemote(remote.copy(sequence = remote.sequence + 2, echo = own.challenge), f.peer))
                val returned = f.session.packet(); f.session.markSent(returned)
                assertEquals(binding, f.session.binding(destination))
                // Even without checking cycleOwner during the intervening
                // session, returning to old packet bytes cannot renew it.
                assertThrows(PhotoFolderScopeError::class.java) { cycleOwner.requireCurrent() }
                val fresh = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                assertEquals("image/png", rows.inspectPublished(fresh).mimeType)
            }
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun nativePublishedReadbackProducesOnlyFreshOfferBoundEncryptedReadProofAfterActualOriginalInspection() {
        NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel) { f, rows, provider, published, raw, payload, token ->
                val offer = DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw)); val before = f.rows(); val reads = provider.readOpens
                val message = f.io {
                    val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    NativeGalleryPublishedReadback.capture(owner, offer, link.channel).use { proof ->
                        assertFalse(proof.grantsWriteAuthority); assertFalse(proof.isSavedReceipt)
                        proof.perform(rows).also { assertEquals(it, proof.actualOutput()) }
                    }
                }
                assertEquals(message, link.frames.single()); assertEquals(DevicePublishedReadbackEnvelope.KIND, message.string("kind"))
                val body = message.getValue("body").jsonObject
                val binding = f.session.binding(body.string("destination_token"))!!
                val parsed = DevicePublishedReadbackEnvelope.parse(message, offer, binding, GalleryMediaType.IMAGES)
                assertFalse(parsed.grantsWriteAuthority); assertFalse(parsed.isSavedReceipt); assertFalse(parsed.allowsChunkOutput)
                assertEquals(published.fingerprint, body.string("publication_sha256"))
                assertNotEquals(manifest(f.pc.deviceId, raw = raw).fingerprint, binding.destinationToken)
                assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes()); assertTrue(provider.readOpens > reads)
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
        }
    }

    @Test fun copiedPublishedObservationCannotMintOrSendReadbackWithoutExactActualProviderCompletionPermit() {
        NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel) { f, rows, provider, published, raw, payload, token ->
                val before = f.rows()
                f.io {
                    val observation = rows.inspectPublished(NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published))
                    val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    val offer = DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw))
                    NativeGalleryPublishedReadback.capture(owner, offer, link.channel).use { proof ->
                        assertThrows(PhotoFolderScopeError::class.java) { proof.sendVerified(rows, owner, observation, CancellationSignal(), {}) }
                        assertNull(proof.actualOutput())
                    }
                }
                assertTrue(link.frames.isEmpty()); assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
        }
    }

    @Test fun nativePublishedReadbackRejectsForeignChangedExpiredOrCurrentlyWithdrawnReadOwnership() {
        for (change in listOf("foreign_channel", "changed_offer", "expired", "consent", "intent", "book", "bytes"))
            NativeGalleryIncomingTransferTest.Link().use { link ->
                withPublishedInspection(link.channel) { f, rows, provider, published, raw, payload, token ->
                    var currentToken = token
                    val owner = f.io { NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { currentToken }, published) }
                    val now = System.currentTimeMillis()
                    val offer = DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId,
                        raw = if (change == "changed_offer") raw.copyOf().also { it[0] = (it[0].toInt() xor 1).toByte() } else raw),
                        if (change == "expired") now - 70000 else now)
                    try {
                        if (change in setOf("foreign_channel", "changed_offer", "expired")) {
                            NativeGalleryIncomingTransferTest.Link().use { other ->
                                f.io { assertThrows(PhotoFolderScopeError::class.java) {
                                    NativeGalleryPublishedReadback.capture(owner, offer, if (change == "foreign_channel") other.channel else link.channel).perform(rows)
                                } }
                                assertTrue(other.frames.isEmpty())
                            }
                        } else {
                            val proof = f.io { NativeGalleryPublishedReadback.capture(owner, offer, link.channel) }
                            when (change) {
                                "consent" -> { f.io { f.controller.revoke(f.index.galleryPolicy(), GalleryMediaType.IMAGES, f.book()) }; f.handshake() }
                                "intent" -> currentToken = intent(twoWay = false)
                                "book" -> f.unlocked = false
                                else -> payload.writeBytes(raw.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
                            }
                            val before = f.rows(); val bytes = payload.readBytes()
                            proof.use {
                                f.io { assertThrows(PhotoFolderScopeError::class.java) { it.perform(rows) } }
                                assertNull(it.actualOutput())
                            }
                            assertEquals(change, before, f.rows()); assertArrayEquals(bytes, payload.readBytes())
                        }
                        f.io { assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() } }
                        assertTrue(link.frames.isEmpty()); assertEquals(published.body, f.index.incomingPublication(published.id)!!.body)
                        assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
                    } finally { owner.close() }
                }
            }
    }

    @Test fun canceledPublishedReadbackKeepsMediaLaneUntilActualEncryptedOutputReturnsAndClaimsNoLocalSuccess() {
        NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel) { f, rows, provider, published, raw, payload, token ->
                val before = f.rows(); val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
                val ended = java.util.concurrent.CountDownLatch(1); val error = java.util.concurrent.atomic.AtomicReference<Throwable?>()
                val proof = f.io {
                    NativeGalleryPublishedReadback.capture(NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published),
                        DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw)), link.channel)
                }
                link.onMessage = { message ->
                    if (message.string("kind") == DevicePublishedReadbackEnvelope.KIND) {
                        entered.countDown(); check(release.await(8, java.util.concurrent.TimeUnit.SECONDS))
                    }
                }
                val worker = Thread {
                    try { f.io { proof.perform(rows) } } catch (failure: Throwable) { error.set(failure) } finally { ended.countDown() }
                }.also { it.start() }
                try {
                    assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); proof.close()
                    assertEquals(1L, ended.count); assertNull(proof.actualOutput())
                    val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
                } finally { release.countDown(); worker.join(5000); link.onMessage = {} }
                assertFalse(worker.isAlive); assertTrue(error.get() is PhotoFolderScopeError); assertNull(proof.actualOutput())
                // Actual wire output may already have arrived. Cancellation is
                // uncertainty, not evidence that no frame was transmitted.
                assertEquals(DevicePublishedReadbackEnvelope.KIND, link.frames.single().string("kind"))
                val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
                assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
        }
    }

    @Test fun failedPublishedReadbackEncryptedOutputNeverClaimsNativeSuccessOrMutatesPublishedOriginal() {
        NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel) { f, rows, provider, published, raw, payload, token ->
                val before = f.rows(); link.failKind = DevicePublishedReadbackEnvelope.KIND
                f.io {
                    val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    NativeGalleryPublishedReadback.capture(owner, DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw)), link.channel).use {
                        assertThrows(java.io.IOException::class.java) { it.perform(rows) }; assertNull(it.actualOutput())
                    }
                }
                assertTrue(link.frames.isEmpty()); assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
        }
    }

    @Test fun publishedReadOnlyInspectionRejectsMissingCurrentRightsAndChangedOriginalEvidence() {
        for (change in listOf("consent", "intent", "book", "peer", "namespace", "member", "owner", "pending", "bytes"))
            withPublishedInspection { f, rows, provider, published, raw, payload, token ->
                var currentToken = token
                val selected = f.io { NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { currentToken }, published) }
                when (change) {
                    "consent" -> { f.io { f.controller.revoke(f.index.galleryPolicy(), GalleryMediaType.IMAGES, f.book()) }; f.handshake() }
                    "intent" -> currentToken = intent(twoWay = false)
                    "book" -> f.unlocked = false
                    "peer" -> f.peer = f.peer.copy(identitySha256 = "b".repeat(64))
                    "namespace" -> provider.namespace = "replaced-provider"
                    "member" -> provider.generation++
                    "owner" -> provider.wrongOwner = true
                    "pending" -> provider.pending = 1L
                    else -> payload.writeBytes(raw.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
                }
                val before = f.rows(); val bytes = payload.readBytes()
                f.io { assertThrows(PhotoFolderScopeError::class.java) { rows.inspectPublished(selected) } }
                assertEquals(change, before, f.rows()); assertArrayEquals(bytes, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
    }

    @Test fun canceledPublishedReadKeepsActualMediaLaneUntilBlockedProviderQueryDrains() =
        withPublishedInspection { f, rows, provider, published, raw, payload, token ->
            val owner = f.io { NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published) }
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
            val ended = java.util.concurrent.CountDownLatch(1); val errors = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val before = f.rows()
            provider.beforeQuery = { entered.countDown(); check(release.await(8, java.util.concurrent.TimeUnit.SECONDS)) }
            val worker = Thread {
                try { f.io { rows.inspectPublished(owner) } } catch (error: Throwable) { errors.set(error) } finally { ended.countDown() }
            }.also { it.start() }
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); owner.close()
                val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe)); assertEquals(1L, ended.count)
            } finally { release.countDown(); worker.join(5000); provider.beforeQuery = {} }
            assertFalse(worker.isAlive); assertTrue(errors.get() is PhotoFolderScopeError)
            val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun publishedReadOwnerCannotAdoptMissingOrUnpublishedOriginalJournal() {
        for (change in listOf("missing", "unpublished", "foreign_pair"))
            withPublishedInspection { f, rows, provider, published, raw, payload, token ->
                var selected = published
                when (change) {
                    "missing" -> SQLiteDatabase.openDatabase(File(f.indexRoot, "photo-source-jobs.db").path, null,
                        SQLiteDatabase.OPEN_READWRITE).use { db ->
                        db.delete("source_meta", "name=?", arrayOf(GalleryIncomingPublication.PREFIX + published.id))
                    }
                    "unpublished" -> selected = GalleryIncomingPublication.parse(JsonObject(published.body + ("state" to JsonPrimitive("publishing"))))
                    else -> {
                        val origin = published.body.getValue("origin").jsonObject
                        val binding = origin.getValue("binding").jsonObject
                        val changedOrigin = JsonObject(origin + ("binding" to JsonObject(binding + ("receiver_identity_sha256" to JsonPrimitive("c".repeat(64))))))
                        selected = GalleryIncomingPublication.parse(JsonObject(published.body + mapOf("origin" to changedOrigin,
                            "id" to JsonPrimitive(DeviceFileControl.digest("magnolie-gallery-incoming-id-v1\u0000", changedOrigin)))))
                    }
                }
                val before = f.rows(); val readOpens = provider.readOpens
                f.io {
                    assertThrows(PhotoFolderScopeError::class.java) {
                        NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, selected).use {
                            rows.inspectPublished(it)
                        }
                    }
                }
                assertEquals(change, before, f.rows()); assertEquals(readOpens, provider.readOpens)
                assertArrayEquals(raw, payload.readBytes()); assertEquals(1, provider.inserts)
                assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
    }

    @Test fun publishedInspectionRejectsForeignIndexAndBusyLaneBeforeProviderRead() =
        withPublishedInspection { f, rows, provider, published, raw, payload, token ->
            val before = f.rows(); val reads = provider.readOpens
            val otherRoot = java.nio.file.Files.createTempDirectory(f.root.toPath(), "foreign-published-index-").toFile()
            PhotoSourceJobIndex(otherRoot, f.protection).use { other ->
                f.io {
                    NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published).use { owner ->
                        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryIncomingRows(f.app, other).inspectPublished(owner) }
                        assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() }
                    }
                    NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published).use { owner ->
                        val occupied = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(occupied))
                        try {
                            assertEquals("gallery_incoming_worker_busy", assertThrows(PhotoFolderScopeError::class.java) { rows.inspectPublished(owner) }.code)
                        } finally { NativeGalleryMediaIoLane.release(occupied) }
                        assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() }
                    }
                }
            }
            assertEquals(before, f.rows()); assertEquals(reads, provider.readOpens); assertArrayEquals(raw, payload.readBytes())
        }

    @Test fun publishedReadbackFailureOrChangedOriginalDescriptorNeverReturnsInspectionOrMutatesRow() {
        for (change in listOf("read_failure", "changed_descriptor", "canceled"))
            withPublishedInspection { f, rows, provider, published, raw, payload, token ->
                val before = f.rows(); val cancellation = CancellationSignal()
                when (change) {
                    "read_failure" -> provider.failReadback = true
                    "changed_descriptor" -> provider.corruptReadback = File(f.root, "wrong-original-readback").apply {
                        writeBytes(raw.copyOf().also { it[0] = (it[0].toInt() xor 1).toByte() })
                    }
                    else -> cancellation.cancel()
                }
                f.io {
                    NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published).use { owner ->
                        when (change) {
                            "read_failure" -> assertThrows(java.io.IOException::class.java) { rows.inspectPublished(owner, cancellation) }
                            "changed_descriptor" -> assertThrows(PhotoFolderScopeError::class.java) { rows.inspectPublished(owner, cancellation) }
                            else -> assertThrows(android.os.OperationCanceledException::class.java) { rows.inspectPublished(owner, cancellation) }
                        }
                        assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() }
                    }
                }
                val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
                assertEquals(change, before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
    }

    @Test fun renewedReceivingConsentCannotForkAnUnpublishedOriginalIntoAnotherInsert() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val manifest = manifest(f.pc.deviceId); val rows = NativeGalleryIncomingRows(f.app, f.index)
            var originalEpoch = ""
            val original = f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                    originalEpoch = owner.binding.permissionEpoch
                    rows.prepare(owner, fileId, "image/jpeg")
                }
            }
            renewReceiving(f)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                    assertNotEquals(originalEpoch, owner.binding.permissionEpoch)
                    assertEquals("gallery_incoming_original_transfer_held", assertThrows(PhotoFolderScopeError::class.java) {
                        rows.prepare(owner, fileId, "image/jpeg")
                    }.code)
                }
            }
            assertEquals(original.body, f.index.incomingPublication(original.id)!!.body)
            assertEquals(1, provider.inserts); assertEquals(0, provider.writeOpens); assertEquals(0, provider.publishes)
        }
    }

    @Test fun changedContentCannotReuseOriginalTransferIdsButExplicitNewSourceJobRemainsAdmissible() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val token = intent(); val first = manifest(f.pc.deviceId)
            val changedFiles = first.wire().getValue("files").jsonArray.map {
                JsonObject(it.jsonObject + ("sha256" to JsonPrimitive("b".repeat(64))))
            }
            val changed = DeviceFileManifest.parse(JsonObject(first.wire() + ("files" to JsonArray(changedFiles))))
            val fresh = DeviceFileManifest.parse(JsonObject(first.wire() + mapOf("source_id" to JsonPrimitive("4".repeat(32)),
                "transfer_id" to JsonPrimitive("5".repeat(32)))))
            f.io {
                fun reserve(manifest: DeviceFileManifest): GalleryIncomingPublication =
                    NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest, GalleryMediaType.IMAGES).use { owner ->
                        f.index.reserveIncomingPublication(GalleryIncomingPublication.plan(owner.binding, manifest, fileId,
                            owner.pairingEpoch, owner.kind, "image/jpeg", owner.scope), owner::requireLocal)
                    }
                val original = reserve(first)
                assertEquals("gallery_incoming_original_transfer_held", assertThrows(PhotoFolderScopeError::class.java) { reserve(changed) }.code)
                val next = reserve(fresh)
                assertNotEquals(original.id, next.id); assertEquals("planned", next.state)
                assertEquals(original.body, f.index.incomingPublication(original.id)!!.body)
                assertEquals(next.body, f.index.incomingPublication(next.id)!!.body)
            }
        }
    }

    @Test fun actualPendingRowHasProtectedOriginalLineageAndRetryNeverReinsertsOrClaimsSaved() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            val result = f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    val saved = rows.prepare(owner, fileId, "image/jpeg")
                    assertEquals(saved.body, rows.prepare(owner, fileId, "image/jpeg").body)
                    saved
                }
            }
            assertEquals(1, provider.inserts); assertEquals("inserted", result.state)
            assertFalse(result.grantsWriteAuthority); assertFalse(result.isSavedReceipt)
            val witness = result.row!!
            assertEquals("Pictures/Magnolie/", witness.string("path")); assertEquals("original.jpg", witness.string("name"))
            assertEquals(result.body, f.index.incomingPublication(result.id)!!.body)
            // Persisted lineage remains readable without a live PC; it is NOT renewed authority.
            f.session.close()
            PhotoSourceJobIndex(f.indexRoot, f.protection).use { reopened -> assertEquals(result.body, reopened.incomingPublication(result.id)!!.body) }
            assertTrue(f.index.jobs().isEmpty())
        }
    }

    @Test fun preinsertCrashRemainsUncertainAndDoesNotCreateAnotherRowAfterRestart() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    f.hook = { if (it == "gallery-incoming-inserting") throw java.io.IOException("crash before actual insert") }
                    assertThrows(java.io.IOException::class.java) { rows.prepare(owner, fileId, "image/jpeg") }
                    f.hook = {}
                    assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(owner, fileId, "image/jpeg") }
                }
            }
            assertEquals(0, provider.inserts)
        }
    }

    @Test fun postinsertWithdrawalRetainsUncertainPendingRowWithoutAdoptionOrSecondInsert() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            var token: Any? = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            provider.afterInsert = { token = null }
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(owner, fileId, "image/jpeg") }
                    token = intent()
                    assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() }
                }
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { fresh ->
                    assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(fresh, fileId, "image/jpeg") }
                }
            }
            assertEquals(1, provider.inserts)
        }
    }

    @Test fun sourceOnlyIntentWrongKindAndMissingReceiveConsentCannotAdmitIncomingRows() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val twoWay = intent(); val oneWay = intent(twoWay = false)
            f.io { assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { twoWay }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES)
            } }
            ready(f)
            f.io {
                for ((token, kind) in listOf(oneWay to GalleryMediaType.IMAGES, twoWay to GalleryMediaType.VIDEO))
                    assertThrows(PhotoFolderScopeError::class.java) {
                        NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), kind)
                    }
            }
            assertEquals(0, provider.inserts)
        }
    }

    @Test fun changedProviderOwnerNamespaceGenerationOrPendingStateNeverReusesHistoricalRow() {
        for (change in listOf("owner", "namespace", "generation", "published")) GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    rows.prepare(owner, fileId, "image/jpeg")
                    when (change) { "owner" -> provider.wrongOwner = true; "namespace" -> provider.namespace = "replacement-provider"
                        "generation" -> provider.generation++; else -> provider.pending = 0 }
                    assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(owner, fileId, "image/jpeg") }
                }
            }
            assertEquals(1, provider.inserts)
        }
    }

    @Test fun protectedMembershipDetectsDeletedIncomingLineageWithoutChangingSourcePolicy() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val policy = f.index.galleryPolicy(); val token = intent()
            val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val row = f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    NativeGalleryIncomingRows(f.app, f.index).prepare(owner, fileId, "image/jpeg")
                }
            }
            assertEquals(policy, f.index.galleryPolicy())
            SQLiteDatabase.openDatabase(File(f.indexRoot, "photo-source-jobs.db").path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                assertEquals(1, db.delete("source_meta", "name=?", arrayOf(GalleryIncomingPublication.PREFIX + row.id)))
            }
            assertThrows(PhotoFolderScopeError::class.java) { f.index.incomingPublication(row.id) }
        }
    }

    @Test fun missingVolumeHoldsWithoutInsertionAndCanRetryOnlyWhenActuallyMounted() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            Shadows.shadowOf(f.app.getSystemService(StorageManager::class.java)).resetStorageVolumeList()
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    val error = assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(owner, fileId, "image/jpeg") }
                    assertEquals("gallery_incoming_volume_missing", error.message)
                }
            }
            assertEquals(0, provider.inserts)
            mountedPrimaryVolume()
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    assertEquals("inserted", rows.prepare(owner, fileId, "image/jpeg").state)
                }
            }
            assertEquals(1, provider.inserts)
        }
    }

    @Test fun videoOnlyLocalConsentAndIntentInsertOnlyIntoNativeMoviesWithoutPhotoAdmission() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            f.peer = f.peer.copy(videoSupported = true)
            val consent = f.approve(GalleryMediaType.VIDEO)
            f.io { f.controller.grant(f.index.galleryPolicy(), consent) }; f.handshake()
            val token = intent(GalleryMediaType.VIDEO)
            val provider = Provider(f.app, GalleryMediaType.VIDEO); ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES)
                }
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, GalleryMediaType.VIDEO), GalleryMediaType.VIDEO).use { owner ->
                    val result = NativeGalleryIncomingRows(f.app, f.index).prepare(owner, fileId, "video/mp4")
                    assertEquals("Movies/Magnolie/", result.row!!.string("path"))
                    assertFalse(result.isSavedReceipt)
                    f.peer = f.peer.copy(videoSupported = false)
                    assertThrows(PhotoFolderScopeError::class.java) { owner.requireCurrent() }
                }
            }
            assertEquals(1, provider.inserts)
        }
    }

    @Test fun capturedOwnerCannotWriteAfterBookPeerPolicyOrIntentTurnoverOrExplicitClose() {
        for (change in listOf("book", "peer", "policy", "intent", "close")) GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            var token: Any? = intent()
            val owner = f.io { NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES) }
            try {
                when (change) {
                    "book" -> f.currentDocuments = null
                    "peer" -> f.peer = f.peer.copy(owner = Any())
                    "policy" -> f.io { f.controller.revoke(f.index.galleryPolicy(), GalleryMediaType.IMAGES, f.book()) }
                    "intent" -> token = intent()
                    else -> owner.close()
                }
                f.io { assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryIncomingRows(f.app, f.index).prepare(owner, fileId, "image/jpeg") } }
                assertEquals(0, provider.inserts)
            } finally { owner.close() }
        }
    }

    @Test fun malformedLineageCannotClaimPublicationSavedOrForeignRowAndStaleJournalCannotRewindInsertion() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val token = intent(); val provider = Provider(f.app); ShadowContentResolver.registerProviderInternal("media", provider)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId), GalleryMediaType.IMAGES).use { owner ->
                    val planned = GalleryIncomingPublication.plan(owner.binding, owner.manifest, fileId, owner.pairingEpoch, owner.kind, "image/jpeg")
                    for (state in listOf("published", "saved")) assertThrows(PhotoFolderScopeError::class.java) {
                        GalleryIncomingPublication.parse(JsonObject(planned.body + ("state" to JsonPrimitive(state))))
                    }
                    assertThrows(PhotoFolderScopeError::class.java) {
                        GalleryIncomingPublication.plan(owner.binding, owner.manifest, fileId, owner.pairingEpoch, owner.kind, "video/mp4")
                    }
                    val saved = NativeGalleryIncomingRows(f.app, f.index).prepare(owner, fileId, "image/jpeg")
                    assertThrows(PhotoFolderScopeError::class.java) { f.index.beginIncomingInsertion(planned, owner::requireLocal) }
                    for ((key, value) in listOf("uri" to "content://foreign/images/media/99", "path" to "DCIM/Camera/", "mime_type" to "image/png")) {
                        val row = JsonObject(saved.row!! + (key to JsonPrimitive(value)))
                        assertThrows(PhotoFolderScopeError::class.java) { GalleryIncomingPublication.parse(JsonObject(saved.body + ("row" to row))) }
                    }
                    assertEquals(saved.body, f.index.incomingPublication(saved.id)!!.body)
                }
            }
            assertEquals(1, provider.inserts)
        }
    }

    @Test fun originalChunksAreCopiedSyncedAndReadBackWithoutPublishingOrReencoding() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val bytes = ByteArray(65536 + 17) { (it % 251).toByte() }; val chunks = mutableListOf<ByteArray>()
            val file = File(f.root, "native-pending-bytes")
            val provider = Provider(f.app, payload = file); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = bytes), GalleryMediaType.IMAGES).use { owner ->
                    val pending = rows.prepare(owner, fileId, "image/jpeg")
                    val verified = rows.copyAndVerify(owner, pending, { chunk ->
                        bytes.copyOfRange(chunk * 65536, minOf(bytes.size, (chunk + 1) * 65536)).also { chunks += it }
                    })
                    assertEquals("copy_verified", verified.state); assertFalse(verified.isSavedReceipt)
                    assertEquals(verified.body, f.index.incomingPublication(verified.id)!!.body)
                    assertEquals(verified.body, rows.copyAndVerify(owner, verified, { error("Verified bytes must not be recopied") }).body)
                }
            }
            assertArrayEquals(bytes, file.readBytes()); assertEquals(1, provider.writeOpens); assertEquals(2, provider.readOpens)
            assertTrue(chunks.all { chunk -> chunk.all { it == 0.toByte() } }); assertEquals(1L, provider.pending)
        }
    }

    @Test fun completeInterruptedCopyResumesByFreshOriginalReadbackWithoutOpeningWriteOrSourceAgain() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val bytes = "original bytes including original EXIF".toByteArray(); val file = File(f.root, "native-pending-complete")
            val provider = Provider(f.app, payload = file); provider.failReadback = true
            ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = bytes), GalleryMediaType.IMAGES).use { owner ->
                    val pending = rows.prepare(owner, fileId, "image/jpeg")
                    assertThrows(java.io.IOException::class.java) { rows.copyAndVerify(owner, pending, { bytes.copyOf() }) }
                    val interrupted = f.index.incomingPublication(pending.id)!!
                    assertEquals("copying", interrupted.state); assertArrayEquals(bytes, file.readBytes())
                    provider.failReadback = false
                    val verified = rows.copyAndVerify(owner, interrupted, { error("Interrupted complete bytes must not use source or write") })
                    assertEquals("copy_verified", verified.state)
                }
            }
            assertEquals(1, provider.writeOpens); assertEquals(1, provider.readOpens); assertEquals(1L, provider.pending)
        }
    }

    @Test fun partialInterruptedCopyAndWrongChunksNeverReopenWriteOrBecomeVerified() {
        for (change in listOf("partial", "short", "hash")) GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val bytes = ByteArray(65536 + 7) { 43 }; val file = File(f.root, "native-pending-partial")
            val provider = Provider(f.app, payload = file); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = bytes), GalleryMediaType.IMAGES).use { owner ->
                    val pending = rows.prepare(owner, fileId, "image/jpeg")
                    assertThrows(Exception::class.java) {
                        rows.copyAndVerify(owner, pending, { chunk ->
                            if (change == "partial" && chunk == 1) throw java.io.IOException("explicit source interruption")
                            if (change == "short") byteArrayOf(43)
                            else bytes.copyOfRange(chunk * 65536, minOf(bytes.size, (chunk + 1) * 65536)).apply { if (change == "hash") this[0] = 44 }
                        })
                    }
                    val held = f.index.incomingPublication(pending.id)!!; val before = file.takeIf { it.exists() }?.readBytes() ?: byteArrayOf()
                    assertEquals("copying", held.state)
                    assertThrows(PhotoFolderScopeError::class.java) { rows.copyAndVerify(owner, held, { error("Never rewrite partial/corrupt bytes") }) }
                    assertArrayEquals(before, file.readBytes()); assertEquals(held.body, f.index.incomingPublication(pending.id)!!.body)
                }
            }
            assertEquals(1, provider.writeOpens); assertEquals(1L, provider.pending)
        }
    }

    @Test fun originalReadbackMismatchDoesNotBecomeVerifiedAndStoredVerifiedCopyIsNotBlindlyTrusted() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val bytes = "original media bytes".toByteArray(); val file = File(f.root, "native-pending-readback")
            val corrupt = File(f.root, "different-original-readback").apply { writeBytes(ByteArray(bytes.size) { 3 }) }
            val provider = Provider(f.app, payload = file); provider.corruptReadback = corrupt
            ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = bytes), GalleryMediaType.IMAGES).use { owner ->
                    val pending = rows.prepare(owner, fileId, "image/jpeg")
                    assertThrows(PhotoFolderScopeError::class.java) { rows.copyAndVerify(owner, pending, { bytes.copyOf() }) }
                    val copying = f.index.incomingPublication(pending.id)!!; assertEquals("copying", copying.state)
                    provider.corruptReadback = null
                    val verified = rows.copyAndVerify(owner, copying, { error("No second byte copy") })
                    file.writeBytes(ByteArray(bytes.size) { 4 })
                    assertThrows(PhotoFolderScopeError::class.java) { rows.copyAndVerify(owner, verified, { error("No recopy") }) }
                    assertEquals(verified.body, f.index.incomingPublication(verified.id)!!.body)
                }
            }
            assertEquals(1, provider.writeOpens); assertEquals(1L, provider.pending)
        }
    }

    @Test fun consentWithdrawalDuringChunkReadStopsBeforeBytesAndKeepsDurableUnpublishedCopyIntent() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val bytes = "unchanged original bytes".toByteArray(); val file = File(f.root, "native-pending-revoked")
            val provider = Provider(f.app, payload = file); ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = bytes), GalleryMediaType.IMAGES).use { owner ->
                    val pending = rows.prepare(owner, fileId, "image/jpeg"); val chunk = bytes.copyOf()
                    assertThrows(PhotoFolderScopeError::class.java) {
                        rows.copyAndVerify(owner, pending, { f.currentDocuments = null; chunk })
                    }
                    assertTrue(chunk.all { it == 0.toByte() }); assertEquals(0L, file.length())
                    assertEquals("copying", f.index.incomingPublication(pending.id)!!.state)
                }
            }
            assertEquals(1, provider.writeOpens); assertEquals(1L, provider.pending)
        }
    }

    private fun pngBytes(): ByteArray {
        val bitmap = android.graphics.Bitmap.createBitmap(16, 9, android.graphics.Bitmap.Config.ARGB_8888)
        return try { java.io.ByteArrayOutputStream().use { output ->
            check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output)); output.toByteArray()
        } } finally { bitmap.recycle() }
    }

    @Test fun actualNativeImagePublicationVerifiesOriginalsAndJournalsNewVisibleRowWithoutSavedOrSecondUpdate() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val policy = f.index.galleryPolicy(); val raw = pngBytes(); val file = File(f.root, "native-publish.png")
            val provider = Provider(f.app, payload = file).apply { allowPublish = true }; ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = raw), GalleryMediaType.IMAGES).use { owner ->
                    val inserted = rows.prepare(owner, fileId, "image/png")
                    val verified = rows.copyAndVerify(owner, inserted, { raw.copyOf() })
                    val published = rows.publish(owner, verified)
                    assertEquals("published", published.state); assertFalse(published.isSavedReceipt); assertFalse(published.grantsWriteAuthority)
                    assertEquals(published.body, f.index.incomingPublication(published.id)!!.body)
                    assertEquals(verified.row!!.string("member"), published.row!!.string("member"))
                    assertTrue(published.row!!.string("revision").toLong() > verified.row!!.string("revision").toLong())
                    assertEquals(published.body, rows.publish(owner, published).body)
                    assertThrows(PhotoFolderScopeError::class.java) { rows.publish(owner, verified) }
                }
            }
            assertEquals(0L, provider.pending); assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            assertArrayEquals(raw, file.readBytes()); assertEquals(policy, f.index.galleryPolicy()); assertTrue(f.index.jobs().isEmpty())
        }
    }

    @Test fun lostPublicationReplyOrPreUpdateCrashResumesFromProtectedHeadWithoutSecondInsertCopyOrVisibilityUpdate() {
        for (phase in listOf("before_update", "lost_reply")) GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val raw = pngBytes(); val file = File(f.root, "native-publish-lost.png")
            val provider = Provider(f.app, payload = file).apply { allowPublish = true }; ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = raw), GalleryMediaType.IMAGES).use { owner ->
                    val verified = rows.copyAndVerify(owner, rows.prepare(owner, fileId, "image/png"), { raw.copyOf() })
                    if (phase == "before_update") f.hook = { if (it == "gallery-incoming-publishing") throw java.io.IOException("explicit pre-update crash") }
                    else provider.afterPublish = { throw java.io.IOException("explicit lost publication reply") }
                    assertThrows(java.io.IOException::class.java) { rows.publish(owner, verified) }
                    val interrupted = f.index.incomingPublication(verified.id)!!
                    assertEquals("publishing", interrupted.state)
                    assertEquals(if (phase == "before_update") 1L else 0L, provider.pending)
                    f.hook = {}; provider.afterPublish = {}
                    val result = rows.publish(owner, interrupted)
                    assertEquals("published", result.state); assertFalse(result.isSavedReceipt)
                }
            }
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            assertArrayEquals(raw, file.readBytes())
        }
    }

    @Test fun bookWithdrawalAfterActualVisibilityChangeReturnsNoCompletionAndNeedsFreshOwnerReadback() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val raw = pngBytes(); val file = File(f.root, "native-publish-withdraw.png")
            val provider = Provider(f.app, payload = file).apply { allowPublish = true }; ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                val old = NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = raw), GalleryMediaType.IMAGES)
                val verified = rows.copyAndVerify(old, rows.prepare(old, fileId, "image/png"), { raw.copyOf() })
                provider.afterPublish = { f.currentDocuments = null }
                try {
                    assertThrows(PhotoFolderScopeError::class.java) { rows.publish(old, verified) }
                    val held = f.index.incomingPublication(verified.id)!!
                    assertEquals("publishing", held.state); assertEquals(0L, provider.pending)
                    provider.afterPublish = {}; f.currentDocuments = f.documents
                    assertThrows(PhotoFolderScopeError::class.java) { old.requireCurrent() }
                    NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = raw), GalleryMediaType.IMAGES).use { fresh ->
                        assertEquals("published", rows.publish(fresh, held).state)
                    }
                } finally { old.close() }
            }
            assertEquals(1, provider.publishes); assertEquals(1, provider.writeOpens); assertArrayEquals(raw, file.readBytes())
        }
    }

    @Test fun selectedPhotoFilterPreventsScreenshotPublicationAndPreservesVerifiedPendingBytes() {
        GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val raw = pngBytes(); val file = File(f.root, "native-filtered-pending.png")
            val provider = Provider(f.app, payload = file).apply { allowPublish = true }
            ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(photosOnly = true); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = raw), GalleryMediaType.IMAGES).use { owner ->
                    val verified = rows.copyAndVerify(owner, rows.prepare(owner, fileId, "image/png"), { raw.copyOf() })
                    assertThrows(PhotoFolderScopeError::class.java) { rows.publish(owner, verified) }
                    assertEquals(verified.body, f.index.incomingPublication(verified.id)!!.body)
                }
            }
            assertEquals(0, provider.publishes); assertEquals(1L, provider.pending)
            assertArrayEquals(raw, file.readBytes())
        }
    }

    @Test fun forgedMimeOrChangedVerifiedBytesCannotPublishOrAcquirePublishedJournalState() {
        for (mode in listOf("garbage", "mime", "hash")) GalleryReceiveConsentTest.Fixture().use { f ->
            ready(f); val raw = if (mode == "garbage") "not actual gallery media".toByteArray() else pngBytes()
            val file = File(f.root, "native-publish-held")
            val provider = Provider(f.app, payload = file).apply { allowPublish = true }; ShadowContentResolver.registerProviderInternal("media", provider)
            val token = intent(); val rows = NativeGalleryIncomingRows(f.app, f.index)
            f.io {
                NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, manifest(f.pc.deviceId, raw = raw), GalleryMediaType.IMAGES).use { owner ->
                    val mime = if (mode == "mime") "image/jpeg" else "image/png"
                    val verified = rows.copyAndVerify(owner, rows.prepare(owner, fileId, mime), { raw.copyOf() })
                    if (mode == "hash") file.writeBytes(ByteArray(raw.size) { 13 })
                    assertThrows(PhotoFolderScopeError::class.java) { rows.publish(owner, verified) }
                    assertEquals(verified.body, f.index.incomingPublication(verified.id)!!.body)
                }
            }
            assertEquals(0, provider.publishes); assertEquals(1L, provider.pending)
        }
    }
}
