package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.ContentProvider
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.provider.ContactsContract
import android.provider.ContactsContract.CommonDataKinds.Event
import android.provider.ContactsContract.CommonDataKinds.StructuredName
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class KontaktProviderRegressionTest {
    private lateinit var provider: FixtureProvider
    private lateinit var adapter: AndroidKontakte

    @Before fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        provider = FixtureProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        adapter = AndroidKontakte(context)
    }

    @Test fun `F55 F56 F57 actual adapter creates and rereads partial names and typed yearless events`() {
        for ((given, family) in listOf("Anna Maria" to "", "" to "Van Dame", "Anne-Marie" to "Van der Berg")) {
            val contact = KontaktDaten(vorname = given, nachname = family, geburtstag = "--02-29", jubilaeum = "--06-07")
            val created = adapter.anlegen(contact)
            assertEquals(contact, adapter.liesRaw(created.rawContactId)!!.daten)
            val events = provider.rows.filter { it[Data.RAW_CONTACT_ID] == created.rawContactId &&
                it[Data.MIMETYPE] == Event.CONTENT_ITEM_TYPE }
            assertEquals(2, events.size)
            assertEquals(setOf(Event.TYPE_BIRTHDAY, Event.TYPE_ANNIVERSARY), events.map { it[Event.TYPE] }.toSet())
        }
    }

    @Test fun `F57 updating one event never overwrites the other event type`() {
        val contact = KontaktDaten(nachname = "Van Dame", geburtstag = "--02-29", jubilaeum = "--06-07")
        val created = adapter.anlegen(contact)
        provider.rows.reverse() // Anniversary precedes birthday in the provider result.
        val changed = adapter.mischen(created.rawContactId, contact.copy(geburtstag = "--12-31"))!!
        assertEquals("--12-31", changed.daten.geburtstag)
        assertEquals("--06-07", changed.daten.jubilaeum)
        val again = adapter.mischen(created.rawContactId, contact.copy(geburtstag = "--12-31", jubilaeum = "1604-02-29"))!!
        assertEquals("--12-31", again.daten.geburtstag)
        assertEquals("1604-02-29", again.daten.jubilaeum)
        assertEquals(2, provider.rows.count { it[Data.MIMETYPE] == Event.CONTENT_ITEM_TYPE })
    }

    @Test fun `v2 retains independent display and complete N FN syntax through provider save reload`() {
        val contact = KontaktDaten(vorname = "Maria", nachname = "de la Cruz", anzeigename = "Club contact",
            vcardName = listOf("N;LANGUAGE=en;SORT-AS=\"Cruz:Maria\":de la Cruz;Maria;Elena;Dr.;Jr.", "FN:Club contact", "FN;LANGUAGE=de:Clubkontakt"),
            geburtstag = "--02-29", jubilaeum = "--06-07")
        val created = adapter.anlegen(contact)
        assertEquals(contact, adapter.liesRaw(created.rawContactId)!!.daten)
        repeat(3) { assertEquals(contact, adapter.mischen(created.rawContactId, contact)!!.daten) }
        val row = provider.rows.single { it[Data.MIMETYPE] == StructuredName.CONTENT_ITEM_TYPE }
        assertEquals("Elena", row[StructuredName.MIDDLE_NAME])
        assertEquals("Dr.", row[StructuredName.PREFIX])
        assertEquals("Jr.", row[StructuredName.SUFFIX])
        assertEquals("Club contact", row[StructuredName.DISPLAY_NAME])
        val displayOnly = KontaktDaten(anzeigename = "Independent display", vcardName = listOf("FN:Independent display"))
        val other = adapter.anlegen(displayOnly)
        assertEquals(displayOnly, adapter.liesRaw(other.rawContactId)!!.daten)
    }

    @Test fun `provider synthesized display does not invent missing source FN`() {
        val contact = KontaktDaten(vorname = "Anna", vcardName = listOf("N:;Anna;;;", "FN:"))
        val created = adapter.anlegen(contact)
        provider.rows.single { it[Data.MIMETYPE] == StructuredName.CONTENT_ITEM_TYPE }[StructuredName.DISPLAY_NAME] = "Anna"
        assertEquals(contact, adapter.liesRaw(created.rawContactId)!!.daten)
    }

    /** All operations stay inside this in-memory provider; no system account or contacts are accessed. */
    @Test fun `MIME types retain work email and work postal semantics`() {
        val data = KontaktDaten(vorname = "Test", emailEintraege = listOf(KontaktWert("arbeit", "test@example.invalid")),
            anschriften = listOf(KontaktAnschrift("arbeit", strasse = "Test street")))
        val saved = adapter.anlegen(data)
        assertEquals(data, adapter.liesRaw(saved.rawContactId)!!.daten)
        assertEquals(2, provider.rows.single { it[Data.MIMETYPE] == ContactsContract.CommonDataKinds.Email.CONTENT_ITEM_TYPE }[Data.DATA2])
        assertEquals(2, provider.rows.single { it[Data.MIMETYPE] == ContactsContract.CommonDataKinds.StructuredPostal.CONTENT_ITEM_TYPE }[Data.DATA2])
    }

    @Test fun `create operation is idempotent and restore removes only its bound contact`() {
        val data = KontaktDaten(vorname = "Owned")
        val first = adapter.anlegen(data, "test-create")
        assertEquals(first.rawContactId, adapter.anlegen(data, "test-create").rawContactId)
        val snapshot = adapter.geplanterStand(data, "create", "test-create")
        assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT, adapter.wiederherstellen(snapshot, false, "undo"))
        assertTrue(adapter.alle().isEmpty())
        assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT, adapter.wiederherstellen(snapshot, false, "undo"))
        assertTrue(adapter.alle().isEmpty())
    }

    @Test fun `missing contact restore repeats with the same provider operation binding`() {
        val first = adapter.anlegen(KontaktDaten(vorname = "Restore"))
        val snapshot = adapter.journalStaende(listOf(first.rawContactId), "delete").single()
        assertTrue(adapter.loeschen(first.rawContactId, first.lookupKey))
        assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT, adapter.wiederherstellen(snapshot, false, "restore-once"))
        val raw = adapter.alle().single().rawContactId
        assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT, adapter.wiederherstellen(snapshot, false, "restore-once"))
        assertEquals(raw, adapter.alle().single().rawContactId)
    }

    private class FixtureProvider : ContentProvider() {
        val rows = mutableListOf<MutableMap<String, Any?>>()
        private val rawIds = mutableListOf<Long>()
        private var nextRow = 1L
        private var nextRaw = 1L
        override fun onCreate() = true
        override fun getType(uri: Uri): String? = null
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?,
                           selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
            val columns = requireNotNull(projection)
            val values: List<Map<String, Any?>> = when (uri.pathSegments.first()) {
                "raw_contacts" -> rawIds.map { mapOf(RawContacts._ID to it, RawContacts.CONTACT_ID to it) }
                "contacts" -> rawIds.map { mapOf(ContactsContract.Contacts._ID to it,
                    ContactsContract.Contacts.LOOKUP_KEY to "lookup-$it") }
                else -> rows.filter { row -> selectionArgs == null ||
                    if (selection?.startsWith("${Data.MIMETYPE}=") == true)
                        row[Data.MIMETYPE] == selectionArgs[0] && row[Data.DATA1] == selectionArgs[1]
                    else
                    (row[Data.RAW_CONTACT_ID].toString() == selectionArgs[0] &&
                        (selectionArgs.size < 2 || row[Data.MIMETYPE] == selectionArgs[1]) &&
                        (selectionArgs.size < 3 || row[Event.TYPE].toString() == selectionArgs[2])) }
            }
            return MatrixCursor(columns).apply { values.forEach { row -> addRow(columns.map { row[it] }.toTypedArray()) } }
        }
        override fun insert(uri: Uri, values: ContentValues?): Uri {
            if (uri.pathSegments.first() == "raw_contacts") {
                val id = nextRaw++
                rawIds += id
                return ContentUris.withAppendedId(uri, id)
            }
            val row = requireNotNull(values).valueSet().associate { it.key to it.value }.toMutableMap()
            val id = nextRow++
            row[Data._ID] = id
            rows += row
            return ContentUris.withAppendedId(uri, id)
        }
        override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int {
            val row = rows.single { it[Data._ID] == ContentUris.parseId(uri) }
            requireNotNull(values).valueSet().forEach { row[it.key] = it.value }
            return 1
        }
        override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int {
            val id = if (uri.pathSegments.first() == "raw_contacts") ContentUris.parseId(uri)
                else requireNotNull(selectionArgs)[0].toLong()
            if (uri.pathSegments.first() == "raw_contacts") rawIds.remove(id)
            val count = rows.count { it[Data.RAW_CONTACT_ID] == id }
            rows.removeAll { it[Data.RAW_CONTACT_ID] == id }
            return count
        }
    }
}
