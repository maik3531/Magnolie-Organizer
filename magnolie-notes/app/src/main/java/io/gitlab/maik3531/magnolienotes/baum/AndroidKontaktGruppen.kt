package io.gitlab.maik3531.magnolienotes.baum

import android.content.ContentProviderOperation
import android.content.ContentResolver
import android.content.ContentUris
import android.provider.ContactsContract.Data
import android.provider.ContactsContract.Groups
import android.provider.ContactsContract.RawContacts
import android.provider.ContactsContract.CommonDataKinds.GroupMembership
import java.text.Normalizer
import java.util.Locale

/** Account-bound native memberships, shared by reviewed contact writes and snapshots. */
internal class AndroidKontaktGruppen(private val resolver: ContentResolver) {
    data class Konto(val name: String?, val type: String?, val dataSet: String?)
    private data class Gruppe(val id: Long, val title: String, val konto: Konto, val autoAdd: Int, val favorites: Int, val sourceId: String?) {
        val system get() = autoAdd != 0 || favorites != 0
        fun assertion() = ContentProviderOperation.newAssertQuery(ContentUris.withAppendedId(Groups.CONTENT_URI, id))
            .withValue(Groups.TITLE, title).withValue(Groups.ACCOUNT_NAME, konto.name)
            .withValue(Groups.ACCOUNT_TYPE, konto.type).withValue(Groups.DATA_SET, konto.dataSet)
            .withValue(Groups.DELETED, 0).withValue(Groups.AUTO_ADD, autoAdd).withValue(Groups.FAVORITES, favorites)
            .withValue(Groups.SOURCE_ID, sourceId).withExpectedCount(1).build()
    }
    data class Angebot(val benutzer: List<String>, val system: List<String>, val pruefungen: List<ContentProviderOperation>)
    private data class Mitglied(val id: Long, val raw: Long, val group: Long)
    private fun key(value: String) = Normalizer.normalize(value.trim(), Normalizer.Form.NFC).lowercase(Locale.ROOT)

    private fun memberships(rawIds: Set<Long>): List<Mitglied> {
        if (rawIds.isEmpty()) return emptyList()
        return rawIds.sorted().chunked(256).flatMap { chunk ->
            requireNotNull(resolver.query(Data.CONTENT_URI,
                arrayOf(Data._ID, Data.RAW_CONTACT_ID, GroupMembership.GROUP_ROW_ID),
                "${Data.RAW_CONTACT_ID} IN (${chunk.joinToString { "?" }}) AND ${Data.MIMETYPE}=?",
                (chunk.map(Long::toString) + GroupMembership.CONTENT_ITEM_TYPE).toTypedArray(), null)).use { cursor ->
                buildList { while (cursor.moveToNext()) add(Mitglied(cursor.getLong(0), cursor.getLong(1), cursor.getLong(2))) }
            }
        }
    }

    private fun groups(): List<Gruppe> {
        require(resolver.getType(Groups.CONTENT_URI) == Groups.CONTENT_TYPE) { "contact_groups_unavailable" }
        return requireNotNull(resolver.query(Groups.CONTENT_URI,
        arrayOf(Groups._ID, Groups.TITLE, Groups.ACCOUNT_NAME, Groups.ACCOUNT_TYPE, Groups.DATA_SET, Groups.AUTO_ADD, Groups.FAVORITES, Groups.SOURCE_ID),
        "${Groups.DELETED}=0", null, "${Groups._ID} ASC")).use { cursor ->
        buildList {
            while (cursor.moveToNext()) {
                require(size < 10000)
                add(Gruppe(cursor.getLong(0), cursor.getString(1).orEmpty(),
                    Konto(cursor.getString(2), cursor.getString(3), cursor.getString(4)), cursor.getInt(5), cursor.getInt(6), cursor.getString(7)))
            }
        }
        }
    }

    /** Unknown provider support is null, never an empty set that would mean deletion. */
    fun lesen(rawIds: Set<Long>): Map<Long, List<String>?>? = runCatching {
        val rows = memberships(rawIds)
        val definitions = groups().associateBy { it.id }
        rawIds.associateWith { raw ->
            runCatching {
            val current = rows.filter { it.raw == raw }
            require(current.all { it.group in definitions }) { "contact_groups_incomplete" }
            KontaktSync.normalisiereGruppen(current.mapNotNull { definitions[it.group] }
                .filterNot { it.system }.map { it.title }).also { names ->
                require(names.size <= 100 && names.all { it.isNotBlank() && it.codePointCount(0, it.length) <= 256 && it.none { char -> char.code < 32 || char.code == 127 } })
            }
            }.getOrNull()
        }
    }.getOrNull()

    private fun konto(raw: Long): Konto = requireNotNull(resolver.query(
        ContentUris.withAppendedId(RawContacts.CONTENT_URI, raw),
        arrayOf(RawContacts.ACCOUNT_NAME, RawContacts.ACCOUNT_TYPE, RawContacts.DATA_SET), null, null, null)).use { cursor ->
        require(cursor.moveToFirst())
        Konto(cursor.getString(0), cursor.getString(1), cursor.getString(2)).also { require(!cursor.moveToNext()) }
    }

    /** Complete user/system title sets for the existing primary raw-contact account. */
    fun angebot(raw: Long): Angebot {
        val owner = konto(raw)
        val definitions = groups().filter { it.konto == owner }
        val selection = mutableListOf("${Groups.DELETED}=0")
        val args = mutableListOf<String>()
        for ((column, value) in listOf(Groups.ACCOUNT_NAME to owner.name, Groups.ACCOUNT_TYPE to owner.type, Groups.DATA_SET to owner.dataSet)) {
            selection += if (value == null) "$column IS NULL" else "$column=?"
            if (value != null) args += value
        }
        val count = ContentProviderOperation.newAssertQuery(Groups.CONTENT_URI)
            .withSelection(selection.joinToString(" AND "), args.toTypedArray()).withExpectedCount(definitions.size).build()
        return Angebot(KontaktSync.normalisiereGruppen(definitions.filterNot { it.system }.map { it.title }),
            KontaktSync.normalisiereGruppen(definitions.filter { it.system }.map { it.title }),
            listOf(count) + definitions.map { it.assertion() })
    }

    /** Writes join the caller's existing version-asserted applyBatch transaction. */
    fun plane(ops: MutableList<ContentProviderOperation>, rawIds: Set<Long>, primary: Long?,
              desired: List<String>?, expected: List<String>?, newAccount: Konto? = null) {
        if (desired == null) return
        val wanted = KontaktSync.normalisiereGruppen(desired)
        require(wanted.size <= 100)
        val definitions = groups()
        val byId = definitions.associateBy { it.id }
        val current = memberships(rawIds)
        require(current.all { it.group in byId }) { "contact_groups_incomplete" }
        if (primary != null) require(expected != null && KontaktSync.normalisiereGruppen(current.mapNotNull { byId[it.group] }
            .filterNot { it.system }.map { it.title }) == KontaktSync.normalisiereGruppen(expected))
        val owner = primary?.let(::konto) ?: requireNotNull(newAccount)
        val wantedKeys = wanted.associateBy(::key)
        val asserted = mutableSetOf<Long>()
        fun assertGroup(group: Gruppe) {
            if (!asserted.add(group.id)) return
            ops += group.assertion()
        }
        // Deleting memberships never deletes a contact or a shared group definition.
        for (row in current) {
            val group = byId[row.group] ?: continue
            if (!group.system) assertGroup(group)
            if (!group.system && key(group.title) !in wantedKeys) {
                ops += ContentProviderOperation.newDelete(ContentUris.withAppendedId(Data.CONTENT_URI, row.id))
                    .withSelection("${Data.RAW_CONTACT_ID}=? AND ${Data.MIMETYPE}=? AND ${GroupMembership.GROUP_ROW_ID}=?",
                        arrayOf(row.raw.toString(), GroupMembership.CONTENT_ITEM_TYPE, row.group.toString())).withExpectedCount(1).build()
            }
        }
        for (name in wanted) {
            val existingMembership = current.any { row -> byId[row.group]?.let { !it.system && key(it.title) == key(name) } == true }
            if (existingMembership) continue
            val candidates = definitions.filter { !it.system && it.konto == owner && key(it.title) == key(name) }
            require(candidates.size <= 1) { "contact_groups_ambiguous" }
            val group = candidates.singleOrNull()
            val groupBackref = if (group == null) {
                val selection = mutableListOf("${Groups.DELETED}=0", "${Groups.TITLE}=? COLLATE NOCASE")
                val arguments = mutableListOf(name)
                for ((column, value) in listOf(Groups.ACCOUNT_NAME to owner.name, Groups.ACCOUNT_TYPE to owner.type, Groups.DATA_SET to owner.dataSet)) {
                    selection += if (value == null) "$column IS NULL" else "$column=?"
                    if (value != null) arguments += value
                }
                ops += ContentProviderOperation.newAssertQuery(Groups.CONTENT_URI)
                    .withSelection(selection.joinToString(" AND "), arguments.toTypedArray()).withExpectedCount(0).build()
                val index = ops.size
                ops += ContentProviderOperation.newInsert(Groups.CONTENT_URI)
                    .withValue(Groups.TITLE, name).withValue(Groups.ACCOUNT_NAME, owner.name)
                    .withValue(Groups.ACCOUNT_TYPE, owner.type).withValue(Groups.DATA_SET, owner.dataSet).build()
                index
            } else {
                assertGroup(group)
                null
            }
            var membership = ContentProviderOperation.newInsert(Data.CONTENT_URI).withValue(Data.MIMETYPE, GroupMembership.CONTENT_ITEM_TYPE)
            membership = if (primary == null) membership.withValueBackReference(Data.RAW_CONTACT_ID, 0) else membership.withValue(Data.RAW_CONTACT_ID, primary)
            membership = if (groupBackref == null) membership.withValue(GroupMembership.GROUP_ROW_ID, group!!.id)
                else membership.withValueBackReference(GroupMembership.GROUP_ROW_ID, groupBackref)
            ops += membership.build()
        }
    }
}
