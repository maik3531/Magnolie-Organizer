package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import java.util.Collections
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

object TelefonEntdeckung {
    fun suchen(context: Context, waitMs: Long = 3000, peerId: String? = null): List<GefundenerDesktop> {
        val nsd = context.applicationContext.getSystemService(Context.NSD_SERVICE) as? NsdManager ?: return emptyList()
        val found = Collections.synchronizedList(mutableListOf<GefundenerDesktop>())
        val done = CountDownLatch(1)
        val resolving = AtomicInteger(0)
        val listener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String?, errorCode: Int) = done.countDown()
            override fun onStopDiscoveryFailed(serviceType: String?, errorCode: Int) = done.countDown()
            override fun onDiscoveryStarted(serviceType: String?) = Unit
            override fun onDiscoveryStopped(serviceType: String?) = done.countDown()
            override fun onServiceLost(serviceInfo: NsdServiceInfo?) = Unit
            override fun onServiceFound(serviceInfo: NsdServiceInfo?) {
                val service = serviceInfo ?: return
                resolving.incrementAndGet()
                @Suppress("DEPRECATION")
                nsd.resolveService(service, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(serviceInfo: NsdServiceInfo?, errorCode: Int) { resolving.decrementAndGet() }
                    override fun onServiceResolved(serviceInfo: NsdServiceInfo?) {
                        resolving.decrementAndGet()
                        val resolved = serviceInfo ?: return
                        fun attribute(name: String) = resolved.attributes?.get(name)?.toString(Charsets.UTF_8).orEmpty()
                        val id = attribute("id")
                        val token = attribute("token")
                        val pairing = peerId == null
                        if (attribute("v") != "1" || attribute("role") != "desktop" ||
                            (pairing && attribute("pair") != "1") || (!pairing && id != peerId) ||
                            runCatching { UUID.fromString(id) }.isFailure || (pairing && runCatching { TelefonKrypto.b64(token, 16) }.isFailure) ||
                            resolved.port != TelefonParameter.PORT) return
                        found += GefundenerDesktop(id.lowercase(), attribute("name").take(60),
                            resolved.host?.hostAddress.orEmpty(), token)
                        done.countDown()
                    }
                })
            }
        }
        var started = false
        return try {
            nsd.discoverServices(TelefonParameter.NSD_TYP, NsdManager.PROTOCOL_DNS_SD, listener)
            started = true
            done.await(waitMs, TimeUnit.MILLISECONDS)
            var waited = 0
            while (resolving.get() > 0 && waited < 2000) { Thread.sleep(50); waited += 50 }
            synchronized(found) { found.distinctBy { it.deviceId } }
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            synchronized(found) { found.distinctBy { it.deviceId } }
        } catch (_: Exception) { synchronized(found) { found.distinctBy { it.deviceId } } }
        finally { if (started) runCatching { nsd.stopServiceDiscovery(listener) } }
    }
}
