package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.telecom.TelecomManager
import android.telephony.PhoneStateListener
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.util.UUID

class EingehendeAnrufe(private val context: Context) {
    private val manager = context.getSystemService(TelephonyManager::class.java)
    private var callback: Any? = null
    private var listenerGeneration = 0
    private var active: TrackedCall? = null
    private val origins = CallControlOriginTracker()
    private val proximity = TelefonNaehe(telefonNaeheSperre(context))
    private val handler = Handler(Looper.getMainLooper())
    private val outgoingTimeout = Runnable { expireUnobservedOutgoing() }
    @Volatile private var serviceRunning = false
    @Volatile private var incomingListening = false

    private data class TrackedCall(val callRef: String, var revision: Int, var state: Int,
        var direction: String, var number: String, val clientRef: String, val startedMs: Long,
        var offhookMs: Long = 0, var observedNonIdle: Boolean = false)

    private fun start() {
        if (callback != null || context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) return
        val generation = ++listenerGeneration
        if (Build.VERSION.SDK_INT >= 31) {
            val listener = object : TelephonyCallback(), TelephonyCallback.CallStateListener {
                override fun onCallStateChanged(value: Int) = changed(value, "", generation)
            }
            callback = listener; manager?.registerTelephonyCallback(context.mainExecutor, listener)
        } else {
            @Suppress("DEPRECATION") val listener = object : PhoneStateListener() {
                @Deprecated("Legacy API for Android 8-11")
                override fun onCallStateChanged(value: Int, number: String?) =
                    changed(value, number.orEmpty(), generation)
            }
            callback = listener; @Suppress("DEPRECATION") manager?.listen(listener, PhoneStateListener.LISTEN_CALL_STATE)
        }
        @Suppress("DEPRECATION")
        changed(manager?.callState ?: TelephonyManager.CALL_STATE_IDLE, "", generation)
    }

    private fun unregister(waitForNoProximity: Boolean) {
        listenerGeneration++
        val listener = callback
        if (listener != null && Build.VERSION.SDK_INT >= 31)
            manager?.unregisterTelephonyCallback(listener as TelephonyCallback)
        else if (listener != null) {
            @Suppress("DEPRECATION")
            manager?.listen(listener as PhoneStateListener, PhoneStateListener.LISTEN_NONE)
        }
        callback = null
        proximity.stop(waitForNoProximity)
    }

    @Synchronized fun serviceStarted(incomingEnabled: Boolean) {
        serviceRunning = true
        incomingListening = incomingEnabled
        reconcileListening()
    }

    @Synchronized fun setIncomingListening(enabled: Boolean) {
        incomingListening = enabled
        reconcileListening()
    }

    @Synchronized fun runtimePermissionsChanged() {
        if (context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
            val call = active
            if (call != null) {
                val now = System.currentTimeMillis()
                finish(call, now)
            }
        }
        reconcileListening()
    }

    @Synchronized fun shutdown() {
        serviceRunning = false
        incomingListening = false
        handler.removeCallbacks(outgoingTimeout)
        val call = active
        if (call != null) finish(call, System.currentTimeMillis()) else unregister(true)
    }

    private fun reconcileListening() {
        val permitted = context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED
        if (telefonLauscherNoetig(serviceRunning, permitted, incomingListening, active != null)) start()
        else unregister(true)
    }

    @Synchronized fun beginOutgoing(number: String, clientRef: String) {
        if (active != null) throw TelefonProtokollFehler("Ein Anruf ist bereits aktiv.")
        @Suppress("DEPRECATION")
        if (manager?.callState != TelephonyManager.CALL_STATE_IDLE)
            throw TelefonProtokollFehler("Ein anderer Anruf ist bereits aktiv.")
        val now = System.currentTimeMillis()
        // The direct-dial contract uses the command client_ref as call_ref for every lifecycle event.
        active = TrackedCall(clientRef, 0, TelephonyManager.CALL_STATE_RINGING, "outgoing", number, clientRef, now)
        origins.begin(clientRef, "desktop")
        emit(active!!, now, 0)
        reconcileListening()
        handler.removeCallbacks(outgoingTimeout)
        handler.postDelayed(outgoingTimeout, OUTGOING_START_TIMEOUT_MS)
    }

    @Synchronized fun failOutgoing(clientRef: String) {
        val call = active?.takeIf { it.clientRef == clientRef } ?: return
        handler.removeCallbacks(outgoingTimeout)
        finish(call, System.currentTimeMillis())
    }

    @Synchronized private fun expireUnobservedOutgoing() {
        val call = active?.takeIf { it.direction == "outgoing" && !it.observedNonIdle } ?: return
        finish(call, System.currentTimeMillis())
    }

    @Synchronized private fun changed(value: Int, suppliedNumber: String, generation: Int) {
        if (!serviceRunning || generation != listenerGeneration) return
        proximity.update(value)
        val now = System.currentTimeMillis()
        var call = active
        var created = false
        if (call == null && value != TelephonyManager.CALL_STATE_IDLE) {
            call = TrackedCall(UUID.randomUUID().toString(), 0, value,
                if (value == TelephonyManager.CALL_STATE_RINGING) "incoming" else "unknown",
                suppliedNumber, "", now, observedNonIdle = true)
            active = call
            origins.begin(call.callRef, if (value == TelephonyManager.CALL_STATE_RINGING) "unknown" else "phone")
            created = true
        }
        val tracked = call ?: return
        if (telefonInitialesAusgehendesIdle(tracked.direction, tracked.observedNonIdle, value)) return
        if (value != TelephonyManager.CALL_STATE_IDLE) {
            tracked.observedNonIdle = true
            handler.removeCallbacks(outgoingTimeout)
        }
        if (!created && tracked.state == value) return
        tracked.state = value
        if (tracked.number.isBlank() && Build.VERSION.SDK_INT <= 30) tracked.number = suppliedNumber
        if (value == TelephonyManager.CALL_STATE_OFFHOOK && tracked.offhookMs == 0L) {
            tracked.offhookMs = now
            origins.offhook(tracked.callRef, now)
        }
        if (value == TelephonyManager.CALL_STATE_IDLE) {
            finish(tracked, now)
        } else runCatching { emit(tracked, now, 0) }
    }

    private fun finish(call: TrackedCall, now: Long) {
        val origin = origins.origin(call.callRef, now)
        active = null
        origins.clear(call.callRef)
        reconcileListening()
        runCatching { emit(call, now, now, origin) }
    }

    private fun emit(call: TrackedCall, occurred: Long, ended: Long,
                     finalOrigin: String? = null) {
        call.revision++
        val storage = TelefonAblage.get(context)
        val peer = runCatching { storage.peers().peer }.getOrNull()
        val localNumber = storage.incomingNumberEnabled()
        val permission = context.checkSelfPermission(Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED
        val shared = peer?.remote_incoming_call_number_granted == true
        val normalized = call.number.takeIf { Regex("\\+[0-9]{3,15}").matches(it) }.orEmpty()
        val numberStatus = when {
            !shared -> "not_shared"
            !localNumber || !permission -> "permission_missing"
            normalized.isNotEmpty() -> "available"
            call.direction == "incoming" && Build.VERSION.SDK_INT <= 30 -> "withheld"
            else -> "unavailable"
        }
        val batteryAllowed = peer?.device_status_granted == true && peer.remote_device_status_granted
        val battery = if (batteryAllowed) DeviceStatusCollector.collect(context, call.callRef, occurred).batteryPercent else -1
        TelefonWerk.get(context).publish("incoming_call_state.event", buildJsonObject {
            put("call_ref", JsonPrimitive(call.callRef)); put("revision", JsonPrimitive(call.revision))
            put("state", JsonPrimitive(if (ended > 0) "idle" else when (call.state) {
                TelephonyManager.CALL_STATE_RINGING -> "ringing"; else -> "offhook" }))
            put("direction", JsonPrimitive(call.direction)); put("number", JsonPrimitive(if (numberStatus == "available") normalized else ""))
            put("number_status", JsonPrimitive(numberStatus)); put("started_ms", JsonPrimitive(call.startedMs))
            put("offhook_ms", JsonPrimitive(call.offhookMs)); put("ended_ms", JsonPrimitive(ended))
            put("occurred_ms", JsonPrimitive(occurred)); put("spam_status", JsonPrimitive("unknown"))
            put("control_origin", JsonPrimitive(finalOrigin ?: origins.origin(call.callRef, occurred)))
            put("battery_percent", JsonPrimitive(battery)); put("battery_captured_ms", JsonPrimitive(if (battery >= 0) occurred else 0))
        }, 60_000)
    }

    private companion object {
        const val OUTGOING_START_TIMEOUT_MS = 30_000L
    }

    fun answer(commandRef: String, expectedCallRef: String): Pair<String, String> {
        synchronized(this) {
            val call = active
            if (!TelefonAblage.get(context).answerCallsEnabled()) return failedAnswer(expectedCallRef, commandRef, "not_granted")
            if (context.checkSelfPermission(Manifest.permission.ANSWER_PHONE_CALLS) != PackageManager.PERMISSION_GRANTED)
                return failedAnswer(expectedCallRef, commandRef, "permission_missing")
            if (expectedCallRef != call?.callRef) return failedAnswer(expectedCallRef, commandRef, "stale_call")
            if (call.state != TelephonyManager.CALL_STATE_RINGING) return failedAnswer(expectedCallRef, commandRef, "not_ringing")
            if (!TelefonEffekte(context).firstEvent("answer:$commandRef")) return "already_answered" to "none"
        }
        val error = runCatching {
            @Suppress("DEPRECATION") context.getSystemService(TelecomManager::class.java)?.acceptRingingCall()
                ?: return failedAnswer(expectedCallRef, commandRef, "os_restricted")
        }.exceptionOrNull()
        if (error != null) return failedAnswer(expectedCallRef, commandRef,
            if (error is SecurityException) "permission_missing" else "os_restricted")
        synchronized(this) {
            val call = active
            if (call?.callRef == expectedCallRef && call.state == TelephonyManager.CALL_STATE_RINGING)
                origins.answerSubmitted(expectedCallRef, commandRef, System.currentTimeMillis())
        }
        return "submitted" to "none"
    }

    @Synchronized private fun failedAnswer(callRef: String, commandRef: String, error: String): Pair<String, String> {
        origins.answerFailed(callRef, commandRef)
        return "failed" to error
    }

    @Synchronized fun rejectAnswer(callRef: String, commandRef: String) {
        origins.answerFailed(callRef, commandRef)
    }

    @Synchronized fun end(commandRef: String, callRef: String, revision: Int): Pair<String, String> {
        val call = active
        if (!TelefonAblage.get(context).answerCallsEnabled()) return "failed" to "not_granted"
        if (Build.VERSION.SDK_INT < 28) return "failed" to "unsupported_api"
        if (context.checkSelfPermission(Manifest.permission.ANSWER_PHONE_CALLS) != PackageManager.PERMISSION_GRANTED) return "failed" to "permission_missing"
        if (call == null) return "already_ended" to "none"
        if (call.callRef != callRef || call.revision != revision) return "failed" to "stale_call"
        if (call.state != TelephonyManager.CALL_STATE_OFFHOOK) return "failed" to "not_active"
        if (!TelefonEffekte(context).firstEvent("end:$commandRef")) return "submitted" to "none"
        return runCatching {
            @Suppress("DEPRECATION") val ended = context.getSystemService(TelecomManager::class.java)?.endCall() ?: false
            if (ended) "submitted" to "none" else "failed" to "not_active"
        }.getOrElse { "failed" to if (it is SecurityException) "permission_missing" else "os_restricted" }
    }
}

internal fun telefonLauscherNoetig(serviceRunning: Boolean, permitted: Boolean,
                                    incomingListening: Boolean, activeCall: Boolean): Boolean =
    serviceRunning && permitted && (incomingListening || activeCall)

internal fun telefonInitialesAusgehendesIdle(direction: String, observedNonIdle: Boolean,
                                             callState: Int): Boolean =
    direction == "outgoing" && !observedNonIdle && callState == TelephonyManager.CALL_STATE_IDLE

internal interface TelefonNaeheSperre {
    val held: Boolean
    fun acquire()
    fun release(waitForNoProximity: Boolean)
}

internal class TelefonNaehe(private val lock: TelefonNaeheSperre?) {
    fun update(callState: Int) {
        val current = lock ?: return
        when (callState) {
            TelephonyManager.CALL_STATE_OFFHOOK ->
                if (!current.held) runCatching { current.acquire() }
            else ->
                if (current.held) runCatching { current.release(true) }
        }
    }

    fun stop(waitForNoProximity: Boolean) {
        val current = lock ?: return
        if (current.held) runCatching { current.release(waitForNoProximity) }
    }
}

private fun telefonNaeheSperre(context: Context): TelefonNaeheSperre? {
    val power = context.getSystemService(PowerManager::class.java) ?: return null
    if (!power.isWakeLockLevelSupported(PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK)) return null
    val wakeLock = runCatching { power.newWakeLock(PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK,
        "${context.packageName}:phone-call-proximity") }.getOrNull() ?: return null
    wakeLock.setReferenceCounted(false)
    return object : TelefonNaeheSperre {
        override val held: Boolean get() = wakeLock.isHeld
        override fun acquire() = wakeLock.acquire()
        override fun release(waitForNoProximity: Boolean) {
            if (waitForNoProximity)
                wakeLock.release(PowerManager.RELEASE_FLAG_WAIT_FOR_NO_PROXIMITY)
            else wakeLock.release()
        }
    }
}

internal class CallControlOriginTracker(private val pendingMs: Long = 10_000) {
    private data class Pending(val callRef: String, val commandRef: String, val submittedMs: Long)
    private var callRef = ""
    private var current = "unknown"
    private var pending: Pending? = null

    fun begin(ref: String, origin: String) {
        callRef = ref
        current = origin
        pending = null
    }

    fun answerSubmitted(ref: String, commandRef: String, now: Long) {
        if (ref == callRef && current == "unknown") pending = Pending(ref, commandRef, now)
    }

    fun answerFailed(ref: String, commandRef: String) {
        if (pending?.let { it.callRef == ref && it.commandRef == commandRef } == true) pending = null
    }

    fun offhook(ref: String, now: Long): String {
        if (ref != callRef) return "unknown"
        if (current == "desktop") return current
        val intent = pending
        current = if (intent != null && intent.callRef == ref && now - intent.submittedMs in 0..pendingMs) "desktop" else "phone"
        pending = null
        return current
    }

    fun origin(ref: String, now: Long): String {
        if (pending?.let { now - it.submittedMs > pendingMs } == true) pending = null
        return if (ref == callRef) current else "unknown"
    }

    fun clear(ref: String) {
        if (ref == callRef) { callRef = ""; current = "unknown"; pending = null }
    }
}
