package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Partner

/** Volatile authenticated route evidence; a saved pairing is never an online indication. */
internal data class FernAbgleichVerbindung(
    val partner: Partner,
    val eigeneKennung: String,
    val eigenerSchluessel: String,
    val epoch: String,
    val gueltigBis: Long
) {
    fun passt(baum: Baumzustand, jetzt: Long = System.nanoTime()): Boolean =
        jetzt < gueltigBis && baum.dienstAn && baum.kennung == eigeneKennung &&
            baum.oeffentlich == eigenerSchluessel && baum.syncEpoch == epoch &&
            baum.partner.any { it.kennung == partner.kennung && it.bestaetigt && it.vertraut &&
                it.oeffentlich == partner.oeffentlich && it.protokoll == partner.protokoll &&
                it.fernAdresse == partner.fernAdresse && it.fernPort == partner.fernPort }
}

internal object FernAbgleich {
    fun internet(context: Context): Boolean = runCatching {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val capabilities = manager?.getNetworkCapabilities(manager.activeNetwork)
        capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }.getOrDefault(false)

    /** The existing signed FS1 handshake authenticates the pinned peer, without sending any content. */
    fun pruefen(eigen: EigeneIdentitaet, partner: Partner, epoch: String,
                jetzt: () -> Long = System::nanoTime,
                transport: () -> Transport = { WlanTransport(partner.fernAdresse, partner.fernPort) }): FernAbgleichVerbindung? {
        if (!partner.bestaetigt || !partner.vertraut || partner.fernAdresse.isBlank() ||
            partner.protokoll != "baum-fs1") return null
        val weg = transport()
        return try {
            val start = Sitzung.baueStart(eigen, partner.kennung, partner.oeffentlich)
            val antwort = weg.anfrage("/magnolie/v2/sitzung", start.nachricht, 1500)
            Sitzung.oeffneAntwort(eigen, partner.kennung, partner.oeffentlich, start, antwort).loeschen()
            FernAbgleichVerbindung(partner, eigen.kennung, eigen.oeffentlich, epoch,
                jetzt() + 30_000_000_000L)
        } catch (_: Exception) { null }
        finally { weg.schliessen() }
    }
}
