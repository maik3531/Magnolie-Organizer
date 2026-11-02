package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class GalleryPhotoPermissionIntentTest {
    @Test fun distinctImmutableOneShotTapIntentsCannotUpdateAnOldSourceAction() {
        val app = RuntimeEnvironment.getApplication()
        val first = NativeGalleryPermissionAction("1".repeat(64)); val second = NativeGalleryPermissionAction("2".repeat(64))
        val old = GalleryPhotoPermissionIntent.pendingIntent(app, first)
        val fresh = GalleryPhotoPermissionIntent.pendingIntent(app, second)
        assertNotEquals(old, fresh)
        val flags = Shadows.shadowOf(old).flags
        assertTrue(flags and PendingIntent.FLAG_IMMUTABLE != 0)
        assertTrue(flags and PendingIntent.FLAG_ONE_SHOT != 0)
        assertEquals(0, flags and PendingIntent.FLAG_UPDATE_CURRENT)
        assertEquals(first.token, GalleryPhotoPermissionIntent.token(Shadows.shadowOf(old).savedIntent))
        assertEquals(second.token, GalleryPhotoPermissionIntent.token(Shadows.shadowOf(fresh).savedIntent))
        assertNull(Shadows.shadowOf(app).nextStartedActivity)
    }

    @Test fun foreignMalformedOrExtraOnlyTokensAreNotNativeActions() {
        val app = RuntimeEnvironment.getApplication(); val valid = GalleryPhotoPermissionIntent.create(app, NativeGalleryPermissionAction("a".repeat(64)))
        assertEquals("a".repeat(64), GalleryPhotoPermissionIntent.token(valid))
        for (intent in listOf(Intent(valid).setAction(Intent.ACTION_VIEW), Intent(valid).setData(null),
            Intent(valid).setData(Uri.parse(valid.dataString + "?grant=true")),
            Intent(valid).setData(Uri.parse(valid.dataString!!.uppercase())),
            Intent(valid).setData(Uri.parse("magnolie-native://gallery-read-permission/" + "a".repeat(16384))),
            Intent().setAction(GalleryPhotoPermissionIntent.ACTION).putExtra("token", "a".repeat(64))))
            assertNull(GalleryPhotoPermissionIntent.token(intent))
        assertFalse(NativeGalleryForeground.acceptsPermissionAction("a".repeat(64)))
    }

    @Test fun deniedNotificationPermissionDoesNotStartAnActivityOrClaimDialogDelivery() {
        val app = RuntimeEnvironment.getApplication()
        Shadows.shadowOf(app).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)
        assertFalse(GalleryPhotoPermissionIntent.post(app, NativeGalleryPermissionAction("1".repeat(64))))
        assertNull(Shadows.shadowOf(app).nextStartedActivity)
    }

    @Test fun permittedNotificationPostsOnlyAPrivateImmutableTapWithoutGrantingOrStartingAnything() {
        val app = RuntimeEnvironment.getApplication()
        Shadows.shadowOf(app).grantPermissions(Manifest.permission.POST_NOTIFICATIONS)
        val action = NativeGalleryPermissionAction("1".repeat(64))
        assertThrows(PhotoFolderScopeError::class.java) { NativeGalleryForeground.postPermissionAction(app, action) }
        assertTrue(GalleryPhotoPermissionIntent.post(app, action)) // UI builder only; no native action is registered.
        val manager = app.getSystemService(android.content.Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
        val notification = Shadows.shadowOf(manager).allNotifications.single()
        assertEquals(android.app.Notification.VISIBILITY_PRIVATE, notification.visibility)
        assertNull(notification.fullScreenIntent)
        assertTrue(notification.contentIntent.isImmutable)
        assertEquals(action.token, GalleryPhotoPermissionIntent.token(Shadows.shadowOf(notification.contentIntent).savedIntent))
        assertFalse(NativeGalleryForeground.acceptsPermissionAction(action.token))
        assertNull(Shadows.shadowOf(app).nextStartedActivity)
    }
}
