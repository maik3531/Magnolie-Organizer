package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import io.gitlab.maik3531.magnolienotes.baum.*
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.telefon.TelefonWerk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal data class WischVerbindungen(val notizen: Boolean = false, val aufgaben: Boolean = false,
    val fern: List<FernAbgleichVerbindung> = emptyList(), val pruefzeit: Long = 0)

/** Foreground-only native status; settings are never rewritten when a route disappears. */
@Composable internal fun wischVerbindungen(baum: Baumzustand, werk: Baumwerk, telefon: TelefonWerk,
                                          benoetigt: Boolean): WischVerbindungen {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var status by remember { mutableStateOf(WischVerbindungen()) }
    val binding = listOf(baum.kennung, baum.oeffentlich, baum.syncEpoch, baum.dienstAn.toString()) +
        baum.partner.flatMap { listOf(it.kennung, it.oeffentlich, it.fernAdresse, it.fernPort.toString(),
            it.protokoll, it.bestaetigt.toString(), it.vertraut.toString()) }
    LaunchedEffect(binding, lifecycle, benoetigt) {
        status = WischVerbindungen()
        if (benoetigt) lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            var naechsteProbe = 0L
            var fern = emptyList<FernAbgleichVerbindung>()
            try {
                coroutineScope {
                    // A slow remote endpoint must not delay local WIFI disconnect/reconnect feedback.
                    launch {
                        while (isActive) {
                            if (!FernAbgleich.internet(context)) { fern = emptyList(); naechsteProbe = 0L }
                            else if (System.nanoTime() >= naechsteProbe) {
                                fern = withContext(Dispatchers.IO) { werk.fernAbgleichVerbindungen() }
                                naechsteProbe = System.nanoTime() + 15_000_000_000L
                            }
                            delay(1000)
                        }
                    }
                    while (isActive) {
                        val aktuell = if (FernAbgleich.internet(context)) fern else emptyList()
                        status = withContext(Dispatchers.IO) {
                            WischVerbindungen(telefon.personalItemSyncAvailable("note"),
                                telefon.personalItemSyncAvailable("task"), aktuell, System.nanoTime())
                        }
                        delay(1000)
                    }
                }
            } finally { status = WischVerbindungen() }
        }
    }
    return status
}
