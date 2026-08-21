package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
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
    private var active: TrackedCall? = null
    private val origins = CallControlOriginTracker()

    private data class TrackedCall(val callRef: String, var revision: Int, var state: Int,
        var direction: String, var number: String, val clientRef: String, val startedMs: Long,
        var offhookMs: Long = 0)

    fun start() {
        if (callback != null || context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) return
        if (Build.VERSION.SDK_INT >= 31) {
            val listener = object : TelephonyCallback(), TelephonyCallback.CallStateListener {
                override fun onCallStateChanged(value: Int) = changed(value, "")
            }
            callback = listener; manager?.registerTelephonyCallback(context.mainExecutor, listener)
        } else {
            @Suppress("DEPRECATION") val listener = object : PhoneStateListener() {
                @Deprecated("Legacy API for Android 8-11")
                override fun onCallStateChanged(value: Int, number: String?) = changed(value, number.orEmpty())
            }
            callback = listener; @Suppress("DEPRECATION") manager?.listen(listener, PhoneStateListener.LISTEN_CALL_STATE)
        }
    }

    fun stop() {
        val listener = callback ?: return
        if (Build.VERSION.SDK_INT >= 31) manager?.unregisterTelephonyCallback(listener as TelephonyCallback)
        else @Suppress("DEPRECATION") manager?.listen(listener as PhoneStateListener, PhoneStateListener.LISTEN_NONE)
        callback = null
    }

    @Synchronized fun persistentListening(enabled: Boolean) {
        if (enabled) start() else if (active?.direction != "outgoing") stop()
    }

    @Synchronized fun beginOutgoing(number: String, clientRef: String) {
        if (active != null) throw TelefonProtokollFehler("Ein Anruf ist bereits aktiv.")
        start()
        val now = System.currentTimeMillis()
        // The direct-dial contract uses the command client_ref as call_ref for every lifecycle event.
        active = TrackedCall(clientRef, 0, TelephonyManager.CALL_STATE_RINGING, "outgoing", number, clientRef, now)
        origins.begin(clientRef, "desktop")
        emit(active!!, now, 0)
    }

    @Synchronized fun failOutgoing(clientRef: String) {
        val call = active?.takeIf { it.clientRef == clientRef } ?: return
        val now = System.currentTimeMillis(); emit(call, now, now); active = null; origins.clear(call.callRef)
        if (!TelefonAblage.get(context).incomingCallsEnabled()) stop()
    }

    @Synchronized private fun changed(value: Int, suppliedNumber: String) {
        val now = System.currentTimeMillis()
        var call = active
        var created = false
        if (call == null && value != TelephonyManager.CALL_STATE_IDLE) {
            call = TrackedCall(UUID.randomUUID().toString(), 0, value,
                if (value == TelephonyManager.CALL_STATE_RINGING) "incoming" else "unknown",
                suppliedNumber, "", now)
            active = call
            origins.begin(call.callRef, if (value == TelephonyManager.CALL_STATE_RINGING) "unknown" else "phone")
            created = true
        }
        if (call == null || !created && call.state == value) return
        call.state = value
        if (call.number.isBlank() && Build.VERSION.SDK_INT <= 30) call.number = suppliedNumber
        if (value == TelephonyManager.CALL_STATE_OFFHOOK && call.offhookMs == 0L) {
            call.offhookMs = now
            origins.offhook(call.callRef, now)
        }
        emit(call, now, if (value == TelephonyManager.CALL_STATE_IDLE) now else 0)
        if (value == TelephonyManager.CALL_STATE_IDLE) {
            active = null; origins.clear(call.callRef)
            if (!TelefonAblage.get(context).incomingCallsEnabled()) stop()
        }
    }

    private fun emit(call: TrackedCall, occurred: Long, ended: Long) {
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
            put("control_origin", JsonPrimitive(origins.origin(call.callRef, occurred)))
            put("battery_percent", JsonPrimitive(battery)); put("battery_captured_ms", JsonPrimitive(if (battery >= 0) occurred else 0))
        }, 60_000)
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
