package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.OperationApplicationException
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.CommonDataKinds.Email
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
class KontaktWertListenProviderTest {
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
    private fun email(raw: Long, address: String, type: Int) = context.contentResolver.insert(Data.CONTENT_URI, ContentValues().apply {
        put(Data.RAW_CONTACT_ID, raw); put(Data.MIMETYPE, Email.CONTENT_ITEM_TYPE)
        put(Email.ADDRESS, address); put(Email.TYPE, type)
    })!!

    @Test fun exactEmailUpdatePreservesItsNativeKindLabelDisplayNameAndPrimaryFlags() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", telefone = listOf(KontaktWert("mobil", "111"))))
        val uri = email(saved.rawContactId, "old@example.invalid", Email.TYPE_CUSTOM)
        context.contentResolver.update(uri, ContentValues().apply {
            put(Email.LABEL, "Native email label"); put(Email.DISPLAY_NAME, "Native display")
            put(Data.IS_PRIMARY, 1); put(Data.IS_SUPER_PRIMARY, 1); put(Data.SYNC1, "native-sync")
        }, null, null)
        val expected = contacts.liesRaw(saved.rawContactId)!!
        val actual = contacts.wertListenUebernehmen(expected, emailEintraege = listOf(KontaktWert("sonstige", "new@example.invalid")))
        assertEquals(expected.daten.telefone, actual.daten.telefone)
        assertEquals(listOf(KontaktWert("sonstige", "new@example.invalid")), actual.daten.emailEintraege)
        context.contentResolver.query(uri, arrayOf(Data._ID, Email.ADDRESS, Email.TYPE, Email.LABEL, Email.DISPLAY_NAME,
            Data.IS_PRIMARY, Data.IS_SUPER_PRIMARY, Data.SYNC1), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals(ContentUris.parseId(uri), c.getLong(0))
            assertEquals("new@example.invalid", c.getString(1)); assertEquals(Email.TYPE_CUSTOM, c.getInt(2))
            assertEquals("Native email label", c.getString(3)); assertEquals("Native display", c.getString(4))
            assertEquals(1, c.getInt(5)); assertEquals(1, c.getInt(6)); assertEquals("native-sync", c.getString(7))
        }
    }

    @Test fun phoneAndEmailChangesAreOneAtomicProviderTransaction() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", telefone = listOf(KontaktWert("mobil", "111")),
            emailEintraege = listOf(KontaktWert("arbeit", "old@example.invalid"))))
        val before = contacts.liesRaw(saved.rawContactId)!!
        val phones = listOf(KontaktWert("mobil", "222")); val emails = listOf(KontaktWert("arbeit", "new@example.invalid"))
        provider.failAt = 2
        assertThrows(OperationApplicationException::class.java) { contacts.wertListenUebernehmen(before, phones, emails) }
        assertEquals(before, contacts.liesRaw(saved.rawContactId))
        provider.failAt = -1
        val calls = provider.batchCalls
        val actual = contacts.wertListenUebernehmen(before, phones, emails)
        assertEquals(calls + 1, provider.batchCalls)
        assertEquals(phones, actual.daten.telefone); assertEquals(emails, actual.daten.emailEintraege)
    }

    @Test fun changingAnEmailKindRetainsItsRowMetadataAndClearsOnlyTheOldCustomLabel() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic"))
        val uri = email(saved.rawContactId, "same@example.invalid", Email.TYPE_CUSTOM)
        context.contentResolver.update(uri, ContentValues().apply {
            put(Email.LABEL, "Old custom kind"); put(Email.DISPLAY_NAME, "Unchanged display")
            put(Data.IS_PRIMARY, 1); put(Data.SYNC1, "Keep native sync")
        }, null, null)
        val expected = contacts.liesRaw(saved.rawContactId)!!
        val actual = contacts.wertListenUebernehmen(expected, emailEintraege = listOf(KontaktWert("arbeit", "same@example.invalid")))
        assertEquals(listOf(KontaktWert("arbeit", "same@example.invalid")), actual.daten.emailEintraege)
        context.contentResolver.query(uri, arrayOf(Email.TYPE, Email.LABEL, Email.DISPLAY_NAME, Data.IS_PRIMARY, Data.SYNC1), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals(Email.TYPE_WORK, c.getInt(0)); assertTrue(c.isNull(1))
            assertEquals("Unchanged display", c.getString(2)); assertEquals(1, c.getInt(3)); assertEquals("Keep native sync", c.getString(4))
        }
    }

    @Test fun phoneKindChangeKeepsItsNormalizedNumberUntilTheNumberActuallyChanges() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic"))
        val uri = context.contentResolver.insert(Data.CONTENT_URI, ContentValues().apply {
            put(Data.RAW_CONTACT_ID, saved.rawContactId); put(Data.MIMETYPE, Phone.CONTENT_ITEM_TYPE)
            put(Phone.NUMBER, "111"); put(Phone.TYPE, Phone.TYPE_CUSTOM); put(Phone.LABEL, "Custom phone")
            put(Phone.NORMALIZED_NUMBER, "+111"); put(Data.IS_PRIMARY, 1); put(Data.SYNC1, "Preserve sync")
        })!!
        val actual = contacts.wertListenUebernehmen(contacts.liesRaw(saved.rawContactId)!!, telefone = listOf(KontaktWert("privat", "111")))
        context.contentResolver.query(uri, arrayOf(Phone.TYPE, Phone.LABEL, Phone.NORMALIZED_NUMBER, Data.IS_PRIMARY, Data.SYNC1), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals(Phone.TYPE_HOME, c.getInt(0)); assertTrue(c.isNull(1))
            assertEquals("+111", c.getString(2)); assertEquals(1, c.getInt(3)); assertEquals("Preserve sync", c.getString(4))
        }
        contacts.wertListenUebernehmen(actual, telefone = listOf(KontaktWert("privat", "222")))
        context.contentResolver.query(uri, arrayOf(Phone.NUMBER, Phone.NORMALIZED_NUMBER), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals("222", c.getString(0)); assertTrue(c.isNull(1))
        }
    }

    @Test fun normalizedEmailDuplicatesSurviveUnrelatedEditsAndAmbiguousEditsDoNotPartiallyWrite() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", telefone = listOf(KontaktWert("mobil", "111"))))
        email(saved.rawContactId, "home@example.invalid", Email.TYPE_HOME)
        val duplicate = email(saved.rawContactId, " HOME@example.invalid ", Email.TYPE_CUSTOM)
        context.contentResolver.update(duplicate, ContentValues().apply { put(Email.LABEL, "Preserve me") }, null, null)
        email(saved.rawContactId, "old@example.invalid", Email.TYPE_WORK)
        val before = contacts.liesRaw(saved.rawContactId)!!
        assertEquals(2, before.daten.emailEintraege.size)
        val actual = contacts.wertListenUebernehmen(before, emailEintraege = before.daten.emailEintraege.map {
            if (it.art == "arbeit") it.copy(wert = "new@example.invalid") else it
        })
        context.contentResolver.query(duplicate, arrayOf(Email.ADDRESS, Email.LABEL), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals(" HOME@example.invalid ", c.getString(0)); assertEquals("Preserve me", c.getString(1))
        }
        val calls = provider.batchCalls
        assertThrows(IllegalArgumentException::class.java) {
            contacts.wertListenUebernehmen(actual, listOf(KontaktWert("mobil", "222")), actual.daten.emailEintraege.map {
                if (it.art == "privat") it.copy(wert = "replacement@example.invalid") else it
            })
        }
        assertEquals(calls, provider.batchCalls); assertEquals(actual, contacts.liesRaw(saved.rawContactId))
        val cleared = contacts.wertListenUebernehmen(actual, emailEintraege = emptyList())
        assertTrue(cleared.daten.emailEintraege.isEmpty())
        assertEquals(actual.daten.telefone, cleared.daten.telefone)
        context.contentResolver.query(duplicate, arrayOf(Data._ID), null, null, null)!!.use { assertFalse(it.moveToFirst()) }
    }
}
