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
import android.os.Looper
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
@Config(sdk = [35], application = Application::class, shadows = [GalleryIncomingRowsTest.WriteTargetLinux::class,
    GalleryIncomingRowsTest.SameFileDescriptorDuplicate::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class GalleryIncomingRowsTest {
    /** Stock Robolectric dup(fd) copies bytes into a DIFFERENT temp file. That
     * cannot test an in-place writer. Registered fixture descriptors reopen the
     * same actual inode without truncation, retaining their access mode. These
     * tests explicitly seek before each borrowed stream; this fixture does NOT
     * claim Android's shared-offset or reliable-close syscall acceptance. */
    @org.robolectric.annotation.Implements(ParcelFileDescriptor::class)
    class SameFileDescriptorDuplicate : org.robolectric.shadows.ShadowParcelFileDescriptor() {
        companion object {
            @JvmStatic @org.robolectric.annotation.Implementation(methodName = "dup") fun sameFileDup(fd: java.io.FileDescriptor): ParcelFileDescriptor {
                val file = NativeIncomingMediaInspectionTest.FixtureLinux.files[fd]
                if (file == null) {
                    val original = org.robolectric.shadows.ShadowParcelFileDescriptor::class.java
                        .getDeclaredMethod("dup", java.io.FileDescriptor::class.java).apply { isAccessible = true }
                    return original.invoke(null, fd) as ParcelFileDescriptor
                }
                val access = WriteTargetLinux.access[fd] ?: android.system.OsConstants.O_RDONLY
                return ParcelFileDescriptor.open(file, if (access == android.system.OsConstants.O_RDWR)
                    ParcelFileDescriptor.MODE_READ_WRITE else ParcelFileDescriptor.MODE_READ_ONLY).also {
                    NativeIncomingMediaInspectionTest.FixtureLinux.files[it.fileDescriptor] = file
                    WriteTargetLinux.access[it.fileDescriptor] = access
                }
            }
        }
    }
    @org.robolectric.annotation.Implements(className = "libcore.io.Linux", isInAndroidSdk = false)
    class WriteTargetLinux : NativeIncomingMediaInspectionTest.FixtureLinux() {
        @org.robolectric.annotation.Implementation fun fcntlInt(fd: java.io.FileDescriptor, command: Int, argument: Int): Int {
            check(command == android.system.OsConstants.F_GETFL && argument == 0)
            return access[fd] ?: android.system.OsConstants.O_RDONLY
        }
        companion object {
            val access = java.util.IdentityHashMap<java.io.FileDescriptor, Int>()
            @JvmStatic @org.robolectric.annotation.Resetter fun resetTarget() { access.clear(); NativeIncomingMediaInspectionTest.FixtureLinux.reset() }
        }
    }
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
        var afterReadOpen: () -> Unit = {}
        var lastReadDescriptor: java.io.FileDescriptor? = null
        var failReadback = false
        var corruptReadback: File? = null
        var allowPublish = false
        var publishes = 0
        var afterPublish: () -> Unit = {}
        var beforeQuery: () -> Unit = {}
        var allowWriteRequest = false
        var writeRequests = 0
        var allowRwTarget = false
        var rwReadOnly = false
        var rwFileOverride: File? = null
        var rwOpens = 0
        var lastRwDescriptor: java.io.FileDescriptor? = null
        var afterRwOpen: () -> Unit = {}
        private var lastSize = 0L
        private var values: ContentValues? = null
        init { attachInfo(app, ProviderInfo().apply { authority = "media"; exported = true }) }
        override fun onCreate() = true
        override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
            if (method == "create_write_request") {
                check(allowWriteRequest)
                @Suppress("DEPRECATION") val clip = extras!!.getParcelable<android.content.ClipData>("clip_data")!!
                check(clip.itemCount == 1 && clip.getItemAt(0).uri.toString() == "content://media/external_primary/${kind.uriSegment}/media/99")
                writeRequests++
                return Bundle().apply { putParcelable("result", android.app.PendingIntent.getActivity(app, writeRequests,
                    Intent("fixture.pc.write.$writeRequests").setData(clip.getItemAt(0).uri), android.app.PendingIntent.FLAG_IMMUTABLE)) }
            }
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
            if (mode == "rw") {
                check(allowRwTarget); check(MediaStore.getRequireOriginal(uri))
                check(uri.buildUpon().clearQuery().build().toString() == "content://media/external_primary/${kind.uriSegment}/media/99")
                check(pending == 0L); rwOpens++
                val file = rwFileOverride ?: payload!!
                return ParcelFileDescriptor.open(file, if (rwReadOnly) ParcelFileDescriptor.MODE_READ_ONLY else ParcelFileDescriptor.MODE_READ_WRITE).also {
                    NativeIncomingMediaInspectionTest.FixtureLinux.files[it.fileDescriptor] = file
                    WriteTargetLinux.access[it.fileDescriptor] = if (rwReadOnly) android.system.OsConstants.O_RDONLY else android.system.OsConstants.O_RDWR
                    lastRwDescriptor = it.fileDescriptor
                    try { afterRwOpen() } catch (error: Throwable) { it.close(); throw error }
                }
            }
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
                lastReadDescriptor = it.fileDescriptor
                try { afterReadOpen() } catch (error: Throwable) { it.close(); throw error }
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

    @Test fun originalReadbackOfferExpiryStopsBeforeNewProviderReadersWithoutExpiringIndependentLocalInspection() {
        NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel) { f, rows, provider, published, raw, payload, token ->
                val before = f.rows(); val reads = provider.readOpens; var delayed = false
                try {
                    f.io {
                        val base = DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw))
                        val deadline = System.currentTimeMillis() + 1000
                        val offer = JsonObject(base + ("expires_ms" to JsonPrimitive(deadline)))
                        val owner = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                        NativeGalleryPublishedReadback.capture(owner, offer, link.channel).use { proof ->
                            assertTrue(System.currentTimeMillis() < deadline) // Actual admitted offer, no fake clocks.
                            provider.beforeQuery = {
                                if (!delayed) {
                                    delayed = true
                                    val remaining = maxOf(0L, deadline - System.currentTimeMillis())
                                    java.util.concurrent.CountDownLatch(1).await(remaining + 20, java.util.concurrent.TimeUnit.MILLISECONDS)
                                    assertTrue(System.currentTimeMillis() >= deadline)
                                }
                            }
                            assertThrows(PhotoFolderScopeError::class.java) { proof.perform(rows) }
                            assertNull(proof.actualOutput())
                        }
                    }
                } finally { provider.beforeQuery = {} }
                assertTrue(delayed); assertEquals(reads, provider.readOpens)
                assertTrue(link.frames.none { it["kind"] == JsonPrimitive(DevicePublishedReadbackEnvelope.KIND) })
                f.io {
                    val fresh = NativeGalleryPublishedInspection.capture(f.session, f.index, f.book(), { f.peer }, { token }, published)
                    assertEquals("image/png", rows.inspectPublished(fresh).mimeType)
                }
                assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
                assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            }
        }
    }

    class PcWriteActivity : androidx.activity.ComponentActivity() {
        var writeAllowed = false
        var writeChecks = 0
        override fun checkUriPermission(uri: Uri?, pid: Int, uid: Int, modeFlags: Int): Int {
            check(uri.toString() == "content://media/external_primary/images/media/99")
            check(modeFlags == Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            writeChecks++
            return if (writeAllowed) android.content.pm.PackageManager.PERMISSION_GRANTED else android.content.pm.PackageManager.PERMISSION_DENIED
        }
    }

    @Test fun actualPcWriteRequestRequiresTheRowsArchivePermitAndDoesNotManufacturePhoneReadOrAMutation() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-write-").toFile(); val before = f.rows()
            f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    val admission = NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit, { f.peer }, { token }, published)
                    rows.preparePublishedPcWrite(admission, archive).use { request ->
                        assertEquals(Uri.parse(published.row!!.string("uri")), request.uri)
                        assertEquals(1, provider.writeRequests)
                        request.requireCurrent() // Original read inspection closed, original mutation admission still current.
                        assertTrue(archive.actions(permit).isEmpty())
                        assertEquals(published.body, archive.verifiedOrigin(request.entry, permit)["publication"])
                        val borrowed = admission.inspection()
                        try {
                            assertThrows(PhotoFolderScopeError::class.java) {
                                NativeGalleryPcWriteRequest.prepare(f.app, rows, borrowed, archive, permit, request.entry, admission)
                            }
                        } finally { borrowed.close() }
                        assertEquals(1, provider.writeRequests)
                        assertThrows(PhotoFolderScopeError::class.java) { archive.verifiedOriginalOrigin(request.entry, permit) }
                    }
                    assertThrows(PhotoFolderScopeError::class.java) { admission.requireCurrent() }
                }
            }
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED, f.app.checkSelfPermission(android.Manifest.permission.READ_MEDIA_IMAGES))
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun pcWriteConsentUsesItsOwnRegistryResultAndActualUriPermissionNotAnOkBoolean() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-write-").toFile(); val before = f.rows()
            fun prepare() = f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    val admission = NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit, { f.peer }, { token }, published)
                    rows.preparePublishedPcWrite(admission, archive)
                }
            }
            val controller = org.robolectric.Robolectric.buildActivity(PcWriteActivity::class.java).setup()
            val activity = controller.get(); val results = mutableListOf<Result<NativeGalleryPcWriteGrant>>()
            val host = NativeGalleryPcWriteConsentHost(activity)
            fun deliver(code: Int) {
                val requestCode = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
                assertTrue(activity.activityResultRegistry.dispatchResult(requestCode, code, Intent()))
                Shadows.shadowOf(Looper.getMainLooper()).idle()
            }
            try {
                val first = prepare(); host.request(first) { results += it }
                deliver(android.app.Activity.RESULT_OK)
                assertTrue(results.single().isFailure); assertTrue(activity.writeChecks > 0)
                activity.writeAllowed = true; results.clear()
                host.request(prepare()) { results += it }; deliver(android.app.Activity.RESULT_CANCELED)
                assertTrue(results.single().isFailure)
                results.clear()
                host.request(prepare()) { results += it }
                controller.pause().resume() // Its own pending OS dialog is allowed; old granted rights are not.
                deliver(android.app.Activity.RESULT_OK)
                val grant = results.single().getOrThrow(); grant.requireCurrent(); grant.consume()
                assertThrows(PhotoFolderScopeError::class.java) { grant.consume() }
                controller.pause().resume()
                assertThrows(PhotoFolderScopeError::class.java) { grant.requireCurrent() }
            } finally { host.close(); controller.pause().stop().destroy() }
            assertEquals(3, provider.writeRequests); assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun pcWriteAdmissionCannotBeRenewedByLaterControlIntentOrBookAfterTheRealArchiveCopy() {
        for (reason in listOf("control", "intent", "book", "cancel")) withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-write-").toFile(); val before = f.rows()
            var incoming: Any? = token
            val cancellation = CancellationSignal()
            val request = f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    val admission = NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit, { f.peer }, { incoming }, published)
                    rows.preparePublishedPcWrite(admission, archive, cancellation)
                }
            }
            request.use {
                when (reason) {
                    "control" -> {
                        val own = f.session.packet(); f.session.markSent(own)
                        val remote = NativeFileControlSession::class.java.getDeclaredField("remote").apply { isAccessible = true }.get(f.session) as DeviceFileControlPacket
                        f.session.observeRemote(remote.copy(sessionEpoch = "a".repeat(64), sequence = 1, echo = own.challenge), f.peer)
                        val echo = f.session.packet(); f.session.markSent(echo)
                    }
                    "intent" -> incoming = MediaSyncTransport.IntentToken(MediaSyncSettings.change(token.body,
                        "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "auto_mode", JsonPrimitive("wifi")))
                    "book" -> f.unlocked = false
                    "cancel" -> cancellation.cancel()
                }
                if (reason == "cancel") assertThrows(android.os.OperationCanceledException::class.java) { request.launch(Any()) }
                else assertThrows(PhotoFolderScopeError::class.java) { request.launch(Any()) }
            }
            assertEquals(1, provider.writeRequests); assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }
    }

    @Test fun pcWriteRequestDoesNotReachTheOsBeforeDetectingEditedOriginalBytes() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-write-").toFile(); val before = f.rows()
            val edited = raw.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() }; payload.writeBytes(edited)
            f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    val admission = NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit, { f.peer }, { token }, published)
                    assertThrows(PhotoFolderScopeError::class.java) { rows.preparePublishedPcWrite(admission, archive) }
                    assertTrue(archive.entries(permit).isEmpty())
                }
            }
            assertEquals(0, provider.writeRequests); assertEquals(before, f.rows()); assertArrayEquals(edited, payload.readBytes())
        }

    @Test fun pcWriteHostRetainsRetiredPendingSlotAndCannotApplyAnOldOsResultToANewerRequest() =
        withPublishedInspection(pcSource = true) { f, rows, provider, published, raw, payload, token ->
            f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
            val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
            val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-write-").toFile(); val before = f.rows()
            fun prepare() = f.io {
                NativeGalleryTrashArchive(root, f.protection).use { archive ->
                    rows.preparePublishedPcWrite(NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit,
                        { f.peer }, { token }, published), archive)
                }
            }
            val controller = org.robolectric.Robolectric.buildActivity(PcWriteActivity::class.java).setup()
            val activity = controller.get().apply { writeAllowed = true }; var otherPending = true
            val host = NativeGalleryPcWriteConsentHost(activity) { otherPending }
            val old = mutableListOf<Result<NativeGalleryPcWriteGrant>>(); val fresh = mutableListOf<Result<NativeGalleryPcWriteGrant>>()
            try {
                prepare().use { first -> prepare().use { second ->
                    assertThrows(PhotoFolderScopeError::class.java) { host.request(first) { old += it } }
                    otherPending = false
                    host.request(first) { old += it }
                    val oldCode = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
                    host.retirePending(); assertTrue(host.requestPending)
                    assertThrows(PhotoFolderScopeError::class.java) { host.request(second) { fresh += it } }
                    activity.activityResultRegistry.dispatchResult(oldCode, android.app.Activity.RESULT_OK, Intent())
                    Shadows.shadowOf(Looper.getMainLooper()).idle()
                    assertTrue(old.single().isFailure); assertTrue(fresh.isEmpty())
                    host.request(second) { fresh += it }
                    val newCode = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
                    assertNotEquals(oldCode, newCode)
                    activity.activityResultRegistry.dispatchResult(oldCode, android.app.Activity.RESULT_OK, Intent())
                    Shadows.shadowOf(Looper.getMainLooper()).idle()
                    assertTrue(fresh.isEmpty()); assertTrue(host.requestPending)
                    f.unlocked = false
                    activity.activityResultRegistry.dispatchResult(newCode, android.app.Activity.RESULT_OK, Intent())
                    Shadows.shadowOf(Looper.getMainLooper()).idle()
                    assertTrue(fresh.single().isFailure)
                } }
            } finally { host.close(); controller.pause().stop().destroy() }
            assertEquals(before, f.rows()); assertArrayEquals(raw, payload.readBytes())
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
        }

    @Test fun proposedPcReplacementIsDurableDenyOnlyMetadataAndNeverRenewsAcceptanceOrOldPublication() {
        for (retireAfterCommit in listOf(false, true)) NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel, pcSource = true) { f, rows, provider, published, raw, payload, token ->
                f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
                val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
                val root = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-plan-").toFile(); val before = f.rows()
                val request = f.io {
                    NativeGalleryTrashArchive(root, f.protection).use { archive ->
                        rows.preparePublishedPcWrite(NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit,
                            { f.peer }, { token }, published), archive)
                    }
                }
                val controller = org.robolectric.Robolectric.buildActivity(PcWriteActivity::class.java).setup()
                val activity = controller.get().apply { writeAllowed = true }; val host = NativeGalleryPcWriteConsentHost(activity)
                try {
                    var granted: NativeGalleryPcWriteGrant? = null
                    host.request(request) { granted = it.getOrThrow() }
                    activity.activityResultRegistry.dispatchResult(Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode,
                        android.app.Activity.RESULT_OK, Intent())
                    Shadows.shadowOf(Looper.getMainLooper()).idle()
                    val grant = granted!!
                    val oldManifest = DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw)).getValue("body").jsonObject.getValue("manifest").jsonObject
                    val file = oldManifest.getValue("files").jsonArray.single().jsonObject
                    val changed = raw + byteArrayOf(17)
                    val newHash = java.security.MessageDigest.getInstance("SHA-256").digest(changed).joinToString("") { "%02x".format(it) }
                    val successor = DeviceFileManifest.parse(JsonObject(oldManifest + mapOf(
                        "source_id" to JsonPrimitive("8".repeat(32)), "transfer_id" to JsonPrimitive("9".repeat(32)),
                        "total_bytes" to JsonPrimitive(changed.size), "files" to JsonArray(listOf(JsonObject(file + mapOf(
                            "size" to JsonPrimitive(changed.size), "sha256" to JsonPrimitive(newHash))))))))
                    val ordinary = DeviceFileOfferEnvelope.create(successor)
                    val offer = link.receive(JsonObject(ordinary + mapOf("kind" to JsonPrimitive(MediaOfferEnvelope.KIND), "body" to buildJsonObject {
                        put("format", 2); put("offer", ordinary.getValue("body")); put("settings", token.body); put("media_type", "images")
                        put("mime_types", buildJsonObject { put(fileId, "image/png") }); put("originals", buildJsonObject {})
                        put("pc_origins", buildJsonObject { put(fileId, buildJsonObject {
                            put("format", 1); put("origin_sha256", published.pcOrigin!!.origin); put("previous_publication_sha256", published.fingerprint)
                        }) })
                    })))
                    val frames = link.frames.toList()
                    if (retireAfterCommit) f.hook = { if (it == "gallery-pc-replacement-proposed") request.close() }
                    val plan = f.io {
                        if (retireAfterCommit) {
                            assertThrows(PhotoFolderScopeError::class.java) { f.index.proposePcReplacement(grant, link.channel, offer) }
                            f.index.pcReplacementPlans().single()
                        } else f.index.proposePcReplacement(grant, link.channel, offer)
                    }
                    assertFalse(plan.grantsWriteAuthority); assertFalse(plan.grantsChunkAuthority)
                    assertEquals(published.body, plan.predecessor.body); assertEquals(request.entry.version, plan.body.getValue("archive").jsonObject.string("version"))
                    assertEquals(listOf(plan.body), f.index.pcReplacementPlans().map { it.body })
                    assertEquals(frames, link.frames); assertArrayEquals(raw, payload.readBytes())
                    assertEquals(before.filterKeys { it != PhotoSourceMembership.NAME },
                        f.rows().filterKeys { !it.startsWith(GalleryPcReplacementPlan.PREFIX) && it != PhotoSourceMembership.NAME })
                    if (!retireAfterCommit) {
                        assertThrows(PhotoFolderScopeError::class.java) { f.io { f.index.proposePcReplacement(grant, link.channel, offer) } }
                        val variants = listOf(
                            JsonObject(plan.body + ("state" to JsonPrimitive("writing"))),
                            JsonObject(plan.body + ("book_version" to JsonPrimitive("bad"))),
                            JsonObject(plan.body + ("archive" to JsonObject(plan.body.getValue("archive").jsonObject + ("sha256" to JsonPrimitive(newHash))))),
                            JsonObject(plan.body + ("predecessor" to JsonObject(published.body - "pc_origin"))),
                            JsonObject(plan.body + ("grant" to JsonPrimitive(true)))
                        )
                        for (invalid in variants) assertThrows(PhotoFolderScopeError::class.java) { GalleryPcReplacementPlan.parse(invalid) }
                        val media = MediaOfferEnvelope.validate(offer, successor.senderId, successor.receiverId)
                        f.io {
                            NativeGalleryIncomingOwner.capture(f.session, f.index, f.book(), { f.peer }, { token }, successor, GalleryMediaType.IMAGES,
                                pcOrigins = media.pcOrigins).use { oldPath ->
                                assertThrows(PhotoFolderScopeError::class.java) { rows.prepare(oldPath, fileId, "image/png") }
                            }
                        } // A proposed plan does not relax the normal PC successor fence.
                        // Populate ONLY this synthetic fixture's proposed metadata through its
                        // actual protected transaction/membership writer, never real history.
                        f.io {
                            val transaction = PhotoSourceJobIndex::class.java.getDeclaredMethod("transaction", java.lang.Boolean.TYPE, kotlin.jvm.functions.Function0::class.java)
                                .apply { isAccessible = true }
                            val put = PhotoSourceJobIndex::class.java.getDeclaredMethod("putMeta", String::class.java, ByteArray::class.java)
                                .apply { isAccessible = true }
                            fun insert(id: String) {
                                val value = JsonObject(plan.body + ("id" to JsonPrimitive(id)))
                                val bytes = java.io.ByteArrayOutputStream().use { output ->
                                    TelefonRahmen.schreiben(output, value, DeviceTransferProtection.MAX_CLEAR_BYTES - 4); output.toByteArray()
                                }
                                val name = GalleryPcReplacementPlan.PREFIX + id
                                val cipher = try { f.protection.seal(bytes, "photo-source-jobs-v1/" + name) } finally { bytes.fill(0) }
                                put.invoke(f.index, name, cipher)
                            }
                            transaction.invoke(f.index, false, {
                                repeat(GalleryPcReplacementPlan.MAX_RECORDS - 1) { number -> insert((number + 1).toString(16).padStart(32, '0')) }
                            })
                            assertEquals(GalleryPcReplacementPlan.MAX_RECORDS, f.index.pcReplacementPlans().size)
                            val retained = f.rows()
                            assertThrows(PhotoFolderScopeError::class.java) { f.index.proposePcReplacement(grant, link.channel, offer) }
                            val failure = assertThrows(java.lang.reflect.InvocationTargetException::class.java) {
                                transaction.invoke(f.index, false, { insert("f".repeat(32)) })
                            }
                            val cause = (failure.cause as? java.lang.reflect.InvocationTargetException)?.cause ?: failure.cause
                            assertEquals("gallery_pc_replacement_plan_capacity", cause?.message)
                            assertEquals(retained, f.rows())
                        }
                    }
                    assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
                    f.hook = {}; request.close(); f.session.close(); f.index.close()
                    PhotoSourceJobIndex.openExisting(f.indexRoot, f.protection).use { offline ->
                        val read = offline.pcReplacementPlans().single { it.id == plan.id }
                        assertEquals(plan.body, read.body); assertFalse(read.grantsWriteAuthority); assertFalse(read.grantsChunkAuthority)
                    }
                } finally { f.hook = {}; host.close(); controller.pause().stop().destroy(); request.close() }
            }
        }
    }

    private class PcStageCase(val f: GalleryReceiveConsentTest.Fixture, val provider: Provider,
        val original: GalleryIncomingPublication, val oldBytes: ByteArray, val originalFile: File,
        val token: MediaSyncTransport.IntentToken, val incoming: java.util.concurrent.atomic.AtomicReference<Any?>,
        val link: NativeGalleryIncomingTransferTest.Link, val grant: NativeGalleryPcWriteGrant,
        val plan: GalleryPcReplacementPlan, val bytes: ByteArray, val context: android.content.Context,
        val rows: NativeGalleryIncomingRows, val archiveRoot: File) : AutoCloseable {
        private val transfers = mutableListOf<NativeGalleryPcReplacementTransfer>()
        fun prepare(boundary: (String) -> Unit = {}) = f.io {
            NativeGalleryPcReplacementTransfer.prepare(context, f.index, plan, grant, link.channel, boundary)
        }.also { transfers += it }
        fun serve(transfer: NativeGalleryPcReplacementTransfer, corrupt: Boolean = false, duplicate: Boolean = false,
            change: (JsonObject) -> JsonObject = { it }) {
            link.onMessage = { message ->
                if (message.string("kind") == DeviceFileChunkEnvelope.REQUEST) {
                    val request = DeviceFileChunkEnvelope.parseRequest(message); val start = request.chunkIndex * DeviceFileManifest.CHUNK_BYTES
                    val clear = bytes.copyOfRange(start, minOf(bytes.size, start + DeviceFileManifest.CHUNK_BYTES))
                    try {
                        if (corrupt && request.chunkIndex == 0) clear[0] = (clear[0].toInt() xor 1).toByte()
                        val response = change(DeviceFileChunkEnvelope.response(request, clear))
                        assertTrue(transfer.observeChunk(link.channel, link.receive(response)))
                        if (duplicate) assertTrue(transfer.observeChunk(link.channel, link.receive(response)))
                    } finally { clear.fill(0) }
                }
            }
        }
        fun assertOriginal() {
            assertArrayEquals(oldBytes, originalFile.readBytes()); assertLineage()
        }
        fun assertLineage() {
            assertEquals(original.body, f.index.incomingPublication(original.id)!!.body)
            assertEquals(1, provider.inserts); assertEquals(1, provider.writeOpens); assertEquals(1, provider.publishes)
            assertTrue(link.frames.none { it["kind"] == JsonPrimitive(DeviceFileSavedEnvelope.KIND) })
        }
        override fun close() { transfers.forEach { it.close(); check(it.awaitIoEnded(5000)) }; link.onMessage = {} }
    }
    private fun withPcStage(unrecognized: Boolean = false, photosOnly: Boolean = false, shortOffer: Boolean = false,
        oldPaddedBytes: Int = 0, action: (PcStageCase) -> Unit) {
        NativeGalleryIncomingTransferTest.Link().use { link ->
            withPublishedInspection(link.channel, pcSource = true, paddedBytes = oldPaddedBytes) { f, rows, provider, published, raw, payload, token ->
                val pcLocalField = GalleryReceiveConsentTest.Fixture::class.java.getDeclaredField("pcLocal").apply { isAccessible = true }
                val pcLocal = pcLocalField.get(f) as NativeLocalFileGrant
                pcLocalField.set(f, NativeLocalFileGrant(DeviceFileGrantState(4, "e".repeat(64), true, false), pcLocal.owner, true)); f.handshake()
                f.documents.setzePapierkorb(true, 30); provider.allowWriteRequest = true
                val permit = NativeGalleryTrashBookPermit.capture(f.documents) { f.unlocked }
                val activeToken = if (photosOnly) MediaSyncTransport.IntentToken(MediaSyncSettings.change(token.body,
                    "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "photos_only", JsonPrimitive(true))) else token
                val incoming = java.util.concurrent.atomic.AtomicReference<Any?>(activeToken)
                val archiveRoot = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-stage-archive-").toFile()
                val request = f.io {
                    NativeGalleryTrashArchive(archiveRoot, f.protection).use { archive ->
                        rows.preparePublishedPcWrite(NativeGalleryPcWriteAdmission.capture(f.session, f.index, f.book(), permit,
                            { f.peer }, { incoming.get() }, published), archive)
                    }
                }
                val controller = org.robolectric.Robolectric.buildActivity(PcWriteActivity::class.java).setup()
                val activity = controller.get().apply { writeAllowed = true }; val host = NativeGalleryPcWriteConsentHost(activity)
                try {
                    var grant: NativeGalleryPcWriteGrant? = null
                    host.request(request) { grant = it.getOrThrow() }
                    activity.activityResultRegistry.dispatchResult(Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode, android.app.Activity.RESULT_OK, Intent())
                    Shadows.shadowOf(Looper.getMainLooper()).idle()
                    val bitmap = android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888).apply { eraseColor(0xff57a836.toInt()) }
                    val bytes = if (unrecognized) ByteArray(DeviceFileManifest.CHUNK_BYTES + 19) { 42 } else try {
                        java.io.ByteArrayOutputStream().use { output ->
                            check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output))
                            output.toByteArray().copyOf(DeviceFileManifest.CHUNK_BYTES + 19)
                        }
                    } finally { bitmap.recycle() }
                    if (unrecognized) bitmap.recycle()
                    val oldManifest = DeviceFileOfferEnvelope.create(manifest(f.pc.deviceId, raw = raw)).getValue("body").jsonObject.getValue("manifest").jsonObject
                    val oldFile = oldManifest.getValue("files").jsonArray.single().jsonObject
                    val hash = NativeHex.lower(java.security.MessageDigest.getInstance("SHA-256").digest(bytes))
                    val successor = DeviceFileManifest.parse(JsonObject(oldManifest + mapOf("transfer_id" to JsonPrimitive("9".repeat(32)),
                        "source_id" to JsonPrimitive("8".repeat(32)), "total_bytes" to JsonPrimitive(bytes.size), "files" to JsonArray(listOf(JsonObject(oldFile + mapOf(
                            "size" to JsonPrimitive(bytes.size), "sha256" to JsonPrimitive(hash))))))))
                    val fullOffer = DeviceFileOfferEnvelope.create(successor)
                    val ordinary = if (shortOffer) JsonObject(fullOffer + ("expires_ms" to JsonPrimitive(System.currentTimeMillis() + 2000))) else fullOffer
                    val offer = link.receive(JsonObject(ordinary + mapOf("kind" to JsonPrimitive(MediaOfferEnvelope.KIND), "body" to buildJsonObject {
                        put("format", 2); put("offer", ordinary.getValue("body")); put("settings", activeToken.body); put("media_type", "images")
                        put("mime_types", buildJsonObject { put(fileId, "image/png") }); put("originals", buildJsonObject {})
                        put("pc_origins", buildJsonObject { put(fileId, buildJsonObject {
                            put("format", 1); put("origin_sha256", published.pcOrigin!!.origin); put("previous_publication_sha256", published.fingerprint)
                        }) })
                    })))
                    val plan = f.io { f.index.proposePcReplacement(grant!!, link.channel, offer) }
                    val base = java.nio.file.Files.createTempDirectory(f.root.toPath(), "pc-stage-private-").toFile()
                    val context = object : android.content.ContextWrapper(f.app) {
                        override fun getApplicationContext(): android.content.Context = this
                        override fun getNoBackupFilesDir(): File = base
                    }
                    PcStageCase(f, provider, published, raw, payload, activeToken, incoming, link, grant!!, plan, bytes, context, rows, archiveRoot).use(action)
                } finally { host.close(); controller.pause().stop().destroy(); request.close() }
            }
        }
    }

    @Test fun actualPcSuccessorStagesEncryptedChunksAndNativeMetadataWithoutOpeningTheOldRowForWriteOrSendingSaved() = withPcStage { h ->
        val before = h.f.rows(); val reads = h.provider.readOpens; val transfer = h.prepare()
        val local = NativeFileControlSession::class.java.getDeclaredField("local").apply { isAccessible = true }.get(h.f.session) as NativeLocalFileGrant
        assertFalse(local.grants.sendFiles); assertTrue(local.grants.receiveFiles)
        val pcLocal = GalleryReceiveConsentTest.Fixture::class.java.getDeclaredField("pcLocal").apply { isAccessible = true }.get(h.f) as NativeLocalFileGrant
        assertTrue(pcLocal.grants.sendFiles); assertFalse(pcLocal.grants.receiveFiles)
        assertFalse(h.f.index.pcStages().single().sealed)
        val stageRoot = File(h.f.index.pcStages().single().body.string("root_path"))
        assertEquals(setOf("owner.enc"), stageRoot.list()!!.toSet())
        h.serve(transfer, duplicate = true)
        h.f.io {
            val acceptance = DeviceFileAcceptanceEnvelope.parse(transfer.sendAcceptance())
            assertEquals(h.f.index.pcStages().single().acceptance.id, acceptance.acceptanceSha256)
            val observed = transfer.receiveAndStage()
            assertEquals("image/png", observed.mimeType); assertEquals(8, observed.width); assertEquals(8, observed.height)
            assertFalse(observed.grantsWriteAuthority)
            val sealed = transfer.sealedRecord(); assertTrue(sealed.sealed); assertFalse(sealed.grantsWriteAuthority)
            val acceptanceBody = sealed.body.getValue("acceptance").jsonObject
            val invalidRecords = listOf(
                JsonObject(sealed.body + ("state" to JsonPrimitive("reserved"))),
                JsonObject(sealed.body + ("write_grant" to JsonPrimitive(true))),
                JsonObject(sealed.body + ("bytes" to JsonPrimitive(sealed.bytes.toString()))),
                JsonObject(sealed.body + ("root_path" to JsonPrimitive("relative/root"))),
                JsonObject(sealed.body + ("acceptance" to JsonObject(acceptanceBody + ("transfer_id" to JsonPrimitive("7".repeat(32)))))),
                JsonObject(sealed.body + ("acceptance" to JsonObject(acceptanceBody + ("scope_sha256" to JsonPrimitive("7".repeat(64)))))),
                JsonObject(sealed.body + ("acceptance" to JsonObject(acceptanceBody + ("total_bytes" to JsonPrimitive(sealed.bytes + 1))))),
                JsonObject(sealed.body + ("seal" to JsonObject(sealed.body.getValue("seal").jsonObject + ("sha256" to JsonPrimitive("bad"))))),
                JsonObject(sealed.body + ("observation" to JsonObject(sealed.body.getValue("observation").jsonObject + ("width" to JsonPrimitive(0)))))
            )
            for (invalid in invalidRecords) assertThrows(PhotoFolderScopeError::class.java) { GalleryPcStageRecord.parse(invalid) }
            val sample = ByteArray(21); val start = DeviceFileManifest.CHUNK_BYTES - 7
            assertEquals(sample.size, transfer.readStagedAt(start.toLong(), sample, 0, sample.size))
            assertArrayEquals(h.bytes.copyOfRange(start, start + sample.size), sample); sample.fill(0)
        }
        assertEquals(setOf("owner.enc", "chunk-0.enc", "chunk-1.enc", "complete.enc"), stageRoot.list()!!.toSet())
        assertEquals(2, h.link.frames.count { it["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST) })
        stageRoot.listFiles()!!.forEach { file ->
            assertFalse(file.readBytes().take(8).toByteArray().contentEquals(h.bytes.take(8).toByteArray()))
        }
        assertEquals(before.filterKeys { it != PhotoSourceMembership.NAME },
            h.f.rows().filterKeys { !it.startsWith(GalleryPcStageRecord.PREFIX) && it != PhotoSourceMembership.NAME })
        assertEquals(reads, h.provider.readOpens); h.assertOriginal(); transfer.close()
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.readStagedAt(0, ByteArray(1), 0, 1) } }
        val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun pcStageRejectsWrongContentHashOrUnrecognizedNativeMediaWithoutPublishingOrDiscardingItsReservation() {
        for (badMedia in listOf(false, true)) withPcStage(unrecognized = badMedia) { h ->
            val transfer = h.prepare(); h.serve(transfer, corrupt = !badMedia)
            h.f.io {
                transfer.sendAcceptance()
                assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndStage() }
            }
            assertFalse(h.f.index.pcStages().single().sealed); h.assertOriginal()
            assertTrue(File(h.f.index.pcStages().single().body.string("root_path"), "chunk-0.enc").exists())
            val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
        }
    }

    @Test fun pcStageCipherChangesCannotBeAdoptedEvenIfBytesArePutBackAfterTheFirstFailedRead() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer)
        h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        val root = File(h.f.io { transfer.sealedRecord().body.string("root_path") }); val chunk = File(root, "chunk-1.enc"); val old = chunk.readBytes()
        chunk.writeBytes(old.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() })
        val target = ByteArray(27) { 126 }
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.readStagedAt((DeviceFileManifest.CHUNK_BYTES - 7).toLong(), target, 3, 21) } }
        assertTrue(target.copyOfRange(0, 3).all { it == 126.toByte() }); assertTrue(target.copyOfRange(3, 10).all { it == 0.toByte() })
        assertTrue(target.copyOfRange(10, target.size).all { it == 126.toByte() })
        chunk.writeBytes(old)
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.readStagedAt(0, ByteArray(3), 0, 3) } }
        assertTrue(h.f.index.pcStages().single().sealed); h.assertOriginal()
    }

    @Test fun canceledPcStagingRetainsTheMediaLaneWhileItsActualCipherFileDescriptorIsStillOpen() = withPcStage { h ->
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        val checkpoints = java.util.concurrent.atomic.AtomicInteger()
        val transfer = h.prepare { if (it == "pc-stage-cipher-durable-before-close" && checkpoints.incrementAndGet() == 2) {
            entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
        } }
        h.serve(transfer); h.f.io { transfer.sendAcceptance() }
        val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val worker = Thread { try { h.f.io { transfer.receiveAndStage() } } catch (error: Throwable) { failure.set(error) } }.also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); transfer.close()
            val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe)); assertTrue(worker.isAlive); assertFalse(transfer.awaitIoEnded(0))
        } finally { release.countDown(); worker.join(7000) }
        assertFalse(worker.isAlive); assertTrue(failure.get() is PhotoFolderScopeError); assertTrue(transfer.awaitIoEnded(0))
        assertFalse(h.f.index.pcStages().single().sealed); h.assertOriginal()
        val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun storedPcProposalCannotStartStagingAfterBookOrFullIntentRevocationAndBusyMediaDoesNotAllocateARoot() {
        for (reason in listOf("book", "intent", "busy", "control", "used")) withPcStage { h ->
            when (reason) {
                "book" -> h.f.unlocked = false
                "intent" -> h.incoming.set(MediaSyncTransport.IntentToken(MediaSyncSettings.change(h.token.body,
                    "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "auto_mode", JsonPrimitive("wifi"))))
                "control" -> {
                    val own = h.f.session.packet(); h.f.session.markSent(own)
                    val old = NativeFileControlSession::class.java.getDeclaredField("remote").apply { isAccessible = true }.get(h.f.session) as DeviceFileControlPacket
                    assertTrue(h.f.session.observeRemote(old.copy(sessionEpoch = "a".repeat(64), sequence = 1, echo = own.challenge), h.f.peer))
                    val echo = h.f.session.packet(); h.f.session.markSent(echo)
                    assertEquals(h.plan.body["binding"], h.f.session.binding(GalleryPcStageRecord.media(h.plan).manifest.fingerprint)!!.snapshot())
                }
                "used" -> h.grant.consume()
            }
            val lane = Any()
            if (reason == "busy") assertTrue(NativeGalleryMediaIoLane.acquire(lane))
            try { assertThrows(PhotoFolderScopeError::class.java) { h.prepare() } }
            finally { if (reason == "busy") NativeGalleryMediaIoLane.release(lane) }
            assertTrue(h.f.index.pcStages().isEmpty()); assertTrue(h.context.noBackupFilesDir.list()!!.isEmpty()); h.assertOriginal()
        }
    }

    @Test fun pcStagingKeepsTheActualOriginalOfferExpiryAfterAcceptanceAndDoesNotOpenAnyChunkReaderLater() = withPcStage(shortOffer = true) { h ->
        val transfer = h.prepare(); h.serve(transfer)
        h.f.io { transfer.sendAcceptance() }
        val deadline = h.plan.body.getValue("offer").jsonObject.long("expires_ms")
        assertTrue(System.currentTimeMillis() < deadline)
        java.util.concurrent.CountDownLatch(1).await(maxOf(0L, deadline - System.currentTimeMillis()) + 20, java.util.concurrent.TimeUnit.MILLISECONDS)
        assertTrue(System.currentTimeMillis() >= deadline)
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.receiveAndStage() } }
        assertFalse(h.f.index.pcStages().single().sealed)
        assertTrue(h.link.frames.none { it["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST) })
        h.assertOriginal()
    }

    @Test fun photosOnlyPcStageRejectsAHashCorrectScreenshotInsteadOfInventingCaptureMetadata() = withPcStage(photosOnly = true) { h ->
        val transfer = h.prepare(); h.serve(transfer)
        h.f.io {
            transfer.sendAcceptance()
            val error = assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndStage() }
            assertEquals("gallery_incoming_photo_metadata_required", error.message)
        }
        assertFalse(h.f.index.pcStages().single().sealed); h.assertOriginal()
    }

    @Test fun pcStageReservedByteBudgetHoldsWithoutAllocatingFilesOrDiscardingOtherProtectedReservations() = withPcStage { h ->
        h.f.io {
            val ordinaryBody = h.plan.body.getValue("offer").jsonObject.getValue("body").jsonObject.getValue("offer").jsonObject
            val rawManifest = ordinaryBody.getValue("manifest").jsonObject
            val oldFile = rawManifest.getValue("files").jsonArray.single().jsonObject
            val large = DeviceFileManifest.parse(JsonObject(rawManifest + mapOf("total_bytes" to JsonPrimitive(DeviceFileManifest.MAX_FILE_BYTES),
                "files" to JsonArray(listOf(JsonObject(oldFile + ("size" to JsonPrimitive(DeviceFileManifest.MAX_FILE_BYTES))))))))
            val wire = h.plan.body.getValue("offer").jsonObject
            val largeOffer = JsonObject(wire + ("body" to JsonObject(wire.getValue("body").jsonObject +
                ("offer" to JsonObject(ordinaryBody + mapOf("manifest" to large.wire(), "manifest_sha256" to JsonPrimitive(large.fingerprint)))))))
            val binding = JsonObject(h.plan.body.getValue("binding").jsonObject + ("destination_token" to JsonPrimitive(large.fingerprint)))
            val transaction = PhotoSourceJobIndex::class.java.getDeclaredMethod("transaction", java.lang.Boolean.TYPE, kotlin.jvm.functions.Function0::class.java)
                .apply { isAccessible = true }
            val put = PhotoSourceJobIndex::class.java.getDeclaredMethod("putMeta", String::class.java, ByteArray::class.java).apply { isAccessible = true }
            fun metadata(name: String, body: JsonObject) {
                val plain = java.io.ByteArrayOutputStream().use { output -> TelefonRahmen.schreiben(output, body, DeviceTransferProtection.MAX_CLEAR_BYTES - 4); output.toByteArray() }
                val cipher = try { h.f.protection.seal(plain, "photo-source-jobs-v1/" + name) } finally { plain.fill(0) }
                put.invoke(h.f.index, name, cipher)
            }
            // Synthetic reservation metadata ONLY; no 400-MiB payload is allocated or claimed verified.
            val count = (DeviceFileManifest.MAX_TOTAL_BYTES / DeviceFileManifest.MAX_FILE_BYTES).toInt()
            val prepared = mutableListOf<Pair<String, JsonObject>>()
            repeat(count) { number ->
                    val id = (number + 1).toString(16).padStart(32, '0')
                    val plan = GalleryPcReplacementPlan.parse(JsonObject(h.plan.body + mapOf("id" to JsonPrimitive(id), "offer" to largeOffer, "binding" to binding)))
                    val media = GalleryPcStageRecord.media(plan)
                    h.grant.request.admission.incomingOwner(media).use { owner ->
                        val acceptance = GalleryIncomingAcceptance.create(owner, media.offer, System.currentTimeMillis())
                        val record = GalleryPcStageRecord.create(plan, File(h.context.noBackupFilesDir, "uncreated-$id"), "synthetic-reservation-$id", acceptance)
                        prepared += GalleryPcReplacementPlan.PREFIX + id to plan.body
                        prepared += GalleryPcStageRecord.PREFIX + id to record.body
                    }
            }
            transaction.invoke(h.f.index, false, { prepared.forEach { (name, body) -> metadata(name, body) } })
            assertEquals(DeviceFileManifest.MAX_TOTAL_BYTES, h.f.index.pcStages().sumOf { it.bytes })
        }
        val retained = h.f.rows()
        val failure = assertThrows(PhotoFolderScopeError::class.java) { h.prepare() }
        assertEquals("gallery_pc_stage_capacity", failure.message)
        assertTrue(h.context.noBackupFilesDir.list()!!.isEmpty()); assertTrue(retained == h.f.rows()); h.assertOriginal()
    }

    @Test fun pcStageCannotTreatFailedSecureOutputOrWrongChunkBindingAsReceivedSuccessorData() {
        for (reason in listOf("acceptance_output", "request_output", "binding", "hash")) withPcStage { h ->
            val transfer = h.prepare()
            if (reason == "acceptance_output") h.link.failKind = DeviceFileAcceptanceEnvelope.KIND
            else if (reason == "request_output") h.link.failKind = DeviceFileChunkEnvelope.REQUEST
            else h.serve(transfer, change = { message ->
                val field = if (reason == "binding") "destination_token" else "data_sha256"
                JsonObject(message + ("body" to JsonObject(message.getValue("body").jsonObject + (field to JsonPrimitive("a".repeat(64))))))
            })
            h.f.io {
                if (reason == "acceptance_output") assertThrows(java.io.IOException::class.java) { transfer.sendAcceptance() }
                else {
                    transfer.sendAcceptance()
                    if (reason == "request_output") assertThrows(java.io.IOException::class.java) { transfer.receiveAndStage() }
                    else assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndStage() }
                }
            }
            assertFalse(h.f.index.pcStages().single().sealed); h.assertOriginal()
            assertEquals(setOf("owner.enc"), File(h.f.index.pcStages().single().body.string("root_path")).list()!!.toSet())
        }
    }

    @Test fun pcStageDoesNotRestartTheOriginalWriteAdmissionClockWhileWaitingForAnUnansweredChunk() = withPcStage { h ->
        val remaining = h.grant.request.admission.remainingMs()
        assertTrue(remaining > 3000)
        // Actual elapsed admission time, not a substituted clock or modified product TTL.
        java.util.concurrent.CountDownLatch(1).await(remaining - 3000, java.util.concurrent.TimeUnit.MILLISECONDS)
        val transfer = h.prepare()
        val accepted = h.f.io { transfer.sendAcceptance() }
        assertTrue(accepted.long("expires_ms") < h.plan.body.getValue("offer").jsonObject.long("expires_ms"))
        val before = h.grant.request.admission.remainingMs(); val started = System.nanoTime()
        h.f.io { assertThrows(PhotoFolderScopeError::class.java) { transfer.receiveAndStage() } }
        assertTrue(java.util.concurrent.TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) <= before + 1000)
        assertFalse(h.f.index.pcStages().single().sealed); h.assertOriginal()
        val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun pcStageEndWaitsForARealConcurrentChunkObserverDescriptorEvenAfterTheReceiveWorkerHasEnded() = withPcStage { h ->
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        val transfer = h.prepare { if (it == "pc-stage-cipher-read-open" && Thread.currentThread().name == "fixture-pc-stage-observer") {
            entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
        } }
        val observer = java.util.concurrent.atomic.AtomicReference<Thread?>()
        val observerFailure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        h.link.onMessage = { message -> if (message["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST)) {
            val request = DeviceFileChunkEnvelope.parseRequest(message)
            val clear = h.bytes.copyOfRange(0, DeviceFileManifest.CHUNK_BYTES)
            val response = try { DeviceFileChunkEnvelope.response(request, clear) } finally { clear.fill(0) }
            Thread({
                try { transfer.observeChunk(h.link.channel, h.link.receive(response)) }
                catch (error: Throwable) { observerFailure.set(error) }
            }, "fixture-pc-stage-observer").also { observer.set(it); it.start() }
        } }
        h.f.io { transfer.sendAcceptance() }
        val receiveFailure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val receiver = Thread { try { h.f.io { transfer.receiveAndStage() } } catch (error: Throwable) { receiveFailure.set(error) } }.also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); transfer.close()
            receiver.join(2000); assertFalse(receiver.isAlive)
            assertTrue(observer.get()!!.isAlive); assertFalse(transfer.awaitIoEnded(0))
            val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
        } finally { release.countDown(); receiver.join(7000); observer.get()?.join(7000) }
        assertFalse(receiver.isAlive); assertFalse(observer.get()!!.isAlive)
        assertTrue(receiveFailure.get() is PhotoFolderScopeError); assertTrue(observerFailure.get() is PhotoFolderScopeError)
        assertTrue(transfer.awaitIoEnded(0)); h.assertOriginal()
        val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun legitimateLateDuplicateChunkObserverCanOverlapTheExactReservedToSealedTransitionWithoutAdoptingNewRights() = withPcStage { h ->
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        val blocked = java.util.concurrent.atomic.AtomicBoolean(false)
        val transfer = h.prepare { if (it == "pc-stage-before-record-check" && Thread.currentThread().name == "fixture-stage-late-duplicate" && blocked.compareAndSet(false, true)) {
            entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
        } }
        val duplicate = java.util.concurrent.atomic.AtomicReference<Thread?>()
        val duplicateResult = java.util.concurrent.atomic.AtomicReference<Boolean?>()
        val duplicateFailure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        h.link.onMessage = { message -> if (message["kind"] == JsonPrimitive(DeviceFileChunkEnvelope.REQUEST)) {
            val request = DeviceFileChunkEnvelope.parseRequest(message); val start = request.chunkIndex * DeviceFileManifest.CHUNK_BYTES
            val clear = h.bytes.copyOfRange(start, minOf(h.bytes.size, start + DeviceFileManifest.CHUNK_BYTES))
            val response = try { DeviceFileChunkEnvelope.response(request, clear) } finally { clear.fill(0) }
            assertTrue(transfer.observeChunk(h.link.channel, h.link.receive(response)))
            if (request.chunkIndex == 1) {
                Thread({
                    try { duplicateResult.set(transfer.observeChunk(h.link.channel, h.link.receive(response))) }
                    catch (error: Throwable) { duplicateFailure.set(error) }
                }, "fixture-stage-late-duplicate").also { duplicate.set(it); it.start() }
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
            }
        } }
        h.f.io { transfer.sendAcceptance() }
        val received = java.util.concurrent.atomic.AtomicReference<NativeIncomingMediaObservation?>()
        val receiveFailure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val receiver = Thread { try { received.set(h.f.io { transfer.receiveAndStage() }) } catch (error: Throwable) { receiveFailure.set(error) } }.also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); receiver.join(7000)
            assertFalse(receiver.isAlive); assertNull(receiveFailure.get()); assertEquals("image/png", received.get()!!.mimeType)
            assertTrue(h.f.io { transfer.sealedRecord().sealed }); assertTrue(duplicate.get()!!.isAlive)
        } finally { release.countDown(); receiver.join(7000); duplicate.get()?.join(7000) }
        assertFalse(duplicate.get()!!.isAlive); assertNull(duplicateFailure.get()); assertEquals(false, duplicateResult.get())
        val target = ByteArray(17); h.f.io { assertEquals(target.size, transfer.readStagedAt(0, target, 0, target.size)) }
        assertArrayEquals(h.bytes.copyOf(target.size), target); target.fill(0)
        h.assertOriginal(); transfer.close(); assertTrue(transfer.awaitIoEnded(0))
    }

    @Test fun pcStageRejectsForeignFilesSubstituteRootsAndHardlinksWithoutDeletingOrAdoptingThem() {
        for (reason in listOf("extra", "root", "hardlink")) withPcStage { h ->
            val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
            val root = File(h.f.io { transfer.sealedRecord().body.string("root_path") })
            val foreign = when (reason) {
                "extra" -> File(root, "foreign.enc").apply { writeText("foreign data remains") }
                "root" -> {
                    assertTrue(root.renameTo(File(root.parentFile, root.name + "-retained")))
                    java.nio.file.Files.createDirectory(root.toPath(), java.nio.file.attribute.PosixFilePermissions.asFileAttribute(
                        java.nio.file.attribute.PosixFilePermissions.fromString("rwx------")))
                    File(root, "foreign.txt").apply { writeText("replacement root remains") }
                }
                else -> File(h.context.noBackupFilesDir, "held-cipher-link.enc").also {
                    java.nio.file.Files.createLink(it.toPath(), File(root, "chunk-0.enc").toPath())
                }
            }
            val retained = foreign.readBytes()
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.readStagedAt(0, ByteArray(3), 0, 3) } }
            assertArrayEquals(retained, foreign.readBytes()); h.assertOriginal()
            assertTrue(h.f.index.pcStages().single().sealed)
        }
    }

    @Test fun pcBeforeWriteJournalRequiresTheActualSealedStageOriginalFdAndIndependentArchiveWithoutAnyOriginalWrite() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        val before = h.f.rows(); val reads = h.provider.readOpens
        val record = h.f.io {
            NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                transfer.prepareBeforeWrite(h.rows, archive)
            }
        }
        assertEquals(reads + 1, h.provider.readOpens)
        assertFalse(record.grantsWriteAuthority); assertEquals("before_write", record.body.string("state"))
        assertEquals(h.oldBytes.size.toLong(), record.body.getValue("descriptor").jsonObject.long("size"))
        assertEquals(record.body, h.f.index.pcBeforeWrite(h.plan.id)!!.body)
        assertEquals(before.filterKeys { it != PhotoSourceMembership.NAME }, h.f.rows().filterKeys {
            it != PhotoSourceMembership.NAME && !it.startsWith(GalleryPcPreWriteRecord.PREFIX)
        }); h.assertOriginal(); h.grant.requireUnused()
        val stage = NativeGalleryPcReplacementTransfer::class.java.getDeclaredField("stage").apply { isAccessible = true }.get(transfer) as NativeGalleryPcStage
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.f.index.recordPcBeforeWrite(h.rows, stage, h.grant, record) } }
        val invalid = listOf(
            JsonObject(record.body + ("state" to JsonPrimitive("written"))),
            JsonObject(record.body + ("saved" to JsonPrimitive(true))),
            JsonObject(record.body + ("descriptor" to JsonObject(record.body.getValue("descriptor").jsonObject + ("links" to JsonPrimitive(2))))),
            JsonObject(record.body + ("descriptor" to JsonObject(record.body.getValue("descriptor").jsonObject + ("size" to JsonPrimitive(h.oldBytes.size + 1))))),
            JsonObject(record.body + ("descriptor" to JsonObject(record.body.getValue("descriptor").jsonObject + ("inode" to JsonPrimitive("1")))))
        )
        for (value in invalid) assertThrows(PhotoFolderScopeError::class.java) { GalleryPcPreWriteRecord.parse(value) }
        val retained = h.f.rows(); val actualReads = h.provider.readOpens
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            assertThrows(PhotoFolderScopeError::class.java) { transfer.prepareBeforeWrite(h.rows, archive) }
        } }
        assertEquals(actualReads, h.provider.readOpens); assertEquals(retained, h.f.rows()); h.assertOriginal()
        transfer.close(); assertTrue(transfer.awaitIoEnded(0)); h.f.session.close(); h.f.index.close()
        PhotoSourceJobIndex.openExisting(h.f.indexRoot, h.f.protection).use { offline ->
            assertEquals(record.body, offline.pcBeforeWrite(h.plan.id)!!.body); assertFalse(offline.pcBeforeWrite(h.plan.id)!!.grantsWriteAuthority)
        }
    }

    @Test fun pcBeforeWriteRechecksActualOriginalArchiveAndOwnerAndDoesNotTrustTheStageMetadataAlone() {
        for (reason in listOf("original", "row", "archive", "grant", "cancel", "wrong_index")) withPcStage { h ->
            val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
            val before = h.f.rows()
            val cancel = CancellationSignal()
            when (reason) {
                "original" -> h.originalFile.writeBytes(h.oldBytes.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() })
                "row" -> h.provider.wrongOwner = true
                "grant" -> h.grant.request.close()
                "cancel" -> cancel.cancel()
            }
            val root = if (reason == "archive") java.nio.file.Files.createTempDirectory(h.f.root.toPath(), "wrong-pc-archive-").toFile() else h.archiveRoot
            h.f.io {
                NativeGalleryTrashArchive(root, h.f.protection, allowCreate = reason == "archive").use { archive ->
                    if (reason == "cancel") assertThrows(android.os.OperationCanceledException::class.java) { transfer.prepareBeforeWrite(h.rows, archive, cancel) }
                    else if (reason == "wrong_index") {
                        val otherRoot = java.nio.file.Files.createTempDirectory(h.f.root.toPath(), "wrong-pc-index-").toFile()
                        PhotoSourceJobIndex(otherRoot, h.f.protection).use { other ->
                            val rows = NativeGalleryIncomingRows(h.f.app, other)
                            assertThrows(PhotoFolderScopeError::class.java) { transfer.prepareBeforeWrite(rows, archive) }
                        }
                    } else assertThrows(PhotoFolderScopeError::class.java) { transfer.prepareBeforeWrite(h.rows, archive) }
                }
            }
            assertNull(h.f.index.pcBeforeWrite(h.plan.id)); assertEquals(before, h.f.rows())
            if (reason == "original") h.originalFile.writeBytes(h.oldBytes)
            h.assertOriginal()
        }
    }

    @Test fun pcBeforeWriteUncertainCommitRetainsTheExactObservationButCannotResumeOrOpenOriginalForWrite() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        h.f.hook = { if (it == "gallery-pc-before-write-recorded") h.grant.request.close() }
        h.f.io {
            NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                assertThrows(PhotoFolderScopeError::class.java) { transfer.prepareBeforeWrite(h.rows, archive) }
                assertThrows(PhotoFolderScopeError::class.java) { transfer.prepareBeforeWrite(h.rows, archive) }
            }
        }
        h.f.hook = {}
        val held = h.f.index.pcBeforeWrite(h.plan.id)!!; assertFalse(held.grantsWriteAuthority); h.assertOriginal()
        assertTrue(transfer.awaitIoEnded(0)); val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun pcBeforeWriteCancellationWaitsForTheActualProviderReadDescriptorBeforeReleasingTheLane() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        h.provider.afterReadOpen = { entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
        val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val worker = Thread {
            try { h.f.io {
                NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                    transfer.prepareBeforeWrite(h.rows, archive)
                }
            } } catch (error: Throwable) { failure.set(error) }
        }.also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); transfer.close()
            assertTrue(worker.isAlive); assertTrue(h.provider.lastReadDescriptor!!.valid()); assertFalse(transfer.awaitIoEnded(0))
            val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
        } finally { release.countDown(); worker.join(7000); h.provider.afterReadOpen = {} }
        assertFalse(worker.isAlive); assertFalse(h.provider.lastReadDescriptor!!.valid())
        assertTrue(failure.get() is PhotoFolderScopeError); assertTrue(transfer.awaitIoEnded(0))
        assertNull(h.f.index.pcBeforeWrite(h.plan.id)); h.assertOriginal()
        val probe = Any(); assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun pcWritableTargetIsNontruncatingExactAndHeldUntilParentRetirementWithoutExportingAMutationApi() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            transfer.prepareBeforeWrite(h.rows, archive)
        } }
        val retained = h.f.rows(); h.provider.allowRwTarget = true
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            transfer.prepareWriteTarget(h.rows, archive)
        } }
        assertEquals(1, h.provider.rwOpens); assertTrue(h.provider.lastRwDescriptor!!.valid()); h.assertOriginal()
        assertEquals(retained, h.f.rows()); h.grant.requireUnused()
        val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
        transfer.close(); assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0))
        assertTrue(NativeGalleryMediaIoLane.acquire(probe)); NativeGalleryMediaIoLane.release(probe)
    }

    @Test fun pcWritableTargetRejectsReadOnlyFdDifferentNativeFileAndChangesAfterItsActualOpenWithoutMutatingAnything() {
        for (reason in listOf("read_only", "other_inode", "revoked", "canceled", "missing_preflight")) withPcStage { h ->
            val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
            if (reason != "missing_preflight") h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                transfer.prepareBeforeWrite(h.rows, archive)
            } }
            h.provider.allowRwTarget = true
            val cancel = CancellationSignal()
            when (reason) {
                "read_only" -> h.provider.rwReadOnly = true
                "other_inode" -> h.provider.rwFileOverride = File(h.f.root, "equal-but-different-native-target.png").apply { writeBytes(h.oldBytes) }
                "revoked" -> h.provider.afterRwOpen = { h.grant.request.close() }
                "canceled" -> h.provider.afterRwOpen = { cancel.cancel() }
            }
            val retained = h.f.rows()
            h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                if (reason == "canceled") assertThrows(android.os.OperationCanceledException::class.java) { transfer.prepareWriteTarget(h.rows, archive, cancel) }
                else assertThrows(PhotoFolderScopeError::class.java) { transfer.prepareWriteTarget(h.rows, archive) }
            } }
            assertEquals(if (reason == "missing_preflight") 0 else 1, h.provider.rwOpens)
            h.provider.lastRwDescriptor?.let { assertFalse(it.valid()) }
            assertEquals(retained, h.f.rows()); h.assertOriginal(); assertTrue(transfer.awaitIoEnded(0))
        }
    }

    @Test fun pcWritableTargetParentCloseWhileActualRwOpenIsBlockedDoesNotPublishDrainOrLeakThatFd() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive -> transfer.prepareBeforeWrite(h.rows, archive) } }
        h.provider.allowRwTarget = true
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        h.provider.afterRwOpen = { entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
        val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val worker = Thread { try { h.f.io {
            NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive -> transfer.prepareWriteTarget(h.rows, archive) }
        } } catch (error: Throwable) { failure.set(error) } }.also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); transfer.close()
            assertTrue(h.provider.lastRwDescriptor!!.valid()); assertFalse(transfer.awaitIoEnded(0)); assertTrue(worker.isAlive)
            val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
        } finally { release.countDown(); worker.join(7000); h.provider.afterRwOpen = {} }
        assertFalse(worker.isAlive); assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(failure.get() is PhotoFolderScopeError)
        assertTrue(transfer.awaitIoEnded(0)); h.assertOriginal()
    }

    @Test fun pcWritableTargetRetirementClosesItsRetainedFdOnlyAfterAllOtherActualStageIoHasDrained() = withPcStage { h ->
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        val transfer = h.prepare { if (it == "pc-stage-cipher-read-open" && Thread.currentThread().name == "fixture-retained-rw-reader") {
            entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
        } }
        h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        h.provider.allowRwTarget = true
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            transfer.prepareBeforeWrite(h.rows, archive); transfer.prepareWriteTarget(h.rows, archive)
        } }
        val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val reader = Thread({ try { transfer.readStagedAt(0, ByteArray(7), 0, 7) } catch (error: Throwable) { failure.set(error) } },
            "fixture-retained-rw-reader").also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); transfer.close()
            assertTrue(h.provider.lastRwDescriptor!!.valid()); assertFalse(transfer.awaitIoEnded(0))
            val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
        } finally { release.countDown(); reader.join(7000) }
        assertFalse(reader.isAlive); assertTrue(failure.get() is PhotoFolderScopeError)
        assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0)); h.assertOriginal()
    }

    @Test fun pcWriteStartRequiresTheActualHeldTargetConsumesTheOriginalGrantOnceAndPreservesItsCompleteWitness() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        h.provider.allowRwTarget = true
        val before = h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            transfer.prepareBeforeWrite(h.rows, archive).also { transfer.prepareWriteTarget(h.rows, archive) }
        } }
        val target = NativeGalleryPcReplacementTransfer::class.java.getDeclaredField("writeTarget").apply { isAccessible = true }
            .get(transfer) as NativeGalleryPcWriteTarget
        val heldRows = h.f.rows()
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.f.index.startPcWrite(target, before, before.startWrite()) } }
        assertEquals(heldRows, h.f.rows())
        val started = h.f.io { transfer.markWriteStarted() }
        assertEquals("write_started", started.state); assertFalse(started.grantsWriteAuthority)
        assertEquals(before.body.filterKeys { it != "state" }, started.body.filterKeys { it != "state" })
        assertEquals(started.body, h.f.index.pcBeforeWrite(h.plan.id)!!.body)
        assertThrows(PhotoFolderScopeError::class.java) { h.grant.requireUnused() }; h.grant.requireCurrent()
        assertTrue(h.provider.lastRwDescriptor!!.valid()); h.assertOriginal()
        val retained = h.f.rows()
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.markWriteStarted() } }
        assertEquals(retained, h.f.rows()); assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0))
        h.assertOriginal(); h.f.session.close(); h.f.index.close()
        PhotoSourceJobIndex.openExisting(h.f.indexRoot, h.f.protection).use { offline ->
            assertEquals(started.body, offline.pcBeforeWrite(h.plan.id)!!.body); assertFalse(offline.pcBeforeWrite(h.plan.id)!!.grantsWriteAuthority)
        }
    }

    @Test fun pcWriteStartCannotBeManufacturedFromPreflightWithoutALiveUnusedOriginalGrantAndActualWritableTarget() {
        for (reason in listOf("no_target", "used", "revoked")) withPcStage { h ->
            val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
            h.provider.allowRwTarget = true
            val before = h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                transfer.prepareBeforeWrite(h.rows, archive).also { if (reason != "no_target") transfer.prepareWriteTarget(h.rows, archive) }
            } }
            when (reason) { "used" -> h.grant.consume(); "revoked" -> h.grant.request.close() }
            val retained = h.f.rows()
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.markWriteStarted() } }
            assertEquals(retained, h.f.rows()); assertEquals(before.body, h.f.index.pcBeforeWrite(h.plan.id)!!.body)
            h.provider.lastRwDescriptor?.let { assertFalse(it.valid()) }; assertTrue(transfer.awaitIoEnded(0)); h.assertOriginal()
        }
    }

    @Test fun pcWriteStartRevokedImmediatelyAfterDurableCasHoldsTheStartFenceWithoutResumingOrMutatingTheOriginal() = withPcStage { h ->
        val transfer = h.prepare(); h.serve(transfer); h.f.io { transfer.sendAcceptance(); transfer.receiveAndStage() }
        h.provider.allowRwTarget = true
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            transfer.prepareBeforeWrite(h.rows, archive); transfer.prepareWriteTarget(h.rows, archive)
        } }
        h.f.hook = { if (it == "gallery-pc-write-started") h.grant.request.close() }
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.markWriteStarted() } }
        h.f.hook = {}
        val started = h.f.index.pcBeforeWrite(h.plan.id)!!; assertEquals("write_started", started.state); assertFalse(started.grantsWriteAuthority)
        assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0)); h.assertOriginal()
        assertThrows(PhotoFolderScopeError::class.java) { h.f.io { transfer.markWriteStarted() } }
        assertEquals(started.body, h.f.index.pcBeforeWrite(h.plan.id)!!.body)
    }

    private fun PcStageCase.prepareStartedCopy(): NativeGalleryPcReplacementTransfer {
        val transfer = prepare(); serve(transfer)
        f.io {
            transfer.sendAcceptance(); transfer.receiveAndStage(); provider.allowRwTarget = true
            NativeGalleryTrashArchive(archiveRoot, f.protection, allowCreate = false).use { archive ->
                transfer.prepareBeforeWrite(rows, archive); transfer.prepareWriteTarget(rows, archive); transfer.markWriteStarted()
            }
        }
        return transfer
    }
    private fun PcStageCase.assertOldArchive() = f.io {
        NativeGalleryTrashArchive(archiveRoot, f.protection, allowCreate = false).use { archive ->
            val bytes = java.io.ByteArrayOutputStream()
            archive.readContent(grant.request.entry, grant.request.admission.archiveBook) { bytes.write(it) }
            assertArrayEquals(oldBytes, bytes.toByteArray())
        }
    }

    @Test fun pcByteCopyWritesOnlyTheCompleteStageAndVerifiesLongerAndShorterOriginalsWithoutClaimingProviderOrHistoryCompletion() {
        for (oldSize in listOf(0, DeviceFileManifest.CHUNK_BYTES * 2 + 39)) withPcStage(oldPaddedBytes = oldSize) { h ->
            val transfer = h.prepareStartedCopy(); val retained = h.f.rows(); val reads = h.provider.readOpens
            val observation = h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                transfer.copyReplacementBytes(archive)
            } }
            assertArrayEquals(h.bytes, h.originalFile.readBytes()); assertEquals(h.bytes.size.toLong(), h.originalFile.length())
            assertEquals(h.bytes.size.toLong(), observation.bytes); assertEquals("image/png", observation.media.mimeType)
            assertEquals(8, observation.media.width); assertEquals(8, observation.media.height)
            assertEquals(h.bytes.size.toLong(), observation.descriptor.long("size"))
            assertFalse(observation.grantsWriteAuthority); assertFalse(observation.isSavedReceipt)
            assertFalse(h.provider.lastRwDescriptor!!.valid()); assertEquals(reads, h.provider.readOpens)
            assertTrue(WriteTargetLinux.access.filterValues { it == android.system.OsConstants.O_RDWR }.keys.none { it.valid() })
            assertEquals(retained, h.f.rows()); assertEquals("write_started", h.f.index.pcBeforeWrite(h.plan.id)!!.state)
            h.assertOldArchive(); h.assertLineage()
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                transfer.copyReplacementBytes(archive)
            } } }
            assertArrayEquals(h.bytes, h.originalFile.readBytes()); assertEquals(retained, h.f.rows()); assertTrue(transfer.awaitIoEnded(0))
        }
    }

    @Test fun pcByteCopyRejectsMissingStartWrongArchiveAndChangedStageBeforeWritingAnyOriginalBytes() {
        for (reason in listOf("not_started", "wrong_archive", "stage")) withPcStage { h ->
            val transfer = h.prepare(); h.serve(transfer); h.provider.allowRwTarget = true
            h.f.io {
                transfer.sendAcceptance(); transfer.receiveAndStage()
                NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
                    transfer.prepareBeforeWrite(h.rows, archive); transfer.prepareWriteTarget(h.rows, archive)
                    if (reason != "not_started") transfer.markWriteStarted()
                }
            }
            if (reason == "stage") {
                val file = File(h.f.index.pcStages().single().body.string("root_path"), "chunk-0.enc")
                file.writeBytes(file.readBytes().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() })
            }
            val root = if (reason == "wrong_archive") java.nio.file.Files.createTempDirectory(h.f.root.toPath(), "wrong-copy-archive-").toFile() else h.archiveRoot
            val retained = h.f.rows()
            h.f.io { NativeGalleryTrashArchive(root, h.f.protection, allowCreate = reason == "wrong_archive").use { archive ->
                assertThrows(PhotoFolderScopeError::class.java) { transfer.copyReplacementBytes(archive) }
            } }
            assertEquals(retained, h.f.rows()); h.assertOriginal(); assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0))
        }
    }

    @Test fun pcByteCopyCancellationAfterAnActualChunkKeepsOriginalArchiveFenceAndLaneUntilBothWriteFdsClose() = withPcStage { h ->
        val transfer = h.prepareStartedCopy(); val retained = h.f.rows()
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val worker = Thread { try { h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            transfer.copyReplacementBytes(archive) { if (it == "pc-replacement-bytes-written") {
                entered.countDown(); assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
            } }
        } } } catch (error: Throwable) { failure.set(error) } }.also { it.start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
            assertArrayEquals(h.bytes.copyOf(DeviceFileManifest.CHUNK_BYTES), h.originalFile.readBytes())
            assertEquals(2, WriteTargetLinux.access.filterValues { it == android.system.OsConstants.O_RDWR }.keys.count { it.valid() })
            transfer.close(); assertTrue(worker.isAlive); assertTrue(h.provider.lastRwDescriptor!!.valid()); assertFalse(transfer.awaitIoEnded(0))
            val probe = Any(); assertFalse(NativeGalleryMediaIoLane.acquire(probe))
        } finally { release.countDown(); worker.join(7000) }
        assertFalse(worker.isAlive); assertTrue(failure.get() is PhotoFolderScopeError)
        assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0))
        assertTrue(WriteTargetLinux.access.filterValues { it == android.system.OsConstants.O_RDWR }.keys.none { it.valid() })
        assertEquals(retained, h.f.rows()); h.assertLineage()
        // The original admission is intentionally retired. Independently fresh
        // local recovery ownership, not the dead write grant, reads the archive.
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            val permit = NativeGalleryTrashBookPermit.capture(h.f.documents) { h.f.unlocked }
            val recovered = java.io.ByteArrayOutputStream()
            archive.readContent(h.grant.request.entry, permit) { recovered.write(it) }
            assertArrayEquals(h.oldBytes, recovered.toByteArray())
        } }
    }

    @Test fun pcByteCopyDetectsAChangedFinalFileAfterForceAndLeavesUncertainBytesFencedWithoutAutomaticRestore() = withPcStage { h ->
        val transfer = h.prepareStartedCopy(); val retained = h.f.rows()
        h.f.io { NativeGalleryTrashArchive(h.archiveRoot, h.f.protection, allowCreate = false).use { archive ->
            assertThrows(PhotoFolderScopeError::class.java) { transfer.copyReplacementBytes(archive) { if (it == "pc-replacement-bytes-forced") {
                h.originalFile.writeBytes(h.bytes.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() })
            } } }
        } }
        assertFalse(h.bytes.contentEquals(h.originalFile.readBytes())); assertEquals(retained, h.f.rows()); h.assertLineage()
        assertEquals("write_started", h.f.index.pcBeforeWrite(h.plan.id)!!.state)
        assertFalse(h.provider.lastRwDescriptor!!.valid()); assertTrue(transfer.awaitIoEnded(0))
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
