package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.telecom.TelecomManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import java.net.InetSocketAddress
import java.net.Socket
import java.util.UUID
import java.util.Base64
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicBoolean
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Anhang
import io.gitlab.maik3531.magnolienotes.daten.PersonalSync
import io.gitlab.maik3531.magnolienotes.daten.PersonalCustom
import io.gitlab.maik3531.magnolienotes.daten.PersonalCustomState
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import io.gitlab.maik3531.magnolienotes.daten.AnhangPruefung
import io.gitlab.maik3531.magnolienotes.daten.PersonalDeletionProposal
import io.gitlab.maik3531.magnolienotes.aufgaben.Erinnerung
import kotlin.concurrent.thread

internal fun personalSyncTransmissionAllowed(peer: TelefonPeer, kind: String, body: JsonObject): Boolean {
    if (kind == "personal_sync.settings") return true
    if (!peer.own_device || !peer.remote_own_device) return false
    if (kind in setOf("personal_sync.deletion_proposals", "personal_sync.deletion_decision"))
        return peer.personal_deletions_sync_granted && peer.remote_personal_deletions_sync_granted
    var notes = false
    var tasks = false
    if (kind in setOf("personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result")) {
        notes = true
    } else if (kind == "personal_sync.batch") {
        (body["records"] as? JsonArray).orEmpty().forEach { element ->
            when (((element as? JsonObject)?.get("kind") as? JsonPrimitive)?.content) {
                "note", "notebook" -> notes = true
                "task" -> tasks = true
            }
        }
    } else if (kind == "personal_sync.request") {
        (body["modules"] as? JsonArray).orEmpty().forEach {
            when ((it as? JsonPrimitive)?.content) { "notes" -> notes = true; "tasks" -> tasks = true }
        }
    } else if (kind == "personal_sync.report") {
        listOf("sent", "received").mapNotNull { body[it] as? JsonObject }.forEach { counts ->
            notes = notes || listOf("notes", "notebooks").any {
                ((counts[it] as? JsonPrimitive)?.content?.toLongOrNull() ?: 0L) > 0
            }
            tasks = tasks || (((counts["tasks"] as? JsonPrimitive)?.content?.toLongOrNull() ?: 0L) > 0)
        }
    }
    val notesAllowed = peer.personal_notes_sync_granted && peer.remote_personal_notes_sync_granted
    val tasksAllowed = peer.personal_tasks_sync_granted && peer.remote_personal_tasks_sync_granted
    return if (!notes && !tasks) notesAllowed || tasksAllowed
        else (!notes || notesAllowed) && (!tasks || tasksAllowed)
}

internal fun <T> replayPendingPersonalDeletions(
    pending: List<T>, policyFor: (T) -> String?, enqueue: (T, String) -> Unit
) {
    pending.forEach { decision ->
        runCatching {
            val policy = policyFor(decision) ?: return@runCatching
            enqueue(decision, policy)
        }
    }
}

internal fun organizerPairingAllowed(current: TelefonPeer?, deviceId: String): Boolean =
    current == null || current.device_id == deviceId

internal fun negotiatedPersonalNotesFormat(peer: TelefonPeer): Int =
    when { 3 in peer.remote_personal_notes_sync_versions -> 3
        2 in peer.remote_personal_notes_sync_versions -> 2
        else -> 1 }

internal fun negotiatedPersonalFormat(peer: TelefonPeer, modules: Collection<String>): Int {
    val supported = modules.map { module -> if (module == "tasks")
        peer.remote_personal_tasks_sync_versions else peer.remote_personal_notes_sync_versions }
    return (1..3).lastOrNull { format -> supported.all { format in it } } ?: 1
}

internal fun shouldStartPersonalSyncOnSecureWifi(
    transport: TelefonTransportArt,
    authenticatedTransition: Boolean,
    autoWifi: Boolean,
    ownDevice: Boolean,
    remoteOwnDevice: Boolean,
    bilateralModuleGrant: Boolean,
    activeAutoRun: Boolean,
    nowMs: Long,
    lastAutoMs: Long,
    currentCounter: Long,
    lastAutoCounter: Long
): Boolean {
    if (transport != TelefonTransportArt.WIFI || !authenticatedTransition || !autoWifi ||
        !ownDevice || !remoteOwnDevice || !bilateralModuleGrant || activeAutoRun) return false
    val remoteUnknown = lastAutoMs <= 0
    val localDirty = lastAutoCounter >= 0 && currentCounter != lastAutoCounter
    return remoteUnknown || localDirty || nowMs - lastAutoMs >= 15 * 60_000L
}

class TelefonWerk private constructor(private val context: Context, private val storage: TelefonAblage) {
    private val _state = MutableStateFlow(TelefonUiZustand(enabled = storage.enabled(),
        bluetoothEnabled = storage.bluetoothEnabled(), peer = safePeer(),
        dialRequestEnabled = storage.dialRequestEnabled(), dialAvailable = TelefonModulStatus.dialResolvable(context),
        notificationsEnabled = storage.notificationsEnabled(), selectedPackages = storage.selectedPackages(),
        notificationAccess = TelefonModulStatus.notificationAccess(context),
        incomingCallsEnabled = storage.incomingCallsEnabled(), incomingNumberEnabled = storage.incomingNumberEnabled(),
        answerCallsEnabled = storage.answerCallsEnabled()))
    val state = _state.asStateFlow()
    private val pending = AtomicReference<PendingPairing?>()
    private var confirmingPairing: PendingPairing? = null
    private val pairing = AtomicBoolean(false)
    private val discovering = AtomicBoolean(false)
    private val connecting = AtomicBoolean(false)
    private val queue = TelefonQueue(context, storage) { Ablage.hole(context).baum.value.syncEpoch }
    private val bluetooth = TelefonBluetooth(context)
    internal var bluetoothListenerFactory: () -> TelefonRfcommListener = bluetooth::listen
    internal val bluetoothPairingRequest = MutableStateFlow<TelefonBluetoothAnfrage?>(null)
    @Volatile private var bluetoothListener: TelefonRfcommListener? = null
    @Volatile private var bluetoothSetupUntil = 0L
    private var bluetoothSetupTimer: java.util.Timer? = null
    private var bluetoothFinishRetried = ""
    @Volatile private var bluetoothBindingAddress = ""
    @Volatile private var bluetoothBindingUntil = 0L
    @Volatile private var bluetoothFirstSessionUntil = 0L
    private val bluetoothRecoveryHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val bluetoothRecoveryPoll = Runnable { reconnect() }
    private val incoming = EingehendeAnrufe(context)
    @Volatile private var activeTransport: Pair<TelefonTransportArt, TelefonRoehre>? = null
    @Volatile private var wifiAvailable = false
    @Volatile private var serviceRunning = false
    @Volatile private var lifecycleGeneration = 0L
    private val captureLock = Any()
    // Runtime only. dial_request v2 reuses client_ref as the exact outgoing call token.
    private data class OutgoingScope(val peerId: String, val identity: String, val callRef: String,
        val deadline: Long, val ended: Boolean = false)
    private var outgoingScope: OutgoingScope? = null // captureLock; never acquire the tracker lock inside it
    @Volatile private var pairingGeneration = 0L

    internal fun <T> peerEffect(expected: TelefonPeer, generation: Long, effect: (TelefonPeer) -> T): T = synchronized(this) {
        val current = safePeer()?.takeIf { generation == pairingGeneration &&
            it.device_id == expected.device_id && it.static_public == expected.static_public }
            ?: throw TelefonProtokollFehler("Unbekannte Gegenstelle.")
        effect(current)
    }

    fun serviceStarted() {
        val generation = synchronized(this) {
            if (serviceRunning || !storage.enabled()) return
            serviceRunning = true
            ++lifecycleGeneration
        }
        TelefonDatenbank(context).writableDatabase.close()
        runCatching { maintenance() }
        replayPendingDeletionDecisions()
        safePeer()?.let { peer ->
            // Runtime permissions may have changed while the service was stopped.
            queue.removeKind(peer.device_id, "capabilities.update")
            queue.removeKind(peer.device_id, "grants.update")
            queue.readyPersonalBatches().filter { it.first == peer.device_id }.forEach {
                synchronized(this) {
                    if (generation != lifecycleGeneration || !storage.enabled()) return
                    runCatching { completePersonalBatch(peer, it.second) }
                }
            }
        }
        refreshModules()
        synchronized(this) {
            if (generation != lifecycleGeneration || !serviceRunning || !storage.enabled()) return
            incoming.serviceStarted(storage.incomingCallsEnabled())
            _state.value = _state.value.copy(enabled = true, connection = TelefonVerbindungsstatus.OFFLINE, error = "")
            if (safePeer() == null) thread(name = "magnolie-phone-discovery", isDaemon = true) {
                runCatching { discover() }
            } else reconnect()
            runCatching { ensureBluetoothListener() }
        }
    }

    private var identifierEpoch = 0L
    private var identifierPermissionTicket: Triple<String, String, Long>? = null
    private var identifierPermissions = identifierPermissionMask()
    private val identifierRequests = mutableMapOf<String, Long>()
    private fun identifierPermissionMask(): Int = AndroidDeviceIdentifierSource(context).let {
        (if (it.phonePermission) 1 else 0) or (if (it.statePermission) 2 else 0)
    }
    private fun identifiersAllowed(peer: TelefonPeer): Boolean = peer.state == "paired" &&
        peer.own_device && peer.remote_own_device && peer.identifier_sharing_enabled &&
        identifierPermissionMask() and 1 != 0 && identifierPermissionMask() and peer.identifier_permission_mask == peer.identifier_permission_mask &&
        peer.device_status_granted && peer.remote_device_status_granted && peer.remote_device_status_available &&
        4 in peer.remote_device_status_versions

    @Synchronized fun beginIdentifierPermission(): String? {
        val peer = safePeer()?.takeIf { it.own_device && it.state == "paired" } ?: return null
        val token = UUID.randomUUID().toString()
        identifierPermissionTicket = Triple(token, peer.static_public, identifierEpoch)
        return token
    }
    @Synchronized fun completeIdentifierPermission(token: String, granted: Boolean) {
        val ticket = identifierPermissionTicket
        identifierPermissionTicket = null
        if (granted && ticket?.first == token && ticket.third == identifierEpoch &&
            safePeer()?.static_public == ticket.second) setIdentifierSharingEnabled(true)
    }
    @Synchronized fun setIdentifierSharingEnabled(enabled: Boolean) {
        identifierEpoch++; identifierPermissionTicket = null; identifierRequests.clear()
        val peer = safePeer() ?: return
        identifierPermissions = identifierPermissionMask()
        storage.savePeer(peer.copy(identifier_sharing_enabled = enabled && peer.own_device && identifierPermissions and 1 != 0,
            identifier_permission_mask = if (enabled) identifierPermissions else 0))
        closeTransport(); modulesChanged()
    }

    fun refreshModules() {
        safePeer()?.takeIf { it.identifier_sharing_enabled }?.let { peer ->
            val mask = identifierPermissionMask()
            if (mask and 1 == 0 || mask and peer.identifier_permission_mask != peer.identifier_permission_mask)
                setIdentifierSharingEnabled(false)
        }
        refreshCustomAuthorization()
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = runCatching { @Suppress("DEPRECATION") context.packageManager.queryIntentActivities(launcher, 0)
            .filter { it.activityInfo.packageName != context.packageName }
            .distinctBy { it.activityInfo.packageName }
            .map { TelefonApp(it.activityInfo.packageName, it.loadLabel(context.packageManager).toString()) }
            .sortedBy { it.label.lowercase() } }.getOrDefault(emptyList())
        _state.value = _state.value.copy(peer = safePeer(), dialRequestEnabled = storage.dialRequestEnabled(),
            dialAvailable = TelefonModulStatus.dialResolvable(context), notificationsEnabled = storage.notificationsEnabled(),
            selectedPackages = storage.selectedPackages(), notificationApps = apps,
            notificationAccess = TelefonModulStatus.notificationAccess(context),
            incomingCallsEnabled = storage.incomingCallsEnabled(), incomingNumberEnabled = storage.incomingNumberEnabled(),
            answerCallsEnabled = storage.answerCallsEnabled(), personalOwnDevice = storage.personalOwnDevice(),
            personalNotesEnabled = storage.personalNotesEnabled(), personalTasksEnabled = storage.personalTasksEnabled(),
            personalAutoWifi = storage.personalAutoWifi(), personalDeletionsEnabled = storage.personalDeletionsEnabled(),
            personalSyncReport = storage.personalSyncReport())
    }

    @Synchronized fun runtimePermissionsChanged() {
        if (!TelefonModulStatus.dialPermissions(context)) synchronized(captureLock) { outgoingScope = null }
        val permissions = identifierPermissionMask()
        if (safePeer()?.identifier_sharing_enabled == true && identifierPermissions and permissions != identifierPermissions)
            setIdentifierSharingEnabled(false)
        identifierPermissions = permissions
        if (context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED ||
            storage.incomingNumberEnabled() && context.checkSelfPermission(Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED) {
            closeTransport()
            queue.removeCallEvents()
        }
        if (_state.value.notificationAccess && !TelefonModulStatus.notificationAccess(context)) closeTransport()
        val previous = TelefonModulStatus.notifications(
            _state.value.selectedPackages, _state.value.notificationAccess)
        refreshModules()
        incoming.runtimePermissionsChanged()
        val current = TelefonModulStatus.notifications(
            _state.value.selectedPackages, _state.value.notificationAccess)
        if (!_state.value.notificationAccess) queue.purgeNotifications(emptySet())
        if (previous != current) controlStateChanged()
    }

    @Synchronized fun setDialRequestEnabled(value: Boolean) {
        if (value && !TelefonModulStatus.dialResolvable(context))
            throw TelefonProtokollFehler("Kein Systemwähler verfügbar.")
        synchronized(captureLock) {
            storage.setDialRequestEnabled(value)
            if (!value) { outgoingScope = null; queue.removeCallEvents() }
        }
        if (!value) closeTransport()
        modulesChanged()
    }
    @Synchronized fun setIncomingCallsEnabled(value: Boolean) {
        if (!value) closeTransport()
        synchronized(captureLock) {
            storage.setIncomingCallsEnabled(value)
            if (!value) queue.removeCallEvents()
        }
        incoming.setIncomingListening(value); modulesChanged()
    }
    @Synchronized fun setIncomingNumberEnabled(value: Boolean) {
        if (!value) closeTransport()
        synchronized(captureLock) {
            storage.setIncomingNumberEnabled(value)
            if (!value) queue.removeCallEvents()
        }
        modulesChanged()
    }
    fun setAnswerCallsEnabled(value: Boolean) { storage.setAnswerCallsEnabled(value); modulesChanged() }
    @Synchronized fun setPersonalSync(own: Boolean, notes: Boolean, tasks: Boolean, autoWifi: Boolean,
                         deletions: Boolean = storage.personalDeletionsEnabled()) {
        val peer = safePeer()
        if (!own) { identifierEpoch++; identifierPermissionTicket = null; identifierRequests.clear(); closeTransport() }
        if (!own) pauseCustom()
        if (peer != null && !own) queue.purgePersonal(peer.device_id)
        else if (peer != null) queue.purgePersonalModules(peer.device_id,
            buildSet { if (!notes) add("notes"); if (!tasks) add("tasks") })
        if (own) Ablage.hole(context).personalSyncRevokeModules(
            buildSet { if (!notes) add("notes"); if (!tasks) add("tasks") })
        else {
            Ablage.hole(context).personalSyncRevokeModules(setOf("notes", "tasks"))
            Ablage.hole(context).personalSyncRevokeDeletions()
        }
        if (peer != null && !deletions) {
            queue.purgePersonalDeletionWire(peer.device_id)
            Ablage.hole(context).personalSyncRevokeDeletions()
        }
        storage.setPersonalSync(own, notes, tasks, autoWifi, deletions)
        if (peer != null) {
            storage.savePeer(peer.copy(own_device = own, identifier_sharing_enabled = own && peer.identifier_sharing_enabled, personal_notes_sync_granted = own && notes,
                personal_tasks_sync_granted = own && tasks, personal_deletions_sync_granted = own && deletions))
            queue.removeKind(peer.device_id, "personal_sync.settings")
            queue.queue(peer.device_id, "personal_sync.settings", buildJsonObject {
                put("format", JsonPrimitive(1)); put("own_device", JsonPrimitive(own))
            }, 86_400_000)
        }
        modulesChanged()
    }

    @Synchronized fun personalSyncNow(trigger: String = "manual") {
        val peer = safePeer() ?: throw TelefonProtokollFehler("Kein eigener Rechner gekoppelt.")
        val custom = requestCustom(trigger)
        if (custom && !(peer.personal_notes_sync_granted && peer.remote_personal_notes_sync_granted) &&
            !(peer.personal_tasks_sync_granted && peer.remote_personal_tasks_sync_granted)) return
        if (!peer.own_device || !peer.remote_own_device) throw TelefonProtokollFehler("Eigenes Gerät ist nicht beidseitig bestätigt.")
        if (trigger == "auto_wifi" && activeTransport?.first != TelefonTransportArt.WIFI)
            throw TelefonProtokollFehler("Automatischer persönlicher Sync läuft nur im WLAN.")
        enqueuePersonalSync(peer, trigger)
        activeTransport?.second?.let { runCatching { it.close() } } ?: reconnect()
    }

    @Synchronized fun personalDeletionDecision(proposalId: String, decision: String): String = synchronized(Ablage.SCHREIBSPERRE) {
        require(decision in setOf("delete", "restore", "delete_changed"))
        val peer = safePeer() ?: return "missing"
        val proposal = Ablage.hole(context).bestand.value.personalSync.pending_proposals
            .firstOrNull { it.proposal_id == proposalId } ?: return "missing"
        if (!peer.own_device || !peer.remote_own_device || !peer.personal_deletions_sync_granted ||
            !peer.remote_personal_deletions_sync_granted) return "blocked"
        val moduleAllowed = if (proposal.kind == "task") peer.personal_tasks_sync_granted && peer.remote_personal_tasks_sync_granted
            else peer.personal_notes_sync_granted && peer.remote_personal_notes_sync_granted
        if (!moduleAllowed) return "blocked"
        val policy = runCatching { queue.personalRunPolicy(peer.device_id, proposal.run_id) }.getOrNull() ?: return "missing"
        val wireDecision = if (decision == "delete_changed") "delete" else decision
        val decisionId = UUID.randomUUID().toString()
        val result = Ablage.hole(context).personalSyncDecide(peer.device_id, proposalId, decisionId, wireDecision,
            allowChanged = decision == "delete_changed")
        if (result == "applied") {
            queue.queueDeletionDecision(peer.device_id, buildJsonObject {
                put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(proposal.run_id))
                put("decision_id", JsonPrimitive(decisionId))
                put("decisions", JsonArray(listOf(buildJsonObject {
                    put("proposal_id", JsonPrimitive(proposal.proposal_id)); put("decision", JsonPrimitive(wireDecision))
                    put("expected_clock", JsonArray(proposal.clock.map { buildJsonObject {
                        put("actor_id", JsonPrimitive(it.actor_id)); put("counter", JsonPrimitive(it.counter)) } }))
                })))
            }, policy)
            activeTransport?.second?.let { runCatching { it.close() } } ?: reconnect()
        }
        return result
    }

    @Synchronized private fun replayPendingDeletionDecisions() {
        replayPendingPersonalDeletions(Ablage.hole(context).personalSyncPendingDecisions().filter { it.state == "pending" }, { pending ->
            queue.personalRunPolicy(pending.peer_device_id, pending.run_id)
        }) { pending, policy ->
                if (safePeer()?.device_id != pending.peer_device_id) return@replayPendingPersonalDeletions
                queue.queueDeletionDecision(pending.peer_device_id, buildJsonObject {
                    put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(pending.run_id))
                    put("decision_id", JsonPrimitive(pending.decision_id)); put("decisions", JsonArray(listOf(buildJsonObject {
                        put("proposal_id", JsonPrimitive(pending.proposal_id)); put("decision", JsonPrimitive(pending.decision))
                        put("expected_clock", JsonArray(pending.expected_clock.map { buildJsonObject {
                            put("actor_id", JsonPrimitive(it.actor_id)); put("counter", JsonPrimitive(it.counter)) } }))
                    })))
                }, policy)
        }
    }
    @Synchronized fun toggleNotificationPackage(packageName: String) {
        if (packageName !in _state.value.notificationApps.map { it.packageName }) throw TelefonProtokollFehler("Unbekannte App.")
        val selected = storage.selectedPackages().toMutableSet().apply { if (!add(packageName)) remove(packageName) }
        closeTransport()
        synchronized(captureLock) {
            storage.setSelectedPackages(selected)
            queue.purgeNotifications(selected)
        }
        modulesChanged()
    }

    fun publish(kind: String, body: JsonObject, ttlMs: Long) {
        synchronized(captureLock) {
            if (!serviceRunning || !storage.enabled()) return
            val peer = safePeer()?.takeIf { it.state == "paired" } ?: return
            val allowed = when (kind) {
                "selected_notifications_readonly.event" -> TelefonModulStatus.notifications(context) &&
                    body.string("package") in storage.selectedPackages()
                "incoming_call_state.event" -> callStateAllowed(peer, body)
                else -> false
            }
            if (!allowed) return
            if (kind == "incoming_call_state.event" && body.string("number").isNotEmpty() &&
                (!storage.incomingNumberEnabled() || !peer.remote_incoming_call_number_granted ||
                    context.checkSelfPermission(Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED)) return
            queue.queue(peer.device_id, kind, body, ttlMs)
            if (kind == "incoming_call_state.event" && scopedOutgoing(peer, body.string("call_ref")) &&
                body.string("state") == "idle") outgoingScope = outgoingScope?.copy(
                    ended = true, deadline = System.nanoTime() + 60_000_000_000L)
        }
        // Telephony callbacks can hold their tracker lock. Reconnect only after returning.
        bluetoothRecoveryHandler.post {
            if (serviceRunning && storage.enabled()) {
                activeTransport?.second?.let { runCatching { it.close() } } ?: reconnect()
            }
        }
    }

    private fun scopedOutgoing(peer: TelefonPeer, callRef: String, active: Boolean = false): Boolean =
        synchronized(captureLock) {
            val scope = outgoingScope ?: return@synchronized false
            serviceRunning && storage.enabled() && TelefonModulStatus.dialRequest(context) &&
                peer.state == "paired" && peer.remote_dial_request_granted && peer.remote_dial_request_available &&
                2 in peer.remote_dial_request_versions && scope.peerId == peer.device_id &&
                scope.identity == peer.static_public && scope.callRef == callRef &&
                System.nanoTime() < scope.deadline && (!active || !scope.ended)
        }

    private fun callStateAllowed(peer: TelefonPeer, body: JsonObject): Boolean =
        context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED &&
            (body.string("direction") == "outgoing" && body.string("control_origin") == "desktop" &&
                scopedOutgoing(peer, body.string("call_ref")) ||
                peer.remote_incoming_call_state_granted && (storage.incomingCallsEnabled() ||
                    storage.dialRequestEnabled() && body.string("direction") == "outgoing"))

    @Synchronized fun placeOutgoing(number: String, clientRef: String): Pair<String, String> {
        if (!serviceRunning || !storage.enabled()) return "failed" to "os_restricted"
        return runCatching {
            incoming.beginOutgoing(number, clientRef)
            if (!serviceRunning ||
                context.checkSelfPermission(Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED ||
                context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED)
                return failOutgoing(clientRef, if (serviceRunning) "permission_missing" else "os_restricted")
            context.getSystemService(TelecomManager::class.java)
                ?.placeCall(Uri.fromParts("tel", number, null), android.os.Bundle())
                ?: return failOutgoing(clientRef, "dial_unavailable")
            "submitted" to "none"
        }.getOrElse { error -> failOutgoing(clientRef,
            if (error is SecurityException) "permission_missing" else "os_restricted") }
    }
    fun failOutgoing(clientRef: String, error: String): Pair<String, String> {
        incoming.failOutgoing(clientRef)
        return "failed" to error
    }

    private fun modulesChanged() {
        refreshModules()
        controlStateChanged()
    }

    @Synchronized private fun controlStateChanged() {
        safePeer()?.let { peer ->
            queue.removeKind(peer.device_id, "capabilities.update"); queue.removeKind(peer.device_id, "grants.update")
            val changed = peer.copy(capabilities_revision = peer.capabilities_revision + 1, grants_revision = peer.grants_revision + 1)
            storage.savePeer(changed); ensureControlMessages(changed)
            activeTransport?.second?.let { runCatching { it.close() } } ?: reconnect()
        }
    }

    @Synchronized fun serviceStopped() {
        identifierEpoch++; identifierPermissionTicket = null; identifierRequests.clear()
        pairingGeneration++
        lifecycleGeneration++
        serviceRunning = false
        closeTransport()
        synchronized(captureLock) { outgoingScope = null; runCatching { queue.purgeNotifications(emptySet()); queue.removeCallEvents() } }
        bluetoothBindingAddress = ""; bluetoothBindingUntil = 0
        bluetoothFirstSessionUntil = 0
        bluetoothRecoveryHandler.removeCallbacks(bluetoothRecoveryPoll)
        stopBluetoothSetup()
        runCatching { bluetoothListener?.close() }; bluetoothListener = null
        pending.getAndSet(null)?.close()
        runCatching { confirmingPairing?.socket?.close() }
        incoming.shutdown()
        pairing.set(false)
        _state.value = _state.value.copy(enabled = false, connection = TelefonVerbindungsstatus.STOPPED,
            found = emptyList(), pairingCode = "", pairingFingerprint = "", pairingName = "")
    }

    // Never wait for a graceful network write from a lifecycle/consent callback.
    @Synchronized private fun closeTransport() {
        val pipe = activeTransport?.second
        activeTransport = null
        runCatching { pipe?.close() }
    }

    internal fun maintenance() {
        val pendingRuns = Ablage.hole(context).personalSyncPendingDecisions()
            .filter { it.state == "pending" }
            .map { it.peer_device_id to it.run_id }.toSet()
        queue.cleanup(protectedRuns = pendingRuns)
    }

    fun wifiChanged(available: Boolean) {
        wifiAvailable = available
        if (!available) safePeer()?.takeIf { queue.hasActiveAutoRun(it.device_id) }?.let {
            storage.setPersonalSyncReport(context.getString(
                io.gitlab.maik3531.magnolienotes.R.string.personal_sync_wlan_pause))
            refreshModules()
        }
        if (activeTransport?.first == TelefonTransportArt.BLUETOOTH && System.nanoTime() < bluetoothFirstSessionUntil) return
        if (available && activeTransport?.first == TelefonTransportArt.BLUETOOTH) {
            closeTransport()
        }
        if (!available && activeTransport?.first == TelefonTransportArt.WIFI) {
            closeTransport()
        }
        if (!serviceRunning || !storage.enabled() || _state.value.connection == TelefonVerbindungsstatus.CODE_PENDING) return
        _state.value = _state.value.copy(connection = when {
            !available -> TelefonVerbindungsstatus.OFFLINE
            _state.value.peer?.state == "paired" -> TelefonVerbindungsstatus.PAIRED
            else -> TelefonVerbindungsstatus.OFFLINE
        })
        reconnect()
    }

    @Synchronized internal fun startBluetoothSetup() {
        check(serviceRunning && storage.enabled() && storage.peers().peer == null)
        if (!bluetooth.erlaubt()) throw SecurityException("Bluetooth permission missing")
        bluetoothSetupUntil = System.nanoTime() + 120_000_000_000L
        bluetoothSetupTimer?.cancel()
        bluetoothSetupTimer = java.util.Timer("magnolie-bt-setup", true).apply {
            schedule(object : java.util.TimerTask() { override fun run() = stopBluetoothSetup() }, 120_000)
        }
        ensureBluetoothListener()
    }

    @Synchronized internal fun stopBluetoothSetup() {
        bluetoothSetupUntil = 0
        bluetoothSetupTimer?.cancel(); bluetoothSetupTimer = null
        bluetoothPairingRequest.value?.close(); bluetoothPairingRequest.value = null
        if (!serviceRunning || !storage.bluetoothEnabled() || storage.peers().peer == null) {
            runCatching { bluetoothListener?.close() }; bluetoothListener = null
        }
    }

    @Synchronized private fun ensureBluetoothListener() {
        val peer = storage.peers().peer
        val recovery = peer?.bluetooth_inbound == true && peer.state == "paired_unverified" &&
            peer.pending_finish_expires_ms > System.currentTimeMillis()
        if (!serviceRunning || !storage.enabled() || !bluetooth.erlaubt() || bluetoothListener != null ||
            !(bluetoothSetupUntil > System.nanoTime() || storage.bluetoothEnabled() && peer != null || recovery)) return
        val listener = bluetoothListenerFactory()
        bluetoothListener = listener
        thread(name = "magnolie-phone-rfcomm-listener", isDaemon = true) {
            var attempts = 0
            try {
                while (serviceRunning && storage.enabled()) {
                    val link = listener.accept()
                    try {
                        if (storage.peers().peer != null) acceptBluetoothSession(link)
                        else if (bluetoothSetupUntil > System.nanoTime() && attempts++ < 8 && !pairing.get()) {
                            val (identity, secret) = storage.identity(Build.MODEL.orEmpty()); secret.fill(0)
                            val request = TelefonBluetoothAnfrage(identity.device_id)
                            bluetoothPairingRequest.value = request
                            try {
                                request.receive(link) { desktop, pipe, address ->
                                    check(beginPairing(desktop, address) { pipe })
                                }
                            } finally { request.close(); bluetoothPairingRequest.value = null }
                        } else {
                            link.pipe.close()
                            if (storage.peers().peer == null && attempts >= 8) stopBluetoothSetup()
                        }
                    } catch (error: Exception) {
                        runCatching { link.pipe.close() }
                        if (serviceRunning && storage.peers().peer != null) _state.value = _state.value.copy(error = error.message.orEmpty())
                    }
                }
            } catch (_: Exception) {
            } finally {
                runCatching { listener.close() }
                synchronized(this) { if (bluetoothListener === listener) bluetoothListener = null }
            }
        }
    }

    internal fun acceptBluetoothSession(link: TelefonBluetoothLink) {
        val peer = storage.peers().peer
        val selectedBinding = bluetoothBindingAddress == link.address && System.nanoTime() < bluetoothBindingUntil
        if (!serviceRunning || !storage.enabled() || !bluetooth.erlaubt() || peer == null ||
            !(peer.bluetooth_address == link.address || selectedBinding) ||
            !(storage.bluetoothEnabled() || peer.state == "paired_unverified" && peer.bluetooth_inbound &&
                peer.pending_finish_expires_ms > System.currentTimeMillis()) || !connecting.compareAndSet(false, true)) {
            link.pipe.close(); return
        }
        val deadline = java.util.Timer("magnolie-bt-authentication", true)
        var proved = false
        deadline.schedule(object : java.util.TimerTask() { override fun run() { runCatching { link.pipe.close() } } }, 15_000)
        try {
            if (peer.state == "paired_unverified" && bluetoothFinishRetried != peer.pending_finish) {
                bluetoothFinishRetried = peer.pending_finish
                val sent = TelefonKanonisch.json.parseToJsonElement(peer.pending_finish) as JsonObject
                TelefonRahmen.schreiben(link.pipe.output, sent)
                val reply = TelefonRahmen.lesen(link.pipe.input)
                requireExact(reply, setOf("p", "type", "side", "transcript", "proof"))
                check(reply.string("p") == TelefonParameter.PROTOKOLL && reply.string("type") == "pair_finish" &&
                    reply.string("side") == "desktop" && reply.string("transcript") == sent.string("transcript"))
                TelefonKrypto.b64(reply.string("proof"), 32)
            } else try {
                session(peer, TelefonTransportArt.BLUETOOTH, link.pipe, bluetoothAddress = link.address,
                    bluetoothInbound = true, authenticated = { deadline.cancel(); proved = true })
            } catch (error: Exception) {
                if (peer.state == "paired_unverified") bluetoothFinishRetried = ""
                throw error
            }
        } finally {
            deadline.cancel(); runCatching { link.pipe.close() }
            activeTransport = null; connecting.set(false)
            if (proved) bluetoothFirstSessionUntil = 0
            if (wifiAvailable && System.nanoTime() >= bluetoothFirstSessionUntil || storage.peers().peer?.state == "paired_unverified") reconnect()
        }
    }

    fun setBluetoothEnabled(enabled: Boolean) {
        if (enabled && (!storage.enabled() || safePeer()?.state != "paired"))
            throw TelefonProtokollFehler("Bluetooth erfordert eine aktive, bereits per WLAN gekoppelte Telefonverbindung.")
        if (enabled && !bluetooth.erlaubt()) throw SecurityException("Bluetooth permission missing")
        storage.setBluetoothEnabled(enabled)
        if (!enabled) {
            bluetoothBindingAddress = ""; bluetoothBindingUntil = 0
            bluetoothFirstSessionUntil = 0
            runCatching { bluetoothListener?.close() }; bluetoothListener = null
        }
        else ensureBluetoothListener()
        if (!enabled && activeTransport?.first == TelefonTransportArt.BLUETOOTH)
            activeTransport?.second?.let { runCatching { it.close() } }
        _state.value = _state.value.copy(bluetoothEnabled = enabled, bluetoothSelecting = false,
            bluetoothDevices = emptyList())
        reconnect()
    }

    fun pairedBluetoothDevices(): List<TelefonBluetoothZiel> {
        if (!storage.enabled() || safePeer()?.state != "paired") return emptyList()
        return bluetooth.gekoppelteGeraete().also {
            _state.value = _state.value.copy(bluetoothSelecting = true, bluetoothDevices = it, error = "")
        }
    }

    fun assignBluetooth(address: String) {
        if (!storage.enabled() || !storage.bluetoothEnabled()) throw TelefonProtokollFehler("Bluetooth-Fallback ist ausgeschaltet.")
        val peer = safePeer()?.takeIf { it.state == "paired" }
            ?: throw TelefonProtokollFehler("Die Telefonverbindung ist noch nicht sicher per WLAN gekoppelt.")
        if (!bluetooth.erlaubt()) throw SecurityException("Bluetooth permission missing")
        require(bluetooth.gekoppelteGeraete().any { it.address == address })
        bluetoothBindingAddress = address
        bluetoothBindingUntil = System.nanoTime() + 120_000_000_000L
        ensureBluetoothListener()
        if (!connecting.compareAndSet(false, true)) return
        thread(name = "magnolie-phone-bluetooth-verify", isDaemon = true) {
            try {
                val pipe = bluetooth.verbinden(address)
                session(peer, TelefonTransportArt.BLUETOOTH, pipe, bluetoothAddress = address)
            } catch (error: Exception) {
                if (serviceRunning && storage.enabled()) _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.OFFLINE,
                    error = error.message.orEmpty())
            } finally { connecting.set(false); reconnect() }
        }
    }

    fun discover(): List<GefundenerDesktop> {
        check(storage.enabled())
        if (!discovering.compareAndSet(false, true)) return _state.value.found
        _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.DISCOVERING, error = "")
        return try {
            TelefonEntdeckung.suchen(context).also { found ->
                _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.OFFLINE, found = found)
            }
        } catch (error: Exception) {
            _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.OFFLINE,
                error = error.message.orEmpty())
            emptyList()
        } finally {
            discovering.set(false)
        }
    }

    fun beginPairing(desktop: GefundenerDesktop) {
        beginPairing(desktop) { TelefonTcpRoehre(desktop.host, localAddress = desktop.localAddress) }
    }

    internal fun beginPairing(desktop: GefundenerDesktop, bluetoothAddress: String = "", open: () -> TelefonRoehre): Boolean {
        val generation = pairingGeneration
        check(storage.enabled())
        val current = safePeer()
        if (!organizerPairingAllowed(current, desktop.deviceId))
            throw TelefonProtokollFehler("Only one Organizer can be paired. Remove the existing Organizer before changing devices.")
        if (current != null)
            throw TelefonProtokollFehler("Dieser Organizer ist bereits kryptografisch gekoppelt.")
        if (!pairing.compareAndSet(false, true)) return false
        var staticPrivate: ByteArray? = null
        var ephemeralPrivate: ByteArray? = null
        var socket: TelefonRoehre? = null
        val expiryLock = Any()
        var attempt: PendingPairing? = null
        try {
            val (identity, privateKey) = storage.identity(Build.MODEL.orEmpty())
            staticPrivate = privateKey
            val (ephemeralKey, ephemeralPublic) = TelefonKrypto.schluesselpaar()
            ephemeralPrivate = ephemeralKey
            val init = buildJsonObject {
                put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive("pair_init"))
                put("pairing_token", JsonPrimitive(desktop.token)); put("device_id", JsonPrimitive(identity.device_id))
                put("role", JsonPrimitive("phone")); put("display_name", JsonPrimitive(identity.display_name))
                put("static_public", JsonPrimitive(identity.static_public)); put("ephemeral_public", JsonPrimitive(TelefonKrypto.b64(ephemeralPublic)))
                put("nonce", JsonPrimitive(TelefonKrypto.b64(TelefonKrypto.zufall(32)))); put("versions", JsonArray(listOf(JsonPrimitive(1))))
            }
            val connection = TelefonPaarungsRoehre(open(), onExpired = {
                synchronized(expiryLock) {
                    val expired = attempt
                    if (expired != null && pending.compareAndSet(expired, null)) {
                        expired.close()
                        synchronized(this) {
                            if (serviceRunning && storage.enabled()) _state.value = _state.value.copy(
                                connection = TelefonVerbindungsstatus.OFFLINE, pairingCode = "", pairingFingerprint = "", pairingName = "")
                            pairing.set(false)
                        }
                    }
                }
            })
            socket = connection
            if (bluetoothAddress.isNotBlank()) bluetoothFirstSessionUntil = connection.expiresAtNanos
            connection.setReadTimeout(10_000)
            TelefonRahmen.schreiben(connection.output, init)
            val response = TelefonRahmen.lesen(connection.input)
            connection.setReadTimeout(120_000)
            requireExact(response, setOf("p", "type", "device_id", "role", "display_name", "static_public", "ephemeral_public", "nonce", "version"))
            if (response.string("p") != TelefonParameter.PROTOKOLL || response.string("type") != "pair_response" ||
                response.string("role") != "desktop" || response.string("device_id") != desktop.deviceId ||
                response.number("version") != 1) throw TelefonProtokollFehler("Ungültige Pairing-Antwort.")
            val responseName = response.string("display_name")
            if (responseName.codePointCount(0, responseName.length) !in 1..60 || responseName.any { it.isISOControl() })
                throw TelefonProtokollFehler("Ungültiger Anzeigename.")
            TelefonKrypto.b64(response.string("nonce"), 32)
            val material = TelefonKrypto.paarung(init, response, ephemeralKey, privateKey)
            synchronized(expiryLock) {
                if (System.nanoTime() >= connection.expiresAtNanos) {
                    material.schluessel.fill(0)
                    throw java.io.IOException(context.getString(io.gitlab.maik3531.magnolienotes.R.string.telefon_status_getrennt))
                }
                synchronized(this) {
                    check(generation == pairingGeneration && safePeer() == null)
                    attempt = PendingPairing(connection, response, material, privateKey, ephemeralKey, desktop.host, bluetoothAddress, generation)
                    pending.getAndSet(attempt)?.close()
                    _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.CODE_PENDING,
                        pairingCode = material.code, pairingName = responseName,
                        pairingFingerprint = TelefonKrypto.fingerabdruck(TelefonKrypto.b64(response.string("static_public"), 32)))
                }
            }
            return true
        } catch (error: Exception) {
            runCatching { socket?.close() }; staticPrivate?.fill(0); ephemeralPrivate?.fill(0)
            pairing.set(false)
            _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.ERROR, error = error.message.orEmpty())
            throw error
        }
    }

    fun confirmPairing(matches: Boolean) {
        val pair = synchronized(this) {
            (pending.getAndSet(null) ?: return).also { confirmingPairing = it }
        }
        try {
            if (!matches) {
                TelefonRahmen.schreiben(pair.socket.output, buildJsonObject {
                    put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive("pair_abort")); put("reason", JsonPrimitive("code_mismatch"))
                })
                _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.OFFLINE, pairingCode = "")
                return
            }
            val transcript = TelefonKrypto.b64(pair.material.transcript)
            TelefonRahmen.schreiben(pair.socket.output, proofObject("pair_confirm", "phone", transcript,
                TelefonKrypto.beweis(pair.material, "magnolie-phone-pair-v1/confirm\u0000", "phone")))
            val desktopConfirm = TelefonRahmen.lesen(pair.socket.input)
            checkProof(desktopConfirm, "pair_confirm", "desktop", pair.material, "magnolie-phone-pair-v1/confirm\u0000")
            val phoneFinish = proofObject("pair_finish", "phone", transcript,
                TelefonKrypto.beweis(pair.material, "magnolie-phone-pair-v1/finish\u0000", "phone"))
            val peer = TelefonPeer(pair.response.string("device_id"), pair.response.string("display_name"),
                pair.response.string("static_public"), state = "paired_unverified", last_host = pair.host,
                bluetooth_address = pair.bluetoothAddress, bluetooth_inbound = pair.bluetoothAddress.isNotBlank(),
                pending_finish = TelefonKanonisch.text(phoneFinish), pending_finish_expires_ms = System.currentTimeMillis() + 600_000)
            synchronized(this) {
                if (pair.generation != pairingGeneration || safePeer() != null)
                    throw TelefonProtokollFehler("Ein Organizer ist bereits kryptografisch gekoppelt.")
                storage.savePeer(peer)
            }
            TelefonRahmen.schreiben(pair.socket.output, phoneFinish)
            val finish = TelefonRahmen.lesen(pair.socket.input)
            checkProof(finish, "pair_finish", "desktop", pair.material, "magnolie-phone-pair-v1/finish\u0000")
            val complete = peer.copy(state = "paired", last_contact_ms = System.currentTimeMillis(), pending_finish = "", pending_finish_expires_ms = 0)
            peerEffect(peer, pair.generation) {
                storage.savePeer(complete)
                if (complete.bluetooth_inbound) {
                    storage.setBluetoothEnabled(true)
                    bluetoothFirstSessionUntil = System.nanoTime() + 120_000_000_000L
                }
                val withControls = ensureControlMessages(complete)
                _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.PAIRED, peer = withControls, bluetoothEnabled = storage.bluetoothEnabled(),
                    pairingCode = "", pairingFingerprint = "", pairingName = "", error = "")
            }
        } catch (error: Exception) {
            _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.ERROR, error = error.message.orEmpty())
            throw error
        } finally {
            pair.close()
            synchronized(this) {
                if (confirmingPairing === pair) confirmingPairing = null
                if (pair.generation == pairingGeneration) pairing.set(false)
            }
            if (safePeer() != null) { runCatching { ensureBluetoothListener() }; reconnect() }
        }
    }

    @Synchronized fun unpair() {
        identifierEpoch++; identifierPermissionTicket = null; identifierRequests.clear()
        Ablage.hole(context).personalCustomChange { PersonalCustomState(items = it.items, firedHighWater = it.firedHighWater) }
        Erinnerung.customNeuStellen(context)
        pairingGeneration++
        lifecycleGeneration++
        bluetoothBindingAddress = ""; bluetoothBindingUntil = 0
        bluetoothFirstSessionUntil = 0
        pending.getAndSet(null)?.close(); closeTransport()
        runCatching { confirmingPairing?.socket?.close() }
        pairing.set(false)
        synchronized(captureLock) {
            outgoingScope = null
            safePeer()?.let { queue.deletePeer(it.device_id) }; storage.savePeer(null)
            storage.setPersonalSync(false, false, false, false)
        }
        _state.value = _state.value.copy(peer = null, connection = TelefonVerbindungsstatus.OFFLINE)
    }

    private fun reconnect() {
        val passive = safePeer()
        if (serviceRunning && storage.enabled() && passive?.state == "paired_unverified" && passive.bluetooth_inbound &&
            passive.pending_finish_expires_ms > System.currentTimeMillis()) {
            runCatching { ensureBluetoothListener() }
            bluetoothRecoveryHandler.removeCallbacks(bluetoothRecoveryPoll)
            bluetoothRecoveryHandler.postDelayed(bluetoothRecoveryPoll, 1000)
            return
        }
        if (serviceRunning && storage.enabled() && passive?.state == "paired" && passive.bluetooth_inbound &&
            (!wifiAvailable || System.nanoTime() < bluetoothFirstSessionUntil)) {
            runCatching { ensureBluetoothListener() }
            return
        }
        if (!serviceRunning || !storage.enabled() || !connecting.compareAndSet(false, true)) return
        thread(name = "magnolie-phone-reconnect", isDaemon = true) {
            try {
                var peer = safePeer() ?: return@thread
                runCatching { ensureBluetoothListener() }
                if (peer.state == "paired_unverified" && peer.pending_finish_expires_ms < System.currentTimeMillis()) {
                    synchronized(this) { if (safePeer() == peer) unpair() }
                    stopBluetoothSetup()
                    return@thread
                }
                var host = peer.last_host
                if (peer.state == "paired_unverified" && !peer.bluetooth_inbound && retryFinish(peer, host)) peer = safePeer() ?: return@thread
                if (peer.bluetooth_inbound && (peer.state == "paired_unverified" || !wifiAvailable || System.nanoTime() < bluetoothFirstSessionUntil)) return@thread
                var direct: TelefonRoehre? = null
                if (wifiAvailable && host.isNotBlank()) direct = runCatching { TelefonTcpRoehre(host, 1_200) }.getOrNull()
                if (direct == null && wifiAvailable) {
                    _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.DISCOVERING, error = "")
                    host = TelefonEntdeckung.suchen(context, peerId = peer.device_id).firstOrNull()?.host.orEmpty()
                }
                val selected = if (direct != null) TelefonTransportArt.WIFI to direct else
                    TelefonTransportwahl.oeffnen(wifiAvailable && host.isNotBlank(), peer.bluetooth_address,
                        !peer.bluetooth_inbound && storage.bluetoothEnabled() && bluetooth.erlaubt(),
                        wifi = { TelefonTcpRoehre(host) }, bluetooth = bluetooth::verbinden)
                session(peer, selected.first, selected.second,
                    wifiHost = if (selected.first == TelefonTransportArt.WIFI) host else "")
            } catch (error: Exception) {
                if (serviceRunning && storage.enabled()) _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.OFFLINE, error = error.message.orEmpty())
            } finally {
                activeTransport = null; connecting.set(false)
                if (serviceRunning && storage.enabled() && safePeer() != null) {
                    Thread.sleep(1_000)
                    reconnect()
                }
            }
        }
    }

    private fun retryFinish(peer: TelefonPeer, host: String): Boolean = runCatching {
        if (peer.pending_finish.isBlank()) return@runCatching false
        val sent = TelefonKanonisch.json.parseToJsonElement(peer.pending_finish) as JsonObject
        Socket().use { socket ->
            socket.connect(InetSocketAddress(host, TelefonParameter.PORT), 10_000); socket.soTimeout = 10_000
            TelefonRahmen.schreiben(socket.getOutputStream(), sent)
            val finish = TelefonRahmen.lesen(socket.getInputStream())
            requireExact(finish, setOf("p", "type", "side", "transcript", "proof"))
            if (finish.string("p") != TelefonParameter.PROTOKOLL || finish.string("type") != "pair_finish" ||
                finish.string("side") != "desktop" || finish.string("transcript") != sent.string("transcript"))
                throw TelefonProtokollFehler("Ungültiger Pairing-Abschluss.")
            TelefonKrypto.b64(finish.string("proof"), 32)
        }
        // Erst der anschließende gepinnte FS-Reconnect bestätigt den Abschluss lokal.
        true
    }.getOrDefault(false)

    private fun session(initialPeer: TelefonPeer, transport: TelefonTransportArt, pipe: TelefonRoehre,
                        bluetoothAddress: String = "", wifiHost: String = "", bluetoothInbound: Boolean = false, authenticated: () -> Unit = {}) {
        val generation = pairingGeneration
        var peer = try { peerEffect(initialPeer, generation) { it } }
            catch (error: Exception) { pipe.close(); throw error }
        val (identity, staticPrivate) = storage.identity(Build.MODEL.orEmpty())
        synchronized(this) {
            if (!serviceRunning || !storage.enabled() || generation != pairingGeneration || safePeer() != peer) {
                pipe.close(); staticPrivate.fill(0); return
            }
            activeTransport = transport to pipe
        }
        val authenticationDeadline = if (transport == TelefonTransportArt.BLUETOOTH)
            TelefonPaarungsRoehre(pipe, 15_000) else null
        _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.AUTHENTICATING, error = "")
        try {
            val secrets = TelefonSession.start(identity, peer, staticPrivate)
            TelefonRahmen.schreiben(pipe.output, secrets.start)
            TelefonSession.finish(secrets, TelefonRahmen.lesen(pipe.input), identity, peer,
                pipe.input, pipe.output).use { channel ->
                channel.send(buildJsonObject {
                    put("type", JsonPrimitive("session_ready")); put("connection_id", JsonPrimitive(UUID.randomUUID().toString()))
                    put("capabilities_revision", JsonPrimitive(maxOf(1, peer.capabilities_revision))); put("last_received_seq", JsonPrimitive(-1))
                })
                TelefonNachrichten.validateReady(channel.receive())
                authenticationDeadline?.disarm()
                authenticated()
                peerEffect(peer, generation) { current ->
                    peer = current
                    if (peer.state == "paired_unverified") {
                        peer = peer.copy(state = "paired", pending_finish = "", pending_finish_expires_ms = 0)
                        storage.savePeer(peer)
                        if (transport == TelefonTransportArt.BLUETOOTH && peer.bluetooth_inbound) storage.setBluetoothEnabled(true)
                    }
                    peer = ensureControlMessages(peer)
                }
                val controls = sendDue(peer, channel, generation).toMutableSet()
                while (controls.isNotEmpty()) {
                    val payload = channel.receive()
                    when (payload.string("type")) {
                        "ack" -> {
                            TelefonNachrichten.validateAck(payload)
                            val id = payload.string("message_id")
                            val policy = queue.outboxPolicy(peer.device_id, id)
                            if (policy == "invalid" || transport == TelefonTransportArt.BLUETOOTH && policy == "wifi_only")
                                throw TelefonProtokollFehler("WLAN-gebundene Bestätigung über Bluetooth.")
                            peerEffect(peer, generation) { handleAck(it.device_id, id, payload.string("status"), payload.string("error")) }
                            if (id in controls) {
                                if (payload.string("status") !in setOf("accepted", "duplicate"))
                                    throw TelefonProtokollFehler("Magnolie Notes hat die Sitzung beendet. App und Organizer müssen denselben Protokollstand verwenden.")
                                controls.remove(id)
                            }
                        }
                        "message" -> receiveMessage(peer, payload, channel, generation)
                        "ping" -> {
                            TelefonNachrichten.validateHeartbeat(payload)
                            channel.send(buildJsonObject { put("type", JsonPrimitive("pong")); put("ping_id", payload.getValue("ping_id")); put("sent_ms", payload.getValue("sent_ms")) })
                        }
                        else -> throw TelefonProtokollFehler("Unbekannter sicherer Inhalt.")
                    }
                }
                peer = sessionEstablished(peer, generation, transport, wifiHost, bluetoothAddress, bluetoothInbound)
                synchronized(this) {
                    refreshCustomAuthorization()
                    if (customSupported(peer)) Ablage.hole(context).bestand.value.personalCustom.local?.let {
                        queue.removeKind(peer.device_id, "personal_sync.custom_settings")
                        queue.queue(peer.device_id, "personal_sync.custom_settings", it, 86_400_000)
                    }
                    if (transport == TelefonTransportArt.WIFI && storage.personalAutoWifi()) requestCustom("auto_wifi")
                }
                peerEffect(peer, generation) { current ->
                    peer = current
                    val now = System.currentTimeMillis()
                    val modules = buildSet {
                        if (peer.personal_notes_sync_granted && peer.remote_personal_notes_sync_granted) add("notes")
                        if (peer.personal_tasks_sync_granted && peer.remote_personal_tasks_sync_granted) add("tasks")
                    }
                    if (transport == TelefonTransportArt.WIFI && storage.personalAutoWifi() && modules.isNotEmpty() &&
                        peer.own_device && peer.remote_own_device)
                        Ablage.hole(context).personalSyncSnapshot(modules, negotiatedPersonalFormat(peer, modules))
                    if (shouldStartPersonalSyncOnSecureWifi(transport, true, storage.personalAutoWifi(),
                            peer.own_device, peer.remote_own_device, modules.isNotEmpty(),
                            queue.hasActiveAutoRun(peer.device_id), now, storage.personalSyncLastAuto(),
                            Ablage.hole(context).personalSyncCounter(), storage.personalSyncLastCounter())) {
                        runCatching { enqueuePersonalSync(peer, "auto_wifi") }
                    }
                }
                sendDue(peer, channel, generation)
                while (serviceRunning && storage.enabled()) {
                    val payload = channel.receive()
                    when (payload.string("type")) {
                        "ping" -> {
                            TelefonNachrichten.validateHeartbeat(payload)
                            channel.send(buildJsonObject { put("type", JsonPrimitive("pong")); put("ping_id", payload.getValue("ping_id")); put("sent_ms", payload.getValue("sent_ms")) })
                        }
                        "pong" -> TelefonNachrichten.validateHeartbeat(payload)
                        "ack" -> {
                            TelefonNachrichten.validateAck(payload)
                            val policy = queue.outboxPolicy(peer.device_id, payload.string("message_id"))
                            if (policy == "invalid" || transport == TelefonTransportArt.BLUETOOTH && policy == "wifi_only")
                                throw TelefonProtokollFehler("WLAN-gebundene Bestätigung über Bluetooth.")
                            peerEffect(peer, generation) { handleAck(it.device_id, payload.string("message_id"), payload.string("status"),
                                payload.string("error")) }
                        }
                        "message" -> receiveMessage(peer, payload, channel, generation)
                        "close" -> return
                        else -> throw TelefonProtokollFehler("Unbekannter sicherer Inhalt.")
                    }
                    sendDue(peer, channel, generation)
                }
            }
        } finally {
            authenticationDeadline?.close()
            staticPrivate.fill(0); runCatching { pipe.close() }
            if (serviceRunning && storage.enabled()) _state.value = _state.value.copy(connection = TelefonVerbindungsstatus.OFFLINE)
        }
    }

    internal fun sessionEstablished(expected: TelefonPeer, generation: Long, transport: TelefonTransportArt,
                                    wifiHost: String = "", bluetoothAddress: String = "", bluetoothInbound: Boolean = false): TelefonPeer =
        peerEffect(expected, generation) { current ->
            val peer = current.copy(last_contact_ms = System.currentTimeMillis(),
                last_host = wifiHost.ifBlank { current.last_host },
                bluetooth_address = bluetoothAddress.ifBlank { current.bluetooth_address },
                bluetooth_inbound = if (bluetoothAddress.isNotBlank()) bluetoothInbound else current.bluetooth_inbound)
            if (bluetoothAddress.isNotBlank()) { bluetoothBindingAddress = ""; bluetoothBindingUntil = 0 }
            storage.savePeer(peer)
            _state.value = _state.value.copy(peer = peer, bluetoothSelecting = false, bluetoothEnabled = storage.bluetoothEnabled(),
                bluetoothDevices = emptyList(), error = "", connection = if (transport == TelefonTransportArt.WIFI)
                    TelefonVerbindungsstatus.ONLINE_WIFI else TelefonVerbindungsstatus.ONLINE_BLUETOOTH)
            peer
        }

    internal fun receiveMessage(sessionPeer: TelefonPeer, message: JsonObject, channel: TelefonSecureChannel,
                               generation: Long) {
        val replies = mutableListOf<JsonObject>()
        val epoch = identifierEpoch
        val permissions = identifierPermissionMask()
        peerEffect(sessionPeer, generation) { receiveMessage(it, message, replies::add) }
        replies.forEach { reply ->
            if ((reply["body"] as? JsonObject)?.containsKey("identifiers") == true) {
                peerEffect(sessionPeer, generation) { current ->
                    if (epoch == identifierEpoch && permissions == identifierPermissionMask() && identifiersAllowed(current) &&
                        System.currentTimeMillis() < message.long("expires_ms")) channel.send(reply)
                }
            } else channel.send(reply)
        }
    }

    @Synchronized private fun receiveMessage(sessionPeer: TelefonPeer, message: JsonObject, send: (JsonObject) -> Unit) {
        val peer = safePeer()?.takeIf { it.device_id == sessionPeer.device_id && it.static_public == sessionPeer.static_public }
            ?: throw TelefonProtokollFehler("Unbekannte Gegenstelle.")
        val kind = runCatching { message.string("kind") }.getOrDefault("")
        if (kind in setOf("personal_sync.custom_settings", "personal_sync.custom_batch")) {
            val result = runCatching {
                TelefonNachrichten.validate(message)
                if (queue.duplicateResult(peer.device_id, message.string("message_id")) != null &&
                    !queue.receivedMatches(peer.device_id, message)) throw TelefonProtokollFehler("Conflicting custom message identity.")
                check(customSupported(peer))
                val body = message["body"] as JsonObject
                if (body["trigger"]?.jsonPrimitive?.content == "auto_wifi") check(activeTransport?.first == TelefonTransportArt.WIFI)
                refreshCustomAuthorization()
                val ablage = Ablage.hole(context)
                val changed = kind == "personal_sync.custom_settings" && ablage.bestand.value.personalCustom.remote != body
                ablage.personalCustomChange { state ->
                    if (kind == "personal_sync.custom_settings") state.copy(remote = PersonalSyncProtokoll.acceptCustomSettings(state.remote, body))
                    else PersonalCustom.apply(state, body)
                }
                if (changed) queue.removeKind(peer.device_id, "personal_sync.custom_request")
                Erinnerung.customNeuStellen(context)
                queue.receive(peer.device_id, message)
            }.getOrElse { "rejected" to when (it) {
                is java.io.IOException, is android.database.sqlite.SQLiteException -> "temporary_failure"
                is TelefonProtokollFehler -> "invalid_schema"
                else -> "not_granted"
            } }
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second))
            refreshModules()
            return
        }
        if (kind !in setOf("device_status.request", "dial_request.command", "answer_call.command", "end_call.command",
                "capabilities.update", "grants.update", "personal_sync.settings", "personal_sync.request",
                "personal_sync.batch", "personal_sync.report", "personal_sync.attachment_request",
                "personal_sync.attachment_chunk", "personal_sync.attachment_result",
                "personal_sync.deletion_proposals", "personal_sync.deletion_decision")) {
            val result = runCatching { queue.terminal(peer.device_id, message, "unsupported") }.getOrElse {
                "rejected" to "invalid_schema"
            }
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second)); return
        }
        if (kind.startsWith("personal_sync.")) {
            val current = peer
            if (kind != "personal_sync.settings") {
                val body = message["body"] as? JsonObject
                    ?: throw TelefonProtokollFehler("Personal-Sync-Inhalt fehlt.")
                PersonalSyncProtokoll.validate(kind, body)
                val runId = body.string("run_id")
                val advertised = if (kind == "personal_sync.request" && body.string("trigger") == "auto_wifi")
                    "wifi_only" else if (kind == "personal_sync.request") "any" else null
                val durable = queue.personalRunPolicy(peer.device_id, runId)
                if (durable != null && advertised != null && durable != advertised)
                    throw TelefonProtokollFehler("Widersprüchliche Personal-Sync-Policy.")
                val policy = durable ?: advertised ?: throw TelefonProtokollFehler("Personal-Sync-Request fehlt.")
                if (policy == "wifi_only" && activeTransport?.first != TelefonTransportArt.WIFI)
                    throw TelefonProtokollFehler("WLAN-gebundener Lauf über Bluetooth.")
            }
            queue.duplicateResult(peer.device_id, message.string("message_id"))?.let { duplicate ->
                val duplicateBody = message["body"] as? JsonObject
                val stillAllowed = runCatching {
                    TelefonNachrichten.validate(message)
                    duplicateBody != null && personalSyncTransmissionAllowed(current, kind, duplicateBody)
                }.getOrDefault(false)
                if (!stillAllowed) {
                    send(TelefonNachrichten.ack(message.string("message_id"), "rejected", "not_granted")); return
                }
                if (kind == "personal_sync.attachment_result" && duplicateBody!!.string("state") == "complete") {
                    val runId = duplicateBody.string("run_id")
                    queue.completeOutgoingAttachment(peer.device_id, runId,
                        (duplicateBody["reply"] as JsonPrimitive).content.toBooleanStrict(),
                        duplicateBody.string("records_hash"), duplicateBody.string("sha256"))
                    queue.releasePersonalReport(peer.device_id, runId,
                        queue.personalRunPolicy(peer.device_id, runId)
                            ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."))
                }
                send(TelefonNachrichten.ack(message.string("message_id"), duplicate.first, duplicate.second)); return
            }
            val result = runCatching {
                TelefonNachrichten.validate(message)
                val body = message["body"] as JsonObject
                val personalFormat = (body["format"] as? JsonPrimitive)?.content?.toIntOrNull()
                val requestedModules = if (kind == "personal_sync.request")
                    (body["modules"] as? JsonArray).orEmpty().map { (it as JsonPrimitive).content }
                else (body["run_id"] as? JsonPrimitive)?.content?.let { runId ->
                    queue.personalRun(peer.device_id, runId)?.get("modules") as? JsonArray
                }.orEmpty().map { (it as JsonPrimitive).content }
                if (personalFormat != null && personalFormat >= 2 &&
                    negotiatedPersonalFormat(current, requestedModules.ifEmpty { listOf("notes", "tasks") }) < personalFormat)
                    throw TelefonProtokollFehler("Personal-Sync-Format wurde nicht ausgehandelt.")
                if (kind == "personal_sync.settings") {
                    val remoteOwn = (body["own_device"] as JsonPrimitive).booleanOrNull == true
                    if (!remoteOwn) pauseCustom()
                    if (!remoteOwn) queue.purgePersonal(peer.device_id)
                    identifierEpoch++; identifierPermissionTicket = null; identifierRequests.clear()
                    storage.savePeer(current.copy(remote_own_device = remoteOwn))
                    return@runCatching queue.receive(peer.device_id, message)
                }
                if (!personalSyncTransmissionAllowed(current, kind, body))
                    return@runCatching queue.terminal(peer.device_id, message, "not_granted")
                if (kind == "personal_sync.request") {
                    if (body.string("trigger") == "auto_wifi" && activeTransport?.first != TelefonTransportArt.WIFI)
                        throw TelefonProtokollFehler("Auto-Sync-Request außerhalb des WLANs.")
                    queue.rememberPersonalRun(peer.device_id, body, message.long("expires_ms"))
                    val accepted = queue.receive(peer.device_id, message)
                    send(TelefonNachrichten.ack(message.string("message_id"), accepted.first, accepted.second))
                    return
                }
                if (kind == "personal_sync.batch") {
                    val request = queue.personalRun(peer.device_id, body.string("run_id"))
                        ?: throw TelefonProtokollFehler("Personal-Sync-Request fehlt.")
                    PersonalSyncProtokoll.validateBatchForRequest(request, body)
                    if (request.string("trigger") == "auto_wifi" && activeTransport?.first != TelefonTransportArt.WIFI)
                        throw TelefonProtokollFehler("Auto-Sync-Batch außerhalb des WLANs.")
                    val staged = queue.stagePersonalBatch(peer.device_id, message)
                    send(TelefonNachrichten.ack(message.string("message_id"), "accepted", "none"))
                    if (staged == null) return
                    completePersonalBatch(current, staged)
                    refreshModules(); return
                }
                if (kind == "personal_sync.attachment_request") {
                    val runId = body.string("run_id")
                    val request = queue.personalRun(peer.device_id, runId)
                        ?: throw TelefonProtokollFehler("Personal-Sync-Request fehlt.")
                    if (request.string("trigger") == "auto_wifi" && activeTransport?.first != TelefonTransportArt.WIFI)
                        throw TelefonProtokollFehler("Auto-Sync-Anhänge außerhalb des WLANs.")
                    val reply = (body["reply"] as JsonPrimitive).content.toBooleanStrict()
                    val wants = (body["wants"] as JsonArray).map { raw ->
                        val want = raw as JsonObject
                        (want["sha256"] as JsonPrimitive).content to (want["ranges"] as JsonArray).map { range ->
                            (range as JsonArray).map { (it as JsonPrimitive).content.toInt() }
                        }
                    }
                    val accepted = queue.receive(peer.device_id, message)
                    queue.requestedAttachmentChunks(peer.device_id, runId, reply, body.string("records_hash"), wants,
                        activeTransport?.first ?: TelefonTransportArt.WIFI).forEach { (hash, index, bytes) ->
                        queue.queue(peer.device_id, "personal_sync.attachment_chunk", buildJsonObject {
                            put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                            put("records_hash", body.getValue("records_hash")); put("sha256", JsonPrimitive(hash))
                            put("index", JsonPrimitive(index)); put("data", JsonPrimitive(Base64.getEncoder().encodeToString(bytes)))
                        }, 86_400_000, transportPolicy = queue.personalRunPolicy(peer.device_id, runId)
                            ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."))
                        bytes.fill(0)
                    }
                    return@runCatching accepted
                }
                if (kind == "personal_sync.attachment_chunk") {
                    val runId = body.string("run_id")
                    val policy = queue.personalRunPolicy(peer.device_id, runId)
                        ?: throw TelefonProtokollFehler("Personal-Sync-Request fehlt.")
                    if (policy == "wifi_only" && activeTransport?.first != TelefonTransportArt.WIFI)
                        throw TelefonProtokollFehler("Auto-Sync-Anhänge außerhalb des WLANs.")
                    val reply = (body["reply"] as JsonPrimitive).content.toBooleanStrict()
                    val hash = body.string("sha256"); val aggregate = body.string("records_hash")
                    val descriptor = queue.readyPersonalBatches().asSequence().filter { it.first == peer.device_id }
                        .flatMap { it.second.asSequence() }.map { it["body"] as JsonObject }
                        .filter { it.string("run_id") == runId && (it["reply"] as JsonPrimitive).content.toBooleanStrict() == reply &&
                            it.string("records_hash") == aggregate }
                        .flatMap { PersonalSyncProtokoll.decodeBatch(it).asSequence() }
                        .filter { it.kind == "note" }.flatMap { (it.value["attachments"] as JsonArray).asSequence() }
                        .map { it as JsonObject }.firstOrNull { (it["sha256"] as JsonPrimitive).content == hash }
                        ?: throw TelefonProtokollFehler("Attachment ist nicht im Manifest.")
                    val raw = Base64.getDecoder().decode(body.string("data"))
                    queue.stageIncomingAttachmentChunk(peer.device_id, runId, reply, aggregate, hash,
                        (descriptor["size"] as JsonPrimitive).content.toInt(), (descriptor["mime"] as JsonPrimitive).content,
                        body.long("index").toInt(), raw, policy, message.long("expires_ms")); raw.fill(0)
                    val accepted = queue.receive(peer.device_id, message)
                    send(TelefonNachrichten.ack(message.string("message_id"), accepted.first, accepted.second))
                    queue.readyPersonalBatches().firstOrNull { it.first == peer.device_id &&
                        (it.second.last()["body"] as JsonObject).string("run_id") == runId }?.let {
                        runCatching { completePersonalBatch(current, it.second) }.onFailure {
                            queue.queue(peer.device_id, "personal_sync.attachment_result", buildJsonObject {
                                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                                put("records_hash", JsonPrimitive(aggregate)); put("sha256", JsonPrimitive(hash))
                                put("state", JsonPrimitive("failed")); put("error", JsonPrimitive("invalid"))
                            }, 86_400_000, transportPolicy = policy)
                            storage.setPersonalSyncReport(context.getString(
                                io.gitlab.maik3531.magnolienotes.R.string.personal_sync_teilweise, "invalid"))
                        }
                    }
                    refreshModules(); return
                }
                if (kind == "personal_sync.attachment_result") {
                    val accepted = queue.receive(peer.device_id, message)
                    if (body.string("state") == "complete") queue.completeOutgoingAttachment(peer.device_id,
                        body.string("run_id"), (body["reply"] as JsonPrimitive).content.toBooleanStrict(),
                        body.string("records_hash"), body.string("sha256"))
                    queue.releasePersonalReport(peer.device_id, body.string("run_id"),
                        queue.personalRunPolicy(peer.device_id, body.string("run_id"))
                            ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."))
                    return@runCatching accepted
                }
                if (kind == "personal_sync.report") {
                    val request = queue.personalRun(peer.device_id, body.string("run_id"))
                        ?: throw TelefonProtokollFehler("Personal-Sync-Request fehlt.")
                    if (request.string("trigger") != body.string("trigger")) throw TelefonProtokollFehler("Widersprüchlicher Trigger.")
                    val pendingDeletions = ((body["deletions"] as JsonObject)["pending"] as JsonPrimitive).content.toInt()
                    val stateText = if (body.string("trigger") == "auto_wifi" && pendingDeletions > 0)
                        context.resources.getQuantityString(
                            io.gitlab.maik3531.magnolienotes.R.plurals.personal_sync_auto_offen,
                            pendingDeletions, pendingDeletions
                        )
                    else if (body.string("state") == "complete")
                        context.getString(io.gitlab.maik3531.magnolienotes.R.string.personal_sync_vollstaendig)
                    else context.getString(io.gitlab.maik3531.magnolienotes.R.string.personal_sync_teilweise, body.string("error"))
                    storage.setPersonalSyncReport(stateText)
                    if (body.string("state") == "complete" && body.string("trigger") == "auto_wifi") {
                        storage.setPersonalSyncLastAuto(System.currentTimeMillis())
                        storage.setPersonalSyncLastCounter(Ablage.hole(context).personalSyncCounter())
                    }
                    queue.markPersonalRun(peer.device_id, body.string("run_id"), "reported")
                }
                if (kind == "personal_sync.deletion_proposals") {
                    val proposals = PersonalSyncProtokoll.decodeDeletionProposals(body).map { value ->
                        PersonalDeletionProposal(body.string("run_id"), value.proposalId, value.kind, value.id,
                            value.parentId, value.clock, value.priorHash, value.deletedMs, value.label, peer.device_id)
                    }
                    synchronized(Ablage.SCHREIBSPERRE) {
                        checkNotNull(queue.personalRun(peer.device_id, body.string("run_id")))
                        Ablage.hole(context).personalSyncStageProposals(body.string("run_id"), peer.device_id, proposals)
                    }
                    storage.setPersonalSyncReport("${proposals.size} Löschungen warten auf manuelle Bestätigung.")
                }
                if (kind == "personal_sync.deletion_decision") {
                    val decisions = PersonalSyncProtokoll.decodeDeletionDecisions(body)
                    val applied = synchronized(Ablage.SCHREIBSPERRE) {
                        checkNotNull(queue.personalRun(peer.device_id, body.string("run_id")))
                        Ablage.hole(context).personalSyncApplyDecisions(body.string("decision_id"), decisions.map {
                            Triple(it.proposalId, it.decision, it.expectedClock) })
                    }
                    if (applied != "applied") return@runCatching queue.terminal(peer.device_id, message, applied)
                }
                val accepted = queue.receive(peer.device_id, message)
                accepted
            }.getOrElse { runCatching { queue.terminal(peer.device_id, message, "invalid_schema") }
                .getOrDefault("rejected" to "invalid_schema") }
            refreshModules()
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second)); return
        }
        if (kind == "dial_request.command" && (!TelefonModulStatus.dialRequest(context) ||
                !peer.remote_dial_request_granted || !peer.remote_dial_request_available)) {
            val denied = queue.terminal(peer.device_id, message, "not_granted")
            send(TelefonNachrichten.ack(message.string("message_id"), denied.first, denied.second)); return
        }
        if (kind == "device_status.request" && (message["body"] as? JsonObject)?.get("version") == JsonPrimitive(4)) {
            val result = runCatching {
                TelefonNachrichten.validate(message)
                if (System.currentTimeMillis() >= message.long("expires_ms")) return@runCatching "rejected" to "expired"
                if (!identifiersAllowed(peer)) return@runCatching "rejected" to "not_granted"
                val now = System.currentTimeMillis()
                identifierRequests.entries.removeAll { it.value <= now }
                val requestId = (message["body"] as JsonObject).string("request_id")
                val accepted = if (identifierRequests.containsKey(requestId)) "duplicate" to "none" else "accepted" to "none"
                if (identifierRequests.size >= 32) return@runCatching "rejected" to "temporary_failure"
                identifierRequests[requestId] = message.long("expires_ms")
                if (accepted.first == "accepted") {
                    val body = message["body"] as JsonObject
                    val report = DeviceStatusCollector.body(DeviceStatusCollector.collect(context, body.string("request_id")), 3)
                    val identifiers = DeviceIdentifiers.collect(AndroidDeviceIdentifierSource(context),
                        (body["include_identifiers"] as JsonPrimitive).booleanOrNull == true)
                    send(TelefonNachrichten.message("device_status.report", JsonObject(report + mapOf(
                        "version" to JsonPrimitive(4), "identifiers" to identifiers)), 60_000))
                }
                accepted
            }.getOrElse { "rejected" to "invalid_schema" }
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second)); return
        }
        val response = if (kind == "device_status.request" && peer.device_status_granted && peer.remote_device_status_granted &&
            peer.remote_device_status_available) runCatching {
            TelefonNachrichten.validate(message)
            val body = message["body"] as JsonObject
            val requestId = body.string("request_id")
            val version = (body["version"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 1
            TelefonNachrichten.message("device_status.report",
                DeviceStatusCollector.body(DeviceStatusCollector.collect(context, requestId), version), 300_000)
        }.getOrNull() else null
        if (kind == "dial_request.command") {
            val result = runCatching {
                TelefonNachrichten.validate(message)
                if (message.long("expires_ms") < System.currentTimeMillis())
                    throw TelefonProtokollFehler("Abgelaufen.")
                val body = message["body"] as JsonObject
                queue.duplicateResult(peer.device_id, message.string("message_id"))?.let { return@runCatching it }
                // Only a freshly executed command can create scope; a durable effect marker cannot.
                val ref = body.string("client_ref")
                val status = if (2 in peer.remote_dial_request_versions) {
                    if (!TelefonEffekte(context).firstEvent("dial:$ref")) "failed" to "os_restricted"
                    else {
                        synchronized(captureLock) {
                            check(outgoingScope?.let { !it.ended && System.nanoTime() < it.deadline } != true)
                            outgoingScope = OutgoingScope(peer.device_id, peer.static_public, ref,
                                System.nanoTime() + 4L * 60 * 60 * 1_000_000_000)
                        }
                        placeOutgoing(body.string("to"), ref).also { if (it.first == "failed")
                            synchronized(captureLock) { outgoingScope = outgoingScope?.copy(ended = true,
                                deadline = System.nanoTime() + 60_000_000_000L) } }
                    }
                } else Waehlauftrag.submit(context, body)
                val response = TelefonNachrichten.message("dial_request.result", buildJsonObject {
                    put("client_ref", JsonPrimitive(body.string("client_ref")))
                    put("state", JsonPrimitive(status.first)); put("error", JsonPrimitive(status.second))
                    put("occurred_ms", JsonPrimitive(System.currentTimeMillis()))
                }, 60_000)
                queue.receive(peer.device_id, message, response)
            }.getOrElse { runCatching { queue.terminal(peer.device_id, message, "permanent_failure") }
                .getOrDefault("rejected" to "invalid_schema") }
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second)); return
        }
        if (kind == "answer_call.command") {
            val result = runCatching {
                TelefonNachrichten.validate(message)
                val body = message["body"] as JsonObject
                if (message.long("expires_ms") < System.currentTimeMillis()) {
                    incoming.rejectAnswer(body.string("call_ref"), body.string("command_ref"))
                    throw TelefonProtokollFehler("Abgelaufen.")
                }
                if (!storage.answerCallsEnabled() || !peer.remote_answer_call_granted ||
                    !peer.remote_answer_call_available) {
                    incoming.rejectAnswer(body.string("call_ref"), body.string("command_ref"))
                    return@runCatching queue.terminal(peer.device_id, message, "not_granted")
                }
                val status = incoming.answer(body.string("command_ref"), body.string("call_ref"))
                val response = TelefonNachrichten.message("answer_call.result", buildJsonObject {
                    put("command_ref", body.getValue("command_ref")); put("call_ref", body.getValue("call_ref"))
                    put("state", JsonPrimitive(status.first)); put("error", JsonPrimitive(status.second))
                    put("occurred_ms", JsonPrimitive(System.currentTimeMillis()))
                }, 60_000)
                queue.receive(peer.device_id, message, response)
            }.getOrElse { runCatching { queue.terminal(peer.device_id, message, "permanent_failure") }
                .getOrDefault("rejected" to "invalid_schema") }
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second)); return
        }
        if (kind == "end_call.command") {
            val result = runCatching {
                TelefonNachrichten.validate(message)
                val body = message["body"] as JsonObject
                val scoped = body.string("expected_state") == "offhook" && scopedOutgoing(peer, body.string("call_ref"), active = true)
                val status = if (message.long("expires_ms") < System.currentTimeMillis()) "failed" to "expired"
                    else if (!scoped && (!storage.answerCallsEnabled() || !peer.remote_end_call_granted || !peer.remote_end_call_available))
                        "failed" to "not_granted"
                    else if (body.string("expected_state") == "ringing" && !peer.remote_answer_call_granted)
                        "failed" to "not_granted"
                    else incoming.end(body.string("command_ref"), body.string("call_ref"),
                        body.long("expected_revision").toInt(), body.string("expected_state"), scoped)
                val response = TelefonNachrichten.message("end_call.result", buildJsonObject {
                    put("command_ref", body.getValue("command_ref")); put("call_ref", body.getValue("call_ref"))
                    put("state", JsonPrimitive(status.first)); put("error", JsonPrimitive(status.second))
                    put("occurred_ms", JsonPrimitive(System.currentTimeMillis()))
                }, 60_000)
                queue.receive(peer.device_id, message, response)
            }.getOrElse { runCatching { queue.terminal(peer.device_id, message, "permanent_failure") }
                .getOrDefault("rejected" to "invalid_schema") }
            send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second)); return
        }
        val result = if (kind == "device_status.request" && (!peer.device_status_granted || !peer.remote_device_status_granted ||
                !peer.remote_device_status_available))
            queue.terminal(peer.device_id, message, "not_granted")
            else queue.receive(peer.device_id, message, response, validateExtra = {
                if (kind in setOf("capabilities.update", "grants.update")) {
                    val revision = (message["body"] as JsonObject).long("revision")
                    val current = safePeer() ?: throw TelefonProtokollFehler("Unbekannte Gegenstelle.")
                    if (kind == "capabilities.update" && revision <= current.remote_capabilities_revision ||
                        kind == "grants.update" && revision <= current.remote_grants_revision) throw TelefonProtokollFehler("Veraltete Revision.")
                }
            })
        if (result.first in setOf("accepted", "duplicate") && kind in setOf("capabilities.update", "grants.update")) {
            identifierEpoch++; identifierRequests.clear()
            check(queue.receivedMatches(peer.device_id, message))
            // A durably accepted control effect remains replayable after its wire TTL.
            TelefonNachrichten.validate(message, message.long("created_ms"))
            val revision = (message["body"] as JsonObject).long("revision")
            val current = peer
            val savedRevision = if (kind == "capabilities.update") current.remote_capabilities_revision else current.remote_grants_revision
            if (revision <= savedRevision) {
                queue.controlApplied(peer.device_id, message.string("message_id"))
                send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second))
                return
            }
            val body = message["body"] as JsonObject
            val updated = if (kind == "capabilities.update") {
                val items = body["items"] as JsonObject
                current.copy(remote_capabilities_revision = revision,
                    remote_device_status_available = ((items["device_status"] as JsonObject)["available"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_device_status_versions = ((items["device_status"] as JsonObject)["versions"] as JsonArray).map { (it as JsonPrimitive).content.toInt() },
                    remote_dial_request_available = ((items["dial_request"] as JsonObject)["available"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_dial_request_versions = ((items["dial_request"] as JsonObject)["versions"] as JsonArray)
                        .map { (it as JsonPrimitive).content.toInt() },
                    remote_answer_call_available = ((items["answer_call"] as JsonObject)["available"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_end_call_available = ((items["end_call"] as JsonObject)["available"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_personal_notes_sync_versions = ((items["personal_notes_sync"] as JsonObject)["versions"] as JsonArray)
                        .map { (it as JsonPrimitive).content.toInt() }.filter { it in 1..3 }.distinct().sorted(),
                    remote_personal_tasks_sync_versions = ((items["personal_tasks_sync"] as JsonObject)["versions"] as JsonArray)
                        .map { (it as JsonPrimitive).content.toInt() }.filter { it in 1..4 }.distinct().sorted(),
                    remote_personal_tasks_sync_available = ((items["personal_tasks_sync"] as JsonObject)["available"] as JsonPrimitive).booleanOrNull == true)
            } else {
                val grants = body["grants"] as JsonObject
                current.copy(remote_grants_revision = revision,
                    remote_device_status_granted = (grants["device_status"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_dial_request_granted = (grants["dial_request"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_answer_call_granted = (grants["answer_call"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_incoming_call_state_granted = (grants["incoming_call_state"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_incoming_call_number_granted = (grants["incoming_call_number"] as JsonPrimitive).content.toBooleanStrict(),
                    remote_end_call_granted = (grants["end_call"] as JsonPrimitive).content.toBooleanStrict())
                    .copy(remote_personal_notes_sync_granted = (grants["personal_notes_sync"] as JsonPrimitive).content.toBooleanStrict(),
                        remote_personal_tasks_sync_granted = (grants["personal_tasks_sync"] as JsonPrimitive).content.toBooleanStrict(),
                        remote_personal_deletions_sync_granted = (grants["personal_deletions_sync"] as JsonPrimitive).content.toBooleanStrict())
            }
            if (kind == "grants.update") {
                if (current.remote_incoming_call_state_granted && !updated.remote_incoming_call_state_granted ||
                    current.remote_incoming_call_number_granted && !updated.remote_incoming_call_number_granted)
                    queue.removeCallEvents()
                val revoked = buildSet {
                    if (!updated.remote_personal_notes_sync_granted) add("notes")
                    if (!updated.remote_personal_tasks_sync_granted) add("tasks")
                }
                queue.purgePersonalModules(peer.device_id, revoked)
                Ablage.hole(context).personalSyncRevokeModules(revoked)
            }
            if (kind == "grants.update" && !updated.remote_personal_deletions_sync_granted)
                queue.purgePersonalDeletionWire(peer.device_id).also {
                    Ablage.hole(context).personalSyncRevokeDeletions()
                }
            synchronized(captureLock) {
                if (!updated.remote_dial_request_granted || !updated.remote_dial_request_available ||
                    2 !in updated.remote_dial_request_versions) outgoingScope = null
                storage.savePeer(updated)
            }
            queue.controlApplied(peer.device_id, message.string("message_id"))
        }
        refreshModules()
        send(TelefonNachrichten.ack(message.string("message_id"), result.first, result.second))
    }

    @Synchronized private fun completePersonalBatch(peer: TelefonPeer, staged: List<JsonObject>): Unit = synchronized(Ablage.SCHREIBSPERRE) {
        val current = peerEffect(peer, pairingGeneration) { it }
        check(personalSyncTransmissionAllowed(current, "personal_sync.batch", staged.last()["body"] as JsonObject))
        val body = staged.last()["body"] as JsonObject
        val runId = body.string("run_id")
        val request = queue.personalRun(peer.device_id, runId)
            ?: throw TelefonProtokollFehler("Personal-Sync-Request fehlt.")
        val records = staged.flatMap {
            PersonalSyncProtokoll.validateBatchForRequest(request, it["body"] as JsonObject)
        }
        val reply = (body["reply"] as JsonPrimitive).content.toBooleanStrict()
        val format = body.long("format").toInt()
        val modules = (request["modules"] as JsonArray).map { (it as JsonPrimitive).content }.toSet()
        val prepared = if (format >= 2) prepareIncomingAttachments(peer, body, records, reply) ?: return else null
        val attachmentValues = prepared?.values ?: emptyMap()
        val applied = Ablage.hole(context).personalSyncApplyOnce(records, attachmentValues,
            "${peer.device_id}:$runId:$reply", modules, format)
        if (format >= 2) {
            val policy = queue.personalRunPolicy(peer.device_id, runId)
                ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt.")
            attachmentValues.keys.forEach { hash -> queue.queue(peer.device_id, "personal_sync.attachment_result",
                buildJsonObject {
                    put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                    put("records_hash", body.getValue("records_hash")); put("sha256", JsonPrimitive(hash))
                    put("state", JsonPrimitive("complete")); put("error", JsonPrimitive("none"))
                }, 86_400_000, transportPolicy = policy) }
        }
        queue.markPersonalDirectionApplied(peer.device_id, runId, reply)
        if (records.any { it.kind == "task" }) Erinnerung.allesNeuStellen(context)
        if (!reply && !queue.personalRunMarked(peer.device_id, runId, "responded")) {
            val format = request.long("format").toInt()
            val responseSnapshot = if (format >= 2) Ablage.hole(context).personalSyncSnapshotMitAnhaengen(modules, format)
                else io.gitlab.maik3531.magnolienotes.daten.PersonalSyncSnapshot(
                    Ablage.hole(context).personalSyncSnapshot(modules), emptyMap())
            val snapshot = buildSnapshotBatches(runId, responseSnapshot.records, true, format)
            val sentRecords = snapshot.first.flatMap(PersonalSyncProtokoll::decodeBatch)
            val aggregate = if (format >= 2) snapshot.first.first().string("records_hash") else ""
            val oversizedSkipped = snapshot.second
            val sentNoteIds = sentRecords.filter { it.kind == "note" }.map { it.id }.toSet()
            val localAttachments = Ablage.hole(context).notizen()
                .filter { it.id in sentNoteIds }.sumOf { it.anhaenge.size }
            val advertisedHashes = sentRecords.filter { it.kind == "note" }.flatMap {
                (it.value["attachments"] as? JsonArray).orEmpty().map { value -> (value as JsonObject).string("sha256") }
            }.toSet()
            val advertisedAttachments = sentRecords.filter { it.kind == "note" }.sumOf {
                (it.value["attachments"] as? JsonArray).orEmpty().size }
            val outgoingAttachments = responseSnapshot.attachments.filterKeys(advertisedHashes::contains)
            val attachmentsOmitted = (localAttachments - advertisedAttachments).coerceAtLeast(0)
            val count = { recordKind: String -> records.count { it.kind == recordKind } }
            val trigger = request.string("trigger")
            val report = buildJsonObject {
                put("format", JsonPrimitive(format)); put("run_id", JsonPrimitive(runId)); put("state", JsonPrimitive("complete"))
                put("trigger", JsonPrimitive(trigger)); put("transport", JsonPrimitive(if (activeTransport?.first == TelefonTransportArt.BLUETOOTH) "bluetooth" else "wifi"))
                put("sent", buildJsonObject { put("notes", JsonPrimitive(sentRecords.count { it.kind == "note" })); put("tasks", JsonPrimitive(sentRecords.count { it.kind == "task" })); put("notebooks", JsonPrimitive(sentRecords.count { it.kind == "notebook" })) })
                put("received", buildJsonObject { put("notes", JsonPrimitive(count("note"))); put("tasks", JsonPrimitive(count("task"))); put("notebooks", JsonPrimitive(count("notebook"))) })
                put("conflicts", JsonPrimitive(applied?.conflicts ?: 0)); put("attachments_omitted", JsonPrimitive(attachmentsOmitted))
                put("oversized_skipped", JsonPrimitive(oversizedSkipped)); put("started_ms", JsonPrimitive(System.currentTimeMillis()))
                put("finished_ms", JsonPrimitive(System.currentTimeMillis())); put("error", JsonPrimitive("none"))
                val current = Ablage.hole(context).bestand.value
                val pending = current.personalSync.pending_proposals
                put("deletions", buildJsonObject {
                    put("pending", JsonPrimitive(pending.size))
                    put("deleted", JsonPrimitive(current.personalSync.entities.values.count { it.state == "deleted" && it.status == "resolved" }))
                    put("restored", JsonPrimitive(current.personalSync.applied_decisions.count { it.endsWith(":restore") }))
                    put("conflicts", JsonPrimitive(pending.count { proposal ->
                        val key = if (proposal.kind == "attachment") "attachment\u0000${proposal.parent_id}\u0000${proposal.id}" else "${proposal.kind}\u0000${proposal.id}"
                        current.personalSync.entities[key]?.hash != proposal.prior_hash }))
                    put("blocked", JsonPrimitive(pending.count { proposal -> proposal.kind == "notebook" &&
                        current.notizen.any { it.notizbuchId == proposal.id } }))
                    put("trash", buildJsonObject {
                        put("notes", JsonPrimitive(current.papierkorb.count { it.art == "note" }))
                        put("tasks", JsonPrimitive(current.papierkorb.count { it.art == "task" }))
                        put("notebooks", JsonPrimitive(current.papierkorb.count { it.art == "notebook" }))
                        put("attachments", JsonPrimitive(current.papierkorb.count { it.art == "attachment" }))
                    })
                })
                if (format >= 2) put("attachments", buildJsonObject {
                    put("declared", JsonPrimitive(outgoingAttachments.size)); put("requested", JsonPrimitive(prepared?.received ?: 0))
                    put("sent", JsonPrimitive(outgoingAttachments.size)); put("received", JsonPrimitive(prepared?.received ?: 0))
                    put("reused", JsonPrimitive(prepared?.reused ?: 0)); put("preserved", JsonPrimitive(localAttachments))
                    put("failed", JsonPrimitive(0)); put("bytes", JsonPrimitive(prepared?.bytes ?: 0L))
                })
            }
            queue.queuePersonalCompletion(peer.device_id, runId, snapshot.first, report,
                queue.personalRunPolicy(peer.device_id, runId)
                    ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."), aggregate,
                if (format >= 2) outgoingAttachments.map { (hash, attachment) -> Triple(hash,
                    (attachment.descriptor["mime"] as JsonPrimitive).content, attachment.bytes) } else emptyList())
        }
        queue.finishPersonalBatch(peer.device_id, runId, reply)
        Ablage.hole(context).personalSyncAcknowledge(peer.device_id)
        storage.setPersonalSyncReport(context.getString(io.gitlab.maik3531.magnolienotes.R.string.personal_sync_vollstaendig))
    }

    private data class PreparedAttachments(val values: Map<String, Anhang>, val reused: Int,
                                           val received: Int, val bytes: Long)

    private fun prepareIncomingAttachments(peer: TelefonPeer, body: JsonObject,
                                           records: List<io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord>,
                                           reply: Boolean): PreparedAttachments? {
        val runId = body.string("run_id"); val aggregate = body.string("records_hash")
        val policy = queue.personalRunPolicy(peer.device_id, runId)
            ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt.")
        val descriptors = records.filter { it.kind == "note" }.flatMap {
            (it.value["attachments"] as? JsonArray).orEmpty().map { value -> value as JsonObject }
        }.associateBy { (it["sha256"] as JsonPrimitive).content }
        if (descriptors.size > 256 || descriptors.values.sumOf { (it["size"] as JsonPrimitive).content.toLong() } > 50L * 1024 * 1024)
            throw TelefonProtokollFehler("Attachment-Lauf ist zu groß.")
        val expires = System.currentTimeMillis() + 86_400_000
        var reused = 0
        val reusedHashes = mutableSetOf<String>()
        descriptors.forEach { (hash, descriptor) ->
            val size = (descriptor["size"] as JsonPrimitive).content.toInt()
            val mime = (descriptor["mime"] as JsonPrimitive).content
            queue.registerIncomingAttachment(peer.device_id, runId, reply, aggregate, hash, size, mime, policy, expires)
            val bytes = Ablage.hole(context).notizen().asSequence().flatMap { it.anhaenge.asSequence() }
                .mapNotNull { AnhangPruefung.dataUrl(it.daten)?.bytes }
                .firstOrNull { bytes -> java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
                    .joinToString("") { "%02x".format(it) } == hash }
            if (bytes != null && bytes.size == size && AnhangPruefung.mime(bytes) == mime &&
                queue.missingAttachmentRanges(peer.device_id, runId, reply, aggregate, hash).isNotEmpty()) {
                reused++
                reusedHashes += hash
                var offset = 0
                while (offset < bytes.size) {
                    val index = offset / PersonalSyncProtokoll.CHUNK_RAW
                    queue.stageIncomingAttachmentChunk(peer.device_id, runId, reply, aggregate, hash, size, mime,
                        index, bytes.copyOfRange(offset, minOf(bytes.size, offset + PersonalSyncProtokoll.CHUNK_RAW)), policy, expires)
                    offset += PersonalSyncProtokoll.CHUNK_RAW
                }
            }
        }
        val wants = descriptors.keys.sortedWith(PersonalSync::compareUtf8).mapNotNull { hash ->
            queue.missingAttachmentRanges(peer.device_id, runId, reply, aggregate, hash).takeIf { it.isNotEmpty() }?.let { hash to it }
        }
        if (wants.isNotEmpty()) {
            queue.queue(peer.device_id, "personal_sync.attachment_request", buildJsonObject {
                put("format", JsonPrimitive(2)); put("run_id", JsonPrimitive(runId)); put("reply", JsonPrimitive(reply))
                put("records_hash", JsonPrimitive(aggregate)); put("wants", JsonArray(wants.map { (hash, ranges) -> buildJsonObject {
                    put("sha256", JsonPrimitive(hash)); put("ranges", JsonArray(ranges.map { range ->
                        JsonArray(range.map { number -> JsonPrimitive(number) }) }))
                } }))
            }, 86_400_000, transportPolicy = policy)
            storage.setPersonalSyncReport(context.getString(
                io.gitlab.maik3531.magnolienotes.R.string.personal_sync_anhaenge_fortschritt,
                descriptors.size - wants.size, descriptors.size))
            return null
        }
        val result = mutableMapOf<String, Anhang>()
        descriptors.forEach { (hash, descriptor) ->
            val output = ByteArrayOutputStream((descriptor["size"] as JsonPrimitive).content.toInt())
            if (!queue.verifyIncomingAttachment(peer.device_id, runId, reply, aggregate, hash, output))
                throw TelefonProtokollFehler("Ungültiger Attachment-Inhalt.")
            val mime = (descriptor["mime"] as JsonPrimitive).content
            result[hash] = Anhang("", "", (descriptor["kind"] as JsonPrimitive).content,
                "data:$mime;base64,${Base64.getEncoder().encodeToString(output.toByteArray())}")
        }
        val received = descriptors.size - reused
        val transferredBytes = descriptors.filterKeys { hash -> hash !in reusedHashes }
            .values.sumOf { (it["size"] as JsonPrimitive).content.toLong() }
        return PreparedAttachments(result, reused, received, transferredBytes)
    }

    private fun sendDue(peer: TelefonPeer, channel: TelefonSecureChannel): Set<String> = sendDue(peer, channel, pairingGeneration)

    private fun sendDue(peer: TelefonPeer, channel: TelefonSecureChannel, generation: Long): Set<String> {
        val controls = mutableSetOf<String>()
        val transport = activeTransport?.first ?: throw TelefonProtokollFehler("Keine aktive Transportart.")
        queue.due(peer.device_id, transport).forEach { entry ->
            synchronized(this) {
                val current = peerEffect(peer, generation) { it }
                if (!serviceRunning || !storage.enabled()) return controls
                val kind = entry.payload.string("kind")
                if (kind == "incoming_call_state.event") {
                    val body = entry.payload["body"] as JsonObject
                    val stateAllowed = callStateAllowed(current, body)
                    val numberAllowed = body.string("number").isEmpty() ||
                        current.remote_incoming_call_number_granted && storage.incomingNumberEnabled() &&
                        context.checkSelfPermission(Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED
                    if (!stateAllowed || !numberAllowed) {
                        queue.acknowledge(peer.device_id, entry.messageId)
                        return@forEach
                    }
                    // Keep the final permission/scope check and write ordered with revocation/unpair.
                    channel.send(entry.payload)
                    queue.sent(entry.messageId, queue.attempts(entry.messageId))
                    return@forEach
                }
                if (kind == "selected_notifications_readonly.event") {
                    val body = entry.payload["body"] as JsonObject
                    if (!TelefonModulStatus.notifications(context) || body.string("package") !in storage.selectedPackages()) {
                        queue.acknowledge(peer.device_id, entry.messageId)
                        return@forEach
                    }
                }
                val policy = queue.outboxPolicy(peer.device_id, entry.messageId)
                if (policy == "invalid" || transport == TelefonTransportArt.BLUETOOTH && policy == "wifi_only")
                    return@forEach
                if (kind.startsWith("personal_sync.")) {
                    val body = entry.payload["body"] as JsonObject
                    if (kind.startsWith("personal_sync.custom_")) {
                        if (kind == "personal_sync.custom_request" && queue.hasKind(peer.device_id, "personal_sync.custom_settings")) return@forEach
                        if (!customTransmissionAllowed(current, kind, body)) {
                            queue.acknowledge(peer.device_id, entry.messageId); return@forEach
                        }
                        // Keep the final authorization check and socket write ordered with revocation.
                        channel.send(entry.payload)
                        queue.sent(entry.messageId, queue.attempts(entry.messageId))
                        return@forEach
                    } else if (!personalSyncTransmissionAllowed(current, kind, body)) {
                        queue.acknowledge(peer.device_id, entry.messageId); return@forEach
                    }
                }
            }
            channel.send(entry.payload)
            peerEffect(peer, generation) { queue.sent(entry.messageId, queue.attempts(entry.messageId)) }
            if (entry.payload.string("kind") in setOf("capabilities.update", "grants.update")) controls += entry.messageId
        }
        return controls
    }

    private fun handleAck(peerId: String, messageId: String, status: String, error: String) {
        queue.acknowledge(peerId, messageId, status, error)?.let { ack ->
            when {
                ack.state == "accepted" -> Ablage.hole(context).personalSyncDecisionAccepted(ack.decisionId)
                ack.state == "expired" || ack.state.startsWith("terminal:") ->
                    Ablage.hole(context).personalSyncDecisionStopped(ack.decisionId, ack.state)
            }
        }
    }

    private fun customSupported(peer: TelefonPeer) = peer.remote_personal_tasks_sync_available && 4 in peer.remote_personal_tasks_sync_versions &&
        4 in TelefonCapabilities.phase1().getValue("personal_tasks_sync").versions

    @Synchronized private fun refreshCustomAuthorization() {
        val ablage = Ablage.hole(context)
        val peer = safePeer() ?: run {
            ablage.personalCustomChange { it.copy(active = false) }
            Erinnerung.customNeuStellen(context)
            return
        }
        var initial = false
        ablage.personalCustomChange { old ->
            var state = PersonalCustom.bind(old, peer.device_id + ":" + peer.static_public)
            if (customSupported(peer) && state.local == null) {
                initial = true
                state = state.copy(local = customSettings(false, 1))
            }
            state.copy(active = customSupported(peer) && peer.own_device && peer.remote_own_device)
        }
        if (initial) queue.queue(peer.device_id, "personal_sync.custom_settings", ablage.bestand.value.personalCustom.local!!, 86_400_000)
        Erinnerung.customNeuStellen(context)
    }

    private fun customSettings(enabled: Boolean, revision: Long): JsonObject {
        check(revision in 1..9_007_199_254_740_991L)
        return buildJsonObject {
            put("format", JsonPrimitive(4)); put("scope", JsonPrimitive("custom")); put("enabled", JsonPrimitive(enabled))
            put("revision", JsonPrimitive(revision)); put("epoch", JsonPrimitive(UUID.randomUUID().toString()))
        }
    }

    @Synchronized fun setCustomSync(enabled: Boolean) {
        val peer = safePeer() ?: return
        check(customSupported(peer))
        refreshCustomAuthorization()
        val ablage = Ablage.hole(context)
        ablage.personalCustomChange { state -> state.copy(local = customSettings(enabled,
            (state.local?.get("revision")?.jsonPrimitive?.long ?: 0) + 1)) }
        queue.removeKind(peer.device_id, "personal_sync.custom_request")
        queue.removeKind(peer.device_id, "personal_sync.custom_settings")
        queue.queue(peer.device_id, "personal_sync.custom_settings", ablage.bestand.value.personalCustom.local!!, 86_400_000)
        Erinnerung.customNeuStellen(context)
        refreshModules()
    }

    @Synchronized private fun pauseCustom() {
        Ablage.hole(context).personalCustomChange { state -> state.copy(active = false,
            local = state.local?.let { customSettings(false, it.getValue("revision").jsonPrimitive.long + 1) }) }
        safePeer()?.let { peer ->
            queue.removeKind(peer.device_id, "personal_sync.custom_request")
            queue.removeKind(peer.device_id, "personal_sync.custom_settings")
            if (customSupported(peer)) Ablage.hole(context).bestand.value.personalCustom.local?.let {
                queue.queue(peer.device_id, "personal_sync.custom_settings", it, 86_400_000) }
        }
        Erinnerung.customNeuStellen(context)
    }

    private fun customTransmissionAllowed(peer: TelefonPeer, kind: String, body: JsonObject): Boolean {
        if (!customSupported(peer)) return false
        val state = Ablage.hole(context).bestand.value.personalCustom
        if (state.owner != peer.device_id + ":" + peer.static_public) return false
        if (kind == "personal_sync.custom_settings") return state.local == body
        return state.active && PersonalSyncProtokoll.customScopeAllowed(state.remote, state.local,
            listOf(4), listOf(4), peer.remote_own_device, peer.own_device,
            body.string("sender_epoch"), body.string("receiver_epoch"), body.long("sender_revision"), body.long("receiver_revision"))
    }

    @Synchronized private fun requestCustom(trigger: String): Boolean {
        val peer = safePeer() ?: return false
        refreshCustomAuthorization()
        val state = Ablage.hole(context).bestand.value.personalCustom
        val local = state.local ?: return false; val remote = state.remote ?: return false
        val body = buildJsonObject {
            put("format", JsonPrimitive(4)); put("trigger", JsonPrimitive(trigger))
            put("sender_epoch", local.getValue("epoch")); put("receiver_epoch", remote.getValue("epoch"))
            put("sender_revision", local.getValue("revision")); put("receiver_revision", remote.getValue("revision"))
        }
        if (!customTransmissionAllowed(peer, "personal_sync.custom_request", body)) return false
        queue.removeKind(peer.device_id, "personal_sync.custom_request")
        queue.queue(peer.device_id, "personal_sync.custom_request", body, 86_400_000,
            transportPolicy = if (trigger == "auto_wifi") "wifi_only" else "any")
        return true
    }

    @Synchronized fun customDeletionDecision(id: String, revision: Long, delete: Boolean) {
        refreshCustomAuthorization()
        Ablage.hole(context).personalCustomChange { PersonalCustom.decide(it, id, revision, delete) }
        Erinnerung.customNeuStellen(context)
    }

    @Synchronized private fun ensureControlMessages(initial: TelefonPeer): TelefonPeer {
        var peer = peerEffect(initial, pairingGeneration) { it }
        if (!queue.hasKind(peer.device_id, "capabilities.update")) {
            peer = peer.copy(capabilities_revision = peer.capabilities_revision + 1); storage.savePeer(peer)
            val notifications = TelefonModulStatus.notifications(context)
            val dialRequest = TelefonModulStatus.dialRequest(context)
            val dialPermission = TelefonModulStatus.dialPermissions(context)
            val incomingCalls = storage.incomingCallsEnabled() && context.checkSelfPermission(
                android.Manifest.permission.READ_PHONE_STATE) == android.content.pm.PackageManager.PERMISSION_GRANTED
            val callState = incomingCalls || dialRequest
            val incomingNumber = incomingCalls && storage.incomingNumberEnabled() && context.checkSelfPermission(
                android.Manifest.permission.READ_CALL_LOG) == android.content.pm.PackageManager.PERMISSION_GRANTED
            val answerCalls = incomingCalls && storage.answerCallsEnabled() && context.checkSelfPermission(
                android.Manifest.permission.ANSWER_PHONE_CALLS) == android.content.pm.PackageManager.PERMISSION_GRANTED &&
                TelefonModulStatus.telephony(context) && context.getSystemService(android.telecom.TelecomManager::class.java) != null
            val endCalls = callState && (storage.answerCallsEnabled() || dialRequest) && context.checkSelfPermission(
                android.Manifest.permission.ANSWER_PHONE_CALLS) == android.content.pm.PackageManager.PERMISSION_GRANTED &&
                Build.VERSION.SDK_INT >= 28 && TelefonModulStatus.telephony(context) &&
                context.getSystemService(android.telecom.TelecomManager::class.java) != null
            queue.queue(peer.device_id, "capabilities.update", TelefonNachrichten.capabilities(peer.capabilities_revision,
                TelefonCapabilities.phase1(notifications, dialRequest, TelefonModulStatus.dialResolvable(context),
                    dialPermission, callState, incomingNumber, answerCalls, endCalls,
                    identifiers = peer.own_device && peer.identifier_sharing_enabled && identifierPermissionMask() and 1 != 0)), 86_400_000)
        }
        if (!queue.hasKind(peer.device_id, "grants.update")) {
            peer = peer.copy(grants_revision = peer.grants_revision + 1); storage.savePeer(peer)
            queue.queue(peer.device_id, "grants.update", TelefonNachrichten.grants(peer.grants_revision,
                TelefonModulStatus.notifications(context), TelefonModulStatus.dialRequest(context),
                storage.incomingCallsEnabled() || storage.dialRequestEnabled(), storage.incomingNumberEnabled(), storage.answerCallsEnabled(),
                storage.answerCallsEnabled(), storage.personalOwnDevice() && storage.personalNotesEnabled(),
                storage.personalOwnDevice() && storage.personalTasksEnabled(),
                storage.personalOwnDevice() && storage.personalDeletionsEnabled()), 86_400_000)
        }
        return peer
    }

    @Synchronized private fun enqueuePersonalSync(expected: TelefonPeer, trigger: String): Boolean {
        val peer = peerEffect(expected, pairingGeneration) { it }
        if (!peer.own_device || !peer.remote_own_device) throw TelefonProtokollFehler("Eigenes Gerät ist nicht beidseitig bestätigt.")
        val modules = buildList { if (peer.personal_notes_sync_granted && peer.remote_personal_notes_sync_granted) add("notes")
            if (peer.personal_tasks_sync_granted && peer.remote_personal_tasks_sync_granted) add("tasks") }
        if (modules.isEmpty()) throw TelefonProtokollFehler("Keine beidseitige Personal-Sync-Freigabe.")
        if (trigger == "auto_wifi" && queue.hasActiveAutoRun(peer.device_id)) return false
        val runId = UUID.randomUUID().toString()
        val format = negotiatedPersonalFormat(peer, modules)
        val request = buildJsonObject {
            put("format", JsonPrimitive(format)); put("run_id", JsonPrimitive(runId)); put("trigger", JsonPrimitive(trigger))
            put("modules", JsonArray(modules.map(::JsonPrimitive)))
        }
        val requestMessage = TelefonNachrichten.message("personal_sync.request", request, 3_600_000)
        queue.rememberPersonalRun(peer.device_id, request, requestMessage.long("expires_ms"))
        if (format >= 2) {
            val snapshot = Ablage.hole(context).personalSyncSnapshotMitAnhaengen(modules.toSet(), format)
            val policy = queue.personalRunPolicy(peer.device_id, runId)
                ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt.")
            val batches = buildSnapshotBatches(runId, snapshot.records, false, format).first
            val aggregate = batches.first().string("records_hash")
            val advertised = batches.flatMap(PersonalSyncProtokoll::decodeBatch).filter { it.kind == "note" }
                .flatMap { (it.value["attachments"] as? JsonArray).orEmpty() }
                .map { (it as JsonObject).string("sha256") }.toSet()
            val attachments = snapshot.attachments.filterKeys(advertised::contains).map { (hash, attachment) -> Triple(hash,
                (attachment.descriptor["mime"] as JsonPrimitive).content, attachment.bytes) }
            queue.queueFormat2Direction(peer.device_id, runId, false, aggregate, null, batches,
                attachments, policy, System.currentTimeMillis() + 86_400_000)
            queue.queuePrepared(peer.device_id, requestMessage, policy)
        } else {
            queue.queuePrepared(peer.device_id, requestMessage, queue.personalRunPolicy(peer.device_id, runId)
                ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."))
            val records = Ablage.hole(context).personalSyncSnapshot(modules.toSet())
            queueSnapshotRecords(peer, runId, records, false, 1)
        }
        if (peer.personal_deletions_sync_granted && peer.remote_personal_deletions_sync_granted) {
            val proposals = PersonalSync.proposals(Ablage.hole(context).bestand.value, peer.device_id)
            proposals.chunked(32).forEachIndexed { index, chunk ->
                queue.queue(peer.device_id, "personal_sync.deletion_proposals", buildJsonObject {
                    put("format", JsonPrimitive(1)); put("run_id", JsonPrimitive(runId))
                    put("proposal_batch_id", JsonPrimitive(UUID.randomUUID().toString())); put("sequence", JsonPrimitive(index))
                    put("last", JsonPrimitive(index == proposals.chunked(32).lastIndex))
                    put("proposals", JsonArray(chunk.map { proposal -> buildJsonObject {
                        put("proposal_id", JsonPrimitive(proposal.proposal_id)); put("kind", JsonPrimitive(proposal.kind))
                        put("id", JsonPrimitive(proposal.id)); put("parent_id", JsonPrimitive(proposal.parent_id))
                        put("clock", JsonArray(proposal.clock.map { buildJsonObject {
                            put("actor_id", JsonPrimitive(it.actor_id)); put("counter", JsonPrimitive(it.counter)) } }))
                        put("prior_hash", JsonPrimitive(proposal.prior_hash)); put("deleted_ms", JsonPrimitive(proposal.deleted_ms))
                        put("label", JsonPrimitive(proposal.label.replace(Regex("[\\x00-\\x1f\\x7f]"), " ").take(120)))
                    } }))
                }, 86_400_000, transportPolicy = queue.personalRunPolicy(peer.device_id, runId)
                    ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."))
            }
        }
        return true
    }

    private fun queueSnapshotRecords(peer: TelefonPeer, runId: String,
                                     records: List<io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord>, reply: Boolean,
                                     format: Int = 1): Int {
        val result = buildSnapshotBatches(runId, records, reply, format)
        result.first.forEach { body ->
            queue.queue(peer.device_id, "personal_sync.batch", body, 86_400_000,
                transportPolicy = queue.personalRunPolicy(peer.device_id, runId)
                    ?: throw TelefonProtokollFehler("Personal-Sync-Policy fehlt."))
        }
        return result.second
    }

    private fun buildSnapshotBatches(runId: String,
                                     records: List<io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord>,
                                     reply: Boolean, format: Int = 1): Pair<List<JsonObject>, Int> {
        val placeholder = "0".repeat(64)
        val chunks = mutableListOf<List<io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord>>()
        var current = mutableListOf<io.gitlab.maik3531.magnolienotes.daten.PersonalSyncRecord>()
        var oversized = 0
        for (record in records) {
            if (runCatching { PersonalSyncProtokoll.decodeBatch(PersonalSyncProtokoll.batch(
                    runId, listOf(record), 0, true, reply, format, placeholder)) }.isFailure) {
                oversized++
                continue
            }
            val candidate = current + record
            if (candidate.size > 32 || TelefonKanonisch.bytes(PersonalSyncProtokoll.batch(
                    runId, candidate, chunks.size, false, reply, format, placeholder)).size > 192 * 1024) {
                if (current.isNotEmpty()) chunks += current.toList()
                current = mutableListOf(record)
                if (TelefonKanonisch.bytes(PersonalSyncProtokoll.batch(
                        runId, current, chunks.size, false, reply, format, placeholder)).size > 192 * 1024) {
                    current.clear(); oversized++
                }
            } else current.add(record)
        }
        if (current.isNotEmpty()) chunks += current
        if (chunks.isEmpty()) chunks.add(emptyList())
        val aggregate = if (format >= 2) PersonalSync.recordsHash(chunks.flatten()) else ""
        return chunks.mapIndexed { index, chunk ->
            PersonalSyncProtokoll.batch(runId, chunk, index, index == chunks.lastIndex, reply, format, aggregate)
        } to oversized
    }

    private fun proofObject(type: String, side: String, transcript: String, proof: ByteArray) = buildJsonObject {
        put("p", JsonPrimitive(TelefonParameter.PROTOKOLL)); put("type", JsonPrimitive(type)); put("side", JsonPrimitive(side))
        put("transcript", JsonPrimitive(transcript)); put("proof", JsonPrimitive(TelefonKrypto.b64(proof)))
    }

    private fun checkProof(objectValue: JsonObject, type: String, side: String, material: PaarungsMaterial, label: String) {
        requireExact(objectValue, setOf("p", "type", "side", "transcript", "proof"))
        val expected = TelefonKrypto.beweis(material, label, side)
        if (objectValue.string("p") != TelefonParameter.PROTOKOLL || objectValue.string("type") != type ||
            objectValue.string("side") != side || objectValue.string("transcript") != TelefonKrypto.b64(material.transcript) ||
            !java.security.MessageDigest.isEqual(expected, TelefonKrypto.b64(objectValue.string("proof"), 32)))
            throw TelefonProtokollFehler("Ungültiger Pairing-Beweis.")
    }

    private fun requireExact(objectValue: JsonObject, fields: Set<String>) {
        if (objectValue.keys != fields) throw TelefonProtokollFehler("Unerwartetes Pairing-Schema.")
    }
    private fun JsonObject.number(name: String) = (getValue(name) as? JsonPrimitive)?.takeIf { !it.isString }?.content?.toIntOrNull()
        ?: throw TelefonProtokollFehler("Falscher Feldtyp: $name")
    private fun safePeer() = runCatching { storage.peers().peer }.getOrNull()

    private data class PendingPairing(val socket: TelefonRoehre, val response: JsonObject, val material: PaarungsMaterial,
        val staticPrivate: ByteArray, val ephemeralPrivate: ByteArray, val host: String, val bluetoothAddress: String = "",
        val generation: Long = 0) {
        fun close() { runCatching { socket.close() }; material.schluessel.fill(0); staticPrivate.fill(0); ephemeralPrivate.fill(0) }
    }

    companion object {
        @Volatile private var instance: TelefonWerk? = null
        fun get(context: Context) = instance ?: synchronized(this) {
            instance ?: TelefonWerk(context.applicationContext, TelefonAblage.get(context)).also { instance = it }
        }
    }
}
