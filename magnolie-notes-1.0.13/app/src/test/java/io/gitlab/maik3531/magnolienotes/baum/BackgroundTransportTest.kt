package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.net.Socket
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE)
class BackgroundTransportTest {
    private open class Handlung : Server.Handlung {
        override fun eigen(): EigeneIdentitaet? = null
        override fun istAn() = true
        override fun partner(kennung: String): Partner? = null
        override fun einladungen() = emptyList<Einladung>()
        override fun dateiPaarungAnnehmen(eigen: EigeneIdentitaet, anfrage: JsonObject, adresse: String): JsonObject = error("unused")
        override fun codeAnfrage(name: String, kennung: String, oeffentlich: String, adresse: String, port: Int) = Unit
        override fun nachricht(vonKennung: String, inhalt: JsonObject) = Unit
        override fun merkeZaehler(vonKennung: String, zaehler: Long) = Unit
        override fun schonGesehen(vonKennung: String, transportId: String) = false
        override fun merkeTransportId(vonKennung: String, transportId: String) = Unit
        override fun adresseGesehen(vonKennung: String, adresse: String) = Unit
    }

    @Test fun restoreCancelsSenderDuringHandshakeBeforeAnyOldPayloadIsSent() = cancelledSender(true)

    @Test fun shutdownCancellationAlsoFencesTheNextRequestWithoutDroppingPendingData() = cancelledSender(false)

    private fun cancelledSender(restore: Boolean) {
        val dir = kotlin.io.path.createTempDirectory("restore-inflight-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = dir
        }
        val ablage = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32), "AES") }
        val senderKeys = Krypto.neuesSchluesselpaar()
        val receiverKeys = Krypto.neuesSchluesselpaar()
        val receiverId = EigeneIdentitaet("receiver", "Receiver", Krypto.b64(receiverKeys.second), Krypto.b64(receiverKeys.first), 0)
        val senderPeer = Partner("sender", oeffentlich = Krypto.b64(senderKeys.second), bestaetigt = true)
        val restored = AtomicBoolean(false)
        val received = AtomicInteger()
        var restorePayload = "" to ""
        val receiver = Server(object : Handlung() {
            override fun eigen(): EigeneIdentitaet {
                if (restored.compareAndSet(false, true)) {
                    if (restore) {
                        check(ablage.journalWiederherstellen(restorePayload.first, restorePayload.second, UUID.randomUUID().toString()))
                        check(ablage.baum.value.postfach.isEmpty())
                    } else ablage.baumTransporteAbbrechen()
                }
                return receiverId
            }
            override fun partner(kennung: String) = senderPeer.takeIf { kennung == "sender" }
            override fun nachricht(vonKennung: String, inhalt: JsonObject) { received.incrementAndGet() }
        }, 0)
        try {
            check(receiver.starten())
            ablage.setzeBaum(Baumzustand(kennung = "sender", name = "Sender", geheim = Krypto.b64(senderKeys.first),
                oeffentlich = Krypto.b64(senderKeys.second), syncEpoch = "before", partner = listOf(Partner("receiver",
                    oeffentlich = receiverId.oeffentlich, adresse = "127.0.0.1", port = receiver.port,
                    bestaetigt = true, vertraut = true, protokoll = "baum-fs1"))))
            restorePayload = ablage.journalNutzlast()
            ablage.aendereBaum { it.copy(postfach = listOf(Sendung(id = UUID.randomUUID().toString(),
                transportId = Krypto.b64(ByteArray(16)), an = "receiver", art = "audit",
                inhalt = "{\"sentinel\":\"PRE_RESTORE\"}", angelegt = System.currentTimeMillis(), syncEpoch = "before", protokoll = "baum-fs1"))) }
            assertEquals(0, Baumwerk.fuerTest(ablage, context).postfachAbarbeiten())
            if (restore) {
                assertNotEquals("before", ablage.baum.value.syncEpoch)
                assertEquals(1, ablage.baum.value.quarantiniertesPostfach.size)
            } else {
                assertEquals("before", ablage.baum.value.syncEpoch)
                assertEquals(1, ablage.baum.value.postfach.size)
                assertEquals(0, ablage.baum.value.postfach.single().versuche)
            }
            assertEquals(0, received.get())
        } finally { receiver.anhalten(); dir.deleteRecursively() }
    }

    @Test fun closedTransportCannotOpenAnotherPayloadConnection() {
        val transport = WlanTransport("127.0.0.1", 1)
        transport.schliessen()
        assertThrows(IllegalStateException::class.java) { transport.anfrage("/fixture", JsonObject(emptyMap())) }
    }

    @Test fun totalDeadlineReleasesSlowHeaderWorkersAndServerStillAcceptsRequests() {
        val server = Server(Handlung(), 0, requestTimeoutMs = 500)
        val clients = mutableListOf<Socket>()
        try {
            check(server.starten())
            repeat(Server.ARBEITER_MAX) {
                clients += Socket("127.0.0.1", server.port).apply {
                    soTimeout = 2000
                    getOutputStream().write("POST /fixture HTTP/1.1\r\nX:".toByteArray())
                }
            }
            repeat(8) {
                clients.forEach { runCatching { it.getOutputStream().write('x'.code); it.getOutputStream().flush() } }
                Thread.sleep(100)
            }
            clients.forEach { assertEquals(-1, try { it.getInputStream().read() } catch (_: java.net.SocketException) { -1 }) }
            Socket("127.0.0.1", server.port).use { socket ->
                socket.soTimeout = 2000
                socket.getOutputStream().write("POST /fixture HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}".toByteArray())
                assertTrue(socket.getInputStream().bufferedReader().readLine().startsWith("HTTP/1.1 503"))
            }
        } finally { clients.forEach { it.close() }; server.anhalten() }
    }

    @Test fun bluetoothCannotStartWithoutForegroundOwner() {
        val dir = kotlin.io.path.createTempDirectory("bt-owner-").toFile()
        try {
            val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
                override fun getApplicationContext(): Context = this
                override fun getFilesDir(): File = dir
            }
            val ablage = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32), "AES") }
            assertFalse(Baumwerk.fuerTest(ablage, context).bluetoothStarten())
            assertFalse(ablage.baum.value.bluetoothAn)
        } finally { dir.deleteRecursively() }
    }
}
