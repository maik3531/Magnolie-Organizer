package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import java.time.Duration
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class AndroidReadOnlyPhotoTreesTest {
    @Test fun actualResolverBoundaryRequestsReadOnlyAndKeepsSharedBackupRights() {
        // Robolectric resolver grants are synthetic; this is not physical SAF
        // user-consent acceptance or access to a personal Android provider.
        val context = RuntimeEnvironment.getApplication()
        val resolver = context.contentResolver
        val trees = AndroidReadOnlyPhotoTrees(context)
        val backup = DocumentsContract.buildTreeDocumentUri("fixture.documents", "existing-backup")
        val photos = DocumentsContract.buildTreeDocumentUri("fixture.documents", "primary:Pictures/Camera")
        resolver.takePersistableUriPermission(backup, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        assertNull(trees.readGrantToken(photos.toString()))
        assertEquals(photos.toString(), trees.canonicalTree(photos.toString()))
        trees.persistRead(photos.toString())
        val permissions = resolver.persistedUriPermissions
        assertTrue(permissions.single { it.uri == photos }.isReadPermission)
        assertFalse(permissions.single { it.uri == photos }.isWritePermission)
        assertTrue(permissions.single { it.uri == backup }.isReadPermission && permissions.single { it.uri == backup }.isWritePermission)
        val first = requireNotNull(trees.readGrantToken(photos.toString()))
        assertEquals(64, first.length)
        resolver.releasePersistableUriPermission(photos, Intent.FLAG_GRANT_READ_URI_PERMISSION) // Synthetic external OS revocation.
        assertNull(trees.readGrantToken(photos.toString()))
        ShadowSystemClock.advanceBy(Duration.ofSeconds(1))
        trees.persistRead(photos.toString())
        assertNotEquals(first, trees.readGrantToken(photos.toString()))
        assertTrue(resolver.persistedUriPermissions.single { it.uri == backup }.isWritePermission)
    }

    @Test fun nonTreeAliasesQueriesFragmentsAndWriteOnlyGrantsNeverBecomePhotoReadAuthority() {
        val context = RuntimeEnvironment.getApplication()
        val resolver = context.contentResolver
        val trees = AndroidReadOnlyPhotoTrees(context)
        val tree = Uri.parse("content://fixture.documents/tree/selected")
        resolver.takePersistableUriPermission(tree, Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        assertNull(trees.readGrantToken(tree.toString()))
        for (invalid in listOf("file:///Pictures", "https://fixture.invalid/tree/selected",
            "content://fixture.documents/document/selected", "content://fixture.documents/tree/selected/document/selected",
            "content://fixture.documents/tree/selected?other=1", "content://fixture.documents/tree/selected#other")) {
            assertThrows(Exception::class.java) { trees.canonicalTree(invalid) }
            assertNull(trees.readGrantToken(invalid))
        }
        assertEquals(1, resolver.persistedUriPermissions.size)
        assertFalse(resolver.persistedUriPermissions.single().isReadPermission)
    }
}
