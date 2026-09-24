package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import java.net.InetAddress

@Implements(NsdManager::class)
class ComputerDiscoveryShadow {
    companion object { var services = emptyList<NsdServiceInfo>(); var stops = 0 }
    @Implementation fun discoverServices(type: String, protocol: Int, listener: NsdManager.DiscoveryListener) {
        services.forEach { listener.onServiceFound(it) }
    }
    @Implementation fun resolveService(service: NsdServiceInfo, listener: NsdManager.ResolveListener) {
        listener.onServiceResolved(service)
    }
    @Implementation fun stopServiceDiscovery(listener: NsdManager.DiscoveryListener) { stops++ }
}

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE, application = Application::class, shadows = [ComputerDiscoveryShadow::class])
class TelefonComputerDiscoveryTest {
    @Test fun knownComputersReconnectWithoutOpeningPairingAndUnknownInvitationsStaySeparate() {
        val home = "11111111-1111-4111-8111-111111111111"
        val office = "22222222-2222-4222-8222-222222222222"
        val unknown = "33333333-3333-4333-8333-333333333333"
        fun service(id: String, pairing: Boolean) = NsdServiceInfo().apply {
            serviceName = "Computer"; serviceType = TelefonParameter.NSD_TYP
            host = InetAddress.getByName("192.0.2.1"); port = TelefonParameter.PORT
            setAttribute("id", id); setAttribute("name", "Computer"); setAttribute("role", "desktop"); setAttribute("v", "1")
            setAttribute("pair", if (pairing) "1" else "0")
            if (pairing) setAttribute("token", TelefonKrypto.b64(ByteArray(16)))
        }
        ComputerDiscoveryShadow.services = listOf(service(unknown, true), service(home, false), service(office, false))
        ComputerDiscoveryShadow.stops = 0
        try {
            val context = ApplicationProvider.getApplicationContext<Context>()
            val known = TelefonEntdeckung.suchen(context, waitMs = 1, peerId = home, pairedIds = setOf(home, office))
            assertEquals(setOf(home, office), known.map { it.deviceId }.toSet())
            assertEquals(listOf(unknown), TelefonEntdeckung.suchen(context, waitMs = 1).map { it.deviceId })
            assertEquals(2, ComputerDiscoveryShadow.stops)
        } finally { ComputerDiscoveryShadow.services = emptyList() }
    }
}
