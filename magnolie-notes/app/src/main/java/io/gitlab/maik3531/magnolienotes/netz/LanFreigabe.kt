package io.gitlab.maik3531.magnolienotes.netz

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper

/** No consent, pairing or account state is stored here. Re-read the OS grant. */
object LanFreigabe {
    const val RECHT = "android.permission.ACCESS_LOCAL_NETWORK"
    val WARTET: String get() = context?.getString(io.gitlab.maik3531.magnolienotes.R.string.lan_freigabe_wartet)
        ?: "Local network is waiting for permission in Android app settings."
    @Volatile private var context: Context? = null
    private val tor = LanTor {
        !erforderlich() || context?.checkSelfPermission(RECHT) == PackageManager.PERMISSION_GRANTED
    }

    fun initialisieren(context: Context) {
        this.context = context.applicationContext
        // No background prompts. Android may also kill the process on revocation.
        if (erforderlich()) {
            val handler = Handler(Looper.getMainLooper())
            handler.post(object : Runnable {
                override fun run() { erlaubt(); handler.postDelayed(this, 1000) }
            })
        }
    }

    fun erforderlich(): Boolean = LanRegel.erforderlich(
        Build.VERSION.SDK_INT, context?.applicationInfo?.targetSdkVersion ?: 37)

    /** Resolve once and connect to that exact address; public remote sync stays independent. */
    fun ziel(host: String): java.net.InetAddress = LanRegel.ziel(host,
        { pruefen() }, { java.net.InetAddress.getByName(it) })
    fun lokal(adresse: java.net.InetAddress): Boolean = LanRegel.lokal(adresse)

    fun erlaubt(): Boolean = tor.erlaubt()
    fun pruefen() { if (!erlaubt()) throw java.io.IOException(WARTET) }
    fun marke(): Long { pruefen(); return tor.marke() }
    fun aktuell(marke: Long): Boolean = tor.aktuell(marke)
    fun beobachten(ressource: AutoCloseable): AutoCloseable = try { tor.beobachten(ressource) }
        catch (error: IllegalStateException) { throw java.io.IOException(WARTET, error) }
}
