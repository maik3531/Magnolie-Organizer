package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/** Caller must retain the authenticated session/generation and general-write consent guard. */
class ContactValueWriteAndroid(private val context: Context, private val now: () -> Long = SystemClock::elapsedRealtime) {
    private data class Ticket(val owner: Any, val contact: AndroidKontakt, val writer: AndroidKontakte, val fields: Set<String>, val account: JsonObject, val expires: Long)
    private val tickets = mutableMapOf<String, Ticket>()
    private val contacts get() = AndroidKontakte(context)
    fun permission(): Boolean = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS).all {
        context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }
    @Synchronized fun clear(owner: Any? = null) {
        if (owner == null) tickets.clear() else tickets.entries.removeAll { it.value.owner === owner }
    }
    @Synchronized fun execute(request: JsonObject, owner: Any): JsonObject {
        ContactValueWrite.validateRequest(request)
        if (!permission()) { tickets.clear(); error("contact_values_not_granted") }
        tickets.entries.removeAll { it.value.expires <= now() }
        val uid = request.string("uid")
        if (request.string("action") == "prepare") {
            require(tickets.size < 8)
            val snapshot = contacts.snapshot(setOf(uid))
            require(snapshot.vollstaendig && snapshot.kontakte.size == 1)
            var contact = snapshot.kontakte.single()
            val names = ContactValueWrite.fieldNames(request)
            var writer = contacts
            if (contact.rawContactIds.size > 1) {
                require(contact.rawContactIds.size <= 16) { "contact_values_ambiguous_source" }
                val candidates = contact.rawContactIds.map { raw ->
                    val scopedWriter = AndroidKontakte(context, rawScope = setOf(raw))
                    val scoped = scopedWriter.snapshot(setOf(uid))
                    require(scoped.vollstaendig && scoped.kontakte.size == 1)
                    scoped.kontakte.single() to scopedWriter
                }
                fun relevant(row: AndroidKontakt) = names.any { name ->
                    if (name == "telefone") row.daten.telefone.isNotEmpty() else row.daten.emailEintraege.isNotEmpty()
                }
                val owners = candidates.filter { relevant(it.first) }
                require(owners.size == 1) { "contact_values_ambiguous_source" }
                val selected = owners.single()
                for (name in names) require((if (name == "telefone") selected.first.daten.telefone.toSet() else selected.first.daten.emailEintraege.toSet()) ==
                    (if (name == "telefone") contact.daten.telefone.toSet() else contact.daten.emailEintraege.toSet())) { "contact_values_incomplete_scope" }
                contact = selected.first; writer = selected.second
            }
            require(contact.lookupKey == uid && contact.rawContactIds == setOf(contact.rawContactId) &&
                contact.rawVersionen.keys.containsAll(contact.rawContactIds)) { "contact_values_ambiguous_source" }
            val identity = contact.herkuenfte.map { Triple(it.accountName, it.accountType, it.dataSet) }.distinct().single()
            val account = buildJsonObject { put("name", identity.first); put("type", identity.second); put("data_set", identity.third) }
            val token = UUID.randomUUID().toString()
            val report = ContactValueWrite.report(request, token, contact.daten, names, account)
            check(permission())
            tickets[token] = Ticket(owner, contact, writer, names, account, now() + 30_000)
            return report
        }
        val token = request.string("token")
        val ticket = requireNotNull(tickets[token]) { "contact_values_stale" }
        require(ticket.owner === owner && ticket.contact.lookupKey == uid && ticket.expires > now())
        val fields = ContactValueWrite.fields(request)
        require(fields.keys == ticket.fields)
        // A failed or uncertain provider transaction cannot be replayed with this token.
        tickets.remove(token)
        val actual = ticket.writer.wertListenUebernehmen(ticket.contact, fields["telefone"], fields["emailEintraege"])
        require(actual.lookupKey == uid && actual.rawContactIds == ticket.contact.rawContactIds)
        val identity = actual.herkuenfte.map { Triple(it.accountName, it.accountType, it.dataSet) }.distinct().single()
        require(ticket.account == buildJsonObject { put("name", identity.first); put("type", identity.second); put("data_set", identity.third) })
        check(permission())
        return ContactValueWrite.report(request, token, actual.daten, ticket.fields, ticket.account)
    }
}
