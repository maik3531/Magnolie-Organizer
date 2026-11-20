package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Partner
import io.gitlab.maik3531.magnolienotes.netz.LanTor
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.lang.reflect.InvocationTargetException
import java.util.concurrent.atomic.AtomicLong
import javax.crypto.spec.SecretKeySpec

/** Real FS1 origin -> actual isolated native receive transaction. No sockets,
 * installed state, private notebooks or physical contacts are accessed by these probes.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class BaumFsEmpfangTest {
    private fun identity(id: String): EigeneIdentitaet {
        val keys = Krypto.neuesSchluesselpaar()
        return EigeneIdentitaet(id, "Synthetic", Krypto.b64(keys.second), Krypto.b64(keys.first), 0)
    }
    private fun call(server: Server, name: String, self: EigeneIdentitaet, message: JsonObject): JsonObject {
        val method = Server::class.java.getDeclaredMethod(name, EigeneIdentitaet::class.java, JsonObject::class.java, String::class.java)
            .apply { isAccessible = true }
        return try { method.invoke(server, self, message, "127.0.0.1") as JsonObject }
        catch (error: InvocationTargetException) { throw requireNotNull(error.cause) }
    }
    private val transport = Krypto.b64(ByteArray(16) { 17 })
    private fun exchange(server: Server, sender: EigeneIdentitaet, receiver: EigeneIdentitaet, body: JsonObject,
                         transportGueltig: (() -> Boolean)? = null,
                         messageTransportGueltig: (() -> Boolean)? = transportGueltig,
                         afterHandshake: () -> Unit = {}) {
        fun request(name: String, message: JsonObject): JsonObject {
            val guard = if (name == "sitzungAufbauen") transportGueltig else messageTransportGueltig
            if (guard == null) return call(server, name, receiver, message)
            val path = if (name == "sitzungAufbauen") "/magnolie/v2/sitzung" else "/magnolie/v2/nachricht"
            val (status, response) = server.behandeln(path, message, "127.0.0.1", guard)
            if (status != 200) throw BaumFehler("Synthetic guarded receive rejected: $status")
            return response
        }
        val start = Sitzung.baueStart(sender, receiver.kennung, receiver.oeffentlich)
        val answer = request("sitzungAufbauen", start.nachricht)
        val channel = Sitzung.oeffneAntwort(sender, receiver.kennung, receiver.oeffentlich, start, answer)
        try {
            afterHandshake()
            val envelope = Sitzung.baueUmschlag(channel, sender.kennung, receiver.kennung, body, transport)
            assertTrue(Sitzung.pruefeQuittung(channel, envelope, request("sichereNachricht", envelope)))
        } finally { channel.loeschen(); start.ephemerGeheim.fill(0) }
    }

    private open class Handler(var self: EigeneIdentitaet, var peer: Partner) : Server.Handlung {
        val seen = mutableSetOf<String>()
        var received = 0
        var origin: Server.FsEmpfang? = null
        override fun eigen() = self
        override fun istAn() = true
        override fun partner(kennung: String) = peer.takeIf { it.kennung == kennung }
        override fun einladungen() = emptyList<Einladung>()
        override fun dateiPaarungAnnehmen(eigen: EigeneIdentitaet, anfrage: JsonObject, adresse: String): JsonObject = error("unused")
        override fun codeAnfrage(name: String, kennung: String, oeffentlich: String, adresse: String, port: Int) = Unit
        override fun nachricht(vonKennung: String, inhalt: JsonObject) { received++ }
        override fun merkeZaehler(vonKennung: String, zaehler: Long) = Unit
        override fun schonGesehen(vonKennung: String, transportId: String) = transportId in seen
        override fun merkeTransportId(vonKennung: String, transportId: String) { seen += transportId }
        override fun adresseGesehen(vonKennung: String, adresse: String) = Unit
        override fun verarbeiteSichereNachricht(ursprung: Server.FsEmpfang, inhalt: JsonObject, transportId: String): Boolean {
            origin = ursprung
            return super.verarbeiteSichereNachricht(ursprung, inhalt, transportId)
        }
    }

    @Test fun actualCryptoMintsTheExactOriginButNotRetargetableJsonAuthority() {
        val sender = identity("sender"); val receiver = identity("receiver")
        val handler = Handler(receiver, Partner("sender", oeffentlich = sender.oeffentlich, bestaetigt = true))
        val clock = AtomicLong(1_700_000_000)
        val server = Server(handler, 0, clockSeconds = clock::get)
        val body = JsonObject(mapOf("art" to JsonPrimitive("synthetic-audit")))
        try {
            exchange(server, sender, receiver, body)
            val proof = handler.origin!!
            assertEquals(sender.kennung, proof.partnerKennung()); assertEquals(sender.oeffentlich, proof.partnerSchluessel())
            assertEquals(16, Krypto.b64Lesen(proof.sitzungId(), 16).size)
            proof.pruefen(receiver, handler.peer, body, transport)
            assertFalse(handler.verarbeiteSichereNachricht(proof, body, transport)) // Same authenticated replay marker, no new effect.
            assertEquals(1, handler.received)
            assertThrows(BaumFehler::class.java) { proof.pruefen(receiver, handler.peer,
                JsonObject(body + ("injected" to JsonPrimitive(true))), transport) }
            assertThrows(BaumFehler::class.java) { proof.pruefen(receiver, handler.peer, body, Krypto.b64(ByteArray(16))) }
            assertThrows(BaumFehler::class.java) { Server.FsEmpfang(Any()).partnerKennung() }
            assertThrows(BaumFehler::class.java) { Server.FsEmpfang(body).pruefen(receiver, handler.peer, body, transport) }
            handler.peer = handler.peer.copy(oeffentlich = identity("sender").oeffentlich)
            assertThrows(BaumFehler::class.java) { proof.pruefen(receiver, handler.peer, body, transport) }
            handler.peer = handler.peer.copy(oeffentlich = sender.oeffentlich)
            clock.addAndGet(31)
            assertThrows(BaumFehler::class.java) { proof.pruefen(receiver, handler.peer, body, transport) }
            assertEquals(1, handler.received)
        } finally { server.anhalten() }
    }

    @Test fun nativeReceiveGateAcceptsCurrentOriginAndKeepsCosmeticChangesHarmless() {
        nativeGate("normal"); nativeGate("cosmetic")
    }
    @Test fun nativeReceiveGateRejectsAPeerKeyChangeAfterServerCheckBeforeCommit() = nativeGate("peer-key")
    @Test fun nativeReceiveGateRejectsOwnKeyChangeAfterServerCheckBeforeCommit() = nativeGate("own-key")
    @Test fun nativeReceiveGateRejectsRevocationAfterServerCheckBeforeCommit() = nativeGate("unconfirmed")
    @Test fun nativeReceiveGateRejectsExpiryWhileWaitingForActualMutation() = nativeGate("expired")
    @Test fun nativeReceiveGateRejectsValidButRetargetedContentAfterDecryption() = nativeGate("content")
    @Test fun nativeReceiveGateRejectsAnotherReplayTransportIdAfterDecryption() = nativeGate("transport")
    @Test fun unsupportedAppointmentsKeepTheExistingStagedButUnacknowledgedPolicy() = nativeGate("appointment")
    @Test fun serverStopInvalidatesAnAlreadyDecryptedOriginBeforeNativeCommit() = nativeGate("stop")
    @Test fun nativeCancellationInvalidatesAnAlreadyDecryptedOriginWithUnchangedKeys() = nativeGate("cancel")
    @Test fun actualNativeRestoreInvalidatesAnAlreadyDecryptedOriginWithUnchangedKeys() = nativeGate("restore")
    @Test fun nativeLifetimeIsCapturedAtHandshakeNotAfterDecryption() = nativeGate("cancel-handshake")
    @Test fun stoppedServerCannotReuseAnOpenHandshakeSession() = nativeGate("stop-handshake")
    @Test fun lanRevocationAfterDecryptionBlocksActualNativeCommit() = nativeGate("lan-revoke")
    @Test fun lanRegrantDoesNotReviveDecryptedWorkBeforeNativeCommit() = nativeGate("lan-regrant")
    @Test fun lanRevocationInvalidatesAnOpenHandshake() = nativeGate("lan-revoke-handshake")
    @Test fun lanRegrantDoesNotReviveAnOpenHandshake() = nativeGate("lan-regrant-handshake")
    @Test fun lanRevocationLeavesTheIndependentBluetoothReceivePathUsable() = nativeGate("bluetooth-lan-revoke")

    private fun nativeGate(change: String) {
        val dir = kotlin.io.path.createTempDirectory("native-fs-origin-").toFile()
        val context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = dir
        }
        val sender = identity("sender"); val receiver = identity("receiver")
        val ablage = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 83 }, "AES") }
        ablage.setzeBaum(Baumzustand(dienstAn = true, kennung = receiver.kennung, name = receiver.name,
            oeffentlich = receiver.oeffentlich, geheim = receiver.geheim, syncEpoch = "synthetic-epoch",
            partner = listOf(Partner(sender.kennung, oeffentlich = sender.oeffentlich, bestaetigt = true,
                vertraut = true, kontaktSync = true, kontaktSyncFassungen = listOf(1, 2)))))
        val actual = Baumwerk.fuerTest(ablage, context)
        val clock = AtomicLong(1_700_000_000)
        var lanAllowed = true
        val lan = LanTor { lanAllowed }
        val lanToken = lan.marke()
        var messageLanToken = lanToken
        fun revokeLan() {
            lanAllowed = false
            assertFalse(lan.erlaubt())
            if (change.contains("regrant")) {
                lanAllowed = true
                assertTrue(lan.erlaubt())
                assertFalse(lan.aktuell(lanToken))
                messageLanToken = lan.marke()
            }
        }
        val transportGueltig: (() -> Boolean)? = if (change.startsWith("lan-")) ({ lan.aktuell(lanToken) }) else null
        val messageTransportGueltig: (() -> Boolean)? = if (change.startsWith("lan-")) ({ lan.aktuell(messageLanToken) }) else null
        var entered = false
        lateinit var server: Server
        val handler = object : Server.Handlung by actual {
            override fun verarbeiteSichereNachricht(ursprung: Server.FsEmpfang, inhalt: JsonObject, transportId: String): Boolean {
                entered = true // AFTER the real server's crypto/pin checks, BEFORE the actual native transaction.
                when (change) {
                    "peer-key" -> ablage.aendereBaum { state -> state.copy(partner = state.partner.map { it.copy(oeffentlich = identity("sender").oeffentlich) }) }
                    "own-key" -> identity("receiver").let { replacement -> ablage.aendereBaum { it.copy(oeffentlich = replacement.oeffentlich, geheim = replacement.geheim) } }
                    "unconfirmed" -> ablage.aendereBaum { state -> state.copy(partner = state.partner.map { it.copy(bestaetigt = false) }) }
                    "cosmetic" -> ablage.aendereBaum { state -> state.copy(name = "New display", partner = state.partner.map { it.copy(name = "New display") }) }
                    "expired" -> clock.addAndGet(31)
                    "stop" -> server.anhalten()
                    "lan-revoke", "lan-regrant", "bluetooth-lan-revoke" -> revokeLan()
                    "cancel" -> ablage.baumTransporteAbbrechen()
                    "restore" -> {
                        val saved = ablage.journalNutzlast()
                        assertTrue(ablage.journalWiederherstellen(saved.first, saved.second, "synthetic-fs-origin-restore"))
                        assertEquals(receiver.oeffentlich, ablage.baum.value.oeffentlich)
                        assertEquals(sender.oeffentlich, ablage.baum.value.partner.single().oeffentlich)
                    }
                }
                val delivered = if (change == "content") JsonObject(inhalt + ("kontakt" to JsonObject(
                    (inhalt.getValue("kontakt") as JsonObject) + ("vorname" to JsonPrimitive("Retargeted valid payload"))))) else inhalt
                if (change == "content") assertNotNull(KontaktSync.lies(delivered))
                val deliveredTransport = if (change == "transport") Krypto.b64(ByteArray(16) { 18 }) else transportId
                return actual.verarbeiteSichereNachricht(ursprung, delivered, deliveredTransport)
            }
        }
        server = Server(handler, 0, clockSeconds = {
            if (entered) assertTrue("Origin was checked outside the actual native writer gate", Thread.holdsLock(Ablage.SCHREIBSPERRE))
            clock.get()
        })
        val body = if (change == "appointment") JsonObject(mapOf("art" to JsonPrimitive("termin"))) else
            KontaktSync.inhalt(KontaktNachricht("canonical-share", 1, sender.kennung, 1000,
                KontaktDaten(vorname = "Synthetic pending contact"), 2))
        try {
            if (change in setOf("normal", "cosmetic", "bluetooth-lan-revoke")) {
                exchange(server, sender, receiver, body, transportGueltig)
                assertEquals(1, ablage.baum.value.kontaktEingang.size)
                assertEquals(listOf(transport), ablage.baum.value.partner.single().gesehen)
            } else if (change == "appointment") {
                assertThrows(BaumFehler::class.java) { exchange(server, sender, receiver, body) }
                assertEquals(1, ablage.baum.value.eingang.count { it.art == "termin" })
                assertEquals(listOf(transport), ablage.baum.value.partner.single().gesehen)
                assertTrue(ablage.baum.value.kontaktEingang.isEmpty())
            } else {
                assertThrows(BaumFehler::class.java) { exchange(server, sender, receiver, body, transportGueltig, messageTransportGueltig) {
                    if (change == "cancel-handshake") ablage.baumTransporteAbbrechen()
                    if (change == "stop-handshake") server.anhalten()
                    if (change == "lan-revoke-handshake" || change == "lan-regrant-handshake") revokeLan()
                } }
                assertTrue(ablage.baum.value.kontaktEingang.isEmpty())
                assertTrue(ablage.baum.value.partner.single().gesehen.isEmpty())
            }
            assertEquals(change !in setOf("cancel-handshake", "stop-handshake", "lan-revoke-handshake", "lan-regrant-handshake"), entered)
        } finally { server.anhalten(); dir.deleteRecursively() }
    }

    @Test fun deniedLanDispatchNeverReadsNativeIdentityOrRunsAHandler() {
        val sender = identity("sender"); val receiver = identity("receiver")
        val handler = object : Handler(receiver, Partner(sender.kennung, oeffentlich = sender.oeffentlich, bestaetigt = true)) {
            override fun eigen(): EigeneIdentitaet = error("Denied LAN must not dispatch")
        }
        val server = Server(handler, 0)
        try {
            for (path in listOf("/magnolie/v1/paarung", "/magnolie/v2/paarung", "/magnolie/v1/nachricht",
                    "/magnolie/v2/sitzung", "/magnolie/v2/nachricht")) {
                assertEquals(403, server.behandeln(path, JsonObject(emptyMap()), "synthetic") { false }.first)
            }
        } finally { server.anhalten() }
    }

    @Test fun pairingAndLegacyDispatchRecheckRevocationInsideTheNativeWriterGate() {
        for (path in listOf("/magnolie/v1/paarung", "/magnolie/v2/paarung", "/magnolie/v1/nachricht")) {
            val sender = identity("sender"); val receiver = identity("receiver")
            var allowed = true
            var mutations = 0
            val handler = object : Handler(receiver, Partner(sender.kennung, oeffentlich = sender.oeffentlich, bestaetigt = true)) {
                override fun eigen(): EigeneIdentitaet { allowed = false; return self }
                override fun codeAnfrage(name: String, kennung: String, oeffentlich: String, adresse: String, port: Int) { mutations++ }
                override fun dateiPaarungAnnehmen(eigen: EigeneIdentitaet, anfrage: JsonObject, adresse: String): JsonObject {
                    mutations++; return JsonObject(emptyMap())
                }
                override fun legacyNachricht(umschlag: JsonObject, quelle: String): JsonObject {
                    mutations++; return JsonObject(emptyMap())
                }
            }
            val request = JsonObject(mapOf("kennung" to JsonPrimitive(sender.kennung),
                "oeffentlich" to JsonPrimitive(sender.oeffentlich)))
            val server = Server(handler, 0)
            try {
                val (status, _) = server.behandeln(path, request, "synthetic") {
                    if (!allowed) assertTrue(Thread.holdsLock(Ablage.SCHREIBSPERRE))
                    allowed
                }
                assertEquals(403, status)
                assertEquals(0, mutations)
            } finally { server.anhalten() }
        }
    }
}
