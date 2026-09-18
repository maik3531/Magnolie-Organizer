package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

// Deliberately separate from the ordinary status/battery collector. Never stored.
internal interface DeviceIdentifierSource {
    val sdk: Int
    val phonePermission: Boolean
    val statePermission: Boolean
    fun defaultVoiceSubscription(): Int
    fun phoneNumber(subscription: Int): String?
    fun serial(): String?
    fun imei(subscription: Int): String?
}

internal class AndroidDeviceIdentifierSource(private val context: Context) : DeviceIdentifierSource {
    override val sdk get() = Build.VERSION.SDK_INT
    override val phonePermission get() = context.checkSelfPermission(Manifest.permission.READ_PHONE_NUMBERS) == PackageManager.PERMISSION_GRANTED
    override val statePermission get() = context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED
    override fun defaultVoiceSubscription() = SubscriptionManager.getDefaultVoiceSubscriptionId()
    @Suppress("DEPRECATION", "MissingPermission")
    override fun phoneNumber(subscription: Int): String? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
        context.getSystemService(SubscriptionManager::class.java)?.getPhoneNumber(subscription)
        else context.getSystemService(TelephonyManager::class.java)?.createForSubscriptionId(subscription)?.line1Number
    @Suppress("MissingPermission")
    override fun serial(): String? = Build.getSerial()
    @Suppress("MissingPermission")
    override fun imei(subscription: Int): String? =
        context.getSystemService(TelephonyManager::class.java)?.createForSubscriptionId(subscription)?.imei
}

internal object DeviceIdentifiers {
    fun collect(source: DeviceIdentifierSource, shared: Boolean): JsonObject {
        fun field(state: String, value: String = "") = buildJsonObject {
            put("status", JsonPrimitive(state)); put("value", JsonPrimitive(value))
        }
        fun read(maximum: Int, digits: Boolean = false, block: () -> String?): JsonObject = try {
            val value = block().orEmpty()
            if (value.isBlank() || value.equals(Build.UNKNOWN, true) || value.length > maximum ||
                value.any(Char::isISOControl) || digits && value.any { it !in '0'..'9' }) field("unavailable")
            else field("available", value)
        } catch (_: SecurityException) { field("permission_missing") }
          catch (_: RuntimeException) { field("unavailable") }
        if (!shared) return buildJsonObject {
            for (name in listOf("phone_number", "serial", "imei")) put(name, field("not_shared"))
        }
        val subscription = try { source.defaultVoiceSubscription() } catch (_: RuntimeException) { -1 }
        // No first-SIM fallback. Android 29+ restricts hardware IDs for ordinary apps.
        return buildJsonObject {
            put("phone_number", when {
                !source.phonePermission -> field("permission_missing")
                subscription < 0 || subscription == Int.MAX_VALUE -> field("no_subscription")
                else -> read(64) { source.phoneNumber(subscription) }
            })
            put("serial", when {
                source.sdk >= 29 -> field("os_restricted")
                !source.statePermission -> field("permission_missing")
                else -> read(128) { source.serial() }
            })
            put("imei", when {
                source.sdk >= 29 -> field("os_restricted")
                !source.statePermission -> field("permission_missing")
                subscription < 0 || subscription == Int.MAX_VALUE -> field("no_subscription")
                else -> read(32, true) { source.imei(subscription) }
            })
        }
    }
}
