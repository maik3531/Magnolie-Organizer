package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.ContentProviderOperation
import android.content.ContentValues
import android.content.Context
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.journal.KontaktZeile
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], application = Application::class)
class KontaktJournalSyncTest {
    private lateinit var adapter: AndroidKontakte
    private val columns = listOf(Data.SYNC1, Data.SYNC2, Data.SYNC3, Data.SYNC4)
    private val expected = listOf("data-one", "", null, "data-four")
    @Before fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val provider = SyncProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        columns.forEachIndexed { index, column -> provider.row[column] = expected[index] }
        listOf(RawContacts.SYNC1, RawContacts.SYNC2, RawContacts.SYNC3, RawContacts.SYNC4).forEach {
            provider.row[it] = "wrong-raw-column"
            provider.raw[it] = "different-raw-metadata"
        }
        provider.row[Data.IS_PRIMARY] = 1
        provider.row[Data.IS_SUPER_PRIMARY] = 1
        adapter = AndroidKontakte(context)
    }

    @Test fun capturesActualDataSyncSlotsNotJoinedRawContactColumns() {
        val frame = adapter.journalStaende(listOf(7L), "test").single()
        assertEquals(expected, frame.rows.single().sync)
        assertTrue(frame.rows.single().primary)
        assertTrue(frame.rows.single().superPrimary)
    }

    @Test fun restoreWritesOnlyTheFourSdkDataSyncColumnsIncludingNullAndEmpty() {
        val frame = adapter.journalStaende(listOf(7L), "test").single()
            .copy(rows = listOf(KontaktZeile("vnd.synthetic.foreign", sync = expected)))
        var calls = 0
        val result = AndroidKontakte.wiederherstellenMitGrenzen(frame, true, { adapter.liesRaw(7L) }) { ops ->
            calls++
            val field = ContentProviderOperation::class.java.getDeclaredField("mValues").apply { isAccessible = true }
            val stored = field.get(ops.last())
            val values: Map<String, Any?> = when (stored) {
                is ContentValues -> stored.valueSet().associate { it.key to it.value }
                is Map<*, *> -> stored.entries.associate { it.key as String to it.value }
                else -> error("Unknown operation values")
            }
            columns.forEachIndexed { index, column ->
                assertTrue("Missing $column", values.containsKey(column))
                assertEquals(expected[index], values[column])
            }
            assertFalse(values.containsKey(RawContacts.SYNC1))
            assertEquals(7L, (values[Data.RAW_CONTACT_ID] as Number).toLong())
        }
        assertEquals(AndroidKontakte.RestoreErgebnis.WIEDERHERGESTELLT, result)
        assertEquals(1, calls)
    }

    @Test fun legacyUnknownProvenanceIsReadableButNeverMutatesEvenWithConflictConfirmation() {
        val legacy = kotlinx.serialization.json.Json.decodeFromString(
            io.gitlab.maik3531.magnolienotes.journal.KontaktRohstand.serializer(),
            """{"rawContactId":7,"rows":[{"mime":"vnd.synthetic.foreign","sync":[null,null,null,null]}]}""")
        assertEquals(0, legacy.syncSpaltenVersion)
        for (existing in listOf(true, false)) {
            var called = false
            val result = AndroidKontakte.wiederherstellenMitGrenzen(legacy, true,
                { if (existing) adapter.liesRaw(7L) else null }) { called = true }
            assertEquals(AndroidKontakte.RestoreErgebnis.NICHT_SCHREIBBAR, result)
            assertFalse(called)
        }
    }

    private class SyncProvider : android.content.ContentProvider() {
        val raw = mutableMapOf<String, Any?>(RawContacts._ID to 7L, RawContacts.CONTACT_ID to 11L,
            RawContacts.VERSION to 1L, RawContacts.DELETED to 0, RawContacts.AGGREGATION_MODE to 0)
        val row = mutableMapOf<String, Any?>(Data._ID to 23L, Data.RAW_CONTACT_ID to 7L,
            Data.MIMETYPE to ContactsContract.CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE,
            ContactsContract.CommonDataKinds.StructuredName.GIVEN_NAME to "Synthetic")
        override fun onCreate() = true
        override fun getType(uri: android.net.Uri): String? = null
        override fun query(uri: android.net.Uri, projection: Array<out String>?, selection: String?,
                           args: Array<out String>?, sort: String?): android.database.Cursor {
            val values = when (uri.pathSegments.first()) {
                "raw_contacts" -> raw
                "data" -> row
                "contacts" -> mapOf(ContactsContract.Contacts._ID to 11L,
                    ContactsContract.Contacts.LOOKUP_KEY to "synthetic-lookup",
                    ContactsContract.Contacts.IS_USER_PROFILE to 0,
                    ContactsContract.Contacts.CONTACT_LAST_UPDATED_TIMESTAMP to 1L)
                else -> error("Unexpected synthetic query")
            }
            val columns = requireNotNull(projection)
            return android.database.MatrixCursor(columns).apply { addRow(columns.map { values[it] }.toTypedArray()) }
        }
        override fun insert(uri: android.net.Uri, values: ContentValues?): android.net.Uri? = error("No live mutation")
        override fun delete(uri: android.net.Uri, selection: String?, args: Array<out String>?): Int = error("No live mutation")
        override fun update(uri: android.net.Uri, values: ContentValues?, selection: String?, args: Array<out String>?): Int = error("No live mutation")
    }
}
