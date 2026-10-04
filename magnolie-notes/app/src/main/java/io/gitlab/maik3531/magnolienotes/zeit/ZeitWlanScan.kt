package io.gitlab.maik3531.magnolienotes.zeit

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.SystemClock
import android.provider.Settings

/** Reads visible scan observations only; never associates, authenticates or saves credentials. */
object ZeitWlanScan {
    data class Observation(val ssid: String, val observedMs: Long)
    private var lastRequestElapsed: Long? = null

    fun permissionGranted(context: Context): Boolean =
        context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    @Suppress("DEPRECATION")
    fun locationEnabled(context: Context): Boolean = if (Build.VERSION.SDK_INT >= 28)
            context.getSystemService(LocationManager::class.java)?.isLocationEnabled == true
        else Settings.Secure.getInt(context.contentResolver, Settings.Secure.LOCATION_MODE,
            Settings.Secure.LOCATION_MODE_OFF) != Settings.Secure.LOCATION_MODE_OFF

    @Suppress("DEPRECATION")
    fun ready(context: Context): Boolean {
        if (!permissionGranted(context) || !locationEnabled(context)) return false
        val wifi = context.applicationContext.getSystemService(WifiManager::class.java) ?: return false
        return wifi.isWifiEnabled || wifi.isScanAlwaysAvailable
    }

    /** Android may still throttle/deny the request; cached results keep their original age. */
    @Synchronized
    @Suppress("DEPRECATION", "MissingPermission")
    fun request(context: Context, elapsed: Long = SystemClock.elapsedRealtime()): Boolean {
        if (!ready(context)) return false
        val previous = lastRequestElapsed
        if (previous != null && elapsed >= previous && elapsed - previous < 60000) return false
        lastRequestElapsed = elapsed
        return try { context.applicationContext.getSystemService(WifiManager::class.java)?.startScan() == true }
        catch (_: SecurityException) { false }
    }

    @Suppress("DEPRECATION", "MissingPermission")
    fun observations(context: Context, now: Long = System.currentTimeMillis(),
                     elapsed: Long = SystemClock.elapsedRealtime()): List<Observation> {
        if (!ready(context)) return emptyList()
        val results = try { context.applicationContext.getSystemService(WifiManager::class.java)?.scanResults.orEmpty() }
            catch (_: SecurityException) { return emptyList() }
        return results.take(1024).mapNotNull { result -> observation(result.SSID.orEmpty(), result.timestamp, now, elapsed) }
            .groupBy { it.ssid }.map { (_, values) -> values.maxBy { it.observedMs } }.sortedBy { it.ssid }
    }

    internal fun observation(ssid: String, timestampMicros: Long, now: Long, elapsed: Long): Observation? {
        if (ssid.isEmpty() || timestampMicros <= 0 || elapsed !in 0..Long.MAX_VALUE / 1000 || now < 0) return null
        if (!Charsets.UTF_8.newEncoder().canEncode(ssid) || ssid.toByteArray(Charsets.UTF_8).size > 32) return null
        val age = elapsed * 1000 - timestampMicros
        if (age !in 0..120000000L) return null
        return (now - age / 1000).takeIf { it >= 0 }?.let { Observation(ssid, it) }
    }
}
