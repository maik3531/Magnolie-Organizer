package io.gitlab.maik3531.magnolienotes.daten

import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.baum.*
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
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
class StabilitaetRegressionTest {
    @Test fun `authenticated note sender cannot extend another objects share`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val ownKeys = Krypto.neuesSchluesselpaar()
        val remoteKeys = Krypto.neuesSchluesselpaar()
        val own = EigeneIdentitaet("phone", "Phone", Krypto.b64(ownKeys.second), Krypto.b64(ownKeys.first), 8737)
        val remote = EigeneIdentitaet("b", "B", Krypto.b64(remoteKeys.second), Krypto.b64(remoteKeys.first), 8737)
        storage.setzeBaum(Baumzustand(kennung = own.kennung, geheim = own.geheim, oeffentlich = own.oeffentlich,
            dienstAn = true, partner = listOf(Partner("b", oeffentlich = remote.oeffentlich, bestaetigt = true, vertraut = true))))
        val note = Notiz("n", titel = "Private", baumFreigabe = Freigabe("share", listOf("a"), listOf("a")), baumVersion = 1)
        storage.setzeNotiz(note)
        val server = Server(werk(storage, context))
        listOf("notiz" to "Forged", "notiz_sync" to "Forged", "notiz" to "Private").forEachIndexed { index, (art, title) ->
            val body = Nutzlast.notizInhalt(note.copy(titel = title, baumVersion = 2), art, "b")
            assertEquals(403, server.behandeln("/magnolie/v1/nachricht",
                Baum1.baue(remote, own.kennung, own.oeffentlich, body, index + 1L), "192.0.2.1").first)
            assertEquals(note, Ablage.fuerTest(context) { key }.notiz("n"))
        }
    }

    @Test fun `task lookup requires the exact authenticated origin binding`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        storage.setzeAufgabe(Aufgabe("local", titel = "Local"))
        storage.setzeAufgabe(Aufgabe("copy", titel = "For A", fremdId = "remote", herkunft = "a"))
        assertNull(storage.aufgabeNachFremdId("local", "b"))
        assertNull(storage.aufgabeNachFremdId("remote", "b"))
        assertEquals("copy", storage.aufgabeNachFremdId("remote", "a")!!.id)
    }

    @Test fun `durable deletion decision reconciles edits before deleting`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val peer = "11111111-1111-4111-8111-111111111111"
        storage.sichereNotiz(Notiz("n", titel = "Before"))
        val record = storage.personalSyncSnapshot(setOf("notes"), 2).single { it.kind == "note" }
        storage.personalSyncStageProposals("run", peer, listOf(PersonalDeletionProposal("run", "proposal", "note", "n",
            clock = record.clock.map { it.copy(counter = it.counter + 1) }, prior_hash = record.hash, deleted_ms = 1000)))
        storage.sichereNotiz(storage.notiz("n")!!.copy(titel = "Changed"))
        assertEquals("conflict", storage.personalSyncDecide(peer, "proposal", "decision", "delete"))
        assertEquals("Changed", Ablage.fuerTest(context) { key }.notiz("n")!!.titel)
    }

    @Test fun `F57 capabilities require authentication and permit version 2 without a reply loop`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val ownKeys = Krypto.neuesSchluesselpaar()
        val remoteKeys = Krypto.neuesSchluesselpaar()
        val own = EigeneIdentitaet("phone", "Phone", Krypto.b64(ownKeys.second), Krypto.b64(ownKeys.first), 8737)
        val remote = EigeneIdentitaet("desktop", "Desktop", Krypto.b64(remoteKeys.second), Krypto.b64(remoteKeys.first), 8737)
        storage.setzeBaum(Baumzustand(kennung = own.kennung, geheim = own.geheim, oeffentlich = own.oeffentlich,
            dienstAn = true, partner = listOf(Partner(remote.kennung, oeffentlich = remote.oeffentlich,
                bestaetigt = true, vertraut = true, kontaktSync = true))))
        val server = Server(werk(storage, context))
        fun deliver(counter: Long, body: kotlinx.serialization.json.JsonObject) = server.behandeln(
            "/magnolie/v1/nachricht", Baum1.baue(remote, own.kennung, own.oeffentlich, body, counter), "192.0.2.2")
        val contact = KontaktSync.inhalt(KontaktNachricht("card", 1, remote.kennung, 1,
            KontaktDaten(nachname = "Van Dame", geburtstag = "--02-29", jubilaeum = "--06-07"), 2))
        assertEquals(403, deliver(1, contact).first)
        assertTrue(storage.baum.value.kontaktEingang.isEmpty())
        val capabilities = kotlinx.serialization.json.JsonObject(KontaktFaehigkeiten.inhalt(false) +
            ("kontakt_import" to kotlinx.serialization.json.JsonArray(listOf(JsonPrimitive(1), JsonPrimitive(2)))))
        val forged = Baum1.baue(remote, own.kennung, own.oeffentlich, capabilities, 2).toMutableMap()
        forged["daten"] = JsonPrimitive(Krypto.b64(ByteArray(16)))
        assertEquals(403, server.behandeln("/magnolie/v1/nachricht",
            kotlinx.serialization.json.JsonObject(forged), "192.0.2.2").first)
        assertEquals(listOf(1), storage.baum.value.partner.single().kontaktSyncFassungen)
        assertEquals(200, deliver(2, capabilities).first)
        assertEquals(1, storage.baum.value.postfach.count { it.art == "kontakt_faehigkeiten" })
        assertEquals(200, deliver(3, kotlinx.serialization.json.JsonObject(capabilities +
            ("antwort" to JsonPrimitive(true)))).first)
        assertEquals(1, storage.baum.value.postfach.count { it.art == "kontakt_faehigkeiten" })
        assertEquals(200, deliver(4, contact).first)
        val restarted = Ablage.fuerTest(context) { key }
        assertEquals(listOf(1, 2), restarted.baum.value.partner.single().kontaktSyncFassungen)
        assertEquals(listOf(1, 2), restarted.baum.value.partner.single().kontaktImportFassungen)
        assertEquals("--06-07", restarted.baum.value.kontaktEingang.single().kontakt.jubilaeum)
        assertEquals("", restarted.baum.value.kontaktEingang.single().kontakt.vorname)
    }

    @Test fun `F28 explicit multiple delegates persist and removal revokes status authorization`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val keys = Krypto.neuesSchluesselpaar()
        storage.setzeBaum(Baumzustand(kennung = "phone", geheim = Krypto.b64(keys.first), oeffentlich = Krypto.b64(keys.second),
            partner = listOf(Partner("a", bestaetigt = true), Partner("b", bestaetigt = true))))
        val flow = werk(storage, context)
        val task = storage.sichereAufgabe(Aufgabe("task", "For two devices"))
        flow.teileAufgabe(task, listOf("a"), sofortSenden = false)
        flow.teileAufgabe(task, listOf("b"), sofortSenden = false)
        assertEquals(setOf("a", "b"), Ablage.fuerTest(context) { key }.aufgabe("task")!!.standPartner.toSet())
        flow.entfernen("a")
        assertEquals(listOf("b"), Ablage.fuerTest(context) { key }.aufgabe("task")!!.standPartner)
        assertTrue(storage.baum.value.postfach.none { it.an == "a" })
    }

    @Test fun `F20 draft and attachments survive storage recreation without touching the saved note`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        storage.sichereNotiz(Notiz("n", text = "Saved before editing"))
        val draft = Notiz("n", text = "Unsaved draft", anhaenge = listOf(
            Anhang("a", "large.png", daten = "data:image/png;base64," + "A".repeat(400_000))))
        storage.setzeNotizEntwurf(draft)
        storage.sichereEntwurf()
        val bytes = File(context.filesDir, "entwurf.json").readBytes()
        assertTrue(DatenDateiKrypto({ key }).istVerschluesselt(bytes))
        assertFalse(bytes.toString(Charsets.UTF_8).contains("Unsaved draft"))
        val recreated = Ablage.fuerTest(context) { key }
        assertEquals(draft, recreated.entwurf.value.notiz)
        assertEquals("Saved before editing", recreated.notiz("n")!!.text)
        val expected = recreated.entwurf.value
        recreated.sichereNotiz(draft)
        assertTrue(recreated.beendeEntwurf(expected))
        val restarted = Ablage.fuerTest(context) { key }
        assertEquals(EditorEntwurf(), restarted.entwurf.value)
        assertEquals(draft.text, restarted.notiz("n")!!.text)
        assertEquals(draft.anhaenge, restarted.notiz("n")!!.anhaenge)
    }

    @Test fun `F20 stale completion cannot discard a newer draft and task minutes survive`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        storage.setzeAufgabenEntwurf(Aufgabe("a", titel = "Old", erinnerungsMinute = 517))
        val old = storage.entwurf.value
        storage.setzeAufgabenEntwurf(old.aufgabe!!.copy(titel = "New"))
        assertFalse(storage.beendeEntwurf(old))
        storage.sichereEntwurf()
        assertEquals("New", Ablage.fuerTest(context) { key }.entwurf.value.aufgabe!!.titel)
        assertEquals(517, Ablage.fuerTest(context) { key }.entwurf.value.aufgabe!!.erinnerungsMinute)
    }

    @Test fun `F20 failed save retains the encrypted draft`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        var fail = false
        val storage = Ablage.fuerTest(context) { if (fail) throw IOException("injected failure") else key }
        storage.setzeNotizEntwurf(Notiz("n", text = "Keep this draft"))
        storage.sichereEntwurf()
        val expected = storage.entwurf.value
        fail = true
        assertThrows(IOException::class.java) {
            storage.sichereNotiz(expected.notiz!!)
            storage.beendeEntwurf(expected)
        }
        assertEquals(expected, storage.entwurf.value)
        assertEquals(expected, Ablage.fuerTest(context) { key }.entwurf.value)
    }

    private fun isolated(test: (Context) -> Unit) {
        val directory = Files.createTempDirectory("android-stability-").toFile()
        val base = ApplicationProvider.getApplicationContext<Context>()
        val context = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        try { test(context) } finally { directory.deleteRecursively() }
    }

    private fun werk(storage: Ablage, context: Context): Baumwerk =
        Baumwerk.fuerTest(storage, context)

    @Test fun `F01 code request cannot rewrite confirmed peer or its durable state`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val keys = Krypto.neuesSchluesselpaar()
        val peerKeys = Krypto.neuesSchluesselpaar()
        val before = Baumzustand(kennung = "phone", geheim = Krypto.b64(keys.first),
            oeffentlich = Krypto.b64(keys.second), dienstAn = true,
            partner = listOf(Partner("desktop", oeffentlich = Krypto.b64(peerKeys.second),
                adresse = "192.0.2.1", bestaetigt = true, vertraut = true, protokoll = "baum-fs1")))
        storage.setzeBaum(before)
        val server = Server(werk(storage, context))
        server.behandeln("/magnolie/v1/paarung", buildJsonObject {
            put("kennung", JsonPrimitive("desktop")); put("name", JsonPrimitive("Replacement"))
            put("oeffentlich", JsonPrimitive(Krypto.b64(peerKeys.second)))
            put("port", JsonPrimitive(12345))
        }, "192.0.2.99")
        assertEquals(before, storage.baum.value)
        assertEquals(before, Ablage.fuerTest(context) { key }.baum.value)
    }

    @Test fun `F28 authenticated unrelated sender cannot complete another peers task`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val keys = Krypto.neuesSchluesselpaar()
        val remoteKeys = Krypto.neuesSchluesselpaar()
        val identity = EigeneIdentitaet("phone", "Phone", Krypto.b64(keys.second), Krypto.b64(keys.first), 8737)
        val remote = EigeneIdentitaet("peer-a", "A", Krypto.b64(remoteKeys.second), Krypto.b64(remoteKeys.first), 8737)
        storage.setzeBaum(Baumzustand(kennung = identity.kennung, geheim = identity.geheim,
            oeffentlich = identity.oeffentlich, dienstAn = true,
            partner = listOf(Partner(remote.kennung, oeffentlich = remote.oeffentlich, bestaetigt = true))))
        storage.setzeAufgabe(Aufgabe("task", titel = "For B", delegiertAn = "peer-b"))
        val server = Server(werk(storage, context))
        fun deliver(counter: Long) = server.behandeln("/magnolie/v1/nachricht",
            Baum1.baue(remote, identity.kennung, identity.oeffentlich, buildJsonObject {
                put("art", JsonPrimitive("stand")); put("id", JsonPrimitive("task"))
                put("erledigt", JsonPrimitive(true)); put("geaendert", JsonPrimitive(100L))
            }, counter), "192.0.2.2")
        assertEquals(403, deliver(1).first)
        assertFalse(storage.aufgabe("task")!!.erledigt)
        storage.setzeAufgabe(storage.aufgabe("task")!!.copy(delegiertAn = "peer-a"))
        assertEquals(200, deliver(2).first)
        assertTrue(Ablage.fuerTest(context) { key }.aufgabe("task")!!.erledigt)
    }

    @Test fun `F29 failed write keeps published and durable Baum unchanged`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        var fail = false
        val storage = Ablage.fuerTest(context) { if (fail) throw IOException("injected write failure") else key }
        val before = Baumzustand(name = "Before")
        storage.setzeBaum(before)
        fail = true
        assertThrows(IOException::class.java) { storage.aendereBaum { it.copy(name = "Uncommitted") } }
        assertEquals(before, storage.baum.value)
        assertThrows(IOException::class.java) { storage.setzeBaum(before.copy(name = "Uncommitted again")) }
        assertEquals(before, storage.baum.value)
        assertEquals(before, Ablage.fuerTest(context) { key }.baum.value)
    }

    @Test fun `F05 local content is reconciled before incoming batch under storage lock`() = isolated { context ->
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val storage = Ablage.fuerTest(context) { key }
        val baseline = PersonalSync.reconcile(Bestand(notizen = listOf(Notiz("n", text = "Base"))), setOf("notes"))
        storage.personalSyncApplyOnce(baseline.second, "initial")
        val desktop = PersonalSync.apply(Bestand(), baseline.second).bestand
        val remote = PersonalSync.reconcile(desktop.copy(notizen = listOf(
            desktop.notizen.single().copy(text = "Desktop change"))), setOf("notes")).second
        storage.sichereNotiz(storage.notiz("n")!!.copy(text = "Phone change"))
        val result = storage.personalSyncApplyOnce(remote, "changed")!!
        assertEquals(1, result.conflicts)
        assertEquals(setOf("Phone change", "Desktop change"), storage.notizen().map { it.text }.toSet())
        assertNull(storage.personalSyncApplyOnce(remote, "changed"))
        assertEquals(2, Ablage.fuerTest(context) { key }.notizen().size)
    }
}
