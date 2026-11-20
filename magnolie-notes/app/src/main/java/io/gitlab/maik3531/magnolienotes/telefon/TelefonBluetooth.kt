package io.gitlab.maik3531.magnolienotes.telefon

import io.gitlab.maik3531.magnolienotes.netz.LanFreigabe

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.UUID

internal interface TelefonRoehre : AutoCloseable {
    val input: InputStream
    val output: OutputStream
    val expiresAtNanos: Long get() = Long.MAX_VALUE
    /** Native transport lifetime, independent of persisted peer/data consent. */
    fun aktuell(): Boolean = true
    fun pruefen() { if (!aktuell()) throw java.io.IOException("Die Verbindung ist nicht mehr gültig.") }
    // Optional per-read timeout; pairing also has a transport-independent deadline.
    fun setReadTimeout(timeoutMs: Int) = Unit
}

internal class TelefonTcpRoehre(host: String, connectTimeoutMs: Int = 10_000,
    port: Int = TelefonParameter.PORT, localAddress: java.net.InetAddress? = null) : TelefonRoehre {
    private val lanMarke = LanFreigabe.marke()
    private val socket = Socket()
    private val lanWache = try { LanFreigabe.beobachten(socket) }
        catch (error: Exception) { runCatching { socket.close() }; throw error }
    init {
        try {
            pruefen()
            if (localAddress != null) socket.bind(InetSocketAddress(localAddress, 0))
            socket.connect(InetSocketAddress(host, port), connectTimeoutMs)
            socket.soTimeout = 75_000
            pruefen()
        } catch (error: Exception) {
            runCatching { lanWache.close() }
            runCatching { socket.close() }
            throw error
        }
    }
    override fun aktuell(): Boolean = !socket.isClosed && LanFreigabe.aktuell(lanMarke)
    override fun pruefen() {
        if (!LanFreigabe.aktuell(lanMarke)) throw java.io.IOException(LanFreigabe.WARTET)
        if (socket.isClosed) throw java.io.IOException("Die Verbindung ist beendet.")
    }
    // The channel keeps these stream objects. Checking only their getter would
    // miss revocation after authentication and before a later frame read/write.
    private val eingabe: InputStream by lazy {
        object : java.io.FilterInputStream(socket.getInputStream()) {
            override fun read(): Int { pruefen(); return `in`.read().also { pruefen() } }
            override fun read(bytes: ByteArray, offset: Int, length: Int): Int {
                pruefen(); return `in`.read(bytes, offset, length).also { pruefen() }
            }
        }
    }
    private val ausgabe: OutputStream by lazy {
        object : java.io.FilterOutputStream(socket.getOutputStream()) {
            override fun write(value: Int) { pruefen(); out.write(value); pruefen() }
            override fun write(bytes: ByteArray, offset: Int, length: Int) {
                pruefen(); out.write(bytes, offset, length); pruefen()
            }
            override fun flush() { pruefen(); out.flush(); pruefen() }
        }
    }
    override val input: InputStream get() { pruefen(); return eingabe }
    override val output: OutputStream get() { pruefen(); return ausgabe }
    internal val remoteAddress: java.net.InetAddress get() = socket.inetAddress
    internal val localAddress: java.net.InetAddress get() = socket.localAddress
    internal val isClosed: Boolean get() = socket.isClosed
    override fun setReadTimeout(timeoutMs: Int) { socket.soTimeout = timeoutMs }
    override fun close() { try { lanWache.close() } finally { socket.close() } }
}

// RFCOMM has no read timeout. Closing the owned pipe enforces the same absolute
// pairing deadline for both transports, including time spent in confirmation UI.
internal class TelefonPaarungsRoehre(private val pipe: TelefonRoehre,
    timeoutMs: Long = 120_000, onExpired: () -> Unit = {}) : TelefonRoehre {
    override val expiresAtNanos = minOf(pipe.expiresAtNanos, System.nanoTime() + java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(timeoutMs))
    private val closed = java.util.concurrent.atomic.AtomicBoolean(false)
    private val deadline = timer.schedule({
        if (closed.compareAndSet(false, true)) {
            runCatching { pipe.close() }
            onExpired()
        }
    }, maxOf(0, expiresAtNanos - System.nanoTime()), java.util.concurrent.TimeUnit.NANOSECONDS)
    override val input: InputStream get() = pipe.input
    override val output: OutputStream get() = pipe.output
    override fun aktuell(): Boolean = !closed.get() && pipe.aktuell()
    override fun pruefen() { if (closed.get()) throw java.io.IOException("Die Verbindung ist beendet."); pipe.pruefen() }
    override fun setReadTimeout(timeoutMs: Int) = pipe.setReadTimeout(timeoutMs)
    fun disarm() { deadline.cancel(false) }
    override fun close() {
        if (closed.compareAndSet(false, true)) {
            deadline.cancel(false)
            pipe.close()
        }
    }
    companion object {
        private val timer = java.util.concurrent.ScheduledThreadPoolExecutor(1) { task ->
            Thread(task, "magnolie-phone-pair-deadline").apply { isDaemon = true }
        }.apply { removeOnCancelPolicy = true }
    }
}

internal class TelefonBluetooth(private val context: Context) {
    fun erlaubt(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
        context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED

    fun gekoppelteGeraete(): List<TelefonBluetoothZiel> {
        if (!erlaubt()) throw SecurityException("Bluetooth permission missing")
        val adapter = adapter() ?: return emptyList()
        @Suppress("MissingPermission")
        return adapter.bondedDevices.map { TelefonBluetoothZiel(it.name.orEmpty(), it.address) }
            .sortedBy { it.name.lowercase() }
    }

    fun verbinden(address: String): TelefonRoehre {
        if (!erlaubt()) throw SecurityException("Bluetooth permission missing")
        val adapter = adapter() ?: throw TelefonProtokollFehler("Bluetooth ist nicht verfügbar.")
        if (!adapter.isEnabled) throw TelefonProtokollFehler("Bluetooth ist ausgeschaltet.")
        val device = try { adapter.getRemoteDevice(address) } catch (_: IllegalArgumentException) {
            throw TelefonProtokollFehler("Ungültige Bluetooth-Adresse.")
        }
        @Suppress("MissingPermission")
        val socket = device.createRfcommSocketToServiceRecord(UUID.fromString(TelefonParameter.RFCOMM_UUID))
        val deadline = TelefonPaarungsRoehre(BluetoothRoehre(socket), 15_000)
        try {
            @Suppress("MissingPermission")
            socket.connect()
            deadline.disarm()
            return BluetoothRoehre(socket)
        } catch (error: Exception) {
            runCatching { socket.close() }
            throw error
        } finally { deadline.disarm() }
    }

    fun listen(): TelefonRfcommListener {
        if (!erlaubt()) throw SecurityException("Bluetooth permission missing")
        val adapter = adapter() ?: throw TelefonProtokollFehler("Bluetooth ist nicht verfügbar.")
        @Suppress("MissingPermission")
        val server = adapter.listenUsingRfcommWithServiceRecord(context.getString(io.gitlab.maik3531.magnolienotes.R.string.telefon_titel),
            UUID.fromString(TelefonParameter.RFCOMM_UUID))
        return object : TelefonRfcommListener {
            override fun accept(): TelefonBluetoothLink {
                val socket = server.accept()
                try {
                    @Suppress("MissingPermission")
                    val bonded = socket.remoteDevice.bondState == android.bluetooth.BluetoothDevice.BOND_BONDED
                    check(erlaubt() && bonded)
                    return TelefonBluetoothLink(socket.remoteDevice.address.uppercase(), BluetoothRoehre(socket))
                } catch (error: Exception) { runCatching { socket.close() }; throw error }
            }
            override fun close() = server.close()
        }
    }

    private fun adapter(): BluetoothAdapter? = context.getSystemService(BluetoothManager::class.java)?.adapter

    private class BluetoothRoehre(private val socket: BluetoothSocket) : TelefonRoehre {
        private val closed = java.util.concurrent.atomic.AtomicBoolean(false)
        override val input: InputStream get() = socket.inputStream
        override val output: OutputStream get() = socket.outputStream
        override fun aktuell(): Boolean = !closed.get()
        override fun close() { if (closed.compareAndSet(false, true)) socket.close() }
    }
}

internal enum class TelefonTransportArt { WIFI, BLUETOOTH }

internal object TelefonTransportwahl {
    fun <T> oeffnen(
        wifiAvailable: Boolean,
        bluetoothAddress: String,
        bluetoothAllowed: Boolean,
        wifi: () -> T,
        bluetooth: (String) -> T
    ): Pair<TelefonTransportArt, T> {
        var wifiError: Throwable? = null
        if (wifiAvailable) try {
            return TelefonTransportArt.WIFI to wifi()
        } catch (error: Throwable) {
            wifiError = error
        }
        if (bluetoothAddress.isNotBlank() && bluetoothAllowed) {
            return TelefonTransportArt.BLUETOOTH to bluetooth(bluetoothAddress)
        }
        throw wifiError ?: TelefonProtokollFehler("Kein erlaubter Telefontransport verfügbar.")
    }
}
