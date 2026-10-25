package io.gitlab.maik3531.magnolienotes

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Owned endpoint fixture; the established host driver performs all release UI actions. */
class DruckerSucheInstrumentationTest {
    @Test fun ownedIppEndpointFollowsBoundedHostCommandsWithoutPrinting() {
        val context = MagnolieTestRunner.testContext
        val prefs = context.getSharedPreferences("magnolie_print_view", Context.MODE_PRIVATE)
        val previous = prefs.getBoolean("only_available_wifi_printer", false)
        val directory = File(context.getExternalFilesDir(null), "printer-probe").apply { mkdirs() }
        val command = File(directory, "command.txt")
        val state = File(directory, "state.txt")
        command.delete(); state.delete()
        fun status(text: String) {
            val pending = File(directory, "state.new").apply { writeText(text) }
            assertTrue("Owned printer status commit failed", pending.renameTo(state))
        }
        fun listen(port: Int): Pair<ServerSocket, Thread> {
            val socket = ServerSocket().apply { reuseAddress = true; bind(InetSocketAddress(port)) }
            val thread = Thread {
                while (!socket.isClosed) try { socket.accept().use { } } catch (_: java.io.IOException) { break }
            }.apply { name = "owned-printer-fixture"; start() }
            return socket to thread
        }
        var listener = listen(0)
        val port = listener.first.localPort
        val nsd = context.getSystemService(NsdManager::class.java)
        val registered = CountDownLatch(1)
        var registrationFailed = false
        val service = NsdServiceInfo().apply {
            serviceName = "MagnolieOwnedPrinter-" + UUID.randomUUID().toString().take(8)
            serviceType = "_ipp._tcp."; setPort(port)
        }
        val registration = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(info: NsdServiceInfo) { registered.countDown() }
            override fun onRegistrationFailed(info: NsdServiceInfo, code: Int) { registrationFailed = true; registered.countDown() }
            override fun onServiceUnregistered(info: NsdServiceInfo) {}
            override fun onUnregistrationFailed(info: NsdServiceInfo, code: Int) {}
        }
        var finished = false
        try {
            assertTrue(prefs.edit().putBoolean("only_available_wifi_printer", true).commit())
            nsd.registerService(service, NsdManager.PROTOCOL_DNS_SD, registration)
            assertTrue("Owned Android DNS-SD registration timed out", registered.await(15, TimeUnit.SECONDS))
            assertFalse("Owned Android DNS-SD registration failed", registrationFailed)
            status("online")
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(180)
            while (System.nanoTime() < deadline && !finished) {
                if (command.isFile) {
                    val next = command.readText().trim(); command.delete()
                    when (next) {
                        "offline" -> { listener.first.close(); listener.second.join(3_000); status("offline") }
                        "online" -> { if (listener.first.isClosed) listener = listen(port); status("online") }
                        "finish" -> { finished = true; status("finished") }
                        else -> fail("Unknown owned printer fixture command")
                    }
                }
                Thread.sleep(100)
            }
            assertTrue("Owned host driver did not complete its UI checks", finished)
        } finally {
            listener.first.close(); listener.second.join(3_000)
            runCatching { nsd.unregisterService(registration) }
            prefs.edit().putBoolean("only_available_wifi_printer", previous).commit()
            command.delete()
        }
    }
}
