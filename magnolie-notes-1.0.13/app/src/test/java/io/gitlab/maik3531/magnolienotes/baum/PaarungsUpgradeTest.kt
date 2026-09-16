package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
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
import java.nio.file.Files
import javax.crypto.KeyGenerator

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PaarungsUpgradeTest {
    @Test fun sequentialUnauthenticatedRequestsStayBoundedAcrossRestart() = store { context, reload ->
        val own = identity("own"); val pinned = identity("pinned")
        val storage = reload().apply { setzeBaum(state(own, pinned)) }
        val work = Baumwerk.fuerTest(storage, context)
        val server = Server(work, 0)
        val request = { id: Int -> buildJsonObject {
            put("kennung", JsonPrimitive("pending-$id")); put("name", JsonPrimitive("Synthetic"))
            put("oeffentlich", JsonPrimitive(own.oeffentlich)); put("port", JsonPrimitive(8737))
        } }
        assertEquals(403, server.behandeln("/magnolie/v1/paarung", request(0), "192.0.2.1").first)
        val window = Baumwerk::class.java.getDeclaredField("codeFenster").apply { isAccessible = true }.get(work) as CodePaarungsFenster
        window.oeffnen()
        repeat(100) { id ->
            assertEquals(if (id < Paarung.OFFEN_MAX) 200 else 403,
                server.behandeln("/magnolie/v1/paarung", request(id), "192.0.2.${id + 1}").first)
        }
        val restarted = reload()
        assertEquals(Paarung.OFFEN_MAX, restarted.baum.value.partner.count { !it.bestaetigt })
        assertEquals(peer(pinned), restarted.baum.value.partner.single { it.bestaetigt })
        val restartedServer = Server(Baumwerk.fuerTest(restarted, context), 0)
        assertEquals(403, restartedServer.behandeln("/magnolie/v1/paarung", request(101), "192.0.2.1").first)
        restarted.aendereBaum { it.copy(partner = it.partner.map { p ->
            if (p.bestaetigt) p else p.copy(paarungGueltigBis = 1) }) }
        assertThrows(BaumFehler::class.java) { Baumwerk.fuerTest(restarted, context).bestaetigen("pending-0") }
        assertEquals(listOf(peer(pinned)), restarted.baum.value.partner)
        assertEquals(listOf(peer(pinned)), reload().baum.value.partner)
    }

    @Test fun `uncertain legacy envelope stays bound without auto retry after response loss upgrade and restart`() = store { context, reload ->
        val a = identity("a"); val b = identity("b")
        val recipientDirectory = File(context.filesDir, "recipient").apply { mkdirs() }
        val recipientContext = object : ContextWrapper(context) {
            override fun getFilesDir() = recipientDirectory
            override fun getApplicationContext(): Context = this
        }
        val recipientKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val recipient = Ablage.fuerTest(recipientContext) { recipientKey }
        recipient.setzeBaum(state(a, b))
        recipient.setzeAufgabe(Aufgabe("once", "One effect", delegiertAn = "b"))
        val handler = Baumwerk.fuerTest(recipient, recipientContext)
        var applied = 0
        val server = Server(object : Server.Handlung by handler {
            override fun legacyNachricht(umschlag: JsonObject, quelle: String): JsonObject {
                val result = handler.legacyNachricht(umschlag, quelle)
                applied++
                if (applied == 1) throw IOException("reply lost after durable mutation")
                return result
            }
        }, 0)
        assertTrue(server.starten())
        try {
            val sender = reload()
            val pinned = peer(a).copy(adresse = "127.0.0.1", port = server.port, fernAdresse = "", bluetooth = "")
            val status = buildJsonObject {
                put("art", JsonPrimitive("stand")); put("id", JsonPrimitive("once"))
                put("erledigt", JsonPrimitive(true)); put("geaendert", JsonPrimitive(100))
            }
            sender.setzeBaum(state(b, a).copy(partner = listOf(pinned), postfach = listOf(Sendung(
                "pending", Krypto.b64(Krypto.zufallsbytes(16)), "a", "stand", Kanonisch.text(status), angelegt = System.currentTimeMillis()))))
            assertEquals(0, Baumwerk.fuerTest(sender, context).postfachAbarbeiten())
            assertTrue(recipient.aufgabe("once")!!.erledigt)
            val pending = reload().baum.value.postfach.single()
            assertTrue(pending.baum1Umschlag.isNotEmpty())
            assertTrue(pending.receiptAttempted && pending.unsicher)
            sender.aendereBaum { Paarung.partnerAufnehmen(it, pinned.copy(protokoll = "baum-fs1"), true) }
            val restarted = reload()
            restarted.aendereBaum { it.copy(postfach = it.postfach.map { item -> item.copy(naechsterVersuch = 0) }) }
            assertEquals(pending.baum1Umschlag, restarted.baum.value.postfach.single().baum1Umschlag)
            assertEquals(0, Baumwerk.fuerTest(restarted, context).postfachAbarbeiten())
            assertEquals(1, applied)
            assertEquals(pending.baum1Umschlag, reload().baum.value.postfach.single().baum1Umschlag)
            assertEquals("baum-fs1", restarted.baum.value.partner.single().protokoll)
            assertFalse(restarted.baum.value.partner.single().vertraut)
        } finally { server.anhalten() }
    }

    private fun identity(id: String) = Krypto.neuesSchluesselpaar().let {
        EigeneIdentitaet(id, id, Krypto.b64(it.second), Krypto.b64(it.first), 8737)
    }
    private fun peer(identity: EigeneIdentitaet) = Partner(identity.kennung, "Pinned name", identity.oeffentlich,
        adresse = "192.0.2.1", port = 12345, fernAdresse = "192.0.2.2", fernPort = 23456,
        bluetooth = "AA:BB:CC:DD:EE:FF", bestaetigt = true, vertraut = false,
        kontaktSync = false, kontaktLoeschSync = false, protokoll = "baum-1", zuletzt = 7,
        zaehlerRaus = 21, zaehlerRein = 17, gesehen = listOf("seen"),
        kontaktSyncFassungen = listOf(1, 2), kontaktImportFassungen = listOf(1))
    private fun state(own: EigeneIdentitaet, remote: EigeneIdentitaet) = Baumzustand(
        kennung = own.kennung, name = own.name, oeffentlich = own.oeffentlich, geheim = own.geheim,
        dienstAn = true, partner = listOf(peer(remote)))
    private fun store(test: (Context, () -> Ablage) -> Unit) {
        val directory = Files.createTempDirectory("pair-upgrade-").toFile()
        val base = ApplicationProvider.getApplicationContext<Context>()
        val context = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        try { test(context) { Ablage.fuerTest(context) { key } } } finally { directory.deleteRecursively() }
    }

    @Test fun `same key file proof advances protocol only and public pairing cannot downgrade`() {
        val a = identity("a"); val b = identity("b")
        val old = state(a, b)
        val incoming = peer(b).copy(name = "Forged name", adresse = "203.0.113.9", port = 1,
            vertraut = true, protokoll = "baum-fs1", kontaktSyncFassungen = listOf(1))
        assertEquals(old, Paarung.partnerAufnehmen(old, incoming))
        val upgraded = Paarung.partnerAufnehmen(old, incoming, true)
        assertEquals(old.partner.single().copy(protokoll = "baum-fs1"), upgraded.partner.single())
        assertEquals(upgraded, Paarung.partnerAufnehmen(upgraded, incoming.copy(protokoll = "baum-1")))
        val future = old.copy(partner = listOf(old.partner.single().copy(protokoll = "future-protocol")))
        assertEquals(future, Paarung.partnerAufnehmen(future, incoming, true))
        assertThrows(BaumFehler::class.java) {
            Paarung.partnerAufnehmen(old, incoming.copy(oeffentlich = identity("b").oeffentlich), true)
        }
    }

    @Test fun `receiver verifies proof expiry nonce pin and durably replays exact receipt once`() = store { context, reload ->
        val a = identity("a"); val b = identity("b"); val now = System.currentTimeMillis() / 1000
        val (file, invite) = Paarung.erzeugeDatei(a, "127.0.0.1", now)
        val request = Paarung.anfrage(file, b)
        val original = state(a, b).copy(einladungen = listOf(invite))
        val storage = reload(); storage.setzeBaum(original)
        val server = Server(Baumwerk.fuerTest(storage, context))
        val forged = JsonObject(request + ("beweis" to JsonPrimitive(Krypto.b64Url(ByteArray(32)))))
        assertEquals(403, server.behandeln("/magnolie/v2/paarung", forged, "203.0.113.9").first)
        assertEquals(original, storage.baum.value)
        val first = server.behandeln("/magnolie/v2/paarung", request, "203.0.113.9")
        assertEquals(200, first.first); Paarung.pruefeAntwort(file, request, first.second)
        val persisted = reload()
        assertEquals(original.partner.single().copy(protokoll = "baum-fs1"), persisted.baum.value.partner.single())
        val beforeReplay = persisted.baum.value
        val restartedServer = Server(Baumwerk.fuerTest(persisted, context))
        assertEquals(first, restartedServer.behandeln("/magnolie/v2/paarung", request, "192.0.2.99"))
        assertEquals(beforeReplay, persisted.baum.value)
        assertEquals(403, restartedServer.behandeln("/magnolie/v2/paarung", Paarung.anfrage(file, b), "127.0.0.1").first)
        assertThrows(BaumFehler::class.java) { Paarung.annehmen(beforeReplay, a, request, "127.0.0.1", now + 86402) }
        assertThrows(BaumFehler::class.java) { Paarung.annehmen(original, a, request, "127.0.0.1", now + 900) }
        val wrongKey = Paarung.anfrage(file, identity("b"))
        assertThrows(BaumFehler::class.java) { Paarung.annehmen(original, a, wrongKey, "127.0.0.1", now + 1) }
        assertThrows(IllegalArgumentException::class.java) { Paarung.anfrage(file, b, ByteArray(31)) }
    }

    @Test fun `selected file retries its persisted nonce after reply loss and never requeues completed pairing`() = store { context, reload ->
        val a = identity("a"); val b = identity("b"); var now = System.currentTimeMillis() / 1000
        val (file, invite) = Paarung.erzeugeDatei(a, "127.0.0.1", now)
        var receiver = state(a, b).copy(einladungen = listOf(invite))
        val storage = reload(); storage.setzeBaum(state(b, a))
        val requests = mutableListOf<JsonObject>()
        val send: (JsonObject, EigeneIdentitaet, JsonObject) -> JsonObject = { _, _, request ->
            requests += request
            val result = Paarung.annehmen(receiver, a, request, "203.0.113.8", now)
            receiver = result.first
            if (requests.size == 1) throw IOException("lost reply")
            result.second
        }
        assertThrows(IOException::class.java) { Baumwerk.fuerTest(storage, context).paareMitDatei(Kanonisch.text(file), send) { now } }
        assertEquals("baum-1", reload().baum.value.partner.single().protokoll)
        val restarted = reload(); val flow = Baumwerk.fuerTest(restarted, context)
        assertEquals(peer(a).copy(protokoll = "baum-fs1"), flow.paareMitDatei(Kanonisch.text(file), send) { now })
        assertEquals(requests[0], requests[1])
        val committed = restarted.baum.value
        flow.paareMitDatei(Kanonisch.text(file), { _, _, _ -> error("must not send twice") }) { now }
        assertEquals(committed, restarted.baum.value)
        now += 900
        assertThrows(BaumFehler::class.java) { flow.paareMitDatei(Kanonisch.text(file), send) { now } }
    }

    @Test fun `response nonce identity and expiry remain bound even with a valid MAC`() = store { context, reload ->
        val a = identity("a"); val b = identity("b"); val now = System.currentTimeMillis() / 1000
        val (file, invite) = Paarung.erzeugeDatei(a, "127.0.0.1", now)
        val request = Paarung.anfrage(file, b)
        val response = Paarung.nimmAnfrageAn(a, listOf(invite), request, now).first
        fun resign(body: JsonObject): JsonObject {
            val core = JsonObject(body - "beweis")
            return JsonObject(core + ("beweis" to JsonPrimitive(Krypto.b64Url(Krypto.hmacUeber(
                Krypto.b64UrlLesen(text(file, "geheimnis"), 32), "magnolie-pair-response-v2\u0000".toByteArray(), core)))))
        }
        val wrongNonce = resign(JsonObject(response + ("nonce" to JsonPrimitive(Krypto.b64Url(ByteArray(32))))))
        assertThrows(BaumFehler::class.java) { Paarung.pruefeAntwort(file, request, wrongNonce) }
        assertThrows(BaumFehler::class.java) { Paarung.pruefeAntwort(file, request,
            resign(JsonObject(response + ("zweig" to identity("a").alsZweig())))) }
        val storage = reload(); val old = state(b, a); storage.setzeBaum(old)
        var clock = now
        assertThrows(BaumFehler::class.java) { Baumwerk.fuerTest(storage, context).paareMitDatei(Kanonisch.text(file),
            { _, _, r -> Paarung.nimmAnfrageAn(a, listOf(invite), r, now).first.also { clock += 900 } }) { clock } }
        assertEquals(old.partner, storage.baum.value.partner)
        assertTrue(storage.baum.value.postfach.isEmpty())
    }

    @Test fun `legacy envelope is persisted before send and survives upgrade with one domain mutation`() = store { context, reload ->
        val a = identity("a"); val b = identity("b")
        val status = buildJsonObject {
            put("art", JsonPrimitive("stand")); put("id", JsonPrimitive("task"))
            put("erledigt", JsonPrimitive(true)); put("geaendert", JsonPrimitive(100))
        }
        val storage = reload(); storage.setzeBaum(state(b, a).copy(postfach = listOf(Sendung(
            "pending", Krypto.b64(Krypto.zufallsbytes(16)), "a", "stand", Kanonisch.text(status)))))
        val flow = Baumwerk.fuerTest(storage, context)
        val prepared = flow.sendungVorbereiten(storage.baum.value.postfach.single().id)!!
        assertTrue(prepared.baum1Umschlag.isNotEmpty())
        assertEquals(prepared, reload().baum.value.postfach.single())
        val upgraded = Paarung.partnerAufnehmen(storage.baum.value, peer(a).copy(protokoll = "baum-fs1"), true)
        storage.setzeBaum(upgraded)
        assertEquals(prepared, flow.sendungVorbereiten(prepared.id))
        val receiverDirectory = File(context.filesDir, "receiver").apply { mkdirs() }
        val receiverContext = object : ContextWrapper(context) {
            override fun getFilesDir() = receiverDirectory
            override fun getApplicationContext(): Context = this
        }
        val receiverKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val received = Ablage.fuerTest(receiverContext) { receiverKey }; received.setzeBaum(state(a, b))
        val receiver = Server(Baumwerk.fuerTest(received, receiverContext))
        val brief = Kanonisch.json.parseToJsonElement(prepared.baum1Umschlag).jsonObject
        received.setzeAufgabe(Aufgabe("task", "Exactly once", delegiertAn = "b"))
        assertEquals(200, receiver.behandeln("/magnolie/v1/nachricht", brief, "192.0.2.1").first)
        val once = received.bestand.value
        val peerOnce = received.baum.value.partner.single()
        val restarted = Ablage.fuerTest(receiverContext) { receiverKey }
        val restartedServer = Server(Baumwerk.fuerTest(restarted, receiverContext))
        assertEquals(200, restartedServer.behandeln("/magnolie/v1/nachricht", brief, "203.0.113.9").first)
        assertEquals(once, restarted.bestand.value); assertEquals(peerOnce, restarted.baum.value.partner.single())
        assertTrue(restarted.aufgabe("task")!!.erledigt)
        val different = Baum1.baue(b, a.kennung, a.oeffentlich,
            JsonObject(status + ("erledigt" to JsonPrimitive(false))), zahl(brief, "zaehler")!!)
        assertEquals(403, restartedServer.behandeln("/magnolie/v1/nachricht", different, "192.0.2.1").first)
        assertEquals(once, restarted.bestand.value)
        val paths = mutableListOf<String>()
        val fake = object : Transport {
            override val bezeichnung = "test"
            override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
                paths += pfad; assertEquals(brief, nutzlast)
                val key = Krypto.partnerschluessel(a.geheim, b.oeffentlich, a.kennung, b.kennung)
                return try { Baum1Quittung.erstellen(key, b.kennung, a.kennung, nutzlast) } finally { key.fill(0) }
            }
        }
        assertTrue(Versand.zustellen(b, upgraded.partner.single(), "stand", status, prepared.transportId, fake, brief).gelungen)
        assertEquals(listOf("/magnolie/v1/nachricht"), paths)
        assertEquals(upgraded.partner.single(), storage.baum.value.partner.single())
    }
}
