package io.gitlab.maik3531.magnolienotes

import android.Manifest
import android.content.Intent
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import io.gitlab.maik3531.magnolienotes.baum.BaumDienst
import io.gitlab.maik3531.magnolienotes.baum.BaumFehler
import io.gitlab.maik3531.magnolienotes.baum.Baumwerk
import io.gitlab.maik3531.magnolienotes.baum.BluetoothZiel
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.baum.Gefunden
import io.gitlab.maik3531.magnolienotes.baum.Nutzlast
import io.gitlab.maik3531.magnolienotes.baum.PaarungsLink
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.einfuhr.Einfuhr
import io.gitlab.maik3531.magnolienotes.einfuhr.Einfuhrergebnis
import io.gitlab.maik3531.magnolienotes.ui.AufgabenBlatt
import io.gitlab.maik3531.magnolienotes.ui.AufgabenEditor
import io.gitlab.maik3531.magnolienotes.ui.BaumBlatt
import io.gitlab.maik3531.magnolienotes.ui.Baumhandlungen
import io.gitlab.maik3531.magnolienotes.ui.Telefonhandlungen
import io.gitlab.maik3531.magnolienotes.telefon.TelefonDienst
import io.gitlab.maik3531.magnolienotes.telefon.TelefonModulStatus
import io.gitlab.maik3531.magnolienotes.telefon.TelefonWerk
import io.gitlab.maik3531.magnolienotes.ui.EinfuhrBlatt
import io.gitlab.maik3531.magnolienotes.ui.Einband
import io.gitlab.maik3531.magnolienotes.ui.MagnolieThema
import io.gitlab.maik3531.magnolienotes.ui.NotizBlatt
import io.gitlab.maik3531.magnolienotes.ui.NotizEditor
import io.gitlab.maik3531.magnolienotes.ui.AnhangEreignis
import io.gitlab.maik3531.magnolienotes.ui.Register
import io.gitlab.maik3531.magnolienotes.ui.JournalBlatt
import io.gitlab.maik3531.magnolienotes.ui.JournalHandlungen
import io.gitlab.maik3531.magnolienotes.journal.AndroidJournal
import io.gitlab.maik3531.magnolienotes.AnhangDatei
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    private val gewuenschteAufgabe = mutableStateOf<String?>(null)
    internal val qrPaarung = mutableStateOf<String?>(null)
    internal val bestaetigteQrPaarung = mutableStateOf<String?>(null)
    internal val benachrichtigungsFreigabe = registerForActivityResult(
        ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(zustand: Bundle?) {
        super.onCreate(zustand)
        gewuenschteAufgabe.value = intent?.getStringExtra(ZEIGE_AUFGABE)
        if (zustand?.getBoolean(QR_LINK_VERBRAUCHT) == true) {
            qrPaarung.value = zustand.getString(QR_PAARUNG)
            bestaetigteQrPaarung.value = zustand.getString(QR_PAARUNG_BESTAETIGT)
            intent?.data = null
        } else {
            empfangePaarungsLink(intent)
        }
        setContent { MagnolieThema { Startblatt(gewuenschteAufgabe) } }
    }

    override fun onResume() {
        super.onResume()
        if ((application as MagnolieApp).startZustand.value == StartZustand.Bereit) {
            runCatching { TelefonWerk.get(this).runtimePermissionsChanged() }
        }
    }

    override fun onNewIntent(absicht: Intent) {
        super.onNewIntent(absicht)
        setIntent(absicht)
        gewuenschteAufgabe.value = absicht.getStringExtra(ZEIGE_AUFGABE)
        empfangePaarungsLink(absicht)
    }

    private fun empfangePaarungsLink(absicht: Intent?) {
        if (absicht?.dataString != null) {
            qrPaarung.value = PaarungsLink.dekodiere(absicht.dataString)
        }
        absicht?.data = null
    }

    override fun onSaveInstanceState(zustand: Bundle) {
        zustand.putBoolean(QR_LINK_VERBRAUCHT, true)
        qrPaarung.value?.let { zustand.putString(QR_PAARUNG, it) }
        bestaetigteQrPaarung.value?.let { zustand.putString(QR_PAARUNG_BESTAETIGT, it) }
        super.onSaveInstanceState(zustand)
    }

    companion object {
        /** Über welche Aufgabe die Benachrichtigung sprach. */
        const val ZEIGE_AUFGABE = "zeige_aufgabe"
        private const val QR_LINK_VERBRAUCHT = "qr_link_verbraucht"
        private const val QR_PAARUNG = "qr_paarung"
        private const val QR_PAARUNG_BESTAETIGT = "qr_paarung_bestaetigt"
    }
}

@Composable
private fun MainActivity.Startblatt(gewuenschteAufgabe: androidx.compose.runtime.MutableState<String?>) {
    val zustand by (application as MagnolieApp).startZustand.collectAsState()
    var einrichtungsschritt by remember {
        mutableStateOf(if (Ersteinrichtung.abgeschlossen(this)) -1 else 0)
    }
    val qrText = qrPaarung.value
    val qrVorschau = remember(qrText) {
        qrText?.let { runCatching { PaarungsLink.vorschau(it) } }
    }
    LaunchedEffect(zustand, einrichtungsschritt) {
        if (zustand == StartZustand.Bereit && einrichtungsschritt < 0) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                benachrichtigungsFreigabe.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            Erinnerung.allesNeuStellen(this@Startblatt)
            TelefonWerk.get(this@Startblatt).refreshModules()
        }
    }
    LaunchedEffect(qrText) {
        qrVorschau?.exceptionOrNull()?.let {
            qrPaarung.value = null
            Toast.makeText(this@Startblatt,
                getString(R.string.baum_paarung_fehler, fehlertext(it)), Toast.LENGTH_LONG).show()
        }
    }
    LaunchedEffect(zustand, bestaetigteQrPaarung.value) {
        val text = bestaetigteQrPaarung.value
        if (zustand == StartZustand.Bereit && text != null) {
            val ergebnis = withContext(Dispatchers.IO) {
                runCatching { Baumwerk.hole(this@Startblatt).paareMitDatei(text) }
            }
            bestaetigteQrPaarung.value = null
            ergebnis.onSuccess {
                Toast.makeText(this@Startblatt,
                    getString(R.string.baum_paarung_gut, it.name), Toast.LENGTH_LONG).show()
            }.onFailure {
                Toast.makeText(this@Startblatt,
                    getString(R.string.baum_paarung_fehler, fehlertext(it)),
                    Toast.LENGTH_LONG).show()
            }
        }
    }
    when (val aktuell = zustand) {
        StartZustand.Laden -> Ladeblatt()
        StartZustand.Bereit -> Hauptblatt(gewuenschteAufgabe)
        is StartZustand.Fehler -> RecoveryBlatt(
            art = aktuell.art,
            erneut = { (application as MagnolieApp).starten() },
            schliessen = { finishAffinity() }
        )
    }
    if (zustand == StartZustand.Bereit) {
        if (einrichtungsschritt >= 0) {
            val schritt = Ersteinrichtung.schritte[einrichtungsschritt]
            AlertDialog(
                onDismissRequest = {},
                title = { Text("${stringResource(schritt.titel)} · ${einrichtungsschritt + 1}/${Ersteinrichtung.schritte.size}") },
                text = {
                    Column {
                        schritt.texte.forEachIndexed { index, text ->
                            if (index > 0) Spacer(Modifier.height(12.dp))
                            Text(stringResource(text))
                        }
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        if (einrichtungsschritt < Ersteinrichtung.schritte.lastIndex) einrichtungsschritt++
                        else if (Ersteinrichtung.abschliessen(this@Startblatt)) einrichtungsschritt = -1
                    }) { Text(stringResource(R.string.ok)) }
                },
                dismissButton = {
                    if (einrichtungsschritt > 0) {
                        TextButton(onClick = { einrichtungsschritt-- }) {
                            Text(stringResource(R.string.zurueck))
                        }
                    }
                }
            )
        }
        qrVorschau?.getOrNull()?.let { vorschau ->
            AlertDialog(
                onDismissRequest = { qrPaarung.value = null },
                title = { Text(stringResource(R.string.baum_paaren_titel)) },
                text = {
                    Column {
                        Text(stringResource(R.string.baum_gefunden,
                            vorschau.name, vorschau.adresse))
                        Spacer(Modifier.height(12.dp))
                        Text("${stringResource(R.string.baum_fingerabdruck)}: " +
                            vorschau.fingerabdruck)
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        qrPaarung.value = null
                        bestaetigteQrPaarung.value = vorschau.text
                    }) { Text(stringResource(R.string.baum_verbinden)) }
                },
                dismissButton = {
                    TextButton(onClick = { qrPaarung.value = null }) {
                        Text(stringResource(R.string.abbrechen))
                    }
                }
            )
        }
    }
}

@Composable
internal fun Ladeblatt() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Spacer(Modifier.height(16.dp))
            Text(stringResource(R.string.start_laden))
        }
    }
}

@Composable
internal fun RecoveryBlatt(art: io.gitlab.maik3531.magnolienotes.daten.StartFehlerArt,
                           erneut: () -> Unit, schliessen: () -> Unit) {
    // Die Art bleibt strukturiert im Zustand; technische Details und Pfade gehoeren nicht in die UI.
    @Suppress("UNUSED_VARIABLE") val strukturierteArt = art
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.start_fehler_titel))
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.start_daten_unveraendert))
            Spacer(Modifier.height(24.dp))
            androidx.compose.foundation.layout.Row(horizontalArrangement = Arrangement.Center) {
                Button(onClick = erneut) { Text(stringResource(R.string.start_erneut)) }
                Spacer(Modifier.width(12.dp))
                Button(onClick = schliessen) { Text(stringResource(R.string.start_schliessen)) }
            }
        }
    }
}

data class AnhangSpeicherAnfrage(val mime: String, val name: String)

class AnhangSpeichernVertrag : ActivityResultContract<AnhangSpeicherAnfrage, Uri?>() {
    override fun createIntent(context: Context, input: AnhangSpeicherAnfrage) =
        Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = input.mime
            putExtra(Intent.EXTRA_TITLE, input.name)
        }

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        intent?.data?.takeIf { resultCode == android.app.Activity.RESULT_OK }
}

@Composable
private fun Hauptblatt(gewuenschteAufgabe: androidx.compose.runtime.MutableState<String?>) {
    val zusammenhang = LocalContext.current
    val ablage = remember { Ablage.hole(zusammenhang) }
    val werk = remember { Baumwerk.hole(zusammenhang) }
    val journal = remember { AndroidJournal.hole(zusammenhang) }
    val telefonWerk = remember { TelefonWerk.get(zusammenhang) }
    val faden = rememberCoroutineScope()

    val bestand by ablage.bestand.collectAsState()
    val baumzustand by werk.zustand.collectAsState()
    val meldungen by werk.meldungen.collectAsState()
    val journalZustand by journal.state.collectAsState()
    val telefonZustand by telefonWerk.state.collectAsState()

    var blatt by remember { mutableStateOf(0) }
    var offeneNotiz by remember { mutableStateOf<Notiz?>(null) }
    var anhangZiel by remember { mutableStateOf<String?>(null) }
    var anhangSpeicherZiel by remember { mutableStateOf<io.gitlab.maik3531.magnolienotes.daten.Anhang?>(null) }
    var anhangEreignis by remember { mutableStateOf<AnhangEreignis?>(null) }
    var offeneAufgabe by remember { mutableStateOf<Aufgabe?>(null) }

    // Kommt die App aus einer Erinnerung, wird die gemeinte Aufgabe geöffnet.
    val gewuenscht = gewuenschteAufgabe.value
    if (gewuenscht != null) {
        androidx.compose.runtime.LaunchedEffect(gewuenscht) {
            ablage.aufgabe(gewuenscht)?.let { offeneAufgabe = it; blatt = 1 }
            gewuenschteAufgabe.value = null
        }
    }
    var einfuhrergebnis by remember { mutableStateOf<Einfuhrergebnis?>(null) }
    var einfuhrLaeuft by remember { mutableStateOf(false) }
    var gefunden by remember { mutableStateOf<List<Gefunden>>(emptyList()) }
    var bluetoothGeraete by remember { mutableStateOf<List<BluetoothZiel>>(emptyList()) }
    var sucheLaeuft by remember { mutableStateOf(false) }
    var kontaktZweig by remember { mutableStateOf<String?>(null) }
    var kontaktNachFreigabe by remember { mutableStateOf<(() -> Unit)?>(null) }

    fun sage(text: String) = Toast.makeText(zusammenhang, text, Toast.LENGTH_LONG).show()

    fun bluetoothErlaubt(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
        zusammenhang.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) ==
        PackageManager.PERMISSION_GRANTED

    val bluetoothFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { erlaubt ->
        if (erlaubt) {
            faden.launch {
                bluetoothGeraete = withContext(Dispatchers.IO) {
                    werk.bluetoothStarten()
                    werk.gekoppelteBluetoothGeraete()
                }
            }
        } else {
            werk.bluetoothAnhalten()
            sage(zusammenhang.getString(R.string.baum_bluetooth_berechtigung))
        }
    }
    val telefonBluetoothFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { erlaubt ->
        if (erlaubt) runCatching { telefonWerk.setBluetoothEnabled(true) }
        else sage(zusammenhang.getString(R.string.telefon_bluetooth_berechtigung))
    }
    var telefonFreigabeZiel by remember { mutableStateOf("") }
    val telefonFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) { ergebnis ->
        val erlaubt = ergebnis.values.all { it }
        if (erlaubt) when (telefonFreigabeZiel) {
            "dial" -> telefonWerk.setDialRequestEnabled(true)
            "incoming" -> telefonWerk.setIncomingCallsEnabled(true)
            "number" -> telefonWerk.setIncomingNumberEnabled(true)
            "answer" -> telefonWerk.setAnswerCallsEnabled(true)
        } else sage(zusammenhang.getString(R.string.telefon_berechtigung_fehlt))
        telefonFreigabeZiel = ""
    }
    fun kontakteErlaubt() =
        zusammenhang.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED &&
            zusammenhang.checkSelfPermission(Manifest.permission.WRITE_CONTACTS) == PackageManager.PERMISSION_GRANTED

    fun kontaktLauf(kennung: String) {
        faden.launch {
            val ergebnis = withContext(Dispatchers.IO) { runCatching { werk.kontakteSynchronisieren(kennung) } }
            ergebnis.onSuccess { sage(zusammenhang.getString(R.string.baum_kontakte_eingereiht)) }
            ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
        }
    }

    val kontaktFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { ergebnis ->
        val kennung = kontaktZweig
        kontaktZweig = null
        val danach = kontaktNachFreigabe
        kontaktNachFreigabe = null
        if (ergebnis.values.all { it }) {
            if (kennung != null) kontaktLauf(kennung) else danach?.invoke()
        } else sage(zusammenhang.getString(R.string.baum_kontakte_berechtigung))
    }

    fun mitKontaktFreigabe(handlung: () -> Unit) {
        if (kontakteErlaubt()) handlung() else {
            kontaktNachFreigabe = handlung
            kontaktFreigabe.launch(arrayOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS))
        }
    }

    LaunchedEffect(baumzustand.bluetoothAn) {
        if (baumzustand.bluetoothAn && bluetoothErlaubt()) {
            bluetoothGeraete = withContext(Dispatchers.IO) {
                werk.gekoppelteBluetoothGeraete()
            }
        } else if (!baumzustand.bluetoothAn) {
            bluetoothGeraete = emptyList()
        }
    }

    val dateiWaehler = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { quelle ->
        if (quelle == null) return@rememberLauncherForActivityResult
        einfuhrLaeuft = true
        faden.launch {
            val bericht = withContext(Dispatchers.IO) { Einfuhr.ausDatei(zusammenhang, quelle) }
            einfuhrergebnis = bericht
            einfuhrLaeuft = false
        }
    }

    val ordnerWaehler = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { baum ->
        if (baum == null) return@rememberLauncherForActivityResult
        einfuhrLaeuft = true
        faden.launch {
            val bericht = withContext(Dispatchers.IO) { Einfuhr.ausOrdner(zusammenhang, baum) }
            einfuhrergebnis = bericht
            einfuhrLaeuft = false
        }
    }

    val anhangWaehler = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { quelle ->
        val ziel = anhangZiel
        anhangZiel = null
        if (quelle == null || ziel == null) return@rememberLauncherForActivityResult
        faden.launch {
            val gelesen = withContext(Dispatchers.IO) { AnhangLeser.lies(zusammenhang, quelle) }
            val anhang = gelesen.anhang
            val aktuell = offeneNotiz
            if (anhang == null) {
                sage(zusammenhang.getString(
                    if (gelesen.fehler == AnhangLeser.Fehler.ZU_GROSS) R.string.notiz_anhang_gross
                    else R.string.notiz_anhang_ungueltig
                ))
            } else if (aktuell?.id == ziel) {
                val neu = Nutzlast.saubere(aktuell.anhaenge + anhang)
                val entscheidung = io.gitlab.maik3531.magnolienotes.baum.AnhangSpeicher.entscheide(
                    ablage.notizen().flatMap { it.anhaenge }, aktuell.anhaenge, neu,
                    zusammenhang.filesDir.usableSpace
                )
                if (neu.size != aktuell.anhaenge.size + 1) {
                    sage(zusammenhang.getString(R.string.notiz_anhang_ungueltig))
                } else if (!entscheidung.erlaubt) {
                    sage(zusammenhang.getString(R.string.baum_anhaenge_speicher))
                } else {
                    offeneNotiz = aktuell.copy(anhaenge = neu)
                    anhangEreignis = AnhangEreignis(ziel, anhang)
                }
            }
        }
    }

    val anhangSpeicher = androidx.activity.compose.rememberLauncherForActivityResult(
        AnhangSpeichernVertrag()
    ) { ziel ->
        val anhang = anhangSpeicherZiel
        anhangSpeicherZiel = null
        if (ziel == null || anhang == null) return@rememberLauncherForActivityResult
        faden.launch {
            val gespeichert = withContext(Dispatchers.IO) {
                AnhangDatei.speichern(zusammenhang, ziel, anhang)
            }
            sage(zusammenhang.getString(
                if (gespeichert) R.string.notiz_anhang_gespeichert
                else R.string.notiz_anhang_speichern_fehler
            ))
        }
    }

    val paarungWaehler = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { quelle ->
        if (quelle == null) return@rememberLauncherForActivityResult
        faden.launch {
            val ergebnis = withContext(Dispatchers.IO) {
                runCatching {
                    val text = zusammenhang.contentResolver.openInputStream(quelle)
                        ?.use { String(it.readBytes(), Charsets.UTF_8) }
                        ?: throw BaumFehler(Fehlertext.DATEI_OEFFNEN)
                    werk.paareMitDatei(text)
                }
            }
            ergebnis.onSuccess { sage(zusammenhang.getString(R.string.baum_paarung_gut, it.name)) }
            ergebnis.onFailure {
                sage(zusammenhang.getString(R.string.baum_paarung_fehler, zusammenhang.fehlertext(it)))
            }
        }
    }

    val bestaetigte = baumzustand.partner.filter { it.bestaetigt }
        .map { zweig ->
            zweig.kennung to (zweig.name.ifBlank { zweig.kennung } +
                (if (zweig.adresse.isNotBlank()) "  ·  " + zweig.adresse else ""))
        }

    val offeneA = offeneAufgabe
    if (offeneA != null) {
        AufgabenEditor(
            aufgabe = offeneA,
            partnernamen = bestaetigte,
            beiSichern = { geaendert ->
                val gesichert = ablage.sichereAufgabe(geaendert)
                offeneAufgabe = gesichert
                Erinnerung.stellen(zusammenhang, gesichert)
                if (gesichert.istFremd && gesichert.erledigt != offeneA.erledigt) {
                    faden.launch {
                        withContext(Dispatchers.IO) {
                            werk.aufgabeAbhaken(gesichert.id, gesichert.erledigt)
                        }
                    }
                }
            },
            beiLoeschen = {
                Erinnerung.abbestellen(zusammenhang, offeneA.id)
                ablage.loescheAufgabe(offeneA.id)
            },
            beiWeitergeben = { kennungen ->
                faden.launch {
                    val ergebnis = withContext(Dispatchers.IO) {
                        runCatching {
                            werk.teileAufgabe(ablage.aufgabe(offeneA.id) ?: offeneA, kennungen)
                        }
                    }
                    ergebnis.onSuccess {
                        offeneAufgabe = it
                        sage(zusammenhang.getString(R.string.baum_geteilt))
                    }
                    ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                }
            },
            beiZurueck = { offeneAufgabe = null }
        )
        // Ohne diesen Griff beendete die Zurueck-Taste des Geraets die ganze
        // App, statt den Bearbeiter zu schliessen. Der Knopf oben bleibt; wer
        // einhaendig bedient, kommt nun auch unten heraus.
        BackHandler { offeneAufgabe = null }
        return
    }

    val offen = offeneNotiz
    if (offen != null) {
        NotizEditor(
            notiz = offen,
            partnernamen = bestaetigte,
            beiSichern = { geaendert ->
                val gesichert = ablage.sichereNotiz(geaendert)
                offeneNotiz = gesichert
                if (gesichert.baumFreigabe != null) {
                    faden.launch {
                        // Die fortgeschriebene Fassung zurückholen, damit die
                        // Versionsnummer beim nächsten Sichern weiterzählt.
                        val fortgeschrieben = withContext(Dispatchers.IO) {
                            werk.notizFortschreiben(gesichert)
                        }
                        if (offeneNotiz?.id == fortgeschrieben.id) offeneNotiz = fortgeschrieben
                    }
                }
            },
            beiLoeschen = { ablage.loescheNotiz(offen.id) },
            beiTeilen = { kennungen ->
                faden.launch {
                    val ergebnis = withContext(Dispatchers.IO) {
                        runCatching { werk.teileNotiz(ablage.notiz(offen.id) ?: offen, kennungen) }
                    }
                    ergebnis.onSuccess {
                        offeneNotiz = it
                        sage(zusammenhang.getString(R.string.baum_geteilt))
                    }
                    ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                }
            },
            beiAnhangOeffnen = { anhang ->
                if (!AnhangDatei.oeffnen(zusammenhang, anhang)) {
                    sage(zusammenhang.getString(R.string.notiz_anhang_oeffnen_fehler))
                }
            },
            beiAnhangSpeichern = { anhang ->
                faden.launch {
                    val inhalt = withContext(Dispatchers.Default) { AnhangDatei.dekodieren(anhang) }
                    if (inhalt == null) {
                        sage(zusammenhang.getString(R.string.notiz_anhang_speichern_fehler))
                    } else {
                        anhangSpeicherZiel = anhang
                        anhangSpeicher.launch(AnhangSpeicherAnfrage(
                            inhalt.mime, AnhangDatei.sichererName(anhang, inhalt)
                        ))
                    }
                }
            },
            beiAnhangHinzufuegen = {
                anhangZiel = offen.id
                anhangWaehler.launch(arrayOf(
                    "image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"
                ))
            },
            anhangEreignis = anhangEreignis,
            beiAnhangEreignisVerbraucht = { anhangEreignis = null },
            beiAnhaengeAenderung = { anhaenge ->
                val current = offeneNotiz?.takeIf { it.id == offen.id }
                val removed = current?.anhaenge?.filter { old -> anhaenge.none { it.id == old.id } }.orEmpty()
                if (removed.size == 1) {
                    ablage.loescheAnhang(offen.id, removed.single().id)
                    offeneNotiz = ablage.notiz(offen.id)
                } else offeneNotiz = current?.copy(anhaenge = anhaenge)
            },
            beiZurueck = { offeneNotiz = null }
        )
        BackHandler { offeneNotiz = null }
        return
    }

    Scaffold(
        topBar = { Einband(stringResource(R.string.app_name)) },
        bottomBar = {
            Register(
                blaetter = listOf(
                    stringResource(R.string.blatt_notizen),
                    stringResource(R.string.blatt_aufgaben),
                    stringResource(R.string.blatt_einfuhr),
                    stringResource(R.string.blatt_baum),
                    stringResource(R.string.blatt_journal)
                ),
                gewaehlt = blatt,
                beiWahl = { blatt = it }
            )
        }
    ) { rand ->
        // Aus einem anderen Reiter fuehrt Zurueck zuerst auf die Notizen; erst
        // von dort verlaesst man die App. Das entspricht dem, was Android-
        // Benutzer erwarten.
        BackHandler(enabled = blatt != 0) { blatt = 0 }
        Box(Modifier.fillMaxSize().padding(rand)) {
            when (blatt) {
                0 -> NotizBlatt(
                    notizen = bestand.notizen,
                    notizbuecher = bestand.notizbuecher,
                    beiOeffnen = { offeneNotiz = it },
                    beiNeu = {
                        offeneNotiz = Notiz(
                            id = Ablage.kennung(),
                            angelegt = System.currentTimeMillis(),
                            geaendert = System.currentTimeMillis()
                        )
                    }
                )

                1 -> AufgabenBlatt(
                    aufgaben = bestand.aufgaben,
                    beiOeffnen = { offeneAufgabe = it },
                    beiAbhaken = { aufgabe, erledigt ->
                        faden.launch {
                            withContext(Dispatchers.IO) {
                                werk.aufgabeAbhaken(aufgabe.id, erledigt)
                            }
                        }
                    },
                    beiNeu = {
                        offeneAufgabe = Aufgabe(
                            id = Ablage.kennung(),
                            angelegt = System.currentTimeMillis(),
                            geaendert = System.currentTimeMillis()
                        )
                    }
                )

                2 -> EinfuhrBlatt(
                    ergebnis = einfuhrergebnis,
                    laeuft = einfuhrLaeuft,
                    beiDatei = { dateiWaehler.launch(arrayOf("*/*")) },
                    beiOrdner = { ordnerWaehler.launch(null) }
                )

                3 -> BaumBlatt(
                    zustand = baumzustand,
                    bestand = bestand,
                    fingerabdruck = werk.fingerabdruck(),
                    gefunden = gefunden,
                    bluetoothGeraete = bluetoothGeraete,
                    sucheLaeuft = sucheLaeuft,
                    meldungen = meldungen,
                    telefon = telefonZustand,
                    telefonHandlungen = Telefonhandlungen(
                        beiDienst = { enabled -> if (enabled) TelefonDienst.start(zusammenhang) else TelefonDienst.stop(zusammenhang) },
                        beiSuchen = { faden.launch(Dispatchers.IO) { runCatching { telefonWerk.discover() } } },
                        beiVerbinden = { desktop -> faden.launch(Dispatchers.IO) { runCatching { telefonWerk.beginPairing(desktop) } } },
                        beiCode = { matches -> faden.launch(Dispatchers.IO) { runCatching { telefonWerk.confirmPairing(matches) } } },
                        beiEntkoppeln = telefonWerk::unpair,
                        beiBluetooth = { enabled ->
                            if (enabled && !bluetoothErlaubt() && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
                                telefonBluetoothFreigabe.launch(Manifest.permission.BLUETOOTH_CONNECT)
                            else runCatching { telefonWerk.setBluetoothEnabled(enabled) }
                                .onFailure { sage(zusammenhang.getString(R.string.telefon_bluetooth_voraussetzung)) }
                        },
                        beiBluetoothEinstellungen = {
                            zusammenhang.startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS))
                        },
                        beiBluetoothGeraete = {
                            faden.launch(Dispatchers.IO) { runCatching { telefonWerk.pairedBluetoothDevices() } }
                        },
                        beiBluetoothZiel = telefonWerk::assignBluetooth,
                        beiWaehlauftrag = { enabled ->
                            if (enabled && !TelefonModulStatus.dialPermissions(zusammenhang)) {
                                telefonFreigabeZiel = "dial"; telefonFreigabe.launch(arrayOf(
                                    Manifest.permission.CALL_PHONE, Manifest.permission.READ_PHONE_STATE))
                            } else telefonWerk.setDialRequestEnabled(enabled)
                        },
                        beiEingehendenAnrufen = { enabled ->
                            if (enabled && zusammenhang.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
                                telefonFreigabeZiel = "incoming"; telefonFreigabe.launch(arrayOf(Manifest.permission.READ_PHONE_STATE))
                            } else telefonWerk.setIncomingCallsEnabled(enabled)
                        },
                        beiAnrufernummer = { enabled ->
                            if (enabled && zusammenhang.checkSelfPermission(Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED) {
                                telefonFreigabeZiel = "number"; telefonFreigabe.launch(arrayOf(Manifest.permission.READ_CALL_LOG))
                            } else telefonWerk.setIncomingNumberEnabled(enabled)
                        },
                        beiAnnehmen = { enabled ->
                            if (enabled && zusammenhang.checkSelfPermission(Manifest.permission.ANSWER_PHONE_CALLS) != PackageManager.PERMISSION_GRANTED) {
                                telefonFreigabeZiel = "answer"; telefonFreigabe.launch(arrayOf(Manifest.permission.ANSWER_PHONE_CALLS))
                            } else telefonWerk.setAnswerCallsEnabled(enabled)
                        },
                        beiBenachrichtigungszugriff = {
                            zusammenhang.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                        },
                        beiBenachrichtigungsApp = telefonWerk::toggleNotificationPackage,
                        beiPersonalEigen = { telefonWerk.setPersonalSync(it, telefonZustand.personalNotesEnabled,
                            telefonZustand.personalTasksEnabled, telefonZustand.personalAutoWifi, telefonZustand.personalDeletionsEnabled) },
                        beiPersonalNotizen = { telefonWerk.setPersonalSync(telefonZustand.personalOwnDevice, it,
                            telefonZustand.personalTasksEnabled, telefonZustand.personalAutoWifi, telefonZustand.personalDeletionsEnabled) },
                        beiPersonalAufgaben = { telefonWerk.setPersonalSync(telefonZustand.personalOwnDevice,
                            telefonZustand.personalNotesEnabled, it, telefonZustand.personalAutoWifi, telefonZustand.personalDeletionsEnabled) },
                        beiPersonalAutoWlan = { telefonWerk.setPersonalSync(telefonZustand.personalOwnDevice,
                            telefonZustand.personalNotesEnabled, telefonZustand.personalTasksEnabled, it, telefonZustand.personalDeletionsEnabled) },
                        beiPersonalLoeschungen = { telefonWerk.setPersonalSync(telefonZustand.personalOwnDevice,
                            telefonZustand.personalNotesEnabled, telefonZustand.personalTasksEnabled,
                            telefonZustand.personalAutoWifi, it) },
                        beiPersonalJetzt = { runCatching { telefonWerk.personalSyncNow() }
                            .onFailure { sage(it.message.orEmpty()) } },
                        beiPersonalEntscheidung = telefonWerk::personalDeletionDecision
                    ),
                    handlungen = Baumhandlungen(
                        beiName = { werk.benenne(it) },
                        beiDienst = { an ->
                            if (an) BaumDienst.starten(zusammenhang)
                            else BaumDienst.anhalten(zusammenhang)
                        },
                        beiBluetooth = { an ->
                            if (an && !bluetoothErlaubt() &&
                                Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                            ) {
                                bluetoothFreigabe.launch(Manifest.permission.BLUETOOTH_CONNECT)
                            } else {
                                faden.launch {
                                    bluetoothGeraete = withContext(Dispatchers.IO) {
                                        if (an) {
                                            werk.bluetoothStarten()
                                            werk.gekoppelteBluetoothGeraete()
                                        } else {
                                            werk.bluetoothAnhalten()
                                            emptyList()
                                        }
                                    }
                                }
                            }
                        },
                        beiAutoWlan = { werk.automatischWlan(it) },
                        beiBluetoothZiel = { kennung, adresse ->
                            werk.bluetoothZuordnen(kennung, adresse)
                        },
                        beiFernziel = { kennung, host, port ->
                            werk.fernzielSichern(kennung, host, port)
                        },
                        beiAllesSynchronisieren = { kennung ->
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) {
                                    runCatching { werk.allesSynchronisieren(kennung) }
                                }
                                ergebnis.onSuccess {
                                    sage(zusammenhang.getString(R.string.baum_sync_eingereiht))
                                }
                                ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                            }
                        },
                        beiKontaktSync = { kennung, an -> werk.kontaktSyncSchalten(kennung, an) },
                        beiKontaktLoeschSync = { kennung, an -> werk.kontaktLoeschSyncSchalten(kennung, an) },
                        beiKontaktVorschlag = { id ->
                            faden.launch { withContext(Dispatchers.IO) { werk.kontaktLoeschungSenden(id) } }
                        },
                        beiKontaktVorschlagAblehnen = { werk.kontaktVorschlagAblehnen(it) },
                        beiDubletteOeffnen = { werk.dubletteOeffnen(it) },
                        beiDubletteVerknuepfen = { id ->
                            mitKontaktFreigabe {
                                faden.launch { withContext(Dispatchers.IO) { werk.dubletteVerknuepfen(id) } }
                            }
                        },
                        beiKontaktGruppeImportieren = { id, getrennt ->
                            mitKontaktFreigabe {
                                faden.launch { withContext(Dispatchers.IO) { werk.kontaktGruppeImportieren(id, getrennt) } }
                            }
                        },
                        beiKontaktGruppeAblehnen = { werk.kontaktGruppeAblehnen(it) },
                        beiSichereKontaktGruppenImportieren = { partner ->
                            mitKontaktFreigabe {
                                faden.launch { withContext(Dispatchers.IO) { werk.sichereKontaktGruppenImportieren(partner) } }
                            }
                        },
                        beiAlleKontaktKartenAblehnen = { werk.alleKontaktKartenAblehnen(it) },
                        beiKontakteSynchronisieren = { kennung ->
                            if (kontakteErlaubt()) kontaktLauf(kennung) else {
                                kontaktZweig = kennung
                                kontaktFreigabe.launch(arrayOf(
                                    Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS
                                ))
                            }
                        },
                        beiPaarungsdatei = { paarungWaehler.launch(arrayOf("*/*")) },
                        beiPaarungstext = { text ->
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) {
                                    runCatching { werk.paareMitDatei(text) }
                                }
                                ergebnis.onSuccess {
                                    sage(zusammenhang.getString(R.string.baum_paarung_gut, it.name))
                                }
                                ergebnis.onFailure {
                                    sage(
                                        zusammenhang.getString(
                                            R.string.baum_paarung_fehler, zusammenhang.fehlertext(it)
                                        )
                                    )
                                }
                            }
                        },
                        beiEigeneDatei = {
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) {
                                    runCatching { werk.erzeugePaarungsdatei() }
                                }
                                ergebnis.onSuccess { inhalt ->
                                    val teilen = Intent(Intent.ACTION_SEND).apply {
                                        type = "application/json"
                                        putExtra(Intent.EXTRA_TEXT, inhalt)
                                        putExtra(Intent.EXTRA_SUBJECT, "magnolie-paarung.json")
                                    }
                                    zusammenhang.startActivity(
                                        Intent.createChooser(
                                            teilen,
                                            zusammenhang.getString(R.string.baum_paarungsdatei_teilen)
                                        )
                                    )
                                }
                                ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                            }
                        },
                        beiSuchen = {
                            sucheLaeuft = true
                            faden.launch {
                                gefunden = withContext(Dispatchers.IO) { werk.suchen(zusammenhang) }
                                sucheLaeuft = false
                            }
                        },
                        beiAnfragen = { zweig ->
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) {
                                    runCatching { werk.frageAn(zweig.adresse, zweig.port) }
                                }
                                ergebnis.onSuccess { (_, code) ->
                                    sage(zusammenhang.getString(R.string.baum_code_vergleichen, code))
                                }
                                ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                            }
                        },
                        beiBestaetigen = { werk.bestaetigen(it) },
                        beiVertrauen = { kennung, an -> werk.vertrauen(kennung, an) },
                        beiEingangAnnehmen = { werk.eingangAnnehmen(it) },
                        beiEingangAblehnen = { werk.eingangEntfernen(it) },
                        beiMeldungenLeeren = { werk.meldungenLeeren() },
                        beiEntfernen = { werk.entfernen(it) },
                        beiSenden = {
                            faden.launch {
                                val zugestellt = withContext(Dispatchers.IO) {
                                    werk.postfachAbarbeiten()
                                }
                                sage(
                                    if (zugestellt > 0) {
                                        zusammenhang.getString(R.string.baum_geteilt)
                                    } else zusammenhang.getString(R.string.baum_nicht_erreicht)
                                )
                            }
                        }
                    )
                )
                else -> JournalBlatt(journalZustand, bestand, JournalHandlungen(
                    beiIntervall = journal::intervalSetzen,
                    beiJetzt = { faden.launch(Dispatchers.IO) { runCatching { journal.appSnapshot("manual", true) } } },
                    beiWiederherstellen = { id, op, force ->
                        val entry = journalZustand.entries.firstOrNull { it.uuid == id }
                        if (entry?.domain == "android-app-data") {
                            faden.launch(Dispatchers.IO) { runCatching { journal.restoreApp(id, op) }
                                .onFailure { withContext(Dispatchers.Main) { sage(zusammenhang.fehlertext(it)) } } }
                            true
                        } else runCatching { journal.restoreContacts(id, op, force) ==
                            io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT }
                            .getOrDefault(false)
                    },
                    beiLoeschen = journal::delete,
                    beiPapierkorbSchalter = ablage::setzePapierkorb,
                    beiPapierkorbTage = ablage::setzePapierkorb,
                    beiPapierkorbWiederherstellen = { ablage.papierkorbWiederherstellen(it) },
                    beiPapierkorbLoeschen = ablage::papierkorbEndgueltig,
                    beiPapierkorbLeeren = ablage::papierkorbLeeren
                ))
            }
        }
    }
}
