package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Suche und Ankündigung im lokalen Netz über DNS-SD (`_magnolie._tcp`) –
 * derselbe Diensttyp und dieselben TXT-Felder, die der Organizer über
 * `python3-zeroconf` veröffentlicht.
 */
object Entdeckung {

    private const val ART = "_magnolie._tcp"

    private var verwalter: NsdManager? = null
    private var anmeldung: NsdManager.RegistrationListener? = null
    private var letzteIdentitaet: EigeneIdentitaet? = null
    private var letzterPort: Int = Netz.PORT

    fun veroeffentlichen(zusammenhang: Context, eigen: EigeneIdentitaet?, port: Int) {
        if (eigen == null) return
        letzteIdentitaet = eigen
        letzterPort = port
        val nsd = zusammenhang.applicationContext
            .getSystemService(Context.NSD_SERVICE) as? NsdManager ?: return
        beenden()
        verwalter = nsd
        val angaben = NsdServiceInfo().apply {
            serviceName = eigen.kennung
            serviceType = ART
            this.port = port
            setAttribute("kennung", eigen.kennung)
            setAttribute("name", eigen.name.take(60))
            setAttribute("fingerabdruck", Krypto.fingerabdruck(eigen.oeffentlich))
            setAttribute("fassung", "1")
        }
        val horcher = object : NsdManager.RegistrationListener {
            override fun onRegistrationFailed(dienst: NsdServiceInfo?, fehler: Int) {}
            override fun onUnregistrationFailed(dienst: NsdServiceInfo?, fehler: Int) {}
            override fun onServiceRegistered(dienst: NsdServiceInfo?) {}
            override fun onServiceUnregistered(dienst: NsdServiceInfo?) {}
        }
        anmeldung = horcher
        runCatching { nsd.registerService(angaben, NsdManager.PROTOCOL_DNS_SD, horcher) }
    }

    /** Nach einer Namensänderung muss die Ankündigung neu heraus. */
    fun neuVeroeffentlichen(eigen: EigeneIdentitaet?, port: Int) {
        val nsd = verwalter ?: return
        val alt = anmeldung
        if (alt != null) runCatching { nsd.unregisterService(alt) }
        anmeldung = null
        val identitaet = eigen ?: letzteIdentitaet ?: return
        letzteIdentitaet = identitaet
        letzterPort = port
        val angaben = NsdServiceInfo().apply {
            serviceName = identitaet.kennung
            serviceType = ART
            this.port = port
            setAttribute("kennung", identitaet.kennung)
            setAttribute("name", identitaet.name.take(60))
            setAttribute("fingerabdruck", Krypto.fingerabdruck(identitaet.oeffentlich))
            setAttribute("fassung", "1")
        }
        val horcher = object : NsdManager.RegistrationListener {
            override fun onRegistrationFailed(dienst: NsdServiceInfo?, fehler: Int) {}
            override fun onUnregistrationFailed(dienst: NsdServiceInfo?, fehler: Int) {}
            override fun onServiceRegistered(dienst: NsdServiceInfo?) {}
            override fun onServiceUnregistered(dienst: NsdServiceInfo?) {}
        }
        anmeldung = horcher
        runCatching { nsd.registerService(angaben, NsdManager.PROTOCOL_DNS_SD, horcher) }
    }

    fun beenden() {
        val nsd = verwalter
        val horcher = anmeldung
        if (nsd != null && horcher != null) runCatching { nsd.unregisterService(horcher) }
        anmeldung = null
        verwalter = null
    }

    /**
     * Sucht Zweige. Läuft synchron und gehört darum in einen Hintergrundfaden.
     */
    fun suchen(
        zusammenhang: Context,
        eigeneKennung: String,
        wartezeitMs: Long = 3000
    ): List<Gefunden> {
        val nsd = zusammenhang.applicationContext
            .getSystemService(Context.NSD_SERVICE) as? NsdManager ?: return emptyList()
        val gefunden = java.util.Collections.synchronizedList(mutableListOf<Gefunden>())
        val fertig = CountDownLatch(1)
        val offen = java.util.concurrent.atomic.AtomicInteger(0)

        val suche = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(art: String?, fehler: Int) = fertig.countDown()
            override fun onStopDiscoveryFailed(art: String?, fehler: Int) = fertig.countDown()
            override fun onDiscoveryStarted(art: String?) {}
            override fun onDiscoveryStopped(art: String?) = fertig.countDown()

            override fun onServiceFound(dienst: NsdServiceInfo?) {
                val angaben = dienst ?: return
                if (angaben.serviceName == eigeneKennung) return
                offen.incrementAndGet()
                nsd.resolveService(angaben, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(dienst: NsdServiceInfo?, fehler: Int) {
                        offen.decrementAndGet()
                    }

                    override fun onServiceResolved(dienst: NsdServiceInfo?) {
                        offen.decrementAndGet()
                        val geloest = dienst ?: return
                        val merkmale = geloest.attributes ?: emptyMap()
                        fun merkmal(name: String) =
                            merkmale[name]?.let { String(it, Charsets.UTF_8) }.orEmpty()
                        val kennung = merkmal("kennung").ifBlank { geloest.serviceName.orEmpty() }
                        if (kennung.isBlank() || kennung == eigeneKennung) return
                        if (gefunden.any { it.kennung == kennung }) return
                        gefunden += Gefunden(
                            kennung = kennung,
                            name = merkmal("name").ifBlank { kennung },
                            fingerabdruck = merkmal("fingerabdruck"),
                            adresse = geloest.host?.hostAddress?.substringBefore('%').orEmpty(),
                            port = geloest.port.takeIf { it > 0 } ?: Netz.PORT
                        )
                    }
                })
            }

            override fun onServiceLost(dienst: NsdServiceInfo?) {}
        }

        return try {
            nsd.discoverServices(ART, NsdManager.PROTOCOL_DNS_SD, suche)
            fertig.await(wartezeitMs, TimeUnit.MILLISECONDS)
            // Den Auflösungen noch einen Moment geben.
            var warten = 0
            while (offen.get() > 0 && warten < 2000) {
                Thread.sleep(100)
                warten += 100
            }
            runCatching { nsd.stopServiceDiscovery(suche) }
            gefunden.toList()
        } catch (fehler: Exception) {
            gefunden.toList()
        }
    }
}
