package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.WeakHashMap

/** Only the normal authenticated reader supplies capabilities and messages.
 * This keeps volatile viewing state and ACKs separate from the durable queue. */
internal class PhoneScreenNotesDispatch(private val context: Context) {
    private class Witness(val channel: TelefonSecureChannel, val pipe: TelefonTcpRoehre,
        val body: JsonObject, val requireOriginal: () -> Unit)
    private class Ack(val id: String, val identity: Any)
    private val gate = Any()
    private val ui = Handler(Looper.getMainLooper())
    private val acks = WeakHashMap<TelefonSecureChannel, ArrayDeque<Ack>>()
    @Volatile private var witness: Witness? = null
    private var run: PhoneScreenNotesRun? = null
    private var runIdentity: Any? = null
    private var dispatched: Witness? = null
    private val refresh = Runnable { startIfReady() }
    private var nextProbeAt = 0L

    fun observe(channel: TelefonSecureChannel, pipe: TelefonTcpRoehre?, body: JsonObject, requireOriginal: () -> Unit) {
        if (Build.VERSION.SDK_INT < 29) return
        val status = (body["items"] as? JsonObject)?.get("device_status") as? JsonObject
        val supported = status?.get("available") == JsonPrimitive(true) &&
            (status["versions"] as? JsonArray)?.contains(JsonPrimitive(PhoneScreenControl.VERSION)) == true
        synchronized(gate) {
            if (witness?.let { supported && it.channel === channel && it.pipe === pipe && it.body == body } == true) return
            witness = if (supported && pipe != null) Witness(channel, pipe, body, requireOriginal) else null
            nextProbeAt = 0
            run?.close()
        }
        refresh()
    }

    fun refresh() {
        if (Build.VERSION.SDK_INT < 29) return
        ui.removeCallbacks(refresh)
        ui.post(refresh)
    }

    private fun startIfReady() {
        if (Build.VERSION.SDK_INT < 29) return
        synchronized(gate) {
            val previous = run
            if (previous != null) {
                if (!previous.isDrained()) {
                    if (witness != null) ui.postDelayed(refresh, if (witness !== dispatched) 100 else 1000)
                    return
                }
                run = null
                runIdentity = null
            }
            val source = witness ?: return
            val now = android.os.SystemClock.elapsedRealtime()
            if (source === dispatched && now < nextProbeAt) {
                ui.postDelayed(refresh, nextProbeAt - now)
                return
            }
            val host = PhoneScreenForeground.availableHost() ?: return
            val identity = Any()
            val current = {
                check(witness === source) { "screen_control_original_capabilities_lost" }
                check(!host.retired) { "screen_original_activity_retired" }
                source.requireOriginal()
            }
            if (runCatching { current() }.isFailure) return
            val next = PhoneScreenNotesRun(context, source.channel, source.pipe, current, { host }, { id ->
                synchronized(gate) {
                    val pending = acks.getOrPut(source.channel) { ArrayDeque() }
                    if (pending.size == 16) pending.removeFirst()
                    pending.addLast(Ack(id, identity))
                }
            })
            run = next
            runIdentity = identity
            dispatched = source
            // A fresh availability probe is not a retry of the previous offer.
            // It can never prompt or stream without a new explicit desktop action.
            nextProbeAt = now + 60_000
            try { next.start() } catch (_: Exception) { next.close() }
            ui.postDelayed(refresh, 60_000)
        }
    }

    fun retire(channel: TelefonSecureChannel? = null) {
        if (Build.VERSION.SDK_INT < 29) return
        synchronized(gate) {
            if (channel != null && witness?.channel !== channel) return
            witness = null
            run?.close()
            ui.removeCallbacks(refresh)
        }
    }

    fun receive(channel: TelefonSecureChannel, message: JsonObject) {
        val bodyValid = runCatching { PhoneScreenControl.validateMessage(message) }.isSuccess
        val owner = if (Build.VERSION.SDK_INT >= 29) synchronized(gate) {
            run?.takeIf { witness?.channel === channel && witness === dispatched }
        } else null
        val accepted = bodyValid && owner != null && runCatching { owner.receive(channel, message) }.getOrDefault(false)
        channel.send(TelefonNachrichten.ack(message.string("message_id"), if (accepted) "accepted" else "rejected",
            if (accepted) "none" else if (bodyValid) "not_granted" else "invalid_schema"))
    }

    fun consumeAck(channel: TelefonSecureChannel, message: JsonObject): Boolean = synchronized(gate) {
        val ack = acks[channel]?.firstOrNull { it.id == message.string("message_id") } ?: return false
        if (Build.VERSION.SDK_INT >= 29 && ack.identity === runIdentity && message.string("status") == "rejected") run?.close()
        true
    }
}
