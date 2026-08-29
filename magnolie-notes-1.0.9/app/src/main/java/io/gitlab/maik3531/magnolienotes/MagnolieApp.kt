package io.gitlab.maik3531.magnolienotes

import android.app.Application
import android.content.Context
import android.os.Build
import android.util.Log
import androidx.work.Configuration
import androidx.work.WorkManager
import io.gitlab.maik3531.magnolienotes.baum.BaumDienst
import io.gitlab.maik3531.magnolienotes.baum.Baumwerk
import io.gitlab.maik3531.magnolienotes.journal.AndroidJournal
import io.gitlab.maik3531.magnolienotes.telefon.TelefonAblage
import io.gitlab.maik3531.magnolienotes.telefon.TelefonDienst
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.StartFehlerArt
import io.gitlab.maik3531.magnolienotes.daten.startFehler
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

sealed interface StartZustand {
    data object Laden : StartZustand
    data object Bereit : StartZustand
    data class Fehler(val art: StartFehlerArt) : StartZustand
}

internal class StartBarriere<T>(private val fehlerart: (Throwable) -> StartFehlerArt) {
    private val _zustand = MutableStateFlow<StartZustand>(StartZustand.Laden)
    val zustand = _zustand.asStateFlow()
    @Volatile private var signal = CompletableDeferred<Result<Unit>>()
    @Volatile internal var startLaeuft = false
        private set

    @Synchronized fun starten(
        scope: CoroutineScope,
        initialisieren: suspend () -> T,
        nachBereit: (T) -> Unit = {}
    ) {
        if (startLaeuft) return
        startLaeuft = true
        signal = CompletableDeferred()
        _zustand.value = StartZustand.Laden
        scope.launch {
            try {
                val ergebnis = initialisieren()
                _zustand.value = StartZustand.Bereit
                signal.complete(Result.success(Unit))
                runCatching { nachBereit(ergebnis) }
            } catch (fehler: Throwable) {
                _zustand.value = StartZustand.Fehler(fehlerart(fehler))
                signal.complete(Result.failure(fehler))
            } finally {
                startLaeuft = false
            }
        }
    }

    suspend fun awaitReady(): Boolean = signal.await().isSuccess

    internal fun zustandFuerInstrumentation(zustand: StartZustand) {
        _zustand.value = zustand
    }
}

class MagnolieApp : Application() {
    // Prozessweite System-Einstiege duerfen nie davon abhaengen, dass der Main-Looper
    // bereits eine Activity verarbeitet. StateFlow ist threadsicher.
    private val startScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val startBarriere = StartBarriere<Baumwerk> { startFehler(it).art }
    val startZustand = startBarriere.zustand
    private var workManagerInitialisiert = false
    private var workManagerFehler: Throwable? = null

    override fun attachBaseContext(base: Context) {
        super.attachBaseContext(base)
        Absturzberichte.installieren(this)
    }

    override fun onCreate() {
        super.onCreate()
        if (BuildConfig.LEGACY_PLAINTEXT_FIXTURE) {
            fixtureEinmaligAnlegen()
            return
        }
        runCatching {
            WorkManager.initialize(this, Configuration.Builder().build())
            workManagerInitialisiert = true
        }.onFailure { workManagerFehler = it }
        starten()
    }

    fun starten() {
        startBarriere.starten(startScope, initialisieren = {
            withContext(Dispatchers.IO) {
                    workManagerFehler?.let { throw it }
                    Log.i("MagnolieStartup", "Ablage")
                    Ablage.hole(this@MagnolieApp)
                    Log.i("MagnolieStartup", "Baumwerk")
                    val baumwerk = Baumwerk.hole(this@MagnolieApp)
                    Log.i("MagnolieStartup", "Journal")
                    val journal = AndroidJournal.hole(this@MagnolieApp)
                    Log.i("MagnolieStartup", "Identitaet")
                    baumwerk.sorgeFuerIdentitaet(vorgabename())
                    if (!workManagerInitialisiert) {
                        WorkManager.initialize(this@MagnolieApp, Configuration.Builder().build())
                        workManagerInitialisiert = true
                    }
                    Log.i("MagnolieStartup", "Planung")
                    journal.aktivieren()
                    Erinnerung.allesNeuStellen(this@MagnolieApp)
                    Log.i("MagnolieStartup", "Initialisierung abgeschlossen")
                    baumwerk
            }
        }, nachBereit = { werk ->
            // Persistierte Dienste werden erst nach vollstaendig erfolgreichem Start aktiviert.
            if (werk.zustand.value.dienstAn) runCatching { BaumDienst.starten(this@MagnolieApp) }
            if (TelefonAblage.get(this@MagnolieApp).enabled()) runCatching {
                TelefonDienst.start(this@MagnolieApp)
            }
        })
    }

    suspend fun awaitReady(): Boolean = startBarriere.awaitReady()

    internal fun startZustandFuerInstrumentation(zustand: StartZustand) {
        startBarriere.zustandFuerInstrumentation(zustand)
    }

    private fun fixtureEinmaligAnlegen() {
        val notizen = File(filesDir, "notizen.json")
        val baum = File(filesDir, "baum.json")
        if (notizen.exists() || baum.exists()) return
        notizen.writeText("""{"notizen":[{"id":"fixture-notiz","titel":"Vorgaenger Sentinel","text":"Nichtleere Upgrade-Daten","angelegt":1700000000000,"geaendert":1700000000000}],"notizbuecher":[],"aufgaben":[]}""")
        baum.writeText("""{"kennung":"fixture-baumidentitaet","name":"Vorgaenger Zweig","geheim":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","oeffentlich":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","port":8737}""")
    }

    /** Wie im Organizer: der kurze Gerätename als Vorgabe für den Zweig. */
    private fun vorgabename(): String {
        val name = Build.MODEL?.trim().orEmpty()
        return if (name.isBlank()) "Magnolie" else name.take(60)
    }
}
