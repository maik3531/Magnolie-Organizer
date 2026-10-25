package io.gitlab.maik3531.magnolienotes.ui

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.ConcurrentHashMap
import kotlin.coroutines.resume

internal object DruckerEinstellungen {
    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences("magnolie_print_view", Context.MODE_PRIVATE)
    fun automatisch(context: Context) = prefs(context).getBoolean("only_available_wifi_printer", true)
    fun automatisch(context: Context, value: Boolean) { check(prefs(context).edit().putBoolean("only_available_wifi_printer", value).commit()) }
}

/** Foreground-only IPP discovery. An announcement alone is not a reachability result. */
@Suppress("DEPRECATION") // Legacy resolver is needed on supported Android 8–12 devices.
internal class DruckerSuche(context: Context) : AutoCloseable {
    private val manager = context.applicationContext.getSystemService(NsdManager::class.java)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val pending = Channel<NsdServiceInfo>(64)
    private val candidates = ConcurrentHashMap<String, Pair<InetAddress, Int>>()
    private val announced = ConcurrentHashMap.newKeySet<String>()
    private val listeners = mutableListOf<NsdManager.DiscoveryListener>()
    private val found = MutableStateFlow(false)
    private val probeLock = Mutex()
    private val stateLock = Any()
    val erreichbar: StateFlow<Boolean> = found
    @Volatile private var closed = false
    private fun key(info: NsdServiceInfo) = info.serviceType.trimEnd('.') + "\u0000" + info.serviceName

    fun starten() {
        val nsd = manager ?: return
        scope.launch {
            for (info in pending) {
                if (key(info) !in announced) continue
                val endpoint = withTimeoutOrNull(5_000) {
                    suspendCancellableCoroutine<Pair<InetAddress, Int>?> { continuation ->
                        try {
                            nsd.resolveService(info, object : NsdManager.ResolveListener {
                                override fun onResolveFailed(service: NsdServiceInfo, code: Int) { if (continuation.isActive) continuation.resume(null) }
                                override fun onServiceResolved(service: NsdServiceInfo) {
                                    if (continuation.isActive) continuation.resume(service.host?.let { it to service.port })
                                }
                            })
                        } catch (_: RuntimeException) { if (continuation.isActive) continuation.resume(null) }
                    }
                }
                if (endpoint != null && endpoint.second in 1..65535 && key(info) in announced && !closed) candidates[key(info)] = endpoint
                pruefen()
            }
        }
        scope.launch { while (isActive) { delay(15_000); pruefen() } }
        for (type in listOf("_ipp._tcp.", "_ipps._tcp.")) {
            val listener = object : NsdManager.DiscoveryListener {
                override fun onDiscoveryStarted(serviceType: String) {}
                override fun onDiscoveryStopped(serviceType: String) {}
                override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) { runCatching { nsd.stopServiceDiscovery(this) } }
                override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
                override fun onServiceFound(info: NsdServiceInfo) {
                    if (!closed && announced.size < 64 && announced.add(key(info))) pending.trySend(info)
                }
                override fun onServiceLost(info: NsdServiceInfo) {
                    announced.remove(key(info)); candidates.remove(key(info))
                    scope.launch { pruefen() }
                }
            }
            listeners += listener
            runCatching { nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, listener) }
        }
    }

    private suspend fun pruefen() = probeLock.withLock {
        var reachable = false
        for ((id, endpoint) in candidates.entries.take(64)) {
            currentCoroutineContext().ensureActive()
            val available = runCatching { Socket().use { it.connect(InetSocketAddress(endpoint.first, endpoint.second), 1000) }; true }.getOrDefault(false)
            if (available && candidates[id] == endpoint && id in announced) { reachable = true; break }
        }
        currentCoroutineContext().ensureActive()
        synchronized(stateLock) { if (!closed) found.value = reachable }
    }

    override fun close() {
        synchronized(stateLock) { closed = true; found.value = false }
        listeners.forEach { listener -> runCatching { manager?.stopServiceDiscovery(listener) } }
        listeners.clear(); announced.clear(); candidates.clear(); pending.close(); scope.cancel(); found.value = false
    }
}
