package io.gitlab.maik3531.magnolienotes.netz

import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Build
import android.os.Handler
import android.os.Looper

/** No consent, pairing or account state is stored here. Re-read the OS grant. */
object LanFreigabe {
    const val RECHT = "android.permission.ACCESS_LOCAL_NETWORK"
    val WARTET: String get() = context?.getString(io.gitlab.maik3531.magnolienotes.R.string.lan_freigabe_wartet)
        ?: "Local network is waiting for permission in Android app settings."
    @Volatile private var context: Context? = null
    private val tor = LanTor { osErlaubt() }
    private val zielWachen = java.util.concurrent.ConcurrentHashMap.newKeySet<LanZielWache>()
    private var monitorGestartet = false

    private fun osErlaubt(): Boolean = !erforderlich() || runCatching {
        context?.checkSelfPermission(RECHT) == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    @Synchronized fun initialisieren(context: Context) {
        this.context = context.applicationContext
        // No background prompts. Android may also kill the process on revocation.
        if (erforderlich() && !monitorGestartet) {
            monitorGestartet = true
            val handler = Handler(Looper.getMainLooper())
            handler.post(object : Runnable {
                override fun run() { erlaubt(); handler.postDelayed(this, 1000) }
            })
        }
    }

    fun erforderlich(): Boolean = LanRegel.erforderlich(
        Build.VERSION.SDK_INT, context?.applicationInfo?.targetSdkVersion ?: 37)

    /** Resolve once, then check the actual route; connect to this exact address. */
    fun ziel(host: String): java.net.InetAddress = LanRegel.ziel(host,
        { pruefen() }, { java.net.InetAddress.getByName(it) }, { lokal(it) })

    fun lokal(adresse: java.net.InetAddress): Boolean {
        if (!erforderlich() || LanRegel.lokal(adresse)) return LanRegel.lokal(adresse)
        val network = verbindungsnetz() ?: return true
        return routenLan(adresse, network) ?: true
    }

    private fun verbindungsnetz(): Network? = runCatching {
        val manager = context?.getSystemService(ConnectivityManager::class.java)
        manager?.boundNetworkForProcess ?: manager?.activeNetwork
    }.getOrNull()

    /** null means the exact network no longer exists or its state cannot be read. */
    private fun routenLan(adresse: java.net.InetAddress, network: Network): Boolean? {
        return runCatching {
            val manager = context?.getSystemService(ConnectivityManager::class.java)
                ?: return@runCatching null
            val caps = manager.getNetworkCapabilities(network) ?: return@runCatching null
            val type = when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> LanRoutenRegel.Netz.VPN
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> LanRoutenRegel.Netz.CELLULAR
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> LanRoutenRegel.Netz.BROADCAST
                else -> LanRoutenRegel.Netz.UNKNOWN
            }
            val routes = manager.getLinkProperties(network)?.routes?.map {
                LanRoutenRegel.Route(it.destination.address, it.destination.prefixLength,
                    it.gateway?.isAnyLocalAddress == false)
            }
            LanRoutenRegel.brauchtLan(adresse, type,
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET), routes)
        }.getOrNull()
    }

    /** Track public destinations too: a route can become local during the request. */
    fun beobachtenZiel(adresse: java.net.InetAddress, socket: java.net.Socket): ZielWache {
        // Pin the socket and every later route check to the same Network. A default
        // switch to cellular/VPN must not reclassify an existing Wi-Fi connection.
        val network = if (erforderlich()) verbindungsnetz() ?: throw java.io.IOException(WARTET) else null
        network?.bindSocket(socket)
        val wache = try { LanZielWache({
            if (network == null) osErlaubt()
            else routenLan(adresse, network)?.let { !it || osErlaubt() } ?: false
        }, socket) }
            catch (error: IllegalStateException) { throw java.io.IOException(WARTET, error) }
        zielWachen.add(wache)
        return ZielWache(wache)
    }

    class ZielWache internal constructor(private val wache: LanZielWache) : AutoCloseable {
        fun pruefen() { wache.pruefen(WARTET) }
        override fun close() {
            zielWachen.remove(wache)
            wache.close()
        }
    }

    fun erlaubt(): Boolean {
        val erlaubt = tor.erlaubt()
        zielWachen.forEach { it.aktuell() }
        return erlaubt
    }
    fun pruefen() { if (!erlaubt()) throw java.io.IOException(WARTET) }
    fun marke(): Long { pruefen(); return tor.marke() }
    fun aktuell(marke: Long): Boolean = tor.aktuell(marke)
    fun beobachten(ressource: AutoCloseable): AutoCloseable = try { tor.beobachten(ressource) }
        catch (error: IllegalStateException) { throw java.io.IOException(WARTET, error) }
}
