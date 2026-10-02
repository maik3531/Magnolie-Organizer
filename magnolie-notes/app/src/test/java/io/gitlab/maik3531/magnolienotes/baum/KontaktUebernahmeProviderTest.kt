package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.CommonDataKinds.Event
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.After
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import javax.crypto.spec.SecretKeySpec
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class KontaktUebernahmeProviderTest {
    private lateinit var provider: KontaktProviderRegressionTest.FixtureProvider
    private lateinit var context: Context
    private lateinit var dir: File
    private lateinit var data: Ablage
    private lateinit var work: Baumwerk
    private lateinit var adapter: AndroidKontakte
    private val key = SecretKeySpec(ByteArray(32) { 23 }, "AES")
    private var snapshots = 0
    private var failSnapshot = false
    private val incoming = KontaktDaten(vorname = "Owned", nachname = "Contact", firma = "Incoming",
        telefone = listOf(KontaktWert("mobil", "+49123")), notiz = "Incoming note", geburtstag = "1980-01-01")
    private val local = incoming.copy(firma = "Local", notiz = "Local note", geburtstag = "1981-02-03")
    private fun load() = Ablage.fuerTest(context) { key }
    @Before fun setup() {
        dir = kotlin.io.path.createTempDirectory("contact-review-").toFile()
        context = object : ContextWrapper(ApplicationProvider.getApplicationContext<Context>()) {
            override fun getFilesDir() = dir
            override fun getApplicationContext(): Context = this
        }
        provider = KontaktProviderRegressionTest.FixtureProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        adapter = AndroidKontakte(context)
        data = load()
        data.setzeBaum(Baumzustand(kennung = "owned-phone", partner = listOf(Partner("peer", bestaetigt = true, vertraut = true, kontaktSync = true)),
            kontaktEingang = listOf(KontaktEingang("peer", "share", 1, "source", 100, incoming, 100))))
        work = Baumwerk.fuerKontaktTest(data, context) { staende, _ ->
            assertTrue(staende.isNotEmpty()); snapshots++
            if (failSnapshot) error("Snapshot unavailable")
        }
    }
    @After fun cleanup() { dir.deleteRecursively() }
    private fun preview() = work.kontaktUebernahmeVorschau("peer", sammel = true)
    private fun choice(p: KontaktUebernahmeVorschau, art: KontaktEntscheidung, fields: Set<String> = emptySet()) =
        listOf(KontaktAuswahl(p.eintraege.single().gruppe.id, art,
            if (art == KontaktEntscheidung.NEU) null else p.eintraege.single().ziele.single().kontakt.rawContactId, fields))

    @Test fun `preview and cancel perform no provider or persistent selection writes`() {
        adapter.anlegen(local)
        val before = provider.rows.map { it.toMap() }; val state = data.baum.value
        val p = preview()
        assertNull(p.eintraege.single().vorauswahl)
        work.kontaktUebernahmeAbbrechen()
        assertThrows(IllegalArgumentException::class.java) { work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.MISCHEN)) }
        assertEquals(before, provider.rows); assertEquals(state, load().baum.value); assertEquals(0, snapshots)
    }

    @Test fun `selected merge preserves notes and commits bindings with consumed input durably`() {
        adapter.anlegen(local)
        val p = preview()
        assertEquals(1, work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.MISCHEN, setOf("firma"))))
        val actual = adapter.alle().single().daten
        assertEquals("Incoming", actual.firma); assertEquals("Local note\n\nIncoming note", actual.notiz)
        assertEquals(local.geburtstag, actual.geburtstag)
        assertEquals(1, snapshots)
        val again = load().baum.value
        assertTrue(again.kontaktEingang.isEmpty()); assertEquals(1, again.kontaktSpuren.size)
        assertEquals(KontaktSync.hash(actual), again.kontaktSpuren.single().inhaltHash)
        assertEquals(0, again.kontaktSpuren.single().inhaltGeaendert)
    }

    @Test fun `keep records rejection without changing provider or requiring snapshot`() {
        adapter.anlegen(local); failSnapshot = true
        val before = provider.rows.map { it.toMap() }; val p = preview()
        work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.BEHALTEN))
        assertEquals(before, provider.rows); assertEquals(0, snapshots)
        assertTrue(load().baum.value.kontaktEingang.isEmpty())
        assertEquals(KontaktSync.hash(incoming), load().baum.value.kontaktAblehnungen.single().inhaltHash)
    }

    @Test fun `snapshot failure stale source changed provider and changed epoch stop before writes`() {
        val saved = adapter.anlegen(local)
        fun fails(change: () -> Unit) {
            val p = preview(); change(); val before = provider.rows.map { it.toMap() }
            assertThrows(Exception::class.java) { work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.MISCHEN)) }
            assertEquals(before, provider.rows); assertEquals(1, data.baum.value.kontaktEingang.size)
        }
        fails { failSnapshot = true }; failSnapshot = false
        fails { data.aendereBaum { it.copy(syncEpoch = "changed") } }
        fails { data.aendereBaum { it.copy(kontaktEingang = it.kontaktEingang.map { k -> k.copy(version = k.version + 1) }) } }
        fails { adapter.mischen(saved.rawContactId, local.copy(firma = "External")) }
    }

    @Test fun `provider version assertions reject a change after final reread`() {
        val saved = adapter.anlegen(local); val expected = adapter.liesRaw(saved.rawContactId)!!
        provider.beforeBatch = { provider.changed(saved.rawContactId) }
        val before = provider.rows.map { it.toMap() }
        assertThrows(android.content.OperationApplicationException::class.java) { adapter.uebernehmen(expected, incoming, true) }
        assertEquals(before, provider.rows)
    }

    @Test fun `replacement retains unrelated provider fields events and operation markers`() {
        val saved = adapter.anlegen(local, "original-operation")
        provider.rows += mutableMapOf(Data._ID to 500L, Data.RAW_CONTACT_ID to saved.rawContactId,
            Data.MIMETYPE to "vnd.test.extra", Data.DATA1 to "Preserve me")
        provider.rows += mutableMapOf(Data._ID to 501L, Data.RAW_CONTACT_ID to saved.rawContactId,
            Data.MIMETYPE to Event.CONTENT_ITEM_TYPE, Event.TYPE to Event.TYPE_OTHER, Event.START_DATE to "2000-04-05")
        val p = preview()
        work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.ERSETZEN))
        assertEquals(incoming, adapter.alle().single().daten)
        assertTrue(provider.rows.any { it[Data.MIMETYPE] == "vnd.test.extra" && it[Data.DATA1] == "Preserve me" })
        assertTrue(provider.rows.any { it[Event.TYPE] == Event.TYPE_OTHER })
        assertEquals(saved.rawContactId, adapter.anlegen(local, "original-operation").rawContactId)
    }

    @Test fun `failed atomic provider batch leaves input and every original field intact`() {
        adapter.anlegen(local)
        val p = preview(); val before = provider.rows.map { it.toMap() }
        provider.failAt = 3
        assertThrows(android.content.OperationApplicationException::class.java) {
            work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.ERSETZEN))
        }
        assertEquals(before, provider.rows); assertEquals(1, load().baum.value.kontaktEingang.size)
        assertTrue(load().baum.value.kontaktSpuren.isEmpty())
    }

    @Test fun `new contact input is consumed only after creation and binding persistence`() {
        val p = preview()
        assertEquals(KontaktEntscheidung.NEU, p.eintraege.single().vorauswahl)
        work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.NEU))
        assertEquals(incoming, adapter.alle().single().daten)
        assertEquals(1, snapshots); assertTrue(load().baum.value.kontaktEingang.isEmpty())
        assertEquals(adapter.alle().single().rawContactId, load().baum.value.kontaktSpuren.single().rawContactId)
    }

    @Test fun `contact picture and replay marker are created in a single provider transaction`() {
        val picture = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        data.aendereBaum { it.copy(kontaktEingang = it.kontaktEingang.map { k -> k.copy(kontakt = k.kontakt.copy(foto = picture)) }) }
        val p = preview(); val before = provider.batches
        work.kontaktUebernahmeBestaetigen(p.id, choice(p, KontaktEntscheidung.NEU))
        assertEquals(1, provider.batches - before)
        assertEquals(picture, adapter.alle().single().daten.foto)
        assertEquals(adapter.alle().single().rawContactId,
            adapter.anlegen(incoming, KontaktEingangslogik.importOperation(p.eintraege.single().gruppe.karten)).rawContactId)
        assertEquals(1, adapter.alle().size)
    }

    @Test fun `closing review stops the remaining batch and preserves the completed receipt`() {
        data.aendereBaum { it.copy(kontaktEingang = it.kontaktEingang +
            it.kontaktEingang.single().copy(freigabeId = "other", kontakt = KontaktDaten(vorname = "Second"))) }
        val p = preview()
        provider.beforeBatch = { work.kontaktUebernahmeAbbrechen() }
        assertThrows(IllegalArgumentException::class.java) {
            work.kontaktUebernahmeBestaetigen(p.id, p.eintraege.map { KontaktAuswahl(it.gruppe.id, KontaktEntscheidung.NEU) })
        }
        assertEquals(1, adapter.alle().size)
        assertEquals(1, load().baum.value.kontaktSpuren.size)
        assertEquals(1, load().baum.value.kontaktEingang.size)
        assertNotEquals(load().baum.value.kontaktSpuren.single().freigabeId, load().baum.value.kontaktEingang.single().freigabeId)
    }
}
