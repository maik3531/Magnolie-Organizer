package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.OperationApplicationException
import android.content.pm.ProviderInfo
import android.provider.ContactsContract
import android.provider.ContactsContract.Groups
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
class KontaktGruppenTitelTest {
    private lateinit var context: Context
    private lateinit var provider: KontaktGruppenProviderTest.GroupProvider
    private lateinit var contacts: AndroidKontakte
    private lateinit var groups: AndroidKontaktGruppen
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext(); provider = KontaktGruppenProviderTest.GroupProvider()
        provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        contacts = AndroidKontakte(context, android.accounts.Account("owner@example.test", "fixture-provider"))
        groups = AndroidKontaktGruppen(context.contentResolver)
    }
    @After fun cleanup() { provider.shutdown() }

    @Test fun titleChangePreservesGroupSourceIdentityAndAllContactsMemberships() {
        val first = contacts.anlegen(KontaktDaten(vorname = "First", gruppen = listOf("Work")))
        val second = contacts.anlegen(KontaktDaten(vorname = "Second", gruppen = listOf("Work")))
        val id = provider.memberIds(first.rawContactId).single()
        val otherAccount = provider.group("Work", "other@example.test", "fixture-provider")
        context.contentResolver.update(ContentUris.withAppendedId(Groups.CONTENT_URI, id), ContentValues().apply { put(Groups.SOURCE_ID, "stable-provider-group") }, null, null)
        val beforeFirst = provider.memberIds(first.rawContactId); val beforeSecond = provider.memberIds(second.rawContactId)
        val plan = groups.titelPlan(first.rawContactId, "Work", "Arbeit")
        assertEquals(id, groups.titelUebernehmen(plan))
        assertEquals(beforeFirst, provider.memberIds(first.rawContactId)); assertEquals(beforeSecond, provider.memberIds(second.rawContactId))
        assertEquals(listOf("Arbeit"), contacts.liesRaw(first.rawContactId)!!.daten.gruppen)
        assertEquals(listOf("Arbeit"), contacts.liesRaw(second.rawContactId)!!.daten.gruppen)
        context.contentResolver.query(ContentUris.withAppendedId(Groups.CONTENT_URI, id), arrayOf(Groups.TITLE, Groups.SOURCE_ID), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals("Arbeit", c.getString(0)); assertEquals("stable-provider-group", c.getString(1))
        }
        context.contentResolver.query(ContentUris.withAppendedId(Groups.CONTENT_URI, otherAccount), arrayOf(Groups.TITLE), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals("Work", c.getString(0))
        }
    }

    @Test fun existingTargetReadonlyAndSystemGroupsAreNotRenamedOrMerged() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Work")))
        val id = provider.memberIds(saved.rawContactId).single()
        val calls = provider.batchCalls
        val existing = provider.group("Arbeit", "owner@example.test", "fixture-provider")
        assertThrows(Exception::class.java) { groups.titelPlan(saved.rawContactId, "Work", "Arbeit") }
        context.contentResolver.delete(ContentUris.withAppendedId(Groups.CONTENT_URI, existing), null, null)
        context.contentResolver.update(ContentUris.withAppendedId(Groups.CONTENT_URI, id), ContentValues().apply { put(Groups.GROUP_IS_READ_ONLY, 1) }, null, null)
        assertThrows(Exception::class.java) { groups.titelPlan(saved.rawContactId, "Work", "Arbeit") }
        context.contentResolver.update(ContentUris.withAppendedId(Groups.CONTENT_URI, id), ContentValues().apply { put(Groups.GROUP_IS_READ_ONLY, 0); put(Groups.AUTO_ADD, 1) }, null, null)
        assertThrows(Exception::class.java) { groups.titelPlan(saved.rawContactId, "Work", "Arbeit") }
        assertEquals(calls, provider.batchCalls)
    }

    @Test fun concurrentCatalogChangePreventsTheTitleWrite() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Work")))
        val id = provider.memberIds(saved.rawContactId).single()
        val plan = groups.titelPlan(saved.rawContactId, "Work", "Arbeit")
        provider.beforeBatch = { provider.group("New concurrent group", "owner@example.test", "fixture-provider") }
        assertThrows(OperationApplicationException::class.java) { groups.titelUebernehmen(plan) }
        context.contentResolver.query(ContentUris.withAppendedId(Groups.CONTENT_URI, id), arrayOf(Groups.TITLE), null, null, null)!!.use { c ->
            assertTrue(c.moveToFirst()); assertEquals("Work", c.getString(0))
        }
    }
}
