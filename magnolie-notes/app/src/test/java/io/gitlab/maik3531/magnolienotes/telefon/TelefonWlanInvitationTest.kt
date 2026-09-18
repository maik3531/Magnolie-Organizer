package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.net.InetAddress
import java.security.KeyStoreSpi
import java.security.Provider
import java.security.Security
import java.security.cert.Certificate
import java.util.Collections
import java.util.Date
import java.util.UUID
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread

// JVM-only Keystore provider. The production TelefonAblage encryption, pairing
// client, queue and secure session execute unchanged against isolated test data.
class InvitationTestKeyStore : KeyStoreSpi() {
    override fun engineGetKey(alias: String?, password: CharArray?) = SecretKeySpec(ByteArray(32) { 37 }, "AES")
    override fun engineLoad(stream: java.io.InputStream?, password: CharArray?) = Unit
    override fun engineStore(stream: java.io.OutputStream?, password: CharArray?) = Unit
    override fun engineAliases() = Collections.enumeration(listOf(TelefonAblage.KEY_ALIAS))
    override fun engineContainsAlias(alias: String?) = true
    override fun engineSize() = 1
    override fun engineIsKeyEntry(alias: String?) = true
    override fun engineIsCertificateEntry(alias: String?) = false
    override fun engineGetCertificate(alias: String?): Certificate? = null
    override fun engineGetCertificateChain(alias: String?): Array<Certificate>? = null
    override fun engineGetCertificateAlias(cert: Certificate?): String? = null
    override fun engineGetCreationDate(alias: String?) = Date(0)
    override fun engineSetKeyEntry(alias: String?, key: java.security.Key?, password: CharArray?, chain: Array<out Certificate>?) = Unit
    override fun engineSetKeyEntry(alias: String?, key: ByteArray?, chain: Array<out Certificate>?) = Unit
    override fun engineSetCertificateEntry(alias: String?, cert: Certificate?) = Unit
    override fun engineDeleteEntry(alias: String?) = Unit
}

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class TelefonWlanInvitationTest {
    private val target = "11111111-1111-4111-8111-111111111111"
    private val nonce = TelefonKrypto.b64(ByteArray(16) { 4 })
    private fun offer() = buildJsonObject {
        put("p", JsonPrimitive(TelefonEinladungsVertrag.PROTOCOL)); put("type", JsonPrimitive("offer"))
        put("target", JsonPrimitive(target)); put("nonce", JsonPrimitive(nonce))
        put("device_id", JsonPrimitive("22222222-2222-4222-8222-222222222222"))
        put("name", JsonPrimitive("Desktop <not markup>")); put("token", JsonPrimitive(TelefonKrypto.b64(ByteArray(16))))
        put("port", JsonPrimitive(8741)); put("ttl", JsonPrimitive(60))
    }
    @Test fun `invitations reject wrong target nonce callback URL loopback and ports`() {
        val source = InetAddress.getByName("192.168.1.2")
        val valid = offer()
        assertEquals("192.168.1.2", TelefonEinladungsVertrag.offer(valid, source, target, nonce).host)
        listOf("target" to JsonPrimitive(UUID.randomUUID().toString()), "nonce" to JsonPrimitive("replay"),
            "url" to JsonPrimitive("http://127.0.0.1/private"), "port" to JsonPrimitive(80),
            "port" to JsonPrimitive("8741"), "ttl" to JsonPrimitive(61), "ttl" to JsonPrimitive(0),
            "name" to JsonPrimitive("spoof\u202e"), "device_id" to JsonPrimitive(target)).forEach { (key, value) ->
            assertThrows(Exception::class.java) { TelefonEinladungsVertrag.offer(JsonObject(valid + (key to value)), source, target, nonce) }
        }
        listOf("127.0.0.1", "::1", "0.0.0.0", "224.0.0.251", "8.8.8.8").forEach {
            assertThrows(Exception::class.java) { TelefonEinladungsVertrag.offer(valid, InetAddress.getByName(it), target, nonce) }
        }
    }

    @Test fun `Linux setup NSD invitation full Android pairing and authenticated session over real TCP`() = live("linux")
    @Test fun `Linux daemon owns WLAN setup through UID guarded real Unix IPC`() = live("linux-daemon")
    @Test fun `Linux Finish persists consent and daemon restart resumes only the authenticated route`() = live("linux-daemon-startup")
    @Test fun `Windows setup NSD invitation full Android pairing and authenticated session over real TCP`() = live("windows")

    private fun address(): String = java.net.DatagramSocket().use {
        it.connect(InetAddress.getByName("192.0.2.1"), 9)
        require(TelefonEinladungsVertrag.local(it.localAddress))
        it.localAddress.hostAddress!!
    }

    @Test fun `real TCP cancel disconnect and expiry consume invitation without callback`() {
        org.junit.Assume.assumeTrue(System.getenv("MAGNOLIE_WLAN_INTEGRATION") == "1")
        for (action in listOf("cancel", "disconnect", "expire")) {
            val clock = java.util.concurrent.atomic.AtomicLong(0)
            val callbacks = java.util.concurrent.atomic.AtomicInteger()
            val receiver = TelefonEinladungsEmpfang(target, "Phone", { callbacks.incrementAndGet() }, clock::get)
            val port = receiver.port
            val worker = receiver.start()
            try {
                java.net.Socket(address(), receiver.port).use { socket ->
                    socket.soTimeout = 3000
                    TelefonRahmen.schreiben(socket.getOutputStream(), JsonObject(offer() + ("nonce" to JsonPrimitive(receiver.nonce))))
                    val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
                    while (receiver.invitation.value == null && System.nanoTime() < until) Thread.sleep(10)
                    assertNotNull(receiver.invitation.value)
                    when (action) {
                        "cancel" -> receiver.decide(false)
                        "disconnect" -> socket.close()
                        else -> { clock.set(TimeUnit.SECONDS.toNanos(61)); receiver.decide(true) }
                    }
                    if (!socket.isClosed) assertEquals(-1, socket.getInputStream().read())
                }
                worker.join(3000)
                assertFalse(worker.isAlive)
                assertTrue(receiver.finished.value)
                assertNull(receiver.invitation.value)
                assertEquals(0, callbacks.get())
                assertThrows(java.io.IOException::class.java) { java.net.Socket(address(), port).close() }
            } finally { receiver.close() }
        }
    }

    @Test fun `unauthenticated frame budget rejects oversize and repeated spoofed offers`() {
        org.junit.Assume.assumeTrue(System.getenv("MAGNOLIE_WLAN_INTEGRATION") == "1")
        val callbacks = java.util.concurrent.atomic.AtomicInteger()
        val receiver = TelefonEinladungsEmpfang(target, "Phone", { callbacks.incrementAndGet() })
        val worker = receiver.start()
        try {
            repeat(8) { attempt ->
                java.net.Socket(address(), receiver.port).use { socket ->
                    socket.soTimeout = 3000
                    if (attempt == 0) java.io.DataOutputStream(socket.getOutputStream()).apply { writeInt(2049); flush() }
                    else TelefonRahmen.schreiben(socket.getOutputStream(), offer()) // wrong public nonce
                    assertEquals(-1, socket.getInputStream().read())
                    assertNull(receiver.invitation.value)
                }
            }
            worker.join(3000)
            assertFalse(worker.isAlive)
            assertEquals(0, callbacks.get())
        } finally { receiver.close() }
    }

    private fun live(platform: String) {
        org.junit.Assume.assumeTrue(System.getenv("MAGNOLIE_WLAN_INTEGRATION") == "1")
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("magnolie_phone_settings", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "telefon").deleteRecursively()
        context.deleteDatabase("magnolie_phone.db")
        val provider = object : Provider("InvitationFixture", 1.0, "JVM fixture only") {
            init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
        }
        Security.insertProviderAt(provider, 1)
        val storage = TelefonAblage::class.java.getDeclaredConstructor(Context::class.java).apply { isAccessible = true }.newInstance(context)
        storage.setEnabled(true)
        val work = TelefonWerk::class.java.getDeclaredConstructor(Context::class.java, TelefonAblage::class.java)
            .apply { isAccessible = true }.newInstance(context, storage)
        listOf("serviceRunning", "wifiAvailable").forEach {
            TelefonWerk::class.java.getDeclaredField(it).apply { isAccessible = true }.setBoolean(work, true)
        }
        val (identity, privateKey) = storage.identity("Owned phone fixture"); privateKey.fill(0)
        val accepted = CompletableFuture<Unit>()
        val receiver = TelefonEinladungsEmpfang(identity.device_id, identity.display_name, { desktop ->
            try { work.beginPairing(desktop); accepted.complete(Unit) }
            catch (error: Throwable) { accepted.completeExceptionally(error) }
        })
        receiver.start()
        val address = address()
        val script = File("../magnolie-organizer/pruefungen/phone_invitation_host.py").canonicalPath
        val process = ProcessBuilder("python3", "-u", script, platform, identity.device_id, receiver.nonce, receiver.port.toString(), address)
            .redirectError(ProcessBuilder.Redirect.INHERIT).start()
        val lines = java.util.concurrent.LinkedBlockingQueue<String>()
        thread(isDaemon = true) { process.inputStream.bufferedReader().forEachLine { lines.put(it) } }
        try {
            val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(45)
            while (receiver.invitation.value == null && System.nanoTime() < until && process.isAlive) Thread.sleep(25)
            assertNotNull("No invitation: $lines", receiver.invitation.value)
            assertNull(storage.peers().peer)
            assertEquals("", work.state.value.pairingCode)
            receiver.decide(true)
            accepted.get(8, TimeUnit.SECONDS)
            val code = lines.poll(8, TimeUnit.SECONDS) ?: error("No desktop code")
            assertEquals("CODE " + work.state.value.pairingCode, code)
            val input = process.outputStream.bufferedWriter()
            input.write("ACCEPT\n"); input.flush()
            work.confirmPairing(true)
            val result = lines.poll(12, TimeUnit.SECONDS) ?: error("No authenticated setup result; phone=${work.state.value}")
            assertTrue(result, result.startsWith("RESULT "))
            assertEquals("paired", storage.peers().peer?.state)
            assertFalse(storage.personalOwnDevice())
            assertFalse(storage.notificationsEnabled())
            assertFalse(storage.dialRequestEnabled())
            work.serviceStopped()
            input.write("STOP\n"); input.flush()
            assertTrue(process.waitFor(5, TimeUnit.SECONDS))
            assertEquals(0, process.exitValue())
        } finally {
            receiver.close(); work.serviceStopped()
            if (process.isAlive) { process.destroy(); process.waitFor(3, TimeUnit.SECONDS); if (process.isAlive) process.destroyForcibly() }
            Security.removeProvider(provider.name)
        }
    }
}
