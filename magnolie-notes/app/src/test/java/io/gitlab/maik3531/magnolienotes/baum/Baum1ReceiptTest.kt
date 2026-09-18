package io.gitlab.maik3531.magnolienotes.baum

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class Baum1ReceiptTest {
    private fun identity(id: String) = Krypto.neuesSchluesselpaar().let {
        EigeneIdentitaet(id, id, Krypto.b64(it.second), Krypto.b64(it.first), 8737)
    }
    private fun state(own: EigeneIdentitaet, peer: EigeneIdentitaet, port: Int = 8737) = Baumzustand(
        kennung = own.kennung, name = own.name, geheim = own.geheim, oeffentlich = own.oeffentlich, dienstAn = true,
        partner = listOf(Partner(peer.kennung, peer.name, peer.oeffentlich, adresse = "127.0.0.1", port = port,
            bestaetigt = true, vertraut = true, protokoll = "baum-1")))
    private fun body(clock: Long = 100) = buildJsonObject {
        put("art", JsonPrimitive("stand")); put("id", JsonPrimitive("task"))
        put("erledigt", JsonPrimitive(true)); put("geaendert", JsonPrimitive(clock))
    }
    private class Store(val directory: File) {
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        val key = SecretKeySpec(ByteArray(32) { 71 }, "AES")
        fun load() = Ablage.fuerTest(context) { key }
    }
    private fun fixture(action: (Store, Store, EigeneIdentitaet, EigeneIdentitaet) -> Unit) {
        val root = kotlin.io.path.createTempDirectory("baum-receipt-").toFile()
        try {
            val sender = Store(File(root, "sender").apply { mkdirs() })
            val receiver = Store(File(root, "receiver").apply { mkdirs() })
            val a = identity("sender"); val b = identity("recipient")
            receiver.load().apply { setzeBaum(state(b, a)); setzeAufgabe(Aufgabe("task", "Fixture", delegiertAn = a.kennung)) }
            action(sender, receiver, a, b)
        } finally { root.deleteRecursively() }
    }
    private fun enqueue(data: Ablage, peer: EigeneIdentitaet) = data.aendereBaum { it.copy(postfach = it.postfach + Sendung(
        UUID.randomUUID().toString(), Krypto.b64(Krypto.zufallsbytes(16)), peer.kennung, "stand", Kanonisch.text(body()),
        angelegt = System.currentTimeMillis(), syncEpoch = it.syncEpoch)) }

    @Test fun portableVectorMatchesAndEveryWrongBindingIsRejected() {
        val shared = File("../contracts/baum-1-receipt-v1-vectors.json")
        val source = if (shared.isFile) shared else File("contracts/baum-1-receipt-v1-vectors.json")
        val vector = Kanonisch.json.parseToJsonElement(source.readText()).jsonObject
        val key = vector.getValue("partnerKeyHex").jsonPrimitive.content.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val envelope = vector.getValue("envelope").jsonObject
        val receipt = Baum1Quittung.erstellen(key, "alpha", "beta", envelope)
        assertEquals(vector["receipt"], receipt)
        assertEquals(vector.getValue("canonicalEnvelope").jsonPrimitive.content, Kanonisch.text(envelope))
        assertEquals(vector.getValue("canonicalCore").jsonPrimitive.content, Kanonisch.text(JsonObject(receipt - "mac")))
        assertTrue(Baum1Quittung.pruefen(key, "alpha", "beta", envelope, receipt))
        assertFalse(Baum1Quittung.pruefen(ByteArray(32), "alpha", "beta", envelope, receipt))
        assertFalse(Baum1Quittung.pruefen(key, "beta", "alpha", envelope, receipt))
        for ((field, value) in listOf("zaehler" to JsonPrimitive(2), "daten" to JsonPrimitive("different")))
            assertFalse(Baum1Quittung.pruefen(key, "alpha", "beta", JsonObject(envelope + (field to value)), receipt))
        for (invalid in listOf(JsonObject(receipt + ("extra" to JsonPrimitive(true))), JsonObject(receipt - "mac"),
                JsonObject(emptyMap()), JsonObject(mapOf("ok" to JsonPrimitive(true))),
                JsonObject(receipt + ("version" to JsonPrimitive("1"))),
                JsonObject(receipt + ("mac" to JsonPrimitive(receipt.getValue("mac").jsonPrimitive.content.trimEnd('='))))))
            assertFalse(Baum1Quittung.pruefen(key, "alpha", "beta", envelope, invalid))
    }

    @Test fun timeoutsResetsAndRefusedHostnamesAreNeverProofOfNoAcceptance() {
        assertFalse(verbindungAbgelehnt(java.net.ConnectException("Failed to connect to refused.example: Connection timed out")))
        assertFalse(verbindungAbgelehnt(java.net.ConnectException("Connection refused").apply {
            initCause(android.system.ErrnoException("connect", android.system.OsConstants.ETIMEDOUT))
        }))
        val a = identity("a"); val b = identity("b")
        val wire = Baum1.baue(a, b.kennung, b.oeffentlich, body(), 1)
        for (failure in listOf(java.net.ConnectException("Connection refused"), java.net.SocketTimeoutException(), java.net.SocketException("reset"))) {
            val transport = object : Transport {
                override val bezeichnung = "after-connect fixture"
                override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject = throw failure
            }
            val result = Versand.zustellen(a, state(a, b).partner.single(), "stand", body(), "", transport, wire)
            assertTrue(result.unsicher); assertFalse(result.gelungen)
        }
    }

    @Test fun verifiedEncryptedLoopbackReleasesOnlyTheExactReservedItem() = fixture { sender, receiver, a, b ->
        val server = Server(Baumwerk.fuerTest(receiver.load(), receiver.context), 0)
        check(server.starten())
        try {
            val data = sender.load(); data.setzeBaum(state(a, b, server.port)); enqueue(data, b)
            assertEquals(1, Baumwerk.fuerTest(data, sender.context).postfachAbarbeiten())
            assertTrue(sender.load().baum.value.postfach.isEmpty())
            val accepted = receiver.load()
            assertTrue(accepted.aufgabe("task")!!.erledigt)
            assertEquals(1, accepted.baum.value.partner.single().baum1Belege.size)
        } finally { server.anhalten() }
    }

    @Test fun unsignedWrongMacWrongBindingAndLostResponsesPauseWithoutFallbackOrRestartRetry() {
        for (mode in listOf("unsigned", "wrong-mac", "wrong-binding", "lost")) fixture { sender, receiver, a, b ->
            val received = receiver.load()
            val handler = Baumwerk.fuerTest(received, receiver.context)
            val calls = AtomicInteger()
            lateinit var server: Server
            server = Server(object : Server.Handlung by handler {
                override fun legacyNachricht(umschlag: JsonObject, quelle: String): JsonObject {
                    calls.incrementAndGet()
                    val receipt = handler.legacyNachricht(umschlag, quelle)
                    return when (mode) {
                        "unsigned" -> JsonObject(emptyMap())
                        "wrong-mac" -> JsonObject(receipt + ("mac" to JsonPrimitive(Krypto.b64(ByteArray(32)))))
                        "wrong-binding" -> {
                            val key = Krypto.partnerschluessel(b.geheim, a.oeffentlich, b.kennung, a.kennung)
                            try { Baum1Quittung.erstellen(key, a.kennung, "other", umschlag) } finally { key.fill(0) }
                        }
                        else -> { server.anhalten(); receipt }
                    }
                }
            }, 0)
            check(server.starten())
            ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { fallback ->
                fallback.soTimeout = 150
                try {
                    val data = sender.load()
                    data.setzeBaum(state(a, b, server.port).let { it.copy(partner = it.partner.map { p -> p.copy(fernAdresse = "127.0.0.1", fernPort = fallback.localPort) }) })
                    enqueue(data, b)
                    assertEquals(0, Baumwerk.fuerTest(data, sender.context).postfachAbarbeiten())
                    val pending = sender.load().baum.value.postfach.single()
                    assertTrue(mode, pending.unsicher && pending.receiptAttempted && pending.receiptProtocol == 1)
                    assertTrue(receiver.load().aufgabe("task")!!.erledigt)
                    val restarted = sender.load(); enqueue(restarted, b)
                    repeat(2) { assertEquals(0, Baumwerk.fuerTest(restarted, sender.context).postfachAbarbeiten()) }
                    assertEquals(1, calls.get()); assertEquals(2, sender.load().baum.value.postfach.size)
                    assertEquals(pending.baum1Umschlag, sender.load().baum.value.postfach.first().baum1Umschlag)
                    assertThrows(java.net.SocketTimeoutException::class.java) { fallback.accept() }
                } finally { server.anhalten() }
            }
        }
    }

    @Test fun connectionRefusalKeepsExactEnvelopeAndAllowsSafeRetry() = fixture { sender, receiver, a, b ->
        val reservation = Socket().apply { bind(InetSocketAddress(InetAddress.getLoopbackAddress(), 0)) }
        val port = reservation.localPort
        val refusal = runCatching { WlanTransport("127.0.0.1", port).anfrage("/fixture", JsonObject(emptyMap())) }.exceptionOrNull()
        assertTrue("${refusal?.javaClass?.name}: ${refusal?.message}; cause=${refusal?.cause}; errno=${android.system.Os.strerror(android.system.OsConstants.ECONNREFUSED)}", refusal is KeineVerbindung)
        val data = sender.load(); data.setzeBaum(state(a, b, port)); enqueue(data, b)
        try { assertEquals(0, Baumwerk.fuerTest(data, sender.context).postfachAbarbeiten()) } finally { reservation.close() }
        val pending = sender.load().baum.value.postfach.single()
        assertFalse(pending.brauchtPruefung); assertEquals(1, pending.versuche)
        val server = Server(Baumwerk.fuerTest(receiver.load(), receiver.context), port)
        check(server.starten())
        try {
            val restarted = sender.load()
            restarted.aendereBaum { it.copy(postfach = it.postfach.map { row -> row.copy(naechsterVersuch = 0) }) }
            assertEquals(pending.baum1Umschlag, restarted.baum.value.postfach.single().baum1Umschlag)
            assertEquals(1, Baumwerk.fuerTest(restarted, sender.context).postfachAbarbeiten())
            assertTrue(sender.load().baum.value.postfach.isEmpty())
        } finally { server.anhalten() }
    }

    @Test fun interruptedAttemptAndOldReservationsNeverTransmitAutomatically() = fixture { sender, receiver, a, b ->
        val calls = AtomicInteger()
        val handler = Baumwerk.fuerTest(receiver.load(), receiver.context)
        val server = Server(object : Server.Handlung by handler {
            override fun legacyNachricht(umschlag: JsonObject, quelle: String): JsonObject {
                calls.incrementAndGet(); return handler.legacyNachricht(umschlag, quelle)
            }
        }, 0)
        check(server.starten())
        try {
            for (old in listOf(false, true)) {
                val data = sender.load(); data.setzeBaum(state(a, b, server.port)); enqueue(data, b)
                val work = Baumwerk.fuerTest(data, sender.context)
                val prepared = work.sendungVorbereiten(data.baum.value.postfach.single().id)!!
                if (old) data.aendereBaum { it.copy(postfach = it.postfach.map { row -> row.copy(receiptProtocol = 0) }) }
                else assertTrue(work.sendungVersuchen(prepared, data.baumVersandGeneration()))
                val restarted = sender.load()
                assertEquals(0, Baumwerk.fuerTest(restarted, sender.context).postfachAbarbeiten())
                assertTrue(sender.load().baum.value.postfach.single().unsicher)
                assertEquals(prepared.baum1Umschlag, sender.load().baum.value.postfach.single().baum1Umschlag)
            }
            assertEquals(0, calls.get())
        } finally { server.anhalten() }
    }

    @Test fun exactReceiptReplaysAfterRestartButDifferentWireAtSameCounterIsRejected() = fixture { _, receiver, a, b ->
        val firstWire = Baum1.baue(a, b.kennung, b.oeffentlich, body(), 1)
        val first = Baumwerk.fuerTest(receiver.load(), receiver.context).legacyNachricht(firstWire, "127.0.0.1")
        val data = receiver.load(); val before = data.journalNutzlast()
        val restarted = Baumwerk.fuerTest(data, receiver.context)
        assertEquals(first, restarted.legacyNachricht(firstWire, "127.0.0.2"))
        assertEquals(before, data.journalNutzlast())
        val changed = Baum1.baue(a, b.kennung, b.oeffentlich, body(), 1)
        assertThrows(BaumFehler::class.java) { restarted.legacyNachricht(changed, "127.0.0.1") }
        assertEquals(before, data.journalNutzlast())
    }

    private class Death : Error()
    @Test fun receiptCounterAndEffectRemainAtomicAtEveryCrashBoundary() {
        for (step in PaarCommitSchritt.entries) fixture { _, receiver, a, b ->
            val broken = Ablage.fuerTest(receiver.context, { receiver.key }) { if (it == step) throw Death() }
            val wire = Baum1.baue(a, b.kennung, b.oeffentlich, body(), 1)
            assertThrows(Death::class.java) { Baumwerk.fuerTest(broken, receiver.context).legacyNachricht(wire, "127.0.0.1") }
            val recovered = receiver.load()
            val cached = recovered.baum.value.partner.single().baum1Belege.singleOrNull()
            assertEquals(step.name, cached != null, recovered.aufgabe("task")!!.erledigt)
            val before = recovered.journalNutzlast()
            val receipt = Baumwerk.fuerTest(recovered, receiver.context).legacyNachricht(wire, "127.0.0.1")
            val key = Krypto.partnerschluessel(a.geheim, b.oeffentlich, a.kennung, b.kennung)
            assertTrue(Baum1Quittung.pruefen(key, a.kennung, b.kennung, wire, receipt)); key.fill(0)
            if (cached != null) assertEquals(before, recovered.journalNutzlast())
        }
    }

    @Test fun inboxStoresExactEncryptedEnvelopeHashWithItsReceipt() = fixture { _, receiver, a, b ->
        val data = receiver.load()
        data.aendereBaum { it.copy(partner = it.partner.map { p -> p.copy(vertraut = false) }) }
        val wire = Baum1.baue(a, b.kennung, b.oeffentlich, buildJsonObject { put("art", JsonPrimitive("notiz")) }, 1)
        Baumwerk.fuerTest(data, receiver.context).legacyNachricht(wire, "127.0.0.1")
        assertEquals(Baum1Quittung.hash(wire), receiver.load().baum.value.eingang.single().envelopeSha256)
    }

    @Test fun receiptCachesAreBoundedPerPeerAndProfileAndEvictedCountersStayRejected() = fixture { _, receiver, a, b ->
        val peers = listOf(a) + (1..4).map { identity("peer$it") }
        val data = receiver.load()
        data.aendereBaum { it.copy(partner = peers.map { p -> Partner(p.kennung, p.name, p.oeffentlich, bestaetigt = true, vertraut = false) }) }
        val work = Baumwerk.fuerTest(data, receiver.context)
        var oldest: JsonObject? = null
        peers.forEach { peer -> repeat(65) { index ->
            val wire = Baum1.baue(peer, b.kennung, b.oeffentlich, buildJsonObject { put("art", JsonPrimitive("fixture")) }, index + 1L)
            if (oldest == null) oldest = wire
            work.legacyNachricht(wire, "127.0.0.1")
        } }
        val persisted = receiver.load()
        assertEquals(256, persisted.baum.value.partner.sumOf { it.baum1Belege.size })
        assertTrue(persisted.baum.value.partner.all { it.baum1Belege.size <= 64 })
        assertThrows(BaumFehler::class.java) { Baumwerk.fuerTest(persisted, receiver.context).legacyNachricht(oldest!!, "127.0.0.1") }
    }
}
