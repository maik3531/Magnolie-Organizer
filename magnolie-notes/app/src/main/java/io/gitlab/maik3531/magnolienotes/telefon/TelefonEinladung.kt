package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.buildJsonObject
import java.net.Inet4Address
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

// Discovery and the invitation are public hints, never authentication. One nonce
// permits one prompt; only the existing user-confirmed telephone handshake pins keys.
internal object TelefonEinladungsVertrag {
    const val SERVICE = "_magnolie-invite._tcp."
    const val PROTOCOL = "magnolie-phone-invite/1"
    fun local(address: InetAddress): Boolean = address is Inet4Address && !address.isLoopbackAddress &&
        !address.isAnyLocalAddress && !address.isMulticastAddress && (address.isSiteLocalAddress || address.isLinkLocalAddress)

    fun offer(value: JsonObject, source: InetAddress, target: String, nonce: String): GefundenerDesktop {
        require(value.keys == setOf("p", "type", "target", "nonce", "device_id", "name", "token", "port", "ttl"))
        fun text(key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error("Invalid invitation")
        require(local(source) && text("p") == PROTOCOL && text("type") == "offer" &&
            text("target") == target && text("nonce") == nonce &&
            (value["port"] as? JsonPrimitive)?.intOrNull == TelefonParameter.PORT &&
            value["port"]?.let { (it as JsonPrimitive).isString } == false &&
            (value["ttl"] as? JsonPrimitive)?.intOrNull == 60 && !(value["ttl"] as JsonPrimitive).isString)
        val id = text("device_id")
        require(UUID.fromString(id).toString() == id && id != target)
        val name = text("name")
        require(name.codePointCount(0, name.length) in 1..60 && name.none { it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt() })
        TelefonKrypto.b64(text("token"), 16)
        return GefundenerDesktop(id, name, requireNotNull(source.hostAddress), text("token"))
    }
}

internal class TelefonEinladungsEmpfang(
    private val target: String, private val name: String,
    private val onAccepted: (GefundenerDesktop) -> Unit,
    private val nanoTime: () -> Long = System::nanoTime
) : AutoCloseable {
    val invitation = MutableStateFlow<GefundenerDesktop?>(null)
    val finished = MutableStateFlow(false)
    val nonce = TelefonKrypto.b64(TelefonKrypto.zufall(16))
    private val listener = ServerSocket(0, 1)
    val port: Int get() = listener.localPort
    private val closed = AtomicBoolean(false)
    private val decision = AtomicReference<Boolean?>(null)
    @Volatile private var active: Socket? = null
    private val until = nanoTime() + 120_000_000_000L
    private val timer = java.util.Timer("magnolie-invitation-expiry", true)

    fun decide(accepted: Boolean) { decision.compareAndSet(null, accepted) }

    fun start() = thread(name = "magnolie-phone-invitation", isDaemon = true) {
        try {
            timer.schedule(object : java.util.TimerTask() { override fun run() = close() }, 120_000)
            listener.soTimeout = 500
            var attempts = 0
            while (!closed.get() && nanoTime() < until && attempts < 8) {
                val socket = try { listener.accept() } catch (_: SocketTimeoutException) { continue }
                    catch (_: java.net.SocketException) { break }
                attempts++
                active = socket
                try {
                    socket.use {
                        if (!TelefonEinladungsVertrag.local(socket.inetAddress)) return@use
                        socket.soTimeout = 2000
                        val readDeadline = object : java.util.TimerTask() { override fun run() { runCatching { socket.close() } } }
                        timer.schedule(readDeadline, 2000)
                        val value = try { TelefonRahmen.lesen(socket.getInputStream(), 2048) }
                            finally { readDeadline.cancel() }
                        val desktop = TelefonEinladungsVertrag.offer(value, socket.inetAddress, target, nonce)
                            .copy(localAddress = socket.localAddress)
                        val expires = minOf(until, nanoTime() + 60_000_000_000L)
                        invitation.value = desktop
                        socket.soTimeout = 200
                        while (!closed.get() && nanoTime() < expires && decision.get() == null) {
                            try { socket.getInputStream().read(); return@use }
                            catch (_: SocketTimeoutException) { }
                        }
                        if (!closed.get() && nanoTime() < expires && decision.get() == true) {
                            TelefonRahmen.schreiben(socket.getOutputStream(), buildJsonObject {
                                put("p", JsonPrimitive(TelefonEinladungsVertrag.PROTOCOL))
                                put("type", JsonPrimitive("accepted")); put("nonce", JsonPrimitive(nonce))
                            }, 2048)
                            onAccepted(desktop)
                        }
                    }
                    if (invitation.value != null) break // consumed, even on reject/disconnect
                } catch (_: Exception) {
                    if (invitation.value != null) break
                    Thread.sleep(250)
                } finally { active = null }
            }
        } catch (_: IllegalStateException) { // The screen may close before timer registration.
        } finally { close() }
    }

    fun advertise(context: Context): AutoCloseable {
        val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        val registration = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(info: NsdServiceInfo) {
                if (closed.get()) runCatching { nsd.unregisterService(this) }
            }
            override fun onServiceUnregistered(info: NsdServiceInfo) = Unit
            override fun onRegistrationFailed(info: NsdServiceInfo, errorCode: Int) { close() }
            override fun onUnregistrationFailed(info: NsdServiceInfo, errorCode: Int) = Unit
        }
        nsd.registerService(NsdServiceInfo().apply {
            serviceName = target; serviceType = TelefonEinladungsVertrag.SERVICE; port = this@TelefonEinladungsEmpfang.port
            setAttribute("v", "1"); setAttribute("id", target); setAttribute("name", name); setAttribute("nonce", nonce)
        }, NsdManager.PROTOCOL_DNS_SD, registration)
        return AutoCloseable { runCatching { nsd.unregisterService(registration) } }
    }

    override fun close() {
        if (closed.compareAndSet(false, true)) {
            runCatching { listener.close() }; runCatching { active?.close() }
            timer.cancel()
            invitation.value = null; finished.value = true
        }
    }
}
