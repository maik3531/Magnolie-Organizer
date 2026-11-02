package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.ContentProvider
import android.content.ContentResolver
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.os.OperationCanceledException
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class AndroidGalleryAlbumDiscoveryTest {
    private data class Row(val id: Long, val bucket: String, val label: String, val mime: String = "image/jpeg")
    private class Provider : ContentProvider() {
        var rows: List<Row> = emptyList()
        val cursors = mutableListOf<Cursor>()
        val requests = mutableListOf<Bundle>()
        var onQuery: (() -> Unit)? = null
        var ignoreLimit = false
        var reverse = false
        override fun onCreate() = true
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, sort: String?): Cursor =
            throw AssertionError("Gallery discovery must use the actual API26 bundle query")
        override fun query(uri: Uri, projection: Array<out String>?, queryArgs: Bundle?, signal: CancellationSignal?): Cursor {
            check(uri.toString() == "content://media/external/images/media")
            val args = requireNotNull(queryArgs)
            requests += Bundle(args)
            val parameters = requireNotNull(args.getStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS))
            check(args.getString(ContentResolver.QUERY_ARG_SQL_SELECTION)!!.startsWith("_id > ? AND LOWER(bucket_display_name) IN ("))
            check(args.getString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER) == "_id ASC")
            val after = parameters.first().toLong(); val labels = parameters.drop(1).toSet()
            var filtered = rows.filter { it.id > after && it.label.lowercase(java.util.Locale.ROOT) in labels }.sortedBy { it.id }
            if (reverse) filtered = filtered.reversed()
            if (!ignoreLimit) filtered = filtered.take(args.getInt(ContentResolver.QUERY_ARG_LIMIT))
            val columns = requireNotNull(projection)
            check("_data" !in columns) // No technical filesystem paths or raw app-directory crawl.
            val cursor = MatrixCursor(columns)
            filtered.forEach { row ->
                val fields = mapOf("_id" to row.id, "bucket_id" to row.bucket, "bucket_display_name" to row.label, "mime_type" to row.mime)
                cursor.addRow(columns.map { fields[it] }.toTypedArray())
            }
            cursors += cursor; onQuery?.invoke(); return cursor
        }
        override fun getType(uri: Uri) = "vnd.android.cursor.dir/image"
        override fun insert(uri: Uri, values: ContentValues?): Uri = throw AssertionError("Read-only gallery attempted insert")
        override fun update(uri: Uri, values: ContentValues?, where: String?, args: Array<out String>?): Int = throw AssertionError("Read-only gallery attempted update")
        override fun delete(uri: Uri, where: String?, args: Array<out String>?): Int = throw AssertionError("Read-only gallery attempted delete")
    }
    private class Fixture {
        val context = RuntimeEnvironment.getApplication()
        val provider = Provider()
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        var request: NativeGalleryRequest? = NativeGalleryRequest(receiver, "a".repeat(64), setOf(GallerySourceKind.WHATSAPP_RECEIVED))
        init {
            provider.attachInfo(context, ProviderInfo().apply { authority = "media"; exported = true })
            ShadowContentResolver.registerProviderInternal("media", provider)
            Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        fun discovery() = AndroidGalleryAlbumDiscovery(context, { request })
        fun assertClosed() { assertTrue(provider.cursors.all { it.isClosed }) }
    }

    @Test fun noActivationOrNoActualOsPhotoPermissionNeverQueriesTheGallery() {
        val f = Fixture()
        f.request = null
        val disabled = AndroidGalleryAlbumDiscovery(f.context, { f.request }) { throw AssertionError("Unactivated photo source inspected OS grants") }
        assertTrue(disabled.discover().albums.isEmpty()); assertTrue(f.provider.requests.isEmpty())
        f.request = NativeGalleryRequest(f.receiver, "a".repeat(64), emptySet())
        assertTrue(disabled.discover().albums.isEmpty())
        f.request = NativeGalleryRequest(f.receiver, "a".repeat(64), setOf(GallerySourceKind.WHATSAPP_RECEIVED))
        Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
        assertEquals(GalleryReadCoverage.NONE, f.discovery().discover().coverage)
        assertTrue(f.provider.requests.isEmpty())
    }

    @Test fun activatedMessengerIsFoundAutomaticallyThroughTargetedPagedAlbumQueriesOnly() {
        val f = Fixture()
        f.provider.rows = (1..600).map { Row(it.toLong(), "whatsapp-album", "WhatsApp Images") } +
            listOf(Row(700, "camera-album", "Camera"), Row(701, "private-album", "Private"), Row(702, "sent-album", "WhatsApp Sent"))
        val catalog = f.discovery().discover()
        assertEquals(GalleryReadCoverage.FULL_IMAGES, catalog.coverage)
        assertEquals("a".repeat(64), catalog.policyEpoch); assertSame(f.request, catalog.activation)
        assertEquals(600L, catalog.albums.single().visibleImageCount)
        assertEquals(GallerySourceKind.WHATSAPP_RECEIVED, catalog.albums.single().kind)
        assertEquals(3, f.provider.requests.size)
        assertTrue(f.provider.requests.all { args -> args.getStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS)!!.drop(1)
            .all { it in setOf("whatsapp images", "whatsapp business images") } })
        assertFalse(catalog.provesFileDeletion)
        assertThrows(UnsupportedOperationException::class.java) { (catalog.albums as MutableList<GalleryAlbumCandidate>).clear() }
        f.assertClosed()
    }

    @Test fun ambiguousLegacyAlbumsNeedADesktopChoiceAndLimitedPhotoVisibilityNeverProvesDeletion() {
        val f = Fixture(); f.provider.rows = listOf(Row(1, "bucket-a", "WhatsApp Images"), Row(2, "bucket-b", "WhatsApp Images"))
        val limited = AndroidGalleryAlbumDiscovery(f.context, { f.request }) { GalleryReadCoverage.SELECTED_ONLY }.discover()
        assertEquals(GalleryReadCoverage.SELECTED_ONLY, limited.coverage)
        assertEquals(2, limited.albums.size); assertTrue(limited.albums.all { it.needsAlbumChoice })
        assertFalse(limited.provesFileDeletion)
        f.provider.rows = emptyList()
        val invisible = AndroidGalleryAlbumDiscovery(f.context, { f.request }) { GalleryReadCoverage.SELECTED_ONLY }.discover()
        assertTrue(invisible.albums.isEmpty()); assertFalse(invisible.provesFileDeletion)
        f.assertClosed()
    }

    @Test fun actualQueryScopeGrantOrOwnerChangesAndCancellationInvalidateTheWholeCatalog() {
        for (change in listOf("owner", "epoch", "policy", "permission", "cancel")) {
            val f = Fixture(); f.provider.rows = listOf(Row(1, "bucket", "WhatsApp Images"))
            val cancellation = CancellationSignal()
            f.provider.onQuery = {
                when (change) {
                    "owner" -> f.request = NativeGalleryRequest(f.receiver.copy(owner = Any()), "a".repeat(64), f.request!!.kinds)
                    "epoch" -> f.request = NativeGalleryRequest(f.receiver.copy(permissionEpoch = "b".repeat(64)), "a".repeat(64), f.request!!.kinds)
                    "policy" -> f.request = NativeGalleryRequest(f.receiver, "b".repeat(64), setOf(GallerySourceKind.CAMERA))
                    "permission" -> Shadows.shadowOf(f.context as Application).denyPermissions(Manifest.permission.READ_EXTERNAL_STORAGE)
                    "cancel" -> cancellation.cancel()
                }
            }
            if (change == "cancel") assertThrows(OperationCanceledException::class.java) { f.discovery().discover(cancellation) }
            else assertEquals("gallery_source_scope_changed", assertThrows(PhotoFolderScopeError::class.java) { f.discovery().discover(cancellation) }.code)
            f.assertClosed()
        }
    }

    @Test fun unboundedOrMisorderedProviderPagesAreNotSilentlyAcceptedAsAnInventory() {
        for (reverse in listOf(false, true)) {
            val f = Fixture()
            f.provider.rows = (1..(AndroidGalleryAlbumDiscovery.PAGE_SIZE + 1)).map { Row(it.toLong(), "bucket", "WhatsApp Images") }
            f.provider.ignoreLimit = !reverse; f.provider.reverse = reverse
            assertEquals(if (reverse) "gallery_invalid_page_order" else "gallery_provider_page_limit",
                assertThrows(PhotoFolderScopeError::class.java) { f.discovery().discover() }.code)
            f.assertClosed()
        }
    }

    @Test fun knownModernPathsMatchReceivedAlbumsWithoutSentBackupsOrNameOnlyGuessing() {
        val kind = setOf(GallerySourceKind.WHATSAPP_RECEIVED)
        for (path in listOf("WhatsApp/Media/WhatsApp Images/", "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/",
            "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Images/"))
            assertEquals(GallerySourceKind.WHATSAPP_RECEIVED, GallerySourceRules.classify(kind, "Label can differ", path, true))
        for (path in listOf("Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/Sent/", "Backup/WhatsApp/Media/WhatsApp Images/",
            "Pictures/Private/", "WhatsApp/Media/WhatsApp Images/../private/"))
            assertNull(GallerySourceRules.classify(kind, "WhatsApp Images", path, true))
        assertNull(GallerySourceRules.classify(kind, "WhatsApp Images", null, true))
        assertNull(GallerySourceRules.classify(setOf(GallerySourceKind.CAMERA), "WhatsApp Images", "WhatsApp/Media/WhatsApp Images/", true))
    }

    @Test fun mutableDesktopDraftsCannotWidenCapturedSourceKindsWithoutANewNativePolicy() {
        val f = Fixture()
        val kinds = mutableSetOf(GallerySourceKind.WHATSAPP_RECEIVED)
        f.request = NativeGalleryRequest(f.receiver, "a".repeat(64), kinds)
        kinds.add(GallerySourceKind.CAMERA)
        f.provider.rows = listOf(Row(1, "whatsapp", "WhatsApp Images"), Row(2, "camera", "Camera"))
        assertEquals(listOf(GallerySourceKind.WHATSAPP_RECEIVED), f.discovery().discover().albums.map { it.kind })
        assertThrows(UnsupportedOperationException::class.java) { (f.request!!.kinds as MutableSet<GallerySourceKind>).add(GallerySourceKind.CAMERA) }
        f.assertClosed()
    }
}
