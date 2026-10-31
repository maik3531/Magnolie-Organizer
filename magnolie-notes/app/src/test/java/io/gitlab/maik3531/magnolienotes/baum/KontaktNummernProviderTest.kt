package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.OperationApplicationException
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.CommonDataKinds.Phone
import android.provider.ContactsContract.Data
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class KontaktNummernProviderTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktGruppenProviderTest.GroupProvider
    private lateinit var contacts: AndroidKontakte
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        provider = KontaktGruppenProviderTest.GroupProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        contacts = AndroidKontakte(context)
    }
    @After fun cleanup() { provider.shutdown() }
    private fun insert(raw: Long, number: String, type: Int = Phone.TYPE_HOME) = context.contentResolver.insert(Data.CONTENT_URI,
        ContentValues().apply {
            put(Data.RAW_CONTACT_ID, raw); put(Data.MIMETYPE, Phone.CONTENT_ITEM_TYPE)
            put(Phone.NUMBER, number); put(Phone.TYPE, type)
        })!!

    @Test fun replacingNumberKeepsNativeRowLabelPrimaryFlagsAndUnrelatedData() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Arbeit")))
        val other = contacts.anlegen(KontaktDaten(vorname = "Other", telefone = listOf(KontaktWert("privat", "999"))))
        val uri = insert(saved.rawContactId, "111", Phone.TYPE_CUSTOM)
        context.contentResolver.update(uri, ContentValues().apply {
            put(Phone.LABEL, "Personal native label"); put(Data.IS_PRIMARY, 1); put(Data.IS_SUPER_PRIMARY, 1)
            put(Data.SYNC1, "provider-owned"); put(Phone.NORMALIZED_NUMBER, "+111")
        }, null, null)
        val wanted = listOf(KontaktWert("sonstige", "222"))
        val actual = contacts.telefonnummernUebernehmen(contacts.liesRaw(saved.rawContactId)!!, wanted)
        assertEquals(wanted, actual.daten.telefone)
        assertEquals(listOf("Arbeit"), actual.daten.gruppen)
        assertEquals(listOf(KontaktWert("privat", "999")), contacts.liesRaw(other.rawContactId)!!.daten.telefone)
        context.contentResolver.query(uri, arrayOf(Data._ID, Phone.NUMBER, Phone.TYPE, Phone.LABEL,
            Data.IS_PRIMARY, Data.IS_SUPER_PRIMARY, Data.SYNC1, Phone.NORMALIZED_NUMBER), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals(ContentUris.parseId(uri), c.getLong(0))
            assertEquals("222", c.getString(1)); assertEquals(Phone.TYPE_CUSTOM, c.getInt(2))
            assertEquals("Personal native label", c.getString(3)); assertEquals(1, c.getInt(4)); assertEquals(1, c.getInt(5))
            assertEquals("provider-owned", c.getString(6)); assertTrue(c.isNull(7)); assertFalse(c.moveToNext())
        }
    }

    @Test fun removeAddAndRepeatDoNotAppendOldNumbersOrRewriteUnchangedRows() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic",
            telefone = listOf(KontaktWert("privat", "111"), KontaktWert("arbeit", "222"))))
        val wanted = listOf(KontaktWert("arbeit", "222"), KontaktWert("mobil", "333"))
        val actual = contacts.telefonnummernUebernehmen(contacts.liesRaw(saved.rawContactId)!!, wanted)
        assertEquals(KontaktSync.normalisiere(KontaktDaten(telefone = wanted)).telefone.toSet(), actual.daten.telefone.toSet())
        val calls = provider.batchCalls
        assertEquals(actual, contacts.telefonnummernUebernehmen(actual, wanted))
        assertEquals(actual, contacts.telefonnummernUebernehmen(actual, wanted.reversed()))
        assertEquals(calls, provider.batchCalls)
        assertTrue(contacts.telefonnummernUebernehmen(actual, emptyList()).daten.telefone.isEmpty())
    }

    @Test fun staleVersionAndFailedBatchNeverPartiallyReplaceNumbers() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", telefone = listOf(KontaktWert("privat", "111"))))
        val expected = contacts.liesRaw(saved.rawContactId)!!
        provider.beforeBatch = { provider.bump(saved.rawContactId) }
        assertThrows(OperationApplicationException::class.java) {
            contacts.telefonnummernUebernehmen(expected, listOf(KontaktWert("privat", "222")))
        }
        assertEquals(expected.daten.telefone, contacts.liesRaw(saved.rawContactId)!!.daten.telefone)
        provider.failAt = 1
        assertThrows(OperationApplicationException::class.java) {
            contacts.telefonnummernUebernehmen(contacts.liesRaw(saved.rawContactId)!!, listOf(KontaktWert("privat", "222")))
        }
        assertEquals(expected.daten.telefone, contacts.liesRaw(saved.rawContactId)!!.daten.telefone)
    }

    @Test fun normalizedDuplicateRowsKeepTheirLabelsWhenAnotherNumberChanges() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic"))
        val first = insert(saved.rawContactId, "+49 111", Phone.TYPE_HOME)
        val duplicate = insert(saved.rawContactId, "49-111", Phone.TYPE_CUSTOM)
        context.contentResolver.update(duplicate, ContentValues().apply {
            put(Phone.LABEL, "Provider label"); put(Data.IS_PRIMARY, 1); put(Data.SYNC1, "native-metadata")
        }, null, null)
        insert(saved.rawContactId, "222", Phone.TYPE_MOBILE)
        val before = contacts.liesRaw(saved.rawContactId)!!
        assertEquals(2, before.daten.telefone.size)
        val actual = contacts.telefonnummernUebernehmen(before, before.daten.telefone.map {
            if (it.art == "mobil") it.copy(wert = "333") else it
        })
        context.contentResolver.query(duplicate, arrayOf(Phone.NUMBER, Phone.LABEL, Data.IS_PRIMARY, Data.SYNC1), null, null, null)!!.use { c ->
            assertTrue("An unprojected native duplicate was deleted", c.moveToFirst())
            assertEquals("49-111", c.getString(0)); assertEquals("Provider label", c.getString(1))
            assertEquals(1, c.getInt(2)); assertEquals("native-metadata", c.getString(3))
        }
        val calls = provider.batchCalls
        assertThrows(IllegalArgumentException::class.java) {
            contacts.telefonnummernUebernehmen(actual, actual.daten.telefone.map {
                if (it.art == "privat") it.copy(wert = "555") else it
            })
        }
        assertEquals(calls, provider.batchCalls)
        assertEquals(actual, contacts.liesRaw(saved.rawContactId))
        context.contentResolver.query(first, arrayOf(Phone.NUMBER), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals("+49 111", c.getString(0))
        }
    }

    @Test fun ambiguousRowsAndAggregatesAreRejectedBeforeMutation() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic",
            telefone = listOf(KontaktWert("privat", "111"), KontaktWert("privat", "222"))))
        val expected = contacts.liesRaw(saved.rawContactId)!!
        val calls = provider.batchCalls
        assertThrows(IllegalArgumentException::class.java) {
            contacts.telefonnummernUebernehmen(expected, listOf(KontaktWert("privat", "333"), KontaktWert("privat", "444")))
        }
        assertEquals(calls, provider.batchCalls)
        assertEquals(expected.daten.telefone, contacts.liesRaw(saved.rawContactId)!!.daten.telefone)
        val overlay = contacts.anlegen(KontaktDaten(vorname = "Linked"))
        provider.aggregate(overlay.rawContactId, saved.contactId)
        val aggregate = contacts.liesRaw(saved.rawContactId)!!
        assertThrows(IllegalArgumentException::class.java) { contacts.telefonnummernUebernehmen(aggregate, emptyList()) }
        assertEquals(aggregate, contacts.liesRaw(saved.rawContactId))
    }
}
