package io.gitlab.maik3531.magnolienotes.telefon

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.StatFs
import android.os.SystemClock
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

object DeviceStatusCollector {
    fun clean(text: String?, maxCodepoints: Int): String {
        val filtered = text.orEmpty().filterNot(Char::isISOControl)
        val end = filtered.offsetByCodePoints(0, minOf(maxCodepoints, filtered.codePointCount(0, filtered.length)))
        return filtered.substring(0, end)
    }

    fun battery(level: Int, scale: Int): Int =
        if (level < 0 || scale <= 0) -1 else ((level.toLong() * 100) / scale).toInt().coerceIn(0, 100)

    fun charging(status: Int): String = when (status) {
        BatteryManager.BATTERY_STATUS_CHARGING -> "charging"
        BatteryManager.BATTERY_STATUS_FULL -> "full"
        BatteryManager.BATTERY_STATUS_DISCHARGING -> "discharging"
        BatteryManager.BATTERY_STATUS_NOT_CHARGING -> "not_charging"
        else -> "unknown"
    }

    fun powerSource(source: Int): String = when (source) {
        BatteryManager.BATTERY_PLUGGED_AC -> "ac"
        BatteryManager.BATTERY_PLUGGED_USB -> "usb"
        BatteryManager.BATTERY_PLUGGED_WIRELESS -> "wireless"
        BatteryManager.BATTERY_PLUGGED_DOCK -> "dock"
        0 -> "none"
        else -> "unknown"
    }

    fun collect(context: Context, requestId: String, now: Long = System.currentTimeMillis()): DeviceStatus {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val storage = StatFs(context.filesDir.absolutePath)
        val memory = ActivityManager.MemoryInfo().also {
            context.getSystemService(ActivityManager::class.java)?.getMemoryInfo(it)
        }
        val connectivity = context.getSystemService(ConnectivityManager::class.java)
        val capabilities = connectivity?.getNetworkCapabilities(connectivity.activeNetwork)
        val transport = when {
            capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true -> "wifi"
            capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true -> "cellular"
            capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) == true -> "ethernet"
            capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true -> "vpn"
            capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH) == true -> "bluetooth"
            else -> "none"
        }
        return DeviceStatus(
            requestId = requestId,
            model = clean(Build.MODEL, 80),
            manufacturer = clean(Build.MANUFACTURER, 80),
            osVersion = clean(Build.VERSION.RELEASE, 40),
            batteryPercent = battery(
                intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1,
                intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
            ),
            charging = charging(intent?.getIntExtra(BatteryManager.EXTRA_STATUS, 1) ?: 1),
            capturedMs = now,
            sdkInt = Build.VERSION.SDK_INT,
            batteryTemperatureDeciC = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1,
            powerSource = powerSource(intent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1),
            storageTotalBytes = storage.totalBytes,
            storageAvailableBytes = storage.availableBytes,
            memoryTotalBytes = memory.totalMem,
            memoryAvailableBytes = memory.availMem,
            uptimeMs = SystemClock.elapsedRealtime(),
            networkTransport = transport,
            networkValidated = capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true,
            networkMetered = connectivity?.isActiveNetworkMetered ?: false
        )
    }

    fun body(status: DeviceStatus, version: Int = 1): JsonObject = buildJsonObject {
        put("request_id", JsonPrimitive(status.requestId))
        put("model", JsonPrimitive(clean(status.model, 80)))
        put("manufacturer", JsonPrimitive(clean(status.manufacturer, 80)))
        put("os_name", JsonPrimitive("Android"))
        put("os_version", JsonPrimitive(clean(status.osVersion, 40)))
        put("battery_percent", JsonPrimitive(status.batteryPercent.takeIf { it in 0..100 } ?: -1))
        put("charging", JsonPrimitive(status.charging.takeIf {
            it in setOf("charging", "full", "discharging", "not_charging", "unknown")
        } ?: "unknown"))
        if (version >= 2) {
            put("sdk_int", JsonPrimitive(status.sdkInt.coerceIn(1, 1000)))
            put("battery_temperature_deci_c", JsonPrimitive(status.batteryTemperatureDeciC.coerceIn(-1, 2000)))
            put("power_source", JsonPrimitive(status.powerSource.takeIf {
                it in setOf("ac", "usb", "wireless", "dock", "none", "unknown")
            } ?: "unknown"))
            put("storage_total_bytes", JsonPrimitive(status.storageTotalBytes.coerceAtLeast(-1)))
            put("storage_available_bytes", JsonPrimitive(status.storageAvailableBytes.coerceAtLeast(-1)))
            put("memory_total_bytes", JsonPrimitive(status.memoryTotalBytes.coerceAtLeast(-1)))
            put("memory_available_bytes", JsonPrimitive(status.memoryAvailableBytes.coerceAtLeast(-1)))
            put("uptime_ms", JsonPrimitive(status.uptimeMs.coerceAtLeast(-1)))
            put("network_transport", JsonPrimitive(status.networkTransport.takeIf {
                it in setOf("wifi", "cellular", "ethernet", "vpn", "bluetooth", "none")
            } ?: "none"))
            put("network_validated", JsonPrimitive(status.networkValidated))
            put("network_metered", JsonPrimitive(status.networkMetered))
        }
        if (version >= 3) {
            put("app_version", JsonPrimitive(clean(status.appVersion, 80).ifEmpty { "unknown" }))
        }
        put("captured_ms", JsonPrimitive(status.capturedMs))
    }
}
