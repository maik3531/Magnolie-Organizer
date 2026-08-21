package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Notification
import android.app.PendingIntent
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.provider.Telephony
import android.telecom.TelecomManager
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.util.UUID

object TelefonModulStatus {
    fun telephony(context: Context): Boolean = context.packageManager.hasSystemFeature(PackageManager.FEATURE_TELEPHONY)
    fun dialResolvable(context: Context): Boolean = telephony(context) &&
        context.getSystemService(TelecomManager::class.java) != null

    fun dialPermissions(context: Context): Boolean =
        context.checkSelfPermission(Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED &&
        context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED

    fun dialRequest(context: Context, storage: TelefonAblage = TelefonAblage.get(context)): Boolean =
        storage.dialRequestEnabled() && dialResolvable(context) && dialPermissions(context)

    fun notifications(context: Context, storage: TelefonAblage = TelefonAblage.get(context)): Boolean =
        storage.notificationsEnabled() && storage.selectedPackages().isNotEmpty() && notificationAccess(context)

    fun notificationAccess(context: Context): Boolean =
        Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners").orEmpty()
            .split(':').mapNotNull(ComponentName::unflattenFromString).any { it.packageName == context.packageName }
}

object Waehlauftrag {
    fun submit(context: Context, body: JsonObject): Pair<String, String> {
        val storage = TelefonAblage.get(context)
        if (!storage.dialRequestEnabled()) return "failed" to "not_granted"
        if (!TelefonModulStatus.dialPermissions(context))
            return "failed" to "permission_missing"
        if (!TelefonModulStatus.telephony(context)) return "failed" to "no_telephony"
        val clientRef = body.string("client_ref")
        val number = body.string("to")
        if (!Regex("\\+[0-9]{3,15}").matches(number)) return "failed" to "invalid_destination"
        if (!TelefonEffekte(context).firstEvent("dial:$clientRef")) return "submitted" to "none"
        // For direct calls, call_ref is canonically the dial command's client_ref.
        TelefonWerk.get(context).beginOutgoing(number, clientRef)
        return runCatching {
            if (context.checkSelfPermission(Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED ||
                context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED)
                return TelefonWerk.get(context).failOutgoing(clientRef, "permission_missing")
            context.getSystemService(TelecomManager::class.java)
                ?.placeCall(Uri.fromParts("tel", number, null), android.os.Bundle())
                ?: return TelefonWerk.get(context).failOutgoing(clientRef, "dial_unavailable")
            "submitted" to "none"
        }.getOrElse { error -> TelefonWerk.get(context).failOutgoing(clientRef,
            if (error is SecurityException) "permission_missing" else "os_restricted") }
    }
}

class AusgewaehlteBenachrichtigungen : NotificationListenerService() {
    private val startupScope = kotlinx.coroutines.CoroutineScope(
        kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Default)
    override fun onNotificationPosted(sbn: StatusBarNotification) { nachStartup(sbn, "posted") }
    override fun onNotificationRemoved(sbn: StatusBarNotification) { nachStartup(sbn, "removed") }

    override fun onDestroy() {
        startupScope.cancel()
        super.onDestroy()
    }

    private fun nachStartup(sbn: StatusBarNotification, event: String) {
        startupScope.launch {
            if ((application as io.gitlab.maik3531.magnolienotes.MagnolieApp).awaitReady()) publish(sbn, event)
        }
    }

    private fun publish(sbn: StatusBarNotification, event: String) {
        val storage = TelefonAblage.get(this)
        val notification = sbn.notification
        if (!TelefonModulStatus.notifications(this, storage) || sbn.packageName !in storage.selectedPackages() ||
            notification.category != Notification.CATEGORY_MESSAGE || notification.flags and
            (Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_ONGOING_EVENT) != 0) return
        val messages = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification)?.messages ?: return
        val title = if (event == "removed") "" else clean(notification.extras.getCharSequence(Notification.EXTRA_TITLE), 500)
        val text = if (event == "removed") "" else clean(messages.lastOrNull()?.text ?: notification.extras.getCharSequence(Notification.EXTRA_TEXT), 5000)
        val key = "notification:$event:${sbn.key}:${sbn.postTime}"
        if (!TelefonEffekte(this).firstEvent(key)) return
        val label = runCatching { packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString() }
            .getOrDefault("")
        TelefonWerk.get(this).publish("selected_notifications_readonly.event", buildJsonObject {
            put("notification_id", JsonPrimitive(UUID.nameUUIDFromBytes(sbn.key.toByteArray()).toString()))
            put("event", JsonPrimitive(event)); put("package", JsonPrimitive(sbn.packageName))
            put("app_label", JsonPrimitive(clean(label, 80))); put("posted_ms", JsonPrimitive(sbn.postTime))
            put("title", JsonPrimitive(title)); put("text", JsonPrimitive(text))
            put("is_default_sms_app", JsonPrimitive(Telephony.Sms.getDefaultSmsPackage(this@AusgewaehlteBenachrichtigungen) == sbn.packageName))
        }, 86_400_000)
    }

    private fun clean(value: CharSequence?, max: Int): String = value?.toString().orEmpty()
        .filter { it == '\n' || it == '\t' || !it.isISOControl() }.take(max)
}
