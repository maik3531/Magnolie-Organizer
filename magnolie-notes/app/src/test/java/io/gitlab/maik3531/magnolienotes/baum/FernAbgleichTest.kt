package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import javax.crypto.spec.SecretKeySpec

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class FernAbgleichTest {
    private fun identity(id: String): EigeneIdentitaet {
        val keys = Krypto.neuesSchluesselpaar()
        return EigeneIdentitaet(id, id, Krypto.b64(keys.second), Krypto.b64(keys.first), 8737)
    }
    private fun peer(id: EigeneIdentitaet) = Partner(id.kennung, oeffentlich = id.oeffentlich,
        fernAdresse = "owned.example.invalid", bestaetigt = true, vertraut = true)

    @Test fun signedHandshakeAuthenticatesOnlyThePinnedPeerAndSendsNoBookContent() {
        val own = identity("own"); val remote = identity("remote")
        var calls = 0; var closed = false
        val transport = object : Transport {
            override val bezeichnung = "owned fixture"
            override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
                calls++
                assertEquals("/magnolie/v2/sitzung", pfad)
                assertEquals(1500, zeitgrenzeMs)
                val answer = Sitzung.baueAntwort(remote, own.kennung, own.oeffentlich, nutzlast)
                return answer.nachricht.also { answer.sitzung.loeschen() }
            }
            override fun schliessen() { closed = true }
        }
        val proof = FernAbgleich.pruefen(own, peer(remote), "epoch", { 100L }, { transport })
        assertNotNull(proof); assertEquals(1, calls); assertTrue(closed)
        assertEquals(30_000_000_100L, proof!!.gueltigBis)
    }

    @Test fun forgedHandshakeAndOfflineRouteNeverBecomeAvailable() {
        val own = identity("own"); val remote = identity("remote"); val impostor = identity("remote")
        for (offline in listOf(false, true)) {
            var closed = false
            val transport = object : Transport {
                override val bezeichnung = "unavailable fixture"
                override fun anfrage(pfad: String, nutzlast: JsonObject, zeitgrenzeMs: Int): JsonObject {
                    if (offline) throw java.net.ConnectException("offline")
                    val answer = Sitzung.baueAntwort(impostor, own.kennung, own.oeffentlich, nutzlast)
                    return answer.nachricht.also { answer.sitzung.loeschen() }
                }
                override fun schliessen() { closed = true }
            }
            assertNull(FernAbgleich.pruefen(own, peer(remote), "epoch", transport = { transport }))
            assertTrue(closed)
        }
    }

    @Test fun untrustedUnconfirmedAndUnconfiguredPeersAreNotProbed() {
        val own = identity("own"); val target = peer(identity("remote"))
        for (invalid in listOf(target.copy(vertraut = false), target.copy(bestaetigt = false),
            target.copy(fernAdresse = ""), target.copy(protokoll = "baum-1"))) {
            assertNull(FernAbgleich.pruefen(own, invalid, "epoch", transport = { error("must not open a route") }))
        }
    }

    @Test fun evidenceExpiresAndCannotSurviveKeyEndpointTrustOrRestoreChanges() {
        val target = peer(identity("remote"))
        val baum = Baumzustand(kennung = "own", oeffentlich = "own-key", syncEpoch = "epoch", partner = listOf(target))
        val proof = FernAbgleichVerbindung(target, "own", "own-key", "epoch", 100)
        assertTrue(proof.passt(baum, 99)); assertFalse(proof.passt(baum, 100))
        for (changed in listOf(baum.copy(syncEpoch = "restored"), baum.copy(dienstAn = false),
            baum.copy(oeffentlich = "other"), baum.copy(partner = emptyList()),
            *listOf(target.copy(oeffentlich = "other"), target.copy(fernPort = 9999),
                target.copy(fernAdresse = "other.invalid"), target.copy(vertraut = false))
                .map { baum.copy(partner = listOf(it)) }.toTypedArray())) {
            assertFalse(proof.passt(changed, 99))
        }
        assertTrue(proof.passt(baum.copy(partner = listOf(target.copy(zuletzt = 1234, zaehlerRein = 4))), 99))
    }

    private fun fixture(): Triple<Ablage, Baumwerk, FernAbgleichVerbindung> {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.filesDir.deleteRecursively(); context.filesDir.mkdirs()
        val storage = Ablage.fuerTest(context) { SecretKeySpec(ByteArray(32) { 37 }, "AES") }
        val own = identity("own"); val target = peer(identity("remote"))
        storage.setzeBaum(Baumzustand(kennung = own.kennung, name = own.name, geheim = own.geheim,
            oeffentlich = own.oeffentlich, syncEpoch = "epoch", partner = listOf(target)))
        val work = Baumwerk.fuerFernAbgleichTest(storage, context) { true }
        val proof = FernAbgleichVerbindung(target, own.kennung, own.oeffentlich, "epoch", System.nanoTime() + 30_000_000_000L)
        return Triple(storage, work, proof)
    }

    @Test fun selectedNoteQueuesOnlyExistingRecipientsAndNeverRequestsAFullRun() {
        val (storage, work, proof) = fixture()
        storage.setzeNotiz(Notiz("chosen", "Chosen", baumFreigabe = Freigabe("share", partner = listOf("remote"))))
        storage.setzeNotiz(Notiz("private", "Private"))
        storage.setzeAufgabe(Aufgabe("unrelated", "Unrelated"))
        assertEquals(1, work.fernEinzelAbgleichen("note", "chosen", listOf(proof), false))
        val outbox = storage.baum.value.postfach
        assertTrue(outbox.isNotEmpty())
        assertTrue(outbox.all { it.an == "remote" && it.art == "notiz_sync" && !it.inhalt.contains("Private") })
        val before = storage.baum.value
        assertEquals(0, work.fernEinzelAbgleichen("note", "private", listOf(proof), false))
        assertEquals(before, storage.baum.value)
        assertNull(storage.notiz("private")!!.baumFreigabe)
        assertEquals(listOf("remote"), storage.notiz("chosen")!!.baumFreigabe!!.partner)
    }

    @Test fun disconnectedAndChangedRoutesDoNothingEvenWithAnEarlierUiProof() {
        val (storage, work, proof) = fixture()
        storage.setzeNotiz(Notiz("chosen", baumFreigabe = Freigabe("share", partner = listOf("remote"))))
        val context = ApplicationProvider.getApplicationContext<Context>()
        val offline = Baumwerk.fuerFernAbgleichTest(storage, context) { false }
        val before = storage.bestand.value
        assertEquals(0, offline.fernEinzelAbgleichen("note", "chosen", listOf(proof), false))
        storage.aendereBaum { it.copy(partner = it.partner.map { peer -> peer.copy(vertraut = false) }) }
        assertEquals(0, work.fernEinzelAbgleichen("note", "chosen", listOf(proof), false))
        assertEquals(before, storage.bestand.value)
        assertTrue(storage.baum.value.postfach.isEmpty())
    }

    @Test fun anAlreadySharedForeignNoteKeepsItsTreeOriginAndNeverBecomesPersonal() {
        val (storage, work, proof) = fixture()
        storage.setzeNotiz(Notiz("from-tree", "From tree", baumQuelle = "origin",
            baumFreigabe = Freigabe("existing-share", partner = listOf("remote"))))
        assertFalse(PersonalSync.ownNote(storage.notiz("from-tree")!!))
        assertEquals(1, work.fernEinzelAbgleichen("note", "from-tree", listOf(proof), false))
        val after = storage.notiz("from-tree")!!
        assertEquals("origin", after.baumQuelle)
        assertFalse(PersonalSync.ownNote(after))
        assertTrue(storage.baum.value.postfach.isNotEmpty())
        assertTrue(storage.baum.value.postfach.all { it.an == "remote" && it.art == "notiz_sync" })
    }

    @Test fun taskSyncKeepsDelegationAndDoesNotResendForeignOrUnsharedTasks() {
        val (storage, work, proof) = fixture()
        val task = Aufgabe("chosen", "Chosen", standPartner = listOf("remote"), delegiertAn = "other")
        storage.setzeAufgabe(task)
        storage.setzeAufgabe(Aufgabe("private", "Private"))
        storage.setzeAufgabe(Aufgabe("foreign", "Foreign", vonZweig = "origin", herkunft = "origin",
            fremdId = "remote-task", standPartner = listOf("remote")))
        val beforeTask = storage.aufgabe("chosen")
        assertEquals(1, work.fernEinzelAbgleichen("task", "chosen", listOf(proof), false))
        assertEquals(beforeTask, storage.aufgabe("chosen"))
        val before = storage.baum.value
        assertEquals(0, work.fernEinzelAbgleichen("task", "private", listOf(proof), false))
        assertEquals(0, work.fernEinzelAbgleichen("task", "foreign", listOf(proof), false))
        assertEquals(before, storage.baum.value)
        assertTrue(before.postfach.all { it.an == "remote" && it.art == "aufgabe" && !it.inhalt.contains("Private") })
    }
}
