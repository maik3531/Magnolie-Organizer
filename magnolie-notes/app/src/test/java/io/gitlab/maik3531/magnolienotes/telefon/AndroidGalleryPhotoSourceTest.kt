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
        val generationAdded: Any = 1L, val generationModified: Any = 1L, val owner: String = "foreign.source.app")
    private class Provider(val root: File, val mediaType: GalleryMediaType = GalleryMediaType.IMAGES) : ContentProvider() {
        var writeRequests = 0
        var originalFile: File? = null
        var denyOriginal = false
        var originalRequests = 0
        var typedOriginalRequests = 0
        var allowTrash = false
        var trashWrites = 0
        var beforeTrash: (() -> Unit)? = null
        var afterTrash: (() -> Unit)? = null
        var allowRestore = false
        var restoreInserts = 0
        var restoreWrites = 0
        var restorePublishes = 0
        var afterRestoreInsert: (() -> Unit)? = null
        var beforeRestorePublish: (() -> Unit)? = null
        var beforeRestoreWrite: (() -> Unit)? = null
        var afterRestorePublish: (() -> Unit)? = null
        var restoreReturnsOldUri = false
        var corruptRestoreRead = false
        val restoredFiles = linkedMapOf<Long, File>()
        var rows = listOf(Row())
        var ignoreSelection = false
        var ignoreLimit = false
        var reverse = false
        var onQuery: (() -> Unit)? = null
        var onOpen: (() -> Unit)? = null
        var namespace = "native-fixture-v1"
        val cursors = mutableListOf<Cursor>()
        val opens = mutableListOf<String>()
        val requests = mutableListOf<Bundle>()
        override fun onCreate() = true
        override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
            if (method == "create_write_request") {
                @Suppress("DEPRECATION") val clip = extras!!.getParcelable<android.content.ClipData>("clip_data")!!
                check(clip.itemCount == 1 && clip.getItemAt(0).uri.toString().startsWith("content://media/external_primary/${mediaType.uriSegment}/media/"))
                writeRequests++
                val intent = Intent("fixture.write." + java.util.UUID.randomUUID()).setData(clip.getItemAt(0).uri)
                return Bundle().apply { putParcelable("result", android.app.PendingIntent.getActivity(context, 0, intent, android.app.PendingIntent.FLAG_IMMUTABLE)) }
            }
            check(method == "get_version" && extras?.getString(Intent.EXTRA_TEXT) == "external_primary")
            return Bundle().apply { putString(Intent.EXTRA_TEXT, namespace) }
        }
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, sort: String?): Cursor =
            throw AssertionError("Expected API26+ bundle query")
        override fun query(uri: Uri, projection: Array<out String>?, queryArgs: Bundle?, cancellation: CancellationSignal?): Cursor {
            val columns = requireNotNull(projection)
            check("_data" !in columns)
            val volume = if (Build.VERSION.SDK_INT >= 29) "external_primary" else "external"
            check(uri.toString().startsWith("content://media/$volume/${mediaType.uriSegment}/media") ||
                uri.toString() == "content://media/1234-5678/${mediaType.uriSegment}/media")
            val args = requireNotNull(queryArgs)
            rows = rows.map { row ->
                val file = restoredFiles[row.id]
                if (file != null && file.length() != row.bytes) row.copy(bytes = file.length(), generationModified = (row.generationModified as Long) + 1) else row
            }
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
                    "is_trashed" to row.trashed, "generation_added" to row.generationAdded, "generation_modified" to row.generationModified,
                    "owner_package_name" to row.owner)
                cursor.addRow(columns.map { data[it] }.toTypedArray())
            }
            cursors += cursor
            onQuery?.invoke()
            return cursor
        }
        override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
            val own = uri.lastPathSegment?.toLongOrNull()?.let { restoredFiles[it] }
            if (mode == "w") {
                check(allowRestore && own != null)
                val row = rows.single { it.id.toString() == uri.lastPathSegment }
                check(row.pending == 1L && row.owner == context!!.packageName)
                restoreWrites++
                beforeRestoreWrite?.invoke()
                return ParcelFileDescriptor.open(own, ParcelFileDescriptor.MODE_WRITE_ONLY or ParcelFileDescriptor.MODE_TRUNCATE)
            }
            check(mode == "r")
            val original = Build.VERSION.SDK_INT >= 30 && android.provider.MediaStore.getRequireOriginal(uri)
            if (original) originalRequests++
            if (original && denyOriginal && own == null) throw UnsupportedOperationException("Fixture denies original media bytes")
            opens += uri.toString()
            onOpen?.invoke()
            val chosen = if (own != null) {
                if (corruptRestoreRead) File(root, "corrupt-restore.bin").also { it.writeText("WRONG") } else own
            } else if (original) originalFile ?: File(root, "source.bin") else File(root, "source.bin")
            return ParcelFileDescriptor.open(chosen, ParcelFileDescriptor.MODE_READ_ONLY)
        }
        override fun openTypedAssetFile(uri: Uri, mimeTypeFilter: String, opts: Bundle?): android.content.res.AssetFileDescriptor {
            if (Build.VERSION.SDK_INT >= 31 && android.provider.MediaStore.getRequireOriginal(uri)) {
                check(opts?.getBoolean(android.provider.MediaStore.EXTRA_ACCEPT_ORIGINAL_MEDIA_FORMAT) == true)
                typedOriginalRequests++
            }
            return android.content.res.AssetFileDescriptor(openFile(uri, "r"), 0, android.content.res.AssetFileDescriptor.UNKNOWN_LENGTH)
        }
        override fun getType(uri: Uri) = "image/jpeg"
        override fun insert(uri: Uri, values: ContentValues?): Uri {
            check(allowRestore && values!!.keySet() == setOf("_display_name", "mime_type", "relative_path", "is_pending"))
            check(values.getAsInteger("is_pending") == 1)
            val id = maxOf(100L, rows.maxOfOrNull { it.id }?.plus(1) ?: 100L)
            val requested = values.getAsString("_display_name")
            val name = if (rows.any { it.name == requested }) "restored-$id-$requested" else requested
            rows = rows + Row(id = id, name = name, mime = values.getAsString("mime_type"), path = values.getAsString("relative_path"),
                bytes = 0, pending = 1, generationAdded = id, generationModified = id, owner = context!!.packageName)
            restoredFiles[id] = File(root, "restored-$id.bin").also { check(it.createNewFile()) }
            restoreInserts++; afterRestoreInsert?.invoke()
            return android.content.ContentUris.withAppendedId(uri, if (restoreReturnsOldUri) 1L else id)
        }
        override fun update(uri: Uri, values: ContentValues?, where: String?, args: Array<out String>?): Int {
            if (values?.keySet() == setOf("is_pending")) {
                check(allowRestore && values.getAsInteger("is_pending") == 0)
                check(where == "_id = ? AND date_added = ? AND generation_added = ? AND generation_modified = ? AND owner_package_name = ? AND is_pending = 1 AND is_trashed = 0")
                beforeRestorePublish?.invoke(); restorePublishes++
                val row = rows.singleOrNull { row -> row.id.toString() == uri.lastPathSegment && row.pending == 1L && row.trashed == 0L &&
                    args!!.toList() == listOf(row.id.toString(), row.added.toString(), row.generationAdded.toString(), row.generationModified.toString(), row.owner) } ?: return 0
                rows = rows.map { if (it === row) it.copy(pending = 0, generationModified = (it.generationModified as Long) + 1) else it }
                afterRestorePublish?.invoke()
                return 1
            }
            check(allowTrash) { "Unexpected photo write" }
            check(values?.keySet() == setOf("is_trashed") && values.getAsInteger("is_trashed") == 1)
            check(where == "_id = ? AND bucket_id = ? AND relative_path = ? AND _display_name = ? AND _size = ? AND date_added = ? AND generation_added = ? AND generation_modified = ? AND mime_type = ? AND is_pending = 0 AND is_trashed = 0")
            beforeTrash?.invoke(); trashWrites++
            val selected = rows.singleOrNull { row ->
                uri.lastPathSegment == row.id.toString() && args!!.toList() == listOf(row.id.toString(), row.bucket, row.path, row.name,
                    row.bytes.toString(), row.added.toString(), row.generationAdded.toString(), row.generationModified.toString(), row.mime) &&
                    row.pending == 0L && row.trashed == 0L
            } ?: return 0
            rows = rows.map { if (it === selected) it.copy(trashed = 1L, generationModified = (it.generationModified as Long) + 1) else it }
            afterTrash?.invoke(); return 1
        }
        override fun delete(uri: Uri, where: String?, args: Array<out String>?): Int = throw AssertionError("Unexpected photo delete")
    }
    private class Fixture(val mediaType: GalleryMediaType = GalleryMediaType.IMAGES) : AutoCloseable {
        val context = RuntimeEnvironment.getApplication()
        val root = Files.createTempDirectory(File("/tmp/opencode").toPath(), "gallery-pfd329-").toFile()
        val provider = Provider(root, mediaType)
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        var request: NativeGalleryRequest? = NativeGalleryRequest(receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), mediaType)
        val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, if (Build.VERSION.SDK_INT >= 29) "external_primary" else "external",
            "camera", "Camera", if (Build.VERSION.SDK_INT >= 29) "DCIM/Camera/" else null, 1, false)
        val scope = GalleryPhotoSourceScope({ request }, AndroidGalleryAccessEnvironment(context, mediaType) { "a".repeat(64) })
        val reader = AndroidGalleryPhotoSource(context, scope)
        init {
            File(root, "source.bin").writeText("hello")
            if (mediaType == GalleryMediaType.VIDEO) provider.rows = listOf(Row(name = "clip.mp4", mime = "video/mp4"))
            Shadows.shadowOf(context as Application).grantPermissions(if (Build.VERSION.SDK_INT >= 33)
                (if (mediaType == GalleryMediaType.IMAGES) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_MEDIA_VIDEO)
                else Manifest.permission.READ_EXTERNAL_STORAGE)
            provider.attachInfo(context, ProviderInfo().apply { authority = "media"; exported = true })
            ShadowContentResolver.registerProviderInternal("media", provider)
        }
        fun lease() = scope.capture(GalleryAlbumCatalog(if (mediaType == GalleryMediaType.IMAGES) GalleryReadCoverage.FULL_IMAGES
            else GalleryReadCoverage.FULL_VIDEOS, listOf(album), request), album)
        fun assertClosed() = assertTrue(provider.cursors.all { it.isClosed })
        override fun close() { assertClosed(); root.deleteRecursively() }
    }

    private fun filterIntent(): MediaSyncTransport.IntentToken {
        val pc = "11111111-1111-4111-8111-111111111111"; val phone = "22222222-2222-4222-8222-222222222222"
        return MediaSyncTransport.IntentToken(MediaSyncSettings.change(MediaSyncSettings.create(pc), pc, phone, "photos_only", JsonPrimitive(true)))
    }

    @Test @Config(sdk = [35]) fun metadataFilterIncludesRenamedCaptureAndExcludesCameraFolderScreenshot() {
        Fixture().use { f ->
            f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), mediaIntent = filterIntent())
            val image = CameraPhotoMetadataTest.photograph()
            val source = File(f.root, "capture.bin").also { it.writeBytes(image) }
            f.provider.restoredFiles[1L] = source
            f.provider.rows = listOf(Row(name = "renamed.txt", bytes = image.size.toLong()), Row(id = 2, name = "IMG_camera.jpg"))
            val inventory = f.reader.enumerate(f.lease())
            assertEquals(listOf("renamed.txt"), inventory.entries.map { it.relativePath })
            assertEquals(2, f.provider.opens.size); assertEquals(0, f.provider.writeRequests)
            assertEquals(0, f.provider.originalRequests)
            assertFalse(f.lease().provesFileDeletion)
        }
    }

    @Test @Config(sdk = [35]) fun metadataFilterAdvancesPastExcludedPagesAndRechecksRevokedRead() {
        Fixture().use { f ->
            f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), mediaIntent = filterIntent())
            f.provider.rows = (1L..33L).map { Row(id = it, name = "image-$it.jpg") }
            val lease = f.lease(); val batch = f.reader.enumerateBatch(lease)
            assertTrue(batch.inventory.entries.isEmpty()); assertNull(batch.continuation)
            assertEquals(33, f.provider.opens.size); assertEquals(2, f.provider.requests.size)
            f.provider.onOpen = { f.request = null }
            assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(lease) }
        }
    }

    @Test @Config(sdk = [35]) fun metadataFilterContinuationPreservesSelectedRowsAcrossExcludedMembers() {
        Fixture().use { f ->
            f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), mediaIntent = filterIntent())
            val image = CameraPhotoMetadataTest.photograph()
            val source = File(f.root, "capture.bin").also { it.writeBytes(image) }
            f.provider.restoredFiles[1L] = source; f.provider.restoredFiles[34L] = source
            f.provider.rows = (1L..34L).map { Row(id = it, name = "image-$it.jpg", bytes = if (it in setOf(1L, 34L)) image.size.toLong() else 5L) }
            val lease = f.lease(); val first = f.reader.enumerateBatch(lease, maxFiles = 1)
            assertEquals(listOf("image-1.jpg"), first.inventory.entries.map { it.relativePath }); assertNotNull(first.continuation)
            val second = f.reader.enumerateBatch(lease, first.continuation, maxFiles = 1)
            assertEquals(listOf("image-34.jpg"), second.inventory.entries.map { it.relativePath }); assertNull(second.continuation)
        }
    }

    @Test @Config(sdk = [35]) fun metadataPhotoFilterDoesNotFilterVideoOrOpenItsBytesDuringInventory() {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA), GalleryMediaType.VIDEO, filterIntent())
            assertEquals(1, f.reader.enumerate(f.lease()).entries.size); assertTrue(f.provider.opens.isEmpty())
        }
    }

    private fun archiveBook(f: Fixture): io.gitlab.maik3531.magnolienotes.daten.Ablage {
        val directory = Files.createTempDirectory(f.root.toPath(), "archive-book-").toFile()
        val context = object : android.content.ContextWrapper(f.context) {
            override fun getApplicationContext(): android.content.Context = this
            override fun getFilesDir(): File = directory
        }
        return io.gitlab.maik3531.magnolienotes.daten.Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 37 }, "AES") }
            .also { it.setzePapierkorb(true, 0) }
    }

    @Test @Config(sdk = [30]) fun disabledTrashDoesNotCreateHiddenRecoveryCopiesOrPrepareAnotherTrashAction() {
        Fixture().use { f ->
            val documents = archiveBook(f)
            val enabled = NativeGalleryTrashBookPermit.capture(documents) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 41 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "disabled-recovery-").toFile()
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            NativeGalleryTrashArchive(root, protection).use { archive ->
                val previous = archive.archive(lease, f.scope, entry, f.reader, hash, enabled)
                documents.setzePapierkorb(false, 0)
                val disabled = NativeGalleryTrashBookPermit.capture(documents) { true }
                assertFalse(disabled.trashEnabled)
                val opens = f.provider.opens.size
                assertThrows(PhotoFolderScopeError::class.java) { archive.archive(lease, f.scope, entry, f.reader, hash, disabled) }
                assertThrows(PhotoFolderScopeError::class.java) { archive.prepareTrash(previous, disabled) { } }
                val denied = assertThrows(PhotoFolderScopeError::class.java) {
                    NativeGalleryWriteRequest.prepare(f.context, archive, previous, disabled, { f.receiver })
                }
                assertEquals("gallery_trash_disabled", denied.message)
                assertEquals(opens, f.provider.opens.size)
                // A setting change does not purge historical user data. Those
                // copies stay explicit local recovery only, never OS mutation.
                assertEquals(listOf(previous), archive.entries(disabled))
                assertTrue(archive.actions(disabled).isEmpty()); assertEquals(0, f.provider.writeRequests)
                assertEquals(0, f.provider.trashWrites); assertEquals(0, f.provider.restoreInserts)
                assertEquals("hello", File(f.root, "source.bin").readText())
            }
        }
    }

    @Test @Config(sdk = [35]) @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    fun actualRecoveryPreviewReadsEncryptedArchiveWithoutProviderAccessOrHistoryMutation() {
        Fixture().use { f ->
            val pixels = android.graphics.Bitmap.createBitmap(800, 400, android.graphics.Bitmap.Config.ARGB_8888)
            pixels.eraseColor(android.graphics.Color.GREEN)
            val encoded = ByteArrayOutputStream().also { assertTrue(pixels.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)) }.toByteArray()
            pixels.recycle()
            File(f.root, "source.bin").writeBytes(encoded)
            f.provider.rows = listOf(Row(bytes = encoded.size.toLong(), mime = "image/png", name = "renamed.bin"))
            val documents = archiveBook(f); var unlocked = true
            val permit = NativeGalleryTrashBookPermit.capture(documents) { unlocked }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 41 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "preview-recovery-").toFile()
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest(encoded).joinToString("") { "%02x".format(it) }
            NativeGalleryTrashArchive(root, protection).use { archive ->
                val archived = archive.archive(lease, f.scope, entry, f.reader, hash, permit)
                val before = archive.entries(permit); val actions = archive.actions(permit)
                val opens = f.provider.opens.size
                f.request = null
                for (side in listOf(192, 1024)) {
                    val bitmap = NativeGalleryRecoveryPreview.read(archive, archived, permit, side, CancellationSignal()) { }
                    assertTrue(bitmap.width in 1..side && bitmap.height in 1..side)
                    assertEquals(android.graphics.Color.GREEN, bitmap.getPixel(bitmap.width / 2, bitmap.height / 2)); bitmap.recycle()
                }
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeGalleryRecoveryPreview.read(archive, archived.copy(version = "0".repeat(64)), permit, 192, CancellationSignal()) { }
                }
                assertEquals(before, archive.entries(permit)); assertEquals(actions, archive.actions(permit))
                assertEquals(opens, f.provider.opens.size); assertEquals(0, f.provider.writeRequests)
                assertEquals(0, f.provider.trashWrites); assertEquals(0, f.provider.restoreInserts)
                val canceled = CancellationSignal().apply { cancel() }
                assertThrows(android.os.OperationCanceledException::class.java) {
                    NativeGalleryRecoveryPreview.read(archive, archived, permit, 192, canceled) { }
                }
                unlocked = false
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeGalleryRecoveryPreview.read(archive, archived, permit, 192, CancellationSignal()) { }
                }
                assertArrayEquals(encoded, File(f.root, "source.bin").readBytes())
            }
        }
    }

    @Test @Config(sdk = [35]) @org.robolectric.annotation.GraphicsMode(org.robolectric.annotation.GraphicsMode.Mode.NATIVE)
    fun recoveryPreviewRejectsActiveContentBoundsAndWithdrawalAfterDecode() {
        for (bytes in listOf("<svg/>".toByteArray(), ByteArray(0))) assertThrows(PhotoFolderScopeError::class.java) {
            NativeGalleryRecoveryPreview.decode(bytes, "images", 192) { }
        }
        val pixels = android.graphics.Bitmap.createBitmap(20, 10, android.graphics.Bitmap.Config.ARGB_8888)
        val bytes = ByteArrayOutputStream().also { pixels.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }.toByteArray(); pixels.recycle()
        var checks = 0
        assertThrows(PhotoFolderScopeError::class.java) {
            NativeGalleryRecoveryPreview.decode(bytes, "images", 192) {
                if (++checks == 3) throw PhotoFolderScopeError("preview_owner_retired")
            }
        }
        assertEquals(3, checks)
        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryRecoveryPreview.decode(bytes, "images", 9000) { } }
    }

    @Test @Config(sdk = [30]) fun actualRecoveryArchiveSurvivesSourceRevocationWithoutBecomingMutationAuthority() {
        Fixture().use { f ->
            val documents = archiveBook(f); var unlocked = true
            val permit = NativeGalleryTrashBookPermit.capture(documents) { unlocked }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 41 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "local-recovery-").toFile()
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            val archived = NativeGalleryTrashArchive(root, protection).use { archive ->
                val result = archive.archive(lease, f.scope, entry, f.reader, hash, permit)
                assertFalse(result.grantsMutationAuthority); assertFalse(result.isRemoteDeletionReceipt)
                assertEquals(5, result.bytes); assertEquals("image.jpg", result.displayName)
                archive.verifyContent(result, permit)
                assertThrows(java.nio.channels.OverlappingFileLockException::class.java) { NativeGalleryTrashArchive(root, protection) }
                result
            }
            f.request = null // Actual source/receiver scope is revoked, not local recovery ownership.
            NativeGalleryTrashArchive(root, protection).use { archive ->
                assertEquals(listOf(archived), archive.entries(permit)); archive.verifyContent(archived, permit)
                val restored = ByteArrayOutputStream(); archive.readContent(archived, permit) { restored.write(it) }
                assertArrayEquals("hello".toByteArray(), restored.toByteArray())
                assertThrows(PhotoFolderScopeError::class.java) { archive.archive(lease, f.scope, entry, f.reader, hash, permit) }
                unlocked = false
                assertThrows(PhotoFolderScopeError::class.java) { archive.verifyContent(archived, permit) }
                unlocked = true
                assertThrows(PhotoFolderScopeError::class.java) { archive.entries(permit) }
                archive.verifyContent(archived, NativeGalleryTrashBookPermit.capture(documents) { unlocked })
            }
            assertEquals("hello", File(f.root, "source.bin").readText()); f.assertClosed()
        }
    }

    @Test @Config(sdk = [30]) fun actualRecoveryArchiveFailedCopyKeyLossOrRevocationNeverChangesProviderBytes() {
        for (reason in listOf("hash", "key", "scope")) Fixture().use { f ->
            val documents = archiveBook(f); val permit = NativeGalleryTrashBookPermit.capture(documents) { true }
            var keyAvailable = true
            val protection = DeviceTransferProtection.fromExistingKeyReader { if (keyAvailable) SecretKeySpec(ByteArray(32) { 42 }, "AES") else null }
            val root = Files.createTempDirectory(f.root.toPath(), "failed-recovery-").toFile()
            val lease = f.lease(); val entry = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            NativeGalleryTrashArchive(root, protection).use { archive ->
                if (reason == "key") f.provider.onOpen = { keyAvailable = false }
                if (reason == "scope") f.provider.onOpen = { f.request = null }
                assertThrows(Exception::class.java) { archive.archive(lease, f.scope, entry, f.reader, if (reason == "hash") "0".repeat(64) else hash, permit) }
            }
            keyAvailable = true; f.provider.onOpen = null
            NativeGalleryTrashArchive(root, protection).use { assertTrue(it.entries(permit).isEmpty()) }
            assertEquals("hello", File(f.root, "source.bin").readText()); f.assertClosed()
        }
    }

    @Test @Config(sdk = [30]) fun actualRecoveryArchiveDoesNotRecreateMissingKeyHeaderOrMembership() {
        Fixture().use { f ->
            val documents = archiveBook(f); val permit = NativeGalleryTrashBookPermit.capture(documents) { true }
            val key = SecretKeySpec(ByteArray(32) { 43 }, "AES")
            val protection = DeviceTransferProtection.fromExistingKeyReader { key }
            val root = Files.createTempDirectory(f.root.toPath(), "guarded-recovery-").toFile()
            NativeGalleryTrashArchive(root, protection).use { assertTrue(it.entries(permit).isEmpty()) }
            val before = root.listFiles()!!.associate { it.name to it.readBytes().toList() }
            assertThrows(DeviceTransferKeyUnavailable::class.java) { NativeGalleryTrashArchive(root, DeviceTransferProtection.fromExistingKeyReader { null }) }
            assertEquals(before, root.listFiles()!!.associate { it.name to it.readBytes().toList() })
            val header = File(root, "media-recovery-owner.enc"); val kept = File(f.root, "kept-recovery-header.enc")
            Files.move(header.toPath(), kept.toPath())
            assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryTrashArchive(root, protection) }
            assertFalse(header.exists()); assertTrue(kept.exists())
            assertEquals("hello", File(f.root, "source.bin").readText())
        }
    }

    @Test @Config(sdk = [30]) fun actualRuntimeRecoveryArchiveUsesOriginalProviderAndDoesNotRetireOrSaveItsSourceJob() {
        ResumeRuntimeCase().use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val id = h.originalMedia["entries"]!!.jsonArray.single().jsonObject.string("file_id")
            h.watchEnd()
            val run = h.runtime.prepareRecoverableMember(h.selected, h.job, id, permit)
            h.awaitEnd()
            assertNull(run.nativeFailure()); assertEquals("archive_ready", run.phase)
            assertNotNull(run.completedNativeArchive()); assertNull(run.snapshotJob()); assertNull(run.completedNativeJob())
            val root = File(h.f.context.noBackupFilesDir, "native-media-recovery")
            NativeGalleryTrashArchive(root, h.protection).use {
                assertEquals(listOf(run.completedNativeArchive()), it.entries(permit)); it.verifyContent(run.completedNativeArchive()!!, permit)
            }
            assertTrue(h.drain().isEmpty()); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualRuntimeCloseRetainsRecoveryArchiveIoSlotUntilBlockedProviderActuallyEnds() {
        ResumeRuntimeCase().use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val id = h.originalMedia["entries"]!!.jsonArray.single().jsonObject.string("file_id")
            val entered = java.util.concurrent.CountDownLatch(1)
            h.f.provider.onOpen = { entered.countDown(); assertTrue(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            var closed = false
            h.watchEnd()
            val run = h.runtime.prepareRecoverableMember(h.selected, h.job, id, permit)
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.prepareSource(h.selected) }
                val before = System.nanoTime()
                assertFalse(h.runtime.closeWhenQuiescent { h.runtime.close(); closed = true })
                assertTrue((System.nanoTime() - before) / 1_000_000 < 1000)
                assertTrue(run.cancelRequested); assertFalse(run.ioEnded); assertFalse(h.worker.isQuiescent)
            } finally { h.release.countDown() }
            h.awaitEnd(); assertTrue(run.ioEnded); assertTrue(h.worker.isQuiescent)
            Shadows.shadowOf(android.os.Looper.getMainLooper()).idle(); assertTrue(closed)
            assertNull(run.completedNativeArchive()); assertNotNull(run.nativeFailure()); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualRuntimeRecoveryArchiveRejectsReusedRowsChangedRevisionAndChangedContent() {
        for (reason in listOf("insertion", "revision", "content")) ResumeRuntimeCase().use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val id = h.originalMedia["entries"]!!.jsonArray.single().jsonObject.string("file_id")
            if (reason == "insertion") h.f.provider.rows = listOf(Row(generationAdded = 2L, generationModified = 2L))
            if (reason == "revision") h.f.provider.rows = listOf(Row(generationModified = 2L))
            if (reason == "content") File(h.f.root, "source.bin").writeText("other")
            h.watchEnd(); val run = h.runtime.prepareRecoverableMember(h.selected, h.job, id, permit); h.awaitEnd()
            assertEquals("failed_held", run.phase); assertNotNull(run.nativeFailure()); assertNull(run.completedNativeArchive())
            assertEquals(if (reason == "content") "other" else "hello", File(h.f.root, "source.bin").readText())
            assertEquals(h.cipher, File(h.root, "photo-source-" + h.job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
            h.inspect { assertEquals(listOf(h.job), it.jobs()); assertNull(it.remoteSaved(h.job)); assertEquals(h.originalAcceptance, it.remoteAcceptance(h.job)!!.record) }
        }
    }

    @Test @Config(sdk = [30]) fun recoveryArchiveRejectsMissingMembershipCorruptChunksAndForeignSchemaWithoutTouchingSource() {
        for (reason in listOf("member", "chunk", "schema")) Fixture().use { f ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(f)) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 45 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "damaged-recovery-").toFile()
            val lease = f.lease(); val file = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            val entry = NativeGalleryTrashArchive(root, protection).use { it.archive(lease, f.scope, file, f.reader, hash, permit) }
            android.database.sqlite.SQLiteDatabase.openDatabase(File(root, "media-recovery.db").path, null,
                android.database.sqlite.SQLiteDatabase.OPEN_READWRITE or android.database.sqlite.SQLiteDatabase.NO_LOCALIZED_COLLATORS).use { db ->
                when (reason) {
                    "member" -> db.delete("recovery_entries", "id=?", arrayOf(entry.id))
                    "schema" -> db.execSQL("CREATE TABLE foreign_rows(value TEXT)")
                    else -> {
                        val cipher = db.rawQuery("SELECT sealed FROM recovery_chunks WHERE id=? AND number=0", arrayOf(entry.id)).use { it.moveToFirst(); it.getBlob(0) }
                        cipher[cipher.lastIndex] = (cipher.last().toInt() xor 1).toByte()
                        db.update("recovery_chunks", ContentValues().apply { put("sealed", cipher) }, "id=? AND number=0", arrayOf(entry.id))
                    }
                }
            }
            if (reason == "chunk") NativeGalleryTrashArchive(root, protection).use {
                assertThrows(javax.crypto.AEADBadTagException::class.java) { it.verifyContent(entry, permit) }
            } else assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryTrashArchive(root, protection) }
            assertEquals("hello", File(f.root, "source.bin").readText())
        }
    }

    private fun originalPermissionResult(h: ResumeRuntimeCase, code: Int, reported: Boolean) {
        // Actual framework dispatch releases mHasCurrentPermissionsRequest
        // BEFORE calling AndroidX onRequestPermissionsResult/registry. Calling
        // only that callback would leave Android's OS dialog permanently busy.
        val data = Intent().apply {
            putExtra("android.content.pm.extra.REQUEST_PERMISSIONS_NAMES", arrayOf(Manifest.permission.ACCESS_MEDIA_LOCATION))
            putExtra("android.content.pm.extra.REQUEST_PERMISSIONS_RESULTS", intArrayOf(
                if (reported) android.content.pm.PackageManager.PERMISSION_GRANTED else android.content.pm.PackageManager.PERMISSION_DENIED))
        }
        android.app.Activity::class.java.getDeclaredMethod("dispatchRequestPermissionsResult", Int::class.javaPrimitiveType, Intent::class.java)
            .also { it.isAccessible = true }.invoke(h.activity.get(), code, data)
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
    }

    @Test @Config(sdk = [30]) fun explicitOriginalAccessRequiresActualOsPermissionAndDoesNotCreateArchiveOrWriteGrant() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val shadow = Shadows.shadowOf(h.activity.get())
            assertNull(shadow.lastRequestedPermission) // Normal source READ never asks for EXIF location.
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val results = mutableListOf<Result<Unit>>()
            h.runtime.requestGalleryOriginalAccess(GalleryMediaType.IMAGES, permit) { results += it }
            val first = shadow.lastRequestedPermission!!
            assertArrayEquals(arrayOf(Manifest.permission.ACCESS_MEDIA_LOCATION), first.requestedPermissions)
            originalPermissionResult(h, first.requestCode, true)
            assertTrue(results.single().isFailure) // A positive callback alone cannot grant OS permission.
            results.clear()
            h.runtime.requestGalleryOriginalAccess(GalleryMediaType.IMAGES, permit) { results += it }
            val second = shadow.lastRequestedPermission!!
            assertNotEquals(first.requestCode, second.requestCode)
            h.activity.pause().resume()
            Shadows.shadowOf(h.f.context as Application).grantPermissions(Manifest.permission.ACCESS_MEDIA_LOCATION)
            originalPermissionResult(h, second.requestCode, true)
            results.single().getOrThrow(); assertFalse(h.writeHost!!.requestPending)
            assertThrows(PhotoFolderScopeError::class.java) { h.catalog.page() }
            assertFalse(File(h.f.context.noBackupFilesDir, "native-media-recovery").exists())
            assertEquals(0, h.f.provider.writeRequests); assertEquals(0, h.f.provider.trashWrites)
            h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun originalAccessOldRepliesCannotConsumeNewRequestOrOverlapWriteAndReadDialogs() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val write = prepareArchivedWrite(h, permit)
            val results = mutableListOf<Result<Unit>>()
            h.runtime.requestGalleryOriginalAccess(GalleryMediaType.IMAGES, permit) { results += it }
            val old = Shadows.shadowOf(h.activity.get()).lastRequestedPermission!!.requestCode
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.requestGalleryWriteConsent(write) {} }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.requestReadPermission() }
            h.writeHost!!.retirePending()
            originalPermissionResult(h, old, false); assertTrue(results.single().isFailure); results.clear()
            h.runtime.requestGalleryOriginalAccess(GalleryMediaType.IMAGES, permit) { results += it }
            val fresh = Shadows.shadowOf(h.activity.get()).lastRequestedPermission!!.requestCode
            assertNotEquals(old, fresh)
            originalPermissionResult(h, old, true)
            assertTrue("stale result delivered ${results.map { it.exceptionOrNull()?.message }}", results.isEmpty()); assertTrue(h.writeHost.requestPending)
            Shadows.shadowOf(h.f.context as Application).grantPermissions(Manifest.permission.ACCESS_MEDIA_LOCATION)
            originalPermissionResult(h, fresh, true)
            assertTrue(results.single().isSuccess); assertFalse(h.writeHost.requestPending); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun originalAccessCannotSurviveBookChangeOrIndependentVideoPolicyReenable() {
        for (change in listOf("book", "video")) ResumeRuntimeCase(withWriteHost = true, mediaType = GalleryMediaType.VIDEO).use { h ->
            val documents = archiveBook(h.f); val permit = NativeGalleryTrashBookPermit.capture(documents) { true }
            var result: Result<Unit>? = null
            h.runtime.requestGalleryOriginalAccess(GalleryMediaType.VIDEO, permit) { result = it }
            val code = Shadows.shadowOf(h.activity.get()).lastRequestedPermission!!.requestCode
            if (change == "book") documents.setzePapierkorb(false, 0) else {
                h.runtime.configureVideosFromAuthenticatedCommand(h.runtime.savedPolicy(), false)
                h.runtime.configureVideosFromAuthenticatedCommand(h.runtime.savedPolicy(), true)
            }
            Shadows.shadowOf(h.f.context as Application).grantPermissions(Manifest.permission.ACCESS_MEDIA_LOCATION)
            originalPermissionResult(h, code, true)
            assertTrue(result!!.isFailure); assertEquals(0, h.f.provider.writeRequests); h.assertOriginal()
            Shadows.shadowOf(h.f.context as Application).denyPermissions(Manifest.permission.ACCESS_MEDIA_LOCATION)
        }
    }

    private fun prepareArchivedWrite(h: ResumeRuntimeCase, permit: NativeGalleryTrashBookPermit,
        entry: NativeGalleryArchiveEntry? = null): NativeGalleryWriteRequest {
        val archive = entry ?: run {
            h.watchEnd()
            val id = h.originalMedia["entries"]!!.jsonArray.single().jsonObject.string("file_id")
            val copying = h.runtime.prepareRecoverableMember(h.selected, h.job, id, permit)
            h.awaitEnd(); assertNull(copying.nativeFailure()); copying.completedNativeArchive()!!
        }
        h.watchEnd(); val preparing = h.runtime.prepareGalleryWriteConsent(archive, permit); h.awaitEnd()
        assertNull(preparing.nativeFailure()); assertEquals("write_request_ready", preparing.phase)
        assertNull(preparing.snapshotJob()); return preparing.completedNativeWriteRequest()!!
    }

    private fun writeResult(h: ResumeRuntimeCase, requestCode: Int, resultCode: Int): Boolean {
        val handled = h.activity.get().activityResultRegistry.dispatchResult(requestCode, resultCode, Intent())
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        return handled
    }

    @Test @Config(sdk = [30]) fun actualWriteConsentRequiresOsPermissionAndResumedActivityRatherThanResultBoolean() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val first = prepareArchivedWrite(h, permit); assertEquals(1, h.f.provider.writeRequests)
            assertNull(Shadows.shadowOf(h.activity.get()).lastIntentSenderRequest)
            val activity = h.activity.get() as WriteConsentActivity
            val draft = android.widget.EditText(activity).also { it.setText("native unsaved draft") }; activity.setContentView(draft)
            val results = mutableListOf<Result<NativeGalleryWriteGrant>>()
            h.runtime.requestGalleryWriteConsent(first) { results += it }
            var code = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            writeResult(h, code, android.app.Activity.RESULT_OK)
            assertTrue(results.single().isFailure); assertTrue(activity.writeChecks > 0)
            val canceled = prepareArchivedWrite(h, permit, first.entry)
            activity.writeAllowed = true; results.clear()
            h.runtime.requestGalleryWriteConsent(canceled) { results += it }
            code = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            writeResult(h, code, android.app.Activity.RESULT_CANCELED); assertTrue(results.single().isFailure)
            val accepted = prepareArchivedWrite(h, permit, first.entry); results.clear()
            h.runtime.requestGalleryWriteConsent(accepted) { results += it }
            code = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            h.activity.pause().resume() // Actual read-access epoch rotates across the OS UI.
            assertThrows(PhotoFolderScopeError::class.java) { h.catalog.page() }
            writeResult(h, code, android.app.Activity.RESULT_OK)
            val grant = results.single().getOrThrow(); grant.requireCurrent(); grant.consume()
            assertThrows(PhotoFolderScopeError::class.java) { grant.consume() }
            h.activity.pause().resume()
            assertThrows(PhotoFolderScopeError::class.java) { grant.requireCurrent() }
            assertEquals("native unsaved draft", draft.text.toString()); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualWriteConsentOldResultsCannotConsumeNewRequestAndPolicyChangeFailsClosed() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val documents = archiveBook(h.f); val permit = NativeGalleryTrashBookPermit.capture(documents) { true }
            val first = prepareArchivedWrite(h, permit); val second = prepareArchivedWrite(h, permit, first.entry)
            val activity = h.activity.get() as WriteConsentActivity; activity.writeAllowed = true
            val old = mutableListOf<Result<NativeGalleryWriteGrant>>(); val fresh = mutableListOf<Result<NativeGalleryWriteGrant>>()
            h.runtime.requestGalleryWriteConsent(first) { old += it }
            val oldCode = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            h.writeHost!!.retirePending()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.requestGalleryWriteConsent(second) { fresh += it } }
            assertTrue(h.writeHost.requestPending)
            writeResult(h, oldCode, android.app.Activity.RESULT_OK)
            assertTrue(old.single().isFailure); assertTrue(fresh.isEmpty())
            h.runtime.requestGalleryWriteConsent(second) { fresh += it }
            val newCode = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            assertNotEquals(oldCode, newCode)
            writeResult(h, oldCode, android.app.Activity.RESULT_OK)
            assertTrue(fresh.isEmpty()); assertTrue(h.writeHost.requestPending)
            documents.setzePapierkorb(false, 0)
            writeResult(h, newCode, android.app.Activity.RESULT_OK)
            assertTrue(fresh.single().isFailure); h.assertOriginal()
        }
    }

    private fun acceptedWriteAfterResume(h: ResumeRuntimeCase): NativeGalleryWriteGrant {
        val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
        val request = prepareArchivedWrite(h, permit)
        val activity = h.activity.get() as WriteConsentActivity; activity.writeAllowed = true
        var result: Result<NativeGalleryWriteGrant>? = null
        h.runtime.requestGalleryWriteConsent(request) { result = it }
        val code = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
        h.activity.pause().resume()
        assertThrows(PhotoFolderScopeError::class.java) { h.catalog.page() }
        writeResult(h, code, android.app.Activity.RESULT_OK)
        return result!!.getOrThrow()
    }

    @Test @Config(sdk = [30]) fun actualWriteConsentCannotSurviveMediaDisableAndReenableOnSamePeer() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val request = prepareArchivedWrite(h, permit)
            val activity = h.activity.get() as WriteConsentActivity; activity.writeAllowed = true
            val oldEpoch = h.runtime.currentRequest()!!.policyEpoch
            var result: Result<NativeGalleryWriteGrant>? = null
            h.runtime.requestGalleryWriteConsent(request) { result = it }
            val code = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            h.runtime.configureFromAuthenticatedCommand(h.runtime.savedPolicy(), false, emptySet())
            h.echoControls()
            h.runtime.configureFromAuthenticatedCommand(h.runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
            h.echoControls()
            assertNotEquals(oldEpoch, h.runtime.currentRequest()!!.policyEpoch)
            writeResult(h, code, android.app.Activity.RESULT_OK)
            assertTrue("old OS request must not inherit a new media consent epoch", result!!.isFailure)
            assertEquals(0, h.f.provider.trashWrites); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualVideoWriteConsentCannotInheritReenabledVideoPolicyOnSameDataBinding() {
        ResumeRuntimeCase(withWriteHost = true, mediaType = GalleryMediaType.VIDEO).use { h ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(h.f)) { true }
            val request = prepareArchivedWrite(h, permit)
            val activity = h.activity.get() as WriteConsentActivity; activity.writeAllowed = true
            val before = h.runtime.currentRequest(GalleryMediaType.VIDEO)!!
            var result: Result<NativeGalleryWriteGrant>? = null
            h.runtime.requestGalleryWriteConsent(request) { result = it }
            val code = Shadows.shadowOf(activity).lastIntentSenderRequest!!.requestCode
            h.runtime.configureVideosFromAuthenticatedCommand(h.runtime.savedPolicy(), false)
            h.runtime.configureVideosFromAuthenticatedCommand(h.runtime.savedPolicy(), true)
            val after = h.runtime.currentRequest(GalleryMediaType.VIDEO)!!
            assertNotEquals(before.policyEpoch, after.policyEpoch)
            assertEquals(before.receiver.permissionEpoch, after.receiver.permissionEpoch)
            writeResult(h, code, android.app.Activity.RESULT_OK)
            assertTrue("old write request must not inherit a new video policy", result!!.isFailure)
            assertEquals(0, h.f.provider.trashWrites); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualPostConsentTargetUsesFreshReadAuthorityAndKeepsOriginalHistory() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val grant = acceptedWriteAfterResume(h)
            h.watchEnd(); val checking = h.runtime.validateGalleryWriteTarget(grant); h.awaitEnd()
            assertNull(checking.nativeFailure()); assertEquals("write_target_verified", checking.phase)
            assertNull(checking.snapshotJob()); assertNull(checking.completedNativeArchive())
            val target = checking.completedNativeWriteTarget()!!
            assertFalse(target.isRemoteDeletionReceipt); target.requireCurrent()
            assertEquals(grant.request.uri.toString(), target.member.documentUri)
            h.activity.pause().resume()
            assertThrows(PhotoFolderScopeError::class.java) { target.requireCurrent() }
            h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualPostConsentTargetRejectsChangedRevisionReusedRowAndRawContent() {
        for (change in listOf("revision", "insertion", "content", "mime", "namespace")) ResumeRuntimeCase(withWriteHost = true).use { h ->
            val grant = acceptedWriteAfterResume(h)
            val row = h.f.provider.rows.single()
            when (change) {
                "revision" -> h.f.provider.rows = listOf(row.copy(generationModified = 2L))
                "insertion" -> h.f.provider.rows = listOf(row.copy(generationAdded = 2L, generationModified = 2L))
                "content" -> h.f.provider.originalFile = File(h.f.root, "changed-raw.bin").also { it.writeText("HELLO") }
                "mime" -> h.f.provider.rows = listOf(row.copy(mime = "image/png"))
                "namespace" -> h.f.provider.namespace = "replaced-volume"
            }
            h.watchEnd(); val checking = h.runtime.validateGalleryWriteTarget(grant); h.awaitEnd()
            assertNotNull("must reject $change", checking.nativeFailure()); assertEquals("failed_held", checking.phase)
            assertNull(checking.completedNativeWriteTarget()); h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualLocalTrashRequiresPreparedJournalConditionalProviderUpdateAndReadback() =
        actualLocalTrashCase(GalleryMediaType.IMAGES)

    @Test @Config(sdk = [30]) fun actualLocalVideoTrashUsesCurrentIndependentVideoConsentAndOriginalReadback() =
        actualLocalTrashCase(GalleryMediaType.VIDEO)

    private fun actualLocalTrashCase(mediaType: GalleryMediaType) {
        ResumeRuntimeCase(withWriteHost = true, mediaType = mediaType).use { h ->
            val grant = acceptedWriteAfterResume(h)
            h.f.provider.allowTrash = true
            h.f.provider.beforeTrash = {
                val dbFile = File(h.f.context.noBackupFilesDir, "native-media-recovery/media-recovery.db")
                android.database.sqlite.SQLiteDatabase.openDatabase(dbFile.path, null,
                    android.database.sqlite.SQLiteDatabase.OPEN_READONLY or android.database.sqlite.SQLiteDatabase.NO_LOCALIZED_COLLATORS).use { db ->
                    db.rawQuery("SELECT name FROM recovery_meta WHERE name<>'membership'", null).use {
                        assertTrue(it.moveToFirst()); assertTrue(it.getString(0).endsWith("/1")); assertFalse(it.moveToNext())
                    }
                }
            }
            h.watchEnd(); val trash = h.runtime.trashGalleryOriginal(grant); h.awaitEnd()
            assertNull(trash.nativeFailure()); assertEquals("local_trash_verified", trash.phase)
            assertEquals(1, h.f.provider.trashWrites); assertEquals(1L, h.f.provider.rows.single().trashed)
            assertFalse(trash.completedNativeTrashAction()!!.isRemoteDeletionReceipt)
            NativeGalleryTrashArchive.openForApplication(h.f.context, h.protection).use {
                assertEquals("trashed", it.actions(grant.request.permit).single().state)
                val restored = ByteArrayOutputStream(); it.readContent(grant.request.entry, grant.request.permit) { bytes -> restored.write(bytes) }
                assertEquals("hello", restored.toString("UTF-8"))
            }
            h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualLocalTrashRacingEditOrUnprovenReadbackRemainsPreparedWithoutReceipt() {
        for (change in listOf("race", "readback")) ResumeRuntimeCase(withWriteHost = true).use { h ->
            val grant = acceptedWriteAfterResume(h); h.f.provider.allowTrash = true
            if (change == "race") h.f.provider.beforeTrash = { h.f.provider.rows = listOf(Row(generationModified = 2L)) }
            else h.f.provider.afterTrash = { h.f.provider.originalFile = File(h.f.root, "changed-trash.bin").also { it.writeText("OTHER") } }
            h.watchEnd(); val trash = h.runtime.trashGalleryOriginal(grant); h.awaitEnd()
            assertNotNull(trash.nativeFailure()); assertEquals("failed_held", trash.phase)
            assertNull(trash.completedNativeTrashAction()); assertEquals(1, h.f.provider.trashWrites)
            assertEquals(if (change == "race") 0L else 1L, h.f.provider.rows.single().trashed)
            NativeGalleryTrashArchive.openForApplication(h.f.context, h.protection).use {
                assertEquals("prepared", it.actions(grant.request.permit).single { action -> action.archiveId == grant.request.entry.id }.state)
                it.verifyContent(grant.request.entry, grant.request.permit)
            }
            h.assertOriginal()
        }
    }

    @Test @Config(sdk = [30]) fun actualRuntimeRestoreCreatesNewOwnedRowPreservesArchiveAndCannotReplayDeletion() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val grant = acceptedWriteAfterResume(h); h.f.provider.allowTrash = true
            h.watchEnd(); val trash = h.runtime.trashGalleryOriginal(grant); h.awaitEnd()
            assertNull(trash.nativeFailure()); val selected = trash.completedNativeTrashAction()!!
            h.f.provider.allowRestore = true
            h.runtime.disableLocally(h.runtime.savedPolicy())
            assertNull(h.runtime.currentRequest()) // Restoration is LOCAL, not a historical READ grant.
            val session = NativeGalleryRestoreSession.capture(h.activity.get(), selected, grant.request.permit)
            session.use {
                h.watchEnd(); val restoring = h.runtime.restoreGalleryOriginal(session); h.awaitEnd()
                assertNull(restoring.nativeFailure()); assertEquals("local_restore_verified", restoring.phase)
                assertNull(restoring.snapshotJob()); assertNull(restoring.completedNativeTrashAction())
                val restored = restoring.completedNativeRestoreAction()!!
                assertEquals("restored", restored.state); assertEquals(5, restored.sequence); assertFalse(restored.isRemoteDeletionReceipt)
                val row = h.f.provider.rows.single { row -> row.pending == 0L && row.trashed == 0L }
                assertNotEquals(1L, row.id); assertEquals(h.f.context.packageName, row.owner)
                assertNotEquals("image.jpg", row.name) // Existing name is preserved, never overwritten.
                assertEquals("hello", h.f.provider.restoredFiles[row.id]!!.readText())
                NativeGalleryTrashArchive.openForApplication(h.f.context, h.protection).use { archive ->
                    assertEquals(restored, archive.actions(grant.request.permit).single())
                    archive.verifyContent(grant.request.entry, grant.request.permit)
                    assertThrows(PhotoFolderScopeError::class.java) { archive.prepareRestore(selected, grant.request.permit) {} }
                    assertThrows(PhotoFolderScopeError::class.java) { archive.finishTrash(selected, grant.request.permit) {} }
                    assertThrows(PhotoFolderScopeError::class.java) { archive.prepareTrash(grant.request.entry, grant.request.permit) {} }
                }
                assertThrows(PhotoFolderScopeError::class.java) { session.consume() }
            }
            assertEquals(1, h.f.provider.restoreInserts); assertEquals(1, h.f.provider.restoreWrites); assertEquals(1, h.f.provider.restorePublishes)
            assertEquals(1L, h.f.provider.rows.single { it.id == 1L }.trashed); h.assertOriginal()
        }
    }

    private fun independentRestoreCase(video: Boolean, change: String? = null) {
        Fixture(if (video) GalleryMediaType.VIDEO else GalleryMediaType.IMAGES).use { f ->
            val documents = archiveBook(f); val permit = NativeGalleryTrashBookPermit.capture(documents) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 61 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "local-restore-").toFile()
            val lease = f.lease(); val member = f.reader.enumerate(lease).entries.single()
            f.provider.originalFile = File(f.root, "exact-restore-original.bin").also { it.writeText("RAW!!") }
            val sha = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            lateinit var archived: NativeGalleryArchiveEntry
            val selected = NativeGalleryTrashArchive(root, protection).use {
                archived = it.archive(lease, f.scope, member, f.reader, sha, permit)
                it.finishTrash(it.prepareTrash(archived, permit) {}, permit) {} // Storage fixture, not a provider mutation proof.
            }
            f.request = null; f.provider.rows = emptyList(); f.provider.denyOriginal = true
            Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO)
            val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup()
            val session = NativeGalleryRestoreSession.capture(controller.get(), selected, permit)
            try {
                f.provider.allowRestore = true
                when (change) {
                    "owner" -> f.provider.afterRestoreInsert = { f.provider.rows = f.provider.rows.map { it.copy(owner = "foreign.app") } }
                    "readback" -> f.provider.corruptRestoreRead = true
                    "race" -> f.provider.beforeRestorePublish = { f.provider.rows = f.provider.rows.map { it.copy(generationModified = (it.generationModified as Long) + 1) } }
                    "old_uri" -> f.provider.restoreReturnsOldUri = true
                    "published_namespace" -> f.provider.afterRestorePublish = { f.provider.namespace = "changed-after-publish" }
                    "lost_finish" -> f.provider.afterRestorePublish = { session.close() }
                    "before_publish", "recovery_replaced", "recovery_content" -> f.provider.beforeRestorePublish = { session.close(); throw PhotoFolderScopeError("fixture_restore_publish_interrupted") }
                    "pause" -> controller.pause().resume()
                    "book" -> documents.setzePapierkorb(false, 0)
                }
                NativeGalleryTrashArchive(root, protection).use { archive ->
                    if (change == null) {
                        val restored = NativeGalleryMediaRestore(f.context).restore(archive, session, CancellationSignal())
                        assertEquals("restored", restored.state); assertNotNull(restored.restoredMember)
                        assertEquals("RAW!!", f.provider.restoredFiles.values.single().readText())
                        assertEquals(0L, f.provider.rows.single().pending)
                    } else {
                        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryMediaRestore(f.context).restore(archive, session, CancellationSignal()) }
                        if (change in setOf("pause", "book")) assertEquals(0, f.provider.restoreInserts)
                        else {
                            assertEquals(1, f.provider.restoreInserts)
                            assertEquals(if (change in setOf("published_namespace", "lost_finish")) 0L else 1L, f.provider.rows.single().pending)
                            val held = archive.actions(permit).single()
                            assertEquals(if (change in setOf("owner", "old_uri")) "restore_prepared" else "restore_row_prepared", held.state)
                            if (change in setOf("owner", "old_uri")) assertEquals(0, f.provider.restoreWrites)
                            assertThrows(PhotoFolderScopeError::class.java) { archive.prepareRestore(selected, permit) {} }
                            if (change in setOf("lost_finish", "before_publish")) {
                                f.provider.beforeRestorePublish = null; f.provider.afterRestorePublish = null
                                NativeGalleryRestoreSession.capture(controller.get(), held, permit).use { fresh ->
                                    val recovered = NativeGalleryMediaRestore(f.context).restore(archive, fresh, CancellationSignal())
                                    assertEquals("restored", recovered.state); assertEquals(5, recovered.sequence)
                                    assertEquals("RAW!!", f.provider.restoredFiles.values.single().readText())
                                    assertEquals(0L, f.provider.rows.single().pending)
                                    assertEquals(1, f.provider.restoreInserts); assertEquals(1, f.provider.restoreWrites)
                                    assertEquals(1, f.provider.restorePublishes)
                                }
                            }
                            if (change in setOf("recovery_replaced", "recovery_content")) {
                                f.provider.beforeRestorePublish = null
                                if (change == "recovery_replaced") f.provider.rows = f.provider.rows.map {
                                    it.copy(generationAdded = (it.generationAdded as Long) + 1, generationModified = (it.generationModified as Long) + 1)
                                } else f.provider.restoredFiles.values.single().writeText("OTHER")
                                NativeGalleryRestoreSession.capture(controller.get(), held, permit).use { fresh ->
                                    assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryMediaRestore(f.context).restore(archive, fresh, CancellationSignal()) }
                                }
                                assertEquals(1, f.provider.restoreInserts); assertEquals(1, f.provider.restoreWrites)
                                assertEquals(0, f.provider.restorePublishes)
                                assertEquals(held, archive.actions(permit).single())
                            }
                        }
                    }
                    if (change != "book") archive.verifyContent(archived, permit)
                }
                assertEquals("hello", File(f.root, "source.bin").readText())
                assertEquals(0, f.provider.trashWrites); assertEquals(0, f.provider.writeRequests)
            } finally { session.close(); controller.pause().stop().destroy() }
        }
    }

    @Test @Config(sdk = [30]) fun actualLocalRecoveryRestoresWithoutPeerSourceOrReadPermission() = independentRestoreCase(false)
    @Test @Config(sdk = [33]) fun actualLocalVideoRecoveryReadsOriginalFormatAndRestoresWithoutHistoricalGrant() = independentRestoreCase(true)
    @Test @Config(sdk = [30]) fun localRestoreForeignOwnerOrBadReadbackOrPublishRaceNeverClaimsRestored() {
        for (change in listOf("owner", "readback", "race", "old_uri", "published_namespace")) independentRestoreCase(false, change)
    }
    @Test @Config(sdk = [30]) fun localRestorePausedActivityOrChangedBookCannotCreateAnyRow() {
        for (change in listOf("pause", "book")) independentRestoreCase(false, change)
    }
    @Test @Config(sdk = [30]) fun localRestoreRecoversCompletedCopyOrLostCompletionWithoutDuplicateInsertOrOverwrite() {
        for (change in listOf("before_publish", "lost_finish")) independentRestoreCase(false, change)
    }
    @Test @Config(sdk = [30]) fun localRestoreRecoveryRejectsReusedPendingRowOrEditedBytesWithoutWritingAgain() {
        for (change in listOf("recovery_replaced", "recovery_content")) independentRestoreCase(false, change)
    }

    @Test @Config(sdk = [30]) fun actualRuntimeCloseHoldsRestoreIoUntilNewRowDescriptorReturns() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val grant = acceptedWriteAfterResume(h); h.f.provider.allowTrash = true
            h.watchEnd(); val trash = h.runtime.trashGalleryOriginal(grant); h.awaitEnd(); assertNull(trash.nativeFailure())
            val session = NativeGalleryRestoreSession.capture(h.activity.get(), trash.completedNativeTrashAction()!!, grant.request.permit)
            session.use {
                h.f.provider.allowRestore = true
                val entered = java.util.concurrent.CountDownLatch(1)
                h.f.provider.beforeRestoreWrite = { entered.countDown(); assertTrue(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                var closed = false; h.watchEnd()
                val run = h.runtime.restoreGalleryOriginal(session)
                try {
                    assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    assertThrows(PhotoFolderScopeError::class.java) { h.runtime.restoreGalleryOriginal(session) }
                    assertFalse(h.runtime.closeWhenQuiescent { h.runtime.close(); closed = true })
                    assertTrue(run.cancelRequested); assertFalse(run.ioEnded); assertFalse(h.worker.isQuiescent)
                } finally { h.release.countDown() }
                h.awaitEnd(); Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                assertTrue(closed); assertTrue(h.worker.isQuiescent); assertNotNull(run.nativeFailure())
                assertNull(run.completedNativeRestoreAction()); assertEquals(0, h.f.provider.restorePublishes)
                NativeGalleryTrashArchive.openForApplication(h.f.context, h.protection).use { archive ->
                    assertEquals("restore_row_prepared", archive.actions(grant.request.permit).single().state)
                    archive.verifyContent(grant.request.entry, grant.request.permit)
                }
                h.assertOriginal()
            }
        }
    }

    private fun localRecoveryEnd(owner: NativeGalleryLocalRecovery): java.util.concurrent.CountDownLatch {
        val worker = NativeGalleryLocalRecovery::class.java.getDeclaredField("worker").also { it.isAccessible = true }.get(owner)
        val field = NativeGallerySourceWorker::class.java.getDeclaredField("onEnded").also { it.isAccessible = true }
        @Suppress("UNCHECKED_CAST") val original = field.get(worker) as (NativeGallerySourceRun) -> Unit
        val ended = java.util.concurrent.CountDownLatch(1)
        field.set(worker, { run: NativeGallerySourceRun -> try { original(run) } finally { ended.countDown() } })
        return ended
    }

    private fun awaitLocalRecovery(ended: java.util.concurrent.CountDownLatch) {
        assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
        Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
    }

    @Test @Config(sdk = [30]) fun localRecoveryPanelOwnerIsInertAndNeverInitializesMissingOrEmptyArchive() {
        Fixture().use { f ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(f)) { true }
            var keyReads = 0
            val protection = DeviceTransferProtection.fromExistingKeyReader { keyReads++; SecretKeySpec(ByteArray(32) { 71 }, "AES") }
            NativeGalleryLocalRecovery(f.context) { protection }.use { owner ->
                assertFalse(owner.present); assertEquals(0, keyReads)
                var result: Result<List<NativeGalleryRecoveryRow>>? = null
                var ended = localRecoveryEnd(owner)
                owner.refresh(permit) { result = it }; awaitLocalRecovery(ended)
                assertTrue(result!!.getOrThrow().isEmpty()); assertEquals(0, keyReads); assertFalse(owner.present)
                val directory = File(f.context.noBackupFilesDir, "native-media-recovery")
                Files.createDirectory(directory.toPath(), java.nio.file.attribute.PosixFilePermissions.asFileAttribute(
                    java.nio.file.attribute.PosixFilePermissions.fromString("rwx------")))
                ended = localRecoveryEnd(owner); result = null
                owner.refresh(permit) { result = it }; awaitLocalRecovery(ended)
                assertTrue(result!!.isFailure); assertTrue(directory.listFiles()!!.isEmpty()); assertEquals(0, keyReads)
                assertEquals(0, f.provider.writeRequests); assertEquals(0, f.provider.restoreInserts)
            }
        }
    }

    @Test @Config(sdk = [30]) fun nativeLocalRecoveryOwnerListsAndRestoresAfterOriginalConnectionRuntimeClosed() {
        ResumeRuntimeCase(withWriteHost = true).use { h ->
            val grant = acceptedWriteAfterResume(h); h.f.provider.allowTrash = true
            h.watchEnd(); val trash = h.runtime.trashGalleryOriginal(grant); h.awaitEnd(); assertNull(trash.nativeFailure())
            h.runtime.close() // Actual old channel/index/host retirement, not a fake historical grant.
            NativeGalleryLocalRecovery(h.f.context) { h.protection }.use { owner ->
                var listing: Result<List<NativeGalleryRecoveryRow>>? = null
                var ended = localRecoveryEnd(owner)
                owner.refresh(grant.request.permit) { listing = it }; awaitLocalRecovery(ended)
                val row = listing!!.getOrThrow().single(); assertTrue(row.canRestore)
                assertEquals(trash.completedNativeTrashAction(), row.action)
                h.f.provider.allowRestore = true
                NativeGalleryRestoreSession.capture(h.activity.get(), row.action!!, grant.request.permit).use { session ->
                    var restored: Result<NativeGalleryTrashAction>? = null
                    ended = localRecoveryEnd(owner)
                    owner.restore(session) { restored = it }; awaitLocalRecovery(ended)
                    assertEquals("restored", restored!!.getOrThrow().state)
                }
                ended = localRecoveryEnd(owner); listing = null
                owner.refresh(grant.request.permit) { listing = it }; awaitLocalRecovery(ended)
                val done = listing!!.getOrThrow().single(); assertFalse(done.canRestore); assertEquals("restored", done.action!!.state)
                assertEquals("hello", h.f.provider.restoredFiles.values.single().readText())
                assertEquals(1, h.f.provider.restoreInserts); h.assertOriginal()
            }
        }
    }

    @Test @Config(sdk = [30]) fun recoveryTrashJournalIsDurableExclusiveAndCannotReplayAnOldPreparedSelection() {
        Fixture().use { f ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(f)) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 47 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "trash-action-").toFile()
            val lease = f.lease(); val file = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            lateinit var entry: NativeGalleryArchiveEntry
            val prepared = NativeGalleryTrashArchive(root, protection).use {
                entry = it.archive(lease, f.scope, file, f.reader, hash, permit)
                it.prepareTrash(entry, permit) {}.also { action ->
                    assertFalse(action.isRemoteDeletionReceipt)
                    assertThrows(PhotoFolderScopeError::class.java) { it.prepareTrash(entry, permit) {} }
                }
            }
            NativeGalleryTrashArchive(root, protection).use {
                assertEquals(listOf(prepared), it.actions(permit))
                val canceled = it.cancelUnmutatedTrash(prepared, permit) {}; assertEquals("canceled", canceled.state)
                assertThrows(PhotoFolderScopeError::class.java) { it.finishTrash(prepared, permit) {} }
                val fresh = it.prepareTrash(entry, permit) {}; assertNotEquals(prepared.operation, fresh.operation)
                // Journal-only transition: no OS mutation or remote receipt is
                // inferred by this storage-level fixture.
                val completed = it.finishTrash(fresh, permit) {}; assertEquals("trashed", completed.state)
                assertEquals(listOf(entry), it.entries(permit)); it.verifyContent(entry, permit)
            }
            assertEquals("hello", File(f.root, "source.bin").readText())
        }
    }

    @Test @Config(sdk = [30]) fun recoveryArchiveMustPreserveOriginalExifBytesRatherThanRedactedReadView() = originalRecoveryBytesCase(false)
    @Test @Config(sdk = [33]) fun recoveryVideoArchiveRequestsOriginalFormatWithoutCompatibilityTranscoding() = originalRecoveryBytesCase(true)

    private fun originalRecoveryBytesCase(video: Boolean) {
        Fixture(if (video) GalleryMediaType.VIDEO else GalleryMediaType.IMAGES).use { f ->
            val redacted = "safe redacted".toByteArray(); val original = "full original".toByteArray()
            assertEquals(redacted.size, original.size)
            File(f.root, "source.bin").writeBytes(redacted)
            f.provider.originalFile = File(f.root, "raw-original.bin").also { it.writeBytes(original) }
            f.provider.rows = listOf(Row(bytes = original.size.toLong(), name = if (video) "clip.mp4" else "image.jpg", mime = if (video) "video/mp4" else "image/jpeg"))
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(f)) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 51 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "original-recovery-").toFile()
            val lease = f.lease(); val file = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest(redacted).joinToString("") { "%02x".format(it) }
            NativeGalleryTrashArchive(root, protection).use {
                val entry = it.archive(lease, f.scope, file, f.reader, hash, permit)
                assertTrue(entry.originalBytesVerified)
                val restored = ByteArrayOutputStream(); it.readContent(entry, permit) { bytes -> restored.write(bytes) }
                assertArrayEquals(original, restored.toByteArray())
                assertEquals(1, f.provider.originalRequests)
                assertEquals(if (video) 1 else 0, f.provider.typedOriginalRequests)
            }
            assertArrayEquals(original, f.provider.originalFile!!.readBytes()); assertArrayEquals(redacted, File(f.root, "source.bin").readBytes())
        }
    }

    @Test @Config(sdk = [30]) fun deniedOriginalMediaCannotFallBackToRedactedArchiveOrWriteConsent() {
        Fixture().use { f ->
            f.provider.denyOriginal = true
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(f)) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 52 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "denied-original-").toFile()
            val lease = f.lease(); val file = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            NativeGalleryTrashArchive(root, protection).use {
                assertThrows(UnsupportedOperationException::class.java) { it.archive(lease, f.scope, file, f.reader, hash, permit) }
            }
            NativeGalleryTrashArchive(root, protection).use { assertTrue(it.entries(permit).isEmpty()) }
            assertEquals(1, f.provider.originalRequests); assertEquals(1, f.provider.opens.size)
            assertEquals(0, f.provider.writeRequests); assertEquals("hello", File(f.root, "source.bin").readText())
        }
    }

    @Test @Config(sdk = [30]) fun legacyRecoveryCopyStaysReadableButCannotAuthorizeOsWriteWithoutOriginalByteWitness() {
        Fixture().use { f ->
            val permit = NativeGalleryTrashBookPermit.capture(archiveBook(f)) { true }
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 53 }, "AES") }
            val root = Files.createTempDirectory(f.root.toPath(), "legacy-original-").toFile()
            val lease = f.lease(); val file = f.reader.enumerate(lease).entries.single()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest("hello".toByteArray()).joinToString("") { "%02x".format(it) }
            val created = NativeGalleryTrashArchive(root, protection).use { it.archive(lease, f.scope, file, f.reader, hash, permit) }
            val header = protection.open(File(root, "media-recovery-owner.enc").readBytes(), "gallery-media-recovery-v1/header")
            val owner = try { Json.parseToJsonElement(header.decodeToString()).jsonObject.string("owner") } finally { header.fill(0) }
            val prefix = "gallery-media-recovery-v1/$owner/"
            // Reconstruct a valid old-format encrypted fixture, not corrupt it
            // into a magically authorized new record. Preserve its raw bytes.
            android.database.sqlite.SQLiteDatabase.openDatabase(File(root, "media-recovery.db").path, null,
                android.database.sqlite.SQLiteDatabase.OPEN_READWRITE or android.database.sqlite.SQLiteDatabase.NO_LOCALIZED_COLLATORS).use { db ->
                val bytes = db.rawQuery("SELECT sealed FROM recovery_entries WHERE id=?", arrayOf(created.id)).use { it.moveToFirst(); it.getBlob(0) }
                val clear = protection.open(bytes, prefix + created.id + "/metadata")
                val body = try { Json.parseToJsonElement(clear.decodeToString()).jsonObject } finally { clear.fill(0) }
                val legacy = JsonObject(body.filterKeys { it !in setOf("original_bytes", "baseline_sha256") } + ("format" to JsonPrimitive(1)))
                val cipher = protection.seal(TelefonKanonisch.bytes(legacy), prefix + created.id + "/metadata")
                db.update("recovery_entries", ContentValues().apply { put("sealed", cipher) }, "id=?", arrayOf(created.id))
                val membership = buildJsonObject {
                    put("format", 1); put("revision", 3)
                    put("entries", JsonArray(listOf(buildJsonObject {
                        put("id", created.id); put("sha256", java.security.MessageDigest.getInstance("SHA-256").digest(cipher).joinToString("") { "%02x".format(it) })
                    })))
                }
                db.update("recovery_meta", ContentValues().apply { put("sealed", protection.seal(TelefonKanonisch.bytes(membership), prefix + "membership")) }, "name=?", arrayOf("membership"))
            }
            NativeGalleryTrashArchive(root, protection).use {
                val legacy = it.entries(permit).single(); assertFalse(legacy.originalBytesVerified)
                val restored = ByteArrayOutputStream(); it.readContent(legacy, permit) { bytes -> restored.write(bytes) }
                assertEquals("hello", restored.toString("UTF-8"))
                assertThrows(PhotoFolderScopeError::class.java) {
                    NativeGalleryWriteRequest.prepare(f.context, it, legacy, permit, { f.receiver.copy(pairingEpoch = "1".repeat(64)) })
                }
                assertEquals(0, f.provider.writeRequests)
            }
        }
    }

    @Test fun explicitAlbumBatchesVisitEveryMemberBeyond128WithoutOpeningPhotoBytes() {
        Fixture().use { f ->
            f.provider.rows = (1..300).map { Row(id = it.toLong(), name = "$it.jpg") }
            val lease = f.lease()
            var continuation: AndroidGalleryPhotoSource.Continuation? = null
            val ids = mutableListOf<String>(); val sizes = mutableListOf<Int>()
            do {
                val batch = f.reader.enumerateBatch(lease, continuation)
                assertFalse(batch.provesDeletion)
                sizes += batch.inventory.entries.size
                ids += batch.inventory.entries.map { it.documentId.substringBefore(':') }
                continuation = batch.continuation
                assertEquals(continuation == null, batch.reachedCurrentEnd)
            } while (continuation != null)
            assertEquals(listOf(128, 128, 44), sizes)
            assertEquals((1..300).map { it.toString() }, ids)
            assertTrue(f.provider.opens.isEmpty()); f.assertClosed()
            // The old whole-inventory API still refuses truncation.
            assertEquals("gallery_inventory_file_limit", assertThrows(PhotoFolderScopeError::class.java) {
                f.reader.enumerate(lease)
            }.code)
        }
    }

    @Test fun explicitAlbumBatchByteBoundaryDoesNotSkipTheLookaheadMember() {
        Fixture().use { f ->
            f.provider.rows = (1..9).map { Row(id = it.toLong(), name = "$it.jpg", bytes = DeviceFileManifest.MAX_FILE_BYTES) }
            val lease = f.lease()
            val first = f.reader.enumerateBatch(lease)
            assertEquals(8, first.inventory.entries.size); assertFalse(first.reachedCurrentEnd)
            val last = f.reader.enumerateBatch(lease, first.continuation)
            assertEquals(listOf("9:90"), last.inventory.entries.map { it.documentId })
            assertTrue(last.reachedCurrentEnd); assertFalse(last.provesDeletion)
            assertTrue(f.provider.opens.isEmpty())
        }
    }

    @Test fun explicitAlbumContinuationRejectsForeignLeaseRevocationAndCancellation() {
        Fixture().use { f ->
            f.provider.rows = (1..129).map { Row(id = it.toLong(), name = "$it.jpg") }
            val lease = f.lease(); val first = f.reader.enumerateBatch(lease)
            assertNotNull(first.continuation)
            assertEquals("gallery_inventory_continuation_changed", assertThrows(PhotoFolderScopeError::class.java) {
                f.reader.enumerateBatch(f.lease(), first.continuation)
            }.code)
            assertThrows(PhotoFolderScopeError::class.java) {
                AndroidGalleryPhotoSource(f.context, f.scope).enumerateBatch(lease, first.continuation)
            }
            val canceled = CancellationSignal().also { it.cancel() }
            assertThrows(OperationCanceledException::class.java) { f.reader.enumerateBatch(lease, first.continuation, canceled) }
            f.request = null
            assertEquals("gallery_inventory_source_revoked", assertThrows(PhotoFolderScopeError::class.java) {
                f.reader.enumerateBatch(lease, first.continuation)
            }.code)
        }
    }

    private class KnownAssociationCase(paired: Boolean = true, mediaType: GalleryMediaType = GalleryMediaType.IMAGES) : AutoCloseable {
        val f = Fixture(mediaType)
        val directory = Files.createTempDirectory(f.root.toPath(), "known-original338-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { 45 }, "AES") }
        var hook: (String) -> Unit = {}
        val index = PhotoSourceJobIndex(directory, protection) { hook(it) }
        val lease: GalleryPhotoSourceLease
        val job: PhotoSourceJob
        val source: IndexedPhotoSource
        val message: JsonObject
        init {
            val receiver = f.receiver.copy(pairingEpoch = if (paired) "1".repeat(64) else null)
            f.request = NativeGalleryRequest(receiver, f.request!!.policyEpoch, f.request!!.kinds, mediaType)
            lease = f.lease(); val inventory = f.reader.enumerate(lease)
            val reserved = index.reserve(inventory, f.scope)
            val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, f.reader, protection)
            job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
            source = index.restore(job, "sender_fixture_01", f.scope, lease)
            val manifest = source.manifest; val now = 1_800_000_000_000L
            val accepted = DeviceFileRemoteAcceptance(java.util.UUID.randomUUID().toString(), manifest.fingerprint, manifest.transferId,
                "c".repeat(64), receiver.permissionEpoch, "e".repeat(64), now + 60_000, "d".repeat(64))
            source.commitRemoteAcceptance(NativeGalleryOfferOutput(accepted.offerId, accepted.transferId, accepted.manifestSha256, accepted.expires), accepted) { }
            message = TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                put("format", 1); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                put("acceptance_sha256", accepted.acceptanceSha256); put("permission_epoch", accepted.permissionEpoch); put("destination_token", accepted.destinationToken)
                put("receipts", JsonArray(manifest.files.map { file -> buildJsonObject {
                    put("file_id", file.id); put("size", file.size); put("sha256", file.sha256); put("receipt_sha256", "0".repeat(64))
                } }))
            }, 60_000, now)
        }
        fun commit(): PhotoSourceRemoteSaved {
            val accepted = index.remoteAcceptance(job)!!.historicalAcceptance()
            return source.commitRemoteSaved(accepted, message) { }
        }
        fun metadata(): Map<String, List<Byte>> = android.database.sqlite.SQLiteDatabase.openDatabase(File(directory, "photo-source-jobs.db").path,
            null, android.database.sqlite.SQLiteDatabase.OPEN_READONLY).use { db -> buildMap {
            db.rawQuery("SELECT name,sealed FROM source_meta ORDER BY name", null).use { cursor ->
                while (cursor.moveToNext()) put(cursor.getString(0), cursor.getBlob(1).toList())
            }
        } }
        override fun close() { index.close(); f.close() }
    }

    @Test @Config(sdk = [35]) fun knownPhoneOriginalAssociationSurvivesActualCacheRetirementAndOfflineSourceLoss() {
        KnownAssociationCase().use { h ->
            assertTrue(h.index.knownPhoneMedia().isEmpty()); val manifest = h.source.manifest
            val saved = h.commit(); val known = h.index.knownPhoneMedia().single()
            assertEquals(manifest.fingerprint, known.reference.body.string("manifest_sha256"))
            assertEquals(saved.confirmation.members.single().receiptSha256, known.reference.body.string("receipt_sha256"))
            assertEquals(h.source.galleryOrigins!!.entries.single().photoId, known.reference.body.string("photo_id"))
            assertFalse(known.grantsWriteAuthority); assertFalse(known.provesDeletion); assertFalse(known.isSavedReceipt)
            h.index.retireCachedSnapshot(h.job)
            assertTrue(h.index.jobs().isEmpty()); assertFalse(h.index.rootFile(h.job).exists())
            File(h.f.root, "source.bin").let { check(it.renameTo(File(h.f.root, "held-original-source.bin"))) }
            h.f.request = null
            Shadows.shadowOf(h.f.context as Application).denyPermissions(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_EXTERNAL_STORAGE)
            val opens = h.f.provider.opens.toList(); val before = h.metadata(); h.index.close()
            PhotoSourceJobIndex.openExisting(h.directory, h.protection).use { reader ->
                assertEquals(known.body, reader.knownPhoneMedia(known.id)!!.body)
                assertEquals(known.body, reader.knownPhoneMedia().single().body)
                assertNull(reader.galleryPolicy().policy)
            }
            assertEquals(before, h.metadata()); assertEquals(opens, h.f.provider.opens)
        }
    }

    @Test @Config(sdk = [35]) fun knownPhoneAssociationAndRemoteSavedCommitAtomicallyAndIdenticalRetryDoesNotRenewHistory() {
        KnownAssociationCase().use { h ->
            val before = h.metadata()
            h.hook = { if (it == "gallery-known-phone-media-recorded") throw java.io.IOException("explicit association writer interruption") }
            assertThrows(java.io.IOException::class.java) { h.commit() }
            assertNull(h.index.remoteSaved(h.job)); assertTrue(h.index.knownPhoneMedia().isEmpty()); assertEquals(before, h.metadata())
            assertEquals(h.job, h.index.jobs().single())
            h.hook = {}; val first = h.commit(); val known = h.index.knownPhoneMedia().single(); val sealed = h.metadata()
            assertEquals(first.record, h.commit().record); assertEquals(sealed, h.metadata())
            assertEquals(known.body, h.index.knownPhoneMedia(known.id)!!.body)
        }
    }

    @Test @Config(sdk = [35]) fun missingKnownPhoneMetadataIsIntegrityFailureNotAnEmptyAssociationThatSavedCanRecreate() {
        KnownAssociationCase().use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single()
            android.database.sqlite.SQLiteDatabase.openDatabase(File(h.directory, "photo-source-jobs.db").path, null,
                android.database.sqlite.SQLiteDatabase.OPEN_READWRITE).use { db ->
                assertEquals(1, db.delete("source_meta", "name=?", arrayOf(GalleryKnownPhoneMedia.PREFIX + known.id)))
            }
            assertThrows(PhotoFolderScopeError::class.java) { h.index.knownPhoneMedia(known.id) }
            assertThrows(PhotoFolderScopeError::class.java) { h.commit() }
        }
    }

    @Test @Config(sdk = [35]) fun phoneReturnReferencePinsOriginalPeerPairingContentAndManifestWithoutInventingCurrentAuthority() {
        KnownAssociationCase().use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single(); val ref = known.reference
            val key = ref.key("sender_fixture_01", h.f.receiver.peerId, h.f.receiver.identitySha256, "1".repeat(64))
            assertEquals(known.id, key)
            assertNotEquals(key, ref.key("sender_fixture_01", h.f.receiver.peerId, h.f.receiver.identitySha256, "2".repeat(64)))
            assertNotEquals(key, ref.key("sender_fixture_01", h.f.receiver.peerId, "3".repeat(64), "1".repeat(64)))
            val changed = GalleryPhoneMediaReference.parse(JsonObject(ref.body + ("original_sha256" to JsonPrimitive("4".repeat(64)))))
            assertNull(h.index.knownPhoneMedia(changed.key("sender_fixture_01", h.f.receiver.peerId, h.f.receiver.identitySha256, "1".repeat(64))))
            assertThrows(PhotoFolderScopeError::class.java) { GalleryPhoneMediaReference.parse(JsonObject(ref.body + ("write" to JsonPrimitive(true)))) }
            assertThrows(PhotoFolderScopeError::class.java) { GalleryKnownPhoneMedia.parse(JsonObject(known.body + ("native_member" to JsonPrimitive("1:90")))) }
        }
    }

    @Test @Config(sdk = [35]) fun unpairedGallerySavedRemainsHistoricalWithoutInventingNativeReturnAssociation() {
        KnownAssociationCase(paired = false).use { h ->
            h.commit(); assertNotNull(h.index.remoteSaved(h.job)); assertTrue(h.index.knownPhoneMedia().isEmpty())
        }
    }

    @Test @Config(sdk = [29]) fun legacyGalleryRowsWithoutNativeInsertionNamespaceDoNotAcquireReturnAssociationFromSaved() {
        KnownAssociationCase().use { h ->
            h.commit(); assertNotNull(h.index.remoteSaved(h.job)); assertTrue(h.index.knownPhoneMedia().isEmpty())
        }
    }

    @Test @Config(sdk = [35]) fun videoKnownOriginalUsesVideoAssociationWithoutPhotoFallback() {
        KnownAssociationCase(mediaType = GalleryMediaType.VIDEO).use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single()
            assertEquals(GalleryMediaType.VIDEO.uriSegment, known.reference.body.string("media_type"))
            assertFalse(known.grantsWriteAuthority); assertFalse(known.provesDeletion)
        }
    }

    @Test @Config(sdk = [35]) fun incomingPhoneInventoryCorrelatesOnlyProtectedSamePhonePcKeyOriginalAfterCacheRetirement() {
        KnownAssociationCase().use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single()
            val source = h.source.manifest
            val incoming = DeviceFileManifest.parse(JsonObject(source.wire() + mapOf(
                "sender_id" to JsonPrimitive(source.receiverId), "receiver_id" to JsonPrimitive(source.senderId))))
            val references = mapOf(incoming.files.single().id to known.reference)
            h.index.retireCachedSnapshot(h.job); h.f.request = null
            val scope = GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory",
                h.f.receiver.identitySha256, references, h.index::knownPhoneMedia)
            assertEquals(known.body, scope.associations.values.single().body)
            assertFalse(scope.associations.values.single().grantsWriteAuthority)
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory", "9".repeat(64), references, h.index::knownPhoneMedia)
            }
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingScope.capture(incoming, GalleryMediaType.VIDEO, "phone_inventory", h.f.receiver.identitySha256, references, h.index::knownPhoneMedia)
            }
            val foreignPhone = DeviceFileManifest.parse(JsonObject(incoming.wire() + ("receiver_id" to JsonPrimitive("foreign_phone_fixture_01"))))
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingScope.capture(foreignPhone, GalleryMediaType.IMAGES, "phone_inventory", h.f.receiver.identitySha256, references, h.index::knownPhoneMedia)
            }
        }
    }

    @Test @Config(sdk = [35]) fun incomingOriginalReferenceCannotBeInventedOrOmittedAndChangedPcVersionRemainsOnlyCorrelation() {
        KnownAssociationCase().use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single(); val source = h.source.manifest
            val files = source.wire()["files"]!!.jsonArray.map { JsonObject(it.jsonObject + ("sha256" to JsonPrimitive("9".repeat(64)))) }
            val incoming = DeviceFileManifest.parse(JsonObject(source.wire() + mapOf("sender_id" to JsonPrimitive(source.receiverId),
                "receiver_id" to JsonPrimitive(source.senderId), "files" to JsonArray(files))))
            val id = incoming.files.single().id
            val changed = GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory", h.f.receiver.identitySha256,
                mapOf(id to known.reference), h.index::knownPhoneMedia)
            assertEquals(known.id, changed.associations.getValue(id).id) // New bytes are independently verified by incoming copy.
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory", h.f.receiver.identitySha256,
                    emptyMap(), h.index::knownPhoneMedia)
            }
            val invented = GalleryPhoneMediaReference.parse(JsonObject(known.reference.body + ("receipt_sha256" to JsonPrimitive("8".repeat(64)))))
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory", h.f.receiver.identitySha256,
                    mapOf(id to invented), h.index::knownPhoneMedia)
            }
            val entire = GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "entire_collection", h.f.receiver.identitySha256,
                emptyMap()) { error("Unknown entire-collection file must not manufacture native history") }
            assertTrue(entire.associations.isEmpty())
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "entire_collection", h.f.receiver.identitySha256,
                    mapOf(id to invented), h.index::knownPhoneMedia)
            }
        }
    }

    @Test @Config(sdk = [35]) fun protectedIncomingJournalRetainsOriginalAssociationAcrossAllStatesAndOfflineReopen() {
        KnownAssociationCase().use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single(); val source = h.source.manifest
            val incoming = DeviceFileManifest.parse(JsonObject(source.wire() + mapOf(
                "sender_id" to JsonPrimitive(source.receiverId), "receiver_id" to JsonPrimitive(source.senderId))))
            val file = incoming.files.single()
            val scope = GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory", h.f.receiver.identitySha256,
                mapOf(file.id to known.reference), h.index::knownPhoneMedia)
            val binding = DeviceTransferBinding(incoming.senderId, incoming.receiverId, h.f.receiver.identitySha256,
                "d".repeat(64), "b".repeat(64), "c".repeat(64))
            var saved = h.index.reserveIncomingPublication(GalleryIncomingPublication.plan(binding, incoming, file.id,
                "2".repeat(64), GalleryMediaType.IMAGES, "image/jpeg", scope)) { }
            val row = buildJsonObject {
                put("uri", "content://media/external_primary/images/media/99"); put("namespace", "new-native-namespace")
                put("volume", "external_primary"); put("member", "99:90:10"); put("revision", "10")
                put("path", "Pictures/Magnolie/"); put("name", "restored.jpg"); put("mime_type", "image/jpeg"); put("owner", "native-fixture")
            }
            // Journal-state fixture only: no claim that these simulated rows were copied or published by Android.
            saved = h.index.beginIncomingInsertion(saved) { }; saved = h.index.recordIncomingRow(saved, row) { }
            saved = h.index.beginIncomingCopy(saved) { }; saved = h.index.recordIncomingVerifiedCopy(saved, row) { }
            saved = h.index.beginIncomingPublishing(saved) { }
            saved = h.index.recordIncomingPublished(saved, JsonObject(row + ("revision" to JsonPrimitive("11")))) { }
            assertEquals(known.id, saved.knownOriginalId); assertEquals(JsonPrimitive(2), saved.body["format"])
            assertEquals(scope.fingerprint(incoming), saved.body.string("scope_sha256")); assertFalse(saved.grantsWriteAuthority)
            h.index.retireCachedSnapshot(h.job); h.f.request = null; h.index.close()
            PhotoSourceJobIndex.openExisting(h.directory, h.protection).use { reopened ->
                val restored = reopened.incomingPublication(saved.id)!!
                assertEquals(saved.body, restored.body); assertEquals(known.body, reopened.knownPhoneMedia(restored.knownOriginalId!!)!!.body)
                assertNull(reopened.galleryPolicy().policy)
            }
        }
    }

    @Test @Config(sdk = [35]) fun incomingJournalRejectsUnknownOriginalAndCannotChangeScopeUnderAnExistingRowIdentity() {
        KnownAssociationCase().use { h ->
            h.commit(); val known = h.index.knownPhoneMedia().single(); val source = h.source.manifest
            val incoming = DeviceFileManifest.parse(JsonObject(source.wire() + mapOf(
                "sender_id" to JsonPrimitive(source.receiverId), "receiver_id" to JsonPrimitive(source.senderId))))
            val file = incoming.files.single()
            val scope = GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "phone_inventory", h.f.receiver.identitySha256,
                mapOf(file.id to known.reference), h.index::knownPhoneMedia)
            val binding = DeviceTransferBinding(incoming.senderId, incoming.receiverId, h.f.receiver.identitySha256,
                "d".repeat(64), "b".repeat(64), "c".repeat(64))
            val plan = GalleryIncomingPublication.plan(binding, incoming, file.id, "2".repeat(64), GalleryMediaType.IMAGES, "image/jpeg", scope)
            val forged = GalleryIncomingPublication.parse(JsonObject(plan.body + ("known_original_id" to JsonPrimitive("9".repeat(64)))))
            val before = h.metadata()
            assertThrows(PhotoFolderScopeError::class.java) { h.index.reserveIncomingPublication(forged) { } }
            assertNull(h.index.incomingPublication(plan.id)); assertEquals(before, h.metadata())
            h.index.reserveIncomingPublication(plan) { }
            val entire = GalleryIncomingScope.capture(incoming, GalleryMediaType.IMAGES, "entire_collection", h.f.receiver.identitySha256,
                emptyMap(), h.index::knownPhoneMedia)
            val changed = GalleryIncomingPublication.plan(binding, incoming, file.id, "2".repeat(64), GalleryMediaType.IMAGES, "image/jpeg", entire)
            assertEquals(plan.id, changed.id)
            assertThrows(PhotoFolderScopeError::class.java) { h.index.reserveIncomingPublication(changed) { } }
            assertEquals(plan.body, h.index.incomingPublication(plan.id)!!.body)
            val legacy = GalleryIncomingPublication.plan(binding, incoming, file.id, "2".repeat(64), GalleryMediaType.IMAGES, "image/jpeg")
            assertNull(legacy.knownOriginalId); assertEquals(plan.id, legacy.id)
            assertEquals(legacy.body, GalleryIncomingPublication.parse(legacy.body).body)
            assertThrows(PhotoFolderScopeError::class.java) { h.index.reserveIncomingPublication(legacy) { } }
            assertThrows(PhotoFolderScopeError::class.java) {
                GalleryIncomingPublication.parse(JsonObject(plan.body + ("known_original_id" to JsonNull)))
            }
        }
    }

    private class HistoricalCase : AutoCloseable {
        val f = Fixture()
        val directory = Files.createTempDirectory(f.root.toPath(), "historical350-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val now = 1_800_000_000_000L
        val job: PhotoSourceJob
        val message: JsonObject
        var receiver: NativePhotoReceiver? = f.receiver.copy(owner = Any(), pairingEpoch = "1".repeat(64))
        private val held: File
        init {
            f.request = NativeGalleryRequest(receiver!!, f.request!!.policyEpoch, f.request!!.kinds, f.request!!.mediaType)
            val lease = f.lease(); val inventory = f.reader.enumerate(lease)
            PhotoSourceJobIndex(directory, protection).use { index ->
                val reserved = index.reserve(inventory, f.scope)
                val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, f.reader, protection)
                job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
                val source = index.restore(job, "sender_fixture_01", f.scope, lease)
                val manifest = source.manifest
                val accepted = DeviceFileRemoteAcceptance(java.util.UUID.randomUUID().toString(), manifest.fingerprint, manifest.transferId,
                    "c".repeat(64), receiver!!.permissionEpoch, "e".repeat(64), now + 60_000, "d".repeat(64))
                source.commitRemoteAcceptance(NativeGalleryOfferOutput(accepted.offerId, accepted.transferId, accepted.manifestSha256, accepted.expires), accepted) { }
                message = TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                    put("format", 1); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                    put("acceptance_sha256", accepted.acceptanceSha256); put("permission_epoch", accepted.permissionEpoch); put("destination_token", accepted.destinationToken)
                    put("receipts", JsonArray(manifest.files.map { buildJsonObject {
                        put("file_id", it.id); put("size", it.size); put("sha256", it.sha256); put("receipt_sha256", "0".repeat(64))
                    } }))
                }, 60_000, now)
            }
            val original = File(directory, "photo-source-" + job.id)
            held = File(f.root, "held-original-cache")
            check(original.renameTo(held))
            f.request = null // No live source lease/permission-host is available.
            receiver = receiver!!.copy(owner = Any()) // Fresh authenticated channel ownership.
        }
        fun open(hook: (String) -> Unit = {}) = PhotoSourceJobIndex(directory, protection, hook)
        fun restoreCache(): File = File(directory, "photo-source-" + job.id).also { check(held.renameTo(it)) }
        override fun close() { f.close() }
    }

    @Test fun freshHistoricalSavedActionStoresProofWithoutCacheOrLiveSourceAndDoesNotReleaseQuota() {
        HistoricalCase().use { h ->
            val opened = h.f.provider.opens.toList()
            h.open().use { index ->
                val action = index.issueHistoricalSavedAction(h.job, { h.receiver })
                val proof = index.commitHistoricalRemoteSaved(action, h.message, { h.now })
                assertEquals(proof.record, index.remoteSaved(h.job)!!.record)
                assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
                assertEquals(listOf(h.job), index.jobs())
                val repeat = index.issueHistoricalSavedAction(h.job, { h.receiver })
                assertEquals(proof.record, index.commitHistoricalRemoteSaved(repeat, h.message, { h.now }).record)
            }
            h.open().use { assertNotNull(it.remoteSaved(h.job)); assertEquals(listOf(h.job), it.jobs()) }
            assertEquals(opened, h.f.provider.opens); assertNull(h.f.request)
            assertFalse(File(h.directory, "photo-source-" + h.job.id).exists())
        }
    }

    @Test @Config(sdk = [35]) fun historicalSavedMetadataAloneCannotManufactureKnownPhoneReturnAssociation() {
        HistoricalCase().use { h ->
            h.open().use { index ->
                val action = index.issueHistoricalSavedAction(h.job, { h.receiver })
                index.commitHistoricalRemoteSaved(action, h.message, { h.now })
                assertNotNull(index.remoteSaved(h.job)); assertTrue(index.knownPhoneMedia().isEmpty())
            }
            assertNull(h.f.request); assertFalse(File(h.directory, "photo-source-" + h.job.id).exists())
        }
    }

    @Test fun historicalSavedActionFencesChangedIdentityPairingPermissionOrChannelOwner() {
        for (change in listOf("identity", "pairing", "epoch", "owner", "revoked")) HistoricalCase().use { h -> h.open().use { index ->
            val action = index.issueHistoricalSavedAction(h.job, { h.receiver })
            h.receiver = when (change) {
                "identity" -> h.receiver!!.copy(identitySha256 = "9".repeat(64))
                "pairing" -> h.receiver!!.copy(pairingEpoch = "9".repeat(64))
                "epoch" -> h.receiver!!.copy(permissionEpoch = "9".repeat(64))
                "owner" -> h.receiver!!.copy(owner = Any())
                else -> null
            }
            assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
            if (change != "owner") assertThrows(PhotoFolderScopeError::class.java) { index.issueHistoricalSavedAction(h.job, { h.receiver }) }
            assertNull(index.remoteSaved(h.job)); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test fun historicalSavedActionExpiryAndMonotonicRollbackCannotBeRenewedByIncomingMetadata() {
        for (tick in listOf(999L, 61_000L)) HistoricalCase().use { h -> h.open().use { index ->
            var elapsed = 1000L
            val action = index.issueHistoricalSavedAction(h.job, { h.receiver }, { elapsed })
            elapsed = tick
            assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
            elapsed = 1000L
            assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
            assertNull(index.remoteSaved(h.job))
        } }
    }

    @Test fun historicalSavedMembershipFailureRollsBackProofAndKeepsExactOriginalJob() {
        HistoricalCase().use { h ->
            var interrupted = false
            h.open { if (interrupted && it == "membership-protect") throw java.io.IOException("fixture historical proof seal failed") }.use { index ->
                val action = index.issueHistoricalSavedAction(h.job, { h.receiver }); interrupted = true
                assertThrows(java.io.IOException::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
                assertNull(index.remoteSaved(h.job)); assertEquals(listOf(h.job), index.jobs())
                interrupted = false
                assertNotNull(index.commitHistoricalRemoteSaved(index.issueHistoricalSavedAction(h.job, { h.receiver }), h.message, { h.now }))
            }
        }
    }

    @Test fun historicalSavedRevocationOrExpiryDuringNativeHeadMutationRollsBackAllProof() {
        for (change in listOf("revoked", "expired")) HistoricalCase().use { h ->
            var active = false; var elapsed = 1000L
            h.open { if (active && it == "membership-protect") {
                if (change == "revoked") h.receiver = null else elapsed = 61_000L
            } }.use { index ->
                val action = index.issueHistoricalSavedAction(h.job, { h.receiver }, { elapsed })
                active = true
                assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
                assertNull(index.remoteSaved(h.job)); assertEquals(listOf(h.job), index.jobs())
            }
        }
    }

    @Test fun historicalSavedSyncLossReturnsNoSuccessButFreshInspectionRetainsActuallyCommittedProof() {
        HistoricalCase().use { h ->
            h.open { if (it == "membership-sync") throw java.io.IOException("fixture historical proof sync lost") }.use { index ->
                val action = index.issueHistoricalSavedAction(h.job, { h.receiver })
                assertThrows(java.io.IOException::class.java) { index.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
                assertNotNull(index.remoteSaved(h.job))
                assertThrows(PhotoFolderScopeError::class.java) { index.issueHistoricalSavedAction(h.job, { h.receiver }) }
            }
            h.open().use { index ->
                assertNotNull(index.remoteSaved(h.job)); assertEquals(listOf(h.job), index.jobs())
                assertNotNull(index.commitHistoricalRemoteSaved(index.issueHistoricalSavedAction(h.job, { h.receiver }), h.message, { h.now }))
            }
        }
    }

    @Test fun historicalSavedConflictOrExpiredEnvelopeCannotReplaceOriginalProof() {
        HistoricalCase().use { h -> h.open().use { index ->
            val proof = index.commitHistoricalRemoteSaved(index.issueHistoricalSavedAction(h.job, { h.receiver }), h.message, { h.now })
            val body = h.message["body"]!!.jsonObject
            val members = body["receipts"]!!.jsonArray.map { JsonObject(it.jsonObject + ("receipt_sha256" to JsonPrimitive("9".repeat(64)))) }
            val changed = JsonObject(h.message + ("body" to JsonObject(body + ("receipts" to JsonArray(members)))))
            assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(index.issueHistoricalSavedAction(h.job, { h.receiver }), changed, { h.now }) }
            assertThrows(PhotoFolderScopeError::class.java) { index.commitHistoricalRemoteSaved(index.issueHistoricalSavedAction(h.job, { h.receiver }), h.message, { h.now + 60_000 }) }
            assertEquals(proof.record, index.remoteSaved(h.job)!!.record)
        } }
    }

    @Test fun historicalSavedActionCannotMoveBetweenFreshIndexOwners() {
        HistoricalCase().use { h -> h.open().use { first -> h.open().use { second ->
            val action = first.issueHistoricalSavedAction(h.job, { h.receiver })
            assertThrows(PhotoFolderScopeError::class.java) { second.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
            assertThrows(PhotoFolderScopeError::class.java) { first.commitHistoricalRemoteSaved(action, h.message, { h.now }) }
            assertNull(first.remoteSaved(h.job)); assertNull(second.remoteSaved(h.job))
        } } }
    }

    private data class ResumeInputs(val scope: GalleryPhotoSourceScope, val reader: AndroidGalleryPhotoSource, val inventory: PhotoSourceInventory)
    private fun resumeInputs(h: HistoricalCase): ResumeInputs {
        h.f.request = NativeGalleryRequest(h.receiver!!, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
        val scope = GalleryPhotoSourceScope({ h.f.request }, AndroidGalleryAccessEnvironment(h.f.context) { "2".repeat(64) })
        val lease = scope.capture(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(h.f.album), h.f.request), h.f.album)
        val reader = AndroidGalleryPhotoSource(h.f.context, scope)
        return ResumeInputs(scope, reader, reader.enumerate(lease))
    }

    @Test fun freshResumeInspectionRevalidatesActualPfdBytesWithoutCacheWritesOrRenewedOutputAuthority() {
        HistoricalCase().use { h -> h.open().use { index ->
            val original = index.requireGalleryResumeOriginal(h.job); val inputs = resumeInputs(h)
            assertNotEquals(original.originalAuthority!!.record["read_grant"], JsonPrimitive(inputs.inventory.lease.readGrantToken))
            val opens = h.f.provider.opens.size
            val observed = NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, original, inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(),
                { assertEquals(original.record, index.requireGalleryResumeOriginal(h.job).record) })
            assertEquals(h.job.id, observed.jobId); assertEquals(1, observed.verifiedFiles); assertEquals(5L, observed.verifiedBytes)
            assertFalse(observed.allowsChunkOutput); assertFalse(observed.provesDeletion)
            assertEquals(opens + 1, h.f.provider.opens.size)
            assertEquals(listOf(h.job), index.jobs()); assertNull(index.remoteSaved(h.job))
            assertFalse(File(h.directory, "photo-source-" + h.job.id).exists())
            assertEquals("hello", File(h.f.root, "source.bin").readText())
        } }
    }

    @Test fun changedOriginalBytesCannotPassResumeInspectionOrBeOverwrittenByOldCache() {
        HistoricalCase().use { h -> h.open().use { index ->
            val inputs = resumeInputs(h); File(h.f.root, "source.bin").writeText("HELLO")
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inputs.inventory, inputs.scope, inputs.reader,
                    CancellationSignal(), { index.requireGalleryResumeOriginal(h.job) })
            }
            assertEquals("HELLO", File(h.f.root, "source.bin").readText()); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test fun missingOrRenamedOriginalMemberHoldsResumeBeforeOpeningAnyPfd() {
        for (change in listOf("missing", "renamed")) HistoricalCase().use { h -> h.open().use { index ->
            h.f.provider.rows = if (change == "missing") listOf(Row(id = 2)) else listOf(Row(name = "renamed.jpg"))
            val inputs = resumeInputs(h); val opens = h.f.provider.opens.toList()
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inputs.inventory, inputs.scope, inputs.reader,
                    CancellationSignal(), { index.requireGalleryResumeOriginal(h.job) })
            }
            assertEquals(opens, h.f.provider.opens); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test fun resumeInspectionRevocationAndCancellationClosePfdWithoutReturningSuccess() {
        for (change in listOf("revoked", "canceled")) HistoricalCase().use { h -> h.open().use { index ->
            val inputs = resumeInputs(h); val cancellation = CancellationSignal()
            h.f.provider.onOpen = { if (change == "revoked") h.f.request = null else cancellation.cancel() }
            assertThrows(java.io.IOException::class.java) {
                try { NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inputs.inventory, inputs.scope, inputs.reader,
                    cancellation, { index.requireGalleryResumeOriginal(h.job) }) }
                catch (error: android.os.OperationCanceledException) { throw java.io.IOException(error) }
            }
            assertEquals(listOf(h.job), index.jobs()); h.f.assertClosed()
        } }
    }

    @Test @Config(sdk = [28]) fun unknownLegacyGalleryNamespaceCannotResumeFromMatchingNamesOrByteSizes() {
        HistoricalCase().use { h -> h.open().use { index ->
            val inputs = resumeInputs(h); val opens = h.f.provider.opens.toList()
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inputs.inventory, inputs.scope, inputs.reader,
                    CancellationSignal(), { index.requireGalleryResumeOriginal(h.job) })
            }
            assertEquals(opens, h.f.provider.opens); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test fun changedNativeGalleryNamespaceCannotRebindOldResumePhotoIdentity() {
        HistoricalCase().use { h -> h.open().use { index ->
            h.f.provider.namespace = "rebuilt-media-store"
            val inputs = resumeInputs(h); val opened = h.f.provider.opens.toList()
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inputs.inventory,
                    inputs.scope, inputs.reader, CancellationSignal(), { index.requireGalleryResumeOriginal(h.job) })
            }
            assertEquals(opened, h.f.provider.opens); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test @Config(sdk = [34]) fun selectedOnlyGalleryVisibilityDoesNotRenewOriginalFullResumeScope() {
        HistoricalCase().use { h -> h.open().use { index ->
            Shadows.shadowOf(h.f.context as Application).denyPermissions(Manifest.permission.READ_MEDIA_IMAGES)
            Shadows.shadowOf(h.f.context as Application).grantPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            h.f.request = NativeGalleryRequest(h.receiver!!, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
            val scope = GalleryPhotoSourceScope({ h.f.request }, AndroidGalleryAccessEnvironment(h.f.context) { "2".repeat(64) })
            val lease = scope.capture(GalleryAlbumCatalog(GalleryReadCoverage.SELECTED_ONLY, listOf(h.f.album), h.f.request), h.f.album)
            val reader = AndroidGalleryPhotoSource(h.f.context, scope); val inventory = reader.enumerate(lease)
            val opened = h.f.provider.opens.toList()
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeInspection.inspect("sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inventory,
                    scope, reader, CancellationSignal(), { index.requireGalleryResumeOriginal(h.job) })
            }
            assertEquals(opened, h.f.provider.opens); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test fun resumeInspectionCannotOutliveItsBoundedAttemptOrIgnoreChangedNativePairing() {
        for (change in listOf("expiry", "pairing", "sender")) HistoricalCase().use { h -> h.open().use { index ->
            if (change == "pairing") h.receiver = h.receiver!!.copy(pairingEpoch = "9".repeat(64))
            val inputs = resumeInputs(h); var ticks = 0; val opens = h.f.provider.opens.toList()
            assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeInspection.inspect(if (change == "sender") "foreign_sender_01" else "sender_fixture_01", h.job, index.requireGalleryResumeOriginal(h.job), inputs.inventory, inputs.scope, inputs.reader,
                    CancellationSignal(), { index.requireGalleryResumeOriginal(h.job) }, { if (++ticks >= 3 && change == "expiry") 61_000L else 1000L })
            }
            assertEquals(opens, h.f.provider.opens); assertEquals(listOf(h.job), index.jobs())
        } }
    }

    @Test fun freshNativeWorkflowInspectsThenExplicitlyRenewsOnlyLocalCacheReadOffMain() {
        Fixture().use { f ->
            val directory = Files.createTempDirectory(f.root.toPath(), "workflow-resume351-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            var receiver = f.receiver.copy(pairingEpoch = "1".repeat(64))
            val firstActivity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val first = NativeGalleryPhotoWorkflow(f.context, directory, "sender_fixture_01", protection) { receiver }
            val job: PhotoSourceJob
            try {
                first.configure(first.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                first.bindActivity(firstActivity.get()) { throw AssertionError("No implicit permission request") }
                firstActivity.start().resume()
                val catalog = first.discover(); val album = catalog.albums.single()
                job = first.freeze(catalog, album)
                first.discoverSelectable().use { choices ->
                    val page = choices.page()
                    val selection = choices.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                    val requests = f.provider.requests.toList(); val opens = f.provider.opens.toList()
                    assertEquals("photo_jobs_remote_acceptance_required", assertThrows(PhotoFolderScopeError::class.java) { first.inspectResume(selection, job) }.code)
                    assertEquals(requests, f.provider.requests); assertEquals(opens, f.provider.opens)
                }
                val source = first.source(job, catalog, album)
                val now = 1_800_000_000_000L; val offered = source.offerMessage(now)
                val manifest = source.manifest
                val accepted = DeviceFileRemoteAcceptance(offered.string("message_id"), manifest.fingerprint, manifest.transferId,
                    "c".repeat(64), receiver.permissionEpoch, "e".repeat(64), now + 60_000, "d".repeat(64))
                source.commitRemoteAcceptance(NativeGalleryOfferOutput(accepted.offerId, accepted.transferId, accepted.manifestSha256, accepted.expires), accepted) { }
            } finally { first.close(); firstActivity.pause().stop().destroy() }
            val cache = File(directory, "photo-source-" + job.id); val held = File(f.root, "held-workflow-cache")
            assertTrue(cache.renameTo(held)); receiver = receiver.copy(owner = Any())
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val reopened = NativeGalleryPhotoWorkflow(f.context, directory, "sender_fixture_01", protection) { receiver }
            val executor = java.util.concurrent.Executors.newSingleThreadExecutor()
            val cancellation = CancellationSignal()
            var selectedCatalog: NativeGalleryAlbumCatalog? = null
            try {
                reopened.bindActivity(activity.get()) { throw AssertionError("No implicit permission request") }
                activity.start().resume()
                val catalog = reopened.discoverSelectable(); selectedCatalog = catalog
                val page = catalog.page()
                val selection = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                val result = executor.submit<NativeGalleryResumeInspection> { reopened.inspectResume(selection, job, cancellation) }
                    .get(10, java.util.concurrent.TimeUnit.SECONDS)
                assertEquals(job.id, result.jobId); assertEquals(5L, result.verifiedBytes)
                assertFalse(result.allowsChunkOutput); assertFalse(result.provesDeletion)
                assertEquals(listOf(job), reopened.jobs()); assertFalse(cache.exists())
                assertNull(Shadows.shadowOf(activity.get()).lastRequestedPermission)
                assertEquals("hello", File(f.root, "source.bin").readText())
                assertThrows(PhotoFolderScopeError::class.java) { reopened.source(job, catalog.source, selection.album, selection.desktopChoice) }
                assertTrue(held.renameTo(cache))
                val originalCipher = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
                val renewed = executor.submit<NativeGalleryRenewedSource> { reopened.renewSource(selection, job, cancellation) }
                    .get(10, java.util.concurrent.TimeUnit.SECONDS)
                val member = renewed.manifest.files.single()
                assertArrayEquals("hello".toByteArray(), renewed.readChunk(member.id, 0)); assertFalse(renewed.allowsOfferOutput)
                assertEquals(listOf(job), reopened.jobs())
                assertEquals(originalCipher, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
                reopened.close()
                assertThrows(PhotoFolderScopeError::class.java) { renewed.readChunk(member.id, 0).fill(0) }
            } finally {
                cancellation.cancel(); executor.shutdownNow(); assertTrue(executor.awaitTermination(5, java.util.concurrent.TimeUnit.SECONDS))
                selectedCatalog?.close(); reopened.close(); activity.pause().stop().destroy()
                if (held.exists()) assertTrue(held.renameTo(cache)) else assertTrue(cache.isDirectory)
            }
        }
    }

    @Test fun renewedLocalSourceUsesFreshNativeLeaseAndOriginalCipherDomainWithoutRewritingJob() {
        HistoricalCase().use { h -> h.open().use { index ->
            val cache = h.restoreCache(); val original = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
            val accepted = index.remoteAcceptance(h.job)!!.record
            val inputs = resumeInputs(h)
            assertThrows(PhotoFolderScopeError::class.java) {
                index.restore(h.job, "sender_fixture_01", inputs.scope, inputs.inventory.lease)
            } // The normal old-context guard remains strict.
            val renewed = index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {})
            val member = renewed.manifest.files.single()
            assertArrayEquals("hello".toByteArray(), renewed.readChunk(member.id, 0))
            assertFalse(renewed.allowsOfferOutput)
            assertEquals(listOf(h.job), index.jobs()); assertEquals(accepted, index.remoteAcceptance(h.job)!!.record)
            assertEquals(original, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
            File(h.f.root, "source.bin").writeText("HELLO")
            assertArrayEquals("hello".toByteArray(), renewed.readChunk(member.id, 0)) // Frozen historical bytes, not current presence.
            assertEquals("HELLO", File(h.f.root, "source.bin").readText())
        } }
    }

    @Test fun renewedSourceRejectsMissingCorruptOrUnfamiliarOriginalCacheWithoutRepairingIt() {
        for (change in listOf("missing", "cipher", "extra")) HistoricalCase().use { h -> h.open().use { index ->
            val cache = if (change == "missing") null else h.restoreCache()
            var edited: File? = null; var preserved: ByteArray? = null
            if (change == "cipher") {
                edited = cache!!.listFiles()!!.single { it.name.endsWith("-0.enc") }
                preserved = edited.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }; edited.writeBytes(preserved)
            } else if (change == "extra") {
                edited = File(cache, "preserve-user-file").apply { writeText("preserve") }; preserved = edited.readBytes()
            }
            val inputs = resumeInputs(h)
            assertThrows(java.io.IOException::class.java) {
                index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {})
            }
            if (edited != null) assertArrayEquals(preserved, edited.readBytes())
            assertEquals(listOf(h.job), index.jobs()); assertNull(index.remoteSaved(h.job))
            if (change == "missing") assertFalse(File(h.directory, "photo-source-" + h.job.id).exists())
        } }
    }

    @Test fun renewedLocalSourceCannotSurviveNativeRevocationOrOriginalIndexExit() {
        for (change in listOf("revoked", "closed")) HistoricalCase().use { h -> h.open().use { index ->
            h.restoreCache(); val inputs = resumeInputs(h)
            val renewed = index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {})
            val member = renewed.manifest.files.single()
            if (change == "revoked") h.f.request = null else index.close()
            assertThrows(PhotoFolderScopeError::class.java) { renewed.readChunk(member.id, 0).fill(0) }
            assertThrows(PhotoFolderScopeError::class.java) { renewed.manifest }
        } }
    }

    @Test fun changedOrRevokedLiveSourceCannotMintRenewedCacheHandle() {
        for (change in listOf("bytes", "revoked")) HistoricalCase().use { h -> h.open().use { index ->
            val cache = h.restoreCache(); val original = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
            val inputs = resumeInputs(h)
            if (change == "bytes") File(h.f.root, "source.bin").writeText("HELLO") else h.f.provider.onOpen = { h.f.request = null }
            var renewed: NativeGalleryRenewedSource? = null
            assertThrows(java.io.IOException::class.java) {
                renewed = index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {})
            }
            assertNull(renewed); assertEquals(listOf(h.job), index.jobs())
            assertEquals(original, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
            if (change == "bytes") assertEquals("HELLO", File(h.f.root, "source.bin").readText())
        } }
    }

    @Test fun renewedCachePreparationCannotOutliveItsBoundedIntentOrReviveAfterClockRollback() {
        for (change in listOf("expired", "rollback")) HistoricalCase().use { h -> h.open().use { index ->
            val cache = h.restoreCache(); val original = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
            val inputs = resumeInputs(h); var ticks = 0
            assertThrows(PhotoFolderScopeError::class.java) {
                index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {},
                    { if (++ticks >= 10) (if (change == "expired") 61_000L else 999L) else 1000L })
            }
            assertEquals(listOf(h.job), index.jobs()); assertEquals(original, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
        } }
    }

    private fun withRenewedResumeSource(action: (HistoricalCase, PhotoSourceJobIndex, NativeGalleryRenewedSource, Long) -> Unit) {
        HistoricalCase().use { h -> h.open().use { index ->
            val cache = h.restoreCache(); val before = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
            val original = index.remoteAcceptance(h.job)!!.record
            val inputs = resumeInputs(h)
            val source = index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {})
            action(h, index, source, h.now + 120_000)
            assertEquals(original, index.remoteAcceptance(h.job)!!.record); assertEquals(listOf(h.job), index.jobs())
            assertNull(index.remoteSaved(h.job)); assertEquals(before, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
        } }
    }

    private fun resumeAcceptance(offerId: String, original: DeviceFileRemoteAcceptance, now: Long,
        changes: Map<String, JsonElement> = emptyMap()) = TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND,
        JsonObject(buildJsonObject {
            put("format", 1); put("offer_id", offerId); put("manifest_sha256", original.manifestSha256)
            put("transfer_id", original.transferId); put("acceptance_sha256", original.acceptanceSha256)
            put("permission_epoch", original.permissionEpoch); put("destination_token", original.destinationToken)
        } + changes), 60_000, now)

    private fun preparedResumeAttempt(index: PhotoSourceJobIndex, source: NativeGalleryRenewedSource, now: Long,
        elapsed: () -> Long): NativeGalleryResumeAttempt = NativeGalleryResumeAttempt.begin(source, now, elapsed).also {
        it.prepareStorage(index, { now })
        assertEquals("prepared", index.resumeAttempt(source.job)!!.phase)
    }

    private fun resumeSource(h: HistoricalCase, index: PhotoSourceJobIndex, restoreOriginal: Boolean = true): NativeGalleryRenewedSource {
        if (restoreOriginal) h.restoreCache()
        val inputs = resumeInputs(h)
        return index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, CancellationSignal(), {}, {})
    }

    @Test fun resumeOfferWithoutDurablePreparationCannotReachAnyOutput() {
        withRenewedResumeSource { _, index, source, now ->
            val attempt = NativeGalleryResumeAttempt.begin(source, now, { 1000L }); var writes = 0
            assertEquals("gallery_resume_attempt_storage_required", assertThrows(PhotoFolderScopeError::class.java) {
                attempt.sendOffer({ writes++ }, { now })
            }.code)
            assertEquals(0, writes); assertNull(index.resumeAttempt(source.job))
        }
    }

    @Test fun persistedResumeAttemptCannotBeAdoptedByAnotherNativeUuidEvenAfterExpiry() {
        withRenewedResumeSource { h, index, source, now ->
            val first = preparedResumeAttempt(index, source, now, { 1000L })
            val actual = index.resumeAttempt(source.job)!!.record
            first.cancel()
            h.open().use { fresh ->
                assertEquals(actual, fresh.resumeAttempt(source.job)!!.record)
                assertFalse(fresh.resumeAttempt(source.job)!!.allowsChunkOutput)
                val second = NativeGalleryResumeAttempt.begin(source, now + 120_000, { 1000L })
                assertEquals("photo_jobs_resume_original_attempt_held", assertThrows(PhotoFolderScopeError::class.java) {
                    second.prepareStorage(fresh, { now + 120_000 })
                }.code)
                assertEquals(actual, fresh.resumeAttempt(source.job)!!.record)
            }
        }
    }

    @Test fun lostOrDamagedResumeRowCannotBecomeEmptyStateAfterFreshOpen() {
        for (change in listOf("missing", "cipher")) HistoricalCase().use { h ->
            val name = "resume-attempt-v1/" + h.job.id
            h.open().use { index ->
                val source = resumeSource(h, index)
                preparedResumeAttempt(index, source, h.now + 120_000, { 1000L })
            }
            android.database.sqlite.SQLiteDatabase.openDatabase(File(h.directory, "photo-source-jobs.db").path, null,
                android.database.sqlite.SQLiteDatabase.OPEN_READWRITE).use { db ->
                if (change == "missing") assertEquals(1, db.delete("source_meta", "name=?", arrayOf(name)))
                else db.rawQuery("SELECT sealed FROM source_meta WHERE name=?", arrayOf(name)).use {
                    assertTrue(it.moveToFirst()); val bad = it.getBlob(0).also { bytes -> bytes[bytes.lastIndex] = (bytes.last().toInt() xor 1).toByte() }
                    db.execSQL("UPDATE source_meta SET sealed=? WHERE name=?", arrayOf(bad, name))
                }
            }
            assertEquals("photo_jobs_membership_changed", assertThrows(PhotoFolderScopeError::class.java) { h.open().close() }.code)
            assertTrue(File(h.directory, "photo-source-" + h.job.id).isDirectory)
            android.database.sqlite.SQLiteDatabase.openDatabase(File(h.directory, "photo-source-jobs.db").path, null,
                android.database.sqlite.SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT job_id FROM source_jobs", null).use { assertTrue(it.moveToFirst()); assertEquals(h.job.id, it.getString(0)); assertFalse(it.moveToNext()) }
            }
        }
    }

    @Test fun resumePhaseTransactionFailurePreservesLastActualPhaseAndExactEnvelope() {
        for (phase in listOf("prepared", "sent", "accepted")) HistoricalCase().use { h ->
            var interrupt = false
            h.open { if (interrupt && it == "membership-protect") throw java.io.IOException("fixture resume phase rollback") }.use { index ->
                val source = resumeSource(h, index); val now = h.now + 120_000
                val attempt = NativeGalleryResumeAttempt.begin(source, now, { 1000L }); val outputs = mutableListOf<JsonObject>()
                if (phase != "prepared") attempt.prepareStorage(index, { now })
                if (phase == "accepted") attempt.sendOffer({ outputs += it }, { now })
                val message = resumeAcceptance(attempt.offerId, source.originalAcceptance().historicalAcceptance(), now)
                var projection: NativeResumeAcceptanceProjection? = null
                interrupt = true
                assertThrows(java.io.IOException::class.java) {
                    when (phase) {
                        "prepared" -> attempt.prepareStorage(index, { now })
                        "sent" -> attempt.sendOffer({ outputs += it }, { now })
                        else -> projection = attempt.observeAcceptance(message, { now })
                    }
                }
                assertNull(projection)
                val expected = when (phase) { "prepared" -> null; "sent" -> "prepared"; else -> "sent" }
                assertEquals(expected, index.resumeAttempt(h.job)?.phase)
                assertEquals(listOf(h.job), index.jobs())
                interrupt = false
                when (phase) {
                    "prepared" -> attempt.prepareStorage(index, { now })
                    "sent" -> { attempt.sendOffer({ outputs += it }, { now }); assertEquals(outputs[0], outputs[1]) }
                    else -> assertFalse(attempt.observeAcceptance(message, { now }).allowsChunkOutput)
                }
                assertEquals(phase, index.resumeAttempt(h.job)!!.phase)
            }
        }
    }

    @Test fun resumePhaseSyncLossReturnsNoSuccessAndFreshOwnerCannotAdoptPersistedAttempt() {
        for (phase in listOf("prepared", "sent", "accepted")) HistoricalCase().use { h ->
            var interrupt = false; lateinit var stored: JsonObject
            h.open { if (interrupt && it == "membership-sync") throw java.io.IOException("fixture resume phase sync lost") }.use { index ->
                val source = resumeSource(h, index); val now = h.now + 120_000
                val attempt = NativeGalleryResumeAttempt.begin(source, now, { 1000L })
                if (phase != "prepared") attempt.prepareStorage(index, { now })
                if (phase == "accepted") attempt.sendOffer({}, { now })
                val message = resumeAcceptance(attempt.offerId, source.originalAcceptance().historicalAcceptance(), now)
                interrupt = true
                assertThrows(java.io.IOException::class.java) {
                    when (phase) { "prepared" -> attempt.prepareStorage(index, { now }); "sent" -> attempt.sendOffer({}, { now }); else -> attempt.observeAcceptance(message, { now }) }
                }
                stored = index.resumeAttempt(h.job)!!.record
                assertEquals(phase, index.resumeAttempt(h.job)!!.phase)
                assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({}, { now }) }
            }
            h.open().use { fresh ->
                assertEquals(stored, fresh.resumeAttempt(h.job)!!.record)
                val source = resumeSource(h, fresh, false)
                val another = NativeGalleryResumeAttempt.begin(source, h.now + 120_000, { 1000L })
                assertEquals("photo_jobs_resume_original_attempt_held", assertThrows(PhotoFolderScopeError::class.java) {
                    another.prepareStorage(fresh, { h.now + 120_000 })
                }.code)
                assertEquals(stored, fresh.resumeAttempt(h.job)!!.record); assertEquals(listOf(h.job), fresh.jobs())
            }
        }
    }

    @Test fun resumeRecordRejectsPhaseBypassTypedTimeAndForeignOriginalContext() {
        withRenewedResumeSource { _, index, source, now ->
            val attempt = preparedResumeAttempt(index, source, now, { 1000L })
            val prepared = index.resumeAttempt(source.job)!!; val original = source.originalAcceptance()
            val message = resumeAcceptance(attempt.offerId, original.historicalAcceptance(), now)
            assertThrows(PhotoFolderScopeError::class.java) { PhotoSourceResumeAttempt.advance(prepared, "accepted", source.job, original, message, now) }
            attempt.sendOffer({}, { now }); attempt.observeAcceptance(message, { now })
            val accepted = index.resumeAttempt(source.job)!!
            val changes = listOf("format" to JsonPrimitive(true), "job_id" to JsonPrimitive("9".repeat(32)),
                "source_job_sha256" to JsonPrimitive("9".repeat(64)), "original_acceptance_sha256" to JsonPrimitive("9".repeat(64)),
                "accepted_at" to JsonPrimitive(true), "accepted_at" to JsonPrimitive(now.toString()), "accepted_at" to JsonPrimitive(now + 60_000))
            for ((field, value) in changes) assertThrows(PhotoFolderScopeError::class.java) {
                PhotoSourceResumeAttempt.parse(JsonObject(accepted.record + (field to value)), source.job, original)
            }
            assertThrows(PhotoFolderScopeError::class.java) { PhotoSourceResumeAttempt.advance(accepted, "sent", source.job, original) }
            assertEquals(accepted.record, index.resumeAttempt(source.job)!!.record)
        }
    }

    @Test fun resumePhaseRevocationOrExpiryDuringHeadMutationCannotCommitSuccess() {
        for (phase in listOf("prepared", "sent", "accepted")) for (change in listOf("revoked", "expired")) HistoricalCase().use { h ->
            var active = false; var wall = h.now + 120_000
            h.open { if (active && it == "membership-protect") {
                if (change == "revoked") h.f.request = null else wall += 60_000
            } }.use { index ->
                val source = resumeSource(h, index)
                val attempt = NativeGalleryResumeAttempt.begin(source, wall, { 1000L })
                if (phase != "prepared") attempt.prepareStorage(index, { wall })
                if (phase == "accepted") attempt.sendOffer({}, { wall })
                val message = resumeAcceptance(attempt.offerId, source.originalAcceptance().historicalAcceptance(), wall)
                active = true
                assertThrows(PhotoFolderScopeError::class.java) {
                    when (phase) { "prepared" -> attempt.prepareStorage(index, { wall }); "sent" -> attempt.sendOffer({}, { wall }); else -> attempt.observeAcceptance(message, { wall }) }
                }
                assertEquals(when (phase) { "prepared" -> null; "sent" -> "prepared"; else -> "sent" }, index.resumeAttempt(h.job)?.phase)
                assertEquals(listOf(h.job), index.jobs())
            }
        }
    }

    @Test fun finalRetirementKeepsResumeProofAndQuotaTogetherOnTransactionFailure() {
        HistoricalCase().use { h ->
            var active = false; var interrupt = false
            h.open { if (active && it == "cleanup-proven") interrupt = true
                if (interrupt && it == "membership-protect") throw java.io.IOException("fixture resume retirement rollback")
            }.use { index ->
                val source = resumeSource(h, index); val now = h.now + 120_000
                val attempt = preparedResumeAttempt(index, source, now, { 1000L }); attempt.sendOffer({}, { now })
                attempt.observeAcceptance(resumeAcceptance(attempt.offerId, source.originalAcceptance().historicalAcceptance(), now), { now })
                val original = index.resumeAttempt(h.job)!!.record
                active = true
                assertThrows(java.io.IOException::class.java) { index.retireCachedSnapshot(h.job) }
                val retired = index.jobs().single()
                assertEquals("retired", retired.phase); assertEquals(h.job.cipherBudget, retired.cipherBudget)
                assertEquals(original, index.resumeAttempt(retired)!!.record)
                assertFalse(File(h.directory, "photo-source-" + h.job.id).exists())
                active = false; interrupt = false
                index.retireCachedSnapshot(retired); assertTrue(index.jobs().isEmpty())
            }
            h.open().use { assertTrue(it.jobs().isEmpty()) }
            assertEquals("hello", File(h.f.root, "source.bin").readText())
        }
    }

    @Test fun freshResumeAttemptUsesNewOfferButNeverRenewsOrRebindsOriginalAcceptance() {
        withRenewedResumeSource { _, index, source, now ->
            val original = source.originalAcceptance().historicalAcceptance()
            assertTrue(now > original.expires)
            val attempt = preparedResumeAttempt(index, source, now, { 1000L })
            assertNotEquals(original.offerId, attempt.offerId)
            var output: JsonObject? = null
            attempt.sendOffer({ output = it; assertEquals("prepared", index.resumeAttempt(source.job)!!.phase) }, { now })
            assertEquals("sent", index.resumeAttempt(source.job)!!.phase)
            val offered = DeviceFileOfferEnvelope.validate(output!!, source.manifest.senderId, source.manifest.receiverId, now)
            assertEquals(source.manifest.fingerprint, offered.fingerprint)
            assertEquals(now, output!!.long("created_ms")); assertEquals(now + 60_000, output!!.long("expires_ms"))
            val message = resumeAcceptance(attempt.offerId, original, now)
            val observed = attempt.observeAcceptance(message, { now })
            assertEquals("accepted", index.resumeAttempt(source.job)!!.phase)
            assertFalse(index.resumeAttempt(source.job)!!.allowsChunkOutput)
            assertFalse(observed.allowsChunkOutput)
            assertEquals(original.acceptanceSha256, observed.accepted.acceptanceSha256)
            assertEquals(now + 60_000, observed.validUntil)
            assertSame(observed, attempt.observeAcceptance(message, { now }))
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({}, { now }) }
        }
    }

    @Test fun uncertainResumeOfferOutputRetriesOnlyItsOriginalEnvelopeBeforeAcceptance() {
        withRenewedResumeSource { _, index, source, now ->
            val attempt = preparedResumeAttempt(index, source, now, { 1000L }); val sent = mutableListOf<JsonObject>()
            val message = resumeAcceptance(attempt.offerId, source.originalAcceptance().historicalAcceptance(), now)
            assertThrows(java.io.IOException::class.java) { attempt.sendOffer({ sent += it; throw java.io.IOException("fixture resume output lost") }, { now }) }
            assertThrows(PhotoFolderScopeError::class.java) { attempt.observeAcceptance(message, { now }) }
            attempt.sendOffer({ sent += it }, { now + 1 })
            assertEquals(2, sent.size); assertEquals(sent[0], sent[1])
            assertFalse(attempt.observeAcceptance(message, { now + 1 }).allowsChunkOutput)
        }
    }

    @Test fun resumeAcceptanceCannotChangeAnyOriginalDestinationOrTransferBinding() {
        withRenewedResumeSource { _, index, source, now ->
            val original = source.originalAcceptance().historicalAcceptance()
            val attempt = preparedResumeAttempt(index, source, now, { 1000L }); attempt.sendOffer({}, { now })
            val wrong = listOf("manifest_sha256" to "9".repeat(64), "transfer_id" to "9".repeat(32),
                "acceptance_sha256" to "9".repeat(64), "permission_epoch" to "9".repeat(64), "destination_token" to "9".repeat(64),
                "offer_id" to original.offerId)
            for ((field, value) in wrong) assertThrows(PhotoFolderScopeError::class.java) {
                attempt.observeAcceptance(resumeAcceptance(attempt.offerId, original, now, mapOf(field to JsonPrimitive(value))), { now })
            }
            val message = resumeAcceptance(attempt.offerId, original, now)
            val accepted = attempt.observeAcceptance(message, { now })
            assertThrows(PhotoFolderScopeError::class.java) { attempt.observeAcceptance(resumeAcceptance(attempt.offerId, original, now), { now }) }
            assertSame(accepted, attempt.observeAcceptance(message, { now }))
        }
    }

    @Test fun resumeAttemptClockRollbackAndExpiryAreStickyWithoutOriginalTtlRenewal() {
        for (change in listOf("wall", "elapsed", "wall-expired", "elapsed-expired")) withRenewedResumeSource { _, index, source, now ->
            var wall = now; var tick = 1000L; var writes = 0
            val attempt = preparedResumeAttempt(index, source, wall, { tick })
            wall += 10; tick = 1001L; attempt.sendOffer({ writes++ }, { wall })
            when (change) {
                "wall" -> wall--
                "elapsed" -> tick--
                "wall-expired" -> wall = now + 60_000
                else -> tick = 61_000L
            }
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({ writes++ }, { wall }) }
            wall = now + 10; tick = 1001L
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({ writes++ }, { wall }) }
            assertEquals(1, writes)
        }
    }

    @Test fun resumeOfferCannotReturnLateSuccessAfterCancelRevocationOrExpiryDuringOutput() {
        for (change in listOf("cancel", "revoked", "expired")) withRenewedResumeSource { h, index, source, now ->
            var wall = now
            val attempt = preparedResumeAttempt(index, source, now, { 1000L }); var calls = 0
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({
                calls++
                when (change) { "cancel" -> attempt.cancel(); "revoked" -> h.f.request = null; else -> wall = now + 60_000 }
            }, { wall }) }
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({ calls++ }, { now }) }
            assertEquals(1, calls)
        }
    }

    @Test fun blockedResumeOfferCanBeCanceledWithoutReentrancyOrLateSuccess() {
        withRenewedResumeSource { _, index, source, now ->
            val attempt = preparedResumeAttempt(index, source, now, { 1000L })
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
            val executor = java.util.concurrent.Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit<Exception?> {
                    try { attempt.sendOffer({
                        assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({}, { now }) }
                        entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    }, { now }); null } catch (error: Exception) { error }
                }
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                attempt.cancel(); release.countDown()
                assertTrue(result.get(5, java.util.concurrent.TimeUnit.SECONDS) is PhotoFolderScopeError)
            } finally { release.countDown(); executor.shutdownNow(); assertTrue(executor.awaitTermination(5, java.util.concurrent.TimeUnit.SECONDS)) }
        }
    }

    @Test fun observedSourceRevocationCannotReviveAnOldResumeAttemptWhenFixturePermissionReturns() {
        withRenewedResumeSource { h, index, source, now ->
            val attempt = preparedResumeAttempt(index, source, now, { 1000L })
            val request = h.f.request
            h.f.request = null
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({}, { now }) }
            h.f.request = request
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({}, { now }) }
        }
    }

    @Test fun resumeAttemptRejectsUnsafeNativeElapsedClockWithoutPublishingAnyOffer() {
        withRenewedResumeSource { _, _, source, now ->
            for (tick in listOf(-1L, Long.MAX_VALUE)) assertThrows(PhotoFolderScopeError::class.java) {
                NativeGalleryResumeAttempt.begin(source, now, { tick })
            }
        }
    }

    @Test fun nativeShortResumeOfferExpiresMonotonicallyWhenWallClockStopsBeforeAnyOutput() {
        withRenewedResumeSource { _, index, source, now ->
            var elapsed = 1000L; var outputs = 0
            val attempt = NativeGalleryResumeAttempt.begin(source, now, { elapsed }, ttlMs = 1000L)
            attempt.prepareStorage(index, { now })
            assertEquals("prepared", index.resumeAttempt(source.job)!!.phase)
            elapsed = 2000L
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({ outputs++ }, { now }) }
            elapsed = 1000L
            assertThrows(PhotoFolderScopeError::class.java) { attempt.sendOffer({ outputs++ }, { now }) }
            assertEquals(0, outputs); assertEquals("prepared", index.resumeAttempt(source.job)!!.phase)
        }
    }

    @Test fun renewedPreparationUsesSameWorkerSlotAndPublishesOnlyAfterRealPfdEnd() {
        HistoricalCase().use { h -> h.open().use { index ->
            h.restoreCache(); val inputs = resumeInputs(h)
            val catalog = NativeGalleryAlbumCatalog(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(h.f.album), h.f.request), Any(), { true })
            val page = catalog.page(); val selected = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1); val ended = java.util.concurrent.CountDownLatch(1)
            val worker = NativeGallerySourceWorker({ _, _ -> throw AssertionError("Renewal must not allocate/freeze a new job") }, { ended.countDown() })
            h.f.provider.onOpen = { entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            try {
                val run = worker.startRenewed(selected) { _, cancellation -> index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, cancellation, {}, {}) }
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertFalse(run.ioEnded); assertFalse(worker.isQuiescent)
                assertThrows(PhotoFolderScopeError::class.java) { run.renewedSource() }
                assertThrows(PhotoFolderScopeError::class.java) { worker.start(selected) }
                assertThrows(PhotoFolderScopeError::class.java) { worker.startRenewed(selected) { _, _ -> throw AssertionError("No overlap") } }
                assertEquals(listOf(h.job), index.jobs())
                release.countDown(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertTrue(run.ioEnded); assertTrue(worker.isQuiescent); assertEquals("snapshot_ready", run.phase)
                assertEquals(h.job, run.snapshotJob())
                val source = run.renewedSource()!!; val file = source.manifest.files.single()
                assertArrayEquals("hello".toByteArray(), source.readChunk(file.id, 0))
                run.cancel(); assertNull(run.renewedSource())
                assertThrows(android.os.OperationCanceledException::class.java) { source.readChunk(file.id, 0).fill(0) }
                assertEquals(listOf(h.job), index.jobs())
            } finally { release.countDown(); worker.close(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)); catalog.close() }
        } }
    }

    @Test fun closingRenewedWorkerRetainsBlockedPfdOwnershipAndRejectsLateSourcePublication() {
        HistoricalCase().use { h -> h.open().use { index ->
            h.restoreCache(); val inputs = resumeInputs(h)
            val catalog = NativeGalleryAlbumCatalog(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(h.f.album), h.f.request), Any(), { true })
            val page = catalog.page(); val selected = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1); val ended = java.util.concurrent.CountDownLatch(1)
            val worker = NativeGallerySourceWorker({ _, _ -> throw AssertionError("No new reservation") }, { ended.countDown() })
            h.f.provider.onOpen = { entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            try {
                val run = worker.startRenewed(selected) { _, cancellation -> index.renewGallerySource(h.job, "sender_fixture_01", inputs.inventory, inputs.scope, inputs.reader, cancellation, {}, {}) }
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                worker.close()
                assertTrue(run.cancelRequested); assertFalse(run.ioEnded); assertFalse(worker.isQuiescent)
                assertThrows(PhotoFolderScopeError::class.java) { run.renewedSource() }
                assertEquals(listOf(h.job), index.jobs())
                release.countDown(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertTrue(run.ioEnded); assertTrue(worker.isQuiescent); assertEquals("canceled_held", run.phase)
                assertNull(run.snapshotJob()); assertNull(run.renewedSource())
                assertThrows(PhotoFolderScopeError::class.java) { worker.start(selected) }
                assertEquals(listOf(h.job), index.jobs()); assertEquals("hello", File(h.f.root, "source.bin").readText())
            } finally { release.countDown(); worker.close(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)); catalog.close() }
        } }
    }

    /** Original acceptance is established through actual controls/OS host and
     * encrypted output, then stopped BEFORE Saved. No consent is fabricated. */
    class WriteConsentActivity : ComponentActivity() {
        var writeAllowed = false
        var writeChecks = 0
        override fun checkUriPermission(uri: Uri, pid: Int, uid: Int, modeFlags: Int): Int {
            check(modeFlags == Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            writeChecks++
            return if (writeAllowed) android.content.pm.PackageManager.PERMISSION_GRANTED else android.content.pm.PackageManager.PERMISSION_DENIED
        }
    }

    @Test @Config(sdk = [33]) fun sharedVideoOnlyNativeRuntimeKeepsImageJobsClosedAndRequiresFreshSelectionAfterIntentChange() {
        var intent: Any? = Any()
        ResumeRuntimeCase(mediaType = GalleryMediaType.VIDEO, currentMediaIntent = { if (it == GalleryMediaType.VIDEO) intent else null }).use { h ->
            assertNull(h.runtime.currentRequest(GalleryMediaType.IMAGES))
            assertNotNull(h.runtime.currentRequest(GalleryMediaType.VIDEO))
            assertNotNull(h.runtime.issueHistoricalSavedAction(h.job))
            val oldSelection = h.selected
            intent = Any() // An off/on transition completed between native checks.
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(oldSelection) }
            h.inspect { assertEquals(h.originalAcceptance, it.remoteAcceptance(h.job)!!.record); assertNull(it.remoteSaved(h.job)) }
            assertEquals(h.cipher, File(h.root, "photo-source-" + h.job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
            val catalog = h.runtime.discoverSelectable(mediaType = GalleryMediaType.VIDEO)
            val page = catalog.page()
            val fresh = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
            h.watchEnd(); val run = h.runtime.beginSyncRun(fresh); h.awaitEnd()
            run.preparation.nativeFailure()?.let { throw it }
            assertNotNull(run.preparation.snapshotJob())
            assertNull(h.runtime.currentRequest(GalleryMediaType.IMAGES))
            h.runtime.cancelSyncRun(run); h.runtime.endStoppedSyncRun(run)
        }
    }

    private class ResumeRuntimeCase(fileCount: Int = 1, withWriteHost: Boolean = false,
        mediaType: GalleryMediaType = GalleryMediaType.IMAGES, currentMediaIntent: ((GalleryMediaType) -> Any?)? = null) : AutoCloseable {
        val f = Fixture(mediaType)
        val root = Files.createTempDirectory(f.root.toPath(), "resume-runtime356-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val now = 1_800_000_000_000L
        val output = ByteArrayOutputStream(); val key = ByteArray(32) { 3 }; val prefix = ByteArray(4) { 4 }
        val channel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output, ByteArray(16), key.copyOf(), prefix, ByteArray(32), ByteArray(4))
        val identity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
        val peer = NativeFileControlPeer(f.receiver.peerId, f.receiver.identitySha256, channel, true, true, true, true, true, "1".repeat(64), mediaType == GalleryMediaType.VIDEO)
        val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, peer.pairingEpoch)
        val pcState = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
        val desktop = NativeFileControlSession(NativeFileControlIdentity(peer.peerId, peer.identitySha256), { pcPeer }, { pcState })
        val runtime = if (currentMediaIntent != null)
            NativeGalleryFileRuntime.withSharedMediaIntent(f.context, root, identity, protection, channel, { peer }, { true },
                { mediaType == GalleryMediaType.VIDEO }, currentMediaIntent)
            else if (mediaType == GalleryMediaType.VIDEO)
            NativeGalleryFileRuntime.withVideoHandlers(f.context, root, identity, protection, channel, { peer }, { true }, { true })
            else NativeGalleryFileRuntime(f.context, root, identity, protection, channel, { peer }, { true })
        val activity = if (withWriteHost) Robolectric.buildActivity(WriteConsentActivity::class.java).create() else Robolectric.buildActivity(ComponentActivity::class.java).create()
        val writeHost = if (withWriteHost) NativeGalleryWriteConsentHost(activity.get()) else null
        val host = GalleryPhotoPermissionHost(activity.get(), mediaType, writeHost)
        val worker = NativeGalleryFileRuntime::class.java.getDeclaredField("sourceWorker").also { it.isAccessible = true }.get(runtime) as NativeGallerySourceWorker
        val endedField = NativeGallerySourceWorker::class.java.getDeclaredField("onEnded").also { it.isAccessible = true }
        @Suppress("UNCHECKED_CAST") val originalEnd = endedField.get(worker) as (NativeGallerySourceRun) -> Unit
        var ended = java.util.concurrent.CountDownLatch(1)
        val release = java.util.concurrent.CountDownLatch(1)
        lateinit var catalog: NativeGalleryAlbumCatalog
        lateinit var selected: NativeGalleryAlbumSelection
        lateinit var job: PhotoSourceJob
        lateinit var originalAcceptance: JsonObject
        lateinit var originalMedia: JsonObject
        lateinit var cipher: Map<String, List<Byte>>
        init {
            try {
                if (fileCount != 1) f.provider.rows = (1..fileCount).map { Row(id = it.toLong(), name = "image-$it.jpg") }
                runtime.attachPermissionHost(host) { throw AssertionError("No implicit permission request") }; activity.start().resume()
                fun echo() {
                    if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(drain().single(), now), pcPeer)
                    val packet = desktop.packet(); desktop.markSent(packet)
                    runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
                    if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(drain().single(), now), pcPeer)
                }
                echo(); runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                if (mediaType == GalleryMediaType.VIDEO) runtime.configureVideosFromAuthenticatedCommand(runtime.savedPolicy(), true)
                catalog = runtime.discoverSelectable(mediaType = mediaType)
                val page = catalog.page()
                selected = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                watchEnd()
                // Preparing encrypted originals is fixture setup, not a UI or
                // cancellation latency assertion (Robolectric/JCE can start cold).
                val normal = runtime.beginSyncRun(selected); awaitEnd(30)
                normal.preparation.nativeFailure()?.let { throw it }
                job = normal.preparation.snapshotJob()!!
                runtime.receiveSourceCommand(TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", 1); put("operation", "media_page"); put("expected_version", runtime.savedPolicy().version)
                    put("run_id", normal.id); put("after", 0)
                    if (mediaType == GalleryMediaType.VIDEO) put("media_type", "video")
                }, 60_000, now), channel::send, { now })
                originalMedia = drain().single()["body"]!!.jsonObject["page"]!!.jsonObject
                runtime.sendSyncRunOffer(normal, channel::send, now)
                val offer = drain().single(); val manifest = DeviceFileOfferEnvelope.validate(offer, identity.deviceId, peer.peerId, now)
                runtime.observeAcceptance(TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                    put("format", 1); put("offer_id", offer.string("message_id")); put("transfer_id", manifest.transferId)
                    put("manifest_sha256", manifest.fingerprint); put("acceptance_sha256", "c".repeat(64))
                    put("permission_epoch", runtime.currentRequest(mediaType)!!.receiver.permissionEpoch); put("destination_token", "e".repeat(64))
                }, 60_000, now), { now })
                inspect { originalAcceptance = it.remoteAcceptance(job)!!.record; assertNull(it.remoteSaved(job)) }
                cipher = File(root, "photo-source-" + job.id).listFiles()!!.associate { it.name to it.readBytes().toList() }
                runtime.cancelSyncRun(normal); runtime.endStoppedSyncRun(normal)
            } catch (error: Throwable) { close(); throw error }
        }
        fun watchEnd() {
            ended = java.util.concurrent.CountDownLatch(1)
            val signal = ended
            endedField.set(worker, { run: NativeGallerySourceRun -> try { originalEnd(run) } finally { signal.countDown() } })
        }
        fun awaitEnd(timeoutSeconds: Long = 5) {
            val finished = ended.await(timeoutSeconds, java.util.concurrent.TimeUnit.SECONDS)
            if (!finished) {
                val sourceStacks = Thread.getAllStackTraces().filter { it.key.name == "magnolie-photo-source" }
                    .entries.joinToString("\n") { (thread, stack) -> thread.state.toString() + ": " + stack.take(10).joinToString("\n") }
                fail("Source completion deadline; quiescent=${worker.isQuiescent}\n$sourceStacks")
            }
        }
        fun echoControls() {
            if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(drain().single(), now), pcPeer)
            val packet = desktop.packet(); desktop.markSent(packet)
            runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
            if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(drain().single(), now), pcPeer)
        }
        fun start(): NativeGalleryResumeRun { watchEnd(); return runtime.beginResumeRun(selected, job) }
        fun drain(): List<JsonObject> {
            val input = ByteArrayInputStream(output.toByteArray()); output.reset(); val result = mutableListOf<JsonObject>()
            while (input.available() > 0) {
                val frame = TelefonRahmen.lesen(input); val header = JsonObject(frame - "ciphertext")
                result += Json.parseToJsonElement(TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")),
                    java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header)).decodeToString()).jsonObject
            }
            return result
        }
        fun inspect(action: (PhotoSourceJobIndex) -> Unit) { PhotoSourceJobIndex(root, protection).use(action) }
        fun indexHook(hook: (String) -> Unit) {
            val index = NativeGalleryFileRuntime::class.java.getDeclaredField("index").also { it.isAccessible = true }.get(runtime)
            PhotoSourceJobIndex::class.java.getDeclaredField("boundary").also { it.isAccessible = true }.set(index, hook)
        }
        fun acceptance(run: NativeGalleryResumeRun, at: Long = now + 120_000): JsonObject {
            lateinit var original: DeviceFileRemoteAcceptance
            inspect { original = it.remoteAcceptance(job)!!.historicalAcceptance() }
            return TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                put("format", 1); put("offer_id", run.attempt.get()!!.offerId); put("transfer_id", original.transferId)
                put("manifest_sha256", original.manifestSha256); put("acceptance_sha256", original.acceptanceSha256)
                put("permission_epoch", original.permissionEpoch); put("destination_token", original.destinationToken)
            }, 60_000, at)
        }
        fun assertOriginal(saved: Boolean = false) {
            inspect {
                assertEquals(listOf(job), it.jobs()); assertEquals(originalAcceptance, it.remoteAcceptance(job)!!.record)
                if (saved) assertNotNull(it.remoteSaved(job)) else assertNull(it.remoteSaved(job))
            }
            assertEquals(cipher, File(root, "photo-source-" + job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
            assertEquals("hello", File(f.root, "source.bin").readText())
        }
        fun acceptedRun(): NativeGalleryResumeRun {
            val run = start(); awaitEnd()
            runtime.sendResumeRunOffer(run, channel::send, { now + 120_000 }); drain()
            runtime.observeResumeRunAcceptance(run, acceptance(run), { now + 120_000 })
            return run
        }
        fun chunk(run: NativeGalleryResumeRun, at: Long = now + 240_000): JsonObject {
            val accepted = run.acceptance.get()!!.accepted
            val file = run.source().manifest.files.single()
            return TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
                put("format", 1); put("transfer_id", accepted.transferId); put("manifest_sha256", accepted.manifestSha256)
                put("acceptance_sha256", accepted.acceptanceSha256); put("permission_epoch", accepted.permissionEpoch)
                put("destination_token", accepted.destinationToken); put("file_id", file.id); put("chunk_index", 0)
            }, 60_000, at)
        }
        fun saved(run: NativeGalleryResumeRun, at: Long = now + 240_000): JsonObject {
            val manifest = run.source().manifest; val accepted = run.acceptance.get()!!.accepted
            return TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                put("format", 1); put("transfer_id", accepted.transferId); put("manifest_sha256", accepted.manifestSha256)
                put("acceptance_sha256", accepted.acceptanceSha256); put("permission_epoch", accepted.permissionEpoch)
                put("destination_token", accepted.destinationToken)
                put("receipts", JsonArray(manifest.files.map { buildJsonObject {
                    put("file_id", it.id); put("size", it.size); put("sha256", it.sha256); put("receipt_sha256", "0".repeat(64))
                } }))
            }, 60_000, at)
        }
        fun resumeCommand(at: Long = now): JsonObject {
            runtime.receiveSourceCommand(TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "discover"); put("expected_version", runtime.savedPolicy().version)
            }, 60_000, at), channel::send, { at })
            val page = drain().single()["body"]!!.jsonObject["page"]!!.jsonObject
            return TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "resume_run"); put("expected_version", runtime.savedPolicy().version)
                put("catalog_id", page.string("catalog_id")); put("album_id", page["albums"]!!.jsonArray.single().jsonObject.string("album_id"))
                put("desktop_choice", true); put("original_job_id", job.id); put("original_job_version", job.version)
            }, 60_000, at)
        }
        fun currentResume(): NativeGalleryResumeRun = NativeGalleryFileRuntime::class.java.getDeclaredField("resumeRun").also { it.isAccessible = true }
            .get(runtime) as NativeGalleryResumeRun
        fun resumeStatus(operation: String, run: NativeGalleryResumeRun, at: Long = now): JsonObject =
            TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", operation); put("expected_version", runtime.savedPolicy().version); put("run_id", run.id)
            }, 60_000, at)
        fun lookup(): JsonObject {
            val manifest = DeviceFileManifest.parse(job.snapshot!!["manifest"]!!.jsonObject)
            return TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "resume_lookup"); put("expected_version", runtime.savedPolicy().version)
                put("source_id", manifest.sourceId); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
            }, 60_000, now)
        }
        fun media(run: NativeGalleryResumeRun, after: Int = 0, at: Long = now + 120_000): JsonObject =
            TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "resume_media_page"); put("expected_version", runtime.savedPolicy().version)
                put("run_id", run.id); put("after", after)
            }, 60_000, at)
        override fun close() {
            release.countDown(); runtime.revokeControl()
            if (!worker.isQuiescent) awaitEnd()
            runtime.close(); host.close(); if (::catalog.isInitialized) catalog.close()
            activity.pause().stop().destroy(); desktop.close(); channel.close(); f.close()
        }
    }

    @Test fun actualResumeRunCommitsOfferAndAcceptanceBeforeProjectionWithoutNormalHandlerFallback() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            val foreign = NativeGalleryResumeRun(h.selected, h.job, run.preparation)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(foreign, h.channel::send, { at }) }
            h.runtime.sendResumeRunOffer(run, { message ->
                h.inspect { assertEquals("prepared", it.resumeAttempt(h.job)!!.phase) }
                assertNull(run.acceptance.get()); h.channel.send(message)
            }, { at })
            val wire = h.drain().single()
            assertEquals(run.attempt.get()!!.offerId, wire.string("message_id"))
            h.inspect { assertEquals("sent", it.resumeAttempt(h.job)!!.phase) }
            val message = h.acceptance(run)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunAcceptance(foreign, message, { at }) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeAcceptance(message, { at }) }
            val projection = h.runtime.observeResumeRunAcceptance(run, message, { at })
            assertSame(projection, run.acceptance.get()); assertFalse(projection.allowsChunkOutput)
            h.inspect { assertEquals("accepted", it.resumeAttempt(h.job)!!.phase) }
            assertSame(projection, h.runtime.observeResumeRunAcceptance(run, message, { at }))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(run, h.channel::send, { at }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
            h.runtime.cancelResumeRun(run); h.runtime.endStoppedResumeRun(run)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunAcceptance(run, message, { at }) }
        }
    }

    @Test fun actualResumeRunRetainsSameAttemptAndEncryptedEnvelopeAfterLostOutput() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            assertThrows(java.io.IOException::class.java) { h.runtime.sendResumeRunOffer(run, {
                h.channel.send(it); throw java.io.IOException("fixture lost encrypted output acknowledgement")
            }, { at }) }
            val first = h.drain().single(); val held = run.attempt.get()!!
            h.inspect { assertEquals("prepared", it.resumeAttempt(h.job)!!.phase) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunAcceptance(run, h.acceptance(run), { at }) }
            h.runtime.sendResumeRunOffer(run, h.channel::send, { at + 1 })
            assertSame(held, run.attempt.get()); assertEquals(first, h.drain().single())
            assertFalse(h.runtime.observeResumeRunAcceptance(run, h.acceptance(run), { at + 1 }).allowsChunkOutput)
            h.assertOriginal()
        }
    }

    @Test fun actualResumeRunPreparingOrCanceledCannotPrepareDurableOfferOrWriteOutput() {
        ResumeRuntimeCase().use { h ->
            val entered = java.util.concurrent.CountDownLatch(1)
            h.f.provider.onOpen = { entered.countDown(); check(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            val run = h.start()
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(run, h.channel::send, { h.now }) }
                assertNull(run.attempt.get()); h.inspect { assertNull(it.resumeAttempt(h.job)) }
                h.runtime.cancelResumeRun(run)
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(run, h.channel::send, { h.now }) }
            } finally { h.release.countDown(); h.awaitEnd() }
            h.runtime.endStoppedResumeRun(run)
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun actualResumeOfferCancelExitOrExpiryDuringEncryptedOutputCannotPublishSentSuccess() {
        for (change in listOf("cancel", "exit", "expired")) ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; var wall = at
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(run, { message ->
                h.channel.send(message)
                when (change) { "cancel" -> run.cancel(); "exit" -> h.runtime.revokeControl(); else -> wall += 60_000 }
            }, { wall }) }
            assertEquals(1, h.drain().size)
            h.inspect { assertEquals("prepared", it.resumeAttempt(h.job)!!.phase) }
            assertNull(run.acceptance.get())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(run, h.channel::send, { at }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun actualResumeAcceptanceExpiryBeforeProjectionNeverPublishesRunGrant() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            h.runtime.sendResumeRunOffer(run, h.channel::send, { at }); h.drain()
            val message = h.acceptance(run); var ticks = 0
            assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.observeResumeRunAcceptance(run, message, { if (++ticks >= 3) at + 60_000 else at })
            }
            assertNull(run.acceptance.get()); h.assertOriginal()
        }
    }

    @Test fun actualResumePreparationOrAcceptanceRollbackRetriesSameLiveRunAttempt() {
        for (phase in listOf("prepared", "accepted")) ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            if (phase == "accepted") { h.runtime.sendResumeRunOffer(run, h.channel::send, { at }); h.drain() }
            h.indexHook { if (it == "membership-protect") throw java.io.IOException("fixture runtime attempt phase rollback") }
            assertThrows(java.io.IOException::class.java) {
                if (phase == "prepared") h.runtime.sendResumeRunOffer(run, h.channel::send, { at })
                else h.runtime.observeResumeRunAcceptance(run, h.acceptance(run), { at })
            }
            val held = run.attempt.get()!!
            h.inspect { assertEquals(if (phase == "prepared") null else "sent", it.resumeAttempt(h.job)?.phase) }
            assertNull(run.acceptance.get()); assertEquals(0, h.output.size())
            h.indexHook { }
            if (phase == "prepared") {
                h.runtime.sendResumeRunOffer(run, h.channel::send, { at })
                assertEquals(held.offerId, h.drain().single().string("message_id"))
            } else {
                assertFalse(h.runtime.observeResumeRunAcceptance(run, h.acceptance(run), { at }).allowsChunkOutput)
            }
            assertSame(held, run.attempt.get()); h.assertOriginal()
        }
    }

    @Test fun actualResumeAcceptedCommitFollowedByExitOrExpiryCannotPublishRunProjection() {
        for (change in listOf("exit", "expired")) ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; var wall = at
            h.runtime.sendResumeRunOffer(run, h.channel::send, { wall }); h.drain()
            h.indexHook { if (it == "membership-committed") {
                if (change == "exit") h.runtime.revokeControl() else wall += 60_000
            } }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunAcceptance(run, h.acceptance(run), { wall }) }
            assertNull(run.acceptance.get())
            h.inspect { assertEquals("accepted", it.resumeAttempt(h.job)!!.phase); assertFalse(it.resumeAttempt(h.job)!!.allowsChunkOutput) }
            h.assertOriginal(); assertEquals(0, h.output.size())
        }
    }

    @Test fun actualAcceptedResumeOutputsFrozenChunkUnderFreshRequestAfterOfferMessageTtlEnds() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val request = h.chunk(run)
            assertTrue(at > run.acceptance.get()!!.validUntil)
            assertFalse(run.acceptance.get()!!.allowsChunkOutput) // Alone never grants bytes.
            h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at })
            val response = h.drain().single()
            assertEquals(DeviceFileChunkEnvelope.RESULT, response.string("kind"))
            val body = response["body"]!!.jsonObject
            assertEquals(request.string("message_id"), body.string("request_id"))
            assertArrayEquals("hello".toByteArray(), java.util.Base64.getDecoder().decode(body.string("data_base64")))
            assertEquals(run.acceptance.get()!!.accepted.acceptanceSha256, body.string("acceptance_sha256"))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(h.selected) }
            h.assertOriginal()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveChunkRequest(request, h.channel::send, { at }) }
            assertEquals(0, h.output.size())
        }
    }

    @Test fun resumeChunkRequiresActualAcceptedOwnerNotStandaloneProjectionOrForeignRun() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            h.runtime.sendResumeRunOffer(run, h.channel::send, { at }); h.drain()
            val message = h.acceptance(run)
            // Component acceptance can be durable without runtime post-I/O binding.
            val standalone = run.attempt.get()!!.observeAcceptance(message, { at })
            val accepted = standalone.accepted; val file = run.source().manifest.files.single()
            val request = TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
                put("format", 1); put("transfer_id", accepted.transferId); put("manifest_sha256", accepted.manifestSha256)
                put("acceptance_sha256", accepted.acceptanceSha256); put("permission_epoch", accepted.permissionEpoch)
                put("destination_token", accepted.destinationToken); put("file_id", file.id); put("chunk_index", 0)
            }, 60_000, at)
            assertNull(run.acceptance.get())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at }) }
            h.runtime.observeResumeRunAcceptance(run, message, { at })
            val foreign = NativeGalleryResumeRun(h.selected, h.job, run.preparation)
            foreign.attempt.set(run.attempt.get()); foreign.acceptance.set(standalone)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(foreign, request, h.channel::send, { at }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeChunkRejectsChangedBindingsExpiredRequestsAndUnknownMembersBeforeOutput() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val message = h.chunk(run); val body = message["body"]!!.jsonObject
            for ((field, value) in listOf("transfer_id" to JsonPrimitive("9".repeat(32)), "manifest_sha256" to JsonPrimitive("9".repeat(64)),
                "acceptance_sha256" to JsonPrimitive("9".repeat(64)), "permission_epoch" to JsonPrimitive("9".repeat(64)),
                "destination_token" to JsonPrimitive("9".repeat(64)), "file_id" to JsonPrimitive("9".repeat(32)), "chunk_index" to JsonPrimitive(1))) {
                val changed = JsonObject(message + ("body" to JsonObject(body + (field to value))))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, changed, h.channel::send, { at }) }
            }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, message, h.channel::send, { at + 60_000 }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeChunkCancelExitOrExpiryDuringEncryptedOutputNeverReturnsLateSuccess() {
        for (change in listOf("cancel", "exit", "expired", "rollback")) ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val request = h.chunk(run); var wall = at
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, request, { response ->
                h.channel.send(response)
                when (change) { "cancel" -> run.cancel(); "exit" -> h.runtime.revokeControl(); "expired" -> wall += 60_000; else -> wall-- }
            }, { wall }) }
            assertEquals(1, h.drain().size) // Actual output is irretractable, never an ACK.
            h.assertOriginal()
        }
    }

    @Test fun resumeChunkExpiryBeforeOutputAndStoppedOwnerCannotLeakSourceBytes() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val request = h.chunk(run); var ticks = 0
            assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { if (++ticks >= 3) at + 60_000 else at })
            }
            h.runtime.cancelResumeRun(run); h.runtime.endStoppedResumeRun(run)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeChunkCannotUseDamagedCacheOrLostDurableAcceptedHead() {
        for (change in listOf("cipher", "head")) ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val request = h.chunk(run)
            if (change == "cipher") {
                val entry = File(h.root, "photo-source-" + h.job.id).listFiles()!!.single { it.name.endsWith("-0.enc") }
                val bytes = entry.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }; entry.writeBytes(bytes)
                assertThrows(java.io.IOException::class.java) { h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at }) }
                assertArrayEquals(bytes, entry.readBytes())
                h.inspect { assertEquals(listOf(h.job), it.jobs()); assertEquals(h.originalAcceptance, it.remoteAcceptance(h.job)!!.record) }
            } else {
                android.database.sqlite.SQLiteDatabase.openDatabase(File(h.root, "photo-source-jobs.db").path, null,
                    android.database.sqlite.SQLiteDatabase.OPEN_READWRITE).use {
                    assertEquals(1, it.delete("source_meta", "name=?", arrayOf("resume-attempt-v1/" + h.job.id)))
                }
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at }) }
                assertTrue(File(h.root, "photo-source-" + h.job.id).isDirectory)
            }
            assertEquals(0, h.output.size()); assertEquals("hello", File(h.f.root, "source.bin").readText())
        }
    }

    @Test fun resumeChunkStopsWhenOriginalHistoricalSavedProofIsAlreadyComplete() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val request = h.chunk(run)
            val source = run.source(); val manifest = source.manifest; val accepted = run.acceptance.get()!!.accepted
            val saved = TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                put("format", 1); put("transfer_id", accepted.transferId); put("manifest_sha256", accepted.manifestSha256)
                put("acceptance_sha256", accepted.acceptanceSha256); put("permission_epoch", accepted.permissionEpoch)
                put("destination_token", accepted.destinationToken)
                put("receipts", JsonArray(manifest.files.map { buildJsonObject {
                    put("file_id", it.id); put("size", it.size); put("sha256", it.sha256); put("receipt_sha256", "0".repeat(64))
                } }))
            }, 60_000, at)
            h.inspect { index ->
                val action = index.issueHistoricalSavedAction(h.job, { h.runtime.currentRequest()!!.receiver })
                index.commitHistoricalRemoteSaved(action, saved, { at })
            } // Another explicit native metadata owner has already confirmed history.
            assertEquals("gallery_resume_original_already_saved", assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at })
            }.code)
            assertEquals(0, h.output.size())
            h.inspect { assertEquals(listOf(h.job), it.jobs()); assertNotNull(it.remoteSaved(h.job)); assertEquals(h.originalAcceptance, it.remoteAcceptance(h.job)!!.record) }
            assertEquals(h.cipher, File(h.root, "photo-source-" + h.job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
        }
    }

    @Test fun actualResumeSavedCommitsOriginalAcceptanceBeforeRamWithoutQuotaRetirement() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000
            val request = h.chunk(run); val saved = h.saved(run)
            h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at }); h.drain()
            val original = h.originalAcceptance["acceptance"]!!.jsonObject
            assertNotEquals(original.string("command_digest"), run.acceptance.get()!!.accepted.commandDigest)
            h.indexHook { if (it == "membership-committed") {
                h.inspect { index -> assertNotNull(index.remoteSaved(h.job)) }
                assertNull(run.remoteSaved.get())
            } }
            val proof = h.runtime.observeResumeRunRemoteSaved(run, saved, { at })
            h.indexHook { }
            assertEquals(original, proof.record["acceptance"])
            assertEquals(proof.confirmation.fingerprint, run.remoteSaved.get()!!.fingerprint)
            val prior = run.remoteSaved.get()
            assertEquals(proof.record, h.runtime.observeResumeRunRemoteSaved(run, saved, { at }).record)
            assertSame(prior, run.remoteSaved.get())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeRemoteSaved(saved, { at }) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveResumeRunChunkRequest(run, request, h.channel::send, { at }) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(h.selected) }
            assertEquals(0, h.output.size()); h.assertOriginal(saved = true)
        }
    }

    @Test fun resumeSavedForeignOwnerWrongBindingOrExpiredEnvelopeCannotCommit() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val message = h.saved(run); val body = message["body"]!!.jsonObject
            val foreign = NativeGalleryResumeRun(h.selected, h.job, run.preparation)
            foreign.attempt.set(run.attempt.get()); foreign.acceptance.set(run.acceptance.get())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(foreign, message, { at }) }
            for (field in listOf("manifest_sha256", "acceptance_sha256", "permission_epoch", "destination_token")) {
                val changed = JsonObject(message + ("body" to JsonObject(body + (field to JsonPrimitive("9".repeat(64))))))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(run, changed, { at }) }
            }
            val incomplete = JsonObject(message + ("body" to JsonObject(body + ("receipts" to JsonArray(emptyList())))))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(run, incomplete, { at }) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(run, message, { at + 60_000 }) }
            assertNull(run.remoteSaved.get()); h.assertOriginal()
        }
    }

    @Test fun resumeSavedChangedReceiptCannotOverwriteOriginalOrItsRunProjection() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val message = h.saved(run)
            val proof = h.runtime.observeResumeRunRemoteSaved(run, message, { at }); val prior = run.remoteSaved.get()
            val body = message["body"]!!.jsonObject
            val receipts = body["receipts"]!!.jsonArray.map { JsonObject(it.jsonObject + ("receipt_sha256" to JsonPrimitive("9".repeat(64)))) }
            val changed = JsonObject(message + ("body" to JsonObject(body + ("receipts" to JsonArray(receipts)))))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(run, changed, { at }) }
            assertSame(prior, run.remoteSaved.get())
            h.inspect { assertEquals(proof.record, it.remoteSaved(h.job)!!.record) }; h.assertOriginal(saved = true)
        }
    }

    @Test fun resumeSavedTransactionFailureReturnsNoProjectionAndExactLiveOwnerCanRetry() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val message = h.saved(run)
            h.indexHook { if (it == "membership-protect") throw java.io.IOException("fixture resume saved rollback") }
            assertThrows(java.io.IOException::class.java) { h.runtime.observeResumeRunRemoteSaved(run, message, { at }) }
            assertNull(run.remoteSaved.get()); h.assertOriginal()
            h.indexHook { }
            assertNotNull(h.runtime.observeResumeRunRemoteSaved(run, message, { at }))
            h.assertOriginal(saved = true)
        }
    }

    @Test fun resumeSavedPostcommitSyncLossLeavesHistoricalProofButNoRunSuccessOrQuotaRelease() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val message = h.saved(run)
            h.indexHook { if (it == "membership-sync") throw java.io.IOException("fixture resume saved sync lost") }
            assertThrows(java.io.IOException::class.java) { h.runtime.observeResumeRunRemoteSaved(run, message, { at }) }
            assertNull(run.remoteSaved.get()); h.assertOriginal(saved = true)
            h.indexHook { }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(run, message, { at }) }
            assertNull(run.remoteSaved.get())
        }
    }

    @Test fun resumeSavedRevocationOrExpiryDuringCommitCannotPublishLateRamSuccess() {
        for (boundary in listOf("membership-protect", "membership-committed")) for (change in listOf("exit", "expired")) ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000; val message = h.saved(run); var wall = at
            h.indexHook { if (it == boundary) {
                if (change == "exit") h.runtime.revokeControl() else wall += 60_000
            } }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunRemoteSaved(run, message, { wall }) }
            assertNull(run.remoteSaved.get()); h.assertOriginal(saved = boundary == "membership-committed")
            assertEquals(0, h.output.size())
        }
    }

    @Test fun resumeSourceCommandsStartOnceAfterLostReplyAndKeepActualRunUntilStoppedEnd() {
        ResumeRuntimeCase().use { h ->
            val command = h.resumeCommand(); h.watchEnd()
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, {
                h.channel.send(it); throw java.io.IOException("fixture resume start reply lost")
            }, { h.now }) }
            val first = h.drain().single(); val run = h.currentResume(); h.awaitEnd()
            val opens = h.f.provider.opens.toList()
            h.runtime.receiveSourceCommand(command, h.channel::send, { h.now })
            val repeated = h.drain().single()
            assertSame(run, h.currentResume()); assertEquals(first["body"]!!.jsonObject.string("run_id"), repeated["body"]!!.jsonObject.string("run_id"))
            assertEquals(opens, h.f.provider.opens); assertNull(run.attempt.get())
            h.runtime.receiveSourceCommand(h.resumeStatus("resume_status", run), h.channel::send, { h.now })
            val status = h.drain().single()["body"]!!.jsonObject
            assertEquals("snapshot_ready", status.string("state")); assertEquals(JsonPrimitive(true), status["source_io_ended"])
            val changed = JsonObject(command + ("created_ms" to JsonPrimitive(h.now + 1)))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(changed, h.channel::send, { h.now }) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(h.selected) }
            h.runtime.receiveSourceCommand(h.resumeStatus("cancel_resume", run), h.channel::send, { h.now })
            assertEquals("canceled_held", h.drain().single()["body"]!!.jsonObject.string("state"))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(h.selected) }
            h.runtime.endStoppedResumeRun(run)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { h.now }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeSourceCommandCancelDoesNotReleaseWorkerWhileRealProviderIoIsBlocked() {
        ResumeRuntimeCase().use { h ->
            val command = h.resumeCommand(); val entered = java.util.concurrent.CountDownLatch(1)
            h.f.provider.onOpen = { entered.countDown(); check(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            h.watchEnd()
            h.runtime.receiveSourceCommand(command, h.channel::send, { h.now }); h.drain()
            val run = h.currentResume()
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                h.runtime.receiveSourceCommand(h.resumeStatus("cancel_resume", run), h.channel::send, { h.now })
                assertEquals("cancel_pending", h.drain().single()["body"]!!.jsonObject.string("state"))
                assertFalse(run.preparation.ioEnded)
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.endStoppedResumeRun(run) }
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(h.selected) }
            } finally { h.release.countDown(); h.awaitEnd() }
            h.runtime.endStoppedResumeRun(run); h.assertOriginal()
        }
    }

    @Test fun resumeSourceCommandUnknownOriginalOrMalformedFieldsCannotOpenAnyPfd() {
        ResumeRuntimeCase().use { h ->
            val message = h.resumeCommand(); val body = message["body"]!!.jsonObject; val opens = h.f.provider.opens.toList()
            for ((field, value) in listOf("original_job_id" to JsonPrimitive("9".repeat(32)), "original_job_version" to JsonPrimitive("9".repeat(64)),
                "original_job_version" to JsonPrimitive(true), "desktop_choice" to JsonPrimitive("true"), "path" to JsonPrimitive("DCIM/Camera"))) {
                val changed = JsonObject(message + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())) +
                    ("body" to JsonObject(body + (field to value))))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(changed, h.channel::send, { h.now }) }
            }
            assertEquals(opens, h.f.provider.opens); assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeSourceCommandReplyExpiryOrExitNeverAdoptsAnotherWorkerOnRetry() {
        for (change in listOf("expired", "exit")) ResumeRuntimeCase().use { h ->
            val message = h.resumeCommand(); var wall = h.now; h.watchEnd()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(message, {
                h.channel.send(it)
                if (change == "exit") h.runtime.revokeControl() else wall += 60_000
            }, { wall }) }
            h.awaitEnd(); val run = h.currentResume(); val opens = h.f.provider.opens.toList()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(message, h.channel::send, { wall }) }
            assertSame(run, h.currentResume()); assertEquals(opens, h.f.provider.opens)
            assertEquals(1, h.drain().size); h.assertOriginal()
        }
    }

    @Test fun resumeSourceCommandReplayLedgerRejectsForeignRuntimeOwnerAndFailedStartRetry() {
        ResumeRuntimeCase().use { h ->
            val message = h.resumeCommand(); val command = DeviceFileSourceCommand.parse(message, h.now)
            val scope = "9".repeat(64); val owner = Any()
            val ledger = NativeGalleryResumeCommands({ h.now }, { 1000L })
            h.watchEnd()
            val run = ledger.start(scope, owner, command, message) { h.runtime.beginResumeRun(h.selected, h.job) }; h.awaitEnd()
            assertSame(run, ledger.start(scope, owner, command, message) { throw AssertionError("No second worker") })
            assertThrows(PhotoFolderScopeError::class.java) { ledger.start(scope, Any(), command, message) { throw AssertionError("Foreign owner") } }
            val failed = NativeGalleryResumeCommands({ h.now }, { 1000L }); var launches = 0
            assertThrows(java.io.IOException::class.java) { failed.start(scope, owner, command, message) { launches++; throw java.io.IOException("fixture start failed") } }
            assertThrows(PhotoFolderScopeError::class.java) { failed.start(scope, owner, command, message) { launches++; run } }
            assertEquals(1, launches); h.assertOriginal()
        }
    }

    @Test fun resumeCommandLedgerBoundsReplayMemoryAndFencesInvalidClocksWithoutNewLaunch() {
        ResumeRuntimeCase().use { h ->
            val message = h.resumeCommand(); val command = DeviceFileSourceCommand.parse(message, h.now)
            val run = h.start(); h.awaitEnd(); val scope = "9".repeat(64); val owner = Any()
            for (change in listOf("wall", "elapsed", "expired", "negative", "overflow")) {
                var wall = h.now; var tick = 1000L; var launches = 0
                val ledger = NativeGalleryResumeCommands({ wall }, { tick })
                ledger.start(scope, owner, command, message) { launches++; run }
                when (change) { "wall" -> wall--; "elapsed" -> tick--; "expired" -> wall += 60_000; "negative" -> tick = -1L; else -> tick = Long.MAX_VALUE }
                assertThrows(PhotoFolderScopeError::class.java) { ledger.start(scope, owner, command, message) { launches++; run } }
                wall = h.now; tick = 1000L
                assertThrows(PhotoFolderScopeError::class.java) { ledger.start(scope, owner, command, message) { launches++; run } }
                assertEquals(1, launches)
            }
            val ledger = NativeGalleryResumeCommands({ h.now }, { 1000L }); var launches = 0
            repeat(64) {
                val unique = JsonObject(message + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())))
                ledger.start(scope, owner, DeviceFileSourceCommand.parse(unique, h.now), unique) { launches++; run }
            }
            val extra = JsonObject(message + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())))
            assertEquals("gallery_resume_commands_held", assertThrows(PhotoFolderScopeError::class.java) {
                ledger.start(scope, owner, DeviceFileSourceCommand.parse(extra, h.now), extra) { launches++; run }
            }.code)
            assertEquals(64, launches); h.assertOriginal()
            var wall = h.now
            val expiry = NativeGalleryResumeCommands({ wall }, { 1000L })
            expiry.start(scope, owner, command, message) { run }
            wall += 60_000
            assertThrows(PhotoFolderScopeError::class.java) { expiry.start(scope, owner, command, message) { throw AssertionError("Expired request") } }
            val fresh = JsonObject(message + mapOf("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString()),
                "created_ms" to JsonPrimitive(wall), "expires_ms" to JsonPrimitive(wall + 60_000)))
            assertSame(run, expiry.start(scope, owner, DeviceFileSourceCommand.parse(fresh, wall), fresh) { run })
            // An expired request must not poison unrelated valid future commands.
        }
    }

    @Test fun resumeOfferCommandClampsOfferToRemainingCommandLifetimeAndRepliesAfterDurableSent() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            val command = h.resumeStatus("offer_resume", run, at)
            h.runtime.receiveSourceCommand(command, { message ->
                h.inspect { assertEquals(if (message.string("kind") == DeviceFileOfferEnvelope.KIND) "prepared" else "sent", it.resumeAttempt(h.job)!!.phase) }
                h.channel.send(message)
            }, { at + 20_000 })
            val frames = h.drain(); assertEquals(2, frames.size)
            val offer = frames[0]; val reply = frames[1]
            assertEquals(at + 60_000, offer.long("expires_ms")); assertEquals(at + 20_000, offer.long("created_ms"))
            assertEquals(offer.string("message_id"), reply["body"]!!.jsonObject.string("offer_id"))
            assertEquals(command.string("message_id"), reply["body"]!!.jsonObject.string("request_id"))
            assertTrue(reply.long("expires_ms") <= offer.long("expires_ms"))
            assertFalse(h.runtime.observeResumeRunAcceptance(run, h.acceptance(run, at + 20_000), { at + 20_000 }).allowsChunkOutput)
            h.assertOriginal()
        }
    }

    @Test fun resumeOfferCommandLostOutputOrReplyRetriesOnlySameCommandAndOfferEnvelope() {
        for (lost in listOf(DeviceFileOfferEnvelope.KIND, DeviceFileSourceCommand.RUN_RESULT)) ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; val command = h.resumeStatus("offer_resume", run, at)
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, {
                h.channel.send(it); if (it.string("kind") == lost) throw java.io.IOException("fixture resume wire output lost")
            }, { at }) }
            val initial = h.drain(); val first = initial.first(); val attempt = run.attempt.get()!!
            h.inspect { assertEquals(if (lost == DeviceFileOfferEnvelope.KIND) "prepared" else "sent", it.resumeAttempt(h.job)!!.phase) }
            h.runtime.receiveSourceCommand(command, h.channel::send, { at + 1 })
            val repeated = h.drain(); assertEquals(first, repeated.first()); assertSame(attempt, run.attempt.get())
            assertEquals(2, repeated.size); h.assertOriginal()
        }
    }

    @Test fun resumeOfferCommandCannotBeReboundToNewRequestChangedEnvelopeOrNativeFallback() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; val command = h.resumeStatus("offer_resume", run, at)
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, { throw java.io.IOException("fixture held wire offer") }, { at }) }
            val held = run.attempt.get()!!
            val changedId = JsonObject(command + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())))
            val changedTime = JsonObject(command + ("created_ms" to JsonPrimitive(at + 1)))
            for (message in listOf(changedId, changedTime)) assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.receiveSourceCommand(message, h.channel::send, { at + 1 })
            }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendResumeRunOffer(run, h.channel::send, { at + 1 }) }
            assertSame(held, run.attempt.get()); assertEquals(0, h.output.size()); h.assertOriginal()
        }
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            h.runtime.sendResumeRunOffer(run, h.channel::send, { at }); h.drain()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(h.resumeStatus("offer_resume", run, at), h.channel::send, { at }) }
            assertNull(run.wireOfferCommand.get()); assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeOfferCommandReplyRollbackOrExitCannotReviveAcceptanceWhenClockReturns() {
        for (change in listOf("rollback", "exit", "expired")) ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; var wall = at
            val command = h.resumeStatus("offer_resume", run, at)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, { message ->
                h.channel.send(message)
                if (message.string("kind") == DeviceFileSourceCommand.RUN_RESULT) {
                    when (change) { "rollback" -> wall--; "exit" -> h.runtime.revokeControl(); else -> wall += 60_000 }
                }
            }, { wall }) }
            assertEquals(2, h.drain().size); assertNull(run.acceptance.get())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.observeResumeRunAcceptance(run, h.acceptance(run, at), { at }) }
            assertNull(run.acceptance.get()); h.assertOriginal()
        }
    }

    @Test fun resumeOfferCommandPreparingOrCanceledRunCannotBindAttemptOrReachOutput() {
        ResumeRuntimeCase().use { h ->
            val entered = java.util.concurrent.CountDownLatch(1)
            h.f.provider.onOpen = { entered.countDown(); check(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            val run = h.start(); val at = h.now + 120_000; val command = h.resumeStatus("offer_resume", run, at)
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
                assertNull(run.attempt.get()); assertNull(run.wireOfferCommand.get())
                h.runtime.cancelResumeRun(run)
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            } finally { h.release.countDown(); h.awaitEnd() }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun guardedResumeSourceCommandsAndCurrentTransferDispatcherCompleteNativeDataWithoutAdoptingHistory() {
        ResumeRuntimeCase().use { h ->
            val start = h.resumeCommand(); h.watchEnd()
            val ledger = NativeGalleryResumeCommands({ h.now }, { 1000L })
            h.runtime.receiveSourceCommand(start, h.channel::send, { h.now }, resumeCommands = ledger)
            h.drain(); h.awaitEnd(); val run = h.currentResume(); val at = h.now + 120_000
            h.runtime.receiveSourceCommand(h.resumeStatus("offer_resume", run, at), h.channel::send, { at })
            val offered = h.drain(); assertEquals(2, offered.size)
            val acceptance = h.acceptance(run, at)
            h.runtime.receiveTransferMessage(acceptance, h.channel::send, { at })
            assertNotNull(run.acceptance.get()); assertEquals(0, h.output.size())
            val request = h.chunk(run); h.runtime.receiveTransferMessage(request, h.channel::send, { h.now + 240_000 })
            val chunk = h.drain().single()
            assertArrayEquals("hello".toByteArray(), java.util.Base64.getDecoder().decode(chunk["body"]!!.jsonObject.string("data_base64")))
            h.runtime.receiveTransferMessage(h.saved(run), h.channel::send, { h.now + 240_000 })
            assertNotNull(run.remoteSaved.get()); assertEquals(0, h.output.size()); h.assertOriginal(saved = true)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginSyncRun(h.selected) }
            h.runtime.cancelResumeRun(run); h.runtime.endStoppedResumeRun(run)
        }
    }

    @Test fun transferDispatcherCannotRestoreRunOrAuthorityFromPersistedAcceptedHeadAndPackets() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val request = h.chunk(run); val saved = h.saved(run); val acceptance = h.acceptance(run)
            h.runtime.cancelResumeRun(run); h.runtime.endStoppedResumeRun(run)
            h.inspect { assertEquals("accepted", it.resumeAttempt(h.job)!!.phase) }
            for (message in listOf(request, saved, acceptance)) assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.receiveTransferMessage(message, h.channel::send, { h.now + 240_000 })
            }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveTransferMessage(h.resumeStatus("resume_status", run), h.channel::send, { h.now }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun transferDispatcherPreparingStoppedOrRevokedOwnerCannotFallBackToOldAcceptedHistory() {
        for (change in listOf("preparing", "canceled", "revoked")) ResumeRuntimeCase().use { h ->
            val entered = java.util.concurrent.CountDownLatch(1)
            h.f.provider.onOpen = { entered.countDown(); check(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            val run = h.start()
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                val original = h.originalAcceptance["acceptance"]!!.jsonObject
                val stale = TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, JsonObject(original - setOf("expires", "command_digest") + ("format" to JsonPrimitive(1))), 60_000, h.now)
                if (change == "canceled") h.runtime.cancelResumeRun(run)
                if (change == "revoked") h.runtime.revokeControl()
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveTransferMessage(stale, h.channel::send, { h.now }) }
                assertNull(run.attempt.get()); assertNull(run.acceptance.get()); assertNull(run.remoteSaved.get())
                assertEquals(0, h.output.size())
            } finally { h.release.countDown(); h.awaitEnd() }
            h.assertOriginal()
        }
    }

    @Test fun historicalResumeLookupUsesExactOriginalManifestWithoutHostCacheOrOsPhotoRead() {
        ResumeRuntimeCase().use { h ->
            val message = h.lookup(); val child = File(h.root, "photo-source-" + h.job.id); val held = File(h.f.root, "held-lookup364")
            assertTrue(child.renameTo(held)); h.host.close()
            Shadows.shadowOf(h.f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
            h.f.provider.onQuery = { throw AssertionError("Historical lookup must not query MediaStore") }
            h.f.provider.onOpen = { throw AssertionError("Historical lookup must not open a PFD") }
            try {
                h.runtime.receiveSourceCommand(message, h.channel::send, { h.now })
                val result = h.drain().single(); assertEquals(DeviceFileSourceCommand.RESUME, result.string("kind"))
                val history = result["body"]!!.jsonObject["history"]!!.jsonObject
                assertEquals(setOf("job_id", "job_version", "phase", "source_id", "transfer_id", "manifest_sha256", "remote_saved_history", "attempt_phase", "attempt_id", "attempt_sha256"), history.keys)
                assertEquals(h.job.id, history.string("job_id")); assertEquals(h.job.version, history.string("job_version"))
                assertEquals(JsonPrimitive(false), history["remote_saved_history"]); assertEquals(JsonNull, history["attempt_phase"])
                assertEquals(JsonNull, history["attempt_id"]); assertEquals(JsonNull, history["attempt_sha256"])
                h.inspect { assertNull(it.resumeAttempt(h.job)) }
                assertFalse(child.exists()); assertEquals(0, h.output.size())
            } finally { assertTrue(held.renameTo(child)) }
            h.assertOriginal()
        }
    }

    @Test fun resumeLookupUnknownManifestOrChangedOriginalNativePeerPolicyRemainsHold() {
        ResumeRuntimeCase().use { h ->
            val message = h.lookup(); val body = message["body"]!!.jsonObject
            for ((field, value) in listOf("source_id" to JsonPrimitive("9".repeat(32)), "transfer_id" to JsonPrimitive("9".repeat(32)),
                "manifest_sha256" to JsonPrimitive("9".repeat(64)), "source_id" to JsonPrimitive(true), "path" to JsonPrimitive("DCIM/Camera"))) {
                val changed = JsonObject(message + ("body" to JsonObject(body + (field to value))))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(changed, h.channel::send, { h.now }) }
            }
            val receiver = h.runtime.currentRequest()!!.receiver; val manifest = DeviceFileManifest.parse(h.job.snapshot!!["manifest"]!!.jsonObject)
            h.inspect { index ->
                for (wrong in listOf(receiver.copy(identitySha256 = "9".repeat(64)), receiver.copy(permissionEpoch = "9".repeat(64)),
                    receiver.copy(pairingEpoch = "9".repeat(64)), receiver.copy(pairingEpoch = null))) assertThrows(PhotoFolderScopeError::class.java) {
                    index.lookupGalleryResume(h.identity.deviceId, manifest.sourceId, manifest.transferId, manifest.fingerprint, wrong, h.runtime.currentRequest()!!.policyEpoch)
                }
                assertThrows(PhotoFolderScopeError::class.java) {
                    index.lookupGalleryResume(h.identity.deviceId, manifest.sourceId, manifest.transferId, manifest.fingerprint, receiver, "9".repeat(64))
                }
                assertThrows(PhotoFolderScopeError::class.java) {
                    index.lookupGalleryResume("foreign_sender_01", manifest.sourceId, manifest.transferId, manifest.fingerprint, receiver, h.runtime.currentRequest()!!.policyEpoch)
                }
            }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeLookupReportsAcceptedHeadOnlyAsHistoricalHintWithoutRestoringRun() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val lookup = h.lookup()
            h.runtime.cancelResumeRun(run); h.runtime.endStoppedResumeRun(run)
            h.runtime.receiveSourceCommand(lookup, h.channel::send, { h.now })
            val history = h.drain().single()["body"]!!.jsonObject["history"]!!.jsonObject
            assertEquals(JsonPrimitive("accepted"), history["attempt_phase"])
            h.inspect { index ->
                val head = index.resumeAttempt(h.job)!!
                assertEquals(head.id, history.string("attempt_id")); assertEquals(head.version, history.string("attempt_sha256"))
            }
            assertEquals(JsonPrimitive(false), history["remote_saved_history"])
            assertFalse(history.containsKey("ready")); assertFalse(history.containsKey("resumable"))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveTransferMessage(h.acceptance(run), h.channel::send, { h.now + 120_000 }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeLookupRetiredOriginalRemainsHistoricalAndCannotBecomeAResumeRun() {
        ResumeRuntimeCase().use { h ->
            val message = h.lookup(); lateinit var retired: PhotoSourceJob
            h.inspect { index ->
                assertThrows(PhotoFolderScopeError::class.java) { index.retireAndClean(h.job) { } }
                retired = index.jobs().single(); assertEquals("retired", retired.phase)
            }
            h.runtime.receiveSourceCommand(message, h.channel::send, { h.now })
            val history = h.drain().single()["body"]!!.jsonObject["history"]!!.jsonObject
            assertEquals(JsonPrimitive("retired"), history["phase"]); assertEquals(retired.version, history.string("job_version"))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginResumeRun(h.selected, retired) }
            assertEquals(h.cipher, File(h.root, "photo-source-" + h.job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
            assertEquals("hello", File(h.f.root, "source.bin").readText())
        }
    }

    @Test fun resumeMediaPagePreservesOriginalFrozenAssociationsWithoutNewScanOfferOrRunGrant() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val command = h.media(run); val at = h.now + 120_000
            val opens = h.f.provider.opens.toList()
            h.f.provider.onQuery = { throw AssertionError("Media metadata must not rescan live source") }
            h.f.provider.onOpen = { throw AssertionError("Media metadata must read only original protected cache") }
            h.runtime.receiveSourceCommand(command, h.channel::send, { at })
            val reply = h.drain().single(); val body = reply["body"]!!.jsonObject
            assertEquals("resume_media_page", body.string("operation")); assertEquals(command.string("message_id"), body.string("request_id"))
            assertEquals(run.id, body.string("run_id")); assertEquals(h.originalMedia, body["page"])
            assertEquals(opens, h.f.provider.opens); assertNull(run.attempt.get()); assertNull(run.acceptance.get())
            h.inspect { assertNull(it.resumeAttempt(h.job)) }; h.assertOriginal()
        }
    }

    @Test fun resumeMediaPagesStayBoundedAndLostOutputRetriesExactOriginalPage() {
        ResumeRuntimeCase(9).use { h ->
            val run = h.start(); h.awaitEnd(30); val at = h.now + 120_000; val command = h.media(run)
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, { throw java.io.IOException("fixture resume media reply lost") }, { at }) }
            h.runtime.receiveSourceCommand(command, h.channel::send, { at })
            val first = h.drain().single()["body"]!!.jsonObject["page"]!!.jsonObject
            assertEquals(h.originalMedia, first); assertEquals(8, first["entries"]!!.jsonArray.size)
            assertEquals(JsonPrimitive(8), first["next_cursor"])
            val all = first["entries"]!!.jsonArray.toMutableList()
            for (after in listOf(8)) {
                h.runtime.receiveSourceCommand(h.media(run, after), h.channel::send, { at })
                val page = h.drain().single()["body"]!!.jsonObject["page"]!!.jsonObject
                assertEquals(first["source_epoch"], page["source_epoch"]); assertEquals(first["manifest_sha256"], page["manifest_sha256"])
                assertTrue(page["entries"]!!.jsonArray.size <= 8); all.addAll(page["entries"]!!.jsonArray)
                assertEquals(JsonNull, page["next_cursor"])
            }
            assertEquals(9, all.size); assertEquals(9, all.map { it.jsonObject.string("photo_id") }.distinct().size)
            h.assertOriginal()
        }
    }

    @Test fun resumeMediaPageRejectsChangedRequestForeignOwnerAndInvalidCursorWithoutFallback() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; val command = h.media(run)
            h.runtime.receiveSourceCommand(command, h.channel::send, { at }); h.drain()
            val body = command["body"]!!.jsonObject
            val changed = JsonObject(command + ("created_ms" to JsonPrimitive(at + 1)))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(changed, h.channel::send, { at + 1 }) }
            for ((field, value) in listOf("run_id" to JsonPrimitive(java.util.UUID.randomUUID().toString()), "after" to JsonPrimitive(true),
                "after" to JsonPrimitive(129), "operation" to JsonPrimitive("media_page"))) {
                val message = JsonObject(command + ("message_id" to JsonPrimitive(java.util.UUID.randomUUID().toString())) +
                    ("body" to JsonObject(body + (field to value))))
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(message, h.channel::send, { at + 1 }) }
            }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(h.media(run, 2), h.channel::send, { at + 1 }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeMediaPageRevocationOrExpiryDuringReplyCannotReturnLateSuccessOrReviveRetry() {
        for (change in listOf("exit", "expired", "lost-expired")) ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; val command = h.media(run); var wall = at
            assertThrows(java.io.IOException::class.java) {
                h.runtime.receiveSourceCommand(command, { message ->
                    h.channel.send(message)
                    if (change == "exit") h.runtime.revokeControl() else wall += 60_000
                    if (change == "lost-expired") throw java.io.IOException("fixture output failed while expired")
                }, { wall })
            }
            assertEquals(1, h.drain().size)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeEndRetiresOnlyActuallySavedOriginalCacheAndRetriesLostEndReply() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000
            h.runtime.receiveTransferMessage(h.saved(run), h.channel::send, { at })
            h.inspect { assertNotNull(it.remoteSaved(h.job)); assertEquals(listOf(h.job), it.jobs()) }
            assertTrue(File(h.root, "photo-source-" + h.job.id).isDirectory)
            h.runtime.cancelResumeRun(run)
            val command = h.resumeStatus("end_resume", run, at)
            assertThrows(java.io.IOException::class.java) {
                h.runtime.receiveSourceCommand(command, { h.channel.send(it); throw java.io.IOException("fixture Saved END reply lost") }, { at })
            }
            val first = h.drain().single()
            assertEquals(JsonPrimitive(true), first["body"]!!.jsonObject["run_ended"])
            h.inspect { assertTrue(it.jobs().isEmpty()) }
            assertFalse(File(h.root, "photo-source-" + h.job.id).exists())
            assertEquals("hello", File(h.f.root, "source.bin").readText())
            h.runtime.receiveSourceCommand(command, h.channel::send, { at + 1 })
            assertEquals(first, h.drain().single())
            h.inspect { assertTrue(it.jobs().isEmpty()) }
        }
    }

    @Test fun resumeEndLostReplyRetriesExactReceiptWithoutEndingAnotherActiveOwnerOrDroppingQuota() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            h.runtime.cancelResumeRun(run); val command = h.resumeStatus("end_resume", run, at)
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, {
                h.channel.send(it); throw java.io.IOException("fixture end reply lost")
            }, { at }) }
            val first = h.drain().single()
            assertEquals(JsonPrimitive(true), first["body"]!!.jsonObject["run_ended"])
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.endStoppedResumeRun(run) }
            val next = h.start(); h.awaitEnd()
            h.runtime.receiveSourceCommand(command, h.channel::send, { at + 1 })
            assertEquals(first, h.drain().single()); assertSame(next, h.currentResume()); assertFalse(next.cancelRequested)
            val changed = JsonObject(command + ("created_ms" to JsonPrimitive(at + 1)))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(changed, h.channel::send, { at + 1 }) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(h.resumeStatus("end_resume", run, at), h.channel::send, { at + 1 }) }
            assertEquals(0, h.output.size()); assertFalse(next.cancelRequested); h.assertOriginal()
        }
    }

    @Test fun resumeEndCannotReleaseBlockedProviderOwnerBeforeActualIoEnds() {
        ResumeRuntimeCase().use { h ->
            val entered = java.util.concurrent.CountDownLatch(1)
            h.f.provider.onOpen = { entered.countDown(); check(h.release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            val run = h.start(); val at = h.now + 120_000; val command = h.resumeStatus("end_resume", run, at)
            try {
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS)); h.runtime.cancelResumeRun(run)
                assertEquals("gallery_source_worker_io_pending", assertThrows(PhotoFolderScopeError::class.java) {
                    h.runtime.receiveSourceCommand(command, h.channel::send, { at })
                }.code)
                assertSame(run, h.currentResume()); assertEquals(0, h.output.size()); assertFalse(run.preparation.ioEnded)
            } finally { h.release.countDown(); h.awaitEnd() }
            h.runtime.receiveSourceCommand(command, h.channel::send, { at })
            assertEquals(JsonPrimitive(true), h.drain().single()["body"]!!.jsonObject["run_ended"])
            h.assertOriginal()
        }
    }

    @Test fun resumeEndRequiresStoppedOwnerAndExpiredReplyCannotBeRevivedByClockReturn() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000; val command = h.resumeStatus("end_resume", run, at)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            assertSame(run, h.currentResume()); h.runtime.cancelResumeRun(run)
            var wall = at
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, {
                h.channel.send(it); wall += 60_000
            }, { wall }) }
            assertEquals(1, h.drain().size)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun pendingResumeLookupHeadIdentityIsStableOnFreshReadAndChangesOnlyWithActualPhase() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            fun lookup(): JsonObject {
                h.runtime.receiveSourceCommand(h.lookup(), h.channel::send, { h.now })
                return h.drain().single()["body"]!!.jsonObject["history"]!!.jsonObject
            }
            assertThrows(java.io.IOException::class.java) { h.runtime.sendResumeRunOffer(run, { throw java.io.IOException("fixture pending lookup head") }, { at }) }
            val prepared = lookup()
            assertEquals(JsonPrimitive("prepared"), prepared["attempt_phase"])
            assertEquals(run.attempt.get()!!.id, prepared.string("attempt_id"))
            h.inspect { assertEquals(it.resumeAttempt(h.job)!!.version, prepared.string("attempt_sha256")) }
            assertEquals(prepared, lookup())
            h.runtime.sendResumeRunOffer(run, h.channel::send, { at }); h.drain()
            val sent = lookup(); assertEquals(prepared["attempt_id"], sent["attempt_id"])
            assertNotEquals(prepared["attempt_sha256"], sent["attempt_sha256"])
            h.runtime.observeResumeRunAcceptance(run, h.acceptance(run, at), { at })
            val accepted = lookup(); assertEquals(sent["attempt_id"], accepted["attempt_id"])
            assertNotEquals(sent["attempt_sha256"], accepted["attempt_sha256"])
            h.inspect { assertEquals(it.resumeAttempt(h.job)!!.version, accepted.string("attempt_sha256")) }
            assertFalse(accepted.containsKey("source_context")); assertFalse(accepted.containsKey("read_grant")); assertFalse(accepted.containsKey("repair_granted"))
            h.runtime.cancelResumeRun(run); h.runtime.endStoppedResumeRun(run)
            assertEquals(accepted, lookup())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveTransferMessage(h.acceptance(run, at), h.channel::send, { at }) }
            h.assertOriginal()
        }
    }

    private fun abandonCommand(h: ResumeRuntimeCase, run: NativeGalleryResumeRun, at: Long): JsonObject {
        lateinit var head: PhotoSourceResumeAttempt
        h.inspect { head = it.resumeAttempt(h.job)!! }
        return TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
            put("format", 1); put("operation", "abandon_resume"); put("expected_version", h.runtime.savedPolicy().version)
            put("run_id", run.id); put("original_job_id", h.job.id); put("original_job_version", h.job.version)
            put("attempt_id", head.id); put("attempt_sha256", head.version)
        }, 60_000, at)
    }

    @Test fun resumeAbandonmentRequiresActualEndedOwnerAndPreservesExactOldHeadBeforeReply() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000
            val command = abandonCommand(h, run, at)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            h.runtime.cancelResumeRun(run)
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            h.runtime.receiveSourceCommand(h.resumeStatus("end_resume", run, at), h.channel::send, { at }); h.drain()
            var durable: JsonObject? = null
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, { message ->
                h.inspect { index ->
                    val receipt = index.resumeAbandonments(h.job).single()
                    assertEquals(index.resumeAttempt(h.job)!!.record, receipt.head)
                    assertEquals(command, receipt.command)
                    assertEquals(receipt.version, message["body"]!!.jsonObject.string("receipt_sha256"))
                    durable = receipt.record
                }
                h.channel.send(message); throw java.io.IOException("fixture abandonment reply lost")
            }, { at }) }
            assertEquals(1, h.drain().size)
            h.runtime.receiveSourceCommand(command, h.channel::send, { at + 1 }); h.drain()
            h.inspect { assertEquals(durable, it.resumeAbandonments(h.job).single().record) }
            val next = h.start(); h.awaitEnd()
            h.runtime.sendResumeRunOffer(next, h.channel::send, { at + 2 }); h.drain()
            h.inspect { index ->
                assertNotEquals(command["body"]!!.jsonObject.string("attempt_id"), index.resumeAttempt(h.job)!!.id)
                assertEquals(durable, index.resumeAbandonments(h.job).single().record)
            }
            h.runtime.observeResumeRunAcceptance(next, h.acceptance(next, at + 2), { at + 2 })
            h.runtime.receiveResumeRunChunkRequest(next, h.chunk(next, at + 3), h.channel::send, { at + 3 })
            assertEquals(1, h.drain().size)
            h.assertOriginal()
        }
    }

    @Test fun resumeAbandonmentTransactionRollbackAndForeignHeadCannotManufactureReceipt() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000
            h.runtime.cancelResumeRun(run)
            h.runtime.receiveSourceCommand(h.resumeStatus("end_resume", run, at), h.channel::send, { at }); h.drain()
            val command = abandonCommand(h, run, at)
            val body = command["body"]!!.jsonObject
            val wrong = JsonObject(command + ("body" to JsonObject(body + ("attempt_sha256" to JsonPrimitive("9".repeat(64))))))
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(wrong, h.channel::send, { at }) }
            h.indexHook { if (it == "membership-protect") throw java.io.IOException("fixture abandonment tx rollback") }
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            h.inspect { assertTrue(it.resumeAbandonments(h.job).isEmpty()) }
            h.indexHook { }
            h.runtime.receiveSourceCommand(command, h.channel::send, { at }); h.drain()
            h.inspect { assertEquals(1, it.resumeAbandonments(h.job).size) }
            h.assertOriginal()
        }
    }

    @Test fun resumeAbandonmentCannotRunAlongsideNewNativeSourceOwner() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000
            val command = abandonCommand(h, run, at)
            h.runtime.cancelResumeRun(run)
            h.runtime.receiveSourceCommand(h.resumeStatus("end_resume", run, at), h.channel::send, { at }); h.drain()
            val next = h.start(); h.awaitEnd()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            assertSame(next, h.currentResume()); assertFalse(next.cancelRequested)
            h.inspect { assertTrue(it.resumeAbandonments(h.job).isEmpty()) }
            assertEquals(0, h.output.size()); h.assertOriginal()
        }
    }

    @Test fun resumeAbandonmentLostSyncKeepsHistoricalReceiptButCannotPublishSuccess() {
        ResumeRuntimeCase().use { h ->
            val run = h.acceptedRun(); val at = h.now + 240_000
            h.runtime.cancelResumeRun(run)
            h.runtime.receiveSourceCommand(h.resumeStatus("end_resume", run, at), h.channel::send, { at }); h.drain()
            val command = abandonCommand(h, run, at)
            h.indexHook { if (it == "membership-sync") throw java.io.IOException("fixture abandonment sync loss") }
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            assertEquals(0, h.output.size())
            h.inspect { assertEquals(command, it.resumeAbandonments(h.job).single().command) }
            h.indexHook { }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command, h.channel::send, { at }) }
            h.assertOriginal()
        }
    }

    @Test fun actualBatchCommandsContinueOnlyAfterEndedSourceAndRetryTheSameNewOwner() = batchCommandCase(false)

    @Test fun actualAcceptedUnsavedBatchEndCannotAuthorizeAnotherBatchOrInterleavedSource() = batchCommandCase(true)

    @Test fun actualEmptyBatchHasNoSourceJobOrOfferAndEndsWithoutSavedOrDeletionClaim() = batchCommandCase(false, true)

    @Test fun actualSelectedBatchKeepsScanPositionAndContinuesOnlyAfterSelectedNativeSavedEnd() = batchCommandCase(false, selectMember = true)

    @Test fun actualAdmittedSelectedAlbumContinuesAfterMetadataExpiry() = batchCommandCase(false, selectMember = true, expireCatalog = true)

    private fun batchCommandCase(holdAccepted: Boolean, empty: Boolean = false, selectMember: Boolean = false, expireCatalog: Boolean = false) {
        ResumeRuntimeCase().use { h ->
            val at = h.now + 120_000
            h.f.provider.rows = (1..17).map { Row(id = it.toLong(), name = "$it.jpg") }
            val discover = h.resumeCommand(at) // Real command discovery also binds the native wire catalog.
            val body = discover["body"]!!.jsonObject
            val begin = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, JsonObject(body.filterKeys {
                it !in setOf("original_job_id", "original_job_version")
            } + ("operation" to JsonPrimitive("batch_run"))), 60_000, at)
            fun current() = NativeGalleryFileRuntime::class.java.getDeclaredField("syncRun").also { it.isAccessible = true }
                .get(h.runtime) as NativeGallerySyncRun
            fun command(operation: String, run: NativeGallerySyncRun) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", operation); put("expected_version", h.runtime.savedPolicy().version); put("run_id", run.id)
            }, 60_000, at)
            if (empty) h.f.provider.rows = emptyList() // Live album disappeared AFTER discovery.
            h.watchEnd(); h.runtime.receiveSourceCommand(begin, h.channel::send, { at }); h.drain()
            // Bounded multi-photo wait; the original one-photo helper is unchanged.
            if (!h.ended.await(60, java.util.concurrent.TimeUnit.SECONDS)) {
                val active = Thread.getAllStackTraces().filterKeys { it.name == "magnolie-photo-source" }
                throw AssertionError(active.entries.joinToString("\n") { (thread, stack) ->
                    thread.state.toString() + "\n" + stack.joinToString("\n")
                })
            }
            var first = current()
            h.runtime.receiveSourceCommand(command("run_status", first), h.channel::send, { at })
            val status = h.drain().single()["body"]!!.jsonObject
            if (empty) {
                assertEquals(JsonPrimitive(true), status["batch_end"]); assertEquals("empty_ready", status.string("state"))
                assertNull(first.preparation.completedNativeJob())
                assertThrows(PhotoFolderScopeError::class.java) { h.runtime.sendSyncRunOffer(first, h.channel::send, at) }
                h.runtime.receiveSourceCommand(command("cancel_run", first), h.channel::send, { at }); h.drain()
                h.runtime.receiveSourceCommand(command("end_run", first), h.channel::send, { at }); h.drain()
                h.assertOriginal()
                return@use
            }
            assertEquals(JsonPrimitive(false), status["batch_end"])
            h.runtime.sendSyncRunOffer(first, h.channel::send, at)
            var offered = h.drain().single()
            var manifest = DeviceFileOfferEnvelope.validate(offered, h.identity.deviceId, h.peer.peerId, at)
            assertEquals(16, manifest.files.size)
            if (expireCatalog) {
                // Expire only metadata, not command deadlines or the monotonic
                // clock. The actual native run has already been admitted.
                val catalog = first.selection.catalog
                NativeGalleryAlbumCatalog::class.java.getDeclaredField("expires").also { it.isAccessible = true }
                    .setLong(catalog, DeviceFileControl.monotonicMs() - 1)
                assertThrows(PhotoFolderScopeError::class.java) { catalog.page() }
            }
            if (selectMember) {
                val preview = first
                val choose = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", 1); put("operation", "select_run"); put("expected_version", h.runtime.savedPolicy().version)
                    put("run_id", first.id); put("manifest_sha256", manifest.fingerprint)
                    put("file_ids", JsonArray(listOf(JsonPrimitive(manifest.files.first().id))))
                }, 60_000, at)
                h.watchEnd(); h.runtime.receiveSourceCommand(choose, h.channel::send, { at }); h.drain(); h.awaitEnd()
                first = current(); assertNotEquals(preview.id, first.id)
                h.runtime.sendSyncRunOffer(first, h.channel::send, at); offered = h.drain().single()
                manifest = DeviceFileOfferEnvelope.validate(offered, h.identity.deviceId, h.peer.peerId, at)
                assertEquals(1, manifest.files.size)
            }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command("next_batch", first), h.channel::send, { at }) }
            if (holdAccepted || selectMember) {
                h.runtime.observeAcceptance(TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                    put("format", 1); put("offer_id", offered.string("message_id")); put("transfer_id", manifest.transferId)
                    put("manifest_sha256", manifest.fingerprint); put("acceptance_sha256", "c".repeat(64))
                    put("permission_epoch", h.runtime.currentRequest()!!.receiver.permissionEpoch); put("destination_token", "e".repeat(64))
                }, 60_000, at), { at })
            }
            if (selectMember) {
                h.runtime.receiveChunkRequest(TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
                    put("format", 1); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                    put("acceptance_sha256", "c".repeat(64)); put("permission_epoch", h.runtime.currentRequest()!!.receiver.permissionEpoch)
                    put("destination_token", "e".repeat(64)); put("file_id", manifest.files.single().id); put("chunk_index", 0)
                }, 60_000, at), h.channel::send, { at })
                assertArrayEquals("hello".toByteArray(), java.util.Base64.getDecoder().decode(h.drain().single()["body"]!!.jsonObject.string("data_base64")))
                h.runtime.observeRemoteSaved(TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                    put("format", 1); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                    put("acceptance_sha256", "c".repeat(64)); put("permission_epoch", h.runtime.currentRequest()!!.receiver.permissionEpoch)
                    put("destination_token", "e".repeat(64)); put("receipts", JsonArray(manifest.files.map { buildJsonObject {
                        put("file_id", it.id); put("size", it.size); put("sha256", it.sha256); put("receipt_sha256", "0".repeat(64))
                    } }))
                }, 60_000, at), { at })
            }
            h.runtime.receiveSourceCommand(command("cancel_run", first), h.channel::send, { at }); h.drain()
            h.runtime.receiveSourceCommand(command("end_run", first), h.channel::send, { at }); h.drain()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.prepareSource(h.selected) }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.beginResumeRun(h.selected, h.job) }
            if (holdAccepted) {
                assertEquals("gallery_album_previous_batch_held", assertThrows(PhotoFolderScopeError::class.java) {
                    h.runtime.receiveSourceCommand(command("next_batch", first), h.channel::send, { at })
                }.code)
                val held = first.preparation.completedNativeJob()!!
                h.inspect { assertEquals(2, it.jobs().size); assertNotNull(it.remoteAcceptance(held)); assertNull(it.remoteSaved(held)) }
                assertTrue(File(h.root, "photo-source-" + held.id).exists())
                val abort = command("end_album", first)
                assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(abort, {
                    h.channel.send(it); throw java.io.IOException("fixture end-album output lost")
                }, { at }) }
                val ended = h.drain().single()
                assertEquals(JsonPrimitive(true), ended["body"]!!.jsonObject["run_ended"])
                assertFalse(ended["body"]!!.jsonObject.containsKey("saved"))
                h.f.provider.rows = listOf(Row())
                h.watchEnd()
                h.runtime.receiveSourceCommand(TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, begin["body"]!!.jsonObject, 60_000, at), h.channel::send, { at })
                h.drain(); h.awaitEnd(); val fresh = current()
                h.runtime.receiveSourceCommand(abort, h.channel::send, { at })
                assertEquals(ended, h.drain().single()); assertSame(fresh, current()); assertFalse(fresh.cancelRequested)
                h.runtime.receiveSourceCommand(command("cancel_run", fresh), h.channel::send, { at }); h.drain()
                h.runtime.receiveSourceCommand(command("end_run", fresh), h.channel::send, { at }); h.drain()
                h.inspect { assertEquals(2, it.jobs().size); assertNotNull(it.remoteAcceptance(held)); assertNull(it.remoteSaved(held)) }
                assertEquals(h.cipher, File(h.root, "photo-source-" + h.job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
                assertEquals("hello", File(h.f.root, "source.bin").readText())
                return@use
            }
            val next = command("next_batch", first)
            h.watchEnd()
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(next, {
                h.channel.send(it); throw java.io.IOException("fixture batch reply lost")
            }, { at }) }
            h.drain(); h.awaitEnd()
            val second = current(); assertNotEquals(first.id, second.id)
            val opened = h.f.provider.opens.size
            h.runtime.receiveSourceCommand(next, h.channel::send, { at }); h.drain()
            assertSame(second, current()); assertEquals(opened, h.f.provider.opens.size)
            h.runtime.receiveSourceCommand(command("run_status", second), h.channel::send, { at })
            assertEquals(JsonPrimitive(true), h.drain().single()["body"]!!.jsonObject["batch_end"])
            h.runtime.sendSyncRunOffer(second, h.channel::send, at)
            val remaining = DeviceFileOfferEnvelope.validate(h.drain().single(), h.identity.deviceId, h.peer.peerId, at)
            assertEquals(1, remaining.files.size); assertEquals("17.jpg", remaining.files.single().path)
            h.runtime.receiveSourceCommand(command("cancel_run", second), h.channel::send, { at }); h.drain()
            h.runtime.receiveSourceCommand(command("end_run", second), h.channel::send, { at }); h.drain()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command("next_batch", second), h.channel::send, { at }) }
            h.assertOriginal()
        }
    }

    @Test fun ordinaryNoDownloadRunEndsActualOwnerAndDiscardsOnlyItsNeverAcceptedCache() {
        ResumeRuntimeCase().use { h ->
            val at = h.now + 120_000
            fun command(operation: String, id: String) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", operation); put("expected_version", h.runtime.savedPolicy().version); put("run_id", id)
            }, 60_000, at)
            h.watchEnd(); val run = h.runtime.beginSyncRun(h.selected); h.awaitEnd()
            val unused = run.preparation.completedNativeJob()!!
            assertNotEquals(h.job.id, unused.id)
            h.runtime.sendSyncRunOffer(run, h.channel::send, at); h.drain()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.receiveSourceCommand(command("end_run", run.id), h.channel::send, { at }) }
            h.runtime.receiveSourceCommand(command("cancel_run", run.id), h.channel::send, { at }); h.drain()
            val end = command("end_run", run.id)
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(end, { message ->
                assertFalse(File(h.root, "photo-source-" + unused.id).exists())
                h.inspect { assertEquals(listOf(h.job), it.jobs()) }
                h.channel.send(message); throw java.io.IOException("fixture ordinary END reply lost")
            }, { at }) }
            val first = h.drain().single()
            assertEquals(JsonPrimitive(true), first["body"]!!.jsonObject["run_ended"])
            h.watchEnd(); val next = h.runtime.beginSyncRun(h.selected); h.awaitEnd()
            h.runtime.receiveSourceCommand(end, h.channel::send, { at + 1 })
            assertEquals(first, h.drain().single()); assertFalse(next.cancelRequested)
            h.runtime.receiveSourceCommand(command("cancel_run", next.id), h.channel::send, { at + 1 }); h.drain()
            h.runtime.receiveSourceCommand(command("end_run", next.id), h.channel::send, { at + 1 }); h.drain()
            h.assertOriginal() // The earlier accepted job/proof/cipher and real phone file survive both scans.
        }
    }

    @Test fun ordinarySelectedRunCopiesOnlyRequestedFrozenMemberWithoutReopeningPhonePhoto() {
        ResumeRuntimeCase(2).use { h ->
            val at = h.now + 120_000
            h.watchEnd(); val preview = h.runtime.beginSyncRun(h.selected); h.awaitEnd()
            val previewJob = preview.preparation.completedNativeJob()!!
            h.runtime.sendSyncRunOffer(preview, h.channel::send, at)
            val fullOffer = h.drain().single()
            val full = DeviceFileOfferEnvelope.validate(fullOffer, h.identity.deviceId, h.peer.peerId, at)
            val chosen = full.files.last()
            val command = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "select_run"); put("expected_version", h.runtime.savedPolicy().version)
                put("run_id", preview.id); put("manifest_sha256", full.fingerprint)
                put("file_ids", JsonArray(listOf(JsonPrimitive(chosen.id))))
            }, 60_000, at)
            val opens = h.f.provider.opens.toList()
            h.f.provider.onOpen = { throw AssertionError("Selected frozen member must not reopen the provider") }
            h.watchEnd()
            assertThrows(java.io.IOException::class.java) { h.runtime.receiveSourceCommand(command, {
                h.channel.send(it); throw java.io.IOException("fixture selected-run reply lost")
            }, { at }) }
            h.drain(); h.awaitEnd()
            val selected = NativeGalleryFileRuntime::class.java.getDeclaredField("syncRun").also { it.isAccessible = true }.get(h.runtime) as NativeGallerySyncRun
            h.runtime.receiveSourceCommand(command, h.channel::send, { at + 1 }); h.drain()
            assertSame(selected, NativeGalleryFileRuntime::class.java.getDeclaredField("syncRun").also { it.isAccessible = true }.get(h.runtime))
            assertNotEquals(preview.id, selected.id); assertTrue(preview.cancelRequested)
            assertNotEquals(previewJob.id, selected.preparation.snapshotJob()!!.id)
            assertFalse(File(h.root, "photo-source-" + previewJob.id).exists())
            assertEquals(opens, h.f.provider.opens)
            h.runtime.sendSyncRunOffer(selected, h.channel::send, at + 1)
            val offered = h.drain().single()
            val subset = DeviceFileOfferEnvelope.validate(offered, h.identity.deviceId, h.peer.peerId, at + 1)
            assertEquals(listOf(chosen), subset.files); assertNotEquals(full.transferId, subset.transferId)
            assertNotEquals(full.sourceId, subset.sourceId)
            h.runtime.observeAcceptance(TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                put("format", 1); put("offer_id", offered.string("message_id")); put("transfer_id", subset.transferId)
                put("manifest_sha256", subset.fingerprint); put("acceptance_sha256", "c".repeat(64))
                put("permission_epoch", h.runtime.currentRequest()!!.receiver.permissionEpoch); put("destination_token", "e".repeat(64))
            }, 60_000, at + 1), { at + 1 })
            val request = TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
                put("format", 1); put("transfer_id", subset.transferId); put("manifest_sha256", subset.fingerprint)
                put("acceptance_sha256", "c".repeat(64)); put("permission_epoch", h.runtime.currentRequest()!!.receiver.permissionEpoch)
                put("destination_token", "e".repeat(64)); put("file_id", chosen.id); put("chunk_index", 0)
            }, 60_000, at + 2)
            h.runtime.receiveChunkRequest(request, h.channel::send, { at + 2 })
            assertArrayEquals("hello".toByteArray(), java.util.Base64.getDecoder().decode(h.drain().single()["body"]!!.jsonObject.string("data_base64")))
            h.inspect { assertEquals(h.originalAcceptance, it.remoteAcceptance(h.job)!!.record); assertEquals(2, it.jobs().size) }
            h.runtime.observeRemoteSaved(TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                put("format", 1); put("transfer_id", subset.transferId); put("manifest_sha256", subset.fingerprint)
                put("acceptance_sha256", "c".repeat(64)); put("permission_epoch", h.runtime.currentRequest()!!.receiver.permissionEpoch)
                put("destination_token", "e".repeat(64)); put("receipts", JsonArray(listOf(buildJsonObject {
                    put("file_id", chosen.id); put("size", chosen.size); put("sha256", chosen.sha256); put("receipt_sha256", "0".repeat(64))
                })))
            }, 60_000, at + 2), { at + 2 })
            fun command(operation: String) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", operation); put("expected_version", h.runtime.savedPolicy().version); put("run_id", selected.id)
            }, 60_000, at + 3)
            h.runtime.receiveSourceCommand(command("cancel_run"), h.channel::send, { at + 3 }); h.drain()
            h.runtime.receiveSourceCommand(command("end_run"), h.channel::send, { at + 3 }); h.drain()
            h.inspect { assertEquals(listOf(h.job), it.jobs()) }
            assertEquals(h.cipher, File(h.root, "photo-source-" + h.job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
            assertEquals("hello", File(h.f.root, "source.bin").readText())
        }
    }

    @Test fun actualWorkflowVideoDomainRequiresExplicitPolicyThenFreezesVideoPfdAndRevokesWithoutPhotoEpochReset() {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            val root = Files.createTempDirectory(f.root.toPath(), "video-workflow330-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val receiver = f.receiver.copy(pairingEpoch = "1".repeat(64))
            NativeGalleryPhotoWorkflow(f.context, root, "sender_fixture_01", protection) { receiver }.use { workflow ->
                val photos = workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                assertNull(workflow.currentRequest(GalleryMediaType.VIDEO))
                assertEquals(GalleryReadCoverage.NONE, workflow.discover(mediaType = GalleryMediaType.VIDEO).coverage)
                assertTrue(f.provider.opens.isEmpty())
                val enabled = workflow.configureVideos(photos, true)
                val catalog = workflow.discoverSelectable(mediaType = GalleryMediaType.VIDEO)
                val page = catalog.page(); assertEquals("full_videos", page.string("coverage"))
                val selected = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                val job = workflow.freeze(selected)
                val source = workflow.source(job, catalog.source, selected.album, true)
                val file = source.manifest.files.single()
                assertEquals("clip.mp4", file.path)
                assertArrayEquals("hello".toByteArray(), source.readChunk(file.id, 0))
                assertEquals("video", source.mediaPage(0).string("media_type"))
                assertThrows(PhotoFolderScopeError::class.java) { source.observeImageAnimation(file.id) }
                assertTrue(f.provider.opens.isNotEmpty() && f.provider.opens.all { "/video/media/" in it })
                val cache = File(root, "photo-source-" + job.id)
                val bytes = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
                val disabled = workflow.configureVideos(enabled, false)
                assertEquals(photos.policy!!.epoch, disabled.policy!!.epoch)
                assertEquals(photos.policy!!.fileGrantRevision, disabled.policy!!.fileGrantRevision)
                assertEquals(GalleryMediaType.IMAGES, workflow.currentRequest()!!.mediaType)
                assertNull(workflow.currentRequest(GalleryMediaType.VIDEO))
                assertThrows(PhotoFolderScopeError::class.java) { source.readChunk(file.id, 0) }
                assertEquals(listOf(job), workflow.jobs())
                assertEquals(bytes, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
                assertEquals("hello", File(f.root, "source.bin").readText())
            }
        }
    }

    @Test @Config(sdk = [35]) fun modernWorkflowVideoReadUsesDeclaredIndependentVideoPermissionAndActualProvider() {
        actualWorkflowVideoDomainRequiresExplicitPolicyThenFreezesVideoPfdAndRevokesWithoutPhotoEpochReset()
    }

    @Test fun videoMetadataScopeChangeCannotInterleaveWithAnActuallyOwnedOriginalResumeRun() {
        ResumeRuntimeCase().use { h ->
            val run = h.start(); h.awaitEnd(); val at = h.now + 120_000
            val before = h.runtime.savedPolicy()
            val command = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "configure_videos"); put("expected_version", before.version); put("enabled", false)
            }, 60_000, at)
            var writes = 0
            assertEquals("gallery_sync_run_busy", assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.receiveSourceCommand(command, { writes++ }, { at })
            }.code)
            assertEquals(0, writes); assertEquals(before, h.runtime.savedPolicy()); h.assertOriginal()
            assertTrue(run.preparation.ioEnded)
            h.runtime.cancelResumeRun(run)
        }
    }

    @Test fun authenticatedVideoCatalogRejectsImageRunSubstitutionBeforeAnySourceIo() = videoCatalogRuntimeCase()
    @Test fun nativeVideoRunUsesItsOwnActivationForActualOfferChunkAndSavedWithoutImageFallback() = videoCatalogRuntimeCase(nativeData = true)
    @Test fun nativeVideoCapabilityWithdrawalBlocksOwnedVideoChunksButStillAllowsActualNativeCancelEnd() = videoCatalogRuntimeCase(nativeData = true, withdraw = true)
    @Test fun videoWireStopThenOriginalResumeUsesVideoLookupMediaSavedAndExactRetriedEnd() = videoCatalogRuntimeCase(nativeData = true, resume = true)
    @Test fun videoWireOriginalResumeCanCancelAndEndAfterCapabilityWithdrawalWithoutReadingOrRetiring() = videoCatalogRuntimeCase(nativeData = true, withdraw = true, resume = true)
    @Test @Config(sdk = [35]) fun modernVideoWireOriginalResumeUsesActualVideoReadAndSavedEnd() = videoCatalogRuntimeCase(nativeData = true, resume = true)
    @Test @Config(sdk = [35]) fun modernVideoWireWithdrawalKeepsExactOriginalUntilActualCancelEnd() = videoCatalogRuntimeCase(nativeData = true, withdraw = true, resume = true)
    @Test fun videoWireBatchesKeepMediaScopeAcrossSixteenFileBoundaryAndEndEachSavedCache() = videoCatalogRuntimeCase(nativeData = true, nextBatch = true)
    @Test fun videoWireAlbumScanCanEndAfterCapabilityWithdrawalWithoutOpeningRemainingMembers() = videoCatalogRuntimeCase(nativeData = true, nextBatch = true, endAlbum = true)
    @Test fun videoWireSubsetKeepsVideoIdentityAndRejectsImageSelectionBeforeChangingOriginalPreview() = videoCatalogRuntimeCase(nativeData = true, subset = true)

    private fun videoCatalogRuntimeCase(nativeData: Boolean = false, withdraw: Boolean = false, resume: Boolean = false,
        nextBatch: Boolean = false, endAlbum: Boolean = false, subset: Boolean = false) {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            if (nextBatch) f.provider.rows = (1..17).map { Row(id = it.toLong(), name = "clip-$it.mp4", mime = "video/mp4") }
            if (subset) f.provider.rows = (1..2).map { Row(id = it.toLong(), name = "clip-$it.mp4", mime = "video/mp4") }
            val root = Files.createTempDirectory(f.root.toPath(), "video-catalog-wire330-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val now = 1_800_000_000_000L; val output = ByteArrayOutputStream()
            val key = ByteArray(32) { 3 }; val prefix = ByteArray(4) { 4 }
            val channel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output, ByteArray(16), key.copyOf(), prefix, ByteArray(32), ByteArray(4))
            val identity = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
            val peer = NativeFileControlPeer(f.receiver.peerId, f.receiver.identitySha256, channel, true, true, true, true, true, "1".repeat(64), true)
            val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, peer.pairingEpoch)
            val pcState = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
            fun drainControl(): DeviceFileControlPacket {
                val frame = TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray())); output.reset()
                val header = JsonObject(frame - "ciphertext")
                val plain = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")),
                    java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header))
                return DeviceFileControlEnvelope.validate(Json.parseToJsonElement(plain.decodeToString()).jsonObject, now)
            }
            var videoReady = true
            NativeFileControlSession(NativeFileControlIdentity(peer.peerId, peer.identitySha256), { pcPeer }, { pcState }).use { desktop ->
                NativeGalleryFileRuntime.withVideoHandlers(f.context, root, identity, protection, channel, { peer }, { true }, { videoReady }).use { runtime ->
                    fun echo() {
                        if (runtime.sendControls(now)) desktop.observeRemote(drainControl(), pcPeer)
                        val packet = desktop.packet(); desktop.markSent(packet)
                        runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
                        if (runtime.sendControls(now)) desktop.observeRemote(drainControl(), pcPeer)
                    }
                    echo(); runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                    fun command(operation: String, extra: JsonObject = JsonObject(emptyMap())) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST,
                        JsonObject(mapOf("format" to JsonPrimitive(1), "operation" to JsonPrimitive(operation),
                            "expected_version" to JsonPrimitive(runtime.savedPolicy().version)) + extra), 60_000, now)
                    runtime.receiveSourceCommand(command("configure_videos", buildJsonObject { put("enabled", true) }), { }, { now })
                    var catalog: JsonObject? = null
                    runtime.receiveSourceCommand(command("discover", buildJsonObject { put("media_type", "video") }), { catalog = it["body"]!!.jsonObject }, { now })
                    val page = catalog!!["page"]!!.jsonObject
                    assertEquals("video", catalog!!.string("media_type")); assertEquals("full_videos", page.string("coverage"))
                    assertEquals(1, page["albums"]!!.jsonArray.size)
                    assertTrue(f.provider.requests.isNotEmpty()) // Video fixture rejects every non-video query URI itself.
                    assertTrue(f.provider.opens.isEmpty())
                    var writes = 0
                    assertEquals("gallery_catalog_not_current", assertThrows(PhotoFolderScopeError::class.java) {
                        runtime.receiveSourceCommand(command("run", buildJsonObject {
                            put("catalog_id", page.string("catalog_id"))
                            put("album_id", page["albums"]!!.jsonArray.single().jsonObject.string("album_id")); put("desktop_choice", true)
                        }), { writes++ }, { now })
                    }.code)
                    assertEquals(0, writes); assertTrue(f.provider.opens.isEmpty())
                    PhotoSourceJobIndex(root, protection).use { assertTrue(it.jobs().isEmpty()) }
                    if (nativeData) {
                        val worker = NativeGalleryFileRuntime::class.java.getDeclaredField("sourceWorker").also { it.isAccessible = true }.get(runtime) as NativeGallerySourceWorker
                        val onEnded = NativeGallerySourceWorker::class.java.getDeclaredField("onEnded").also { it.isAccessible = true }
                        @Suppress("UNCHECKED_CAST") val original = onEnded.get(worker) as (NativeGallerySourceRun) -> Unit
                        var ended = java.util.concurrent.CountDownLatch(1)
                        onEnded.set(worker, { value: NativeGallerySourceRun -> try { original(value) } finally { ended.countDown() } })
                        val replies = mutableListOf<JsonObject>()
                        var previousRunId: String? = null
                        val seenFiles = mutableSetOf<String>()
                        for (batchIndex in 0..(if (nextBatch && !endAlbum) 1 else 0)) {
                        ended = java.util.concurrent.CountDownLatch(1); replies.clear()
                        if (previousRunId != null) assertEquals("gallery_source_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) {
                            runtime.receiveSourceCommand(command("next_batch", buildJsonObject { put("run_id", previousRunId) }), { replies += it }, { now })
                        }.code)
                        runtime.receiveSourceCommand(command(if (previousRunId != null) "next_batch" else if (nextBatch) "batch_run" else "run", buildJsonObject {
                            put("media_type", "video")
                            if (previousRunId != null) put("run_id", previousRunId) else {
                                put("catalog_id", page.string("catalog_id"))
                                put("album_id", page["albums"]!!.jsonArray.single().jsonObject.string("album_id")); put("desktop_choice", true)
                            }
                        }), { replies += it }, { now })
                        val started = replies.single()["body"]!!.jsonObject; replies.clear()
                        assertEquals("video", started.string("media_type"))
                        var run = NativeGalleryFileRuntime::class.java.getDeclaredField("syncRun").also { it.isAccessible = true }.get(runtime) as NativeGallerySyncRun
                        assertEquals(run.id, started.string("run_id"))
                         // This first encrypted-original freeze prepares the fixture;
                         // separate resume/cancel waits below retain their five-second bound.
                         if (!ended.await(if (nextBatch) 60 else 30, java.util.concurrent.TimeUnit.SECONDS)) {
                             val stacks = Thread.getAllStackTraces().filter { it.key.name == "magnolie-photo-source" }
                                 .entries.joinToString("\n") { (thread, stack) -> thread.state.toString() + ": " + stack.take(10).joinToString("\n") }
                             fail("Initial video fixture completion deadline; quiescent=${worker.isQuiescent}\n$stacks")
                         }
                         run.preparation.nativeFailure()?.let { throw it }
                         var job = run.preparation.snapshotJob()!!
                        assertTrue(f.provider.opens.isNotEmpty() && f.provider.opens.all { "/video/media/" in it })
                        var currentRunId = run.id
                        fun runCommand(operation: String, media: String? = "video", extra: JsonObject = JsonObject(emptyMap())) = command(operation,
                            JsonObject(mapOf("run_id" to JsonPrimitive(currentRunId)) + (if (media == null) emptyMap() else mapOf("media_type" to JsonPrimitive(media))) + extra))
                        for (operation in listOf("run_status", "cancel_run", "offer_run")) {
                            assertEquals("gallery_source_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.receiveSourceCommand(runCommand(operation, null), { replies += it }, { now })
                            }.code)
                        }
                        assertTrue(replies.isEmpty()); assertFalse(run.cancelRequested)
                        var cursor: Int? = 0
                        var previewHash: String? = null; var selectedFile: String? = null
                        do {
                            runtime.receiveSourceCommand(runCommand("media_page", extra = buildJsonObject { put("after", cursor) }), { replies += it }, { now })
                            val media = replies.single()["body"]!!.jsonObject; replies.clear()
                            assertEquals("video", media.string("media_type")); assertEquals("video", media["page"]!!.jsonObject.string("media_type"))
                            previewHash = media["page"]!!.jsonObject.string("manifest_sha256")
                            if (selectedFile == null) selectedFile = media["page"]!!.jsonObject["entries"]!!.jsonArray.first().jsonObject.string("file_id")
                            val next = media["page"]!!.jsonObject["next_cursor"]!!
                            cursor = if (next == JsonNull) null else next.jsonPrimitive.int
                        } while (cursor != null)
                        if (subset) {
                            val originalPreview = job; val originalRun = run; val opens = f.provider.opens.size
                            val fields = buildJsonObject { put("manifest_sha256", previewHash); put("file_ids", JsonArray(listOf(JsonPrimitive(selectedFile)))) }
                            assertEquals("gallery_source_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.receiveSourceCommand(runCommand("select_run", null, fields), { replies += it }, { now })
                            }.code)
                            assertFalse(originalRun.cancelRequested)
                            PhotoSourceJobIndex(root, protection).use { assertEquals(listOf(originalPreview), it.jobs()) }
                            ended = java.util.concurrent.CountDownLatch(1)
                            runtime.receiveSourceCommand(runCommand("select_run", extra = fields), { replies += it }, { now })
                            val result = replies.single()["body"]!!.jsonObject; replies.clear()
                            assertEquals("video", result.string("media_type")); currentRunId = result.string("run_id")
                            assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                            run = NativeGalleryFileRuntime::class.java.getDeclaredField("syncRun").also { it.isAccessible = true }.get(runtime) as NativeGallerySyncRun
                            job = run.preparation.snapshotJob()!!
                            assertEquals(currentRunId, run.id); assertNotEquals(originalPreview.id, job.id)
                            assertEquals(opens, f.provider.opens.size)
                            runtime.receiveSourceCommand(runCommand("media_page", extra = buildJsonObject { put("after", 0) }), { replies += it }, { now })
                            val selected = replies.single()["body"]!!.jsonObject; replies.clear()
                            assertEquals("video", selected.string("media_type"))
                            assertEquals(selectedFile, selected["page"]!!.jsonObject["entries"]!!.jsonArray.single().jsonObject.string("file_id"))
                        }
                        runtime.receiveSourceCommand(runCommand("offer_run"), { replies += it }, { now })
                        val offer = replies.single { it.string("kind") == DeviceFileOfferEnvelope.KIND }
                        assertEquals("video", replies.single { it.string("kind") == DeviceFileSourceCommand.RUN_RESULT }["body"]!!.jsonObject.string("media_type"))
                        replies.clear()
                        val manifest = DeviceFileOfferEnvelope.validate(offer, identity.deviceId, peer.peerId, now)
                        if (nextBatch) assertEquals(if (batchIndex == 0) 16 else 1, manifest.files.size)
                        for (file in manifest.files) assertTrue(seenFiles.add(file.id))
                        val grant = runtime.currentRequest(GalleryMediaType.VIDEO)!!.receiver.permissionEpoch
                        fun accept(selectedOffer: JsonObject) = runtime.receiveTransferMessage(TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                                put("format", 1); put("offer_id", selectedOffer.string("message_id")); put("transfer_id", manifest.transferId)
                                put("manifest_sha256", manifest.fingerprint); put("acceptance_sha256", "c".repeat(64))
                                put("permission_epoch", grant); put("destination_token", "e".repeat(64))
                            }, 60_000, now), { replies += it }, { now })
                        accept(offer)
                        if (resume) {
                            runtime.receiveSourceCommand(runCommand("cancel_run"), { replies += it }, { now }); replies.clear()
                            runtime.receiveSourceCommand(runCommand("end_run"), { replies += it }, { now }); replies.clear()
                            PhotoSourceJobIndex(root, protection).use { assertEquals(listOf(job), it.jobs()); assertNull(it.remoteSaved(job)) }
                            assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.receiveSourceCommand(command("resume_lookup", buildJsonObject {
                                    put("source_id", manifest.sourceId); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                                }), { replies += it }, { now })
                            }
                            assertTrue(replies.isEmpty())
                            runtime.receiveSourceCommand(command("resume_lookup", buildJsonObject {
                                put("media_type", "video"); put("source_id", manifest.sourceId); put("transfer_id", manifest.transferId)
                                put("manifest_sha256", manifest.fingerprint)
                            }), { replies += it }, { now })
                            val history = replies.single()["body"]!!.jsonObject; replies.clear()
                            assertEquals("video", history.string("media_type")); assertEquals(job.id, history["history"]!!.jsonObject.string("job_id"))
                            runtime.receiveSourceCommand(command("discover", buildJsonObject { put("media_type", "video") }), { replies += it }, { now })
                            val fresh = replies.single()["body"]!!.jsonObject["page"]!!.jsonObject; replies.clear()
                            ended = java.util.concurrent.CountDownLatch(1)
                            runtime.receiveSourceCommand(command("resume_run", buildJsonObject {
                                put("media_type", "video"); put("catalog_id", fresh.string("catalog_id"))
                                put("album_id", fresh["albums"]!!.jsonArray.single().jsonObject.string("album_id")); put("desktop_choice", true)
                                put("original_job_id", job.id); put("original_job_version", job.version)
                            }), { replies += it }, { now })
                            val resumed = replies.single()["body"]!!.jsonObject; replies.clear()
                            currentRunId = resumed.string("run_id"); assertEquals("video", resumed.string("media_type"))
                            assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                            val originalOwner = NativeGalleryFileRuntime::class.java.getDeclaredField("resumeRun").also { it.isAccessible = true }.get(runtime) as NativeGalleryResumeRun
                            assertEquals(job, originalOwner.originalJob)
                            for (operation in listOf("resume_status", "cancel_resume", "offer_resume")) assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.receiveSourceCommand(runCommand(operation, null), { replies += it }, { now })
                            }
                            assertTrue(replies.isEmpty()); assertFalse(originalOwner.cancelRequested)
                            runtime.receiveSourceCommand(runCommand("resume_media_page", extra = buildJsonObject { put("after", 0) }), { replies += it }, { now })
                            assertEquals("video", replies.single()["body"]!!.jsonObject.string("media_type")); replies.clear()
                            runtime.receiveSourceCommand(runCommand("offer_resume"), { replies += it }, { now })
                            val renewedOffer = replies.single { it.string("kind") == DeviceFileOfferEnvelope.KIND }
                            assertEquals("video", replies.single { it.string("kind") == DeviceFileSourceCommand.RUN_RESULT }["body"]!!.jsonObject.string("media_type"))
                            replies.clear(); accept(renewedOffer)
                        }
                        fun chunkRequest(file: DeviceManifestFile) = TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST, buildJsonObject {
                            put("format", 1); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                            put("acceptance_sha256", "c".repeat(64)); put("permission_epoch", grant); put("destination_token", "e".repeat(64))
                            put("file_id", file.id); put("chunk_index", 0)
                        }, 60_000, now)
                        val cache = File(root, "photo-source-" + job.id)
                        val bytes = cache.listFiles()!!.associate { it.name to it.readBytes().toList() }
                        if (withdraw) {
                            videoReady = false
                            assertNotNull(runtime.currentRequest()); assertNull(runtime.currentRequest(GalleryMediaType.VIDEO))
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveTransferMessage(chunkRequest(manifest.files.first()), { replies += it }, { now }) }
                            assertTrue(replies.isEmpty())
                        } else {
                            for (file in manifest.files) {
                                runtime.receiveTransferMessage(chunkRequest(file), { replies += it }, { now })
                                assertArrayEquals("hello".toByteArray(), java.util.Base64.getDecoder().decode(replies.single()["body"]!!.jsonObject.string("data_base64")))
                                replies.clear()
                            }
                            runtime.receiveTransferMessage(TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND, buildJsonObject {
                                put("format", 1); put("transfer_id", manifest.transferId); put("manifest_sha256", manifest.fingerprint)
                                put("acceptance_sha256", "c".repeat(64)); put("permission_epoch", grant); put("destination_token", "e".repeat(64))
                                put("receipts", JsonArray(manifest.files.map { buildJsonObject {
                                    put("file_id", it.id); put("size", it.size); put("sha256", it.sha256); put("receipt_sha256", "0".repeat(64))
                                } }))
                            }, 60_000, now), { replies += it }, { now })
                        }
                        PhotoSourceJobIndex(root, protection).use {
                            assertEquals(listOf(job), it.jobs()); assertNotNull(it.remoteAcceptance(job))
                            if (withdraw) assertNull(it.remoteSaved(job)) else assertNotNull(it.remoteSaved(job))
                        }
                        assertEquals(bytes, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
                        runtime.receiveSourceCommand(runCommand(if (resume) "resume_status" else "run_status"), { replies += it }, { now })
                        if (nextBatch) assertEquals(JsonPrimitive(batchIndex == 1), replies.single()["body"]!!.jsonObject["batch_end"])
                        replies.clear()
                        runtime.receiveSourceCommand(runCommand(if (resume) "cancel_resume" else "cancel_run"), { replies += it }, { now }); replies.clear()
                        assertEquals("gallery_source_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) {
                            runtime.receiveSourceCommand(runCommand(if (resume) "end_resume" else "end_run", null), { replies += it }, { now })
                        }.code)
                        assertTrue(replies.isEmpty())
                        PhotoSourceJobIndex(root, protection).use { assertEquals(listOf(job), it.jobs()) }
                        assertEquals(bytes, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
                        val end = runCommand(if (resume) "end_resume" else "end_run")
                        assertThrows(java.io.IOException::class.java) {
                            runtime.receiveSourceCommand(end, { replies += it; throw java.io.IOException("fixture video END reply lost") }, { now })
                        }
                        val endedReply = replies.single(); replies.clear()
                        assertEquals("video", endedReply["body"]!!.jsonObject.string("media_type"))
                        assertEquals(JsonPrimitive(true), endedReply["body"]!!.jsonObject["run_ended"])
                        val changedType = JsonObject(end + ("body" to JsonObject(end["body"]!!.jsonObject - "media_type")))
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(changedType, { replies += it }, { now }) }
                        assertTrue(replies.isEmpty())
                        runtime.receiveSourceCommand(end, { replies += it }, { now })
                        assertEquals(endedReply, replies.single())
                        PhotoSourceJobIndex(root, protection).use { assertEquals(if (withdraw) listOf(job) else emptyList<PhotoSourceJob>(), it.jobs()) }
                        if (withdraw) assertEquals(bytes, cache.listFiles()!!.associate { it.name to it.readBytes().toList() }) else assertFalse(cache.exists())
                        if (withdraw && resume) {
                            // Capability return is not consent-epoch renewal. The
                            // original policy remains unchanged; only explicit
                            // metadata abandonment of the actually ended head follows.
                            videoReady = true; replies.clear()
                            val head = PhotoSourceJobIndex(root, protection).use { it.resumeAttempt(job)!! }
                            fun abandonment(media: Boolean) = command("abandon_resume", buildJsonObject {
                                if (media) put("media_type", "video")
                                put("run_id", currentRunId); put("original_job_id", job.id); put("original_job_version", job.version)
                                put("attempt_id", head.id); put("attempt_sha256", head.version)
                            })
                            assertEquals("gallery_source_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.receiveSourceCommand(abandonment(false), { replies += it }, { now })
                            }.code)
                            assertTrue(replies.isEmpty())
                            val abandon = abandonment(true)
                            runtime.receiveSourceCommand(abandon, { replies += it }, { now })
                            val receipt = replies.single(); replies.clear()
                            assertEquals("video", receipt["body"]!!.jsonObject.string("media_type"))
                            runtime.receiveSourceCommand(abandon, { replies += it }, { now })
                            assertEquals(receipt["body"], replies.single()["body"])
                            PhotoSourceJobIndex(root, protection).use {
                                assertEquals(listOf(job), it.jobs()); assertEquals(head.record, it.resumeAttempt(job)!!.record); assertNull(it.remoteSaved(job))
                                assertEquals(head.record, it.resumeAbandonments(job).single().head)
                            }
                            assertEquals(bytes, cache.listFiles()!!.associate { it.name to it.readBytes().toList() })
                        }
                        assertEquals("hello", File(f.root, "source.bin").readText())
                        previousRunId = run.id
                        }
                        if (nextBatch) assertEquals(if (endAlbum) 16 else 17, seenFiles.size)
                        if (endAlbum) {
                            val opens = f.provider.opens.size; videoReady = false; replies.clear()
                            assertEquals("gallery_source_media_scope_changed", assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.receiveSourceCommand(command("end_album", buildJsonObject { put("run_id", previousRunId) }), { replies += it }, { now })
                            }.code)
                            assertTrue(replies.isEmpty())
                            val end = command("end_album", buildJsonObject { put("media_type", "video"); put("run_id", previousRunId) })
                            assertThrows(java.io.IOException::class.java) {
                                runtime.receiveSourceCommand(end, { replies += it; throw java.io.IOException("fixture video album END reply lost") }, { now })
                            }
                            val reply = replies.single(); replies.clear()
                            assertEquals("video", reply["body"]!!.jsonObject.string("media_type"))
                            runtime.receiveSourceCommand(end, { replies += it }, { now })
                            assertEquals(reply, replies.single()); assertEquals(opens, f.provider.opens.size)
                            PhotoSourceJobIndex(root, protection).use { assertTrue(it.jobs().isEmpty()) }
                        }
                    }
                }
            }
            channel.close()
        }
    }

    @Test fun videoNativeDomainDiscoversOnlyVideoAlbumAndFreezesActualReadOnlyPfdWithoutPhotoScopeReuse() {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            val catalog = AndroidGalleryAlbumDiscovery(f.context, { f.request }, mediaType = GalleryMediaType.VIDEO).discover()
            assertEquals(GalleryReadCoverage.FULL_VIDEOS, catalog.coverage)
            assertFalse(catalog.provesFileDeletion); assertEquals(1, catalog.albums.size)
            assertTrue(f.provider.opens.isEmpty())
            val lease = f.scope.capture(catalog, catalog.albums.single())
            assertTrue(lease.sourceKey.startsWith("gallery-video-album-v1:"))
            val inventory = f.reader.enumerate(lease)
            assertEquals("clip.mp4", inventory.entries.single().relativePath)
            assertTrue(inventory.entries.single().documentUri.contains("/video/media/"))
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val cache = Files.createTempDirectory(f.root.toPath(), "native-video-cache-").toFile()
            val job: PhotoSourceJob
            PhotoSourceJobIndex(cache, protection).use { index ->
                val reserved = index.reserve(inventory, f.scope)
                val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, f.reader, protection)
                job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
            }
            val opens = f.provider.opens.size
            PhotoSourceJobIndex(cache, protection).use { index ->
                val restored = index.restore(job, "sender_fixture_01", f.scope, lease)
                assertNotNull(restored.galleryOrigins)
                assertArrayEquals("hello".toByteArray(), restored.readChunk(restored.manifest.files.single().id, 0))
                assertThrows(PhotoFolderScopeError::class.java) { restored.observeImageAnimation(restored.manifest.files.single().id) }
                val page = restored.mediaPage(0)
                assertEquals("video", page.string("media_type"))
                assertEquals("video", page["entries"]!!.jsonArray.single().jsonObject.string("media_kind"))
                assertEquals(restored.manifest.fingerprint, page.string("manifest_sha256"))
                assertEquals(opens, f.provider.opens.size)
                f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
                assertFalse(f.scope.isCurrent(lease))
                assertThrows(PhotoFolderScopeError::class.java) { restored.readChunk(restored.manifest.files.single().id, 0) }
                assertEquals(opens, f.provider.opens.size)
            }
        }
    }

    @Test fun videoInventoryRejectsImageMimeAndForgedImageUrisBeforeOpeningAnyBytes() {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            val lease = f.lease()
            val entry = f.reader.enumerate(lease).entries.single()
            val forged = entry.copy(documentUri = entry.documentUri.replace("/video/", "/images/"))
            assertThrows(PhotoFolderScopeError::class.java) { f.reader.openRead(lease, forged, CancellationSignal()) }
            f.provider.rows = listOf(Row(mime = "image/jpeg"))
            assertThrows(PhotoFolderScopeError::class.java) { f.reader.enumerate(lease) }
            assertTrue(f.provider.opens.isEmpty())
            val wrong = GalleryPhotoSourceScope({ f.request }, AndroidGalleryAccessEnvironment(f.context) { "a".repeat(64) })
            assertThrows(PhotoFolderScopeError::class.java) { wrong.capture(GalleryAlbumCatalog(GalleryReadCoverage.FULL_VIDEOS, listOf(f.album), f.request), f.album) }
        }
    }

    @Test @Config(sdk = [33]) fun grantedImagesAreNotNativeVideoReadPermissionOrAReasonToScanVideos() {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            val app = Shadows.shadowOf(f.context as Application)
            app.denyPermissions(Manifest.permission.READ_MEDIA_VIDEO)
            app.grantPermissions(Manifest.permission.READ_MEDIA_IMAGES)
            assertEquals(GalleryReadCoverage.FULL_IMAGES, AndroidGalleryReadPermissions.observe(f.context))
            assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(f.context, GalleryMediaType.VIDEO))
            val catalog = AndroidGalleryAlbumDiscovery(f.context, { f.request }, mediaType = GalleryMediaType.VIDEO).discover()
            assertEquals(GalleryReadCoverage.NONE, catalog.coverage)
            assertTrue(catalog.albums.isEmpty() && f.provider.requests.isEmpty() && f.provider.opens.isEmpty())
            assertThrows(PhotoFolderScopeError::class.java) { f.lease() }
        }
    }

    @Test fun inactiveOrImageOnlyNativePolicyCannotReachVideoQueriesEvenWithOsMediaPermission() {
        Fixture().use { f ->
            assertThrows(PhotoFolderScopeError::class.java) {
                AndroidGalleryAlbumDiscovery(f.context, { f.request }, mediaType = GalleryMediaType.VIDEO).discover()
            }
            assertTrue(f.provider.requests.isEmpty())
            f.request = null
            val catalog = AndroidGalleryAlbumDiscovery(f.context, { f.request }, mediaType = GalleryMediaType.VIDEO,
                readCoverage = { throw AssertionError("Inactive video source inspected OS permissions") }).discover()
            assertTrue(catalog.albums.isEmpty())
        }
    }

    @Test @Config(sdk = [33]) fun nativeGifImageStaysInPhotoDomainWithoutAnyVideoPermission() {
        Fixture().use { f ->
            Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_MEDIA_VIDEO)
            val gif = java.util.Base64.getDecoder().decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
            File(f.root, "source.bin").writeBytes(gif)
            f.provider.rows = listOf(Row(name = "animation.gif", mime = "image/gif", bytes = gif.size.toLong()))
            val catalog = AndroidGalleryAlbumDiscovery(f.context, { f.request }).discover()
            assertEquals(GalleryReadCoverage.FULL_IMAGES, catalog.coverage)
            val lease = f.scope.capture(catalog, catalog.albums.single())
            val inventory = f.reader.enumerate(lease)
            assertEquals("animation.gif", inventory.entries.single().relativePath)
            assertTrue(inventory.entries.single().documentUri.contains("/images/media/"))
            assertEquals(GalleryReadCoverage.NONE, AndroidGalleryReadPermissions.observe(f.context, GalleryMediaType.VIDEO))
            f.reader.openRead(lease, inventory.entries.single(), CancellationSignal()).use { assertArrayEquals(gif, it.readBytes()) }
            assertTrue(f.provider.opens.all { it.contains("/images/media/") })
        }
        Fixture(GalleryMediaType.VIDEO).use { f ->
            f.provider.rows = listOf(Row(name = "animation.gif", mime = "image/gif"))
            val catalog = AndroidGalleryAlbumDiscovery(f.context, { f.request }, mediaType = GalleryMediaType.VIDEO).discover()
            assertTrue(catalog.albums.isEmpty() && f.provider.opens.isEmpty())
            assertFalse(catalog.provesFileDeletion)
        }
    }

    @Test @Config(sdk = [34]) fun selectedVideoVisibilityNeverBecomesFullVideoCoverageOrRevivesAnOldReadLease() {
        Fixture(GalleryMediaType.VIDEO).use { f ->
            val original = f.lease()
            val app = Shadows.shadowOf(f.context as Application)
            app.denyPermissions(Manifest.permission.READ_MEDIA_VIDEO)
            app.grantPermissions(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            assertEquals(GalleryReadCoverage.SELECTED_ONLY, AndroidGalleryReadPermissions.observe(f.context, GalleryMediaType.VIDEO))
            assertFalse(f.scope.isCurrent(original))
            val limited = GalleryAlbumCatalog(GalleryReadCoverage.SELECTED_ONLY, listOf(f.album), f.request)
            val selected = f.scope.capture(limited, f.album)
            assertNotEquals(original.readGrantToken, selected.readGrantToken)
            assertFalse(selected.provesFileDeletion)
            app.denyPermissions(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            assertFalse(f.scope.isCurrent(selected))
            assertTrue(f.provider.opens.isEmpty())
        }
    }

    @Test fun nativeAnimationObservationReadsOnlyProtectedFrozenImageBytesAndRemainsBoundToItsLiveLease() {
        Fixture().use { f ->
            val gif = NativeImageAnimationTest().gif(2)
            File(f.root, "source.bin").writeBytes(gif)
            f.provider.rows = listOf(Row(name = "not-an-extension-hint.bin", mime = "image/gif", bytes = gif.size.toLong()))
            val lease = f.lease(); val inventory = f.reader.enumerate(lease)
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val cache = Files.createTempDirectory(f.root.toPath(), "native-animation-cache-").toFile()
            PhotoSourceJobIndex(cache, protection).use { index ->
                val reserved = index.reserve(inventory, f.scope)
                val snapshot = ProtectedPhotoSourceSnapshot.freeze(index.rootFile(reserved), inventory, "sender_fixture_01", f.scope, f.reader, protection)
                val job = index.publishSnapshot(reserved, snapshot, f.scope, lease)
                val source = index.restore(job, "sender_fixture_01", f.scope, lease)
                val file = source.manifest.files.single(); val opens = f.provider.opens.size
                val observed = source.observeImageAnimation(file.id)
                assertEquals(NativeImageAnimationKind.ANIMATED, observed.kind)
                assertEquals(file.sha256, observed.contentSha256)
                assertEquals(source.manifest.fingerprint, observed.manifestSha256)
                assertFalse(observed.grantsWriteAuthority); assertFalse(observed.isSavedReceipt)
                assertArrayEquals(gif, source.readChunk(file.id, 0))
                val page = source.mediaPage(0)
                assertEquals(source.manifest.fingerprint, page.string("manifest_sha256"))
                assertEquals("images", page.string("media_type"))
                assertEquals(64, page.string("source_epoch").length)
                val member = page["entries"]!!.jsonArray.single().jsonObject
                assertEquals(file.id, member.string("file_id")); assertEquals("animation", member.string("media_kind"))
                assertEquals(64, member.string("photo_id").length)
                assertFalse(page.toString().contains("native_member")); assertFalse(page.toString().contains("/media/"))
                assertTrue(source.mediaPage(1)["entries"]!!.jsonArray.isEmpty())
                assertThrows(PhotoFolderScopeError::class.java) { source.mediaPage(2) }
                var checks = 0
                assertThrows(PhotoFolderScopeError::class.java) {
                    source.mediaPage(0) { if (++checks == 5) DeviceFileControl.fail("fixture_media_command_expired_during_read") }
                }
                assertEquals(5, checks)
                assertEquals(opens, f.provider.opens.size)
                assertEquals("sealed", index.jobs().single().phase)
                f.request = null
                assertThrows(PhotoFolderScopeError::class.java) { source.observeImageAnimation(file.id) }
                assertEquals(opens, f.provider.opens.size)
            }
        }
    }

    @Test fun nativeAlbumBatchesFreezeRealSourcesAndRequirePreviousCacheRetirementBeforeContinuing() {
        Fixture().use { f ->
            f.provider.rows = (1..130).map { Row(id = it.toLong(), name = "$it.jpg") }
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-batches-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { }; activity.start().resume()
                val catalog = workflow.discoverSelectable()
                val page = catalog.page()
                val selection = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.first().jsonObject.string("album_id"), false)
                workflow.albumBatches(selection).use { scan ->
                    val first = scan.next(); val job = first.job!!
                    assertFalse(first.reachedCurrentEnd); assertFalse(first.provesDeletion)
                    val source = workflow.source(job, catalog.source, selection.album)
                    assertEquals(128, source.manifest.files.size)
                    val firstSourceId = source.manifest.sourceId
                    val firstOrigins = source.galleryOrigins!!.entries.map { it.nativeMember.substringBefore(':') }.toSet()
                    source.manifest.files.forEach { assertArrayEquals("hello".toByteArray(), source.readChunk(it.id, 0)) }
                    val opens = f.provider.opens.size
                    assertEquals("gallery_album_previous_batch_held", assertThrows(PhotoFolderScopeError::class.java) { scan.next() }.code)
                    assertEquals(opens, f.provider.opens.size); assertEquals(listOf(job), workflow.jobs())
                    workflow.retireCached(job) // Explicit native unaccepted preview cleanup, not a Saved claim.
                    assertTrue(workflow.jobs().isEmpty())
                    val last = scan.next(); assertTrue(last.reachedCurrentEnd); assertFalse(last.provesDeletion)
                    val lastJob = last.job!!
                    val rest = workflow.source(lastJob, catalog.source, selection.album)
                    assertEquals(2, rest.manifest.files.size)
                    assertNotEquals(firstSourceId, rest.manifest.sourceId)
                    assertEquals(setOf("129", "130"), rest.galleryOrigins!!.entries.map { it.nativeMember.substringBefore(':') }.toSet())
                    assertEquals((1..128).map { it.toString() }.toSet(), firstOrigins)
                    rest.manifest.files.forEach { assertArrayEquals("hello".toByteArray(), rest.readChunk(it.id, 0)) }
                    assertThrows(PhotoFolderScopeError::class.java) { scan.next() }
                    workflow.retireCached(lastJob)
                }
                assertTrue(workflow.jobs().isEmpty()); assertEquals("hello", File(f.root, "source.bin").readText())
            } finally { workflow.close(); activity.pause().stop().destroy() }
        }
    }

    @Test fun nativeEmptyAlbumBatchCreatesNoJobAndCannotProveDeletion() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-empty-batch-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { }; activity.start().resume()
                val catalog = workflow.discoverSelectable(); val page = catalog.page()
                val selection = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.first().jsonObject.string("album_id"), false)
                f.provider.rows = emptyList() // The live album emptied AFTER discovery, not a delete authorization.
                workflow.albumBatches(selection).use { scan ->
                    val empty = scan.next()
                    assertNull(empty.job); assertTrue(empty.reachedCurrentEnd); assertFalse(empty.provesDeletion)
                    assertThrows(PhotoFolderScopeError::class.java) { scan.next() }
                }
                assertTrue(workflow.jobs().isEmpty()); assertTrue(f.provider.opens.isEmpty())
            } finally { workflow.close(); activity.pause().stop().destroy() }
        }
    }

    @Test fun nativeAlbumBatchCloseRequestsCancellationWithoutWaitingForBlockedProviderOrReleasingIo() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-blocked-batch-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
            val error = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            var worker: Thread? = null
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                workflow.bindActivity(activity.get()) { }; activity.start().resume()
                val catalog = workflow.discoverSelectable(); val page = catalog.page()
                val selection = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.first().jsonObject.string("album_id"), false)
                val scan = workflow.albumBatches(selection)
                f.provider.onQuery = { entered.countDown(); check(release.await(10, java.util.concurrent.TimeUnit.SECONDS)) }
                worker = Thread { try { scan.next() } catch (failure: Throwable) { error.set(failure) } }.also { it.start() }
                check(entered.await(10, java.util.concurrent.TimeUnit.SECONDS))
                scan.close() // Must return while provider still owns its open cursor.
                assertTrue(worker.isAlive); assertTrue(workflow.jobs().isEmpty())
                release.countDown(); worker.join(10_000); assertFalse(worker.isAlive)
                assertTrue(error.get() is OperationCanceledException)
                assertThrows(PhotoFolderScopeError::class.java) { scan.next() }
                assertTrue(workflow.jobs().isEmpty()); assertTrue(f.provider.opens.isEmpty())
            } finally {
                release.countDown(); worker?.join(10_000)
                workflow.close(); activity.pause().stop().destroy()
            }
        }
    }

    @Test fun nativeBackgroundWorkflowUsesExistingOsReadAndExplicitFilePolicyWithoutActivityOrPrompt() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-background-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                assertTrue(workflow.discover().albums.isEmpty()); assertTrue(f.provider.requests.isEmpty())
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                val catalog = workflow.discoverSelectable(); val page = catalog.page()
                val selection = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), false)
                val result = java.util.concurrent.atomic.AtomicReference<PhotoSourceJob?>()
                val error = java.util.concurrent.atomic.AtomicReference<Throwable?>()
                val worker = Thread { try { result.set(workflow.freeze(catalog.source, selection.album)) } catch (failure: Throwable) { error.set(failure) } }
                worker.start(); worker.join(10_000); assertFalse(worker.isAlive); assertNull(error.get())
                val job = result.get()!!; val source = workflow.source(job, catalog.source, selection.album)
                assertArrayEquals("hello".toByteArray(), source.readChunk(source.manifest.files.single().id, 0))
                assertNull(Shadows.shadowOf(f.context as Application).nextStartedActivity)
                assertEquals("hello", File(f.root, "source.bin").readText())
                workflow.nativeReadAccessChanged()
                assertThrows(PhotoFolderScopeError::class.java) { source.offerMessage() }
                assertEquals(listOf(job), workflow.jobs()) // Epoch rotation is not retirement or Saved.
                workflow.retireCached(job)
            } finally { workflow.close() }
        }
    }

    @Test fun nativeBackgroundDiscoveryWithoutOsReadNeverPromptsOpensBytesOrProvesDeletion() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-background-denied-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                Shadows.shadowOf(f.context as Application).denyPermissions(if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE)
                val page = workflow.discoverSelectable().page()
                assertEquals("none", page.string("coverage")); assertTrue(page["albums"]!!.jsonArray.isEmpty())
                assertEquals(JsonPrimitive(false), page["proves_deletion"])
                assertTrue(f.provider.opens.isEmpty()); assertTrue(workflow.jobs().isEmpty())
                assertNull(Shadows.shadowOf(f.context as Application).nextStartedActivity)
                assertEquals("gallery_workflow_permission_host_missing", assertThrows(PhotoFolderScopeError::class.java) {
                    workflow.requestReadPermission() }.code)
            } finally { workflow.close() }
        }
    }

    @Test fun nativeActivityDestructionInvalidatesOldUiCatalogButFreshBackgroundReadKeepsExistingOsConsent() {
        Fixture().use { f ->
            val cache = Files.createTempDirectory(f.root.toPath(), "workflow-background-host-").toFile()
            val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
            val workflow = NativeGalleryPhotoWorkflow(f.context, cache, "sender_fixture_01", protection) { f.receiver }
            val activity = Robolectric.buildActivity(ComponentActivity::class.java).create()
            val host = GalleryPhotoPermissionHost(activity.get())
            var destroyed = false
            try {
                workflow.configure(workflow.savedPolicy(), true, setOf(GallerySourceKind.CAMERA))
                val background = workflow.discoverSelectable(); val first = background.page()
                workflow.attachPermissionHost(host) { throw AssertionError("No permission prompt expected") }
                activity.start().resume()
                assertThrows(PhotoFolderScopeError::class.java) {
                    background.select(first.string("catalog_id"), first["albums"]!!.jsonArray.single().jsonObject.string("album_id"), false)
                }
                val ui = workflow.discoverSelectable(); val old = ui.page()
                activity.pause().stop().destroy(); destroyed = true
                assertThrows(PhotoFolderScopeError::class.java) {
                    ui.select(old.string("catalog_id"), old["albums"]!!.jsonArray.single().jsonObject.string("album_id"), false)
                }
                val fresh = workflow.discoverSelectable(); val page = fresh.page()
                val selection = fresh.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), false)
                val job = workflow.freeze(fresh.source, selection.album)
                assertEquals("sealed", job.phase); assertEquals("hello", File(f.root, "source.bin").readText())
                workflow.retireCached(job)
            } finally { workflow.close(); if (!destroyed) activity.pause().stop().destroy() }
        }
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
                // Permission attempts above still opened no photo bytes. Only
                // this following explicit, exact-album run may prepare a source.
                Shadows.shadowOf(f.context as Application).grantPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
                runtime.receiveSourceCommand(request("discover", version), channel::send, { now })
                val runPage = drain().single()["body"]!!.jsonObject["page"]!!.jsonObject
                val start = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", 1); put("operation", "run"); put("expected_version", version)
                    put("catalog_id", runPage.string("catalog_id"))
                    put("album_id", runPage["albums"]!!.jsonArray.single().jsonObject.string("album_id")); put("desktop_choice", true)
                }, 60_000, now)
                val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
                val ended = java.util.concurrent.CountDownLatch(1)
                val worker = NativeGalleryFileRuntime::class.java.getDeclaredField("sourceWorker").also { it.isAccessible = true }.get(runtime)
                val endedField = NativeGallerySourceWorker::class.java.getDeclaredField("onEnded").also { it.isAccessible = true }
                @Suppress("UNCHECKED_CAST") val originalEnd = endedField.get(worker) as (NativeGallerySourceRun) -> Unit
                endedField.set(worker, { value: NativeGallerySourceRun -> try { originalEnd(value) } finally { ended.countDown() } })
                f.provider.onOpen = { entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                val sharedRuns = NativeGalleryRunCommands()
                try {
                    val expiring = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, start["body"]!!.jsonObject, 60_000, now)
                    var ticks = 0
                    assertThrows(PhotoFolderScopeError::class.java) {
                        runtime.receiveSourceCommand(expiring, channel::send,
                            { if (++ticks >= 4) now + 60_000 else now }, runCommands = sharedRuns)
                    }
                    assertTrue(f.provider.opens.isEmpty()); assertEquals(0, output.size())
                    assertThrows(java.io.IOException::class.java) {
                        runtime.receiveSourceCommand(start, { throw java.io.IOException("run reply lost") }, { now }, runCommands = sharedRuns)
                    }
                    assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    runtime.receiveSourceCommand(start, channel::send, { now }, runCommands = sharedRuns)
                    val running = drain().single()["body"]!!.jsonObject
                    assertEquals("preparing", running.string("state")); assertEquals(JsonPrimitive(false), running["source_io_ended"])
                    val runId = running.string("run_id")
                    val rewritten = JsonObject(start + ("body" to JsonObject(start["body"]!!.jsonObject + ("desktop_choice" to JsonPrimitive(false)))))
                    assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(rewritten, channel::send, { now }, runCommands = sharedRuns) }
                    fun control(op: String) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                        put("format", 1); put("operation", op); put("expected_version", version); put("run_id", runId)
                    }, 60_000, now)
                    runtime.receiveSourceCommand(control("cancel_run"), channel::send, { now })
                    assertEquals("cancel_pending", drain().single()["body"]!!.jsonObject.string("state"))
                    release.countDown(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    runtime.receiveSourceCommand(control("run_status"), channel::send, { now })
                    val stopped = drain().single()["body"]!!.jsonObject
                    assertEquals("canceled_held", stopped.string("state")); assertEquals(JsonPrimitive(true), stopped["source_io_ended"])
                    assertFalse(stopped.containsKey("success")); assertFalse(stopped.containsKey("quota_retired"))
                    val another = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, start["body"]!!.jsonObject, 60_000, now)
                    assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(another, channel::send, { now }, runCommands = sharedRuns) }
                    assertEquals(1, f.provider.opens.size)
                } finally {
                    release.countDown(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS))
                }
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
                    val sync = runtime.beginSyncRun(selected)
                    val started = sync.preparation; run = started
                    assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                    if (mode != "completed") {
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.prepareSource(selected) }
                        started.cancellation.setOnCancelListener {
                            assertFalse("Native cancellation ran under runtime ownership", Thread.holdsLock(runtime))
                        }
                        runtime.cancelSyncRun(sync)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedSyncRun(sync) }
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
                        val whole = sync
                        assertNotEquals(whole.id, started.id)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.beginSyncRun(selected) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.prepareSource(selected) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedSyncRun(whole) }
                        assertNull(whole.offeredManifestSha256)
                        assertThrows(java.io.IOException::class.java) {
                            runtime.sendSyncRunOffer(whole, { throw java.io.IOException("offer output failed") }, now)
                        }
                        assertNull(whole.offeredManifestSha256)
                        var manifest: DeviceFileManifest? = null
                        runtime.sendSyncRunOffer(whole, {
                            manifest = DeviceFileOfferEnvelope.validate(it, identity.deviceId, peer.peerId, now)
                            assertNull(whole.offeredManifestSha256) // Write callback has not completed yet.
                            channel.send(it)
                        }, now)
                        assertEquals(manifest!!.fingerprint, whole.offeredManifestSha256)
                        val frame = TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray())); output.reset()
                        val header = JsonObject(frame - "ciphertext")
                        val clear = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, header.long("seq")),
                            java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header))
                        assertEquals(manifest!!.fingerprint, DeviceFileOfferEnvelope.validate(
                            Json.parseToJsonElement(clear.decodeToString()).jsonObject, identity.deviceId, peer.peerId, now).fingerprint)
                        val actualOffer=whole.offerOutput.get()!!
                        var acceptance=TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                            put("format",1); put("offer_id",actualOffer.messageId); put("transfer_id",manifest!!.transferId)
                            put("manifest_sha256",manifest!!.fingerprint); put("acceptance_sha256","c".repeat(64))
                            put("permission_epoch",runtime.currentRequest()!!.receiver.permissionEpoch); put("destination_token","e".repeat(64))
                        },60_000,now)
                        for ((field,value) in listOf("offer_id" to JsonPrimitive(java.util.UUID.randomUUID().toString()),
                            "manifest_sha256" to JsonPrimitive("a".repeat(64)),"permission_epoch" to JsonPrimitive("a".repeat(64)))) {
                            val invalid=JsonObject(acceptance+("body" to JsonObject(acceptance["body"]!!.jsonObject+(field to value))))
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.observeAcceptance(invalid,{now}) }
                            assertNull(whole.acceptance.get())
                        }
                        var acceptanceTicks=0
                        assertThrows(PhotoFolderScopeError::class.java) {
                            runtime.observeAcceptance(acceptance,{if (++acceptanceTicks>=3) now+60_000 else now})
                        }
                        assertNull(whole.acceptance.get())
                        val wireOfferCommand = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                            put("format",1); put("operation","offer_run"); put("expected_version",runtime.savedPolicy().version); put("run_id",whole.id)
                        },60_000,now)
                        val providerOpens = f.provider.opens.size
                        val oldOutput = whole.offerOutput.get()
                        assertThrows(java.io.IOException::class.java) {
                            runtime.receiveSourceCommand(wireOfferCommand, { throw java.io.IOException("wire offer output failed") }, {now})
                        }
                        assertSame(oldOutput,whole.offerOutput.get())
                        assertNotNull(whole.wireOfferAttempt.get())
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.observeAcceptance(acceptance,{now}) }
                        fun drainedWire(): List<JsonObject> {
                            val input=ByteArrayInputStream(output.toByteArray());output.reset()
                            val result=mutableListOf<JsonObject>()
                            while(input.available()>0) {
                                val encrypted=TelefonRahmen.lesen(input);val aad=JsonObject(encrypted-"ciphertext")
                                val plain=TelefonKrypto.entschluesseln(key,TelefonKrypto.nonce(prefix,aad.long("seq")),
                                    java.util.Base64.getDecoder().decode(encrypted.string("ciphertext")),TelefonKanonisch.bytes(aad))
                                result+=Json.parseToJsonElement(plain.decodeToString()).jsonObject
                            }
                            return result
                        }
                        val mediaCommand = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                            put("format",1); put("operation","media_page"); put("expected_version",runtime.savedPolicy().version)
                            put("run_id",whole.id); put("after",0)
                        },60_000,now)
                        assertThrows(java.io.IOException::class.java) {
                            runtime.receiveSourceCommand(mediaCommand, { throw java.io.IOException("media output lost") }, {now})
                        }
                        runtime.receiveSourceCommand(mediaCommand,channel::send,{now})
                        val mediaResult = drainedWire().single()
                        assertEquals(DeviceFileSourceCommand.MEDIA,mediaResult.string("kind"))
                        val mediaBody = mediaResult["body"]!!.jsonObject
                        assertEquals(mediaCommand.string("message_id"),mediaBody.string("request_id"))
                        assertEquals(whole.id,mediaBody.string("run_id"))
                        assertEquals(manifest!!.fingerprint,mediaBody["page"]!!.jsonObject.string("manifest_sha256"))
                        assertEquals("unknown_image",mediaBody["page"]!!.jsonObject["entries"]!!.jsonArray.single().jsonObject.string("media_kind"))
                        runtime.receiveSourceCommand(mediaCommand,channel::send,{now})
                        assertEquals(mediaBody["page"],drainedWire().single()["body"]!!.jsonObject["page"])
                        val changedMedia = JsonObject(mediaCommand+("created_ms" to JsonPrimitive(now+1)))
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(changedMedia,channel::send,{now}) }
                        assertEquals(providerOpens,f.provider.opens.size)
                        assertThrows(java.io.IOException::class.java) {
                            runtime.receiveSourceCommand(wireOfferCommand, {
                                if(it.string("kind")==DeviceFileSourceCommand.RUN_RESULT) throw java.io.IOException("offer result output lost")
                                channel.send(it)
                            }, {now})
                        }
                        val unconfirmed=drainedWire().single()
                        assertEquals(DeviceFileOfferEnvelope.KIND,unconfirmed.string("kind"))
                        runtime.receiveSourceCommand(wireOfferCommand,channel::send,{now})
                        val offeredWire=drainedWire()
                        assertEquals(2,offeredWire.size);assertEquals(unconfirmed,offeredWire[0])
                        val wireResult=offeredWire[1]
                        assertEquals(DeviceFileSourceCommand.RUN_RESULT,wireResult.string("kind"))
                        assertEquals(wireOfferCommand.string("message_id"),wireResult["body"]!!.jsonObject.string("request_id"))
                        assertEquals("offer_run",wireResult["body"]!!.jsonObject.string("operation"))
                        assertEquals(offeredWire[0].string("message_id"),wireResult["body"]!!.jsonObject.string("offer_id"))
                        assertEquals(manifest!!.fingerprint,wireResult["body"]!!.jsonObject.string("manifest_sha256"))
                        assertTrue(wireResult.long("expires_ms")<=offeredWire[0].long("expires_ms"))
                        runtime.receiveSourceCommand(wireOfferCommand,channel::send,{now})
                        assertEquals(offeredWire[0],drainedWire()[0])
                        val changed=JsonObject(wireOfferCommand+("created_ms" to JsonPrimitive(now+1)))
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(changed,channel::send,{now}) }
                        val replacementCommand=TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST,wireOfferCommand["body"]!!.jsonObject,60_000,now)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveSourceCommand(replacementCommand,channel::send,{now}) }
                        assertEquals(0,output.size());assertEquals(providerOpens,f.provider.opens.size)
                        acceptance=JsonObject(acceptance+("body" to JsonObject(acceptance["body"]!!.jsonObject+
                            ("offer_id" to JsonPrimitive(offeredWire[0].string("message_id"))))))
                        runtime.receiveTransferMessage(acceptance,channel::send,{now}); runtime.observeAcceptance(acceptance,{now})
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.beginResumeRun(selected, started.snapshotJob()!!) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.issueHistoricalSavedAction(started.snapshotJob()!!) }
                        PhotoSourceJobIndex(root, protection).use { inspected ->
                            val originalJob = inspected.jobs().single()
                            assertEquals(whole.acceptance.get()!!.acceptanceSha256,
                                (inspected.remoteAcceptance(originalJob)!!.acceptance["acceptance_sha256"] as JsonPrimitive).content)
                            val originalAuthority = inspected.remoteAcceptance(originalJob)!!.originalAuthority!!
                            assertEquals(peer.peerId, originalAuthority.receiverId)
                            assertEquals(peer.identitySha256, originalAuthority.receiverIdentitySha256)
                            assertEquals(peer.pairingEpoch, originalAuthority.pairingEpoch)
                            assertEquals(runtime.currentRequest()!!.receiver.permissionEpoch, originalAuthority.permissionEpoch)
                            assertNull(inspected.remoteSaved(originalJob))
                        } // No chunk has been returned yet.
                        assertEquals("e".repeat(64),whole.acceptance.get()!!.destinationToken)
                        val chunkRequest=TelefonNachrichten.message(DeviceFileChunkEnvelope.REQUEST,buildJsonObject {
                            put("format",1);put("transfer_id",manifest!!.transferId);put("manifest_sha256",manifest!!.fingerprint)
                            put("acceptance_sha256","c".repeat(64));put("permission_epoch",runtime.currentRequest()!!.receiver.permissionEpoch)
                            put("destination_token","e".repeat(64));put("file_id",manifest!!.files.single().id);put("chunk_index",0)
                        },60_000,now)
                        val wrongChunk=JsonObject(chunkRequest+("body" to JsonObject(chunkRequest["body"]!!.jsonObject+("destination_token" to JsonPrimitive("f".repeat(64))))))
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveChunkRequest(wrongChunk,channel::send,{now}) }
                        var chunkTicks=0
                        assertThrows(PhotoFolderScopeError::class.java) {
                            runtime.receiveChunkRequest(chunkRequest,channel::send,{if (++chunkTicks>=3) now+60_000 else now})
                        }
                        assertEquals(0,output.size())
                        assertThrows(java.io.IOException::class.java) {
                            runtime.receiveChunkRequest(chunkRequest,{throw java.io.IOException("chunk output failed")},{now})
                        }
                        runtime.receiveTransferMessage(chunkRequest,channel::send,{now})
                        val chunkFrame=TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray()));output.reset()
                        val chunkHeader=JsonObject(chunkFrame-"ciphertext")
                        val chunkClear=TelefonKrypto.entschluesseln(key,TelefonKrypto.nonce(prefix,chunkHeader.long("seq")),
                            java.util.Base64.getDecoder().decode(chunkFrame.string("ciphertext")),TelefonKanonisch.bytes(chunkHeader))
                        val chunk=Json.parseToJsonElement(chunkClear.decodeToString()).jsonObject
                        assertEquals(DeviceFileChunkEnvelope.RESULT,chunk.string("kind"))
                        assertEquals(chunkRequest.string("message_id"),chunk["body"]!!.jsonObject.string("request_id"))
                        assertArrayEquals("hello".toByteArray(),java.util.Base64.getDecoder().decode(chunk["body"]!!.jsonObject.string("data_base64")))
                        val savedMessage=TelefonNachrichten.message(DeviceFileSavedEnvelope.KIND,buildJsonObject {
                            put("format",1);put("transfer_id",manifest!!.transferId);put("manifest_sha256",manifest!!.fingerprint)
                            put("acceptance_sha256","c".repeat(64));put("permission_epoch",runtime.currentRequest()!!.receiver.permissionEpoch)
                            put("destination_token","e".repeat(64));put("receipts",JsonArray(manifest!!.files.map { file -> buildJsonObject {
                                put("file_id",file.id);put("size",file.size);put("sha256",file.sha256);put("receipt_sha256","0".repeat(64))
                            } }))
                        },60_000,now)
                        val incompleteSaved=JsonObject(savedMessage+("body" to JsonObject(savedMessage["body"]!!.jsonObject+("receipts" to JsonArray(emptyList())))))
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.observeRemoteSaved(incompleteSaved,{now}) }
                        assertNull(whole.remoteSaved.get())
                        var savedTicks=0
                        assertThrows(PhotoFolderScopeError::class.java) {
                            runtime.observeRemoteSaved(savedMessage,{if (++savedTicks>=2) now+60_000 else now})
                        }
                        assertNull(whole.remoteSaved.get())
                        runtime.receiveTransferMessage(savedMessage,channel::send,{now})
                        val historical=whole.remoteSaved.get()!!
                        PhotoSourceJobIndex(root, protection).use { inspected ->
                            val originalJob = inspected.jobs().single()
                            assertEquals(started.snapshotJob()!!.id, originalJob.id)
                            assertEquals(historical.fingerprint, inspected.remoteSaved(originalJob)!!.confirmation.fingerprint)
                            assertEquals("sealed", originalJob.phase)
                        }
                        runtime.observeRemoteSaved(savedMessage,{now});assertSame(historical,whole.remoteSaved.get())
                        assertEquals(manifest!!.files.single().id,historical.members.single().fileId)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.beginSyncRun(selected) }
                        val replacement=JsonObject(acceptance+("body" to JsonObject(acceptance["body"]!!.jsonObject+("destination_token" to JsonPrimitive("f".repeat(64))))))
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.observeAcceptance(replacement,{now}) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.sendSyncRunOffer(whole,{},now) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.beginSyncRun(selected) }
                        val foreign = NativeGallerySyncRun(selected, started)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.cancelSyncRun(foreign) }
                        runtime.cancelSyncRun(whole)
                        assertTrue(whole.cancelRequested)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.observeAcceptance(acceptance,{now}) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.receiveChunkRequest(chunkRequest,channel::send,{now}) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.observeRemoteSaved(savedMessage,{now}) }
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.sendSyncRunOffer(whole, {}, now) }
                        runtime.endStoppedSyncRun(whole)
                        assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedSyncRun(whole) }
                        val originalJob = PhotoSourceJobIndex(root, protection).use { it.jobs().single() }
                        runtime.discoverSelectable().use { resumeCatalog ->
                            val resumePage = resumeCatalog.page()
                            val resumeSelected = resumeCatalog.select(resumePage.string("catalog_id"), resumePage["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                            val beforeResumeOpens = f.provider.opens.toList()
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.beginResumeRun(resumeSelected, originalJob.copy(version = "9".repeat(64))) }
                            assertEquals(beforeResumeOpens, f.provider.opens)
                            val resumeEntered = java.util.concurrent.CountDownLatch(1); val resumeRelease = java.util.concurrent.CountDownLatch(1)
                            val resumeEnded = java.util.concurrent.CountDownLatch(1)
                            endedField.set(worker, { value: NativeGallerySourceRun -> try { original(value) } finally { resumeEnded.countDown() } })
                            f.provider.onOpen = { resumeEntered.countDown(); check(resumeRelease.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                            try {
                                val resuming = runtime.beginResumeRun(resumeSelected, originalJob)
                                assertTrue(resumeEntered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                                assertFalse(resuming.preparation.ioEnded)
                                assertThrows(PhotoFolderScopeError::class.java) { resuming.source() }
                                assertThrows(PhotoFolderScopeError::class.java) { runtime.beginSyncRun(resumeSelected) }
                                assertThrows(PhotoFolderScopeError::class.java) { runtime.prepareSource(resumeSelected) }
                                assertThrows(PhotoFolderScopeError::class.java) { runtime.beginResumeRun(resumeSelected, originalJob) }
                                assertThrows(PhotoFolderScopeError::class.java) { runtime.issueHistoricalSavedAction(originalJob) }
                                runtime.cancelResumeRun(resuming)
                                assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedResumeRun(resuming) }
                                resumeRelease.countDown(); assertTrue(resumeEnded.await(5, java.util.concurrent.TimeUnit.SECONDS))
                                assertNull(resuming.preparation.renewedSource()); runtime.endStoppedResumeRun(resuming)
                            } finally { resumeRelease.countDown(); assertTrue(resumeEnded.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                            f.provider.onOpen = null
                            val ready = java.util.concurrent.CountDownLatch(1)
                            endedField.set(worker, { value: NativeGallerySourceRun -> try { original(value) } finally { ready.countDown() } })
                            val resumed = runtime.beginResumeRun(resumeSelected, originalJob)
                            assertTrue(ready.await(5, java.util.concurrent.TimeUnit.SECONDS))
                            val local = resumed.source(); val resumedFile = local.manifest.files.single()
                            assertArrayEquals("hello".toByteArray(), local.readChunk(resumedFile.id, 0))
                            assertEquals("gallery_resume_original_already_saved", assertThrows(PhotoFolderScopeError::class.java) {
                                runtime.sendResumeRunOffer(resumed, channel::send, { now })
                            }.code)
                            assertNull(resumed.attempt.get())
                            PhotoSourceJobIndex(root, protection).use { assertNull(it.resumeAttempt(originalJob)) }
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedResumeRun(resumed) }
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.beginSyncRun(resumeSelected) }
                            val foreignResume = NativeGalleryResumeRun(resumeSelected, originalJob, resumed.preparation)
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.cancelResumeRun(foreignResume) }
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedResumeRun(foreignResume) }
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.issueHistoricalSavedAction(originalJob) }
                            runtime.cancelResumeRun(resumed)
                            assertThrows(android.os.OperationCanceledException::class.java) { local.readChunk(resumedFile.id, 0).fill(0) }
                            runtime.endStoppedResumeRun(resumed)
                            File(f.root, "source.bin").writeText("HELLO")
                            val failedEnd = java.util.concurrent.CountDownLatch(1)
                            endedField.set(worker, { value: NativeGallerySourceRun -> try { original(value) } finally { failedEnd.countDown() } })
                            val failedResume = runtime.beginResumeRun(resumeSelected, originalJob)
                            assertTrue(failedEnd.await(5, java.util.concurrent.TimeUnit.SECONDS))
                            assertEquals("failed_held", failedResume.preparation.phase)
                            assertThrows(PhotoFolderScopeError::class.java) { failedResume.source() }
                            assertThrows(PhotoFolderScopeError::class.java) { runtime.endStoppedResumeRun(failedResume) }
                            runtime.cancelResumeRun(failedResume); runtime.endStoppedResumeRun(failedResume)
                            assertEquals("HELLO", File(f.root, "source.bin").readText())
                            assertEquals(listOf(originalJob), runtime.historicalSourceJobs())
                        }
                        assertNotNull(runtime.savedPolicy().policy); assertEquals(0, released.get())
                        // Explicit fixture user edit back to the original bytes for
                        // the separate blocked-close scenario, never app repair.
                        File(f.root, "source.bin").writeText("hello")
                        runtime.discoverSelectable().use { closingCatalog ->
                            val closingPage = closingCatalog.page()
                            val selectedClosing = closingCatalog.select(closingPage.string("catalog_id"), closingPage["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                            val enteredClose = java.util.concurrent.CountDownLatch(1); val releaseClose = java.util.concurrent.CountDownLatch(1)
                            val endedClose = java.util.concurrent.CountDownLatch(1)
                            endedField.set(worker, { value: NativeGallerySourceRun -> try { original(value) } finally { endedClose.countDown() } })
                            f.provider.onOpen = { enteredClose.countDown(); check(releaseClose.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                            try {
                                val closingRun = runtime.beginResumeRun(selectedClosing, originalJob)
                                assertTrue(enteredClose.await(5, java.util.concurrent.TimeUnit.SECONDS))
                                connection!!.close()
                                assertFalse(closingRun.preparation.ioEnded); assertEquals(0, released.get())
                                assertNotNull(runtime.savedPolicy().policy); assertNull(runtime.currentRequest())
                                releaseClose.countDown(); assertTrue(endedClose.await(5, java.util.concurrent.TimeUnit.SECONDS))
                                assertNull(closingRun.preparation.renewedSource())
                            } finally { releaseClose.countDown(); assertTrue(endedClose.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
                        }
                        connection!!.close()
                        val originalCache = File(root, "photo-source-" + originalJob.id)
                        val heldCache = File(root.parentFile, root.name + "-held-cache")
                        assertTrue(originalCache.renameTo(heldCache))
                        val previousOpens = f.provider.opens.toList()
                        val freshOutput = ByteArrayOutputStream(); val freshKey = ByteArray(32) { 7 }; val freshPrefix = ByteArray(4) { 8 }
                        val freshChannel = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), freshOutput, ByteArray(16),
                            freshKey.copyOf(), freshPrefix, ByteArray(32), ByteArray(4))
                        val freshPeer = peer.copy(owner = freshChannel)
                        val freshPcPeer = pcPeer.copy(owner = Any())
                        val freshDesktop = NativeFileControlSession(NativeFileControlIdentity(peer.peerId, peer.identitySha256), { freshPcPeer }, { pcState })
                        val reopened = NativeGalleryFileRuntime(f.context, root, identity, protection, freshChannel, { freshPeer }, { true })
                        try {
                            fun freshToDesktop() {
                                if (!reopened.sendControls(now)) return
                                val sent = TelefonRahmen.lesen(ByteArrayInputStream(freshOutput.toByteArray())); freshOutput.reset()
                                val sentHeader = JsonObject(sent - "ciphertext")
                                val decoded = TelefonKrypto.entschluesseln(freshKey, TelefonKrypto.nonce(freshPrefix, sentHeader.long("seq")),
                                    java.util.Base64.getDecoder().decode(sent.string("ciphertext")), TelefonKanonisch.bytes(sentHeader))
                                freshDesktop.observeRemote(DeviceFileControlEnvelope.validate(Json.parseToJsonElement(decoded.decodeToString()).jsonObject, now), freshPcPeer)
                            }
                            freshToDesktop(); val agreement = freshDesktop.packet(); freshDesktop.markSent(agreement)
                            reopened.observeControls(DeviceFileControlEnvelope.create(agreement, now), now); freshToDesktop()
                            val selectedOriginal = reopened.historicalSourceJobs().single()
                            val recovery = reopened.issueHistoricalSavedAction(selectedOriginal)
                            assertEquals(historical.fingerprint, reopened.recoverHistoricalSaved(recovery, savedMessage, { now }).confirmation.fingerprint)
                            assertThrows(PhotoFolderScopeError::class.java) { reopened.recoverHistoricalSaved(recovery, savedMessage, { now }) }
                            assertEquals(listOf(originalJob), reopened.historicalSourceJobs())
                            assertEquals(previousOpens, f.provider.opens)
                            assertEquals(0, freshOutput.size()) // No source/offer/chunk/ACK output.
                            val ending = reopened.issueHistoricalSavedAction(selectedOriginal)
                            reopened.close()
                            assertThrows(PhotoFolderScopeError::class.java) { reopened.recoverHistoricalSaved(ending, savedMessage, { now }) }
                        } finally {
                            reopened.close(); freshDesktop.close(); freshChannel.close()
                            assertTrue(heldCache.renameTo(originalCache))
                        }
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
