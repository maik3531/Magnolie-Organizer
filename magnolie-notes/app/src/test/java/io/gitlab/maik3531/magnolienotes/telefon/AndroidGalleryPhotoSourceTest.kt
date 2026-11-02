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
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.nio.file.Files
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29], application = Application::class, shadows = [AndroidGalleryVolumeAccessTest.MountedVolumes::class])
class AndroidGalleryPhotoSourceTest {
    private data class Row(val id: Long = 1, val bucket: String = "camera", val label: String = "Camera",
        val name: String = "image.jpg", val bytes: Long = 5, val modified: Any = 100L, val added: Long = 90,
        val mime: String = "image/jpeg", val path: String = "DCIM/Camera/", val pending: Long = 0, val trashed: Long = 0)
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
            check(uri.toString().startsWith("content://media/$volume/images/media"))
            val args = requireNotNull(queryArgs)
            var selected = rows
            if (uri.pathSegments.size == 3) {
                requests += Bundle(args)
                check(args.getString(ContentResolver.QUERY_ARG_SQL_SELECTION) == "_id > ? AND bucket_id = ?" +
                    (if (Build.VERSION.SDK_INT >= 29) " AND is_pending = 0" else "") +
                    (if (Build.VERSION.SDK_INT >= 30) " AND is_trashed = 0" else ""))
                check(args.getString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER) == "_id ASC")
                val values = requireNotNull(args.getStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS))
                if (!ignoreSelection) selected = selected.filter { it.id > values[0].toLong() && it.bucket == values[1] &&
                    (Build.VERSION.SDK_INT < 29 || it.pending == 0L) && (Build.VERSION.SDK_INT < 30 || it.trashed == 0L) }
                selected = selected.sortedBy { it.id }
                if (reverse) selected = selected.reversed()
                if (!ignoreLimit) selected = selected.take(args.getInt(ContentResolver.QUERY_ARG_LIMIT))
            } else selected = selected.filter { it.id.toString() == uri.lastPathSegment }
            val cursor = MatrixCursor(columns)
            selected.forEach { row ->
                val data = mapOf("_id" to row.id, "bucket_id" to row.bucket, "bucket_display_name" to row.label,
                    "_display_name" to row.name, "mime_type" to row.mime, "_size" to row.bytes,
                    "date_modified" to row.modified, "date_added" to row.added, "relative_path" to row.path, "is_pending" to row.pending,
                    "is_trashed" to row.trashed)
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
