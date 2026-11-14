package io.gitlab.maik3531.magnolienotes.baum

import android.Manifest
import android.content.ContentProviderOperation
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.provider.ContactsContract
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.ProviderStatus

/** Native observation only, never consent. Not serialized or accepted from a peer.
 * The full-return controller must separately require its native durable source
 * approval, protect the original and verify readback/result persistence.
 */
internal class KontaktOriginalBindung private constructor(
    private val context: Context,
    private val original: Beobachtung
) {
    data class Quelle(val kontoName: String?, val kontoTyp: String?, val datenSatz: String?)

    private data class Rohstand(val id: Long, val kontaktId: Long, val version: Long,
        val quelle: Quelle, val sourceId: String?)
    private data class Beobachtung(val kontakt: AndroidKontakt, val roh: Rohstand, val zeilen: List<Long>, val datenbank: Long)

    val quelle: Quelle get() = original.roh.quelle
    val rawContactId: Long get() = original.roh.id
    val lookupKey: String get() = original.kontakt.lookupKey
    val sourceId: String? get() = original.roh.sourceId
    val datenbankErstellt: Long get() = original.datenbank

    /** A fresh observation, not the privately retained preparation snapshot. */
    fun aktuell(): AndroidKontakt = beobachte(context, lookupKey).also {
        require(it == original) { "contact_original_binding_changed" }
    }.kontakt

    /** Include these assertions in the SAME batch as the eventual targeted write.
     * A successful preflight alone is not an atomic provider revision check.
     */
    fun pruefungen(): List<ContentProviderOperation> {
        aktuell()
        val roh = original.roh
        val raw = ContentProviderOperation.newAssertQuery(ContentUris.withAppendedId(RawContacts.CONTENT_URI, roh.id))
            .withValue(RawContacts.CONTACT_ID, roh.kontaktId)
            .withValue(RawContacts.VERSION, roh.version)
            .withValue(RawContacts.ACCOUNT_NAME, roh.quelle.kontoName)
            .withValue(RawContacts.ACCOUNT_TYPE, roh.quelle.kontoTyp)
            .withValue(RawContacts.DATA_SET, roh.quelle.datenSatz)
            .withValue(RawContacts.SOURCE_ID, roh.sourceId)
            .withValue(RawContacts.DELETED, 0)
            .withValue(RawContacts.RAW_CONTACT_IS_READ_ONLY, 0)
            .withExpectedCount(1).build()
        val contact = ContentProviderOperation.newAssertQuery(ContentUris.withAppendedId(ContactsContract.Contacts.CONTENT_URI, roh.kontaktId))
            .withValue(ContactsContract.Contacts.LOOKUP_KEY, lookupKey)
            .withValue(ContactsContract.Contacts.IS_USER_PROFILE, 0).withExpectedCount(1).build()
        val membership = ContentProviderOperation.newAssertQuery(RawContacts.CONTENT_URI)
            .withSelection("${RawContacts.CONTACT_ID}=? AND ${RawContacts.DELETED}=0", arrayOf(roh.kontaktId.toString()))
            .withValue(RawContacts._ID, roh.id).withExpectedCount(1).build()
        val generation = ContentProviderOperation.newAssertQuery(ProviderStatus.CONTENT_URI)
            .withValue(ProviderStatus.STATUS, ProviderStatus.STATUS_NORMAL)
            .withValue(ProviderStatus.DATABASE_CREATION_TIMESTAMP, original.datenbank).withExpectedCount(1).build()
        return listOf(generation, raw, contact, membership) + original.zeilen.map { id ->
            ContentProviderOperation.newAssertQuery(ContentUris.withAppendedId(Data.CONTENT_URI, id))
                .withValue(Data.RAW_CONTACT_ID, roh.id).withValue(Data.IS_READ_ONLY, 0)
                .withExpectedCount(1).build()
        }
    }

    internal fun resolver() = context.contentResolver

    internal fun ruecklesenNachSchreiben(): AndroidKontakt {
        berechtigt(context)
        // A provider may change LOOKUP_KEY after a legitimate name edit. Resolve
        // only through the exact previously bound native contact ID, never via
        // names, canonical UID, another raw contact or a default address book.
        val uri = ContentUris.withAppendedId(ContactsContract.Contacts.CONTENT_URI, original.roh.kontaktId)
        val currentKey = requireNotNull(context.contentResolver.query(uri,
            arrayOf(ContactsContract.Contacts._ID, ContactsContract.Contacts.LOOKUP_KEY,
                ContactsContract.Contacts.IS_USER_PROFILE), null, null, null)).use { cursor ->
            require(cursor.count == 1 && cursor.moveToFirst() && cursor.getLong(0) == original.roh.kontaktId &&
                cursor.getType(2) == android.database.Cursor.FIELD_TYPE_INTEGER && cursor.getInt(2) == 0)
            requireNotNull(cursor.getString(1))
        }
        val after = beobachte(context, currentKey)
        require(after.datenbank == original.datenbank && after.roh.copy(version = original.roh.version) == original.roh &&
            after.roh.version > original.roh.version) { "contact_original_write_identity_changed" }
        return after.kontakt
    }

    companion object {
        fun erfassen(context: Context, lookupKey: String): KontaktOriginalBindung =
            KontaktOriginalBindung(context, beobachte(context, lookupKey))

        private fun berechtigt(context: Context) {
            if (!listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS).all {
                    context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED })
                throw SecurityException("contact_original_permission_required")
        }

        private fun beobachte(context: Context, lookupKey: String): Beobachtung {
            berechtigt(context)
            require(lookupKey.isNotBlank() && lookupKey.length <= 256 && lookupKey.none(Char::isISOControl))
            fun datenbank(): Long = requireNotNull(context.contentResolver.query(ProviderStatus.CONTENT_URI,
                arrayOf(ProviderStatus.STATUS, ProviderStatus.DATABASE_CREATION_TIMESTAMP), null, null, null)).use { cursor ->
                require(cursor.count == 1 && cursor.moveToFirst() &&
                    cursor.getType(0) == android.database.Cursor.FIELD_TYPE_INTEGER && cursor.getInt(0) == ProviderStatus.STATUS_NORMAL &&
                    cursor.getType(1) == android.database.Cursor.FIELD_TYPE_INTEGER && cursor.getLong(1) > 0) {
                    "contact_original_provider_generation_unavailable"
                }
                cursor.getLong(1)
            }
            val generation = datenbank()
            val adapter = AndroidKontakte(context)
            fun kontakt(): AndroidKontakt {
                val snapshot = adapter.snapshot(setOf(lookupKey))
                require(snapshot.vollstaendig && snapshot.kontakte.size == 1) { "contact_original_unavailable" }
                return snapshot.kontakte.single().also {
                    require(it.lookupKey == lookupKey && it.rawContactId > 0 &&
                        !ContactsContract.isProfileId(it.contactId) &&
                        it.rawContactIds == setOf(it.rawContactId) &&
                        it.rawVersionen.keys == it.rawContactIds) { "contact_original_ambiguous" }
                }
            }
            val before = kontakt()
            val rawUri = ContentUris.withAppendedId(RawContacts.CONTENT_URI, before.rawContactId)
            fun roh(): Rohstand = requireNotNull(context.contentResolver.query(rawUri, arrayOf(
                RawContacts._ID, RawContacts.CONTACT_ID, RawContacts.VERSION, RawContacts.ACCOUNT_NAME,
                RawContacts.ACCOUNT_TYPE, RawContacts.DATA_SET, RawContacts.SOURCE_ID,
                RawContacts.DELETED, RawContacts.RAW_CONTACT_IS_READ_ONLY), null, null, null)).use { cursor ->
                require(cursor.count == 1 && cursor.moveToFirst()) { "contact_original_unavailable" }
                require(cursor.getType(7) == android.database.Cursor.FIELD_TYPE_INTEGER && cursor.getInt(7) == 0 &&
                    cursor.getType(8) == android.database.Cursor.FIELD_TYPE_INTEGER && cursor.getInt(8) == 0) {
                    "contact_original_not_writable"
                }
                val version = cursor.getString(2)?.toLongOrNull()
                require(version != null && version >= 0)
                Rohstand(cursor.getLong(0), cursor.getLong(1), version,
                    Quelle(cursor.getString(3), cursor.getString(4), cursor.getString(5)), cursor.getString(6))
            }
            val raw = roh()
            require(raw.id == before.rawContactId && raw.kontaktId == before.contactId &&
                raw.version == before.rawVersionen.getValue(raw.id)) { "contact_original_binding_changed" }
            // Snapshot aggregation intentionally omits empty modeled contacts.
            // An empty linked raw contact still makes original ownership ambiguous.
            requireNotNull(context.contentResolver.query(RawContacts.CONTENT_URI, arrayOf(RawContacts._ID),
                "${RawContacts.CONTACT_ID}=? AND ${RawContacts.DELETED}=0", arrayOf(raw.kontaktId.toString()), null)).use { cursor ->
                require(cursor.count == 1 && cursor.moveToFirst() && cursor.getLong(0) == raw.id) {
                    "contact_original_ambiguous"
                }
            }
            val rows = requireNotNull(context.contentResolver.query(Data.CONTENT_URI,
                arrayOf(Data._ID, Data.RAW_CONTACT_ID, Data.IS_READ_ONLY), "${Data.RAW_CONTACT_ID}=?",
                arrayOf(raw.id.toString()), null)).use { cursor ->
                val ids = mutableListOf<Long>()
                while (cursor.moveToNext()) {
                    require(ids.size < 500 && cursor.getType(0) == android.database.Cursor.FIELD_TYPE_INTEGER &&
                        cursor.getLong(0) > 0 && cursor.getType(1) == android.database.Cursor.FIELD_TYPE_INTEGER &&
                        cursor.getLong(1) == raw.id && cursor.getType(2) == android.database.Cursor.FIELD_TYPE_INTEGER &&
                        cursor.getInt(2) == 0) { "contact_original_rows_not_writable" }
                    ids += cursor.getLong(0)
                }
                require(ids.distinct().size == ids.size)
                ids.sorted()
            }
            require(kontakt() == before && roh() == raw && datenbank() == generation) { "contact_original_binding_changed" }
            berechtigt(context)
            return Beobachtung(before, raw, rows, generation)
        }
    }
}
