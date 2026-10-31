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
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.security.MessageDigest
import java.nio.CharBuffer
import java.nio.charset.CodingErrorAction

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
    data class TitelPlan(val id: Long, val konto: Konto, val sourceId: String?, val vorher: String,
                         val nachher: String, val pruefungen: List<ContentProviderOperation>, val identitaet: String)
    data class TitelStand(val id: Long, val konto: Konto, val title: String, val identitaet: String)
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
        // Some Android providers expose the complete Groups query interface but
        // return no/another MIME hint. Only the actual bounded query and its
        // referenced definitions establish readability, not getType().
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
            runCatching { namen(raw, rows, definitions) }.getOrNull()
        }
    }.getOrNull()

    private fun namen(raw: Long, rows: List<Mitglied>, definitions: Map<Long, Gruppe>): List<String> {
        val current = rows.filter { it.raw == raw }
        require(current.all { it.group in definitions }) { "contact_groups_incomplete" }
        return KontaktSync.normalisiereGruppen(current.mapNotNull { definitions[it.group] }
            .filterNot { it.system }.map { it.title }).also { names ->
            require(names.size <= 100 && names.all { it.isNotBlank() && it.codePointCount(0, it.length) <= 256 && it.none { char -> char.code < 32 || char.code == 127 } })
        }
    }

    /** The debug probe follows the same reader but retains its finite failure cause. */
    fun pruefeLesbarkeit(rawIds: Set<Long>) {
        val rows = memberships(rawIds); val definitions = groups().associateBy { it.id }
        rawIds.forEach { namen(it, rows, definitions) }
    }

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

    private fun titelIdentitaet(group: Gruppe): String {
        val bytes = ByteArrayOutputStream()
        DataOutputStream(bytes).use { out ->
            for (part in listOf(group.id.toString(), group.konto.name, group.konto.type, group.konto.dataSet, group.sourceId)) {
                val value = part?.let {
                    val encoded = Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(it))
                    ByteArray(encoded.remaining()).also { buffer -> encoded.get(buffer) }
                }
                out.writeInt(value?.size ?: -1)
                if (value != null) out.write(value)
            }
        }
        return MessageDigest.getInstance("SHA-256").digest(bytes.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    /** Read a previously prepared group by native identity, never by its old label. */
    fun titelStand(raw: Long, id: Long): TitelStand? {
        val group = groups().singleOrNull { it.id == id } ?: return null
        if (group.system || group.konto != konto(raw) || memberships(setOf(raw)).none { it.group == id }) return null
        return TitelStand(group.id, group.konto, group.title, titelIdentitaet(group))
    }

    /** Explicit title changes keep the provider identity and every membership row. */
    fun titelPlan(raw: Long, vorher: String, nachher: String): TitelPlan {
        require(vorher != nachher)
        for (name in listOf(vorher, nachher)) require(name.isNotBlank() && name == Normalizer.normalize(name.trim(), Normalizer.Form.NFC) &&
            name.codePointCount(0, name.length) <= 256 && name.none(Char::isISOControl) && name.codePoints().noneMatch { it in 0xD800..0xDFFF })
        val owner = konto(raw)
        val offered = angebot(raw)
        val definitions = groups().filter { it.konto == owner }
        val group = definitions.filter { it.title == vorher && !it.system }.single()
        require(definitions.none { it.id != group.id && key(it.title) == key(nachher) }) { "contact_group_title_exists" }
        require(memberships(setOf(raw)).any { it.group == group.id }) { "contact_group_title_unbound" }
        requireNotNull(resolver.query(ContentUris.withAppendedId(Groups.CONTENT_URI, group.id), arrayOf(Groups.GROUP_IS_READ_ONLY), null, null, null)).use { c ->
            require(c.moveToFirst() && !c.isNull(0) && c.getString(0).toIntOrNull() == 0 && !c.moveToNext()) { "contact_group_title_readonly" }
        }
        val writable = ContentProviderOperation.newAssertQuery(ContentUris.withAppendedId(Groups.CONTENT_URI, group.id))
            .withValue(Groups.GROUP_IS_READ_ONLY, 0).withExpectedCount(1).build()
        return TitelPlan(group.id, owner, group.sourceId, vorher, nachher, offered.pruefungen + group.assertion() + writable, titelIdentitaet(group))
    }

    fun titelUebernehmen(plan: TitelPlan, rawChecks: List<ContentProviderOperation> = emptyList()): Long {
        val operations = ArrayList(rawChecks + plan.pruefungen)
        operations += ContentProviderOperation.newUpdate(ContentUris.withAppendedId(Groups.CONTENT_URI, plan.id))
            .withValue(Groups.TITLE, plan.nachher).withExpectedCount(1).build()
        resolver.applyBatch(android.provider.ContactsContract.AUTHORITY, operations)
        val actual = groups().single { it.id == plan.id }
        require(actual.title == plan.nachher && actual.konto == plan.konto && actual.sourceId == plan.sourceId && !actual.system)
        return actual.id
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
