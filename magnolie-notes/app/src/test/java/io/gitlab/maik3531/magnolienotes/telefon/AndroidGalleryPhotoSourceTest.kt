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
    private class Provider(val root: File, val mediaType: GalleryMediaType = GalleryMediaType.IMAGES) : ContentProvider() {
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
    private class ResumeRuntimeCase : AutoCloseable {
        val f = Fixture()
        val root = Files.createTempDirectory(f.root.toPath(), "resume-runtime356-").toFile()
        val protection = DeviceTransferProtection.fromExistingKeyReader { SecretKeySpec(ByteArray(32) { it.toByte() }, "AES") }
        val now = 1_800_000_000_000L
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
        val worker = NativeGalleryFileRuntime::class.java.getDeclaredField("sourceWorker").also { it.isAccessible = true }.get(runtime) as NativeGallerySourceWorker
        val endedField = NativeGallerySourceWorker::class.java.getDeclaredField("onEnded").also { it.isAccessible = true }
        @Suppress("UNCHECKED_CAST") val originalEnd = endedField.get(worker) as (NativeGallerySourceRun) -> Unit
        var ended = java.util.concurrent.CountDownLatch(1)
        val release = java.util.concurrent.CountDownLatch(1)
        lateinit var catalog: NativeGalleryAlbumCatalog
        lateinit var selected: NativeGalleryAlbumSelection
        lateinit var job: PhotoSourceJob
        lateinit var originalAcceptance: JsonObject
        lateinit var cipher: Map<String, List<Byte>>
        init {
            try {
                runtime.attachPermissionHost(host) { throw AssertionError("No implicit permission request") }; activity.start().resume()
                fun echo() {
                    if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(drain().single(), now), pcPeer)
                    val packet = desktop.packet(); desktop.markSent(packet)
                    runtime.observeControls(DeviceFileControlEnvelope.create(packet, now), now)
                    if (runtime.sendControls(now)) desktop.observeRemote(DeviceFileControlEnvelope.validate(drain().single(), now), pcPeer)
                }
                echo(); runtime.configureFromAuthenticatedCommand(runtime.savedPolicy(), true, setOf(GallerySourceKind.CAMERA)); echo()
                catalog = runtime.discoverSelectable()
                val page = catalog.page()
                selected = catalog.select(page.string("catalog_id"), page["albums"]!!.jsonArray.single().jsonObject.string("album_id"), true)
                watchEnd()
                val normal = runtime.beginSyncRun(selected); awaitEnd()
                job = normal.preparation.snapshotJob()!!
                runtime.sendSyncRunOffer(normal, channel::send, now)
                val offer = drain().single(); val manifest = DeviceFileOfferEnvelope.validate(offer, identity.deviceId, peer.peerId, now)
                runtime.observeAcceptance(TelefonNachrichten.message(DeviceFileAcceptanceEnvelope.KIND, buildJsonObject {
                    put("format", 1); put("offer_id", offer.string("message_id")); put("transfer_id", manifest.transferId)
                    put("manifest_sha256", manifest.fingerprint); put("acceptance_sha256", "c".repeat(64))
                    put("permission_epoch", runtime.currentRequest()!!.receiver.permissionEpoch); put("destination_token", "e".repeat(64))
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
        fun awaitEnd() { assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
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
        fun assertOriginal() {
            inspect { assertEquals(listOf(job), it.jobs()); assertEquals(originalAcceptance, it.remoteAcceptance(job)!!.record); assertNull(it.remoteSaved(job)) }
            assertEquals(cipher, File(root, "photo-source-" + job.id).listFiles()!!.associate { it.name to it.readBytes().toList() })
            assertEquals("hello", File(f.root, "source.bin").readText())
        }
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
                        runtime.observeAcceptance(acceptance,{now}); runtime.observeAcceptance(acceptance,{now})
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
                        runtime.receiveChunkRequest(chunkRequest,channel::send,{now})
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
                        runtime.observeRemoteSaved(savedMessage,{now})
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
