package io.gitlab.maik3531.magnolienotes.baum

import android.app.Application
import android.content.*
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import android.provider.ContactsContract
import android.provider.ContactsContract.Contacts
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.Groups
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.CommonDataKinds.GroupMembership
import androidx.test.core.app.ApplicationProvider
import io.gitlab.maik3531.magnolienotes.daten.Ablage
import io.gitlab.maik3531.magnolienotes.daten.Baumzustand
import io.gitlab.maik3531.magnolienotes.daten.Partner
import io.gitlab.maik3531.magnolienotes.telefon.ContactGroupWrite
import io.gitlab.maik3531.magnolienotes.telefon.ContactGroupWriteAndroid
import kotlinx.serialization.json.*
import org.robolectric.Shadows.shadowOf
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class KontaktGruppenProviderTest {
    private lateinit var context: Context
    private lateinit var provider: GroupProvider
    private lateinit var contacts: AndroidKontakte
    @Before fun setup() {
        context = ApplicationProvider.getApplicationContext()
        provider = GroupProvider(); provider.attachInfo(context, ProviderInfo().apply { authority = ContactsContract.AUTHORITY })
        ShadowContentResolver.registerProviderInternal(ContactsContract.AUTHORITY, provider)
        contacts = AndroidKontakte(context)
    }
    @After fun cleanup() { provider.shutdown() }

    @Test fun addRemoveAndRepeatedSyncWriteActualMembershipsWithoutResurrectingOldGroups() {
        val colleague = provider.group("Kollegen")
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic"))
        val other = contacts.anlegen(KontaktDaten(vorname = "Unrelated"))
        provider.member(saved.rawContactId, colleague); provider.member(other.rawContactId, colleague)
        assertEquals(listOf("Kollegen"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
        assertEquals(listOf("Arbeit", "Kollegen"), contacts.mischen(saved.rawContactId,
            KontaktDaten(gruppen = listOf("Arbeit", "Kollegen")))!!.daten.gruppen)
        repeat(3) {
            assertEquals(listOf("Arbeit"), contacts.mischen(saved.rawContactId, KontaktDaten(gruppen = listOf("Arbeit")))!!.daten.gruppen)
            assertEquals(listOf("Arbeit"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
        }
        assertEquals(listOf("Kollegen"), contacts.liesRaw(other.rawContactId)!!.daten.gruppen)
        assertTrue(provider.groupExists(colleague))
        assertEquals(emptyList<String>(), contacts.mischen(saved.rawContactId, KontaktDaten(gruppen = emptyList()))!!.daten.gruppen)
        assertTrue(provider.groupExists(colleague))
    }

    @Test fun groupsWithTheSameTitleAreBoundToTheRawContactAccount() {
        val foreign = provider.group("Arbeit", "other", "provider")
        val own = provider.group("Arbeit", "owned", "provider")
        val writer = AndroidKontakte(context, android.accounts.Account("owned", "provider"))
        val saved = writer.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Arbeit")))
        assertEquals(setOf(own), provider.memberIds(saved.rawContactId))
        assertFalse(foreign in provider.memberIds(saved.rawContactId))
    }

    @Test fun aggregateRemovalCoversBoundRawContactsAndPreservesAutomaticGroups() {
        val first = contacts.anlegen(KontaktDaten(vorname = "Synthetic"))
        val second = contacts.anlegen(KontaktDaten(vorname = "Linked"))
        provider.aggregate(second.rawContactId, first.contactId)
        val a = provider.group("Kollegen")
        val automatic = provider.group("MY CONTACTS", automatic = true)
        provider.member(first.rawContactId, automatic); provider.member(second.rawContactId, a)
        val actual = contacts.liesRaw(first.rawContactId)!!
        assertEquals(2, actual.rawContactIds.size)
        assertEquals(listOf("Kollegen"), actual.daten.gruppen)
        val saved = contacts.uebernehmen(actual, actual.daten.copy(gruppen = listOf("Arbeit")), false)
        assertEquals(listOf("Arbeit"), saved.daten.gruppen)
        assertTrue(automatic in provider.memberIds(first.rawContactId))
        assertFalse(a in provider.memberIds(second.rawContactId))
    }

    @Test fun providerRaceAndFailedBatchDoNotPartiallyChangeMembershipsOrCreateGroups() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Kollegen")))
        val expected = contacts.liesRaw(saved.rawContactId)!!
        provider.beforeBatch = { provider.bump(saved.rawContactId) }
        assertThrows(OperationApplicationException::class.java) { contacts.uebernehmen(expected, expected.daten.copy(gruppen = listOf("Arbeit")), false) }
        assertEquals(listOf("Kollegen"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
        provider.failAt = 3
        val current = contacts.liesRaw(saved.rawContactId)!!
        assertThrows(OperationApplicationException::class.java) { contacts.uebernehmen(current, current.daten.copy(gruppen = listOf("Arbeit")), false) }
        assertEquals(listOf("Kollegen"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
        assertFalse(provider.hasGroup("Arbeit"))
    }

    @Test fun legacyMissingGroupsNeverClearExistingNativeMemberships() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Kollegen")))
        assertEquals(listOf("Kollegen"), contacts.mischen(saved.rawContactId, KontaktDaten(firma = "Updated"))!!.daten.gruppen)
        assertEquals(listOf("Kollegen"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
    }

    @Test fun unresolvedMembershipsAreUnknownAndRetainedGroupRenameRacesAbortTheWholeWrite() {
        val dangling = contacts.anlegen(KontaktDaten(vorname = "Dangling"))
        provider.member(dangling.rawContactId, 999999)
        assertNull(contacts.liesRaw(dangling.rawContactId)!!.daten.gruppen)
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Work")))
        val expected = contacts.liesRaw(saved.rawContactId)!!
        val group = provider.memberIds(saved.rawContactId).single()
        provider.beforeBatch = {
            provider.update(ContentUris.withAppendedId(Groups.CONTENT_URI, group),
                ContentValues().apply { put(Groups.TITLE, "Renamed concurrently") }, null, null)
        }
        assertThrows(OperationApplicationException::class.java) {
            contacts.uebernehmen(expected, expected.daten.copy(firma = "Must not be written"), false)
        }
        val actual = contacts.liesRaw(saved.rawContactId)!!
        assertEquals("", actual.daten.firma)
        assertEquals(listOf("Renamed concurrently"), actual.daten.gruppen)
    }

    @Test fun actualIncomingReviewCommitsGroupMembershipsBindingsAndConsumedInputTogether() {
        val directory = kotlin.io.path.createTempDirectory("group-contact-review-").toFile()
        val isolated = object : ContextWrapper(context) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir() = directory
        }
        val key = SecretKeySpec(ByteArray(32) { 41 }, "AES")
        fun load() = Ablage.fuerTest(isolated) { key }
        try {
            val data = load()
            data.setzeBaum(Baumzustand(kennung = "owned-phone", partner = listOf(Partner("peer", bestaetigt = true,
                vertraut = true, kontaktSync = true, kontaktSyncFassungen = listOf(1, 2, 3, 4)))))
            var snapshots = 0
            val work = Baumwerk.fuerKontaktTest(data, isolated) { rows, _ -> assertTrue(rows.isNotEmpty()); snapshots++ }
            val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Colleagues")))
            for ((index, groups) in listOf(listOf("Colleagues", "Work"), listOf("Work"), emptyList()).withIndex()) {
                val wire = KontaktSync.inhalt(KontaktNachricht("shared-group-contact", index + 1L, "peer", 1000,
                    KontaktDaten(vorname = "Synthetic", gruppen = groups), 4, 1000))
                work.nachricht("peer", wire)
                val preview = work.kontaktUebernahmeVorschau("peer", sammel = true)
                val choice = KontaktAuswahl(preview.eintraege.single().gruppe.id, KontaktEntscheidung.MISCHEN, saved.rawContactId)
                assertEquals(1, work.kontaktUebernahmeBestaetigen(preview.id, listOf(choice)))
                val actual = contacts.liesRaw(saved.rawContactId)!!
                assertEquals(groups, actual.daten.gruppen)
                val persisted = load().baum.value
                assertTrue(persisted.kontaktEingang.isEmpty())
                assertEquals(KontaktSync.hash(actual.daten), persisted.kontaktSpuren.single().inhaltHash)
                assertEquals(saved.rawContactId, persisted.kontaktSpuren.single().rawContactId)
                assertEquals(index + 1, snapshots)
                work.nachricht("peer", wire)
                assertTrue(load().baum.value.kontaktEingang.isEmpty())
                assertEquals(groups, contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
            }
        } finally { directory.deleteRecursively() }
    }

    private fun groupRequest(action: String, uid: String, token: String = "", groups: List<String> = emptyList()) = buildJsonObject {
        put("version", ContactGroupWrite.VERSION); put("request_id", java.util.UUID.randomUUID().toString())
        put("action", action); put("uid", uid)
        if (action == "apply") { put("token", token); put("groups", JsonArray(groups.map(::JsonPrimitive))) }
    }

    private fun groupWriter(): ContactGroupWriteAndroid {
        shadowOf(context as Application).grantPermissions(android.Manifest.permission.READ_CONTACTS, android.Manifest.permission.WRITE_CONTACTS)
        return ContactGroupWriteAndroid(context)
    }

    @Test fun liveGroupTicketWritesOnlyMembershipsAndReturnsActualNativeReadback() {
        val automatic = provider.group("MY CONTACTS", automatic = true)
        val work = provider.group("Work")
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", firma = "Preserve", notiz = "Preserve note", gruppen = listOf("Coworkers")))
        val other = contacts.anlegen(KontaktDaten(vorname = "Unrelated", gruppen = listOf("Coworkers")))
        provider.member(saved.rawContactId, automatic)
        val before = contacts.liesRaw(saved.rawContactId)!!
        val owner = Any(); val writer = groupWriter()
        val prepared = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        assertEquals("prepared", prepared["state"]!!.jsonPrimitive.content)
        assertEquals(listOf("Coworkers"), ContactGroupWrite.names(prepared, "groups"))
        assertFalse("MY CONTACTS" in ContactGroupWrite.names(prepared, "catalog", 1000))
        val request = groupRequest("apply", saved.lookupKey, prepared["token"]!!.jsonPrimitive.content, listOf("Work"))
        val report = writer.execute(request, owner)
        assertEquals("saved", report["state"]!!.jsonPrimitive.content)
        assertEquals(listOf("Work"), ContactGroupWrite.names(report, "groups"))
        val actual = contacts.liesRaw(saved.rawContactId)!!
        assertEquals(before.daten, actual.daten.copy(gruppen = before.daten.gruppen))
        assertTrue(automatic in provider.memberIds(saved.rawContactId))
        assertTrue(work in provider.memberIds(saved.rawContactId))
        assertEquals(listOf("Coworkers"), contacts.liesRaw(other.rawContactId)!!.daten.gruppen)
        assertThrows(IllegalArgumentException::class.java) { writer.execute(request, owner) }
        val next = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        val custom = writer.execute(groupRequest("apply", saved.lookupKey, next["token"]!!.jsonPrimitive.content, listOf("My own label", "Work")), owner)
        assertEquals(listOf("My own label", "Work"), ContactGroupWrite.names(custom, "groups"))
        assertTrue(provider.hasGroup("My own label"))
        assertTrue(automatic in provider.memberIds(saved.rawContactId))
        assertEquals(listOf("Coworkers"), contacts.liesRaw(other.rawContactId)!!.daten.gruppen)
    }

    @Test fun liveGroupTicketRejectsWrongSessionProviderChangesAndPermissionRevocation() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Coworkers")))
        val owner = Any(); val writer = groupWriter()
        val prepared = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        val request = groupRequest("apply", saved.lookupKey, prepared["token"]!!.jsonPrimitive.content, listOf("Work"))
        assertThrows(IllegalArgumentException::class.java) { writer.execute(request, Any()) }
        shadowOf(context as Application).denyPermissions(android.Manifest.permission.WRITE_CONTACTS)
        assertThrows(IllegalStateException::class.java) { writer.execute(request, owner) }
        shadowOf(context as Application).grantPermissions(android.Manifest.permission.WRITE_CONTACTS)
        provider.bump(saved.rawContactId)
        assertThrows(IllegalArgumentException::class.java) { writer.execute(request, owner) }
        assertEquals(listOf("Coworkers"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
        assertFalse(provider.hasGroup("Work"))
    }

    @Test fun liveGroupTicketExpiresAndCannotReplaceAutomaticMemberships() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Coworkers")))
        provider.group("MY CONTACTS", automatic = true)
        groupWriter()
        var time = 100L
        val writer = ContactGroupWriteAndroid(context) { time }; val owner = Any()
        val prepared = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        val token = prepared["token"]!!.jsonPrimitive.content
        assertThrows(IllegalArgumentException::class.java) { writer.execute(groupRequest("apply", saved.lookupKey, token, listOf("MY CONTACTS")), owner) }
        time += 30_000
        assertThrows(IllegalArgumentException::class.java) { writer.execute(groupRequest("apply", saved.lookupKey, token, emptyList()), owner) }
        assertEquals(listOf("Coworkers"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
    }

    @Test fun liveGroupTicketFailedBatchNeverReportsSavedAndFreshReadCanPrepareAgain() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Coworkers")))
        val writer = groupWriter(); val owner = Any()
        val prepared = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        provider.failAt = 3
        assertThrows(OperationApplicationException::class.java) {
            writer.execute(groupRequest("apply", saved.lookupKey, prepared["token"]!!.jsonPrimitive.content, listOf("Work")), owner)
        }
        assertFalse(provider.hasGroup("Work"))
        assertEquals(listOf("Coworkers"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
        provider.failAt = -1
        val fresh = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        val report = writer.execute(groupRequest("apply", saved.lookupKey, fresh["token"]!!.jsonPrimitive.content, emptyList()), owner)
        assertEquals(emptyList<String>(), ContactGroupWrite.names(report, "groups"))
        assertEquals(emptyList<String>(), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
    }

    @Test fun liveGroupTicketBindsTheCatalogAndRejectsConcurrentRenamesWithoutCreatingDuplicateLabels() {
        val saved = contacts.anlegen(KontaktDaten(vorname = "Synthetic", gruppen = listOf("Coworkers")))
        val target = provider.group("Work")
        val writer = groupWriter(); val owner = Any()
        val prepared = writer.execute(groupRequest("prepare", saved.lookupKey), owner)
        provider.beforeBatch = {
            provider.update(ContentUris.withAppendedId(Groups.CONTENT_URI, target), ContentValues().apply {
                put(Groups.TITLE, "Renamed work label")
            }, null, null)
        }
        assertThrows(OperationApplicationException::class.java) {
            writer.execute(groupRequest("apply", saved.lookupKey, prepared["token"]!!.jsonPrimitive.content, listOf("Work")), owner)
        }
        assertFalse(provider.hasGroup("Work"))
        assertTrue(provider.hasGroup("Renamed work label"))
        assertEquals(listOf("Coworkers"), contacts.liesRaw(saved.rawContactId)!!.daten.gruppen)
    }

    private class GroupProvider : ContentProvider() {
        private lateinit var db: SQLiteDatabase
        var beforeBatch: (() -> Unit)? = null
        var failAt = -1
        override fun onCreate(): Boolean {
            db = SQLiteDatabase.create(null)
            db.execSQL("CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER, account_name TEXT, account_type TEXT, data_set TEXT, sourceid TEXT, version INTEGER DEFAULT 1, deleted INTEGER DEFAULT 0, aggregation_mode INTEGER)")
            db.execSQL("CREATE TABLE contacts (_id INTEGER PRIMARY KEY, lookup TEXT, is_user_profile INTEGER DEFAULT 0, contact_last_updated_timestamp INTEGER DEFAULT 1000)")
            db.execSQL("CREATE TABLE contact_groups (_id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, account_name TEXT, account_type TEXT, data_set TEXT, sourceid TEXT, deleted INTEGER DEFAULT 0, auto_add INTEGER DEFAULT 0, favorites INTEGER DEFAULT 0)")
            db.execSQL("CREATE TABLE data (_id INTEGER PRIMARY KEY AUTOINCREMENT, raw_contact_id INTEGER, mimetype TEXT, " +
                (1..14).joinToString { "data$it TEXT" } + ", data15 BLOB, " + (1..4).joinToString { "sync$it TEXT" } + ", is_primary INTEGER DEFAULT 0, is_super_primary INTEGER DEFAULT 0)")
            return true
        }
        private fun table(uri: Uri) = if (uri.pathSegments.first() == "groups") "contact_groups" else uri.pathSegments.first()
        private fun selection(uri: Uri, where: String?): String? = listOfNotNull(
            uri.lastPathSegment?.toLongOrNull()?.let { "_id=$it" }, where?.let { "($it)" }).joinToString(" AND ").ifBlank { null }
        override fun getType(uri: Uri): String? = if (uri.pathSegments.first() == "groups") Groups.CONTENT_TYPE else null
        override fun query(uri: Uri, projection: Array<out String>?, where: String?, args: Array<out String>?, order: String?): Cursor =
            db.query(table(uri), projection, selection(uri, where), args, null, null, order)
        override fun insert(uri: Uri, values: ContentValues?): Uri {
            val table = table(uri); val copy = ContentValues(requireNotNull(values))
            val id = db.insertOrThrow(table, null, copy)
            if (table == "raw_contacts") {
                db.execSQL("UPDATE raw_contacts SET contact_id=? WHERE _id=?", arrayOf(id, id))
                db.execSQL("INSERT INTO contacts (_id,lookup) VALUES (?,?)", arrayOf(id, "lookup-$id"))
            }
            if (table == "data") bump(copy.getAsLong(Data.RAW_CONTACT_ID))
            return ContentUris.withAppendedId(uri, id)
        }
        override fun update(uri: Uri, values: ContentValues?, where: String?, args: Array<out String>?): Int =
            db.update(table(uri), values, selection(uri, where), args)
        override fun delete(uri: Uri, where: String?, args: Array<out String>?): Int {
            val raws = if (table(uri) == "data") query(uri, arrayOf(Data.RAW_CONTACT_ID), where, args, null).use { c ->
                buildList { while (c.moveToNext()) add(c.getLong(0)) }
            } else emptyList()
            val count = db.delete(table(uri), selection(uri, where), args)
            raws.distinct().forEach(::bump)
            return count
        }
        override fun applyBatch(operations: ArrayList<ContentProviderOperation>): Array<ContentProviderResult> {
            beforeBatch?.also { beforeBatch = null }?.invoke()
            db.beginTransaction()
            try {
                val results = arrayOfNulls<ContentProviderResult>(operations.size)
                operations.forEachIndexed { index, operation ->
                    if (index == failAt) throw OperationApplicationException("Injected group batch failure")
                    results[index] = operation.apply(this, results, index)
                }
                db.setTransactionSuccessful(); return results.map { requireNotNull(it) }.toTypedArray()
            } finally { db.endTransaction() }
        }
        fun bump(raw: Long) { db.execSQL("UPDATE raw_contacts SET version=version+1 WHERE _id=?", arrayOf(raw)) }
        fun group(title: String, name: String? = null, type: String? = null, automatic: Boolean = false): Long = ContentUris.parseId(insert(Groups.CONTENT_URI,
            ContentValues().apply { put(Groups.TITLE, title); put(Groups.ACCOUNT_NAME, name); put(Groups.ACCOUNT_TYPE, type); put(Groups.AUTO_ADD, if (automatic) 1 else 0) }))
        fun member(raw: Long, group: Long) { insert(Data.CONTENT_URI, ContentValues().apply {
            put(Data.RAW_CONTACT_ID, raw); put(Data.MIMETYPE, GroupMembership.CONTENT_ITEM_TYPE); put(GroupMembership.GROUP_ROW_ID, group) }) }
        fun aggregate(raw: Long, contact: Long) { db.execSQL("UPDATE raw_contacts SET contact_id=? WHERE _id=?", arrayOf(contact, raw)) }
        fun memberIds(raw: Long): Set<Long> = query(Data.CONTENT_URI, arrayOf(GroupMembership.GROUP_ROW_ID),
            "${Data.RAW_CONTACT_ID}=? AND ${Data.MIMETYPE}=?", arrayOf(raw.toString(), GroupMembership.CONTENT_ITEM_TYPE), null).use { c ->
                buildSet { while (c.moveToNext()) add(c.getLong(0)) }
            }
        fun groupExists(id: Long) = query(ContentUris.withAppendedId(Groups.CONTENT_URI, id), arrayOf(Groups._ID), null, null, null).use { it.count == 1 }
        fun hasGroup(name: String) = query(Groups.CONTENT_URI, arrayOf(Groups._ID), "${Groups.TITLE}=?", arrayOf(name), null).use { it.count > 0 }
        override fun shutdown() { db.close(); super.shutdown() }
    }
}
