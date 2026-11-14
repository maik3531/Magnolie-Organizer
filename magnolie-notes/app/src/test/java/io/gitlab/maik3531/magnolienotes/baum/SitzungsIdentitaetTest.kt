package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import io.gitlab.maik3531.magnolienotes.daten.Partner
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.lang.reflect.InvocationTargetException

/** Real FS1 crypto and receiver methods, no listening socket/device/user state. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class SitzungsIdentitaetTest {
    private fun identity(id: String): EigeneIdentitaet {
        val keys = Krypto.neuesSchluesselpaar()
        return EigeneIdentitaet(id, "Synthetic", Krypto.b64(keys.second), Krypto.b64(keys.first), 0)
    }
    private fun call(server: Server, name: String, eigen: EigeneIdentitaet, message: JsonObject): JsonObject {
        val method = Server::class.java.getDeclaredMethod(name, EigeneIdentitaet::class.java, JsonObject::class.java, String::class.java)
            .apply { isAccessible = true }
        return try { method.invoke(server, eigen, message, "synthetic-offline") as JsonObject }
        catch (error: InvocationTargetException) { throw requireNotNull(error.cause) }
    }
    private fun probe(change: String) {
        val sender = identity("sender")
        var receiver = identity("receiver")
        var peer = Partner("sender", oeffentlich = sender.oeffentlich, bestaetigt = true)
        var received = 0
        val server = Server(object : Server.Handlung {
            override fun eigen() = receiver
            override fun istAn() = true
            override fun partner(kennung: String) = peer.takeIf { it.kennung == kennung }
            override fun einladungen() = emptyList<Einladung>()
            override fun dateiPaarungAnnehmen(eigen: EigeneIdentitaet, anfrage: JsonObject, adresse: String): JsonObject = error("unused")
            override fun codeAnfrage(name: String, kennung: String, oeffentlich: String, adresse: String, port: Int) = Unit
            override fun nachricht(vonKennung: String, inhalt: JsonObject) { received++ }
            override fun merkeZaehler(vonKennung: String, zaehler: Long) = Unit
            override fun schonGesehen(vonKennung: String, transportId: String) = false
            override fun merkeTransportId(vonKennung: String, transportId: String) = Unit
            override fun adresseGesehen(vonKennung: String, adresse: String) = Unit
        }, 0)
        val start = Sitzung.baueStart(sender, receiver.kennung, receiver.oeffentlich)
        val answer = call(server, "sitzungAufbauen", receiver, start.nachricht)
        val channel = Sitzung.oeffneAntwort(sender, receiver.kennung, receiver.oeffentlich, start, answer)
        val envelope = Sitzung.baueUmschlag(channel, sender.kennung, receiver.kennung,
            JsonObject(mapOf("art" to JsonPrimitive("synthetic-audit"))), Krypto.b64(ByteArray(16) { 9 }))
        try {
            when (change) {
                "peer-key" -> peer = peer.copy(oeffentlich = identity("sender").oeffentlich)
                "own-key" -> receiver = identity("receiver")
                "unconfirmed" -> peer = peer.copy(bestaetigt = false)
                "cosmetic" -> { peer = peer.copy(name = "Changed display"); receiver = receiver.copy(name = "Changed display") }
            }
            if (change in setOf("normal", "cosmetic")) {
                val ack = call(server, "sichereNachricht", receiver, envelope)
                assertTrue(Sitzung.pruefeQuittung(channel, envelope, ack))
                assertEquals(1, received)
            } else {
                assertThrows(BaumFehler::class.java) { call(server, "sichereNachricht", receiver, envelope) }
                assertEquals(0, received)
            }
            assertThrows(BaumFehler::class.java) { call(server, "sichereNachricht", receiver, envelope) }
        } finally { channel.loeschen(); start.ephemerGeheim.fill(0); server.anhalten() }
    }
    @Test fun unchangedPinsRemainUsableAndTheChannelIsOneUse() = probe("normal")
    @Test fun displayChangesDoNotInvalidateCryptographicIdentity() = probe("cosmetic")
    @Test fun changedPeerPinCannotUseTheOldEphemeralChannel() = probe("peer-key")
    @Test fun changedOwnKeysCannotReuseTheOldEphemeralChannel() = probe("own-key")
    @Test fun unconfirmedPeerCannotUseTheOldEphemeralChannel() = probe("unconfirmed")
}
