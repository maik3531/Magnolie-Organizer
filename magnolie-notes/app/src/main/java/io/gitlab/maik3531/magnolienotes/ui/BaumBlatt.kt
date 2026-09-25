package io.gitlab.maik3531.magnolienotes.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Switch
import androidx.compose.material3.Checkbox
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.TextButton
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.gitlab.maik3531.magnolienotes.R
import io.gitlab.maik3531.magnolienotes.baum.BluetoothZiel
import io.gitlab.maik3531.magnolienotes.baum.Gefunden
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Bestand
import io.gitlab.maik3531.magnolienotes.daten.PersonalDeletionDecisions
import io.gitlab.maik3531.magnolienotes.daten.PersonalDeletionPrompt
import io.gitlab.maik3531.magnolienotes.daten.PersonalDeletionProposal
import io.gitlab.maik3531.magnolienotes.baum.KontaktEingangslogik
import io.gitlab.maik3531.magnolienotes.baum.KontaktGruppenArt
import io.gitlab.maik3531.magnolienotes.baum.KontaktPruefung
import io.gitlab.maik3531.magnolienotes.baum.KontaktImportVorschau
import io.gitlab.maik3531.magnolienotes.telefon.TelefonUiZustand
import io.gitlab.maik3531.magnolienotes.telefon.TelefonVerbindungsstatus
import io.gitlab.maik3531.magnolienotes.telefon.GefundenerDesktop
import kotlinx.serialization.json.*

/** Alles, was das Baumblatt an Handlungen anbietet. */
class Baumhandlungen(
    val beiName: (String) -> Unit,
    val beiDienst: (Boolean) -> Unit,
    val beiBluetooth: (Boolean) -> Unit,
    val beiAutoWlan: (Boolean) -> Unit,
    val beiBluetoothZiel: (String, String) -> Unit,
    val beiFernziel: (String, String, Int) -> Unit,
    val beiAllesSynchronisieren: (String) -> Unit,
    val beiKontaktSync: (String, Boolean) -> Unit,
    val beiKontakteSynchronisieren: (String) -> Unit,
    val kontaktImportVorschau: KontaktImportVorschau?,
    val beiKontaktImport: (String) -> Unit,
    val beiKontaktImportBestaetigen: (String) -> Unit,
    val beiKontaktImportAbbrechen: () -> Unit,
    val beiKontaktLoeschSync: (String, Boolean) -> Unit,
    val beiKontaktVorschlag: (String) -> Unit,
    val beiKontaktVorschlagAblehnen: (String) -> Unit,
    val beiDubletteOeffnen: (String) -> Unit,
    val beiDubletteVerknuepfen: (String) -> Unit,
    val beiKontaktGruppeImportieren: (String, Boolean) -> Unit,
    val beiKontaktGruppeAblehnen: (String) -> Unit,
    val beiSichereKontaktGruppenImportieren: (String) -> Unit,
    val beiAlleKontaktKartenAblehnen: (String) -> Unit,
    val beiPaarungsdatei: () -> Unit,
    val beiPaarungstext: (String) -> Unit,
    val beiEigeneDatei: () -> Unit,
    val beiSuchen: () -> Unit,
    val beiAnfragen: (Gefunden) -> Unit,
    val beiBestaetigen: (String) -> Unit,
    val beiEntfernen: (String) -> Unit,
    val beiSenden: () -> Unit,
    val beiVertrauen: (String, Boolean) -> Unit,
    val beiEingangAnnehmen: (String) -> Unit,
    val beiEingangAblehnen: (String) -> Unit,
    val beiMeldungenLeeren: () -> Unit
)

class Telefonhandlungen(
    val beiDienst: (Boolean) -> Unit,
    val beiSuchen: () -> Unit,
    val beiVerbinden: (GefundenerDesktop) -> Unit,
    val beiCode: (Boolean) -> Unit,
    val beiEntkoppeln: (io.gitlab.maik3531.magnolienotes.telefon.TelefonPeer?) -> Unit,
    val beiRechner: (String?) -> Unit,
    val beiBluetooth: (Boolean) -> Unit,
    val beiBluetoothEinstellungen: () -> Unit,
    val beiBluetoothGeraete: () -> Unit,
    val beiBluetoothZiel: (String) -> Unit,
    val beiWaehlauftrag: (Boolean) -> Unit,
    val beiEingehendenAnrufen: (Boolean) -> Unit,
    val beiAnrufernummer: (Boolean) -> Unit,
    val beiAnnehmen: (Boolean) -> Unit,
    val beiBenachrichtigungszugriff: () -> Unit,
    val beiBenachrichtigungsApp: (String) -> Unit,
    val beiPersonalEigen: (Boolean) -> Unit,
    val beiIdentifierSharing: (Boolean) -> Unit,
    val beiPersonalNotizen: (Boolean) -> Unit,
    val beiPersonalAufgaben: (Boolean) -> Unit,
    val beiPersonalAutoWlan: (Boolean) -> Unit,
    val beiPersonalLoeschungen: (Boolean) -> Unit,
    val beiPersonalJetzt: () -> Unit,
    val beiPersonalEntscheidung: (String, String) -> String,
    val beiCustomSync: (Boolean) -> Unit,
    val beiCustomEntscheidung: (String, Long, Boolean) -> Unit
)

@Composable
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
fun BaumBlatt(
    zustand: Baumzustand,
    bestand: Bestand,
    customFokus: String?,
    beiCustomFokus: () -> Unit,
    fingerabdruck: String,
    gefunden: List<Gefunden>,
    bluetoothGeraete: List<BluetoothZiel>,
    sucheLaeuft: Boolean,
    meldungen: List<String>,
    handlungen: Baumhandlungen,
    telefon: TelefonUiZustand,
    telefonHandlungen: Telefonhandlungen,
    modifier: Modifier = Modifier
) {
    var telefonAppsOffen by remember { mutableStateOf(false) }
    var name by remember(zustand.name) { mutableStateOf(zustand.name) }
    var eingefuegt by remember { mutableStateOf("") }
    var loeschWarnung by remember { mutableStateOf<String?>(null) }
    var entfernenWarnung by remember { mutableStateOf<String?>(null) }
    val peerScope = telefon.peer?.let { it.device_id + ":" + it.static_public }
    val activeProposals = bestand.personalSync.pending_proposals.filter { it.source_device == telefon.peer?.device_id }
    var telefonEntfernenWarnung by remember(peerScope) { mutableStateOf(false) }
    val personalDecisions = remember(peerScope) { PersonalDeletionDecisions() }
    var personalProposal by remember(peerScope) { mutableStateOf<PersonalDeletionProposal?>(null) }
    var personalRemember by remember(peerScope) { mutableStateOf(false) }
    var massDecision by remember(peerScope) { mutableStateOf<Pair<String, List<PersonalDeletionProposal>>?>(null) }
    var changedDelete by remember(peerScope) { mutableStateOf<PersonalDeletionProposal?>(null) }
    var customDelete by remember(peerScope) { mutableStateOf<Pair<String, Long>?>(null) }

    customDelete?.let { (id, revision) ->
        AlertDialog(onDismissRequest = { customDelete = null },
            title = { Text(stringResource(R.string.personal_custom_title)) },
            text = { Column {
                Text(stringResource(R.string.personal_custom_delete))
                bestand.personalCustom.items[id]?.let { item ->
                    item.record["value"]?.jsonObject?.get("title")?.jsonPrimitive?.content?.let { Text(it) }
                    if (item.deletion?.get("prior_hash") != item.record["hash"])
                        Text(stringResource(R.string.personal_sync_geaendert_titel), fontWeight = FontWeight.Bold)
                }
            } },
            confirmButton = { TextButton(onClick = { telefonHandlungen.beiCustomEntscheidung(id, revision, true); customDelete = null }) {
                Text(stringResource(R.string.loeschen)) } },
            dismissButton = { TextButton(onClick = { telefonHandlungen.beiCustomEntscheidung(id, revision, false); customDelete = null }) {
                Text(stringResource(R.string.personal_custom_keep)) } })
    }

    fun applyPersonal(decision: String, proposals: List<PersonalDeletionProposal>) {
        proposals.forEach { telefonHandlungen.beiPersonalEntscheidung(it.proposal_id, decision) }
        proposals.map { it.run_id }.distinct().forEach { runId ->
            if (bestand.personalSync.pending_proposals.none { it.run_id == runId }) personalDecisions.resolveRun(runId)
        }
    }

    fun requestMass(decision: String, proposals: List<PersonalDeletionProposal>) {
        val normal = proposals.filter { personalDecisions.prompt(bestand, it) in
            setOf(PersonalDeletionPrompt.NORMAL, PersonalDeletionPrompt.REMEMBERED) }
        val live = bestand.personalSync.entities.values.count { it.state == "live" && it.acknowledged_by_peer }
        if (personalDecisions.needsMassConfirmation(normal.size, live)) massDecision = decision to normal
        else applyPersonal(decision, normal)
    }

    Column(
        modifier.fillMaxSize().background(Magnolie.papier).verticalScroll(rememberScrollState())
    ) {
        Abschnitt(
            ueberschrift = stringResource(R.string.telefon_titel),
            hinweis = stringResource(R.string.telefon_hinweis)
        ) {
            Schalterzeile(
                beschriftung = stringResource(R.string.telefon_hauptschalter),
                an = telefon.enabled,
                beiAenderung = telefonHandlungen.beiDienst
            )
            val verbindungsstatus = when (telefon.connection) {
                TelefonVerbindungsstatus.STOPPED -> stringResource(R.string.telefon_status_aus)
                TelefonVerbindungsstatus.PAIRED -> stringResource(R.string.telefon_status_gepaart)
                TelefonVerbindungsstatus.DISCOVERING -> stringResource(R.string.telefon_dienst_sucht)
                TelefonVerbindungsstatus.HANDSHAKING, TelefonVerbindungsstatus.AUTHENTICATING ->
                    stringResource(R.string.telefon_dienst_verbindet, telefon.pairingName)
                TelefonVerbindungsstatus.CODE_PENDING -> stringResource(R.string.telefon_status_code)
                TelefonVerbindungsstatus.ONLINE_WIFI -> stringResource(R.string.telefon_dienst_wlan,
                    telefon.peer?.display_name.orEmpty())
                TelefonVerbindungsstatus.ONLINE_BLUETOOTH -> stringResource(R.string.telefon_dienst_bluetooth,
                    telefon.peer?.display_name.orEmpty())
                TelefonVerbindungsstatus.ERROR -> stringResource(R.string.telefon_status_fehler)
                else -> stringResource(R.string.telefon_status_getrennt)
            }
            Wertzeile(stringResource(R.string.telefon_status), verbindungsstatus)
            if (telefon.enabled && telefon.connection != TelefonVerbindungsstatus.CODE_PENDING) {
                telefon.pairedComputers.filter { it.device_id != telefon.peer?.device_id }.forEach { computer ->
                    Papierknopf(stringResource(R.string.telefon_verbinden, computer.display_name), modifier = Modifier.fillMaxWidth()) {
                        telefonHandlungen.beiRechner(computer.device_id)
                    }
                }
                if (telefon.peer != null) Papierknopf(stringResource(R.string.telefon_rechner_hinzufuegen), modifier = Modifier.fillMaxWidth()) {
                    telefonHandlungen.beiRechner(null)
                }
            }
            if (telefon.enabled && telefon.peer == null) {
                if (telefon.connection != TelefonVerbindungsstatus.CODE_PENDING)
                    io.gitlab.maik3531.magnolienotes.telefon.TelefonEinladungsDialog(telefonHandlungen.beiVerbinden)
                if (telefon.connection != TelefonVerbindungsstatus.CODE_PENDING)
                    io.gitlab.maik3531.magnolienotes.telefon.TelefonBluetoothSetupDialog()
                telefon.found.forEach { desktop ->
                    Lederknopf(stringResource(R.string.telefon_verbinden,
                        desktop.name.ifBlank { desktop.deviceId }), modifier = Modifier.fillMaxWidth()) {
                        telefonHandlungen.beiVerbinden(desktop)
                    }
                }
                Papierknopf(stringResource(R.string.telefon_suchen), modifier = Modifier.fillMaxWidth(),
                    beiKlick = telefonHandlungen.beiSuchen)
            }
            if (telefon.connection == TelefonVerbindungsstatus.CODE_PENDING) {
                Text(telefon.pairingCode, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold,
                    fontSize = 22.sp, color = Magnolie.rot)
                Text("${telefon.pairingName} · ${telefon.pairingFingerprint}", fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp, color = Magnolie.braunHell)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Lederknopf(stringResource(R.string.telefon_code_stimmt)) { telefonHandlungen.beiCode(true) }
                    Papierknopf(stringResource(R.string.telefon_code_falsch)) { telefonHandlungen.beiCode(false) }
                }
            }
            telefon.peer?.let { peer ->
                Wertzeile(stringResource(R.string.telefon_kopplung), peer.display_name)
                Wertzeile(stringResource(R.string.telefon_geraetestatus),
                    if (peer.device_status_granted) stringResource(R.string.telefon_freigegeben)
                    else stringResource(R.string.telefon_nicht_freigegeben))
                Text(stringResource(R.string.telefon_mehrere_rechner), fontFamily = FontFamily.SansSerif,
                    fontSize = 11.sp, lineHeight = 16.sp, color = Magnolie.braunHell)
                Papierknopf(stringResource(R.string.telefon_entkoppeln), modifier = Modifier.fillMaxWidth(),
                    beiKlick = { telefonEntfernenWarnung = true })
            }
            if (telefon.error.isNotBlank()) Text(telefon.error, color = Magnolie.rot,
                fontFamily = FontFamily.SansSerif, fontSize = 11.sp)

            Papierknopf(stringResource(R.string.telefon_bluetooth_systempaarung), modifier = Modifier.fillMaxWidth(),
                beiKlick = telefonHandlungen.beiBluetoothEinstellungen)
            Schalterzeile(stringResource(R.string.telefon_bluetooth_fallback), telefon.bluetoothEnabled,
                telefonHandlungen.beiBluetooth)
            Text(stringResource(R.string.telefon_bluetooth_hinweis), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, lineHeight = 16.sp, color = Magnolie.braunHell)
            if (telefon.bluetoothEnabled && telefon.peer != null) {
                Papierknopf(stringResource(R.string.telefon_bluetooth_geraete), modifier = Modifier.fillMaxWidth(),
                    beiKlick = telefonHandlungen.beiBluetoothGeraete)
                telefon.bluetoothDevices.forEach { device ->
                    Lederknopf(stringResource(R.string.telefon_bluetooth_verwenden,
                        device.name.ifBlank { device.address }), modifier = Modifier.fillMaxWidth()) {
                        telefonHandlungen.beiBluetoothZiel(device.address)
                    }
                }
            }
            Text(stringResource(R.string.telefon_benachrichtigungen_titel), fontFamily = FontFamily.SansSerif,
                fontWeight = FontWeight.Bold, color = Magnolie.braun)
            Papierknopf(stringResource(if (telefon.notificationAccess) R.string.telefon_systemzugriff_erteilt
                else R.string.telefon_systemzugriff_oeffnen), modifier = Modifier.fillMaxWidth(),
                beiKlick = telefonHandlungen.beiBenachrichtigungszugriff)
            Papierknopf("${stringResource(R.string.telefon_apps_titel)} (${telefon.selectedPackages.size}) ${if (telefonAppsOffen) "▲" else "▼"}",
                modifier = Modifier.fillMaxWidth()) { telefonAppsOffen = !telefonAppsOffen }
            if (telefonAppsOffen) {
                telefon.notificationApps.forEach { app ->
                    Schalterzeile(app.label, app.packageName in telefon.selectedPackages) {
                        telefonHandlungen.beiBenachrichtigungsApp(app.packageName)
                    }
                }
            }
            Text(stringResource(R.string.telefon_benachrichtigungen_hinweis), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, lineHeight = 16.sp, color = Magnolie.braunHell)

            Text(stringResource(R.string.telefon_eingehend_titel), fontFamily = FontFamily.SansSerif,
                fontWeight = FontWeight.Bold, color = Magnolie.braun)
            Schalterzeile(stringResource(R.string.telefon_waehlen_schalter), telefon.dialRequestEnabled,
                telefonHandlungen.beiWaehlauftrag)
            Text(stringResource(if (telefon.dialAvailable) R.string.telefon_waehlen_hinweis
                else R.string.telefon_waehlen_nicht_verfuegbar), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, lineHeight = 16.sp, color = Magnolie.braunHell)
            Schalterzeile(stringResource(R.string.telefon_eingehend_schalter), telefon.incomingCallsEnabled,
                telefonHandlungen.beiEingehendenAnrufen)
            Schalterzeile(stringResource(R.string.telefon_nummer_schalter), telefon.incomingNumberEnabled,
                telefonHandlungen.beiAnrufernummer)
            Schalterzeile(stringResource(R.string.telefon_annehmen_schalter), telefon.answerCallsEnabled,
                telefonHandlungen.beiAnnehmen)
            Text(stringResource(R.string.telefon_eingehend_hinweis), fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp, lineHeight = 16.sp, color = Magnolie.braunHell)
        }
        Abschnitt(
            ueberschrift = stringResource(R.string.personal_sync_titel),
            hinweis = stringResource(R.string.personal_sync_hinweis)
        ) {
            Text(stringResource(R.string.personal_sync_nicht_baum), fontFamily = FontFamily.SansSerif,
                fontWeight = FontWeight.Bold, color = Magnolie.braun)
            LaunchedEffect(telefon.peer?.device_id, telefon.personalOwnDevice) {
                if (telefon.peer?.state == "paired" && !telefon.personalOwnDevice)
                    telefonHandlungen.beiPersonalEigen(true)
            }
            if (telefon.personalOwnDevice) {
                Schalterzeile(stringResource(R.string.device_identifiers_share), telefon.peer?.identifier_sharing_enabled == true,
                    telefonHandlungen.beiIdentifierSharing)
                Text(stringResource(R.string.device_identifiers_explanation), fontSize = 12.sp)
            }
            Schalterzeile(stringResource(R.string.personal_sync_notizen), telefon.personalNotesEnabled,
                telefonHandlungen.beiPersonalNotizen)
            Schalterzeile(stringResource(R.string.personal_sync_aufgaben), telefon.personalTasksEnabled,
                telefonHandlungen.beiPersonalAufgaben)
            val customSupported = telefon.peer?.remote_personal_tasks_sync_available == true && 4 in (telefon.peer?.remote_personal_tasks_sync_versions ?: emptyList()) &&
                4 in io.gitlab.maik3531.magnolienotes.telefon.TelefonCapabilities.phase1().getValue("personal_tasks_sync").versions
            if (customSupported) Schalterzeile(stringResource(R.string.personal_custom_optin),
                bestand.personalCustom.local?.get("enabled")?.jsonPrimitive?.booleanOrNull == true, telefonHandlungen.beiCustomSync)
            else Text(stringResource(R.string.personal_custom_unsupported), fontSize = 12.sp)
            Text(stringResource(R.string.personal_custom_explanation), fontSize = 12.sp)
            Text(stringResource(R.string.personal_custom_privacy), fontSize = 12.sp)
            if (bestand.personalCustom.local?.get("enabled")?.jsonPrimitive?.booleanOrNull == true &&
                bestand.personalCustom.remote?.get("enabled")?.jsonPrimitive?.booleanOrNull != true)
                Text(stringResource(R.string.baum_wartet), fontSize = 12.sp)
            Schalterzeile(stringResource(R.string.personal_sync_auto_wlan), telefon.personalAutoWifi,
                telefonHandlungen.beiPersonalAutoWlan)
            Schalterzeile(stringResource(R.string.personal_sync_loeschungen), telefon.personalDeletionsEnabled,
                telefonHandlungen.beiPersonalLoeschungen)
            Lederknopf(stringResource(R.string.personal_sync_jetzt), modifier = Modifier.fillMaxWidth(),
                aktiv = telefon.personalOwnDevice && telefon.peer?.remote_own_device == true &&
                    ((telefon.personalNotesEnabled && telefon.peer?.remote_personal_notes_sync_granted == true) ||
                        (telefon.personalTasksEnabled && telefon.peer?.remote_personal_tasks_sync_granted == true) ||
                        (customSupported && bestand.personalCustom.local?.get("enabled")?.jsonPrimitive?.booleanOrNull == true &&
                            bestand.personalCustom.remote?.get("enabled")?.jsonPrimitive?.booleanOrNull == true)),
                beiKlick = telefonHandlungen.beiPersonalJetzt)
            Text(telefon.personalSyncReport.ifBlank { stringResource(R.string.personal_sync_keine_loeschung) },
                fontFamily = FontFamily.SansSerif, fontSize = 11.sp, lineHeight = 16.sp, color = Magnolie.braunHell)
            if (activeProposals.isNotEmpty()) Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Papierknopf(stringResource(R.string.personal_sync_alle_loeschen)) {
                    requestMass("delete", activeProposals) }
                Papierknopf(stringResource(R.string.personal_sync_alle_wiederherstellen)) {
                    requestMass("restore", activeProposals) }
            }
            activeProposals.forEach { proposal ->
                Text("${lokalisierterText(TechnischeWerteLokalisierung.art(proposal.kind))}: ${proposal.label.ifBlank { proposal.id }}",
                    fontFamily = FontFamily.SansSerif, fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Papierknopf(stringResource(R.string.personal_sync_entscheiden)) {
                        personalRemember = false; personalProposal = proposal }
                }
            }
            Text(stringResource(R.string.personal_custom_title), fontWeight = FontWeight.Bold)
            bestand.personalCustom.items.forEach { (id, item) ->
                if (item.status != "deleted") key(id) {
                    val position = remember { BringIntoViewRequester() }
                    val fokus = remember { FocusRequester() }
                    var angeordnet by remember { mutableStateOf(false) }
                    LaunchedEffect(customFokus, angeordnet, beiCustomFokus) {
                        if (customFokus == id && angeordnet) {
                            position.bringIntoView()
                            fokus.requestFocus()
                            beiCustomFokus()
                        }
                    }
                    Column(Modifier.fillMaxWidth().bringIntoViewRequester(position)
                        .focusRequester(fokus).focusable().onGloballyPositioned { angeordnet = true }) {
                        val value = item.record.getValue("value").jsonObject
                        Text(stringResource(if (item.record.getValue("kind").jsonPrimitive.content == "task") R.string.art_aufgabe else R.string.art_termin), fontWeight = FontWeight.Bold)
                        Text(listOf("module_title", "title", "date", "time", "timezone", "note")
                            .map { value.getValue(it).jsonPrimitive.content }.filter { it.isNotBlank() }.joinToString("\n"), fontSize = 13.sp)
                        if (value.getValue("completed").jsonPrimitive.boolean) Text(stringResource(R.string.aufgabe_erledigt))
                        if (item.status == "kept") Text(stringResource(R.string.personal_custom_keep), fontSize = 12.sp)
                        if (item.status == "pending" && item.owner == bestand.personalCustom.owner &&
                            item.generation == bestand.personalCustom.generation && bestand.personalCustom.active &&
                            bestand.personalCustom.local?.get("enabled")?.jsonPrimitive?.booleanOrNull == true &&
                            bestand.personalCustom.remote?.get("enabled")?.jsonPrimitive?.booleanOrNull == true)
                            Papierknopf(stringResource(R.string.personal_sync_entscheiden)) { customDelete = id to item.revision }
                        Zwischenraum(8)
                    }
                }
            }
        }
        Box(Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 8.dp)
            .height(1.dp).background(Magnolie.braun))
        Abschnitt(
            ueberschrift = stringResource(R.string.baum_ueberschrift),
            hinweis = stringResource(R.string.baum_erklaerung)
        ) {
            Schreibfeld(
                wert = name,
                beschriftung = stringResource(R.string.baum_eigener_name),
                beiAenderung = { name = it; handlungen.beiName(it) }
            )
            Zwischenraum(8)
            Wertzeile(stringResource(R.string.baum_fingerabdruck), fingerabdruck)
            Wertzeile(stringResource(R.string.baum_kennung), zustand.kennung)
            Zwischenraum(6)
            Schalterzeile(
                beschriftung = stringResource(R.string.baum_dienst_an),
                an = zustand.dienstAn,
                beiAenderung = handlungen.beiDienst
            )
            Schalterzeile(
                beschriftung = stringResource(R.string.baum_bluetooth_an),
                an = zustand.bluetoothAn,
                beiAenderung = handlungen.beiBluetooth
            )
            Schalterzeile(
                beschriftung = stringResource(R.string.baum_auto_wlan),
                an = zustand.automatischWlan,
                beiAenderung = handlungen.beiAutoWlan
            )
            Text(
                stringResource(R.string.baum_bluetooth_hinweis),
                fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp,
                lineHeight = 16.sp,
                color = Magnolie.braunHell,
                modifier = Modifier.padding(top = 4.dp)
            )
        }
        Abschnitt(ueberschrift = stringResource(R.string.baum_suchen)) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Papierknopf(
                    stringResource(R.string.baum_suchen),
                    aktiv = !sucheLaeuft,
                    modifier = Modifier.fillMaxWidth(),
                    beiKlick = handlungen.beiSuchen
                )
                if (sucheLaeuft) {
                    Text(
                        "…",
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 13.sp,
                        color = Magnolie.braun
                    )
                } else if (gefunden.isEmpty()) {
                    Text(
                        stringResource(R.string.baum_nichts_gefunden),
                        fontFamily = FontFamily.SansSerif,
                        fontSize = 12.sp,
                        lineHeight = 18.sp,
                        color = Magnolie.braunHell
                    )
                }
                gefunden.forEach { zweig ->
                    Row(
                        Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                stringResource(
                                    R.string.baum_gefunden, zweig.name,
                                    zweig.adresse + ":" + zweig.port
                                ),
                                fontFamily = FontFamily.SansSerif,
                                fontSize = 13.sp,
                                color = Magnolie.tinte
                            )
                            Text(
                                zweig.fingerabdruck,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 11.sp,
                                color = Magnolie.braunHell
                            )
                        }
                        Papierknopf(stringResource(R.string.baum_verbinden)) {
                            handlungen.beiAnfragen(zweig)
                        }
                    }
                }
            }
        }
        Abschnitt(
            ueberschrift = stringResource(R.string.baum_paaren_titel),
            hinweis = stringResource(R.string.baum_paaren_text)
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Lederknopf(
                    stringResource(R.string.baum_paarungsdatei),
                    modifier = Modifier.fillMaxWidth(),
                    beiKlick = handlungen.beiPaarungsdatei
                )
                Schreibfeld(
                    wert = eingefuegt,
                    beschriftung = stringResource(R.string.baum_paarung_einfuegen),
                    beiAenderung = { eingefuegt = it },
                    einzeilig = false
                )
                Papierknopf(
                    stringResource(R.string.ok),
                    aktiv = eingefuegt.isNotBlank()
                ) { handlungen.beiPaarungstext(eingefuegt); eingefuegt = "" }
                Papierknopf(
                    stringResource(R.string.baum_eigene_paarungsdatei),
                    modifier = Modifier.fillMaxWidth(),
                    beiKlick = handlungen.beiEigeneDatei
                )
            }
        }

        zustand.kontaktEingang.groupBy { it.partner }.forEach { (partner, karten) ->
            val gruppen = KontaktEingangslogik.gruppiere(karten)
            val partnerName = zustand.partner.firstOrNull { it.kennung == partner }
                ?.name?.ifBlank { partner } ?: partner
            Abschnitt(ueberschrift = stringResource(R.string.baum_kontakt_eingang_titel, partnerName)) {
                val sicher = gruppen.count { it.art == KontaktGruppenArt.SICHER }
                val pruefen = gruppen.count { it.art == KontaktGruppenArt.PRUEFEN }
                val konflikt = gruppen.count { it.art == KontaktGruppenArt.KONFLIKT }
                Text(pluralStringResource(R.plurals.baum_kontakt_eingang_bilanz, karten.size,
                    karten.size, gruppen.size),
                    fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold,
                    fontSize = 13.sp, color = Magnolie.tinte)
                Text(pluralStringResource(R.plurals.baum_kontakt_eingang_status, sicher,
                    sicher, pruefen, konflikt),
                    fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.braun)
                Text(stringResource(R.string.baum_kontakt_noch_nicht_geschrieben),
                    fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.rot,
                    modifier = Modifier.padding(vertical = 6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Lederknopf(stringResource(R.string.baum_kontakt_alle_sicheren),
                        aktiv = sicher > 0, modifier = Modifier.weight(1f)) {
                        handlungen.beiSichereKontaktGruppenImportieren(partner)
                    }
                    Papierknopf(stringResource(R.string.baum_kontakt_alle_ablehnen),
                        modifier = Modifier.weight(1f)) {
                        handlungen.beiAlleKontaktKartenAblehnen(partner)
                    }
                }
                gruppen.forEach { gruppe ->
                    Box(Modifier.fillMaxWidth().padding(top = 10.dp).height(1.dp).background(Magnolie.linie))
                    val status = when (gruppe.art) {
                        KontaktGruppenArt.SICHER -> stringResource(R.string.baum_kontakt_sicher)
                        KontaktGruppenArt.PRUEFEN -> stringResource(R.string.baum_kontakt_pruefen)
                        KontaktGruppenArt.KONFLIKT -> stringResource(R.string.baum_kontakt_konflikt)
                    }
                    Text("$status · ${KontaktPruefung.name(gruppe.kontakt)}",
                        fontFamily = FontFamily.Serif, fontWeight = FontWeight.SemiBold,
                        fontSize = 15.sp, color = if (gruppe.art == KontaktGruppenArt.KONFLIKT) Magnolie.rot else Magnolie.tinte,
                        modifier = Modifier.padding(top = 8.dp))
                    Text(pluralStringResource(R.plurals.baum_kontakt_rohkarten, gruppe.karten.size,
                        gruppe.karten.size),
                        fontFamily = FontFamily.SansSerif, fontSize = 11.sp, color = Magnolie.braunHell)
                    val feldzeilen = buildList {
                        gruppe.kontakt.firma.takeIf(String::isNotBlank)?.let { add(stringResource(R.string.baum_kontakt_firma) to it) }
                        gruppe.kontakt.telefone.forEach { add(stringResource(R.string.baum_kontakt_telefon) to it.wert) }
                        gruppe.kontakt.emailEintraege.forEach { add(stringResource(R.string.baum_kontakt_email) to it.wert) }
                        gruppe.kontakt.anschriften.forEach { add(stringResource(R.string.baum_kontakt_anschrift) to
                            listOf(it.strasse, it.plz, it.ort, it.region, it.land).filter(String::isNotBlank).joinToString(", ")) }
                        gruppe.kontakt.geburtstag.takeIf(String::isNotBlank)?.let { add(stringResource(R.string.baum_kontakt_geburtstag) to it) }
                        gruppe.kontakt.jubilaeum.takeIf(String::isNotBlank)?.let { add(stringResource(R.string.baum_kontakt_jubilaeum) to it) }
                        if (gruppe.kontakt.foto.isNotBlank()) add(stringResource(R.string.baum_kontakt_bild) to stringResource(R.string.baum_kontakt_vorhanden))
                        gruppe.kontakt.notiz.takeIf(String::isNotBlank)?.let { add(stringResource(R.string.baum_kontakt_notiz) to it) }
                    }
                    feldzeilen.forEach { (feld, wert) -> Text("$feld: $wert",
                        fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.tinte) }
                    gruppe.konflikte.forEach { konflikt -> Text(
                        stringResource(R.string.baum_kontakt_konflikt_zeile,
                            when (konflikt.feld) {
                                "jubilaeum" -> stringResource(R.string.baum_kontakt_jubilaeum)
                                "anzeigename", "vcardName" -> stringResource(R.string.art_kontakt)
                                else -> konflikt.feld
                            },
                            konflikt.werte.joinToString(" / ")),
                        fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.rot) }
                    Text(stringResource(R.string.baum_kontakt_quellen,
                        gruppe.karten.joinToString(", ") { it.freigabeId }),
                        fontFamily = FontFamily.Monospace, fontSize = 9.sp, color = Magnolie.braunHell)
                    Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.padding(top = 4.dp)) {
                        if (gruppe.art == KontaktGruppenArt.SICHER) Lederknopf(
                            stringResource(R.string.baum_kontakt_importieren)) {
                            handlungen.beiKontaktGruppeImportieren(gruppe.id, false)
                        } else {
                            Papierknopf(stringResource(R.string.baum_kontakt_getrennt_importieren)) {
                                handlungen.beiKontaktGruppeImportieren(gruppe.id, true)
                            }
                            Papierknopf(stringResource(R.string.baum_kontakt_karten_zusammenfuehren),
                                aktiv = gruppe.zusammenfuehrbar) {
                                handlungen.beiKontaktGruppeImportieren(gruppe.id, false)
                            }
                        }
                        Papierknopf(stringResource(R.string.baum_ablehnen)) {
                            handlungen.beiKontaktGruppeAblehnen(gruppe.id)
                        }
                    }
                }
            }
        }

        if (zustand.kontaktVorschlaege.isNotEmpty()) {
            Abschnitt(ueberschrift = stringResource(R.string.baum_kontakt_lokal_titel),
                hinweis = stringResource(R.string.baum_kontakt_lokal_hinweis)) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    zustand.kontaktVorschlaege.forEach { v ->
                        val art = when (v.art) {
                            "neu" -> stringResource(R.string.baum_kontakt_neu)
                            "geaendert" -> stringResource(R.string.baum_kontakt_geaendert)
                            "dublette" -> stringResource(R.string.baum_kontakt_dublette)
                            else -> stringResource(R.string.baum_kontakt_loeschvorschlag)
                        }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("$art: ${v.name}", modifier = Modifier.weight(1f),
                                fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.tinte)
                            if (v.art == "loeschen") {
                                Lederknopf(stringResource(R.string.baum_einzeln_bestaetigen)) {
                                    handlungen.beiKontaktVorschlag(v.id)
                                }
                            } else if (v.art == "dublette") {
                                Papierknopf(stringResource(R.string.baum_systemkontakt_oeffnen)) {
                                    handlungen.beiDubletteOeffnen(v.id)
                                }
                                Papierknopf(stringResource(R.string.baum_kontakt_verknuepfen)) {
                                    handlungen.beiDubletteVerknuepfen(v.id)
                                }
                            }
                            Papierknopf(stringResource(R.string.baum_ablehnen)) {
                                handlungen.beiKontaktVorschlagAblehnen(v.id)
                            }
                        }
                    }
                }
            }
        }

        Abschnitt(ueberschrift = stringResource(R.string.baum_partner)) {
            if (zustand.partner.isEmpty()) {
                Text(
                    stringResource(R.string.baum_keine_partner),
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    color = Magnolie.braunHell
                )
            }
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                zustand.partner.forEach { zweig ->
                    var fernHost by remember(zweig.kennung, zweig.fernAdresse) {
                        mutableStateOf(zweig.fernAdresse)
                    }
                    var fernPort by remember(zweig.kennung, zweig.fernPort) {
                        mutableStateOf(zweig.fernPort.toString())
                    }
                    Column(Modifier.fillMaxWidth()) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    zweig.name.ifBlank { zweig.kennung },
                                    fontFamily = FontFamily.Serif,
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 15.sp,
                                    color = Magnolie.tinte
                                )
                                Text(
                                    io.gitlab.maik3531.magnolienotes.baum.Krypto
                                        .fingerabdruck(zweig.oeffentlich),
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                    color = Magnolie.braunHell
                                )
                                Text(
                                    buildString {
                                        append(
                                            if (zweig.bestaetigt) stringResource(R.string.baum_bestaetigt)
                                            else stringResource(R.string.baum_wartet)
                                        )
                                        append(" · ").append(zweig.protokoll)
                                        if (zweig.adresse.isNotBlank()) {
                                            append(" · ").append(zweig.adresse)
                                        }
                                        if (zweig.bluetooth.isNotBlank()) {
                                            append(" · Bluetooth ").append(zweig.bluetooth)
                                        }
                                        append(" · ")
                                        append(
                                            if (zweig.zuletzt > 0) {
                                                Zeit.tagUndUhrzeit(zweig.zuletzt)
                                            } else stringResource(R.string.baum_nie)
                                        )
                                    },
                                    fontFamily = FontFamily.SansSerif,
                                    fontSize = 11.sp,
                                    color = Magnolie.braunHell
                                )
                            }
                        }
                        if (zweig.bestaetigt) {
                            Text(
                                stringResource(R.string.baum_fernziel_hinweis),
                                fontFamily = FontFamily.SansSerif,
                                fontSize = 11.sp,
                                lineHeight = 16.sp,
                                color = Magnolie.braunHell,
                                modifier = Modifier.padding(top = 8.dp)
                            )
                            Schreibfeld(
                                wert = fernHost,
                                beschriftung = stringResource(R.string.baum_fernziel_host),
                                beiAenderung = { fernHost = it }
                            )
                            Schreibfeld(
                                wert = fernPort,
                                beschriftung = stringResource(R.string.baum_fernziel_port),
                                beiAenderung = { fernPort = it.filter(Char::isDigit).take(5) }
                            )
                            Papierknopf(
                                stringResource(R.string.sichern),
                                aktiv = fernHost.isBlank() || fernPort.toIntOrNull() in 1..65535,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                handlungen.beiFernziel(
                                    zweig.kennung, fernHost, fernPort.toIntOrNull() ?: 8737
                                )
                            }
                            Lederknopf(
                                stringResource(R.string.baum_alles_sync),
                                aktiv = zweig.vertraut,
                                modifier = Modifier.fillMaxWidth()
                            ) { handlungen.beiAllesSynchronisieren(zweig.kennung) }
                            Schalterzeile(
                                beschriftung = stringResource(R.string.baum_kontakt_sync),
                                an = zweig.kontaktSync,
                                beiAenderung = { handlungen.beiKontaktSync(zweig.kennung, it) }
                            )
                            Text(
                                stringResource(R.string.baum_kontakt_sync_hinweis),
                                fontFamily = FontFamily.SansSerif,
                                fontSize = 11.sp,
                                lineHeight = 16.sp,
                                color = Magnolie.braunHell
                            )
                            Schalterzeile(
                                beschriftung = stringResource(R.string.baum_kontakt_loesch_sync),
                                an = zweig.kontaktLoeschSync,
                                beiAenderung = { an ->
                                    if (an) loeschWarnung = zweig.kennung
                                    else handlungen.beiKontaktLoeschSync(zweig.kennung, false)
                                }
                            )
                            Text(
                                stringResource(R.string.baum_kontakt_loesch_hinweis),
                                fontFamily = FontFamily.SansSerif, fontSize = 11.sp,
                                lineHeight = 16.sp, color = Magnolie.braunHell
                            )
                            Lederknopf(
                                stringResource(R.string.baum_kontakte_sync),
                                aktiv = zweig.vertraut && zweig.kontaktSync,
                                modifier = Modifier.fillMaxWidth()
                            ) { handlungen.beiKontakteSynchronisieren(zweig.kennung) }
                            Lederknopf(
                                stringResource(R.string.baum_kontakt_importieren),
                                aktiv = zweig.bestaetigt,
                                modifier = Modifier.fillMaxWidth()
                            ) { handlungen.beiKontaktImport(zweig.kennung) }
                            val vertrauenBeschreibung = stringResource(R.string.baum_vertrauen)
                            Row(
                                Modifier.fillMaxWidth().padding(top = 4.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    stringResource(R.string.baum_vertrauen),
                                    fontFamily = FontFamily.SansSerif,
                                    fontSize = 12.sp,
                                    color = Magnolie.braunHell,
                                    modifier = Modifier.weight(1f)
                                )
                                Switch(
                                    checked = zweig.vertraut,
                                    onCheckedChange = { handlungen.beiVertrauen(zweig.kennung, it) },
                                    modifier = Modifier.semantics {
                                        contentDescription = vertrauenBeschreibung
                                    },
                                    colors = SwitchDefaults.colors(
                                        checkedThumbColor = Magnolie.gold,
                                        checkedTrackColor = Magnolie.leder,
                                        uncheckedThumbColor = Magnolie.braunHell,
                                        uncheckedTrackColor = Magnolie.papierTief,
                                        uncheckedBorderColor = Magnolie.linieStark
                                    )
                                )
                            }
                            if (zustand.bluetoothAn && bluetoothGeraete.isNotEmpty()) {
                                Text(
                                    stringResource(R.string.baum_bluetooth_geraete),
                                    fontFamily = FontFamily.SansSerif,
                                    fontSize = 12.sp,
                                    color = Magnolie.braunHell,
                                    modifier = Modifier.padding(top = 6.dp, bottom = 2.dp)
                                )
                                bluetoothGeraete.forEach { geraet ->
                                    Papierknopf(
                                        stringResource(
                                            R.string.baum_bluetooth_zuordnen, geraet.name
                                        ),
                                        aktiv = zweig.bluetooth != geraet.adresse,
                                        modifier = Modifier.fillMaxWidth()
                                    ) {
                                        handlungen.beiBluetoothZiel(
                                            zweig.kennung, geraet.adresse
                                        )
                                    }
                                }
                                if (zweig.bluetooth.isNotBlank()) {
                                    Papierknopf(
                                        stringResource(R.string.baum_bluetooth_trennen),
                                        modifier = Modifier.fillMaxWidth()
                                    ) { handlungen.beiBluetoothZiel(zweig.kennung, "") }
                                }
                            }
                        }
                        if (zweig.wartet && zweig.code.isNotBlank()) {
                            Row(
                                Modifier.fillMaxWidth().padding(top = 6.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    zweig.code,
                                    fontFamily = FontFamily.Monospace,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 22.sp,
                                    color = Magnolie.rot,
                                    modifier = Modifier.weight(1f)
                                )
                                Lederknopf(stringResource(R.string.baum_code_stimmt)) {
                                    handlungen.beiBestaetigen(zweig.kennung)
                                }
                            }
                        }
                        Text(stringResource(R.string.baum_verbindung_gefahr_titel),
                            fontFamily = FontFamily.Serif, fontWeight = FontWeight.Bold,
                            fontSize = 14.sp, color = Magnolie.rot,
                            modifier = Modifier.padding(top = 14.dp))
                        Text(stringResource(R.string.baum_verbindung_gefahr_hinweis),
                            fontFamily = FontFamily.SansSerif, fontSize = 11.sp,
                            lineHeight = 16.sp, color = Magnolie.braunHell)
                        Button(onClick = { entfernenWarnung = zweig.kennung },
                            modifier = Modifier.fillMaxWidth().padding(top = 5.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Magnolie.rot)) {
                            Text(stringResource(R.string.baum_verbindung_entfernen))
                        }
                        Box(
                            Modifier.fillMaxWidth().padding(top = 8.dp)
                                .height(1.dp).background(Magnolie.linie)
                        )
                    }
                }
            }
            Text(
                stringResource(R.string.baum_vertrauen_hinweis),
                fontFamily = FontFamily.SansSerif,
                fontSize = 11.sp,
                lineHeight = 16.sp,
                color = Magnolie.braunHell,
                modifier = Modifier.padding(top = 8.dp)
            )
            Zwischenraum(10)
            val offen = zustand.postfach.count { !it.aufgegeben }
            val unsicher = zustand.postfach.count { it.brauchtPruefung }
            val blockiert = zustand.postfach.filter { it.brauchtPruefung }.mapTo(mutableSetOf()) { it.an }
            if (unsicher > 0) Text(stringResource(R.string.baum_postfach_unsicher, unsicher),
                fontFamily = FontFamily.SansSerif, fontSize = 12.sp, color = Magnolie.rot)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    pluralStringResource(R.plurals.baum_postfach, offen, offen),
                    fontFamily = FontFamily.SansSerif,
                    fontSize = 12.sp,
                    color = Magnolie.braunHell,
                    modifier = Modifier.weight(1f)
                )
                Papierknopf(
                    stringResource(R.string.baum_senden),
                    aktiv = zustand.postfach.any { !it.aufgegeben && it.an !in blockiert },
                    beiKlick = handlungen.beiSenden
                )
            }
        }

        if (zustand.eingang.isNotEmpty()) {
            Abschnitt(ueberschrift = stringResource(R.string.baum_eingang)) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    zustand.eingang.forEach { stueck ->
                        val artName = when (stueck.art) {
                            "aufgabe" -> stringResource(R.string.art_aufgabe)
                            "termin" -> stringResource(R.string.art_termin)
                            "kontakt_sync" -> stringResource(R.string.art_kontakt)
                            "kontakt_loeschen" -> stringResource(R.string.art_kontakt_loeschen)
                            else -> stringResource(R.string.art_notiz)
                        }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    stringResource(
                                        R.string.baum_eingang_stueck, artName,
                                        stueck.vonName.ifBlank { stueck.von }
                                    ),
                                    fontFamily = FontFamily.SansSerif,
                                    fontSize = 13.sp,
                                    color = Magnolie.tinte
                                )
                                if (stueck.art == "termin") Text(
                                    stringResource(R.string.baum_termin_nicht_unterstuetzt),
                                    fontFamily = FontFamily.SansSerif,
                                    fontSize = 12.sp,
                                    color = Magnolie.rot
                                )
                            }
                            Papierknopf(stringResource(R.string.baum_ablehnen)) {
                                handlungen.beiEingangAblehnen(stueck.id)
                            }
                            Zwischenraum(0)
                            Lederknopf(stringResource(R.string.baum_annehmen)) {
                                handlungen.beiEingangAnnehmen(stueck.id)
                            }
                        }
                    }
                }
            }
        }

        if (meldungen.isNotEmpty()) {
            Abschnitt(
                ueberschrift = stringResource(R.string.baum_ereignisse),
                kopfAktion = { Papierkorbknopf(handlungen.beiMeldungenLeeren) }
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    meldungen.reversed().take(8).forEach { zeile ->
                        Text(
                            "· " + zeile,
                            fontFamily = FontFamily.SansSerif,
                            fontSize = 12.sp,
                            lineHeight = 17.sp,
                            color = Magnolie.tinte
                        )
                    }
                }
            }
        }

        Zwischenraum(20)
    }

    handlungen.kontaktImportVorschau?.let { preview ->
        val quellen = preview.herkuenfte.joinToString("\n") {
            listOf(it.kontoName, it.kontoTyp, it.dataSet).filter(String::isNotBlank).joinToString(" · ") +
                " (${it.anzahl})"
        }
        AlertDialog(
            onDismissRequest = handlungen.beiKontaktImportAbbrechen,
            title = { Text(stringResource(R.string.baum_kontakt_vorschau)) },
            text = { Column { Text(preview.anzahl.toString()); Text(stringResource(R.string.baum_kontakt_quellen, quellen)) } },
            confirmButton = { TextButton(onClick = { handlungen.beiKontaktImportBestaetigen(preview.id) }) {
                Text(stringResource(R.string.baum_kontakt_importieren))
            } },
            dismissButton = { TextButton(onClick = handlungen.beiKontaktImportAbbrechen) {
                Text(stringResource(R.string.abbrechen))
            } })
    }

    val warnPartner = loeschWarnung
    val proposal = personalProposal
    if (proposal != null) {
        val prompt = personalDecisions.prompt(bestand, proposal)
        AlertDialog(onDismissRequest = { personalProposal = null },
            title = { Text(if (prompt == PersonalDeletionPrompt.CONFLICT)
                stringResource(R.string.personal_sync_geaendert_titel) else
                stringResource(R.string.personal_sync_entscheiden)) },
            text = { Column {
                Text(proposal.label.ifBlank { proposal.id })
                when (prompt) {
                    PersonalDeletionPrompt.BLOCKED -> Text(stringResource(R.string.personal_sync_notizbuch_blockiert))
                    PersonalDeletionPrompt.CONFLICT -> Text(stringResource(R.string.personal_sync_geaendert_hinweis))
                    else -> Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = personalRemember, onCheckedChange = { personalRemember = it })
                        Text(stringResource(R.string.personal_sync_lauf_merken))
                    }
                }
            } },
            confirmButton = { if (prompt != PersonalDeletionPrompt.BLOCKED) TextButton(onClick = {
                if (prompt == PersonalDeletionPrompt.CONFLICT) changedDelete = proposal
                else {
                    if (personalRemember) personalDecisions.remember(proposal.run_id, "delete")
                    val targets = if (personalRemember) bestand.personalSync.pending_proposals.filter {
                        it.run_id == proposal.run_id && personalDecisions.prompt(bestand, it) != PersonalDeletionPrompt.CONFLICT &&
                            personalDecisions.prompt(bestand, it) != PersonalDeletionPrompt.BLOCKED } else listOf(proposal)
                    requestMass("delete", targets)
                }
                personalProposal = null
            }) { Text(if (prompt == PersonalDeletionPrompt.CONFLICT)
                stringResource(R.string.personal_sync_trotz_aenderung_loeschen) else stringResource(R.string.loeschen),
                color = Magnolie.rot) } },
            dismissButton = { TextButton(onClick = {
                if (prompt == PersonalDeletionPrompt.CONFLICT || prompt == PersonalDeletionPrompt.BLOCKED) {
                    applyPersonal("restore", listOf(proposal)); personalProposal = null
                    return@TextButton
                }
                if (personalRemember)
                    personalDecisions.remember(proposal.run_id, "restore")
                val targets = if (personalRemember)
                    bestand.personalSync.pending_proposals.filter { it.run_id == proposal.run_id &&
                        personalDecisions.prompt(bestand, it) != PersonalDeletionPrompt.CONFLICT &&
                        personalDecisions.prompt(bestand, it) != PersonalDeletionPrompt.BLOCKED } else listOf(proposal)
                requestMass("restore", targets); personalProposal = null
            }) { Text(if (prompt == PersonalDeletionPrompt.CONFLICT)
                stringResource(R.string.personal_sync_geaenderte_version_wiederherstellen) else
                stringResource(R.string.personal_sync_wiederherstellen)) } }
        )
    }

    val changed = changedDelete
    if (changed != null) AlertDialog(onDismissRequest = { changedDelete = null },
        title = { Text(stringResource(R.string.personal_sync_endgueltig_titel)) },
        text = { Text(stringResource(R.string.personal_sync_endgueltig_hinweis, changed.label.ifBlank { changed.id })) },
        confirmButton = { TextButton(onClick = {
            applyPersonal("delete_changed", listOf(changed)); changedDelete = null
        }) { Text(stringResource(R.string.personal_sync_trotz_aenderung_loeschen), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = { changedDelete = null }) { Text(stringResource(R.string.abbrechen)) } })

    val mass = massDecision
    if (mass != null) {
        val counts = personalDecisions.typeCounts(mass.second)
        AlertDialog(onDismissRequest = { massDecision = null },
            title = { Text(stringResource(R.string.personal_sync_massen_titel)) },
            text = { Text(pluralStringResource(R.plurals.personal_sync_massen_hinweis, mass.second.size,
                mass.second.size,
                counts.getValue("note"), counts.getValue("notebook"), counts.getValue("task"),
                counts.getValue("attachment"))) },
            confirmButton = { TextButton(onClick = { applyPersonal(mass.first, mass.second); massDecision = null }) {
                Text(stringResource(R.string.baum_annehmen), color = Magnolie.rot) } },
            dismissButton = { TextButton(onClick = { massDecision = null }) { Text(stringResource(R.string.abbrechen)) } })
    }

    if (telefonEntfernenWarnung) AlertDialog(
        onDismissRequest = { telefonEntfernenWarnung = false },
        title = { Text(stringResource(R.string.telefon_entkoppeln)) },
        text = { Text(stringResource(R.string.telefon_entkoppeln_frage,
            telefon.peer?.display_name.orEmpty())) },
        confirmButton = { TextButton(onClick = {
            telefonHandlungen.beiEntkoppeln(telefon.peer); telefonEntfernenWarnung = false
        }) { Text(stringResource(R.string.telefon_entkoppeln), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = { telefonEntfernenWarnung = false }) {
            Text(stringResource(R.string.abbrechen))
        } }
    )

    if (warnPartner != null) AlertDialog(
        onDismissRequest = { loeschWarnung = null },
        title = { Text(stringResource(R.string.baum_kontakt_loesch_warnung_titel)) },
        text = { Text(stringResource(R.string.baum_kontakt_loesch_warnung)) },
        confirmButton = { TextButton(onClick = {
            handlungen.beiKontaktLoeschSync(warnPartner, true); loeschWarnung = null
        }) { Text(stringResource(R.string.baum_einzeln_bestaetigen), color = Magnolie.rot) } },
        dismissButton = { TextButton(onClick = { loeschWarnung = null }) {
            Text(stringResource(R.string.abbrechen))
        } }
    )

    val entfernenPartner = entfernenWarnung
    if (entfernenPartner != null) {
        val zweig = zustand.partner.firstOrNull { it.kennung == entfernenPartner }
        val name = zweig?.name?.ifBlank { entfernenPartner } ?: entfernenPartner
        AlertDialog(
            onDismissRequest = { entfernenWarnung = null },
            title = { Text(stringResource(R.string.baum_verbindung_entfernen)) },
            text = { Text(stringResource(R.string.baum_verbindung_entfernen_frage, name)) },
            confirmButton = { TextButton(onClick = {
                handlungen.beiEntfernen(entfernenPartner); entfernenWarnung = null
            }) { Text(stringResource(R.string.baum_verbindung_entfernen), color = Magnolie.rot) } },
            dismissButton = { TextButton(onClick = { entfernenWarnung = null }) {
                Text(stringResource(R.string.abbrechen))
            } }
        )
    }
}

@Composable
private fun Papierkorbknopf(beiKlick: () -> Unit) {
    val beschreibung = stringResource(R.string.loeschen)
    Box(
        Modifier
            .size(36.dp)
            .clickable(onClick = beiKlick)
            .semantics { contentDescription = beschreibung },
        contentAlignment = Alignment.Center
    ) {
        Canvas(Modifier.size(22.dp)) {
            val strich = Stroke(width = 1.8.dp.toPx())
            drawLine(Magnolie.braun, Offset(size.width * .22f, size.height * .25f),
                Offset(size.width * .78f, size.height * .25f), strokeWidth = strich.width)
            drawLine(Magnolie.braun, Offset(size.width * .40f, size.height * .16f),
                Offset(size.width * .60f, size.height * .16f), strokeWidth = strich.width)
            drawRect(Magnolie.braun, Offset(size.width * .29f, size.height * .34f),
                Size(size.width * .42f, size.height * .49f), style = strich)
            drawLine(Magnolie.braun, Offset(size.width * .43f, size.height * .43f),
                Offset(size.width * .43f, size.height * .72f), strokeWidth = strich.width)
            drawLine(Magnolie.braun, Offset(size.width * .57f, size.height * .43f),
                Offset(size.width * .57f, size.height * .72f), strokeWidth = strich.width)
        }
    }
}

@Composable
internal fun Schalterzeile(beschriftung: String, an: Boolean, beiAenderung: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            beschriftung,
            fontFamily = FontFamily.SansSerif,
            fontSize = 13.sp,
            color = Magnolie.tinte,
            modifier = Modifier.weight(1f)
        )
        Switch(
            checked = an,
            onCheckedChange = beiAenderung,
            modifier = Modifier.semantics { contentDescription = beschriftung },
            colors = SwitchDefaults.colors(
                checkedThumbColor = Magnolie.gold,
                checkedTrackColor = Magnolie.leder,
                uncheckedThumbColor = Magnolie.braunHell,
                uncheckedTrackColor = Magnolie.papierTief,
                uncheckedBorderColor = Magnolie.linieStark
            )
        )
    }
}
