package io.gitlab.maik3531.magnolienotes.daten

import android.Manifest
import android.app.Application
import android.location.LocationManager
import android.net.wifi.ScanResult
import android.net.wifi.WifiManager
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.zeit.ZeitWlanScan
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class ZeitWlanScanTest {
    private fun ready(): Application {
        val app = ApplicationProvider.getApplicationContext<Application>()
        shadowOf(app).grantPermissions(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        shadowOf(app.getSystemService(LocationManager::class.java)).setLocationEnabled(true)
        shadowOf(app.getSystemService(WifiManager::class.java)).setWifiState(WifiManager.WIFI_STATE_ENABLED)
        return app
    }

    @Test fun scanTimestampPreservesAgeAndRejectsStaleUnknownFutureAndOversizedSsids() {
        val elapsed = 1000000L
        val now = 1800000000000L
        assertEquals(now - 1234, ZeitWlanScan.observation("Synthetic", (elapsed - 1234) * 1000, now, elapsed)?.observedMs)
        assertNull(ZeitWlanScan.observation("Synthetic", 0, now, elapsed))
        assertNull(ZeitWlanScan.observation("Synthetic", (elapsed + 1) * 1000, now, elapsed))
        assertNull(ZeitWlanScan.observation("Synthetic", (elapsed - 120001) * 1000, now, elapsed))
        assertNull(ZeitWlanScan.observation("界".repeat(11), elapsed * 1000, now, elapsed))
        assertNull(ZeitWlanScan.observation("", elapsed * 1000, now, elapsed))
        assertNull(ZeitWlanScan.observation("Synthetic", 1, now, Long.MAX_VALUE))
    }

    @Test @Suppress("DEPRECATION") fun visibleObservationsDoNotConnectOrSaveNetworksAndCannotBeUsedWithoutPermission() {
        val app = ready()
        val wifi = app.getSystemService(WifiManager::class.java)
        val manager = shadowOf(wifi)
        manager.setScanResults(listOf(
            ScanResult().apply { SSID = "Synthetic"; timestamp = 990000000 },
            ScanResult().apply { SSID = "Synthetic"; timestamp = 999000000 },
            ScanResult().apply { SSID = "Stale"; timestamp = 1000000 }))
        val visible = ZeitWlanScan.observations(app, 1800000000000, 1000000)
        assertEquals(listOf(ZeitWlanScan.Observation("Synthetic", 1799999999000)), visible)
        assertNull(manager.lastEnabledNetwork)
        assertTrue(wifi.configuredNetworks.isEmpty())
        assertFalse(manager.wasConfigurationSaved())
        assertTrue(shadowOf(app.getSystemService(LocationManager::class.java)).requestLocationUpdateListeners.isEmpty())
        shadowOf(app).denyPermissions(Manifest.permission.ACCESS_FINE_LOCATION)
        assertFalse(ZeitWlanScan.ready(app))
        assertTrue(ZeitWlanScan.observations(app, 1800000000000, 1000000).isEmpty())
    }

    @Test fun scanFailuresAreNotFreshObservationsAndRequestsRespectTheirMinimumInterval() {
        val app = ready()
        val manager = shadowOf(app.getSystemService(WifiManager::class.java))
        manager.setStartScanSucceeds(false)
        assertFalse(ZeitWlanScan.request(app, 1000000))
        manager.setStartScanSucceeds(true)
        assertFalse(ZeitWlanScan.request(app, 1059999))
        assertTrue(ZeitWlanScan.request(app, 1060000))
        shadowOf(app.getSystemService(LocationManager::class.java)).setLocationEnabled(false)
        assertFalse(ZeitWlanScan.ready(app))
        assertFalse(ZeitWlanScan.request(app, 1120000))
    }
}
