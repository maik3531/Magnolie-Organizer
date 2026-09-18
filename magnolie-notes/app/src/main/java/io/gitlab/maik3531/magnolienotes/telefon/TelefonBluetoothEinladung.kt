package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

internal data class TelefonBluetoothLink(val address: String, val pipe: TelefonRoehre)
internal interface TelefonRfcommListener : AutoCloseable {
    fun accept(): TelefonBluetoothLink
}

internal object TelefonBluetoothEinladung {
    const val PROTOCOL = "magnolie-phone-invite/1"
    fun address(value: String) = Regex("[0-9A-F]{2}(:[0-9A-F]{2}){5}").matches(value)
    fun control(type: String, nonce: String) = buildJsonObject {
        put("p", JsonPrimitive(PROTOCOL)); put("type", JsonPrimitive(type)); put("nonce", JsonPrimitive(nonce))
    }
    fun offer(value: JsonObject, target: String, nonce: String): GefundenerDesktop {
        require(value.keys == setOf("p", "type", "target", "nonce", "device_id", "name", "token", "ttl"))
        require(value.string("p") == PROTOCOL && value.string("type") == "bluetooth_offer" &&
            value.string("target") == target && value.string("nonce") == nonce && value.long("ttl") == 60L)
        val id = value.string("device_id"); val name = value.string("name")
        require(UUID.fromString(id).toString() == id && id != target)
        require(name.codePointCount(0, name.length) in 1..60 && name.none {
            it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt()
        })
        TelefonKrypto.b64(value.string("token"), 16)
        return GefundenerDesktop(id, name, "", value.string("token"))
    }
}

// One owned first-pair stream. The public nonce/consent frames confer no trust.
// Short request/reply polls detect disconnect without competing RFCOMM readers.
internal class TelefonBluetoothAnfrage(private val target: String,
    private val nanoTime: () -> Long = System::nanoTime) : AutoCloseable {
    val invitation = MutableStateFlow<GefundenerDesktop?>(null)
    private val decision = AtomicReference<Boolean?>(null)
    private val closed = AtomicBoolean(false)
    @Volatile private var active: TelefonRoehre? = null
    fun decide(accepted: Boolean) { decision.compareAndSet(null, accepted) }

    fun receive(link: TelefonBluetoothLink, accepted: (GefundenerDesktop, TelefonRoehre, String) -> Unit) {
        require(TelefonBluetoothEinladung.address(link.address))
        val pipe = TelefonPaarungsRoehre(link.pipe)
        active = pipe
        val nonce = TelefonKrypto.b64(TelefonKrypto.zufall(16))
        val consentTimer = java.util.Timer("magnolie-bt-consent", true)
        var transferred = false
        try {
            check(!closed.get())
            TelefonRahmen.schreiben(pipe.output, buildJsonObject {
                put("p", JsonPrimitive(TelefonBluetoothEinladung.PROTOCOL)); put("type", JsonPrimitive("bluetooth_available"))
                put("device_id", JsonPrimitive(target)); put("nonce", JsonPrimitive(nonce))
            }, 2048)
            val timer = java.util.Timer("magnolie-bt-offer-deadline", true)
            val task = object : java.util.TimerTask() { override fun run() { runCatching { pipe.close() } } }
            val desktop = try {
                timer.schedule(task, 2000)
                TelefonBluetoothEinladung.offer(TelefonRahmen.lesen(pipe.input, 2048), target, nonce)
            } finally { timer.cancel() }
            val until = nanoTime() + 60_000_000_000L
            consentTimer.schedule(object : java.util.TimerTask() { override fun run() { runCatching { pipe.close() } } }, 60_000)
            invitation.value = desktop
            repeat(240) {
                if (closed.get() || nanoTime() >= until) return
                val poll = TelefonRahmen.lesen(pipe.input, 2048)
                require(poll == TelefonBluetoothEinladung.control("wait", nonce))
                if (closed.get() || nanoTime() >= until) return
                val answer = decision.get()
                TelefonRahmen.schreiben(pipe.output, TelefonBluetoothEinladung.control(
                    if (answer == true) "accepted" else if (answer == false) "rejected" else "pending", nonce), 2048)
                if (answer != null) {
                    if (answer) {
                        consentTimer.cancel()
                        active = null
                        transferred = true
                        try { accepted(desktop, pipe, link.address) }
                        catch (error: Exception) { pipe.close(); throw error }
                    }
                    return
                }
            }
        } finally {
            invitation.value = null
            consentTimer.cancel()
            active = null
            if (!transferred) pipe.close()
            closed.set(true)
        }
    }

    override fun close() {
        closed.set(true)
        active?.let { runCatching { it.close() } }
        invitation.value = null
    }
}
