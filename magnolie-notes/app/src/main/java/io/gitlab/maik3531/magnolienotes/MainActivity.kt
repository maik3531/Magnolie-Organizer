package io.gitlab.maik3531.magnolienotes

import android.Manifest
import android.content.ClipData
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.core.content.FileProvider
import io.gitlab.maik3531.magnolienotes.baum.BaumDienst
import io.gitlab.maik3531.magnolienotes.baum.BaumFehler
import io.gitlab.maik3531.magnolienotes.baum.Baumwerk
import io.gitlab.maik3531.magnolienotes.baum.BluetoothZiel
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import io.gitlab.maik3531.magnolienotes.baum.Gefunden
import io.gitlab.maik3531.magnolienotes.baum.KontaktImportVorschau
import io.gitlab.maik3531.magnolienotes.baum.Nutzlast
import io.gitlab.maik3531.magnolienotes.baum.PaarungsLink
import io.gitlab.maik3531.magnolienotes.daten.Aufgabe
import io.gitlab.maik3531.magnolienotes.daten.AufgabenHierarchie
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Notiz
import io.gitlab.maik3531.magnolienotes.daten.GeprueftesPortableArchiv
import io.gitlab.maik3531.magnolienotes.daten.PortableArchiv
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
import io.gitlab.maik3531.magnolienotes.sicherung.AndroidAutoSicherung
import io.gitlab.maik3531.magnolienotes.AnhangDatei
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.time.LocalDate
import java.util.UUID


private fun liesPortableArchiv(context: Context, uri: Uri): ByteArray {
    val puffer = ByteArrayOutputStream()
    context.contentResolver.openInputStream(uri)?.use { strom ->
        val block = ByteArray(64 * 1024)
        var gesamt = 0L
        while (true) {
            val n = strom.read(block)
            if (n < 0) break
            gesamt += n
            require(gesamt <= PortableArchiv.MAX_ARCHIV_BYTES)
            puffer.write(block, 0, n)
        }
    } ?: error("Datei kann nicht geoeffnet werden")
    return puffer.toByteArray()
}


class MainActivity : ComponentActivity() {

    private val gewuenschteAufgabe = mutableStateOf<String?>(null)
    internal val gewuenschtesCustom = mutableStateOf<Intent?>(null)
    internal val qrPaarung = mutableStateOf<String?>(null)
    internal val bestaetigteQrPaarung = mutableStateOf<String?>(null)
    internal val benachrichtigungsFreigabe = registerForActivityResult(
        ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(zustand: Bundle?) {
        super.onCreate(zustand)
        if (zustand?.getBoolean(QR_LINK_VERBRAUCHT) == true) {
            if (intent?.data == null && intent?.action in listOf(null, Intent.ACTION_MAIN))
                gewuenschteAufgabe.value = intent?.getStringExtra(ZEIGE_AUFGABE)
            qrPaarung.value = zustand.getString(QR_PAARUNG)
            bestaetigteQrPaarung.value = zustand.getString(QR_PAARUNG_BESTAETIGT)
            @Suppress("DEPRECATION")
            val custom = zustand.getParcelable<Intent>(CUSTOM_ZIEL)
            gewuenschtesCustom.value = CustomNavigation.anfrage(this, custom)
        } else {
            empfangeAbsicht(intent)
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
        entwurfSichern()
        setIntent(absicht)
        empfangeAbsicht(absicht)
    }

    private fun empfangeAbsicht(absicht: Intent?) {
        val custom = CustomNavigation.anfrage(this, absicht)
        if (custom != null) {
            gewuenschtesCustom.value = custom
            absicht?.data = null
            return
        }
        // Ordinary reminders have no data URI. A foreign URI cannot inject an editor ID.
        if (absicht?.data == null && absicht?.action in listOf(null, Intent.ACTION_MAIN))
            gewuenschteAufgabe.value = absicht?.getStringExtra(ZEIGE_AUFGABE)
        empfangePaarungsLink(absicht)
    }

    private fun empfangePaarungsLink(absicht: Intent?) {
        if (absicht?.dataString != null) {
            val paarung = PaarungsLink.dekodiere(absicht.dataString) ?: return
            qrPaarung.value = paarung
            absicht?.data = null
        }
    }

    override fun onSaveInstanceState(zustand: Bundle) {
        entwurfSichern()
        zustand.putBoolean(QR_LINK_VERBRAUCHT, true)
        qrPaarung.value?.let { zustand.putString(QR_PAARUNG, it) }
        bestaetigteQrPaarung.value?.let { zustand.putString(QR_PAARUNG_BESTAETIGT, it) }
        gewuenschtesCustom.value?.let { zustand.putParcelable(CUSTOM_ZIEL, it) }
        super.onSaveInstanceState(zustand)
    }

    override fun onStop() {
        entwurfSichern()
        super.onStop()
    }

    private fun entwurfSichern() {
        if ((application as MagnolieApp).startZustand.value == StartZustand.Bereit) {
            runCatching { Ablage.hole(this).sichereEntwurf() }.onFailure {
                Toast.makeText(this, fehlertext(it), Toast.LENGTH_LONG).show()
            }
        }
    }

    companion object {
        /** Über welche Aufgabe die Benachrichtigung sprach. */
        const val ZEIGE_AUFGABE = "zeige_aufgabe"
        private const val QR_LINK_VERBRAUCHT = "qr_link_verbraucht"
        private const val QR_PAARUNG = "qr_paarung"
        private const val QR_PAARUNG_BESTAETIGT = "qr_paarung_bestaetigt"
        private const val CUSTOM_ZIEL = "custom_ziel"
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
        StartZustand.Bereit -> Hauptblatt(gewuenschteAufgabe, gewuenschtesCustom)
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

class PortableExportVertrag : ActivityResultContract<String, Uri?>() {
    override fun createIntent(context: Context, input: String) =
        Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "application/vnd.magnolie.notes-backup"
            putExtra(Intent.EXTRA_TITLE, input)
        }
    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        intent?.data?.takeIf { resultCode == android.app.Activity.RESULT_OK }
}

@Composable
private fun Hauptblatt(gewuenschteAufgabe: androidx.compose.runtime.MutableState<String?>,
                      gewuenschtesCustom: androidx.compose.runtime.MutableState<Intent?>) {
    val zusammenhang = LocalContext.current
    val ablage = remember { Ablage.hole(zusammenhang) }
    val werk = remember { Baumwerk.hole(zusammenhang) }
    val journal = remember { AndroidJournal.hole(zusammenhang) }
    val autoSicherung = remember { AndroidAutoSicherung.hole(zusammenhang) }
    val telefonWerk = remember { TelefonWerk.get(zusammenhang) }
    val faden = rememberCoroutineScope()

    val bestand by ablage.bestand.collectAsState()
    val baumzustand by werk.zustand.collectAsState()
    val meldungen by werk.meldungen.collectAsState()
    val journalZustand by journal.state.collectAsState()
    val autoSicherungsZustand by autoSicherung.zustand.collectAsState()
    val telefonZustand by telefonWerk.state.collectAsState()

    var blatt by rememberSaveable { mutableStateOf(0) }
    val entwurf by ablage.entwurf.collectAsState()
    val offeneNotiz = entwurf.notiz
    val offeneAufgabe = entwurf.aufgabe
    var editorSpeichert by remember { mutableStateOf(false) }
    var anhangZiel by rememberSaveable { mutableStateOf<String?>(null) }
    var anhangSpeicherZiel by rememberSaveable { mutableStateOf<String?>(null) }
    var anhangEreignis by remember { mutableStateOf<AnhangEreignis?>(null) }

    val customAnfrage = gewuenschtesCustom.value
    val customZiel = CustomNavigation.ziel(zusammenhang, customAnfrage, bestand.personalCustom, telefonZustand.peer)
    LaunchedEffect(customAnfrage, customZiel, entwurf) {
        if (customAnfrage != null && customZiel == null) gewuenschtesCustom.value = null
        // Keep both the editor and the request until the user finishes the draft.
        // Revalidate on every content/consent change; a withdrawn target is consumed, not revived.
        else if (customZiel != null && entwurf == io.gitlab.maik3531.magnolienotes.daten.EditorEntwurf()) blatt = 3
    }

    // Kommt die App aus einer Erinnerung, wird die gemeinte Aufgabe geöffnet.
    val gewuenscht = gewuenschteAufgabe.value
    if (gewuenscht != null) {
        androidx.compose.runtime.LaunchedEffect(gewuenscht) {
            if (entwurf == io.gitlab.maik3531.magnolienotes.daten.EditorEntwurf())
                ablage.aufgabe(gewuenscht)?.let { ablage.setzeAufgabenEntwurf(it); blatt = 1 }
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
    var kontaktImportZweig by remember { mutableStateOf<String?>(null) }
    var kontaktImportVorschau by remember { mutableStateOf<KontaktImportVorschau?>(null) }
    var portableExportPasswort by remember { mutableStateOf<String?>(null) }
    var portableExportZiel by rememberSaveable { mutableStateOf<String?>(null) }
    var exportPasswortErneut by remember { mutableStateOf("") }
    var portableImportUri by remember { mutableStateOf<Uri?>(null) }
    var portableGeprueft by remember { mutableStateOf<GeprueftesPortableArchiv?>(null) }
    var portableLaeuft by remember { mutableStateOf(false) }
    var portableFehler by remember { mutableStateOf(false) }

    fun sage(text: String) = Toast.makeText(zusammenhang, text, Toast.LENGTH_LONG).show()

    LaunchedEffect(entwurf) {
        delay(250)
        withContext(Dispatchers.IO) { runCatching { ablage.sichereEntwurf() } }
            .onFailure { sage(zusammenhang.fehlertext(it)) }
    }

    fun editorAktion(aktion: () -> Unit) {
        if (editorSpeichert) return
        editorSpeichert = true
        faden.launch {
            try {
                val ergebnis = withContext(Dispatchers.IO) { runCatching(aktion) }
                ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                if (ergebnis.isSuccess) faden.launch(Dispatchers.IO) { runCatching { werk.postfachAbarbeiten() } }
            } finally { editorSpeichert = false }
        }
    }

    fun bluetoothErlaubt(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
        zusammenhang.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) ==
        PackageManager.PERMISSION_GRANTED

    val bluetoothFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { erlaubt ->
        if (erlaubt) {
            faden.launch {
                bluetoothGeraete = withContext(Dispatchers.IO) {
                    BaumDienst.starten(zusammenhang, bluetooth = true)
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
    var identifierPermissionToken by remember { mutableStateOf("") }
    val identifierPermission = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()) { granted ->
        telefonWerk.completeIdentifierPermission(identifierPermissionToken, granted)
        identifierPermissionToken = ""
    }
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
    fun kontakteLesbar() =
        zusammenhang.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED
    fun kontakteSchreibbar() = kontakteLesbar() &&
        zusammenhang.checkSelfPermission(Manifest.permission.WRITE_CONTACTS) == PackageManager.PERMISSION_GRANTED

    fun kontaktLauf(kennung: String) {
        faden.launch {
            val ergebnis = withContext(Dispatchers.IO) { runCatching { werk.kontakteSynchronisieren(kennung) } }
            ergebnis.onSuccess { sage(zusammenhang.getString(R.string.baum_kontakte_eingereiht)) }
            ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
        }
    }

    val kontaktSchreibFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
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

    fun mitKontaktSchreibfreigabe(handlung: () -> Unit) {
        if (kontakteSchreibbar()) handlung() else {
            kontaktNachFreigabe = handlung
            kontaktSchreibFreigabe.launch(arrayOf(
                Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS))
        }
    }

    fun kontaktImportVorschauLaden(kennung: String) {
        faden.launch {
            val ergebnis = withContext(Dispatchers.IO) { runCatching { werk.kontaktImportVorschau(kennung) } }
            ergebnis.onSuccess { kontaktImportVorschau = it }
            ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
        }
    }
    val kontaktLeseFreigabe = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()) { erlaubt ->
        val kennung = kontaktImportZweig
        kontaktImportZweig = null
        if (erlaubt && kennung != null) kontaktImportVorschauLaden(kennung)
        else sage(zusammenhang.getString(R.string.baum_kontakte_berechtigung))
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

    fun portableExportieren(ziel: Uri, passwort: String) {
        portableLaeuft = true
        faden.launch {
            val ergebnis = withContext(Dispatchers.IO) { runCatching {
                val geheim = passwort.toCharArray()
                try {
                    val bytes = PortableArchiv.erstellen(ablage.bestand.value, geheim)
                    val erwartet = io.gitlab.maik3531.magnolienotes.daten.ArchivIdentitaet(bytes)
                    try { zusammenhang.contentResolver.openOutputStream(ziel, "w")?.use { it.write(bytes) }
                        ?: error("Datei kann nicht geoeffnet werden") } finally { bytes.fill(0) }
                    val rueckgelesen = liesPortableArchiv(zusammenhang, ziel)
                    try { erwartet.pruefen(rueckgelesen); PortableArchiv.pruefen(rueckgelesen, geheim) }
                    finally { rueckgelesen.fill(0) }
                } catch (fehler: Exception) {
                    runCatching { zusammenhang.contentResolver.delete(ziel, null, null) }
                    throw fehler
                } finally { geheim.fill('\u0000') }
            } }
            portableLaeuft = false
            portableFehler = ergebnis.isFailure
            sage(zusammenhang.getString(if (ergebnis.isSuccess) R.string.portable_exportiert
                else R.string.portable_fehler))
        }
    }
    val portableExport = androidx.activity.compose.rememberLauncherForActivityResult(
        PortableExportVertrag()) { ziel ->
        val passwort = portableExportPasswort
        portableExportPasswort = null
        if (ziel != null) {
            if (passwort == null) portableExportZiel = ziel.toString()
            else portableExportieren(ziel, passwort)
        }
    }
    portableExportZiel?.let { ziel ->
        AlertDialog(onDismissRequest = { portableExportZiel = null; exportPasswortErneut = "" },
            title = { Text(stringResource(R.string.portable_export)) },
            text = { io.gitlab.maik3531.magnolienotes.ui.Schreibfeld(exportPasswortErneut,
                stringResource(R.string.portable_passwort), { exportPasswortErneut = it.take(1024) }, passwort = true) },
            confirmButton = { TextButton(enabled = exportPasswortErneut.isNotEmpty(), onClick = {
                val geheim = exportPasswortErneut
                portableExportZiel = null; exportPasswortErneut = ""
                portableExportieren(Uri.parse(ziel), geheim)
            }) { Text(stringResource(R.string.portable_export)) } },
            dismissButton = { TextButton(onClick = { portableExportZiel = null; exportPasswortErneut = "" }) {
                Text(stringResource(R.string.abbrechen)) } })
    }
    val portableImport = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()) { quelle ->
        portableImportUri = quelle
        portableGeprueft = null
        portableFehler = false
    }

    val autoSicherungsOrdner = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { baum ->
        if (baum != null) runCatching { autoSicherung.ordnerSetzen(baum) }
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
            val aktuell = ablage.entwurf.value.notiz
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
                    ablage.setzeNotizEntwurf(aktuell.copy(anhaenge = neu))
                    anhangEreignis = AnhangEreignis(ziel, anhang)
                }
            }
        }
    }

    val anhangSpeicher = androidx.activity.compose.rememberLauncherForActivityResult(
        AnhangSpeichernVertrag()
    ) { ziel ->
        val anhang = ablage.entwurf.value.notiz?.anhaenge?.firstOrNull { it.id == anhangSpeicherZiel }
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
                        ?.use { io.gitlab.maik3531.magnolienotes.baum.Paarung.liesDatei(it) }
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
            alleAufgaben = bestand.aufgaben,
            partnernamen = bestaetigte,
            beiEntwurf = { if (!editorSpeichert) ablage.setzeAufgabenEntwurf(it) },
            speichert = editorSpeichert,
            beiSichern = { geaendert ->
                val erwartet = ablage.entwurf.value
                editorAktion {
                    val gesichert = ablage.sichereAufgabe(erwartet.aufgabe?.takeIf { it.id == geaendert.id } ?: geaendert)
                    Erinnerung.stellen(zusammenhang, gesichert)
                    ablage.beendeEntwurf(erwartet)
                }
            },
            beiLoeschen = {
                val erwartet = entwurf
                editorAktion {
                    Erinnerung.abbestellen(zusammenhang, offeneA.id)
                    ablage.loescheAufgabe(offeneA.id)
                    ablage.beendeEntwurf(erwartet)
                }
            },
            beiWeitergeben = { kennungen ->
                editorAktion {
                    val gesichert = ablage.sichereAufgabe(offeneA)
                    Erinnerung.stellen(zusammenhang, gesichert)
                    val geteilt = werk.teileAufgabe(gesichert, kennungen, sofortSenden = false)
                    ablage.setzeAufgabenEntwurf(geteilt)
                    ablage.sichereEntwurf()
                }
            }
        )
        return
    }

    val offen = offeneNotiz
    if (offen != null) {
        NotizEditor(
            notiz = offen,
            partnernamen = bestaetigte,
            beiEntwurf = { if (!editorSpeichert) ablage.setzeNotizEntwurf(it) },
            speichert = editorSpeichert,
            beiSichern = { geaendert ->
                val erwartet = ablage.entwurf.value
                editorAktion {
                    val gesichert = ablage.sichereNotiz(erwartet.notiz?.takeIf { it.id == geaendert.id } ?: geaendert)
                    werk.notizFortschreiben(gesichert, sofortSenden = false)
                    ablage.beendeEntwurf(erwartet)
                }
            },
            beiLoeschen = {
                val erwartet = entwurf
                editorAktion { ablage.loescheNotiz(offen.id); ablage.beendeEntwurf(erwartet) }
            },
            beiTeilen = { kennungen ->
                editorAktion {
                    val gesichert = ablage.sichereNotiz(offen)
                    val geteilt = werk.teileNotiz(gesichert, kennungen, sofortSenden = false)
                    ablage.setzeNotizEntwurf(geteilt)
                    ablage.sichereEntwurf()
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
                        anhangSpeicherZiel = anhang.id
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
                val current = ablage.entwurf.value.notiz?.takeIf { it.id == offen.id }
                val removed = current?.anhaenge?.filter { old -> anhaenge.none { it.id == old.id } }.orEmpty()
                if (removed.size == 1) {
                    ablage.loescheAnhang(offen.id, removed.single().id)
                }
                current?.let { ablage.setzeNotizEntwurf(it.copy(anhaenge = anhaenge)) }
            }
        )
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
                    beiOeffnen = ablage::setzeNotizEntwurf,
                    beiNeu = {
                        ablage.setzeNotizEntwurf(Notiz(
                            id = Ablage.kennung(),
                            angelegt = System.currentTimeMillis(),
                            geaendert = System.currentTimeMillis()
                        ))
                    }
                )

                1 -> AufgabenBlatt(
                    aufgaben = bestand.aufgaben,
                    beiOeffnen = ablage::setzeAufgabenEntwurf,
                    beiAbhaken = { aufgabe, erledigt ->
                        faden.launch {
                            withContext(Dispatchers.IO) {
                                werk.aufgabeAbhaken(aufgabe.id, erledigt)
                            }
                        }
                    },
                    beiNeu = {
                        val id = Ablage.kennung()
                        ablage.setzeAufgabenEntwurf(Aufgabe(
                            id = id, uid = AufgabenHierarchie.stabileUid(id),
                            angelegt = System.currentTimeMillis(),
                            geaendert = System.currentTimeMillis()
                        ))
                    },
                    beiTeilaufgabe = { parent ->
                        val id = Ablage.kennung()
                        ablage.setzeAufgabenEntwurf(Aufgabe(id = id, uid = AufgabenHierarchie.stabileUid(id),
                            elternUid = parent.uid,
                            reihenfolge = bestand.aufgaben.count { it.elternUid == parent.uid },
                            angelegt = System.currentTimeMillis(), geaendert = System.currentTimeMillis()))
                    },
                    beiVerschieben = { aufgabe, delta -> ablage.verschiebeAufgabe(aufgabe.uid, delta) },
                    beiWurzel = { aufgabe -> ablage.setzeAufgabenEltern(aufgabe.uid, "") }
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
                    customFokus = customZiel,
                    beiCustomFokus = { if (gewuenschtesCustom.value === customAnfrage) gewuenschtesCustom.value = null },
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
                        beiRechner = telefonWerk::selectComputer,
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
                                if (identifierPermissionToken.isEmpty() && telefonFreigabeZiel.isEmpty()) {
                                    telefonFreigabeZiel = "dial"; telefonFreigabe.launch(arrayOf(
                                        Manifest.permission.CALL_PHONE, Manifest.permission.READ_PHONE_STATE))
                                }
                            } else telefonWerk.setDialRequestEnabled(enabled)
                        },
                        beiEingehendenAnrufen = { enabled ->
                            if (enabled && zusammenhang.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
                                if (identifierPermissionToken.isEmpty() && telefonFreigabeZiel.isEmpty()) {
                                    telefonFreigabeZiel = "incoming"; telefonFreigabe.launch(arrayOf(Manifest.permission.READ_PHONE_STATE))
                                }
                            } else telefonWerk.setIncomingCallsEnabled(enabled)
                        },
                        beiAnrufernummer = { enabled ->
                            if (enabled && zusammenhang.checkSelfPermission(Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED) {
                                if (identifierPermissionToken.isEmpty() && telefonFreigabeZiel.isEmpty()) {
                                    telefonFreigabeZiel = "number"; telefonFreigabe.launch(arrayOf(Manifest.permission.READ_CALL_LOG))
                                }
                            } else telefonWerk.setIncomingNumberEnabled(enabled)
                        },
                        beiAnnehmen = { enabled ->
                            if (enabled && zusammenhang.checkSelfPermission(Manifest.permission.ANSWER_PHONE_CALLS) != PackageManager.PERMISSION_GRANTED) {
                                if (identifierPermissionToken.isEmpty() && telefonFreigabeZiel.isEmpty()) {
                                    telefonFreigabeZiel = "answer"; telefonFreigabe.launch(arrayOf(Manifest.permission.ANSWER_PHONE_CALLS))
                                }
                            } else telefonWerk.setAnswerCallsEnabled(enabled)
                        },
                        beiBenachrichtigungszugriff = {
                            zusammenhang.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                        },
                        beiBenachrichtigungsApp = { paket ->
                            faden.launch(Dispatchers.IO) {
                                runCatching { telefonWerk.toggleNotificationPackage(paket) }.onFailure {
                                    withContext(Dispatchers.Main) { sage(zusammenhang.fehlertext(it)) }
                                }
                            }
                        },
                        beiIdentifierSharing = { enabled ->
                            if (!enabled) telefonWerk.setIdentifierSharingEnabled(false)
                            else if (telefonFreigabeZiel.isEmpty() && identifierPermissionToken.isEmpty()) {
                                if (zusammenhang.checkSelfPermission(Manifest.permission.READ_PHONE_NUMBERS) == PackageManager.PERMISSION_GRANTED)
                                    telefonWerk.setIdentifierSharingEnabled(true)
                                else telefonWerk.beginIdentifierPermission()?.let { token ->
                                    identifierPermissionToken = token
                                    identifierPermission.launch(Manifest.permission.READ_PHONE_NUMBERS)
                                }
                            }
                        },
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
                        beiPersonalEntscheidung = telefonWerk::personalDeletionDecision,
                        beiCustomSync = { runCatching { telefonWerk.setCustomSync(it) }
                            .onFailure { sage(zusammenhang.fehlertext(it)) } },
                        beiCustomEntscheidung = { id, revision, delete -> runCatching {
                            telefonWerk.customDeletionDecision(id, revision, delete)
                        }.onFailure { sage(zusammenhang.fehlertext(it)) } }
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
                                            BaumDienst.starten(zusammenhang, bluetooth = true)
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
                        beiKontaktSync = { kennung, an ->
                            if (an) mitKontaktSchreibfreigabe { werk.kontaktSyncSchalten(kennung, true) }
                            else werk.kontaktSyncSchalten(kennung, false)
                        },
                        beiKontaktLoeschSync = { kennung, an -> werk.kontaktLoeschSyncSchalten(kennung, an) },
                        beiKontaktVorschlag = { id ->
                            faden.launch { withContext(Dispatchers.IO) { werk.kontaktLoeschungSenden(id) } }
                        },
                        beiKontaktVorschlagAblehnen = { werk.kontaktVorschlagAblehnen(it) },
                        beiDubletteOeffnen = { werk.dubletteOeffnen(it) },
                        beiDubletteVerknuepfen = { id ->
                            mitKontaktSchreibfreigabe {
                                faden.launch { withContext(Dispatchers.IO) { werk.dubletteVerknuepfen(id) } }
                            }
                        },
                        beiKontaktGruppeImportieren = { id, getrennt ->
                            mitKontaktSchreibfreigabe {
                                faden.launch { withContext(Dispatchers.IO) { werk.kontaktGruppeImportieren(id, getrennt) } }
                            }
                        },
                        beiKontaktGruppeAblehnen = { werk.kontaktGruppeAblehnen(it) },
                        beiSichereKontaktGruppenImportieren = { partner ->
                            mitKontaktSchreibfreigabe {
                                faden.launch { withContext(Dispatchers.IO) { werk.sichereKontaktGruppenImportieren(partner) } }
                            }
                        },
                        beiAlleKontaktKartenAblehnen = { werk.alleKontaktKartenAblehnen(it) },
                        beiKontakteSynchronisieren = { kennung ->
                            if (kontakteSchreibbar()) kontaktLauf(kennung) else {
                                kontaktZweig = kennung
                                kontaktSchreibFreigabe.launch(arrayOf(
                                    Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS))
                            }
                        },
                        kontaktImportVorschau = kontaktImportVorschau,
                        beiKontaktImport = { kennung ->
                            if (kontakteLesbar()) kontaktImportVorschauLaden(kennung) else {
                                kontaktImportZweig = kennung
                                kontaktLeseFreigabe.launch(Manifest.permission.READ_CONTACTS)
                            }
                        },
                        beiKontaktImportBestaetigen = { id ->
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) {
                                    runCatching { werk.kontaktImportBestaetigen(id) }
                                }
                                kontaktImportVorschau = null
                                ergebnis.onSuccess { sage(zusammenhang.getString(R.string.baum_kontakte_eingereiht)) }
                                ergebnis.onFailure { sage(zusammenhang.fehlertext(it)) }
                            }
                        },
                        beiKontaktImportAbbrechen = {
                            werk.kontaktImportAbbrechen(); kontaktImportVorschau = null
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
                        beiBestaetigen = { kennung ->
                            runCatching { werk.bestaetigen(kennung) }
                                .onFailure { sage(zusammenhang.fehlertext(it)) }
                        },
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
                    beiMaximum = journal::maximumSetzen,
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
                    beiPapierkorbWiederherstellen = { id ->
                        faden.launch(Dispatchers.IO) {
                            runCatching {
                                if (ablage.papierkorbWiederherstellen(id)) Erinnerung.allesNeuStellen(zusammenhang)
                            }.onFailure { withContext(Dispatchers.Main) { sage(zusammenhang.fehlertext(it)) } }
                        }
                    },
                    beiPapierkorbLoeschen = ablage::papierkorbEndgueltig,
                    beiPapierkorbLeeren = ablage::papierkorbLeeren,
                    absturzberichtVorhanden = Absturzberichte.bericht(zusammenhang) != null,
                    beiAbsturzberichtTeilen = {
                        Absturzberichte.bericht(zusammenhang)?.let { bericht ->
                            val uri = FileProvider.getUriForFile(
                                zusammenhang, zusammenhang.packageName + ".dateien", bericht)
                            val teilen = Intent(Intent.ACTION_SEND).apply {
                                type = "text/plain"
                                putExtra(Intent.EXTRA_STREAM, uri)
                                putExtra(Intent.EXTRA_SUBJECT, bericht.name)
                                clipData = ClipData.newRawUri(bericht.name, uri)
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            zusammenhang.startActivity(Intent.createChooser(
                                teilen, zusammenhang.getString(R.string.absturzbericht_teilen)))
                        }
                    },
                    portableImportBereit = portableImportUri != null,
                    portableVorschau = portableGeprueft?.vorschau,
                    portableLaeuft = portableLaeuft,
                    portableFehler = portableFehler,
                    beiPortableExport = { passwort ->
                        portableExportPasswort = passwort
                        portableExport.launch("magnolie-notes-${LocalDate.now()}.magnolie")
                    },
                    beiPortableDatei = { portableImport.launch(arrayOf(
                        "application/vnd.magnolie.notes-backup", "application/octet-stream", "*/*")) },
                    beiPortablePruefen = { passwort ->
                        val quelle = portableImportUri
                        if (quelle != null) {
                            portableLaeuft = true; portableFehler = false
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) { runCatching {
                                    val bytes = liesPortableArchiv(zusammenhang, quelle)
                                    val geheim = passwort.toCharArray()
                                    try { PortableArchiv.pruefen(bytes, geheim) }
                                    finally { bytes.fill(0); geheim.fill('\u0000') }
                                } }
                                portableGeprueft = ergebnis.getOrNull()
                                portableFehler = ergebnis.isFailure
                                portableLaeuft = false
                            }
                        }
                    },
                    beiPortableWiederherstellen = {
                        val geprueft = portableGeprueft
                        if (geprueft != null) {
                            portableLaeuft = true
                            faden.launch {
                                val ergebnis = withContext(Dispatchers.IO) { runCatching {
                                    check(journal.restorePortable(
                                        geprueft, UUID.randomUUID().toString()))
                                } }
                                portableLaeuft = false
                                portableFehler = ergebnis.isFailure
                                if (ergebnis.isSuccess) {
                                    portableImportUri = null; portableGeprueft = null
                                    sage(zusammenhang.getString(R.string.portable_wiederhergestellt))
                                }
                            }
                        }
                    },
                    beiPortableAbbrechen = {
                        portableImportUri = null; portableGeprueft = null; portableFehler = false
                    },
                    autoSicherung = autoSicherungsZustand,
                    beiAutoOrdner = { autoSicherungsOrdner.launch(null) },
                    beiAutoPasswort = { autoSicherung.passwortSichern(it.toCharArray()) },
                    beiAutoAktiv = autoSicherung::aktiviertSetzen,
                    beiAutoIntervall = autoSicherung::intervallSetzen,
                    beiAutoAufbewahrung = autoSicherung::aufbewahrungSetzen,
                    beiAutoJetzt = autoSicherung::jetztTesten,
                ))
            }
        }
    }
}
