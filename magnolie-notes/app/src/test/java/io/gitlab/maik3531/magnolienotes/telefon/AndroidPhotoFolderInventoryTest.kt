package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.OperationCanceledException
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.DocumentsProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

/** Actual resolver/DocumentsProvider calls, synthetic metadata only; no personal URI/provider. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class AndroidPhotoFolderInventoryTest {
    private data class Row(val id: String, val name: String = "photo.jpg", val mime: String = "image/jpeg",
        val size: Any? = 5L, val modified: Any? = 100L, val flags: Any? = 0L)
    private class Provider : DocumentsProvider() {
        val rows = mutableMapOf<String, List<Row>>()
        val queried = mutableListOf<String>()
        val cursors = mutableListOf<Cursor>()
        var onQuery: (() -> Unit)? = null
        var onClose: (() -> Unit)? = null
        var opened = 0
        var deleted = 0
        override fun onCreate() = true
        override fun queryRoots(projection: Array<out String>?) = throw AssertionError("Unselected roots enumerated")
        override fun queryDocument(documentId: String, projection: Array<out String>?) = throw AssertionError("Unexpected document lookup")
        override fun queryChildDocuments(parentDocumentId: String, projection: Array<out String>?, sortOrder: String?): Cursor {
            queried += parentDocumentId
            val columns = requireNotNull(projection)
            val cursor = object : MatrixCursor(columns) {
                override fun close() { super.close(); onClose?.invoke() }
            }
            rows[parentDocumentId].orEmpty().forEach { row ->
                val fields = mapOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID to row.id,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME to row.name, DocumentsContract.Document.COLUMN_MIME_TYPE to row.mime,
                    DocumentsContract.Document.COLUMN_SIZE to row.size, DocumentsContract.Document.COLUMN_LAST_MODIFIED to row.modified,
                    DocumentsContract.Document.COLUMN_FLAGS to row.flags)
                cursor.addRow(columns.map { fields[it] }.toTypedArray())
            }
            cursors += cursor; onQuery?.invoke(); return cursor
        }
        override fun isChildDocument(parentDocumentId: String, documentId: String) = documentId.startsWith(parentDocumentId + "/")
        override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor {
            opened++; throw AssertionError("Inventory is not a frozen byte snapshot and must not open content")
        }
        override fun deleteDocument(documentId: String) { deleted++; throw AssertionError("Read-only inventory attempted provider mutation") }
    }

    private class Fixture {
        val context = RuntimeEnvironment.getApplication()
        val provider = Provider()
        var receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64),
            true, true, true, true, true, true, 1)
        val trees = AndroidReadOnlyPhotoTrees(context)
        val store = object : PhotoFolderPreferenceStore {
            var snapshot = PhotoPreferenceSnapshot("absent", null)
            override fun read() = snapshot
            override fun compareAndSet(expected: PhotoPreferenceSnapshot, next: PhotoFolderPreference, permitted: () -> Boolean): PhotoPreferenceSnapshot {
                check(expected == snapshot && permitted())
                snapshot = PhotoPreferenceSnapshot(next.epoch, next); return snapshot
            }
        }
        val scope = PhotoFolderScope({ receiver }, trees, store)
        val inventory = AndroidPhotoFolderInventory(context, scope)
        val lease: PhotoFolderLease
        init {
            provider.attachInfo(context, ProviderInfo().apply {
                authority = AUTHORITY; exported = true; grantUriPermissions = true
                readPermission = "android.permission.MANAGE_DOCUMENTS"; writePermission = "android.permission.MANAGE_DOCUMENTS"
            })
            ShadowContentResolver.registerProviderInternal(AUTHORITY, provider)
            scope.completePicker(scope.beginPicker(), TREE)
            scope.setEnabled(true)
            lease = requireNotNull(scope.lease())
        }
        fun scan() = inventory.enumerate(lease)
        fun assertReadOnlyAndClosed() {
            assertEquals(0, provider.opened); assertEquals(0, provider.deleted)
            assertTrue(provider.cursors.all { it.isClosed })
        }
    }

    @Test fun selectedTreeOnlyRecursesBoundedDirectoriesAndReturnsImmutableMetadataNotByteProofs() {
        val f = Fixture()
        f.provider.rows[ROOT] = listOf(Row("$ROOT/top", "Blüte.jpg"), Row("$ROOT/dir", "Trip", DocumentsContract.Document.MIME_TYPE_DIR),
            Row("$ROOT/text", "private.txt", "text/plain"))
        f.provider.rows["$ROOT/dir"] = listOf(Row("$ROOT/dir/photo", "second.png", "image/png", 12L, null))
        val result = f.scan()
        assertSame(f.lease, result.lease)
        assertEquals(listOf("Blüte.jpg", "Trip/second.png"), result.entries.map { it.relativePath })
        assertEquals(listOf(5L, 12L), result.entries.map { it.advertisedBytes })
        assertEquals(listOf(ROOT, "$ROOT/dir"), f.provider.queried)
        assertTrue(result.entries.all { it.documentUri.startsWith(TREE + "/document/") })
        assertThrows(UnsupportedOperationException::class.java) { (result.entries as MutableList<PhotoInventoryEntry>).clear() }
        f.assertReadOnlyAndClosed()
    }

    @Test fun outsideTreeCyclesDuplicateIdsUnsafeNamesAndVirtualFilesFailWithoutPartialInventory() {
        for (rows in listOf(listOf(Row("foreign/document")), listOf(Row(ROOT, "loop", DocumentsContract.Document.MIME_TYPE_DIR)),
            listOf(Row("$ROOT/same"), Row("$ROOT/same", "other.jpg")), listOf(Row("$ROOT/bad", "../escape.jpg")),
            listOf(Row("$ROOT/bad", "CON.jpg")), listOf(Row("$ROOT/bad", "e\u0301.jpg")),
            listOf(Row("$ROOT/bad", flags = DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT.toLong())),
            listOf(Row("$ROOT/first", "straße.jpg"), Row("$ROOT/second", "STRAẞE.jpg")))) {
            val f = Fixture(); f.provider.rows[ROOT] = rows
            assertThrows(PhotoFolderScopeError::class.java) { f.scan() }
            f.assertReadOnlyAndClosed()
        }
    }

    @Test fun malformedOrUnboundedMetadataIsNotTrustedAsACompleteTransferList() {
        for (row in listOf(Row("$ROOT/a", size = null), Row("$ROOT/a", size = "5"), Row("$ROOT/a", size = -1L),
            Row("$ROOT/a", size = DeviceFileManifest.MAX_FILE_BYTES + 1), Row("$ROOT/a", modified = -1L),
            Row("$ROOT/a", modified = "100"), Row("$ROOT/a", flags = null), Row("$ROOT/a", flags = "0"))) {
            val f = Fixture(); f.provider.rows[ROOT] = listOf(row)
            assertThrows(PhotoFolderScopeError::class.java) { f.scan() }; f.assertReadOnlyAndClosed()
        }
        for (rows in listOf((0..128).map { Row("$ROOT/$it", "photo$it.jpg") },
            (0..512).map { Row("$ROOT/$it", "ignored$it.txt", "text/plain") },
            (0..8).map { Row("$ROOT/$it", "photo$it.jpg", size = DeviceFileManifest.MAX_FILE_BYTES) },
            (0..31).map { Row("$ROOT/$it", "dir$it", DocumentsContract.Document.MIME_TYPE_DIR) })) {
            val f = Fixture(); f.provider.rows[ROOT] = rows
            assertThrows(PhotoFolderScopeError::class.java) { f.scan() }; f.assertReadOnlyAndClosed()
        }
        val deep = Fixture()
        for (depth in 0..16) {
            val parent = ROOT + "/d".repeat(depth)
            deep.provider.rows[parent] = listOf(Row("$parent/d", "folder", DocumentsContract.Document.MIME_TYPE_DIR))
        }
        assertEquals("photo_inventory_directory_limit", assertThrows(PhotoFolderScopeError::class.java) { deep.scan() }.code)
        deep.assertReadOnlyAndClosed()
    }

    @Test fun revocationCancellationAndLateProviderChangesCloseCursorsAndInvalidateTheLease() {
        for (point in listOf("before", "query", "close", "cancel")) {
            val f = Fixture(); f.provider.rows[ROOT] = listOf(Row("$ROOT/photo"))
            val cancellation = CancellationSignal()
            val revoke = { f.receiver = f.receiver.copy(permissionEpoch = "a".repeat(64)) }
            when (point) {
                "before" -> revoke()
                "query" -> f.provider.onQuery = revoke
                "close" -> f.provider.onClose = revoke
                "cancel" -> f.provider.onQuery = { cancellation.cancel() }
            }
            if (point == "cancel") assertThrows(OperationCanceledException::class.java) { f.inventory.enumerate(f.lease, cancellation) }
            else assertEquals("photo_inventory_source_revoked", assertThrows(PhotoFolderScopeError::class.java) {
                f.inventory.enumerate(f.lease, cancellation) }.code)
            if (point == "before") assertTrue(f.provider.queried.isEmpty())
            f.assertReadOnlyAndClosed()
        }
        val f = Fixture(); val cancellation = CancellationSignal().apply { cancel() }
        assertThrows(OperationCanceledException::class.java) { f.inventory.enumerate(f.lease, cancellation) }
        assertTrue(f.provider.queried.isEmpty())
    }

    companion object {
        private const val AUTHORITY = "inventory.fixture.documents"
        private const val ROOT = "selected"
        private const val TREE = "content://inventory.fixture.documents/tree/selected"
    }
}
