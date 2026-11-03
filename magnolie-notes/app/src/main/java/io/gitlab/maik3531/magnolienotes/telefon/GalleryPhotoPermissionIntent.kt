package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import io.gitlab.maik3531.magnolienotes.MainActivity

/** Explicit user-tap route. The URI contains an opaque process-local action
 * token, not source paths, grants, receiver identities or restored OS tickets.
 */
internal object GalleryPhotoPermissionIntent {
    const val ACTION = "io.gitlab.maik3531.magnolienotes.action.GALLERY_READ_PERMISSION"
    private const val PREFIX = "magnolie-native://gallery-read-permission/"
    private const val CHANNEL = "magnolie-phone-file-permission"
    private const val NOTIFICATION = 0x4d46494c

    fun create(context: Context, action: NativeGalleryPermissionAction): Intent {
        if (!DeviceFileControl.hash(action.token)) DeviceFileControl.fail("gallery_permission_action_unknown")
        return Intent(context, MainActivity::class.java).setAction(ACTION).setData(Uri.parse(PREFIX + action.token))
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    }

    fun token(intent: Intent?): String? {
        if (intent?.action != ACTION) return null
        val value = intent.dataString ?: return null
        if (value.length != PREFIX.length + 64 || !value.startsWith(PREFIX)) return null
        val token = value.removePrefix(PREFIX)
        return token.takeIf { DeviceFileControl.hash(it) && value == PREFIX + it }
    }

    fun pendingIntent(context: Context, action: NativeGalleryPermissionAction): PendingIntent =
        PendingIntent.getActivity(context, 0, create(context, action), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_ONE_SHOT)

    /** No background Activity start, full-screen intent or automatic notification
     * permission request. False means the native controller must report that
     * foreground user interaction is still required, not a delivered dialog.
     */
    fun post(context: Context, action: NativeGalleryPermissionAction): Boolean {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return false
        if (Build.VERSION.SDK_INT >= 24 && !manager.areNotificationsEnabled()) return false
        val video = action.mediaType == GalleryMediaType.VIDEO
        val channel = if (video) CHANNEL + "-video" else CHANNEL
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(NotificationChannel(channel,
            if (video) "Videozugriff bestätigen" else "Fotozugriff bestätigen", NotificationManager.IMPORTANCE_DEFAULT))
        val notification = NotificationCompat.Builder(context, channel).setSmallIcon(android.R.drawable.ic_menu_gallery)
            .setContentTitle(if (video) "Videosynchronisation: Zugriff bestätigen" else "Fotosynchronisation: Zugriff bestätigen")
            .setContentText(if (video) "Notes öffnen, um den Zugriff auf die ausgewählten Videoquellen zu bestätigen."
                else "Notes öffnen, um den Zugriff auf die ausgewählten Fotoquellen zu bestätigen.")
            .setContentIntent(pendingIntent(context, action)).setAutoCancel(true).setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setCategory(NotificationCompat.CATEGORY_STATUS).build()
        manager.notify(if (video) NOTIFICATION + 1 else NOTIFICATION, notification)
        return true
    }
}
