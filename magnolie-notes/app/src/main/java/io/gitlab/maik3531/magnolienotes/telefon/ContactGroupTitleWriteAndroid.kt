package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.content.ContentProviderOperation
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import android.provider.ContactsContract.RawContacts
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakt
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontaktGruppen
import io.gitlab.maik3531.magnolienotes.baum.AndroidKontakte
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.UUID

/** Account-bound explicit title change. The caller holds fresh session/consent guards. */
class ContactGroupTitleWriteAndroid(private val context: Context, private val now: () -> Long = SystemClock::elapsedRealtime) {
    private data class Ticket(val owner: Any, val contact: AndroidKontakt, val writer: AndroidKontakte,
                              val plan: AndroidKontaktGruppen.TitelPlan, val account: JsonObject, val expires: Long)
    private val tickets = mutableMapOf<String, Ticket>()
    private val groups get() = AndroidKontaktGruppen(context.contentResolver)
    fun permission() = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.WRITE_CONTACTS).all {
        context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }
    @Synchronized fun clear(owner: Any? = null) {
        if (owner == null) tickets.clear() else tickets.entries.removeAll { it.value.owner === owner }
    }
    @Synchronized fun execute(request: JsonObject, owner: Any): JsonObject {
        ContactGroupTitleWrite.validateRequest(request)
        if (!permission()) { clear(); error("contact_group_title_not_granted") }
        tickets.entries.removeAll { it.value.expires <= now() }
        val uid = request.string("uid")
        if (request.string("action") in setOf("prepare", "inspect")) {
            val inspect = request.string("action") == "inspect"
            if (!inspect) require(tickets.size < 8)
            val full = AndroidKontakte(context).snapshot(setOf(uid))
            require(full.vollstaendig && full.kontakte.size == 1)
            val contact = full.kontakte.single(); require(contact.rawContactIds.size <= 16)
            val owners = contact.rawContactIds.mapNotNull { raw ->
                val writer = AndroidKontakte(context, rawScope = setOf(raw)); val snapshot = writer.snapshot(setOf(uid))
                require(snapshot.vollstaendig && snapshot.kontakte.size <= 1)
                snapshot.kontakte.singleOrNull()?.takeIf {
                    if (inspect) groups.titelStand(raw, request.string("group_id").toLong()) != null
                    else request.string("old_title") in requireNotNull(it.daten.gruppen)
                }?.let { it to writer }
            }
            require(owners.size == 1) { "contact_group_title_ambiguous_source" }
            val selected = owners.single(); require(selected.first.lookupKey == uid && selected.first.rawContactIds.size == 1 &&
                selected.first.rawVersionen.keys.containsAll(selected.first.rawContactIds))
            if (inspect) {
                val actual = requireNotNull(groups.titelStand(selected.first.rawContactId, request.string("group_id").toLong()))
                val account = buildJsonObject { put("name", actual.konto.name.orEmpty()); put("type", actual.konto.type.orEmpty()); put("data_set", actual.konto.dataSet.orEmpty()) }
                require(account == request["account"]) { "contact_group_title_account_changed" }
                require(selected.second.liesRaw(selected.first.rawContactId) == selected.first) { "contact_group_title_source_changed" }
                check(permission())
                return ContactGroupTitleWrite.inspection(request, actual.id, account, actual.identitaet, actual.title)
            }
            val plan = groups.titelPlan(selected.first.rawContactId, request.string("old_title"), request.string("new_title"))
            val account = buildJsonObject { put("name", plan.konto.name.orEmpty()); put("type", plan.konto.type.orEmpty()); put("data_set", plan.konto.dataSet.orEmpty()) }
            val token = UUID.randomUUID().toString(); val report = ContactGroupTitleWrite.report(request, token, plan.id, account, plan.identitaet)
            check(permission()); tickets[token] = Ticket(owner, selected.first, selected.second, plan, account, now() + 30_000)
            return report
        }
        val token = request.string("token"); val ticket = requireNotNull(tickets[token]) { "contact_group_title_stale" }
        require(ticket.owner === owner && ticket.contact.lookupKey == uid && ticket.expires > now() &&
            ticket.plan.vorher == request.string("old_title") && ticket.plan.nachher == request.string("new_title"))
        tickets.remove(token)
        require(ticket.writer.liesRaw(ticket.contact.rawContactId) == ticket.contact)
        val checks = ticket.contact.rawVersionen.map { (raw, version) -> ContentProviderOperation.newAssertQuery(ContentUris.withAppendedId(RawContacts.CONTENT_URI, raw))
            .withValue(RawContacts.VERSION, version).withExpectedCount(1).build() }
        val id = groups.titelUebernehmen(ticket.plan, checks)
        val actual = requireNotNull(ticket.writer.liesRaw(ticket.contact.rawContactId))
        require(actual.lookupKey == uid && actual.rawContactIds == ticket.contact.rawContactIds &&
            ticket.plan.nachher in requireNotNull(actual.daten.gruppen) && ticket.plan.vorher !in actual.daten.gruppen)
        check(permission())
        return ContactGroupTitleWrite.report(request, token, id, ticket.account, ticket.plan.identitaet)
    }
}
