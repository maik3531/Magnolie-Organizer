package io.gitlab.maik3531.magnolietabletbeta

import android.Manifest
import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

internal fun notificationPermission(context: Context): Boolean =
    (Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
        context.getSystemService(NotificationManager::class.java).areNotificationsEnabled()

internal fun eligibleAlarms(value: JSONObject, now: Long): List<JSONObject> {
    if (!value.optBoolean("enabled")) return emptyList()
    val alarms = value.optJSONArray("alarms") ?: JSONArray()
    val delivered = value.optJSONObject("delivered") ?: JSONObject()
    return (0 until alarms.length()).map { alarms.getJSONObject(it) }.filter {
        (!it.getBoolean("custom") || value.optBoolean("customEnabled")) &&
            !delivered.has(it.getString("id")) && it.getLong("at") >= now - 24 * 60 * 60 * 1000
    }.sortedBy { it.getLong("at") }
}

internal fun scheduleReminders(context: Context, value: JSONObject) {
    val manager = context.getSystemService(AlarmManager::class.java)
    val pending = PendingIntent.getBroadcast(context, 1,
        Intent(context, ReminderReceiver::class.java).setAction("tablet.beta.REMIND"),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    manager.cancel(pending)
    if (!notificationPermission(context)) return
    val now = System.currentTimeMillis()
    val next = eligibleAlarms(value, now).firstOrNull() ?: return
    manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, maxOf(now + 1000, next.getLong("at")), pending)
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        AndroidStore.io.execute {
            try {
                val vault = AndroidStore.vault(context)
                val value = vault.read() ?: return@execute
                val manager = context.getSystemService(NotificationManager::class.java)
                manager.createNotificationChannel(NotificationChannel("tablet-beta-reminders",
                    context.getString(R.string.notifications), NotificationManager.IMPORTANCE_DEFAULT))
                if (notificationPermission(context)) {
                    val now = System.currentTimeMillis()
                    val delivered = value.optJSONObject("delivered") ?: JSONObject()
                    for (alarm in eligibleAlarms(value, now).filter { it.getLong("at") <= now }.take(20)) {
                        val key = alarm.getString("id")
                        val digest = MessageDigest.getInstance("SHA-256").digest(key.toByteArray())
                        val id = java.nio.ByteBuffer.wrap(digest).int and Int.MAX_VALUE
                        val open = PendingIntent.getActivity(context, id, Intent(context, MainActivity::class.java),
                            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                        val notification = Notification.Builder(context, "tablet-beta-reminders")
                            .setSmallIcon(R.drawable.beta_icon).setContentTitle(context.getString(R.string.notifications))
                            .setContentText(alarm.getString("title")).setContentIntent(open).setAutoCancel(true)
                            .setVisibility(Notification.VISIBILITY_PRIVATE)
                            .setPublicVersion(Notification.Builder(context, "tablet-beta-reminders")
                                .setSmallIcon(R.drawable.beta_icon).setContentTitle("Magnolie Organizer Android Tablet Beta").build())
                            .build()
                        // Stable notification IDs make a crash between delivery and receipt idempotent.
                        manager.notify(id, notification)
                        delivered.put(key, now)
                    }
                    value.put("delivered", delivered)
                    vault.write(value)
                }
                scheduleReminders(context, value)
            } catch (_: Exception) {
                // No plaintext recovery or empty state. Surface a non-sensitive failure when permitted.
                val manager = context.getSystemService(NotificationManager::class.java)
                if (notificationPermission(context)) {
                    manager.createNotificationChannel(NotificationChannel("tablet-beta-errors",
                        context.getString(R.string.failed), NotificationManager.IMPORTANCE_DEFAULT))
                    manager.notify(0, Notification.Builder(context, "tablet-beta-errors")
                        .setSmallIcon(R.drawable.beta_icon).setContentTitle("Magnolie Organizer Android Tablet Beta")
                        .setContentText(context.getString(R.string.save_failed)).build())
                }
            } finally { pending.finish() }
        }
    }
}
