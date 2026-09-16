package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.security.Provider
import java.security.Security
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class TelefonBluetoothSetupTest {
    private val pc = "AA:BB:CC:DD:EE:02"
    private class Pipe(private val socket: Socket, private val dropFinish: java.util.concurrent.atomic.AtomicBoolean? = null,
        override val expiresAtNanos: Long = Long.MAX_VALUE) : TelefonRoehre {
        override val input get() = socket.getInputStream()
        override val output get() = object : java.io.OutputStream() {
            override fun write(value: Int) = socket.getOutputStream().write(value)
            override fun write(bytes: ByteArray, offset: Int, length: Int) {
                if (dropFinish?.get() == true && String(bytes, offset, length, Charsets.UTF_8).contains("\"type\":\"pair_finish\"") &&
                    dropFinish.compareAndSet(true, false)) throw java.io.IOException("Fixture dropped finish")
                socket.getOutputStream().write(bytes, offset, length)
            }
            override fun flush() = socket.getOutputStream().flush()
        }
        override fun setReadTimeout(timeoutMs: Int) { socket.soTimeout = timeoutMs }
        override fun close() = socket.close()
    }
    private fun waitFor(check: () -> Boolean) {
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(12)
        while (!check() && System.nanoTime() < until) Thread.sleep(20)
        assertTrue("Timed out waiting for Bluetooth state", check())
    }

    @Test fun `Linux native setup adapter and Android factory first pair then secure RFCOMM reconnect`() = live("linux")
    @Test fun `Linux daemon owns first Bluetooth setup and reconnect through Unix IPC`() = live("linux-daemon")
    @Test fun `Windows native setup adapter and Android factory first pair then secure RFCOMM reconnect`() = live("windows")
    @Test fun `Windows setup disposal hands off to a foreground owner without startup consent`() = live("windows", "foreground-restart")
    @Test fun `Windows Finish consent persists startup and restarts the authenticated route`() = live("windows", "background-restart")
    @Test fun `legacy paired peer can bind a selected BlueZ transport without replacing its pinned key`() = live("linux", "legacy-binding")
    @Test fun `selected first Bluetooth session is not diverted to available WLAN`() = live("windows", "wifi-present")
    @Test fun `Linux resumes a dropped Bluetooth finish using the authenticated pending route`() = live("linux", "drop-finish")
    @Test fun `Windows resumes a dropped Bluetooth finish using the authenticated pending route`() = live("windows", "drop-finish")
    @Test fun `Bluetooth code deadline clears pending keys and UI without granting trust`() = live("windows", "expire-code")
    @Test fun `Linux OS denial wrong device app decline and code decline never persist trust`() {
        listOf("deny", "wrong-device", "decline", "code-decline").forEach { live("linux", it) }
    }
    @Test fun `Windows OS denial wrong device app decline and code decline never persist trust`() {
        listOf("deny", "wrong-device", "decline", "code-decline").forEach { live("windows", it) }
    }

    private fun live(platform: String, mode: String = "accept") {
        org.junit.Assume.assumeTrue(System.getenv("MAGNOLIE_BLUETOOTH_INTEGRATION") == "1")
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively(); context.deleteDatabase("magnolie_phone.db")
        Shadows.shadowOf(context as Application).grantPermissions(Manifest.permission.BLUETOOTH_CONNECT)
        val provider = object : Provider("BluetoothFixture", 1.0, "JVM fixture only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        val storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java).apply { isAccessible = true }.newInstance(context)
        storage.setEnabled(true)
        val work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
            .apply { isAccessible = true }.newInstance(context, storage)
        TelefonWerk::class.java.getDeclaredField("serviceRunning").apply { isAccessible = true }.setBoolean(work, true)
        if (mode == "wifi-present") TelefonWerk::class.java.getDeclaredField("wifiAvailable").apply { isAccessible = true }.setBoolean(work, true)
        val port = AtomicInteger()
        val dropFinish = java.util.concurrent.atomic.AtomicBoolean(mode == "drop-finish")
        work.bluetoothListenerFactory = {
            val server = ServerSocket().apply { reuseAddress = true; bind(InetSocketAddress(InetAddress.getLoopbackAddress(), port.get())) }
            port.compareAndSet(0, server.localPort)
            object : TelefonRfcommListener {
                override fun accept(): TelefonBluetoothLink {
                    val socket = server.accept()
                    return TelefonBluetoothLink(pc, Pipe(socket, dropFinish,
                        if (mode == "expire-code") System.nanoTime() + TimeUnit.SECONDS.toNanos(5) else Long.MAX_VALUE))
                }
                override fun close() = server.close()
            }
        }
        work.startBluetoothSetup()
        val script = File("../magnolie-organizer-2.0.0/pruefungen/phone_bluetooth_host.py").canonicalPath
        val process = ProcessBuilder("python3", "-u", script, platform, port.get().toString(), mode).redirectError(ProcessBuilder.Redirect.INHERIT).start()
        val lines = LinkedBlockingQueue<String>()
        thread(isDaemon = true) { process.inputStream.bufferedReader().forEachLine { lines.put(it) } }
        val input = process.outputStream.bufferedWriter()
        fun command(value: String) { input.write(value + "\n"); input.flush() }
        fun rejected() {
            assertEquals("REJECTED", lines.poll(8, TimeUnit.SECONDS))
            assertNull(storage.peers().peer); assertFalse(storage.bluetoothEnabled()); assertFalse(storage.personalOwnDevice())
            assertTrue(process.waitFor(8, TimeUnit.SECONDS)); assertEquals(0, process.exitValue())
        }
        try {
            assertEquals("OSPAIR", lines.poll(10, TimeUnit.SECONDS))
            assertNull(storage.peers().peer); assertFalse(storage.bluetoothEnabled())
            command(if (mode == "deny") "OSDENY" else "OSACCEPT")
            if (mode in setOf("deny", "wrong-device")) { rejected(); return }
            waitFor { work.bluetoothPairingRequest.value?.invitation?.value != null }
            assertNull(storage.peers().peer); assertEquals("", work.state.value.pairingCode)
            work.bluetoothPairingRequest.value!!.decide(mode != "decline")
            if (mode == "decline") { rejected(); return }
            waitFor { work.state.value.connection == TelefonVerbindungsstatus.CODE_PENDING }
            assertEquals("CODE " + work.state.value.pairingCode, lines.poll(10, TimeUnit.SECONDS))
            // The real Compose screen transfers stream ownership at this point.
            work.stopBluetoothSetup()
            if (mode == "expire-code") {
                val reference = TelefonWerk::class.java.getDeclaredField("pending").apply { isAccessible = true }.get(work) as java.util.concurrent.atomic.AtomicReference<*>
                val pending = reference.get()!!
                val secret = pending.javaClass.getDeclaredField("staticPrivate").apply { isAccessible = true }.get(pending) as ByteArray
                waitFor { work.state.value.connection != TelefonVerbindungsstatus.CODE_PENDING }
                assertNull(reference.get()); assertTrue(secret.all { it == 0.toByte() }); assertEquals("", work.state.value.pairingCode)
                command("REJECT"); rejected(); return
            }
            command(if (mode == "code-decline") "REJECT" else "ACCEPT")
            if (mode == "code-decline") {
                assertThrows(Exception::class.java) { work.confirmPairing(true) }
                rejected(); return
            }
            if (mode == "drop-finish") assertThrows(java.io.IOException::class.java) { work.confirmPairing(true) }
            else work.confirmPairing(true)
            val result = lines.poll(12, TimeUnit.SECONDS).orEmpty()
            assertTrue("No authenticated result: ${work.state.value}", result.startsWith("RESULT"))
            waitFor { work.state.value.connection == TelefonVerbindungsstatus.ONLINE_BLUETOOTH }
            val peer = storage.peers().peer!!
            assertEquals("paired", peer.state); assertEquals(pc, peer.bluetooth_address)
            assertTrue(peer.bluetooth_inbound); assertEquals("", peer.last_host)
            assertTrue(storage.bluetoothEnabled()); assertFalse(storage.personalOwnDevice())
            assertFalse(storage.notificationsEnabled()); assertFalse(storage.dialRequestEnabled())
            if (mode == "legacy-binding") {
                val adapter = android.bluetooth.BluetoothAdapter.getDefaultAdapter()
                val device = adapter.getRemoteDevice(pc)
                Shadows.shadowOf(device).setBondState(android.bluetooth.BluetoothDevice.BOND_BONDED)
                Shadows.shadowOf(adapter).setBondedDevices(setOf(device))
                storage.savePeer(peer.copy(bluetooth_address = "", bluetooth_inbound = false))
                work.assignBluetooth(pc)
            }
            if (mode == "wifi-present") TelefonWerk::class.java.getDeclaredField("wifiAvailable").apply { isAccessible = true }.setBoolean(work, false)
            command("RECONNECT")
            assertEquals("RECONNECTED", lines.poll(18, TimeUnit.SECONDS))
            waitFor { (work.state.value.peer?.last_contact_ms ?: 0) > peer.last_contact_ms }
            assertEquals(TelefonVerbindungsstatus.ONLINE_BLUETOOTH, work.state.value.connection)
            assertEquals(peer.static_public, storage.peers().peer!!.static_public)
            assertEquals(pc, storage.peers().peer!!.bluetooth_address)
            assertTrue(storage.peers().peer!!.bluetooth_inbound)
            work.serviceStopped(); command("STOP")
            assertTrue(process.waitFor(8, TimeUnit.SECONDS)); assertEquals(0, process.exitValue())
        } finally {
            work.serviceStopped()
            if (process.isAlive) { process.destroy(); if (!process.waitFor(3, TimeUnit.SECONDS)) process.destroyForcibly() }
            Security.removeProvider(provider.name)
        }
    }

    @Test fun `Bluetooth offer is exact target nonce bound and rejects URL replay and wrong device`() {
        val target = "11111111-1111-4111-8111-111111111111"
        val nonce = TelefonKrypto.b64(ByteArray(16))
        val offer = JsonObject(mapOf("p" to JsonPrimitive(TelefonBluetoothEinladung.PROTOCOL),
            "type" to JsonPrimitive("bluetooth_offer"), "target" to JsonPrimitive(target), "nonce" to JsonPrimitive(nonce),
            "device_id" to JsonPrimitive("22222222-2222-4222-8222-222222222222"), "name" to JsonPrimitive("Desktop"),
            "token" to JsonPrimitive(nonce), "ttl" to JsonPrimitive(60)))
        assertEquals("", TelefonBluetoothEinladung.offer(offer, target, nonce).host)
        for ((key, value) in listOf("target" to JsonPrimitive("wrong"), "nonce" to JsonPrimitive("replay"),
            "ttl" to JsonPrimitive(61), "url" to JsonPrimitive("http://127.0.0.1"), "name" to JsonPrimitive("spoof\u202e")))
            assertThrows(Exception::class.java) { TelefonBluetoothEinladung.offer(JsonObject(offer + (key to value)), target, nonce) }
    }

    @Test fun `RFCOMM consent expiry replay cancellation and disconnect close only the owned stream`() {
        val target = "11111111-1111-4111-8111-111111111111"
        for (action in listOf("expire", "replay", "cancel", "disconnect", "oversize")) {
            val clock = java.util.concurrent.atomic.AtomicLong()
            val request = TelefonBluetoothAnfrage(target, clock::get)
            val called = AtomicInteger()
            ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { server ->
                val worker = thread(isDaemon = true) {
                    try { request.receive(TelefonBluetoothLink(pc, Pipe(server.accept()))) { _, _, _ -> called.incrementAndGet() } }
                    catch (_: Exception) { }
                }
                Socket(InetAddress.getLoopbackAddress(), server.localPort).use { socket ->
                    socket.soTimeout = 3000
                    val hello = TelefonRahmen.lesen(socket.getInputStream(), 2048)
                    val nonce = hello.string("nonce")
                    if (action == "oversize") java.io.DataOutputStream(socket.getOutputStream()).apply { writeInt(2049); flush() }
                    else {
                        TelefonRahmen.schreiben(socket.getOutputStream(), JsonObject(mapOf(
                            "p" to JsonPrimitive(TelefonBluetoothEinladung.PROTOCOL), "type" to JsonPrimitive("bluetooth_offer"),
                            "target" to JsonPrimitive(target), "nonce" to JsonPrimitive(nonce),
                            "device_id" to JsonPrimitive("22222222-2222-4222-8222-222222222222"),
                            "name" to JsonPrimitive("Desktop"), "token" to JsonPrimitive(TelefonKrypto.b64(ByteArray(16))), "ttl" to JsonPrimitive(60))))
                        waitFor { request.invitation.value != null }
                        when (action) {
                            "expire" -> { clock.set(TimeUnit.SECONDS.toNanos(61)); request.decide(true) }
                            "cancel" -> request.close()
                            "disconnect" -> socket.close()
                        }
                        if (action == "expire" || action == "replay") TelefonRahmen.schreiben(socket.getOutputStream(),
                            TelefonBluetoothEinladung.control("wait", if (action == "replay") "old-nonce" else nonce))
                    }
                    if (!socket.isClosed) assertEquals(-1, socket.getInputStream().read())
                }
                worker.join(3000)
                assertFalse(worker.isAlive); assertEquals(0, called.get()); assertNull(request.invitation.value)
                request.close()
            }
        }
    }

    @Test fun `Android Bluetooth permission denial never starts a listener or grants transport`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        File(context.filesDir, "telefon").deleteRecursively()
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        Shadows.shadowOf(context as Application).denyPermissions(Manifest.permission.BLUETOOTH_CONNECT)
        val storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java).apply { isAccessible = true }.newInstance(context)
        storage.setEnabled(true)
        val work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
            .apply { isAccessible = true }.newInstance(context, storage)
        TelefonWerk::class.java.getDeclaredField("serviceRunning").apply { isAccessible = true }.setBoolean(work, true)
        var opened = false
        work.bluetoothListenerFactory = { opened = true; error("must not open") }
        assertThrows(SecurityException::class.java) { work.startBluetoothSetup() }
        assertFalse(opened); assertFalse(storage.bluetoothEnabled()); assertNull(storage.peers().peer)
        work.serviceStopped()
    }

    @Test fun `Bluetooth setup labels are explicitly translated in all twenty Android locales`() {
        val root = File("app/src/main/res")
        val locales = root.listFiles()!!.filter { it.name.startsWith("values") && File(it, "strings.xml").isFile }
        assertEquals(20, locales.size)
        for (key in listOf("telefon_bluetooth_setup", "telefon_bluetooth_setup_hinweis")) {
            val pattern = Regex("<string name=\"$key\">([^<]+)</string>")
            val english = pattern.find(File(root, "values/strings.xml").readText())!!.groupValues[1]
            for (locale in locales) {
                val text = pattern.find(File(locale, "strings.xml").readText())?.groupValues?.get(1)
                assertNotNull("Missing $key in ${locale.name}", text)
                if (locale.name != "values") assertNotEquals("English fallback in ${locale.name}", english, text)
            }
        }
    }
}
