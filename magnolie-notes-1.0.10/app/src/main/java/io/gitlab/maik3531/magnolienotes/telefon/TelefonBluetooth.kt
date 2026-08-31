package io.gitlab.maik3531.magnolienotes.telefon

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
}

internal class TelefonTcpRoehre(host: String, connectTimeoutMs: Int = 10_000) : TelefonRoehre {
    private val socket = Socket().apply {
        connect(InetSocketAddress(host, TelefonParameter.PORT), connectTimeoutMs)
        soTimeout = 75_000
    }
    override val input: InputStream get() = socket.getInputStream()
    override val output: OutputStream get() = socket.getOutputStream()
    override fun close() = socket.close()
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
        try {
            @Suppress("MissingPermission")
            socket.connect()
            return BluetoothRoehre(socket)
        } catch (error: Exception) {
            runCatching { socket.close() }
            throw error
        }
    }

    private fun adapter(): BluetoothAdapter? = context.getSystemService(BluetoothManager::class.java)?.adapter

    private class BluetoothRoehre(private val socket: BluetoothSocket) : TelefonRoehre {
        override val input: InputStream get() = socket.inputStream
        override val output: OutputStream get() = socket.outputStream
        override fun close() = socket.close()
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
